from decimal import Decimal
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .models import Course, Lesson
from .services import (
    validate_video_file,
    get_video_duration,
    get_allowed_price_range,
    validate_course_price,
)


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ["title", "category", "description", "price", "thumbnail", "status"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20",
                    "placeholder": _("e.g. Master Django & PostgreSQL"),
                }
            ),
            "category": forms.Select(
                attrs={
                    "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20",
                    "rows": 4,
                    "placeholder": _("Detailed overview of what students will learn..."),
                }
            ),
            "price": forms.NumberInput(
                attrs={
                    "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20",
                    "min": "0",
                    "step": "1",
                }
            ),
            "thumbnail": forms.FileInput(
                attrs={
                    "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none",
                    "accept": "image/*",
                }
            ),
            "status": forms.Select(
                attrs={
                    "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20",
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        price = cleaned_data.get("price")
        category = cleaned_data.get("category")
        status = cleaned_data.get("status")

        if price is not None and category:
            duration = self.instance.total_duration_seconds if self.instance.pk else 0
            min_price, max_price = get_allowed_price_range(category, duration)

            if price < min_price or price > max_price:
                self.add_error(
                    "price",
                    _(
                        "Price %(price)s BDT is outside the allowed range of %(min)s - %(max)s BDT for %(category)s (%(dur)d min)."
                    )
                    % {
                        "price": price,
                        "min": min_price,
                        "max": max_price,
                        "category": dict(Course.Category.choices).get(category, category),
                        "dur": round(duration / 60),
                    },
                )

            if status == Course.Status.PUBLISHED:
                if not self.instance.pk or self.instance.lessons.count() == 0:
                    self.add_error("status", _("A course must have at least one lesson before publishing."))
        return cleaned_data


class LessonForm(forms.ModelForm):
    duration_input = forms.IntegerField(
        required=False,
        min_value=1,
        help_text=_("Duration in minutes (required only if using an external video URL)"),
        widget=forms.NumberInput(
            attrs={
                "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20",
                "placeholder": _("Duration in minutes"),
            }
        ),
    )

    class Meta:
        model = Lesson
        fields = ["title", "order", "video_file", "video_url", "is_free_preview"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20",
                    "placeholder": _("e.g. 01. Introduction to the course"),
                }
            ),
            "order": forms.NumberInput(
                attrs={
                    "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20",
                    "min": "1",
                }
            ),
            "video_file": forms.FileInput(
                attrs={
                    "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none",
                    "accept": "video/mp4",
                }
            ),
            "video_url": forms.URLInput(
                attrs={
                    "class": "w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20",
                    "placeholder": _("https://www.youtube.com/watch?v=..."),
                }
            ),
            "is_free_preview": forms.CheckboxInput(
                attrs={
                    "class": "h-5 w-5 rounded border-fern/30 text-forest focus:ring-forest/20",
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        video_file = cleaned_data.get("video_file")
        video_url = cleaned_data.get("video_url")
        duration_input = cleaned_data.get("duration_input")

        # Must have either a video file, video_url, or existing file on the instance
        has_file = bool(video_file) or (self.instance.pk and bool(self.instance.video_file))
        if not has_file and not video_url:
            raise forms.ValidationError(_("You must upload an MP4 video file or provide a video URL."))

        if video_file:
            # Server-side validation using mutagen (PRD 7.3)
            course = getattr(self.instance, "course", None)
            duration = validate_video_file(video_file, course=course)
            self.instance.duration_seconds = duration
        elif video_url and not (self.instance.pk and self.instance.video_file):
            if duration_input:
                self.instance.duration_seconds = duration_input * 60
            elif not self.instance.pk or not self.instance.duration_seconds:
                self.instance.duration_seconds = 300  # Default 5 minutes if not provided

        return cleaned_data
