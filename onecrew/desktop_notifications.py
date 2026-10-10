"""Event-driven Windows result windows. No scheduler, model, or task mutation.

The outbox is separate from the task database (including its full disk). A mapped
window is delivery evidence, never evidence of attention or task approval.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
from contextlib import contextmanager

from .ledger import Ledger, LedgerError, canonical, content_hash, utcnow
from .monitor import safe
from .snapshots import durable_write
from .workflow import task_lock

ACTIONABLE = {'completed', 'failed', 'blocked', 'cancelled', 'waiting', 'paused'}


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


def questions(conn, task):
    result = []
    for row in conn.execute("SELECT * FROM requests WHERE task_id=? AND state='pending'", (task,)):
        result.append(dict(id=row['id'], revision=row['revision'], **json.loads(row['payload'])))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_questions'").fetchone():
        for row in conn.execute("SELECT * FROM conversation_questions WHERE state='pending'"):
            data = json.loads(row['payload'])
            if task in data.get('affected_tasks', []):
                result.append(dict(id=row['id'], revision=row['revision'], **data))
    return sorted(result, key=lambda item: item['id'])


def snapshots(ledger, after=0, task=None):
    """Latest checkpoint only: never show an old failure after it has recovered."""
    with ledger.transaction() as conn:
        if conn is None:
            return []
        query = """SELECT e.*,t.project_path FROM events e JOIN tasks t ON t.id=e.task_id
            WHERE t.project_id=? AND e.kind='workflow.checkpoint' AND e.seq=(
            SELECT MAX(x.seq) FROM events x WHERE x.task_id=e.task_id AND x.kind=e.kind)"""
        args = [ledger.project_id]
        if task:
            query += ' AND e.task_id=?'
            args.append(task)
        result = []
        for row in conn.execute(query, args):
            state = json.loads(row['payload'])
            phase = state.get('phase')
            pending = questions(conn, row['task_id'])
            if phase not in ACTIONABLE and not pending:
                continue
            # Consecutive checkpoints in the same phase belong to one outcome.
            previous = conn.execute("""SELECT COALESCE(MAX(seq),0) FROM events WHERE task_id=?
                AND kind='workflow.checkpoint' AND seq<? AND json_extract(payload,'$.phase')!=?""",
                (row['task_id'], row['seq'], phase)).fetchone()[0]
            first = conn.execute("""SELECT MIN(seq) FROM events WHERE task_id=?
                AND kind='workflow.checkpoint' AND seq>?""", (row['task_id'], previous)).fetchone()[0]
            if not task and row['seq'] <= after:
                continue
            identity = ([{'id':q['id'], 'revision':q['revision']} for q in pending] if pending else
                        {'phase':phase, 'first':first})
            key = content_hash({'task':row['task_id'], 'outcome':identity})[:32]
            result.append(dict(id=key, task=row['task_id'], project=row['project_path'],
                               checkpoint=row['seq'], phase=phase, state=state, questions=pending))
        return result


def text_report(item):
    state = item['state']
    native = state.get('native_change') or {}
    lines = ['OneCrew — Kết quả / cần xử lý', 'Task: '+item['task'],
             'Project: '+safe(item['project'], 1000), 'Trạng thái: '+str(item['phase']),
             'Checkpoint: '+str(item['checkpoint']), '', safe(state.get('message') or '', 3000)]
    for q in item['questions']:
        lines += ['', 'CẦN ANH XỬ LÝ: '+safe(q.get('question') or '', 3000),
                  safe(q.get('reason') or '', 2000), 'Request: '+q['id'], 'Revision: '+q['revision'],
                  'Lựa chọn: '+safe(canonical(q.get('options', [])), 2500)]
    if state.get('report'):
        lines += ['', 'Báo cáo runtime:', safe(str(state['report']), 12000)]
    if native.get('candidate_report'):
        lines += ['', 'Báo cáo ứng viên của worker (chưa thay thế kiểm chứng độc lập):',
                  safe(str(native['candidate_report']), 6000)]
    for label, value in [('Test (bằng chứng runtime)', state.get('tests')),
                         ('Kiểm chứng độc lập', state.get('verification')),
                         ('Native checks', native.get('checks')),
                         ('Review accepted', native.get('review_accepted')),
                         ('Applied', native.get('applied')),
                         ('Bàn giao', state.get('deliveries'))]:
        lines += ['', label+': '+safe(canonical(value), 4000)]
    lines += ['', 'Timeout checkpoints: '+str(len(native.get('timeout_checkpoints') or [])),
              'Assistance: '+safe(str(state.get('assistance', 'unknown')), 500),
              '', 'Giới hạn: đây là bằng chứng runtime đã lưu. Test bỏ qua không chứng minh '
              'widget/device/server thật đã đạt. null nghĩa là chưa có bằng chứng.',
              'Đóng cửa sổ không trả lời câu hỏi, không duyệt, không hủy hoặc tiếp tục task.']
    return '\n'.join(lines)+'\n'


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


def launch(root, key):
    if os.name != 'nt':
        raise OSError('Windows desktop is required.')
    # Argument vector only. No event text can become a shell command.
    return subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'onecrew.desktop_window',
                             str(root), key], cwd=Path(__file__).resolve().parents[1],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)


def publish(ledger, task=None):
    root = directory(ledger)
    config = read(root/'config.json', {})
    if not config.get('enabled'):
        return {'enabled':False, 'launched':[]}
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
            durable_write(report, text_report(item).encode('utf-8'))
            record = dict(id=item['id'], task=item['task'], project=item['project'],
                          checkpoint=item['checkpoint'], phase=item['phase'],
                          status='launching', report=str(report), created_at=utcnow(),
                          transport='windows-window', chat_callback=False)
            write(path, record)  # Claim before launch. Unknown launch outcomes never auto-replay.
            launches.append(item['id'])
    launched, errors = [], []
    for key in launches:
        try:
            launch(root, key)
            launched.append(key)
        except OSError as error:
            with lock(root):
                record = read(root/(key+'.json'))
                record.update(status='pending', error=safe(str(error), 1000))
                write(root/(key+'.json'), record)
            errors.append({'id':key, 'error':safe(str(error), 1000)})
    return dict(enabled=True, launched=launched, errors=errors, directory=str(root))


def best_effort(ledger):
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


def retry(ledger, key):
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--state-root', type=Path)
    commands = parser.add_subparsers(dest='group', required=True).add_parser('desktop').add_subparsers(dest='command', required=True)
    for name in ('enable', 'disable', 'status', 'show', 'retry'):
        command = commands.add_parser(name)
        if name=='show': command.add_argument('--task', required=True)
        if name=='retry': command.add_argument('--id', required=True)
    args = parser.parse_args(argv)
    ledger = Ledger(args.project, args.state_root)
    try:
        if args.command in ('enable', 'disable'): result = configure(ledger, args.command=='enable')
        elif args.command=='show': result = publish(ledger, args.task)
        elif args.command=='retry': result = retry(ledger, args.id)
        else: result = status(ledger)
        print(canonical(result))
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print('Desktop notification: '+str(error), file=sys.stderr)
        return 2
