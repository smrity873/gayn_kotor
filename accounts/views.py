from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from .forms import SignUpForm


def signup(request):
    if request.user.is_authenticated:
        return redirect("core:home")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            if user.is_active:
                messages.success(request, _("Account created successfully!"))
            else:
                messages.info(
                    request,
                    _("Account created. A lecturer account must be approved by the admin before you can log in."),
                )
            return redirect("core:home")
    else:
        form = SignUpForm()

    return render(request, "accounts/signup.html", {"form": form})