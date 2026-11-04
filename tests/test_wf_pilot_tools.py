"""W38b / W38c / W38d local tools (wfkit.pilot_tools), on FIXTURES only.

* report: the interim (T35b) generator runs over the fixture ledger of tests.test_wf_r03a_metrics (three finished plan roots built through the
  real plan code under a fake clock); its output must be accepted by wfkit.pilot_report.check_report (round trip), be deterministic, carry
  fixture provenance and no acceptance claim, and the checker must still refuse a forged copy.
* report --kind aggregate (W38c, T35c): the same pipeline over two SYNTHETIC pilot ledgers (AggregateGeneratorTests; manifest template in
  tests/fixtures/pilot/aggregate-manifest.json): round trip through check_report, deterministic bytes, provenance per figure, and the
  refusals (missing sample kept in the denominator, duplicate rows, contradiction, wrong artifact, wrong scope, forged figure, synthetic
  claiming real) plus the CLI entry. Running it on the real ten-job pilot is external (W38c).
* rerun-check: the A->B analysis of T45e (E23-E26) on a four-item fixture map.
* supp-run: supplementary checks run on a fixture "final wheel" (bytes written by the test), receipts read back through finalgate.Evidence.
No pilot, provider or owner decision is used or claimed.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import test_wf_r03a_metrics as r03

from onecrew import interventions
from onecrew.ledger import canonical
from onecrew.snapshots import Snapshots
from onecrew.v2 import outcome, plan as plans, review_policy, verdict
from wfkit import pilot_report as pr, pilot_tools as pt
from wfkit.finalgate import Evidence

H = 'b' * 64
COMMIT = 'c' * 40


def manifest(**changes):
    m = {'schema': 1, 'kind': 'interim', 'fixture': True,
         'provenance': {'state_root': 'FIXTURE-STATE-ROOT', 'commit': COMMIT, 'wheel_sha256': H},
         'jobs': [{'id': 'J1', 'root': 'P1'}, {'id': 'J2', 'root': 'P2'}, {'id': 'J3', 'root': 'P3'}],
         'chat_log': {'J1': {'decision': 2, 'intervention': 0, 'outcome': 1}, 'J2': {'decision': 2, 'intervention': 0, 'outcome': 1},
                      'J3': {'decision': 4, 'intervention': 0, 'outcome': 1}},
         'observations': {'owner_minutes': {'J1': 3, 'J3': 9}, 'owner_retries': {'J1': 0, 'J2': 1, 'J3': 2}},
         'desktop_window': {'event_id': 'EV-1', 'emitted_at': '2026-10-24T12:00:00+00:00', 'shown_at': '2026-10-24T12:00:03+00:00',
                            'delivery_status': 'đã giao'}}
    m.update(changes)
    return m


class Generated(r03.ThreeRoots):
    def setUp(self):
        super().setUp()
        for name in ('P1', 'P2', 'P3'):
            outcome.record(self.ledger, name)


class ReportGeneratorTests(Generated):
    """One test method on purpose: building the three-root fixture ledger takes minutes on a loaded machine, so each case is a sub-test."""

    def case_round_trip_passes_the_existing_checker(self):
        report, text = pt.generate_interim(self.ledger, manifest())
        res = pr.check_report(report, text)
        self.assertEqual(res['result'], 'pass', res)
        self.assertEqual((res['owner_acceptance'], res['pilot_evidence'], res['simulated']), (False, False, True))

    def case_figures_come_from_the_ledger_and_unknown_is_not_zero(self):
        report, text = pt.generate_interim(self.ledger, manifest())
        by = {m['id']: m for m in report['metrics']}
        self.assertEqual([c['value'] for c in by['time_to_usable']['cells'].values()], [18, 4, 49])      # hand-worked in test_wf_r03a_metrics
        self.assertEqual([c['value'] for c in by['rework_rounds']['cells'].values()], [1, 0, 2])
        self.assertEqual([c['value'] for c in by['owner_decisions']['cells'].values()], [2, 2, 4])
        self.assertEqual(by['owner_minutes']['cells']['J2'], {'no_data': pr.NO_NOTES})                    # no owner note: not 0
        self.assertEqual(report['owner_notes_missing']['owner_minutes'], ['J2'])
        for mid in ('false_pass', 'noise_stop_hook', 'ledger_manual_fixes', 'owner_keystrokes'):
            self.assertEqual(by[mid]['k'], 0, mid)
            self.assertIn('no_data', by[mid]['summary'], mid)
        self.assertEqual(by['amend_authoring_error']['cells']['J3'], {'no_data': 'nguyên nhân amend không có trong sổ'})   # P3 had an amend
        self.assertEqual(by['amend_authoring_error']['cells']['J1'], {'value': 0})                         # P1 had none
        self.assertNotIn('skip_leak', by)
        self.assertNotIn('baseline', text.lower())
        detail = {d['job']: d for d in report['jobs_detail']}
        self.assertEqual((detail['J3']['verdicts'], detail['J3']['revision'], detail['J3']['status']), ({'pass': 1, 'fail': 2}, 2, 'accepted'))
        self.assertEqual(detail['J3']['open_findings'], pt.UNKNOWN)

    def case_deterministic_and_provenance_without_acceptance(self):
        a = pt.generate_interim(self.ledger, manifest())
        b = pt.generate_interim(self.ledger, manifest())
        self.assertEqual(a, b)
        report, text = a
        self.assertEqual(report['provenance'], {'kind': 'fixture', 'state_root': 'FIXTURE-STATE-ROOT', 'commit': COMMIT, 'wheel_sha256': H,
                                                'generator': 'wfkit.pilot_tools report'})
        self.assertIn('fixture, không phải pilot thật', text)
        self.assertIn('không phải nghiệm thu', text)
        self.assertIs(report['owner_acceptance'], False)
        self.assertIs(report['pilot_evidence'], False)

    def case_files_are_written_and_checkable_by_the_cli_checker(self):
        report, text = pt.generate_interim(self.ledger, manifest())
        with tempfile.TemporaryDirectory() as tmp:
            j, m = pt.write_report(report, text, tmp)
            self.assertEqual(pr.check_files(j, m)['result'], 'pass')

    def case_refuses_a_forged_report(self):
        report, text = pt.generate_interim(self.ledger, manifest())
        forged = json.loads(json.dumps(report))
        by = {m['id']: m for m in forged['metrics']}
        by['owner_minutes']['cells']['J2'] = {'value': 0}                    # a missing note turned into 0
        res = pr.check_report(forged, text)
        self.assertEqual(res['result'], 'refused')
        self.assertTrue(any('E35' in p or 'E23' in p or 'E7' in p for p in res['problems']), res['problems'])
        forged = json.loads(json.dumps(report))
        forged['ledger_columns']['hand_filled'] = 1
        self.assertEqual(pr.check_report(forged, text)['result'], 'refused')
        self.assertEqual(pr.check_report(report, text + 'Ghi chú: đã có baseline sơ bộ.\n')['result'], 'refused')
        forged = json.loads(json.dumps(report))
        forged['owner_acceptance'] = True
        self.assertEqual(pr.check_report(forged, text)['result'], 'refused')

    def case_chat_ledger_mismatch_is_reported_with_both_sources_not_hidden(self):
        m = manifest()
        m['chat_log']['J2']['decision'] = 5
        report, text = pt.generate_interim(self.ledger, m)
        row = next(r for r in report['ledger_columns']['rows'] if (r['job'], r['column']) == ('J2', 'decision'))
        self.assertEqual((row['ledger'], row['chat'], row['match']), (2, 5, False))
        self.assertTrue(row['reason'])
        self.assertEqual(pr.check_report(report, text)['result'], 'pass')

    def case_missing_outcome_row_is_listed_and_the_report_is_refused_by_the_checker(self):
        with self.ledger.transaction(write=True) as conn:
            for row in conn.execute("SELECT seq, payload FROM events WHERE kind='learning.outcome'").fetchall():
                if json.loads(row['payload']).get('plan_revision') == 1:
                    conn.execute('DELETE FROM events WHERE seq=?', (row['seq'],))
        report, text = pt.generate_interim(self.ledger, manifest())
        gaps = report['outcomes']['missing']
        self.assertTrue(gaps)
        res = pr.check_report(report, text)
        self.assertEqual(res['result'], 'refused')
        self.assertTrue(any('E25' in p for p in res['problems']), res['problems'])

    # ---- refusals of the generator itself ----------------------------------------------------------------------------
    def test_generator(self):
        order = ['round_trip_passes_the_existing_checker', 'figures_come_from_the_ledger_and_unknown_is_not_zero', 'deterministic_and_provenance_without_acceptance', 'files_are_written_and_checkable_by_the_cli_checker', 'refuses_a_forged_report', 'chat_ledger_mismatch_is_reported_with_both_sources_not_hidden', 'missing_outcome_row_is_listed_and_the_report_is_refused_by_the_checker', 'refuses_aggregate_kind', 'refuses_hand_filled_group_a_and_missing_chat_log', 'refuses_unknown_root_and_unended_root', 'refuses_undeclared_fixture_flag_and_missing_provenance']
        for name in order:
            with self.subTest(name):
                getattr(self, 'case_' + name)()

    def refuses(self, m, needle):
        with self.assertRaises(pt.ReportError) as ctx:
            pt.generate_interim(self.ledger, m)
        self.assertIn(needle, str(ctx.exception))

    def case_refuses_aggregate_kind(self):
        self.refuses(manifest(kind='aggregate'), 'only kind "interim"')

    def case_refuses_hand_filled_group_a_and_missing_chat_log(self):
        self.refuses(manifest(observations={'time_to_usable': {'J1': 1}}), 'only supply group B/C')
        m = manifest()
        del m['chat_log']['J3']
        self.refuses(m, 'chat_log needs')

    def case_refuses_unknown_root_and_unended_root(self):
        m = manifest()
        m['jobs'][0]['root'] = 'NOPE'
        self.refuses(m, 'not exactly one plan root')
        self.propose('P4', r03.plan_json(title='Fourth'))
        m = manifest()
        m['jobs'][0]['root'] = 'P4'
        self.refuses(m, 'has not ended')

    def case_refuses_undeclared_fixture_flag_and_missing_provenance(self):
        m = manifest()
        del m['fixture']
        self.refuses(m, 'fixture must be declared')
        m = manifest()
        m['provenance']['wheel_sha256'] = 'zz'
        self.refuses(m, 'provenance needs')


# ---- W38c: aggregate (T35c, PL-B) generator, on SYNTHETIC ledgers ------------------------------------------------------

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'pilot'
REPO = Path(__file__).resolve().parents[1]


def u_question(cls, label):
    """A typed owner question carrying its U class the way the product writes it (estimates: parameters.class; engine: reason_class)."""
    action = ({'type': 'authorize', 'parameters': {'class': cls, 'fixture': label}} if cls == 'U2' else
              {'type': 'v2.workflow_hold', 'parameters': {'reason_class': cls, 'fixture': label}})
    return {'schema_version': 1, 'question': f'Synthetic {cls} decision ({label})', 'reason': 'synthetic fixture', 'impact': 'none: synthetic',
            'options': [{'id': 'continue', 'label': 'Continue'}, {'id': 'stop', 'label': 'Stop'}], 'recommendation': 'continue', 'action': action}


class AggregateGeneratorTests(r03.ThreeRoots):
    """W38c (T35c) aggregate generator on two SYNTHETIC pilot ledgers (L1: P1-P6, L2: Q7-Q10 + an excluded stopped root X1), built through
    the product code (plan propose/approve/accept, verdict.record, ledger requests/replies, review_policy.decide, interventions.record,
    outcome.record) under a fake clock; provider and hook events are emitted in the shape verdict.record / hook sync write them. Every
    ledger and the report are flagged synthetic. One test method: building eleven roots takes minutes on a loaded machine."""

    # ---- fixture ---------------------------------------------------------------------------------------------------
    def build(self):
        from onecrew.ledger import Ledger
        import os
        base = Path(self.temp.name)
        os.environ['ONECREW_DESKTOP_HOME'] = str(base / 'desktop')        # no desktop record: nothing was shown
        self.l2 = Ledger(self.root, base / 'state2')
        self.wheel1, self.wheel2, self.package = base / 'l1.whl', base / 'l2.whl', base / 'continuation-package.json'
        self.wheel1.write_bytes(b'synthetic wheel of the PL-A build')
        self.wheel2.write_bytes(b'synthetic wheel of the PL-B build')
        self.package.write_bytes(b'{"synthetic": "continuation package"}')
        L1, L2, c = self.ledger, self.l2, self.clock
        self.simple(L1, 'P1', '01', fail_first=True)
        self.start(L1, 'P2', '02')
        self.ask(L1, 'P2', 'U1', '02:02', '02:04')
        self.ask(L1, 'P2', 'U2', '02:05', '02:06')
        c.at('02:07'); self.provider_call(L1, 'P2', 'codex', 'invalid_response')
        self.finish(L1, 'P2', '02:10', '02:11')
        c.at('03:00'); self.propose_on(L1, 'P3', r03.plan_json(title='P3'))
        c.at('03:01'); plans.approve(L1, 'P3', 'owner', 'synthetic: owner said yes')
        c.at('03:05'); self.check(L1, 'P3', 'fail', 10)
        c.at('03:10'); out = self.check(L1, 'P3', 'fail', 10)
        request = L1.requests(out['anchor_task'])[0]
        c.at('03:40'); L1.reply(request['id'], request['revision'], 'amend_plan', source='fixture', reference='synthetic owner answer', decided_by='user', by='user')
        c.at('03:45'); plans.amend(L1, 'P3', r03.plan_json(title='P3 again'), 'synthetic: continue after the stop', 'claude')
        c.at('03:46'); plans.approve(L1, 'P3', 'owner', 'synthetic: owner said yes again')
        self.finish(L1, 'P3', '03:50', '03:52', revision=2)
        c.at('04:00'); self.propose_on(L1, 'P4', r03.plan_json(title='P4', review_policy={'depth': 'light', 'optional_reviews': ['R-opt']}))
        c.at('04:01'); plans.approve(L1, 'P4', 'owner', 'synthetic: owner said yes')
        c.at('04:02'); self.skip = review_policy.decide(L1, 'P4', 'R-opt', artifact_sha=self.tree(), evidence=('synthetic',))
        c.at('04:03'); self.provider_call(L1, 'P4', 'codex', 'quota_exhausted')
        self.finish(L1, 'P4', '04:05', '04:06')
        self.start(L1, 'P5', '05')
        self.ask(L1, 'P5', 'U3', '05:02', '05:04')
        self.ask(L1, 'P5', 'U4', '05:05', '05:06')
        c.at('05:07'); interventions.record(L1, self.task(L1, 'P5'), 'plan.fix', actor='claude', reason='synthetic: re-issued a lost receipt', key='syn-fix-1')
        c.at('05:08'); blob = self.issue(L1, 'P5', 'pass', 15)
        c.at('05:09')
        self.hook(L1, 'P5', 'hook.stop_blocked', 'Stop', 'stop_pending_milestone', '', 'h1')       # a receipt waits for its verdict: noise
        self.hook(L1, 'P5', 'hook.blocked', 'Edit', 'outside_scope', 'a.txt', 'h2')              # a.txt is in scope.owned: wrong-scope block
        self.hook(L1, 'P5', 'hook.blocked', 'Write', 'outside_scope', 'b.txt', 'h3')             # b.txt is not: a right block
        c.at('05:10'); verdict.record(L1, 'P5', 'M1', 'pass', 'command', blob, self.tree())
        c.at('05:12'); plans.accept(L1, 'P5', 'owner', 'synthetic: accepted', self.tree())
        self.start(L1, 'P6', '06')
        c.at('06:03'); self.provider_call(L1, 'P6', 'claude', 'provider_unavailable')
        self.finish(L1, 'P6', '06:05', '06:06')
        self.simple(L2, 'Q7', '08')
        self.start(L2, 'Q8', '09')
        self.ask(L2, 'Q8', 'U2', '09:02', '10:40')                                           # answered after 98 min, never shown: missed
        self.finish(L2, 'Q8', '10:45', '10:46')
        self.simple(L2, 'Q9', '11')
        self.simple(L2, 'Q10', '12')
        c.at('13:00'); self.propose_on(L2, 'X1', r03.plan_json(title='X1'))
        c.at('13:01'); plans.approve(L2, 'X1', 'owner', 'synthetic: owner said yes')
        c.at('13:05'); self.check(L2, 'X1', 'fail', 10)
        c.at('13:10'); self.check(L2, 'X1', 'fail', 10)                                           # stopped_with_report
        for ledger, names in ((L1, ('P1', 'P2', 'P3', 'P4', 'P5', 'P6')), (L2, ('Q7', 'Q8', 'Q9', 'Q10', 'X1'))):
            for name in names:
                outcome.record(ledger, name)

    def propose_on(self, ledger, name, value):
        return plans.propose(ledger, name, value, 'claude')

    def task(self, ledger, name):
        with ledger.transaction() as conn:
            return plans.derive(ledger, conn, name)['task_id']

    def start(self, ledger, name, hour):
        self.clock.at(f'{hour}:00'); self.propose_on(ledger, name, r03.plan_json(title=name))
        self.clock.at(f'{hour}:01'); plans.approve(ledger, name, 'owner', 'synthetic: owner said yes')

    def finish(self, ledger, name, passed, accepted, revision=1):
        self.clock.at(passed); self.check(ledger, name, 'pass', 20, revision)
        self.clock.at(accepted); plans.accept(ledger, name, 'owner', 'synthetic: accepted', self.tree())

    def simple(self, ledger, name, hour, fail_first=False):
        self.start(ledger, name, hour)
        if fail_first:
            self.clock.at(f'{hour}:10'); self.check(ledger, name, 'fail', 60)
        self.finish(ledger, name, f'{hour}:20', f'{hour}:22')

    def issue(self, ledger, name, result, seconds, revision=1):
        with ledger.transaction() as conn:
            sha = plans.derive(ledger, conn, name)['revisions'][revision]['sha']
        body = {'kind': 'command-receipt', 'plan': name, 'revision': revision, 'milestone': 'M1', 'argv': r03.OK, 'exit_code': 0 if result == 'pass' else 3,
                'timed_out': False, 'error': None, 'artifact_sha': self.tree(), 'artifact_sha_after': self.tree(), 'plan_sha': sha, 'seconds': seconds}
        blob = Snapshots(ledger.state_root).blob(canonical(body).encode('utf-8'))
        with ledger.transaction(write=True) as conn:
            plans.emit(ledger, conn, plans.derive(ledger, conn, name)['task_id'], 'verdict.receipt_issued',
                       {'plan': name, 'revision': revision, 'milestone': 'M1', 'receipt': blob})
        return blob

    def check(self, ledger, name, result, seconds, revision=1):
        return verdict.record(ledger, name, 'M1', result, 'command', self.issue(ledger, name, result, seconds, revision), self.tree())

    def provider_call(self, ledger, name, provider, error):
        """An inconclusive reviewer verdict event with the W43 fields verdict.record writes (provider, model, calls, provider_error)."""
        blob = Snapshots(ledger.state_root).blob(canonical({'kind': 'synthetic-reviewer-receipt', 'provider': provider, 'provider_error': error,
                                                            'seconds': 4}).encode('utf-8'))
        with ledger.transaction(write=True) as conn:
            state = plans.derive(ledger, conn, name)
            plans.emit(ledger, conn, state['task_id'], 'verdict.recorded',
                       {'plan': name, 'revision': 1, 'milestone': 'M1', 'plan_sha': state['revisions'][1]['sha'], 'result': 'inconclusive', 'by': 'reviewer',
                        'receipt': blob, 'artifact_sha': self.tree(), 'run': 1, 'cwd': None, 'independence': 'other-vendor', 'model': 'synthetic-model',
                        'calls': 1, 'provider': provider, 'provider_error': error})

    def ask(self, ledger, name, cls, asked, answered):
        self.clock.at(asked)
        req = ledger.create_request(self.task(ledger, name), f'syn-{name}-{cls}', u_question(cls, name))
        self.clock.at(answered)
        ledger.reply(req['id'], req['revision'], 'continue', source='fixture', reference='synthetic owner answer', decided_by='user', by='user')

    def hook(self, ledger, name, kind, tool, rule, subject, spool_id):
        with ledger.transaction(write=True) as conn:
            plans.emit(ledger, conn, plans.derive(ledger, conn, name)['task_id'], kind,
                       {'plan': name, 'revision': 1, 'tool': tool, 'rule': rule, 'reason': 'synthetic hook record', 'subject': subject, 'mode': 'enforce',
                        'session': 'syn', 'spool_id': spool_id, 'recorded_at': self.clock()})

    def manifest(self):
        m = json.loads((FIXTURES / 'aggregate-manifest.json').read_text(encoding='utf-8'))
        for row, ledger, wheel in ((m['ledgers'][0], self.ledger, self.wheel1), (m['ledgers'][1], self.l2, self.wheel2)):
            row.update(project=str(self.root), state_root=str(ledger.state_root), wheel=str(wheel), wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest())
        m['continuation_trial'].update(package=str(self.package), package_sha256=hashlib.sha256(self.package.read_bytes()).hexdigest())
        return m

    def open(self, entry):
        return {'L1': self.ledger, 'L2': self.l2}[entry['id']]

    def generate(self, m=None):
        return pt.generate_aggregate(self.manifest() if m is None else m, open_ledger=self.open)

    def refuses(self, m, needle):
        with self.assertRaises(pt.ReportError) as ctx:
            self.generate(m)
        self.assertIn(needle, str(ctx.exception))

    def refused(self, report, text, needle):
        res = pr.check_report(report, text)
        self.assertEqual(res['result'], 'refused', res)
        self.assertTrue(any(needle in p for p in res['problems']), res['problems'])
        return res

    def job(self, m, jid):
        return next(j for j in m['jobs'] if j['id'] == jid)

    # ---- cases -----------------------------------------------------------------------------------------------------
    def case_round_trip_accepted_deterministic_synthetic(self):
        # T35c E6, E20-E24, E27, E29-E34, E38: the generated aggregate passes check_report; same inputs -> same bytes; synthetic, no acceptance
        report, text = self.generate()
        res = pr.check_report(report, text)
        self.assertEqual(res['result'], 'pass', res['problems'])
        self.assertEqual((res['owner_acceptance'], res['pilot_evidence'], res['simulated'], res['kind']), (False, False, True, 'aggregate'))
        again, text2 = self.generate()
        dump = lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True, indent=2)
        self.assertEqual((dump(report), text), (dump(again), text2))
        p = report['provenance']
        self.assertEqual((p['kind'], [x['id'] for x in p['ledgers']], [x['synthetic'] for x in p['ledgers']]), ('synthetic', ['L1', 'L2'], [True, True]))
        self.assertEqual([x['wheel_verified'] for x in p['ledgers']], [True, True])
        self.assertEqual(p['ledgers'][1]['roots'], ['Q10', 'Q7', 'Q8', 'Q9', 'X1'])
        self.assertEqual(p['ledgers'][1]['excluded'][0]['root'], 'X1')
        self.assertIn(pr.SYNTHETIC_LINE, text)
        self.assertIn(p['ledgers'][0]['wheel_sha256'], text)
        self.assertEqual(report['figures_sha256'], pr.figures_digest(report))
        self.assertTrue(text.splitlines()[1].startswith(pr.AC5 + 'đạt'))

    def case_figures_come_from_the_ledgers_with_their_sources(self):
        report, _ = self.generate()
        by = {m['id']: m for m in report['metrics']}
        self.assertEqual(by['time_to_usable']['k'], 10)
        self.assertEqual(by['time_to_usable']['computed_from'][0], {'job': 'J1', 'ledger': 'L1', 'root': 'P1'})
        self.assertEqual({x['ledger'] for x in by['time_to_usable']['computed_from']}, {'L1', 'L2'})
        self.assertEqual(by['owner_minutes']['cells']['J6'], {'no_data': pr.NO_NOTES})                       # B missing: not 0, not dropped
        self.assertEqual((by['owner_minutes']['k'], by['owner_minutes']['n'], by['owner_minutes']['missing']), (9, 10, ['J6']))
        self.assertEqual(by['owner_minutes']['label'], 'baseline một phần (9/10)')
        self.assertEqual(by['noise_stop_hook']['cells']['J5']['value'], 1)
        self.assertEqual(by['wrong_scope_block']['cells']['J5']['value'], 1)
        self.assertEqual(by['missed_wait_1h']['cells']['J8']['value'], 1)
        self.assertEqual(by['missed_wait_1h']['target_status'], 'không đạt')
        self.assertEqual(by['ledger_manual_fixes']['cells']['J5']['value'], 1)
        per = report['owner_decisions']['per_job']
        self.assertEqual((per['J2']['U1'], per['J2']['U2'], per['J5']['U3'], per['J5']['U4'], per['J8']['U2'], per['J3']['other']), (1, 1, 1, 1, 1, 1))
        self.assertEqual(per['J1'], {'root_approval': 1, 'acceptance': 1, 'U1': 0, 'U2': 0, 'U3': 0, 'U4': 0, 'other': 0})
        self.assertEqual(report['owner_decisions']['ac1']['status'], 'không đạt')                         # J2 has 4, J3 has an "other"
        self.assertEqual([(m['job'], m['ledger'], m['chat']) for m in report['owner_decisions']['mismatches']], [('J7', 2, 3)])
        prov = {p['provider']: (p['calls'], p['failures'], p['reasons']) for p in report['providers']}
        self.assertEqual(prov, {'claude': (1, 1, {'lỗi công cụ': 1}), 'codex': (2, 1, {'hạn mức': 1})})
        self.assertEqual((report['skip_leak']['skip_count'], report['skip_leak']['links']), (1, []))
        self.assertEqual(self.skip['action'], 'SKIP')
        self.assertEqual(report['manual_fixes']['interventions'], 1)
        self.assertNotIn('mismatch_reason', report['manual_fixes'])
        self.assertEqual(report['continuation_trial']['result'], 'đạt')
        self.assertEqual(report['tiers']['tier3']['conclusion'], pr.NO_REDUCTION)

    def case_job_without_metrics_stays_in_the_denominator(self):
        m = self.manifest()
        j10 = self.job(m, 'J10')
        j10.clear(); j10.update(id='J10', skipped='synthetic: việc bị hủy trước khi chạy')
        del m['chat_log']['J10']
        for cells in m['observations'].values():
            cells.pop('J10', None)
        m['continuation_trial']['job'] = 'J9'
        m['excluded'].append({'ledger': 'L2', 'root': 'Q10', 'reason': 'root của việc J10 bị bỏ (synthetic)'})
        report, text = self.generate(m)
        for metric in report['metrics']:
            self.assertEqual(metric['n'], 10, metric['id'])
            self.assertIn('J10', metric['missing'], metric['id'])
            self.assertIn('no_data', metric['cells']['J10'], metric['id'])
        self.assertEqual(report['skipped_jobs'], [{'job': 'J10', 'reason': 'synthetic: việc bị hủy trước khi chạy'}])
        res = self.refused(report, text, 'E32 AC5 — năng lực đo: không đạt: nhóm A thiếu J10')
        self.assertTrue(any('E31' in p for p in res['problems']), res['problems'])

    def case_stopped_root_is_reported_not_dropped(self):
        m = self.manifest()
        self.job(m, 'J10').update(root='X1', final_outcome='stopped_with_report')
        m['excluded'] = [{'ledger': 'L2', 'root': 'Q10', 'reason': 'synthetic swap'}]
        report, text = self.generate(m)
        self.assertEqual(report['outcomes']['roots'][-1]['final_outcome'], 'stopped_with_report')
        self.refused(report, text, 'E32 AC5 — năng lực đo: không đạt: nhóm A thiếu J10 time_to_usable')

    def case_duplicate_job_rows_refused(self):
        m = self.manifest()
        self.job(m, 'J9')['root'] = 'Q8'
        self.refuses(m, 'duplicate job rows')
        report, text = self.generate()
        m = self.manifest()
        self.job(m, 'J9')['root'] = report['jobs_detail'][7]['plan']                             # the same root under its selector
        self.assertNotEqual(self.job(m, 'J9')['root'], 'Q8')
        self.refuses(m, 'duplicate job rows')
        forged = json.loads(json.dumps(report))
        forged['jobs_detail'][8] = dict(forged['jobs_detail'][7], job='J9')
        self.refused(forged, text, 'ID dòng việc trùng')

    def case_contradictory_data_refused(self):
        m = self.manifest()
        self.job(m, 'J2')['final_outcome'] = 'failed'
        self.refuses(m, 'contradictory data')
        m = self.manifest()
        m['ledgers'][1]['state_root'] = m['ledgers'][0]['state_root']
        self.refuses(m, 'contradictory data')
        report, text = self.generate()
        forged = json.loads(json.dumps(report))
        forged['jobs_detail'][1]['status'] = 'failed'
        self.refused(forged, text, 'ID dữ liệu mâu thuẫn')

    def case_wrong_artifact_refused(self):
        m = self.manifest()
        m['ledgers'][0]['wheel_sha256'] = 'e' * 64
        self.refuses(m, 'wrong artifact')
        m = self.manifest()
        self.job(m, 'J1')['wheel_sha256'] = 'e' * 64
        self.refuses(m, 'wrong artifact')
        m = self.manifest()
        m['continuation_trial']['package_sha256'] = 'e' * 64
        self.refuses(m, 'wrong artifact')
        report, text = self.generate()
        forged = json.loads(json.dumps(report))
        forged['jobs_detail'][0]['wheel_sha256'] = 'e' * 64
        self.refused(forged, text, 'ID sai artifact')

    def case_wrong_scope_refused(self):
        m = self.manifest()
        m['excluded'] = []
        self.refuses(m, 'wrong scope')
        m = self.manifest()
        self.job(m, 'J7')['ledger'] = 'L9'
        self.refuses(m, 'not a pilot ledger')
        report, text = self.generate()
        forged = json.loads(json.dumps(report))
        forged['provenance']['ledgers'][0]['roots'].append('P99')
        self.refused(forged, text, 'ID root ngoài phạm vi pilot ở sổ L1: P99')
        forged = json.loads(json.dumps(report))
        forged['jobs_detail'][6]['ledger'] = 'L9'
        self.refused(forged, text, 'ID sai phạm vi')

    def case_forged_figure_refused(self):
        report, text = self.generate()
        forged = json.loads(json.dumps(report))
        m = next(x for x in forged['metrics'] if x['id'] == 'time_to_usable')
        m['cells']['J1']['value'] += 5
        self.refused(forged, text, 'ID số liệu giả: time_to_usable')
        m['summary']['value'] += 5                                                                  # summary made consistent: the digest still catches it
        self.refused(forged, text, 'ID figures_sha256')
        forged = json.loads(json.dumps(report))
        next(x for x in forged['metrics'] if x['id'] == 'verify_cost')['computed_from'].pop()
        self.refused(forged, text, 'ID verify_cost: computed_from')
        with tempfile.TemporaryDirectory() as tmp:
            pt.write_named(report, text, tmp, pt.AGG_FILES)
            self.assertEqual(pt.verify_aggregate(self.manifest(), tmp, open_ledger=self.open)['result'], 'pass')
            forged = json.loads(json.dumps(report))
            next(x for x in forged['metrics'] if x['id'] == 'rework_rounds')['cells']['J1']['value'] = 0
            forged['figures_sha256'] = pr.figures_digest(forged)                                     # even a recomputed digest: regeneration differs
            pt.write_named(forged, text, tmp, pt.AGG_FILES)
            res = pt.verify_aggregate(self.manifest(), tmp, open_ledger=self.open)
            self.assertEqual(res['result'], 'refused')
            self.assertTrue(any('khác bản sinh lại' in p for p in res['problems']), res['problems'])

    def case_synthetic_claiming_real_refused(self):
        report, text = self.generate()
        forged = json.loads(json.dumps(report))
        forged['provenance']['kind'], forged['simulated'] = 'real', False
        self.refused(forged, text, 'ID dữ liệu synthetic không chứng minh pilot thật')
        self.refused(report, text + 'Chủ sở hữu đã nghiệm thu PL-B.\n', 'ID báo cáo synthetic tự nhận pilot thật hay nghiệm thu')
        forged = json.loads(json.dumps(report))
        forged['owner_acceptance'] = True
        self.assertEqual(pr.check_report(forged, text)['result'], 'refused')
        forged = json.loads(json.dumps(report))
        forged['pilot_evidence'] = True
        self.refused(forged, text, 'ID báo cáo synthetic ghi bằng chứng pilot hay nghiệm thu')
        m = self.manifest()
        m['synthetic'] = False
        self.refuses(m, 'a synthetic ledger cannot make a real report')

    def case_cli_entry(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'manifest.json').write_text(json.dumps(self.manifest(), ensure_ascii=False), encoding='utf-8')
            env = dict(os.environ, PYTHONPATH=str(REPO))

            def run(*argv):
                proc = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'wfkit.pilot_tools', *argv], cwd=str(REPO), env=env,
                                      capture_output=True, text=True, encoding='utf-8', timeout=600)
                return proc.returncode, proc.stdout, proc.stderr
            code, out, err = run('report', '--kind', 'aggregate', '--manifest', str(tmp / 'manifest.json'), '--out-dir', str(tmp / 'out'))
            self.assertEqual(code, 0, out + err)
            self.assertEqual(json.loads(out)['check']['result'], 'pass')
            report, text = self.generate()
            self.assertEqual((tmp / 'out' / 'aggregate-report.md').read_text(encoding='utf-8'), text)     # same bytes as in-process
            code, out, err = run('verify', '--manifest', str(tmp / 'manifest.json'), '--report-dir', str(tmp / 'out'))
            self.assertEqual((code, json.loads(out)['result']), (0, 'pass'), out + err)
            md = tmp / 'out' / 'aggregate-report.md'
            md.write_text(md.read_text(encoding='utf-8').replace('chưa kết luận giảm', 'đã giảm', 1), encoding='utf-8')
            code, out, err = run('verify', '--manifest', str(tmp / 'manifest.json'), '--report-dir', str(tmp / 'out'))
            self.assertEqual(code, 1, out + err)
            bad = self.manifest()
            self.job(bad, 'J9')['root'] = 'Q8'
            (tmp / 'bad.json').write_text(json.dumps(bad, ensure_ascii=False), encoding='utf-8')
            code, out, err = run('report', '--kind', 'aggregate', '--manifest', str(tmp / 'bad.json'), '--out-dir', str(tmp / 'bad'))
            self.assertEqual(code, 2, out + err)
            self.assertIn('duplicate job rows', out)
            code, out, err = run('report', '--kind', 'interim', '--manifest', str(tmp / 'manifest.json'), '--out-dir', str(tmp / 'x'))
            self.assertEqual(code, 2, out + err)

    def case_tier1_composite_uses_one_job_set(self):
        # round 7 F3 (Codex P2) on the real generator: J3 (P3) is the only root with an amend, its causes observed 0/1/0; every other job
        # had no amend in its ledger (cell 0). Full data: 0+1+0 = 1 amend over all ten jobs.
        amend = lambda r: next(c for c in r['tiers']['tier1']['comparisons'] if c['metric'] == 'amend_total')
        report, text = self.generate()
        c = amend(report)
        self.assertEqual((c['pilot_count'], c['pilot_jobs'], c['complete'], c['missing']), (1, 10, True, {}))
        # Codex's case: delete J3's amend_authoring_error observation; J3 still has amend_requirement_change 1. J3 leaves the composite
        # entirely: the nine others have 0 amends -> 0 over 9 jobs (the old generator wrote 1 over 9).
        m = self.manifest()
        del m['observations']['amend_authoring_error']['J3']
        report, text = self.generate(m)
        c = amend(report)
        self.assertEqual((c['pilot_count'], c['pilot_jobs'], c['pilot_per_job'], c['complete']), (0, 9, 0.0, False))
        self.assertEqual(c['computed_from'], ['J1', 'J10', 'J2', 'J4', 'J5', 'J6', 'J7', 'J8', 'J9'])
        self.assertEqual(c['missing'], {'amend_authoring_error': ['J3']})
        line = next(l for l in text.splitlines() if l.startswith('- amend_total:'))
        self.assertIn('pilot 0 trên 9 việc', line)
        self.assertIn('so sánh một phần, thiếu amend_authoring_error: J3', line)
        res = pr.check_report(report, text)
        self.assertEqual(res['result'], 'pass', res['problems'])

    def test_aggregate(self):
        order = ['round_trip_accepted_deterministic_synthetic', 'figures_come_from_the_ledgers_with_their_sources', 'tier1_composite_uses_one_job_set',
                 'job_without_metrics_stays_in_the_denominator', 'stopped_root_is_reported_not_dropped', 'duplicate_job_rows_refused',
                 'contradictory_data_refused', 'wrong_artifact_refused', 'wrong_scope_refused', 'forged_figure_refused',
                 'synthetic_claiming_real_refused', 'cli_entry']
        for name in order:
            with self.subTest(name):
                getattr(self, 'case_' + name)()


# ---- W38d: re-run plan ------------------------------------------------------------------------------------------------

SRC = {'commit': 'a' * 40, 'wheel_sha256': 'a' * 64}
DST = {'commit': 'd' * 40, 'wheel_sha256': 'd' * 64}


def analysis(**changes):
    a = {'schema': 1, 'source': SRC, 'target': DST, 'changed_files': ['onecrew/a.py'],
         'items': [{'id': 'T1', 'owned': ['onecrew/a.py'], 'depends_on': []}, {'id': 'T2', 'owned': ['onecrew/b.py'], 'depends_on': ['T1']},
                   {'id': 'T3', 'owned': ['onecrew/c.py'], 'depends_on': []}, {'id': 'T4', 'owned': ['onecrew/d.py'], 'depends_on': []}],
         'jobs': [{'id': 'J1', 'items': ['T1']}, {'id': 'J2', 'items': ['T2']}, {'id': 'J3', 'items': ['T3']}, {'id': 'J4', 'items': ['T4']}],
         'evidence': [{'job': 'J3', 'wheel_sha256': SRC['wheel_sha256']}, {'job': 'J4', 'wheel_sha256': SRC['wheel_sha256']}]}
    a.update(changes)
    return a


def good_plan(**changes):
    p = {'rerun_jobs': ['J1', 'J2'], 'supplements': {'T1': ['chk-1'], 'T2': ['chk-2']}}
    p.update(changes)
    return p


class RerunPlanTests(unittest.TestCase):
    def refused(self, a, p, needle):
        res = pt.check_rerun_plan(a, p)
        self.assertEqual(res['result'], 'refused', res)
        self.assertTrue(any(needle in x for x in res['problems']), res['problems'])
        return res

    def test_good_plan_reruns_exactly_the_affected_jobs(self):
        res = pt.check_rerun_plan(analysis(), good_plan())
        self.assertEqual(res['result'], 'pass', res)
        self.assertEqual((res['affected_items'], res['rerun_required']), (['T1', 'T2'], ['J1', 'J2']))     # T2 depends on T1: spread by dependency_core
        self.assertEqual((res['owner_acceptance'], res['pilot_evidence']), (False, False))

    def test_refuses_the_whole_pilot(self):
        self.refused(analysis(), good_plan(rerun_jobs=['J1', 'J2', 'J3', 'J4']), 'chạy lại toàn bộ pilot không theo phân tích')

    def test_refuses_skipping_an_affected_job(self):
        res = self.refused(analysis(), good_plan(rerun_jobs=['J1']), 'bỏ qua việc bị ảnh hưởng: J2')
        self.assertEqual(res['rerun_required'], ['J1', 'J2'])

    def test_refuses_an_unaffected_job_and_an_unknown_one(self):
        self.refused(analysis(), good_plan(rerun_jobs=['J1', 'J2', 'J3']), 'chạy lại việc không bị ảnh hưởng')
        self.refused(analysis(), good_plan(rerun_jobs=['J1', 'J2', 'J9']), 'not pilot jobs')

    def test_file_outside_the_map_affects_every_item_so_rerunning_all_is_allowed(self):
        a = analysis(changed_files=['onecrew/a.py', 'onecrew/new.py'])
        res = pt.check_rerun_plan(a, good_plan(rerun_jobs=['J1', 'J2', 'J3', 'J4'], supplements={t: ['x'] for t in ('T1', 'T2', 'T3', 'T4')}))
        self.assertEqual(res['result'], 'pass', res)
        self.assertEqual(res['outside_map'], ['onecrew/new.py'])
        self.refused(a, good_plan(), 'bỏ qua việc bị ảnh hưởng: J3, J4')

    def test_refuses_missing_analysis_and_missing_supplement_and_changed_hash(self):
        self.refused(analysis(), None, 'kế thừa không có phân tích')
        self.refused(analysis(), good_plan(supplements={'T1': ['chk-1']}), 'mục bị ảnh hưởng thiếu kiểm bổ sung: T2')
        res = self.refused(analysis(evidence=[{'job': 'J3', 'wheel_sha256': DST['wheel_sha256']}]), good_plan(), 'hash bằng chứng bị đổi')
        self.assertIn(DST['wheel_sha256'], ' '.join(res['problems']))
        self.assertIn(SRC['wheel_sha256'], ' '.join(res['problems']))

    def test_refuses_malformed_analysis(self):
        a = analysis()
        a['jobs'][0]['items'] = ['T9']
        self.refused(a, good_plan(), 'INPUT: pilot jobs must each name known items')
        self.refused(analysis(source=DST), good_plan(), 'đối chiếu sai cặp hash')

    def test_nothing_changed_requires_no_rerun(self):
        res = pt.check_rerun_plan(analysis(changed_files=[]), {'rerun_jobs': [], 'supplements': {}})
        self.assertEqual(res['result'], 'pass', res)


# ---- W38d: supplementary checks run on the final artifact ---------------------------------------------------------------

class SupplementRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        wheel = b'fixture wheel bytes'
        (self.root / 'final.whl').write_bytes(wheel)
        self.sha = hashlib.sha256(wheel).hexdigest()
        self.final = {'commit': 'f' * 40, 'wheel_sha256': self.sha}
        self.ref = self.write('final-receipt.json', dict(self.final, result='pass', at='2026-10-25T10:00:00+00:00', simulated=True,
                                                         provenance={'kind': 'fixture', 'source': 'test'}))

    def write(self, name, body):
        raw = json.dumps(body, sort_keys=True).encode('utf-8')
        (self.root / name).write_bytes(raw)
        return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def spec(self, **changes):
        ok = [sys.executable, '-c', 'import os,sys; sys.exit(0 if os.environ["ONECREW_FINAL_WHEEL_SHA256"] else 3)']
        s = {'schema': 1, 'mode': 'fixture', 'artifact': dict(self.final, wheel='final.whl'), 'final_receipt': self.ref,
             'affected': ['AC1'], 'checks': [{'id': 'c1', 'item': 'AC1', 'argv': ok}]}
        s.update(changes)
        return s

    def run_spec(self, spec):
        return pt.run_supplements(spec, self.root, self.root / 'out', now=lambda: '2026-10-25T11:00:00+00:00')

    def test_runs_the_check_and_writes_receipts_readable_by_finalgate(self):
        res = self.run_spec(self.spec())
        self.assertEqual((res['results'], res['all_pass']), ({'c1': 'pass'}, True))
        receipt = Evidence(self.root, True).read(res['receipts']['c1'])
        self.assertEqual((receipt['kind'], receipt['item'], receipt['result'], receipt['wheel_sha256'], receipt['simulated']),
                         ('supplement', 'AC1', 'pass', self.sha, True))
        self.assertEqual(receipt['check']['exit_code'], 0)
        self.assertEqual(receipt['provenance'], {'kind': 'fixture', 'source': 'wfkit.pilot_tools supp-run'})
        self.assertIs(res['owner_acceptance'], False)

    def test_failing_and_unstartable_checks_are_recorded_not_passed(self):
        bad = [sys.executable, '-c', 'import sys; sys.exit(7)']
        res = self.run_spec(self.spec(checks=[{'id': 'c1', 'item': 'AC1', 'argv': bad}, {'id': 'c2', 'item': 'AC1', 'argv': ['no-such-program-xyz']}]))
        self.assertEqual(res['results'], {'c1': 'fail', 'c2': 'blocked'})
        self.assertFalse(res['all_pass'])
        blocked = Evidence(self.root, True).read(res['receipts']['c2'])
        self.assertTrue(blocked['reason'])

    def test_refuses_a_wheel_that_differs_from_the_artifact(self):
        (self.root / 'final.whl').write_bytes(b'another wheel')
        with self.assertRaises(ValueError) as ctx:
            self.run_spec(self.spec())
        self.assertIn('differs from the artifact', str(ctx.exception))
        self.assertFalse((self.root / 'out').exists())                               # nothing ran, nothing written

    def test_refuses_a_receipt_with_another_wheel_sha(self):
        other = self.write('other.json', dict(self.final, wheel_sha256='e' * 64, result='pass', at='2026-10-25T10:00:00+00:00', simulated=True,
                                              provenance={'kind': 'fixture', 'source': 'test'}))
        with self.assertRaises(ValueError) as ctx:
            self.run_spec(self.spec(final_receipt=other))
        self.assertIn('wheel sha of the receipt given', str(ctx.exception))
        self.assertFalse((self.root / 'out').exists())

    def test_refuses_an_affected_item_without_a_check_and_a_real_mode_fixture_receipt(self):
        with self.assertRaises(ValueError) as ctx:
            self.run_spec(self.spec(affected=['AC1', 'AC2']))
        self.assertIn('mục bị ảnh hưởng thiếu kiểm bổ sung: AC2', str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            self.run_spec(self.spec(mode='real'))
        self.assertIn('simulated evidence cannot prove a real gate', str(ctx.exception))

    def test_refuses_a_tampered_receipt_reference(self):
        ref = dict(self.ref, sha256='0' * 64)
        with self.assertRaises(ValueError) as ctx:
            self.run_spec(self.spec(final_receipt=ref))
        self.assertIn('receipt hash changed', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
