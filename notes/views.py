from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, F
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from accounts.decorators import verified_required
from accounts.models import User
from campus.models import Department
from credits.models import CreditLedger
from credits.services import add_entry, get_balance

from .forms import NoteForm
from .models import Note, NoteDownload, NoteRating
from .services import (
    approve_note,
    can_review,
    can_upload,
    can_view_note,
    make_preview,
    reject_note,
    reviewable_notes,
    reviewer_batch_ids,
    search_notes,
    visible_notes,
    publish_overdue_notes,
)

DOWNLOAD_COST = 5
RATER_REWARD = 1
OWNER_REWARD = 5
RATER_DAILY_CAP = 5
OWNER_DAILY_CAP = 10


@login_required
def note_list(request):
    publish_overdue_notes()
    tab = "mine" if request.GET.get("tab") == "mine" else "all"

    if tab == "mine":
        notes = Note.objects.filter(owner=request.user).select_related("owner", "department", "batch")
    else:
        notes = visible_notes(request.user)

    q = request.GET.get("q", "").strip()
    department = request.GET.get("department", "")
    semester = request.GET.get("semester", "")

    notes = search_notes(notes, q)
    if department.isdigit():
        notes = notes.filter(department_id=int(department))
    if semester.isdigit():
        notes = notes.filter(semester=int(semester))

    page = Paginator(notes, 12).get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    allowed, hint = can_upload(request.user)

    context = {
        "page": page,
        "tab": tab,
        "q": q,
        "department": department,
        "semester": semester,
        "departments": Department.objects.all(),
        "semesters": range(1, 13),
        "querystring": params.urlencode(),
        "can_upload": allowed,
        "upload_hint": hint,
    }
    return render(request, "notes/list.html", context)


@login_required
def note_preview(request, pk):
    note = get_object_or_404(Note, pk=pk)
    if not can_view_note(request.user, note):
        raise Http404

    if not note.preview:
        make_preview(note)
    if not note.preview:
        raise Http404

    response = FileResponse(note.preview.open("rb"), content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=86400"
    return response


@login_required
@verified_required
def upload(request):
    user = request.user
    allowed, hint = can_upload(user)
    if not allowed:
        messages.info(request, hint)
        return redirect("notes:list")

    batch = None
    if user.role == User.Role.STUDENT:
        batch = user.membership.batch

    if request.method == "POST":
        form = NoteForm(request.POST, request.FILES, user=user)
        if form.is_valid():
            note = form.save(commit=False)
            note.owner = user
            note.batch = batch
            note.save()
            make_preview(note)

            if user.role == User.Role.LECTURER:
                approve_note(note)
                messages.success(request, "Note published! You earned 10 nuts.")
            else:
                messages.success(request, "Note submitted. Your CR will review it soon.")
            return redirect("notes:list")
    else:
        form = NoteForm(user=user)

    return render(request, "notes/upload.html", {"form": form})


@login_required
def review_list(request):
    if not (request.user.is_superuser or reviewer_batch_ids(request.user)):
        raise PermissionDenied
    publish_overdue_notes()
    notes = reviewable_notes(request.user).order_by("created_at")
    return render(request, "notes/review_list.html", {"notes": notes})


@login_required
def review_detail(request, pk):
    note = get_object_or_404(Note, pk=pk)
    if not can_review(request.user, note):
        raise Http404
    return render(request, "notes/review_detail.html", {"note": note})

@login_required
@require_POST
def review_action(request, pk):
    note = get_object_or_404(Note, pk=pk)
    is_reviewer = request.user.is_superuser or (
        note.batch_id and note.batch_id in reviewer_batch_ids(request.user) and note.owner_id != request.user.id
    )
    if not is_reviewer:
        raise Http404

    action = request.POST.get("action")
    if action == "reject":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "Please write a reason for rejecting the note.")
            return redirect("notes:review_detail", pk=pk)

    with transaction.atomic():
        locked_note = Note.objects.select_for_update().get(pk=note.pk)
        if locked_note.status not in (Note.Status.PENDING, Note.Status.UNVERIFIED):
            messages.info(request, "This note was already decided by another reviewer.")
            return redirect("notes:review_list")

        owner_name = locked_note.owner.get_full_name() or locked_note.owner.username
        if action == "approve":
            paid = approve_note(locked_note, reviewer=request.user)
            if paid:
                messages.success(request, f"Approved. {owner_name} earned 10 nuts.")
            else:
                messages.success(request, "Approved.")
        elif action == "reject":
            reject_note(locked_note, request.user, reason)
            messages.info(request, f"Rejected. {owner_name} can see your reason.")

    return redirect("notes:review_list")

@login_required
@xframe_options_sameorigin
def note_file(request, pk):
    note = get_object_or_404(Note, pk=pk)
    user = request.user
    is_privileged = note.owner_id == user.id or user.is_superuser or can_review(user, note)
    if note.status == Note.Status.REMOVED and not is_privileged:
        raise Http404
    
    # Check if user has already downloaded/unlocked the note
    has_downloaded = NoteDownload.objects.filter(user=user, note=note).exists()
    
    # Allow access if owner, superuser, reviewer, OR has downloaded
    if not (is_privileged or has_downloaded):
        raise Http404
        
    return FileResponse(note.file.open("rb"), content_type="application/pdf")


def earned_today(user, reason):
    return CreditLedger.objects.filter(
        user=user, reason=reason, created_at__date=timezone.localdate()
    ).count()


@login_required
def note_detail(request, pk):
    note = get_object_or_404(
        Note.objects.select_related("owner", "department", "batch"), pk=pk
    )
    user = request.user
    if not can_view_note(user, note):
        raise Http404

    is_owner = note.owner_id == user.id
    has_downloaded = (not is_owner) and NoteDownload.objects.filter(user=user, note=note).exists()
    my_rating = NoteRating.objects.filter(user=user, note=note).first()
    stats = NoteRating.objects.filter(note=note).aggregate(avg=Avg("rating"), count=Count("id"))
    reviews = NoteRating.objects.filter(note=note).select_related("user").order_by("-id")[:10]

    return render(request, "notes/note_detail.html", {
        "note": note,
        "is_owner": is_owner,
        "has_downloaded": has_downloaded,
        "my_rating": my_rating,
        "can_rate": has_downloaded and my_rating is None,
        "avg_rating": stats["avg"],
        "rating_count": stats["count"],
        "reviews": reviews,
        "download_cost": DOWNLOAD_COST,
        "can_afford": get_balance(user) >= DOWNLOAD_COST,
    })


@login_required
@require_POST
@verified_required
def note_download(request, pk):
    note = get_object_or_404(Note, pk=pk)
    user = request.user

    if note.owner_id == user.id or user.is_superuser:
        return redirect("notes:file", pk=note.pk)

    if not visible_notes(user).filter(pk=note.pk).exists():
        raise Http404

    try:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            _, created = NoteDownload.objects.get_or_create(user=user, note=note)
            if created:
                add_entry(
                    user,
                    -DOWNLOAD_COST,
                    CreditLedger.Reason.NOTE_DOWNLOAD,
                    f"Unlocked note: {note.title}",
                )
                Note.objects.filter(pk=note.pk).update(download_count=F("download_count") + 1)
    except ValueError:
        messages.error(request, f"You need {DOWNLOAD_COST} nuts to unlock this note.")
        return redirect("notes:detail", pk=note.pk)

    if created:
        messages.success(request, f"Note unlocked! {DOWNLOAD_COST} nuts were used.")
    return redirect("notes:file", pk=note.pk)


@login_required
@require_POST
@verified_required
def note_rate(request, pk):
    note = get_object_or_404(Note, pk=pk)
    user = request.user
    back = redirect("notes:detail", pk=note.pk)

    if note.owner_id == user.id:
        messages.error(request, "You cannot rate your own note.")
        return back

    try:
        value = int(request.POST.get("rating", 0))
    except ValueError:
        value = 0
    if not 1 <= value <= 5:
        messages.error(request, "Please choose a rating from 1 to 5.")
        return back
    review_text = request.POST.get("review", "").strip()[:500]

    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)

        if not NoteDownload.objects.filter(user=user, note=note).exists():
            messages.error(request, "You must unlock the note before rating it.")
            return back
        if NoteRating.objects.filter(user=user, note=note).exists():
            messages.error(request, "You have already rated this note.")
            return back

        NoteRating.objects.create(user=user, note=note, rating=value, review=review_text)

        rater_paid = earned_today(user, CreditLedger.Reason.RATING_GIVEN) < RATER_DAILY_CAP
        owner_paid = earned_today(note.owner, CreditLedger.Reason.RATING_RECEIVED) < OWNER_DAILY_CAP
        if rater_paid:
            add_entry(user, RATER_REWARD, CreditLedger.Reason.RATING_GIVEN, f"Rated note: {note.title}")
        if owner_paid:
            add_entry(note.owner, OWNER_REWARD, CreditLedger.Reason.RATING_RECEIVED, f"Rating on note: {note.title}")

    if rater_paid:
        messages.success(request, f"Thanks for rating! You earned {RATER_REWARD} nut.")
    else:
        messages.success(request, "Thanks for rating! You reached today's nut limit for ratings.")
    return back