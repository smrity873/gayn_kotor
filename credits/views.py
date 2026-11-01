from django.core.paginator import Paginator
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import CreditLedger
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


@login_required
def ledger_list(request):
    qs = request.user.ledger.all()
    selected_reason = request.GET.get("reason", "").strip()
    if selected_reason and selected_reason in dict(CreditLedger.Reason.choices):
        qs = qs.filter(reason=selected_reason)

    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "entries": page_obj.object_list,
        "selected_reason": selected_reason,
        "reasons": CreditLedger.Reason.choices,
        "balance": get_balance(request.user),
    }
    return render(request, "credits/ledger.html", context)
