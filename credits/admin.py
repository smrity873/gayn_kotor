from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from .models import CreditLedger
from .services import reverse_entry


@admin.action(description=_("Reverse selected entries"))
def reverse_selected_entries(modeladmin, request, queryset):
    reversed_count = 0
    errors = []
    for entry in queryset.order_by("id"):
        if entry.reason == CreditLedger.Reason.REVERSAL:
            errors.append(f"Entry #{entry.id} is already a reversal.")
            continue
        if hasattr(entry, "reversed_by") and entry.reversed_by is not None:
            errors.append(f"Entry #{entry.id} has already been reversed by #{entry.reversed_by.id}.")
            continue
        try:
            reverse_entry(entry)
            reversed_count += 1
        except Exception as e:
            errors.append(f"Entry #{entry.id}: {str(e)}")

    if reversed_count > 0:
        modeladmin.message_user(
            request,
            f"Successfully reversed {reversed_count} entry/entries.",
            messages.SUCCESS,
        )
    for err in errors:
        modeladmin.message_user(request, err, messages.WARNING)


@admin.register(CreditLedger)
class CreditLedgerAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "amount", "reason", "description", "reverses", "created_at")
    list_filter = (
        "reason",
        "created_at",
        ("user", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("user__username", "user__email", "description")
    readonly_fields = ("reverses", "user", "amount", "reason", "description", "created_at")
    date_hierarchy = "created_at"
    actions = [reverse_selected_entries]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
