from django.contrib import admin
from .models import Course, CoursePurchase, InstructorWallet

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'instructor', 'price', 'is_published', 'created_at')
    list_filter = ('is_published',)
    search_fields = ('title', 'instructor__username')

@admin.register(CoursePurchase)
class CoursePurchaseAdmin(admin.ModelAdmin):
    list_display = ('user', 'course', 'amount_paid', 'is_successful', 'purchased_at')
    list_filter = ('is_successful', 'purchased_at')
    search_fields = ('user__username', 'course__title', 'transaction_id')

@admin.register(InstructorWallet)
class InstructorWalletAdmin(admin.ModelAdmin):
    list_display = ('instructor', 'balance', 'total_earned')
    search_fields = ('instructor__username',)
