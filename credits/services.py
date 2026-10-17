from django.db import transaction
from django.db.models import Sum

from .models import CreditLedger


def get_balance(user):
    total = user.ledger.aggregate(total=Sum("amount"))["total"]
    return total or 0


@transaction.atomic
def add_entry(user, amount, reason, description=""):
    if amount < 0 and get_balance(user) + amount < 0:
        raise ValueError("Not enough credits.")
    return CreditLedger.objects.create(
        user=user,
        amount=amount,
        reason=reason,
        description=description,
    )