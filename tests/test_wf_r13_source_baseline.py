"""R13 P1-S (Codex round 13): "outside the write scope" is judged against ONE baseline the engine authenticated for the attempt.

Codex reproduction on dev14: node C may write only a.txt; b.txt has UNCOMMITTED working content "USER UNCOMMITTED CONTENT" while HEAD
has "keep me"; the candidate puts b.txt back to the committed content -> pass, outside_scope=[] (R12 `_source_values` accepted the HEAD
blob OR the current working bytes). Applying that candidate loses the user's uncommitted change.

Invariants (docs/wf/r13-notes.md 1-3): the baseline is the source capture the ENGINE takes when the attempt starts (recorded in
node.started: the HEAD it observed and the working-tree bytes of the node's read+write scope, uncommitted edits, new files and deletions
included) overlaid with the outputs of the producers the engine recorded for that attempt (same rules as R12). HEAD, the working tree
and producers are not alternatives. A missing/unreadable capture, or one that cannot be tied to the observed HEAD, is unverifiable:
the candidate fails and is kept. Every case runs a real executor body inside engine.step on a real temporary Git project and is judged
by the real CandidateChecker through engine.verify; the candidate Git tree is inspected.
"""
import json
import subprocess
import unittest
from unittest import mock

from onecrew.common_verification import OUT_RULE, candidate_tree, snapshot_candidate
from onecrew.ledger import canonical
from onecrew.v2 import engine
from tests.test_wf_r12_parent_chain import ParentChainFixture, deleted

USER = 'USER UNCOMMITTED CONTENT\n'


class SourceBaselineFixture(ParentChainFixture):
    def committed(self, path):
        """The bytes of `path` at the project HEAD (what a 'revert to the committed content' candidate writes)."""
        return subprocess.check_output(['git', '-C', str(self.root), 'cat-file', 'blob', 'HEAD:' + path])

    def tree_file(self, nid, path):
        """`path` in the real candidate Git tree of the node's current artifact (None = absent)."""
        view = engine.state(self.ledger, 'P1')
        manifest = snapshot_candidate(self.ledger, view, nid, view['nodes'][nid]['artifact'])
        tree = candidate_tree(self.ledger, manifest)
        listed = subprocess.check_output(['git', '-C', str(self.root), 'ls-tree', tree, '--', path]).decode().strip()
        if not listed: return None
        return subprocess.check_output(['git', '-C', str(self.root), 'cat-file', 'blob', listed.split()[2]])

    def uncommitted(self, path='b.txt', text=USER):
        target = self.root / path
        if text is None: target.unlink()
        else: target.write_text(text)

    @staticmethod
    def edit(path, value):
        return lambda files: files.__setitem__(path, value)

    def without(self, path):
        """An executor-made candidate whose manifest leaves `path` out entirely (the tree then takes it from the base commit)."""
        def build(current):
            manifest = self.store.load(self.store.overlay(self.native_base(current), {current['write'][0]: b'node output\n'}, current['write']))
            manifest['files'].pop(path)
            return self.store.save(manifest)
        return build


class UncommittedOutsideChangesAreKept(SourceBaselineFixture):
    def test_s1_codex_reproduction_revert_to_committed_content_is_refused(self):
        self.start(); self.uncommitted()
        reverted = self.chain_worker([self.edit('b.txt', self.store.blob(self.committed('b.txt')))])
        out = self.assertOutFails(self.produce_and_verify('C', reverted), 'changed outside the write scope: b.txt')
        self.assertEqual(out['outside_scope'], ['b.txt'])
        self.assertEqual(self.tree_file('C', 'b.txt'), self.committed('b.txt'))   # the tree really holds the committed content
        self.assertEqual(out['rule'], OUT_RULE)

    def test_s1b_modify_delete_or_drop_from_the_manifest_is_refused(self):
        cases = {'modify': lambda: self.chain_worker([self.edit('b.txt', self.store.blob(b'other\n'))]),
                 'delete': lambda: self.chain_worker([deleted('b.txt')]),
                 'left out of the manifest (tree takes HEAD)': lambda: self.without('b.txt')}
        for number, (label, build) in enumerate(cases.items()):
            with self.subTest(label):
                if number: self.setUp()
                self.start(); self.uncommitted()
                out = self.assertOutFails(self.produce_and_verify('C', build()), 'changed outside the write scope: b.txt')
                self.assertEqual(out['outside_scope'], ['b.txt'])

    def test_s2_candidate_keeping_the_uncommitted_content_passes(self):
        self.start(); self.uncommitted()
        out = self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'C wrote this\n')])))
        self.assertEqual(out['outside_scope'], [])
        self.assertEqual(self.tree_file('C', 'b.txt').replace(b'\r\n', b'\n'), USER.encode())


class DeletedAndNewFilesOfTheBaseline(SourceBaselineFixture):
    def test_s3_a_file_the_user_deleted_is_not_resurrected(self):
        cases = {'committed content written back': lambda: self.chain_worker([self.edit('b.txt', self.store.blob(self.committed('b.txt')))]),
                 'left out of the manifest (tree takes HEAD)': lambda: self.without('b.txt')}
        for number, (label, build) in enumerate(cases.items()):
            with self.subTest(label):
                if number: self.setUp()
                self.start(); self.uncommitted(text=None)
                out = self.assertOutFails(self.produce_and_verify('C', build()), 'changed outside the write scope: b.txt')
                self.assertEqual(out['outside_scope'], ['b.txt'])
                self.assertIsNotNone(self.tree_file('C', 'b.txt'))

    def test_s3b_keeping_the_user_deletion_passes(self):
        self.start(); self.uncommitted(text=None)
        self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'C wrote this\n')])))
        self.assertIsNone(self.tree_file('C', 'b.txt'))

    def test_s3c_a_new_uncommitted_file_of_the_baseline_is_not_lost(self):
        cases = {'deleted in the manifest': lambda: self.chain_worker([deleted('n.txt')]),
                 'left out of the manifest': lambda: self.without('n.txt')}
        for number, (label, build) in enumerate(cases.items()):
            with self.subTest(label):
                if number: self.setUp()
                self.start(c_read=('a.txt', 'b.txt', 'n.txt')); self.uncommitted('n.txt', 'new user file\n')
                out = self.assertOutFails(self.produce_and_verify('C', build()), 'changed outside the write scope: n.txt')
                self.assertEqual(out['outside_scope'], ['n.txt'])
        self.setUp()
        self.start(c_read=('a.txt', 'b.txt', 'n.txt')); self.uncommitted('n.txt', 'new user file\n')
        self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'C wrote this\n')])))
        self.assertIsNotNone(self.tree_file('C', 'n.txt'))


class ProducerInheritanceOnTheCapturedBaseline(SourceBaselineFixture):
    def run_chain(self, d_build=None):
        """C then D on the uncommitted b.txt; `d_build` is a factory called once the fixture store exists."""
        self.start(); self.uncommitted()
        self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'C wrote this\n')])))
        return self.produce_and_verify('D', d_build() if d_build else self.worker([('c.txt', 'D wrote this\n')]))

    def test_s4_dependent_inheriting_the_recorded_producer_output_passes_and_integration_carries_it(self):
        self.assertEqual(self.assertPasses(self.run_chain())['outside_scope'], [])
        self.assertPasses(self.produce_and_verify('I', lambda current: self.native_base(current)))

    def test_s4b_producer_output_replaced_by_the_older_source_content_is_refused(self):
        older = lambda: self.chain_worker([self.edit('a.txt', self.store.blob(self.committed('a.txt')))], {'c.txt': b'D wrote this\n'})
        self.assertEqual(self.assertOutFails(self.run_chain(older), 'changed outside the write scope')['outside_scope'], ['a.txt'])

    def test_s4c_dependent_reverting_the_uncommitted_file_is_refused(self):
        build = lambda: self.chain_worker([self.edit('b.txt', self.store.blob(self.committed('b.txt')))], {'c.txt': b'D wrote this\n'})
        self.assertEqual(self.assertOutFails(self.run_chain(build), 'changed outside the write scope')['outside_scope'], ['b.txt'])

    def test_s5_integration_reverting_the_uncommitted_file_is_refused(self):
        self.assertPasses(self.run_chain())
        build = lambda current: self.intermediate(self.native_base(current), self.edit('b.txt', self.store.blob(self.committed('b.txt'))))
        self.assertEqual(self.assertOutFails(self.produce_and_verify('I', build), 'changed outside the write scope')['outside_scope'], ['b.txt'])

    def test_s5b_resume_with_uncommitted_outside_content_passes(self):
        self.start(); self.uncommitted()
        partial = lambda artifact, attempt: canonical({'kind': 'native-node-receipt', 'partial': True, 'attempt': attempt['id'],
                                                       'artifact': artifact, 'continuation': {'remaining': 'second half'}}).encode()
        self.assertEqual(self.step(self.worker([('a.txt', 'half\n')]), receipt=partial)['state'], 'continuing')
        self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'half\nand the rest\n')])))


class TheBaselineIsTheEngineCapture(SourceBaselineFixture):
    def test_s6_an_executor_capture_taken_after_the_attempt_started_is_not_the_baseline(self):
        # the user edits b.txt again after the engine started the attempt; the executor captures the newer bytes itself
        self.start(); self.uncommitted()
        def build(current):
            self.uncommitted(text='edited again during the run\n')
            return self.store.overlay(self.store.capture(self.root, ['a.txt', 'b.txt']), {'a.txt': b'node output\n'}, ['a.txt'])
        out = self.assertOutFails(self.produce_and_verify('C', build), 'changed outside the write scope: b.txt')
        self.assertEqual(out['outside_scope'], ['b.txt'])

    def test_s6b_head_moved_after_the_attempt_started_is_unverifiable(self):
        self.start()
        def build(current):
            (self.root / 'c.txt').write_text('committed during the run\n'); self.git('commit', '-qam', 'during the run')
            return self.store.overlay(self.store.capture(self.root, ['a.txt', 'b.txt']), {'a.txt': b'node output\n'}, ['a.txt'])
        self.assertOutFails(self.produce_and_verify('C', build), 'candidate provenance unverifiable')

    def test_s6c_head_moved_after_production_is_still_refused(self):
        self.start()
        self.step(self.worker([('a.txt', 'C wrote this\n')]))
        (self.root / 'c.txt').write_text('committed later\n'); self.git('commit', '-qam', 'later')
        self.assertOutFails(engine.verify(self.ledger, 'P1', 'C', self.checker), 'candidate provenance unverifiable', 'project HEAD')

    def test_s7_a_root_without_an_engine_recorded_capture_is_unverifiable(self):
        # what a node.started written before R13 looks like: no `source`
        self.start(); self.uncommitted()
        with mock.patch.object(engine, '_source_capture', lambda ledger, item: (None, 'simulated pre-R13 engine'), create=True):
            self.step(self.worker([('a.txt', 'C wrote this\n')]))
        out = self.assertOutFails(engine.verify(self.ledger, 'P1', 'C', self.checker), 'candidate provenance unverifiable')
        self.assertIn('source capture', out['reason'])
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['artifact'] is not None, True)   # the candidate is kept

    def test_s7b_an_unreadable_recorded_capture_is_unverifiable(self):
        self.start(); self.uncommitted()
        self.step(self.worker([('a.txt', 'C wrote this\n')]))
        key = engine.state(self.ledger, 'P1')['nodes']['C'].get('source')
        self.assertTrue(key, 'node.started records the engine source capture')
        path = self.store.root / 'manifests' / (key + '.json')
        path.write_text(path.read_text(encoding='utf-8').replace('"version":1', '"version":1,"x":1'), encoding='utf-8')
        out = self.assertOutFails(engine.verify(self.ledger, 'P1', 'C', self.checker), 'candidate provenance unverifiable')
        self.assertIn('source capture', out['reason'])

    def test_s8_a_pass_receipt_of_the_r12_rule_is_not_reused(self):
        self.start()
        self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'C wrote this\n')])))
        self.assertNotEqual(OUT_RULE, 'r12-declared-vs-candidate+authenticated-baseline')
        view = engine.state(self.ledger, 'P1'); record = view['nodes']['C']
        item = next(n for n in view['definition']['nodes'] if n['id'] == 'C')
        body = json.loads(self.store.read_blob(record['verification_receipt']))
        body['observed']['output_check']['rule'] = 'r12-declared-vs-candidate+authenticated-baseline'
        old = self.store.blob(canonical(body).encode())
        with self.ledger.transaction(write=True) as conn:
            engine._event(self.ledger, conn, engine.state(self.ledger, 'P1', conn), 'C', 'node.verification', result='pass', receipt=old)
        self.assertNotIn('reuse_basis', self.checker(item, record['artifact'], previous_receipt=old))


if __name__ == '__main__':
    unittest.main()
