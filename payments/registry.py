from typing import Callable, Dict

_FULFILLERS: Dict[str, Callable] = {}


def register_fulfiller(purpose: str, fulfiller_fn: Callable):
    """
    Registers a callback function to fulfill a PaymentOrder with the specified purpose.
    fulfiller_fn must take (order: PaymentOrder) and perform domain-specific fulfillment.
    """
    _FULFILLERS[purpose] = fulfiller_fn


def get_fulfiller(purpose: str) -> Callable:
    """Returns the registered fulfillment callback for a given purpose, or None."""
    return _FULFILLERS.get(purpose)


def clear_fulfillers():
    """Clears all registered fulfillers (primarily for test cleanup)."""
    _FULFILLERS.clear()
