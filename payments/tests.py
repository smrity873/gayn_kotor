import sys
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from core.testing import make_student
from credits.models import CreditLedger
from credits.services import get_balance
from payments.gateways.base import PaymentResult
from payments.models import PaymentOrder
from payments.services import complete_order, create_order, fulfil_order, get_gateway


class PaymentsArchitectureTests(TestCase):
    def test_payments_app_does_not_import_credits_or_courses(self):
        """Verifies architecture constraint: payments must not import credits or courses."""
        # Check all python files in payments/
        import os
        import ast

        payments_dir = os.path.join(settings.BASE_DIR, "payments")
        forbidden = ["credits", "courses"]

        for root, _, files in os.walk(payments_dir):
            for file in files:
                if file.endswith(".py") and file != "tests.py":
                    filepath = os.path.join(root, file)
                    with open(filepath, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=filepath)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                for bad in forbidden:
                                    self.assertFalse(
                                        alias.name.startswith(bad),
                                        f"{filepath} imports {alias.name} (forbidden!)"
                                    )
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                for bad in forbidden:
                                    self.assertFalse(
                                        node.module.startswith(bad),
                                        f"{filepath} imports from {node.module} (forbidden!)"
                                    )


class PaymentOrderAndSandboxTests(TestCase):
    def setUp(self):
        self.user = make_student(username="buyer_1")
        self.other_user = make_student(username="other_buyer")
        self.client = Client()

    def test_pay_then_replay_callback_adds_credits_once(self):
        """Acceptance test: Pay then replay callback: credits added once."""
        initial_balance = get_balance(self.user)

        # Create an order for 50 BDT (50 credits)
        order = create_order(
            user=self.user,
            purpose=PaymentOrder.Purpose.CREDIT_TOPUP,
            amount_bdt=Decimal("50.00"),
            reference_type="credits",
            reference_id="50",
        )
        self.assertEqual(order.status, PaymentOrder.Status.CREATED)

        # 1. Complete order via callback (simulate success)
        result = PaymentResult(
            order_id=str(order.id),
            success=True,
            gateway_txn_id="txn_test_12345",
        )
        updated_order = complete_order(order, result)
        self.assertEqual(updated_order.status, PaymentOrder.Status.PAID)
        self.assertEqual(get_balance(self.user), initial_balance + 50)

        purchase_entries_count = CreditLedger.objects.filter(
            user=self.user, reason=CreditLedger.Reason.PURCHASE
        ).count()
        self.assertEqual(purchase_entries_count, 1)

        # 2. Replay callback with same or different txn_id
        replay_result = PaymentResult(
            order_id=str(order.id),
            success=True,
            gateway_txn_id="txn_test_12345_replay",
        )
        replayed_order = complete_order(order, replay_result)
        self.assertEqual(replayed_order.status, PaymentOrder.Status.PAID)

        # Credits must remain unchanged (added only once)
        self.assertEqual(get_balance(self.user), initial_balance + 50)
        self.assertEqual(
            CreditLedger.objects.filter(user=self.user, reason=CreditLedger.Reason.PURCHASE).count(),
            1,
        )

    def test_fail_or_cancel_gives_no_credits(self):
        """Acceptance test: Fail or cancel: no credits."""
        initial_balance = get_balance(self.user)

        order = create_order(
            user=self.user,
            purpose=PaymentOrder.Purpose.CREDIT_TOPUP,
            amount_bdt=Decimal("100.00"),
        )

        fail_result = PaymentResult(
            order_id=str(order.id),
            success=False,
            error_message="User cancelled payment.",
        )
        complete_order(order, fail_result)
        order.refresh_from_db()

        self.assertEqual(order.status, PaymentOrder.Status.FAILED)
        self.assertEqual(get_balance(self.user), initial_balance)
        self.assertFalse(
            CreditLedger.objects.filter(user=self.user, reason=CreditLedger.Reason.PURCHASE).exists()
        )

    def test_amount_below_min_or_above_max_is_rejected(self):
        """Acceptance test: Amount below min or above max is rejected."""
        self.client.force_login(self.user)

        # Test below min (e.g. 5 < min 10)
        response_below = self.client.post(
            reverse("payments:buy_credits"),
            {"nuts": 5}
        )
        self.assertEqual(response_below.status_code, 302)
        self.assertEqual(PaymentOrder.objects.filter(user=self.user).count(), 0)

        # Test above max (e.g. 6000 > max 5000)
        response_above = self.client.post(
            reverse("payments:buy_credits"),
            {"nuts": 6000}
        )
        self.assertEqual(response_above.status_code, 302)
        self.assertEqual(PaymentOrder.objects.filter(user=self.user).count(), 0)

    def test_tampering_with_posted_credit_count_or_amount_has_no_effect(self):
        """
        Acceptance test: Tampering with a posted credit count or amount has no effect.
        Credits added during fulfillment are strictly computed server-side from order.amount_bdt.
        """
        initial_balance = get_balance(self.user)

        # Legitimate order for 50 BDT
        order = create_order(
            user=self.user,
            purpose=PaymentOrder.Purpose.CREDIT_TOPUP,
            amount_bdt=Decimal("50.00"),
            reference_type="credits",
            reference_id="50",
        )

        # In sandbox, attacker attempts to POST extra fields like "credits": 9999 or "amount_bdt": 1
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("payments:sandbox", args=[order.id]),
            {
                "order_id": str(order.id),
                "action": "pay",
                "credits": 99999,
                "amount": 1,
                "amount_bdt": Decimal("1.00"),
            }
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PAID)

        # Balance increased by exactly 50 (computed from server-side order.amount_bdt / CREDIT_PRICE_BDT)
        self.assertEqual(get_balance(self.user), initial_balance + 50)

    def test_order_of_another_user_cannot_be_viewed_or_completed(self):
        """Acceptance test: An order of another user cannot be viewed or completed."""
        order = create_order(
            user=self.user,
            purpose=PaymentOrder.Purpose.CREDIT_TOPUP,
            amount_bdt=Decimal("50.00"),
        )

        self.client.force_login(self.other_user)

        # Viewing another user's order detail gives 403
        detail_response = self.client.get(reverse("payments:order_detail", args=[order.id]))
        self.assertEqual(detail_response.status_code, 403)

        # Accessing another user's sandbox view gives 403
        sandbox_get = self.client.get(reverse("payments:sandbox", args=[order.id]))
        self.assertEqual(sandbox_get.status_code, 403)

        # Attempting to post to another user's sandbox view gives 403
        sandbox_post = self.client.post(
            reverse("payments:sandbox", args=[order.id]),
            {"action": "pay"}
        )
        self.assertEqual(sandbox_post.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.CREATED)

    @override_settings(DEBUG=False, SANDBOX_ALLOWED=False)
    def test_sandbox_refuses_to_work_when_debug_false_and_sandbox_disallowed(self):
        """The sandbox page must refuse to work when DEBUG=False unless SANDBOX_ALLOWED=True."""
        order = create_order(
            user=self.user,
            purpose=PaymentOrder.Purpose.CREDIT_TOPUP,
            amount_bdt=Decimal("50.00"),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("payments:sandbox", args=[order.id]))
        self.assertEqual(response.status_code, 403)

        post_response = self.client.post(
            reverse("payments:sandbox", args=[order.id]),
            {"action": "pay"}
        )
        self.assertEqual(post_response.status_code, 403)

