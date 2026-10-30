from django import forms
from django.conf import settings

from accounts.forms import INPUT_CLASSES
from accounts.models import User

from .models import Note

FILE_CLASSES = (
    "w-full rounded-xl border border-green-200 bg-white px-4 py-2 text-sm text-green-950 "
    "file:mr-4 file:rounded-full file:border-0 file:bg-green-600 file:px-4 file:py-1.5 "
    "file:font-semibold file:text-white hover:file:bg-green-700 "
    "dark:border-green-800 dark:bg-canvas-dark dark:text-green-50"
)


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ("title", "course_code", "department", "semester", "description", "visibility", "file")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        for name, field in self.fields.items():
            field.widget.attrs["class"] = FILE_CLASSES if name == "file" else INPUT_CLASSES

        self.fields["file"].widget.attrs["accept"] = "application/pdf"
        self.fields["file"].help_text = f"PDF only, up to {getattr(settings, 'NOTE_MAX_UPLOAD_MB', 20)} MB."

        if user is not None and user.role == User.Role.LECTURER:
            self.fields["visibility"].choices = [
                c for c in Note.Visibility.choices if c[0] != Note.Visibility.BATCH
            ]

        membership = getattr(user, "membership", None)
        if membership is not None and not self.is_bound:
            self.fields["department"].initial = membership.batch.department_id

    def clean_course_code(self):
        return self.cleaned_data["course_code"].strip().upper()

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            from .models import validate_file_size, validate_pdf_header
            validate_file_size(file)
            validate_pdf_header(file)
        return file