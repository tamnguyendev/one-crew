"""R12 (Codex round 12, P1-B): "outside the write scope" is judged against a baseline the ENGINE authenticated, never against the
`parent` chain a candidate declares about itself.

Codex reproduction: node C may write a.txt and read b.txt; an executor builds a parent snapshot that already deleted b.txt and overlays
a.txt on top of it; the real candidate tree lacks b.txt but R11 compared it only with its immediate (self-declared) parent: pass,
outside_scope=[]. The authenticated baseline (docs/wf/r12-notes.md invariant 4) is: the project source at the candidate's base commit,
which must be the project HEAD the engine observes (plus the project's current working bytes of that file), and the outputs of the
producers the engine itself recorded for this attempt (node.started inputs) at the producer's current artifact and generation. Every
candidate here is built by an executor body inside engine.step on a real temporary Git project and judged by the real CandidateChecker
through engine.verify; nothing is applied to the project.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from onecrew.common_verification import OUT_RULE
from onecrew.ledger import canonical
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine
from tests.test_wf_engine import node
from tests.test_wf_r12_output_contract import R12Fixture


def deleted(path):
    return lambda files: files.__setitem__(path, None)


class ParentChainFixture(R12Fixture):
    def setUp(self):
        R12Fixture.setUp(self)
        self.files.update({'a.txt': 'source a\n', 'b.txt': 'keep me\n', 'c.txt': 'third\n'})

    def nodes(self, c_write=('a.txt',), c_read=('a.txt', 'b.txt')):
        c = node('C', write=c_write); c['read'] = list(c_read)
        d = node('D', ['C'], write=('c.txt',)); d['read'] = ['a.txt', 'b.txt']        # D reads what C writes (inherited input)
        i = node('I', ['C', 'D'], integration=True, write=()); i['read'] = ['a.txt', 'b.txt', 'c.txt']
        return [c, d, i]

    def intermediate(self, base, edit, **extra):
        """An executor-made intermediate snapshot: a copy of `base` with raw manifest edits (bypassing the artifact API)."""
        manifest = self.store.load(base)
        working = {path: row['working'] for path, row in manifest['files'].items()}
        edit(working)
        for path, value in working.items():
            if path not in manifest['files']: manifest['files'][path] = {'working': None, 'index': []}
            manifest['files'][path]['working'] = value
        manifest['parent'] = base
        manifest.update(extra)
        return self.store.save(manifest)

    def chain_worker(self, edits, change=None):
        """Native base -> one intermediate parent per edit -> overlay of the node's own write change."""
        def build(current):
            key = self.native_base(current)
            for edit in edits: key = self.intermediate(key, edit)
            return self.store.overlay(key, change or {current['write'][0]: b'node output\n'}, current['write'])
        return build

    def produce_and_verify(self, nid, build):
        self.step(build)
        return engine.verify(self.ledger, 'P1', nid, self.checker)

    def start(self, **kw):
        self.prepare(); self.revise(self.nodes(**kw))


class HiddenOutsideChangesAreRefused(ParentChainFixture):
    def test_b1_codex_reproduction_deletion_hidden_in_an_intermediate_parent(self):
        self.start()
        out = self.assertOutFails(self.produce_and_verify('C', self.chain_worker([deleted('b.txt')])), 'changed outside the write scope', 'b.txt')
        self.assertEqual(out['outside_scope'], ['b.txt'])

    def test_b2_modify_delete_add_through_several_intermediate_parents(self):
        cases = {'modify': ([lambda f: f.__setitem__('b.txt', self.store.blob(b'tampered\n'))], ['b.txt']),
                 'delete two levels up': ([lambda f: None, deleted('b.txt'), lambda f: None], ['b.txt']),
                 'add a file outside any scope': ([lambda f: f.__setitem__('z.txt', self.store.blob(b'new\n'))], ['z.txt']),
                 'modify then restore is clean': ([deleted('b.txt'), lambda f: f.__setitem__('b.txt', self.store.blob(b'keep me\n'))], [])}
        for number, (label, (edits, outside)) in enumerate(cases.items()):
            with self.subTest(label):
                if number: self.setUp()
                self.start()
                result = self.produce_and_verify('C', self.chain_worker(edits))
                if outside: self.assertEqual(self.assertOutFails(result, 'changed outside the write scope')['outside_scope'], outside)
                else: self.assertPasses(result)

    def test_b3_no_parent_at_all_but_an_outside_change_is_refused(self):
        self.start()
        def build(current):
            manifest = self.store.load(self.store.capture(self.root, ['a.txt', 'b.txt']))
            manifest['files']['a.txt']['working'] = self.store.blob(b'node output\n')
            manifest['files']['b.txt']['working'] = None
            return self.store.save(manifest)                                  # parent: None
        self.assertEqual(self.assertOutFails(self.produce_and_verify('C', build), 'changed outside the write scope')['outside_scope'], ['b.txt'])

    def test_b4_parent_switched_to_a_snapshot_not_from_this_source(self):
        self.start()
        with tempfile.TemporaryDirectory() as other:
            subprocess.check_output(['git', 'clone', '-q', str(self.root), other], stderr=subprocess.PIPE)
            Path(other, 'b.txt').write_text('other source\n')
            foreign = Snapshots(self.ledger.state_root).capture(other, ['a.txt', 'b.txt'])
            def build(current):
                manifest = self.store.load(self.store.overlay(foreign, {'a.txt': b'node output\n'}, ['a.txt']))
                manifest['source'] = str(self.root.resolve())                 # the candidate claims this project; its parent does not
                return self.store.save(manifest)
            out = self.assertOutFails(self.produce_and_verify('C', build), 'changed outside the write scope', 'provenance')
        self.assertEqual(out['outside_scope'], ['b.txt'])

    def test_b5_parent_chain_missing_or_unreadable_is_refused(self):
        for number, label in enumerate(('missing', 'corrupt', 'link on another base commit')):
            with self.subTest(label):
                if number: self.setUp()
                self.start()
                def build(current, label=label):
                    base = self.native_base(current)
                    manifest = self.store.load(self.store.overlay(base, {'a.txt': b'node output\n'}, ['a.txt']))
                    if label == 'missing':
                        manifest['parent'] = 'f' * 64
                    elif label == 'corrupt':
                        broken = self.intermediate(base, lambda f: None)
                        path = self.store.root / 'manifests' / (broken + '.json')
                        path.write_text(path.read_text(encoding='utf-8').replace('"version":1', '"version":1,"x":1'), encoding='utf-8')
                        manifest['parent'] = broken
                    else:                                                       # content addressing makes a real cycle impossible
                        manifest['parent'] = self.intermediate(base, lambda f: None, head=self.git('rev-list', '--max-parents=0', 'HEAD'))
                    return self.store.save(manifest)
                self.assertOutFails(self.produce_and_verify('C', build), 'candidate provenance unverifiable')

    def test_b6_base_commit_switched_hides_a_file_outside_the_manifest(self):
        self.start()
        first = self.git('rev-list', '--max-parents=0', 'HEAD')                 # the fixture's first commit has no c.txt
        def build(current):
            manifest = self.store.load(self.store.overlay(self.native_base(current), {'a.txt': b'node output\n'}, ['a.txt']))
            manifest['head'] = first
            return self.store.save(manifest)
        self.assertOutFails(self.produce_and_verify('C', build), 'candidate provenance unverifiable', 'project HEAD')


class AuthenticatedInheritancePasses(ParentChainFixture):
    def run_chain(self, d_build=None):
        self.start()
        self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'C wrote this\n')])))
        return self.produce_and_verify('D', d_build or self.worker([('c.txt', 'D wrote this\n')]))

    def test_c1_dependent_inherits_the_recorded_producer_output_and_integration_carries_it(self):
        out = self.assertPasses(self.run_chain())
        self.assertEqual(out['outside_scope'], [])
        out = self.assertPasses(self.produce_and_verify('I', lambda current: self.native_base(current)))
        self.assertEqual(out['outside_scope'], [])
        self.assertEqual(out['rule'], OUT_RULE)

    def test_c2_dependent_built_directly_on_the_producer_artifact_passes(self):
        # inheritance through a parent chain is not banned: the chain is a producer artifact the engine recorded for this attempt
        def build(current):
            produced = current['input_artifacts']['C']['artifact']
            manifest = self.store.load(produced)
            if 'c.txt' not in manifest['files']:
                manifest['files']['c.txt'] = {'working': self.store.blob(b'third\n'), 'index': []}
                manifest['parent'] = produced; produced = self.store.save(manifest)
            return self.store.overlay(produced, {'c.txt': b'D wrote this\n'}, ['c.txt'])
        self.assertPasses(self.run_chain(build))

    def test_c3_producer_content_from_another_artifact_is_refused(self):
        def build(current):
            key = self.native_base(current)
            key = self.intermediate(key, lambda f: f.__setitem__('a.txt', self.store.blob(b'not what C produced\n')))
            return self.store.overlay(key, {'c.txt': b'D wrote this\n'}, ['c.txt'])
        self.assertEqual(self.assertOutFails(self.run_chain(build), 'changed outside the write scope')['outside_scope'], ['a.txt'])

    def test_c4_producer_invalidated_after_the_dependent_started_is_refused(self):
        self.start()
        self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'C wrote this\n')])))
        self.step(self.worker([('c.txt', 'D wrote this\n')]))
        with self.ledger.transaction(write=True) as conn:                        # C moves to a new generation (a resume/replan of C)
            view = engine.state(self.ledger, 'P1', conn)
            engine._event(self.ledger, conn, view, 'C', 'node.resumed', reason='fixture: producer invalidated', budget_reset=False)
        view = engine.state(self.ledger, 'P1')
        item = next(n for n in view['definition']['nodes'] if n['id'] == 'D')
        observed = self.checker(item, view['nodes']['D']['artifact'])          # the checker itself; engine.verify holds D behind C
        out = observed['output_check']
        self.assertEqual(out['result'], 'fail', json.dumps(out))
        self.assertIn('changed outside the write scope', out['reason'])
        self.assertEqual(out['outside_scope'], ['a.txt'])

    def test_c5_resume_of_the_same_node_continues_from_its_partial_candidate(self):
        self.start()
        partial = lambda artifact, attempt: canonical({'kind': 'native-node-receipt', 'partial': True, 'attempt': attempt['id'],
                                                       'artifact': artifact, 'continuation': {'remaining': 'second half'}}).encode()
        first = self.step(self.worker([('a.txt', 'half\n')]), receipt=partial)
        self.assertEqual(first['state'], 'continuing')
        # the continuation answers on top of the resumed candidate (the native base carries it)
        out = self.assertPasses(self.produce_and_verify('C', self.worker([('a.txt', 'half\nand the rest\n')])))
        self.assertEqual(out['declared'], {'a.txt': 'content'})

    def test_c6_resume_built_directly_on_the_engine_recorded_partial_candidate(self):
        self.start()
        partial = lambda artifact, attempt: canonical({'kind': 'native-node-receipt', 'partial': True, 'attempt': attempt['id'],
                                                       'artifact': artifact, 'continuation': {'remaining': 'second half'}}).encode()
        self.assertEqual(self.step(self.worker([('a.txt', 'half\n')]), receipt=partial)['state'], 'continuing')
        build = lambda current: self.store.overlay(current['resume_artifact'], {'a.txt': b'half\nand the rest\n'}, ['a.txt'])
        self.assertPasses(self.produce_and_verify('C', build))
        # the same continuation with a deletion hidden in a parent between the partial candidate and the answer is refused
        self.setUp(); self.start()
        self.assertEqual(self.step(self.worker([('a.txt', 'half\n')]), receipt=partial)['state'], 'continuing')
        build = lambda current: self.store.overlay(self.intermediate(current['resume_artifact'], deleted('b.txt')), {'a.txt': b'rest\n'}, ['a.txt'])
        self.assertEqual(self.assertOutFails(self.produce_and_verify('C', build), 'changed outside the write scope')['outside_scope'], ['b.txt'])


class ReceiptReuse(ParentChainFixture):
    def test_r1_a_pass_receipt_of_an_older_output_rule_is_never_reused(self):
        self.start()
        result = self.produce_and_verify('C', self.worker([('a.txt', 'C wrote this\n')]))
        self.assertPasses(result)
        view = engine.state(self.ledger, 'P1')
        item = next(n for n in view['definition']['nodes'] if n['id'] == 'C')
        record = view['nodes']['C']
        reused = self.checker(item, record['artifact'], previous_receipt=record['verification_receipt'])
        self.assertIn('reuse_basis', reused)                                    # the current rule's receipt is reusable
        body = json.loads(self.store.read_blob(record['verification_receipt']))
        body['observed']['output_check'].pop('rule')                            # what an R11 receipt looks like
        old = self.store.blob(canonical(body).encode())
        with self.ledger.transaction(write=True) as conn:
            engine._event(self.ledger, conn, engine.state(self.ledger, 'P1', conn), 'C', 'node.verification', result='pass', receipt=old)
        again = self.checker(item, record['artifact'], previous_receipt=old)
        self.assertNotIn('reuse_basis', again)
        self.assertEqual(again['output_check']['rule'], OUT_RULE)


if __name__ == '__main__':
    unittest.main()
