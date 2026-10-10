"""Page complete oversized evidence into the native review workspace.

The prompt retains a hash-addressed manifest, never a truncated diff. Files are
runtime-owned context so a later worker repair cannot silently change them.
"""
from pathlib import Path

from .ledger import LedgerError, canonical
from .snapshots import bytes_hash, durable_write, safe_file

PROMPT_LIMIT = 60000  # leave space for instructions and the invocation wrapper
PAGE_CHARS = 12000


def packet(runtime, state, values):
    result = dict(values)
    if len(canonical(result)) <= PROMPT_LIMIT:
        return result
    native = state['native_change']
    workspace = Path(native['workspace'])
    refs = {}
    for key in sorted(values, key=lambda k: len(canonical(values[k])), reverse=True):
        if len(canonical(result)) <= PROMPT_LIMIT:
            break
        value = values[key]
        raw = value if isinstance(value, str) else canonical(value)
        if len(raw) < PAGE_CHARS:
            continue
        digest = bytes_hash(raw.encode('utf-8'))
        pages = []
        for offset in range(0, len(raw), PAGE_CHARS):
            data = raw[offset:offset + PAGE_CHARS].encode('utf-8')
            name = 'ONECREW_REVIEW_EVIDENCE/' + digest + '-' + str(len(pages) + 1) + '.txt'
            target = safe_file(workspace, name)
            page_hash = bytes_hash(data)
            if target.exists():
                if target.read_bytes() != data:
                    raise LedgerError('Native review evidence changed: ' + name)
            else:
                durable_write(target, data)
            # Preserve the unowned-file guard on continuation/repair. Only exact
            # bytes written and verified by this runtime enter its baseline.
            if 'tool_baseline' in native:
                old = native['tool_baseline'].get(name)
                if old is not None and old != page_hash:
                    raise LedgerError('Native review evidence baseline changed: ' + name)
                native['tool_baseline'][name] = page_hash
            pages.append({'path': name, 'sha256': page_hash, 'bytes': len(data)})
        refs[key] = {'encoding': 'utf-8', 'format': 'text' if isinstance(value, str) else 'json',
                     'sha256': digest, 'characters': len(raw), 'pages': pages,
                     'complete': True, 'truncated': False}
        result[key] = {'external_evidence': refs[key],
                       'instructions': 'Read ALL listed pages in order with native Read before deciding. '
                                       'Concatenating pages gives the complete original evidence; page boundaries may split lines. '
                                       'If a page is unavailable, do not accept: report the evidence access blocker.'}
    if len(canonical(result)) > PROMPT_LIMIT:
        raise LedgerError('Native review manifest exceeds bounded prompt; narrow explicit context.')
    native['review_evidence'] = refs
    return result
