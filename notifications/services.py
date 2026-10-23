from .models import Notification


def notify(user, message, link=""):
    return Notification.objects.create(user=user, message=message[:200], link=link)


def notify_many(users, message, link=""):
    Notification.objects.bulk_create(
        [Notification(user=u, message=message[:200], link=link) for u in users]
    )


def unread_count(user):
    return user.notifications.filter(is_read=False).count()