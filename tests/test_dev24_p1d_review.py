"""2.5.0.dev24 — Kiro review of 945afdc (FAIL, 3 P1 + 3 P2 + 1 P3); owner 11/11: "Sửa cả lỗi cũ".
- P1-1, owner 11/11 option A ("ok, làm theo lời khuyên"): the program rule on RECORDED workflow verifications is taken back out of dev24; a
  verified node stays verified after its program's Python packages changed, as in 2.5.0.dev23 (LOI-DA-BIET; a design-first task later). A
  proof that is REUSED is still judged by the rule (proof_mismatch with the project), so a re-check runs the verifier again.
- P1-2: `.`/`..` in an absolute path (on the command line or in an input's text) no longer passes the live-tree checks.
- P1-3: inputs_unscanned cannot exempt what the command line names under another spelling (`tool/./check.py`, case on Windows).
- P2: a relative program with a folder that is not there is refused before the verifier; the tracking page offers owner accept for a plan whose
  milestones declare different inputs (the union tree, as `verdict artifact`); a view polled again does not read unchanged files again.
- P3: the tracking milestone rows show the live view the acceptance card used.
Red on 945afdc (the P1-1 cases now assert the dev23 behaviour, green on both).
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from onecrew.common_verification import CandidateChecker, proof_mismatch
from onecrew.common_handoff import handoff
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, engine, plan as plans, tracking, verdict
from onecrew.v2.verifiers import command
from tests import test_hf_verifier_inputs as mep
from tests.test_dev24_p1_environment import venv
from tests.test_dev24_p1c_review import Base
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_wf_candidate_handoff import CandidateFixture


class WorkflowFixture(CandidateFixture):
    def milestones(self):
        if not hasattr(self, 'exe'):
            self.exe, self.site = venv(Path(self.temp.name) / 've')
        check = [str(self.exe), '-c', 'from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\n"; print("candidate tested")']
        return [milestone(argv=check)]

    def upgrade_a_package(self):
        (self.site / 'pytest_plugin-2.0.dist-info').mkdir(exist_ok=True)
        (self.site / 'pytest_plugin-2.0.dist-info' / 'RECORD').write_text('plugin/__init__.py,,\n')

    def evidence_of(self, nid):
        record = engine.state(self.ledger, 'P1')['nodes'][nid]
        body = json.loads(self.store.read_blob(record['verification_receipt']))
        return [row['evidence'] for row in body['observed']['checks']]


# the fixture's own tests are not run again here
for _name in [n for n in dir(CandidateFixture) if n.startswith('test')]: setattr(WorkflowFixture, _name, None)


class RecordedVerificationAsInDev23(WorkflowFixture):
    # owner 11/11 option A: a recorded verification is trusted as in 2.5.0.dev23 (known issue); these assert that behaviour
    def test_a_verified_node_stays_verified_after_its_program_packages_changed(self):
        self.revise(self.definition()); self.step()
        engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.upgrade_a_package()
        view = engine.state(self.ledger, 'P1')
        self.assertEqual(view['nodes']['C']['state'], 'verified', view['nodes']['C'])
        self.assertFalse(view['nodes']['C'].get('needs_recheck'))
        self.assertEqual(engine.accept_node(self.ledger, 'P1', 'C')['state'], 'accepted')

    def test_a_handoff_stays_idempotent_and_root_ready_after_the_program_changed(self):
        self.revise(self.definition()); self.step()
        engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.step(); engine.verify(self.ledger, 'P1', 'I', self.production_checker)
        result = handoff(self.ledger, 'P1', control=self.control)
        self.upgrade_a_package()
        self.assertTrue(engine.root_ready(self.ledger, 'P1', result['artifact']))
        self.assertIsNotNone(engine.handoff_evidence(self.ledger, 'P1'))
        self.assertTrue(handoff(self.ledger, 'P1', control=self.control)['idempotent'])


class ReusedProofIsJudged(WorkflowFixture):

    def test_proof_mismatch_names_the_program_change_with_the_project(self):
        self.revise(self.definition()); self.step()
        engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        wrapper = json.loads(self.store.read_blob(self.evidence_of('C')[0]))
        proof = json.loads(self.store.read_blob(wrapper['command_receipt']))
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'P1')
        contract, sha = plans.load(self.ledger, state, state['latest'])
        m = contract['milestones'][0]
        args = (wrapper, proof, m, sha, state['latest'], wrapper['tree'])
        self.assertIsNone(proof_mismatch(*args, project=self.ledger.project))
        self.upgrade_a_package()
        self.assertIn('program', proof_mismatch(*args, project=self.ledger.project) or '')


class LiveTreeSpelledWithDots(Base):
    def dotted(self, *tail):
        return os.sep.join([str(self.root.parent), '.', self.root.name, *tail])

    def test_an_absolute_output_path_with_a_dot_segment_is_refused(self):
        with self.assertRaises(LedgerError):
            command.check_argv_scope(self.root, [mep.PY, self.dotted('generated.txt')], self.inputs)
        with self.assertRaises(LedgerError):
            command.check_live_tree_named(self.root, [mep.PY, self.dotted('generated.txt')], self.root / 'tool')

    def test_an_input_that_spells_the_live_tree_with_dot_segments_is_refused(self):
        workspace = Path(self.temp.name) / 'ban-chep'; (workspace / 'spec').mkdir(parents=True)
        for text in (self.dotted('config.txt'), os.sep.join([str(self.root.parent), 'khac', '..', self.root.name, 'config.txt'])):
            with self.subTest(text=text):
                (workspace / 'spec' / 'a.txt').write_text('doc ' + text + '\n')
                with self.assertRaises(LedgerError):
                    command.check_live_tree_named(self.root, [mep.PY, 'x'], workspace)

    def test_an_unrelated_dotted_path_is_not_refused(self):
        workspace = Path(self.temp.name) / 'ban-chep-2'; (workspace / 'spec').mkdir(parents=True)
        (workspace / 'spec' / 'a.txt').write_text('see ' + os.sep.join([str(self.root.parent), '.', self.root.name + '-khac', 'x.txt']) + '\n')
        command.check_live_tree_named(self.root, [mep.PY, 'x'], workspace)


class UnscannedNeverExemptsTheCommandLine(Fixture):
    def contract(self, argv, unscanned):
        m = milestone(argv=argv); m['verifier']['config'].update(inputs=['tool'], inputs_unscanned=unscanned)
        return plan_json(milestones=[m])

    def test_another_spelling_of_the_program_cannot_be_exempted(self):
        spellings = [['python', 'tool/./check.py'], ['python', 'tool/x/../check.py']]
        if os.name == 'nt': spellings.append(['python', 'TOOL/check.py'])
        for argv in spellings:
            with self.subTest(argv=argv), self.assertRaises(LedgerError):
                contracts.validate(self.contract(argv, ['tool/check.py']))

    def test_at_the_run_what_the_command_line_names_is_scanned_anyway(self):
        workspace = Path(self.temp.name) / 'ban-chep'; (workspace / 'tool').mkdir(parents=True)
        (workspace / 'tool' / 'check.py').write_text('open(r"' + str(self.root / 'live.txt') + '")\n')
        with self.assertRaises(LedgerError):
            command.check_live_tree_named(self.root, ['python', 'tool/./check.py'], workspace, ['tool/check.py'])


class RelativeProgramMissing(Base):
    def test_a_relative_program_with_a_folder_that_is_not_there_is_refused_before_the_verifier(self):
        self.plan(argv=['tool/missing-check'])
        for _ in range(2):
            with self.assertRaises(LedgerError) as caught:
                self.run_m1()
            self.assertIs(getattr(caught.exception, 'verifier_started', None), False)
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['runs'], 0)


class Tracking(Base):
    def item(self):
        return tracking.detail(self.ledger.state_root, 'P1')

    def test_milestones_of_different_inputs_are_offered_for_owner_accept_on_the_union(self):
        for name in ('mot', 'hai'): (self.root / name).write_text(name + '\n')
        self.git('add', '-A'); self.git('commit', '-qm', 'hai input')
        m1 = milestone('M1', argv=[mep.PY, '-c', "print('ok')"]); m1['verifier']['config']['inputs'] = ['mot']
        m2 = milestone('M2', argv=[mep.PY, '-c', "print('ok')"]); m2['verifier']['config']['inputs'] = ['hai']
        self.enforce(value=mep.owned_plan(milestones=[m1, m2]))
        verdict.run(self.ledger, 'P1', 'M1'); verdict.run(self.ledger, 'P1', 'M2')
        acceptance = self.item()['acceptance']
        self.assertTrue(acceptance['ready'], acceptance)
        self.assertEqual(acceptance['artifact'], verdict.artifact(self.ledger, 'P1')['artifact_sha'])

    def test_the_rows_show_the_live_view_after_a_package_change(self):
        exe, site = venv(Path(self.temp.name) / 've')
        self.plan(inputs=None, argv=[str(exe), '-c', "print('ok')"])
        self.run_m1()
        self.assertEqual(self.item()['milestones'][0]['state'], 'passed')
        (site / 'plugin-2.0.dist-info').mkdir(); (site / 'plugin-2.0.dist-info' / 'RECORD').write_text('x\n')
        item = self.item()
        self.assertFalse(item['acceptance']['ready'], item['acceptance'])
        row = item['milestones'][0]
        self.assertTrue(row['state'] != 'passed' or row['stale'], row)

    def test_a_second_look_does_not_read_unchanged_files_again(self):
        exe, site = venv(Path(self.temp.name) / 've2')
        (site / 'goi-1.0.dist-info').mkdir(); (site / 'goi-1.0.dist-info' / 'RECORD').write_text('x\n')
        tool = command.tool_identity(str(exe), {})
        body = {'kind': 'command-receipt', 'program': tool, 'cwd': str(self.root)}
        self.assertEqual(command.program_reasons(body, self.root), [])
        real = open
        opened = []
        with patch('builtins.open', side_effect=lambda f, *a, **k: opened.append(str(f)) or real(f, *a, **k)):
            self.assertEqual(command.program_reasons(body, self.root), [])
        self.assertEqual([f for f in opened if not f.endswith('pyvenv.cfg')], [], opened)
