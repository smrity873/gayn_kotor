from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from notifications.services import notify

from .models import Batch, BatchMembership


@login_required
def manage(request):
    batches = Batch.objects.filter(class_teacher=request.user).select_related("department")
    if not batches.exists():
        raise PermissionDenied

    items = []
    for batch in batches:
        memberships = batch.memberships.select_related("user").order_by("user__first_name")
        items.append({
            "batch": batch,
            "pending": memberships.filter(status=BatchMembership.Status.PENDING),
            "members": memberships.filter(status=BatchMembership.Status.APPROVED),
        })
    return render(request, "campus/manage.html", {"items": items})


@login_required
@require_POST
def membership_action(request, pk):
    membership = get_object_or_404(
        BatchMembership.objects.select_related("user", "batch"),
        pk=pk,
        batch__class_teacher=request.user,
    )
    action = request.POST.get("action")
    name = membership.user.get_full_name() or membership.user.username
    batch = membership.batch

    if action == "approve":
        membership.status = BatchMembership.Status.APPROVED
        membership.save()
        messages.success(request, f"{name} approved.")
        notify(
            membership.user,
            f"Welcome to {batch}! You can now upload notes and see your batch.",
            reverse("notes:list"),
        )
    elif action == "reject":
        membership.status = BatchMembership.Status.REJECTED
        membership.is_cr = False
        membership.save()
        messages.info(request, f"{name} rejected.")
        notify(
            membership.user,
            f"Your request to join {batch} was rejected. Please talk to your class teacher.",
            reverse("core:home"),
        )
    elif action == "make_cr" and membership.status == BatchMembership.Status.APPROVED:
        membership.is_cr = True
        membership.save()
        messages.success(request, f"{name} is now a CR.")
        notify(
            membership.user,
            f"You are now a CR of {batch}. You can review notes of your batch.",
            reverse("notes:review_list"),
        )
    elif action == "remove_cr":
        was_cr = membership.is_cr
        membership.is_cr = False
        membership.save()
        messages.info(request, f"{name} is no longer a CR.")
        if was_cr:
            notify(
                membership.user,
                f"You are no longer a CR of {batch}.",
                reverse("core:home"),
            )

    return redirect("campus:manage")