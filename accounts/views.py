from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from credits.services import grant_signup_bonus

from .forms import SignUpForm
from .services import send_verification_email, verify_token

User = get_user_model()


def signup(request):
    if request.user.is_authenticated:
        return redirect("core:home")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            send_verification_email(user, request=request)
            if user.is_active:
                messages.success(
                    request,
                    _("Account created successfully! We sent a verification link to your email."),
                )
            else:
                messages.info(
                    request,
                    _("Account created. A lecturer account must be approved by the admin before you can log in. A verification link has also been sent to your email."),
                )
            return redirect("core:home")
    else:
        form = SignUpForm()

    return render(request, "accounts/signup.html", {"form": form})


def verify_email(request, token):
    result = verify_token(token)
    if not result:
        messages.error(request, _("The verification link is invalid or has expired."))
        return redirect("core:home")

    user_pk, user_email = result
    user = get_object_or_404(User, pk=user_pk)

    if user.email.lower() != user_email.lower():
        messages.error(request, _("The verification link is invalid for this account."))
        return redirect("core:home")

    if user.email_verified_at:
        messages.info(request, _("Your email is already verified."))
        return redirect("core:home")

    user.email_verified_at = timezone.now()
    user.is_email_verified = True
    user.save(update_fields=["email_verified_at", "is_email_verified"])

    grant_signup_bonus(user)

    messages.success(request, _("Email verified successfully! You have received 30 welcome nuts."))
    return redirect("core:home")


@login_required
def resend_verification(request):
    if request.user.email_verified_at:
        messages.info(request, _("Your email is already verified."))
        return redirect("core:home")

    cache_key = f"resend_verification_{request.user.pk}"
    if cache.get(cache_key):
        messages.warning(request, _("Please wait a minute before requesting another verification email."))
        return redirect("core:home")

    send_verification_email(request.user, request=request)
    cache.set(cache_key, True, timeout=60)
    messages.success(request, _("Verification email sent! Please check your inbox."))
    return redirect("core:home")


@login_required
def profile(request):
    user = request.user
    context = {
        "profile_user": user,
    }
    if user.role == User.Role.STUDENT and hasattr(user, "membership"):
        context["membership"] = user.membership
        context["batch"] = user.membership.batch
        context["department"] = user.membership.batch.department
    elif user.role == User.Role.LECTURER:
        context["batches"] = user.class_teacher_of.select_related("department").all()

    return render(request, "accounts/profile.html", context)
