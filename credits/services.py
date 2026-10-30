from django.db import transaction
from django.db.models import Sum

from .models import CreditLedger


def get_balance(user):
    total = user.ledger.aggregate(total=Sum("amount"))["total"]
    return total or 0


@transaction.atomic
def add_entry(user, amount, reason, description="", allow_negative=False):
    if amount < 0:
        type(user).objects.select_for_update().get(pk=user.pk)
        if not allow_negative and get_balance(user) + amount < 0:
            raise ValueError("Not enough credits.")
    


    return CreditLedger.objects.create(
        user=user,
        amount=amount,
        reason=reason,
        description=description,
    )