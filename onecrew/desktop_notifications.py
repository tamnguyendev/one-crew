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


def legacy_home():
    """Pre-12/10 outbox root (install directory or ONECREW_DESKTOP_HOME); read only by the one-time migration."""
    return Path(os.environ.get('ONECREW_DESKTOP_HOME') or
                Path(__file__).resolve().parents[1] / '.onecrew' / 'desktop').resolve()


def directory(ledger):
    """<state_root>/desktop: runners started by the keeper, a reply or another runtime share one flag and dedup set."""
    root = Path(ledger.state_root).resolve() / 'desktop'
    if not (root / 'config.json').exists():
        try:
            migrate(ledger, root)
        except (OSError, ValueError) as error:
            # Never fatal to a committed checkpoint or a read: the config is written last, so the next call retries.
            if not (root / 'config.json').exists():
                try:
                    write(root / 'error.json', {'status': 'migration_pending', 'error': safe(str(error), 1000)})
                except OSError:
                    pass
    return root


def migrate(ledger, root):
    """Copy the old per-install outbox once; the old files stay untouched. The config is written last, so an
    interrupted migration is completed by the next call and never re-launches an outcome already delivered."""
    old = legacy_home() / content_hash(str(Path(ledger.state_root).resolve()).casefold())[:16]
    if not (old / 'config.json').is_file():
        return
    with lock(root):
        if (root / 'config.json').exists():
            return
        for path in sorted(old.glob('*')):
            if not path.is_file() or len(path.stem) != 32 or path.suffix not in ('.json', '.txt') or (root / path.name).exists():
                continue
            data = path.read_bytes()
            if path.suffix == '.json':
                record = json.loads(data)
                record.update(report=str(root / (path.stem + '.txt')), migrated_from=str(old))
                data = canonical(record).encode('utf-8')
            durable_write(root / path.name, data)
        write(root / 'config.json', dict(read(old / 'config.json'), migrated_from=str(old)))
        if (read(root / 'error.json') or {}).get('status') == 'migration_pending':
            (root / 'error.json').unlink(missing_ok=True)


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
            from .delivery_store import root_id
            parent=root_id(conn,row['task_id'])
            if parent and parent!=row['task_id']: continue
            state = json.loads(row['payload'])
            phase = state.get('phase')
            pending = questions(conn, row['task_id'])
            if parent==row['task_id']:
                for child in conn.execute('SELECT task_id FROM delivery_children WHERE root=?',(parent,)):
                    pending.extend(questions(conn,child[0]))
            if phase not in ACTIONABLE and not pending:
                continue
            # An answered recovery question is being applied by the coordinator; it is not a new outcome.
            if phase == 'waiting' and state.get('waiting_reason') == 'decision' and not pending:
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
            result.append(dict(id=key, task=row['task_id'], project=row['project_path'], state_root=str(ledger.state_root),
                               checkpoint=row['seq'], phase=phase, state=state, questions=pending))
        return result


# Generic evidence of a delivery root, whatever the project kind: (label, node kinds, distinctive key, fields shown).
EVIDENCE = (('Artifact', {'build', 'apk_audit', 'node_build', 'node_build_live', 'version', 'install'}, 'artifact',
             ('artifact', 'apk', 'sha256', 'bytes', 'variant', 'manifest_version', 'dist_tree_sha256', 'dist_manifest_sha256')),
            ('E2E', {'device', 'e2e_mock', 'e2e_live'}, 'checks',
             ('checks', 'counts', 'runs', 'repeat', 'min_checks', 'writes', 'summary', 'scenario')),
            ('Git', {'commit'}, 'commit', ('commit', 'commits', 'branch', 'head', 'base_head', 'ref', 'pushed', 'paths')))
# A completed root is a full loop only when its plan also built and ran E2E; tests alone never are.
LOOP = (('build', {'build', 'node_build', 'node_build_live'}), ('E2E', {'device', 'e2e_mock', 'e2e_live'}))


def root_view(state):
    """(delivery state, {node id: row}, {node id: kind}) of a delivery root; empty for any other checkpoint shape."""
    d = state.get('delivery') if isinstance(state.get('delivery'), dict) else {}
    plan = state.get('plan') if isinstance(state.get('plan'), dict) else {}
    rows = {k: v for k, v in (d.get('nodes') or {}).items() if isinstance(v, dict)} if isinstance(d.get('nodes'), dict) else {}
    kinds = {n.get('id'): n.get('kind') for n in plan.get('nodes') or [] if isinstance(n, dict)}
    return d, rows, kinds


def title(item):
    """Level-aware headline: partial, plan-only or standalone work is never titled a full-loop completion."""
    state, phase = item['state'], item['phase']
    if item['questions']:
        return 'Cần anh trả lời'
    if phase != 'completed':
        return {'blocked':'Bị chặn', 'failed':'Thất bại', 'cancelled':'Đã hủy', 'paused':'Tạm dừng'}.get(phase, 'Đang chờ')
    d, rows, kinds = root_view(state)
    if not d:
        return 'Hoàn thành job đơn lẻ (không phải trọn luồng)'
    criteria = d.get('criteria') if isinstance(d.get('criteria'), dict) else {}
    not_run = [k for k, v in criteria.items() if v != 'passed']
    not_run += [k for k, r in rows.items() if isinstance(r.get('receipt'), dict) and r['receipt'].get('skipped') or r.get('phase') != 'passed']
    if not_run or state.get('verification') != 'passed' or d.get('technical_verified') is False:
        return safe('Hoàn thành một phần (not_run: '+(', '.join(dict.fromkeys(not_run)) or 'chưa kiểm chứng')+')', 200)
    missing = [name for name, group in LOOP if not set(kinds.values()) & group]
    return 'Hoàn thành theo kế hoạch (không có: '+', '.join(missing)+')' if missing else 'Hoàn thành trọn luồng'


def evidence(state):
    """(label, fields) per delivery node that produced an artifact, E2E or git receipt; only fields present."""
    d, rows, kinds = root_view(state)
    result = []
    for node, row in rows.items():
        receipt = row.get('receipt')
        if not isinstance(receipt, dict):
            continue
        for label, group, key, fields in EVIDENCE:
            if kinds.get(node) in group or kinds.get(node) not in KNOWN and key in receipt:
                shown = {k: receipt[k] for k in ('passed', 'skipped')+fields if k in receipt}
                if receipt.get('skipped') or not receipt.get('passed'):
                    shown['detail'] = receipt.get('detail')
                result.append((label+' ('+node+')', shown))
                break
    if d.get('git'):
        result.append(('Git baseline', d['git']))
    return result


KNOWN = {'change', 'regression', 'review', 'handover'}.union(*(group for _, group, _, _ in EVIDENCE))


def quoted(value):
    return "'"+str(value).replace("'", "''")+"'"


def reply(item, q):
    """The exact command the user runs, attributed to the user; a reply restarts the stopped root by itself."""
    base = ("$env:ONECREW_ACTOR='user'; & "+quoted(Path(__file__).resolve().parents[1]/'onecrew.ps1')+
            ' --project '+quoted(item['project'])+' --state-root '+quoted(item.get('state_root') or ''))
    if not str(q['id']).startswith('REQ-'):
        return ['Trả lời (PowerShell): '+base+' conversation reply --file <reply.json> với {"qid":"'+q['id']+
                '","revision":"'+q['revision']+'","choice":"<option>","source":"user","reference":"<câu trả lời của anh>"}']
    return ['Trả lời (PowerShell, chọn một dòng):']+['  '+o['id']+': '+base+' request reply '+q['id']+' --revision '+
            q['revision']+' --choice '+o['id']+' --decided-by user' for o in q.get('options', [])[:8] if isinstance(o, dict) and o.get('id')]


def text_report(item):
    state = item['state']
    native = state.get('native_change') or {}
    lines = ['OneCrew — '+title(item), 'Task: '+item['task'],
             'Project: '+safe(item['project'], 1000), 'Trạng thái: '+str(item['phase']),
             'Checkpoint: '+str(item['checkpoint']), '', safe(state.get('message') or '', 3000)]
    for q in item['questions']:
        lines += ['', 'CẦN ANH XỬ LÝ: '+safe(q.get('question') or '', 3000),
                  safe(q.get('reason') or '', 2000), 'Request: '+q['id'], 'Revision: '+q['revision'],
                  'Lựa chọn: '+safe(canonical(q.get('options', [])), 2500)]
        lines += [safe(line, 3000) for line in reply(item, q)]
    if state.get('report'):
        lines += ['', 'Báo cáo runtime:', safe(str(state['report']), 12000)]
    if state.get('report_file'):
        lines += ['', 'Báo cáo đầy đủ: '+str(state['report_file'])]
    if state.get('delivery'):
        lines += ['', 'Các bước: '+safe(canonical({k:v['phase'] for k,v in state['delivery']['nodes'].items()}),4000)]
    if native.get('candidate_report'):
        lines += ['', 'Báo cáo ứng viên của worker (chưa thay thế kiểm chứng độc lập):',
                  safe(str(native['candidate_report']), 6000)]
    labels = [('Test (bằng chứng runtime)', state.get('tests')),
              ('Kiểm chứng độc lập', state.get('verification')),
              ('Native checks', native.get('checks')),
              ('Review accepted', native.get('review_accepted')),
              ('Applied', native.get('applied')),
              ('Caller census', native.get('caller_summary'))]
    if native.get('apk_build'):
        labels += [('APK artifact', native['apk_build'].get('artifact')), ('APK build evidence', native['apk_build'])]
    for label, value in labels+evidence(state)+[('Bàn giao', state.get('deliveries'))]:
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
    argv = [sys.executable, '-X', 'utf8', '-m', 'onecrew.desktop_window', str(root), key]
    options = dict(cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, close_fds=True)
    try:
        # Same detached breakaway as runner.start: the window outlives the launching command's Job (entry shell, keeper).
        return subprocess.Popen(argv, creationflags=0x8 | 0x200 | 0x01000000, **options)
    except PermissionError:
        # The Job forbids breakaway: a detached window is still better than none.
        return subprocess.Popen(argv, creationflags=0x8 | 0x200, **options)


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
                          checkpoint=item['checkpoint'], phase=item['phase'], title=title(item),
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
        except (OSError, ValueError):
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
