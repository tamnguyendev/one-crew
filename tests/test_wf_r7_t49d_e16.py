"""Round 7 / T49d [E16] — the rollback REPORT and its check (python -m wfkit.rollback_report_check) on the S2 fixture.

The real report is the one the rollback script (python -m wfkit.rollback_cli) writes on a disposable copy of S2 at N5 (the allowed case),
next to the scan.json it decided on. Its labels come from that scan only (wfkit.rollback_cli.label_for over compat_scan's old_readable);
the test also asks the UNMODIFIED archived old binary d3120c6 (`plan show` from the root's own project) and requires every "đọc OK" line
to exit 0 and every "chỉ được bảo toàn" line to be refused, so the labels are not only self-consistent. Three wrong sample reports (and a
"mất" variant) are each refused by the check, naming the offending root.
"""
import json
import subprocess
import sys

from tests.test_wf_r7_t49d import LABELS
from tests.test_wf_r7_t49d_e5 import ROOT, _S2Cases, script
from wfkit import rollback_cli, rollback_report_check as check


def run_check(report_path, scan_path):
    result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'wfkit.rollback_report_check', str(report_path), str(scan_path)],
                            cwd=str(ROOT), env={**__import__('os').environ, 'PYTHONPATH': str(ROOT)},
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    return result.returncode, result.stdout + result.stderr


class RollbackReport(_S2Cases):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._real = None

    def real(self):
        cls = type(self)
        if cls._real is None:
            state, out = self.prepared('N5'), self.out()
            code, text = script(state, out)
            assert code == rollback_cli.EXIT_ALLOWED, text
            cls._real = (state, out, json.loads((out / 'report.json').read_text(encoding='utf-8')),
                         json.loads((out / 'scan.json').read_text(encoding='utf-8')))
        return cls._real

    def line(self, report, label):
        index, anchor = LABELS[label]
        return next(l for l in report['lines'] if (l['project_id'], l['anchor']) == (self.pids[index], anchor))

    def write_sample(self, out, name, report):
        path = out.parent / (out.name + '-' + name + '.json')
        path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        return path

    def test_e16_real_report_one_line_per_root_and_the_check_passes(self):
        state, out, report, scan = self.real()
        self.assertEqual(len(report['lines']), len(scan['roots']))
        self.assertEqual(len(report['lines']), 7)
        want = {'R1': rollback_cli.READ_OK, 'R4': rollback_cli.READ_OK, 'DUPa': rollback_cli.READ_OK,
                'R2': rollback_cli.PRESERVED_ONLY, 'R3': rollback_cli.PRESERVED_ONLY, 'DUPb': rollback_cli.PRESERVED_ONLY,
                'DUPk': rollback_cli.PRESERVED_ONLY}
        self.assertEqual({label: self.line(report, label)['label'] for label in LABELS}, want)
        self.assertEqual(check.violations(report, scan), [])
        code, text = run_check(out / 'report.json', out / 'scan.json')
        self.assertEqual(code, 0, text)
        self.assertIn('ok: 7 lines match scan ' + report['scan_sha'], text)
        txt = (out / 'report.txt').read_text(encoding='utf-8')
        self.assertTrue(txt.startswith('rollback: allowed: 0 block conditions'), txt)
        self.assertEqual(sum(1 for l in txt.splitlines() if not l.startswith('WARNING') and (' plan:' in l or ' plan-ns:' in l)), 7)

    def test_e16_real_report_labels_agree_with_the_archived_old_binary(self):
        state, _, report, _ = self.real()
        for label, (index, anchor) in LABELS.items():
            with self.subTest(root=label):
                code, out = self.old.run(self.projects[index], state, 'plan', 'show', anchor.split(':', 1)[1])
                if self.line(report, label)['label'] == rollback_cli.READ_OK:
                    self.assertEqual(code, 0, out)
                else:
                    self.assertNotEqual(code, 0, out)

    def wrong(self, name, mutate, offending):
        _, out, report, _ = self.real()
        sample = json.loads(json.dumps(report))
        mutate(sample)
        code, text = run_check(self.write_sample(out, name, sample), out / 'scan.json')
        self.assertEqual(code, 1, text)
        refused = [l for l in text.splitlines() if l.startswith('refused: ')]
        self.assertTrue(refused, text)
        index, anchor = LABELS[offending]
        for l in refused:
            self.assertIn(f'{anchor} (project {self.pids[index]})', l)
        return refused

    def test_e16_wrong_sample_read_ok_for_a_root_the_scan_keeps_preserved_only(self):
        refused = self.wrong('r2-read-ok', lambda r: self.line(r, 'R2').__setitem__('label', rollback_cli.READ_OK), 'R2')
        self.assertIn('the scan says "chỉ được bảo toàn"', refused[0])

    def test_e16_wrong_sample_lost_for_a_root_whose_data_is_kept(self):
        refused = self.wrong('r2-lost', lambda r: self.line(r, 'R2').__setitem__('label', rollback_cli.LOST), 'R2')
        self.assertIn('labelled "mất"', refused[0])

    def test_e16_wrong_sample_root_missing(self):
        refused = self.wrong('r3-missing', lambda r: r['lines'].remove(self.line(r, 'R3')), 'R3')
        self.assertIn('missing from the report', refused[0])

    def test_e16_wrong_sample_diagnosed_by_old_for_a_root_the_old_binary_reads_fine(self):
        refused = self.wrong('r1-diagnosed', lambda r: self.line(r, 'R1').__setitem__('label', rollback_cli.DIAGNOSED_BY_OLD), 'R1')
        self.assertIn('labelled "đã chẩn đoán bởi bản cũ"', refused[0])


if __name__ == '__main__':
    import unittest
    unittest.main()
