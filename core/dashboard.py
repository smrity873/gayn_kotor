from datetime import timedelta
from django.conf import settings
from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from campus.models import BatchMembership
from courses.models import Course
from credits.management.commands.check_ledger import run_ledger_check
from credits.models import CreditLedger
from credits.services import get_balance
from notes.models import Note, NoteAppeal, NoteDownload
from swaps.models import SwapSession


def build_student_context(user):
    """Builds dashboard context for student role."""
    now = timezone.now()

    # Nut balance
    nut_balance = get_balance(user)

    # Recent ledger entries (up to 5)
    recent_ledger = list(user.ledger.all()[:5])

    # Unlocked notes
    unlocked_notes = list(
        NoteDownload.objects.filter(user=user)
        .select_related("note", "note__owner", "note__department")
        .order_by("-downloaded_at")[:5]
    )

    # My notes by status (counts + recent list)
    status_counts = {status.value: 0 for status in Note.Status}
    for row in user.notes.values("status").annotate(count=Count("id")):
        status_counts[row["status"]] = row["count"]

    my_notes = list(
        user.notes.all()
        .select_related("department")
        .order_by("-created_at")[:5]
    )

    # Upcoming scheduled sessions
    upcoming_sessions = list(
        SwapSession.objects.filter(
            Q(teacher=user) | Q(learner=user),
            status=SwapSession.Status.SCHEDULED,
            proposed_time__gte=now,
        )
        .select_related("teacher", "learner")
        .order_by("proposed_time")[:5]
    )

    # Unread notifications
    unread_notifications = list(
        user.notifications.filter(is_read=False).order_by("-created_at")[:5]
    )
    unread_count = user.notifications.filter(is_read=False).count()

    context = {
        "nut_balance": nut_balance,
        "recent_ledger": recent_ledger,
        "unlocked_notes": unlocked_notes,
        "status_counts": status_counts,
        "my_notes": my_notes,
        "upcoming_sessions": upcoming_sessions,
        "unread_notifications": unread_notifications,
        "unread_count": unread_count,
    }

    # CR review queue summary if user is an approved CR
    try:
        membership = user.membership
    except Exception:
        membership = None

    if membership and membership.is_cr and membership.status == BatchMembership.Status.APPROVED:
        cr_batch = membership.batch
        review_queue_count = Note.objects.filter(
            batch=cr_batch,
            status=Note.Status.PENDING,
        ).count()
        review_queue_notes = list(
            Note.objects.filter(batch=cr_batch, status=Note.Status.PENDING)
            .select_related("owner", "department")
            .order_by("created_at")[:5]
        )
        context["is_cr"] = True
        context["cr_batch"] = cr_batch
        context["review_queue_count"] = review_queue_count
        context["review_queue_notes"] = review_queue_notes

    return context


def build_class_teacher_context(user):
    """Builds dashboard context for class teacher (lecturer) role."""
    batches = list(user.class_teacher_of.select_related("department").all())
    if not batches:
        return {}

    # Escalated notes (pending notes marked escalated or past escalation deadline)
    now = timezone.now()
    escalate_threshold = now - timedelta(days=getattr(settings, "NOTE_ESCALATE_DAYS", 3))
    escalated_notes = list(
        Note.objects.filter(
            batch__in=batches,
            status=Note.Status.PENDING,
        )
        .filter(Q(escalated_at__isnull=False) | Q(created_at__lte=escalate_threshold))
        .select_related("owner", "department", "batch")
        .order_by("created_at")[:5]
    )

    # Flagged notes
    flagged_notes = list(
        Note.objects.filter(batch__in=batches, status=Note.Status.FLAGGED)
        .select_related("owner", "department", "batch")
        .order_by("-created_at")[:5]
    )

    # Open appeals
    open_appeals = list(
        NoteAppeal.objects.filter(note__batch__in=batches, status=NoteAppeal.Status.OPEN)
        .select_related("note", "user")
        .order_by("created_at")[:5]
    )

    # Pending join requests
    pending_join_requests = list(
        BatchMembership.objects.filter(
            batch__in=batches, status=BatchMembership.Status.PENDING
        )
        .select_related("user", "batch")
        .order_by("created_at")[:5]
    )
    pending_joins_count = BatchMembership.objects.filter(
        batch__in=batches, status=BatchMembership.Status.PENDING
    ).count()

    # Member count
    member_count = BatchMembership.objects.filter(
        batch__in=batches, status=BatchMembership.Status.APPROVED
    ).count()

    # CR list
    cr_list = list(
        BatchMembership.objects.filter(
            batch__in=batches, is_cr=True, status=BatchMembership.Status.APPROVED
        ).select_related("user", "batch")
    )

    return {
        "batches": batches,
        "escalated_notes": escalated_notes,
        "escalated_count": len(escalated_notes),
        "flagged_notes": flagged_notes,
        "flagged_count": len(flagged_notes),
        "open_appeals": open_appeals,
        "open_appeals_count": len(open_appeals),
        "pending_join_requests": pending_join_requests,
        "pending_joins_count": pending_joins_count,
        "member_count": member_count,
        "cr_list": cr_list,
        "manage_batch_url": reverse("campus:manage"),
    }


def build_lecturer_context(user):
    """Builds dashboard context for lecturer role."""
    enable_courses = getattr(settings, "ENABLE_VIDEO_COURSES", True)

    # Own notes with unlock counts
    own_notes = list(
        user.notes.annotate(unlock_count=Count("downloads"))
        .select_related("department")
        .order_by("-created_at")[:5]
    )

    # Own teaching sessions
    own_sessions = list(
        SwapSession.objects.filter(teacher=user)
        .select_related("learner")
        .order_by("-updated_at")[:5]
    )

    context = {
        "own_notes": own_notes,
        "own_sessions": own_sessions,
    }

    if enable_courses:
        from payments.services import get_wallet_balance
        courses = list(
            Course.objects.filter(instructor=user).order_by("-created_at")[:5]
        )
        context["courses"] = courses
        context["wallet_balance"] = get_wallet_balance(user)

    return context


def build_admin_context(user):
    """Builds dashboard context for admin role (counts and integrity summary, no moderation)."""
    enable_courses = getattr(settings, "ENABLE_VIDEO_COURSES", True)

    total_users = User.objects.count()
    total_notes = Note.objects.count()
    total_sessions = SwapSession.objects.count()
    total_courses = Course.objects.count() if enable_courses else 0
    total_credits = CreditLedger.objects.aggregate(total=Sum("amount"))["total"] or 0

    ledger_summary = run_ledger_check()

    return {
        "admin_url": reverse("admin:index"),
        "total_users": total_users,
        "total_notes": total_notes,
        "total_sessions": total_sessions,
        "total_courses": total_courses,
        "total_credits": total_credits,
        "check_ledger_summary": ledger_summary,
    }


def get_dashboard_context(user):
    """Combines modular role context builders for a user.
    A user with multiple roles sees the union of widgets.
    """
    is_student = (user.role == User.Role.STUDENT)
    try:
        is_cr = (
            is_student
            and user.membership.is_cr
            and user.membership.status == BatchMembership.Status.APPROVED
        )
    except Exception:
        is_cr = False
    is_lecturer = (user.role == User.Role.LECTURER)
    is_class_teacher = user.class_teacher_of.exists()
    is_admin = user.is_staff or user.is_superuser

    context = {
        "user": user,
        "is_student": is_student,
        "is_cr": is_cr,
        "is_lecturer": is_lecturer,
        "is_class_teacher": is_class_teacher,
        "is_admin": is_admin,
    }

    if is_student:
        context["student"] = build_student_context(user)
    if is_class_teacher:
        context["class_teacher"] = build_class_teacher_context(user)
    if is_lecturer:
        context["lecturer"] = build_lecturer_context(user)
    if is_admin:
        context["admin"] = build_admin_context(user)

    return context