import re

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Replace, Upper
from django.utils import timezone

from accounts.models import User
from campus.models import BatchMembership
from credits.models import CreditLedger
from credits.services import add_entry

from .models import Note
from datetime import timedelta

from django.conf import settings

UPLOAD_REWARD = 10


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
        )
    return pay


def publish_overdue_notes():
    """Notes nobody reviewed in time go live as 'unverified' (no reward yet)."""
    cutoff = timezone.now() - timedelta(days=settings.NOTE_AUTOPUBLISH_DAYS)
    return Note.objects.filter(
        status=Note.Status.PENDING, created_at__lte=cutoff
    ).update(status=Note.Status.UNVERIFIED, published_at=timezone.now())

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
    if note.owner_id == user.id or user.is_superuser:
        return True
    if note.batch_id and note.batch_id in reviewer_batch_ids(user):
        return True
    return visible_notes(user).filter(pk=note.pk).exists()



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
    
    

def reviewable_notes(user):
    pending = Note.objects.filter(status=Note.Status.PENDING).select_related(
        "owner", "department", "batch"
    )
    if user.is_superuser:
        return pending
    return pending.filter(batch_id__in=reviewer_batch_ids(user)).exclude(owner=user)


def can_review(user, note):
    return reviewable_notes(user).filter(pk=note.pk).exists()


@transaction.atomic
def reject_note(note, reviewer, reason):
    note.status = Note.Status.REJECTED
    note.reviewed_by = reviewer
    note.rejection_reason = reason.strip()
    note.save()