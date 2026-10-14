from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "id_number", "is_email_verified", "is_active")
    list_filter = ("role", "is_email_verified", "is_active")
    search_fields = ("username", "email", "id_number")

    fieldsets = UserAdmin.fieldsets + (
        ("Gayn Kotor", {"fields": ("role", "id_number", "is_email_verified")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Gayn Kotor", {"fields": ("email", "role", "id_number")}),
    )