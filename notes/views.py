from django.conf import settings
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, F
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from accounts.decorators import verified_required
from accounts.models import User
from campus.models import Department
from credits.models import CreditLedger
from credits.services import add_entry, get_balance

from .forms import NoteForm
from notifications.services import notify
from .models import Note, NoteDownload, NoteRating, NoteAppeal, NoteReport
from .services import (
    approve_note,
    can_review,
    can_upload,
    can_view_note,
    make_preview,
    reject_note,
    reviewable_notes,
    reviewer_batch_ids,
    search_notes,
    visible_notes,
    publish_overdue_notes,
    trigger_deadlines_lazy,
    remove_note,
    can_remove_note,
)

UPLOAD_REWARD = 10
DOWNLOAD_COST = 5
RATER_REWARD = 1
OWNER_REWARD = 5
RATER_DAILY_CAP = 5
OWNER_DAILY_CAP = 10


@login_required
def note_list(request):
    trigger_deadlines_lazy()
    tab = "mine" if request.GET.get("tab") == "mine" else "all"

    if tab == "mine":
        notes = Note.objects.filter(owner=request.user).select_related("owner", "department", "batch")
    else:
        notes = visible_notes(request.user)

    q = request.GET.get("q", "").strip()
    department = request.GET.get("department", "")
    semester = request.GET.get("semester", "")

    notes = search_notes(notes, q)
    if department.isdigit():
        notes = notes.filter(department_id=int(department))
    if semester.isdigit():
        notes = notes.filter(semester=int(semester))

    page = Paginator(notes, 12).get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    allowed, hint = can_upload(request.user)

    context = {
        "page": page,
        "tab": tab,
        "q": q,
        "department": department,
        "semester": semester,
        "departments": Department.objects.all(),
        "semesters": range(1, 13),
        "querystring": params.urlencode(),
        "can_upload": allowed,
        "upload_hint": hint,
    }
    return render(request, "notes/list.html", context)


@login_required
def note_preview(request, pk):
    note = get_object_or_404(Note, pk=pk)
    if not can_view_note(request.user, note):
        raise Http404

    if not note.preview:
        make_preview(note)
    if not note.preview:
        raise Http404

    response = FileResponse(note.preview.open("rb"), content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=86400"
    return response


@login_required
@verified_required
def upload(request):
    user = request.user
    allowed, hint = can_upload(user)
    if not allowed:
        messages.info(request, hint)
        return redirect("notes:list")

    batch = None
    if user.role == User.Role.STUDENT:
        batch = user.membership.batch

    if request.method == "POST":
        form = NoteForm(request.POST, request.FILES, user=user)
        if form.is_valid():
            note = form.save(commit=False)
            note.owner = user
            note.batch = batch
            note.save()
            make_preview(note)

            if user.role == User.Role.LECTURER:
                approve_note(note)
                messages.success(request, "Note published! You earned 10 nuts.")
            else:
                messages.success(request, "Note submitted. Your CR will review it soon.")
            return redirect("notes:list")
    else:
        form = NoteForm(user=user)

    return render(request, "notes/upload.html", {"form": form})


@login_required
def review_list(request):
    if not (request.user.is_superuser or reviewer_batch_ids(request.user)):
        raise PermissionDenied
    trigger_deadlines_lazy()
    notes = reviewable_notes(request.user).order_by(F("escalated_at").desc(nulls_last=True), "created_at")
    return render(request, "notes/review_list.html", {"notes": notes})


@login_required
def review_detail(request, pk):
    note = get_object_or_404(Note, pk=pk)
    if not can_review(request.user, note):
        raise Http404
    return render(request, "notes/review_detail.html", {"note": note})

@login_required
@require_POST
def review_action(request, pk):
    note = get_object_or_404(Note, pk=pk)
    is_reviewer = request.user.is_superuser or (
        note.batch_id and note.batch_id in reviewer_batch_ids(request.user) and note.owner_id != request.user.id
    )
    if not is_reviewer:
        raise Http404

    action = request.POST.get("action")
    if action == "reject":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "Please write a reason for rejecting the note.")
            return redirect("notes:review_detail", pk=pk)

    with transaction.atomic():
        locked_note = Note.objects.select_for_update().get(pk=note.pk)
        if locked_note.status not in (Note.Status.PENDING, Note.Status.UNVERIFIED):
            messages.info(request, "This note was already decided by another reviewer.")
            return redirect("notes:review_list")

        owner_name = locked_note.owner.get_full_name() or locked_note.owner.username
        if action == "approve":
            paid = approve_note(locked_note, reviewer=request.user)
            if paid:
                messages.success(request, f"Approved. {owner_name} earned 10 nuts.")
            else:
                messages.success(request, "Approved.")
        elif action == "reject":
            reject_note(locked_note, request.user, reason)
            messages.info(request, f"Rejected. {owner_name} can see your reason.")

    return redirect("notes:review_list")

@login_required
@xframe_options_sameorigin
def note_file(request, pk):
    note = get_object_or_404(Note, pk=pk)
    user = request.user
    is_privileged = note.owner_id == user.id or user.is_superuser
    if note.status == Note.Status.REMOVED and not is_privileged:
        raise Http404

    has_downloaded = NoteDownload.objects.filter(user=user, note=note).exists()
    is_reviewer = note.batch_id and note.batch_id in reviewer_batch_ids(user)

    if not (is_privileged or is_reviewer or has_downloaded):
        raise Http404

    return FileResponse(note.file.open("rb"), content_type="application/pdf")


def earned_today(user, reason):
    return CreditLedger.objects.filter(
        user=user, reason=reason, created_at__date=timezone.localdate()
    ).count()


@login_required
def note_detail(request, pk):
    note = get_object_or_404(
        Note.objects.select_related("owner", "department", "batch"), pk=pk
    )
    user = request.user
    if not can_view_note(user, note):
        raise Http404

    is_owner = note.owner_id == user.id
    has_downloaded = (not is_owner) and NoteDownload.objects.filter(user=user, note=note).exists()
    my_rating = NoteRating.objects.filter(user=user, note=note).first()
    stats = NoteRating.objects.filter(note=note).aggregate(avg=Avg("rating"), count=Count("id"))
    reviews = NoteRating.objects.filter(note=note).select_related("user").order_by("-id")[:10]

    can_remove = can_remove_note(user, note)
    has_reported = user.is_authenticated and (not is_owner) and NoteReport.objects.filter(user=user, note=note).exists()

    return render(request, "notes/note_detail.html", {
        "note": note,
        "is_owner": is_owner,
        "has_downloaded": has_downloaded,
        "my_rating": my_rating,
        "can_rate": has_downloaded and my_rating is None,
        "avg_rating": stats["avg"],
        "rating_count": stats["count"],
        "reviews": reviews,
        "download_cost": DOWNLOAD_COST,
        "can_afford": get_balance(user) >= DOWNLOAD_COST,
        "can_remove": can_remove,
        "has_reported": has_reported,
        "report_reasons": NoteReport.Reason.choices,
    })


@login_required
@require_POST
@verified_required
def note_download(request, pk):
    note = get_object_or_404(Note, pk=pk)
    user = request.user

    if note.owner_id == user.id or user.is_superuser:
        return redirect("notes:file", pk=note.pk)

    if not visible_notes(user).filter(pk=note.pk).exists():
        raise Http404

    try:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            _, created = NoteDownload.objects.get_or_create(user=user, note=note)
            if created:
                add_entry(
                    user,
                    -DOWNLOAD_COST,
                    CreditLedger.Reason.NOTE_DOWNLOAD,
                    f"Unlocked note: {note.title}",
                )
                Note.objects.filter(pk=note.pk).update(download_count=F("download_count") + 1)

                locked_note = Note.objects.select_for_update().get(pk=note.pk)
                if locked_note.status == Note.Status.UNVERIFIED and not locked_note.reward_paid:
                    downloads_count = NoteDownload.objects.filter(note=locked_note).count()
                    threshold = getattr(settings, "NOTE_UNVERIFIED_REWARD_DOWNLOADS", 3)
                    if downloads_count >= threshold:
                        locked_note.reward_paid = True
                        locked_note.save(update_fields=["reward_paid"])
                        add_entry(
                            locked_note.owner,
                            UPLOAD_REWARD,
                            CreditLedger.Reason.NOTE_UPLOAD,
                            f'Upload reward for "{locked_note.title}" released after {downloads_count} downloads',
                            notify=False,
                        )
                        notify(
                            locked_note.owner,
                            f'Your unverified note "{locked_note.title}" reached {downloads_count} downloads! You earned {UPLOAD_REWARD} nuts.',
                            reverse("notes:detail", args=[locked_note.pk]),
                        )
    except ValueError:
        messages.error(request, f"You need {DOWNLOAD_COST} nuts to unlock this note.")
        return redirect("notes:detail", pk=note.pk)

    if created:
        messages.success(request, f"Note unlocked! {DOWNLOAD_COST} nuts were used.")
    return redirect("notes:file", pk=note.pk)


@login_required
@require_POST
@verified_required
def note_rate(request, pk):
    note = get_object_or_404(Note, pk=pk)
    user = request.user
    back = redirect("notes:detail", pk=note.pk)

    if note.owner_id == user.id:
        messages.error(request, "You cannot rate your own note.")
        return back

    try:
        value = int(request.POST.get("rating", 0))
    except ValueError:
        value = 0
    if not 1 <= value <= 5:
        messages.error(request, "Please choose a rating from 1 to 5.")
        return back
    review_text = request.POST.get("review", "").strip()[:500]

    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)

        if not NoteDownload.objects.filter(user=user, note=note).exists():
            messages.error(request, "You must unlock the note before rating it.")
            return back
        if NoteRating.objects.filter(user=user, note=note).exists():
            messages.error(request, "You have already rated this note.")
            return back

        max_raters = getattr(settings, "NOTE_MAX_REWARDED_RATERS", 10)
        rewarded_raters_count = NoteRating.objects.filter(note=note, owner_rewarded=True).count()
        can_reward_owner = rewarded_raters_count < max_raters

        owner_paid = can_reward_owner and (earned_today(note.owner, CreditLedger.Reason.RATING_RECEIVED) < OWNER_DAILY_CAP)

        NoteRating.objects.create(
            user=user,
            note=note,
            rating=value,
            review=review_text,
            owner_rewarded=can_reward_owner,
        )

        rater_paid = earned_today(user, CreditLedger.Reason.RATING_GIVEN) < RATER_DAILY_CAP
        if rater_paid:
            add_entry(user, RATER_REWARD, CreditLedger.Reason.RATING_GIVEN, f"Rated note: {note.title}", notify=False)
        if owner_paid:
            add_entry(note.owner, OWNER_REWARD, CreditLedger.Reason.RATING_RECEIVED, f"Rating on note: {note.title}", notify=False)

        owner_nuts = OWNER_REWARD if owner_paid else 0
        notify(
            note.owner,
            f'Your note "{note.title}" received a {value}-star rating and {owner_nuts} nuts!',
            reverse("notes:detail", args=[note.pk]),
        )

    if rater_paid:
        messages.success(request, f"Thanks for rating! You earned {RATER_REWARD} nut.")
    else:
        messages.success(request, "Thanks for rating! You reached today's nut limit for ratings.")
    return back

@login_required
@verified_required
def note_appeal(request, pk):
    note = get_object_or_404(Note, pk=pk)
    if note.owner_id != request.user.id or note.status != Note.Status.REJECTED:
        raise PermissionDenied("You can only appeal rejected notes that belong to you.")

    if NoteAppeal.objects.filter(note=note, status=NoteAppeal.Status.OPEN).exists():
        messages.info(request, "An appeal is already pending review for this note.")
        return redirect(f"{reverse('notes:list')}?tab=mine")

    if request.method == "POST":
        message = request.POST.get("message", "").strip()[:500]
        if not message:
            messages.error(request, "Please enter a message explaining why this rejection should be reviewed.")
            return render(request, "notes/note_appeal.html", {"note": note})

        NoteAppeal.objects.create(note=note, user=request.user, message=message)
        if note.batch and note.batch.class_teacher:
            notify(
                note.batch.class_teacher,
                f'Appeal submitted for rejected note "{note.title}" by {request.user.get_full_name() or request.user.username}.',
                reverse("notes:appeals_list"),
            )
        messages.success(request, "Your appeal has been submitted to your class teacher.")
        return redirect(f"{reverse('notes:list')}?tab=mine")

    return render(request, "notes/note_appeal.html", {"note": note})


@login_required
def appeals_list(request):
    if not (request.user.is_superuser or request.user.class_teacher_of.exists()):
        raise PermissionDenied("Only class teachers can review appeals.")

    if request.user.is_superuser:
        appeals = NoteAppeal.objects.all().select_related("note", "user", "decided_by", "note__batch")
    else:
        teacher_batches = request.user.class_teacher_of.all()
        appeals = NoteAppeal.objects.filter(note__batch__in=teacher_batches).select_related(
            "note", "user", "decided_by", "note__batch"
        )

    from django.db.models import Case, When, Value, IntegerField
    appeals = appeals.annotate(
        is_open=Case(
            When(status=NoteAppeal.Status.OPEN, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by("is_open", "-created_at")

    return render(request, "notes/appeals_list.html", {"appeals": appeals})


@login_required
@require_POST
def appeal_action(request, pk):
    appeal = get_object_or_404(NoteAppeal.objects.select_related("note", "note__batch", "user"), pk=pk)
    is_teacher = appeal.note.batch and appeal.note.batch.class_teacher_id == request.user.id
    if not (request.user.is_superuser or is_teacher):
        raise PermissionDenied

    if appeal.status != NoteAppeal.Status.OPEN:
        messages.info(request, "This appeal has already been decided.")
        return redirect("notes:appeals_list")

    action = request.POST.get("action")
    decision_note = request.POST.get("decision_note", "").strip()

    if action == "uphold" and not decision_note:
        messages.error(request, "Upholding an appeal requires a reason.")
        return redirect("notes:appeals_list")

    with transaction.atomic():
        locked_appeal = NoteAppeal.objects.select_for_update().get(pk=pk)
        if locked_appeal.status != NoteAppeal.Status.OPEN:
            messages.info(request, "This appeal has already been decided.")
            return redirect("notes:appeals_list")

        locked_appeal.decided_by = request.user
        locked_appeal.decided_at = timezone.now()
        locked_appeal.decision_note = decision_note

        teacher_name = request.user.get_full_name() or request.user.username

        if action == "grant":
            locked_appeal.status = NoteAppeal.Status.GRANTED
            locked_appeal.save()
            approve_note(locked_appeal.note, reviewer=request.user)
            notify(
                locked_appeal.user,
                f'Your appeal for "{locked_appeal.note.title}" was granted! The note is approved.',
                reverse("notes:detail", args=[locked_appeal.note.pk]),
            )
            if locked_appeal.note.reviewed_by and locked_appeal.note.reviewed_by_id != request.user.id:
                notify(
                    locked_appeal.note.reviewed_by,
                    f'The rejection for "{locked_appeal.note.title}" was overturned on appeal by class teacher {teacher_name}.',
                    reverse("notes:detail", args=[locked_appeal.note.pk]),
                )
            messages.success(request, f'Appeal granted. "{locked_appeal.note.title}" is now approved.')
        elif action == "uphold":
            locked_appeal.status = NoteAppeal.Status.UPHELD
            locked_appeal.save()
            notify(
                locked_appeal.user,
                f'Your appeal for "{locked_appeal.note.title}" was upheld. Reason: {decision_note}',
                f"{reverse('notes:list')}?tab=mine",
            )
            if locked_appeal.note.reviewed_by and locked_appeal.note.reviewed_by_id != request.user.id:
                notify(
                    locked_appeal.note.reviewed_by,
                    f'The appeal for "{locked_appeal.note.title}" was reviewed and upheld by class teacher {teacher_name}.',
                )
            messages.info(request, f'Appeal upheld. "{locked_appeal.note.title}" remains rejected.')

    return redirect("notes:appeals_list")


@login_required
@verified_required
@require_POST
def report_note(request, pk):
    note = get_object_or_404(Note, pk=pk)
    if not can_view_note(request.user, note):
        raise Http404

    if note.owner_id == request.user.id:
        messages.error(request, "You cannot report your own note.")
        return redirect("notes:detail", pk=pk)

    reason = request.POST.get("reason", NoteReport.Reason.OTHER)
    if reason not in NoteReport.Reason.values:
        reason = NoteReport.Reason.OTHER
    details = request.POST.get("details", "").strip()[:500]

    existing = NoteReport.objects.filter(note=note, user=request.user).first()
    if existing:
        messages.info(request, "You have already reported this note.")
        return redirect("notes:detail", pk=pk)

    NoteReport.objects.create(note=note, user=request.user, reason=reason, details=details)
    messages.success(request, "Thank you. Your report has been submitted.")

    distinct_reporters = NoteReport.objects.filter(note=note).count()
    threshold = getattr(settings, "NOTE_REPORT_THRESHOLD", 3)
    if distinct_reporters >= threshold and note.status != Note.Status.FLAGGED:
        note.status_before_flag = note.status
        note.status = Note.Status.FLAGGED
        note.save(update_fields=["status", "status_before_flag"])
        if note.batch and note.batch.class_teacher:
            notify(
                note.batch.class_teacher,
                f'Note "{note.title}" in {note.batch.name} was flagged after {distinct_reporters} reports.',
                reverse("notes:flagged_list"),
            )

    return redirect("notes:detail", pk=pk)


@login_required
def flagged_list(request):
    if not (request.user.is_superuser or request.user.class_teacher_of.exists()):
        raise PermissionDenied("Only class teachers can view flagged notes.")

    if request.user.is_superuser:
        flagged_notes = Note.objects.filter(status=Note.Status.FLAGGED).select_related(
            "owner", "batch", "department"
        ).prefetch_related("reports", "reports__user")
    else:
        batches = request.user.class_teacher_of.all()
        flagged_notes = Note.objects.filter(status=Note.Status.FLAGGED, batch__in=batches).select_related(
            "owner", "batch", "department"
        ).prefetch_related("reports", "reports__user")

    return render(request, "notes/flagged_list.html", {"flagged_notes": flagged_notes})


@login_required
@require_POST
def flagged_action(request, pk):
    note = get_object_or_404(Note.objects.select_related("batch", "owner"), pk=pk)
    is_teacher = note.batch and note.batch.class_teacher_id == request.user.id
    if not (request.user.is_superuser or is_teacher):
        raise PermissionDenied

    action = request.POST.get("action")
    if action == "dismiss":
        note.status = note.status_before_flag or Note.Status.APPROVED
        note.status_before_flag = None
        note.save(update_fields=["status", "status_before_flag"])
        NoteReport.objects.filter(note=note, resolved_at__isnull=True).update(
            resolved_at=timezone.now(), resolved_by=request.user
        )
        messages.success(request, f'Flags on "{note.title}" dismissed and note restored.')
    elif action == "remove":
        reason = request.POST.get("reason", "").strip() or "Violates community guidelines"
        reverse_reward = request.POST.get("reverse_reward") in ("1", "true", "True", "on")
        remove_note(note, by=request.user, reason=reason, reverse_reward=reverse_reward)
        NoteReport.objects.filter(note=note, resolved_at__isnull=True).update(
            resolved_at=timezone.now(), resolved_by=request.user
        )
        messages.success(request, f'Note "{note.title}" removed.')

    return redirect("notes:flagged_list")


@login_required
@require_POST
def remove_note_view(request, pk):
    note = get_object_or_404(Note, pk=pk)
    if not can_remove_note(request.user, note):
        raise PermissionDenied

    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "A reason is required to remove this note.")
        return redirect("notes:detail", pk=pk)

    reverse_reward = request.POST.get("reverse_reward") in ("1", "true", "True", "on")
    remove_note(note, by=request.user, reason=reason, reverse_reward=reverse_reward)
    messages.success(request, f'Note "{note.title}" removed.')
    return redirect("notes:list")
