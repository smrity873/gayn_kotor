from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class CreditLedger(models.Model):
    class Reason(models.TextChoices):
        SIGNUP_BONUS = "signup_bonus", _("Sign-up bonus")
        NOTE_UPLOAD = "note_upload", _("Note upload reward")
        NOTE_DOWNLOAD = "note_download", _("Note download")
        RATING_RECEIVED = "rating_received", _("Rating received")
        RATING_GIVEN = "rating_given", _("Rating given")
        PURCHASE = "purchase", _("Credit purchase")
        SWAP_HOLD = "swap_hold", _("Skill swap deposit held")
        SWAP_RETURN = "swap_return", _("Skill swap deposit returned")
        SWAP_FORFEIT = "swap_forfeit", _("Skill swap deposit forfeited")
        ADMIN = "admin", _("Admin adjustment")
        REVERSAL = "reversal", _("Reversal")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ledger",
    )
    amount = models.IntegerField(_("amount"))
    reason = models.CharField(max_length=20, choices=Reason.choices)
    description = models.CharField(max_length=200, blank=True)
    reverses = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reversed_by",
        help_text=_("The ledger entry that this entry reverses."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user} {self.amount:+d} ({self.reason})"
