import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from campus.models import Batch, BatchMembership, Department
from core.testing import make_department, make_batch, make_student, make_lecturer, make_note
from courses.models import Course, Lesson, CoursePurchase
from notes.models import Note, NoteAppeal, NoteReport
from payments.models import PaymentOrder, WalletEntry, WithdrawalRequest
from payments.services import create_order
from swaps.models import SkillPost, SwapSession


def sample_pdf():
    return SimpleUploadedFile("test.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")


def sample_mp4():
    mp4_path = os.path.join(settings.BASE_DIR, "static", "images", "video.mp4")
    with open(mp4_path, "rb") as f:
        data = f.read()
    return SimpleUploadedFile("test.mp4", data, content_type="video/mp4")


class IDORPermissionMatrixTests(TestCase):
    """
    PRD 8.1: Object-level permission test matrix covering every ID-based URL (IDOR):
    - note detail
    - note preview
    - note download
    - note review
    - note appeal
    - note flagged
    - swap session detail
    - swap session link
    - lesson stream
    - payment order detail
    - payment sandbox
    - withdrawal requests isolation
    """

    def setUp(self):
        # Departments & Batches
        self.dept_a = make_department(code="CSE_A")
        self.dept_b = make_department(code="EEE_B")

        self.batch_a = make_batch(department=self.dept_a, name="Batch A")
        self.batch_b = make_batch(department=self.dept_b, name="Batch B")

        # Class teachers
        self.teacher_a = make_lecturer(username="teacher_a")
        self.batch_a.class_teacher = self.teacher_a
        self.batch_a.save()

        self.teacher_b = make_lecturer(username="teacher_b")
        self.batch_b.class_teacher = self.teacher_b
        self.batch_b.save()

        # Students & CRs
        self.student_a = make_student(batch=self.batch_a, username="student_a")
        self.cr_a = make_student(batch=self.batch_a, cr=True, username="cr_a")

        self.student_b = make_student(batch=self.batch_b, username="student_b_stranger")
        self.cr_b = make_student(batch=self.batch_b, cr=True, username="cr_b")

        # Notes in Batch A
        self.batch_private_note = make_note(
            owner=self.student_a,
            department=self.dept_a,
            batch=self.batch_a,
            title="Batch A Secrets",
            course_code="CSE101",
            visibility=Note.Visibility.BATCH,
            status=Note.Status.APPROVED,
        )

        self.pending_note = make_note(
            owner=self.student_a,
            department=self.dept_a,
            batch=self.batch_a,
            title="Pending Note",
            course_code="CSE102",
            visibility=Note.Visibility.PUBLIC,
            status=Note.Status.PENDING,
        )

        self.flagged_note = make_note(
            owner=self.student_a,
            department=self.dept_a,
            batch=self.batch_a,
            title="Flagged Note",
            course_code="CSE103",
            visibility=Note.Visibility.PUBLIC,
            status=Note.Status.FLAGGED,
        )

        self.appeal = NoteAppeal.objects.create(
            note=self.flagged_note,
            user=self.student_a,
            message="Unfair flagging",
            status=NoteAppeal.Status.OPEN,
        )

        # Swap Session between student_a and teacher_a
        self.swap_post = SkillPost.objects.create(
            user=self.student_a,
            kind=SkillPost.Kind.OFFER,
            skill_name="Python",
        )
        self.swap_session = SwapSession.objects.create(
            post=self.swap_post,
            teacher=self.student_a,
            learner=self.teacher_a,
            skill_name="Python",
            status=SwapSession.Status.SCHEDULED,
            proposed_time=timezone.now() + timezone.timedelta(days=2),
            meeting_link="https://meet.google.com/abc-defg-hij",
        )

        # Course & Lesson by teacher_a
        self.course = Course.objects.create(
            instructor=self.teacher_a,
            title="Secure Python Course",
            category=Course.Category.ACADEMIC,
            price=Decimal("50.00"),
            status=Course.Status.PUBLISHED,
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            title="Lesson 1",
            order=1,
            video_file=sample_mp4(),
            duration_seconds=10,
            is_free_preview=False,
        )

        # Payment Order for student_a
        self.order = create_order(
            user=self.student_a,
            purpose=PaymentOrder.Purpose.CREDIT_TOPUP,
            amount_bdt=Decimal("50.00"),
        )

        # Withdrawal Request for teacher_a
        self.withdrawal = WithdrawalRequest.objects.create(
            user=self.teacher_a,
            amount=Decimal("500.00"),
            method=WithdrawalRequest.Method.BKASH,
            account_details="01700000000",
            status=WithdrawalRequest.Status.PENDING,
        )

        self.client = Client()

    # 1. Note Detail IDOR
    def test_note_batch_private_idor(self):
        """Student from batch B cannot view Batch A private note."""
        self.client.force_login(self.student_b)
        resp = self.client.get(reverse("notes:detail", args=[self.batch_private_note.id]))
        self.assertIn(resp.status_code, [403, 404])

    # 2. Note Preview IDOR
    def test_note_preview_idor(self):
        """Stranger cannot preview batch private note."""
        self.client.force_login(self.student_b)
        resp = self.client.get(reverse("notes:preview", args=[self.batch_private_note.id]))
        self.assertIn(resp.status_code, [403, 404])

    # 3. Note Download & File IDOR
    def test_note_download_idor(self):
        """Stranger cannot download batch private note."""
        self.client.force_login(self.student_b)
        resp = self.client.post(reverse("notes:download", args=[self.batch_private_note.id]))
        self.assertIn(resp.status_code, [403, 404])

    def test_note_file_idor(self):
        """Stranger cannot directly stream/read private file."""
        self.client.force_login(self.student_b)
        resp = self.client.get(reverse("notes:file", args=[self.batch_private_note.id]))
        self.assertIn(resp.status_code, [403, 404])

    # 4. Note Review IDOR
    def test_note_review_idor(self):
        """CR from batch B cannot access review page of Batch A note."""
        self.client.force_login(self.cr_b)
        resp = self.client.get(reverse("notes:review_detail", args=[self.pending_note.id]))
        self.assertIn(resp.status_code, [403, 404])

    # 5. Note Appeal IDOR
    def test_note_appeal_idor(self):
        """Teacher from batch B cannot decide appeal of Batch A note."""
        self.client.force_login(self.teacher_b)
        resp = self.client.post(
            reverse("notes:appeal_action", args=[self.appeal.id]),
            {"action": "grant"},
        )
        self.assertIn(resp.status_code, [403, 404])

    # 6. Flagged Note IDOR
    def test_flagged_note_idor(self):
        """Teacher from batch B cannot decide Batch A flagged note."""
        self.client.force_login(self.teacher_b)
        resp = self.client.post(
            reverse("notes:flagged_action", args=[self.flagged_note.id]),
            {"action": "dismiss"},
        )
        self.assertIn(resp.status_code, [403, 404])

    # 7. Swap Session Detail & Meeting Link IDOR
    def test_swap_session_detail_idor(self):
        """Third-party user cannot view swap session details or link."""
        self.client.force_login(self.student_b)
        resp = self.client.get(reverse("swaps:session_detail", args=[self.swap_session.id]))
        self.assertEqual(resp.status_code, 403)

    def test_swap_session_meeting_link_idor(self):
        """Non-teacher cannot set or edit meeting link."""
        self.client.force_login(self.student_b)
        resp = self.client.post(
            reverse("swaps:session_set_link", args=[self.swap_session.id]),
            {"meeting_link": "https://meet.google.com/hacker-link"},
        )
        self.assertEqual(resp.status_code, 403)

    # 8. Lesson Stream IDOR
    def test_lesson_stream_idor(self):
        """Non-buyer student B cannot stream paid lesson."""
        self.client.force_login(self.student_b)
        resp = self.client.get(reverse("courses:lesson_stream", args=[self.lesson.id]))
        self.assertEqual(resp.status_code, 403)

    # 9. Payment Order Detail & Sandbox IDOR
    def test_payment_order_detail_idor(self):
        """Student B cannot view student A's payment order."""
        self.client.force_login(self.student_b)
        resp = self.client.get(reverse("payments:order_detail", args=[self.order.id]))
        self.assertEqual(resp.status_code, 403)

    def test_payment_sandbox_idor(self):
        """Student B cannot view or complete student A's sandbox order."""
        self.client.force_login(self.student_b)
        resp = self.client.get(reverse("payments:sandbox", args=[self.order.id]))
        self.assertEqual(resp.status_code, 403)
        post_resp = self.client.post(
            reverse("payments:sandbox", args=[self.order.id]),
            {"action": "pay"},
        )
        self.assertEqual(post_resp.status_code, 403)

    # 10. Withdrawal Request Isolation
    def test_withdrawal_request_isolation(self):
        """Student A cannot see Teacher A's withdrawal requests."""
        self.client.force_login(self.student_a)
        resp = self.client.get(reverse("payments:withdrawals"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "01700000000")

