import re
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Replace, Upper
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from campus.models import BatchMembership
from credits.models import CreditLedger
from credits.services import add_entry
from notifications.services import notify, notify_many

from .models import Note, NoteDownload

UPLOAD_REWARD = 10


def batch_reviewers(batch):
    """Class teacher and approved CRs of a batch."""
    if batch is None:
        return []
    users = {}
    if batch.class_teacher_id:
        users[batch.class_teacher_id] = batch.class_teacher
    cr_users = User.objects.filter(
        membership__batch=batch,
        membership__is_cr=True,
        membership__status=BatchMembership.Status.APPROVED,
    )
    for u in cr_users:
        users[u.id] = u
    return list(users.values())


def notify_reviewers(note):
    owner_name = note.owner.get_full_name() or note.owner.username
    reviewers = [u for u in batch_reviewers(note.batch) if u.id != note.owner_id]
    notify_many(
        reviewers,
        f'New note to review: "{note.title}" by {owner_name}',
        reverse("notes:review_detail", args=[note.pk]),
    )


@transaction.atomic
def approve_note(note, reviewer=None):
    """Publishes the note as verified. Pays the upload reward only once.
    Returns True when nuts were paid."""
    note.status = Note.Status.APPROVED
    note.reviewed_by = reviewer
    note.rejection_reason = ""
    if note.published_at is None:
        note.published_at = timezone.now()

    pay = not note.reward_paid
    if pay:
        note.reward_paid = True
    note.save()

    if pay:
        add_entry(
            note.owner,
            UPLOAD_REWARD,
            CreditLedger.Reason.NOTE_UPLOAD,
            f"Note approved: {note.title}",
            notify=False,
        )

    if reviewer is not None:
        text = f'Your note "{note.title}" was approved.'
        if pay:
            text += f" You earned {UPLOAD_REWARD} nuts."
        notify(note.owner, text, reverse("notes:detail", args=[note.pk]))
    return pay


@transaction.atomic
def reject_note(note, reviewer, reason):
    note.status = Note.Status.REJECTED
    note.reviewed_by = reviewer
    note.rejection_reason = reason.strip()
    note.save()
    notify(
        note.owner,
        f'Your note "{note.title}" was rejected. Reason: {note.rejection_reason}',
        reverse("notes:list") + "?tab=mine",
    )


def publish_overdue_notes(now=None):
    """Notes nobody reviewed in time go live as 'unverified' (no reward yet)."""
    if now is None:
        now = timezone.now()
    cutoff = now - timedelta(days=settings.NOTE_AUTOPUBLISH_DAYS)
    notes = list(
        Note.objects.filter(status=Note.Status.PENDING, created_at__lte=cutoff).select_related("owner")
    )
    if not notes:
        return 0

    Note.objects.filter(id__in=[n.id for n in notes]).update(
        status=Note.Status.UNVERIFIED, published_at=now
    )
    for n in notes:
        notify(
            n.owner,
            f'Your note "{n.title}" is now public (not yet verified).',
            reverse("notes:detail", args=[n.pk]),
        )
    return len(notes)


def process_review_deadlines(now=None):
    """Evaluates CR reminders, teacher escalations, and auto-publishing for pending notes."""
    if now is None:
        now = timezone.now()

    cr_reminder_days = getattr(settings, "NOTE_CR_REMINDER_DAYS", 2)
    escalate_days = getattr(settings, "NOTE_ESCALATE_DAYS", 3)
    autopublish_days = getattr(settings, "NOTE_AUTOPUBLISH_DAYS", 7)

    pending_notes = Note.objects.filter(
        status=Note.Status.PENDING
    ).select_related("owner", "batch", "batch__class_teacher")

    updated_count = 0

    for note in pending_notes:
        age = now - note.created_at
        batch = note.batch

        # 1. Day 7+: Auto-publish as UNVERIFIED
        if age >= timedelta(days=autopublish_days):
            note.status = Note.Status.UNVERIFIED
            note.published_at = now
            note.save(update_fields=["status", "published_at"])
            notify(
                note.owner,
                f'Your note "{note.title}" is now public (not yet verified).',
                reverse("notes:detail", args=[note.pk]),
            )
            updated_count += 1
            continue

        if not batch:
            continue

        crs = list(User.objects.filter(
            membership__batch=batch,
            membership__is_cr=True,
            membership__status=BatchMembership.Status.APPROVED,
        ).exclude(pk=note.owner_id))

        has_cr = len(crs) > 0
        teacher = batch.class_teacher
        has_teacher = teacher is not None and teacher.pk != note.owner_id

        # Batch with no CR goes straight to class teacher
        is_escalated = (
            age >= timedelta(days=escalate_days)
            or (not has_cr and age >= timedelta(days=cr_reminder_days))
        )

        if is_escalated:
            if not note.escalated_at:
                note.escalated_at = now
                note.last_reminder_at = now
                fields_to_save = ["escalated_at", "last_reminder_at"]
                if not note.cr_reminded_at:
                    note.cr_reminded_at = now
                    fields_to_save.append("cr_reminded_at")
                note.save(update_fields=fields_to_save)

                if has_teacher:
                    notify(
                        teacher,
                        f'Escalated review: "{note.title}" in {batch.name} requires your review.',
                        reverse("notes:review_detail", args=[note.pk]),
                    )
                updated_count += 1
            else:
                # Then one reminder per day (last_reminder_at)
                if note.last_reminder_at and (now - note.last_reminder_at >= timedelta(days=1)):
                    note.last_reminder_at = now
                    note.save(update_fields=["last_reminder_at"])
                    if has_teacher:
                        notify(
                            teacher,
                            f'Reminder: "{note.title}" in {batch.name} is waiting for your review.',
                            reverse("notes:review_detail", args=[note.pk]),
                        )
                    updated_count += 1

        elif age >= timedelta(days=cr_reminder_days):
            if not note.cr_reminded_at:
                note.cr_reminded_at = now
                note.save(update_fields=["cr_reminded_at"])

                if crs:
                    notify_many(
                        crs,
                        f'Review reminder: "{note.title}" is waiting for review.',
                        reverse("notes:review_detail", args=[note.pk]),
                    )

                owner_is_cr = BatchMembership.objects.filter(
                    user=note.owner, batch=batch, is_cr=True, status=BatchMembership.Status.APPROVED
                ).exists()
                if owner_is_cr and has_teacher:
                    notify(
                        teacher,
                        f'Review notification: "{note.title}" was uploaded by CR {note.owner.get_full_name() or note.owner.username}.',
                        reverse("notes:review_detail", args=[note.pk]),
                    )
                updated_count += 1

    return updated_count


def trigger_deadlines_lazy():
    """Runs review deadline engine throttled by cache (at most once every 5 minutes)."""
    key = "notes_deadline_engine_last_run"
    if cache.add(key, "1", timeout=300):
        try:
            process_review_deadlines()
            publish_overdue_notes()
        except Exception:
            cache.delete(key)
            raise


def visible_notes(user):
    published = Note.objects.filter(
        status__in=[Note.Status.APPROVED, Note.Status.UNVERIFIED]
    ).select_related("owner", "department", "batch")

    if user.is_superuser or user.role == User.Role.LECTURER:
        return published

    allowed = Q(visibility=Note.Visibility.PUBLIC) | Q(owner=user)
    membership = getattr(user, "membership", None)
    if membership is not None and membership.status == BatchMembership.Status.APPROVED:
        allowed |= Q(
            visibility=Note.Visibility.DEPARTMENT,
            department_id=membership.batch.department_id,
        )
        allowed |= Q(visibility=Note.Visibility.BATCH, batch_id=membership.batch_id)
    return published.filter(allowed)


def reviewer_batch_ids(user):
    """Batches where this user can review notes (class teacher or CR)."""
    ids = set(user.class_teacher_of.values_list("id", flat=True))
    ids |= set(
        BatchMembership.objects.filter(
            user=user, is_cr=True, status=BatchMembership.Status.APPROVED
        ).values_list("batch_id", flat=True)
    )
    return ids


def can_view_note(user, note):
    if note.status == Note.Status.REMOVED:
        if user.is_authenticated and (note.owner_id == user.id or user.is_superuser):
            return True
        return False

    if user.is_authenticated and (note.owner_id == user.id or user.is_superuser):
        return True
    if user.is_authenticated and note.batch_id and note.batch_id in reviewer_batch_ids(user):
        return True
    if user.is_authenticated and NoteDownload.objects.filter(user=user, note=note).exists():
        return True
    return visible_notes(user).filter(pk=note.pk).exists()


def reviewable_notes(user):
    waiting = Note.objects.filter(
        status__in=[Note.Status.PENDING, Note.Status.UNVERIFIED]
    ).select_related("owner", "department", "batch")
    if user.is_superuser:
        return waiting
    return waiting.filter(batch_id__in=reviewer_batch_ids(user)).exclude(owner=user)


def can_review(user, note):
    return reviewable_notes(user).filter(pk=note.pk).exists()


def can_upload(user):
    """Returns (allowed, hint_message)."""
    if user.is_superuser or user.role == User.Role.LECTURER:
        return True, ""
    membership = getattr(user, "membership", None)
    if membership is None:
        return False, "Join a batch first. Ask your class teacher to approve your request."
    if membership.status == BatchMembership.Status.APPROVED:
        return True, ""
    if membership.status == BatchMembership.Status.PENDING:
        return False, "Your batch request is waiting for your class teacher's approval."
    return False, "Your batch request was rejected. Please contact your class teacher."


def search_notes(notes, query):
    """Every word must match somewhere: title, course code, description,
    department code or uploader's name. 'cse101', 'CSE 101' and 'cse-101' all work."""
    query = (query or "").strip()
    if not query:
        return notes

    notes = notes.annotate(
        code_norm=Replace(
            Replace(Replace(Upper("course_code"), Value(" "), Value("")), Value("-"), Value("")),
            Value("_"),
            Value(""),
        )
    )
    for word in query.split():
        match = (
            Q(title__icontains=word)
            | Q(course_code__icontains=word)
            | Q(description__icontains=word)
            | Q(department__code__icontains=word)
            | Q(owner__first_name__icontains=word)
            | Q(owner__last_name__icontains=word)
            | Q(owner__username__icontains=word)
        )
        normalized = re.sub(r"[\s\-_]", "", word).upper()
        if normalized:
            match |= Q(code_norm__icontains=normalized)
        notes = notes.filter(match)
    return notes


def make_preview(note):
    """Saves the first page of the PDF as a small JPEG. Never raises."""
    try:
        import fitz  # PyMuPDF

        note.file.open("rb")
        data = note.file.read()
        note.file.close()

        doc = fitz.open(stream=data, filetype="pdf")
        if doc.page_count == 0:
            return False
        page = doc[0]
        zoom = 600 / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        note.preview.save(f"note-{note.pk}.jpg", ContentFile(pix.tobytes("jpeg")), save=True)
        doc.close()
        return True
    except Exception:
        return False

@transaction.atomic
def remove_note(note, by, reason, reverse_reward=False):
    """Sets REMOVED, notifies the owner, and if reverse_reward and the reward was paid,
    writes a REVERSAL ledger row with allow_negative=True."""
    note.status = Note.Status.REMOVED
    note.save(update_fields=["status"])

    if reverse_reward and note.reward_paid:
        add_entry(
            note.owner,
            -UPLOAD_REWARD,
            CreditLedger.Reason.REVERSAL,
            f"Reward reversed: {reason}",
            allow_negative=True,
            notify=False,
        )

    notify(
        note.owner,
        f'Your note "{note.title}" was removed by {by.get_full_name() or by.username}. Reason: {reason}',
        "",
    )


def can_remove_note(user, note):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if note.batch and note.batch.class_teacher_id == user.id:
        return True
    return False
