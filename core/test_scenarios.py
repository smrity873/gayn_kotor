from datetime import timedelta
from decimal import Decimal
import os

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.services import generate_verification_token
from campus.models import Batch, BatchMembership, Department
from core.testing import (
    make_batch,
    make_department,
    make_lecturer,
    make_note,
    make_student,
    sample_pdf_file,
)
from courses.models import Course, CoursePurchase, Lesson, PricingRule
from credits.models import CreditLedger
from credits.services import add_entry, get_balance
from notes.models import Note, NoteAppeal, NoteDownload, NoteRating, NoteReport
from notes.services import approve_note, process_review_deadlines
from payments.gateways.base import PaymentResult
from payments.models import PaymentOrder, WalletEntry, WithdrawalRequest
from payments.services import (
    complete_order,
    create_order,
    create_withdrawal_request,
    get_wallet_balance,
)
from swaps.models import SessionRating, SkillPost, SwapSession
from swaps.services import (
    accept_and_propose_time,
    cancel_session,
    confirm_time,
    rate_session,
    report_outcome,
    request_session,
    resolve_all_swaps,
    set_meeting_link,
)


def sample_mp4_file(name="sample.mp4"):
    mp4_path = os.path.join(settings.BASE_DIR, "static", "images", "video.mp4")
    if os.path.exists(mp4_path):
        with open(mp4_path, "rb") as f:
            data = f.read()
    else:
        data = b"dummy mp4 video bytes"
    return SimpleUploadedFile(name, data, content_type="video/mp4")


class UserLifecycleAndOnboardingScenarioTest(TestCase):
    """Scenario 1: Signup, verification token consumption, signup bonus credit."""

    def setUp(self):
        self.dept = make_department(name="Computer Engineering", code="CPE")
        self.batch = make_batch(department=self.dept, name="Batch 2024")
        self.client = Client()

    def test_signup_verification_and_bonus_flow(self):
        # 1. User signs up via POST
        signup_data = {
            "username": "new_student",
            "email": "new_student@campus.edu",
            "password1": "Password123!",
            "password2": "Password123!",
            "role": User.Role.STUDENT,
            "department": str(self.dept.id),
            "batch": str(self.batch.id),
            "id_number": "0872220005101099",
            "first_name": "New",
            "last_name": "Student",
        }
        resp = self.client.post(reverse("accounts:signup"), data=signup_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        user = User.objects.get(username="new_student")
        self.assertFalse(user.is_email_verified)
        self.assertEqual(get_balance(user), 0)

        # 2. Token generation
        token = generate_verification_token(user)
        self.assertIsNotNone(token)

        # 3. User accesses verification link
        verify_url = reverse("accounts:verify", args=[token])
        resp_verify = self.client.get(verify_url, follow=True)
        self.assertEqual(resp_verify.status_code, 200)

        # 4. Email is verified and signup bonus (50 nuts) is awarded
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)
        self.assertIsNotNone(user.email_verified_at)

        bonus_entry = CreditLedger.objects.filter(
            user=user,
            reason=CreditLedger.Reason.SIGNUP_BONUS,
        ).first()
        self.assertIsNotNone(bonus_entry)
        self.assertEqual(bonus_entry.amount, 30)
        self.assertEqual(get_balance(user), 30)


class NoteLifecycleEscalationAndRewardsScenarioTest(TestCase):
    """Scenario 2: Note upload, review escalation, approval, download/unlock, rating reward."""

    def setUp(self):
        self.dept = make_department(name="Civil Engineering", code="CE")
        self.teacher = make_lecturer(username="teacher_ce")
        self.batch = make_batch(department=self.dept, name="CE Batch 2024", class_teacher=self.teacher)

        self.cr = make_student(batch=self.batch, cr=True, username="cr_ce")
        self.uploader = make_student(batch=self.batch, username="uploader_ce")
        self.downloader = make_student(batch=self.batch, username="downloader_ce")

        # Initial credits
        add_entry(self.downloader, 50, CreditLedger.Reason.SIGNUP_BONUS, "Initial signup bonus")
        self.client = Client()

    def test_full_note_lifecycle(self):
        # 1. Note upload
        self.client.force_login(self.uploader)
        upload_resp = self.client.post(
            reverse("notes:upload"),
            data={
                "title": "Structural Mechanics Overview",
                "department": self.dept.id,
                "batch": self.batch.id,
                "course_code": "CE201",
                "semester": 4,
                "file": sample_pdf_file(),
                "visibility": Note.Visibility.PUBLIC,
            },
            follow=True,
        )
        self.assertEqual(upload_resp.status_code, 200)

        note = Note.objects.get(title="Structural Mechanics Overview")
        self.assertEqual(note.status, Note.Status.PENDING)
        self.assertFalse(note.reward_paid)
        self.assertEqual(get_balance(self.uploader), 0)

        # 2. Test escalation: age note 2 days -> reminder
        two_days_ago = timezone.now() - timedelta(days=2, hours=1)
        Note.objects.filter(pk=note.pk).update(created_at=two_days_ago)
        updated_2d = process_review_deadlines()
        self.assertEqual(updated_2d, 1)  # Reminder action executed
        note.refresh_from_db()
        self.assertIsNotNone(note.cr_reminded_at)

        # Age note 4 days -> escalated to teacher
        four_days_ago = timezone.now() - timedelta(days=4, hours=1)
        Note.objects.filter(pk=note.pk).update(created_at=four_days_ago)
        updated_4d = process_review_deadlines()
        self.assertEqual(updated_4d, 1)  # Escalation action executed
        note.refresh_from_db()
        self.assertIsNotNone(note.escalated_at)

        # 3. Class teacher reviews and approves note
        self.client.force_login(self.teacher)
        review_resp = self.client.post(
            reverse("notes:review_action", args=[note.pk]),
            data={"action": "approve"},
            follow=True,
        )
        self.assertEqual(review_resp.status_code, 200)

        note.refresh_from_db()
        self.assertEqual(note.status, Note.Status.APPROVED)
        self.assertTrue(note.reward_paid)
        self.assertEqual(note.reviewed_by, self.teacher)
        # Uploader received 10 nuts upload reward
        self.assertEqual(get_balance(self.uploader), 10)

        # 4. Downloader unlocks / downloads note
        self.client.force_login(self.downloader)
        download_resp = self.client.post(reverse("notes:download", args=[note.pk]), follow=True)
        self.assertEqual(download_resp.status_code, 200)

        self.assertTrue(NoteDownload.objects.filter(user=self.downloader, note=note).exists())
        # Downloader paid 5 nuts (50 - 5 = 45)
        self.assertEqual(get_balance(self.downloader), 45)
        # Uploader balance is 10 nuts (upload reward)
        self.assertEqual(get_balance(self.uploader), 10)

        # 5. Downloader rates note 5 stars
        rate_resp = self.client.post(
            reverse("notes:rate", args=[note.pk]),
            data={"rating": 5, "review": "Exceptional study material!"},
            follow=True,
        )
        self.assertEqual(rate_resp.status_code, 200)

        rating_obj = NoteRating.objects.get(user=self.downloader, note=note)
        self.assertEqual(rating_obj.rating, 5)
        # Rating rewards: Uploader earned +5 for rating >= 4 (10 + 5 = 15), reviewer earned +1 (45 + 1 = 46)
        self.assertEqual(get_balance(self.uploader), 15)
        self.assertEqual(get_balance(self.downloader), 46)


class NoteFlaggingAndAppealScenarioTest(TestCase):
    """Scenario 3: Note report, flagging, appeal submission and moderation decision."""

    def setUp(self):
        self.dept = make_department()
        self.teacher = make_lecturer(username="teacher_mod")
        self.batch = make_batch(department=self.dept, class_teacher=self.teacher)
        self.author = make_student(batch=self.batch, username="author_mod")
        self.reporters = [
            make_student(batch=self.batch, username=f"rep_{i}")
            for i in range(3)
        ]

        self.note = make_note(
            owner=self.author,
            department=self.dept,
            batch=self.batch,
            status=Note.Status.APPROVED,
            title="Questionable Content Notes",
        )
        self.client = Client()

    def test_report_flag_appeal_and_restore_flow(self):
        # 1. 3 distinct students file reports -> note automatically becomes FLAGGED
        for reporter in self.reporters:
            self.client.force_login(reporter)
            rep_resp = self.client.post(
                reverse("notes:report", args=[self.note.pk]),
                data={"reason": "copyright", "details": "Matches copyrighted textbook chapter."},
                follow=False,
            )
            self.assertEqual(rep_resp.status_code, 302)

        self.note.refresh_from_db()
        self.assertEqual(self.note.status, Note.Status.FLAGGED)

        # 2. Class teacher dismisses flag -> note restored to APPROVED
        self.client.force_login(self.teacher)
        dismiss_resp = self.client.post(
            reverse("notes:flagged_action", args=[self.note.pk]),
            data={"action": "dismiss"},
            follow=True,
        )
        self.assertEqual(dismiss_resp.status_code, 200)
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, Note.Status.APPROVED)

        # 3. Teacher rejects note -> author submits appeal
        from notes.services import reject_note
        reject_note(self.note, reviewer=self.teacher, reason="Needs more explanatory diagrams")
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, Note.Status.REJECTED)

        self.client.force_login(self.author)
        appeal_resp = self.client.post(
            reverse("notes:appeal", args=[self.note.pk]),
            data={"message": "All diagrams and equations have been supplemented with derivations."},
            follow=True,
        )
        self.assertEqual(appeal_resp.status_code, 200)

        appeal = NoteAppeal.objects.get(note=self.note, user=self.author)
        self.assertEqual(appeal.status, NoteAppeal.Status.OPEN)

        # 4. Teacher grants appeal -> Restores and approves note
        self.client.force_login(self.teacher)
        grant_resp = self.client.post(
            reverse("notes:appeal_action", args=[appeal.pk]),
            data={"action": "grant"},
            follow=True,
        )
        self.assertEqual(grant_resp.status_code, 200)

        appeal.refresh_from_db()
        self.note.refresh_from_db()
        self.assertEqual(appeal.status, NoteAppeal.Status.GRANTED)
        self.assertEqual(self.note.status, Note.Status.APPROVED)


class SkillSwapDepositStateMachineScenarioTest(TestCase):
    """Scenario 4: Swap post, booking, deposit hold, meeting link, completion, and no-show forfeit."""

    def setUp(self):
        self.teacher = make_student(username="swap_teacher")
        self.learner = make_student(username="swap_learner")
        add_entry(self.teacher, 50, CreditLedger.Reason.SIGNUP_BONUS, "Deposit funds")
        add_entry(self.learner, 50, CreditLedger.Reason.SIGNUP_BONUS, "Deposit funds")

        self.post = SkillPost.objects.create(
            user=self.teacher,
            kind=SkillPost.Kind.OFFER,
            skill_name="Full Stack Python",
            description="Mentoring in Django and React",
        )
        self.client = Client()

    def test_happy_path_swap_completion_returns_both_deposits(self):
        # 1. Learner requests session
        session = request_session(self.post, self.learner)
        self.assertEqual(session.status, SwapSession.Status.REQUESTED)
        # Deposits not held yet in REQUESTED state
        self.assertEqual(get_balance(self.teacher), 50)
        self.assertEqual(get_balance(self.learner), 50)

        # 2. Teacher accepts and proposes time
        proposed_dt = timezone.now() + timedelta(days=2)
        accept_and_propose_time(session, self.teacher, proposed_dt)
        session.refresh_from_db()
        self.assertEqual(session.status, SwapSession.Status.ACCEPTED)

        # 3. Learner confirms time -> transitions to SCHEDULED, holds 10 nuts each
        confirm_time(session, self.learner)
        session.refresh_from_db()
        self.assertEqual(session.status, SwapSession.Status.SCHEDULED)
        self.assertEqual(get_balance(self.teacher), 40)
        self.assertEqual(get_balance(self.learner), 40)

        # 4. Teacher sets valid Google Meet link
        set_meeting_link(session, self.teacher, "https://meet.google.com/xyz-uvwx-rst")
        session.refresh_from_db()
        self.assertEqual(session.meeting_link, "https://meet.google.com/xyz-uvwx-rst")

        # 5. Simulate session time having arrived and both report outcome as completed
        SwapSession.objects.filter(pk=session.pk).update(proposed_time=timezone.now() - timedelta(minutes=10))
        session.refresh_from_db()

        report_outcome(session, self.teacher, SwapSession.Outcome.COMPLETED)
        report_outcome(session, self.learner, SwapSession.Outcome.COMPLETED)

        session.refresh_from_db()
        self.assertEqual(session.status, SwapSession.Status.COMPLETED)

        # Deposits returned (+10 nuts each)
        self.assertEqual(get_balance(self.teacher), 50)
        self.assertEqual(get_balance(self.learner), 50)

        # 6. Both rate session
        rate_session(session, self.learner, 5, "Brilliant mentor!")
        rate_session(session, self.teacher, 5, "Fast learner!")
        self.assertEqual(SessionRating.objects.filter(session=session).count(), 2)

    def test_noshow_forfeits_guilty_party_deposit(self):
        # Request, accept, confirm session
        session = request_session(self.post, self.learner)
        proposed_dt = timezone.now() + timedelta(days=1)
        accept_and_propose_time(session, self.teacher, proposed_dt)
        confirm_time(session, self.learner)
        set_meeting_link(session, self.teacher, "https://meet.google.com/xyz-uvwx-rst")

        self.assertEqual(get_balance(self.teacher), 40)
        self.assertEqual(get_balance(self.learner), 40)

        # Simulate session time arrived and 25h passed without teacher reporting
        now = timezone.now()
        SwapSession.objects.filter(pk=session.pk).update(
            proposed_time=now - timedelta(hours=26),
            learner_outcome=SwapSession.Outcome.NO_SHOW,
            learner_outcome_at=now - timedelta(hours=25),
        )
        session.refresh_from_db()
        resolve_all_swaps()

        session.refresh_from_db()
        self.assertEqual(session.status, SwapSession.Status.NO_SHOW)
        # Teacher deposit forfeited (balance remains 40)
        self.assertEqual(get_balance(self.teacher), 40)
        # Learner received deposit return (10) + forfeit compensation (10) = 40 + 20 = 60
        self.assertEqual(get_balance(self.learner), 60)


@override_settings(SANDBOX_ALLOWED=True)
class CreditPurchaseViaSandboxScenarioTest(TestCase):
    """Scenario 5: Credit purchase via sandbox payment gateway."""

    def setUp(self):
        self.user = make_student(username="buyer_sandbox")
        self.client = Client()
        self.client.force_login(self.user)

    def test_credit_topup_via_sandbox_flow(self):
        self.assertEqual(get_balance(self.user), 0)

        # 1. User posts credit purchase request (100 nuts = 100 BDT)
        resp = self.client.post(
            reverse("payments:buy_credits"),
            data={"nuts": "100"},
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)

        order = PaymentOrder.objects.filter(user=self.user).first()
        self.assertIsNotNone(order)
        self.assertEqual(order.purpose, PaymentOrder.Purpose.CREDIT_TOPUP)
        self.assertEqual(order.amount_bdt, Decimal("100.00"))
        self.assertEqual(order.status, PaymentOrder.Status.CREATED)

        # 2. Redirected to sandbox view
        sandbox_url = reverse("payments:sandbox", args=[order.id])
        self.assertEqual(resp.url, sandbox_url)

        # 3. User clicks 'Pay' in sandbox
        sandbox_resp = self.client.post(
            sandbox_url,
            data={"action": "pay", "order_id": str(order.id)},
            follow=True,
        )
        self.assertEqual(sandbox_resp.status_code, 200)

        # 4. Order is marked PAID and fulfiller delivers 100 nuts to user
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PAID)
        self.assertIsNotNone(order.paid_at)

        self.assertEqual(get_balance(self.user), 100)
        ledger_entry = CreditLedger.objects.filter(
            user=self.user,
            reason=CreditLedger.Reason.PURCHASE,
        ).first()
        self.assertIsNotNone(ledger_entry)
        self.assertEqual(ledger_entry.amount, 100)


@override_settings(ENABLE_VIDEO_COURSES=True, WITHDRAW_MIN_BDT=Decimal("40.00"))
class VideoCoursesPurchaseStreamingAndPayoutScenarioTest(TestCase):
    """Scenario 6: Course creation, lesson upload, purchase, HTTP range streaming, and withdrawal."""

    def setUp(self):
        PricingRule.objects.get_or_create(
            category=Course.Category.ACADEMIC,
            defaults={"min_per_hour": Decimal("50.00"), "max_per_hour": Decimal("150.00")},
        )
        self.lecturer = make_lecturer(username="prof_course_author")
        self.student = make_student(username="student_enrolled")
        self.intruder = make_student(username="student_not_enrolled")

        self.client = Client()

    def test_full_course_and_payout_lifecycle(self):
        # 1. Lecturer creates course
        self.client.force_login(self.lecturer)
        create_resp = self.client.post(
            reverse("courses:course_create"),
            data={
                "title": "Full Stack Web Architecture",
                "description": "Comprehensive course on web engineering and scale.",
                "category": Course.Category.ACADEMIC,
                "price": "50.00",
                "status": Course.Status.DRAFT,
            },
            follow=True,
        )
        self.assertEqual(create_resp.status_code, 200)
        course = Course.objects.get(title="Full Stack Web Architecture")
        self.assertEqual(course.status, Course.Status.DRAFT)

        # 2. Upload Lesson 1 (Free Preview) and Lesson 2 (Paid)
        lesson1 = Lesson.objects.create(
            course=course,
            title="Lesson 1: Introduction",
            order=1,
            is_free_preview=True,
            duration_seconds=300,
            video_file=sample_mp4_file("lesson1.mp4"),
        )
        lesson2 = Lesson.objects.create(
            course=course,
            title="Lesson 2: Advanced Backend Architecture",
            order=2,
            is_free_preview=False,
            duration_seconds=600,
            video_file=sample_mp4_file("lesson2.mp4"),
        )
        course.total_duration_seconds = 900
        course.save()

        # 3. Publish course
        pub_resp = self.client.post(reverse("courses:course_publish_toggle", args=[course.pk]), follow=True)
        self.assertEqual(pub_resp.status_code, 200)
        course.refresh_from_db()
        self.assertEqual(course.status, Course.Status.PUBLISHED)

        # 4. Student purchases course
        self.client.force_login(self.student)
        buy_resp = self.client.post(reverse("courses:course_buy", args=[course.pk]), follow=False)
        self.assertEqual(buy_resp.status_code, 302)

        order = PaymentOrder.objects.filter(user=self.student, purpose=PaymentOrder.Purpose.COURSE).first()
        self.assertIsNotNone(order)

        # Complete payment in sandbox
        sandbox_resp = self.client.post(
            reverse("payments:sandbox", args=[order.id]),
            data={"action": "pay", "order_id": str(order.id)},
            follow=True,
        )
        self.assertEqual(sandbox_resp.status_code, 200)

        self.assertTrue(CoursePurchase.objects.filter(user=self.student, course=course, is_successful=True).exists())

        # Instructor wallet received 90% share (90% of 50.00 = 45.00 BDT)
        instructor_balance = get_wallet_balance(self.lecturer)
        self.assertEqual(instructor_balance, Decimal("45.00"))

        # 5. Enrolled student streams Lesson 2 using HTTP Range
        stream_url = reverse("courses:lesson_stream", args=[lesson2.pk])
        range_resp = self.client.get(stream_url, HTTP_RANGE="bytes=0-99")
        self.assertEqual(range_resp.status_code, 206)
        self.assertIn("Content-Range", range_resp.headers)
        self.assertTrue(range_resp.headers["Content-Range"].startswith("bytes 0-99/"))
        self.assertEqual(range_resp.headers.get("Accept-Ranges"), "bytes")
        content_bytes = b"".join(range_resp.streaming_content)
        self.assertEqual(len(content_bytes), 100)

        # 6. Unenrolled student tries to stream Lesson 2 -> 403 Forbidden
        self.client.force_login(self.intruder)
        intruder_resp = self.client.get(stream_url)
        self.assertEqual(intruder_resp.status_code, 403)

        # Unenrolled student CAN stream Lesson 1 (Free preview)
        stream_l1_url = reverse("courses:lesson_stream", args=[lesson1.pk])
        preview_resp = self.client.get(stream_l1_url, HTTP_RANGE="bytes=0-50")
        self.assertEqual(preview_resp.status_code, 206)

        # 7. Lecturer requests cash withdrawal from wallet
        self.client.force_login(self.lecturer)
        withdraw_resp = self.client.post(
            reverse("payments:withdrawals"),
            data={
                "amount": "40.00",
                "method": WithdrawalRequest.Method.BKASH,
                "account_details": "01700000000",
            },
            follow=True,
        )
        self.assertEqual(withdraw_resp.status_code, 200)

        withdrawal = WithdrawalRequest.objects.filter(user=self.lecturer).first()
        self.assertIsNotNone(withdrawal)
        self.assertEqual(withdrawal.amount, Decimal("40.00"))
        self.assertEqual(withdrawal.status, WithdrawalRequest.Status.PENDING)
        # Remaining wallet balance is 45.00 - 40.00 = 5.00 BDT
        self.assertEqual(get_wallet_balance(self.lecturer), Decimal("5.00"))
