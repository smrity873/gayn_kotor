from django.contrib import admin

from .models import SessionRating, SkillPost, SwapSession


@admin.register(SkillPost)
class SkillPostAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "skill_name", "normalized_skill", "is_active", "created_at")
    list_filter = ("kind", "is_active", "created_at")
    search_fields = ("user__username", "user__email", "skill_name", "normalized_skill")


@admin.register(SwapSession)
class SwapSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "skill_name", "teacher", "learner", "status", "proposed_time", "deposit_held", "created_at")
    list_filter = ("status", "deposit_held", "created_at")
    search_fields = ("teacher__username", "learner__username", "skill_name")


@admin.register(SessionRating)
class SessionRatingAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "rater", "rating", "created_at")
    list_filter = ("rating", "created_at")
    search_fields = ("rater__username", "rater__email")
