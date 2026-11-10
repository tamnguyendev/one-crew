"""The checkout-policy epoch of a plan (2.5.0.dev22, owner 10/11 "Đồng ý": A-lite).

The first time this OneCrew WRITES to a plan (a verdict run or record, an engine verify, step, accept or handoff, plan accept), it records
one `checkout.policy_epoch` event for the checkout policy it runs (verifiers.command.CHECKOUT_POLICY), on the plan's own task. A new policy
value gets a new epoch. Evidence of a plan that is not accepted counts only when it was made AFTER that event (by seq):
  - a top-level verdict by the seq of its `verdict.receipt_issued` (a receipt issued before and recorded after the epoch is still before it);
  - a node verification by the seq of its `node.verification`.
Read-only commands write nothing: before any write under this policy there is no epoch, and every earlier evidence reads as "needs a new
check". An accepted plan keeps its history (its views come from the acceptance record). Owner-manual verdicts do not depend on a checkout and
are not judged here.
"""
from ..ledger import utcnow

KIND = 'checkout.policy_epoch'


def _policy():
    from .verifiers import command
    return command.CHECKOUT_POLICY


def seq(conn, task_id, policy=None):
    """The seq of this plan's epoch for `policy` (default: the running one), or None when no write has happened under it."""
    row = conn.execute("SELECT seq FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.policy')=? ORDER BY seq LIMIT 1",
                       (task_id, KIND, policy or _policy())).fetchone()
    return row['seq'] if row else None


def ensure(ledger, task_id, conn=None):
    """The epoch of this plan for the running policy, written now if it is not there yet. Call it inside (or as) a write transaction, before
    the write that may produce or use evidence."""
    if conn is None:
        with ledger.transaction(write=True) as opened:
            return ensure(ledger, task_id, opened)
    found = seq(conn, task_id)
    if found is not None: return found
    ledger._event(conn, task_id, KIND, {'policy': _policy(), 'at': utcnow()})
    return seq(conn, task_id)


def fresh(evidence_seq, epoch):
    """Evidence counts only when made after the epoch of the running policy."""
    return epoch is not None and evidence_seq is not None and evidence_seq > epoch


NOTE = ('cần kiểm lại: bằng chứng này có trước khi OneCrew đổi cách chép artifact cho bộ kiểm (chính sách chép mới); '
        'chạy lại verdict để bộ kiểm thấy đúng nội dung git lưu')
REASON = 'the evidence predates the checkout policy this OneCrew runs (policy epoch): run the verdict again'
