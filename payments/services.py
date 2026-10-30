from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .gateways.base import PaymentGateway, PaymentResult
from .gateways.sandbox import SandboxGateway
from .models import PaymentOrder
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
