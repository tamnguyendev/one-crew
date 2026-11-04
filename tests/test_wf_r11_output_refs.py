"""R11 (Codex round 11, finding B): extensionless file references (`Dockerfile:999999`, `Makefile:12`, `src/Dockerfile:3`,
`LICENSE:1`) are references and are judged; a token that cannot be resolved is an offender, never a silent pass. Negative controls:
URLs, host:port, times, ratios, Windows drive paths, YAML keys, image tags and ordinary prose are neither references nor offenders."""
import unittest

from onecrew.v2.verifiers import output_refs
from tests.test_wf_r10_output_refs import OutputRefsFixture

TREE = {'Dockerfile': 3, 'Makefile': 20, 'LICENSE': 5, 'src/Dockerfile': 4, 'src/app.cs': 9, 'tools/gradlew': 7, 'README.md': 3}


def judge(text, tree=TREE, outputs=()):
    return output_refs.check(tree, output_refs.scan(text), list(outputs))


class ExtensionlessReferences(unittest.TestCase):
    def test_a_known_build_file_that_is_not_in_the_tree_is_an_offender(self):
        got = judge('The base image is set at Dockerfile:999999.', tree={'README.md': 3})
        self.assertEqual((got['result'], got['counts']['unresolvable'], got['offender_count']), ('fail', 1, 1))
        self.assertIn('Dockerfile:999999', got['offenders'][0])

    def test_b_known_build_file_line_outside_the_file_is_an_offender(self):
        got = judge('Dockerfile:999999')
        self.assertEqual((got['result'], got['reasons']['line_outside_file']), ('fail', 1))

    def test_c_extensionless_references_resolve(self):
        got = judge('See Makefile:12, src/Dockerfile:3, LICENSE:1, Dockerfile:1-3 and tools/gradlew:7.')
        self.assertEqual(got['result'], 'pass', got)
        self.assertEqual(got['counts']['resolved'], 5)

    def test_d_slash_path_without_extension_that_does_not_exist_is_an_offender(self):
        got = judge('Broken at src/Gonefile:3 and tools/missing:2.')
        self.assertEqual((got['result'], got['counts']['unresolvable'], got['reasons']['no_such_file']), ('fail', 2, 2))

    def test_e_known_or_tree_basename_cited_bare_is_a_bare_basename_offender(self):
        got = judge('gradlew:3 is wrong.', tree={'tools/gradlew': 7})
        self.assertEqual((got['result'], got['reasons']['bare_basename']), ('fail', 1))
        got = judge('Makefile:2', tree={'build/Makefile': 7})
        self.assertEqual((got['result'], got['reasons']['bare_basename']), ('fail', 1))

    def test_f_malformed_extensionless_reference_is_unverifiable(self):
        for text in ('Makefile:12:5', 'Dockerfile:line 4', 'LICENSE:L1', 'src/Dockerfile:3-x'):
            with self.subTest(text):
                got = judge(text)
                self.assertEqual((got['result'], got['counts']['unverifiable']), ('fail', 1), got)

    def test_g_an_existing_top_level_extensionless_file_is_a_reference(self):
        got = judge('configure:3 and configure:99', tree={'configure': 10})
        self.assertEqual((got['counts']['resolved'], got['counts']['unresolvable']), (1, 1))


class NegativeControls(unittest.TestCase):
    CONTROLS = ['https://x/y:80', 'http://example.com:8080/a', 'example.com:443', 'localhost:8080', '127.0.0.1:5000',
                'at 12:30 today', 'at 12:30:45', 'ratio 16:9', 'C:\\Users\\NUC\\file.txt', 'D:/OneCrewRuns/x', 'C:5',
                'image: nginx', 'image: nginx:1.25', 'FROM node:18', 'python:3.12-slim', 'ports: "8080:80"',
                'Lưu ý: 3 điều', 'Bước 2: 5 phút', 'Note:3 in prose', 'Step:2', 'Version:2', 'Namespace.Class:Method',
                'redis/redis-stack:7', 'library/nginx:1.25']

    def test_controls_are_not_references_and_not_offenders(self):
        for text in self.CONTROLS:
            with self.subTest(text):
                got = judge(text)
                self.assertEqual((got['result'], got['counts']['total'], got['offender_count']), ('pass', 0, 0), got)

    def test_ignored_ambiguous_tokens_are_recorded(self):
        got = judge('Note:3 and localhost:8080')
        self.assertEqual(got['ignored']['count'], 2)


class ExtensionlessThroughCandidateChecker(OutputRefsFixture):
    def test_h_report_citing_a_missing_dockerfile_fails_m1(self):
        out = self.assertOutFails(self.verify_reports({'docs/rep/K03.md': 'The image is built at Dockerfile:999999.\n'}), 'Dockerfile:999999')
        self.assertEqual(out['counts']['unresolvable'], 1)

    def test_i_prose_and_host_ports_in_a_report_still_pass(self):
        text = 'Lưu ý: 3 điều. Bước 2: 5 phút. Note:3. Server localhost:8080, 127.0.0.1:5000, at 12:30. image: nginx:1.25. See a.cs:1.\n'
        result = self.verify_reports({'docs/rep/K03.md': text})
        out = result['observed']['output_check']
        self.assertEqual((result['result'], out['result'], out['counts']['total'], out['counts']['resolved']), ('pass', 'pass', 1, 1), out)


if __name__ == '__main__':
    unittest.main()
