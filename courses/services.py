from decimal import Decimal
import os
import mutagen
from mutagen.mp4 import MP4
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from campus.models import BatchMembership
from notifications.services import notify
from payments.models import PaymentOrder, WalletEntry
from .models import Course, Lesson, PricingRule, CoursePurchase


def can_sell(user) -> bool:
    """
    PRD 7.4: User must have verified email, and be either a lecturer
    or a student with an approved batch membership. Superusers can also sell.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if not user.email_verified:
        return False
    if user.role == User.Role.LECTURER:
        return True
    if user.role == User.Role.STUDENT:
        return BatchMembership.objects.filter(
            user=user,
            status=BatchMembership.Status.APPROVED,
        ).exists()
    return False


def get_video_duration(file_obj) -> int:
    """
    Reads the video duration in seconds using mutagen (pure Python).
    Accepts a filename/path or a file-like object.
    Returns integer duration in seconds (at least 1), or None if it cannot be read.
    """
    if not file_obj:
        return None

    # If it's a file path or string
    if isinstance(file_obj, str):
        if not os.path.exists(file_obj):
            return None
        try:
            audio_video = mutagen.File(file_obj)
            if audio_video and getattr(audio_video, "info", None) and hasattr(audio_video.info, "length"):
                return max(1, round(audio_video.info.length))
            mp4 = MP4(file_obj)
            if mp4 and getattr(mp4, "info", None) and hasattr(mp4.info, "length"):
                return max(1, round(mp4.info.length))
        except Exception:
            return None

    # If it's an UploadedFile with temporary_file_path()
    if hasattr(file_obj, "temporary_file_path"):
        try:
            path = file_obj.temporary_file_path()
            return get_video_duration(path)
        except Exception:
            pass

    # If it's a file-like object or FieldFile
    pos = file_obj.tell() if hasattr(file_obj, "tell") else 0
    try:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        audio_video = mutagen.File(file_obj)
        if audio_video and getattr(audio_video, "info", None) and hasattr(audio_video.info, "length"):
            return max(1, round(audio_video.info.length))

        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        mp4 = MP4(fileobj=file_obj)
        if mp4 and getattr(mp4, "info", None) and hasattr(mp4.info, "length"):
            return max(1, round(mp4.info.length))
    except Exception:
        return None
    finally:
        if hasattr(file_obj, "seek"):
            try:
                file_obj.seek(pos)
            except Exception:
                pass

    return None


def validate_video_file(file_obj):
    """
    PRD 7.3: Validates that uploaded file is MP4 and within size limits.
    """
    if not file_obj:
        return

    name = getattr(file_obj, "name", "")
    ext = os.path.splitext(name)[1].lower()
    if ext != ".mp4":
        raise ValidationError(_("Only MP4 video files (.mp4) are allowed."))

    max_mb = getattr(settings, "COURSE_VIDEO_MAX_MB", 300)
    size = getattr(file_obj, "size", 0)
    if size > max_mb * 1024 * 1024:
        raise ValidationError(_("Video file exceeds maximum size of %(max)d MB.") % {"max": max_mb})

    duration = get_video_duration(file_obj)
    if duration is None or duration <= 0:
        raise ValidationError(_("Could not read video duration. Please upload a valid MP4 file."))

    return duration


def get_default_pricing_rates(category: str):
    """Fallback rates if database PricingRule has not been seeded yet."""
    if category == Course.Category.ACADEMIC:
        return Decimal("50.00"), Decimal("150.00")
    return Decimal("200.00"), Decimal("600.00")


def get_allowed_price_range(category: str, total_duration_seconds: int):
    """
    PRD 7.2:
    billable_hours = max(total_duration_seconds / 3600, COURSE_MIN_BILLABLE_HOURS)
    Allowed price is [min_per_hour * billable_hours, max_per_hour * billable_hours].
    Boundary values (exactly min and exactly max) are accepted.
    """
    rule = PricingRule.objects.filter(category=category).first()
    if rule:
        min_rate = rule.min_per_hour
        max_rate = rule.max_per_hour
    else:
        min_rate, max_rate = get_default_pricing_rates(category)

    min_hours_cfg = Decimal(str(getattr(settings, "COURSE_MIN_BILLABLE_HOURS", 0.5)))
    actual_hours = Decimal(str(total_duration_seconds)) / Decimal("3600")
    billable_hours = max(actual_hours, min_hours_cfg)

    min_price = (min_rate * billable_hours).quantize(Decimal("0.01"))
    max_price = (max_rate * billable_hours).quantize(Decimal("0.01"))
    return min_price, max_price


def validate_course_price(course: Course):
    """
    Validates that course.price is within [min_price, max_price].
    Raises ValidationError if out of range.
    """
    min_price, max_price = get_allowed_price_range(course.category, course.total_duration_seconds)
    if course.price < min_price or course.price > max_price:
        raise ValidationError(
            _(
                "Price %(price)s BDT is outside the allowed range of %(min)s - %(max)s BDT for %(category)s course (%(dur)d min)."
            )
            % {
                "price": course.price,
                "min": min_price,
                "max": max_price,
                "category": course.get_category_display(),
                "dur": course.total_duration_minutes,
            }
        )


def check_and_update_course_on_lesson_change(course: Course):
    """
    PRD 7.2: If lessons change after publishing and the price falls outside the range,
    the course is automatically moved back to draft and the seller is notified.
    """
    course.update_duration()
    if course.status == Course.Status.PUBLISHED:
        min_price, max_price = get_allowed_price_range(course.category, course.total_duration_seconds)
        if course.price < min_price or course.price > max_price:
            course.status = Course.Status.DRAFT
            course.save(update_fields=["status", "updated_at"])
            notify(
                user=course.instructor,
                message=_(
                    "Your course '%(title)s' duration changed and the price %(price)s BDT is no longer within the allowed range (%(min)s - %(max)s BDT). It has been reverted to draft."
                )
                % {
                    "title": course.title,
                    "price": course.price,
                    "min": min_price,
                    "max": max_price,
                },
                link=f"/courses/{course.id}/edit/",
            )


@transaction.atomic
def fulfill_course_purchase(order: PaymentOrder) -> CoursePurchase:
    """
    PRD 7.6:
    Creates CoursePurchase, splits commission (COURSE_COMMISSION_PERCENT),
    credits seller's wallet via WalletEntry (append-only), and notifies seller.
    Fulfilment is idempotent; second purchase of the same course is blocked.
    """
    course = Course.objects.select_for_update().get(id=int(order.reference_id))

    # Idempotency check:
    existing = CoursePurchase.objects.filter(user=order.user, course=course, is_successful=True).first()
    if existing:
        return existing

    commission_pct = Decimal(str(getattr(settings, "COURSE_COMMISSION_PERCENT", 10))) / Decimal("100")
    commission_amount = (order.amount_bdt * commission_pct).quantize(Decimal("0.01"))
    seller_earning = (order.amount_bdt - commission_amount).quantize(Decimal("0.01"))

    purchase = CoursePurchase.objects.create(
        user=order.user,
        course=course,
        amount_paid=order.amount_bdt,
        commission_amount=commission_amount,
        seller_earning=seller_earning,
        transaction_id=str(order.id),
        is_successful=True,
    )

    # Credit seller wallet
    WalletEntry.objects.create(
        user=course.instructor,
        amount=seller_earning,
        reason=WalletEntry.Reason.COURSE_SALE,
        reference=f"order:{order.id}:course:{course.id}",
    )

    # Notify instructor
    notify(
        user=course.instructor,
        message=_(
            "User @%(buyer)s purchased your course '%(course)s'. You earned %(earning)s BDT (after %(comm)s BDT commission)."
        )
        % {
            "buyer": order.user.username,
            "course": course.title,
            "earning": seller_earning,
            "comm": commission_amount,
        },
        link=f"/courses/{course.id}/",
    )

    # Notify buyer
    notify(
        user=order.user,
        message=_("You have successfully purchased '%(course)s'! You can start learning right now.")
        % {"course": course.title},
        link=f"/courses/{course.id}/learn/",
    )

    return purchase
