import json
import os
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import goal_history, plan, report, tracking
from onecrew.v2.verifiers import advisor
from tests.v2_fixture import AUTHOR, DECISION, AdvisorFixture, plan_json, sourced


class GoalOrigin(AdvisorFixture):
    words = 'Giữ mục tiêu tôi đã gõ.'

    def pin(self):
        return goal_history.pin(self.ledger, 'P1', self.words)

    def amend(self, raw, *sources):
        return plan.amend(self.ledger, 'P1', raw, 'extend the sample', AUTHOR, goal_sources=sources)

    def observe(self, kind, text, revision=1, source=None, **values):
        with self.ledger.transaction(write=True) as conn:
            task = plan.derive(self.ledger, conn, 'P1')['task_id']
            self.ledger._event(conn, task, 'hook.observed',
                               dict(observation=kind, text=text, session='fixture', revision=revision,
                                    source=source or ('ai_claim' if kind == 'ai_question' else 'claude_session'), **values))
            return conn.execute('SELECT max(seq) FROM events WHERE task_id=?', (task,)).fetchone()[0]

    def test_original_owner_words_and_revision_one_survive_two_approved_amendments(self):
        self.propose()
        initial = self.pin()
        for rev in (1, 2, 3):
            if rev > 1:
                self.amend(plan_json(title=f'Change {rev}'))
            view = plan.approve(self.ledger, 'P1', 'owner', 'fixture approval', revision=rev)
            self.assertEqual(view['approved_revision'], rev)
            self.assertEqual(view['goal_history']['original']['text'], self.words)
            self.assertEqual(view['goal_history']['revision_one']['sha'], initial['sha'])

    def test_amend_cannot_replace_typed_goal_or_promote_unsourced_text(self):
        self.propose()
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'codex'}), self.assertRaises(LedgerError):
            self.pin()
        self.pin()
        with self.assertRaises(LedgerError):
            goal_history.pin(self.ledger, 'P1', 'replacement')
        amended = self.amend(sourced(plan_json()))['goal_history']
        self.assertEqual(amended['original']['text'], self.words)
        self.assertEqual(amended['sources'], [])
        with self.assertRaises(LedgerError):
            self.amend(plan_json(title='Invalid source'), 999999)
        self.assertEqual(plan.show(self.ledger, 'P1')['revision'], 2)

    def test_typed_addition_links_source_and_revision_without_rewriting_goal(self):
        self.propose()
        self.pin()
        words = 'Thêm phần tôi vừa yêu cầu.'
        seq = self.observe('owner_prompt', words, source='owner')  # historical hook row
        history = self.amend(plan_json(title='Two'), seq)['goal_history']
        self.assertEqual(history['sources'], [dict(kind='typed', seq=seq, text=words, source='claude_session', observed_revision=1, revision=2)])
        self.assertEqual(history['original']['text'], self.words)
        self.assertEqual(history['unsourced_revisions'], [2])
        self.assertFalse(plan.show(self.ledger, 'P1', 1)['goal_history']['sources'])
        with self.assertRaises(LedgerError):
            self.amend(plan_json(title='Three'), seq)

    def test_citing_pinned_owner_words_clears_only_that_revision(self):
        self.propose()
        self.pin()
        pin = plan.show(self.ledger, 'P1')['goal_history']['original']
        history = self.amend(plan_json(title='Two'), pin['seq'])['goal_history']
        self.assertEqual(history['unsourced_revisions'], [])
        self.assertIn(f"Chủ gõ (#{pin['seq']}): {self.words}", '\n'.join(goal_history.lines(history)))
        self.assertEqual(self.amend(plan_json(title='Three'))['goal_history']['unsourced_revisions'], [3])

    def test_machine_prompt_cannot_source_an_amendment(self):
        self.propose()
        seq = self.observe('owner_prompt', 'diagnostic', source='claude_machine')
        with self.assertRaises(LedgerError):
            self.amend(plan_json(title='Two'), seq)

    def test_picked_recommendation_and_other_pick_link_ai_question_and_choice(self):
        self.propose()
        sources, question_seqs = [], []
        for n, answer in enumerate(('A (Recommended)', 'B')):
            qid = f'q{n}'
            question_seqs.append(self.observe('ai_question', 'Chọn cách nào?', question_id=qid, options=['A (Recommended)', 'B']))
            sources.append(self.observe('owner_choice', answer, question_id=qid))
        entries = self.amend(plan_json(title='Choices'), *sources)['goal_history']['sources']
        self.assertEqual([e['kind'] for e in entries], ['picked_recommendation', 'picked_other'])
        self.assertEqual([e['question_seq'] for e in entries], question_seqs)
        self.assertEqual([e['seq'] for e in entries], sources)
        self.assertTrue(all(e['question'] == 'Chọn cách nào?' and e['revision'] == 2 for e in entries))
        present = report.render_present(self.ledger.state_root, 'P1')
        for seq, label in zip(sources, ('khuyến nghị của AI', 'phương án khác của AI')):
            self.assertIn(f'Ghi nhận trong phiên Claude (chưa xác thực) ({label}) (#{seq})', present)
        self.assertNotIn('Chủ chọn', '\n'.join(line for line in present.splitlines() if 'Bản 2 ·' in line))
        seq = self.observe('owner_choice', 'B', revision=2, question_id='unmatched')
        with self.assertRaises(LedgerError):
            self.amend(plan_json(title='No question'), seq)

    def test_show_present_and_approval_page_show_cumulative_items_owned_and_origin(self):
        self.propose()
        self.pin()
        raw = plan_json()
        raw['items'].append(dict(id='I2', title='New deliverable', tier='should'))
        self.amend(raw)
        raw['scope']['owned'].append('b.txt')
        seq = self.observe('owner_prompt', 'Thêm một tệp.', revision=2)
        self.amend(raw, seq)
        view = plan.show(self.ledger, 'P1')['goal_history']
        self.assertEqual(view['delta']['items']['added'], ['I2'])
        self.assertEqual(view['delta']['owned']['added'], ['b.txt'])
        page = tracking.detail(self.ledger.state_root, 'P1', comparison=False)
        card = next(n for n in page['needs_user'] if n['kind'] == 'approve')
        present = report.render_present(self.ledger.state_root, 'P1')
        for text in ('I2', 'b.txt', self.words, f'Ghi nhận trong phiên Claude (chưa xác thực) (#{seq}): Thêm một tệp.'):
            self.assertIn(text, present)
            self.assertIn(text, ' '.join(card['goal_history_lines']))

    def test_scope_change_with_stale_owner_presentation_is_flagged_before_approval(self):
        raw = sourced(plan_json())
        self.propose(value=raw)
        raw['scope']['owned'].append('new.txt')
        view = self.amend(raw)
        self.assertTrue(view['goal_history']['presentation_stale'])
        self.assertIn('Cần đối chiếu trước khi duyệt', report.render_present(self.ledger.state_root, 'P1'))
        raw['presentation']['request'] = 'Bổ sung tài liệu cho người đọc.'
        self.assertFalse(self.amend(raw)['goal_history']['presentation_stale'])

    def test_q1_uses_pinned_goal_revision_one_and_sourced_changes(self):
        self.start()
        self.pin()
        seq = self.observe('owner_prompt', 'Thêm hướng dẫn.')
        raw = sourced(plan_json(), decisions=[DECISION])
        raw['scope']['owned'].append('guide.txt')
        view = self.amend(raw, seq)
        advisor.advise(self.ledger, 'P1', 'claude-opus-5-5')
        prompt = self.prompts[0][0]
        context = json.loads(prompt.split('\nContract:\n', 1)[1])
        self.assertEqual(context['goal_history'], view['goal_history'])
        self.assertEqual(context['goal_history']['original']['text'], self.words)
        self.assertIn('guide.txt', context['owned'])
        self.assertIn('Which changes exceed that scope?', prompt)

    def test_legacy_origin_without_provenance_stays_unknown(self):
        raw = sourced(plan_json())
        self.propose(value=raw)
        original = plan.show(self.ledger, 'P1')['goal_history']['original']
        self.assertEqual(original, {'kind': 'unknown', 'text': raw['origin']['quote']})
        self.assertIn('nguồn chưa rõ', report.render_present(self.ledger.state_root, 'P1'))

    def test_amend_receipt_marks_removed_inputs_and_added_unscanned_as_acceptance(self):
        raw = plan_json()
        cfg = raw['milestones'][0]['verifier']['config']
        cfg['inputs'] = ['a.txt', 'b.txt']
        self.propose(value=raw)
        for field, value in [('inputs', ['a.txt']), ('inputs_unscanned', ['a.txt'])]:
            with self.subTest(field=field):
                cfg[field] = value
                self.amend(raw)
                event = [p for k, p in self.events() if k == 'plan.amended'][-1]
                diff = event['acceptance_diff']
                self.assertEqual(diff['classification'], 'U1')
                self.assertTrue(any(c['acceptance'] and field in c['path'] for c in diff['changes']))
