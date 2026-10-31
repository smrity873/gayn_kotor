from datetime import datetime
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _

from credits.services import get_balance

from .forms import (
    MeetingLinkForm,
    ProposeTimeForm,
    ReportOutcomeForm,
    SessionRatingForm,
    SkillPostForm,
)
from .models import SessionRating, SkillPost, SwapSession
from .services import (
    InsufficientCreditsError,
    accept_and_propose_time,
    cancel_session,
    confirm_time,
    create_skill_post,
    decline_session,
    evaluate_session_outcomes,
    propose_new_time,
    rate_session,
    report_outcome,
    request_session,
    set_meeting_link,
)


def swap_list(request):
    """Browse offers and requests, view matches, and list my sessions."""
    tab = request.GET.get("tab", "offers")
    query = request.GET.get("q", "").strip()

    posts_qs = SkillPost.objects.filter(is_active=True).select_related("user")
    if query:
        posts_qs = posts_qs.filter(
            Q(skill_name__icontains=query) | Q(description__icontains=query)
        )

    my_sessions = []
    my_posts = []
    matches = []

    if request.user.is_authenticated:
        my_sessions = (
            SwapSession.objects.filter(
                Q(teacher=request.user) | Q(learner=request.user)
            )
            .select_related("teacher", "learner", "post")
            .order_by("-updated_at")
        )
        my_posts = SkillPost.objects.filter(user=request.user).order_by("-created_at")

        # "Matches for you" panel (PRD 5.6):
        # Other people whose offers equal my requests (by normalized_skill)
        my_requests = SkillPost.objects.filter(
            user=request.user,
            kind=SkillPost.Kind.REQUEST,
            is_active=True,
        )
        my_req_skills = set(my_requests.values_list("normalized_skill", flat=True))

        my_offers = SkillPost.objects.filter(
            user=request.user,
            kind=SkillPost.Kind.OFFER,
            is_active=True,
        )
        my_offer_skills = set(my_offers.values_list("normalized_skill", flat=True))

        if my_req_skills:
            matching_offers = (
                SkillPost.objects.filter(
                    kind=SkillPost.Kind.OFFER,
                    is_active=True,
                    normalized_skill__in=my_req_skills,
                )
                .exclude(user=request.user)
                .select_related("user")
            )
            for offer in matching_offers:
                # Check if other user has a request matching what I offer -> mutual swap!
                is_mutual = SkillPost.objects.filter(
                    user=offer.user,
                    kind=SkillPost.Kind.REQUEST,
                    is_active=True,
                    normalized_skill__in=my_offer_skills,
                ).exists()
                matches.append({
                    "post": offer,
                    "is_mutual": is_mutual,
                })

    if tab == "requests":
        active_list = posts_qs.filter(kind=SkillPost.Kind.REQUEST)
    elif tab == "my_sessions":
        active_list = my_sessions
    elif tab == "my_posts":
        active_list = my_posts
    else:
        tab = "offers"
        active_list = posts_qs.filter(kind=SkillPost.Kind.OFFER)

    paginator = Paginator(active_list, 15)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "tab": tab,
        "query": query,
        "page_obj": page_obj,
        "matches": matches,
        "deposit": getattr(settings, "SWAP_DEPOSIT", 10),
    }
    return render(request, "swaps/list.html", context)


@login_required
def post_create(request):
    """Creates a new skill offer or request."""
    if request.method == "POST":
        form = SkillPostForm(request.POST)
        if form.is_valid():
            try:
                post = create_skill_post(
                    user=request.user,
                    kind=form.cleaned_data["kind"],
                    skill_name=form.cleaned_data["skill_name"],
                    description=form.cleaned_data["description"],
                )
                messages.success(request, _(f"Skill {post.get_kind_display()} published successfully!"))
                return redirect(f"{reverse('swaps:list')}?tab={post.kind}s")
            except PermissionDenied as e:
                messages.error(request, str(e))
    else:
        kind = request.GET.get("kind", SkillPost.Kind.OFFER)
        form = SkillPostForm(initial={"kind": kind})

    return render(request, "swaps/post_form.html", {"form": form, "title": _("Post a Skill")})


@login_required
def post_edit(request, pk):
    """Edits an existing skill post."""
    post = get_object_or_404(SkillPost, pk=pk)
    if post.user_id != request.user.id and not request.user.is_superuser:
        raise PermissionDenied(_("You can only edit your own posts."))

    if request.method == "POST":
        form = SkillPostForm(request.POST, instance=post)
        if form.is_valid():
            form.save()
            messages.success(request, _("Skill post updated."))
            return redirect(f"{reverse('swaps:list')}?tab=my_posts")
    else:
        form = SkillPostForm(instance=post)

    return render(request, "swaps/post_form.html", {"form": form, "post": post, "title": _("Edit Skill Post")})


@login_required
def post_deactivate(request, pk):
    """Deactivates a skill post."""
    post = get_object_or_404(SkillPost, pk=pk)
    if post.user_id != request.user.id and not request.user.is_superuser:
        raise PermissionDenied(_("You can only deactivate your own posts."))

    if request.method == "POST":
        post.is_active = False
        post.save(update_fields=["is_active"])
        messages.success(request, _("Skill post deactivated."))

    return redirect(f"{reverse('swaps:list')}?tab=my_posts")


@login_required
def session_request(request, post_id):
    """Requests a skill swap session with the post owner."""
    post = get_object_or_404(SkillPost, pk=post_id, is_active=True)

    if request.method == "POST":
        proposed_time_raw = request.POST.get("proposed_time")
        proposed_time = parse_datetime(proposed_time_raw) if proposed_time_raw else None

        try:
            session = request_session(post=post, user=request.user, proposed_time=proposed_time)
            messages.success(request, _("Swap session requested! Waiting for teacher's acceptance."))
            return redirect("swaps:session_detail", pk=session.id)
        except (ValidationError, PermissionDenied) as e:
            msg = e.message if hasattr(e, "message") else str(e)
            messages.error(request, msg)
            return redirect("swaps:session_request", post_id=post.id)

    # GET request - show confirmation form
    context = {
        "post": post,
        "deposit": getattr(settings, "SWAP_DEPOSIT", 10),
        "user_balance": get_balance(request.user),
    }
    return render(request, "swaps/session_request.html", context)


@login_required
def session_detail(request, pk):
    """Detailed view for a SwapSession.
    Enforces object-level permission: only teacher, learner, and superusers.
    Lazily evaluates state resolution on page load.
    """
    session = get_object_or_404(
        SwapSession.objects.select_related("teacher", "learner", "post"),
        pk=pk,
    )

    is_teacher = (session.teacher_id == request.user.id)
    is_learner = (session.learner_id == request.user.id)
    is_admin = request.user.is_superuser

    if not (is_teacher or is_learner or is_admin):
        raise PermissionDenied(_("You do not have permission to view this session."))

    # Lazy engine execution on page load (PRD 5.7)
    evaluate_session_outcomes(session)
    session.refresh_from_db()

    user_balance = get_balance(request.user)
    deposit = getattr(settings, "SWAP_DEPOSIT", 10)
    has_sufficient_credits = (user_balance >= deposit)

    now = timezone.now()
    free_cancel_hours = getattr(settings, "SWAP_FREE_CANCEL_HOURS", 24)
    free_cancel_cutoff = (
        session.proposed_time - timezone.timedelta(hours=free_cancel_hours)
        if session.proposed_time
        else None
    )
    is_free_cancel = (now <= free_cancel_cutoff) if free_cancel_cutoff else True

    # User rating status
    existing_rating = SessionRating.objects.filter(session=session, rater=request.user).first()
    other_user_rating = SessionRating.objects.filter(
        session=session,
        rater=session.learner if is_teacher else session.teacher,
    ).first()

    context = {
        "session": session,
        "is_teacher": is_teacher,
        "is_learner": is_learner,
        "is_admin": is_admin,
        "user_balance": user_balance,
        "deposit": deposit,
        "has_sufficient_credits": has_sufficient_credits,
        "is_free_cancel": is_free_cancel,
        "free_cancel_cutoff": free_cancel_cutoff,
        "can_report_outcome": (
            session.status == SwapSession.Status.SCHEDULED
            and session.proposed_time
            and now >= session.proposed_time
        ),
        "existing_rating": existing_rating,
        "other_user_rating": other_user_rating,
        "rating_form": SessionRatingForm() if not existing_rating else None,
        "meeting_link_form": MeetingLinkForm(initial={"meeting_link": session.meeting_link}),
    }
    return render(request, "swaps/session_detail.html", context)


@login_required
def session_accept(request, pk):
    """Teacher accepts session and proposes time."""
    if request.method != "POST":
        return redirect("swaps:session_detail", pk=pk)

    session = get_object_or_404(SwapSession, pk=pk)
    time_str = request.POST.get("proposed_time")
    proposed_time = parse_datetime(time_str) if time_str else None

    try:
        accept_and_propose_time(session, request.user, proposed_time)
        messages.success(request, _("Session accepted and meeting time proposed!"))
    except (ValidationError, PermissionDenied) as e:
        msg = e.message if hasattr(e, "message") else str(e)
        messages.error(request, msg)

    return redirect("swaps:session_detail", pk=pk)


@login_required
def session_decline(request, pk):
    """Teacher declines session request."""
    if request.method != "POST":
        return redirect("swaps:session_detail", pk=pk)

    session = get_object_or_404(SwapSession, pk=pk)
    try:
        decline_session(session, request.user)
        messages.info(request, _("Session request declined."))
    except (ValidationError, PermissionDenied) as e:
        msg = e.message if hasattr(e, "message") else str(e)
        messages.error(request, msg)

    return redirect("swaps:session_detail", pk=pk)


@login_required
def session_propose_time(request, pk):
    """Participant proposes a different meeting time."""
    if request.method != "POST":
        return redirect("swaps:session_detail", pk=pk)

    session = get_object_or_404(SwapSession, pk=pk)
    time_str = request.POST.get("proposed_time")
    proposed_time = parse_datetime(time_str) if time_str else None

    try:
        propose_new_time(session, request.user, proposed_time)
        messages.success(request, _("New meeting time proposed."))
    except (ValidationError, PermissionDenied) as e:
        msg = e.message if hasattr(e, "message") else str(e)
        messages.error(request, msg)

    return redirect("swaps:session_detail", pk=pk)


@login_required
def session_confirm(request, pk):
    """Learner confirms time and deposits are locked."""
    if request.method != "POST":
        return redirect("swaps:session_detail", pk=pk)

    session = get_object_or_404(SwapSession, pk=pk)
    try:
        confirm_time(session, request.user)
        messages.success(request, _("Session scheduled! Deposit successfully held."))
    except InsufficientCreditsError as e:
        buy_url = reverse("payments:buy_credits")
        messages.error(
            request,
            _(f"{e.user.username} does not have enough credits ({e.current}/{e.required} nuts). "
              f"Please top up at <a href='{buy_url}' class='underline font-bold'>Buy nuts</a>.")
        )
    except (ValidationError, PermissionDenied) as e:
        msg = e.message if hasattr(e, "message") else str(e)
        messages.error(request, msg)

    return redirect("swaps:session_detail", pk=pk)


@login_required
def session_set_link(request, pk):
    """Teacher sets or edits the meeting link."""
    if request.method != "POST":
        return redirect("swaps:session_detail", pk=pk)

    session = get_object_or_404(SwapSession, pk=pk)
    link = request.POST.get("meeting_link", "")

    try:
        set_meeting_link(session, request.user, link)
        messages.success(request, _("Meeting link updated successfully."))
    except (ValidationError, PermissionDenied) as e:
        msg = e.message if hasattr(e, "message") else str(e)
        messages.error(request, msg)

    return redirect("swaps:session_detail", pk=pk)


@login_required
def session_cancel(request, pk):
    """Cancels a session."""
    if request.method != "POST":
        return redirect("swaps:session_detail", pk=pk)

    session = get_object_or_404(SwapSession, pk=pk)
    try:
        cancel_session(session, request.user)
        messages.info(request, _("Session cancelled."))
    except (ValidationError, PermissionDenied) as e:
        msg = e.message if hasattr(e, "message") else str(e)
        messages.error(request, msg)

    return redirect("swaps:session_detail", pk=pk)


@login_required
def session_report_outcome(request, pk):
    """Reports outcome: completed or no_show."""
    if request.method != "POST":
        return redirect("swaps:session_detail", pk=pk)

    session = get_object_or_404(SwapSession, pk=pk)
    outcome = request.POST.get("outcome")

    try:
        report_outcome(session, request.user, outcome)
        messages.success(request, _("Session outcome reported successfully."))
    except (ValidationError, PermissionDenied) as e:
        msg = e.message if hasattr(e, "message") else str(e)
        messages.error(request, msg)

    return redirect("swaps:session_detail", pk=pk)


@login_required
def session_rate(request, pk):
    """Submits a rating for a completed session."""
    if request.method != "POST":
        return redirect("swaps:session_detail", pk=pk)

    session = get_object_or_404(SwapSession, pk=pk)
    rating = request.POST.get("rating")
    comment = request.POST.get("comment", "")

    try:
        rate_session(session, request.user, rating, comment)
        messages.success(request, _("Thank you for your rating!"))
    except (ValidationError, PermissionDenied) as e:
        msg = e.message if hasattr(e, "message") else str(e)
        messages.error(request, msg)

    return redirect("swaps:session_detail", pk=pk)
