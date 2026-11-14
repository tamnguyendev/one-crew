"""Owner coverage must be sourced even when the candidate prose overclaims. No Git, process or model calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.snapshots import Snapshots
from onecrew.v2 import report
from tests.test_mrr_sources import changed, fingerprint


class OwnerCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Snapshots(self.root)
        self.facts = {'contract': {'authority': {'repos': [{'alias': 'core', 'path': 'repo-a', 'read': ['src/**']},
                                                        {'alias': 'gone', 'path': 'repo-b', 'read': ['src/**']}]}},
                      'state_root': self.root, 'events': [], 'state': {'status': 'approved', 'latest': 1}, 'requests': [], 'views': []}

    def candidate(self):
        content = self.store.blob(b'ALL REPOSITORIES FULLY REVIEWED\n- core@aaaaaaaaaaaa:src/a.py:1 real cite\n')
        artifact = self.store.save({'version': 1, 'head': None, 'files': {'reports/analysis.md': {'working': content, 'index': []}}})
        source = {'repos': {'core': {'kind': 'git-tree', 'status': 'pinned', 'tree': 'a'*40, 'head': 'b'*40, 'dirty': False},
                            'gone': {'kind': 'unavailable', 'status': 'unavailable', 'state': 'missing', 'reason': 'folder missing'}},
                  'coverage_gaps': [{'repo': 'gone', 'status': 'unavailable', 'state': 'missing'}]}
        key = self.store.blob(json.dumps({'source': source, 'partial': False, 'artifact': artifact,
                                         'changed_paths': ['reports/analysis.md']}).encode())
        self.facts['events'] = [('node.produced', '2026-11-04T00:00:00+00:00', {'node': 'R', 'artifact': artifact, 'receipt': key})]
        return key

    def test_receipt_gap_stays_visible_despite_full_review_claim_and_reads_do_not_write(self):
        key = self.candidate()
        before = fingerprint(self.root)
        text = '\n'.join(report._repo_coverage(self.facts))
        self.assertIn('PHỦ THIẾU', text)
        self.assertIn('gone: unavailable; missing; folder missing', text)
        self.assertIn(key, text)
        self.assertIn('a'*40, text)
        self.assertIn('ALL REPOSITORIES FULLY REVIEWED', text)  # preserved as candidate prose, not promoted into coverage evidence
        self.assertIn('chưa được kiểm hoặc nghiệm thu', text)
        self.assertEqual(changed(before, fingerprint(self.root)), [])
        with patch.object(report, '_open_findings', return_value=[]):
            self.assertIn('xem bản phân tích MR-R', report._needs(self.facts))

    def test_declaration_without_a_receipt_never_claims_a_source_was_read(self):
        text = '\n'.join(report._repo_coverage(self.facts))
        self.assertIn('quyền được khai không chứng minh nguồn đã được đọc', text)
        self.assertIn('gone: repo-b', text)

    def test_single_repo_opt_out_has_no_added_report_section(self):
        self.facts['contract'] = {'authority': {'read': ['src/**']}}
        self.assertEqual(report._repo_coverage(self.facts), [])


if __name__ == '__main__':
    unittest.main()
