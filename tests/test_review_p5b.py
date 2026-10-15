"""P5b: the two defects Codex verified in the P5 fix (1e3d27a).

1. `contract plan` returned the plan carried by the asking response itself, not the plan the prompt had shown (cut, with the
   pointer "contract plan"): the core stored the response's new plan before it ran the action. The pointer must give back what
   the prompt showed, also after a restart of the runner, whatever plan the asking response carries.
2. A page of one list item larger than the page (page.item) is continued with item_offset. When the budget had grown enough to
   hold the whole item, the continuation returned the item again from its first character and reported the end of the list
   (a defect since P4b-R2, not new in P5). A continuation must resume at the character where the previous page ended, whatever
   the budget is now, and pages must reassemble to exactly the stored content.

The reproductions go through the public paths only (paging.view, the real core run loop), so they run unchanged on 1e3d27a and
fail there for the behaviour, not for a missing API. Fixtures are temporary; no task, host or ledger of the machine is used."""
import hashlib
import json
import random
import unittest
from unittest.mock import patch

from onecrew import paging
from onecrew.ledger import LedgerError, canonical
from onecrew.owned import Owned
from tests.test_review_p3 import context
from tests.test_review_p5 import BudgetFixture, PlanFollower, s1_contract
from tests.test_work_contract import action

# Quotes, backslashes, tab, control characters, markup, JSON, a character outside the BMP, a newline: every one costs several
# characters once an item's JSON is embedded in a page as a string, so cuts land next to escapes.
ESCAPES = 'dòng "trích dẫn" \\ gạch ngược \\\\ \t tab \x01\x1f điều khiển </script> {"json": [1, 2]} 😀 đồng\n'


def text(size, tag=''):
    return (ESCAPES * (size // len(ESCAPES) + 1))[:size] + tag


def plan_text(size, tag):
    return (f'Kế hoạch {tag}: ' + 'bước đã xong, bước còn lại, bằng chứng receipt; ' * (size // 40 + 1))[:size] + f' HẾT-{tag}'


def commit(size, tag):
    return {'sha': tag, 'subject': text(size, tag)}


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def check_exact(case, items, pieces):
    """pieces: (item index, offset inside the item JSON, text) in the order delivered. Every item arrives once, in order, from
    its first character to its last, with no gap and no overlap: the concatenation is the stored content, hash included."""
    expected = [canonical(item) for item in items]
    got, last = {}, -1
    for index, offset, piece in pieces:
        case.assertGreaterEqual(index, last, 'items arrive in order'); last = index
        have = got.get(index, '')
        case.assertEqual(offset, len(have), f'item {index}: a piece starts at {offset} after {len(have)} delivered (gap or overlap)')
        got[index] = have + piece
    case.assertEqual([got.get(i) for i in range(len(items))], expected, 'every item arrives complete')
    case.assertEqual(sha(''.join(got[i] for i in range(len(items)))), sha(''.join(expected)))


class ItemContinuationTests(unittest.TestCase):
    """The protocol as a worker follows it: ask, read the page, follow `next`; the budget of each hop is chosen by the test."""

    def record(self, items, cursor=None):
        return {'action': 'git_log', 'request': {}, 'result': {'commits': items, 'next_cursor': cursor}}

    def walk(self, record, budgets, limit=300):
        field, ask, hop, pieces, trail = 'commits', {'offset': 0, 'item_offset': 0}, 0, [], []
        while True:
            self.assertLess(hop, limit, 'the continuation never ends')
            budget = budgets(hop) if callable(budgets) else budgets[hop % len(budgets)]
            value, pages = paging.view(record, budget, index=3, field=field, **ask)
            page = next(p for p in pages if p['field'] == field)
            self.assertEqual(page['offset'], ask['offset'], 'the page starts where it was asked to')
            for n, item in enumerate(value['result'][field]): pieces.append((page['offset'] + n, 0, canonical(item)))
            if page.get('item'):
                part = page['item']
                self.assertEqual((part['index'], part['offset']), (ask['offset'], ask['item_offset']),
                                 'a continuation inside an item resumes at the character where the previous page ended')
                pieces.append((part['index'], part['offset'], part['text']))
            else:
                self.assertEqual(ask['item_offset'], 0, f'RED-P5b: a continuation at item_offset {ask["item_offset"]} (budget {budget}) '
                                 f'did not come back as the rest of that item: it delivered {page["delivered"]} whole item(s) from '
                                 f'offset {page["offset"]}, eof={page["eof"]}')
            trail.append((budget, dict(page, shown=len(value['result'][field]))))
            hop += 1
            if page['eof']: return pieces, trail
            args = page['next']['arguments']
            self.assertEqual(page['next']['action'], 'receipt')
            ask = {'offset': args['offset'], 'item_offset': args.get('item_offset', 0)}

    def finished_items(self, trail):
        return [p for _, p in trail if p.get('item') and p['item']['offset'] + p['item']['delivered'] == p['item']['total']]

    # --- reproductions of the verified defect -------------------------------------------------------------------------

    def test_a_budget_that_grew_enough_for_the_whole_item_continues_the_item_and_does_not_restart_it(self):
        items = [commit(120, 'a'), commit(6000, 'b'), commit(150, 'c'), commit(150, 'd')]
        pieces, trail = self.walk(self.record(items), [1400, 1400, 30000, 30000])
        check_exact(self, items, pieces)
        first, second, third = trail[1][1], trail[2][1], trail[3][1] if len(trail) > 3 else None
        self.assertEqual(first['item']['offset'], 0); self.assertLess(first['item']['delivered'], first['item']['total'])
        self.assertEqual(second['item']['offset'], first['item']['delivered'], 'the second page resumes after the first')
        self.assertEqual(second['item']['offset'] + second['item']['delivered'], second['item']['total'], 'and ends the item')
        self.assertEqual(second['next']['arguments'], {'index': 3, 'field': 'commits', 'offset': 2},
                         'after the last page of an item the list goes on with the next item')
        self.assertTrue(trail[-1][1]['eof'])

    def test_the_budget_shrinking_and_growing_between_pages_never_moves_the_continuation(self):
        items = [commit(9000, 'big'), commit(100, 's')]
        pieces, trail = self.walk(self.record(items), [6000, 1100, 1000, 2500, 1200, 40000, 40000])
        check_exact(self, items, pieces)
        sizes = [p['item']['delivered'] for _, p in trail if p.get('item') and p['item']['index'] == 0]
        self.assertTrue(any(b > a * 2 for a, b in zip(sizes, sizes[1:])), 'the budget grew: ' + str(sizes))
        self.assertTrue(any(b < a for a, b in zip(sizes, sizes[1:])), 'and shrank: ' + str(sizes))

    def test_control_after_the_last_page_of_an_item_the_next_oversized_item_starts_from_its_first_character(self):
        items = [commit(5000, 'h0'), commit(5000, 'h1'), commit(90, 's')]
        pieces, trail = self.walk(self.record(items), [1500])
        check_exact(self, items, pieces)
        done = self.finished_items(trail)
        self.assertEqual([p['item']['index'] for p in done], [0, 1])
        for page in done[:-1]:
            self.assertEqual(page['next']['arguments'], {'index': 3, 'field': 'commits', 'offset': page['item']['index'] + 1})
        starts = [p['item']['offset'] for _, p in trail if p.get('item') and p['item']['index'] == 1][:1]
        self.assertEqual(starts, [0])

    def test_escaped_content_is_cut_and_continued_exactly_under_any_sequence_of_budgets(self):
        for seed in range(40):
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                items = [commit(rng.choice([10, 60, 300, 1500, 4000, 9000, 16000]), f'i{n}') for n in range(rng.randint(2, 6))]
                budgets = [rng.choice([1000, 1100, 1700, 2600, 4000, 7000, 12000, 30000]) for _ in range(rng.randint(3, 9))]
                pieces, trail = self.walk(self.record(items), budgets)
                check_exact(self, items, pieces)
                self.assertTrue(trail[-1][1]['eof'] and all(not p['eof'] for _, p in trail[:-1]), 'EOF exactly at the end')

    def test_a_continuation_past_the_end_of_an_item_is_a_request_error_whatever_the_budget(self):
        record = self.record([commit(6000, 'a'), commit(50, 'b')])
        length = len(canonical(record['result']['commits'][0]))
        for budget in (1200, 30000):  # the second budget used to hand back the item whole instead of refusing
            with self.subTest(budget=budget):
                with self.assertRaises(LedgerError): paging.view(record, budget, index=3, field='commits', offset=0, item_offset=length)

    def test_a_continuation_in_an_item_that_does_not_exist_is_a_request_error(self):
        record = self.record([commit(6000, 'a'), commit(50, 'b')])
        for budget in (1200, 30000):
            for offset in (2, 7):  # the list has items 0 and 1
                with self.subTest(budget=budget, offset=offset):
                    with self.assertRaises(LedgerError): paging.view(record, budget, index=3, field='commits', offset=offset, item_offset=5)

    def test_the_last_page_of_the_last_item_ends_the_list_or_goes_on_with_the_tools_own_cursor(self):
        items = [commit(80, 'a'), commit(5000, 'z')]
        pieces, trail = self.walk(self.record(items), [1500, 1500, 1500, 1500, 30000])
        self.assertTrue(trail[-1][1]['eof'] and 'next' not in trail[-1][1])
        # the same list with more behind it: the tool's cursor, never EOF
        more = self.record(items, cursor=40)
        ask, page = {'offset': 1, 'item_offset': 0}, None
        for budget in (1500, 1500, 1500, 1500, 30000, 30000):
            value, pages = paging.view(more, budget, index=3, field='commits', **ask)
            page = pages[0]
            if 'next' not in page or page['next']['action'] != 'receipt': break
            ask = {'offset': page['next']['arguments']['offset'], 'item_offset': page['next']['arguments'].get('item_offset', 0)}
        self.assertFalse(page['eof'])
        self.assertEqual(page['next'], {'action': 'git_log', 'arguments': {'directory': '', 'cursor': 40}})

    def test_a_page_that_begins_inside_the_first_item_offers_from_start(self):
        record = self.record([commit(6000, 'a')])
        _, pages = paging.view(record, 1400, index=3, field='commits', offset=0, item_offset=0)
        self.assertNotIn('from_start', pages[0])
        _, pages = paging.view(record, 30000, index=3, field='commits', offset=0, item_offset=700)
        self.assertIn('from_start', pages[0], 'RED-P5b: a page that begins at item_offset 700 of item 0 does not offer the way back to the start')
        self.assertEqual(pages[0]['from_start'], {'action': 'receipt', 'arguments': {'index': 3, 'field': 'commits', 'offset': 0}})

    # --- controls: green with or without the fix ------------------------------------------------------------------------

    def test_control_constant_budgets_reassemble_exactly(self):
        items = [commit(40, 'a'), commit(7000, 'b'), commit(2500, 'c'), commit(60, 'd')]
        for budget in (900, 1500, 4000):
            with self.subTest(budget=budget):
                pieces, trail = self.walk(self.record(items), [budget])
                check_exact(self, items, pieces)

    def test_control_a_budget_that_holds_the_list_delivers_it_whole_and_ends(self):
        items = [commit(200, 'a'), commit(300, 'b')]
        pieces, trail = self.walk(self.record(items), [30000])
        check_exact(self, items, pieces)
        self.assertEqual(len(trail), 1); self.assertTrue(trail[0][1]['eof'])

    def test_control_a_wrong_item_offset_with_a_small_budget_is_refused(self):
        record = self.record([commit(6000, 'a')])
        with self.assertRaises(LedgerError): paging.view(record, 1200, index=3, field='commits', offset=0, item_offset=10 ** 6)


class CapFollower(PlanFollower):
    """PlanFollower whose provider cap changes between steps: after each answer the cap used for the NEXT prompt is taken from
    `caps` (the first prompt of the job keeps the real cap, so the first-call check is unchanged)."""
    def __init__(self, ledger, first, caps):
        super().__init__(ledger, first)
        self.caps, self.used = list(caps), []

    def decide(self, pages, whole):
        value = super().decide(pages, whole)
        if self.caps: Owned.PROMPT_LIMITS['kiro'] = self.caps.pop(0)
        self.used.append(Owned.PROMPT_LIMITS['kiro'])
        return value


class ItemContinuationCoreTests(BudgetFixture):
    """The same defect through the real core: the room the prompt leaves for the latest result changes from step to step (the
    cap here; in a live run the plan, the history, the recovery section)."""

    def run_list(self, entries, caps, steps=60):
        self.addCleanup(Owned.PROMPT_LIMITS.update, dict(Owned.PROMPT_LIMITS))
        real = Owned._work_tool
        def tool(self_, task_id, state, name, args, profile):
            if name == 'list': return {'directory': '', 'entries': entries, 'next_cursor': None}
            return real(self_, task_id, state, name, args, profile)
        self.commit({'docs/a.txt': 'a\n'})
        worker = CapFollower(self.ledger, [action('list', directory='')], caps)
        with patch.object(Owned, '_work_tool', tool):
            runtime, task, worker, state = self.run_job(self.contract(edit=True, commands=True), [], steps=steps, worker=worker)
        return runtime, task, worker, state

    def pieces_of(self, worker):
        """What the worker was shown of the list, in order, from its latest results (the list itself, then receipt lookups)."""
        pieces = []
        for latest in worker.latest:
            for page in latest.get('page') or []:
                if page['field'] != 'entries': continue
                for n, entry in enumerate((latest.get('result') or {}).get('entries') or []):
                    pieces.append((page['offset'] + n, 0, canonical(entry)))
                if page.get('item'): pieces.append((page['item']['index'], page['item']['offset'], page['item']['text']))
        return pieces

    def test_a_cap_that_rises_after_a_split_item_continues_it_and_the_list_goes_on(self):
        entries = [{'path': text(4000, 'cuối'), 'kind': 'file'}, {'path': 'p1', 'kind': 'file'}, {'path': 'p2', 'kind': 'file'}]
        runtime, task, worker, state = self.run_list(entries, caps=[10600, 15000, 15000, 15000, 15000])
        self.assertEqual(state['phase'], 'running', str(state.get('message')))
        self.assertEqual([i for i, l in enumerate(worker.latest) if l.get('does_not_fit')], [])
        check_exact(self, entries, self.pieces_of(worker))
        parts = [p['item'] for l in worker.latest for p in l.get('page') or [] if p.get('item')]
        self.assertGreaterEqual(len(parts), 2, 'the item was split first: ' + str(parts))
        self.assertTrue(any(p['offset'] > 0 and p['offset'] + p['delivered'] == p['total'] for p in parts),
                        'RED-P5b: after the split, the room grew and the rest of the item was not delivered as such: ' + str(parts))

    def test_caps_that_rise_and_fall_between_steps_deliver_every_item_exactly_once(self):
        # Two items that fit one prompt at the high cap (the defect needs that: split at the low cap, then room for all of it) around
        # one that fits at none (22,000 characters); the cap alternates low / high / mid between the steps.
        entries = [{'path': text(4000, 'A'), 'kind': 'file'}, {'path': text(22000, 'B'), 'kind': 'file'},
                   {'path': text(4000, 'C'), 'kind': 'file'}, {'path': 'tiếp theo', 'kind': 'file'}]
        caps = [10600, 15000, 15000, 10600, 15000, 11500, 15000, 10600, 15000, 15000, 15000, 10600, 15000, 15000, 15000, 15000]
        runtime, task, worker, state = self.run_list(entries, caps=caps)
        self.assertEqual(state['phase'], 'running', str(state.get('message')))
        check_exact(self, entries, self.pieces_of(worker))
        sizes = [p['item']['delivered'] for l in worker.latest for p in l.get('page') or [] if p.get('item')]
        self.assertTrue(any(b > a for a, b in zip(sizes, sizes[1:])) and any(b < a for a, b in zip(sizes, sizes[1:])),
                        'the room changed between pages: ' + str(sizes))
        parts = [p['item'] for l in worker.latest for p in l.get('page') or [] if p.get('item')]
        self.assertTrue(any(p['index'] == 0 and p['offset'] > 0 and p['offset'] + p['delivered'] == p['total'] for p in parts),
                        'RED-P5b: the first item was not completed by a continuation after the room grew: ' + str(parts[:4]))


class PlanPointerTests(BudgetFixture):
    """`contract plan` returns the plan the prompt of that step showed, not the plan carried by the asking response."""

    def retrieved(self, runtime, task):
        out = []
        for ref in runtime.state(task)[1]['receipts']:
            if ref['action'] == 'contract':
                out.append(json.loads(runtime.store.read_blob(ref['blob']))['result'].get('text'))
        return out

    def start(self, first, contract=None):
        self.commit({'docs/a.txt': 'a\n'})
        return self.run_job(contract or s1_contract(), first, steps=0)

    # --- reproductions ---------------------------------------------------------------------------------------------------

    def test_each_retrieval_returns_the_plan_its_own_prompt_showed(self):
        p0, p1 = plan_text(4300, 'P0'), plan_text(3300, 'P1')
        first = [dict(action('read', path='docs/a.txt'), plan=p0), dict(action('contract', section='plan'), plan=p1),
                 dict(action('contract', section='plan'), plan='Short asking plan.'), dict(action('git_status'), plan='Done.')]
        runtime, task, worker, state = self.run_job(s1_contract(), first, steps=4)
        self.assertIn('contract plan', context(worker.prompts[1][0])['plan'], 'the prompt shows the plan cut, with its pointer')
        self.assertEqual(self.retrieved(runtime, task), [p0, p1],
                         'RED-P5b: a retrieval returned the plan its own response carried, not the one the prompt showed')

    def test_a_short_plan_is_returned_too_and_a_first_step_has_no_previous_plan(self):
        runtime, task, worker, state = self.start([dict(action('contract', section='plan'), plan='Asking at step 0.'),
                                                   dict(action('read', path='docs/a.txt'), plan='Plan ngắn đủ hiển thị.'),
                                                   dict(action('contract', section='plan'), plan='Asking at step 2.'),
                                                   dict(action('git_status'), plan='Done.')])
        initial = runtime.state(task)[1]['plan']  # what the job starts with
        for _ in range(4): runtime.run(task, steps=1)
        self.assertEqual(self.retrieved(runtime, task), [initial, 'Plan ngắn đủ hiển thị.'])

    def test_the_plan_is_retrieved_exactly_after_the_runner_restarted_before_the_retrieval_ran(self):
        p0 = plan_text(4300, 'P0')
        runtime, task, worker, _ = self.start([dict(action('read', path='docs/a.txt'), plan=p0),
                                               dict(action('contract', section='plan'), plan='Retrieve the previous plan before continuing.'),
                                               dict(action('git_status'), plan='Done.')])
        runtime.run(task, steps=1)
        real = Owned._tool
        def stopped(self_, task_id, state, name, args, profile):
            if name == 'contract': raise KeyboardInterrupt('runner stopped after the model answered, before the retrieval ran')
            return real(self_, task_id, state, name, args, profile)
        with patch.object(Owned, '_tool', stopped):
            with self.assertRaises(KeyboardInterrupt): runtime.run(task, steps=1)
        calls = len(worker.prompts)
        self.assertIsNotNone(runtime.state(task)[1]['response'], 'the answered step is in the checkpoint')
        runtime = Owned(self.ledger, worker); worker.runtime = runtime  # a new runner, from the durable checkpoint
        runtime.run(task, steps=1)
        self.assertEqual(len(worker.prompts), calls, 'the answered step runs without a new model call')
        self.assertEqual(self.retrieved(runtime, task), [p0], 'RED-P5b: the restarted runner returned another plan')

    def test_the_plan_is_retrieved_exactly_when_a_checkpoint_already_holds_the_new_plan(self):
        p0 = plan_text(4300, 'P0')
        runtime, task, worker, _ = self.start([dict(action('read', path='docs/a.txt'), plan=p0),
                                               dict(action('contract', section='plan'), plan='Retrieve the previous plan before continuing.'),
                                               dict(action('git_status'), plan='Done.')])
        runtime.run(task, steps=1)
        real = Owned._tool
        def checkpointed(self_, task_id, state, name, args, profile):
            if name == 'contract':
                seq, _ = self_.state(task_id)
                self_.persist(task_id, seq, state)  # saved AFTER the response's plan was stored, then the runner dies
                raise KeyboardInterrupt('runner stopped after a checkpoint that holds the new plan')
            return real(self_, task_id, state, name, args, profile)
        with patch.object(Owned, '_tool', checkpointed):
            with self.assertRaises(KeyboardInterrupt): runtime.run(task, steps=1)
        saved = runtime.state(task)[1]
        self.assertEqual(saved['plan'], 'Retrieve the previous plan before continuing.', 'the checkpoint holds the new plan')
        runtime = Owned(self.ledger, worker); worker.runtime = runtime
        runtime.run(task, steps=1)
        self.assertEqual(self.retrieved(runtime, task), [p0], 'RED-P5b: the plan the prompt showed was lost with that checkpoint')

    def test_a_reset_that_clears_the_response_without_moving_the_step_returns_the_plan_the_new_prompt_showed(self):
        # solution_gate.reply(revise_solution) rewrites an owned_execution checkpoint with response=None (and review, context_prompt,
        # review_prompt) and leaves step and plan: the next prompt, at the SAME step, shows the plan the interrupted response wrote.
        p0, p1 = plan_text(4300, 'P0'), plan_text(3300, 'P1')
        runtime, task, worker, _ = self.start([dict(action('read', path='docs/a.txt'), plan=p0), dict(action('git_status'), plan=p1),
                                               dict(action('contract', section='plan'), plan='Retrieve the previous plan before continuing.'),
                                               dict(action('git_status'), plan='Done.')])
        runtime.run(task, steps=1)
        real = Owned._tool
        def checkpointed(self_, task_id, state, name, args, profile):
            if name == 'git_status':
                seq, _ = self_.state(task_id)
                self_.persist(task_id, seq, state)  # the response, the new plan and the plan it was written against
                raise KeyboardInterrupt('runner stopped after a checkpoint that holds the answered step')
            return real(self_, task_id, state, name, args, profile)
        with patch.object(Owned, '_tool', checkpointed):
            with self.assertRaises(KeyboardInterrupt): runtime.run(task, steps=1)
        seq, saved = runtime.state(task)
        self.assertEqual((saved['plan'], saved['step']), (p1, 1))
        saved.update(response=None, review=None, context_prompt=None, review_prompt=None)  # the reset; step and plan stay
        runtime.persist(task, seq, saved)
        runtime = Owned(self.ledger, worker); worker.runtime = runtime
        runtime.run(task, steps=1)  # a new prompt at step 1 shows p1 (cut); the worker asks for it
        self.assertIn('contract plan', context(worker.prompts[-1][0])['plan'])
        self.assertEqual(self.retrieved(runtime, task), [p1], 'RED-P5b: the retrieval returned the plan of the step before the reset')

    # --- controls: green with or without the fix ------------------------------------------------------------------------

    def test_control_other_contract_parts_are_returned_exactly_whatever_plan_the_request_carries(self):
        contract = s1_contract()
        first = [dict(action('read', path='docs/a.txt'), plan='Plan 0.'),
                 dict(action('contract', section='goal'), plan='Asking 1.'),
                 dict(action('contract', section='acceptance', index=1), plan='Asking 2.'),
                 dict(action('contract', section='preserve', index=0), plan='Asking 3.'), dict(action('git_status'), plan='Done.')]
        runtime, task, worker, state = self.run_job(contract, first, steps=5)
        self.assertEqual(self.retrieved(runtime, task), [contract['goal'], contract['acceptance'][1], contract['preserve'][0]])

    def test_control_a_worker_that_repeats_its_plan_in_the_request_gets_it_back(self):
        p0 = plan_text(4300, 'P0')
        first = [dict(action('read', path='docs/a.txt'), plan=p0), dict(action('contract', section='plan'), plan=p0),
                 dict(action('git_status'), plan='Done.')]
        runtime, task, worker, state = self.run_job(s1_contract(), first, steps=3)
        self.assertEqual(self.retrieved(runtime, task), [p0])


if __name__ == '__main__':
    unittest.main()
