from dataclasses import dataclass
from typing import Optional


@dataclass
class PaymentResult:
    order_id: str
    success: bool
    gateway_txn_id: Optional[str] = None
    error_message: str = ""


class PaymentGateway:
    name: str

    def create_payment(self, order, return_url: str) -> str:
        """Returns the URL to send the user to for payment."""
        raise NotImplementedError

    def parse_callback(self, request) -> PaymentResult:
        """Parses the callback/return request and returns a PaymentResult."""
        raise NotImplementedError
