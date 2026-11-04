"""2.4, Codex review of 2.4.0.dev3, P3: the package's combined limits (docs/v24/limits-final.md, shipped as docs/limits-final.md) said the
claim was taken over by the old rule while the S2 limits (limits-s2.md) already described the pid + process-creation-time check and the
renewal; the checkout was fixed after the package snapshot, the package was not.

Expected: every milestone section of the combined limits is, line for line, the milestone's own limits file (so the two cannot drift
again), and the package build ships these files unchanged (checked from the artifact by the package verifier, V29).
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs' / 'v24'
SECTIONS = {'2.4-S1': 'limits-s1.md', '2.4-S2': 'limits-s2.md', '2.4-A': 'limits-a.md', '2.4-B': 'limits-b.md', '2.4-C': 'limits-c.md'}


def bullets(text):
    return [line.rstrip() for line in text.splitlines() if line.startswith('- ')]


def sections(text):
    """{'2.4-S1': [bullet lines], ...} of the combined file: a section starts at a line '**2.4-X**'."""
    out, current = {}, None
    for line in text.splitlines():
        found = re.fullmatch(r'\*\*(2\.4-[A-Z0-9]+)\*\*\s*', line)
        if found:
            current = found.group(1); out[current] = []; continue
        if current and line.startswith('- '): out[current].append(line.rstrip())
    return out


class LimitsInSync(unittest.TestCase):
    def test_every_section_of_the_combined_limits_is_the_milestone_file(self):
        combined = sections((DOCS / 'limits-final.md').read_text(encoding='utf-8'))
        self.assertEqual(set(combined), set(SECTIONS))
        for section, name in SECTIONS.items():
            with self.subTest(section=section):
                self.assertEqual(combined[section], bullets((DOCS / name).read_text(encoding='utf-8')),
                                 f'{section} of limits-final.md differs from {name}')

    def test_the_claim_text_names_the_pid_and_creation_time_check_in_both(self):
        for name in ('limits-s2.md', 'limits-final.md'):
            text = (DOCS / name).read_text(encoding='utf-8')
            claim = next(line for line in text.splitlines() if line.startswith('- **Claim chỉ loại trừ nhau'))
            self.assertIn('pid và thời điểm tạo tiến trình', claim, name)
            self.assertIn('gia hạn', claim, name)

    def test_the_bytecode_rule_is_stated_where_the_trust_boundary_is(self):
        for name in ('limits-s2.md', 'limits-final.md'):
            text = (DOCS / name).read_text(encoding='utf-8')
            line = next(l for l in text.splitlines() if l.startswith('- **Ranh giới tin cậy của việc kiểm venv'))
            self.assertIn('.pyc', line, name)
            self.assertIn('không chạy', line, name)


if __name__ == '__main__':
    unittest.main()
