"""T54.1 / T54.3 behaviour scenarios of R05, R06, R07, R08, RP, RX1 and RX2 on the INSTALLED build (review a2476ab P1: the old scenarios were import-only).

Every body runs inside the venv of the wheel (no checkout on sys.path, nothing from `tests` importable) and asserts RESULTS (states, texts, counts,
refusals), never imports. The expected event kinds are the ones `wfkit/release_events.json` declares for the release, written by the public path
(CLI where a subcommand exists, the module API otherwise, executors and providers being explicit local fixtures; no real provider is called).
Shared fixture source (`ENGINE`) is prepended to the bodies that drive the common engine.
"""
from tests import wf_scenarios as sc

# ---- shared engine fixture (copied literals of tests.test_wf_engine / test_v2_l1: nothing of `tests` exists in the venv) ---------------------------------
ENGINE = r'''
import os, sys, json, subprocess, time
from pathlib import Path
from onecrew.control_core import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan, engine, internal_plan, questions, findings, verdict
from onecrew.v2.verifiers import command as vcommand
SELF_DECIDE = ['Q1', 'Q2', 'Q3', 'Q4', 'Q8', 'Q9', 'Q12']
def node(nid, dependencies=(), integration=False, write=('a.txt',), read=('a.txt',), checks=None):
    return {'id': nid, 'goal': 'Produce evidence for O1', 'input': [], 'output': ['Evidence for O1'], 'acceptance': ['O1'],
            'depends': [{'node': up, 'requires': 'verified'} for up in dependencies], 'read': list(read), 'write': list(write), 'resources': [],
            'estimate_seconds': [1, 2], 'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': checks or [{'id': 'check-' + nid, 'spec': 'Check the declared O1 output of ' + nid}], 'integration': integration}
CAPS = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
def start(raw, nodes, caps=CAPS, name='P1'):
    plan.propose(ledger, name, raw, 'codex', workflow=True, capabilities=caps)
    plan.approve(ledger, name, 'owner', 'fixture approval on a temporary ledger')
    os.environ['ONECREW_ACTOR'] = 'codex'
    migrate(ledger)
    internal_plan.revise(ledger, name, nodes, reason='Split work inside the approved scope', evidence=['a.txt:1'])
    return Control(ledger)
store = Snapshots(ledger.state_root)
def execute(ledger, control, task, item, attempt):
    control.launched(attempt['id'], attempt['generation'], {'fixture': True})
    artifact = store.blob(('artifact-' + item['id']).encode()); receipt = store.blob(('executor-' + item['id']).encode())
    control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
    return {'artifact': artifact, 'receipt': receipt}
def checker_with(result):
    def run(item, artifact):
        return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': result, 'evidence': store.blob(b'fixture check observation')} for c in item['checks']]}
    return run
def kinds_of(name='P1'):
    with ledger.transaction() as conn:
        task = plan.anchor_events(ledger, conn, name)['task_id']
    return [e['kind'] for e in ledger.events(task)]
def owner():
    os.environ.pop('ONECREW_ACTOR', None)
def ai():
    os.environ['ONECREW_ACTOR'] = 'codex'
'''

# =============================================================== R05 ===============================================================
R05_FINDINGS = ENGINE + r"""
raw = contract()
raw['scope'] = {'owned': ['a.txt', 'b.txt', 'x.txt']}
raw['authority'] = {'edit': True, 'commands': True, 'self_decide': SELF_DECIDE}
raw['review_policy'] = {'depth': 'light', 'optional_reviews': ['OptionalReview']}
raw['milestones'][0]['verifier'] = {'type': 'data', 'config': {'path': 'a.txt', 'columns': {'one': 'string'}, 'key': ['one'], 'row_count': 2}}
nodes = [node('Nw'), node('Nr', write=()), node('Nd', ['Nw'], write=('b.txt',), read=()), node('Nx', write=('x.txt',), read=('x.txt',)),
         node('I', ['Nw', 'Nr', 'Nd', 'Nx'], integration=True, write=(), read=())]
control = start(raw, nodes, CAPS + ['finding-register'])
produced = engine.step(ledger, 'P1', execute, control=control)
def forbidden(*args): raise AssertionError('a held or skipped optional review must not call a checker')
skip = engine.review_optional(ledger, 'P1', 'Nw', 'OptionalReview', forbidden, produced['artifact'])
check('W26 with no finding the approved light policy skips the optional review', produced['node'] == 'Nw' and skip['decision']['action'] == 'SKIP', skip['decision'])
calls = []
def late(ledger, control, task, item, attempt):
    calls.append(item['id'])
    result = execute(ledger, control, task, item, attempt)
    verdict.run(ledger, 'P1', 'M1')                                   # the REAL data check fails on a.txt -> W17 registers the finding
    opened = findings.list_findings(ledger, 'P1', open_only=True)
    findings.update(ledger, 'P1', opened[0]['id'], reason='The failing assertion reads only a.txt', read=['a.txt'], write=[])
    return result
first = engine.step(ledger, 'P1', late, control=control)
rows = findings.list_findings(ledger, 'P1')
check('W17 a failed check registered exactly one open finding', len(rows) == 1 and rows[0]['status'] == 'open', rows)
check('W21 a result settled while the finding opened is retained, not published', first['node'] == 'Nr' and first['state'] == 'retained' and kinds_of().count('node.produced') == 1, first)
check('W17 the finding event is on the plan-ns root', 'finding.registered' in kinds_of() and 'node.result_retained' in kinds_of())
view = engine.state(ledger, 'P1')
check('W18 writers, readers and dependents are held by the finding', sorted(view['finding_blockers']) == ['I', 'Nd', 'Nr', 'Nw'], view['finding_blockers'])
ready = [n['id'] for n in json.loads(cli('engine', 'ready', 'P1'))]
check('W18 the hold is by scope: only the independent node is ready', ready == ['Nx'], ready)
held = engine.review_optional(ledger, 'P1', 'Nw', 'OptionalReview', forbidden, produced['artifact'])
check('W26 an open finding turns the same review into HOLD without a checker call', held['decision']['action'] == 'HOLD' and 'Unresolved findings: ' + rows[0]['id'] in held['decision']['reason'], held['decision'])
listed = json.loads(cli('findings', 'list', 'P1'))
check('the CLI lists the same open finding', listed and listed[0]['id'] == rows[0]['id'] and listed[0]['status'] == 'open', listed)
check('the independent node still runs while the others are held', engine.step(ledger, 'P1', execute, control=control)['node'] == 'Nx')
check('the root is not deliverable while a finding is open', not engine.root_ready(ledger, 'P1'))
(root / 'a.txt').write_text('one\nrow1\nrow2\n')
shown = verdict.run(ledger, 'P1', 'M1')
check('the repaired a.txt passes the real check', shown['milestones'][0]['state'] == 'passed', shown['milestones'][0])
receipt = shown['milestones'][0]['last_verdict']['receipt']
closed = findings.resolve(ledger, 'P1', rows[0]['id'], receipt, reason='Original failing assertion now passes', artifact_sha=vcommand.artifact_sha(root))
check('only the receipt-based transition closes the finding', closed['closed'] == [rows[0]['id']], closed)
check('the holds are gone and the review is skippable again', engine.state(ledger, 'P1')['finding_blockers'] == {} and
      engine.review_optional(ledger, 'P1', 'Nw', 'OptionalReview', forbidden, produced['artifact'])['decision']['action'] == 'SKIP')
released = engine.step(ledger, 'P1', late, control=control)
check('W21 the retained result is released without a second model call', released.get('released_retained') is True and released['artifact'] == first['artifact'] and calls == ['Nr'], (released, calls))
check('the released candidate is published as node.produced', kinds_of().count('node.produced') == 3, kinds_of())
tree = vcommand.artifact_sha(root)
deferred = json.loads(cli('plan', 'review-decision', 'P1', '--node', 'OptionalReview', '--artifact-sha', tree, '--not-ready', '--evidence', 'a.txt:1'))
unknown = json.loads(cli('plan', 'review-decision', 'P1', '--node', 'OptionalReview', '--artifact-sha', tree, '--unknown', 'U9', '--evidence', 'a.txt:1'))
mandatory = json.loads(cli('plan', 'review-decision', 'P1', '--node', 'M1', '--artifact-sha', tree, '--evidence', 'a.txt:1'))
check('W26 the CLI rules give DEFER for missing evidence, HOLD for a named unknown, REVIEW for a mandatory milestone',
      (deferred['action'], unknown['action'], mandatory['action']) == ('DEFER', 'HOLD', 'REVIEW'), (deferred['action'], unknown['action'], mandatory['action']))
check('W26 a decision cites its evidence and is cached on the same inputs', deferred['record']['subject'] == {'component': 'review_policy', 'model': 'rules'} and
      json.loads(cli('plan', 'review-decision', 'P1', '--node', 'OptionalReview', '--artifact-sha', tree, '--not-ready', '--evidence', 'a.txt:1'))['cached'] is True)
"""
sc.register('R05', 'r05-findings-holds-retained',
            ['W17 a failed check registers a finding on the plan-ns root', 'W18 holds by read/write scope; independent nodes continue',
             'W21 a late result is retained then released without a second call',
             'W26 the rule decision SKIP/DEFER/REVIEW/HOLD carries reason, evidence and a cache bound to the same inputs; an open finding turns SKIP into HOLD without a checker call'],
            ['finding.registered', 'node.result_retained', 'node.produced'], R05_FINDINGS)

R05_HOLD_ANSWER = ENGINE + r'''
raw = contract()
raw['scope'] = {'owned': ['a.txt', 'b.txt']}
raw['authority'] = {'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': SELF_DECIDE}
nodes = [node('A'), node('B', write=('b.txt',), read=('b.txt',)), node('I', ['A', 'B'], integration=True, write=(), read=())]
control = start(raw, nodes)
def phases():
    return {nid: (r['phase'], r['generation']) for nid, r in engine.state(ledger, 'P1')['nodes'].items()}
decision = engine.request_action(ledger, 'P1', 'A', {'kind': 'write', 'paths': ['outside.txt']})
before = phases()
check('a write outside the grant is a typed U2 decision', decision['class'] == 'U2' and not decision['in_authority'], decision)
check('only the closure of A (A and its dependent I) is held; B is not', {n for n, (p, g) in before.items() if p == 'held'} == {'A', 'I'}, before)
check('node.held names the reason and no outside file was written', 'node.held' in kinds_of() and not (root / 'outside.txt').exists())
pending = json.loads(cli('question', 'list', '--plan', 'P1', '--pending'))
check('one pending owner question exists for the hold', len(pending) == 1 and pending[0]['revision'], pending)
ai_try = subprocess.run([exe, '--project', str(root), '--state-root', str(state), 'question', 'answer', pending[0]['id'], '--revision', str(pending[0]['revision']),
                         '--choice', 'continue', '--reference', 'ai pretending'], capture_output=True, text=True, env={**os.environ, 'ONECREW_ACTOR': 'codex', 'CLAUDECODE': '1'})
check('the owner verb is refused inside an AI tool session and nothing is resumed', ai_try.returncode != 0 and 'refused' in ai_try.stdout and phases() == before and 'node.resumed' not in kinds_of(), ai_try.stdout[-200:] + ai_try.stderr[-200:])
owner()
answered = json.loads(cli('question', 'answer', pending[0]['id'], '--revision', str(pending[0]['revision']), '--choice', 'continue', '--reference', 'owner decision fixture'))
effect = answered['controller_effect']
after = phases()
check('continue resumes exactly the held generations inside the grant', effect['effect'] == 'continued_within_grant' and effect['grants_authority'] is False, effect)
check('A and I moved one generation forward and are pending again, B is untouched',
      after['A'] == ('pending', before['A'][1] + 1) and after['I'] == ('pending', before['I'][1] + 1) and after['B'] == before['B'], (before, after))
check('request.applied and node.resumed were written once', kinds_of().count('request.applied') == 1 and kinds_of().count('node.resumed') == 2, kinds_of())
ai()
check('the resumed node runs next, still inside its original grant', engine.step(ledger, 'P1', execute, control=control)['node'] == 'A' and not (root / 'outside.txt').exists())
engine.request_action(ledger, 'P1', 'B', {'kind': 'write', 'paths': ['outside.txt']})
second = json.loads(cli('question', 'list', '--plan', 'P1', '--pending'))
check('a second hold opens a second question', len(second) == 1 and second[0]['id'] != pending[0]['id'], second)
owner()
stopped = json.loads(cli('question', 'answer', second[0]['id'], '--revision', str(second[0]['revision']), '--choice', 'stop', '--reference', 'owner stops the root'))
check('W30c stop closes the plan-ns root once', stopped['controller_effect']['effect'] == 'closed' and plan.show(ledger, 'P1')['status'] == 'closed', stopped['controller_effect'])
ks = kinds_of()
check('plan.closed + request.applied were written, nothing was accepted', ks.count('plan.closed') == 1 and ks.count('request.applied') == 2 and 'plan.accepted' not in ks, ks)
check('a closed root has nothing ready and the report says so', engine.ready(ledger, 'P1') == [] and 'ĐÃ ĐÓNG' in cli('plan', 'present', 'P1'))
'''
sc.register('R05', 'r05-hold-answer-resume-stop',
            ['W36 an out-of-grant action holds the dependency closure (node.held) and asks the owner', 'W18 an out-of-grant action holds the dependency closure (node.held) and asks the owner',
             'W30c the typed continue answer resumes the exact generations once (node.resumed, request.applied); stop closes the root (plan.closed)',
             'C11: an AI session cannot answer for the owner'],
            ['node.held', 'node.resumed', 'request.applied', 'plan.closed'], R05_HOLD_ANSWER)

R05_RECOVERY = ENGINE + r'''
raw = contract()
raw['scope'] = {'owned': ['a.txt', 'b.txt']}
raw['authority'] = {'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': SELF_DECIDE}
control = start(raw, [node('A'), node('I', ['A'], integration=True, write=(), read=())])
def action_file(body):
    target = Path(state) / 'action-input.json'
    target.write_text(json.dumps(body), encoding='utf-8')
    return str(target)
prepared = json.loads(cli('engine', 'prepare-tests', 'P1', '--file', action_file({'implementation': 'A', 'node_id': 'Tests', 'write': ['b.txt'],
    'checks': [{'id': 'prep', 'spec': 'Acceptance cases prepared'}], 'estimate_seconds': [1, 2], 'execution_cap_seconds': 60, 'budget_calls': 1,
    'reason': 'Acceptance tests before code', 'evidence': ['a.txt:1']})))
ready = [n['id'] for n in json.loads(cli('engine', 'ready', 'P1'))]
check('W19 prepared tests become the only ready node before the implementation', ready == ['Tests'], (ready, prepared))
engine.step(ledger, 'P1', execute, control=control)
check('the prepared test node verifies', engine.verify(ledger, 'P1', 'Tests', checker_with('pass'))['result'] == 'pass')
engine.step(ledger, 'P1', execute, control=control)
failed = engine.verify(ledger, 'P1', 'A', checker_with('fail'))
check('a failed configured check is a real failed verification', failed['result'] == 'fail', failed)
check('W20 the failed verification itself recorded exactly one recovery decision', kinds_of().count('workflow.recovery_decided') == 1, kinds_of())
first = json.loads(cli('engine', 'diagnose', 'P1', 'A'))
check('W20 the first failure is authorized for one bounded repair', first['disposition'] == 'repair' and first['grants_authority'] is False and not first['creates_owner_request'], first)
again = json.loads(cli('engine', 'diagnose', 'P1', 'A'))
check('W20 the same failed receipt yields the same decision (idempotent)', again['event'] == first['event'] and kinds_of().count('workflow.recovery_decided') == 1)
repaired = json.loads(cli('engine', 'repair', 'P1', '--file', action_file({'target': 'A', 'failed_node': 'A', 'reason': 'Repair the genuine failed fixture check',
                                                                          'evidence': [first['source_receipt']]})))
check('W19 the bounded repair re-issues A without resetting the budget', repaired and 'A' in json.dumps(repaired), repaired)
engine.step(ledger, 'P1', execute, control=control)
engine.verify(ledger, 'P1', 'A', checker_with('fail'))
second = json.loads(cli('engine', 'diagnose', 'P1', 'A'))
check('W20 a repeat failure with no material progress is diagnose, not another repair', second['disposition'] == 'diagnose' and second['record']['count'] == 2, second)
check('W20 diagnose never creates an owner request or resets the budget', not second['creates_owner_request'] and second['resets_budget'] is False and
      json.loads(cli('question', 'list', '--plan', 'P1', '--pending')) == [])
refusal = cli('engine', 'repair', 'P1', '--file', action_file({'target': 'A', 'failed_node': 'A', 'reason': 'Try again without progress',
                                                              'evidence': [second['source_receipt']]}), expect=2)
check('a third repair without progress is refused with the diagnose requirement', 'diagnose' in refusal, refusal)
check('the root stays approved and nothing was accepted', plan.show(ledger, 'P1')['status'] == 'approved' and 'plan.accepted' not in kinds_of())
report_text = cli('plan', 'report', 'P1')
check('W20 the plan report shows the diagnosis of node A (red check, attempts, spend, next step)', 'Cần chẩn đoán node A' in report_text and 'check-A' in report_text and 'lời gọi' in report_text, report_text[-800:])
check('two failed receipts produced exactly two recovery decisions', kinds_of().count('workflow.recovery_decided') == 2)
'''
sc.register('R05', 'r05-recovery-no-progress',
            ['W19 prepared tests then a bounded repair of a genuinely failed node (CLI)', 'W20 the recovery decision per failed receipt: repair, then diagnose on no progress, no owner request, no budget reset'],
            ['workflow.recovery_decided'], R05_RECOVERY)

R05_HANDOFF = ENGINE + r'''
import contextlib, io
from unittest.mock import patch
from onecrew.v2.cli import main as v2main
raw = contract()
raw['authority'] = {'edit': True, 'commands': True, 'unconfined_commands': True, 'apply_to_project': True, 'self_decide': SELF_DECIDE}
raw['milestones'][0]['verifier']['config']['argv'] = [sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text().strip()=="candidate"; print("installed candidate checked")']
nodes = [node('C', checks=[{'id': 'M1', 'spec': 'Run the approved immutable root command'}]), node('I', ['C'], integration=True, write=(), read=('a.txt',), checks=[{'id': 'M1', 'spec': 'Run the approved immutable root command'}])]
for item in nodes: item['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'gpt-6.1-sol'}
control = start(raw, nodes)
index_before = git('write-tree').strip()
calls = []
def factory(control, provider):
    class Worker:
        def capability(self): return {'provider': provider, 'mode': 'fixture-no-tools'}
        def run(self, attempt, prompt, schema, profile):
            calls.append({'provider': provider, 'model': profile['model']})
            control.launched(attempt['id'], attempt['generation'], {'fixture': True}); control.finish(attempt['id'], attempt['generation'], {'exit_code': 0})
        def result(self, attempt):
            return ({'summary': 'producer', 'files': [{'path': 'a.txt', 'content': 'candidate\n'}], 'backlog': []} if len(calls) == 1
                    else {'summary': 'readonly integration', 'evidence': []}), []
    return Worker()
def inproc(*args, expect=0):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): code = v2main(['--project', str(root), '--state-root', str(state), *args])
    must('in-process ' + ' '.join(args) + ' exits ' + str(expect), code == expect, out.getvalue()[-300:])
    return json.loads(out.getvalue())
with patch('onecrew.artifact_provider_core.make_worker', side_effect=factory):
    inproc('engine', 'step', 'P1'); verified_c = inproc('engine', 'verify', 'P1', 'C')
    inproc('engine', 'step', 'P1'); verified_i = inproc('engine', 'verify', 'P1', 'I')
    check('the producer and the mandatory integration node verified with the real command', verified_c['result'] == 'pass' and verified_i['result'] == 'pass', (verified_c, verified_i))
    check('before the handoff the project is untouched and the root is not deliverable', (root / 'a.txt').read_text() == 'base\n' and not engine.root_ready(ledger, 'P1'))
    delivered = inproc('engine', 'handoff', 'P1')
check('the pinned provider/model worked both nodes', calls == [{'provider': 'codex', 'model': 'gpt-6.1-sol'}] * 2, calls)
check('the handoff applied the verified candidate to the project through CAS', (root / 'a.txt').read_text() == 'candidate\n' and git('write-tree').strip() == index_before, delivered)
check('workflow.handoff is written and the root is deliverable only for that artifact', kinds_of().count('workflow.handoff') == 1 and engine.root_ready(ledger, 'P1', delivered['artifact']), kinds_of())
check('an unrelated artifact is not deliverable', not engine.root_ready(ledger, 'P1', 'f' * 40))
check('the root contract still verifies on the delivered tree', verdict.run(ledger, 'P1', 'M1')['milestones'][0]['state'] == 'passed')
owner()
accepted = plan.accept(ledger, 'P1', 'owner', 'delivered tree accepted on a temporary ledger', delivered['artifact'])
check('only the owner accepts the delivered tree', accepted['status'] == 'accepted' and plan.show(ledger, 'P1')['status'] == 'accepted')
'''
sc.register('R05', 'r05-native-handoff',
            ['workflow.handoff: the verified integration candidate is applied to the project by the handoff (not by the producer)',
             'root_ready is false before and true after the handoff for exactly that artifact', 'the owner accepts the delivered tree'],
            ['workflow.handoff', 'node.verification'], R05_HANDOFF)

R05_REUSE = r'''
(root / 'interface.txt').write_text('interface A')
git('add', '.'); git('commit', '-qm', 'interface')
raw = contract()
raw['scope'] = {'owned': ['a.txt'], 'neutral': ['docs/**']}
raw['understanding']['target']['paths'] = ['a.txt', 'interface.txt']
file = Path(state).parent / 'reuse-contract.json'; file.write_text(json.dumps(raw))
cli('plan', 'propose', 'P1', '--file', str(file), '--author', 'fixture', '--workflow',
    *[x for cap in ('namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine', 'parallel-engine') for x in ('--capability', cap)])
cli('plan', 'approve', 'P1', '--by', 'owner', '--reference', 'fixture approval on a temporary ledger')
ran = json.loads(cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1'))
receipt = ran['milestones'][0]['last_verdict']['receipt']
check('the command verdict passed and carries a receipt', ran['milestones'][0]['state'] == 'passed' and receipt)
(root / 'docs').mkdir(); (root / 'docs' / 'note.md').write_text('Neutral note'); git('add', '.'); git('commit', '-qm', 'neutral')
current = json.loads(cli('verdict', 'artifact', '--plan', 'P1'))['artifact_sha']
first = json.loads(cli('plan', 'evidence-reuse', 'P1', '--milestone', 'M1', '--receipt', receipt, '--artifact-sha', current))
check('W08 the neutral docs change is a recorded reuse basis', first['basis']['kind'] == 'scope.neutral' and first['basis']['matching_globs'] == {'docs/note.md': ['docs/**']}, first)
check('the record grants no authority and changes no verdict', first['grants_authority'] is False and json.loads(cli('plan', 'show', 'P1'))['milestones'][0]['state'] == 'passed')
second = json.loads(cli('plan', 'evidence-reuse', 'P1', '--milestone', 'M1', '--receipt', receipt, '--artifact-sha', current))
check('the same reuse is idempotent (same key)', second['key'] == first['key'])
(root / 'unrelated.txt').write_text('not an input')
changed = json.loads(cli('verdict', 'artifact', '--plan', 'P1'))['artifact_sha']
refused = cli('plan', 'evidence-reuse', 'P1', '--milestone', 'M1', '--receipt', receipt, '--artifact-sha', changed, expect=2)
check('W08 a change outside the declared neutral scope has no reuse basis', 'No valid changed-artifact reuse basis' in refused and 'scope.neutral' in refused, refused)
refused2 = cli('plan', 'evidence-reuse', 'P1', '--milestone', 'M1', '--receipt', 'f' * 64, '--artifact-sha', changed, expect=2)
check('a receipt that is not the latest authentic passing one cannot be reused', 'authentic passing receipt' in refused2, refused2)
'''
sc.register('R05', 'r05-evidence-reuse',
            ['W08 plan evidence-reuse records a scope.neutral basis for a docs-only change, once', 'W08 a change outside scope.neutral and a forged receipt are refused'],
            ['evidence.reuse'], R05_REUSE)

R05_LOST_RUN = r'''
import signal, time
def kinds_text():
    import sqlite3
    conn = sqlite3.connect((state / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
    try: return ' '.join(r[0] for r in conn.execute('SELECT kind FROM events ORDER BY seq'))
    finally: conn.close()
marker = Path(state).parent / 'x-effects.txt'
code = 'import os,sys,time; p=sys.argv[1]; n=open(p).read().count("x") if os.path.exists(p) else 0; open(p,"a").write("x"+chr(10)); print("x ran"); time.sleep(0 if n else 120)'
raw = contract()
raw['milestones'][0]['verifier']['config']['argv'] = [sys.executable, '-c', code, str(marker)]
file = Path(state).parent / 'lost-run-contract.json'; file.write_text(json.dumps(raw))
cli('plan', 'propose', 'P1', '--file', str(file), '--author', 'fixture', '--workflow')
cli('plan', 'approve', 'P1', '--by', 'owner', '--reference', 'fixture approval on a temporary ledger')
def lines():
    return marker.read_text().count('x') if marker.exists() else 0
env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
proc = subprocess.Popen([exe, '--project', str(root), '--state-root', str(state), 'verdict', 'run', '--plan', 'P1', '--milestone', 'M1'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
end = time.monotonic() + 90
dispatched = []
while time.monotonic() < end and not (dispatched and lines() >= 1):
    dispatched = list((Path(state) / 'verdict-runs').glob('*/dispatched.json')) if (Path(state) / 'verdict-runs').exists() else []
    time.sleep(0.1)
must('the verifier X was dispatched and ran once before the crash', dispatched and lines() == 1, (dispatched, lines()))
run_id = dispatched[0].parent.name
if os.name == 'nt': subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
else: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
proc.wait(timeout=30)                                              # crash point: after dispatch, before any receipt
def run_again():
    return subprocess.run([exe, '--project', str(root), '--state-root', str(state), 'verdict', 'run', '--plan', 'P1', '--milestone', 'M1'],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
restart = run_again()
check('W37a the restart reconciles first and refuses to dispatch X again', restart.returncode != 0 and 'unknown outcome' in restart.stdout and 'release-run' in restart.stdout, restart.stdout[-400:])
check('X was not run a second time by the restart', lines() == 1, lines())
status = json.loads(cli('verdict', 'status', '--plan', 'P1'))
check('the lost run is reported as held with an unknown outcome', status['held'] == [run_id] and [r['outcome'] for r in status['runs']] == ['held_unknown_outcome'], status)
again = run_again()
check('a second restart changes nothing by itself', again.returncode != 0 and lines() == 1 and kinds_text().count('verdict.run_held') == 1, again.stdout[-200:])
bad = cli('verdict', 'release-run', '--plan', 'P1', '--run', 'no-such-run', '--reason', 'typo', expect=2)
check('releasing a run that is not held is refused', 'is not held' in bad, bad)
released = json.loads(cli('verdict', 'release-run', '--plan', 'P1', '--run', run_id, '--reason', 'Checked: the marker file shows one line; a second run is acceptable here.'))
check('the release is a recorded decision that does not promise exactly-once', 'not promised' in released['note'] and released['run_id'] == run_id, released)
check('after the release nothing is held', json.loads(cli('verdict', 'status', '--plan', 'P1'))['held'] == [])
shown = json.loads(cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1'))
check('only the release let X run again, and the milestone now passes', shown['milestones'][0]['state'] == 'passed' and lines() == 2, (shown['milestones'][0], lines()))
'''
sc.register('R05', 'r05-lost-run-held-released',
            ['W37a a verifier run killed after dispatch is reconciled before any retry: unknown outcome -> held, X is not dispatched again',
             'verdict release-run is the only way to a second run and records that exactly-once is not promised'],
            ['verdict.run_reconciled', 'verdict.run_held', 'verdict.run_released'], R05_LOST_RUN)

# =============================================================== R06 ===============================================================
R06_REVIEWER = r'''
import contextlib, io
from unittest.mock import patch
from onecrew.v2 import plan, verdict, incidents, lessons, findings, context
from onecrew.v2.verifiers import reviewer
NL = chr(10)
(root / '.gitignore').write_text('.onecrew/' + NL)
(root / 'service.py').write_text('def export_records(rows):' + NL + '    return list(rows)[1:]' + NL)
git('add', '.'); git('commit', '-qm', 'buggy export before work')
raw = contract()
raw['scope'] = {'owned': ['a.txt', 'service.py']}
raw['milestones'][0] = {'id': 'M1', 'title': 'Verify the export', 'covers': ['O1'], 'mode': 'until_pass', 'max_repairs': 5,
    'verifier': {'type': 'reviewer', 'config': {'provider': 'claude', 'model': 'claude-haiku-5-5', 'max_minutes': 5,
        'criteria': [{'id': 'R1', 'question': 'Does service.py preserve every row? Fail if the first row is dropped.'}]}}}
plan.propose(ledger, 'R', raw, 'codex', workflow=True)
plan.approve(ledger, 'R', 'owner', 'fixture approval on a temporary ledger')
environment_failure = [True]
def local_fake_reviewer(prompt, config, env, scratch, limit):
    namespace = {}
    exec(compile((root / 'service.py').read_text(), 'controlled-fixture-service.py', 'exec'), namespace)
    passed = namespace['export_records']([1, 2]) == [1, 2]
    answer = json.dumps({'criteria': [{'id': 'R1', 'verdict': 'pass' if passed else 'fail', 'evidence': [{'file': 'service.py', 'line': 2, 'note': 'controlled export check'}]}], 'outside_criteria': []})
    error = 'sdk unavailable: required environment variable is missing' if environment_failure[0] else None
    environment_failure[0] = False
    return answer, {}, error, False, b''
def root_events(kind=None):
    with ledger.transaction() as conn:
        task = plan.anchor_events(ledger, conn, 'R')['task_id']
        return [(r['seq'], r['kind'], json.loads(r['payload'])) for r in conn.execute('SELECT seq,kind,payload FROM events WHERE task_id=? ORDER BY seq', (task,)) if kind is None or r['kind'] == kind]
with patch.object(reviewer, 'call', side_effect=local_fake_reviewer):
    (root / 'a.txt').write_text('attempt one' + NL); git('add', '.'); git('commit', '-qm', 'environment attempt')
    verdict.run(ledger, 'R', 'M1')
    first = root_events('verdict.recorded')[-1]
    check('an environment error is not a product failure and opens no incident', not incidents.list_incidents(ledger, 'R') and first[2]['result'] != 'pass', first[2])
    (root / 'a.txt').write_text('attempt two' + NL); git('add', '.'); git('commit', '-qm', 'product attempt')
    verdict.run(ledger, 'R', 'M1')
    second = root_events('verdict.recorded')[-1]
    check('the product attempt really fails and registers the finding', second[2]['result'] == 'fail' and findings.list_findings(ledger, 'R')[0]['id'] == 'RF1', second[2])
    check('no incident exists while the red is unrepaired', root_events('learning.incident') == [])
    refuted = context.observe(ledger, 'R', {'type': 'hypothesis_refuted', 'text': 'H1: timezone is not used by this code path.', 'source': {'type': 'event', 'id': second[0]}})
    incidents.observe(ledger, 'R', 'RF1', second[2]['receipt'], refuted_hypotheses=[{'id': 'H1', 'text': 'timezone caused the defect', 'event': refuted['event']}])
    (root / 'service.py').write_text('def export_records(rows):' + NL + '    return list(rows)' + NL)
    git('add', '.'); git('commit', '-qm', 'verified repair'); fixed = git('rev-parse', 'HEAD').strip()
    verdict.run(ledger, 'R', 'M1')
green = root_events('verdict.recorded')[-1]
check('the repaired code passes the same check', green[2]['result'] == 'pass', green[2])
saved = incidents.list_incidents(ledger, 'R')
check('W49a exactly one incident, written by the verified repair', len(saved) == 1 and len(root_events('learning.incident')) == 1, saved)
incident = saved[0]
check('W49a its attempts are environment, product, verified - with their three receipts', [a['classification'] for a in incident['attempts']] == ['environment', 'product', 'verified'] and
      [a['receipt'] for a in incident['attempts']] == [first[2]['receipt'], second[2]['receipt'], green[2]['receipt']], incident['attempts'])
check('W49a the refuted hypothesis is kept and the cause stays unclaimed', incident['refuted_hypotheses'][0]['id'] == 'H1' and incident['cause'] is None, incident)
lesson_events = root_events('learning.lesson')
check('W49b one project lesson was written after the verified verdict and before the root ends', len(lesson_events) == 1 and lesson_events[0][0] > green[0] and plan.show(ledger, 'R')['status'] == 'approved' and not root_events('plan.accepted'))
lesson = lessons._latest(ledger, 'R').popitem()[1]
check('W49b the lesson is located at the fixed revision and the reviewer criterion, and is never injected or promoted by itself',
      lesson['location']['revision'] == fixed and lesson['location']['test'] == 'reviewer:R1' and not lesson['automatic_injection'] and not lesson['automatic_promotion'], lesson['location'])
check('a green check never silently closes the finding', findings.list_findings(ledger, 'R')[0]['status'] == 'open')
count = len(root_events())
listed = json.loads(cli('lesson', 'list', '--name', 'R'))
check('the CLI reads the lesson through the common reader and writes nothing', listed['entries'] and len(root_events()) == count, listed)
check('the CLI lists the incident with its three attempts', len(json.loads(cli('incident', 'list', 'R'))['incidents'][0]['attempts']) == 3)
try:
    incidents.observe(ledger, 'R', 'RF1', '0' * 64); forged_refused = False
except LedgerError:
    forged_refused = True
check('forged evidence cannot become learning', forged_refused and len(root_events('learning.incident')) == 1)
shared = json.loads(cli('lesson', 'general', 'R', lesson['lesson'], '--text', 'Preserve all rows when collecting an iterator.', '--condition', 'Python', '--condition', 'sqlite'))
check('a general candidate is only proposed data', shared['status'] == 'proposed' and shared['location'] is None and shared['automatic_promotion'] is False, shared)
json.loads(cli('lesson', 'withdraw', 'R', lesson['lesson'], '--reason', 'the lesson was too broad'))
check('a withdrawn lesson is no longer retrieved', not any(e.get('lesson') == lesson['lesson'] for e in context.retrieve(ledger, plan='R')['entries']))
'''
sc.register('R06', 'r06-incident-lesson-reviewer',
            ['W49a a real red check, an environment error kept apart, a refuted hypothesis, one incident from the verified repair',
             'W49b one project lesson before the root ends; CLI reads write nothing; forged evidence refused; general candidate only proposed'],
            ['learning.incident', 'learning.lesson'], R06_REVIEWER)

R06_NATIVE = ENGINE + r'''
from onecrew.common_executor import NativeExecutor
from onecrew.common_verification import CandidateChecker
from onecrew.v2 import incidents, lessons, context
NL = chr(10)
(root / '.gitignore').write_text('.onecrew/' + NL)
git('add', '.'); git('commit', '-qm', 'ignore state')
raw = contract()
raw['authority'] = {'edit': True, 'commands': True, 'unconfined_commands': True, 'self_decide': SELF_DECIDE}
raw['milestones'][0]['verifier']['config']['argv'] = [sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text().splitlines()==["1","2"]; print("row preservation verified")']
nodes = [node('C', checks=[{'id': 'M1', 'spec': 'Preserve both rows under the approved real command.'}]),
         node('I', ['C'], integration=True, write=(), read=('a.txt',), checks=[{'id': 'M1', 'spec': 'Preserve both rows under the approved real command.'}])]
for item in nodes: item['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
control = start(raw, nodes)
output = ['2' + NL]
calls = []
def factory(control, provider):
    class Worker:
        def capability(self): return {'provider': provider, 'mode': 'explicit-no-provider-call-fixture'}
        def run(self, attempt, prompt, schema, profile):
            calls.append(attempt['id'])
            control.launched(attempt['id'], attempt['generation'], {'fixture': True}); control.finish(attempt['id'], attempt['generation'], {'exit_code': 0})
        def result(self, attempt):
            return {'summary': 'fixture', 'files': [{'path': 'a.txt', 'content': output[0]}], 'backlog': []}, []
    return Worker()
executor = NativeExecutor(ledger, worker_factory=factory)
checker = CandidateChecker(ledger, 'P1')
engine.step(ledger, 'P1', executor)
red = engine.verify(ledger, 'P1', 'C', checker)
check('the real approved command fails on the first candidate', red['result'] == 'fail', red)
check('W49a a single red has no incident yet', incidents.list_incidents(ledger, 'P1') == [] and 'learning.incident' not in kinds_of())
source = engine.state(ledger, 'P1')['nodes']['C']['verification_receipt']
action = Path(state) / 'repair-input.json'
action.write_text(json.dumps({'target': 'C', 'failed_node': 'C', 'reason': 'Repair the actual row-preservation assertion', 'evidence': [source]}))
cli('engine', 'repair', 'P1', '--file', str(action))
output[0] = '1' + NL + '2' + NL
engine.step(ledger, 'P1', executor)
green = engine.verify(ledger, 'P1', 'C', checker)
check('the repaired candidate passes the same real command', green['result'] == 'pass', green)
saved = incidents.list_incidents(ledger, 'P1')
check('W49a the verified repair wrote exactly one node episode incident, with no finding or claimed cause', len(saved) == 1 and saved[0]['finding'] is None and saved[0]['episode'].startswith('NEP-') and saved[0]['cause'] is None, saved)
check('W49a its attempts are product then verified, from two distinct attempts', [o['classification'] for o in saved[0]['attempts']] == ['product', 'verified'] and len({o['attempt'] for o in saved[0]['attempts']}) == 2 and len(calls) == 2, saved[0]['attempts'])
entry = lessons.retrieve(ledger, name='P1')['entries'][0]
lesson = lessons._latest(ledger, 'P1')[entry['lesson']]
check('W49b the lesson is located at the candidate tree, file and check, and is only data',
      lesson['location']['revision'] == green['observed']['candidate_tree'] and lesson['location']['path'] == 'a.txt' and lesson['location']['test'] == 'check:M1'
      and not lesson['automatic_promotion'] and not lesson['automatic_injection'], lesson['location'])
check('W49b the lesson exists while the root is still open and nothing is delivered', plan.show(ledger, 'P1')['status'] == 'approved' and (root / 'a.txt').read_text() == 'base' + NL and not engine.root_ready(ledger, 'P1'))
pinned = next(e for e in context.retrieve(ledger, plan='P1', revision=green['observed']['candidate_tree'])['entries'] if e.get('lesson'))
check('the next task can query the candidate input before the project is changed', pinned['label'] == 'verified', pinned)
listed = json.loads(cli('lesson', 'list', '--name', 'P1'))
check('the CLI reads the same lesson', any(e.get('lesson') == entry['lesson'] for e in listed['entries']))
check('both kinds are on the ledger once', kinds_of().count('learning.incident') == 1 and kinds_of().count('learning.lesson') == 1, kinds_of())
'''
sc.register('R06', 'r06-native-node-repair-lesson',
            ['W49a on the common engine: a real failed command check, a bounded repair, the verified candidate writes one incident and one project lesson mid-root', 'W49b on the common engine: a real failed command check, a bounded repair, the verified candidate writes one incident and one project lesson mid-root',
             'the lesson is located at the candidate tree before any project apply'],
            ['learning.incident', 'learning.lesson'], R06_NATIVE)

# =============================================================== R07 ===============================================================
R07_LOCALIZE = r'''
from onecrew.v2 import plan, localization, providers
NL = chr(10)
ISSUE = 'Click "Export report" gives 500 for month 2.'
(root / '.gitignore').write_text('.onecrew/' + NL)
(root / 'ui.html').write_text('<button data-handler="ReportController.export" data-route="/reports/export">Export report</button>' + NL)
(root / 'reports.py').write_text('class ReportController:' + NL + '    def export(self, month):' + NL + '        return ExportService().build(month)' + NL + NL +
                                 'class ExportService:' + NL + '    def build(self, month):' + NL + '        return 31' + NL)
(root / 'test_reports.py').write_text('def test_export_build():' + NL + '    assert ExportService().build(2) == 28' + NL)
git('add', '.'); git('commit', '-qm', 'before report issue repair'); pinned = git('rev-parse', 'HEAD').strip()
plan.propose(ledger, 'P1', contract(), 'codex')
task = plan.show(ledger, 'P1')['anchor_task']
before = ledger.events(task)
indexed = json.loads(cli('issue', 'map', 'P1', '--revision', pinned))
check('R07 the explicit map records one bounded, complete, pinned map', indexed['recorded'] and indexed['complete'] and indexed['files'] >= 4, indexed)
check('R07 the map is exactly one context entry on the plan and a second map of the same revision records nothing', len(ledger.events(task)) == len(before) + 1 and not json.loads(cli('issue', 'map', 'P1', '--revision', pinned))['recorded'])
(root / 'reports.py').write_text('class FutureRename:' + NL + '    def renamed(self):' + NL + '        return 28' + NL)
git('add', '.'); git('commit', '-qm', 'future repair renamed the old symbols')
events_before = ledger.events(task)
result = json.loads(cli('issue', 'localize', ISSUE, '--name', 'P1', '--revision', pinned))
suspects = {s['method']: s for s in result['suspects']}
check('R07 the lookup finds the controller and the service at the PINNED revision although HEAD renamed them', result['revision'] == pinned and {'ReportController.export', 'ExportService.build'} <= set(suspects), sorted(suspects))
item = suspects['ExportService.build']
check('R07 every suspect is a labelled hypothesis with a reason, a pinned source line and the test to run first',
      item['label'] == 'hypothesis' and item['reason'] and item['file'] == 'reports.py' and item['source']['line'] > 0 and item['source']['revision'] == pinned and 'test_export_build' in item['next_check']['tests'], item)
check('R07 the lookup proposes no change and keeps its search receipts', not result['proposed_changes'] and result['search_receipts'] and result['search_complete'], result['search_complete'])
check('R07 the lookup is read-only: no event was written', ledger.events(task) == events_before)
vague = json.loads(cli('issue', 'localize', 'app slow', '--name', 'P1', '--revision', pinned))
check('R07 a vague issue gets no suspect but the three things still needed', not vague['suspects'] and vague['status'] and len(vague['needed']) == 3, vague['needed'])
fallback = json.loads(cli('issue', 'localize', ISSUE, '--name', 'P1', '--revision', pinned, '--image', str(root / 'missing-screenshot.png'), '--provider', 'codex'))
check('R07 an image with a provider that declares no vision is NOT read (the missing file is never opened) and the reason says why',
      fallback['image']['read'] is False and 'vision' in fallback['image']['reason'] and 'declares no vision adapter' in fallback['image']['reason'], fallback['image'])
check('R07 the text lookup still answers without the image', {'ReportController.export', 'ExportService.build'} <= {s['method'] for s in fallback['suspects']} and not any(o['source']['type'] == 'image' for o in fallback['observations']))
declared = providers.vision('codex')
check('R07 the provider declaration is data: no capability, no observer, a reason', declared['capabilities'] == [] and declared['observe_image'] is None and declared['reason'], declared)
try:
    providers.vision('not-a-provider'); unknown_refused = False
except Exception as error:
    unknown_refused = 'expected one of' in str(error)
check('R07 an unknown provider name is refused', unknown_refused)
'''
sc.register('R07', 'r07-localize-map-image-fallback',
            ['W50a explicit issue map, pinned-revision lookup with hypothesis labels, source lines and tests, vague issue asks for data, read-only',
             'W50b an image is not opened when the provider declares no vision adapter; the reason is reported and the text lookup still answers'],
            [], R07_LOCALIZE, no_new_events='W50a/W50b add no event kind: issue lookup and image fallback are read paths over the existing ledger and evidence (04-TASKS W50a/W50b).')

R07_VISION = r'''
from onecrew.v2 import plan, localization, providers
NL = chr(10)
(root / '.gitignore').write_text('.onecrew/' + NL)
(root / 'ui.html').write_text('<button data-handler="ReportController.export">Export report</button>' + NL)
(root / 'reports.py').write_text('class ReportController:' + NL + '    def export(self, month):' + NL + '        return ExportService().build(month)' + NL + NL +
                                 'class ExportService:' + NL + '    def build(self, month):' + NL + '        return 31' + NL)
(root / 'test_reports.py').write_text('def test_export_build():' + NL + '    assert ExportService().build(2) == 28' + NL)
git('add', '.'); git('commit', '-qm', 'before report issue repair'); pinned = git('rev-parse', 'HEAD').strip()
plan.propose(ledger, 'P1', contract(), 'codex')
task = plan.show(ledger, 'P1')['anchor_task']
before = ledger.events(task)
calls = []
missing = root / 'not-present.png'
text_only = localization.localize(ledger, 'Error screenshot', revision=pinned, image=missing, provider={'name': 'T', 'capabilities': [], 'observe_image': lambda p: calls.append(p)})
check('R07 capability is checked BEFORE any image access: the observer is never called for a text-only provider', calls == [] and text_only['image']['read'] is False and 'không đọc ảnh' in text_only['image']['reason'], text_only['image'])
check('R07 a text-only lookup of a screenshot-only issue has no suspects and says what it needs', not text_only['suspects'] and len(text_only['needed']) == 3)
image = root / 'error.png'; image.write_bytes(b'controlled fixture image bytes')
def vision(path):
    calls.append(path.read_bytes())
    return ['Screen reports error 500 on "Export report".']
viewed = localization.localize(ledger, 'Error screenshot', revision=pinned, image=image, provider={'name': 'V', 'capabilities': ['vision'], 'observe_image': vision})
check('R07 a declared vision adapter reads the image exactly once', calls == [b'controlled fixture image bytes'] and viewed['image']['read'] is True, calls)
check('R07 the image observation is labelled observed with its provider, and drives real suspects',
      any(o['source']['type'] == 'image' and o['label'] == 'observed' and o['source']['provider'] == 'V' for o in viewed['observations']) and 'ReportController.export' in {s['method'] for s in viewed['suspects']}, viewed['observations'])
check('R07 image-derived suspects stay hypotheses and propose no change', all(s['label'] == 'hypothesis' for s in viewed['suspects']) and not viewed['proposed_changes'])
try:
    localization.localize(ledger, 'Error screenshot', revision=pinned, image=image, provider={'name': 'V', 'capabilities': ['vision'], 'observe_image': None}); refused = False
except Exception as error:
    refused = 'explicit image observer' in str(error)
check('R07 vision declared without an observer is refused, not guessed', refused)
check('R07 no lookup wrote to the ledger', ledger.events(task) == before)
'''
sc.register('R07', 'r07-image-capability-order',
            ['W50b the capability declaration is checked before the image is touched; a declared adapter reads it once and its text is labelled observed',
             'vision without an observer is refused; lookups are read-only'],
            [], R07_VISION, no_new_events='W50a/W50b add no event kind: issue lookup and image fallback are read paths over the existing ledger and evidence (04-TASKS W50a/W50b).')

# =============================================================== R08 ===============================================================
R08_BATCH = ENGINE + r'''
import contextlib, io
from onecrew import artifact_provider_core
from onecrew.budget_core import group
from onecrew.process_core import Supervisor, native_python
from onecrew.subscription import environment
from onecrew.v2.cli import main as v2main
NL = chr(10)
os.environ['ONECREW_HOST_HOME'] = str(Path(state).parent / 'host-home')
(root / 'b.txt').write_text('base-b' + NL); git('add', '.'); git('commit', '-qm', 'add b')
raw = contract()
raw['scope'] = {'owned': ['a.txt', 'b.txt']}
raw['understanding']['target']['paths'] = ['a.txt', 'b.txt']
raw['authority'] = {'edit': True, 'commands': True, 'unconfined_commands': True, 'apply_to_project': True, 'self_decide': SELF_DECIDE}
second = json.loads(json.dumps(raw['milestones'][0])); second['id'] = 'M2'; second['title'] = 'Check second producer'; raw['milestones'].append(second)
for milestone, path in zip(raw['milestones'], ['a.txt', 'b.txt']):
    milestone['verifier']['config']['argv'] = [sys.executable, '-c', 'from pathlib import Path; assert Path("' + path + '").read_text().strip()=="candidate-' + path + '"; print("actual candidate check passed")']
nodes = [node('A', checks=[{'id': 'M1', 'spec': 'Run approved M1'}]), node('B', write=('b.txt',), read=('b.txt',), checks=[{'id': 'M2', 'spec': 'Run approved M2'}]),
         node('I', ['A', 'B'], integration=True, write=(), read=('a.txt', 'b.txt'), checks=[{'id': 'M1', 'spec': 'Run approved M1'}, {'id': 'M2', 'spec': 'Run approved M2'}])]
for item in nodes: item['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
control = start(raw, nodes, CAPS + ['parallel-engine'])
initial_index = git('write-tree').strip()
ready_dir = Path(state).parent / 'ready'; ready_dir.mkdir()
calls = []
def factory(control, provider):
    class Worker:
        def capability(self): return {'provider': provider, 'mode': 'local-process-no-provider'}
        def run(self, attempt, prompt, schema, profile):
            calls.append(attempt['id'])
            directory = ledger.state_root / 'worker-io' / attempt['id']; directory.mkdir(parents=True)
            paths = schema['properties'].get('files', {}).get('items', {}).get('properties', {}).get('path', {}).get('enum', [])
            value = ({'summary': 'isolated producer', 'files': [{'path': path, 'content': 'candidate-' + path + NL} for path in paths], 'backlog': []} if paths
                     else {'summary': 'integration report', 'evidence': []})
            script = ('import pathlib,sys,time' + NL + 'ready=pathlib.Path(sys.argv[1]);(ready/sys.argv[2]).write_text("ready")' + NL +
                      'end=time.monotonic()+5' + NL + 'while sys.argv[4]=="pair" and len(list(ready.iterdir()))<2 and time.monotonic()<end:time.sleep(.02)' + NL +
                      'assert sys.argv[4]!="pair" or len(list(ready.iterdir()))>=2,"second slot missing"' + NL + 'pathlib.Path("answer.json").write_text(sys.argv[3])' + NL)
            return Supervisor(control).run(attempt, [native_python(), '-c', script, str(ready_dir), attempt['id'], json.dumps(value), 'pair' if paths else 'single'],
                                           cwd=directory, timeout=8, env=environment())
        def result(self, attempt):
            return json.loads((ledger.state_root / 'worker-io' / attempt['id'] / 'answer.json').read_text()), []
    return Worker()
def inproc(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): code = v2main(['--project', str(root), '--state-root', str(state), *args])
    must('in-process ' + ' '.join(args) + ' exits 0', code == 0, out.getvalue()[-300:])
    return json.loads(out.getvalue())
with ledger.transaction() as conn: before = group(conn, plan.show(ledger, 'P1')['anchor_task'])
original = artifact_provider_core.make_worker
artifact_provider_core.make_worker = factory
try:
    batch = inproc('engine', 'batch', 'plan-ns:P1', '--slots', '2')
    check('W14b the parallel engine produced both disjoint nodes in ONE batch, each in its own real process', len(batch['results']) == 2 and all(r['state'] == 'produced' for r in batch['results']) and len(calls) == 2, batch)
    check('the two real processes overlapped (each saw the other ready before finishing)', len(list(ready_dir.iterdir())) == 2)
    inproc('engine', 'verify', 'P1', 'A'); inproc('engine', 'verify', 'P1', 'B')
    inproc('engine', 'step', 'P1'); inproc('engine', 'verify', 'P1', 'I')
    delivered = inproc('engine', 'handoff', 'P1')
finally:
    artifact_provider_core.make_worker = original
check('W15 the mandatory integration node ran after both producers: three worker processes in total', len(calls) == 3, calls)
check('the project received the candidates only through the handoff (git index unchanged)', (root / 'a.txt').read_text().strip() == 'candidate-a.txt' and (root / 'b.txt').read_text().strip() == 'candidate-b.txt' and git('write-tree').strip() == initial_index)
with ledger.transaction() as conn:
    rows = conn.execute("SELECT payload FROM events WHERE kind='executor.managed' AND task_id IN (SELECT id FROM tasks WHERE project_id=?)", (ledger.project_id,)).fetchall()
phases = [json.loads(r['payload'])['phase'] for r in rows]
check('executor.managed journals each batch attempt (prepared, dispatching, candidate); the sequential integration step uses the plain native executor', phases.count('prepared') == 2 and phases.count('dispatching') == 2 and phases.count('candidate') == 2, phases)
with ledger.transaction() as conn: after = group(conn, plan.show(ledger, 'P1')['anchor_task'])
check('the shared root budget is charged once per worker call and never reset', after['used_calls'] == 3 and after['reserved_calls'] == 0 and after['deadline'] == before['deadline'], (before, after))
check('the delivered root is ready only for the handed-off artifact', engine.root_ready(ledger, 'P1', delivered['artifact']))
cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1'); cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M2')
owner()
check('the owner accepts the delivered two-slot result', plan.accept(ledger, 'P1', 'owner', 'delivered two-slot fixture accepted', delivered['artifact'])['status'] == 'accepted')
check('the v1 job runtime was never loaded by the managed path', not any(n in sys.modules for n in ('onecrew.workflow', 'onecrew.control', 'onecrew.supervisor', 'onecrew.solution_gate')))
'''
sc.register('R08', 'r08-managed-parallel-batch',
            ['W14b the parallel engine runs two disjoint producers as two overlapping real managed processes, then the mandatory integration node',
             'W15 one handoff applies the verified candidates; the root budget is charged per call and never reset; executor.managed journals every attempt'],
            ['executor.managed', 'workflow.handoff'], R08_BATCH)

R08_MANAGED_COMMON = ENGINE + r'''
import threading
from onecrew.process_core import Supervisor, native_python
from onecrew.subscription import environment
from onecrew.v2 import managed_executor, executors
NL = chr(10)
os.environ['ONECREW_HOST_HOME'] = str(Path(state).parent / 'host-home')
marker = Path(state).parent / 'operations.txt'
started = Path(state).parent / 'operation-started'
go = Path(state).parent / 'operation-go'
launches = []
def factory(control, provider):
    class LocalArtifactWorker:
        def capability(self): return {'provider': provider, 'mode': 'local-test-artifact-no-tools'}
        def run(self, attempt, prompt, schema, profile):
            launches.append(attempt['id'])
            directory = ledger.state_root / 'worker-io' / attempt['id']; directory.mkdir(parents=True)
            script = ('import pathlib,sys,time' + NL + 'pathlib.Path(sys.argv[1]).write_text("started")' + NL +
                      'until=time.monotonic()+float(sys.argv[3])' + NL +
                      'while not pathlib.Path(sys.argv[5]).exists() and time.monotonic()<until: time.sleep(0.05)' + NL +
                      'with pathlib.Path(sys.argv[2]).open("a") as out: out.write("operation completed" + chr(10))' + NL +
                      'pathlib.Path("answer.json").write_text(sys.argv[4])' + NL)
            value = {'summary': 'Local fixture candidate', 'files': [{'path': 'a.txt', 'content': 'isolated candidate' + NL}], 'backlog': []}
            return Supervisor(control).run(attempt, [native_python(), '-c', script, str(started), str(marker), '25', json.dumps(value), str(go)],
                                           cwd=directory, timeout=min(30, profile['step_seconds']), env=environment())
        def result(self, attempt):
            return json.loads((ledger.state_root / 'worker-io' / attempt['id'] / 'answer.json').read_text()), []
    return LocalArtifactWorker()
def background_step(adapter):
    result = {}
    def run():
        try: result['value'] = engine.step(ledger, 'P1', adapter)
        except BaseException as error: result['error'] = error
    thread = threading.Thread(target=run); thread.start()
    until = time.monotonic() + 15
    while not started.exists() and time.monotonic() < until: time.sleep(0.05)
    must('the managed worker process is really running', started.exists(), result)
    with ledger.transaction() as conn:
        attempt = conn.execute("SELECT id FROM attempts WHERE status='running' ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    return thread, result, attempt
def executor_json(*args, expect=0):
    return json.loads(cli('executor', *args, expect=expect))
'''

R08_PAUSE = R08_MANAGED_COMMON + r'''
raw = contract()
raw['scope'] = {'owned': ['a.txt', 'b.txt']}
raw['authority'] = {'edit': True, 'commands': True, 'self_decide': SELF_DECIDE}
raw['milestones'][0]['verifier'] = {'type': 'data', 'config': {'path': 'a.txt', 'columns': {'one': 'string'}, 'key': ['one'], 'row_count': 2}}
first = node('C'); first['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
other = node('X', write=('b.txt',), read=('b.txt',))
integration = node('I', ['C', 'X'], integration=True, write=(), read=()); integration['executor'] = dict(first['executor'])
control = start(raw, [first, other, integration], CAPS + ['finding-register'])
adapter = managed_executor.ManagedExecutor(ledger, worker_factory=factory)
thread, result, attempt = background_step(adapter)
verdict.run(ledger, 'P1', 'M1')                                   # the REAL data check fails while the operation of C is in flight -> a finding opens
rows = findings.list_findings(ledger, 'P1', open_only=True)
check('W17 the finding opened while the managed node was running', len(rows) == 1)
history = adapter._history(attempt)
requested = [p for p in history if p['phase'] == 'pause_requested']
check('W36 the engine asked THAT attempt to pause at its safe point, naming the finding and the node', len(requested) == 1 and rows[0]['id'] in requested[0]['reason'] and 'C' in requested[0]['reason'], history)
check('the operation in flight is not interrupted: nothing completed yet', not marker.exists())
shown = executor_json('state', attempt)
check('the CLI says pause requested, not paused, until the Supervisor confirms', shown['state'] == 'pause_requested' and not shown['safe_point_acknowledged'], shown)
go.write_text('go')                                               # the bounded operation ends: that is the safe point
thread.join(40)
check('the step returned held at the real safe point', not thread.is_alive() and 'error' not in result and result['value']['state'] == 'held' and result['value']['executor_state'] == 'paused', result)
paused = executor_json('state', attempt)
check('the CLI now reports the tree stopped at the safe point, with the exact words', paused['state'] == 'paused' and paused['tree_stopped'] and paused['text'] == 'đã dừng tại điểm an toàn', paused)
check('the one bounded operation completed exactly once and the project is untouched', marker.read_text().splitlines() == ['operation completed'] and (root / 'a.txt').read_text() == 'base' + NL)
view = engine.state(ledger, 'P1')
check('the safe-point candidate is retained, never published, while the finding holds C', view['nodes']['C']['phase'] == 'running' and view['nodes']['C']['artifact'] is None and 'node.result_retained' in kinds_of(), view['nodes']['C'])
findings.update(ledger, 'P1', rows[0]['id'], reason='scope is a.txt only', read=['a.txt'], write=[])
check('a second register change does not repeat the pause request', len([p for p in adapter._history(attempt) if p['phase'] == 'pause_requested']) == 1)
(root / 'a.txt').write_text('one' + NL + 'row1' + NL + 'row2' + NL)
shown_pass = verdict.run(ledger, 'P1', 'M1')
findings.resolve(ledger, 'P1', rows[0]['id'], shown_pass['milestones'][0]['last_verdict']['receipt'], reason='rows restored', artifact_sha=vcommand.artifact_sha(root))
check('real passing evidence closed the finding', findings.list_findings(ledger, 'P1', open_only=True) == [])
released = engine.step(ledger, 'P1', adapter)
check('W36 the release reuses the retained candidate: no second process was launched', released['node'] == 'C' and released['state'] == 'produced' and released['released_retained'] is True and launches == [attempt], (released, launches))
check('the released artifact is the candidate that was paused', released['artifact'] == paused['candidate']['artifact'] and Snapshots(ledger.state_root).context(released['artifact'])['a.txt'] == 'isolated candidate' + NL)
check('executor.managed journal shows the pause request and the single candidate', [p['phase'] for p in adapter._history(attempt)].count('candidate') == 1 and 'pause_requested' in [p['phase'] for p in adapter._history(attempt)])
'''
sc.register('R08', 'r08-pause-safe-point-release',
            ['W36 a finding opened while a managed node runs asks that attempt to pause; the pause is only claimed after the Supervisor safe point (CLI executor state)', 'W18 a finding opened while a managed node runs asks that attempt to pause; the pause is only claimed after the Supervisor safe point (CLI executor state)',
             'W15 after real passing evidence closes the finding, the retained candidate is released without another process', 'W36 after real passing evidence closes the finding, the retained candidate is released without another process'],
            ['executor.managed', 'finding.registered', 'node.result_retained'], R08_PAUSE)

R08_STOP = R08_MANAGED_COMMON + r'''
raw = contract()
raw['scope'] = {'owned': ['a.txt', 'b.txt']}
raw['authority'] = {'edit': True, 'commands': True, 'self_decide': SELF_DECIDE}
first = node('C'); first['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
integration = node('I', ['C'], integration=True, write=(), read=()); integration['executor'] = dict(first['executor'])
control = start(raw, [first, integration])
adapter = managed_executor.ManagedExecutor(ledger, worker_factory=factory)
thread, result, attempt = background_step(adapter)
requested = executor_json('stop', attempt, '--reason', 'Stop bounded test process')
check('the owner stop is requested through the CLI against the running attempt', requested['state'] in ('stop_requested', 'stopped'), requested)
thread.join(40)
check('the step ended after the stop', not thread.is_alive())
stopped = executor_json('state', attempt)
check('W15 a stop waits for the process tree to die and is never reported as a safe pause', stopped['state'] == 'stopped' and stopped['tree_stopped'] and not stopped['safe_point_acknowledged'] and stopped['candidate'] is None, stopped)
check('the emergency stop is not claimed as a completed operation', not marker.exists() and launches == [attempt])
recovered = executor_json('recover', attempt)
check('recover reconciles evidence and never starts the worker again', launches == [attempt] and recovered['automatic_restart'] is False, recovered)
isolation = executor_json('isolate', attempt)
check('the isolation answer is honest: write scope only, no network or read isolation', isolation['write_scope'] == ['a.txt'] and isolation['network_isolation'] is False and isolation['read_isolation'] is False, isolation)
check('a stopped node has no candidate to publish and the project is untouched', engine.state(ledger, 'P1')['nodes']['C']['artifact'] is None and (root / 'a.txt').read_text() == 'base' + NL)
refused = cli('executor', 'state', 'ATT-not-a-managed-attempt', expect=2)
check('controls are refused for an attempt this project does not own', 'Unknown attempt' in refused, refused)
'''
sc.register('R08', 'r08-stop-is-not-a-safe-pause',
            ['W15 a stop kills the real process tree, reports stopped (never paused), keeps no candidate, and recover does not relaunch',
             'controls are refused for an unknown attempt'],
            ['executor.managed'], R08_STOP)

# =============================================================== RP ===============================================================
# One LOCAL fake CLI (copied from tests/test_wf_rp_providers.py): it records argv, working directory and stdin and answers in the format of the provider it
# stands for. It proves the interface and the rules of the installed build; the real CLIs are W45 evidence, not this scenario.
FAKE_CLI = r'''import json, os, sys
from pathlib import Path
here = Path(__file__).parent
tag, args = sys.argv[1], sys.argv[2:]
if args == ['--version']:
    print('fake-%s 0.0.1' % tag); sys.exit(0)
stdin = sys.stdin.read()
with (here / 'calls.jsonl').open('a', encoding='utf-8') as log:
    log.write(json.dumps({'provider': tag, 'args': args, 'cwd': os.getcwd(), 'stdin': stdin, 'listing': sorted(os.listdir('.'))}) + '\n')
mode = (here / 'mode.txt').read_text().strip() if (here / 'mode.txt').exists() else 'ok'
answer = (here / 'answer.txt').read_text(encoding='utf-8') if (here / 'answer.txt').exists() else ''
quota = "You've hit your usage limit. Try again later."
def emit(*events):
    for event in events: print(json.dumps(event))
if mode == 'tooloutput': print('this is not json at all'); sys.exit(0)
if tag == 'claude':
    if mode == 'quota': print(json.dumps({'type': 'result', 'is_error': True, 'result': quota})); sys.exit(1)
    print(json.dumps({'type': 'result', 'is_error': False, 'result': answer, 'usage': {'input_tokens': 1, 'output_tokens': 1}}))
elif tag == 'codex':
    if mode == 'quota': emit({'type': 'turn.failed', 'error': {'message': quota}}); sys.exit(1)
    emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': answer}}, {'type': 'turn.completed', 'usage': {'output_tokens': 1}})
else:
    chunk = {'type': 'update', 'data': {'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': answer}}}}
    if mode == 'quota': emit({'type': 'runFinished', 'data': {'status': 'error', 'error': quota}}); sys.exit(1)
    emit(chunk, {'type': 'runFinished', 'data': {'status': 'success', 'stopReason': 'end_turn', 'finalTextTruncated': False}})
'''

RP_COMMON = r'''
NL = chr(10)
AUTHOR = 'claude-sonnet-5-5'
MODELS = {'claude': 'claude-haiku-5-5', 'codex': 'gpt-5-codex', 'kiro': 'claude-haiku-4.5'}
ADVISOR_MODELS = {'claude': 'claude-opus-5-5', 'codex': 'gpt-5-codex', 'kiro': 'claude-haiku-4.5'}
CRITERIA = [{'id': 'R1', 'question': 'Does the diff of a.txt add the line "two"? Fail if it does not.'},
            {'id': 'R2', 'question': 'Does the diff touch any file other than a.txt? Fail if it does.'}]
fake = Path(state).parent / 'fake'; fake.mkdir()
script = fake / 'fake_cli.py'
script.write_text(__FAKE__, encoding='utf-8')
for provider_name, variable in (('codex', 'ONECREW_CODEX_CLI'), ('kiro', 'ONECREW_KIRO_CLI')):
    os.environ[variable] = json.dumps([sys.executable, str(script), provider_name])      # a LOCAL fake in place of the CLI; nothing real is called
def set_mode(value): (fake / 'mode.txt').write_text(value)
def reply(text): (fake / 'answer.txt').write_text(text, encoding='utf-8')
def calls():
    path = fake / 'calls.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
def events_of(kind, name):
    from onecrew.v2 import plan as _plan
    with ledger.transaction() as conn:
        task = _plan.anchor_events(ledger, conn, name)['task_id']
        return [json.loads(r['payload']) for r in conn.execute('SELECT payload FROM events WHERE task_id=? AND kind=? ORDER BY seq', (task, kind))]
def blob(key):
    from onecrew.snapshots import Snapshots
    return json.loads(Snapshots(ledger.state_root).read_blob(key))
set_mode('ok')
'''.replace('__FAKE__', repr(FAKE_CLI))

RP_LINT = r'''
from onecrew.v2 import contract as contracts
MODELS = {'claude': 'claude-haiku-5-5', 'codex': 'gpt-5-codex', 'kiro': 'claude-haiku-4.5'}
def reviewer_milestone(provider, model):
    return {'id': 'M1', 'title': 'Review', 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': {'provider': provider, 'model': model, 'max_minutes': 5,
            'criteria': [{'id': 'R1', 'question': 'Does the diff of a.txt add the line "two"? Fail if it does not.'}]}}}
def lint_file(name, value, expect):
    target = Path(state).parent / (name + '.json'); target.write_text(json.dumps(value))
    return cli('plan', 'lint', '--file', str(target), '--author', 'claude-sonnet-5-5', expect=expect)
for provider, model in MODELS.items():
    value = contract(); value['milestones'] = [reviewer_milestone(provider, model)]; value['advisor'] = {'provider': provider, 'model': model}
    out = lint_file('ok-' + provider, value, 0)
    config = contracts.validate(value)['milestones'][0]['verifier']['config']
    check('E17 provider ' + provider + ' with a model is accepted by lint and kept by the contract', (config['provider'], config['model']) == (provider, model) and 'schema' not in out, out)
bad_cases = {}
value = contract(); value['milestones'] = [reviewer_milestone('gemini', 'gemini-2.5-pro')]; bad_cases['reviewer provider outside the three'] = value
value = contract(); value['milestones'] = [reviewer_milestone('claude', 'claude-haiku-5-5')]; del value['milestones'][0]['verifier']['config']['model']; bad_cases['reviewer without a model'] = value
value = contract(); value['advisor'] = {'provider': 'codex'}; bad_cases['advisor without a model'] = value
value = contract(); value['advisor'] = {'provider': 'kiro', 'model': '--trust-all-tools'}; bad_cases['advisor model that looks like a flag'] = value
value = contract(); value['advisor'] = {'provider': 'claude', 'model': 'claude-opus-5-5', 'tools': 'all'}; bad_cases['advisor with extra keys'] = value
for label, value in bad_cases.items():
    out = lint_file('bad-' + label.replace(' ', '-'), value, 1)
    check('E17 lint refuses: ' + label, 'schema' in out, out)
# changing the provider is a change of two fields: the contract text is otherwise identical (E13)
a = contract(); a['milestones'] = [reviewer_milestone('claude', MODELS['claude'])]
b = contract(); b['milestones'] = [reviewer_milestone('codex', MODELS['codex'])]
flat = lambda v: json.dumps(v, sort_keys=True).replace('claude-haiku-5-5', 'M').replace('gpt-5-codex', 'M').replace('"claude"', '"P"').replace('"codex"', '"P"')
check('E1/E13 two contracts that differ only in provider and model fields are otherwise identical', flat(a) == flat(b))
'''
sc.register('RP', 'rp-lint-provider-fields',
            ['W43 E17 contract lint (installed CLI) accepts claude, codex and kiro with a model for reviewer and advisor and refuses a fourth provider, a missing model, a flag-like model and extra advisor keys',
             'E1/E13: changing provider is a change of the two fields only'],
            [], RP_LINT, no_new_events='W43 pins provider/model in the contract and reuses plan.advised / verdict.recorded (class 0); the real six cells are W45 evidence, not events.')

RP_REVIEWER = RP_COMMON + r'''
from unittest.mock import patch
from onecrew.v2 import plan, verdict
from onecrew.v2.verifiers import reviewer
def answer_text():
    row = lambda cid: {'id': cid, 'verdict': 'pass', 'evidence': [{'file': 'a.txt', 'line': 2, 'note': 'seen'}]}
    return json.dumps({'criteria': [row('R1'), row('R2')], 'outside_criteria': []})
def start(name, provider, model, author=AUTHOR):
    value = contract()
    value['milestones'] = [{'id': 'M1', 'title': 'Review', 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': {'provider': provider, 'model': model, 'criteria': CRITERIA, 'max_minutes': 5}}}]
    git('checkout', '--', 'a.txt')
    plan.propose(ledger, name, value, author)
    plan.approve(ledger, name, 'owner', 'fixture approval on a temporary ledger')
    (root / 'a.txt').write_text('one' + NL + 'two' + NL)           # the work the reviewer will look at, made AFTER the approved base
reply(answer_text())
claude_argv = lambda env: [sys.executable, str(script), 'claude']
for provider in ('codex', 'kiro', 'claude'):
    name = 'P' + provider
    start(name, provider, MODELS[provider])
    seen = len(calls()); status_before = git('status', '--porcelain')
    if provider == 'claude':
        with patch.object(reviewer, 'cli_argv', claude_argv):
            view = verdict.run(ledger, name, 'M1', root)
    else:
        view = json.loads(cli('verdict', 'run', '--plan', name, '--milestone', 'M1'))
    recorded = events_of('verdict.recorded', name)[-1]
    receipt = blob(recorded['receipt'])
    check('E19/E3 ' + provider + ' reviewer passes through its CLI and the receipt names provider, model and role',
          view['milestones'][0]['state'] == 'passed' and (recorded['provider'], recorded['model'], recorded['result'], recorded['calls']) == (provider, MODELS[provider], 'pass', 1) and
          (receipt['provider'], receipt['model'], receipt['role']) == (provider, MODELS[provider], 'reviewer'), (recorded, {k: receipt.get(k) for k in ('provider', 'model', 'role')}))
    mine = calls()[seen:]
    check('E2 ' + provider + ' was called exactly once, in an EMPTY scratch directory that is not the project', len(mine) == 1 and mine[0]['listing'] == [] and Path(mine[0]['cwd']).resolve() != root.resolve(), mine)
    check('E2 ' + provider + ' got the diff and a read-only command shape (no write or trust-all flag)',
          '+two' in mine[0]['stdin'] + ' '.join(mine[0]['args']) and not [f for f in ('--full-auto', '--dangerously-bypass-approvals-and-sandbox', 'workspace-write', 'danger-full-access', '--yolo', '--trust-all-tools', '--trust-tools=fs_write', '--trust-tools=execute_bash') if f in mine[0]['args']], mine[0]['args'])
    check('E15 ' + provider + ' wrote nothing in the project (same status before and after the review)', git('status', '--porcelain') == status_before, git('status', '--porcelain'))
codex_args = [c for c in calls() if c['provider'] == 'codex'][0]['args']
kiro_args = [c for c in calls() if c['provider'] == 'kiro'][0]['args']
check('E2 codex runs exec in a read-only sandbox and kiro trusts only fs_read', codex_args[:3] == ['exec', '-s', 'read-only'] and [a for a in kiro_args if a.startswith('--trust')] == ['--trust-tools=fs_read'], (codex_args[:4], kiro_args[:5]))
# independence by vendor: refused BEFORE any call
start('Pown', 'kiro', 'claude-sonnet-5.5')
seen = len(calls())
refusal = subprocess.run([exe, '--project', str(root), '--state-root', str(state), 'verdict', 'run', '--plan', 'Pown', '--milestone', 'M1'], capture_output=True, text=True, encoding='utf-8', errors='replace')
check('E4 a kiro reviewer running the author own model is refused and costs no call', refusal.returncode != 0 and 'would be the author' in refusal.stdout and len(calls()) == seen and not events_of('verdict.recorded', 'Pown'), refusal.stdout[-300:])
# a usage limit is inconclusive, with the reason, and no other provider is tried
set_mode('quota')
start('Pquota', 'codex', MODELS['codex'])
seen = len(calls())
cli('verdict', 'run', '--plan', 'Pquota', '--milestone', 'M1')
limited = events_of('verdict.recorded', 'Pquota')[-1]
check('E5/E12 a usage limit is inconclusive with the typed reason and the pinned provider only', limited['result'] == 'inconclusive' and limited['provider_error'] == 'quota_exhausted' and [c['provider'] for c in calls()[seen:]] == ['codex'], (limited, calls()[seen:]))
check('E5 the receipt keeps the provider error text for the report', 'usage limit' in blob(limited['receipt'])['error'], blob(limited['receipt']).get('error'))
'''
sc.register('RP', 'rp-reviewer-local-fake-cli',
            ['W43 LOCAL adapter check (real cells are W45): reviewer through codex and kiro CLIs (env ONECREW_*_CLI) and claude (reviewer.cli_argv) from the installed build',
             'receipt carries provider+model+role; the CLI ran once in an empty scratch dir; read-only argv; nothing written in the project; same-model reviewer refused before a call; quota is inconclusive and never switches'],
            [], RP_REVIEWER, no_new_events='W43 pins provider/model in the contract and reuses plan.advised / verdict.recorded (class 0); the real six cells are W45 evidence, not events.')

RP_ADVISOR = RP_COMMON + r'''
from onecrew.v2 import plan
ORIGIN = {'by': 'owner', 'at': '2026-10-19', 'quote': 'Add the sample file and prove it works.'}
DECISION = {'id': 'D1', 'choice': 'Plain text file', 'alternative': 'JSON file', 'cost': 'None'}
def advice_contract(provider, model):
    value = contract()
    value['origin'] = dict(ORIGIN)
    value['items'] = [dict(i, source='origin') for i in value['items']]
    value['decisions'] = [DECISION]
    value['advisor'] = {'provider': provider, 'model': model}
    return value
cli('plan', 'rules', 'init')
reply(json.dumps({'answers': [{'id': 'Q' + str(n), 'verdict': 'ok', 'note': 'fine'} for n in (1, 2, 3)]}))
for provider in ('codex', 'kiro'):
    name = 'A' + provider
    plan.propose(ledger, name, advice_contract(provider, ADVISOR_MODELS[provider]), 'claude-fable-5-1')
    seen = len(calls())
    cli('plan', 'advise', name)                                        # no flag: the contract advisor decides
    advice = events_of('plan.advised', name)[-1]
    receipt = blob(advice['receipt'])
    check('E19/E3 ' + provider + ' advisor answered through its CLI: usable, no provider error, receipt names provider, model and role',
          (advice['provider'], advice['model'], advice['usable'], advice['provider_error']) == (provider, ADVISOR_MODELS[provider], True, None) and
          (receipt['provider'], receipt['model'], receipt['role'], receipt['calls']) == (provider, ADVISOR_MODELS[provider], 'advisor', 1), (advice, receipt))
    mine = calls()[seen:]
    check('E2 the ' + provider + ' advisor ran once in an empty scratch directory outside the project', len(mine) == 1 and mine[0]['listing'] == [] and Path(mine[0]['cwd']).resolve() != root.resolve(), mine)
check('E15 the advisors wrote nothing in the project', git('status', '--porcelain').strip() == '')
plan.propose(ledger, 'Aown', advice_contract('kiro', 'claude-fable-5-1'), 'claude-fable-5-1')
seen = len(calls())
refused = subprocess.run([exe, '--project', str(root), '--state-root', str(state), 'plan', 'advise', 'Aown'], capture_output=True, text=True, encoding='utf-8', errors='replace')
check('E4 an advisor that is the author own model is refused with no call and no advice event', refused.returncode != 0 and len(calls()) == seen and not events_of('plan.advised', 'Aown'), refused.stdout[-300:])
set_mode('quota')
plan.propose(ledger, 'Aquota', advice_contract('codex', ADVISOR_MODELS['codex']), 'claude-fable-5-1')
seen = len(calls())
cli('plan', 'advise', 'Aquota')
limited = events_of('plan.advised', 'Aquota')[-1]
check('E5/E12 an advisor usage limit is typed, reported, usable=False, and no other provider is tried', limited['provider_error'] == 'quota_exhausted' and limited['usable'] is False and [c['provider'] for c in calls()[seen:]] == ['codex'], (limited, calls()[seen:]))
'''
sc.register('RP', 'rp-advisor-local-fake-cli',
            ['W43 LOCAL adapter check (real cells are W45): advisor through codex and kiro CLIs via the contract advisor field, plan advise from the installed CLI',
             'receipt carries provider+model+role; empty scratch dir; nothing written; the author own model is refused before a call; a usage limit is typed and never switches provider'],
            [], RP_ADVISOR, no_new_events='W43 pins provider/model in the contract and reuses plan.advised / verdict.recorded (class 0); the real six cells are W45 evidence, not events.')

# =============================================================== RX1 ===============================================================
RX1_PROBE = r'''
from onecrew.v2 import plan, verdict, compat
from onecrew.v2.verifiers import port
PY = sys.executable
(root.parent / 'outside.txt').write_text('secret', encoding='utf-8')
class Probe:
    """Test-only adapter (copied from tests/test_wf_rx1_core.py): it tries the forbidden acts, in order, and the core must refuse each."""
    NAME = 'probe'
    outcomes = []
    OPS = {
        'retry': lambda p: p.retry('flaky source'),
        'close_finding': lambda p: p.close_finding('F1', evidence='trust me'),
        'accept': lambda p: p.set_status('accepted'),
        'spend': lambda p: p.spend(1),
        'read_outside': lambda p: p.read_text('../outside.txt'),
        'command_string': lambda p: p.run_command('echo hi'),
        'command_allowed': lambda p: p.run_command([PY, '-c', 'print("allowed")']),
        'write': lambda p: (Path(p.workspace) / 'planted.md').write_text('planted', encoding='utf-8'),
    }
    @staticmethod
    def validate_config(config, label):
        if set(config) - {'attempt', 'catch', 'report'}: raise LedgerError(label + ': probe takes attempt, catch and report.')
        return {'attempt': list(config.get('attempt', [])), 'catch': bool(config.get('catch', True)), 'report': config.get('report', 'honest')}
    @staticmethod
    def run(config, p):
        Probe.outcomes = []
        for op in config['attempt']:
            try:
                Probe.OPS[op](p); Probe.outcomes.append((op, 'allowed'))
            except port.AdapterViolation as error:
                Probe.outcomes.append((op, str(error)))
                if not config['catch']: raise
        report = {'checks': [{'id': 'probe', 'ok': True, 'checked': 1, 'problems': []}], 'findings': [{'id': 'F1', 'text': 'one open finding'}]}
        if config['report'] == 'forged_status': report['status'] = 'accepted'
        if config['report'] == 'closed_finding': report['findings'][0]['status'] = 'closed'
        return report
port.register(Probe)
def run_probe(name, attempt, authority=None, catch=True, report='honest'):
    raw = contract()
    config = {'attempt': attempt, 'catch': catch, 'report': report}
    if authority is not None: config['authority'] = authority
    raw['milestones'] = [{'id': 'M1', 'title': 'Probe M1', 'verifier': {'type': 'probe', 'config': config}, 'covers': ['O1']}]
    plan.propose(ledger, name, raw, 'claude')
    plan.approve(ledger, name, 'owner', 'fixture approval on a temporary ledger')
    view = verdict.run(ledger, name, 'M1', root)
    receipt = json.loads(Snapshots(ledger.state_root).read_blob(view['milestones'][0]['last_verdict']['receipt']).decode('utf-8'))
    return view, receipt
def kinds_and_payloads(name):
    with ledger.transaction() as conn:
        task = plan.anchor_events(ledger, conn, name)['task_id']
    return [(e['kind'], e['payload']) for e in ledger.events(task)]
view, receipt = run_probe('P1', ['retry', 'retry', 'close_finding', 'accept', 'spend', 'spend'], authority={'retries': 1, 'calls': 1})
outcomes = Probe.outcomes
check('T23 the grant is honoured and nothing more: the first retry and the first spend pass, the other four acts are refused',
      [text == 'allowed' for _, text in outcomes] == [True, False, False, False, True, False], outcomes)
check('T23 each refusal names the core own rule', 'retry policy' in outcomes[1][1] and 'a finding is closed by the core on a receipt' in outcomes[2][1] and 'owner acceptance verb' in outcomes[3][1] and 'reservation' in outcomes[5][1], outcomes)
found = [p for k, p in kinds_and_payloads('P1') if k == 'adapter.violation']
check('T23 each refusal is one adapter.violation event naming the adapter, the act, the rule, the plan, the milestone and the receipt',
      [(v['adapter'], v['op']) for v in found] == [('probe', 'retry'), ('probe', 'close_finding'), ('probe', 'set_status'), ('probe', 'spend')] and all(v['rule'] and v['plan'] == 'P1' and v['milestone'] == 'M1' and v['revision'] == 1 and v['receipt'] for v in found), found)
check('T23 none of the four took effect: one retry, one call, the finding still open, no acceptance, no pass',
      receipt['retries_used'] == 1 and receipt['calls'] == 1 and [f['status'] for f in receipt['findings']] == ['open'] and plan.show(ledger, 'P1')['status'] != 'accepted'
      and 'plan.accepted' not in [k for k, _ in kinds_and_payloads('P1')] and 'milestone.passed' not in [k for k, _ in kinds_and_payloads('P1')], receipt)
recorded = [p for k, p in kinds_and_payloads('P1') if k == 'verdict.recorded'][-1]
check('an adapter that overstepped has no pass even though every check is ok', all(c['ok'] for c in receipt['checks']) and port.expected_result(receipt) == 'inconclusive' and recorded['result'] == 'inconclusive' and view['milestones'][0]['state'] == 'failed', recorded)
check('adapter.violation is a class A event the old version ignores', compat.event_class('adapter.violation') == 'A')
view2, receipt2 = run_probe('P2', ['retry', 'spend', 'command_allowed'], authority={'retries': 1, 'calls': 1, 'commands': [[PY, '-c', 'print("allowed")']]})
check('counter-example: an adapter that stays inside its grant passes and writes no violation', view2['milestones'][0]['state'] == 'passed' and receipt2['violations'] == [] and
      not [1 for k, _ in kinds_and_payloads('P2') if k == 'adapter.violation'] and Probe.outcomes == [('retry', 'allowed'), ('spend', 'allowed'), ('command_allowed', 'allowed')], Probe.outcomes)
view3, receipt3 = run_probe('P3', [], report='closed_finding')
check('the adapter cannot close a finding by reporting it closed: the core keeps it open and records a report violation', [f['status'] for f in receipt3['findings']] == ['open'] and [v['op'] for v in receipt3['violations']] == ['report'] and view3['milestones'][0]['state'] == 'failed')
view4, receipt4 = run_probe('P4', [], report='forged_status')
check('the adapter cannot claim a status in its report', [v['op'] for v in receipt4['violations']] == ['report'] and plan.show(ledger, 'P4')['status'] != 'accepted' and view4['milestones'][0]['state'] == 'failed')
view5, receipt5 = run_probe('P5', ['read_outside', 'command_string'], authority={'commands': [[PY, '-c', 'print("other")']]})
check('reads outside the project and a string command are refused by rule', [v['rule'] for v in receipt5['violations']] == ['read_scope', 'command_authority'], receipt5['violations'])
view6, receipt6 = run_probe('P6', ['write'])
check('a write the adapter makes itself is detected in its scratch checkout and never reaches the project', [v['op'] for v in receipt6['violations']] == ['write'] and 'planted.md' in receipt6['violations'][0]['detail'] and not (root / 'planted.md').exists())
check('the surface offered to an adapter is exactly the declared one, with no ledger access', {n for n in dir(port.Port) if not n.startswith('_')} == {'read_text', 'exists', 'files', 'run_command', 'retry', 'spend', 'close_finding', 'set_status', 'workspace', 'authority', 'adapter'})
class Impostor:
    NAME = 'command'
    validate_config = staticmethod(lambda config, label: config)
    run = staticmethod(lambda config, p: {})
try:
    port.register(Impostor); impostor_refused = False
except LedgerError:
    impostor_refused = True
check('an adapter cannot take the name of a core verifier', impostor_refused)
'''
sc.register('RX1', 'rx1-core-refuses-adapter-oversteps',
            ['W22 T23 the installed core refuses an adapter that retries, closes a finding, accepts, spends beyond its grant, reads outside the project, runs ungranted commands, writes or forges its report',
             'each refusal is one adapter.violation (class A) with adapter, act, rule and receipt; an overstepping run is inconclusive; an adapter inside its grant passes'],
            ['adapter.violation'], RX1_PROBE.replace('from onecrew.v2 import plan, verdict, compat', 'from onecrew.snapshots import Snapshots\nfrom onecrew.ledger import LedgerError\nfrom onecrew.v2 import plan, verdict, compat'))


def _doc_fixture_files():
    """The sample documents of tests/wf_rx1_fixture, as text (embedded as literals in the scenario body)."""
    from pathlib import Path
    base = Path(__file__).resolve().parent / 'wf_rx1_fixture'
    return {p.relative_to(base).as_posix(): p.read_text(encoding='utf-8') for p in sorted(base.rglob('*')) if p.is_file()}


RX1_DOC = r'''
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan, verdict
from onecrew.v2.verifiers import doc, port, artifact
FILES = __FILES__
for rel, text in FILES.items():
    target = root / rel; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline=chr(10))
git('add', '.'); git('commit', '-qm', 'documents')
GOOD = {'docs': [{'path': 'docs/guide.md', 'headings': ['Tổng quan', 'Cài đặt', 'Nguồn'], 'tables': [{'under': 'Cài đặt', 'columns': ['Bước', 'Lệnh']}],
                  'sources': {'section': 'Nguồn', 'min': 1, 'cite': 'S\\d+', 'external': 'unverified'}},
                 {'path': 'docs/design.md', 'headings': ['Kiến trúc']}],
        'links': True, 'ids': [{'name': 'REQ', 'pattern': 'REQ-\\d+', 'defined_in': ['docs/design.md']}]}
def doc_contract(config):
    raw = contract()
    raw['milestones'] = [{'id': 'M1', 'title': 'Document M1', 'verifier': {'type': 'doc', 'config': config}, 'covers': ['O1'], 'max_repairs': 2}]
    return raw
def write_contract(name, raw):
    target = Path(state).parent / (name + '.json'); target.write_text(json.dumps(raw), encoding='utf-8'); return str(target)
# propose-time refusals come from the installed lint, not from a late run
bad = dict(GOOD, extra=1)
refused = cli('plan', 'lint', '--file', write_contract('bad-key', doc_contract(bad)), expect=1)
check('the doc adapter refuses an unknown key before any run (installed lint, exit 1)', 'schema' in refused, refused)
refused = cli('plan', 'lint', '--file', write_contract('bad-path', doc_contract(dict(GOOD, docs=['../x.md']))), expect=1)
check('a document path that leaves the project is refused at propose time', 'schema' in refused, refused)
refused = cli('plan', 'lint', '--file', write_contract('bad-authority', doc_contract(dict(GOOD, authority={'retries': 9}))), expect=1)
check('the authority of an adapter is bounded by the core: retries over the cap are refused', 'schema' in refused, refused)
cli('plan', 'lint', '--file', write_contract('good', doc_contract(GOOD)))
cli('plan', 'propose', 'P1', '--file', write_contract('good', doc_contract(GOOD)), '--author', 'claude')
cli('plan', 'approve', 'P1', '--by', 'owner', '--reference', 'fixture approval on a temporary ledger')
def receipt_of(view):
    return json.loads(Snapshots(ledger.state_root).read_blob(view['milestones'][0]['last_verdict']['receipt']).decode('utf-8'))
def kinds_now():
    with ledger.transaction() as conn:
        task = plan.anchor_events(ledger, conn, 'P1')['task_id']
    return [e['kind'] for e in ledger.events(task)]
view = json.loads(cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1'))
receipt = receipt_of(view)
check('RX1 a clean document root passes through the same core, with a doc receipt the core issued',
      view['milestones'][0]['state'] == 'passed' and view['milestones'][0]['last_verdict']['by'] == 'doc' and (receipt['kind'], receipt['adapter'], receipt['violations']) == ('doc-receipt', 'doc', []), view['milestones'][0])
check('every doc check ran and examined something', [c['id'] for c in receipt['checks']] == ['documents', 'structure', 'sources', 'links', 'ids'] and all(c['checked'] > 0 and c['ok'] for c in receipt['checks']), receipt['checks'])
check('the receipt is bound to the artifact and was issued before it was recorded', receipt['artifact_sha'] == artifact.identity(root) and kinds_now().index('verdict.receipt_issued') < kinds_now().index('verdict.recorded') and 'adapter.violation' not in kinds_now())
guide = root / 'docs' / 'guide.md'
guide.write_text(guide.read_text(encoding='utf-8').replace('(design.md#kiến-trúc)', '(thiet-ke.md#kiến-trúc)'), encoding='utf-8', newline=chr(10))
git('commit', '-qam', 'break a link')
failed = json.loads(cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1'))
row = failed['milestones'][0]
bad_receipt = receipt_of(failed)
check('a broken link fails exactly the links check and leaves repairs', row['state'] == 'failed' and row['repairs_left'] == 1 and [c['id'] for c in bad_receipt['checks'] if not c['ok']] == ['links'], row)
check('the adapter finding is open and names the broken target; only the core can close it', bad_receipt['findings'][0]['status'] == 'open' and 'thiet-ke.md' in bad_receipt['findings'][0]['text'])
guide.write_text(guide.read_text(encoding='utf-8').replace('(thiet-ke.md#kiến-trúc)', '(design.md#kiến-trúc)'), encoding='utf-8', newline=chr(10))
git('commit', '-qam', 'repair the link')
passed = json.loads(cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1'))
check('the repaired document passes the same milestone', passed['milestones'][0]['state'] == 'passed')
(root / 'sources' / 'notes.txt').unlink(); git('commit', '-qam', 'drop a cited source')
lost = json.loads(cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1'))
lost_receipt = receipt_of(lost)
check('a cited source that no longer exists is found by the sources check and only by it', lost['milestones'][0]['state'] == 'failed' and [c['id'] for c in lost_receipt['checks'] if not c['ok']] == ['sources'] and any('S2' in p and 'sources/notes.txt' in p for c in lost_receipt['checks'] for p in c['problems']), lost_receipt['checks'])
(root / 'sources' / 'notes.txt').write_text(FILES['sources/notes.txt'], encoding='utf-8', newline=chr(10)); git('add', '.'); git('commit', '-qm', 'restore the source')
final = json.loads(cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1'))
check('after the restore the document passes again', final['milestones'][0]['state'] == 'passed')
accepted = json.loads(cli('plan', 'accept', 'P1', '--by', 'owner', '--reference', 'document root accepted on a temporary ledger', '--artifact-sha', json.loads(cli('verdict', 'artifact', '--plan', 'P1'))['artifact_sha']))
check('the owner accepts the document root with the same verb as a code root', accepted['status'] == 'accepted' and 'plan.accepted' in kinds_now())
check('no adapter.violation was written by the honest doc adapter in the whole lifecycle', 'adapter.violation' not in kinds_now())
'''
sc.register('RX1', 'rx1-doc-root-end-to-end',
            ['W22 T14a a document root runs the real doc adapter through the installed CLI: lint refusals, pass, link failure with an open finding, repair, missing source, restore, owner acceptance',
             'the doc adapter oversteps nothing: no adapter.violation in the lifecycle'],
            ['milestone.failed', 'milestone.passed'], RX1_DOC.replace('__FILES__', repr(_doc_fixture_files())))

# =============================================================== RX2 ===============================================================
# Fixture literals copied from tests/test_wf_rx2_adapters.py / tests/wf_installed_adapters.py (fake data only).
RX2_COMMON = r'''
import hashlib
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan
NL = chr(10)
TABLE = 'id,amount,active' + NL + '1,0.1,true' + NL + '2,0.2,false' + NL
REQUEST = hashlib.sha256(b'update cache to version 2').hexdigest()
DATA = {'path': 'output.csv', 'columns': {'id': 'integer', 'amount': 'number', 'active': 'boolean'}, 'key': ['id'], 'row_count': 2,
        'reconcile': {'path': 'input.csv', 'compare': ['amount', 'active'], 'totals': ['amount']},
        'samples': [{'key': {'id': 2}, 'values': {'amount': 0.2, 'active': False}}]}
OPS = {'pre': 'pre.json', 'post': 'post.json', 'receipt': 'operation.json', 'reconcile': 'observation.json', 'operation_id': 'op-1', 'request_sha': REQUEST,
       'preconditions': [{'path': ['version'], 'equals': 1}], 'postconditions': [{'path': ['version'], 'equals': 2}]}
def write_ops(**receipt_changes):
    def save(name, value):
        raw = json.dumps(value, sort_keys=True).encode()
        (root / name).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()
    before = save('pre.json', {'version': 1})
    after = save('post.json', {'version': 2})
    receipt = {'operation_id': 'op-1', 'request_sha': REQUEST, 'status': 'succeeded', 'pre_sha': before, 'post_sha': after}
    receipt.update(receipt_changes)
    issued = save('operation.json', receipt)
    save('observation.json', {'operation_id': 'op-1', 'request_sha': REQUEST, 'status': 'succeeded', 'observation_id': 'observation-2', 'receipt_sha': issued, 'post_sha': after})
PLAN = ['P1']
def propose_root(kind, config, owned, name=None):
    PLAN[0] = name or 'P1'
    raw = contract()
    raw['scope'] = {'owned': owned}
    raw['understanding']['target']['paths'] = owned
    raw['preconditions'][0]['args']['path'] = owned[0]
    raw['milestones'] = [{'id': 'M1', 'title': 'Check output', 'max_repairs': 5, 'verifier': {'type': kind, 'config': config}, 'covers': ['O1']}]
    target = Path(state).parent / (kind + '-' + PLAN[0] + '-contract.json'); target.write_text(json.dumps(raw), encoding='utf-8')
    cli('plan', 'propose', PLAN[0], '--file', str(target), '--author', 'codex', '--workflow', '--capability', 'namespaced-storage', '--capability', 'finding-register')
    cli('plan', 'approve', PLAN[0], '--by', 'owner', '--reference', 'fixture approval on a temporary ledger')
def run_milestone():
    view = json.loads(cli('verdict', 'run', '--plan', PLAN[0], '--milestone', 'M1'))
    key = view['milestones'][0]['last_verdict']['receipt']
    return view['milestones'][0], json.loads(Snapshots(ledger.state_root).read_blob(key).decode('utf-8'))
def failing(receipt):
    return sorted(c['id'] for c in receipt['checks'] if not c['ok'])
def root_kinds():
    with ledger.transaction() as conn:
        task = plan.anchor_events(ledger, conn, PLAN[0])['task_id']
    return [e['kind'] for e in ledger.events(task)]
def commit(message):
    git('add', '.'); git('commit', '-qm', message)
'''

RX2_DATA = RX2_COMMON + r'''
for name in ('input.csv', 'output.csv'): (root / name).write_text(TABLE, encoding='utf-8', newline=NL)
commit('data fixture')
propose_root('data', DATA, ['output.csv'])
row, receipt = run_milestone()
check('RX2 a data root passes end to end from the installed build, by the data adapter, with the four checks',
      row['state'] == 'passed' and row['last_verdict']['by'] == 'data' and [c['id'] for c in receipt['checks']] == ['schema', 'row_count', 'reconcile', 'samples'] and not failing(receipt) and receipt['violations'] == [], row)
check('the pass is bound to the project tree and carries no model call', receipt['artifact_sha'] == receipt['artifact_sha_after'] and receipt['calls'] == 0 and receipt['retries_used'] == 0)
variants = (('a different column name', TABLE.replace('id,amount,active', 'id,other,active'), 'schema'),
            ('a duplicate key', TABLE.replace('2,0.2,false', '1,0.2,false'), 'schema'),
            ('a value that is not a number', TABLE.replace('2,0.2,false', '2,nan,false'), 'schema'),
            ('an amount that no longer reconciles with the input', TABLE.replace('2,0.2,false', '2,0.3,false'), 'reconcile'),
            ('a missing row', TABLE.replace('2,0.2,false' + NL, ''), 'reconcile'))
for label, text, expected in variants:
    (root / 'output.csv').write_text(text, encoding='utf-8', newline=NL); commit(label)
    row, receipt = run_milestone()
    check('RX2 data: ' + label + ' fails the ' + expected + ' check, with an open finding, and is not a pass', row['state'] == 'failed' and expected in failing(receipt) and receipt['findings'] and all(f['status'] == 'open' for f in receipt['findings']), (row['state'], failing(receipt)))
(root / 'output.csv').write_text(TABLE, encoding='utf-8', newline=NL); commit('repair the data')
row, receipt = run_milestone()
check('RX2 data: the repaired file passes again through the same core', row['state'] == 'passed' and not failing(receipt))
bad_contract = Path(state).parent / 'data-bad.json'
raw = contract(); raw['milestones'] = [{'id': 'M1', 'title': 'Check output', 'verifier': {'type': 'data', 'config': dict(DATA, path='../outside.csv')}, 'covers': ['O1']}]
bad_contract.write_text(json.dumps(raw), encoding='utf-8')
refused = cli('plan', 'lint', '--file', str(bad_contract), expect=1)
check('RX2 data: a path outside the project is refused at lint (fail closed, before any run)', 'schema' in refused, refused)
tree = json.loads(cli('verdict', 'artifact', '--plan', 'P1'))['artifact_sha']
blocked = cli('plan', 'accept', 'P1', '--by', 'owner', '--reference', 'data root accepted on a temporary ledger', '--artifact-sha', tree, expect=2)
check('RX2 data: a green check never closes the adapter findings by itself: acceptance is refused while they are open', 'unresolved findings' in blocked, blocked)
final_receipt = row['last_verdict']['receipt']
open_ids = [f['id'] for f in json.loads(cli('findings', 'list', 'P1', '--open-only'))]
closed = [json.loads(cli('findings', 'resolve', 'P1', ident, '--receipt', final_receipt, '--reason', 'the repaired file passes this check', '--artifact-sha', tree))['closed'] for ident in open_ids]
check('RX2 data: only an explicit receipt-based resolution closes each finding', open_ids and all(len(c) == 1 for c in closed) and json.loads(cli('findings', 'list', 'P1', '--open-only')) == [], (open_ids, closed))
accepted = json.loads(cli('plan', 'accept', 'P1', '--by', 'owner', '--reference', 'data root accepted on a temporary ledger', '--artifact-sha', tree))
ks = root_kinds()
check('RX2 data: the owner then accepts with the same verb; the lifecycle is the common one (failed x5, passed, accepted)', accepted['status'] == 'accepted' and ks.count('milestone.failed') == 5 and 'milestone.passed' in ks and 'adapter.violation' not in ks, ks)
'''
sc.register('RX2', 'rx2-data-root-end-to-end',
            ['W39 T14b a data root (CSV schema, key, row count, reconcile, samples) passes, fails per defect with an open finding, repairs and is accepted from the installed build',
             'a path outside the project is refused before any run'],
            [], RX2_DATA, no_new_events='W39 data/ops adapters reuse the verdict lifecycle (verdict.receipt_issued / verdict.recorded / milestone.*) and add no kind.')

RX2_OPS = RX2_COMMON + r'''
write_ops()
(root / 'a.txt').write_text('one' + NL)
commit('ops fixture')
propose_root('ops', OPS, ['operation.json', 'post.json'])
row, receipt = run_milestone()
check('RX2 an ops root passes end to end from the installed build when the receipt, the pre/post states and the reconcile observation agree',
      row['state'] == 'passed' and row['last_verdict']['by'] == 'ops' and not failing(receipt) and receipt['violations'] == [], (row, failing(receipt)))
check('RX2 ops: checking real local evidence makes no call and no retry', receipt['calls'] == 0 and receipt['retries_used'] == 0 and receipt['artifact_sha'] == receipt['artifact_sha_after'])
ids = [c['id'] for c in receipt['checks']]
check('RX2 ops: the receipt, precondition, postcondition and reconcile checks all ran', {'receipt', 'preconditions', 'postconditions', 'reconcile'} <= set(ids), ids)
for field, value in (('status', 'failed'), ('request_sha', 'f' * 64)):
    write_ops(**{field: value}); commit('receipt ' + field)
    row, receipt = run_milestone()
    check('RX2 ops: a receipt with a wrong ' + field + ' fails the receipt check', row['state'] == 'failed' and 'receipt' in failing(receipt), (row['state'], failing(receipt)))
for name, changes, expected in (('pre.json', {'version': 0}, 'preconditions'), ('post.json', {'version': True}, 'postconditions'), ('observation.json', {'receipt_sha': 'f' * 64}, 'reconcile')):
    write_ops()
    target = root / name
    value = json.loads(target.read_text()); value.update(changes); target.write_text(json.dumps(value), encoding='utf-8')
    commit('tamper ' + name)
    row, receipt = run_milestone()
    check('RX2 ops: tampering with ' + name + ' fails the ' + expected + ' check and is not a pass', row['state'] == 'failed' and expected in failing(receipt), (row['state'], failing(receipt)))
write_ops(status='unknown'); commit('operation of unknown outcome')
propose_root('ops', OPS, ['operation.json', 'post.json'], name='P2')
row, receipt = run_milestone()
check('RX2 ops: an operation of unknown outcome is never a pass and never retried: inconclusive, reconcile first, zero calls',
      row['last_verdict']['result'] == 'inconclusive' and 'reconcile before any retry' in (receipt['error'] or '') and (receipt['retries_used'], receipt['calls']) == (0, 0), (row['last_verdict'], receipt['error']))
write_ops(); commit('restore the evidence')
row, receipt = run_milestone()
check('RX2 ops: the restored evidence passes again', row['state'] == 'passed' and not failing(receipt))
p2_kinds = root_kinds(); PLAN[0] = 'P1'; p1_kinds = root_kinds()
check('RX2 ops: no adapter oversteps in the whole lifecycle of either root, and the first root failed exactly five times', 'adapter.violation' not in p1_kinds + p2_kinds and p1_kinds.count('milestone.failed') == 5, (p1_kinds, p2_kinds))
'''
sc.register('RX2', 'rx2-ops-root-end-to-end',
            ['W39 T14b an ops root passes with agreeing receipt, pre/post states and reconcile observation; each tampering fails its own check; an unknown-outcome operation is inconclusive and not retried',
             'no adapter violation across the lifecycle'],
            [], RX2_OPS, no_new_events='W39 data/ops adapters reuse the verdict lifecycle (verdict.receipt_issued / verdict.recorded / milestone.*) and add no kind.')
