from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse

from notifications.services import notify

from .models import CreditLedger


def get_balance(user):
    total = user.ledger.aggregate(total=Sum("amount"))["total"]
    return total or 0


@transaction.atomic
def add_entry(user, amount, reason, description="", allow_negative=False, notify=True):
    if amount < 0:
        get_user_model().objects.select_for_update().get(pk=user.pk)
        if not allow_negative and get_balance(user) + amount < 0:
            raise ValueError("Not enough credits.")

    entry = CreditLedger.objects.create(
        user=user,
        amount=amount,
        reason=reason,
        description=description,
    )

    if notify and amount != 0:
        sign = "+" if amount > 0 else ""
        msg = f"{sign}{amount} nuts"
        if description:
            msg += f": {description}"
        else:
            msg += f" ({reason.replace('_', ' ').capitalize()})"

        def send_notif():
            try:
                from notifications.services import notify as send_notification
                send_notification(user, msg, reverse("credits:hollow"))
            except Exception:
                pass

        transaction.on_commit(send_notif)

    return entry


@transaction.atomic
def grant_signup_bonus(user):
    get_user_model().objects.select_for_update().get(pk=user.pk)
    if CreditLedger.objects.filter(user=user, reason=CreditLedger.Reason.SIGNUP_BONUS).exists():
        return None

    amount = getattr(settings, "SIGNUP_BONUS", 30)
    entry = add_entry(user, amount, CreditLedger.Reason.SIGNUP_BONUS, "Welcome bonus", notify=False)
    try:
        notify(
            user,
            f"You received {amount} nuts welcome bonus for verifying your email!",
            reverse("credits:hollow"),
        )
    except Exception:
        pass
    return entry
