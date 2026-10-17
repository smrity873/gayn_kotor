from django.contrib import admin

from .models import CreditLedger


@admin.register(CreditLedger)
class CreditLedgerAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "reason", "description", "created_at")
    list_filter = ("reason",)
    search_fields = ("user__username", "description")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False