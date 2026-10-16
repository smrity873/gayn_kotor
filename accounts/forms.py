from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from campus.models import Batch, BatchMembership

from .models import User

INPUT_CLASSES = (
    "w-full rounded-xl border border-green-200 bg-white px-4 py-2.5 "
    "text-green-950 outline-none transition focus:border-green-500 "
    "focus:ring-2 focus:ring-green-500/30 "
    "dark:border-green-800 dark:bg-canvas-dark dark:text-green-50"
)


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
        return user


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username"
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASSES