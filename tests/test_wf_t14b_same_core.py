"""T14b [E5], [E9] (W39): a DATA root and an OPS root go through the same lifecycle, authority, budget, finding register and handover as a
CODE root; only the adapter (verifier type) and its checks differ — nothing in the core branches on the kind of work.

Three roots in one temporary project/ledger: CODE (command verifier), DATA (data verifier on output.csv), OPS (ops verifier on a local
operation receipt). Each is proposed, approved, verified, reported and accepted through the same functions; the lifecycle event sequence,
the authority refusal (an AI session cannot accept), the budget/estimate record and the handover shape are identical. [E9]: a criteria grep
over the core finds no `data`/`ops` special case — the only dispatch by kind is the verifier port registry.
"""
import copy
import os
import re
from pathlib import Path

from onecrew.ledger import LedgerError
from onecrew.v2 import estimates, findings, plan as plans, report, verdict
from tests.test_v2_l1 import Fixture, plan_json, milestone
import tests.test_wf_rx2_adapters as rx2

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ('task.submitted', 'plan.proposed', 'plan.approved', 'verdict.run_started', 'verdict.receipt_issued', 'verdict.recorded',
             'milestone.passed', 'plan.accepted')


class SameCoreTests(Fixture):
    def setUp(self):
        super().setUp()
        for name in ('input.csv', 'output.csv'):
            (self.root / name).write_text(rx2.TABLE, encoding='utf-8')
        rx2.write_ops(self.root)
        self.git('add', '.'); self.git('commit', '-qm', 'data and ops fixtures')
        import sys
        self.kinds_ = {'CODE': milestone('M1', argv=[sys.executable, '-c', 'print("ok")']),
                       'DATA': rx2.milestone('data', copy.deepcopy(rx2.DATA)),
                       'OPS': rx2.milestone('ops', copy.deepcopy(rx2.OPS))}

    def drive(self, name, verifier_milestone):
        value = plan_json(milestones=[verifier_milestone], scope={'owned': ['a.txt', 'output.csv', 'operation.json', 'post.json']})
        plans.propose(self.ledger, name, value, 'codex', workflow=True, capabilities=['namespaced-storage', 'finding-register'])
        plans.approve(self.ledger, name, 'owner', 'fixture', estimate={'execution_seconds': [60, 120], 'evidence': ['fixture decomposition']})
        shown = verdict.run(self.ledger, name, 'M1', self.root)
        self.assertEqual(shown['milestones'][0]['state'], 'passed', (name, shown))
        self.assertEqual(findings.list_findings(self.ledger, name, open_only=True), [])              # the same register, usable
        handover = report.render_handover(self.ledger.state_root, name, project_id=self.ledger.project_id)
        self.assertIn('O1 đạt', handover)
        os.environ['ONECREW_ACTOR'] = 'codex'
        try:
            with self.assertRaises(LedgerError):                                                      # the same authority: no AI acceptance
                plans.accept(self.ledger, name, 'owner', 'ai tries', verdict.artifact(self.ledger, name)['artifact_sha'])
        finally:
            os.environ.pop('ONECREW_ACTOR', None)
        plans.accept(self.ledger, name, 'owner', 'fixture acceptance', verdict.artifact(self.ledger, name)['artifact_sha'])
        self.assertEqual(plans.show(self.ledger, name)['status'], 'accepted')
        kinds = [k for k in self.kinds(name) if k in LIFECYCLE]
        budget = estimates.read(self.ledger, name)
        return kinds, sorted(budget), handover.splitlines()[0].split(':')[0]

    def test_e5_data_and_ops_roots_share_lifecycle_authority_budget_findings_and_handover_with_code(self):
        results = {name: self.drive(name, m) for name, m in self.kinds_.items()}
        code = results['CODE']
        for name in ('DATA', 'OPS'):
            self.assertEqual(results[name][0], code[0], name)                                         # [E5] identical lifecycle
            self.assertEqual(results[name][1], code[1], name)                                         # the same budget/estimate record
            self.assertEqual(results[name][2], code[2], name)                                         # the same handover page
        self.assertEqual(code[0][:3], ['task.submitted', 'plan.proposed', 'plan.approved'])

    SPECIAL = re.compile(r"""(?:==|!=)\s*['"](?:data|ops)['"]|['"](?:data|ops)['"]\s*(?:==|!=)|\bin\s*[\(\[\{][^)\]}]*['"](?:data|ops)['"]""")

    @staticmethod
    def core_modules():
        """W39 / T14b E9: every module of onecrew/v2 (verifiers/ included, except the three shipped adapters that own their kind) and
        onecrew/common_verification.py, enumerated from disk; the former 8-file hand list is a subset."""
        base = ROOT / 'onecrew'
        mods = [p for p in sorted((base / 'v2').rglob('*.py')) if not (p.parent.name == 'verifiers' and p.name in ('data.py', 'ops.py', 'doc.py'))]
        return mods + [base / 'common_verification.py']

    def test_e9_no_data_or_ops_special_case_in_the_core(self):
        mods = self.core_modules()
        rels = {p.relative_to(ROOT).as_posix() for p in mods}
        for must in ('onecrew/v2/plan.py', 'onecrew/v2/verdict.py', 'onecrew/v2/engine.py', 'onecrew/v2/authority.py', 'onecrew/v2/report.py',
                     'onecrew/v2/findings.py', 'onecrew/v2/internal_plan.py', 'onecrew/v2/estimates.py', 'onecrew/v2/namespaces.py',
                     'onecrew/v2/contract.py', 'onecrew/v2/step0.py', 'onecrew/v2/gate.py', 'onecrew/common_verification.py',
                     'onecrew/v2/verifiers/port.py', 'onecrew/v2/verifiers/artifact.py'):
            self.assertIn(must, rels)
        self.assertGreaterEqual(len(rels), 70)
        self.assertNotIn('onecrew/v2/verifiers/data.py', rels)
        hits = {p.relative_to(ROOT).as_posix(): [m.group(0) for m in self.SPECIAL.finditer(p.read_text(encoding='utf-8'))] for p in mods}
        self.assertEqual({k: v for k, v in hits.items() if v}, {}, 'the core must not branch on the kind of work')
        from onecrew.v2.verifiers import port
        self.assertTrue(port.known('data') and port.known('ops'), 'the only dispatch by kind is the verifier port registry')

    def test_e9_counter_example_a_data_or_ops_branch_in_any_scanned_module_is_found(self):
        """W39 / T14b E9 counter-example: one injected `kind == 'data'` / `in ('ops', ...)` line in namespaces.py, step0.py,
        gate.py, contract.py or common_verification.py (modules the old 8-file list omitted) is reported by the same criteria."""
        wanted = {'namespaces.py', 'step0.py', 'gate.py', 'contract.py', 'common_verification.py'}
        checked = 0
        for path in self.core_modules():
            if path.name not in wanted:
                continue
            lines = path.read_text(encoding='utf-8').splitlines()
            self.assertFalse(any(self.SPECIAL.search(line) for line in lines), path.name)
            for injected in ("    if kind == 'data':", "    elif work in ('ops', 'doc'):", "    if 'ops' != item_type:"):
                self.assertTrue(self.SPECIAL.search(injected), injected)
            checked += 1
        self.assertEqual(checked, len(wanted))
