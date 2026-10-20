from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from django.contrib.auth import get_user_model
User = get_user_model()
from django.core.validators import MinValueValidator, MaxValueValidator

MAX_FILE_MB = 50


def validate_file_size(file):
    if file.size > MAX_FILE_MB * 1024 * 1024:
        raise ValidationError(_("File is too large. Maximum size is %(mb)s MB.") % {"mb": MAX_FILE_MB})


class Note(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for review")
        APPROVED = "approved", _("Approved")
        UNVERIFIED = "unverified", _("Published (unverified)")
        REJECTED = "rejected", _("Rejected")
        REMOVED = "removed", _("Removed")

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
        upload_to="notes/%Y/%m/",
        validators=[FileExtensionValidator(["pdf"]), validate_file_size],
    )
    preview = models.ImageField(upload_to="previews/%Y/%m/", blank=True)
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

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.course_code} - {self.title}"
    
class NoteDownload(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='downloaded_notes')
    note = models.ForeignKey('Note', on_delete=models.CASCADE, related_name='downloads')
    downloaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'note')

    def __str__(self):
        return f"{self.user.username} downloaded {self.note.title}"
    
class NoteRating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_ratings')
    note = models.ForeignKey('Note', on_delete=models.CASCADE, related_name='ratings')
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    review = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'note')

    def __str__(self):
        return f"{self.user.username} rated {self.note.title} {self.rating}/5"