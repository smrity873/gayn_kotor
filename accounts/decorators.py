from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.utils.translation import gettext as _


def verified_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not getattr(request.user, "is_verified", False):
            messages.warning(
                request,
                _("Please verify your email address to access this feature."),
            )
            return redirect("core:home")
        return view_func(request, *args, **kwargs)

    return _wrapped_view
