"""MR-R regression (task item 6 of the slice): a root WITHOUT `authority.repos` and a node WITH `sources` (2.4-A, one project repository)
gets the prompt, schema, receipt, results blob, delivery record and node.started it got before MR-R, byte for byte.

The digests in tests/mrr_single_baseline.json were taken with this very test on the commit that added it (its runtime is the base 0cc20ae:
that commit changed tests and docs only), with MRR_RECORD_BASELINE=1. Commit dates are fixed so the commit ids in the prompt are stable;
the volatile values (task, attempt, artifact and base keys, the root id in a knowledge revision, timings) are replaced by '<v>' before
hashing, the rest is hashed as it is.
"""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import canonical, content_hash
from tests.test_v24_a_sources import SourceFixture, ask, body_of, done

BASELINE = Path(__file__).with_name('mrr_single_baseline.json')
DATE = '2026-11-01T10:00:00+07:00'
VOLATILE = {'task', 'attempt', 'base', 'artifact', 'elapsed_seconds', 'continues_attempt', 'resume_artifact', 'continues', 'revision',
            'seconds', 'child', 'at'}


def scrub(value):
    if isinstance(value, dict): return {k: ('<v>' if k in VOLATILE else scrub(v)) for k, v in value.items()}
    if isinstance(value, list): return [scrub(v) for v in value]
    return value


class SingleRepositoryDigests(SourceFixture):
    def setUp(self):
        dates = patch.dict(os.environ, {'GIT_AUTHOR_DATE': DATE, 'GIT_COMMITTER_DATE': DATE})
        dates.start(); self.addCleanup(dates.stop)
        super().setUp()

    def events_all(self):
        from onecrew.v2 import plan as plans
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
            return [(r['kind'], json.loads(r['payload'])) for r in conn.execute('SELECT kind,payload FROM events WHERE task_id=? ORDER BY seq', (task,))]

    def digests(self):
        self.plan(self.item(patterns=('src/', 'docs/')))
        self.values += [lambda p, s: ask({'op': 'read', 'path': 'src/lib/x.py'}, {'op': 'search', 'query': 'helper', 'path': 'src'},
                                         {'op': 'list', 'path': 'docs'}, {'op': 'read', 'path': 'src/creds.txt'}, {'op': 'read', 'path': 'other/y.py'}),
                        lambda p, s: done('read\n')]
        states = [self.step()['state'], self.step()['state']]
        out = {'states': states}
        for n, call in enumerate(self.calls):
            header, body = call['prompt'].split('\n', 1)
            out[f'prompt{n}'] = content_hash(header + '\n' + canonical(scrub(json.loads(body))))
            out[f'prompt{n}_chars'] = len(call['prompt'])
            out[f'schema{n}'] = content_hash(call['schema'])
        events = self.events_all()
        receipts = [json.loads(self.store.read_blob(p['candidate']['receipt'])) for k, p in events if k == 'node.result_retained']
        receipts += [json.loads(self.store.read_blob(p['receipt'])) for k, p in events if k == 'node.produced']
        for n, receipt in enumerate(receipts):
            out[f'receipt{n}_keys'] = sorted(receipt)
            out[f'receipt{n}'] = content_hash(scrub(receipt))
            out[f'results{n}'] = content_hash(json.loads(self.store.read_blob(receipt['source']['results'])))
        for n, payload in enumerate(p for k, p in events if k == 'node.started' and p['node'] == 'C'):
            out[f'started{n}_keys'] = sorted(payload)
            out[f'started{n}_tree'] = content_hash({k: v for k, v in payload['source_tree'].items() if k != 'seconds'})
        for n, payload in enumerate(p for k, p in events if k == 'knowledge.delivered'):
            out[f'delivered{n}_keys'] = sorted(payload)
            out[f'delivered{n}_sources'] = content_hash(payload.get('sources_read'))
        out['tools0_keys'] = sorted(body_of(self.calls[0]['prompt'])['source_tools'])
        return out

    def test_mr16_a_single_repository_node_with_sources_is_byte_identical_to_the_base(self):
        digests = self.digests()
        if os.environ.get('MRR_RECORD_BASELINE'):
            BASELINE.write_text(json.dumps({'note': 'taken by MRR_RECORD_BASELINE=1 on the red-test commit (runtime = base 0cc20ae)',
                                            'digests': digests}, indent=1, sort_keys=True) + '\n', encoding='utf-8')
            self.skipTest('baseline recorded in ' + str(BASELINE))
        self.assertTrue(BASELINE.is_file(), 'the baseline was never recorded on the base runtime')
        self.assertEqual(digests, json.loads(BASELINE.read_text(encoding='utf-8'))['digests'])


if __name__ == '__main__':
    unittest.main()
