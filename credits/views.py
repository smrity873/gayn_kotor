from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import get_balance


@login_required
def hollow(request):
    entries = request.user.ledger.all()[:20]
    context = {
        "balance": get_balance(request.user),
        "entries": entries,
    }
    return render(request, "credits/hollow.html", context)