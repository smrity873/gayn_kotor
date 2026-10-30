from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import verified_required
from .models import PaymentOrder
from .services import complete_order, create_order, get_gateway


@login_required
@verified_required
def buy_credits(request):
    """Preset packs and custom credit top-up view."""
    credit_price = getattr(settings, "CREDIT_PRICE_BDT", Decimal("1"))
    min_nuts = getattr(settings, "CREDIT_TOPUP_MIN", 10)
    max_nuts = getattr(settings, "CREDIT_TOPUP_MAX", 5000)
    packs = [50, 100, 200]

    if request.method == "POST":
        raw_val = request.POST.get("amount") or request.POST.get("nuts") or request.POST.get("pack")
        try:
            nuts = int(raw_val)
        except (TypeError, ValueError):
            messages.error(request, "Please enter a valid whole number of nuts.")
            return redirect("payments:buy_credits")

        if nuts < min_nuts or nuts > max_nuts:
            messages.error(request, f"Credit purchase must be between {min_nuts} and {max_nuts} nuts.")
            return redirect("payments:buy_credits")

        amount_bdt = Decimal(nuts) * credit_price

        order = create_order(
            user=request.user,
            purpose=PaymentOrder.Purpose.CREDIT_TOPUP,
            amount_bdt=amount_bdt,
            reference_type="credits",
            reference_id=str(nuts),
        )

        gateway = get_gateway()
        return_url = request.build_absolute_uri(reverse("payments:order_detail", args=[order.id]))
        redirect_url = gateway.create_payment(order, return_url)
        return redirect(redirect_url)

    context = {
        "packs": packs,
        "credit_price": credit_price,
        "min_nuts": min_nuts,
        "max_nuts": max_nuts,
    }
    return render(request, "payments/buy_credits.html", context)


@login_required
def sandbox_view(request, order_id):
    """
    Sandbox payment simulation view.
    Refuses to run in production (when DEBUG=False) unless SANDBOX_ALLOWED=True.
    Enforces user authorization.
    """
    sandbox_allowed = getattr(settings, "DEBUG", False) or getattr(settings, "SANDBOX_ALLOWED", False)
    if not sandbox_allowed:
        raise PermissionDenied("Payment sandbox is disabled in production.")

    order = get_object_or_404(PaymentOrder, id=order_id)
    if order.user_id != request.user.id and not request.user.is_superuser:
        raise PermissionDenied("You cannot view or complete another user's order.")

    if order.status in (PaymentOrder.Status.PAID, PaymentOrder.Status.FAILED, PaymentOrder.Status.CANCELLED):
        return redirect("payments:order_detail", order_id=order.id)

    if request.method == "POST":
        gateway = get_gateway("sandbox")
        result = gateway.parse_callback(request)
        complete_order(order, result)
        if result.success:
            messages.success(request, f"Payment of {order.amount_bdt} BDT successful! Your order has been fulfilled.")
        else:
            messages.error(request, f"Payment failed or cancelled.")
        return redirect("payments:order_detail", order_id=order.id)

    return render(request, "payments/sandbox.html", {"order": order})


@login_required
def order_list(request):
    """Order history view for the authenticated user."""
    orders_qs = request.user.payment_orders.all().order_by("-created_at")
    paginator = Paginator(orders_qs, 15)
    page_number = request.GET.get("page")
    page = paginator.get_page(page_number)
    return render(request, "payments/order_list.html", {"page": page})


@login_required
def order_detail(request, order_id):
    """Detail view for a single order."""
    order = get_object_or_404(PaymentOrder, id=order_id)
    if order.user_id != request.user.id and not request.user.is_superuser:
        raise PermissionDenied("You cannot view another user's order.")

    return render(request, "payments/order_detail.html", {"order": order})


@require_POST
def gateway_callback(request):
    """Generic gateway callback / webhook endpoint."""
    gateway = get_gateway()
    result = gateway.parse_callback(request)
    order = get_object_or_404(PaymentOrder, id=result.order_id)
    complete_order(order, result)
    return redirect("payments:order_detail", order_id=order.id)

