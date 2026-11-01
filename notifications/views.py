from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def notification_list(request):
    notifications_qs = request.user.notifications.all()
    paginator = Paginator(notifications_qs, 20)
    page_number = request.GET.get("page")
    page = paginator.get_page(page_number)
    unread_cnt = request.user.notifications.filter(is_read=False).count()
    return render(
        request,
        "notifications/notification_list.html",
        {"page": page, "unread_count": unread_cnt},
    )


@login_required
def summary(request):
    items = request.user.notifications.all()[:8]
    return JsonResponse({
        "unread": request.user.notifications.filter(is_read=False).count(),
        "items": [
            {
                "id": n.id,
                "message": n.message,
                "is_read": n.is_read,
                "time": n.created_at.strftime("%d %b, %I:%M %p"),
            }
            for n in items
        ],
    })


@login_required
def open_notification(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])

    target = n.link or "/"
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = "/"
    return redirect(target)


@login_required
@require_POST
def mark_all_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.POST.get("format") == "json":
        return JsonResponse({"ok": True})
    return redirect(request.META.get("HTTP_REFERER", "notifications:list"))
