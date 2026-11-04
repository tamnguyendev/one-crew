"""The existing v1 Windows desktop outbox; callbacks supply views, never a new queue."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
from contextlib import contextmanager
from .ledger import LedgerError, canonical, content_hash, utcnow
from .display_core import safe
from .snapshots import durable_write
from .locking_core import task_lock

def home():
    return Path(os.environ.get('ONECREW_DESKTOP_HOME') or
                Path(__file__).resolve().parents[1] / '.onecrew' / 'desktop').resolve()


def directory(ledger):
    return home() / content_hash(str(ledger.state_root.resolve()).casefold())[:16]


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write(path, value):
    durable_write(path, canonical(value).encode('utf-8'))


@contextmanager
def lock(root, name='desktop'):
    # UI startup and a checkpoint may overlap. Bounded contention, no polling of work.
    manager = None
    for attempt in range(40):
        candidate = task_lock(SimpleNamespace(state_root=root), name)
        try:
            candidate.__enter__()
            manager = candidate
            break
        except LedgerError:
            if attempt == 39:
                raise
            time.sleep(.025)
    try:
        yield
    finally:
        manager.__exit__(None, None, None)


def configure(ledger, enabled):
    root = directory(ledger)
    with lock(root):
        config = read(root/'config.json')
        if config is None:
            with ledger.transaction() as conn:
                start = conn.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0] if conn else 0
            config = {'since':start, 'state_root':str(ledger.state_root)}
        config.update(enabled=enabled, transport='windows-window', chat_callback=False)
        write(root/'config.json', config)
    return dict(config, directory=str(root))


def launch(root, key, module='onecrew.v2.notification_window'):
    if os.name != 'nt':
        raise OSError('Windows desktop is required.')
    # Argument vector only. No event text can become a shell command.
    return subprocess.Popen([sys.executable, '-X', 'utf8', '-m', module,
                             str(root), key], cwd=Path(__file__).resolve().parents[1],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)


def publish(ledger, task=None, *, snapshots, text_report, launcher, observe=None, write_report=durable_write):
    root = directory(ledger)
    config = read(root/'config.json', {})
    if not config.get('enabled'):
        return {'enabled':False, 'launched':[]}
    if observe: observe(ledger)
    current = snapshots(ledger, config['since'], task)
    launches = []
    with lock(root):
        # Disable may race with the read above.
        if not read(root/'config.json', {}).get('enabled'):
            return {'enabled':False, 'launched':[]}
        for item in current:
            path = root/(item['id']+'.json')
            record = read(path)
            if record and record['status'] != 'pending':
                continue
            report = root/(item['id']+'.txt')
            write_report(report, text_report(item).encode('utf-8'))
            record = dict(id=item['id'], task=item['task'], project=item['project'],
                          checkpoint=item['checkpoint'], phase=item['phase'],
                          status='launching', report=str(report), created_at=utcnow(),
                          transport='windows-window', chat_callback=False)
            write(path, record)  # Claim before launch. Unknown launch outcomes never auto-replay.
            launches.append(item['id'])
    launched, errors = [], []
    for key in launches:
        try:
            launcher(root, key)
            launched.append(key)
        except OSError as error:
            with lock(root):
                record = read(root/(key+'.json'))
                record.update(status='pending', error=safe(str(error), 1000))
                write(root/(key+'.json'), record)
            errors.append({'id':key, 'error':safe(str(error), 1000)})
    return dict(enabled=True, launched=launched, errors=errors, directory=str(root))


def best_effort(ledger, *, publish):
    try:
        result = publish(ledger)
        if result.get('enabled'):
            (directory(ledger)/'error.json').unlink(missing_ok=True)
        return result
    except (OSError, ValueError, sqlite3.Error) as error:
        result = {'status':'delivery_pending', 'error':safe(str(error), 1000)}
        try:
            write(directory(ledger)/'error.json', result)
        except OSError:
            pass
        return result


def status(ledger):
    root = directory(ledger)
    records = [read(path) for path in root.glob('*.json') if len(path.stem)==32]
    return dict(config=read(root/'config.json', {'enabled':False}), directory=str(root),
                records=records, last_error=read(root/'error.json'), chat_callback=False)


def retry(ledger, key, *, publish):
    if len(key)!=32 or any(c not in '0123456789abcdef' for c in key):
        raise LedgerError('Invalid notification ID.')
    root = directory(ledger)
    # An open window owns this lock. Retrying can never create a second live window.
    with lock(root, 'ui.'+key), lock(root):
        record = read(root/(key+'.json'))
        if not record:
            raise LedgerError('Unknown notification.')
        if record['status'] in ('shown', 'closed'):
            raise LedgerError('Already shown; no automatic redelivery.')
        record['status'] = 'pending'
        write(root/(key+'.json'), record)
    # Regenerate from current truth; never reopen a stale question or past failure.
    return publish(ledger, record['task'])
