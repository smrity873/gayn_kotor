import re

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


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
    is_email_verified = models.BooleanField(default=False)
    REQUIRED_FIELDS = []

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