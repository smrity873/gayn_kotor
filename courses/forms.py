from django import forms
from .models import Course

class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['title', 'description', 'price', 'thumbnail', 'video_file', 'is_published']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20', 
                'rows': 4
            }),
            'price': forms.NumberInput(attrs={
                'class': 'w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none focus:border-forest focus:ring-2 focus:ring-forest/20'
            }),
            'thumbnail': forms.FileInput(attrs={
                'class': 'w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none'
            }),
            'video_file': forms.FileInput(attrs={
                'class': 'w-full rounded-xl border border-fern/30 bg-canvas dark:bg-canvas-dark px-4 py-2.5 text-gray-900 dark:text-white outline-none'
            }),
            'is_published': forms.CheckboxInput(attrs={
                'class': 'h-5 w-5 rounded border-fern/30 text-forest focus:ring-forest/20'
            }),
        }