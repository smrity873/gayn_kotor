from datetime import timedelta
from unittest.mock import patch
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from credits.models import CreditLedger
from credits.services import add_entry, get_balance
from notes.forms import NoteForm
from notes.models import Note, NoteDownload, NoteRating, validate_pdf_header
from notes.services import (
    approve_note,
    can_view_note,
    publish_overdue_notes,
    visible_notes,
)
from notifications.models import Notification
from core.testing import (
    give_credits,
    make_batch,
    make_department,
    make_lecturer,
    make_note,
    make_student,
    sample_pdf_file,
)


class CreditServicesTests(TestCase):
    def setUp(self):
        self.user = make_student()

    def test_get_balance_empty(self):
        self.assertEqual(get_balance(self.user), 0)

    def test_add_entry_positive(self):
        entry = add_entry(self.user, 25, CreditLedger.Reason.SIGNUP_BONUS, "Bonus")
        self.assertEqual(entry.amount, 25)
        self.assertEqual(get_balance(self.user), 25)

    def test_add_entry_insufficient_funds(self):
        give_credits(self.user, 10)
        with self.assertRaises(ValueError) as ctx:
            add_entry(self.user, -15, CreditLedger.Reason.NOTE_DOWNLOAD)
        self.assertIn("Not enough credits", str(ctx.exception))
        self.assertEqual(get_balance(self.user), 10)

    def test_add_entry_atomicity_on_failure(self):
        give_credits(self.user, 20)
        try:
            with transaction.atomic():
                add_entry(self.user, 10, CreditLedger.Reason.ADMIN, "Temp")
                raise RuntimeError("Simulated failure")
        except RuntimeError:
            pass
        self.assertEqual(get_balance(self.user), 20)

    def test_add_entry_allow_negative(self):
        give_credits(self.user, 5)
        entry = add_entry(self.user, -20, CreditLedger.Reason.ADMIN, "Adjustment", allow_negative=True)
        self.assertEqual(entry.amount, -20)
        self.assertEqual(get_balance(self.user), -15)


class NotesReviewAndUploadTests(TestCase):
    def setUp(self):
        self.dept = make_department(name="Computer Science", code="CS")
        self.teacher = make_lecturer(username="prof_smith")
        self.batch = make_batch(department=self.dept, class_teacher=self.teacher)
        self.student = make_student(batch=self.batch)
        self.cr = make_student(batch=self.batch, cr=True)
        self.client = Client()

    def test_upload_then_approve_pays_reward_exactly_once(self):
        note = make_note(owner=self.student, batch=self.batch, department=self.dept, status=Note.Status.PENDING)
        initial_balance = get_balance(self.student)

        # First approval
        paid = approve_note(note, reviewer=self.cr)
        self.assertTrue(paid)
        self.assertEqual(get_balance(self.student), initial_balance + 10)
        note.refresh_from_db()
        self.assertEqual(note.status, Note.Status.APPROVED)
        self.assertTrue(note.reward_paid)

        # Second approval attempt directly
        paid_again = approve_note(note, reviewer=self.cr)
        self.assertFalse(paid_again)
        self.assertEqual(get_balance(self.student), initial_balance + 10)

    def test_concurrent_double_approve_rejected_via_view(self):
        note = make_note(owner=self.student, batch=self.batch, department=self.dept, status=Note.Status.PENDING)
        initial_balance = get_balance(self.student)

        self.client.force_login(self.cr)
        # First reviewer approves via POST review_action
        url = reverse("notes:review_action", args=[note.pk])
        resp1 = self.client.post(url, {"action": "approve"})
        self.assertEqual(resp1.status_code, 302)
        self.assertEqual(get_balance(self.student), initial_balance + 10)

        # Second reviewer (teacher or another CR) tries to decide the same note
        self.client.force_login(self.teacher)
        resp2 = self.client.post(url, {"action": "approve"}, follow=True)
        self.assertEqual(resp2.status_code, 200)
        # Verify info message that note was already decided
        messages = [m.message for m in resp2.context["messages"]]
        self.assertTrue(any("already decided" in m.lower() for m in messages))
        # Credits paid only once
        self.assertEqual(get_balance(self.student), initial_balance + 10)

    def test_lecturer_upload_auto_publishes(self):
        self.client.force_login(self.teacher)
        pdf = sample_pdf_file("lecture.pdf")
        initial_balance = get_balance(self.teacher)
        resp = self.client.post(
            reverse("notes:upload"),
            {
                "title": "Algorithms 101",
                "course_code": "CS101",
                "department": self.dept.pk,
                "semester": 1,
                "visibility": Note.Visibility.PUBLIC,
                "file": pdf,
            },
        )
        self.assertEqual(resp.status_code, 302)
        note = Note.objects.get(title="Algorithms 101")
        self.assertEqual(note.status, Note.Status.APPROVED)
        self.assertTrue(note.reward_paid)
        self.assertEqual(get_balance(self.teacher), initial_balance + 10)

    def test_validate_pdf_header_rejects_non_pdf(self):
        non_pdf = sample_pdf_file("fake.pdf", content=b"NOT_A_PDF_FILE_HEADER")
        with self.assertRaises(ValidationError) as ctx:
            validate_pdf_header(non_pdf)
        self.assertIn("Invalid PDF file", str(ctx.exception))

    def test_note_form_validation_rejects_fake_pdf(self):
        non_pdf = sample_pdf_file("fake.pdf", content=b"MZ_DOS_HEADER_FAKE_DATA")
        form = NoteForm(
            data={
                "title": "Bad File",
                "course_code": "CS101",
                "department": self.dept.pk,
                "semester": 1,
                "visibility": Note.Visibility.PUBLIC,
            },
            files={"file": non_pdf},
            user=self.student,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)


class NotesDownloadTests(TestCase):
    def setUp(self):
        self.dept = make_department()
        self.batch = make_batch(department=self.dept)
        self.owner = make_student(batch=self.batch)
        self.downloader = make_student(batch=self.batch)
        self.note = make_note(owner=self.owner, batch=self.batch, department=self.dept, status=Note.Status.APPROVED)
        self.client = Client()

    def test_download_deducts_once_and_is_idempotent(self):
        give_credits(self.downloader, 10)
        self.client.force_login(self.downloader)

        url = reverse("notes:download", args=[self.note.pk])
        # First download: deducts 5 credits
        resp1 = self.client.post(url)
        self.assertEqual(resp1.status_code, 302)
        self.assertEqual(get_balance(self.downloader), 5)
        self.assertTrue(NoteDownload.objects.filter(user=self.downloader, note=self.note).exists())
        self.note.refresh_from_db()
        self.assertEqual(self.note.download_count, 1)

        # Second download: does not deduct again
        resp2 = self.client.post(url)
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(get_balance(self.downloader), 5)
        self.note.refresh_from_db()
        self.assertEqual(self.note.download_count, 1)

    def test_download_insufficient_credits_blocked(self):
        give_credits(self.downloader, 2)
        self.client.force_login(self.downloader)
        resp = self.client.post(reverse("notes:download", args=[self.note.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_balance(self.downloader), 2)
        self.assertFalse(NoteDownload.objects.filter(user=self.downloader, note=self.note).exists())

    def test_owner_and_superuser_download_free(self):
        self.client.force_login(self.owner)
        initial_balance = get_balance(self.owner)
        resp = self.client.post(reverse("notes:download", args=[self.note.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(get_balance(self.owner), initial_balance)
        self.assertFalse(NoteDownload.objects.filter(user=self.owner, note=self.note).exists())


class NotesRatingTests(TestCase):
    def setUp(self):
        self.dept = make_department()
        self.batch = make_batch(department=self.dept)
        self.owner = make_student(batch=self.batch)
        self.rater = make_student(batch=self.batch)
        self.note = make_note(owner=self.owner, batch=self.batch, department=self.dept, status=Note.Status.APPROVED)
        self.client = Client()

    def test_rate_own_file_rejected(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse("notes:rate", args=[self.note.pk]), {"rating": 5}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(NoteRating.objects.filter(user=self.owner, note=self.note).exists())

    def test_rate_before_download_rejected(self):
        self.client.force_login(self.rater)
        resp = self.client.post(reverse("notes:rate", args=[self.note.pk]), {"rating": 5}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(NoteRating.objects.filter(user=self.rater, note=self.note).exists())

    def test_rate_happy_path_and_duplicate_rejected(self):
        give_credits(self.rater, 10)
        self.client.force_login(self.rater)
        # Unlock first
        self.client.post(reverse("notes:download", args=[self.note.pk]))

        rater_bal = get_balance(self.rater)
        owner_bal = get_balance(self.owner)

        # Rate note
        resp = self.client.post(reverse("notes:rate", args=[self.note.pk]), {"rating": 5, "review": "Great!"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(get_balance(self.rater), rater_bal + 1)
        self.assertEqual(get_balance(self.owner), owner_bal + 5)
        self.assertTrue(NoteRating.objects.filter(user=self.rater, note=self.note).exists())

        # Second rating attempt on same note
        resp2 = self.client.post(reverse("notes:rate", args=[self.note.pk]), {"rating": 4}, follow=True)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(get_balance(self.rater), rater_bal + 1)
        self.assertEqual(get_balance(self.owner), owner_bal + 5)

    def test_rate_daily_cap(self):
        give_credits(self.rater, 100)
        self.client.force_login(self.rater)

        # Simulate reaching daily cap of 5 ratings
        for i in range(5):
            CreditLedger.objects.create(
                user=self.rater,
                amount=1,
                reason=CreditLedger.Reason.RATING_GIVEN,
                description=f"Fake rating {i}",
            )
        NoteDownload.objects.create(user=self.rater, note=self.note)

        bal_before = get_balance(self.rater)
        self.client.post(reverse("notes:rate", args=[self.note.pk]), {"rating": 5})
        self.assertEqual(get_balance(self.rater), bal_before)  # Rater not rewarded beyond cap


class NotesVisibilityTests(TestCase):
    def setUp(self):
        self.dept_a = make_department(name="Dept A", code="DA")
        self.dept_b = make_department(name="Dept B", code="DB")
        self.batch_a1 = make_batch(department=self.dept_a, name="A1")
        self.batch_a2 = make_batch(department=self.dept_a, name="A2")
        self.batch_b1 = make_batch(department=self.dept_b, name="B1")

        self.student_a1 = make_student(batch=self.batch_a1)
        self.student_a2 = make_student(batch=self.batch_a2)
        self.student_b1 = make_student(batch=self.batch_b1)
        self.lecturer = make_lecturer()
        self.client = Client()

    def test_visibility_matrix(self):
        n_public = make_note(owner=self.student_a1, batch=self.batch_a1, department=self.dept_a, visibility=Note.Visibility.PUBLIC, status=Note.Status.APPROVED)
        n_dept = make_note(owner=self.student_a1, batch=self.batch_a1, department=self.dept_a, visibility=Note.Visibility.DEPARTMENT, status=Note.Status.APPROVED)
        n_batch = make_note(owner=self.student_a1, batch=self.batch_a1, department=self.dept_a, visibility=Note.Visibility.BATCH, status=Note.Status.APPROVED)
        n_pending = make_note(owner=self.student_a1, batch=self.batch_a1, department=self.dept_a, visibility=Note.Visibility.PUBLIC, status=Note.Status.PENDING)

        # Student A1 (owner): sees all four
        self.assertTrue(can_view_note(self.student_a1, n_public))
        self.assertTrue(can_view_note(self.student_a1, n_dept))
        self.assertTrue(can_view_note(self.student_a1, n_batch))
        self.assertTrue(can_view_note(self.student_a1, n_pending))

        # Student A2 (same dept, different batch): sees public & dept, but not batch or pending
        self.assertTrue(can_view_note(self.student_a2, n_public))
        self.assertTrue(can_view_note(self.student_a2, n_dept))
        self.assertFalse(can_view_note(self.student_a2, n_batch))
        self.assertFalse(can_view_note(self.student_a2, n_pending))

        # Student B1 (different dept): sees public only
        self.assertTrue(can_view_note(self.student_b1, n_public))
        self.assertFalse(can_view_note(self.student_b1, n_dept))
        self.assertFalse(can_view_note(self.student_b1, n_batch))
        self.assertFalse(can_view_note(self.student_b1, n_pending))

        # Lecturer: sees all approved/unverified notes
        self.assertTrue(can_view_note(self.lecturer, n_public))
        self.assertTrue(can_view_note(self.lecturer, n_dept))
        self.assertTrue(can_view_note(self.lecturer, n_batch))

    def test_note_file_removed_status_returns_404(self):
        note = make_note(owner=self.student_a1, batch=self.batch_a1, department=self.dept_a, status=Note.Status.REMOVED)
        NoteDownload.objects.create(user=self.student_a2, note=note)

        # Regular user who previously unlocked note gets 404
        self.client.force_login(self.student_a2)
        resp = self.client.get(reverse("notes:file", args=[note.pk]))
        self.assertEqual(resp.status_code, 404)

        # Owner still has access
        self.client.force_login(self.student_a1)
        resp_owner = self.client.get(reverse("notes:file", args=[note.pk]))
        self.assertEqual(resp_owner.status_code, 200)


class OverdueNotesTests(TestCase):
    def setUp(self):
        self.dept = make_department()
        self.student = make_student()

    def test_publish_overdue_notes(self):
        # Note older than 7 days
        old_note = make_note(owner=self.student, department=self.dept, status=Note.Status.PENDING)
        # Note created recently
        recent_note = make_note(owner=self.student, department=self.dept, status=Note.Status.PENDING)

        # Backdate old_note to 8 days ago
        Note.objects.filter(pk=old_note.pk).update(created_at=timezone.now() - timedelta(days=8))

        count = publish_overdue_notes()
        self.assertEqual(count, 1)

        old_note.refresh_from_db()
        recent_note.refresh_from_db()
        self.assertEqual(old_note.status, Note.Status.UNVERIFIED)
        self.assertEqual(recent_note.status, Note.Status.PENDING)

        # Idempotent call
        count_again = publish_overdue_notes()
        self.assertEqual(count_again, 0)


class NotificationEndpointTests(TestCase):
    def setUp(self):
        self.user_a = make_student()
        self.user_b = make_student()
        self.client = Client()

    def test_notification_summary_isolated_by_user(self):
        Notification.objects.create(user=self.user_a, message="Hello A", link="/")
        Notification.objects.create(user=self.user_b, message="Hello B", link="/")

        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("notifications:summary"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["unread"], 1)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["message"], "Hello A")

    def test_open_notification_marks_read_and_safe_redirect(self):
        n = Notification.objects.create(user=self.user_a, message="Note ready", link="/notes/")
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("notifications:open", args=[n.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/notes/")
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_open_other_user_notification_returns_404(self):
        n = Notification.objects.create(user=self.user_b, message="Secret B", link="/")
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("notifications:open", args=[n.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_open_notification_open_redirect_protection(self):
        # External URL must be sanitized to "/"
        n = Notification.objects.create(user=self.user_a, message="Phishing", link="https://evil.com/steal")
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("notifications:open", args=[n.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/")


class PrivateStorageProtectionTests(TestCase):
    def test_note_pdf_stored_in_private_storage_not_media(self):
        dept = make_department()
        student = make_student()
        note = make_note(owner=student, department=dept)
        
        # File must be inside PRIVATE_MEDIA_ROOT
        self.assertTrue(str(note.file.path).startswith(str(settings.PRIVATE_MEDIA_ROOT)))
        # File must NOT be inside MEDIA_ROOT
        self.assertFalse(str(note.file.path).startswith(str(settings.MEDIA_ROOT)))
