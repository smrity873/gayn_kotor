from django.contrib import admin
from .models import PaymentOrder


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "purpose", "amount_bdt", "status", "gateway", "created_at", "paid_at")
    list_filter = ("status", "purpose", "gateway", "created_at")
    search_fields = ("id", "user__username", "user__email", "gateway_txn_id", "reference_id")
    readonly_fields = ("id", "created_at", "paid_at")

