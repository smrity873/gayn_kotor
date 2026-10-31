from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.forms import INPUT_CLASSES

from .models import SessionRating, SkillPost, SwapSession
from .services import validate_meeting_link


class SkillPostForm(forms.ModelForm):
    class Meta:
        model = SkillPost
        fields = ["kind", "skill_name", "description"]
        widgets = {
            "kind": forms.Select(attrs={"class": INPUT_CLASSES}),
            "skill_name": forms.TextInput(attrs={
                "class": INPUT_CLASSES,
                "placeholder": _("e.g. Python Programming, Organic Chemistry, Guitar Basics"),
            }),
            "description": forms.Textarea(attrs={
                "class": INPUT_CLASSES,
                "rows": 4,
                "placeholder": _("Describe what you can teach or what you hope to learn..."),
            }),
        }


class ProposeTimeForm(forms.Form):
    proposed_time = forms.DateTimeField(
        label=_("Proposed Date & Time"),
        widget=forms.DateTimeInput(attrs={
            "type": "datetime-local",
            "class": INPUT_CLASSES,
        }),
    )

    def clean_proposed_time(self):
        t = self.cleaned_data.get("proposed_time")
        if t and t <= timezone.now():
            raise forms.ValidationError(_("Proposed time must be in the future."))
        return t


class MeetingLinkForm(forms.Form):
    meeting_link = forms.CharField(
        max_length=300,
        label=_("Meeting Link"),
        widget=forms.TextInput(attrs={
            "class": INPUT_CLASSES,
            "placeholder": "https://meet.google.com/xxx-xxxx-xxx or https://zoom.us/j/...",
        }),
    )

    def clean_meeting_link(self):
        link = self.cleaned_data.get("meeting_link", "").strip()
        validate_meeting_link(link)
        return link


class ReportOutcomeForm(forms.Form):
    outcome = forms.ChoiceField(
        choices=SwapSession.Outcome.choices,
        label=_("Session Outcome"),
        widget=forms.RadioSelect,
    )


class SessionRatingForm(forms.ModelForm):
    class Meta:
        model = SessionRating
        fields = ["rating", "comment"]
        widgets = {
            "rating": forms.Select(
                choices=[(i, f"{i} ★") for i in range(5, 0, -1)],
                attrs={"class": INPUT_CLASSES},
            ),
            "comment": forms.Textarea(attrs={
                "class": INPUT_CLASSES,
                "rows": 3,
                "placeholder": _("Optional feedback on this swap session..."),
            }),
        }

