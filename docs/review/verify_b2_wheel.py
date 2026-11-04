"""2.5-B cycle 2 smoke for an installed wheel. Run with the wheel venv's python -I -B -X utf8, outside the checkout. No test-package imports.

python -I -B -X utf8 verify_b2_wheel.py <new-output-directory>

Temporary project, ledger, synthetic approval and synthetic candidate; checkers and the provider are local callables. This proves the check
lifecycle of the installed code, not a user's approval, a real provider, or that a reviewer finds anything.
"""
import argparse
import concurrent.futures
import hashlib
import io
import json
import os
from contextlib import redirect_stdout
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
    from onecrew import __file__ as installed_file, budget_core
    from onecrew.common_verification import CandidateChecker, InvestigationChecker
    from onecrew.control_core import Control, migrate
    from onecrew.ledger import Ledger, LedgerError, canonical
    from onecrew.snapshots import Snapshots
    from onecrew.v2 import engine, engine_cli, internal_plan, plan, review_dispatch

    project = output / 'temporary project'; project.mkdir()
    (project / 'a.txt').write_text('one\n', encoding='utf-8')
    def git(*args): subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)
    git('init', '-q'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@localhost')
    git('add', '.'); git('commit', '-qm', 'fixture baseline')
    ledger = Ledger(project, output / 'temporary state'); store = Snapshots(ledger.state_root)
    check = [sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\n"; print("candidate tested")']
    contract = {'schema_version': 2, 'title': 'Check lifecycle wheel fixture', 'size': 'S',
        'understanding': {'restated_goal': 'Keep every check on one run per request.',
            'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']}, 'assumptions': [], 'confidence': 'high', 'unknowns': []},
        'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'fixture exists'}],
        'output': ['Evidence exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['No real provider'],
        'items': [{'id': 'I1', 'title': 'Check', 'tier': 'must', 'milestone': 'M1'}, {'id': 'W1', 'title': 'Never', 'tier': 'wont'}],
        'milestones': [{'id': 'M1', 'title': 'Fixture check', 'covers': ['O1'], 'verifier': {'type': 'command', 'config': {'argv': check}}}],
        'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
        'authority': {'edit': True, 'commands': True, 'unconfined_commands': True, 'apply_to_project': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']},
        'review_policy': {'depth': 'deep', 'optional_reviews': ['investigate']}}
    plan.propose(ledger, 'P1', contract, 'codex', workflow=True, capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
    plan.approve(ledger, 'P1', 'owner', 'Synthetic approval in an isolated wheel fixture; not user acceptance')
    os.environ['ONECREW_ACTOR'] = 'codex'
    migrate(ledger); control = Control(ledger)
    def node(nid, dependencies=(), integration=False, write=('a.txt',)):
        return {'id': nid, 'goal': 'Produce O1 evidence', 'input': [], 'output': ['Evidence'], 'acceptance': ['O1'],
                'depends': [{'node': n, 'requires': 'verified'} for n in dependencies], 'read': ['a.txt'], 'write': list(write), 'resources': [],
                'estimate_seconds': [1, 2], 'execution_cap_seconds': 120, 'budget_calls': 1, 'checks': [{'id': 'M1', 'spec': 'The approved command'}], 'integration': integration}
    internal_plan.revise(ledger, 'P1', [node('C'), node('I', ['C'], integration=True, write=())], reason='Fixture decomposition', evidence=['a.txt:1'])
    def execute(ledger_, control_, task, item, attempt):
        control_.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = store.overlay(store.capture(project, ['a.txt']), {'a.txt': b'candidate\n'}, ['a.txt'])
        receipt = store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
        control_.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}
    results = []
    def verify_ok(name, condition):
        results.append({'name': name, 'pass': bool(condition)})
        if not condition: raise AssertionError(name)
    def used():
        with ledger.transaction() as conn:
            return budget_core.group(conn, plan.anchor_events(ledger, conn, 'P1')['task_id'])['used_calls']
    def fixture_check(item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'pass', 'evidence': store.blob(b'fixture passed')} for c in item['checks']]}
    def forbidden(*args): raise AssertionError('unexpected checker invocation')
    def cli(*argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = engine_cli.main(['--project', str(project), '--state-root', str(ledger.state_root), 'engine', *argv])
        return code, json.loads(out.getvalue())

    engine.step(ledger, 'P1', execute, control=control)
    artifact = engine.state(ledger, 'P1')['nodes']['C']['artifact']

    # an optional limited investigation; the provider is a local callable
    prompts = []
    def provider(prompt, config, env, scratch, limit):
        prompts.append(prompt)
        return json.dumps({'findings': [], 'not_investigated': ['everything else'], 'summary': 'fixture'}), {}, None, False, b'fixture'
    before = used()
    seen = engine.review_optional(ledger, 'P1', 'C', 'investigate', InvestigationChecker(ledger, 'P1', 'investigate',
        {'provider': 'claude', 'model': 'claude-haiku-5-5', 'question': 'Is a.txt there?', 'paths': ['a.txt']}, call=provider), artifact)
    body = json.loads(store.read_blob(seen['receipt']))
    verify_ok('investigation is a limited observation', seen['status'] == 'observed' and body['authority'] == 'none' and body['observed']['full_review'] is False)
    verify_ok('investigation is metered once and leaves the node produced', used() == before + 1 and engine.state(ledger, 'P1')['nodes']['C']['state'] == 'produced')

    # an unknown outcome is held, never replayed; the released check uses the production port through the CLI
    def lost(item, value): raise OSError('fixture unknown outcome')
    try: engine.verify(ledger, 'P1', 'C', lost)
    except OSError: pass
    else: raise AssertionError('unknown fixture did not fail')
    held = engine.verify(ledger, 'P1', 'C', forbidden)
    verify_ok('unknown outcome is held and explained', held['status'] == 'held' and 'release-check' in held['next'])
    code, shown = cli('reconcile-check', 'P1', held['check_run']['run_id'])
    verify_ok('reconcile-check runs nothing', code == 0 and shown['status'] == 'held')
    code, shown = cli('release-check', 'P1', held['check_run']['run_id'], '--reason', 'Synthetic fixture: the callable ran nothing.')
    verify_ok('release-check records the decision without a budget reset', code == 0 and shown['budget_reset'] is False)

    # two doors, one production check
    entered, release, calls = threading.Event(), threading.Event(), []
    production = CandidateChecker(ledger, 'P1')
    from onecrew.v2.verifiers import command
    original = command.run
    def blocked(*args, **kwargs):
        calls.append(args[4]['id']); entered.set()
        if not release.wait(60): raise RuntimeError('fixture not released')
        return original(*args, **kwargs)
    command.run = blocked
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(engine.verify, ledger, 'P1', 'C', production)
            verify_ok('first check dispatched', entered.wait(60))
            try:
                second = engine.verify(ledger, 'P1', 'C', CandidateChecker(ledger, 'P1'))
                listed = review_dispatch.active_checks(ledger, 'P1')
            finally:
                release.set()
            done = first.result(timeout=120)
    finally:
        command.run = original
    verify_ok('second door observes the same run', second['status'] == 'pending' and second['check_run']['run_id'] == done['check_run']['run_id'])
    verify_ok('one verifier execution, one published pass', len(calls) == 1 and done['result'] == 'pass')
    verify_ok('the running check is visible to other doors', any(row['door'] == 'engine.verify' for row in listed))
    verify_ok('the production port states its execution identity', done['check_run']['cache_reusable'] is True)
    try:
        engine.verify(ledger, 'P1', 'C', forbidden)
        raise AssertionError('a verified node dispatched again')
    except LedgerError as error:
        verify_ok('a valid pass is not dispatched again', done['check_run']['run_id'] in str(error))

    # the integration node meets the same milestone on the same tree: reused, not executed; delivery still authenticates it
    engine.step(ledger, 'P1', execute, control=control)
    calls.clear()
    def counted(*args, **kwargs):
        calls.append(args[4]['id'])
        return original(*args, **kwargs)
    command.run = counted
    try:
        integrated = engine.verify(ledger, 'P1', 'I', CandidateChecker(ledger, 'P1'))
    finally:
        command.run = original
    wrapper = json.loads(store.read_blob(integrated['observed']['checks'][0]['evidence']))
    verify_ok('same request on the same tree is reused with its source', calls == [] and integrated['result'] == 'pass' and wrapper['reused_from_run'] == next(
        r['run_id'] for r in review_dispatch.check_runs(ledger, 'P1') if r['check'] == 'milestone' and r['outcome'] == 'observed'))
    code, listed = cli('check-runs', 'P1')
    verify_ok('check-runs lists the runs of every door', code == 0 and {'engine.verify', 'candidate'} <= {row['door'] for row in listed})
    verify_ok('checks grant no owner request', ledger.requests() == [])
    verify_ok('produced or verified is not accepted', plan.show(ledger, 'P1')['status'] == 'approved')
    verify_ok('real registry unchanged', digest(real_registry) == registry_before)
    report = {'pass': all(r['pass'] for r in results), 'checks': results, 'installed_module': installed_file, 'real_provider_tested': False,
              'owner_approval': 'temporary simulation fixture', 'registry_unchanged': digest(real_registry) == registry_before}
    (output / 'b2-wheel-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
