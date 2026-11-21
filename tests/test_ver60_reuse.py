"""VER60 MR, from public run, report and tracking entry points on temporary ledgers."""
import json
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import acceptance_diff, plan as plans, report, tracking, verdict
from onecrew.snapshots import Snapshots
from tests import v2_fixture as fixtures


def scoped(mid, paths, **config):
    result = fixtures.milestone(mid)
    result['verifier']['config'].update(inputs=paths, **config)
    return result


class Reuse(fixtures.Fixture):
    def setUp(self):
        super().setUp()
        (self.root / 'b.txt').write_text('second')
        self.external = Path(self.temp.name) / 'rules.txt'
        self.external.write_text('first')

    def start(self, *, owner_step=False):
        checks = [scoped('M1', ['a.txt'], env_inputs=[str(self.external)]), scoped('M2', ['b.txt'])]
        if owner_step:
            checks.append(fixtures.milestone('MO', verifier={'type': 'owner-manual', 'config': {}}))
        self.approved(value=fixtures.plan_json(checks))
        return self.check('M1')

    def check(self, mid):
        shown = verdict.run(self.ledger, 'P1', mid)
        return next(v for v in shown['milestones'] if v['id'] == mid)

    def views(self):
        return plans.show(self.ledger, 'P1')['milestones']

    def test_other_milestone_file_change_keeps_pass(self):
        first = self.start()
        (self.root / 'b.txt').write_text('another')
        current = self.views()[0]
        self.assertEqual((current['state'], current['last_verdict'], current['runs']), ('passed', first['last_verdict'], 1))
        with self.assertRaisesRegex(LedgerError, 'already passed'):
            self.check('M1')

    def test_env_input_change_makes_stale(self):
        self.start()
        self.external.write_text('changed outside')
        current = self.views()[0]
        self.assertTrue(current['stale'])
        self.assertNotIn('reuse_note', current)
        self.assertIn('env_inputs', ' '.join(current['stale_reasons']))

    def test_kept_pass_labelled_in_report(self):
        self.start()
        (self.root / 'b.txt').write_text('new')
        rendered = ' '.join(report.render_report(self.ledger.state_root, 'P1').split())
        self.assertIn('Giữ từ lần kiểm trước vì các tệp liên quan không đổi', rendered)

    def test_kept_pass_labelled_on_page(self):
        self.start()
        (self.root / 'b.txt').write_text('new')
        item = tracking.detail(self.ledger.state_root, 'P1')
        row = item['milestone_checks']['rows'][0]
        self.assertEqual((row['state'], row['note']), ('passed', 'Giữ từ lần kiểm trước vì các tệp liên quan không đổi.'))

    def test_stale_earlier_milestone_lets_later_run_said(self):
        self.start()
        (self.root / 'a.txt').write_text('new input')
        text = ' '.join(report.render_report(self.ledger.state_root, 'P1').split())
        note = 'Mốc cũ vẫn cho chạy mốc sau.'
        self.assertIn(note, text)
        item = tracking.detail(self.ledger.state_root, 'P1')
        self.assertIn(note, item['milestone_checks']['rows'][0]['note'])
        delivery = self.check('M2')
        self.assertEqual(delivery['state'], 'passed')
        with self.assertRaisesRegex(LedgerError, 'Cannot accept'):
            plans.accept(self.ledger, 'P1', 'owner', 'fixture', delivery['last_verdict']['artifact_sha'])

    def test_final_milestone_never_reuses_before_manual_handover(self):
        self.start(owner_step=True)
        with patch.object(verdict, '_reuse_candidate_pass', side_effect=AssertionError('borrowed delivery proof')):
            original = self.check('M2')
        sha = original['last_verdict']['artifact_sha']
        self.assertEqual(sha, verdict.artifact(self.ledger, 'P1')['artifact_sha'])
        (self.root / 'outside.txt').write_text('new outside both scopes')
        first, final, manual = self.views()
        self.assertEqual(first['state'], 'passed')
        self.assertTrue(final['stale'])
        self.assertEqual(manual['runs'], 0)
        self.assertNotEqual(self.check('M2')['last_verdict']['artifact_sha'], sha)

    def test_final_milestone_never_reuses_single_command_or_neutral_change(self):
        value = fixtures.plan_json([scoped('M1', ['a.txt'])], scope={'owned': ['a.txt'], 'neutral': ['b.txt']})
        self.approved(value=value)
        original = self.check('M1')['last_verdict']
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(original['receipt']))
        self.assertNotIn('input_scope', body)
        self.assertGreaterEqual(body['snapshot']['checkout_files'], 2)
        self.assertEqual(body['artifact_sha'], self.tree())
        (self.root / 'b.txt').write_text('changed neutral path')
        self.assertTrue(self.views()[0]['stale'])
        self.check('M1')
        plans.amend(self.ledger, 'P1', dict(value, title='New wording'), 'wording', 'claude')
        plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        self.assertEqual(self.views()[0]['state'], 'pending')

    def test_stale_earlier_milestone_after_a_successful_repair_is_a_recheck(self):
        first = scoped('M1', ['a.txt'])
        first['verifier']['config']['argv'] = [fixtures.PY, '-c',
            "from pathlib import Path; import sys; print('checking'); sys.exit(Path('a.txt').read_text() != 'fixed')"]
        self.approved(value=fixtures.plan_json([first, fixtures.milestone('M2')]))
        self.assertEqual(self.check('M1')['state'], 'failed')
        (self.root / 'a.txt').write_text('fixed')
        self.assertEqual(self.check('M1')['state'], 'passed')
        (self.root / 'a.txt').write_text('changed again')
        current = self.views()[0]
        self.assertEqual((current['state'], current['failures'], current['stale']), ('pending', 1, True))
        page = tracking.detail(self.ledger.state_root, 'P1')
        self.assertEqual(page['milestone_checks']['rows'][0]['state'], 'recheck')

    def test_old_scoped_receipt_cannot_stand_for_full_delivery_even_on_identical_tree(self):
        value = fixtures.plan_json([scoped('M1', ['a.txt', 'b.txt'])])
        self.approved(value=value)
        real = verdict.command.run
        def historical(*args, **kwargs):
            kwargs.pop('full_tree')
            return real(*args, **kwargs)
        with patch.object(verdict.command, 'run', historical):
            old = self.check('M1')
        self.assertEqual(old['last_verdict']['artifact_sha'], self.tree())
        self.assertTrue(old['stale'])
        self.assertEqual(self.check('M1')['state'], 'passed')

    def test_narrowing_inputs_by_amend_flagged(self):
        for before in (fixtures.milestone('M1'), scoped('M1', ['src'])):
            change = acceptance_diff.classify_contract(fixtures.plan_json([before]),
                                                       fixtures.plan_json([scoped('M1', ['src/a.py'])]))
            self.assertEqual(change['classification'], 'U1')
            self.assertTrue(any(c['kind'] == 'narrowed' and c['path'] == 'milestones.M1.inputs'
                                for c in change['changes']))
