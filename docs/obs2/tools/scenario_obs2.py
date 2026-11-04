"""Installed-wheel synthetic fixture only. No provider, real hook/registry or real ledger.

Creates two roots with the same workflow shape: code and plain document output.
Checks are explicit fixture assertions, not a real provider/pilot or a production test suite.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys

from onecrew.control_core import Control, migrate
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, internal_plan, plan, repair_tasks, tracking


def contract(path, goal):
    return {'schema_version': 2, 'title': goal, 'size': 'S',
        'understanding': {'restated_goal': goal, 'target': {'repo': '.', 'ref': 'HEAD', 'paths': [path]},
                          'assumptions': [], 'confidence': 'high', 'unknowns': []},
        'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': path}, 'why': 'Tệp đầu vào thử đã có'}],
        'output': ['Kết quả thử đọc được và giữ nội dung đã chốt'], 'scope': {'owned': [path]}, 'non_goals': ['Không thao tác bên ngoài sổ thử'],
        'items': [{'id': 'I1', 'title': 'Tạo kết quả và kiểm nội dung', 'tier': 'must', 'milestone': 'M1'}],
        'milestones': [{'id': 'M1', 'title': 'Đối chiếu kết quả thử', 'covers': ['O1'],
                        'verifier': {'type': 'owner-manual', 'config': {}}}],
        'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
        'authority': {'edit': True, 'commands': True, 'edit_tests': True,
                      'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}}


def node(nid, path, integration=False):
    return {'id': nid, 'goal': 'Kiểm lại kết quả tích hợp trước bàn giao' if integration else 'Chuẩn bị nội dung đầu ra trong phạm vi đã chốt',
        'input': [], 'output': ['Kết quả có nội dung đối chiếu được'], 'acceptance': ['O1'],
        'depends': [{'node': 'C', 'requires': 'verified'}] if integration else [],
        'read': [path], 'write': [] if integration else [path], 'resources': [],
        'estimate_seconds': [1, 2], 'execution_cap_seconds': 60, 'budget_calls': 1,
        'checks': [{'id': 'check-' + nid, 'spec': 'Nội dung có dấu hiệu kết quả thử đã yêu cầu'}], 'integration': integration}


def create(work):
    work = Path(work).resolve(); project, state = work / 'project', work / 'state'
    project.mkdir(); state.mkdir()
    (project / 'code.py').write_text('def add(a, b): return a + b\n', encoding='utf-8')
    (project / 'guide.txt').write_text('A plain document fixture.\n', encoding='utf-8')
    for args in (('init', '-q'), ('config', 'user.name', 'OBS2 fixture'), ('config', 'user.email', 'fixture@localhost'),
                 ('add', 'code.py', 'guide.txt'), ('commit', '-q', '-m', 'synthetic baseline')):
        subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)
    ledger = Ledger(project, state); store = Snapshots(state); migrate(ledger); control = Control(ledger)
    # Bind only this newly-created disposable project to the installed trial runtime.
    # No init, user registry, global settings or existing project is touched.
    exe = Path(sys.executable).with_name('onecrew.exe' if sys.platform == 'win32' else 'onecrew')
    if exe.is_file():
        from onecrew.v2 import hook_cli
        settings = project / '.claude' / 'settings.local.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps(hook_cli.portable_settings(exe, state)), encoding='utf-8')
    caps = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine']
    for name, path, goal in (('CODE', 'code.py', 'Sửa phép cộng và kiểm kết quả trước bàn giao (dữ liệu thử)'),
                             ('DOC', 'guide.txt', 'Soạn hướng dẫn bắt đầu cho người dùng mới (dữ liệu thử)')):
        value = contract(path, goal)
        plan.propose(ledger, name, value, 'fixture', workflow=True, capabilities=caps)
        plan.approve(ledger, name, 'owner', 'Synthetic fixture only, not user acceptance')
        internal_plan.revise(ledger, name, [node('C', path), node('I', path, True)], reason='Tách phần tạo kết quả và kiểm tích hợp trong quyền của sổ thử', evidence=[path + ':1'])
        def execute(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            generation = engine.state(ledger, name)['nodes'][item['id']]['generation']
            marker = 'Incomplete first coding candidate' if name == 'CODE' and item['id'] == 'C' and generation == 0 else 'Readable fixture result'
            artifact = store.blob((goal + '\n' + marker + '\n').encode())
            receipt = store.blob(json.dumps({'kind': 'fixture-executor-receipt', 'actor': 'synthetic fixture',
                'node': item['id'], 'attempt': attempt['id'], 'artifact': artifact}).encode())
            control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
            return {'artifact': artifact, 'receipt': receipt}
        def checker(item, artifact):
            passed = b'Readable fixture result' in store.read_blob(artifact)
            return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'pass' if passed else 'fail',
                'evidence': store.blob(b'Fixture assertion: marker found' if passed else b'Fixture assertion: marker missing'), 'testcases': [
                    {'id': 'marker', 'suite': name, 'result': 'pass' if passed else 'fail'}]} for c in item['checks']]}
        engine.step(ledger, name, execute, control=control)
        if name == 'CODE':
            engine.verify(ledger, name, 'C', checker)
            failed_receipt = engine.state(ledger, name)['nodes']['C']['verification_receipt']
            repair_tasks.prepare(ledger, name, 'C', 'C', reason='Sửa đúng phần việc có kiểm không đạt, giữ yêu cầu kiểm tích hợp', evidence=[failed_receipt])
            engine.step(ledger, name, execute, control=control)
        engine.verify(ledger, name, 'C', checker)
        if name == 'CODE':
            engine.step(ledger, name, execute, control=control); engine.verify(ledger, name, 'I', checker)
            pending = copy.deepcopy(value); pending['title'] = 'Đề xuất làm rõ phần bàn giao phép cộng — chưa được duyệt'
            plan.amend(ledger, name, pending, 'Làm rõ tên phần bàn giao; bản đang thực hiện vẫn là revision 1 đã duyệt', 'fixture')
        else:
            with ledger.transaction(write=True) as conn:
                view = engine.state(ledger, name, conn)
                engine._event(ledger, conn, view, 'C', 'node.resumed', reason='Thử lại kỹ thuật trong cùng yêu cầu; không phải vòng sửa finding')
            engine.step(ledger, name, execute, control=control)
    return {'kind': 'obs2-synthetic-state', 'project': str(project), 'state_root': str(state),
            'project_id': tracking.project_identity(project), 'plans': ['CODE', 'DOC'],
            'note': 'Synthetic data and assertions; no provider call and no real task acceptance.'}


if __name__ == '__main__':
    print(json.dumps(create(sys.argv[1]), ensure_ascii=False))
