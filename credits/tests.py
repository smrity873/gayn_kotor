import os
from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from core.testing import make_student
from credits.admin import CreditLedgerAdmin, reverse_selected_entries
from credits.management.commands.check_ledger import run_ledger_check
from credits.models import CreditLedger
from credits.services import add_entry, get_balance, grant_signup_bonus, reverse_entry


class DummyRequest:
    def __init__(self, user):
        self.user = user
        self._messages = []

    def get_messages(self):
        return self._messages


class HollowStateEndpointTests(TestCase):
    def setUp(self):
        self.user = make_student(username="hollow_user", email="hollow@test.com")
        self.client = Client()

    def test_endpoint_requires_login(self):
        res = self.client.get(reverse("credits:hollow_state"))
        self.assertEqual(res.status_code, 302)

    def test_endpoint_returns_json_balance_and_entries(self):
        self.client.force_login(self.user)
        add_entry(self.user, 50, CreditLedger.Reason.PURCHASE, "Bought nuts")
        add_entry(self.user, 10, CreditLedger.Reason.NOTE_UPLOAD, "Uploaded note")
        add_entry(self.user, -5, CreditLedger.Reason.NOTE_DOWNLOAD, "Unlocked note")

        res = self.client.get(reverse("credits:hollow_state"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["balance"], 55)
        self.assertEqual(len(data["entries"]), 3)

        newest = data["entries"][0]
        self.assertEqual(newest["amount"], -5)
        self.assertEqual(newest["reason"], "note_download")
        self.assertIn("id", newest)
        self.assertIn("created_at", newest)

    def test_endpoint_limits_to_last_20_entries(self):
        self.client.force_login(self.user)
        for i in range(25):
            add_entry(self.user, 1, CreditLedger.Reason.ADMIN, f"Entry {i}")

        res = self.client.get(reverse("credits:hollow_state"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data["entries"]), 20)

    def test_user_only_sees_own_entries(self):
        other = make_student(username="other_hollow", email="other_hollow@test.com")
        add_entry(other, 100, CreditLedger.Reason.PURCHASE, "Other purchase")

        self.client.force_login(self.user)
        add_entry(self.user, 15, CreditLedger.Reason.SIGNUP_BONUS, "Bonus")

        res = self.client.get(reverse("credits:hollow_state"))
        data = res.json()
        self.assertEqual(data["balance"], 15)
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["amount"], 15)


class HollowSceneTemplateTests(TestCase):
    def setUp(self):
        self.user = make_student(username="scene_user", email="scene@test.com")
        self.client = Client()

    def test_video_file_remains_untouched_on_disk(self):
        """Phase 4 rule: static/images/video.mp4 must not be deleted or modified."""
        video_path = os.path.join(settings.BASE_DIR, "static", "images", "video.mp4")
        self.assertTrue(os.path.exists(video_path), "video.mp4 must exist on disk")
        self.assertGreater(os.path.getsize(video_path), 1000000, "video.mp4 must have non-zero size")

    def test_hollow_page_renders_svg_scene_and_controls(self):
        self.client.force_login(self.user)
        add_entry(self.user, 500, CreditLedger.Reason.PURCHASE, "Big pack")

        res = self.client.get(reverse("credits:hollow"))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode("utf-8")

        # SVG scene present
        self.assertIn('id="hollow-scene"', content)
        self.assertIn('id="hollow-nuts-group"', content)
        self.assertIn('id="squirrel-actor"', content)
        self.assertIn('id="replay-animation"', content)
        self.assertIn('prefers-reduced-motion', content)
        self.assertIn('hollow_last_seen', content)
        self.assertIn('balance-counter', content)


class CreditLedgerPageTests(TestCase):
    def setUp(self):
        self.user = make_student(username="ledger_user", email="ledger@test.com")
        self.client = Client()

    def test_ledger_page_requires_login(self):
        res = self.client.get(reverse("credits:ledger"))
        self.assertEqual(res.status_code, 302)

    def test_ledger_page_renders_with_entries(self):
        self.client.force_login(self.user)
        add_entry(self.user, 30, CreditLedger.Reason.SIGNUP_BONUS, "Welcome bonus")
        add_entry(self.user, 10, CreditLedger.Reason.NOTE_UPLOAD, "Notes on Physics")

        res = self.client.get(reverse("credits:ledger"))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode("utf-8")
        self.assertIn("Credit Ledger", content)
        self.assertIn("Welcome bonus", content)
        self.assertIn("+30 🌰", content)
        self.assertIn("+10 🌰", content)

    def test_ledger_filter_by_reason(self):
        self.client.force_login(self.user)
        add_entry(self.user, 30, CreditLedger.Reason.SIGNUP_BONUS, "Bonus")
        add_entry(self.user, 10, CreditLedger.Reason.NOTE_UPLOAD, "Upload")
        add_entry(self.user, 50, CreditLedger.Reason.PURCHASE, "Purchase")

        res = self.client.get(reverse("credits:ledger") + f"?reason={CreditLedger.Reason.PURCHASE}")
        self.assertEqual(res.status_code, 200)
        entries = res.context["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].reason, CreditLedger.Reason.PURCHASE)

    def test_ledger_pagination(self):
        self.client.force_login(self.user)
        for i in range(25):
            add_entry(self.user, 1, CreditLedger.Reason.ADMIN, f"Item {i:02d}")

        res = self.client.get(reverse("credits:ledger"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context["entries"]), 20)
        self.assertTrue(res.context["page_obj"].has_next())

        # Page 2
        res2 = self.client.get(reverse("credits:ledger") + "?page=2")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(len(res2.context["entries"]), 5)


class AdminLedgerReversalTests(TestCase):
    def setUp(self):
        self.user = make_student(username="rev_user", email="rev@test.com")

    def test_reverse_entry_service_creates_reversal_row(self):
        orig = add_entry(self.user, 20, CreditLedger.Reason.NOTE_UPLOAD, "Uploaded math note")
        rev = reverse_entry(orig)

        self.assertEqual(rev.amount, -20)
        self.assertEqual(rev.reason, CreditLedger.Reason.REVERSAL)
        self.assertEqual(rev.description, f"Reversal of #{orig.id}")
        self.assertEqual(rev.reverses, orig)

        orig.refresh_from_db()
        self.assertEqual(orig.reversed_by, rev)
        self.assertEqual(get_balance(self.user), 0)

    def test_reversing_same_entry_twice_is_blocked(self):
        orig = add_entry(self.user, 50, CreditLedger.Reason.PURCHASE, "Credit buy")
        reverse_entry(orig)

        # Second reversal via service must fail with ValueError
        with self.assertRaises(ValueError):
            reverse_entry(orig)

        # Direct DB creation with duplicate reverses field must violate uniqueness
        with self.assertRaises(IntegrityError):
            CreditLedger.objects.create(
                user=self.user,
                amount=-50,
                reason=CreditLedger.Reason.REVERSAL,
                reverses=orig,
            )

    def test_reversing_a_reversal_is_blocked(self):
        orig = add_entry(self.user, 20, CreditLedger.Reason.NOTE_UPLOAD, "Note upload")
        rev = reverse_entry(orig)

        with self.assertRaises(ValueError):
            reverse_entry(rev)

    def test_admin_action_reverse_selected_entries(self):
        e1 = add_entry(self.user, 10, CreditLedger.Reason.NOTE_UPLOAD, "Note 1")
        e2 = add_entry(self.user, 15, CreditLedger.Reason.NOTE_UPLOAD, "Note 2")

        site = AdminSite()
        admin_obj = CreditLedgerAdmin(CreditLedger, site)

        from django.test import RequestFactory
        factory = RequestFactory()
        req = factory.post("/admin/credits/creditledger/")
        req.user = make_student(username="admin_user", is_staff=True, is_superuser=True)
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, "session", {})
        setattr(req, "_messages", FallbackStorage(req))

        qs = CreditLedger.objects.filter(id__in=[e1.id, e2.id])
        reverse_selected_entries(admin_obj, req, qs)

        self.assertEqual(get_balance(self.user), 0)
        e1.refresh_from_db()
        e2.refresh_from_db()
        self.assertIsNotNone(e1.reversed_by)
        self.assertIsNotNone(e2.reversed_by)

        # Trying to reverse again through admin action produces no new reversals
        count_before = CreditLedger.objects.count()
        reverse_selected_entries(admin_obj, req, qs)
        count_after = CreditLedger.objects.count()
        self.assertEqual(count_before, count_after)


class CheckLedgerCommandTests(TestCase):
    def setUp(self):
        self.user1 = make_student(username="user1", email="u1@test.com")
        self.user2 = make_student(username="user2", email="u2@test.com")

    def test_clean_ledger_reports_zero_issues(self):
        add_entry(self.user1, 30, CreditLedger.Reason.SIGNUP_BONUS, "Bonus")
        add_entry(self.user2, 30, CreditLedger.Reason.SIGNUP_BONUS, "Bonus")

        findings = run_ledger_check()
        self.assertEqual(findings["total_issues"], 0)
        self.assertEqual(len(findings["negative_balances"]), 0)
        self.assertEqual(len(findings["duplicate_signups"]), 0)
        self.assertEqual(len(findings["duplicate_upload_rewards"]), 0)
        self.assertEqual(len(findings["orphan_reversals"]), 0)

    def test_detects_negative_balance(self):
        add_entry(self.user1, -20, CreditLedger.Reason.ADMIN, "Negative adj", allow_negative=True)
        findings = run_ledger_check()
        self.assertEqual(len(findings["negative_balances"]), 1)
        self.assertEqual(findings["negative_balances"][0]["user_id"], self.user1.id)

    def test_detects_duplicate_signup_bonus(self):
        CreditLedger.objects.create(user=self.user1, amount=30, reason=CreditLedger.Reason.SIGNUP_BONUS)
        CreditLedger.objects.create(user=self.user1, amount=30, reason=CreditLedger.Reason.SIGNUP_BONUS)

        findings = run_ledger_check()
        self.assertEqual(len(findings["duplicate_signups"]), 1)
        self.assertEqual(findings["duplicate_signups"][0]["user_id"], self.user1.id)

    def test_detects_duplicate_upload_rewards(self):
        CreditLedger.objects.create(
            user=self.user1,
            amount=10,
            reason=CreditLedger.Reason.NOTE_UPLOAD,
            description="Note approved: Advanced Calculus",
        )
        CreditLedger.objects.create(
            user=self.user1,
            amount=10,
            reason=CreditLedger.Reason.NOTE_UPLOAD,
            description="Note approved: Advanced Calculus",
        )

        findings = run_ledger_check()
        self.assertEqual(len(findings["duplicate_upload_rewards"]), 1)
        self.assertEqual(findings["duplicate_upload_rewards"][0]["user_id"], self.user1.id)

    def test_detects_orphan_reversal(self):
        CreditLedger.objects.create(
            user=self.user1,
            amount=-10,
            reason=CreditLedger.Reason.REVERSAL,
            description="Manual reversal without target",
            reverses=None,
        )

        findings = run_ledger_check()
        self.assertEqual(len(findings["orphan_reversals"]), 1)
        self.assertEqual(findings["orphan_reversals"][0]["user_id"], self.user1.id)

    def test_management_command_execution(self):
        from io import StringIO
        out = StringIO()
        call_command("check_ledger", stdout=out)
        output = out.getvalue()
        self.assertIn("Credit Ledger Integrity Audit", output)
        self.assertIn("[OK]", output)
