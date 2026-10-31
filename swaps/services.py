from datetime import timedelta
import urllib.parse

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from credits.models import CreditLedger
from credits.services import add_entry, get_balance
from notifications.services import notify

from .models import SessionRating, SkillPost, SwapSession


class InsufficientCreditsError(ValueError):
    """Raised when one or both participants lack credits for a skill swap deposit."""
    def __init__(self, user, required, current):
        self.user = user
        self.required = required
        self.current = current
        super().__init__(
            f"User {user.username} has insufficient credits: needs {required}, has {current}."
        )


def is_user_verified(user):
    """Checks if a user is email-verified."""
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_superuser or user.is_staff or user.email_verified_at or user.is_email_verified)


def validate_meeting_link(url):
    """Validates meeting link per Phase 5.5:
    - scheme must be 'https'
    - hostname equals or is a subdomain of an allowed domain (from SWAP_ALLOWED_LINK_DOMAINS)
    - no username/password in URL
    - length at most 300
    """
    if not url:
        return
    if len(url) > 300:
        raise ValidationError(_("Meeting link cannot exceed 300 characters."))

    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValidationError(_("Meeting link must use the https scheme."))

    if parsed.username or parsed.password:
        raise ValidationError(_("Meeting link must not contain credentials."))

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValidationError(_("Meeting link must include a valid hostname."))

    allowed_domains = getattr(
        settings,
        "SWAP_ALLOWED_LINK_DOMAINS",
        ["meet.google.com", "zoom.us", "teams.microsoft.com"],
    )

    # Check exact match or subdomain
    is_allowed = False
    for domain in allowed_domains:
        d = domain.lower().strip()
        if hostname == d or hostname.endswith("." + d):
            is_allowed = True
            break

    if not is_allowed:
        raise ValidationError(_(f"'{hostname}' is not an allowed meeting domain."))


@transaction.atomic
def create_skill_post(user, kind, skill_name, description=""):
    """Creates a new SkillPost."""
    if not is_user_verified(user):
        raise PermissionDenied(_("You must verify your email before posting skills."))

    post = SkillPost.objects.create(
        user=user,
        kind=kind,
        skill_name=skill_name.strip(),
        description=description.strip(),
        is_active=True,
    )
    return post


@transaction.atomic
def request_session(post, user, proposed_time=None):
    """Learner requests a session from an OFFER post, or teacher offers to teach a REQUEST post.
    Enforces email verification and one open request per learner per post.
    """
    if not is_user_verified(user):
        raise PermissionDenied(_("You must verify your email before requesting a swap session."))

    if not is_user_verified(post.user):
        raise PermissionDenied(_("Post owner must have a verified email."))

    if post.user_id == user.id:
        raise ValidationError(_("You cannot swap skills with yourself."))

    # Determine teacher and learner
    if post.kind == SkillPost.Kind.OFFER:
        teacher = post.user
        learner = user
    else:
        teacher = user
        learner = post.user

    # One open request per learner per post
    open_statuses = [
        SwapSession.Status.REQUESTED,
        SwapSession.Status.ACCEPTED,
        SwapSession.Status.SCHEDULED,
    ]
    if SwapSession.objects.filter(post=post, learner=learner, status__in=open_statuses).exists():
        raise ValidationError(_("There is already an open session request for this post."))

    session = SwapSession.objects.create(
        teacher=teacher,
        learner=learner,
        post=post,
        skill_name=post.skill_name,
        status=SwapSession.Status.REQUESTED,
        proposed_time=proposed_time,
    )

    # Notify teacher
    learner_name = learner.get_full_name() or learner.username
    notify(
        teacher,
        f'{learner_name} requested a skill swap session for "{session.skill_name}".',
        reverse("swaps:session_detail", args=[session.id]),
    )
    return session


@transaction.atomic
def accept_and_propose_time(session, user, proposed_time):
    """Teacher accepts session and proposes a meeting time."""
    session = SwapSession.objects.select_for_update().get(pk=session.pk)

    if session.teacher_id != user.id:
        raise PermissionDenied(_("Only the teacher can accept this session."))

    if session.status != SwapSession.Status.REQUESTED:
        raise ValidationError(_(f"Cannot accept session in status '{session.status}'."))

    if not proposed_time or proposed_time <= timezone.now():
        raise ValidationError(_("Proposed time must be in the future."))

    session.proposed_time = proposed_time
    session.status = SwapSession.Status.ACCEPTED
    session.save(update_fields=["proposed_time", "status", "updated_at"])

    # Notify learner
    teacher_name = session.teacher.get_full_name() or session.teacher.username
    notify(
        session.learner,
        f'{teacher_name} accepted your session for "{session.skill_name}" and proposed a time.',
        reverse("swaps:session_detail", args=[session.id]),
    )
    return session


@transaction.atomic
def decline_session(session, user):
    """Teacher declines a session request."""
    session = SwapSession.objects.select_for_update().get(pk=session.pk)

    if session.teacher_id != user.id:
        raise PermissionDenied(_("Only the teacher can decline this session."))

    if session.status != SwapSession.Status.REQUESTED:
        raise ValidationError(_(f"Cannot decline session in status '{session.status}'."))

    session.status = SwapSession.Status.DECLINED
    session.save(update_fields=["status", "updated_at"])

    teacher_name = session.teacher.get_full_name() or session.teacher.username
    notify(
        session.learner,
        f'{teacher_name} declined the session request for "{session.skill_name}".',
        reverse("swaps:session_detail", args=[session.id]),
    )
    return session


@transaction.atomic
def propose_new_time(session, user, proposed_time):
    """Either teacher or learner proposes a new time while in ACCEPTED status."""
    session = SwapSession.objects.select_for_update().get(pk=session.pk)

    if user.id not in (session.teacher_id, session.learner_id):
        raise PermissionDenied(_("You are not a participant in this session."))

    if session.status != SwapSession.Status.ACCEPTED:
        raise ValidationError(_("Can only propose new time while session is in accepted status."))

    if not proposed_time or proposed_time <= timezone.now():
        raise ValidationError(_("Proposed time must be in the future."))

    session.proposed_time = proposed_time
    session.save(update_fields=["proposed_time", "updated_at"])

    other_user = session.learner if user.id == session.teacher_id else session.teacher
    actor_name = user.get_full_name() or user.username
    notify(
        other_user,
        f'{actor_name} proposed a new time for your session "{session.skill_name}".',
        reverse("swaps:session_detail", args=[session.id]),
    )
    return session


@transaction.atomic
def confirm_time(session, user):
    """Learner confirms the proposed time. Holds deposits from both users."""
    session = SwapSession.objects.select_for_update().get(pk=session.pk)

    if session.learner_id != user.id:
        raise PermissionDenied(_("Only the learner can confirm the session time."))

    if session.status != SwapSession.Status.ACCEPTED or session.deposit_held:
        raise ValidationError(_(f"Cannot confirm session in status '{session.status}'."))

    if not session.proposed_time or session.proposed_time <= timezone.now():
        raise ValidationError(_("Session time must be scheduled in the future."))

    deposit = getattr(settings, "SWAP_DEPOSIT", 10)

    # Lock both users in ascending ID order to prevent deadlocks
    first_id, second_id = sorted([session.teacher_id, session.learner_id])
    users = {
        u.id: u
        for u in User.objects.select_for_update().filter(id__in=[first_id, second_id])
    }
    teacher = users[session.teacher_id]
    learner = users[session.learner_id]

    t_bal = get_balance(teacher)
    l_bal = get_balance(learner)

    if l_bal < deposit:
        raise InsufficientCreditsError(learner, deposit, l_bal)
    if t_bal < deposit:
        raise InsufficientCreditsError(teacher, deposit, t_bal)

    # Write two SWAP_HOLD entries (negative)
    add_entry(
        user=teacher,
        amount=-deposit,
        reason=CreditLedger.Reason.SWAP_HOLD,
        description=f"Skill swap deposit for session #{session.id} ({session.skill_name})",
        allow_negative=False,
        notify=False,
    )
    add_entry(
        user=learner,
        amount=-deposit,
        reason=CreditLedger.Reason.SWAP_HOLD,
        description=f"Skill swap deposit for session #{session.id} ({session.skill_name})",
        allow_negative=False,
        notify=False,
    )

    session.deposit_held = True
    session.status = SwapSession.Status.SCHEDULED
    session.save(update_fields=["deposit_held", "status", "updated_at"])

    # Notifications
    notify(
        session.teacher,
        f'Session "{session.skill_name}" has been confirmed! Deposit of {deposit} nuts held.',
        reverse("swaps:session_detail", args=[session.id]),
    )
    notify(
        session.learner,
        f'Session "{session.skill_name}" confirmed! Deposit of {deposit} nuts held.',
        reverse("swaps:session_detail", args=[session.id]),
    )
    return session


@transaction.atomic
def set_meeting_link(session, user, link):
    """Sets or edits the meeting link. Only the teacher can do so before completion."""
    session = SwapSession.objects.select_for_update().get(pk=session.pk)

    if session.teacher_id != user.id:
        raise PermissionDenied(_("Only the teacher can set or edit the meeting link."))

    if session.status in (SwapSession.Status.COMPLETED, SwapSession.Status.CANCELLED, SwapSession.Status.NO_SHOW):
        raise ValidationError(_("Cannot edit meeting link for ended sessions."))

    clean_link = (link or "").strip()
    validate_meeting_link(clean_link)

    session.meeting_link = clean_link
    session.save(update_fields=["meeting_link", "updated_at"])

    # Notify learner (Never put the URL in the notification text)
    notify(
        session.learner,
        f'Meeting link added for your session "{session.skill_name}".',
        reverse("swaps:session_detail", args=[session.id]),
    )
    return session


@transaction.atomic
def cancel_session(session, user):
    """Cancels a session.
    If in SCHEDULED status with deposits held:
    - Cancel at least SWAP_FREE_CANCEL_HOURS before start: both deposits returned.
    - Later cancel: treated as a no-show by the canceller. Non-canceller receives RETURN + FORFEIT.
    """
    session = SwapSession.objects.select_for_update().get(pk=session.pk)

    if user.id not in (session.teacher_id, session.learner_id):
        raise PermissionDenied(_("You are not a participant in this session."))

    if session.status in (SwapSession.Status.COMPLETED, SwapSession.Status.CANCELLED, SwapSession.Status.NO_SHOW, SwapSession.Status.EXPIRED):
        raise ValidationError(_("Session has already ended."))

    deposit = getattr(settings, "SWAP_DEPOSIT", 10)

    if session.status == SwapSession.Status.SCHEDULED and session.deposit_held:
        # Lock both users in ascending ID order
        u1_id, u2_id = sorted([session.teacher_id, session.learner_id])
        users = {
            u.id: u
            for u in User.objects.select_for_update().filter(id__in=[u1_id, u2_id])
        }
        teacher = users[session.teacher_id]
        learner = users[session.learner_id]

        free_cancel_hours = getattr(settings, "SWAP_FREE_CANCEL_HOURS", 24)
        cutoff = session.proposed_time - timedelta(hours=free_cancel_hours)
        now = timezone.now()

        if now <= cutoff:
            # Free cancel: both returned
            add_entry(
                user=teacher,
                amount=deposit,
                reason=CreditLedger.Reason.SWAP_RETURN,
                description=f"Deposit returned: Session #{session.id} cancelled in advance",
                allow_negative=True,
                notify=True,
            )
            add_entry(
                user=learner,
                amount=deposit,
                reason=CreditLedger.Reason.SWAP_RETURN,
                description=f"Deposit returned: Session #{session.id} cancelled in advance",
                allow_negative=True,
                notify=True,
            )
        else:
            # Late cancel: treated as no-show by the canceller
            non_canceller = learner if user.id == session.teacher_id else teacher
            add_entry(
                user=non_canceller,
                amount=deposit,
                reason=CreditLedger.Reason.SWAP_RETURN,
                description=f"Deposit returned: Session #{session.id} late cancelled by other party",
                allow_negative=True,
                notify=True,
            )
            add_entry(
                user=non_canceller,
                amount=deposit,
                reason=CreditLedger.Reason.SWAP_FORFEIT,
                description=f"Forfeited deposit: Session #{session.id} late cancelled by other party",
                allow_negative=True,
                notify=True,
            )

        session.deposit_held = False

    session.status = SwapSession.Status.CANCELLED
    session.save(update_fields=["status", "deposit_held", "updated_at"])

    # Notify both
    other_user = session.learner if user.id == session.teacher_id else session.teacher
    actor_name = user.get_full_name() or user.username
    notify(
        other_user,
        f'{actor_name} cancelled the session "{session.skill_name}".',
        reverse("swaps:session_detail", args=[session.id]),
    )
    return session


@transaction.atomic
def report_outcome(session, user, outcome):
    """Reports outcome (completed or no_show) after session start time."""
    session = SwapSession.objects.select_for_update().get(pk=session.pk)

    if user.id not in (session.teacher_id, session.learner_id):
        raise PermissionDenied(_("You are not a participant in this session."))

    if session.status != SwapSession.Status.SCHEDULED:
        raise ValidationError(_(f"Cannot report outcome for session in status '{session.status}'."))

    if not session.proposed_time or timezone.now() < session.proposed_time:
        raise ValidationError(_("Cannot report outcome before the session start time."))

    if outcome not in (SwapSession.Outcome.COMPLETED, SwapSession.Outcome.NO_SHOW):
        raise ValidationError(_("Invalid outcome value."))

    now = timezone.now()
    if user.id == session.teacher_id:
        if session.teacher_outcome:
            raise ValidationError(_("You have already reported the outcome for this session."))
        session.teacher_outcome = outcome
        session.teacher_outcome_at = now
    else:
        if session.learner_outcome:
            raise ValidationError(_("You have already reported the outcome for this session."))
        session.learner_outcome = outcome
        session.learner_outcome_at = now

    session.save(update_fields=["teacher_outcome", "teacher_outcome_at", "learner_outcome", "learner_outcome_at", "updated_at"])

    other_user = session.learner if user.id == session.teacher_id else session.teacher
    actor_name = user.get_full_name() or user.username
    notify(
        other_user,
        f'{actor_name} reported an outcome for session "{session.skill_name}".',
        reverse("swaps:session_detail", args=[session.id]),
    )

    return evaluate_session_outcomes(session)


@transaction.atomic
def evaluate_session_outcomes(session):
    """Evaluates outcomes for a session and settles deposits if conditions are met."""
    session = SwapSession.objects.select_for_update().get(pk=session.pk)

    if session.status != SwapSession.Status.SCHEDULED or not session.deposit_held:
        return session

    deposit = getattr(settings, "SWAP_DEPOSIT", 10)
    now = timezone.now()

    # Lock users
    u1_id, u2_id = sorted([session.teacher_id, session.learner_id])
    users = {
        u.id: u
        for u in User.objects.select_for_update().filter(id__in=[u1_id, u2_id])
    }
    teacher = users[session.teacher_id]
    learner = users[session.learner_id]

    t_out = session.teacher_outcome
    l_out = session.learner_outcome

    # 1. Both reported "completed"
    if t_out == SwapSession.Outcome.COMPLETED and l_out == SwapSession.Outcome.COMPLETED:
        add_entry(
            user=teacher,
            amount=deposit,
            reason=CreditLedger.Reason.SWAP_RETURN,
            description=f"Deposit returned: Session #{session.id} completed successfully",
            allow_negative=True,
            notify=True,
        )
        add_entry(
            user=learner,
            amount=deposit,
            reason=CreditLedger.Reason.SWAP_RETURN,
            description=f"Deposit returned: Session #{session.id} completed successfully",
            allow_negative=True,
            notify=True,
        )
        session.deposit_held = False
        session.status = SwapSession.Status.COMPLETED
        session.save(update_fields=["deposit_held", "status", "updated_at"])
        return session

    # 2. Reports contradict (one says completed, other says no_show)
    if (t_out == SwapSession.Outcome.COMPLETED and l_out == SwapSession.Outcome.NO_SHOW) or \
       (t_out == SwapSession.Outcome.NO_SHOW and l_out == SwapSession.Outcome.COMPLETED) or \
       (t_out == SwapSession.Outcome.NO_SHOW and l_out == SwapSession.Outcome.NO_SHOW):
        add_entry(
            user=teacher,
            amount=deposit,
            reason=CreditLedger.Reason.SWAP_RETURN,
            description=f"Deposit returned: Session #{session.id} outcome disputed",
            allow_negative=True,
            notify=True,
        )
        add_entry(
            user=learner,
            amount=deposit,
            reason=CreditLedger.Reason.SWAP_RETURN,
            description=f"Deposit returned: Session #{session.id} outcome disputed",
            allow_negative=True,
            notify=True,
        )
        session.deposit_held = False
        session.status = SwapSession.Status.DISPUTED
        session.save(update_fields=["deposit_held", "status", "updated_at"])

        notify(
            teacher,
            f'Outcomes contradicted for session "{session.skill_name}". Marked as disputed; deposits returned.',
            reverse("swaps:session_detail", args=[session.id]),
        )
        notify(
            learner,
            f'Outcomes contradicted for session "{session.skill_name}". Marked as disputed; deposits returned.',
            reverse("swaps:session_detail", args=[session.id]),
        )
        return session

    # 3. One side reports no_show, and other has not reported within SWAP_DISPUTE_HOURS
    dispute_hours = getattr(settings, "SWAP_DISPUTE_HOURS", 24)
    if t_out == SwapSession.Outcome.NO_SHOW and not l_out:
        if now >= session.teacher_outcome_at + timedelta(hours=dispute_hours):
            # Learner failed to contest: teacher receives RETURN + FORFEIT
            add_entry(
                user=teacher,
                amount=deposit,
                reason=CreditLedger.Reason.SWAP_RETURN,
                description=f"Deposit returned: Session #{session.id} no-show by learner",
                allow_negative=True,
                notify=True,
            )
            add_entry(
                user=teacher,
                amount=deposit,
                reason=CreditLedger.Reason.SWAP_FORFEIT,
                description=f"Forfeited deposit received: Session #{session.id} no-show by learner",
                allow_negative=True,
                notify=True,
            )
            session.deposit_held = False
            session.status = SwapSession.Status.NO_SHOW
            session.save(update_fields=["deposit_held", "status", "updated_at"])
            notify(
                teacher,
                f'No-show confirmed for session "{session.skill_name}". You received {deposit * 2} nuts.',
                reverse("swaps:session_detail", args=[session.id]),
            )
            notify(
                learner,
                f'Session "{session.skill_name}" closed as no-show due to no response. Deposit forfeited.',
                reverse("swaps:session_detail", args=[session.id]),
            )
            return session

    if l_out == SwapSession.Outcome.NO_SHOW and not t_out:
        if now >= session.learner_outcome_at + timedelta(hours=dispute_hours):
            # Teacher failed to contest: learner receives RETURN + FORFEIT
            add_entry(
                user=learner,
                amount=deposit,
                reason=CreditLedger.Reason.SWAP_RETURN,
                description=f"Deposit returned: Session #{session.id} no-show by teacher",
                allow_negative=True,
                notify=True,
            )
            add_entry(
                user=learner,
                amount=deposit,
                reason=CreditLedger.Reason.SWAP_FORFEIT,
                description=f"Forfeited deposit received: Session #{session.id} no-show by teacher",
                allow_negative=True,
                notify=True,
            )
            session.deposit_held = False
            session.status = SwapSession.Status.NO_SHOW
            session.save(update_fields=["deposit_held", "status", "updated_at"])
            notify(
                learner,
                f'No-show confirmed for session "{session.skill_name}". You received {deposit * 2} nuts.',
                reverse("swaps:session_detail", args=[session.id]),
            )
            notify(
                teacher,
                f'Session "{session.skill_name}" closed as no-show due to no response. Deposit forfeited.',
                reverse("swaps:session_detail", args=[session.id]),
            )
            return session

    # 4. Nobody reports within SWAP_AUTO_RESOLVE_HOURS after start time: both deposits returned
    auto_resolve_hours = getattr(settings, "SWAP_AUTO_RESOLVE_HOURS", 72)
    if session.proposed_time and now >= session.proposed_time + timedelta(hours=auto_resolve_hours):
        add_entry(
            user=teacher,
            amount=deposit,
            reason=CreditLedger.Reason.SWAP_RETURN,
            description=f"Deposit returned: Session #{session.id} auto-resolved after {auto_resolve_hours}h",
            allow_negative=True,
            notify=True,
        )
        add_entry(
            user=learner,
            amount=deposit,
            reason=CreditLedger.Reason.SWAP_RETURN,
            description=f"Deposit returned: Session #{session.id} auto-resolved after {auto_resolve_hours}h",
            allow_negative=True,
            notify=True,
        )
        session.deposit_held = False
        session.status = SwapSession.Status.COMPLETED
        session.save(update_fields=["deposit_held", "status", "updated_at"])
        return session

    return session


@transaction.atomic
def resolve_all_swaps():
    """Runs periodic or lazy engine resolution across all eligible sessions.
    - Resolves time-based rules: dispute window expiration, auto-resolution after 72h.
    - Expires requested/accepted sessions without action after 7 days.
    """
    now = timezone.now()
    resolved_count = 0

    # 1. Scheduled sessions needing dispute resolution or auto-resolve
    scheduled_sessions = SwapSession.objects.filter(
        status=SwapSession.Status.SCHEDULED,
        deposit_held=True,
    )
    for session in scheduled_sessions:
        before_status = session.status
        before_held = session.deposit_held
        evaluate_session_outcomes(session)
        session.refresh_from_db()
        if session.status != before_status or session.deposit_held != before_held:
            resolved_count += 1

    # 2. Expire requested/accepted sessions with no response in 7 days
    stale_cutoff = now - timedelta(days=7)
    expired_sessions = SwapSession.objects.filter(
        status__in=[SwapSession.Status.REQUESTED, SwapSession.Status.ACCEPTED],
        updated_at__lte=stale_cutoff,
    )
    for s in expired_sessions:
        s.status = SwapSession.Status.EXPIRED
        s.save(update_fields=["status", "updated_at"])
        resolved_count += 1

    return resolved_count


@transaction.atomic
def rate_session(session, user, rating, comment=""):
    """Submits a rating (1-5) for a completed session. Ratings give no credits."""
    session.refresh_from_db()
    if user.id not in (session.teacher_id, session.learner_id):
        raise PermissionDenied(_("Only participants can rate this session."))

    if session.status not in (SwapSession.Status.COMPLETED, SwapSession.Status.NO_SHOW):
        raise ValidationError(_("Can only rate completed sessions."))

    if SessionRating.objects.filter(session=session, rater=user).exists():
        raise ValidationError(_("You have already rated this session."))

    rating_obj = SessionRating.objects.create(
        session=session,
        rater=user,
        rating=int(rating),
        comment=comment.strip(),
    )

    other_user = session.learner if user.id == session.teacher_id else session.teacher
    notify(
        other_user,
        f'You received a {rating}★ rating for session "{session.skill_name}".',
        reverse("swaps:session_detail", args=[session.id]),
    )
    return rating_obj

