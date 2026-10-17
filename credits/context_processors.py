from .services import get_balance


def credit_balance(request):
    if request.user.is_authenticated:
        return {"credit_balance": get_balance(request.user)}
    return {}