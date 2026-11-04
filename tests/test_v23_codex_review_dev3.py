"""Codex review of 2.3.0.dev3 (0594a43, 29/10), P2: the applicability of shared (general) knowledge.

`context retrieve` judged a general record by the lifecycle only: a 2.3 general record whose condition is false here (`platform: linux`
on Windows) came back `verified` with no stale reason, with or without --plan, while `wiki show --plan` left it out as not_applicable.
Counterexamples (red on 0594a43): a general record whose condition is false or cannot be checked here is never shown as a current fact by
`context retrieve`, in every form that returns the general scope (no --plan or --plan, scope general or both, --revision). Controls: a
general record whose condition holds stays verified; project entries, withdrawal, supersession, history, the original label and the 2.2
rule for 2.2 entries do not change. Every case goes through the CLI entrypoint (`onecrew.v2.cli.main`) on a temporary ledger.
"""
import json
import sys
from unittest.mock import patch

from onecrew.v2 import context, knowledge
from tests import test_v23_a2_knowledge as a2
from tests.test_v23_a2_knowledge import A2Fixture

ELSEWHERE = 'linux' if sys.platform != 'linux' else 'win32'
GENERAL_FORMS = (('--scope', 'general'), ('--scope', 'both'), ('--plan', 'P1', '--scope', 'general'), ('--plan', 'P1', '--scope', 'both'),
                 ('--plan', 'P1', '--scope', 'general', '--revision', 'HEAD'))


class GeneralApplicability(A2Fixture):
    ledger_event = a2.RecordingTests.ledger_event
    run_cli = a2.CliTests.run_cli

    def cli(self, *args):
        code, out = self.run_cli(*args)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def general(self, text, *conditions, status='verified'):
        args = ['wiki', 'record', '--plan', 'P1', '--kind', 'decision', '--text', text, '--status', status, '--scope', 'general',
                '--source', f'event:{self.ledger_event()}']
        if status == 'verified': args += ['--property', 'the retry check passed']
        for condition in conditions:
            args += ['--condition', condition if isinstance(condition, str) else json.dumps(condition)]
        return self.cli(*args)

    def retrieved(self, *form):
        return {e['text']: e for e in self.cli('context', 'retrieve', *form)['entries']}

    def wiki(self):
        """id -> what `wiki show --plan P1` decided: the use of a delivered or listed entry, or the reason it was left out unnamed."""
        package = self.cli('wiki', 'show', '--plan', 'P1')
        seen = {e['id']: e['use'] for e in package['entries']}
        seen.update({row['id']: row['use'] for row in package['omitted']['index']})
        return seen, package['omitted']['by_reason']

    def test_a_general_record_whose_condition_is_false_here_is_never_a_current_fact(self):
        written = self.general('Use exponential retry delay', {'type': 'env', 'key': 'platform', 'value': ELSEWHERE})
        seen, reasons = self.wiki()
        self.assertNotIn(written['id'], seen); self.assertEqual(reasons.get('not_applicable'), 1, reasons)
        for form in GENERAL_FORMS:
            with self.subTest(form=form):
                entry = self.retrieved(*form)['Use exponential retry delay']
                self.assertEqual(entry['label'], 'stale', entry)
                self.assertTrue((entry['stale_reason'] or '').startswith('not applicable now'), entry)
                self.assertIn(ELSEWHERE, entry['stale_reason'])
                self.assertEqual((entry['stored_label'], entry['source']['type']), ('verified', 'event'))     # the original label and source
                self.assertTrue(any(ELSEWHERE in c for c in entry['conditions']), entry)

    def test_a_general_record_whose_condition_cannot_be_checked_here_is_never_a_current_fact(self):
        model = self.general('Use the long timeout for this model', {'type': 'env', 'key': 'model', 'value': 'some-model'})
        text = self.general('Use the batch endpoint', 'only when the queue is drained')
        seen, _ = self.wiki()
        self.assertEqual((seen.get(model['id']), seen.get(text['id'])), ('lead', 'lead'))
        for form in GENERAL_FORMS:
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                for name in ('Use the long timeout for this model', 'Use the batch endpoint'):
                    entry = entries[name]
                    self.assertEqual(entry['label'], 'stale', entry)
                    self.assertTrue((entry['stale_reason'] or '').startswith('cannot be checked now'), entry)
                    self.assertEqual(entry['stored_label'], 'verified')

    def test_control_a_general_record_whose_condition_holds_stays_verified(self):
        here = self.general('Retry rule here', {'type': 'env', 'key': 'platform', 'value': sys.platform})
        plain = self.general('Retry rule anywhere', {'type': 'env', 'key': 'python', 'value': '%d.%d' % sys.version_info[:2]})
        observed = self.general('Retries looked slower', {'type': 'env', 'key': 'platform', 'value': sys.platform}, status='observed')
        seen, _ = self.wiki()
        self.assertEqual((seen.get(here['id']), seen.get(plain['id']), seen.get(observed['id'])), ('fact', 'fact', 'lead'))
        for form in GENERAL_FORMS:
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                for name, label in (('Retry rule here', 'verified'), ('Retry rule anywhere', 'verified'), ('Retries looked slower', 'observed')):
                    self.assertEqual((entries[name]['label'], entries[name]['stale_reason']), (label, None), entries[name])

    def test_wiki_and_context_agree_on_applicability_for_the_same_reader(self):
        cases = {'Rule for elsewhere': {'type': 'env', 'key': 'platform', 'value': ELSEWHERE},
                 'Rule for here': {'type': 'env', 'key': 'platform', 'value': sys.platform},
                 'Rule for a model': {'type': 'env', 'key': 'model', 'value': 'some-model'}}
        ids = {name: self.general(name, condition)['id'] for name, condition in cases.items()}
        seen, _ = self.wiki()
        entries = self.retrieved('--plan', 'P1', '--scope', 'both')
        for name, ident in ids.items():
            use, entry = seen.get(ident, 'not_applicable'), entries[name]
            expected = {'fact': 'verified', 'lead': 'stale', 'not_applicable': 'stale'}[use]
            self.assertEqual(entry['label'], expected, (name, use, entry))

    def test_control_project_entries_keep_their_judgement(self):
        knowledge.record(self.ledger, 'P1', kind='decision', text='Project rule for elsewhere', applies_to=['a.txt'],
                         conditions=[{'type': 'env', 'key': 'platform', 'value': ELSEWHERE}],
                         evidence={'status': 'verified', 'property': 'checked by M1', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        knowledge.record(self.ledger, 'P1', kind='decision', text='Project rule for here', applies_to=['a.txt'],
                         evidence={'status': 'verified', 'property': 'checked by M1', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        for form in (('--plan', 'P1', '--scope', 'project'), ('--scope', 'project'), ('--plan', 'P1')):
            with self.subTest(form=form):
                entries = self.retrieved(*form)
                self.assertEqual(entries['Project rule for elsewhere']['label'], 'stale')
                self.assertTrue(entries['Project rule for elsewhere']['stale_reason'].startswith('not applicable now'))
                self.assertEqual((entries['Project rule for here']['label'], entries['Project rule for here']['stale_reason']), ('verified', None))

    def test_withdrawn_or_superseded_general_records_never_come_back_and_stay_in_the_history(self):
        valid = self.general('Withdrawn general rule', {'type': 'env', 'key': 'platform', 'value': sys.platform})
        wrong = self.general('Withdrawn rule for elsewhere', {'type': 'env', 'key': 'platform', 'value': ELSEWHERE})
        replaced = self.general('Replaced general rule', {'type': 'env', 'key': 'platform', 'value': sys.platform})
        for ident in (valid['id'], wrong['id']):
            self.cli('wiki', 'withdraw', ident, '--plan', 'P1', '--reason', 'shown wrong', '--source', f'event:{self.ledger_event()}')
        knowledge.record(self.ledger, 'P1', kind='decision', text='The project rule that replaces it', supersedes=[replaced['id']],
                         evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        for form in GENERAL_FORMS:
            with self.subTest(form=form):
                texts = set(self.retrieved(*form))
                self.assertFalse({'Withdrawn general rule', 'Withdrawn rule for elsewhere', 'Replaced general rule'} & texts, texts)
        history = {r['id']: r for r in self.cli('wiki', 'history')['records']}
        self.assertEqual((history[valid['id']]['status'], history[wrong['id']]['status'], history[replaced['id']]['status']),
                         ('withdrawn', 'withdrawn', 'superseded'))
        self.assertEqual(history[wrong['id']]['label'], 'verified')                                 # the history keeps the original label

    def test_control_a_22_general_entry_keeps_the_22_rule(self):
        context.add(self.ledger, 'P1', kind='note', label='observed', text='2.2 shared note', scope='general', conditions=['Python'],
                    source={'type': 'event', 'id': self.ledger_event()})
        for form in GENERAL_FORMS:
            with self.subTest(form=form):
                entry = self.retrieved(*form)['2.2 shared note']
                self.assertEqual((entry['label'], entry['stale_reason'], entry['conditions']), ('observed', None, ['Python']))

    def test_when_the_judgement_fails_a_general_record_is_not_shown_as_current(self):
        self.general('General rule here', {'type': 'env', 'key': 'platform', 'value': sys.platform})
        gone = self.general('General rule withdrawn', {'type': 'env', 'key': 'platform', 'value': sys.platform})
        self.cli('wiki', 'withdraw', gone['id'], '--plan', 'P1', '--reason', 'shown wrong', '--source', f'event:{self.ledger_event()}')
        context.add(self.ledger, 'P1', kind='note', label='observed', text='2.2 shared note', scope='general', conditions=['Python'],
                    source={'type': 'event', 'id': self.ledger_event()})
        raw = context.retrieve(self.ledger, plan='P1', scope='general', raw=True)['entries']
        with patch.object(knowledge, 'for_root', side_effect=RuntimeError('broken reader')):
            entries = {e['text']: e for e in context.judged(self.ledger, raw)}
        self.assertNotIn('General rule withdrawn', entries)                                         # gone stays gone
        self.assertEqual(entries['General rule here']['label'], 'stale')
        self.assertIn('knowledge state not checked', entries['General rule here']['stale_reason'])
        self.assertEqual(entries['2.2 shared note']['label'], 'observed')                          # a 2.2 entry keeps its label (R2-09)
