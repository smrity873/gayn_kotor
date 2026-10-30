from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
import os
import uuid
from core.storage import private_storage



from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import timedelta

from django.utils import timezone

def validate_pdf_header(file):
    pos = file.tell() if hasattr(file, "tell") else 0
    if hasattr(file, "seek"):
        file.seek(0)
    header = file.read(5)
    if hasattr(file, "seek"):
        file.seek(pos)
    if header != b"%PDF-":
        raise ValidationError(_("Invalid PDF file. The file does not have a valid PDF header."))


def validate_file_size(file):
    max_mb = getattr(settings, "NOTE_MAX_UPLOAD_MB", 20)
    if file.size > max_mb * 1024 * 1024:
        raise ValidationError(_("File is too large. Maximum size is %(mb)s MB.") % {"mb": max_mb})



def note_file_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".pdf"
    return f"notes/{uuid.uuid4()}{ext}"


def note_preview_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"previews/{uuid.uuid4()}{ext}"


class Note(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for review")
        APPROVED = "approved", _("Approved")
        UNVERIFIED = "unverified", _("Published (unverified)")
        REJECTED = "rejected", _("Rejected")
        REMOVED = "removed", _("Removed")
        FLAGGED = "flagged", _("Flagged")

    class Visibility(models.TextChoices):
        PUBLIC = "public", _("Everyone")
        DEPARTMENT = "department", _("My department only")
        BATCH = "batch", _("My batch only")

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notes",
    )
    title = models.CharField(_("title"), max_length=150)
    course_code = models.CharField(_("course code"), max_length=20)
    department = models.ForeignKey(
        "campus.Department",
        on_delete=models.PROTECT,
        related_name="notes",
    )
    semester = models.PositiveSmallIntegerField(
        _("semester"),
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    description = models.TextField(_("description"), blank=True)
    visibility = models.CharField(
        max_length=12,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )
    file = models.FileField(
        storage=private_storage,
        upload_to=note_file_upload_to,
        validators=[FileExtensionValidator(["pdf"]), validate_file_size, validate_pdf_header],
    )
    preview = models.ImageField(
        storage=private_storage,
        upload_to=note_preview_upload_to,
        blank=True,
    )
    batch = models.ForeignKey(
        "campus.Batch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )
    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_notes",
    )
    download_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    reward_paid = models.BooleanField(default=False)
    cr_reminded_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    status_before_flag = models.CharField(max_length=12, blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.course_code} - {self.title}"
    
    @property
    def is_overdue(self):
        if self.status != self.Status.PENDING:
            return False
        return timezone.now() - self.created_at >= timedelta(days=settings.NOTE_ESCALATE_DAYS)

    @property
    def days_left_to_autopublish(self):
        if self.status != self.Status.PENDING:
            return None
        left = self.created_at + timedelta(days=settings.NOTE_AUTOPUBLISH_DAYS) - timezone.now()
        return max(0, left.days)
    
class NoteDownload(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='downloaded_notes')
    note = models.ForeignKey('Note', on_delete=models.CASCADE, related_name='downloads')
    downloaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'note')

    def __str__(self):
        return f"{self.user.username} downloaded {self.note.title}"
    
class NoteRating(models.Model):
    owner_rewarded = models.BooleanField(default=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='given_ratings')
    note = models.ForeignKey('Note', on_delete=models.CASCADE, related_name='ratings')
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    review = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'note')

    def __str__(self):
        return f"{self.user.username} rated {self.note.title} {self.rating}/5"


class NoteAppeal(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        UPHELD = "upheld", _("Upheld")
        GRANTED = "granted", _("Granted")

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="appeals")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="note_appeals",
    )
    message = models.TextField(max_length=500)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decided_note_appeals",
    )
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Appeal for {self.note.title} by {self.user} ({self.status})"


class NoteReport(models.Model):
    class Reason(models.TextChoices):
        INACCURATE = "inaccurate", _("Inaccurate / Incorrect Content")
        COPYRIGHT = "copyright", _("Copyright Violation")
        SPAM = "spam", _("Spam or Irrelevant")
        OFFENSIVE = "offensive", _("Inappropriate or Offensive")
        OTHER = "other", _("Other Issue")

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="reports")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="note_reports",
    )
    reason = models.CharField(max_length=20, choices=Reason.choices, default=Reason.OTHER)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_note_reports",
    )

    class Meta:
        unique_together = ("note", "user")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Report on {self.note.title} by {self.user} ({self.reason})"
