"""Real-artifact tests of T40c [E30] (round 8): the RP Producer on the REAL W45 matrix output of this machine
(D:/OneCrewRuns/wf-w45-matrix-6366137, read only). Kept OUT of the gate registry on purpose: the snapshot gate forbids skipped tests and
these must skip where the matrix is absent. Run by hand:
  PYTHONPATH=".;tests" python -X utf8 -m unittest tests.test_wf_r7_t40c_real
"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from onecrew.ledger import LedgerError
from wfkit import provider_evidence, release_bundle, release_check as check
from wfkit.finalgate import evidence_status, identity
from tests import test_wf_release_check as base
W45 = Path(r'D:\OneCrewRuns\wf-w45-matrix-6366137')
from tests.test_wf_r7_t40c import *  # noqa: F401,F403 — helpers of the registered module


@unittest.skipUnless((W45 / 'matrix.json').exists(), 'the real W45 matrix output is not on this machine')
class T40cProducerDecisionTests(unittest.TestCase):
    """Round 8 H [E30], producer side: wfkit.release_bundle.Producer.provider_bundle on the REAL W45 matrix (read only; receipts copied into a
    temporary bundle dir) records the decisions before the subset and after the shared verdict, with the receipts' pins_source."""

    def producer(self):
        temp = tempfile.TemporaryDirectory(prefix='wf-r8h-'); self.addCleanup(temp.cleanup)
        matrix = json.loads((W45 / 'matrix.json').read_text(encoding='utf-8'))
        producer = object.__new__(release_bundle.Producer)
        producer.matrix_dir, producer.out = W45, Path(temp.name)
        producer.artifacts = {'current': {'commit': matrix['commit'], 'wheel_sha256': matrix['wheel_sha256']}}
        return producer, matrix

    def test_e30_the_producer_records_before_and_after_and_the_notes_line(self):
        producer, matrix = self.producer()
        bundle, notes = producer.provider_bundle()
        decisions = bundle['decisions']
        self.assertEqual(decisions['before'], decisions['after'])
        self.assertEqual(decisions['before'], record(matrix['rows'], PINS_SOURCE))                 # the pins the W45 matrix ran with
        self.assertIn(line(decisions['after']), notes['matrix_markdown'].splitlines())
        written = json.loads((producer.out / 'provider-matrix' / 'decisions.json').read_text(encoding='utf-8'))
        self.assertEqual(written, decisions)
        self.assertEqual(producer.decisions_after_verdict(), {'before_sha256': decisions['before']['sha256'],
                                                              'after_verdict_sha256': decisions['before']['sha256'], 'unchanged': True})

    def test_e30_a_pin_changed_during_the_rp_decision_stops_the_producer_naming_the_cell(self):
        producer, matrix = self.producer()
        real = provider_evidence.evaluate

        def evaluate_then_change(rows, *args, **kwargs):
            states = real(rows, *args, **kwargs)
            next(r for r in rows if r['id'] == 'kiro:reviewer')['model'] = 'changed-model'
            return states
        with mock.patch.object(provider_evidence, 'evaluate', evaluate_then_change):
            with self.assertRaises(LedgerError) as raised:
                producer.provider_bundle()
        self.assertIn('kiro:reviewer', str(raised.exception)); self.assertIn('quyết định hợp đồng trước/sau đã đổi', str(raised.exception))
