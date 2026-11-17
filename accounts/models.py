import os
import re
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


def user_avatar_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"avatars/{instance.pk or uuid.uuid4().hex[:12]}-{uuid.uuid4().hex[:8]}{ext}"


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", _("Student")
        LECTURER = "lecturer", _("Lecturer")

    email = models.EmailField(_("email address"), unique=True)
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.STUDENT,
    )
    id_number = models.CharField(
        _("ID number"),
        max_length=30,
        unique=True,
    )
    profile_picture = models.ImageField(
        _("profile picture"),
        upload_to=user_avatar_upload_to,
        blank=True,
        null=True,
    )
    profile_picture_url = models.URLField(
        _("profile picture URL"),
        max_length=500,
        blank=True,
        default="",
    )
    is_email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suspended_users",
    )
    suspension_reason = models.TextField(blank=True, default="")

    @property
    def is_verified(self):
        return self.email_verified_at is not None

    @property
    def avatar_url(self):
        if self.profile_picture:
            try:
                return self.profile_picture.url
            except Exception:
                pass
        return self.profile_picture_url or ""

    REQUIRED_FIELDS = []

    def save(self, *args, **kwargs):
        if self.profile_picture:
            try:
                self.profile_picture_url = self.profile_picture.url
            except Exception:
                pass
        elif not self.profile_picture and self.profile_picture_url:
            self.profile_picture_url = ""
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.is_superuser:
            return
        id_number = self.id_number or ""
        if self.role == self.Role.STUDENT:
            if not re.fullmatch(r"\d{15,17}", id_number):
                raise ValidationError(
                    {"id_number": _("Student ID must be 15 to 17 digits.")}
                )
        else:
            if not re.fullmatch(r"[A-Za-z0-9-]{3,30}", id_number):
                raise ValidationError(
                    {"id_number": _("Teacher ID must be 3 to 30 characters (letters, digits, hyphen).")}
                )

    def __str__(self):
        return self.get_full_name() or self.username
