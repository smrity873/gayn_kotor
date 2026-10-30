from django.apps import AppConfig


class CreditsConfig(AppConfig):
    name = "credits"

    def ready(self):
        try:
            from payments.models import PaymentOrder
            from payments.registry import register_fulfiller
            from .services import fulfill_credit_topup

            register_fulfiller(PaymentOrder.Purpose.CREDIT_TOPUP, fulfill_credit_topup)
        except Exception:
            pass
