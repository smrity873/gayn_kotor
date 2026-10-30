from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from notifications.services import notify

from .models import Batch, BatchMembership

User = get_user_model()


@login_required
def manage(request):
    user = request.user
    if user.is_superuser:
        batches = Batch.objects.all().select_related("department")
    elif user.class_teacher_of.exists():
        batches = user.class_teacher_of.select_related("department")
    elif (
        hasattr(user, "membership")
        and user.membership.is_cr
        and user.membership.status == BatchMembership.Status.APPROVED
    ):
        batches = Batch.objects.filter(pk=user.membership.batch_id).select_related("department")
    else:
        raise PermissionDenied

    items = []
    for batch in batches:
        memberships = batch.memberships.select_related("user").order_by("user__first_name")
        items.append({
            "batch": batch,
            "is_teacher": (user.is_superuser or batch.class_teacher_id == user.pk),
            "is_cr": (
                hasattr(user, "membership")
                and user.membership.batch_id == batch.pk
                and user.membership.is_cr
            ),
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
    )
    user = request.user
    batch = membership.batch
    target_user = membership.user
    action = request.POST.get("action")
    name = target_user.get_full_name() or target_user.username

    is_teacher = bool(user.is_superuser or batch.class_teacher_id == user.pk)
    is_cr = bool(
        hasattr(user, "membership")
        and user.membership.batch_id == batch.pk
        and user.membership.is_cr
        and user.membership.status == BatchMembership.Status.APPROVED
    )

    if action in ["approve", "reject", "make_cr", "remove_cr"]:
        if not is_teacher:
            raise PermissionDenied

        if action == "approve":
            membership.status = BatchMembership.Status.APPROVED
            membership.save()
            messages.success(request, f"{name} approved.")
            notify(
                target_user,
                f"Welcome to {batch}! You can now upload notes and see your batch.",
                reverse("notes:list"),
            )
        elif action == "reject":
            membership.status = BatchMembership.Status.REJECTED
            membership.is_cr = False
            membership.save()
            messages.info(request, f"{name} rejected.")
            notify(
                target_user,
                f"Your request to join {batch} was rejected. Please talk to your class teacher.",
                reverse("core:home"),
            )
        elif action == "make_cr" and membership.status == BatchMembership.Status.APPROVED:
            membership.is_cr = True
            membership.save()
            messages.success(request, f"{name} is now a CR.")
            notify(
                target_user,
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
                    target_user,
                    f"You are no longer a CR of {batch}.",
                    reverse("core:home"),
                )

    elif action == "suspend":
        if target_user.role == User.Role.LECTURER and not user.is_superuser:
            raise PermissionDenied
        if batch.class_teacher_id == target_user.pk:
            raise PermissionDenied

        if is_teacher:
            pass
        elif is_cr:
            if membership.is_cr or target_user.pk == user.pk:
                raise PermissionDenied
        else:
            raise PermissionDenied

        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "A reason is required to suspend a student.")
            return redirect("campus:manage")

        target_user.is_active = False
        target_user.suspended_at = timezone.now()
        target_user.suspended_by = user
        target_user.suspension_reason = reason
        target_user.save(update_fields=["is_active", "suspended_at", "suspended_by", "suspension_reason"])

        notify(
            target_user,
            f"Your account has been suspended: {reason}",
            reverse("core:home"),
        )
        messages.success(request, f"{name} has been suspended.")

    elif action == "reactivate":
        if not is_teacher:
            raise PermissionDenied

        target_user.is_active = True
        target_user.suspended_at = None
        target_user.suspended_by = None
        target_user.suspension_reason = ""
        target_user.save(update_fields=["is_active", "suspended_at", "suspended_by", "suspension_reason"])

        notify(
            target_user,
            "Your account has been reactivated.",
            reverse("core:home"),
        )
        messages.success(request, f"{name} has been reactivated.")

    else:
        messages.error(request, "Invalid action.")

    return redirect("campus:manage")
