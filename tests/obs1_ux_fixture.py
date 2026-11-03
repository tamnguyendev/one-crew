"""The OBS-1 UX data set on a real temporary ledger (EngineFixture): every state the page must tell apart, built through the real engine.

P1 waiting on an owner question with two options (keep / drop; the question carries a password that must never show);
P2 one node produced (an event with evidence); P3 closed before anything ran (closed ≠ accepted); P4 running its SECOND attempt and blocked
by an observation of that attempt, with a late observation of the first attempt in the timeline (stale); P5 produced with a wait that was
closed; P6 every node verified, waiting for acceptance; P7 accepted; PB a plan of ANOTHER project in the same ledger (proposed).
`populate(case)` returns the running P4 worker (released on cleanup) so the page is looked at while P4 is live.
"""
import os
import threading
from unittest.mock import patch

from onecrew.ledger import Ledger
from onecrew.v2 import engine, executors, internal_plan, plan as plans, progress_track, tracking
from tests.test_obs1_tracking import QUESTION, _Blocking
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node


class Managed(executors.Executor):
    declaration = executors.Declaration('fixture-managed', 'managed', ('measure',), ('time',))


def quick_executor(case):
    def quick(ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = case.store.blob(('artifact-' + item['id']).encode())
        receipt = case.store.blob(('{"kind":"fixture-receipt","item":"' + item['id'] + '","note":"api_key=sk-fixture-secret"}').encode())
        control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}
    return quick


def make_root(case, name, title, ledger=None):
    ledger = ledger or case.ledger
    value = plan_json(scope={'owned': ['a.txt', 'b.txt']}, authority={'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
    value['title'] = title
    view = plans.propose(ledger, name, value, 'codex', workflow=True, capabilities=case.engine_caps)
    return view


def approve_and_revise(case, name, ledger=None):
    ledger = ledger or case.ledger
    with patch.dict(os.environ):                      # the fixture shell says ONECREW_ACTOR=codex after its own approval: an owner approves here, as in setUp
        os.environ.pop('ONECREW_ACTOR', None)
        plans.approve(ledger, name, 'owner', 'fixture approval')
    internal_plan.revise(ledger, name, [node('C'), node('I', ['C'], integration=True, write=())], reason='UX data', evidence=['a.txt:1'])


def task_of(case, name):
    with case.ledger.transaction() as conn:
        return plans.anchor_events(case.ledger, conn, name)['task_id']


def populate(case):
    quick = quick_executor(case); step = lambda name, ex=quick: engine.step(case.ledger, name, ex, control=case.control)
    # P1: the fixture's root, question with options
    case.revise([node('A'), node('I', ['A'], integration=True, write=())])
    case.request = case.ledger.create_request(case.root_view['anchor_task'], 'retention', QUESTION)
    # P2 produced
    make_root(case, 'P2', 'Viết out.txt qua worker (một phần việc đã tạo đầu ra)'); approve_and_revise(case, 'P2'); step('P2')
    # P3 closed, nothing ran
    make_root(case, 'P3', 'Plan bị chủ sở hữu đóng trước khi chạy'); approve_and_revise(case, 'P3')
    with case.ledger.transaction(write=True) as conn:
        plans.emit(case.ledger, conn, task_of(case, 'P3'), 'plan.closed', {'revision': 1, 'reason': 'owner cancelled the unfinished task'})
    # P5 produced + a closed wait
    make_root(case, 'P5', 'Phần việc có khoảng chờ đã kết thúc'); approve_and_revise(case, 'P5'); step('P5')
    att5 = tracking.detail(case.ledger.state_root, 'P5')['nodes']['C']['attempt']
    kw = dict(source='tool_call', ref='wait-receipt', at='2026-11-03T00:00:00+00:00', wait_reason='external_service')
    executors.observe(case.ledger, 'P5', Managed(), att5, 'wait', **kw)
    executors.observe(case.ledger, 'P5', Managed(), att5, 'wait', until='2026-11-03T00:00:05+00:00', **kw)
    # P6 verified, waiting for acceptance; P7 accepted
    for name, title in (('P6', 'Mọi phần việc đã kiểm, chờ nghiệm thu'), ('P7', 'Plan đã được nghiệm thu')):
        make_root(case, name, title); approve_and_revise(case, name)
        step(name); engine.verify(case.ledger, name, 'C', case.checker); step(name); engine.verify(case.ledger, name, 'I', case.checker)
    with case.ledger.transaction(write=True) as conn:
        plans.emit(case.ledger, conn, task_of(case, 'P7'), 'plan.accepted', {'plan': 'P7', 'revision': 1, 'by': 'owner', 'artifact_sha': 'x'})
    # PB: another project in the same ledger
    other = case.root.parent / 'project B'; other.mkdir(exist_ok=True); (other / 'a.txt').write_text('base\n')
    case.ledger_b = Ledger(other, case.ledger.state_root)
    make_root(case, 'PB', 'PROJECT B PRIVATE GOAL', ledger=case.ledger_b)
    # P4: attempt 1 produced, a new generation, attempt 2 running and blocked by ITS observation; a late observation of attempt 1
    make_root(case, 'P4', 'Phần việc chạy lại: attempt cũ có quan sát đến muộn, attempt mới bị chặn'); approve_and_revise(case, 'P4'); step('P4')
    old = tracking.detail(case.ledger.state_root, 'P4')['nodes']['C']['attempt']
    with case.ledger.transaction(write=True) as conn:
        view = engine.state(case.ledger, 'P4', conn); engine._event(case.ledger, conn, view, 'C', 'node.resumed')
    worker = _Blocking(case)
    thread = threading.Thread(target=engine.step, args=(case.ledger, 'P4', worker), kwargs={'control': case.control}, daemon=True); thread.start()
    case.addCleanup(thread.join, 30); case.addCleanup(worker.release.set)
    assert worker.started.wait(20), 'P4: the second attempt did not start'
    new = tracking.detail(case.ledger.state_root, 'P4')['nodes']['C']['attempt']
    progress_track.observe(case.ledger, 'P4', 'C', Managed(), old, 'late-old-command', {'kind': 'command', 'elapsed_seconds': 60}, source='tool_call', ref='old-receipt', command_cap_seconds=60)
    progress_track.observe(case.ledger, 'P4', 'C', Managed(), new, 'current-command', {'kind': 'command', 'elapsed_seconds': 60}, source='tool_call', ref='current-receipt', command_cap_seconds=60)
    case.p4 = {'old': old, 'new': new, 'worker': worker}
    return worker
