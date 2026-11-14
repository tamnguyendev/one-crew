"""OBS-2C data set on a real temporary ledger (no provider, no real hook, registry or ledger).

More plan roots than one page (W001…W150, newest first, W007 old and found by its words), the four origins (owner quote, owner author,
nothing recorded, an AI coordinator), REPAIR: an engine root built through the real engine (a failed check, a repair task prepared from
it, child tasks of the nodes), finished work (ACCEPTED, CLOSED), a pass whose receipt is in the store and one whose receipt is gone
(RCPT-OK / RCPT-GONE), approvals whose session is declared owner and unknown, SAME in two projects of one ledger, a secret in an owner
quote and in an amendment reason. Plans, REPAIR's approval, the engine and the repair go through their real API; the events no API writes
cheaply in a test (plan.accepted, plan.closed, a command milestone's verdict.receipt_issued / verdict.recorded, and the other approvals,
with approve's own payload and session record: see `approved`) are emitted with plans.emit, as tests/obs1_ux_fixture.py does.
"""
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from onecrew.control_core import Control, migrate
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan as plans, repair_tasks, tracking

ACTOR = 'ONECREW_' + 'ACTOR'
AI_MARKERS = ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', ACTOR, 'ONECREW_V2_REQUIRE_PLAN')
SECRET = 'ghp_' + 'Q7k' * 10
OLD, OLD_WORDS = 'W007', 'kỳ lân bạc'
CAPS = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine']


@contextlib.contextmanager
def owner_shell(actor=None):
    """A shell without AI-session markers (as tests/test_v2_l1.Fixture); `actor` declares the actor recorded in an approval's session."""
    with patch.dict(os.environ):
        for name in AI_MARKERS: os.environ.pop(name, None)
        if actor: os.environ[ACTOR] = actor
        yield


def contract(title, *, origin=None, engine_root=False, path='a.txt'):
    value = {'schema_version': 2, 'title': title, 'size': 'S',
             'understanding': {'restated_goal': title + ' (mục tiêu kỹ thuật)', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': [path]},
                               'assumptions': [], 'confidence': 'high', 'unknowns': []},
             'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': path}, 'why': 'tệp thử có sẵn'}],
             'output': ['Kết quả thử đọc được'], 'scope': {'owned': [path]}, 'non_goals': ['Không làm gì ngoài sổ thử'],
             'items': [{'id': 'I1', 'title': 'Làm và kiểm', 'tier': 'must', 'milestone': 'M1'}],
             'milestones': [{'id': 'M1', 'title': 'Kiểm kết quả thử', 'covers': ['O1'],
                             'verifier': {'type': 'owner-manual', 'config': {}} if engine_root else
                             {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print(1)']}}}],
             'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}
    if engine_root:
        value['authority'] = {'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}
    if origin:
        value['origin'] = origin
        value['items'][0]['source'] = 'origin'
    return value


def node(nid, path='a.txt', integration=False):
    return {'id': nid, 'goal': 'Kiểm lại kết quả tích hợp' if integration else 'Chuẩn bị nội dung đầu ra',
            'input': [], 'output': ['Kết quả đối chiếu được'], 'acceptance': ['O1'],
            'depends': [{'node': 'C', 'requires': 'verified'}] if integration else [],
            'read': [path], 'write': [] if integration else [path], 'resources': [],
            'estimate_seconds': [1, 2], 'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': [{'id': 'check-' + nid, 'spec': 'Nội dung có dấu hiệu kết quả thử'}], 'integration': integration}


def make_project(path):
    path.mkdir(parents=True)
    (path / 'a.txt').write_text('base\n', encoding='utf-8')
    for args in (('init', '-q'), ('config', 'user.name', 'OBS2C fixture'), ('config', 'user.email', 'fixture@localhost'),
                 ('add', 'a.txt'), ('commit', '-q', '-m', 'base')):
        subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True)
    return path


def task_of(ledger, name):
    with ledger.transaction() as conn:
        return plans.anchor_events(ledger, conn, name)['task_id']


def emit(ledger, name, kind, payload):
    with ledger.transaction(write=True) as conn:
        plans.emit(ledger, conn, task_of(ledger, name), kind, payload)


def owner(quote, by='owner'):
    return {'by': by, 'at': '2026-11-01', 'quote': quote}


def approved(ledger, name, actor=None):
    """plan.approved with the payload plans.approve writes (revision, sha, by, reference, this process's session record from
    ownership.session_info), without the git snapshots of the project approve takes first (tens of git calls: minutes on a loaded machine
    for every root). The reader sees the same event; REPAIR, which the engine runs, is approved through plans.approve itself."""
    from onecrew.v2 import ownership
    with owner_shell(actor):
        with ledger.transaction(write=True) as conn:
            state = plans.anchor_events(ledger, conn, name)
            revision = state['latest']
            plans.emit(ledger, conn, state['task_id'], 'plan.approved', {'plan': name, 'revision': revision, 'sha': state['revisions'][revision]['sha'],
                                                                         'by': 'owner', 'reference': 'fixture approval', 'ticked': [], 'chosen': None,
                                                                         'base_artifact': None, **ownership.session_info()})


def repair_root(ledger, store, name='REPAIR'):
    """An engine root through the real engine: node C fails its check, a repair task is prepared from that receipt, C runs again and passes."""
    control = Control(ledger)
    plans.propose(ledger, name, contract('Sửa phép cộng và kiểm lại trước bàn giao', engine_root=True,
                                         origin=owner('Sửa phép cộng cho đúng rồi bàn giao')), 'claude', workflow=True, capabilities=CAPS)
    plans.approve(ledger, name, 'owner', 'fixture approval')
    internal_plan.revise(ledger, name, [node('C'), node('I', integration=True)], reason='Tách phần tạo kết quả và kiểm tích hợp', evidence=['a.txt:1'])

    def execute(ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        generation = engine.state(ledger, name)['nodes'][item['id']]['generation']
        marker = 'first incomplete result' if item['id'] == 'C' and generation == 0 else 'Readable fixture result'
        artifact = store.blob((item['id'] + '\n' + marker + '\n').encode())
        receipt = store.blob(json.dumps({'kind': 'fixture-executor-receipt', 'actor': 'synthetic fixture', 'node': item['id'],
                                         'attempt': attempt['id'], 'artifact': artifact}).encode())
        control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def checker(item, artifact):
        passed = b'Readable fixture result' in store.read_blob(artifact)
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'pass' if passed else 'fail',
                'evidence': store.blob(b'marker found' if passed else b'marker missing')} for c in item['checks']]}

    engine.step(ledger, name, execute, control=control)
    engine.verify(ledger, name, 'C', checker)
    failed = engine.state(ledger, name)['nodes']['C']['verification_receipt']
    repair_tasks.prepare(ledger, name, 'C', 'C', reason='Sửa đúng phần việc có kiểm không đạt, giữ yêu cầu kiểm tích hợp', evidence=[failed])
    engine.step(ledger, name, execute, control=control)
    engine.verify(ledger, name, 'C', checker)


def verdict(ledger, store, name, *, keep_receipt):
    """A command milestone's pass as verdict.run records it (receipt announced, then the verdict). keep_receipt False: the receipt key the
    events name is not in the store (lost to retention or deleted)."""
    body = json.dumps({'kind': 'command-receipt', 'plan': name, 'milestone': 'M1', 'exit_code': 0, 'note': 'fixture'}, sort_keys=True).encode()
    key = store.blob(body) if keep_receipt else __import__('hashlib').sha256(body + b'gone').hexdigest()
    artifact = '0123456789abcdef0123456789abcdef01234567'
    emit(ledger, name, 'verdict.receipt_issued', {'plan': name, 'revision': 1, 'milestone': 'M1', 'receipt': key})
    emit(ledger, name, 'verdict.recorded', {'plan': name, 'revision': 1, 'milestone': 'M1', 'result': 'pass', 'by': 'command',
                                            'receipt': key, 'artifact_sha': artifact})
    return key


def create(work, count=150, repair=True):
    work = Path(work).resolve()
    a, b = make_project(work / 'du-an-a'), make_project(work / 'du-an-b')
    state = work / 'state'
    la, lb = Ledger(a, state), Ledger(b, state)
    store = Snapshots(state)
    with owner_shell():
        migrate(la)
        if repair: repair_root(la, store)
        for i in range(1, count + 1):
            name, kind = f'W{i:03d}', i % 4
            title = f'Việc thử số {i:03d}' + (' — ' + OLD_WORDS if name == OLD else '')
            origin = owner(f'Chủ giao việc số {i:03d}') if kind == 0 else owner(f'Điều phối giao việc số {i:03d}', by='claude-coordinator') if kind == 3 else None
            plans.propose(la, name, contract(title, origin=origin), 'owner' if kind == 1 else 'claude')
        plans.propose(la, 'SAME', contract('Việc trùng tên ở dự án A', origin=owner('Làm việc trùng tên ở A')), 'claude')
        plans.propose(lb, 'SAME', contract('Việc trùng tên ở dự án B', origin=owner('Làm việc trùng tên ở B')), 'claude')
        plans.propose(la, 'APPROVED-OWNER', contract('Việc duyệt từ phiên tự khai là chủ', origin=owner('Làm việc duyệt có khai báo')), 'claude')
        plans.propose(la, 'APPROVED-UNKNOWN', contract('Việc duyệt từ phiên không khai báo', origin=owner('Làm việc duyệt không khai báo')), 'claude')
        plans.propose(la, 'CLOSED', contract('Việc bị chủ huỷ trước khi chạy', engine_root=True, origin=owner('Làm thử rồi huỷ')), 'claude',
                      workflow=True, capabilities=CAPS)
        plans.propose(la, 'ACCEPTED', contract('Việc đã được nghiệm thu', origin=owner('Làm và nghiệm thu')), 'claude')
        for name, keep in (('RCPT-OK', True), ('RCPT-GONE', False)):
            plans.propose(la, name, contract('Mốc đạt, receipt ' + ('còn trong kho' if keep else 'đã mất'), origin=owner('Kiểm mốc ' + name)), 'claude')
        value = contract('Việc có bí mật trong lời giao', origin=owner('Dùng khoá ' + SECRET + ' để thử'))
        plans.propose(la, 'SECRET', value, 'claude')
        value = dict(value, title='Việc có bí mật trong lời giao (bản 2)')
        plans.amend(la, 'SECRET', value, 'đổi tên; khoá cũ ' + SECRET[:24], 'claude')
    approved(la, 'APPROVED-UNKNOWN')                       # no declaration: the session is recorded as unknown
    approved(la, 'APPROVED-OWNER', actor='owner')          # a shell that declares the owner: ai_session False
    for name in ('CLOSED', 'ACCEPTED', 'RCPT-OK', 'RCPT-GONE'): approved(la, name)
    with owner_shell():
        emit(la, 'CLOSED', 'plan.closed', {'revision': 1, 'reason': 'chủ huỷ việc, chưa có kết quả'})
        verdict(la, store, 'ACCEPTED', keep_receipt=True)
        emit(la, 'ACCEPTED', 'plan.accepted', {'plan': 'ACCEPTED', 'revision': 1, 'by': 'owner', 'artifact_sha': '0123456789abcdef0123456789abcdef01234567'})
        for name, keep in (('RCPT-OK', True), ('RCPT-GONE', False)): verdict(la, store, name, keep_receipt=keep)
    return {'kind': 'obs2c-synthetic-state', 'state_root': str(state), 'project_a': str(a), 'project_b': str(b),
            'a_id': tracking.project_identity(a), 'b_id': tracking.project_identity(b), 'count': count,
            'note': 'Synthetic data only; no provider call and no real task acceptance.'}


if __name__ == '__main__':
    print(json.dumps(create(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 150), ensure_ascii=False))
