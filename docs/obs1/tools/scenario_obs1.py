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
        request = ledger.create_request(task, 'obs1-question', question)
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
    raise SystemExit('unknown case ' + case)


if __name__ == '__main__':
    sys.exit(main())
