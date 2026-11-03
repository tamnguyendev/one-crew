"""scenario_obs1.py <work dir> <case> - the OBS-1 trial flows, run by verify_obs1.py with the INSTALLED onecrew (python -I, cwd = work, the
fake `claude` first on PATH). A temporary project and ledger under <work>; a fixture owner approval (never a real ledger). Writes JSON to stdout.

Cases:
  setup     project + ledger; plan P1 proposed (tracking says: waiting for approval), approved, an engine root with node C (pin claude /
            claude-haiku-5-5) and the integration node; one engine.step through the real NativeExecutor -> ClaudeArtifact -> Supervisor -> the
            fake claude.exe. Prints the tracking statuses before / idle / after and the paths.
  request   a pending owner question on P1 whose text carries a password (must never show). Prints the request id and the write time.
  verify    engine.verify P1 C through the real CandidateChecker (the command check of the node). Prints the result.
  second    plan P2 (same project) with a node whose fake worker stays busy for FAKE_SLEEP seconds (policy sleep): a long-running step.
            Prints when the step started and its final state.
  untracked a task outside any plan (task_intake.submit) and a hook registry entry for a project that has no plan.
  p2        the four Codex P2 counterexamples of 03/11 on the installed wheel (after `untracked`): P3 closed with unstarted nodes (P2-01);
            P4 running a second attempt while a late blocked observation of the FIRST attempt is written (P2-02; the step stays open for
            OBS1_P2_HOLD seconds twice: first with only the old observation, then with one of the current attempt); P5 with a wait that was
            closed on a settled attempt (P2-03); a second project B in the same ledger with a private plan PB and evidence blob (P2-04).
            Prints one JSON line per phase (p4-window, p4-current, done); the verifier reads the server/CLI during the windows.
  ux        (after `p2`) the states the page must tell apart that the earlier cases do not leave behind: P6 every node verified (waiting for
            acceptance) and P7 accepted, through engine.step + engine.verify with the real CandidateChecker; then P4 is re-opened: a second
            attempt kept running by an in-process worker and blocked by an observation of THAT attempt (a late observation of the first attempt
            is in the timeline). Prints `ready` and holds P4 running until stdin is closed or OBS1_UX_HOLD seconds pass; then prints `done`.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

work, case = Path(sys.argv[1]).resolve(), sys.argv[2]
root, state = work / 'project with space', work / 'state with space'


def git(*args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def node(nid, depends=(), write=('out.txt',), integration=False, cap=60, estimate=(1, 2)):
    return {'id': nid, 'goal': 'Produce evidence for O1', 'input': [], 'output': ['Evidence for O1'], 'acceptance': ['O1'],
            'depends': [{'node': d, 'requires': 'verified'} for d in depends], 'read': ['a.txt'], 'write': list(write), 'resources': [],
            'estimate_seconds': list(estimate), 'execution_cap_seconds': cap, 'budget_calls': 1,
            'checks': [{'id': 'M1', 'spec': 'out.txt is written by the worker.'}], 'integration': integration,
            'executor': {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}}


def contract(title='OBS-1 trial task'):
    return {'schema_version': 2, 'title': title, 'size': 'S',
            'understanding': {'restated_goal': 'Write out.txt through a worker so the tracking page shows a real root, node and attempt.',
                              'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']}, 'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
            'output': ['out.txt holds the worker result'], 'scope': {'owned': ['a.txt', 'out.txt']}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
            'milestones': [{'id': 'M1', 'title': 'out.txt written', 'verifier': {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print("ok")']}}, 'covers': ['O1']}],
            'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
            'authority': {'edit': True, 'commands': True, 'unconfined_commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}}   # as scenario_a1 of 2.3: a temporary fixture ledger, the command check needs it


def main():
    from onecrew.ledger import Ledger
    from onecrew.v2 import tracking
    if case == 'setup':
        from onecrew.common_executor import NativeExecutor
        from onecrew.v2 import engine, internal_plan, plan
        root.mkdir(parents=True)
        git('init', '-q'); git('config', 'user.name', 'fixture'); git('config', 'user.email', 'fixture@localhost')
        (root / 'a.txt').write_text('base\n'); (root / 'out.txt').write_text('base\n'); (root / '.gitignore').write_text('.onecrew/\n')
        git('add', '.'); git('commit', '-qm', 'base')
        ledger = Ledger(root, state)
        plan.propose(ledger, 'P1', contract(), 'codex', workflow=True, capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
        before = tracking.overview(state)['projects'][0]['tasks'][0]
        plan.approve(ledger, 'P1', 'owner', 'temporary fixture only (not a real ledger)')
        internal_plan.revise(ledger, 'P1', [node('C'), node('I', ['C'], write=(), integration=True)], reason='OBS-1 trial', evidence=['a.txt:1'])
        idle = tracking.overview(state)['projects'][0]['tasks'][0]
        started = time.time()
        step = engine.step(ledger, 'P1', NativeExecutor(ledger))
        after = tracking.overview(state)['projects'][0]['tasks'][0]
        detail = tracking.detail(state, 'P1')
        print(json.dumps({'project': str(root), 'state_root': str(state), 'before': before['status'], 'before_needs': [n['kind'] for n in before['needs_user']],
                          'idle': idle['status'], 'step_state': step['state'], 'step_seconds': round(time.time() - started, 2), 'after': after['status'],
                          'after_level': after['level'], 'nodes': {k: [v['phase'], v['state'], v['generation'], v['child']] for k, v in detail['nodes'].items()},
                          'attempts': [a['status'] for a in detail['attempts']], 'receipt': detail['nodes']['C']['receipt'],
                          'evidence_keys': len(detail['evidence_keys']), 'timeline_kinds': [e['kind'] for e in detail['timeline']],
                          'last_seq': detail['source']['last_seq'], 'worktree_out': (root / 'out.txt').read_text(),
                          'origins': {n: getattr(sys.modules.get(n), '__file__', None) for n in ('onecrew.v2.tracking', 'onecrew.v2.engine', 'onecrew.common_executor')}},
                         ensure_ascii=True))   # ASCII: the caller's console may be cp1252
        return 0
    ledger = Ledger(root, state)
    if case == 'request':
        from onecrew.v2 import plan
        with ledger.transaction() as conn:
            task = plan.derive(ledger, conn, 'P1')['task_id']
        question = {'schema_version': 1, 'question': 'Keep the old key? (password=hunter2-must-not-show)', 'reason': 'The worker found two configurations.',
                    'impact': 'The next node waits for this answer.', 'options': [{'id': 'keep', 'label': 'Keep it'}, {'id': 'drop', 'label': 'Drop it'}],
                    'recommendation': 'keep', 'action': {'type': 'clarify_config', 'parameters': {}}}
        written = time.time()
        request = ledger.create_request(task, os.environ.get('OBS1_REQUEST_KEY') or 'obs1-question', question)   # a new key = a new request (same key + content is a no-op)
        print(json.dumps({'request': request['id'], 'revision': request['revision'], 'written_at': written}))
        return 0
    if case == 'verify':
        from onecrew.common_verification import CandidateChecker
        from onecrew.v2 import engine
        result = engine.verify(ledger, 'P1', 'C', CandidateChecker(ledger, 'P1'))
        print(json.dumps({'result': result.get('result') or result.get('state'), 'keys': sorted(result)[:12]}, default=str))
        return 0
    if case == 'second':
        from onecrew.common_executor import NativeExecutor
        from onecrew.v2 import engine, internal_plan, plan
        plan.propose(ledger, 'P2', contract('OBS-1 long step'), 'codex', workflow=True, capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
        plan.approve(ledger, 'P2', 'owner', 'temporary fixture only (not a real ledger)')
        internal_plan.revise(ledger, 'P2', [node('C', cap=120), node('I', ['C'], write=(), integration=True)], reason='OBS-1 long step', evidence=['a.txt:1'])
        print(json.dumps({'phase': 'stepping', 'at': time.time()}), flush=True)
        started = time.time()
        step = engine.step(ledger, 'P2', NativeExecutor(ledger))
        print(json.dumps({'phase': 'done', 'step_state': step['state'], 'seconds': round(time.time() - started, 2)}), flush=True)
        return 0
    if case == 'untracked':
        from onecrew.task_intake import submit
        task = submit(ledger, 'A task outside any plan (v1-style)', 'v1-job')
        registry = Path(os.environ['LOCALAPPDATA']) / 'OneCrew'; registry.mkdir(parents=True, exist_ok=True)
        (registry / 'hook-projects.json').write_text(json.dumps({'projects': {str(work / 'other project'): str(state)}}), encoding='utf-8')
        print(json.dumps({'task': task['id'], 'registry': str(registry / 'hook-projects.json')}))
        return 0
    if case == 'p2':
        import threading
        from onecrew.snapshots import Snapshots
        from onecrew.control_core import Control, migrate
        from onecrew.v2 import engine, executors, internal_plan, plan, progress_track
        store, caps = Snapshots(state), ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
        migrate(ledger); control = Control(ledger)
        hold = float(os.environ.get('OBS1_P2_HOLD', '10'))

        class Managed(executors.Executor):
            declaration = executors.Declaration('fixture-managed', 'managed', ('measure',), ('time',))

        def quick(ledger_, control, task, item, attempt):           # an in-process executor: produces at once (no model, no process)
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            artifact, receipt = store.blob(('artifact-' + item['id']).encode()), store.blob(b'{"kind":"fixture-receipt"}')
            control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
            return {'artifact': artifact, 'receipt': receipt}

        class Blocking:                                             # an in-process executor whose attempt stays RUNNING until released
            def __init__(self): self.started, self.release = threading.Event(), threading.Event()
            def __call__(self, ledger_, control, task, item, attempt):
                control.launched(attempt['id'], attempt['generation'], {'fixture': True}); self.started.set(); self.release.wait(hold * 4 + 30)
                return quick(ledger_, control, task, item, attempt)

        def make_root(name, title):
            plan.propose(ledger, name, contract(title), 'codex', workflow=True, capabilities=caps)
            plan.approve(ledger, name, 'owner', 'temporary fixture only (not a real ledger)')
            internal_plan.revise(ledger, name, [node('C'), node('I', ['C'], write=(), integration=True)], reason='OBS-1 P2 counterexample', evidence=['a.txt:1'])
            with ledger.transaction() as conn:
                return plan.anchor_events(ledger, conn, name)['task_id']
        out = {}
        # P2-01: closed, nothing ever ran
        task3 = make_root('P3', 'OBS-1 P2-01 closed before any node ran')
        with ledger.transaction(write=True) as conn:
            plan.emit(ledger, conn, task3, 'plan.closed', {'revision': 1, 'reason': 'owner cancelled the unfinished task'})
        out['p3'] = {k: tracking.detail(state, 'P3')[k] for k in ('root_status', 'level', 'status')}
        # P2-03: a wait closed on the settled attempt of P5
        make_root('P5', 'OBS-1 P2-03 closed wait'); engine.step(ledger, 'P5', quick, control=control)
        att5 = tracking.detail(state, 'P5')['nodes']['C']['attempt']
        kw = dict(source='tool_call', ref='wait-receipt', at='2026-11-03T00:00:00+00:00', wait_reason='external_service')
        executors.observe(ledger, 'P5', Managed(), att5, 'wait', **kw)
        executors.observe(ledger, 'P5', Managed(), att5, 'wait', until='2026-11-03T00:00:05+00:00', **kw)
        d5 = tracking.detail(state, 'P5')
        out['p5'] = {'attempt': att5, 'status': d5['status'], 'waits': d5['waits'], 'executor_waits': d5['measure'].get('executor_waits')}
        # P2-04: project B in the same ledger
        other = work / 'project B'; other.mkdir(parents=True, exist_ok=True); (other / 'a.txt').write_text('base\n')
        for args in (('init', '-q'), ('config', 'user.name', 'fixture'), ('config', 'user.email', 'fixture@localhost'), ('add', '.'), ('commit', '-qm', 'base')):
            subprocess.run(['git', '-C', str(other), *args], check=True, capture_output=True)
        ledger_b = Ledger(other, state)
        plan.propose(ledger_b, 'PB', contract('PROJECT B PRIVATE GOAL'), 'codex', workflow=True, capabilities=caps)
        key_b = store.blob(b'PROJECT B PRIVATE EVIDENCE')
        with ledger_b.transaction(write=True) as conn:
            task_b = plan.anchor_events(ledger_b, conn, 'PB')['task_id']
            plan.emit(ledger_b, conn, task_b, 'workflow.checkpoint', {'phase': 'review', 'message': 'test', 'evidence': key_b})
        out['projects'] = {'a': ledger.project_id, 'b': ledger_b.project_id, 'b_path': str(other), 'b_key': key_b}
        # P2-02: P4, attempt 1 produced, generation 1 opened, attempt 2 running; a late observation of attempt 1
        make_root('P4', 'OBS-1 P2-02 late observation of an old attempt'); engine.step(ledger, 'P4', quick, control=control)
        old = tracking.detail(state, 'P4')['nodes']['C']['attempt']
        with ledger.transaction(write=True) as conn:
            view = engine.state(ledger, 'P4', conn); engine._event(ledger, conn, view, 'C', 'node.resumed')
        worker = Blocking(); thread = threading.Thread(target=engine.step, args=(ledger, 'P4', worker), kwargs={'control': control}, daemon=True); thread.start()
        if not worker.started.wait(60): raise SystemExit('P4: the second attempt did not start')
        new = tracking.detail(state, 'P4')['nodes']['C']['attempt']
        progress_track.observe(ledger, 'P4', 'C', Managed(), old, 'late-old-command', {'kind': 'command', 'elapsed_seconds': 60}, source='tool_call', ref='old-receipt', command_cap_seconds=60)
        print(json.dumps({'phase': 'p4-window', 'old': old, 'new': new, 'hold': hold, 'status': tracking.detail(state, 'P4')['status']}, ensure_ascii=True), flush=True)
        time.sleep(hold)
        progress_track.observe(ledger, 'P4', 'C', Managed(), new, 'current-command', {'kind': 'command', 'elapsed_seconds': 60}, source='tool_call', ref='current-receipt', command_cap_seconds=60)
        print(json.dumps({'phase': 'p4-current', 'status': tracking.detail(state, 'P4')['status']}, ensure_ascii=True), flush=True)
        time.sleep(hold)
        worker.release.set(); thread.join(120)
        out['p4'] = {'old': old, 'new': new, 'final': tracking.detail(state, 'P4')['status']}
        print(json.dumps(dict(out, phase='done'), ensure_ascii=True, default=str), flush=True)
        return 0
    if case == 'ux':
        import threading
        from onecrew.snapshots import Snapshots
        from onecrew.control_core import Control, migrate
        from onecrew.v2 import engine, executors, internal_plan, plan, progress_track
        store, caps = Snapshots(state), ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
        migrate(ledger); control = Control(ledger)
        hold = float(os.environ.get('OBS1_UX_HOLD', '120'))

        class Managed(executors.Executor):
            declaration = executors.Declaration('fixture-managed', 'managed', ('measure',), ('time',))

        def quick(ledger_, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            artifact, receipt = store.blob(('artifact-' + item['id']).encode()), store.blob(b'{"kind":"fixture-receipt","note":"api_key=sk-fixture-secret"}')
            control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
            return {'artifact': artifact, 'receipt': receipt}

        class Blocking:
            def __init__(self): self.started, self.release = threading.Event(), threading.Event()
            def __call__(self, ledger_, control, task, item, attempt):
                control.launched(attempt['id'], attempt['generation'], {'fixture': True}); self.started.set(); self.release.wait(hold + 60)
                return quick(ledger_, control, task, item, attempt)

        def make_root(name, title):
            plan.propose(ledger, name, contract(title), 'codex', workflow=True, capabilities=caps)
            plan.approve(ledger, name, 'owner', 'temporary fixture only (not a real ledger)')
            internal_plan.revise(ledger, name, [node('C'), node('I', ['C'], write=(), integration=True)], reason='OBS-1 UX data', evidence=['a.txt:1'])
            with ledger.transaction() as conn:
                return plan.anchor_events(ledger, conn, name)['task_id']
        def checker(item, artifact):                                 # the quick executor's artifact is a blob, not a candidate tree: a fixture verdict with evidence
            return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'pass', 'evidence': store.blob(b'fixture check passed')} for c in item['checks']]}
        out = {}
        with ledger.transaction() as conn:
            task1 = plan.derive(ledger, conn, 'P1')['task_id']
        for key, text, opts in (('ux-q2', 'Co dung lai cau hinh cu cua may chu ky so cho moi truong thu khong (cau hoi thu hai, dai de thu xuong dong)?', [{'id': 'reuse', 'label': 'Dung lai'}, {'id': 'fresh', 'label': 'Tao moi'}]),
                                ('ux-q3', 'Giu log hai tuan hay mot thang?', [{'id': 'two', 'label': '2 tuan'}, {'id': 'month', 'label': '1 thang'}])):
            ledger.create_request(task1, key, {'schema_version': 1, 'question': text, 'reason': 'Can chot truoc khi chay tiep.', 'impact': 'Phan viec ke tiep cho cau tra loi.',
                                               'options': opts, 'recommendation': opts[0]['id'], 'action': {'type': 'clarify', 'parameters': {}}})
        long_dir = work / 'du an thu nghiem voi ten thu muc rat dai de kiem tra bo loc project va tran chieu ngang 2026'
        long_dir.mkdir(parents=True, exist_ok=True); (long_dir / 'a.txt').write_text('base\n')
        for args in (('init', '-q'), ('config', 'user.name', 'fixture'), ('config', 'user.email', 'fixture@localhost'), ('add', '.'), ('commit', '-qm', 'base')):
            subprocess.run(['git', '-C', str(long_dir), *args], check=True, capture_output=True)
        plan.propose(Ledger(long_dir, state), 'PC', contract('Ra soat va viet lai tai lieu huong dan cai dat SDK ky so cho khach hang moi (ten dai tu nhien)'), 'codex', workflow=True, capabilities=caps)
        hostile = work / "demo$SDK 'q' (a)&b`t"; hostile.mkdir(parents=True, exist_ok=True); (hostile / 'a.txt').write_text('base\n')
        ledger_ps = Ledger(hostile, state)
        plan.propose(ledger_ps, 'PS', contract('Project co ky tu dac biet trong duong dan ($SDK, dau nhay, backtick, &, ngoac)'), 'codex', workflow=True, capabilities=caps)
        with ledger_ps.transaction() as conn:
            ps_task = plan.anchor_events(ledger_ps, conn, 'PS')['task_id']
        ledger_ps.create_request(ps_task, 'ps-q', {'schema_version': 1, 'question': 'Duong dan co $SDK va dau nhay: mau lenh co giu nguyen khong?', 'reason': 'P2-B', 'impact': 'parser',
                                                   'options': [{'id': 'yes', 'label': 'Co'}, {'id': 'no', 'label': 'Khong'}], 'recommendation': 'yes', 'action': {'type': 'clarify', 'parameters': {}}})
        names = (os.environ.get('OBS1_UX_NAMES') or 'P6,P7').split(',')
        for name, title in ((names[0], 'OBS-1 UX: moi phan viec da kiem, cho nghiem thu'), (names[1], 'OBS-1 UX: plan da duoc nghiem thu')):
            task = make_root(name, title)
            engine.step(ledger, name, quick, control=control); engine.verify(ledger, name, 'C', checker)
            engine.step(ledger, name, quick, control=control); engine.verify(ledger, name, 'I', checker)
            if name == names[1]:
                with ledger.transaction(write=True) as conn:
                    plan.emit(ledger, conn, task, 'plan.accepted', {'plan': name, 'revision': 1, 'by': 'owner', 'artifact_sha': 'x'})
            out['P6' if name == names[0] else 'P7'] = tracking.detail(state, name)['status']
        # P8: two phần việc without dependency, both running at once
        c8 = contract('OBS-1 UX: hai phan viec chay song song'); c8['scope'] = {'owned': ['a.txt', 'b.txt', 'out.txt']}      # node B writes b.txt
        plan.propose(ledger, 'P8', c8, 'codex', workflow=True, capabilities=caps + ['parallel-engine'])
        plan.approve(ledger, 'P8', 'owner', 'temporary fixture only (not a real ledger)')
        internal_plan.revise(ledger, 'P8', [node('A', write=('a.txt',)), node('B', write=('b.txt',)), node('I', ['A', 'B'], write=(), integration=True)], reason='parallel', evidence=['a.txt:1'])
        class Isolated(executors.Executor):
            declaration = executors.Declaration('fixture-isolated', 'managed', ('start', 'isolate'))
            barrier = threading.Barrier(2)
            def __init__(self): self.control = control
            def start(self, ledger_, control_, task, item, attempt):
                control_.launched(attempt['id'], attempt['generation'], {'fixture': True})
                try: self.barrier.wait(30)
                except threading.BrokenBarrierError: pass
                time.sleep(1.5)
                artifact, receipt = store.blob(('artifact-' + item['id']).encode()), store.blob(b'{"kind":"fixture-receipt"}')
                control_.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
                return {'artifact': artifact, 'receipt': receipt}
            def isolate(self, attempt_id): return {'attempt': attempt_id, 'writes': 'scoped candidate only'}
        p8 = engine.run_batch(ledger, 'P8', Isolated(), slots=2)
        if [r.get('state') for r in p8.get('results', [])] != ['produced', 'produced']: raise SystemExit('P8 did not run both nodes: ' + json.dumps(p8, default=str)[:300])
        out['p8'] = tracking.detail(state, 'P8')['status']
        # P4 again: a new generation, a second attempt that stays running and is blocked by its own observation; the first attempt's late observation
        with ledger.transaction(write=True) as conn:
            view = engine.state(ledger, 'P4', conn); engine._event(ledger, conn, view, 'C', 'node.resumed')
        old = tracking.detail(state, 'P4')['nodes']['C']['attempt'] or ''
        worker = Blocking(); thread = threading.Thread(target=engine.step, args=(ledger, 'P4', worker), kwargs={'control': control}, daemon=True); thread.start()
        if not worker.started.wait(60): raise SystemExit('P4: the attempt did not start')
        new = tracking.detail(state, 'P4')['nodes']['C']['attempt']
        progress_track.observe(ledger, 'P4', 'C', Managed(), new, 'ux-current-command', {'kind': 'command', 'elapsed_seconds': 60}, source='tool_call', ref='ux-current-receipt', command_cap_seconds=60)
        out['p4'] = {'old': old, 'new': new, 'status': tracking.detail(state, 'P4')['status']}
        print(json.dumps(dict(out, phase='ready'), ensure_ascii=True, default=str), flush=True)
        t0 = time.time()
        while time.time() - t0 < hold:
            line = sys.stdin.readline() if not sys.stdin.closed else ''
            if not line: break
        worker.release.set(); thread.join(120)
        print(json.dumps({'phase': 'done', 'final': tracking.detail(state, 'P4')['status']}, ensure_ascii=True), flush=True)
        return 0
    raise SystemExit('unknown case ' + case)


if __name__ == '__main__':
    sys.exit(main())
