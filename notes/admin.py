from django.contrib import admin

from .models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("title", "course_code", "department", "semester", "owner", "status", "created_at")
    list_filter = ("status", "department", "semester", "visibility")
    search_fields = ("title", "course_code", "owner__username")