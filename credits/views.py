from django.http import JsonResponse
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

@login_required
def hollow_state(request):
    entries = request.user.ledger.all()[:20]
    return JsonResponse({
        "balance": get_balance(request.user),
        "entries": [
            {
                "id": e.id,
                "amount": e.amount,
                "reason": e.reason,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
    })
