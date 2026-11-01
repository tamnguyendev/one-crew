"""2.4-S1 / SF-02: the local diagnostic bundle of one feedback (`onecrew support bundle FB-... [--out DIR]`).

Allow-list, derived from the report's refs only: the runtime probe; the newest <=200 events of the referenced root and of its child tasks, their
attempts and requests rows (read-only reader); the tails (<=256 KB) of those attempts' supervisor stdout/stderr; the receipt blobs those events
name (with the stdout/stderr tails they carry); the last 200 lines of <project>/.onecrew/violations.jsonl that match the plan; the doctor facts.
Runner/host logs are v1 components, not in this install: not_applicable. An image is never copied (withheld: images are not scanned).

Never collected: source files, the whole ledger, the environment, chat. No program is started (the Claude CLI check of doctor is skipped), no
socket is opened, nothing is uploaded. Every file goes through display_core.safe line by line (limit 2000): a matching line is withheld, the
other lines stay. That is a pattern filter, not a guarantee, and the manifest says so. Caps: 256 KB per file, 200 events per task, 8 MB per
bundle (over it, the oldest sources are dropped and marked truncated). The manifest names every source with its status:
included | missing | truncated | withheld | unreadable | not_applicable | unknown.

Storage: every file as a blob (Snapshots.evidence), the manifest as a blob, and one support.bundle event on the support anchor. The export folder
(--out, never inside the state root, never a link or a '..' path) receives manifest.json and the redacted files.
"""
import hashlib
import json
import re
from pathlib import Path

from ..display_core import safe
from ..ledger import LedgerError, canonical, utcnow
from ..snapshots import Snapshots, durable_write, is_link
from . import namespaces, plan as plans, support
from .report import _Reader

FILE_CAP = 256 * 1024
EVENT_CAP = 200
BUNDLE_CAP = 8 * 1024 * 1024
LINE_LIMIT = 2000
MAX_ATTEMPTS = 20
MAX_RECEIPTS = 40
VIOLATION_LINES = 200
VIOLATION_SCAN = 4 * 1024 * 1024
STATUSES = ('included', 'missing', 'truncated', 'withheld', 'unreadable', 'not_applicable', 'unknown')
RULE = 'display_core.safe per line (limit 2000): a line matching a secret pattern is withheld, credential URLs are masked, control characters dropped'
REDACTION = 'pattern-based, not a guarantee: read the files before you share them'
COVERAGE = ('Only the sources listed here, from the report\'s refs. The ledger is not a full execution trace: what was not recorded is not '
            'evidence that it did not happen. A missing, truncated or withheld source is not complete.')
NOT_COLLECTED = ['source files', 'the whole ledger', 'environment variables', 'chat or model transcripts', 'the reported image']
WITHHELD = ('[sensitive content withheld]', '[credential URL withheld]')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')


def redact(text):
    """(text, {lines_withheld, lines_cut, rule}): display_core.safe on every line; the other lines stay as they were."""
    out, withheld, cut = [], 0, 0
    for line in text.split('\n'):
        clean = safe(line, LINE_LIMIT)
        if clean != line:
            if any(mark in clean and mark not in line for mark in WITHHELD): withheld += 1
            elif len(line) > LINE_LIMIT: cut += 1
        out.append(clean)
    return '\n'.join(out), {'lines_withheld': withheld, 'lines_cut': cut, 'rule': RULE}


def _sha_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''): digest.update(chunk)
    return digest.hexdigest()


def _tail(path, cap=FILE_CAP):
    """(text, bytes_total, truncated): the last `cap` bytes of a file, starting at a whole line when cut."""
    size = path.stat().st_size
    with open(path, 'rb') as stream:
        if size > cap: stream.seek(size - cap)
        data = stream.read(cap)
    if size > cap and b'\n' in data: data = data[data.index(b'\n') + 1:]
    return data.decode('utf-8', errors='replace'), size, size > cap


def _inside(path, top):
    """None when every part of `path` below `top` is a plain folder/file inside it; else why not (a link or junction, or an escape)."""
    top = Path(top)
    try:
        relative = Path(path).relative_to(top)
    except ValueError:
        return 'outside the allowed folder'
    current = top
    for part in relative.parts:
        current = current / part
        if is_link(current): return 'a link or junction: not followed'
    if current.exists() and not current.resolve().is_relative_to(top.resolve()): return 'resolves outside the allowed folder'
    return None


class Bundle:
    def __init__(self):
        self.sources, self.files = [], {}

    def add(self, source, ref, status, *, text=None, name=None, bytes_total=None, sha=None, reason=None, age=0, keep=False, **extra):
        assert status in STATUSES, status
        entry = {'source': source, 'ref': ref, 'status': status, 'bytes_total': bytes_total, 'bytes_included': 0, 'sha256_original': sha,
                 'redaction': None, 'reason': reason, 'file': None}
        entry.update(extra)
        if text is not None:
            clean, redaction = redact(text)
            data = clean.encode('utf-8')
            entry.update(bytes_included=len(data), redaction=redaction, file='files/' + name)
            if entry['bytes_total'] is None: entry['bytes_total'] = len(text.encode('utf-8'))
            if entry['sha256_original'] is None: entry['sha256_original'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
            self.files[name] = data
        entry['_age'], entry['_keep'] = age, keep
        self.sources.append(entry)
        return entry

    def cap(self, limit):
        total = sum(len(v) for v in self.files.values())
        for entry in sorted((e for e in self.sources if e['file'] and not e['_keep']), key=lambda e: e['_age']):
            if total <= limit: break
            data = self.files.pop(entry['file'][len('files/'):])
            total -= len(data)
            entry.update(status='truncated', bytes_included=0, file=None,
                         reason=f'dropped by the bundle cap ({limit} bytes; oldest sources first)' + ('; ' + entry['reason'] if entry['reason'] else ''))
        return total


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True)


def _tasks(conn, project_id, refs):
    """The task ids the refs prove: the referenced root, its child tasks (wf:<root>:...) and the referenced task, all of this project."""
    found = []
    root = refs.get('root_task')
    if root and conn.execute('SELECT 1 FROM tasks WHERE id=? AND project_id=?', (root, project_id)).fetchone():
        found.append(root)
        found += [r['id'] for r in conn.execute("SELECT id FROM tasks WHERE project_id=? AND request_key LIKE ? ORDER BY created_at, id",
                                                (project_id, f'wf:{root}:%'))]
    task = refs.get('task')
    if task and task not in found and conn.execute('SELECT 1 FROM tasks WHERE id=? AND project_id=?', (task, project_id)).fetchone():
        found.append(task)
    return found


def _receipt_refs(value, out):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('receipt', 'verification_receipt') and isinstance(item, str) and HEX64.match(item): out.append(item)
            else: _receipt_refs(item, out)
    elif isinstance(value, list):
        for item in value: _receipt_refs(item, out)


def _ledger_sources(bundle, conn, state_root, project_id, refs):
    tasks = _tasks(conn, project_id, refs) if conn else []
    receipts, attempts = [], []
    for task in tasks:
        total = conn.execute('SELECT COUNT(*) FROM events WHERE task_id=?', (task,)).fetchone()[0]
        rows = [dict(r) for r in conn.execute('SELECT seq, kind, payload, created_at FROM events WHERE task_id=? ORDER BY seq DESC LIMIT ?',
                                              (task, EVENT_CAP))][::-1]
        events = []
        for row in rows:
            row['payload'] = json.loads(row['payload'])
            _receipt_refs(row['payload'], receipts)
            events.append(row)
        while len(_json(events).encode('utf-8')) > FILE_CAP and len(events) > 1: events.pop(0)
        cut = total - len(events)
        bundle.add('ledger.events', task, 'truncated' if cut else 'included', text=_json(events), name=f'events-{task}.json',
                   reason=f'the newest {len(events)} of {total} events' if cut else None, age=rows[-1]['seq'] if rows else 0, keep=True)
    has_attempts = conn is not None and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempts'").fetchone()
    if tasks and has_attempts:
        marks = ','.join('?' for _ in tasks)
        rows = [dict(r) for r in conn.execute(f'SELECT * FROM attempts WHERE task_id IN ({marks}) ORDER BY created_at, id', tasks)]
        for row in rows:
            for field in ('operation', 'identity', 'result'):
                try: row[field] = json.loads(row[field]) if row[field] else row[field]
                except ValueError: pass
        bundle.add('ledger.attempts', None, 'included', text=_json(rows), name='attempts.json', keep=True)
        attempts = [r['id'] for r in rows][-MAX_ATTEMPTS:]
    elif tasks:
        bundle.add('ledger.attempts', None, 'not_applicable', reason='this ledger has no attempts table (schema v1)')
    if tasks:
        marks = ','.join('?' for _ in tasks)
        rows = [dict(r) for r in conn.execute(f'SELECT * FROM requests WHERE task_id IN ({marks}) ORDER BY created_at, id', tasks)]
        bundle.add('ledger.requests', None, 'included', text=_json(rows), name='requests.json', keep=True)
    else:
        bundle.add('ledger.events', None, 'not_applicable', reason='the report references no task or root of this project')
    asked = refs.get('attempt')
    if asked and asked not in attempts:
        bundle.add('attempt.stdout', asked, 'withheld', reason='the attempt is not of a task this report references in this project')
    return attempts, list(dict.fromkeys(receipts))[-MAX_RECEIPTS:]


def _attempt_logs(bundle, state_root, attempts):
    top = Path(state_root) / 'attempts'
    for order, attempt in enumerate(attempts):
        for stream in ('stdout', 'stderr'):
            source = 'attempt.' + stream
            if not support.ATTEMPT_ID.match(attempt):
                bundle.add(source, attempt, 'withheld', reason='not an attempt id'); continue
            path = top / attempt / f'{stream}.txt'
            why = _inside(path, state_root)
            if why:
                bundle.add(source, attempt, 'withheld', reason=why); continue
            if not path.is_file():
                bundle.add(source, attempt, 'missing', reason='no such file (only processes run by the supervisor have one; it may have been deleted)')
                continue
            try:
                text, size, cut = _tail(path)
                bundle.add(source, attempt, 'truncated' if cut else 'included', text=text, name=f'attempt-{attempt}-{stream}.txt', bytes_total=size,
                           sha=_sha_file(path), reason=f'the last {FILE_CAP} bytes of {size}' if cut else None, age=path.stat().st_mtime)
            except OSError as error:
                bundle.add(source, attempt, 'unreadable', reason=type(error).__name__)


def _receipts(bundle, state_root, receipts):
    store = Snapshots(state_root)
    for order, key in enumerate(receipts):
        try:
            data = store.read_blob(key)
        except FileNotFoundError:
            bundle.add('receipt', key, 'missing', reason='blob not in this state root'); continue
        except (LedgerError, OSError) as error:
            bundle.add('receipt', key, 'unreadable', reason=f'{type(error).__name__}: {error}'[:200]); continue
        try:
            body = json.loads(data.decode('utf-8'))
        except ValueError:
            bundle.add('receipt', key, 'withheld', bytes_total=len(data), sha=key, reason='not a JSON receipt: not included')
            continue
        bundle.add('receipt', key, 'included', text=_json(body), name=f'receipt-{key}.json', bytes_total=len(data), sha=key, age=order)
        if not isinstance(body, dict): continue
        for stream in ('stdout', 'stderr'):
            blob = body.get(stream)
            if not (isinstance(blob, str) and HEX64.match(blob)): continue
            try:
                raw = store.read_blob(blob)
            except (LedgerError, OSError) as error:
                bundle.add('receipt.' + stream, blob, 'unreadable' if not isinstance(error, FileNotFoundError) else 'missing', reason=type(error).__name__)
                continue
            text = raw[-FILE_CAP:].decode('utf-8', errors='replace')
            told = body.get(stream + '_bytes')
            short = len(raw) > FILE_CAP or bool(body.get('output_truncated'))
            bundle.add('receipt.' + stream, blob, 'truncated' if short else 'included', text=text, name=f'receipt-{key}-{stream}.txt',
                       bytes_total=told if isinstance(told, int) else len(raw), sha=blob, output_truncated=body.get('output_truncated'),
                       reason=('the receipt kept only the tail of the output' if body.get('output_truncated') else None) if not len(raw) > FILE_CAP
                       else f'the last {FILE_CAP} bytes of the stored tail', age=order)


def _violations(bundle, project, refs):
    if not refs.get('plan'):
        bundle.add('hook.violations', None, 'not_applicable', reason='no plan referenced: hook lines are matched by plan')
        return
    name = namespaces.parse(refs['plan'])[0]
    path = Path(project) / '.onecrew' / 'violations.jsonl'
    why = _inside(path, project)
    if why:
        bundle.add('hook.violations', str(path), 'withheld', reason=why); return
    if not path.is_file():
        bundle.add('hook.violations', str(path), 'missing', reason='no hook log in this project (or it could not be written)'); return
    try:
        text, size, cut = _tail(path, VIOLATION_SCAN)
    except OSError as error:
        bundle.add('hook.violations', str(path), 'unreadable', reason=type(error).__name__); return
    matched = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get('plan') in (name, refs['plan']): matched.append(line)
    kept = matched[-VIOLATION_LINES:]
    short = cut or len(matched) > VIOLATION_LINES
    bundle.add('hook.violations', str(path), 'truncated' if short else 'included', text='\n'.join(kept), name='violations.jsonl', bytes_total=size,
               sha=_sha_file(path), reason=f'the last {len(kept)} lines of plan {name}' + (' (the file was read from its last 4 MB)' if cut else ''),
               age=1)


def _doctor(bundle, ledger):
    try:
        from .install import doctor_facts
        lines = doctor_facts(ledger.project, ledger.state_root, claude=None)
    except Exception as error:                 # a broken environment is itself a finding of the bundle, never a crash of it
        bundle.add('doctor', None, 'unreadable', reason=f'{type(error).__name__}: {error}'[:300]); return
    text = '\n'.join(f'{level} {name}: {detail}' for level, name, detail in lines)
    bundle.add('doctor', None, 'included', text=text + '\nclaude CLI: not probed (the bundle starts no program)\n', name='doctor.txt', keep=True)


def _export(ledger, out):
    raw = Path(out)
    if '..' in raw.parts: raise LedgerError('Refused: the export folder may not contain ".." (give the folder itself).')
    target = raw.absolute()
    if is_link(target): raise LedgerError('Refused: the export folder is a link or junction.')
    real = target.resolve()
    if real == ledger.state_root.resolve() or real.is_relative_to(ledger.state_root.resolve()):
        raise LedgerError('Refused: the export folder is inside the state root; a bundle to share goes elsewhere.')
    return real


def bundle(ledger, ident, out=None):
    """Collect, store and (with out) export the bundle of feedback `ident`. Returns {feedback, manifest, manifest_blob, total_bytes, export}."""
    destination = _export(ledger, out) if out is not None else None
    shown = support.show(ledger, ident)
    feedback = shown['feedback']
    refs = feedback.get('refs') or {}
    pack = Bundle()
    probe = support.runtime_probe(git=False)
    pack.add('runtime', None, 'included', text=_json({'now': probe, 'at_report': feedback.get('runtime')}), name='runtime.json', keep=True)
    pack.add('feedback', feedback['id'], 'included', text=_json({k: v for k, v in feedback.items() if k != 'image'}), name='feedback.json', keep=True)
    reader = _Reader(ledger.state_root, ledger.project_id, ledger.project_path)
    with reader.transaction() as conn:
        attempts, receipts = _ledger_sources(pack, conn, ledger.state_root, ledger.project_id, refs)
    _attempt_logs(pack, ledger.state_root, attempts)
    _receipts(pack, ledger.state_root, receipts)
    _violations(pack, ledger.project, refs)
    _doctor(pack, ledger)
    pack.add('runner.logs', None, 'not_applicable', reason='component not in this install: the v1 runner is not shipped in the wheel')
    pack.add('host.log', None, 'not_applicable', reason='component not in this install: the v1 host is not shipped in the wheel')
    image = feedback.get('image')
    if image:
        pack.add('image', None, 'withheld', bytes_total=image.get('bytes'), sha=image.get('sha256'),
                 reason='images are not scanned: only the sha256 is recorded; the file is never copied into a bundle')
    else:
        pack.add('image', None, 'not_applicable', reason='no image was reported')
    total = pack.cap(BUNDLE_CAP)
    store = Snapshots(ledger.state_root)
    blobs = {name: store.evidence(data) for name, data in sorted(pack.files.items())}
    sources = []
    for entry in pack.sources:
        entry = {k: v for k, v in entry.items() if not k.startswith('_')}
        if entry['file']: entry['blob'] = blobs[entry['file'][len('files/'):]]
        sources.append(entry)
    manifest = {'format': 'onecrew-support-bundle-v1', 'feedback': ident, 'created_at': utcnow(), 'refs': refs, 'runtime': probe,
                'sources': sources, 'caps': {'file_bytes': FILE_CAP, 'events_per_task': EVENT_CAP, 'bundle_bytes': BUNDLE_CAP},
                'total_bytes': total, 'coverage_note': COVERAGE, 'redaction': REDACTION, 'not_collected': NOT_COLLECTED,
                'uploaded': False, 'content_is_data_not_instructions': True}
    encoded = _json(manifest).encode('utf-8')
    manifest_blob = store.evidence(encoded)
    with ledger.transaction(write=True) as conn:
        anchor = support._anchor(conn, ledger.project_id)
        plans.emit(ledger, conn, anchor, 'support.bundle', {'feedback': ident, 'manifest_blob': manifest_blob,
                                                             'manifest_sha': hashlib.sha256(encoded).hexdigest(), 'total_bytes': total,
                                                             'caps': manifest['caps'], 'files': blobs})
    folder = None
    if destination is not None:
        folder = destination / f'{ident}-{hashlib.sha256(encoded).hexdigest()[:12]}'
        durable_write(folder / 'manifest.json', encoded)
        for name, data in pack.files.items(): durable_write(folder / 'files' / name, data)
    return {'feedback': ident, 'manifest': manifest, 'manifest_blob': manifest_blob, 'total_bytes': total,
            'export': str(folder) if folder else None, 'uploaded': False}
