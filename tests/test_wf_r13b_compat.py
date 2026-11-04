"""R13b (round 13b, reviewer item 2): continuing work recorded by a build before R13.

R13 judges "outside the write scope" against the source capture the engine records in node.started (`source`). A node.started
written before R13 has none. These cases lock the compatibility guarantees (docs/wf/r13b-compat.md) on fixtures, without a model:
the pre-R13 admission is simulated by an engine whose capture records nothing (`_source_capture` -> (None, None): the payload then
carries no capture and no capture error, as a dev14 node.started), and a dev14 pass verdict by the node.verification event it wrote
(R12 rule). The real dev14-made data is exercised by D:/OneCrewRuns/wf-dev-tools/compat/run_dev15.py (results in the doc).

  1. old evidence is never legitimized: an old candidate (produced, or verified under R12) re-checked on R13 is unverifiable -> fail,
     the candidate and its old verdict stay recorded; the same old candidate verified again stays fail;
  2. work continues only through NEW attempts that carry the capture: a partial old attempt is continued by a new attempt
     (`continues` = the old attempt), a failed old candidate by the existing bounded repair, a pre-R13 integration by an internal
     revision that re-issues it; nothing else re-runs and the spent calls stay spent;
  3. an old candidate that reverted the user's uncommitted change outside its scope cannot carry that revert into the R13
     integration, and the handoff leaves the project untouched;
  4. a pre-R13 integration verified under R12 is not handed off by R13 (project unchanged); after re-issuing it, it is.
"""
import json
import subprocess
import unittest
from unittest import mock

from onecrew import budget_core
from onecrew.common_handoff import handoff
from onecrew.ledger import LedgerError, canonical
from onecrew.v2 import engine, repair_tasks, internal_plan
from tests.test_wf_r12_parent_chain import ParentChainFixture

USER = 'USER UNCOMMITTED CONTENT\n'
R12_RULE = 'r12-declared-vs-candidate+authenticated-baseline'


class PreR13Fixture(ParentChainFixture):
    def pre_r13(self):
        """An engine before R13: node.started records no source capture (no `source`, no `source_error`)."""
        return mock.patch.object(engine, '_source_capture', lambda ledger, item: (None, None))

    def old_pass(self, nid):
        """The node.verification pass a dev14 engine wrote for the current artifact (R12 rule, no capture)."""
        view = engine.state(self.ledger, 'P1'); record = view['nodes'][nid]
        item = next(n for n in view['definition']['nodes'] if n['id'] == nid)
        body = {'kind': 'node-verifier-receipt', 'root': view['root'], 'node': nid, 'internal_revision': view['internal_revision'],
                'generation': record['generation'], 'artifact': record['artifact'], 'inputs': record['inputs'], 'evidence_errors': [],
                'observed': {'artifact': record['artifact'], 'checks': [{'id': c['id'], 'result': 'pass'} for c in item['checks']],
                             'output_check': {'id': 'OUT', 'rule': R12_RULE, 'result': 'pass'}}, 'result': 'pass'}
        with self.ledger.transaction(write=True) as conn:
            engine._event(self.ledger, conn, engine.state(self.ledger, 'P1', conn), nid, 'node.verification', result='pass',
                          receipt=self.store.blob(canonical(body).encode()))

    def started(self, nid):
        with self.ledger.transaction() as conn:
            root = engine.state(self.ledger, 'P1', conn)['root']
            rows = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='node.started' ORDER BY seq", (root,)).fetchall()
        return [p for p in (json.loads(r['payload']) for r in rows) if p['node'] == nid]

    def used_calls(self):
        with self.ledger.transaction() as conn:
            return budget_core.group(conn, engine.state(self.ledger, 'P1', conn)['root'])['used_calls']

    def recheck(self, nid):
        view = engine.state(self.ledger, 'P1')
        item = next(n for n in view['definition']['nodes'] if n['id'] == nid)
        return self.checker(item, view['nodes'][nid]['artifact'])['output_check']

    def committed(self):
        return subprocess.check_output(['git', '-C', str(self.root), 'cat-file', 'blob', 'HEAD:b.txt'])

    def project(self):
        return {name: (self.root / name).read_text() for name in ('a.txt', 'b.txt', 'c.txt')} | {'head': self.git('rev-parse', 'HEAD')}


class OldEvidenceIsNotLegitimized(PreR13Fixture):
    def test_old_produced_candidate_fails_and_is_repaired_by_a_new_attempt(self):
        self.start()
        with self.pre_r13():
            self.step(self.worker([('a.txt', 'C wrote this\n')]))
        old = engine.state(self.ledger, 'P1')['nodes']['C']
        self.assertIsNone(old.get('source')); self.assertEqual(self.started('C')[0].get('source'), None)
        for _ in range(2):                                   # the same old candidate, verified as is, twice
            result = engine.verify(self.ledger, 'P1', 'C', self.checker)
            out = self.assertOutFails(result, 'candidate provenance unverifiable')
            self.assertIn('node.started written before R13', out['reason'])
            self.assertEqual(result['recovery']['disposition'], 'repair')
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['artifact'], old['artifact'])   # the candidate is kept
        self.store.load(old['artifact'])                                                                # and still loads
        receipt = engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='pre-R13 candidate has no engine capture', evidence=[receipt])
        self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'C wrote this\n')])))
        attempts = self.started('C')
        self.assertEqual([bool(p.get('source')) for p in attempts], [False, True])
        self.assertNotEqual(attempts[0]['attempt'], attempts[1]['attempt'])
        self.assertEqual(self.used_calls(), 2)

    def test_old_verified_node_rechecked_is_unverifiable_and_its_record_is_kept(self):
        self.start()
        with self.pre_r13():
            self.step(self.worker([('a.txt', 'C wrote this\n')]))
        self.old_pass('C')
        out = self.recheck('C')
        self.assertEqual(out['result'], 'fail'); self.assertIn('candidate provenance unverifiable', out['reason'])
        record = engine.state(self.ledger, 'P1')['nodes']['C']
        self.assertEqual((record['state'], record['verification_result']), ('verified', 'pass'))   # history is not rewritten
        with self.assertRaisesRegex(LedgerError, 'Only the current produced node can be verified'):
            engine.verify(self.ledger, 'P1', 'C', self.checker)


class WorkContinuesThroughNewAttempts(PreR13Fixture):
    def test_partial_old_attempt_is_continued_by_a_new_captured_attempt(self):
        self.start()
        partial = lambda artifact, attempt: canonical({'kind': 'native-node-receipt', 'partial': True, 'attempt': attempt['id'],
                                                       'artifact': artifact, 'continuation': {'remaining': 'second half'}}).encode()
        with self.pre_r13():
            first = self.step(self.worker([('a.txt', 'half\n')]), receipt=partial)
        self.assertEqual(first['state'], 'continuing')
        self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'half\nand the rest\n')])))
        attempts = self.started('C')
        self.assertEqual([bool(p.get('source')) for p in attempts], [False, True])
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['continues'], attempts[0]['attempt'])
        self.assertEqual(self.used_calls(), 2)

    def test_old_revert_of_an_uncommitted_change_does_not_reach_the_integration_or_the_project(self):
        self.start(); (self.root / 'b.txt').write_text(USER)
        with self.pre_r13():                                  # C reverts the user's uncommitted b.txt: dev14 passed this (R13 P1-S)
            self.step(self.chain_worker([lambda files: files.__setitem__('b.txt', self.store.blob(self.committed()))]))
        self.old_pass('C')
        self.assertEqual(self.recheck('C')['result'], 'fail')
        before = self.project()
        self.assertPasses(self.produce_and_verify('D', self.worker([('c.txt', 'D wrote this\n')])))
        self.assertPasses(self.produce_and_verify('I', lambda current: self.native_base(current)))
        self.assertEqual([bool(p.get('source')) for p in self.started('I')], [True])
        self.assertEqual(len(self.started('C')), 1)                               # C is not re-run
        with self.assertRaisesRegex(LedgerError, 'outside its internal write provenance'):
            handoff(self.ledger, 'P1', control=self.control)                     # the user's b.txt is not the base: nothing applied
        self.assertEqual(self.project(), before); self.assertEqual(before['b.txt'], USER)

    def test_pre_r13_integration_is_not_handed_off_until_it_is_re_issued(self):
        self.start()
        with self.pre_r13():
            self.step(self.worker([('a.txt', 'C wrote this\n')])); self.old_pass('C')
            self.step(self.worker([('c.txt', 'D wrote this\n')])); self.old_pass('D')
            self.step(lambda current: self.native_base(current)); self.old_pass('I')
        self.assertTrue(engine.verification_ready(self.ledger, 'P1'))
        before = self.project()
        with self.assertRaisesRegex(LedgerError, 'failed its approved root checks; project unchanged'):
            handoff(self.ledger, 'P1', control=self.control)
        self.assertEqual(self.project(), before)
        view = engine.state(self.ledger, 'P1')
        nodes = json.loads(json.dumps(view['definition']['nodes']))
        next(n for n in nodes if n['integration'])['goal'] += ' (re-issued on the R13 build)'
        internal_plan.revise(self.ledger, 'P1', nodes, reason='Re-issue the pre-R13 integration', evidence=['a.txt:1'],
                             expected_revision=view['internal_revision'])
        self.assertPasses(self.produce_and_verify('I', lambda current: self.native_base(current)))
        self.assertEqual(handoff(self.ledger, 'P1', control=self.control)['state'], 'delivered')
        self.assertEqual((self.root / 'a.txt').read_text().replace('\r\n', '\n'), 'C wrote this\n')
        self.assertEqual([len(self.started(n)) for n in ('C', 'D', 'I')], [1, 1, 2])   # only the integration re-ran
        self.assertEqual(self.used_calls(), 4)


if __name__ == '__main__':
    unittest.main()
