"""Independent adversarial review r3 of 522a6c9 (the fixes for review-codex-r2.md) — probe tests, defects introduced by 522a6c9 only.

Every `test_r3_NN` asserts the EXPECTED behaviour (a failing test = a confirmed defect); `test_r3_cN` are controls expected to pass.
Report: D:\\OneCrewRuns\\v23\\review-codex-r3.md. Temporary repositories and ledgers only; no model call.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import knowledge
from tests import test_v23_a2_knowledge as a2
from tests import test_v23_review_codex_r1 as r1
from tests import test_v23_review_codex_r2 as r2
from tests.test_v23_a2_knowledge import A2Fixture


class R3(A2Fixture):
    ledger_event = a2.RecordingTests.ledger_event
    run_cli = a2.CliTests.run_cli
    must_meta, must_text, write, commit = r1.Probe.must_meta, r1.Probe.must_text, r1.Probe.write, r1.Probe.commit
    package, outcome, decision = r1.Probe.package, r1.Probe.outcome, r1.Probe.decision
    section = r2.R2.section

    def retrieve_labels(self, *extra):
        code, out = self.run_cli('context', 'retrieve', '--plan', 'P1', *extra)
        self.assertEqual(code, 0, out)
        return {e['text']: (e['label'], e['stale_reason']) for e in json.loads(out)['entries']}

    def test_r3_01_the_unread_check_is_not_exponential_in_the_derivation_graph(self):
        n = 14                                                     # a ladder: x_i, y_i derive from x_{i+1}, y_{i+1}; the bottom cites b.txt
        meta = lambda ident, derived, **kw: dict({'id': ident, 'kind': 'summary', 'label': 'observed', 'derived_from': derived}, **kw)
        parts = [self.section(dict(self.must_meta('top'), derived_from=['x0', 'y0']), 'a.txt top rule', 'a.txt must hold VALUE: right.')]
        for i in range(n):
            for side in 'xy':
                parts.append(self.section(meta(f'{side}{i}', [f'x{i + 1}', f'y{i + 1}']), f'step {side}{i}', f'Summary {side}{i}.'))
        for side in 'xy':
            parts.append(self.section({'id': f'{side}{n}', 'kind': 'finding', 'label': 'verified',
                                       'sources': [{'type': 'file', 'path': 'b.txt', 'revision': self.head}]}, f'bottom {side}', f'Finding {side}.'))
        self.write(self.wiki_dir / 'ladder.md', '\n'.join(parts)); self.commit()
        calls = [0]
        def profile(frame, event, arg):
            if event == 'call' and frame.f_code.co_name == 'unread': calls[0] += 1
        sys.setprofile(profile)
        try:
            self.outcome()
        finally:
            sys.setprofile(None)
        self.assertLessEqual(calls[0], 20 * (2 * n + 3), f'{calls[0]} unread() calls for {2 * n + 3} entries')

    def test_r3_02_a_utf8_page_with_one_nul_byte_is_still_read(self):
        self.write(self.wiki_dir / 'rules.md', self.must_text() + 'Pasted from a terminal log: ok\x00\n'); self.commit()
        self.assertEqual(self.outcome(), ('delivered', ['required-rule']))

    def test_r3_03_the_revision_view_reads_the_project_whatever_git_environment_the_caller_has(self):
        self.decision('Use the old a.txt convention')                                      # a.txt pinned at HEAD, unchanged
        self.assertEqual(self.retrieve_labels('--revision', 'HEAD')['Use the old a.txt convention'], ('verified', None))   # control
        other = Path(self.temp.name) / 'other'; other.mkdir()
        subprocess.run(['git', 'init', '-q', str(other)], check=True)
        with patch.dict(os.environ, {'GIT_DIR': str(other / '.git')}):   # e.g. called from a git hook; command._git strips GIT_* (F8)
            labels = self.retrieve_labels('--revision', 'HEAD')
        self.assertEqual(labels['Use the old a.txt convention'], ('verified', None))

    def test_r3_c1_context_retrieve_revision_judges_on_that_commit(self):
        old = self.git('rev-parse', 'HEAD')
        self.decision('Use the old a.txt convention')
        (self.root / 'a.txt').write_text('a different content\n'); self.commit('a.txt changed')
        self.assertEqual(self.retrieve_labels('--revision', old)['Use the old a.txt convention'], ('verified', None))
        self.assertEqual(self.retrieve_labels('--revision', 'HEAD')['Use the old a.txt convention'][0], 'stale')
