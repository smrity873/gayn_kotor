import uuid
from django.urls import reverse

from .base import PaymentGateway, PaymentResult


class SandboxGateway(PaymentGateway):
    name = "sandbox"

    def create_payment(self, order, return_url: str) -> str:
        return reverse("payments:sandbox", args=[order.id])

    def parse_callback(self, request) -> PaymentResult:
        order_id = request.POST.get("order_id") or request.GET.get("order_id")
        action = request.POST.get("action", "").lower()
        success = action == "pay"
        txn_id = f"sbx_txn_{uuid.uuid4().hex[:12]}" if success else None
        error_message = "" if success else (request.POST.get("reason") or "Payment cancelled or failed in sandbox.")
        return PaymentResult(
            order_id=str(order_id),
            success=success,
            gateway_txn_id=txn_id,
            error_message=error_message,
        )
