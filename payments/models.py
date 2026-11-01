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


class Wallet(models.Model):
    """Optional metadata model for user wallet (PRD 7.7)."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Wallet for {self.user.username}"


class WalletEntry(models.Model):
    """Append-only financial ledger for instructor earnings and withdrawals (PRD 7.7)."""
    class Reason(models.TextChoices):
        COURSE_SALE = "course_sale", _("Course Sale")
        WITHDRAWAL_HOLD = "withdrawal_hold", _("Withdrawal Hold")
        WITHDRAWAL_REVERSAL = "withdrawal_reversal", _("Withdrawal Reversal")
        ADJUSTMENT = "adjustment", _("Adjustment")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet_entries",
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text=_("Signed amount in BDT"),
    )
    reason = models.CharField(max_length=30, choices=Reason.choices)
    reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["reason"]),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.amount:+f} BDT ({self.reason})"


class WithdrawalRequest(models.Model):
    """Instructor cash withdrawal request (PRD 7.8)."""
    class Method(models.TextChoices):
        BKASH = "bkash", _("bKash")
        NAGAD = "nagad", _("Nagad")
        ROCKET = "rocket", _("Rocket")
        BANK = "bank", _("Bank Transfer")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PAID = "paid", _("Paid")
        REJECTED = "rejected", _("Rejected")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="withdrawal_requests",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices)
    account_details = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Withdrawal #{self.id} for {self.user.username} ({self.amount} BDT - {self.status})"
