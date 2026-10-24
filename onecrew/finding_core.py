"""The shared finding register: pure state transitions used by v1 and plan v2.

Storage, receipt authenticity and execution generations belong to the caller.
The register never closes a finding merely because code changed or a reviewer
accepted the work; a closure must name an open id and evidence shown to it.
"""
import hashlib

from .ledger import LedgerError


def norm(text):
    """Preserve case and the whole claim; only whitespace is insignificant."""
    return ' '.join(str(text).split())


def claim_key(text):
    return hashlib.sha256(norm(text).encode('utf-8', 'surrogatepass')).hexdigest()


def safe(text):
    return str(text).encode('utf-8', 'replace').decode('utf-8')


def register(state):
    value = state.setdefault('review_register', {'next': 1, 'notes_next': 1, 'review': 1, 'findings': [], 'notes': []})
    value.setdefault('unprocessed', [])
    value.setdefault('ob_next', 1)
    return value


def open_findings(state):
    found = [f for f in (state.get('review_register') or {}).get('findings') or [] if f.get('status') == 'open']
    # Keep the unreleased v1 checkpoint shape visible and fail closed.
    for old in state.get('review_findings') or []:
        if isinstance(old, dict) and old.get('status') == 'open':
            claim = str(old.get('claim', ''))
            found.append({'id': str(old.get('id', 'RF?')), 'status': 'open', 'review': 0, 'round': old.get('round', 0), 'candidate': None,
                          'chars': old.get('chars', len(claim)), 'head': claim[:500], 'norm': '', 'legacy': True,
                          'source': dict(old.get('source') or {})})
    return found


def append_finding(value, entry):
    """Allocate a stable register id. Callers deduplicate against whole claim keys."""
    number = value['next']
    value['next'] = number + 1
    item = dict(entry, id=f'RF{number}', status='open')
    value['findings'].append(item)
    return item


def closure_reason(findings, ident, receipt, *, shown, listed=None, receipts=(), taken=()):
    target = next((f for f in findings if f['id'] == ident), None)
    if target is None or target['status'] != 'open' or ident in taken:
        return f'{ident} is not an open finding'
    if listed is not None and ident not in listed:
        return f'{ident} was not shown to the reviewer in this review'
    if receipt not in shown:
        return f'receipt {receipt} was not shown in this review'
    held = {r['index']: r for r in receipts}
    if (held.get(receipt) or {}).get('action') == 'finish':
        return f'receipt {receipt} is a finish: the rejection that carries a finding is not evidence that it is resolved'
    return None


def close_finding(value, ident, receipt, *, shown, resolution, listed=None, receipts=(), status='resolved', head_closed=160):
    """The one closure transition; validation never mutates the register."""
    if status not in ('resolved', 'rejected'):
        raise LedgerError('A finding closes as resolved or rejected.')
    reason = closure_reason(value['findings'], ident, receipt, shown=shown, listed=listed, receipts=receipts)
    if reason:
        raise LedgerError(reason)
    if receipt is None or not resolution or resolution.get('receipt') != receipt:
        raise LedgerError('A finding closure needs its named evidence receipt.')
    target = next(f for f in value['findings'] if f['id'] == ident)
    target.pop('closure_refused', None)
    target['head'] = target['head'][:head_closed]
    target.update(status=status, resolution=dict(resolution))
    return target
