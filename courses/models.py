import os
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.storage import private_storage


def lesson_video_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".mp4"
    return f"lessons/{uuid.uuid4()}{ext}"


class PricingRule(models.Model):
    category = models.CharField(max_length=20, unique=True)
    min_per_hour = models.DecimalField(max_digits=10, decimal_places=2)
    max_per_hour = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["category"]

    def __str__(self):
        return f"{self.category}: {self.min_per_hour} - {self.max_per_hour} BDT/h"


class Course(models.Model):
    class Category(models.TextChoices):
        ACADEMIC = "academic", _("Academic")
        NON_ACADEMIC = "non_academic", _("Non-academic")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")

    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="courses",
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.ACADEMIC,
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Price in BDT",
    )
    thumbnail = models.ImageField(
        upload_to="course_thumbnails/",
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    total_duration_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED

    @property
    def total_duration_minutes(self):
        return round(self.total_duration_seconds / 60)

    @property
    def total_duration_hours(self):
        return round(self.total_duration_seconds / 3600, 1)

    def update_duration(self):
        total = self.lessons.aggregate(models.Sum("duration_seconds"))["duration_seconds__sum"] or 0
        self.total_duration_seconds = total
        self.save(update_fields=["total_duration_seconds", "updated_at"])
        return total


class Lesson(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="lessons",
    )
    title = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=1)
    video_file = models.FileField(
        storage=private_storage,
        upload_to=lesson_video_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["mp4"])],
    )
    video_url = models.URLField(
        max_length=500,
        blank=True,
        help_text=_("Optional YouTube unlisted video link"),
    )
    duration_seconds = models.PositiveIntegerField(default=0)
    is_free_preview = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["course", "order", "id"]

    def __str__(self):
        return f"{self.course.title} - #{self.order} {self.title}"

    @property
    def duration_minutes(self):
        return round(self.duration_seconds / 60)


class CoursePurchase(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="purchased_courses",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="purchases",
    )
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    commission_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    seller_earning = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    transaction_id = models.CharField(max_length=100, unique=True, blank=True, null=True)
    is_successful = models.BooleanField(default=False)
    purchased_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-purchased_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "course"],
                condition=models.Q(is_successful=True),
                name="unique_successful_course_purchase",
            )
        ]

    def __str__(self):
        return f"{self.user.username} purchased {self.course.title}"
