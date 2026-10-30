import uuid
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class PaymentOrder(models.Model):
    class Purpose(models.TextChoices):
        CREDIT_TOPUP = "credit_topup", _("Credit Top-up")
        COURSE = "course", _("Course Purchase")

    class Status(models.TextChoices):
        CREATED = "created", _("Created")
        PENDING = "pending", _("Pending")
        PAID = "paid", _("Paid")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_orders",
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    amount_bdt = models.DecimalField(max_digits=10, decimal_places=2)
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
    )
    gateway = models.CharField(max_length=50, default="sandbox")
    gateway_txn_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Order {self.id} ({self.get_purpose_display()} - {self.amount_bdt} BDT) - {self.status}"
