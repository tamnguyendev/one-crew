"""T49c/d: real archived CLI on disposable namespace fixtures, never owner verbs.

N1..N7 exercise the rollback *gate*, not an installation swap or a live pilot.
"""
import hashlib
import io
import json
import shutil
import sqlite3
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.v2 import compat, compat_cli, compat_scan, plan
from tests import wf_oldversion as ov
from tests.wf_rollback import rollback_drill


class NamespaceCompatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = ov._short_runs()
        cls.old = ov.OldVersion(ov.archive('d3120c6', Path(__file__).resolve().parents[1], cls.runs))
        cls.projects = [ov.git_project(cls.runs, 'P' + str(n)) for n in (1, 2, 3)]
        cls.base = cls.runs / 'S2'
        cls.ids = {}
        for name in ('r1', 'r4', 'dup'):
            raw = cls.runs / (name + '.json')
            raw.write_text(json.dumps(ov.contract(name.upper())), encoding='utf-8')
            code, output = cls.old.run(cls.projects[0], cls.base, 'plan', 'propose', name,
                                       '--file', str(raw), '--author', 'codex-fixture')
            assert code == 0, output
        for index, name in ((1, 'r2'), (0, 'r3'), (1, 'dup'), (2, 'dup')):
            plan.propose(Ledger(cls.projects[index], cls.base), name, ov.contract(f'P{index + 1}-{name}'), 'codex-fixture')
        cls.pids = [ov.project_id(cls.base, p) for p in cls.projects]
        with sqlite3.connect(cls.base / 'ledger.sqlite3') as conn:
            conn.execute("UPDATE tasks SET request_key='plan:dup' WHERE project_id=? AND request_key='plan-ns:dup'", (cls.pids[2],))
        for label, pindex, key in (('R1', 0, 'plan:r1'), ('R4', 0, 'plan:r4'), ('R2', 1, 'plan-ns:r2'),
                                   ('R3', 0, 'plan-ns:r3'), ('DUPa', 0, 'plan:dup'),
                                   ('DUPb', 1, 'plan-ns:dup'), ('DUPk', 2, 'plan:dup')):
            cls.ids[label] = ov.anchor_id(cls.base, cls.pids[pindex], key)
        for label in ('R1', 'R2', 'R3', 'R4'):
            ov.make_approved(cls.base, cls.ids[label], label.lower())
        ov.insert_event(cls.base, cls.ids['R4'], 'plan.revoked', {'plan': 'r4', 'revision': 1, 'reason': 'fixture'})
        cls.active_relative = Path('plans') / cls.pids[1] / 'active-plan.json'
        cls.write_active(cls.base)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    @classmethod
    def write_active(cls, state, status='approved', path=None):
        path = path or state / cls.active_relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'project': str(cls.projects[1]), 'state_root': str(state),
            'plan': 'r2', 'anchor': 'plan-ns:r2', 'anchor_task': cls.ids['R2'], 'status': status,
            'expires': '2000-01-01T00:00:00+00:00'}), encoding='utf-8')

    def copy(self):
        state = self.runs / uuid.uuid4().hex[:8]
        shutil.copytree(self.base, state)
        self.write_active(state)
        return state

    def root(self, report, label):
        index, anchor = {'R1': (0, 'plan:r1'), 'R4': (0, 'plan:r4'), 'R2': (1, 'plan-ns:r2'),
                         'R3': (0, 'plan-ns:r3'), 'DUPa': (0, 'plan:dup'), 'DUPb': (1, 'plan-ns:dup'),
                         'DUPk': (2, 'plan:dup')}[label]
        return next(r for r in report['roots'] if r['project_id'] == self.pids[index] and r['anchor'] == anchor)

    def accept(self, state, label):
        ov.make_accepted(state, self.ids[label], 'dup' if label.startswith('DUP') else label.lower())

    def test_s2_properties_blocks_and_scan_preserves_files(self):
        state = self.copy()
        def snapshot():
            return {str(p.relative_to(state)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                    for p in state.rglob('*') if p.is_file()}
        before = snapshot()
        rep = compat_scan.scan(state)
        self.assertEqual(before, snapshot())
        self.assertEqual(len(rep['roots']), 7)
        self.assertEqual(rep['old_version'], 'd3120c6')
        self.assertEqual(rep['blocking'], {'read': 0, 'continue': 3, 'total': 3})
        for label, blocks in (('R1', []), ('R4', ['B2']), ('R2', ['B1']), ('R3', []),
                              ('DUPa', []), ('DUPb', []), ('DUPk', ['B3'])):
            root = self.root(rep, label)
            self.assertEqual([b['id'] for b in root['blocks']], blocks, label)
            if label in ('R2', 'R3', 'DUPb'):
                self.assertTrue(root['preserved_only'])
                self.assertEqual(root['properties'], {'unchanged': True, 'old_readable': False, 'old_continuable': False})
                self.assertNotIn('ns:', root['name'])
        self.assertTrue(rep['input_hashes'])

    def test_n1_to_n7_gate_branches(self):
        cases = [('N1', ('R4', 'DUPk'), None, {'B1'}), ('N2', ('R2', 'R4'), 'accepted', {'B3'}),
                 ('N3', ('R2',), 'accepted', {'B2', 'B3'}), ('N4', ('R4',), 'stopped_with_report', {'B1', 'B3'}),
                 ('N5', ('R2', 'R4', 'DUPk'), 'accepted', set()), ('N6', ('R4', 'DUPk'), 'remove', set()),
                 ('N7', ('R2', 'DUPk'), 'accepted', {'B2'})]
        for name, accepted, active, expected in cases:
            with self.subTest(name=name):
                state = self.copy()
                for label in accepted:
                    self.accept(state, label)
                if name == 'N4':
                    ov.make_stopped(state, self.ids['R2'], 'r2')
                    ov.make_stopped(state, self.ids['DUPk'], 'dup')
                if active == 'remove':
                    (state / self.active_relative).unlink()
                elif active:
                    self.write_active(state, active)
                result = rollback_drill(state)
                found = {b['id'] for r in result['scan']['roots'] for b in r['blocks']}
                self.assertEqual(found, expected)
                self.assertEqual(result['ran'], not expected)
                if 'R2' in accepted:
                    self.assertTrue(self.root(result['scan'], 'R2')['preserved_only'])

    def test_b1_either_copy_stale_acceptance_and_expiry(self):
        state = self.copy()
        self.accept(state, 'R2')
        # Acceptance alone and expired exports do not release B1.
        self.assertEqual(self.root(compat_scan.scan(state), 'R2')['blocks'][0]['id'], 'B1')
        self.write_active(state, 'accepted')
        project_copy = self.projects[1] / '.onecrew' / 'active-plan.json'
        self.write_active(state, 'stopped_with_report', project_copy)
        try:
            self.assertEqual(self.root(compat_scan.scan(state), 'R2')['blocks'][0]['id'], 'B1')
            project_copy.unlink()
            self.assertEqual(self.root(compat_scan.scan(state), 'R2')['blocks'], [])
        finally:
            project_copy.unlink(missing_ok=True)
        state = self.copy()
        self.write_active(state, 'accepted')
        self.assertEqual(self.root(compat_scan.scan(state), 'R2')['blocks'][0]['id'], 'B1')

    def test_real_old_namespace_reads_and_propose_split(self):
        state = self.copy()
        rep = compat_scan.scan(state)
        for command in (('plan', 'show'), ('plan', 'report'), ('plan', 'amend'), ('verdict', 'run')):
            args = [*command, 'r2']
            if command[0] == 'verdict':
                args = [*command, '--plan', 'r2', '--milestone', 'M1']
            if command[-1] == 'amend':
                args += ['--file', str(self.runs / 'r1.json'), '--reason', 'fixture', '--author', 'codex-fixture']
            code, out = self.old.run(self.projects[1], state, *args)
            self.assertNotEqual(code, 0, out)
            self.assertIn('No plan named', out)
        code, out = self.old.run(self.projects[1], state, 'plan', 'digest')
        self.assertEqual(code, 0, out)
        self.assertNotIn('P2-r2', out)
        for name, success in (('r2', True), ('dup', False)):
            fresh = self.copy()
            before_sha = ov._sha(fresh, self.ids['R2' if name == 'r2' else 'DUPb'])
            code, out = self.old.run(self.projects[1], fresh, 'plan', 'propose', name,
                                     '--file', str(self.runs / 'r1.json'), '--author', 'codex-fixture')
            self.assertEqual(code == 0, success, out)
            self.assertEqual(before_sha, ov._sha(fresh, self.ids['R2' if name == 'r2' else 'DUPb']))
            prediction = self.root(rep, 'R2' if name == 'r2' else 'DUPb')['commands']['plan propose <same name>']
            self.assertIn('creates a separate' if success else 'refused', prediction)
            if success:
                ov.anchor_id(fresh, self.pids[1], 'plan:r2')
                dual = self.root(compat_scan.scan(fresh), 'R2')
                self.assertIn('legacy plan:', dual['commands']['plan show'])
                self.assertTrue(dual['preserved_only'])

    def test_real_old_moved_legacy_writes_other_directory(self):
        state = self.copy()
        root = self.root(compat_scan.scan(state), 'DUPk')
        self.assertIn('B3', root['commands']['plan amend'])
        for command in ('show', 'report'):
            code, out = self.old.run(self.projects[2], state, 'plan', command, 'dup')
            self.assertEqual(code, 2 if command == 'show' else 0, out)
            self.assertIn('does not match the recorded hash', out)
        code, out = self.old.run(self.projects[2], state, 'plan', 'digest')
        self.assertEqual(code, 0, out)
        self.assertIn('?/?', out)
        global_v1 = (state / 'plans' / 'dup' / 'v1.json').read_bytes()
        code, out = self.old.run(self.projects[2], state, 'plan', 'amend', 'dup',
                                 '--file', str(self.runs / 'r1.json'), '--reason', 'fixture', '--author', 'codex-fixture')
        self.assertEqual(code, 0, out)
        self.assertTrue((state / 'plans' / 'dup' / 'v2.json').is_file())
        self.assertEqual((state / 'plans' / 'dup' / 'v1.json').read_bytes(), global_v1)
        self.assertFalse((state / 'plans' / self.pids[2] / 'dup' / 'v2.json').exists())

    def test_b3_requires_writable_target_and_own_acceptance(self):
        state = self.copy()
        self.accept(state, 'DUPa')
        self.assertEqual(self.root(compat_scan.scan(state), 'DUPk')['blocks'][0]['id'], 'B3')
        target = state / 'plans' / 'dup' / 'v2.json'
        target.write_text('{}', encoding='utf-8')
        root = self.root(compat_scan.scan(state), 'DUPk')
        self.assertEqual([b['id'] for b in root['blocks']], ['B2'])
        self.assertIn('refused', root['commands']['plan amend'])
        code, out = self.old.run(self.projects[2], state, 'plan', 'amend', 'dup',
                                 '--file', str(self.runs / 'r1.json'), '--reason', 'fixture', '--author', 'codex-fixture')
        self.assertNotEqual(code, 0, out)
        self.accept(state, 'DUPk')
        self.assertEqual(self.root(compat_scan.scan(state), 'DUPk')['blocks'], [])

    def test_invalid_existing_state_never_returns_zero_permission(self):
        for kind in ('malformed', 'unsupported', 'missing', 'broken-revision', 'broken-active'):
            with self.subTest(kind=kind):
                state = self.copy()
                if kind == 'malformed':
                    (state / 'ledger.sqlite3').write_bytes(b'not a database')
                elif kind == 'unsupported':
                    with sqlite3.connect(state / 'ledger.sqlite3') as conn:
                        conn.execute('PRAGMA user_version=999')
                elif kind == 'missing':
                    (state / 'ledger.sqlite3').unlink()
                elif kind == 'broken-revision':
                    (state / 'plans' / self.pids[1] / 'r2' / 'v1.json').write_text('{}', encoding='utf-8')
                else:
                    (state / self.active_relative).write_text('[]', encoding='utf-8')
                with self.assertRaises(LedgerError):
                    rollback_drill(state)
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = compat_cli.main(['--state-root', str(state), 'scan', '--json'])
                self.assertEqual(rc, 2)
                self.assertEqual(out.getvalue(), '')
                self.assertIn('error', err.getvalue())
        fresh = self.runs / uuid.uuid4().hex[:8]
        self.assertEqual(compat_scan.scan(fresh)['blocking']['total'], 0)
        self.assertFalse(fresh.exists())

    def test_contract_field_predictions_match_archived_validator(self):
        for field, value, blocked in (('advisor', {'provider': 'codex', 'model': 'fixture-model'}, False),
                                      ('future_contract_field', {}, True), ('scoped_unknown', None, True), ('adapter', None, True)):
            with self.subTest(field=field):
                state = self.copy()
                revision = state / 'plans' / 'r1' / 'v1.json'
                document = json.loads(revision.read_text(encoding='utf-8'))
                if field == 'adapter':
                    document['contract']['milestones'][0]['verifier'] = {'type': 'doc', 'config': {'docs': ['guide.md']}}
                elif field == 'scoped_unknown':
                    document['contract']['understanding']['unknowns'] = [{'id': 'U1', 'question': 'Which file?',
                        'status': 'open', 'closed_by': None, 'evidence': None, 'affected': ['I1'], 'required_by': 'approval'}]
                else:
                    document['contract'][field] = value
                sha = content_hash(document['contract'])
                document['content_sha'] = sha
                revision.write_text(json.dumps(document), encoding='utf-8')
                # Exact historical fixture; no owner command is involved.
                with sqlite3.connect(state / 'ledger.sqlite3') as conn:
                    rows = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind IN ('plan.proposed','plan.approved')",
                                        (self.ids['R1'],)).fetchall()
                    for seq, payload in rows:
                        payload = json.loads(payload)
                        payload['sha'] = sha
                        conn.execute('UPDATE events SET payload=? WHERE seq=?', (json.dumps(payload), seq))
                root = self.root(compat_scan.scan(state), 'R1')
                self.assertEqual([b['id'] for b in root['blocks']], ['B2'] if blocked else [])
                amended = dict(document['contract'], title='Changed title')
                raw = self.runs / (uuid.uuid4().hex[:8] + '.json')
                raw.write_text(json.dumps(amended), encoding='utf-8')
                code, out = self.old.run(self.projects[0], state, 'plan', 'amend', 'r1',
                                         '--file', str(raw), '--reason', 'fixture', '--author', 'codex-fixture')
                self.assertEqual(code != 0, blocked, out)

    def test_wrong_types_crash_actual_old_reader_even_after_acceptance(self):
        for kind, payload, field in (
                ('plan.amended', {'revision': 'one'}, 'revision'),
                ('verdict.receipt_issued', {'revision': 1, 'milestone': [], 'receipt': 'r'}, 'milestone'),
                ('verdict.receipt_issued', {'revision': 1, 'milestone': 'M1', 'receipt': []}, 'receipt')):
            with self.subTest(field=field):
                state = self.copy()
                self.accept(state, 'R1')
                ov.insert_event(state, self.ids['R1'], kind, payload)
                for args in (('plan', 'show', 'r1'), ('plan', 'digest')):
                    code, output = self.old.run(self.projects[0], state, *args)
                    self.assertEqual(code, 1, output)
                    self.assertIn('TypeError', output)
                root = self.root(compat_scan.scan(state), 'R1')
                self.assertEqual(root['status'], 'closed')
                self.assertEqual([b['id'] for b in root['blocks']], ['B4'])
                self.assertFalse(root['properties']['old_readable'])
                self.assertIn(field + ' expected ', root['blocks'][0]['why'])
                self.assertIn('TypeError', root['commands']['plan show'])
                with self.assertRaisesRegex(LedgerError, field + ' expected '):
                    compat.check_write(kind, payload, 'plan:r1')


class ClassZeroTypeTests(unittest.TestCase):
    def test_every_required_field_keeps_exact_type_and_allows_additions(self):
        valid = {'revision': 1, 'milestone': 'M1', 'receipt': 'r', 'new_field': {'anything': [None, 2]}}
        for kind, fields in compat.CLASS_0_REQUIRED.items():
            self.assertIsNone(compat.check_write(kind, valid, 'plan:r1'))
            for field in fields:
                bad_values = ('one', True, 1.0, [], {}, None) if field == 'revision' else (1, True, [], {}, None)
                for value in bad_values:
                    with self.subTest(kind=kind, field=field, value=value):
                        payload = dict(valid, **{field: value})
                        self.assertFalse(compat.class0_payload_ok(kind, payload))
                        with self.assertRaisesRegex(LedgerError, field):
                            compat.check_write(kind, payload, 'plan:r1')
                        # Namespace roots remain outside the archived reader.
                        self.assertIsNone(compat.check_write(kind, payload, 'plan-ns:r1'))


if __name__ == '__main__':
    unittest.main()
