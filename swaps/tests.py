from datetime import timedelta
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.testing import make_student
from credits.models import CreditLedger
from credits.services import add_entry, get_balance
from swaps.forms import MeetingLinkForm
from swaps.models import SessionRating, SkillPost, SwapSession
from swaps.services import (
    InsufficientCreditsError,
    accept_and_propose_time,
    cancel_session,
    confirm_time,
    create_skill_post,
    decline_session,
    propose_new_time,
    rate_session,
    report_outcome,
    request_session,
    resolve_all_swaps,
    set_meeting_link,
    validate_meeting_link,
)


class MeetingLinkValidationTests(TestCase):
    def test_meeting_link_allowed_and_rejected_domains(self):
        """Acceptance test:
        evil.com, http://meet.google.com, https://meet.google.com.evil.com, https://user@zoom.us rejected.
        https://us02web.zoom.us/j/123 accepted.
        """
        # Rejections
        rejected = [
            "https://evil.com",
            "http://meet.google.com",
            "https://meet.google.com.evil.com",
            "https://user@zoom.us",
            "https://user:pass@zoom.us",
            "http://zoom.us",
            "ftp://meet.google.com",
            "https://" + "a" * 301 + ".zoom.us",
        ]
        for url in rejected:
            with self.assertRaises(ValidationError, msg=f"Should reject {url}"):
                validate_meeting_link(url)

        # Acceptances
        accepted = [
            "https://us02web.zoom.us/j/123",
            "https://meet.google.com/abc-defg-hij",
            "https://teams.microsoft.com/l/meetup-join/123",
        ]
        for url in accepted:
            try:
                validate_meeting_link(url)
            except ValidationError:
                self.fail(f"Valid meeting link '{url}' was unexpectedly rejected.")


class SwapPermissionAndAccessTests(TestCase):
    def setUp(self):
        self.teacher = make_student(username="teacher1", email="teacher1@example.com")
        self.learner = make_student(username="learner1", email="learner1@example.com")
        self.intruder = make_student(username="intruder1", email="intruder1@example.com")
        self.client = Client()

        self.post = create_skill_post(
            user=self.teacher,
            kind=SkillPost.Kind.OFFER,
            skill_name="Python 101",
            description="Basics of Python",
        )
        self.session = request_session(self.post, self.learner)

    def test_third_user_cannot_access_session_page(self):
        self.client.force_login(self.intruder)
        res = self.client.get(reverse("swaps:session_detail", args=[self.session.id]))
        self.assertEqual(res.status_code, 403)

    def test_third_user_cannot_rate_session(self):
        self.session.status = SwapSession.Status.COMPLETED
        self.session.save()

        self.client.force_login(self.intruder)
        res = self.client.post(
            reverse("swaps:session_rate", args=[self.session.id]),
            {"rating": 5, "comment": "Nice"},
        )
        self.assertEqual(res.status_code, 403)

    def test_non_teacher_cannot_set_meeting_link(self):
        with self.assertRaises(PermissionDenied):
            set_meeting_link(self.session, self.learner, "https://meet.google.com/abc-defg-hij")

    def test_unverified_user_cannot_create_post(self):
        unverified = make_student(
            username="unverified",
            email="unv@example.com",
            is_email_verified=False,
            email_verified_at=None,
        )
        with self.assertRaises(PermissionDenied):
            create_skill_post(unverified, SkillPost.Kind.OFFER, "Math")

    def test_one_open_request_per_learner_per_post(self):
        with self.assertRaises(ValidationError):
            request_session(self.post, self.learner)


class SwapDepositStateMachineTests(TestCase):
    def setUp(self):
        self.teacher = make_student(username="tea_user", email="tea@test.com")
        self.learner = make_student(username="lea_user", email="lea@test.com")
        # Fund each user with 50 nuts
        add_entry(self.teacher, 50, CreditLedger.Reason.PURCHASE, "Funding")
        add_entry(self.learner, 50, CreditLedger.Reason.PURCHASE, "Funding")

        self.post = create_skill_post(
            user=self.teacher,
            kind=SkillPost.Kind.OFFER,
            skill_name="Data Structures",
        )
        self.session = request_session(self.post, self.learner)
        self.future_time = timezone.now() + timedelta(days=2)
        accept_and_propose_time(self.session, self.teacher, self.future_time)
        self.session.refresh_from_db()

    def test_concurrent_confirmations_hold_deposits_only_once(self):
        """Acceptance test: Concurrent attempts to confirm one session hold deposits only once."""
        self.assertEqual(self.session.status, SwapSession.Status.ACCEPTED)

        # First confirmation
        confirm_time(self.session, self.learner)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SwapSession.Status.SCHEDULED)
        self.assertTrue(self.session.deposit_held)

        self.assertEqual(get_balance(self.teacher), 40)
        self.assertEqual(get_balance(self.learner), 40)

        # Second attempt must be rejected or not re-charge deposits
        with self.assertRaises(ValidationError):
            confirm_time(self.session, self.learner)

        # Ensure total SWAP_HOLD entries for this session are strictly 2
        hold_count = CreditLedger.objects.filter(
            reason=CreditLedger.Reason.SWAP_HOLD,
            description__contains=f"#{self.session.id}",
        ).count()
        self.assertEqual(hold_count, 2)

    def test_path_both_completed_conserves_credits(self):
        """Acceptance test: Path 1 - both report completed -> both deposits returned."""
        confirm_time(self.session, self.learner)
        self.session.proposed_time = timezone.now() - timedelta(hours=2)
        self.session.save(update_fields=["proposed_time"])

        # Both report completed
        report_outcome(self.session, self.teacher, SwapSession.Outcome.COMPLETED)
        report_outcome(self.session, self.learner, SwapSession.Outcome.COMPLETED)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SwapSession.Status.COMPLETED)
        self.assertFalse(self.session.deposit_held)

        # Balances returned in full
        self.assertEqual(get_balance(self.teacher), 50)
        self.assertEqual(get_balance(self.learner), 50)
        self.assertEqual(get_balance(self.teacher) + get_balance(self.learner), 100)

    def test_path_advance_cancellation_conserves_credits(self):
        """Acceptance test: Path 2 - cancellation >= 24h before start -> both returned."""
        confirm_time(self.session, self.learner)
        self.session.proposed_time = timezone.now() + timedelta(hours=48)
        self.session.save(update_fields=["proposed_time"])

        cancel_session(self.session, self.learner)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SwapSession.Status.CANCELLED)
        self.assertFalse(self.session.deposit_held)

        self.assertEqual(get_balance(self.teacher), 50)
        self.assertEqual(get_balance(self.learner), 50)
        self.assertEqual(get_balance(self.teacher) + get_balance(self.learner), 100)

    def test_path_late_cancellation_forfeits_to_innocent_party(self):
        """Acceptance test: Path 3 - late cancellation < 24h before start.
        Canceller forfeits deposit; non-canceller receives RETURN + FORFEIT.
        """
        confirm_time(self.session, self.learner)
        # Schedule 2 hours in future (late)
        self.session.proposed_time = timezone.now() + timedelta(hours=2)
        self.session.save(update_fields=["proposed_time"])

        # Learner cancels late
        cancel_session(self.session, self.learner)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SwapSession.Status.CANCELLED)
        self.assertFalse(self.session.deposit_held)

        # Learner lost 10 nuts (balance 40)
        self.assertEqual(get_balance(self.learner), 40)
        # Teacher receives RETURN (10) + FORFEIT (10) = balance 60
        self.assertEqual(get_balance(self.teacher), 60)
        # Credits conserved across both users (40 + 60 = 100)
        self.assertEqual(get_balance(self.teacher) + get_balance(self.learner), 100)

    def test_path_contradictory_outcomes_marked_disputed_both_returned(self):
        """Acceptance test: Path 4 - one says completed, other says no_show -> DISPUTED, both returned."""
        confirm_time(self.session, self.learner)
        self.session.proposed_time = timezone.now() - timedelta(hours=2)
        self.session.save(update_fields=["proposed_time"])

        report_outcome(self.session, self.teacher, SwapSession.Outcome.COMPLETED)
        report_outcome(self.session, self.learner, SwapSession.Outcome.NO_SHOW)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SwapSession.Status.DISPUTED)
        self.assertFalse(self.session.deposit_held)

        self.assertEqual(get_balance(self.teacher), 50)
        self.assertEqual(get_balance(self.learner), 50)
        self.assertEqual(get_balance(self.teacher) + get_balance(self.learner), 100)

    def test_path_uncontested_no_show_after_dispute_window(self):
        """Acceptance test: Path 5 - one says no_show and other fails to contest in 24h.
        Attending side gets RETURN + FORFEIT; no-show forfeits.
        """
        confirm_time(self.session, self.learner)
        self.session.proposed_time = timezone.now() - timedelta(hours=30)
        self.session.save(update_fields=["proposed_time"])

        # Learner reports teacher was a no-show
        report_outcome(self.session, self.learner, SwapSession.Outcome.NO_SHOW)

        # Fast forward past 24h dispute window
        self.session.learner_outcome_at = timezone.now() - timedelta(hours=25)
        self.session.save(update_fields=["learner_outcome_at"])

        # Engine runs
        resolve_all_swaps()

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SwapSession.Status.NO_SHOW)
        self.assertFalse(self.session.deposit_held)

        # Learner got RETURN + FORFEIT (balance 60), teacher forfeited (balance 40)
        self.assertEqual(get_balance(self.learner), 60)
        self.assertEqual(get_balance(self.teacher), 40)
        self.assertEqual(get_balance(self.teacher) + get_balance(self.learner), 100)

    def test_path_nobody_reports_within_72h_auto_resolves_both_returned(self):
        """Acceptance test: Path 6 - nobody reports within 72h -> both returned."""
        confirm_time(self.session, self.learner)
        self.session.proposed_time = timezone.now() - timedelta(hours=73)
        self.session.save(update_fields=["proposed_time"])

        resolve_all_swaps()

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SwapSession.Status.COMPLETED)
        self.assertFalse(self.session.deposit_held)

        self.assertEqual(get_balance(self.teacher), 50)
        self.assertEqual(get_balance(self.learner), 50)
        self.assertEqual(get_balance(self.teacher) + get_balance(self.learner), 100)

    def test_path_stale_sessions_expire_after_7_days(self):
        """Acceptance test: Path 7 - requested/accepted session without response in 7 days -> expired."""
        stale_session = request_session(self.post, make_student(username="stale_u", email="stale@test.com"))
        stale_session.updated_at = timezone.now() - timedelta(days=8)
        # Update using queryset update to bypass auto_now
        SwapSession.objects.filter(id=stale_session.id).update(updated_at=timezone.now() - timedelta(days=8))

        resolve_all_swaps()

        stale_session.refresh_from_db()
        self.assertEqual(stale_session.status, SwapSession.Status.EXPIRED)

    def test_rating_gives_no_credits(self):
        """Ratings give 1-5 stars, recorded only once, and give 0 credits."""
        confirm_time(self.session, self.learner)
        self.session.proposed_time = timezone.now() - timedelta(hours=2)
        self.session.save(update_fields=["proposed_time"])
        report_outcome(self.session, self.teacher, SwapSession.Outcome.COMPLETED)
        report_outcome(self.session, self.learner, SwapSession.Outcome.COMPLETED)

        bal_before = get_balance(self.teacher)
        r = rate_session(self.session, self.learner, 5, "Amazing lesson!")
        self.assertEqual(r.rating, 5)
        self.assertEqual(get_balance(self.teacher), bal_before)

        # Second rating by same user raises ValidationError
        with self.assertRaises(ValidationError):
            rate_session(self.session, self.learner, 4, "Trying again")

    def test_insufficient_credits_blocks_scheduling(self):
        """Cannot confirm session if either user has < deposit nuts."""
        poor_learner = make_student(username="poor_u", email="poor@test.com")
        # poor learner has 0 nuts
        post = create_skill_post(self.teacher, SkillPost.Kind.OFFER, "Guitar")
        session = request_session(post, poor_learner)
        accept_and_propose_time(session, self.teacher, timezone.now() + timedelta(days=1))

        with self.assertRaises(InsufficientCreditsError):
            confirm_time(session, poor_learner)
