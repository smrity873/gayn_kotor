from django.contrib import admin
from .models import PaymentOrder, Wallet, WalletEntry, WithdrawalRequest


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "purpose", "amount_bdt", "status", "gateway", "created_at", "paid_at")
    list_filter = ("status", "purpose", "gateway", "created_at")
    search_fields = ("id", "user__username", "user__email", "gateway_txn_id", "reference_id")
    readonly_fields = ("id", "created_at", "paid_at")


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "updated_at")
    search_fields = ("user__username", "user__email")


@admin.register(WalletEntry)
class WalletEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "reason", "reference", "created_at")
    list_filter = ("reason", "created_at")
    search_fields = ("user__username", "reference")
    readonly_fields = ("created_at",)


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "amount", "method", "status", "created_at", "decided_at")
    list_filter = ("status", "method", "created_at")
    search_fields = ("user__username", "account_details", "admin_note")
    readonly_fields = ("created_at",)
    actions = ["mark_as_paid", "mark_as_rejected"]

    @admin.action(description="Mark selected requests as Paid")
    def mark_as_paid(self, request, queryset):
        from payments.services import mark_withdrawal_paid
        count = 0
        for req in queryset.filter(status=WithdrawalRequest.Status.PENDING):
            mark_withdrawal_paid(req.id, note="Paid via admin action")
            count += 1
        self.message_user(request, f"{count} withdrawal requests marked as Paid.")

    @admin.action(description="Reject selected requests (with reversal)")
    def mark_as_rejected(self, request, queryset):
        from payments.services import reject_withdrawal_request
        count = 0
        for req in queryset.filter(status=WithdrawalRequest.Status.PENDING):
            reject_withdrawal_request(req.id, note="Rejected via admin action")
            count += 1
        self.message_user(request, f"{count} withdrawal requests rejected and refunded.")
