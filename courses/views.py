import os
import re
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import models
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseNotFound,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from payments.models import PaymentOrder
from payments.services import create_order, get_gateway, get_wallet_balance
from .forms import CourseForm, LessonForm
from .models import Course, Lesson, CoursePurchase
from .services import (
    can_sell,
    check_and_update_course_on_lesson_change,
    get_allowed_price_range,
    validate_course_price,
)


def _check_courses_enabled():
    if not getattr(settings, "ENABLE_VIDEO_COURSES", True):
        raise Http404(_("Video courses are currently disabled."))


def course_list(request):
    """
    PRD 7.5: Catalog list with search, category filter, price sort and pagination.
    """
    _check_courses_enabled()

    qs = Course.objects.filter(status=Course.Status.PUBLISHED).select_related("instructor").prefetch_related("lessons")

    # Search filter
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            models.Q(title__icontains=q)
            | models.Q(description__icontains=q)
            | models.Q(instructor__username__icontains=q)
        )

    # Category filter
    category = request.GET.get("category", "").strip()
    if category in dict(Course.Category.choices):
        qs = qs.filter(category=category)

    # Free / Premium filter
    pricing = request.GET.get("pricing", "").strip()
    if pricing == "free":
        qs = qs.filter(price=0)
    elif pricing == "premium":
        qs = qs.filter(price__gt=0)

    # Sorting
    sort = request.GET.get("sort", "newest").strip()
    if sort == "price_asc":
        qs = qs.order_by("price", "-created_at")
    elif sort == "price_desc":
        qs = qs.order_by("-price", "-created_at")
    elif sort == "duration":
        qs = qs.order_by("-total_duration_seconds", "-created_at")
    else:
        qs = qs.order_by("-created_at")

    paginator = Paginator(qs, 12)
    page = paginator.get_page(request.GET.get("page"))

    categories = Course.Category.choices
    user_can_sell = can_sell(request.user) if request.user.is_authenticated else False

    context = {
        "page": page,
        "courses": page.object_list,
        "search_query": q,
        "selected_category": category,
        "selected_pricing": pricing,
        "selected_sort": sort,
        "categories": categories,
        "can_sell": user_can_sell,
    }
    return render(request, "courses/course_list.html", context)


def course_detail(request, pk):
    """
    PRD 7.5: Detail page with course description, syllabus with lesson durations,
    preview flags, and buy/owned buttons.
    """
    _check_courses_enabled()

    course = get_object_or_404(
        Course.objects.select_related("instructor").prefetch_related("lessons"),
        pk=pk,
    )

    is_seller = request.user.is_authenticated and request.user == course.instructor
    is_admin = request.user.is_authenticated and request.user.is_superuser

    if course.status != Course.Status.PUBLISHED and not (is_seller or is_admin):
        raise Http404(_("Course not found or not published."))

    has_purchased = (
        request.user.is_authenticated
        and CoursePurchase.objects.filter(user=request.user, course=course, is_successful=True).exists()
    )

    can_access = is_seller or has_purchased or is_admin
    lessons = course.lessons.all().order_by("order", "id")

    context = {
        "course": course,
        "lessons": lessons,
        "is_seller": is_seller,
        "has_purchased": has_purchased,
        "can_access": can_access,
    }
    return render(request, "courses/course_detail.html", context)


@login_required
def my_courses(request):
    """
    PRD 7.5: Seller overview with drafts, published courses, and earnings summary.
    """
    _check_courses_enabled()

    if not can_sell(request.user):
        raise PermissionDenied(_("Only approved batch members or lecturers can publish courses."))

    courses_qs = Course.objects.filter(instructor=request.user).prefetch_related("lessons").order_by("-created_at")

    total_sales_count = CoursePurchase.objects.filter(
        course__instructor=request.user, is_successful=True
    ).count()

    total_earnings = (
        CoursePurchase.objects.filter(course__instructor=request.user, is_successful=True).aggregate(
            total=models.Sum("seller_earning")
        )["total"]
        or Decimal("0.00")
    )

    wallet_balance = get_wallet_balance(request.user)

    context = {
        "courses": courses_qs,
        "total_sales_count": total_sales_count,
        "total_earnings": total_earnings,
        "wallet_balance": wallet_balance,
    }
    return render(request, "courses/my_courses.html", context)


@login_required
def course_create(request):
    """
    PRD 7.5: Create a new course (begins in Draft).
    """
    _check_courses_enabled()

    if not can_sell(request.user):
        raise PermissionDenied(_("Only approved batch members or lecturers can publish courses."))

    if request.method == "POST":
        form = CourseForm(request.POST, request.FILES)
        if form.is_valid():
            course = form.save(commit=False)
            course.instructor = request.user
            course.save()
            messages.success(request, _("Course created! Now you can add video lessons."))
            return redirect("courses:course_edit", pk=course.pk)
    else:
        form = CourseForm(
            initial={
                "category": Course.Category.ACADEMIC,
                "price": Decimal("50.00"),
                "status": Course.Status.DRAFT,
            }
        )

    return render(request, "courses/course_form.html", {"form": form, "is_new": True})


@login_required
def course_edit(request, pk):
    """
    PRD 7.5: Edit course metadata, manage lessons, and toggle publish.
    """
    _check_courses_enabled()

    course = get_object_or_404(Course, pk=pk)
    if course.instructor != request.user and not request.user.is_superuser:
        raise PermissionDenied(_("You cannot edit this course."))

    if request.method == "POST":
        form = CourseForm(request.POST, request.FILES, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, _("Course details saved successfully."))
            return redirect("courses:course_edit", pk=course.pk)
    else:
        form = CourseForm(instance=course)

    lessons = course.lessons.all().order_by("order", "id")
    min_price, max_price = get_allowed_price_range(course.category, course.total_duration_seconds)

    context = {
        "course": course,
        "form": form,
        "lessons": lessons,
        "min_price": min_price,
        "max_price": max_price,
        "is_new": False,
    }
    return render(request, "courses/course_edit.html", context)


@login_required
@require_POST
def course_publish_toggle(request, pk):
    """
    PRD 7.2 & 7.5: Toggle publish status with strict pricing rule validation.
    """
    _check_courses_enabled()

    course = get_object_or_404(Course, pk=pk)
    if course.instructor != request.user and not request.user.is_superuser:
        raise PermissionDenied(_("You cannot publish this course."))

    if course.status == Course.Status.DRAFT:
        if course.lessons.count() == 0:
            messages.error(request, _("A course must have at least one lesson before publishing."))
            return redirect("courses:course_edit", pk=course.pk)

        try:
            validate_course_price(course)
            course.status = Course.Status.PUBLISHED
            course.save(update_fields=["status", "updated_at"])
            messages.success(request, _("Congratulations! Your course is now published and available in the catalog."))
        except ValidationError as e:
            messages.error(request, e.message if hasattr(e, "message") else str(e))
    else:
        course.status = Course.Status.DRAFT
        course.save(update_fields=["status", "updated_at"])
        messages.info(request, _("Course moved back to draft."))

    return redirect("courses:course_edit", pk=course.pk)


@login_required
def lesson_create(request, course_pk):
    """
    PRD 7.3 & 7.5: Upload an MP4 lesson or add external video URL.
    """
    _check_courses_enabled()

    course = get_object_or_404(Course, pk=course_pk)
    if course.instructor != request.user and not request.user.is_superuser:
        raise PermissionDenied(_("You cannot add lessons to this course."))

    lesson = Lesson(course=course)
    if request.method == "POST":
        form = LessonForm(request.POST, request.FILES, instance=lesson)
        if form.is_valid():
            form.save()
            check_and_update_course_on_lesson_change(course)
            messages.success(request, _("Lesson '%(title)s' added.") % {"title": lesson.title})
            return redirect("courses:course_edit", pk=course.pk)
    else:
        next_order = (course.lessons.aggregate(models.Max("order"))["order__max"] or 0) + 1
        form = LessonForm(instance=lesson, initial={"order": next_order})

    return render(request, "courses/lesson_form.html", {"form": form, "course": course, "is_new": True})


@login_required
def lesson_edit(request, pk):
    """
    PRD 7.5: Edit an existing lesson.
    """
    _check_courses_enabled()

    lesson = get_object_or_404(Lesson.objects.select_related("course"), pk=pk)
    course = lesson.course
    if course.instructor != request.user and not request.user.is_superuser:
        raise PermissionDenied(_("You cannot edit this lesson."))

    if request.method == "POST":
        form = LessonForm(request.POST, request.FILES, instance=lesson)
        if form.is_valid():
            form.save()
            check_and_update_course_on_lesson_change(course)
            messages.success(request, _("Lesson '%(title)s' updated.") % {"title": lesson.title})
            return redirect("courses:course_edit", pk=course.pk)
    else:
        initial = {}
        if lesson.duration_seconds:
            initial["duration_input"] = round(lesson.duration_seconds / 60)
        form = LessonForm(instance=lesson, initial=initial)

    return render(
        request,
        "courses/lesson_form.html",
        {"form": form, "course": course, "lesson": lesson, "is_new": False},
    )


@login_required
@require_POST
def lesson_delete(request, pk):
    """
    PRD 7.5: Delete a lesson and recalculate course duration.
    """
    _check_courses_enabled()

    lesson = get_object_or_404(Lesson.objects.select_related("course"), pk=pk)
    course = lesson.course
    if course.instructor != request.user and not request.user.is_superuser:
        raise PermissionDenied(_("You cannot delete this lesson."))

    title = lesson.title
    lesson.delete()
    check_and_update_course_on_lesson_change(course)
    messages.success(request, _("Lesson '%(title)s' deleted.") % {"title": title})
    return redirect("courses:course_edit", pk=course.pk)


@login_required
def course_buy(request, pk):
    """
    PRD 7.6: Purchase flow via PaymentOrder and registered fulfiller.
    Blocks purchasing own course or double-purchasing.
    """
    _check_courses_enabled()

    course = get_object_or_404(Course, pk=pk, status=Course.Status.PUBLISHED)

    if course.instructor == request.user:
        messages.error(request, _("You cannot buy your own course."))
        return redirect("courses:course_detail", pk=course.pk)

    if CoursePurchase.objects.filter(user=request.user, course=course, is_successful=True).exists():
        messages.info(request, _("You already own this course."))
        return redirect("courses:course_learn", pk=course.pk)

    if course.price <= Decimal("0.00"):
        CoursePurchase.objects.get_or_create(
            user=request.user,
            course=course,
            is_successful=True,
            defaults={
                "amount_paid": Decimal("0.00"),
                "commission_amount": Decimal("0.00"),
                "seller_earning": Decimal("0.00"),
            },
        )
        messages.success(request, _("Enrolled in free course '%(title)s'!") % {"title": course.title})
        return redirect("courses:course_learn", pk=course.pk)

    order = create_order(
        user=request.user,
        purpose=PaymentOrder.Purpose.COURSE,
        amount_bdt=course.price,
        reference_type="course",
        reference_id=str(course.id),
    )

    gateway = get_gateway()
    return_url = request.build_absolute_uri(reverse("payments:order_detail", args=[order.id]))
    redirect_url = gateway.create_payment(order, return_url)
    return redirect(redirect_url)


@login_required
def course_learn(request, pk):
    """
    PRD 7.9: Learn page with HTML5 video player and lesson playlist selector.
    """
    _check_courses_enabled()

    course = get_object_or_404(
        Course.objects.select_related("instructor").prefetch_related("lessons"),
        pk=pk,
    )

    is_seller = request.user == course.instructor
    is_admin = request.user.is_superuser
    has_purchased = CoursePurchase.objects.filter(
        user=request.user, course=course, is_successful=True
    ).exists()

    if not (is_seller or is_admin or has_purchased):
        raise PermissionDenied(_("You must purchase this course before accessing the lessons."))

    lessons = list(course.lessons.all().order_by("order", "id"))
    active_lesson = None
    lesson_id = request.GET.get("lesson")
    if lesson_id:
        active_lesson = next((l for l in lessons if str(l.id) == lesson_id), None)
    if not active_lesson and lessons:
        active_lesson = lessons[0]

    context = {
        "course": course,
        "lessons": lessons,
        "active_lesson": active_lesson,
    }
    return render(request, "courses/learn.html", context)


# -------------------------------------------------------------------------
# Secure HTTP Range Streaming (PRD 7.9)
# -------------------------------------------------------------------------

def _parse_range_header(header: str, file_size: int):
    """
    Parses HTTP_RANGE header (e.g. 'bytes=0-99', 'bytes=100-').
    Returns tuple (start, end) or 'invalid' on out-of-bounds, or None if no valid range prefix.
    """
    if not header or not header.startswith("bytes="):
        return None

    val = header[6:].strip()
    match = re.match(r"^(\d*)-(\d*)$", val)
    if not match:
        return "invalid"

    s_str, e_str = match.groups()
    if not s_str and not e_str:
        return "invalid"

    if not s_str:  # Suffix byte range: -N (last N bytes)
        length = int(e_str)
        if length <= 0:
            return "invalid"
        start = max(0, file_size - length)
        end = file_size - 1
    elif not e_str:  # Prefix byte range: N- (from N to EOF)
        start = int(s_str)
        end = file_size - 1
    else:
        start = int(s_str)
        end = int(e_str)

    if start > end or start >= file_size:
        return "invalid"

    end = min(end, file_size - 1)
    return (start, end)


def _file_chunk_generator(file_obj, start: int, end: int, chunk_size: int = 65536):
    """
    Yields chunks of a file between start and end byte offsets (inclusive).
    Closes the file handle when finished.
    """
    try:
        file_obj.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            bytes_to_read = min(remaining, chunk_size)
            data = file_obj.read(bytes_to_read)
            if not data:
                break
            remaining -= len(data)
            yield data
    finally:
        try:
            file_obj.close()
        except Exception:
            pass


def lesson_stream(request, pk):
    """
    PRD 7.9: Secure lesson video streaming.
    - Accessible by buyer, seller, superusers, or anyone when is_free_preview.
    - Non-buyers get 403 Forbidden.
    - Full support for HTTP 206 Partial Content (Content-Range, Accept-Ranges: bytes, Cache-Control: private).
    - Invalid range yields HTTP 416 Range Not Satisfiable.
    - Optional X-Accel-Redirect mode for nginx via USE_X_ACCEL_REDIRECT setting.
    """
    _check_courses_enabled()

    lesson = get_object_or_404(Lesson.objects.select_related("course", "course__instructor"), pk=pk)
    course = lesson.course

    # Permission check
    can_stream = False
    if lesson.is_free_preview:
        can_stream = True
    elif request.user.is_authenticated:
        if request.user.is_superuser or request.user == course.instructor:
            can_stream = True
        elif CoursePurchase.objects.filter(user=request.user, course=course, is_successful=True).exists():
            can_stream = True

    if not can_stream:
        return HttpResponseForbidden(_("You do not have permission to stream this lesson."))

    # If lesson points to an external video URL (e.g. YouTube unlisted)
    if not lesson.video_file:
        if lesson.video_url:
            return redirect(lesson.video_url)
        return HttpResponseNotFound(_("No video media found for this lesson."))

    # Optional X-Accel-Redirect mode
    if getattr(settings, "USE_X_ACCEL_REDIRECT", False):
        response = HttpResponse()
        response["X-Accel-Redirect"] = lesson.video_file.url
        response["Content-Type"] = "video/mp4"
        response["Cache-Control"] = "private"
        return response

    try:
        file_size = lesson.video_file.size
        file_obj = lesson.video_file.open("rb")
    except Exception:
        return HttpResponseNotFound(_("Video file could not be opened."))

    range_header = request.META.get("HTTP_RANGE", "").strip()
    if range_header:
        parsed_range = _parse_range_header(range_header, file_size)
        if parsed_range == "invalid":
            file_obj.close()
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{file_size}"
            return response
        if parsed_range is not None:
            start, end = parsed_range
            content_length = end - start + 1
            response = StreamingHttpResponse(
                _file_chunk_generator(file_obj, start, end),
                status=206,
                content_type="video/mp4",
            )
            response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            response["Content-Length"] = str(content_length)
            response["Accept-Ranges"] = "bytes"
            response["Cache-Control"] = "private"
            return response

    # No range requested: stream entire file with 200 OK
    response = StreamingHttpResponse(
        _file_chunk_generator(file_obj, 0, file_size - 1),
        status=200,
        content_type="video/mp4",
    )
    response["Content-Length"] = str(file_size)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private"
    return response
