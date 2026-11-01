from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from notifications.services import notify
from .gateways.base import PaymentGateway, PaymentResult
from .gateways.sandbox import SandboxGateway
from .models import PaymentOrder, Wallet, WalletEntry, WithdrawalRequest
from .registry import get_fulfiller

_GATEWAYS = {
    "sandbox": SandboxGateway,
}


def get_gateway(name: str = None) -> PaymentGateway:
    """Returns an instance of the configured payment gateway."""
    gateway_name = name or getattr(settings, "PAYMENT_GATEWAY", "sandbox")
    gateway_cls = _GATEWAYS.get(gateway_name)
    if not gateway_cls:
        raise ValueError(f"Unknown payment gateway: '{gateway_name}'")
    return gateway_cls()


def create_order(
    user,
    purpose: str,
    amount_bdt: Decimal,
    reference_type: str = "",
    reference_id: str = "",
    gateway: str = None,
) -> PaymentOrder:
    """Creates a new PaymentOrder in CREATED status."""
    gateway_name = gateway or getattr(settings, "PAYMENT_GATEWAY", "sandbox")
    order = PaymentOrder.objects.create(
        user=user,
        purpose=purpose,
        amount_bdt=amount_bdt,
        reference_type=reference_type,
        reference_id=reference_id,
        status=PaymentOrder.Status.CREATED,
        gateway=gateway_name,
    )
    return order


@transaction.atomic
def fulfil_order(order: PaymentOrder, gateway_txn_id: str = None) -> PaymentOrder:
    """
    Fulfills a paid order.
    Atomically locks the order. If already paid, returns as a no-op (idempotent).
    Otherwise marks PAID, records paid_at and gateway_txn_id, and calls the registered fulfiller.
    """
    locked_order = PaymentOrder.objects.select_for_update().get(id=order.id)
    if locked_order.status == PaymentOrder.Status.PAID:
        return locked_order

    locked_order.status = PaymentOrder.Status.PAID
    locked_order.paid_at = timezone.now()
    if gateway_txn_id:
        locked_order.gateway_txn_id = gateway_txn_id
    locked_order.save(update_fields=["status", "paid_at", "gateway_txn_id"])

    fulfiller = get_fulfiller(locked_order.purpose)
    if not fulfiller:
        raise ValueError(f"No fulfiller registered for purpose: '{locked_order.purpose}'")

    fulfiller(locked_order)
    return locked_order


@transaction.atomic
def fail_order(order: PaymentOrder, reason: str = "") -> PaymentOrder:
    """Marks an order as failed if it was not already paid."""
    locked_order = PaymentOrder.objects.select_for_update().get(id=order.id)
    if locked_order.status == PaymentOrder.Status.PAID:
        return locked_order

    locked_order.status = PaymentOrder.Status.FAILED
    locked_order.save(update_fields=["status"])
    return locked_order


@transaction.atomic
def cancel_order(order: PaymentOrder) -> PaymentOrder:
    """Marks an order as cancelled if it was not already paid."""
    locked_order = PaymentOrder.objects.select_for_update().get(id=order.id)
    if locked_order.status == PaymentOrder.Status.PAID:
        return locked_order

    locked_order.status = PaymentOrder.Status.CANCELLED
    locked_order.save(update_fields=["status"])
    return locked_order


def complete_order(order: PaymentOrder, result: PaymentResult) -> PaymentOrder:
    """Processes a payment result and either fulfills or fails the order."""
    if result.success:
        return fulfil_order(order, gateway_txn_id=result.gateway_txn_id)
    else:
        return fail_order(order, reason=result.error_message)


# -------------------------------------------------------------------------
# Wallet Ledger & Withdrawals (PRD 7.7 & 7.8)
# -------------------------------------------------------------------------

def get_wallet_balance(user) -> Decimal:
    """
    PRD 7.7: Returns the current wallet balance for the user,
    calculated as the sum of signed WalletEntry amounts.
    """
    if not user or not user.is_authenticated:
        return Decimal("0.00")
    total = WalletEntry.objects.filter(user=user).aggregate(
        total=models.Sum("amount")
    )["total"]
    return total if total is not None else Decimal("0.00")


@transaction.atomic
def create_withdrawal_request(
    user,
    amount: Decimal,
    method: str,
    account_details: str,
) -> WithdrawalRequest:
    """
    PRD 7.8:
    Creates a withdrawal request.
    Validates minimum amount (WITHDRAW_MIN_BDT) and that amount <= current balance.
    Locks user's Wallet to prevent concurrent double-withdrawal race conditions.
    Writes a negative withdrawal_hold WalletEntry atomically.
    """
    min_amount = getattr(settings, "WITHDRAW_MIN_BDT", Decimal("500"))
    if amount < min_amount:
        raise ValidationError(
            _("Minimum withdrawal amount is %(min)s BDT.") % {"min": min_amount}
        )

    # Lock wallet anchor for user
    Wallet.objects.select_for_update().get_or_create(user=user)

    balance = get_wallet_balance(user)
    if amount > balance:
        raise ValidationError(
            _("Withdrawal amount (%(amount)s BDT) exceeds available balance (%(bal)s BDT).")
            % {"amount": amount, "bal": balance}
        )

    req = WithdrawalRequest.objects.create(
        user=user,
        amount=amount,
        method=method,
        account_details=account_details,
        status=WithdrawalRequest.Status.PENDING,
    )

    # Append negative hold entry to financial ledger
    WalletEntry.objects.create(
        user=user,
        amount=-amount,
        reason=WalletEntry.Reason.WITHDRAWAL_HOLD,
        reference=f"withdrawal:{req.id}",
    )

    notify(
        user=user,
        message=_(
            "Your withdrawal request of %(amount)s BDT via %(method)s is pending review."
        )
        % {"amount": amount, "method": req.get_method_display()},
        link="/payments/wallet/",
    )

    return req


@transaction.atomic
def reject_withdrawal_request(req_id: int, note: str = "") -> WithdrawalRequest:
    """
    PRD 7.8:
    Rejects a pending withdrawal request and creates a withdrawal_reversal WalletEntry.
    Idempotent: does nothing if not pending.
    """
    req = WithdrawalRequest.objects.select_for_update().get(id=req_id)
    if req.status != WithdrawalRequest.Status.PENDING:
        return req

    # Lock wallet anchor
    Wallet.objects.select_for_update().get_or_create(user=req.user)

    req.status = WithdrawalRequest.Status.REJECTED
    req.admin_note = note
    req.decided_at = timezone.now()
    req.save(update_fields=["status", "admin_note", "decided_at"])

    # Reverse the hold
    WalletEntry.objects.create(
        user=req.user,
        amount=req.amount,
        reason=WalletEntry.Reason.WITHDRAWAL_REVERSAL,
        reference=f"withdrawal:{req.id}:reversal",
    )

    notify(
        user=req.user,
        message=_(
            "Your withdrawal request of %(amount)s BDT was rejected. The funds have been returned to your wallet. Note: %(note)s"
        )
        % {"amount": req.amount, "note": note or "None"},
        link="/payments/wallet/",
    )

    return req


@transaction.atomic
def mark_withdrawal_paid(req_id: int, note: str = "") -> WithdrawalRequest:
    """
    PRD 7.8:
    Marks a pending withdrawal request as paid. Status update only.
    Idempotent: does nothing if not pending.
    """
    req = WithdrawalRequest.objects.select_for_update().get(id=req_id)
    if req.status != WithdrawalRequest.Status.PENDING:
        return req

    req.status = WithdrawalRequest.Status.PAID
    req.admin_note = note
    req.decided_at = timezone.now()
    req.save(update_fields=["status", "admin_note", "decided_at"])

    notify(
        user=req.user,
        message=_(
            "Your withdrawal of %(amount)s BDT has been sent to your %(method)s account (%(details)s)."
        )
        % {
            "amount": req.amount,
            "method": req.get_method_display(),
            "details": req.account_details,
        },
        link="/payments/wallet/",
    )

    return req
