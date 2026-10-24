"""RX1 core tests: T14a (code root and document root go through the same core) and T23 (the core refuses an adapter that oversteps).

T14a: the document root is run with the REAL `doc` adapter; the repair is done by a fake worker (the test edits and commits). It proves the
      interface and the sameness of the core path, not that a worker can write good documents. Data and operations roots are RX2 (T14b).
T23 : the adapter is a FAKE probe that tries the four forbidden acts of the testcase (a)-(d) and a few more. It proves the contract between
      core and adapter (what the core refuses, what it writes, what stays unchanged), not that a real adapter does its job (T14a does that).
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import compat, contract as contracts, plan as plans, report, verdict
from onecrew.v2.verifiers import command, port

from tests import test_v2_l1 as l1
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_rx1_doc import SAMPLE, doc_milestone

PY = sys.executable
REPO = Path(__file__).resolve().parents[1]
CORE = ('verdict', 'contract', 'plan', 'gate', 'step0', 'report', 'cli', 'plan_cli', 'compat', 'lint', 'hook_cli', 'active_plan', 'items', 'ownership',
        'where', 'decisions', 'messages', 'owner_cli', 'install', 'boundary', 'compat_scan', 'compat_cli')


# ---- T23: a fake adapter that oversteps ----------------------------------------------------------------------------------

class Probe:
    """Test-only adapter. `attempt` lists what it tries, in order; every refusal is caught (unless `catch` is false) so that it can try the next."""
    NAME = 'probe'
    outcomes = []

    OPS = {
        'retry': lambda p: p.retry('flaky source'),
        'close_finding': lambda p: p.close_finding('F1', evidence='trust me'),
        'accept': lambda p: p.set_status('accepted'),
        'spend': lambda p: p.spend(1),
        'read_outside': lambda p: p.read_text('../outside.txt'),
        'read_absolute': lambda p: p.read_text(str(Path(sys.executable))),
        'command_denied': lambda p: p.run_command([PY, '-c', 'print(1)']),
        'command_string': lambda p: p.run_command('echo hi'),
        'command_allowed': lambda p: p.run_command([PY, '-c', 'print("allowed")']),
        'write': lambda p: (Path(p.workspace) / 'docs' / 'planted.md').write_text('planted', encoding='utf-8'),
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
                Probe.OPS[op](p)
                Probe.outcomes.append((op, 'allowed'))
            except port.AdapterViolation as error:
                Probe.outcomes.append((op, str(error)))
                if not config['catch']: raise
        report = {'checks': [{'id': 'probe', 'ok': True, 'checked': 1, 'problems': []}], 'findings': [{'id': 'F1', 'text': 'one open finding'}]}
        if config['report'] == 'forged_status': report['status'] = 'accepted'
        if config['report'] == 'forged_result': report['result'] = 'pass'
        if config['report'] == 'closed_finding': report['findings'][0]['status'] = 'closed'
        return report


def probe_milestone(attempt, authority=None, catch=True, report='honest', mid='M1', **extra):
    config = {'attempt': attempt, 'catch': catch, 'report': report}
    if authority is not None: config['authority'] = authority
    return {'id': mid, 'title': 'Probe ' + mid, 'verifier': {'type': 'probe', 'config': config}, 'covers': ['O1'], **extra}


class ProbeFixture(Fixture):
    def setUp(self):
        super().setUp()
        port.register(Probe); self.addCleanup(port.unregister, 'probe')
        shutil.copytree(SAMPLE, self.root, dirs_exist_ok=True)
        self.git('add', '.'); self.git('commit', '-q', '-m', 'documents')
        (self.root.parent / 'outside.txt').write_text('secret', encoding='utf-8')

    def run_probe(self, attempt, **kw):
        self.approved('P1', plan_json(milestones=[probe_milestone(attempt, **kw)]))
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        key = view['milestones'][0]['last_verdict']['receipt']
        return view, json.loads(Snapshots(self.ledger.state_root).read_blob(key).decode('utf-8'))

    def violations(self):
        return [p for k, p in self.events() if k == 'adapter.violation']


class AdapterOverstepTests(ProbeFixture):
    FOUR = ['retry', 'retry', 'close_finding', 'accept', 'spend', 'spend']          # the first retry/spend is inside the grant, the second is not

    def run_four(self):
        return self.run_probe(self.FOUR, authority={'retries': 1, 'calls': 1})

    # [E1] T23: the core refuses all four, naming its own rule
    def test_e1_the_core_refuses_all_four_and_names_the_rule(self):
        self.run_four()
        outcomes = dict(((op, i), text) for i, (op, text) in enumerate(Probe.outcomes))
        self.assertEqual([t == 'allowed' for _, t in Probe.outcomes], [True, False, False, False, True, False])      # grants are honoured, nothing more
        self.assertIn('retry policy', outcomes[('retry', 1)])
        self.assertIn('a finding is closed by the core on a receipt', outcomes[('close_finding', 2)])
        self.assertIn('owner acceptance verb', outcomes[('accept', 3)])
        self.assertIn('reservation', outcomes[('spend', 5)])

    # [E2] T23: each refusal writes one violation naming the adapter and the act
    def test_e2_each_refusal_is_one_violation_record_in_the_ledger(self):
        self.run_four()
        found = self.violations()
        self.assertEqual([(v['adapter'], v['op']) for v in found], [('probe', 'retry'), ('probe', 'close_finding'), ('probe', 'set_status'), ('probe', 'spend')])
        self.assertTrue(all(v['rule'] and v['plan'] == 'P1' and v['milestone'] == 'M1' and v['revision'] == 1 for v in found))
        self.assertEqual(compat.event_class('adapter.violation'), 'A')

    # [E3] T23 forbidden: none of the four succeeds - state after
    def test_e3_the_state_after_shows_none_of_the_four_took_effect(self):
        view, receipt = self.run_four()
        self.assertLessEqual(receipt['retries_used'], 1)                              # <= the policy
        self.assertEqual(receipt['retries_used'], 1)
        self.assertEqual([f['status'] for f in receipt['findings']], ['open'])         # the finding is still open
        self.assertNotEqual(plans.show(self.ledger, 'P1')['status'], 'accepted')
        kinds = self.kinds()
        self.assertNotIn('plan.accepted', kinds)
        self.assertNotIn('milestone.passed', kinds)
        self.assertLessEqual(receipt['calls'], 1)                                      # spent only inside the reservation
        self.assertEqual(receipt['calls'], 1)
        self.assertEqual(view['milestones'][0]['last_verdict']['by'], 'probe')
        self.assertEqual(view['milestones'][0]['state'], 'failed')                    # an adapter that overstepped has no pass
        self.assertEqual(receipt['violations'][0]['adapter'], 'probe')

    def test_a_run_with_a_violation_is_inconclusive_even_when_every_check_is_ok(self):
        view, receipt = self.run_four()
        self.assertTrue(all(c['ok'] for c in receipt['checks']))
        self.assertEqual(port.expected_result(receipt), 'inconclusive')
        last = [p for k, p in self.events() if k == 'verdict.recorded'][-1]
        self.assertEqual(last['result'], 'inconclusive')

    def test_counter_an_adapter_that_stays_inside_its_grant_passes(self):
        view, receipt = self.run_probe(['retry', 'spend', 'command_allowed'], authority={'retries': 1, 'calls': 1, 'commands': [[PY, '-c', 'print("allowed")']]})
        self.assertEqual(view['milestones'][0]['state'], 'passed')
        self.assertEqual((receipt['violations'], receipt['retries_used'], receipt['calls']), ([], 1, 1))
        self.assertEqual(self.violations(), [])
        self.assertEqual(Probe.outcomes, [('retry', 'allowed'), ('spend', 'allowed'), ('command_allowed', 'allowed')])

    def test_without_a_grant_every_retry_and_every_call_is_over_policy(self):
        view, receipt = self.run_probe(['retry', 'spend'])
        self.assertEqual([v['op'] for v in receipt['violations']], ['retry', 'spend'])
        self.assertEqual((receipt['retries_used'], receipt['calls']), (0, 0))

    def test_an_uncaught_refusal_ends_the_adapter_but_the_core_still_records_it(self):
        view, receipt = self.run_probe(['accept'], catch=False)
        self.assertEqual(view['milestones'][0]['state'], 'failed')
        self.assertEqual([v['op'] for v in self.violations()], ['set_status'])
        self.assertEqual(port.expected_result(receipt), 'inconclusive')

    def test_the_adapter_cannot_close_a_finding_by_reporting_it_closed(self):
        view, receipt = self.run_probe([], report='closed_finding')
        self.assertEqual([f['status'] for f in receipt['findings']], ['open'])
        self.assertEqual([v['op'] for v in receipt['violations']], ['report'])
        self.assertEqual(view['milestones'][0]['state'], 'failed')

    def forged(self, report_kind):
        view, receipt = self.run_probe([], report=report_kind)
        self.assertEqual([v['op'] for v in receipt['violations']], ['report'])
        self.assertEqual(view['milestones'][0]['state'], 'failed')
        self.assertNotEqual(plans.show(self.ledger, 'P1')['status'], 'accepted')
        self.assertNotIn('milestone.passed', self.kinds())

    def test_the_adapter_cannot_claim_a_status_in_its_report(self):
        self.forged('forged_status')

    def test_the_adapter_cannot_claim_a_result_in_its_report(self):
        self.forged('forged_result')

    # ---- scope and commands -----------------------------------------------------------------------------------------
    def test_reads_outside_the_project_are_refused_and_recorded(self):
        view, receipt = self.run_probe(['read_outside', 'read_absolute'])
        self.assertEqual([v['rule'] for v in receipt['violations']], ['read_scope', 'read_scope'])
        self.assertTrue(all('outside' in text for _, text in Probe.outcomes))

    def test_a_write_the_adapter_makes_itself_is_detected_and_recorded(self):
        view, receipt = self.run_probe(['write'])
        self.assertEqual([v['op'] for v in receipt['violations']], ['write'])
        self.assertIn('docs/planted.md', receipt['violations'][0]['detail'])
        self.assertEqual(view['milestones'][0]['state'], 'failed')
        self.assertFalse((self.root / 'docs' / 'planted.md').exists())                 # it was a clean scratch checkout, not the project

    def test_a_command_outside_the_granted_list_is_refused_and_a_string_command_never_runs(self):
        view, receipt = self.run_probe(['command_denied', 'command_string'], authority={'commands': [[PY, '-c', 'print("other")']]})
        self.assertEqual([v['rule'] for v in receipt['violations']], ['command_authority', 'command_authority'])
        self.assertEqual(self.violations()[0]['op'], 'run_command')

    def test_a_granted_command_runs_in_the_clean_checkout_with_the_verifier_environment(self):
        class Env:
            @staticmethod
            def seen(p): Env.value = p.run_command([PY, '-c', 'import os; print(os.getcwd()); print(os.environ.get("ONECREW_PROBE_SECRET"))'])
        Probe.OPS['env'] = Env.seen
        self.addCleanup(Probe.OPS.pop, 'env')
        os.environ['ONECREW_PROBE_SECRET'] = 'leak'; self.addCleanup(os.environ.pop, 'ONECREW_PROBE_SECRET')
        view, receipt = self.run_probe(['env'], authority={'commands': [[PY, '-c', 'import os; print(os.getcwd()); print(os.environ.get("ONECREW_PROBE_SECRET"))']]})
        code, out, err = Env.value
        self.assertEqual(code, 0)
        self.assertNotIn('leak', out)
        self.assertNotIn(str(self.root), out)                                          # the checkout, not the live project
        self.assertEqual(receipt['violations'], [])

    def test_the_time_reservation_ends_the_run_as_inconclusive(self):
        ticks = iter([0.0, 10_000.0, 20_000.0, 30_000.0])
        grant = port.authority({'max_minutes': 1}, 'x')
        box = port.Port(self.root, grant, 'probe', clock=lambda: next(ticks))
        with self.assertRaises(port.Timeout): box.read_text('a.txt')
        self.assertIsInstance(port.Timeout('x'), port.Inconclusive)

    def test_the_surface_the_core_offers_an_adapter_is_exactly_this(self):
        names = {n for n in dir(port.Port) if not n.startswith('_')}
        self.assertEqual(names, {'read_text', 'exists', 'files', 'run_command', 'retry', 'spend', 'close_finding', 'set_status', 'workspace', 'authority', 'adapter'})
        box = port.Port(self.root, port.authority(None, 'x'), 'probe')
        self.assertFalse(any(hasattr(box, n) for n in ('ledger', 'emit', 'record', 'accept', 'approve', 'conn')))


# ---- T14a: one core for every output kind -------------------------------------------------------------------------------

GOOD_A = 'ok\n'
BAD_A = 'bad\n'


def code_milestone(mid='M1', **extra):
    check = 'import sys; print("checked a.txt"); sys.exit(0 if "ok" in open("a.txt").read() else 3)'     # a silent success would be "suspicious", so it says something
    return dict({'id': mid, 'title': 'Check ' + mid, 'verifier': {'type': 'command', 'config': {'argv': [PY, '-c', check]}}, 'covers': ['O1']}, **extra)


class OneCoreTests(Fixture):
    """A code root and a document root, each with the same budget, stop limits, attention, scope and output text; only the verifier differs."""

    def setUp(self):
        super().setUp()
        shutil.copytree(SAMPLE, self.root, dirs_exist_ok=True)
        (self.root / 'a.txt').write_text(BAD_A)                                       # the code root starts red ...
        guide = self.root / 'docs' / 'guide.md'
        guide.write_text(guide.read_text(encoding='utf-8').replace('(design.md#kiến-trúc)', '(thiet-ke.md#kiến-trúc)'), encoding='utf-8', newline='\n')   # ... and so does the document
        self.git('add', '.'); self.git('commit', '-q', '-m', 'sample')
        self.names = {'CODE': code_milestone(max_repairs=2), 'DOC': doc_milestone(max_repairs=2)}

    def task_id(self, name):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, name)['task_id']

    def worker_repairs(self):
        """The fake worker: edits both outputs and commits. It proves the interface of the core, not that a worker can do it."""
        (self.root / 'a.txt').write_text(GOOD_A)
        guide = self.root / 'docs' / 'guide.md'
        guide.write_text(guide.read_text(encoding='utf-8').replace('(thiet-ke.md#kiến-trúc)', '(design.md#kiến-trúc)'), encoding='utf-8', newline='\n')
        self.git('commit', '-qam', 'repair')

    def lifecycle(self):
        for name, milestone in self.names.items():
            self.approved(name, plan_json(milestones=[milestone]))
        first = {name: verdict.run(self.ledger, name, 'M1', self.root) for name in self.names}
        self.worker_repairs()
        second = {name: verdict.run(self.ledger, name, 'M1', self.root) for name in self.names}
        accepted = {name: plans.accept(self.ledger, name, 'owner', 'test data: said yes', self.tree()) for name in self.names}
        return first, second, accepted

    # [E1] same lifecycle, authority, budget, finding path, handover
    def test_e1_both_roots_have_the_same_lifecycle_in_the_ledger(self):
        first, second, accepted = self.lifecycle()
        lifecycles = {name: self.kinds(name) for name in self.names}
        self.assertEqual(lifecycles['CODE'], lifecycles['DOC'])
        self.assertIn('milestone.failed', lifecycles['DOC'])
        self.assertIn('milestone.passed', lifecycles['DOC'])
        self.assertEqual([k for k in lifecycles['DOC'] if k != 'learning.outcome'][-1], 'plan.accepted')
        self.assertEqual({n: first[n]['milestones'][0]['state'] for n in self.names}, {'CODE': 'failed', 'DOC': 'failed'})
        self.assertEqual({n: second[n]['milestones'][0]['state'] for n in self.names}, {'CODE': 'passed', 'DOC': 'passed'})
        self.assertEqual({n: accepted[n]['status'] for n in self.names}, {'CODE': 'accepted', 'DOC': 'accepted'})

    def test_e1_the_events_carry_the_same_fields_of_authority_and_budget(self):
        self.lifecycle()
        shapes = {name: {kind: sorted(payload) for kind, payload in self.events(name)} for name in self.names}
        self.assertEqual(shapes['CODE'], shapes['DOC'])
        views = {name: plans.show(self.ledger, name) for name in self.names}
        for field in ('budget', 'stop', 'attention', 'scope'):
            self.assertEqual(views['CODE']['contract'][field], views['DOC']['contract'][field], field)
        self.assertEqual({n: (v['milestones'][0]['max_repairs'], v['milestones'][0]['runs'], v['milestones'][0]['failures']) for n, v in views.items()},
                         {'CODE': (2, 2, 1), 'DOC': (2, 2, 1)})

    def test_e1_the_same_stop_rule_ends_both_roots_the_same_way(self):
        self.names = {'CODE': code_milestone(max_repairs=0), 'DOC': doc_milestone(max_repairs=0)}
        for name, milestone in self.names.items():
            self.approved(name, plan_json(milestones=[milestone]))
        views = {name: verdict.run(self.ledger, name, 'M1', self.root) for name in self.names}
        self.assertEqual({n: v['status'] for n, v in views.items()}, {'CODE': 'stopped_with_report', 'DOC': 'stopped_with_report'})
        self.assertEqual(self.kinds('CODE'), self.kinds('DOC'))
        self.assertEqual({n: len(self.ledger.requests(self.task_id(n))) for n in self.names}, {'CODE': 1, 'DOC': 1})       # one question to the owner each

    def test_e1_the_handover_has_the_same_shape(self):
        self.lifecycle()
        heads = {name: [line for line in report.render_report(self.ledger.state_root, name).splitlines() if line.startswith('#')] for name in self.names}
        self.assertEqual(len(heads['CODE']), len(heads['DOC']))
        self.assertEqual([re.sub(r'(CODE|DOC)', 'X', h) for h in heads['CODE']], [re.sub(r'(CODE|DOC)', 'X', h) for h in heads['DOC']])
        for name in self.names:
            self.assertIn(name, report.render_present(self.ledger.state_root, name))

    # [E2] only the adapter field and its checks differ
    def test_e2_the_two_contracts_differ_only_in_the_verifier(self):
        self.lifecycle()
        views = {name: plans.show(self.ledger, name)['contract'] for name in self.names}
        stripped = {}
        for name, contract in views.items():
            contract = copy.deepcopy(contract)
            contract['milestones'][0].pop('verifier'); contract['milestones'][0].pop('title')
            stripped[name] = contract
        self.assertEqual(stripped['CODE'], stripped['DOC'])
        self.assertEqual({n: c['milestones'][0]['verifier']['type'] for n, c in views.items()}, {'CODE': 'command', 'DOC': 'doc'})

    # ---- [E3] [E7] [E8] reading the core code --------------------------------------------------------------------------
    def core_files(self):
        return {name: (REPO / 'onecrew' / 'v2' / (name + '.py')) for name in CORE} | {'port': REPO / 'onecrew' / 'v2' / 'verifiers' / 'port.py'}

    def test_e3_e8_the_core_has_no_branch_on_the_kind_of_work_or_the_project(self):
        pattern = re.compile(r'''task_type\s*[=!]=|task_type\s+in\b|kind_of_work|work_kind|\b(?:kind|type|adapter|name)\s*(?:==|!=|in)\s*\(?\s*['"]doc['"]|['"]doc['"]\s*(?:==|!=)''')
        hits = {name: [n for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1) if pattern.search(line)] for name, path in self.core_files().items()}
        self.assertEqual({k: v for k, v in hits.items() if v}, {})

    def test_e3_the_name_of_a_shipped_adapter_is_in_the_one_table_and_in_no_condition_of_the_core(self):
        self.assertEqual(port.BUILTIN, ('doc', 'data', 'ops'))
        for adapter in port.BUILTIN:
            quoted = re.compile(rf"""(?i)(verifier|adapter|milestone).*['"]{adapter}['"]|['"]{adapter}['"].*(verifier|adapter|milestone)""")
            found = {name: [line.strip() for line in path.read_text(encoding='utf-8').splitlines() if quoted.search(line)] for name, path in self.core_files().items()}
            self.assertEqual({k: v for k, v in found.items() if v and k != 'port'}, {}, f'the core names the adapter {adapter}')
            self.assertEqual([l for l in found['port'] if 'BUILTIN' not in l and not l.startswith(('"""', '#'))], [], 'port.py names it outside BUILTIN')

    def test_e3_no_project_name_in_the_core(self):
        names = re.compile(r'\b(vimes|vmagent|nursing|leohis)\b', re.I)
        hits = {name: [n for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1) if names.search(line)] for name, path in self.core_files().items()}
        self.assertEqual({k: v for k, v in hits.items() if v}, {})

    def test_e7_nothing_in_the_core_is_called_only_for_the_document_adapter(self):
        users = []
        for path in (REPO / 'onecrew').rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            if re.search(r'verifiers\s+import\s+[^\n]*\bdoc\b|verifiers\.doc\b|import\s+doc\b', text) and path.name != 'doc.py': users.append(path.name)
        self.assertEqual(users, [])                                                  # the loader imports it by the name in the BUILTIN table

    def test_e7_both_roots_ran_through_the_same_functions(self):
        from unittest.mock import patch
        calls = []
        real_record = verdict.record
        def spy_record(*args, **kw):
            calls.append(args[1:3] + (args[4],)); return real_record(*args, **kw)
        with patch.object(verdict, 'record', spy_record):
            self.lifecycle()
        by = {(name, by) for name, _, by in calls}
        self.assertEqual(by, {('CODE', 'command'), ('DOC', 'doc')})


# ---- the old version still reads a root that carries the new class-A event ----------------------------------------------

def _have_git():
    try:
        return subprocess.run(['git', '--version'], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_have_git(), 'git is required to archive the old version')
class OldVersionTests(unittest.TestCase):
    BASELINE = 'ee46539'

    @classmethod
    def setUpClass(cls):
        import tests.wf_oldversion as ov
        cls.ov = ov
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive(cls.BASELINE, str(REPO), cls.runs))
        cls.proj = ov.git_project(cls.runs, 'P1')
        cfile = cls.runs / 'c.json'; cfile.write_text(json.dumps(ov.contract('R0')), encoding='utf-8')
        cls.s0 = cls.runs / 'state0'
        code, out = cls.old.run(cls.proj, cls.s0, 'plan', 'propose', 'r1', '--file', str(cfile), '--author', 'claude-probe')
        assert code == 0, out
        cls.pid = ov.project_id(cls.s0, cls.proj)
        cls.task = ov.anchor_id(cls.s0, cls.pid, 'plan:r1')
        ov.make_approved(cls.s0, cls.task, 'r1')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_adapter_violation_is_class_A_and_the_old_binary_keeps_S_G_C(self):
        ov = self.ov
        base = ov.read(self.old, self.proj, self.s0, 'r1')
        copy_ = self.runs / 'withviolation'
        shutil.copytree(self.s0, copy_)
        task = ov.anchor_id(copy_, self.pid, 'plan:r1')
        payload = {'plan': 'r1', 'revision': 1, 'milestone': 'M1', 'adapter': 'doc', 'op': 'set_status', 'rule': 'accepted_needs_owner_verb',
                   'detail': 'probe', 'receipt': '0' * 64}
        self.assertEqual(compat.event_class('adapter.violation'), 'A')
        ov.insert_event(copy_, task, 'adapter.violation', payload)
        after = ov.read(self.old, self.proj, copy_, 'r1')
        diff = ov.compare(base, after)
        self.assertTrue(diff['S'] and diff['G'] and diff['C'], (base, after))
        self.assertFalse(after['read_blocked'])

    def test_a_root_with_a_doc_milestone_is_read_by_the_old_binary_which_refuses_to_run_it_and_writes_nothing(self):
        """What a rollback would meet: the old binary has no `doc` verifier. It must read the root (S) and refuse the run plainly, not crash and not write."""
        from unittest.mock import patch
        from onecrew.ledger import Ledger
        ov = self.ov
        proj = ov.git_project(self.runs, 'D1')
        shutil.copytree(SAMPLE, proj, dirs_exist_ok=True)
        for args in (['add', '.'], ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'docs']):
            subprocess.run(['git', *args], cwd=proj, check=True, capture_output=True)
        state = self.runs / 'docstate'
        with patch.dict(os.environ):
            for name in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)
            ledger = Ledger(proj, state)
            plans.propose(ledger, 'r1', plan_json(milestones=[doc_milestone()]), 'claude-probe')
            plans.approve(ledger, 'r1', 'owner', 'test data: approved on a scratch ledger')      # test data on a scratch state root
            # Historical legacy root carrying an unsupported verifier. New
            # proposals are namespaced and intentionally invisible to this CLI.
            shutil.copytree(state / 'plans' / ledger.project_id / 'r1', state / 'plans' / 'r1')
            with ledger.transaction(write=True) as conn:
                conn.execute("UPDATE tasks SET request_key='plan:r1' WHERE project_id=? AND request_key='plan-ns:r1'", (ledger.project_id,))
        count = lambda: ov._db(state).execute('SELECT COUNT(*) FROM events').fetchone()[0]
        before = count()
        reading = ov.read(self.old, proj, state, 'r1')
        self.assertEqual((reading['S']['status'], reading['read_blocked']), ('approved', False))
        code, out = self.old.run(proj, state, 'verdict', 'run', '--plan', 'r1', '--milestone', 'M1')
        self.assertEqual(code, 2)
        self.assertIn('is not verified by a command or a reviewer', out)
        self.assertEqual(count(), before)


if __name__ == '__main__':
    unittest.main()
