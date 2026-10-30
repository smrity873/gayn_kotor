import datetime
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.signing import TimestampSigner, b62_encode
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.forms import SignUpForm
from accounts.services import TOKEN_SALT, generate_verification_token
from campus.models import BatchMembership
from core.testing import make_batch, make_department, make_lecturer, make_student
from credits.models import CreditLedger
from credits.services import get_balance

User = get_user_model()


class Phase1AccountsTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.dept = make_department(name="CSE Dept", code="CSE")
        self.teacher = make_lecturer(username="teacher1")
        self.batch_a = make_batch(department=self.dept, name="Batch A", class_teacher=self.teacher)
        self.batch_b = make_batch(department=self.dept, name="Batch B", class_teacher=self.teacher)

    def test_signup_gives_zero_credits(self):
        form_data = {
            "first_name": "Rahim",
            "last_name": "Uddin",
            "username": "rahim123",
            "email": "rahim@example.com",
            "role": User.Role.STUDENT,
            "id_number": "100000000000001",
            "batch": self.batch_a.pk,
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
        }
        form = SignUpForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(get_balance(user), 0)
        self.assertFalse(CreditLedger.objects.filter(user=user, reason=CreditLedger.Reason.SIGNUP_BONUS).exists())
        self.assertIsNone(user.email_verified_at)
        self.assertFalse(user.is_verified)

    def test_verification_grants_signup_bonus_once(self):
        student = make_student(batch=self.batch_a, email_verified_at=None, is_email_verified=False)
        self.assertEqual(get_balance(student), 0)

        token = generate_verification_token(student)
        response = self.client.get(reverse("accounts:verify", args=[token]))
        self.assertRedirects(response, reverse("core:home"))

        student.refresh_from_db()
        self.assertTrue(student.is_verified)
        self.assertIsNotNone(student.email_verified_at)
        self.assertEqual(get_balance(student), 30)
        self.assertEqual(
            CreditLedger.objects.filter(user=student, reason=CreditLedger.Reason.SIGNUP_BONUS).count(),
            1,
        )

        # Visiting the link twice gives 30 total (idempotent)
        response2 = self.client.get(reverse("accounts:verify", args=[token]))
        self.assertRedirects(response2, reverse("core:home"))
        student.refresh_from_db()
        self.assertEqual(get_balance(student), 30)
        self.assertEqual(
            CreditLedger.objects.filter(user=student, reason=CreditLedger.Reason.SIGNUP_BONUS).count(),
            1,
        )

    def test_expired_or_tampered_token_rejected(self):
        student = make_student(batch=self.batch_a, email_verified_at=None, is_email_verified=False)

        # Tampered
        response = self.client.get(reverse("accounts:verify", args=["bad:fake:token"]))
        self.assertRedirects(response, reverse("core:home"))
        student.refresh_from_db()
        self.assertFalse(student.is_verified)
        self.assertEqual(get_balance(student), 0)

        # Expired (older than 3 days)
        signer = TimestampSigner(salt=TOKEN_SALT)
        old_timestamp = b62_encode(int(time.time() - 4 * 86400))
        value = f"{student.pk}:{student.email}"
        sig = signer.signature(f"{value}{signer.sep}{old_timestamp}")
        expired_token = f"{value}{signer.sep}{old_timestamp}{signer.sep}{sig}"

        resp_expired = self.client.get(reverse("accounts:verify", args=[expired_token]))
        self.assertRedirects(resp_expired, reverse("core:home"))
        student.refresh_from_db()
        self.assertFalse(student.is_verified)
        self.assertEqual(get_balance(student), 0)

    def test_resend_verification_throttled(self):
        student = make_student(batch=self.batch_a, email_verified_at=None, is_email_verified=False)
        self.client.force_login(student)

        # First resend
        resp1 = self.client.get(reverse("accounts:resend_verification"))
        self.assertRedirects(resp1, reverse("core:home"))
        self.assertEqual(len(mail.outbox), 1)

        # Immediate second resend -> throttled
        resp2 = self.client.get(reverse("accounts:resend_verification"))
        self.assertRedirects(resp2, reverse("core:home"))
        self.assertEqual(len(mail.outbox), 1)

    def test_verified_required_gate(self):
        unverified_student = make_student(batch=self.batch_a, email_verified_at=None, is_email_verified=False)
        self.client.force_login(unverified_student)

        # Browsing notes list is allowed
        list_resp = self.client.get(reverse("notes:list"))
        self.assertEqual(list_resp.status_code, 200)

        # Upload is blocked
        upload_resp = self.client.get(reverse("notes:upload"))
        self.assertRedirects(upload_resp, reverse("core:home"))

        # Download is blocked
        download_resp = self.client.post(reverse("notes:download", args=[999]))
        self.assertRedirects(download_resp, reverse("core:home"))

        # Rate is blocked
        rate_resp = self.client.post(reverse("notes:rate", args=[999]))
        self.assertRedirects(rate_resp, reverse("core:home"))

    @override_settings(ALLOWED_EMAIL_DOMAINS=["campus.edu"])
    def test_domain_rule(self):
        form_data_invalid = {
            "first_name": "Karim",
            "last_name": "Ahmed",
            "username": "karim123",
            "email": "karim@gmail.com",
            "role": User.Role.STUDENT,
            "id_number": "100000000000002",
            "batch": self.batch_a.pk,
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
        }
        form_inv = SignUpForm(data=form_data_invalid)
        self.assertFalse(form_inv.is_valid())
        self.assertIn("email", form_inv.errors)

        form_data_valid = form_data_invalid.copy()
        form_data_valid["email"] = "karim@campus.edu"
        form_val = SignUpForm(data=form_data_valid)
        self.assertTrue(form_val.is_valid(), form_val.errors)

    def test_cr_cannot_suspend_another_cr(self):
        cr1 = make_student(batch=self.batch_a, cr=True)
        cr2 = make_student(batch=self.batch_a, cr=True)
        self.client.force_login(cr1)

        membership2 = cr2.membership
        resp = self.client.post(
            reverse("campus:membership_action", args=[membership2.pk]),
            {"action": "suspend", "reason": "Violation"},
        )
        self.assertEqual(resp.status_code, 403)
        cr2.refresh_from_db()
        self.assertTrue(cr2.is_active)
        self.assertIsNone(cr2.suspended_at)

    def test_cr_cannot_suspend_teacher(self):
        cr = make_student(batch=self.batch_a, cr=True)
        self.client.force_login(cr)

        resp = self.client.post(
            reverse("campus:membership_action", args=[99999]),
            {"action": "suspend", "reason": "Test"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_cr_cannot_suspend_student_of_different_batch(self):
        cr_a = make_student(batch=self.batch_a, cr=True)
        student_b = make_student(batch=self.batch_b, cr=False)
        self.client.force_login(cr_a)

        resp = self.client.post(
            reverse("campus:membership_action", args=[student_b.membership.pk]),
            {"action": "suspend", "reason": "Spam"},
        )
        self.assertEqual(resp.status_code, 403)
        student_b.refresh_from_db()
        self.assertTrue(student_b.is_active)

    def test_cr_can_suspend_regular_student_in_own_batch(self):
        cr_a = make_student(batch=self.batch_a, cr=True)
        student_a = make_student(batch=self.batch_a, cr=False)
        self.client.force_login(cr_a)

        resp = self.client.post(
            reverse("campus:membership_action", args=[student_a.membership.pk]),
            {"action": "suspend", "reason": "Inappropriate content"},
        )
        self.assertRedirects(resp, reverse("campus:manage"))
        student_a.refresh_from_db()
        self.assertFalse(student_a.is_active)
        self.assertIsNotNone(student_a.suspended_at)
        self.assertEqual(student_a.suspended_by, cr_a)
        self.assertEqual(student_a.suspension_reason, "Inappropriate content")

    def test_suspension_requires_reason(self):
        cr_a = make_student(batch=self.batch_a, cr=True)
        student_a = make_student(batch=self.batch_a, cr=False)
        self.client.force_login(cr_a)

        resp = self.client.post(
            reverse("campus:membership_action", args=[student_a.membership.pk]),
            {"action": "suspend", "reason": "   "},
        )
        self.assertRedirects(resp, reverse("campus:manage"))
        student_a.refresh_from_db()
        self.assertTrue(student_a.is_active)

    def test_class_teacher_can_suspend_and_reactivate(self):
        student_a = make_student(batch=self.batch_a, cr=False)
        self.client.force_login(self.teacher)

        # Suspend
        resp = self.client.post(
            reverse("campus:membership_action", args=[student_a.membership.pk]),
            {"action": "suspend", "reason": "Academic dishonesty"},
        )
        self.assertRedirects(resp, reverse("campus:manage"))
        student_a.refresh_from_db()
        self.assertFalse(student_a.is_active)

        # Reactivate
        resp_act = self.client.post(
            reverse("campus:membership_action", args=[student_a.membership.pk]),
            {"action": "reactivate"},
        )
        self.assertRedirects(resp_act, reverse("campus:manage"))
        student_a.refresh_from_db()
        self.assertTrue(student_a.is_active)
        self.assertIsNone(student_a.suspended_at)
        self.assertEqual(student_a.suspension_reason, "")

    def test_suspended_user_cannot_login_and_sees_clear_message(self):
        student = make_student(batch=self.batch_a, password="MyPassword123!")
        student.is_active = False
        student.suspended_at = timezone.now()
        student.suspension_reason = "Cheating on exam"
        student.save()

        login_resp = self.client.post(
            reverse("accounts:login"),
            {"username": student.username, "password": "MyPassword123!"},
        )
        self.assertEqual(login_resp.status_code, 200)
        self.assertContains(login_resp, "Your account has been suspended")
        self.assertContains(login_resp, "Cheating on exam")

    def test_login_throttle_blocks_after_5_failures(self):
        student = make_student(batch=self.batch_a, password="RealPassword123!")

        # 5 failed attempts
        for _ in range(5):
            resp = self.client.post(
                reverse("accounts:login"),
                {"username": student.username, "password": "WrongPassword!"},
            )
            self.assertEqual(resp.status_code, 200)

        # 6th attempt even with correct password is throttled
        resp_blocked = self.client.post(
            reverse("accounts:login"),
            {"username": student.username, "password": "RealPassword123!"},
        )
        self.assertEqual(resp_blocked.status_code, 200)
        self.assertContains(resp_blocked, "Too many failed login attempts")

    def test_profile_page_displays_info(self):
        student = make_student(batch=self.batch_a)
        self.client.force_login(student)

        resp = self.client.get(reverse("accounts:profile"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, student.username)
        self.assertContains(resp, student.id_number)
        self.assertContains(resp, self.batch_a.name)
        self.assertContains(resp, self.dept.code)
