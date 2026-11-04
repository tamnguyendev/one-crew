"""W11a — the event-type ledger and the old-version comparator (R00, 00 §6.1).

The compatibility boundary is judged by the EVENT CLASS, not by derive()'s KINDS tuple. KINDS (plan.py:15-16) is only the filter the
projector reads; the old version itself writes kinds that are not in KINDS (task.submitted when the anchor is created, request.*, hook.*),
so using KINDS as an allow-list would wrongly flag those. This module names, for every kind, its class:

  class 0 — the old version writes it itself. A new-version write MUST keep every field the old version reads, with the same type
            (fields may only be ADDED). A changed/removed class-0 field is a read block (B4): the old version crashes KeyError.
  class A — a neutral addition. The old version does not read it; its S (status), G (gate/hook) and C (continue) are unchanged. Safe on
            any `plan:` anchor.
  class B — changes meaning (status, gate or continuation). Only legal on a `plan-ns:` root the old version cannot see. On a `plan:`
            anchor it is a continue block (B2).

`event_class(kind)` returns '0' | 'A' | 'B' | None (unknown). `check_write(kind, payload, anchor)` is the guard every create/amend path
calls before writing on an anchor: it refuses a class-B kind, or a class-0 payload missing a required field, on a `plan:` anchor.
"""
from ..ledger import LedgerError

# ---- the event-type ledger (00 §6.1) ---------------------------------------------------------------------------------------

CLASS_0 = (
    'task.submitted', 'plan.proposed', 'plan.amended', 'plan.approved', 'plan.accepted', 'plan.advised', 'plan.step0_closed',
    'precondition.recorded', 'unknown.closed', 'poc.answered', 'verdict.receipt_issued', 'verdict.recorded', 'milestone.passed',
    'milestone.failed', 'milestone.stopped', 'attention.exceeded', 'hook.blocked', 'hook.logged', 'hook.reminded',
    'hook.stop_blocked', 'request.created', 'request.revised', 'request.deferred', 'request.answered',
)
CLASS_A = (
    'executor.managed',
    'review.observed',
    'review.run_started', 'review.run_result', 'review.run_finished', 'review.run_held',  # optional observations, never milestone/node authority
    'evidence.reuse',
    'adapter.violation',
    'executor.observed',
    'survey.opened', 'survey.finished', 'survey.denied', 'survey.worker_started',
    'learning.outcome', 'control.intervention', 'verdict.run_started', 'verdict.run_abandoned', 'context.entry',
    'estimate.baseline', 'estimate.eta', 'work.additional', 'notice.exception', 'learning.incident', 'learning.lesson',
    'decision.recorded',                              # W03: the decision record is a neutral addition
    'proposal.checked',                               # W47: the step-0 proposal check result (nothing reads it as status or gate for the old version)
    'verdict.run_reconciled', 'verdict.run_held', 'verdict.run_released',   # W37a: reconcile of a run of unknown outcome (the old version counts only verdict.recorded)
    'plan.baseline_recorded',                         # P1-D (review a2476ab): the owner records the base tree of a root approved by a build that kept none
    'support.feedback', 'support.classified', 'support.linked', 'support.bundle', 'support.user_confirmed',   # 2.4-S1: on the support anchor only
    'support.target', 'support.artifact', 'support.install_prepared', 'support.install', 'support.recheck', 'support.resumed',   # 2.4-S2
    'knowledge.delivered',                            # 2.4-B: what one attempt was given (v2/working_context); nothing reads it as status or gate for the old version
)
CLASS_B = (
    'solution.linked',
    'workflow.recovery_decided', 'workflow.recovery_replanned',
    'workflow.unknown_opened', 'workflow.unknown_resolved',
    'node.started', 'node.produced', 'node.verification', 'node.accepted', 'node.held', 'node.resumed',
    'node.result_retained', 'workflow.handoff',
    'budget.group',
    'finding.registered',
    'plan.revoked', 'plan.revised', 'plan.closed', 'request.applied',
    'decision.hold', 'decision.defer', 'milestone.held',              # W26 rule-based decisions / W36 pauses (named here for the boundary)
    'workflow.mode',                                  # 2.4-C: the recorded execution-mode choice of a node (waits included); plan-ns roots only
)

# The fields the OLD version reads for each class-0 kind. A class-0 write that drops one, or stores it as the wrong type, is a read
# block (B4): the old version crashes KeyError on plan show / digest of the whole state root (EV-K). Only these fields are load-bearing
# for the old reader; a new version may add fields freely. 'at' is added to every event by plan.emit.
# Only the fields the OLD projector derive()/status() actually DEREFERENCES: it reads p['revision'] on every revision-bearing kind in its
# KINDS tuple, and p['milestone'] / p['receipt'] on a receipt. A missing one is exactly the KeyError EV-K reproduced (plan.advised without
# 'revision' before a valid plan.accepted). A kind the old projector does not read (task.submitted, hook.*, request.*) has NO load-bearing
# field here, so it is never a read block — listing one would wrongly flag healthy roots.
CLASS_0_REQUIRED = {
    'plan.proposed': ('revision',),
    'plan.amended': ('revision',),
    'plan.approved': ('revision',),
    'plan.accepted': ('revision',),
    'plan.advised': ('revision',),
    'verdict.recorded': ('revision',),
    'verdict.receipt_issued': ('revision', 'milestone', 'receipt'),
    'milestone.passed': ('revision',),
    'milestone.failed': ('revision',),
    'milestone.stopped': ('revision',),
}
CLASS_0_FIELD_TYPES = {'revision': int, 'milestone': str, 'receipt': str}


def event_class(kind):
    if kind in CLASS_0: return '0'
    if kind in CLASS_A: return 'A'
    if kind in CLASS_B: return 'B'
    return None


def required_fields(kind):
    return CLASS_0_REQUIRED.get(kind, ())


def anchor_kind(anchor):
    """'plan:' for a root the old version sees, 'plan-ns:' for a new root it cannot. Anything else is treated as a plain task."""
    if anchor.startswith('plan-ns:'): return 'plan-ns:'
    if anchor.startswith('plan:'): return 'plan:'
    return anchor


def class0_payload_errors(kind, payload):
    """Load-bearing field shape only; additional fields keep their existing freedom."""
    if not isinstance(payload, dict): return ['payload expected object']
    errors = []
    for field in required_fields(kind):
        if field not in payload or payload[field] is None:
            errors.append(f'missing {field}')
        else:
            expected = CLASS_0_FIELD_TYPES[field]
            # bool is an int subclass, but it is not the revision type the old
            # writer emitted. JSON strings/arrays must not become dict/set keys.
            if type(payload[field]) is not expected:
                errors.append(f'{field} expected {expected.__name__}, got {type(payload[field]).__name__}')
    return errors


def class0_payload_ok(kind, payload):
    """Every old-reader field is present with its original type (B4 otherwise)."""
    return not class0_payload_errors(kind, payload)


def check_write(kind, payload, anchor):
    """The guard for a write on `anchor`. On a `plan:` anchor (a root the old version sees): a class-B kind is refused (it would be a B2
    continue-block), and a class-0 payload missing a required field is refused (a B4 read-block). class A is always allowed. An unknown
    kind on a `plan:` anchor is refused (the boundary is closed: a kind with no declared class cannot be proven neutral). On a `plan-ns:`
    anchor every class is allowed (the old version cannot see it). Returns None on success; raises LedgerError otherwise."""
    kind_of_anchor = anchor_kind(anchor)
    if kind_of_anchor != 'plan:':
        return None                                   # plan-ns: (or a non-plan task) is outside the old reader's reach
    klass = event_class(kind)
    if klass is None:
        raise LedgerError(f'event {kind!r} has no declared compatibility class: it cannot be written on a plan: anchor the old version reads '
                          f'(00 §6.1). Declare it class 0/A/B in compat.py first.')
    if klass == 'B':
        raise LedgerError(f'event {kind!r} is class B (it changes status, gate or continuation): the old version would read or continue the '
                          f'root wrongly (B2). A class-B event belongs only on a plan-ns: root (W12b/R04), never a plan: anchor.')
    if klass == '0' and not class0_payload_ok(kind, payload):
        problems = '; '.join(class0_payload_errors(kind, payload))
        raise LedgerError(f'event {kind!r} has an incompatible class-0 payload: {problems}. The old reader can crash KeyError/TypeError '
                          f'on this root and on digest of the whole state root (B4, read block). Keep every old field and its type.')
    return None
