from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from accounts.models import User
from campus.models import Department
from credits.services import add_entry, get_balance

from .forms import NoteForm
from .models import Note, NoteDownload, NoteRating
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
)


@login_required
def note_list(request):
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
    notes = reviewable_notes(request.user).order_by("created_at")
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
    if not can_review(request.user, note):
        raise Http404

    owner_name = note.owner.get_full_name() or note.owner.username
    action = request.POST.get("action")

    if action == "approve":
        approve_note(note, reviewer=request.user)
        messages.success(request, f"Approved. {owner_name} earned 10 nuts.")
    elif action == "reject":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "Please write a reason for rejecting the note.")
            return redirect("notes:review_detail", pk=pk)
        reject_note(note, request.user, reason)
        messages.info(request, f"Rejected. {owner_name} can see your reason.")

    return redirect("notes:review_list")


@login_required
@xframe_options_sameorigin
def note_file(request, pk):
    note = get_object_or_404(Note, pk=pk)
    user = request.user
    
    # Check if user has already downloaded/unlocked the note
    has_downloaded = NoteDownload.objects.filter(user=user, note=note).exists()
    
    # Allow access if owner, superuser, reviewer, OR has downloaded
    if not (note.owner_id == user.id or user.is_superuser or can_review(user, note) or has_downloaded):
        raise Http404
        
    return FileResponse(note.file.open("rb"), content_type="application/pdf")


@login_required
def note_detail(request, pk):
    note = get_object_or_404(Note, pk=pk)
    is_owner = (request.user == note.owner)
    
    has_downloaded = False
    if not is_owner:
        has_downloaded = NoteDownload.objects.filter(user=request.user, note=note).exists()
    
    return render(request, 'notes/note_detail.html', {
        'note': note,
        'is_owner': is_owner,
        'has_downloaded': has_downloaded,
    })


@login_required
@require_POST
def note_download(request, pk):
    note = get_object_or_404(Note, pk=pk)
    
    # If user is the owner, allow free access
    if request.user == note.owner:
        return redirect('notes:file', pk=note.pk)
        
    # Check if already unlocked
    has_downloaded = NoteDownload.objects.filter(user=request.user, note=note).exists()
    if has_downloaded:
        return redirect('notes:file', pk=note.pk)
        
    # 1. Check if the user has enough balance
    if get_balance(request.user) < 5:
        messages.error(request, "You do not have enough nuts! You need at least 5 nuts to unlock this note.")
        return redirect('notes:detail', pk=note.pk)
        
    # 2. Deduct 5 nuts using the credit service
    try:
        add_entry(
            user=request.user, 
            amount=-5, 
            reason="note_download", 
            description=f"Unlocked note: {note.title}"
        )
    except ValueError:
        messages.error(request, "Error processing your nuts. Please try again.")
        return redirect('notes:detail', pk=note.pk)
    
    # 3. Save download record
    NoteDownload.objects.create(user=request.user, note=note)
    messages.success(request, "Note unlocked successfully! 5 nuts have been deducted.")
    
    return redirect('notes:file', pk=note.pk)

@login_required
@require_POST
def note_rate(request, pk):
    note = get_object_or_404(Note, pk=pk)
    
    # Owner cannot rate their own note
    if request.user == note.owner:
        messages.error(request, "You cannot rate your own note.")
        return redirect('notes:detail', pk=note.pk)
        
    # User must unlock/download the note before rating
    has_downloaded = NoteDownload.objects.filter(user=request.user, note=note).exists()
    if not has_downloaded:
        messages.error(request, "You must unlock the note before rating it.")
        return redirect('notes:detail', pk=note.pk)
        
    # Check if already rated
    if NoteRating.objects.filter(user=request.user, note=note).exists():
        messages.error(request, "You have already rated this note.")
        return redirect('notes:detail', pk=note.pk)
        
    # Get rating value from form
    try:
        rating_val = int(request.POST.get('rating', 0))
        if rating_val < 1 or rating_val > 5:
            raise ValueError
    except ValueError:
        messages.error(request, "Invalid rating. Please select between 1 and 5.")
        return redirect('notes:detail', pk=note.pk)
        
    review_text = request.POST.get('review', '').strip()
    
    # Save the rating
    NoteRating.objects.create(
        user=request.user,
        note=note,
        rating=rating_val,
        review=review_text
    )
    
    # Reward credits (1 nut to rater, 5 nuts to uploader)
    try:
        add_entry(
            user=request.user, 
            amount=1, 
            reason="rating_given", 
            description=f"Rated note: {note.title}"
        )
        add_entry(
            user=note.owner, 
            amount=5, 
            reason="rating_received", 
            description=f"Received rating on note: {note.title}"
        )
    except Exception:
        pass # Ignore if there's any ledger error, but rating is already saved
        
    messages.success(request, "Thank you for rating! You earned 1 nut and the uploader received 5 nuts.")
    return redirect('notes:detail', pk=note.pk)