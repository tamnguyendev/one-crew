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
from .display_core import safe
from .snapshots import durable_write
from .locking_core import task_lock
from . import desktop_core
from .desktop_core import home, directory, read, write, lock, configure, status

ACTIONABLE = {'completed', 'failed', 'blocked', 'cancelled', 'waiting', 'paused'}


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
            result.append(dict(id=key, task=row['task_id'], project=row['project_path'],
                               checkpoint=row['seq'], phase=phase, state=state, questions=pending))
    from .v2 import exceptions
    result.extend(exceptions.desktop_snapshots(ledger, after, task))
    return result


def text_report(item):
    if item.get('plan_notice'):
        return item['open_text']
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
    if state.get('report_file'):
        lines += ['', 'Báo cáo đầy đủ: '+str(state['report_file'])]
    if state.get('delivery'):
        lines += ['', 'Các bước: '+safe(canonical({k:v['phase'] for k,v in state['delivery']['nodes'].items()}),4000)]
    if native.get('candidate_report'):
        lines += ['', 'Báo cáo ứng viên của worker (chưa thay thế kiểm chứng độc lập):',
                  safe(str(native['candidate_report']), 6000)]
    for label, value in [('Test (bằng chứng runtime)', state.get('tests')),
                         ('Kiểm chứng độc lập', state.get('verification')),
                         ('Native checks', native.get('checks')),
                         ('Review accepted', native.get('review_accepted')),
                         ('Applied', native.get('applied')),
                         ('Caller census', native.get('caller_summary')),
                         ('APK artifact', (native.get('apk_build') or {}).get('artifact')),
                         ('APK build evidence', native.get('apk_build')),
                         ('Bàn giao', state.get('deliveries'))]:
        lines += ['', label+': '+safe(canonical(value), 4000)]
    lines += ['', 'Timeout checkpoints: '+str(len(native.get('timeout_checkpoints') or [])),
              'Assistance: '+safe(str(state.get('assistance', 'unknown')), 500),
              '', 'Giới hạn: đây là bằng chứng runtime đã lưu. Test bỏ qua không chứng minh '
              'widget/device/server thật đã đạt. null nghĩa là chưa có bằng chứng.',
              'Đóng cửa sổ không trả lời câu hỏi, không duyệt, không hủy hoặc tiếp tục task.']
    return '\n'.join(lines)+'\n'


def launch(root, key):
    return desktop_core.launch(root, key, module='onecrew.desktop_window')


def publish(ledger, task=None):
    from .v2 import exceptions
    return desktop_core.publish(ledger, task, snapshots=snapshots, text_report=text_report,
        launcher=launch, observe=exceptions.observe_project, write_report=durable_write)


def best_effort(ledger):
    return desktop_core.best_effort(ledger, publish=publish)


def retry(ledger, key):
    return desktop_core.retry(ledger, key, publish=publish)


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
