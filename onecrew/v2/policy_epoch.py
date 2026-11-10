"""The checkout-policy epoch of a plan (2.5.0.dev22, owner 10/11 "Đồng ý": A-lite).

The first time this OneCrew WRITES to a plan (propose, amend, approve, a verdict run or record, an engine step, verify, accept or handoff,
plan accept), it records the plan's epoch for the checkout policy it runs (verifiers.command.CHECKOUT_POLICY): the ledger's last event seq at
that moment, in its own table `policy_epochs` (no event: the event stream every reader and test knows stays as it was; an older OneCrew never
reads the table). A new policy value gets a new epoch. Evidence of a plan that is not accepted counts only when it was made AFTER the epoch:
  - a top-level verdict by the seq of its `verdict.receipt_issued` (a receipt issued before and recorded after the epoch is still before it);
  - a node verification by the seq of its `node.verification`.
Read-only commands write nothing: before any write under this policy there is no epoch, and every earlier evidence reads as "needs a new
check". An accepted plan keeps its history. Owner-manual verdicts do not depend on a checkout and are not judged here.
"""
import sqlite3

from ..ledger import utcnow

TABLE = ('CREATE TABLE IF NOT EXISTS policy_epochs (task_id TEXT NOT NULL, policy TEXT NOT NULL, seq INTEGER NOT NULL, '
         'created_at TEXT NOT NULL, PRIMARY KEY(task_id, policy))')


def _policy():
    from .verifiers import command
    return command.CHECKOUT_POLICY


def seq(conn, task_id, policy=None):
    """This plan's epoch for `policy` (default: the running one), or None when no write has happened under it (or the ledger is older)."""
    try:
        row = conn.execute('SELECT seq FROM policy_epochs WHERE task_id=? AND policy=?', (task_id, policy or _policy())).fetchone()
    except sqlite3.OperationalError:            # a ledger no write of this OneCrew has touched: no table yet
        return None
    return row['seq'] if row else None


def ensure(ledger, task_id, conn=None):
    """The epoch of this plan for the running policy, recorded now if it is not there yet (the last event seq of the ledger). Call it inside
    (or as) a write transaction, before the write that may produce or use evidence."""
    if conn is None:
        with ledger.transaction(write=True) as opened:
            return ensure(ledger, task_id, opened)
    found = seq(conn, task_id)
    if found is not None: return found
    conn.execute(TABLE)
    last = conn.execute('SELECT COALESCE(MAX(seq), 0) AS last FROM events').fetchone()['last']
    conn.execute('INSERT OR IGNORE INTO policy_epochs(task_id, policy, seq, created_at) VALUES(?,?,?,?)', (task_id, _policy(), last, utcnow()))
    return seq(conn, task_id)


def fresh(evidence_seq, epoch):
    """Evidence counts only when made after the epoch of the running policy."""
    return epoch is not None and evidence_seq is not None and evidence_seq > epoch


NOTE = ('cần kiểm lại: bằng chứng này có trước khi OneCrew đổi cách chép artifact cho bộ kiểm (chính sách chép mới); '
        'chạy lại verdict để bộ kiểm thấy đúng nội dung git lưu')
REASON = 'the evidence predates the checkout policy this OneCrew runs (policy epoch): run the verdict again'
