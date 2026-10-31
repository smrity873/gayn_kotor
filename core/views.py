from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render

from accounts.models import User
from courses.models import Course
from credits.models import CreditLedger
from notes.models import Note
from swaps.models import SwapSession

from .dashboard import get_dashboard_context


def home(request):
    """Home page with top 6 popular public notes, flag-gated courses, and platform counters."""
    enable_courses = getattr(settings, "ENABLE_VIDEO_COURSES", True)

    # 1. Popular notes (top 6 by unlocks, public and published only)
    popular_notes = list(
        Note.objects.filter(
            visibility=Note.Visibility.PUBLIC,
            status__in=[Note.Status.APPROVED, Note.Status.UNVERIFIED],
        )
        .annotate(unlocks_count=Count("downloads"))
        .select_related("owner", "department")
        .order_by("-unlocks_count", "-created_at")[:6]
    )

    # 2. Latest published courses (flag-gated)
    latest_courses = []
    if enable_courses:
        latest_courses = list(
            Course.objects.filter(is_published=True)
            .select_related("instructor")
            .order_by("-created_at")[:4]
        )

    # 3. Platform counters
    counters = {
        "notes_count": Note.objects.filter(
            visibility=Note.Visibility.PUBLIC,
            status__in=[Note.Status.APPROVED, Note.Status.UNVERIFIED],
        ).count(),
        "students_count": User.objects.filter(is_active=True).count(),
        "swaps_count": SwapSession.objects.filter(
            status__in=[SwapSession.Status.SCHEDULED, SwapSession.Status.COMPLETED]
        ).count(),
        "nuts_circulating": CreditLedger.objects.filter(amount__gt=0).aggregate(
            total=Sum("amount")
        )["total"] or 0,
    }

    context = {
        "popular_notes": popular_notes,
        "latest_courses": latest_courses,
        "counters": counters,
        "enable_courses": enable_courses,
    }
    return render(request, "home.html", context)


@login_required
def dashboard(request):
    """Role-aware dashboard view."""
    context = get_dashboard_context(request.user)
    return render(request, "dashboard.html", context)
