from django.contrib import admin
from .models import Course, Lesson, PricingRule, CoursePurchase


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 1


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "instructor", "category", "price", "status", "total_duration_seconds", "created_at")
    list_filter = ("category", "status", "created_at")
    search_fields = ("title", "instructor__username")
    inlines = [LessonInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("course", "order", "title", "duration_seconds", "is_free_preview", "created_at")
    list_filter = ("is_free_preview", "course")
    search_fields = ("title", "course__title")


@admin.register(PricingRule)
class PricingRuleAdmin(admin.ModelAdmin):
    list_display = ("category", "min_per_hour", "max_per_hour")


@admin.register(CoursePurchase)
class CoursePurchaseAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "amount_paid", "commission_amount", "seller_earning", "is_successful", "purchased_at")
    list_filter = ("is_successful", "purchased_at")
    search_fields = ("user__username", "course__title", "transaction_id")
