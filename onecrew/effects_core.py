"""Shared uncertain-effect signal; recovery observes the same durable intent."""
from .ledger import LedgerError


class EffectUnknown(LedgerError):
    """Retain the exact tool intent; resume may only observe its existing action."""
