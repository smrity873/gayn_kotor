from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User

INPUT_CLASSES = (
    "w-full rounded-xl border border-green-200 bg-white px-4 py-2.5 "
    "text-green-950 outline-none transition focus:border-green-500 "
    "focus:ring-2 focus:ring-green-500/30 "
    "dark:border-green-800 dark:bg-canvas-dark dark:text-green-50"
)


class SignUpForm(UserCreationForm):
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

    def save(self, commit=True):
        user = super().save(commit=False)
        if user.role == User.Role.LECTURER:
            user.is_active = False
        if commit:
            user.save()
        return user

class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username"
        for field in self.fields.values():
            field.widget.attrs["class"] = INPUT_CLASSES