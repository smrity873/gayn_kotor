from django import forms
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.core.cache import cache
from django.urls import reverse

from campus.models import Batch, BatchMembership
from notifications.services import notify

from .models import User

INPUT_CLASSES = (
    "w-full rounded-xl border border-green-200 bg-white px-4 py-2.5 "
    "text-green-950 outline-none transition focus:border-green-500 "
    "focus:ring-2 focus:ring-green-500/30 "
    "dark:border-green-800 dark:bg-canvas-dark dark:text-green-50"
)


def get_client_ip(request):
    if not request:
        return "127.0.0.1"
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


class SignUpForm(UserCreationForm):
    batch = forms.ModelChoiceField(
        queryset=Batch.objects.select_related("department"),
        required=False,
        empty_label="Select your batch",
        label="Batch",
        help_text="Students only. Your class teacher will approve your request.",
    )

    field_order = [
        "first_name", "last_name", "username", "email",
        "role", "id_number", "batch", "password1", "password2",
    ]

    class Meta:
        model = User
        fields = ("first_name", "last_name", "username", "email", "role", "id_number")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["role"].label = "I am a"
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASSES

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        allowed_domains = getattr(settings, "ALLOWED_EMAIL_DOMAINS", [])
        if allowed_domains:
            domain = email.split("@")[-1] if "@" in email else ""
            if domain not in allowed_domains:
                raise forms.ValidationError(
                    f"Registration is restricted to the following email domains: {', '.join(allowed_domains)}"
                )
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("role") == User.Role.STUDENT and not cleaned.get("batch"):
            self.add_error("batch", "Please select your batch.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if user.role == User.Role.LECTURER:
            user.is_active = False
        if commit:
            user.save()
            batch = self.cleaned_data.get("batch")
            if user.role == User.Role.STUDENT and batch:
                BatchMembership.objects.create(user=user, batch=batch)
                if batch.class_teacher_id:
                    notify(
                        batch.class_teacher,
                        f"New join request: {user.get_full_name() or user.username} wants to join {batch}.",
                        reverse("campus:manage"),
                    )
        return user


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username"
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASSES

    def clean(self):
        username = self.cleaned_data.get("username", "").strip()
        password = self.cleaned_data.get("password")

        if username and password:
            client_ip = get_client_ip(self.request)
            throttle_key = f"login_failed_{username.lower()}_{client_ip}"
            failed_count = cache.get(throttle_key, 0)
            if failed_count >= 5:
                raise forms.ValidationError(
                    "Too many failed login attempts. Please try again in 15 minutes."
                )

            self.user_cache = authenticate(
                self.request, username=username, password=password
            )

            if self.user_cache is None:
                cache.set(throttle_key, failed_count + 1, timeout=15 * 60)

                matched_user = User.objects.filter(username__iexact=username).first()
                if matched_user and matched_user.check_password(password):
                    if matched_user.suspended_at or matched_user.suspension_reason:
                        raise forms.ValidationError(
                            f"Your account has been suspended. Reason: {matched_user.suspension_reason or 'No reason provided.'}"
                        )
                    if not matched_user.is_active:
                        if matched_user.role == User.Role.LECTURER:
                            raise forms.ValidationError(
                                "Your lecturer account is pending administrator approval."
                            )
                        raise forms.ValidationError("This account is inactive.")

                raise self.get_invalid_login_error()
            else:
                self.confirm_login_allowed(self.user_cache)
                cache.delete(throttle_key)

        return self.cleaned_data


class StyledPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASSES


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASSES


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASSES
