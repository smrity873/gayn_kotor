from .services import get_balance


def credit_balance(request):
    """
    PRD 8.2: Context processor that caches credit balance per-request.
    """
    if request.user.is_authenticated:
        return {"credit_balance": get_balance(request.user, request=request)}
    return {}
