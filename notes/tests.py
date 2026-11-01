from datetime import timedelta
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from campus.models import Batch, BatchMembership
from core.testing import (
    give_credits,
    make_batch,
    make_department,
    make_lecturer,
    make_note,
    make_student,
)
from credits.models import CreditLedger
from credits.services import get_balance
from notes.models import Note, NoteAppeal, NoteDownload, NoteRating, NoteReport
from notes.services import (
    approve_note,
    can_view_note,
    process_review_deadlines,
    reject_note,
    remove_note,
)
from notifications.models import Notification


class ReviewDeadlineEngineTests(TestCase):
    def setUp(self):
        self.dept = make_department(name="Computer Science", code="CSE")
        self.teacher = make_lecturer(username="teacher_review")
        self.batch = make_batch(department=self.dept, class_teacher=self.teacher)
        self.cr = make_student(batch=self.batch, cr=True, username="cr_user")
        self.student = make_student(batch=self.batch, cr=False, username="author_user")

        self.t0 = timezone.now() - timedelta(days=10)
        self.note = make_note(
            owner=self.student,
            batch=self.batch,
            department=self.dept,
            status=Note.Status.PENDING,
        )
        # Fix created_at to t0
        Note.objects.filter(pk=self.note.pk).update(created_at=self.t0)
        self.note.refresh_from_db()

    def test_deadline_timeline_and_idempotency(self):
        # Day 1: No reminders
        Notification.objects.all().delete()
        now_d1 = self.t0 + timedelta(days=1)
        actions = process_review_deadlines(now=now_d1)
        self.assertEqual(actions, 0)
        self.assertEqual(Notification.objects.count(), 0)

        # Day 2: CR reminded once
        now_d2 = self.t0 + timedelta(days=2, hours=1)
        actions = process_review_deadlines(now=now_d2)
        self.assertEqual(actions, 1)
        self.note.refresh_from_db()
        self.assertIsNotNone(self.note.cr_reminded_at)
        self.assertIsNone(self.note.escalated_at)
        self.assertTrue(Notification.objects.filter(user=self.cr).exists())
        self.assertFalse(Notification.objects.filter(user=self.teacher).exists())
        cr_notifs_count = Notification.objects.filter(user=self.cr).count()

        # Running engine again on Day 2 produces 0 duplicates
        actions_dup = process_review_deadlines(now=now_d2)
        self.assertEqual(actions_dup, 0)
        self.assertEqual(Notification.objects.filter(user=self.cr).count(), cr_notifs_count)

        # Day 3: Escalated to class teacher
        now_d3 = self.t0 + timedelta(days=3, hours=1)
        actions_d3 = process_review_deadlines(now=now_d3)
        self.assertEqual(actions_d3, 1)
        self.note.refresh_from_db()
        self.assertIsNotNone(self.note.escalated_at)
        self.assertTrue(Notification.objects.filter(user=self.teacher).exists())
        teacher_notifs_count = Notification.objects.filter(user=self.teacher).count()

        # Running again on Day 3 produces 0 duplicates
        actions_d3_dup = process_review_deadlines(now=now_d3)
        self.assertEqual(actions_d3_dup, 0)
        self.assertEqual(Notification.objects.filter(user=self.teacher).count(), teacher_notifs_count)

        # Day 4: Daily reminder to class teacher
        now_d4 = self.t0 + timedelta(days=4, hours=2)
        actions_d4 = process_review_deadlines(now=now_d4)
        self.assertEqual(actions_d4, 1)
        self.assertEqual(Notification.objects.filter(user=self.teacher).count(), teacher_notifs_count + 1)
        teacher_notifs_count += 1

        # Running again on Day 4 produces 0 duplicates
        actions_d4_dup = process_review_deadlines(now=now_d4)
        self.assertEqual(actions_d4_dup, 0)
        self.assertEqual(Notification.objects.filter(user=self.teacher).count(), teacher_notifs_count)

        # Day 7: Auto-publish as UNVERIFIED and notify uploader
        now_d7 = self.t0 + timedelta(days=7, hours=1)
        actions_d7 = process_review_deadlines(now=now_d7)
        self.assertEqual(actions_d7, 1)
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, Note.Status.UNVERIFIED)
        self.assertTrue(Notification.objects.filter(user=self.student).exists())

        # Running again on Day 7 produces 0 actions
        actions_d7_dup = process_review_deadlines(now=now_d7)
        self.assertEqual(actions_d7_dup, 0)

    def test_deadline_edge_cases(self):
        # Case 1: Batch with no CR goes straight to class teacher at Day 2
        batch_no_cr = make_batch(department=self.dept, class_teacher=self.teacher)
        student_b2 = make_student(batch=batch_no_cr, cr=False)
        note_b2 = make_note(owner=student_b2, batch=batch_no_cr, department=self.dept, status=Note.Status.PENDING)
        Note.objects.filter(pk=note_b2.pk).update(created_at=self.t0)
        note_b2.refresh_from_db()

        Notification.objects.all().delete()
        now_d2 = self.t0 + timedelta(days=2, hours=1)
        process_review_deadlines(now=now_d2)
        note_b2.refresh_from_db()
        self.assertIsNotNone(note_b2.escalated_at)
        self.assertTrue(Notification.objects.filter(user=self.teacher).exists())

        # Case 2: Uploader is a CR -> notify other CRs + teacher, never uploader
        cr2 = make_student(batch=self.batch, cr=True, username="cr_second")
        note_cr_author = make_note(owner=self.cr, batch=self.batch, department=self.dept, status=Note.Status.PENDING)
        Note.objects.filter(pk=note_cr_author.pk).update(created_at=self.t0)

        Notification.objects.all().delete()
        process_review_deadlines(now=now_d2)
        # CR author should NOT receive review notification for their own note
        self.assertFalse(Notification.objects.filter(user=self.cr).exists())
        # Other CR should receive review notification
        self.assertTrue(Notification.objects.filter(user=cr2).exists())
        # Teacher should receive notification because author is CR
        self.assertTrue(Notification.objects.filter(user=self.teacher).exists())

        # Case 3: Batch with neither CR nor teacher -> auto-publish still applies on day 7
        batch_empty = make_batch(department=self.dept, class_teacher=None)
        student_b3 = make_student(batch=batch_empty, cr=False)
        note_b3 = make_note(owner=student_b3, batch=batch_empty, department=self.dept, status=Note.Status.PENDING)
        Note.objects.filter(pk=note_b3.pk).update(created_at=self.t0)

        now_d7 = self.t0 + timedelta(days=7, hours=1)
        process_review_deadlines(now=now_d7)
        note_b3.refresh_from_db()
        self.assertEqual(note_b3.status, Note.Status.UNVERIFIED)


class NoteAppealTests(TestCase):
    def setUp(self):
        self.dept = make_department()
        self.teacher = make_lecturer()
        self.batch = make_batch(department=self.dept, class_teacher=self.teacher)
        self.cr = make_student(batch=self.batch, cr=True)
        self.owner = make_student(batch=self.batch, cr=False)
        self.other_user = make_student(batch=self.batch, cr=False)

        self.note = make_note(owner=self.owner, batch=self.batch, department=self.dept, status=Note.Status.PENDING)
        reject_note(self.note, reviewer=self.cr, reason="Blurry pages")
        self.note.refresh_from_db()

        self.client = Client()

    def test_appeal_permissions_and_single_open_constraint(self):
        # Non-owner cannot appeal
        self.client.force_login(self.other_user)
        response = self.client.post(reverse("notes:appeal", args=[self.note.pk]), {"message": "Please review"})
        self.assertEqual(response.status_code, 403)

        # Owner appeals successfully
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("notes:appeal", args=[self.note.pk]),
            {"message": "I rescanned the blurry pages, please look again."}
        )
        self.assertEqual(response.status_code, 302)
        appeal = NoteAppeal.objects.get(note=self.note)
        self.assertEqual(appeal.status, NoteAppeal.Status.OPEN)
        self.assertEqual(appeal.user, self.owner)
        self.assertTrue(Notification.objects.filter(user=self.teacher).exists())

        # Second open appeal blocked
        response2 = self.client.post(
            reverse("notes:appeal", args=[self.note.pk]),
            {"message": "Another appeal message"}
        )
        self.assertEqual(NoteAppeal.objects.filter(note=self.note).count(), 1)

    def test_appeal_decision_uphold_and_grant(self):
        appeal = NoteAppeal.objects.create(
            note=self.note,
            user=self.owner,
            message="Please reconsider",
            status=NoteAppeal.Status.OPEN,
        )

        # Non-teacher / CR cannot decide appeals
        self.client.force_login(self.cr)
        response = self.client.post(
            reverse("notes:appeal_action", args=[appeal.pk]),
            {"action": "grant"}
        )
        self.assertEqual(response.status_code, 403)

        # Teacher upholds appeal without reason -> rejected
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("notes:appeal_action", args=[appeal.pk]),
            {"action": "uphold", "decision_note": ""}
        )
        appeal.refresh_from_db()
        self.assertEqual(appeal.status, NoteAppeal.Status.OPEN)

        # Teacher upholds appeal with reason
        response = self.client.post(
            reverse("notes:appeal_action", args=[appeal.pk]),
            {"action": "uphold", "decision_note": "Rejection stands, please re-upload clear pages."}
        )
        appeal.refresh_from_db()
        self.assertEqual(appeal.status, NoteAppeal.Status.UPHELD)
        self.assertEqual(appeal.decided_by, self.teacher)

        # Create new appeal and test granting
        appeal2 = NoteAppeal.objects.create(
            note=self.note,
            user=self.owner,
            message="Second try reconsider",
            status=NoteAppeal.Status.OPEN,
        )
        response = self.client.post(
            reverse("notes:appeal_action", args=[appeal2.pk]),
            {"action": "grant", "decision_note": "Approved after review"}
        )
        appeal2.refresh_from_db()
        self.assertEqual(appeal2.status, NoteAppeal.Status.GRANTED)
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, Note.Status.APPROVED)
        self.assertEqual(self.note.reviewed_by, self.teacher)


class NoteReportAndFlaggingTests(TestCase):
    def setUp(self):
        self.dept = make_department()
        self.teacher = make_lecturer()
        self.batch = make_batch(department=self.dept, class_teacher=self.teacher)
        self.owner = make_student(batch=self.batch, cr=False)
        self.note = make_note(owner=self.owner, batch=self.batch, department=self.dept, status=Note.Status.APPROVED)

        self.reporters = [make_student(batch=self.batch, cr=False) for _ in range(4)]
        self.client = Client()

    def test_owner_cannot_report_own_note(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("notes:report", args=[self.note.pk]),
            {"reason": "inaccurate", "details": "Self report"}
        )
        self.assertEqual(NoteReport.objects.filter(note=self.note).count(), 0)

    def test_three_reports_flag_and_dismiss_restores(self):
        # 1st and 2nd report: Note remains APPROVED
        for r in self.reporters[:2]:
            self.client.force_login(r)
            self.client.post(
                reverse("notes:report", args=[self.note.pk]),
                {"reason": "spam", "details": "Spam content"}
            )
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, Note.Status.APPROVED)

        # 3rd report: Triggers FLAGGED
        self.client.force_login(self.reporters[2])
        self.client.post(
            reverse("notes:report", args=[self.note.pk]),
            {"reason": "offensive", "details": "Offensive"}
        )
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, Note.Status.FLAGGED)
        self.assertEqual(self.note.status_before_flag, Note.Status.APPROVED)
        self.assertTrue(Notification.objects.filter(user=self.teacher).exists())

        # Unlocked user keeps access while FLAGGED
        unlocked_user = self.reporters[3]
        NoteDownload.objects.create(user=unlocked_user, note=self.note)
        self.assertTrue(can_view_note(unlocked_user, self.note))

        # Teacher dismisses flags -> status restored to APPROVED
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("notes:flagged_action", args=[self.note.pk]),
            {"action": "dismiss"}
        )
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, Note.Status.APPROVED)
        self.assertIsNone(self.note.status_before_flag)


class NoteRewardRulesTests(TestCase):
    def setUp(self):
        self.dept = make_department()
        self.teacher = make_lecturer()
        self.batch = make_batch(department=self.dept, class_teacher=self.teacher)
        self.owner = make_student(batch=self.batch, cr=False)
        self.note = make_note(owner=self.owner, batch=self.batch, department=self.dept, status=Note.Status.APPROVED)
        self.client = Client()

    def test_eleventh_rater_earns_owner_nothing(self):
        initial_owner_balance = get_balance(self.owner)

        # 10 raters rate the note
        for i in range(10):
            rater = make_student(batch=self.batch, cr=False)
            give_credits(rater, 10)
            NoteDownload.objects.create(user=rater, note=self.note)
            self.client.force_login(rater)
            self.client.post(reverse("notes:rate", args=[self.note.pk]), {"rating": 5, "review": "Great"})

        self.assertEqual(NoteRating.objects.filter(note=self.note, owner_rewarded=True).count(), 10)
        balance_after_10 = get_balance(self.owner)

        # 11th rater rates note
        rater_11 = make_student(batch=self.batch, cr=False)
        give_credits(rater_11, 10)
        NoteDownload.objects.create(user=rater_11, note=self.note)
        self.client.force_login(rater_11)
        self.client.post(reverse("notes:rate", args=[self.note.pk]), {"rating": 5, "review": "11th rating"})

        # Owner balance unchanged by 11th rater
        self.assertEqual(get_balance(self.owner), balance_after_10)
        # Rater 11 still receives their reward
        r11_rating = NoteRating.objects.get(user=rater_11, note=self.note)
        self.assertFalse(r11_rating.owner_rewarded)
        self.assertTrue(CreditLedger.objects.filter(user=rater_11, reason=CreditLedger.Reason.RATING_GIVEN).exists())

    def test_unverified_note_releases_upload_reward_after_three_downloads(self):
        unverified_note = make_note(
            owner=self.owner,
            batch=self.batch,
            department=self.dept,
            status=Note.Status.UNVERIFIED,
        )
        self.assertFalse(unverified_note.reward_paid)
        owner_start_balance = get_balance(self.owner)

        # First 2 downloads
        for _ in range(2):
            downloader = make_student(batch=self.batch, cr=False)
            give_credits(downloader, 10)
            self.client.force_login(downloader)
            self.client.post(reverse("notes:download", args=[unverified_note.pk]))

        unverified_note.refresh_from_db()
        self.assertFalse(unverified_note.reward_paid)
        self.assertEqual(get_balance(self.owner), owner_start_balance)

        # 3rd download: unlocks upload reward (+10)
        downloader_3 = make_student(batch=self.batch, cr=False)
        give_credits(downloader_3, 10)
        self.client.force_login(downloader_3)
        self.client.post(reverse("notes:download", args=[unverified_note.pk]))

        unverified_note.refresh_from_db()
        self.assertTrue(unverified_note.reward_paid)
        self.assertEqual(get_balance(self.owner), owner_start_balance + 10)


class RemovedNoteAccessTests(TestCase):
    def setUp(self):
        self.dept = make_department()
        self.teacher = make_lecturer()
        self.batch = make_batch(department=self.dept, class_teacher=self.teacher)
        self.owner = make_student(batch=self.batch, cr=False)
        self.note = make_note(owner=self.owner, batch=self.batch, department=self.dept, status=Note.Status.APPROVED)
        self.reader = make_student(batch=self.batch, cr=False)
        give_credits(self.reader, 10)
        self.client = Client()

    def test_removed_note_returns_404_to_unlocked_user(self):
        # Reader unlocks note
        self.client.force_login(self.reader)
        self.client.post(reverse("notes:download", args=[self.note.pk]))
        self.assertTrue(NoteDownload.objects.filter(user=self.reader, note=self.note).exists())

        # Reader can access file before removal
        response = self.client.get(reverse("notes:file", args=[self.note.pk]))
        self.assertEqual(response.status_code, 200)

        # Teacher removes note
        remove_note(self.note, by=self.teacher, reason="Copyright claim", reverse_reward=False)
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, Note.Status.REMOVED)

        # Reader now gets 404 when accessing the note file
        response_after = self.client.get(reverse("notes:file", args=[self.note.pk]))
        self.assertEqual(response_after.status_code, 404)
