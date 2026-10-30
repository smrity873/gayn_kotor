from django.conf import settings
from django.core.mail import send_mail

from .models import Notification


def notify(user, message, link="", email=False):
    notif = Notification.objects.create(user=user, message=message[:200], link=link)
    if email and getattr(user, "email", None):
        subject = f"[{getattr(settings, 'SITE_NAME', 'Campus App')}] New Notification"
        body = message
        if link:
            body += f"\n\nView details: {link}"
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
            recipient_list=[user.email],
            fail_silently=True,
        )
    return notif


def notify_many(users, message, link="", email=False):
    notifs = [Notification(user=u, message=message[:200], link=link) for u in users]
    Notification.objects.bulk_create(notifs)
    if email:
        for u in users:
            if getattr(u, "email", None):
                send_mail(
                    subject=f"[{getattr(settings, 'SITE_NAME', 'Campus App')}] New Notification",
                    message=message + (f"\n\nView details: {link}" if link else ""),
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
                    recipient_list=[u.email],
                    fail_silently=True,
                )


def unread_count(user):
    return user.notifications.filter(is_read=False).count()
