"""2.5.0.dev14 — issue #9 (tamnguyendev/one-crew, from MEP 09/11; independent review DANH-GIA-ISSUE-2-10.vi.md): plan amend's classifier called a
weakened verification "routine" ("wording or added checks only" on the approval card). Owner 09/11: "Đưa vào" 2.5.

The rule now: every change of a verifier's configuration, of a milestone, of the owned scope or of the scope is a change of acceptance (the owner
approves it), except what is listed as harmless: a review criterion added or reworded, a milestone added, a milestone title. Red on 698e118.
"""
import copy
import unittest

from onecrew.v2 import acceptance_diff as ad


def contract(*milestones, owned=('a.txt',), scope_extra=None):
    scope = dict({'owned': list(owned)}, **(scope_extra or {}))
    return {'schema_version': 2, 'title': 'T', 'size': 'S', 'output': ['The result'], 'scope': scope, 'non_goals': ['Nothing else'],
            'items': [], 'milestones': list(milestones)}


def m(vtype, config, **extra):
    return dict({'id': 'M1', 'title': 'Check', 'covers': ['O1'], 'verifier': {'type': vtype, 'config': config}}, **extra)


DATA = {'path': 'out.csv', 'row_count': 100, 'samples': [{'row': 1, 'equals': 'a'}]}
DOC = {'path': 'README.md', 'contains': ['Install', 'Usage'], 'min_lines': 20}
REVIEWER = {'provider': 'claude', 'model': 'claude-haiku-5-5', 'max_minutes': 5, 'auth': 'subscription',
            'criteria': [{'id': 'R1', 'question': 'Does a.txt hold the line? fail if it does not.'}]}
COMMAND = {'argv': ['python', 'check.py'], 'cwd': '.', 'max_minutes': 5}


class WeakenedIsAcceptance(unittest.TestCase):
    def changed(self, before, after):
        result = ad.classify_contract(before, after)
        self.assertEqual(result['classification'], 'U1', result)
        self.assertNotEqual(result['summary'], 'wording or added checks only')
        return result

    def test_a_data_verifier_that_drops_its_row_count_or_samples(self):
        for key in ('row_count', 'samples'):
            with self.subTest(key=key):
                weaker = {k: v for k, v in DATA.items() if k != key}
                self.changed(contract(m('data', DATA)), contract(m('data', weaker)))

    def test_a_doc_verifier_that_drops_a_pattern_or_its_line_count(self):
        self.changed(contract(m('doc', DOC)), contract(m('doc', dict(DOC, contains=['Install']))))
        self.changed(contract(m('doc', DOC)), contract(m('doc', {k: v for k, v in DOC.items() if k != 'min_lines'})))

    def test_any_added_verifier_setting_such_as_an_exemption(self):
        self.changed(contract(m('command', COMMAND)), contract(m('command', dict(COMMAND, inputs_unscanned=['big.bin']))))
        self.changed(contract(m('command', dict(COMMAND, inputs=['a.txt', 'b.txt']))), contract(m('command', dict(COMMAND, inputs=['a.txt']))))

    def test_the_reviewer_auth_or_any_other_reviewer_setting(self):
        self.changed(contract(m('reviewer', REVIEWER)), contract(m('reviewer', dict(REVIEWER, auth='api-key'))))

    def test_a_widened_owned_scope_and_any_other_scope_change(self):
        self.changed(contract(m('command', COMMAND)), contract(m('command', COMMAND), owned=('a.txt', '.')))
        self.changed(contract(m('command', COMMAND)), contract(m('command', COMMAND), scope_extra={'external_owned': ['D:/x']}))

    def test_an_unknown_milestone_or_verifier_field(self):
        self.changed(contract(m('command', COMMAND)), contract(m('command', COMMAND, depends_on=['M0'])))
        before = contract(m('command', COMMAND)); after = copy.deepcopy(before); after['milestones'][0]['verifier']['extra'] = 1
        self.changed(before, after)

    def test_the_card_names_the_change(self):
        result = self.changed(contract(m('data', DATA)), contract(m('data', {k: v for k, v in DATA.items() if k != 'row_count'})))
        self.assertIn('milestones.M1.row_count', result['summary'])


class HarmlessStaysRoutine(unittest.TestCase):
    def routine(self, before, after):
        result = ad.classify_contract(before, after)
        self.assertEqual(result['classification'], 'routine', result)

    def test_a_criterion_added_or_reworded(self):
        more = dict(REVIEWER, criteria=REVIEWER['criteria'] + [{'id': 'R2', 'question': 'Is b.txt untouched? fail if it changed.'}])
        self.routine(contract(m('reviewer', REVIEWER)), contract(m('reviewer', more)))
        reworded = dict(REVIEWER, criteria=[{'id': 'R1', 'question': 'Does a.txt hold the line?  Fail if it does not.'}])
        self.routine(contract(m('reviewer', REVIEWER)), contract(m('reviewer', reworded)))

    def test_a_milestone_added_and_a_milestone_title(self):
        self.routine(contract(m('command', COMMAND)), contract(m('command', COMMAND), dict(m('data', DATA), id='M2')))
        self.routine(contract(m('command', COMMAND)), contract(m('command', COMMAND, title='Check again')))

    def test_a_narrower_scope_is_still_acceptance_as_before_and_an_equal_cwd_spelling_is_not_a_change(self):
        self.assertEqual(ad.classify_contract(contract(m('command', COMMAND), owned=('a.txt', 'b.txt')), contract(m('command', COMMAND)))['classification'], 'U1')
        self.routine(contract(m('command', COMMAND)), contract(m('command', {k: v for k, v in COMMAND.items() if k != 'cwd'})))
