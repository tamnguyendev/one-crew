"""Independent adversarial review r2 of 989eb9c (the fixes for review-codex-r1.md) — probe tests.

Every `test_r2_NN` asserts the EXPECTED behaviour (a failing test = a confirmed defect); its first assertion is usually a control.
`test_r2_cN` are controls of the design choices of 989eb9c that are expected to pass. Report: D:\\OneCrewRuns\\v23\\review-codex-r2.md.
Temporary repositories and ledgers only (the fixtures of test_v23_a1/a2); the worker is the A2 fixture worker (no model call).
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import canonical
from onecrew.v2 import knowledge, wiki
from tests.test_v23_a1_knowledge import fence
from tests import test_v23_a2_knowledge as a2
from tests import test_v23_review_codex_r1 as r1
from tests.test_v23_a2_knowledge import A2Fixture


class R2(A2Fixture):
    ledger_event = a2.RecordingTests.ledger_event
    run_cli = a2.CliTests.run_cli
    must_meta, must_text, write, commit = r1.Probe.must_meta, r1.Probe.must_text, r1.Probe.write, r1.Probe.commit
    package, outcome, step, prompt_must = r1.Probe.package, r1.Probe.outcome, r1.Probe.step, r1.Probe.prompt_must
    decision = r1.Probe.decision

    def section(self, meta, heading, text):
        return f'## {heading}\n' + fence(meta) + text + '\n'

    # ---- --revision ----------------------------------------------------------------------------------------------------------
    def test_r2_01_context_retrieve_revision_head_does_not_show_a_record_whose_pinned_file_changed_as_verified(self):
        self.decision('Use the old a.txt convention')                                       # verified, a.txt pinned at HEAD
        (self.root / 'a.txt').write_text('a different content\n'); self.commit('a.txt changed')
        code, out = self.run_cli('context', 'retrieve', '--plan', 'P1')
        self.assertEqual({e['text']: e['label'] for e in json.loads(out)['entries']}['Use the old a.txt convention'], 'stale')   # control
        code, out = self.run_cli('context', 'retrieve', '--plan', 'P1', '--revision', 'HEAD')   # the same state, named explicitly
        self.assertEqual(code, 0, out)
        entry = {e['text']: e for e in json.loads(out)['entries']}['Use the old a.txt convention']
        self.assertEqual(entry['label'], 'stale', {k: entry[k] for k in ('label', 'stale_reason')})

    # ---- derived_from (r1 F4 follow-up) ------------------------------------------------------------------------------------
    def chain(self, names):
        rule = dict(self.must_meta('a-rule'), derived_from=['b-mid'])
        mid = {'id': 'b-mid', 'kind': 'summary', 'label': 'verified', 'applies_to': ['a.txt'], 'derived_from': ['z-base'],
               'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}
        base = {'id': 'z-base', 'kind': 'finding', 'label': 'verified', 'applies_to': ['a.txt'],
                'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}
        sections = [self.section(rule, 'a.txt value', 'a.txt must hold VALUE: right.'), self.section(mid, 'a.txt VALUE summary', 'VALUE is right.'),
                    self.section(base, 'a.txt VALUE finding', 'Measured: VALUE right.')]
        if len(names) == 1:
            self.write(self.wiki_dir / names[0], '\n'.join(sections))
        else:
            for name, text in zip(names, sections): self.write(self.wiki_dir / name, text)

    def test_r2_02_a_mandatory_rule_two_derivations_away_from_a_page_after_the_budget_is_not_dropped_silently(self):
        self.chain(['a-rule.md', 'b-mid.md', 'z-base.md'])
        self.commit()
        self.assertEqual(self.outcome(), ('delivered', ['a-rule']))                             # control: the whole wiki is read
        with patch.object(wiki, 'MAX_PAGES', 2):                                                # z-base.md sorts after the budget
            state, value = self.outcome()
        self.assertTrue(state == 'held' or value == ['a-rule'], (state, value))

    def test_r2_02b_the_same_chain_on_one_page_after_the_budget_is_not_dropped_silently(self):
        self.write(self.wiki_dir / 'a-first.md', '## Meeting room\nThe meeting room is on floor two.\n')
        self.chain(['b-rules.md'])
        self.commit()
        self.assertEqual(self.outcome(), ('delivered', ['a-rule']))                             # control
        with patch.object(wiki, 'MAX_PAGES', 1):                                                # b-rules.md is read for its mandatory part
            state, value = self.outcome()
        self.assertTrue(state == 'held' or value == ['a-rule'], (state, value))

    # ---- duplicate ids (r1 F6 follow-up) -----------------------------------------------------------------------------------
    def test_r2_03_two_different_mandatory_sections_under_one_id_with_a_dangling_ledger_id_are_not_resolved_by_name_order(self):
        # wiki pages travel with git, ledgers do not: an export made from another state root names ledger subjects this ledger lacks
        meta = dict(self.must_meta('copy-ctx-0123456789abcdef01234567'), ledger_id='ctx-0123456789abcdef01234567')
        self.write(self.wiki_dir / 'a-2026-09' / 'onecrew-export.md', self.section(meta, 'a.txt value', 'a.txt must hold VALUE: old.'))
        self.write(self.wiki_dir / 'onecrew-export.md', self.section(meta, 'a.txt value', 'a.txt must hold VALUE: right.'))
        self.commit()
        state, value = self.outcome()
        delivered = [e['text'] for e in self.package()['entries'] if e['must']] if state == 'delivered' else None
        self.assertEqual(state, 'held', ('the older text is delivered as the mandatory rule and the newer one is skipped', delivered))

    def test_r2_04_two_mandatory_sections_that_differ_only_in_their_heading_are_not_one_copy(self):
        meta = self.must_meta('enc-rule')
        self.write(self.wiki_dir / 'a.md', self.section(meta, 'a.txt must be ASCII', 'Checked by the encoding gate.'))
        self.write(self.wiki_dir / 'b.md', self.section(meta, 'a.txt must be UTF-16', 'Checked by the encoding gate.'))
        self.commit()
        self.assertEqual(self.outcome()[0], 'held')            # (message no longer calls package(): a held package raises)

    def test_r2_04b_two_mandatory_rules_that_differ_only_in_their_heading_are_not_copies_of_each_other(self):
        self.write(self.wiki_dir / 'a.md', self.section(self.must_meta('ascii-rule'), 'a.txt must be ASCII', 'Checked by the encoding gate.'))
        self.write(self.wiki_dir / 'b.md', self.section(self.must_meta('crlf-rule'), 'a.txt must end lines with CRLF', 'Checked by the encoding gate.'))
        self.commit()
        self.assertEqual(sorted(self.outcome()[1]), ['ascii-rule', 'crlf-rule'], self.package()['omitted']['by_reason'])

    # ---- encodings (r1 F1 follow-up) ---------------------------------------------------------------------------------------
    def test_r2_05_a_utf16_page_too_large_to_read_that_declares_a_mandatory_section_holds_the_node(self):
        with patch.object(wiki, 'MAX_PAGE_BYTES', 400):
            self.write(self.wiki_dir / 'rules.md', (self.must_text() + 'More detail. ' * 40).encode('utf-16'))
            self.commit()
            state, value = self.outcome()
        self.assertEqual(state, 'held', (state, value))

    def test_r2_06_a_utf16_page_without_a_bom_does_not_lose_its_mandatory_section(self):
        self.write(self.wiki_dir / 'rules.md', self.must_text().encode('utf-16-le'))             # ASCII text: every byte < 0x80
        self.commit()
        state, value = self.outcome()
        self.assertTrue(state == 'held' or value == ['required-rule'], (state, value))

    # ---- the cap (r1 F16 follow-up) ----------------------------------------------------------------------------------------
    def test_r2_07_valid_optional_pages_do_not_push_a_fitting_mandatory_rule_over_the_cap(self):
        self.write(self.wiki_dir / 'rules.md', self.must_text() + 'Detail. ' * 300 + '\n'); self.commit()
        cons = knowledge.consumer(self.ledger, 'P1', node=self.item())
        cap = len(canonical(knowledge.package(self.ledger, cons, cap_chars=16000))) + 400
        self.assertEqual([e['id'] for e in knowledge.package(self.ledger, cons, cap_chars=cap)['entries'] if e['must']], ['required-rule'])
        for i in range(15):                                                                      # optional, valid, unrelated pages
            self.write(self.wiki_dir / f'meeting-{i:02d}.md', f'## Weekly meeting {i:02d} of the team, held in the room on floor two\nMinutes {i:02d}: the coffee machine moved to room {i + 100}.\n')
        self.commit('optional pages')
        try:
            pkg = knowledge.package(self.ledger, cons, cap_chars=cap)
        except knowledge.KnowledgeOverflow as error:
            self.fail('valid optional pages hold the node: ' + str(error)[:300])
        self.assertEqual([e['id'] for e in pkg['entries'] if e['must']], ['required-rule'])

    # ---- declares_mandatory (r1 F5 follow-up) ------------------------------------------------------------------------------
    def test_r2_08_a_folder_named_like_a_page_does_not_make_the_project_declare_mandatory_knowledge(self):
        self.write(self.wiki_dir / 'notes.md', '## Note\nNothing mandatory here.\n')
        self.assertFalse(knowledge.declares_mandatory(self.ledger))                             # control
        (self.wiki_dir / 'archive.md').mkdir()
        self.write(self.wiki_dir / 'archive.md' / 'old.txt', 'kept for reference\n')
        self.assertFalse(knowledge.declares_mandatory(self.ledger))

    # ---- controls of the design choices (expected to pass) -----------------------------------------------------------------
    def test_r2_c1_content_that_cannot_be_known_is_reported_and_does_not_hold(self):
        self.write(self.wiki_dir / 'rules.md', self.must_text()); self.commit()
        config = self.root / '.onecrew' / 'config.json'
        self.write(config, json.dumps({'wiki': {'paths': ['docs/wiki', str(Path(self.temp.name) / 'offline-share')]}}))
        pkg = self.package()
        self.assertEqual([e['id'] for e in pkg['entries'] if e['must']], ['required-rule'])
        self.assertTrue(pkg['wiki']['missing_folders'])
        self.write(config, '{"wiki": {"paths": ["docs/wiki"]},}')
        pkg = self.package()
        self.assertEqual([e['id'] for e in pkg['entries'] if e['must']], ['required-rule']); self.assertTrue(pkg['wiki']['config_problem'])
        config.unlink()
        self.write(self.wiki_dir / 'locked.md', '## Locked\nunknown\n'); self.commit('locked page')
        real = Path.read_bytes
        def locked(path):
            if path.name == 'locked.md': raise PermissionError(13, 'The process cannot access the file')
            return real(path)
        with patch.object(Path, 'read_bytes', locked):
            pkg = self.package()
        self.assertEqual([e['id'] for e in pkg['entries'] if e['must']], ['required-rule'])
        self.assertTrue(any('cannot read' in p['problem'] for p in pkg['problems']), pkg['problems'])

    def test_r2_c2_an_unexpected_failure_runs_the_node_in_a_project_without_mandatory_knowledge(self):
        note = {'id': 'a-note', 'kind': 'note', 'label': 'verified', 'applies_to': ['a.txt'], 'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}
        self.write(self.wiki_dir / 'notes.md', self.section(note, 'a.txt note', 'a.txt is read by the importer.')); self.commit()
        with patch.object(knowledge, 'blob_of', side_effect=subprocess.TimeoutExpired(['git', 'hash-object'], 120)):
            produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        record = json.loads(self.store.read_blob(produced['receipt']))['knowledge']
        self.assertIn('TimeoutExpired', record.get('error') or '')

    def test_r2_c3_another_roots_newer_version_is_told_without_its_text(self):
        first = self.decision('a.txt format: one line', key='fmt')
        self.root_b('P2')
        self.decision('a.txt format: two lines (P2 detail)', plan='P2', key='fmt', base=first['version'])
        code, out = self.run_cli('continue', 'P1', '--json')
        entry = {e['text']: e for e in json.loads(out)['context']}['a.txt format: one line']
        self.assertEqual(entry['label'], 'stale')
        self.assertNotIn('two lines', json.dumps(entry))

    # ---- 2.2 entries when the judgement of their root fails ----------------------------------------------------------------
    def test_r2_09_a_22_entry_keeps_its_label_when_its_roots_contract_cannot_be_read(self):
        from onecrew.v2 import context, contract
        context.add(self.ledger, 'P1', kind='decision', label='verified', text='Keep a.txt short', source={'type': 'event', 'id': self.ledger_event()})
        self.assertEqual({e['text']: e['label'] for e in context.for_pack(self.ledger, 'P1')}, {'Keep a.txt short': 'verified'})   # control
        folder = contract.plan_dir(self.ledger, 'plan-ns:P1')
        folder.rename(folder.with_name(folder.name + '-moved'))          # an old root whose plan files are gone (cleanup, another machine)
        shown = {e['text']: (e['label'], e['stale_reason']) for e in context.for_pack(self.ledger, 'P1')}
        self.assertEqual(shown, {'Keep a.txt short': ('verified', None)})        # 2.2 rule: only lifecycle acts, and lifecycle was read
