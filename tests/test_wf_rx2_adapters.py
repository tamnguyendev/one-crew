"""W39/T14b actual local adapters on disposable data, not external provider proof."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan, verdict
from onecrew.v2.verifiers import artifact, data, doc, ops, port
from tests import wf_oldversion as ov
from tests.test_v2_l1 import Fixture, plan_json


DATA = {'path': 'output.csv', 'columns': {'id': 'integer', 'amount': 'number', 'active': 'boolean'}, 'key': ['id'],
        'row_count': 2, 'reconcile': {'path': 'input.csv', 'compare': ['amount', 'active'], 'totals': ['amount']},
        'samples': [{'key': {'id': 2}, 'values': {'amount': 0.2, 'active': False}}]}
TABLE = 'id,amount,active\n1,0.1,true\n2,0.2,false\n'
REQUEST = hashlib.sha256(b'update cache to version 2').hexdigest()
OPS = {'pre': 'pre.json', 'post': 'post.json', 'receipt': 'operation.json', 'reconcile': 'observation.json',
       'operation_id': 'op-1', 'request_sha': REQUEST,
       'preconditions': [{'path': ['version'], 'equals': 1}],
       'postconditions': [{'path': ['version'], 'equals': 2}]}


def write_ops(root, **receipt_changes):
    def save(name, value):
        raw = json.dumps(value, sort_keys=True).encode()
        (root / name).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()
    before = save('pre.json', {'version': 1})
    after = save('post.json', {'version': 2})
    receipt = {'operation_id': 'op-1', 'request_sha': REQUEST, 'status': 'succeeded', 'pre_sha': before, 'post_sha': after}
    receipt.update(receipt_changes)
    issued = save('operation.json', receipt)
    save('observation.json', {'operation_id': 'op-1', 'request_sha': REQUEST, 'status': 'succeeded',
                              'observation_id': 'observation-2', 'receipt_sha': issued, 'post_sha': after})


def milestone(kind, config):
    return {'id': 'M1', 'title': 'Check output', 'max_repairs': 2,
            'verifier': {'type': kind, 'config': config}, 'covers': ['O1']}


class LocalChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'source'
        self.root.mkdir()
        self.ledger = Ledger(self.root, Path(self.temp.name) / 'state')
        for name in ('input.csv', 'output.csv'):
            (self.root / name).write_text(TABLE, encoding='utf-8')
        write_ops(self.root)

    def check(self, kind, config):
        module = port.get(kind)
        return module.run(module.validate_config(copy.deepcopy(config), 'test'),
                          port.Port(self.root, port.authority(None, 'test'), kind))

    def receipt(self, kind, config):
        m = milestone(kind, port.normalize(kind, config, 'test'))
        return port.run(self.ledger, 'P1', 1, 'a' * 64, m, self.root)

    def test_data_csv_schema_reconcile_samples_and_exact_decimal_control(self):
        report = self.check('data', DATA)
        self.assertEqual([c['id'] for c in report['checks']], ['schema', 'row_count', 'reconcile', 'samples'])
        self.assertTrue(all(c['ok'] for c in report['checks']))
        key, receipt = self.receipt('data', DATA)
        self.assertEqual(port.expected_result(receipt), 'pass')
        self.assertEqual(receipt['artifact_kind'], 'snapshot')
        self.assertTrue(artifact.validate_evidence(self.ledger, receipt['artifact_sha'], receipt))
        self.assertEqual(json.loads(Snapshots(self.ledger.state_root).read_blob(key)), receipt)

    def test_data_negative_schema_duplicates_missing_rows_values_samples(self):
        for text, check in (
                (TABLE.replace('id,amount,active', 'id,other,active'), 'schema'),
                (TABLE.replace('2,0.2,false', '1,0.2,false'), 'schema'),
                (TABLE.replace('2,0.2,false', '2,nan,false'), 'schema'),
                (TABLE.replace('2,0.2,false', '2,0.3,false'), 'reconcile'),
                (TABLE.replace('2,0.2,false\n', ''), 'reconcile')):
            with self.subTest(text=text):
                (self.root / 'output.csv').write_text(text, encoding='utf-8')
                report = self.check('data', DATA)
                self.assertFalse(next(c for c in report['checks'] if c['id'] == check)['ok'])
                self.assertTrue(report['findings'])
        (self.root / 'output.csv').write_text(TABLE, encoding='utf-8')
        config = copy.deepcopy(DATA)
        config['samples'][0]['values']['amount'] = 99
        self.assertFalse(next(c for c in self.check('data', config)['checks'] if c['id'] == 'samples')['ok'])

    def test_data_json_schema_strict_types_and_duplicate_object_keys(self):
        config = dict(DATA, path='output.json', format='json', reconcile=None)
        good = [{'id': 1, 'amount': 0.1, 'active': True}, {'id': 2, 'amount': 0.2, 'active': False}]
        (self.root / 'output.json').write_text(json.dumps(good), encoding='utf-8')
        self.assertTrue(all(c['ok'] for c in self.check('data', config)['checks']))
        for raw in ('[{"id":1,"id":2,"amount":0.2,"active":false}]',
                    '[{"id":true,"amount":0.2,"active":false}]',
                    '[{"id":1,"amount":NaN,"active":false}]'):
            (self.root / 'output.json').write_text(raw, encoding='utf-8')
            self.assertFalse(self.check('data', config)['checks'][0]['ok'])

    def test_ops_real_local_evidence_and_each_negative(self):
        self.assertTrue(all(c['ok'] for c in self.check('ops', OPS)['checks']))
        _, receipt = self.receipt('ops', OPS)
        self.assertEqual(port.expected_result(receipt), 'pass')
        self.assertEqual(receipt['calls'], 0)
        for field, value, check in (('operation_id', 'other', 'receipt'), ('request_sha', 'f' * 64, 'receipt'),
                                     ('pre_sha', 'f' * 64, 'receipt'), ('post_sha', 'f' * 64, 'receipt'),
                                     ('status', 'failed', 'receipt')):
            write_ops(self.root, **{field: value})
            self.assertFalse(next(c for c in self.check('ops', OPS)['checks'] if c['id'] == check)['ok'])
        write_ops(self.root)
        for name, changes, check in (('pre.json', {'version': 0}, 'preconditions'),
                                     ('post.json', {'version': True}, 'postconditions'),
                                     ('observation.json', {'receipt_sha': 'f' * 64}, 'reconcile')):
            write_ops(self.root)
            target = self.root / name
            value = json.loads(target.read_text())
            value.update(changes)
            target.write_text(json.dumps(value), encoding='utf-8')
            self.assertFalse(next(c for c in self.check('ops', OPS)['checks'] if c['id'] == check)['ok'])

    def test_ops_unknown_pending_never_retry_or_pass(self):
        for status in ('unknown', 'pending'):
            write_ops(self.root, status=status)
            before = {p.name: p.read_bytes() for p in self.root.iterdir()}
            _, receipt = self.receipt('ops', OPS)
            self.assertEqual(port.expected_result(receipt), 'inconclusive')
            self.assertIn('reconcile before any retry', receipt['error'])
            self.assertEqual((receipt['retries_used'], receipt['calls']), (0, 0))
            self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_missing_evidence_and_malformed_configs_fail_closed(self):
        (self.root / 'observation.json').unlink()
        self.assertFalse(self.check('ops', OPS)['checks'][0]['ok'])
        for kind, config in (('data', dict(DATA, path='../outside.csv')), ('data', dict(DATA, key=[])),
                              ('ops', dict(OPS, preconditions=[])), ('ops', dict(OPS, post=OPS['pre'])),
                              ('ops', dict(OPS, request_sha='0' * 64))):
            with self.assertRaises(LedgerError): port.normalize(kind, config, 'test')

    def test_snapshot_identity_pin_mutation_tamper_wrong_source_and_null(self):
        before = artifact.identity(self.root)
        _, receipt = self.receipt('data', DATA)
        self.assertEqual(before, receipt['artifact_sha'])
        self.assertEqual(artifact.canonical(self.ledger, before), before)
        (self.root / 'output.csv').write_text(TABLE + '3,1,true\n', encoding='utf-8')
        self.assertNotEqual(artifact.identity(self.root), before)
        manifest = Snapshots(self.ledger.state_root).load(before)
        with self.assertRaises(LedgerError): artifact.canonical(self.ledger, '0' * 64)
        with self.assertRaises(LedgerError): artifact.canonical(self.ledger, 'a' * 64)
        with self.assertRaises(LedgerError): artifact.validate_evidence(self.ledger, before, dict(receipt, cwd=str(self.root.parent)))
        reference = manifest['files']['input.csv']['working']
        (Path(self.ledger.state_root) / 'snapshots' / 'blobs' / reference).write_bytes(b'changed')
        with self.assertRaises(LedgerError): artifact.validate_evidence(self.ledger, before, receipt)

    def test_read_scope_rejects_windows_aliases_and_traversal(self):
        box = port.Port(self.root, port.authority(None, 'test'), 'data')
        for path in ('../outside', '/absolute', 'C:/absolute', 'file:stream', 'a/../output.csv', 'output.csv.', '.git/config'):
            with self.subTest(path=path), self.assertRaises(port.AdapterViolation): box.read_text(path)
        self.assertEqual(len(box._violations), 7)

    def test_port_malformed_reports_and_receipts_never_pass(self):
        box = port.Port(self.root, port.authority(None, 'test'), 'data')
        for report in ({'checks': [{'id': 'a', 'ok': True, 'problems': [123]}]},
                       {'checks': [{'id': 'a', 'ok': True}], 'findings': {}},
                       {'checks': [{'id': 'a', 'ok': True}], 'unverified': [None]}):
            with self.assertRaises(port.Inconclusive): port._checks(report, box)
        self.assertEqual(port.expected_result({'checks': [{'id': 'a', 'ok': True}]}), 'inconclusive')
        _, receipt = self.receipt('data', DATA)
        bad = copy.deepcopy(receipt)
        bad['checks'][0]['problems'] = ['real failure hidden behind ok=true']
        self.assertEqual(port.expected_result(bad), 'fail')

    def test_doc_long_line_is_not_silently_truncated(self):
        (self.root / 'guide.md').write_text('a' * 4001 + '[bad](missing.md)', encoding='utf-8')
        _, receipt = self.receipt('doc', {'docs': ['guide.md']})
        self.assertEqual(port.expected_result(receipt), 'inconclusive')

    def test_large_scratch_write_preserving_size_and_mtime_is_detected(self):
        (self.root / 'large.txt').write_bytes(b'a' * 300_000)
        class Mutator:
            NAME = 'mutator'
            @staticmethod
            def validate_config(config, label): return {}
            @staticmethod
            def run(config, box):
                target = box.workspace / 'large.txt'
                saved = target.stat()
                target.write_bytes(b'b' * saved.st_size)
                os.utime(target, ns=(saved.st_atime_ns, saved.st_mtime_ns))
                return {'checks': [{'id': 'fake', 'ok': True, 'checked': 1, 'problems': []}]}
        port.register(Mutator)
        self.addCleanup(port.unregister, 'mutator')
        _, receipt = self.receipt('mutator', {})
        self.assertEqual(port.expected_result(receipt), 'inconclusive')
        self.assertIn('read_only_scope', [v['rule'] for v in receipt['violations']])
        self.assertEqual((self.root / 'large.txt').read_bytes(), b'a' * 300_000)


class SameCoreTests(Fixture):
    def setUp(self):
        super().setUp()
        for name in ('input.csv', 'output.csv'):
            (self.root / name).write_text(TABLE, encoding='utf-8')
        write_ops(self.root)
        self.git('add', '.')
        self.git('commit', '-qm', 'data and operation evidence')

    def test_data_and_ops_use_same_receipt_record_and_artifact_path(self):
        for kind, config in (('data', DATA), ('ops', OPS)):
            name = kind.upper()
            self.approved(name, plan_json(milestones=[milestone(kind, config)]))
            out = verdict.run(self.ledger, name, 'M1')
            self.assertEqual(out['milestones'][0]['state'], 'passed')
            last = out['milestones'][0]['last_verdict']
            receipt = json.loads(Snapshots(self.ledger.state_root).read_blob(last['receipt']))
            self.assertEqual(receipt['artifact_kind'], 'git-tree')
            self.assertEqual(receipt['artifact_sha'], self.tree())
            self.assertEqual(last['by'], kind)
        self.assertEqual(self.kinds('DATA'), self.kinds('OPS'))


class NonGitLifecycle(unittest.TestCase):
    setUp = LocalChecks.setUp
    def contract(self, kind, config, ref='snapshot'):
        value = plan_json(milestones=[milestone(kind, config)])
        value['understanding']['target'] = {'repo': '.', 'ref': ref, 'paths': ['output.csv']}
        value['preconditions'][0]['args']['path'] = 'output.csv'
        value['scope']['owned'] = ['output.csv']
        return value

    def test_head_and_nonadapter_cannot_bypass_non_git_target_check(self):
        for name, value in (('HEAD', self.contract('data', DATA, 'HEAD')),
                            ('COMMAND', self.contract('command', {'argv': ['python', '-c', 'pass']}))):
            plan.propose(self.ledger, name, value, 'codex-fixture')
            with self.assertRaisesRegex(LedgerError, 'target_repo'):
                plan.approve(self.ledger, name, 'owner', 'fixture')
            self.assertEqual(plan.show(self.ledger, name)['status'], 'proposed')

    def test_non_git_run_issue_record_repair_and_forged_receipt_refusal(self):
        for kind, config in (('data', DATA), ('ops', OPS)):
            name = kind.upper()
            plan.propose(self.ledger, name, self.contract(kind, config), 'codex-fixture')
            self.assertEqual(plan.approve(self.ledger, name, 'owner', 'fixture')['status'], 'approved')
            out = verdict.run(self.ledger, name, 'M1')
            self.assertEqual(out['milestones'][0]['state'], 'passed')
            receipt_ref = out['milestones'][0]['last_verdict']['receipt']
            body = json.loads(Snapshots(self.ledger.state_root).read_blob(receipt_ref))
            self.assertEqual(body['artifact_sha'], artifact.identity(self.root))
            self.assertTrue(artifact.validate_evidence(self.ledger, body['artifact_sha'], body))
            # Mutating the live artifact invalidates the old pass without editing history.
            (self.root / 'extra.txt').write_text(kind)
            self.assertNotEqual(plan.show(self.ledger, name)['milestones'][0]['state'], 'passed')
            forged = copy.deepcopy(body)
            forged['artifact_sha'] = forged['artifact_sha_after'] = artifact.identity(self.root)
            forged_ref = Snapshots(self.ledger.state_root).blob(json.dumps(forged).encode())
            with self.assertRaisesRegex(LedgerError, 'not issued'):
                verdict.record(self.ledger, name, 'M1', 'pass', kind, forged_ref, forged['artifact_sha'])
            self.assertEqual(verdict.run(self.ledger, name, 'M1')['milestones'][0]['state'], 'passed')


if __name__ == '__main__':
    unittest.main()
