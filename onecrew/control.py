"""Legacy policy adapter over the one shared execution/admission core."""
from .control_core import ACTIVE, SCHEMA, CapacityWait, Control as SharedControl, migrate


class LegacyPolicy:
    def check(self, ledger, task_id, conn):
        from .solution_gate import check
        return check(ledger, task_id, conn)


class Control(SharedControl):
    def __init__(self, ledger, clock=None):
        super().__init__(ledger, clock, policy=LegacyPolicy())
