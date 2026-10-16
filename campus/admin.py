from django.contrib import admin

from .models import Batch, BatchMembership, Department


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "class_teacher")
    list_filter = ("department",)
    search_fields = ("name",)


@admin.register(BatchMembership)
class BatchMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "batch", "status", "created_at")
    list_filter = ("status", "batch__department", "batch")
    search_fields = ("user__username", "user__id_number")
    actions = ["approve_selected", "reject_selected"]

    @admin.action(description="Approve selected requests")
    def approve_selected(self, request, queryset):
        queryset.update(status=BatchMembership.Status.APPROVED)

    @admin.action(description="Reject selected requests")
    def reject_selected(self, request, queryset):
        queryset.update(status=BatchMembership.Status.REJECTED)