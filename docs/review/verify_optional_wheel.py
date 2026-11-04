"""Run with installed-wheel python -I, outside checkout. No test-package imports.

Synthetic temporary approval/produced candidate adapted from
tests/test_wf_installed_review_dispatch.py. These fixtures prove optional review
coordination, not real user approval, native execution or model quality.
"""
import argparse
import concurrent.futures
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path, help='A new isolated directory')
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    real_registry = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'OneCrew' / 'hook-projects.json'
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    registry_before = digest(real_registry)
    for key in ('TEMP', 'TMP', 'LOCALAPPDATA', 'APPDATA'):
        path = output / key.lower(); path.mkdir(exist_ok=True); os.environ[key] = str(path)
    for key in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'):
        os.environ.pop(key, None)
    from onecrew import __file__ as installed_file
    from onecrew import budget_core
    from onecrew.ledger import Ledger
    from onecrew.snapshots import Snapshots
    from onecrew.v2 import plan, engine, internal_plan, review_dispatch

    project = output / 'temporary project'; project.mkdir()
    (project / 'a.txt').write_text('fixture\n', encoding='utf-8')
    def git(*args): subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)
    git('init', '-q'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@localhost')
    git('add', '.'); git('commit', '-qm', 'fixture baseline')
    ledger = Ledger(project, output / 'temporary state'); store = Snapshots(ledger.state_root)
    contract = {'schema_version': 2, 'title': 'Optional lifecycle wheel fixture', 'size': 'S',
        'understanding': {'restated_goal': 'Keep optional observations coordinated.',
            'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']}, 'assumptions': [], 'confidence': 'high', 'unknowns': []},
        'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'fixture exists'}],
        'output': ['Evidence exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['No real provider'],
        'items': [{'id': 'I1', 'title': 'Observe', 'tier': 'must', 'milestone': 'M1'},
                  {'id': 'S1', 'title': 'Extra', 'tier': 'should'}, {'id': 'W1', 'title': 'Never', 'tier': 'wont'}],
        'milestones': [{'id': 'M1', 'title': 'Fixture check', 'covers': ['O1'],
            'verifier': {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print("fixture")']}}}],
        'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
        'authority': {'edit': True, 'commands': True, 'edit_tests': True,
                      'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']},
        'review_policy': {'depth': 'deep', 'optional_reviews': ['extra', 'unknown', 'stale']}}
    root = plan.propose(ledger, 'P1', contract, 'codex', workflow=True,
                        capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
    plan.approve(ledger, 'P1', 'owner', 'Synthetic approval in isolated wheel fixture; not user acceptance')
    os.environ['ONECREW_ACTOR'] = 'codex'
    def node(nid, dependencies=(), integration=False, write=('a.txt',)):
        return {'id': nid, 'goal': 'Produce O1 evidence', 'input': [], 'output': ['Evidence'], 'acceptance': ['O1'],
            'depends': [{'node': n, 'requires': 'verified'} for n in dependencies], 'read': ['a.txt'],
            'write': list(write), 'resources': [], 'estimate_seconds': [1, 2], 'execution_cap_seconds': 60,
            'budget_calls': 1, 'checks': [{'id': 'check-' + nid, 'spec': 'Check O1'}], 'integration': integration}
    nodes = [node('C'), node('I', ['C'], integration=True, write=())]
    internal_plan.revise(ledger, 'P1', nodes, reason='Fixture decomposition', evidence=['a.txt:1'])
    artifact = store.blob(b'explicit synthetic candidate')
    with ledger.transaction(write=True) as conn:
        view = engine.state(ledger, 'P1', conn)
        engine._event(ledger, conn, view, 'C', 'node.produced', artifact=artifact,
                      receipt=store.blob(b'explicit synthetic executor receipt'), inputs={})
    execution = {'method': 'adapter', 'implementation': 'installed-fixture-v1', 'configuration': {},
                 'environment': {'fixture': 'local'}, 'provenance': {'adapter': 'verify_optional_wheel'}}
    def budget():
        with ledger.transaction() as conn:
            group = budget_core.group(conn, root['anchor_task'])
        return {key: group[key] for key in ('used_calls', 'remaining_calls', 'unknown_attempts', 'deadline')}
    budget_before = budget()
    results = []
    def check(name, condition):
        results.append({'name': name, 'pass': bool(condition)})
        if not condition: raise AssertionError(name)
    def invoke(checker, review='extra'):
        return engine.review_optional(ledger, 'P1', 'C', review, checker, artifact, execution=execution)
    entered, release = threading.Event(), threading.Event(); calls = []
    def blocked(item, value):
        calls.append(value); entered.set()
        if not release.wait(30): raise RuntimeError('fixture not released')
        return {'artifact': value, 'result': 'pass'}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(invoke, blocked)
        try:
            check('first checker entered', entered.wait(30))
            other = invoke(blocked)
            check('second request observes original run', other['status'] == 'pending' and not other['executed'])
        finally: release.set()
        first = future.result(timeout=30)
    check('single invocation and shared run', len(calls) == 1 and first['run_id'] == other['run_id'])
    def forbidden(*args): raise AssertionError('unexpected checker invocation')
    cached = invoke(forbidden)
    check('completed authenticated reuse', cached['cached_observation'] and cached['receipt'] == first['receipt'])
    def unknown(*args): raise OSError('fixture unknown outcome')
    try: invoke(unknown, 'unknown')
    except OSError: pass
    else: raise AssertionError('unknown fixture did not fail')
    held = invoke(forbidden, 'unknown')
    check('unknown has no blind retry', held['status'] == 'held' and not held['executed'])
    check('reconcile needs issued evidence', review_dispatch.reconcile_optional(ledger, 'P1', held['run_id'])['status'] == 'held')
    def stale(item, value):
        changed = copy.deepcopy(nodes); changed[0]['goal'] = 'Changed during fixture review'
        internal_plan.revise(ledger, 'P1', changed, reason='Fixture changed input', evidence=['a.txt:1'])
        return {'result': 'pass', 'artifact': value}
    changed = invoke(stale, 'stale')
    check('independent request executes despite held request, stale result is not applicable',
          changed['executed'] and changed['status'] == 'stale_observation')
    events = ledger.events(root['anchor_task'])
    check('observations grant no node verification', not any(e['kind'] == 'node.verification' for e in events))
    check('no owner requests generated', ledger.requests() == [])
    check('coordination neither charges another model call nor resets original budget', budget() == budget_before)
    check('real registry unchanged', digest(real_registry) == registry_before)
    report = {'pass': all(r['pass'] for r in results), 'checks': results, 'installed_module': installed_file,
              'real_provider_tested': False, 'owner_approval': 'temporary simulation fixture',
              'registry_unchanged': digest(real_registry) == registry_before}
    (output / 'optional-wheel-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
