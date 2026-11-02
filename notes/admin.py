from django.contrib import admin

from .models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("title", "course_code", "department", "semester", "owner", "status", "created_at")
    list_filter = ("status", "department", "semester", "visibility")
    search_fields = ("title", "course_code", "owner__username")

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status in (Note.Status.APPROVED, Note.Status.UNVERIFIED):
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status in (Note.Status.APPROVED, Note.Status.UNVERIFIED, Note.Status.REJECTED):
            return False
        return super().has_change_permission(request, obj)
