from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class SkillPost(models.Model):
    class Kind(models.TextChoices):
        OFFER = "offer", _("Offer (I can teach)")
        REQUEST = "request", _("Request (I want to learn)")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="skill_posts",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    skill_name = models.CharField(max_length=100)
    normalized_skill = models.CharField(max_length=100, blank=True, db_index=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["kind", "is_active", "normalized_skill"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.skill_name:
            self.normalized_skill = " ".join(self.skill_name.lower().split())
        else:
            self.normalized_skill = ""
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username}: {self.get_kind_display()} - {self.skill_name}"


class SwapSession(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested")
        ACCEPTED = "accepted", _("Accepted")
        DECLINED = "declined", _("Declined")
        SCHEDULED = "scheduled", _("Scheduled")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")
        NO_SHOW = "no_show", _("No-show")
        DISPUTED = "disputed", _("Disputed")
        EXPIRED = "expired", _("Expired")

    class Outcome(models.TextChoices):
        COMPLETED = "completed", _("Completed")
        NO_SHOW = "no_show", _("Other party was a no-show")

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="teaching_sessions",
    )
    learner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="learning_sessions",
    )
    post = models.ForeignKey(
        SkillPost,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sessions",
    )
    skill_name = models.CharField(max_length=100)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
        db_index=True,
    )
    proposed_time = models.DateTimeField(null=True, blank=True)
    meeting_link = models.CharField(max_length=300, blank=True)
    deposit_held = models.BooleanField(default=False)
    teacher_outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    learner_outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    teacher_outcome_at = models.DateTimeField(null=True, blank=True)
    learner_outcome_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "proposed_time"]),
            models.Index(fields=["teacher", "status"]),
            models.Index(fields=["learner", "status"]),
        ]

    def __str__(self):
        return f"{self.skill_name} ({self.teacher} -> {self.learner}) [{self.status}]"


class SessionRating(models.Model):
    session = models.ForeignKey(
        SwapSession,
        on_delete=models.CASCADE,
        related_name="ratings",
    )
    rater = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="swap_ratings",
    )
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text=_("Rating from 1 to 5"),
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "rater"],
                name="unique_rating_per_session_and_rater",
            )
        ]

    def __str__(self):
        return f"Rating {self.rating}★ for session #{self.session_id} by {self.rater}"
