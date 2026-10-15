"""P6: the two evidence-transport gaps Codex verified after P5b (d83b834), and their controls.

R1. The completion reviewer could not get a receipt that does not fit the prompt. review_evidence.packet() included a requested
    receipt whole or not at all, so under Kiro's cap a ~11,000-character file requested by the reviewer came back as
    requested=[0], not_included=[0], full_receipts=[]; asking again was an "unavailable" rejection that told the worker to re-read
    the same file. The reviewer now receives the receipt PAGE BY PAGE through the same paging.view the worker uses, asks for the
    next page with the `next` it was given (evidence_requests accepts {index, field, offset, item_offset}), carries its own notes
    from round to round, and the core distinguishes: the evidence proves the work wrong (a rejection, to the worker), the evidence
    could not be completed within the bound (the job is BLOCKED, nothing accepted, nothing rejected, no worker call spent), and a
    request no valid page can serve (blocked, naming the part that takes the room).
R2. A page of a list could be a sliver: a small item followed by one that does not fit gave a page of a few characters, and the
    worker's valid-page rule (>= 1,000 characters of content) blocked the job although the next page would have carried ~6,000.
    The paginator now fills such a page with the start of the next item, so a page that is not final carries real content.

Synthetic data are marked as such: the lists and files below are generated; the tool code (paging.view, the real core run loop,
the real git_log on a temporary repository) is the product's. Nothing here is a live run. Only public paths are used, so the
tests run unchanged on d83b834 and fail there for the behaviour, not for a missing API."""
import hashlib
import json
import random
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew import paging
from onecrew.ledger import LedgerError, canonical
from onecrew.owned import Owned, PromptBudgetError
from tests.test_review_p3 import CAP, context
from tests.test_review_p5 import BudgetFixture, FlowWorker, ACCEPT, s1_contract, vietnamese_source
from tests import test_review_p5b as p5b  # by module: importing its TestCase classes by name would make this module run them too
from tests.test_review_p5b import CapFollower, check_exact, commit, text
from tests.test_work_contract import action, python

MIN_PAGE = 1000  # the content a page that is not final owes the reader (the P5 valid-page rule), written here as a literal


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def page_content(value, pages):
    """Characters of the result itself in a page: whole items as their JSON, string values, and the item chunk (page.item)."""
    out = 0
    for page in pages:
        shown = value['result'].get(page['field'])
        out += len(shown) if isinstance(shown, str) else sum(len(canonical(x)) for x in shown or [])
        if page.get('item'): out += page['item']['delivered']
    return out


# --- R2: pages of a list ---------------------------------------------------------------------------------------------------

class SliverPagingTests(unittest.TestCase):
    """paging.view on synthetic lists, followed the way a worker follows page.next, with the budget of each hop chosen here."""

    def record(self, items, cursor=None):
        return {'action': 'git_log', 'request': {}, 'result': {'commits': items, 'next_cursor': cursor}}

    def walk(self, record, budgets, limit=400):
        """Follow page.next. A page = whole items from page.offset, then (optionally) the start of the next item as page.item. A
        continuation inside an item (item_offset) is that item's remainder. Returns (pieces, trail) for check_exact."""
        ask, hop, pieces, trail = {'offset': 0, 'item_offset': 0}, 0, [], []
        while True:
            self.assertLess(hop, limit, 'the continuation never ends')
            budget = budgets(hop) if callable(budgets) else budgets[hop % len(budgets)]
            value, pages = paging.view(record, budget, index=3, field='commits', **ask)
            page = next(p for p in pages if p['field'] == 'commits')
            self.assertEqual(page['offset'], ask['offset'], 'the page starts where it was asked to')
            whole = value['result']['commits']
            for n, item in enumerate(whole): pieces.append((page['offset'] + n, 0, canonical(item)))
            chunk = page.get('item')
            if chunk:
                if ask['item_offset']:
                    self.assertEqual((chunk['index'], chunk['offset'], len(whole)), (ask['offset'], ask['item_offset'], 0),
                                     'a continuation inside an item is that item alone, from the character where it ended')
                else:
                    self.assertEqual((chunk['index'], chunk['offset']), (page['offset'] + len(whole), 0),
                                     'the chunk is the start of the item right after the whole items')
                pieces.append((chunk['index'], chunk['offset'], chunk['text']))
            else:
                self.assertEqual(ask['item_offset'], 0, 'a continuation inside an item comes back as that item')
            content = page_content(value, pages)
            self.assertGreater(content, 0, 'RED-P6: a page without content of the result (metadata only)')
            # The one page that may carry less than MIN_PAGE although more follows: the REMAINDER of an item that completes it (the
            # page of a continuation holds that item alone); there is at most one per split item.
            finishes = bool(chunk) and ask['item_offset'] > 0 and chunk['offset'] + chunk['delivered'] == chunk['total']
            trail.append({'budget': budget, 'content': content, 'page': page, 'whole': len(whole), 'finishes_item': finishes})
            hop += 1
            if page['eof']: return pieces, trail
            args = page['next']['arguments']
            ask = {'offset': args['offset'], 'item_offset': args.get('item_offset', 0)}

    # --- reproductions of the verified defect ------------------------------------------------------------------------------

    def test_a_small_first_item_does_not_leave_a_sliver_page(self):
        items = [commit(60, 'a'), commit(6000, 'b'), commit(150, 'c')]
        value, pages = paging.view(self.record(items), 2400, index=3, field='commits', offset=0)
        content = page_content(value, pages)
        self.assertGreaterEqual(content, MIN_PAGE, f'RED-P6: a page of {content} characters of content with room for more ({pages[0]["delivered"]} item(s))')
        self.assertFalse(pages[0]['eof'])

    def test_every_page_that_is_not_final_carries_real_content_and_the_walk_is_bounded(self):
        for seed in range(40):
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                sizes = [rng.choice([5, 40, 120, 300]) for _ in range(rng.randint(1, 4))] + \
                        [rng.choice([40, 600, 2500, 6000, 12000]) for _ in range(rng.randint(2, 6))]
                rng.shuffle(sizes)
                items = [commit(size, f'i{n}') for n, size in enumerate(sizes)]
                budgets = [rng.choice([3000, 4000, 7000, 12000, 30000]) for _ in range(rng.randint(2, 6))]
                pieces, trail = self.walk(self.record(items), budgets)
                check_exact(self, items, pieces)
                total = sum(len(canonical(i)) for i in items)
                for hop in trail[:-1]:
                    if hop['finishes_item']: continue  # the remainder of one item (see walk)
                    self.assertGreaterEqual(hop['content'], MIN_PAGE, f'RED-P6: page at budget {hop["budget"]} with {hop["content"]} characters of content')
                split = {h['page']['item']['index'] for h in trail if h['page'].get('item')}
                self.assertEqual(sum(h['finishes_item'] for h in trail), len(split), 'one finishing page per item that was split, no more')
                self.assertLessEqual(len(trail), total // MIN_PAGE + 2 * len(items) + 2, 'the walk is bounded by the content it must deliver')
                self.assertTrue(trail[-1]['page']['eof'] and all(not h['page']['eof'] for h in trail[:-1]), 'EOF exactly at the end')

    def test_the_item_that_starts_a_page_continues_with_item_offset_and_the_list_goes_on(self):
        items = [commit(80, 'a'), commit(7000, 'b'), commit(90, 'c'), commit(8000, 'd'), commit(70, 'e')]
        pieces, trail = self.walk(self.record(items), [2600, 2600, 9000, 2600])
        check_exact(self, items, pieces)
        mixed = [h for h in trail if h['page'].get('item') and h['whole']]
        self.assertTrue(mixed, 'RED-P6: no page started the big item after the small one: ' + str([(h['whole'], bool(h['page'].get('item'))) for h in trail]))
        first = mixed[0]['page']
        self.assertEqual(first['next']['arguments'], {'index': 3, 'field': 'commits', 'offset': first['item']['index'], 'item_offset': first['item']['delivered']})

    # --- controls: green with or without the fix -------------------------------------------------------------------------

    def test_control_items_are_not_split_when_whole_items_already_fill_the_page(self):
        items = [commit(600, f'i{n}') for n in range(8)]
        pieces, trail = self.walk(self.record(items), [3000])
        check_exact(self, items, pieces)
        self.assertTrue(all(h['page'].get('item') is None for h in trail), 'whole items already carry >= 1,000 characters: no item is split')

    def test_control_a_complete_small_list_is_one_page_and_eof(self):
        items = [commit(40, 'a'), commit(300, 'b')]
        pieces, trail = self.walk(self.record(items), [30000])
        check_exact(self, items, pieces)
        self.assertEqual(len(trail), 1); self.assertTrue(trail[0]['page']['eof'])

    def test_control_the_first_item_larger_than_the_page_is_paged_by_item_offset(self):
        items = [commit(9000, 'big'), commit(100, 's')]
        pieces, trail = self.walk(self.record(items), [2600, 4000, 30000])
        check_exact(self, items, pieces)


def exact_item(size, tag='c'):
    """A commit-shaped item whose JSON is exactly `size` characters (synthetic)."""
    base = len(canonical({'sha': tag, 'subject': ''}))
    value = {'sha': tag, 'subject': 'x' * (size - base)}
    assert len(canonical(value)) == size
    return value


def owes_nothing(value, pages):
    """The valid-page rule the worker's prompt builder applies (owned._fit_work.valid): the whole result, the last of what there is, or
    MIN_PAGE characters of the result itself."""
    return not pages or all(p['eof'] for p in pages) or page_content(value, pages) >= MIN_PAGE


class FillRuleTests(unittest.TestCase):
    """L1 and L2 of the P6 probe (verified by an independent re-implementation): the rule that fills a short page with the start of the
    next item (R2) used room that other fields of the same result would have had, and its longer `next` landed a re-allocation a few
    characters over the budget so the page shrank as the budget grew. Synthetic lists (generated sizes; the numbers are the ones the
    verifier measured), the product's paging.view."""

    def commits(self, sizes):
        return {'action': 'git_log', 'request': {}, 'result': {'commits': [exact_item(s) for s in sizes], 'next_cursor': None}}

    def view(self, sizes, budget, **kw):
        return paging.view(self.commits(sizes), budget, index=3, field='commits', **kw)

    # --- L1: a page the whole-items rule served validly stays valid ------------------------------------------------------------

    def test_a_page_of_whole_items_that_is_valid_is_not_replaced_by_a_filled_one_that_is_not(self):
        for sizes, budget in (([237, 580, 237, 579, 1286], 1300), ([237, 580, 237, 48], 1300), ([400, 580], 1175)):
            with self.subTest(sizes=sizes, budget=budget):
                value, pages = self.view(sizes, budget)
                content = page_content(value, pages)
                self.assertTrue(owes_nothing(value, pages), f'RED-P6: {content} characters of content and not the last page, where 3 whole items were enough')
                self.assertLessEqual(len(canonical(dict(value, page=pages))), budget)

    def test_the_page_of_a_list_next_to_a_long_note_stays_valid_in_every_room_the_whole_items_page_was(self):
        # Core-level (the exact valid() rule of _fit_work): list entries at offset 2 of a receipt lookup + a 281-character note. At
        # d83b834 the page is valid from a room of 1,732 characters up; with the fill rule alone it was refused in 1,744..1,908 (the
        # room that includes RESULT_RESERVE=1800, the designed operating point).
        entries = [{'path': (chr(97 + i % 26) * n)[:n], 'kind': 'file'} for i, n in enumerate([9800, 593, 120, 594, 105, 1287, 9799, 26])]
        result = {'directory': '', 'entries': entries, 'notes': 'n' * 281, 'next_cursor': None}
        lookup = {'action': 'receipt', 'arguments': {'index': 1, 'field': 'entries', 'offset': 2}, 'result': {'action': 'list', 'request': {}, 'result': result}}
        refused = [left for left in range(1732, 2800, 4) if not self.core_serves(lookup, left)]
        self.assertEqual(refused, [], f'RED-P6: the core refused {len(refused)} rooms the whole-items page was valid in, from {refused[:1]} to {refused[-1:]}')

    def test_the_changed_paths_page_of_a_command_next_to_its_stderr_stays_valid_in_every_room_it_was(self):
        changed = [{'status': 'M', 'path': 'c' * n} for n in (60, 90, 120, 200, 150, 3000, 50)]
        result = {'exit_code': 1, 'stdout': '', 'stderr': 'e' * 700, 'changed': changed, 'log': None}
        lookup = {'action': 'receipt', 'arguments': {'index': 1, 'field': 'changed', 'offset': 0}, 'result': {'action': 'run', 'arguments': {}, 'result': result}}
        refused = [left for left in range(1676, 2800, 4) if not self.core_serves(lookup, left)]
        self.assertEqual(refused, [], f'RED-P6: the core refused {len(refused)} rooms the whole-items page was valid in, from {refused[:1]} to {refused[-1:]}')

    @staticmethod
    def core_serves(record, left):
        """owned._fit_work's valid() for the latest result `record` in `left` characters: no starvation, MIN_PAGE_CONTENT (or all of
        it) delivered, within the room. No model, no store beyond the one record."""
        class Store:
            def read_blob(self, _): return json.dumps(record).encode()
        runtime = Owned.__new__(Owned); runtime.store = Store()
        state = {'receipts': [{'index': 3, 'action': record['action'], 'blob': 'b'}]}
        runtime._page_starved = False
        runtime._latest_result(state, 10 ** 8)
        want = min(Owned.MIN_PAGE_CONTENT, runtime._page_content)
        runtime._page_starved = False
        shown = runtime._latest_result(state, left)
        return not runtime._page_starved and runtime._page_content >= want and len(canonical(shown)) <= left

    # --- the fill rule itself ---------------------------------------------------------------------------------------------------

    def test_a_short_page_is_filled_with_the_next_item_when_that_makes_it_valid(self):
        for sizes, budget in (([900, 63, 900, 63, 900, 900, 26, 579], 1575), ([237, 579, 900, 1286, 580], 1375), ([63, 579, 237, 9800, 9800], 1525)):
            with self.subTest(sizes=sizes, budget=budget):
                value, pages = self.view(sizes, budget)
                self.assertTrue(owes_nothing(value, pages), f'RED-P6: {page_content(value, pages)} characters of content with room in the budget')
                self.assertTrue(pages[0].get('item'), 'the start of the next item is what completed it')
                self.assertLessEqual(len(canonical(dict(value, page=pages))), budget)

    def test_a_page_that_filling_cannot_make_valid_is_the_page_of_whole_items(self):
        # a few characters of the next item are not worth a page entry, and take the room other fields would have had
        value, pages = self.view([400, 237, 9800, 1271, 106], 1050)
        self.assertEqual((pages[0]['delivered'], pages[0].get('item')), (2, None), f'RED-P6: {pages[0]}')
        self.assertEqual((value, pages), self.view([400, 237, 9800, 1271, 106], 1050, fill=False))

    def test_a_valid_page_does_not_become_invalid_when_the_budget_grows(self):
        for sizes in ([579, 237, 26, 579, 9800], [580, 106, 1286, 9800, 48, 579, 26, 3519, 237, 1271, 63]):
            with self.subTest(sizes=sizes):
                valid_since = None
                for budget in range(1000, 3000, 10):
                    value, pages = self.view(sizes, budget)
                    ok = owes_nothing(value, pages)
                    if ok and valid_since is None: valid_since = budget
                    if valid_since is not None:
                        self.assertTrue(ok, f'RED-P6: valid at {valid_since}, not at {budget} ({page_content(value, pages)} characters)')

    def test_a_larger_budget_gives_a_page_that_is_not_smaller_than_the_page_of_whole_items(self):
        # L2: the re-allocation that lands a few characters over the budget used to be dropped, leaving less than the whole-items page
        value, pages = self.view([579, 237, 26, 579, 9800], 1200)
        self.assertGreaterEqual(page_content(value, pages), 842, 'RED-P6: the page of whole items delivers 842 characters here')
        self.assertLessEqual(len(canonical(dict(value, page=pages))), 1200)

    def test_property_a_page_is_within_the_budget_never_less_than_whole_items_and_never_worse_than_what_was_valid(self):
        sizes_pool = [26, 48, 63, 106, 120, 237, 400, 580, 579, 594, 900, 1271, 1286, 3519, 9800]
        checked = 0
        for seed in range(60):
            rng = random.Random(seed)
            sizes = [rng.choice(sizes_pool) for _ in range(rng.randint(2, 9))]
            for budget in rng.sample(range(900, 3400, 25), 8):
                with self.subTest(seed=seed, budget=budget):
                    try: whole = self.view(sizes, budget, fill=False)
                    except LedgerError: continue  # a budget no page fits: view raises the same for both
                    value, pages = self.view(sizes, budget)
                    checked += 1
                    self.assertLessEqual(len(canonical(dict(value, page=pages))), budget, 'within the budget')
                    self.assertGreaterEqual(page_content(value, pages), page_content(*whole), 'never less than the page of whole items')
                    if owes_nothing(*whole): self.assertEqual((value, pages), whole, 'a page that owes nothing is exactly the page of whole items')
                    else: self.assertTrue(owes_nothing(value, pages) or (value, pages) == whole, 'filled only to make the page valid')
        self.assertGreater(checked, 300)


# --- R2 through the real core ---------------------------------------------------------------------------------------------

class SliverCoreTests(BudgetFixture):
    """The worker's prompt builder with a provider cap that changes between steps (Owned.PROMPT_LIMITS, as in P5b)."""
    run_list = p5b.ItemContinuationCoreTests.run_list      # synthetic list result through the real core and prompt builder
    pieces_of = p5b.ItemContinuationCoreTests.pieces_of

    def test_a_small_item_before_a_large_one_is_served_not_blocked(self):
        # The repro Codex found (oos_sliver_block.py of P5b): at the S1 shape the page was 27 characters and the job was blocked.
        entries = [{'path': 'p0', 'kind': 'file'}, {'path': text(6500, 'cuối'), 'kind': 'file'}, {'path': 'p2', 'kind': 'file'}]
        runtime, task, worker, state = self.run_list(entries, caps=[10600, 15000, 15000, 15000, 15000])
        self.assertEqual(state['phase'], 'running', 'RED-P6: ' + str(state.get('message')))
        self.assertEqual([i for i, l in enumerate(worker.latest) if l.get('does_not_fit')], [])
        check_exact(self, entries, self.pieces_of(worker))

    def test_real_git_log_output_with_a_short_subject_first_is_served_under_a_tight_cap(self):
        # Real tool output: git_log on a temporary repository. The commit messages are generated (500-character subjects, the cap
        # git_log keeps); the tool, the paging and the prompt builder are the product's. The tight cap is set by the test.
        self.addCleanup(Owned.PROMPT_LIMITS.update, dict(Owned.PROMPT_LIMITS))
        for n in range(9): self.git('commit', '-q', '--allow-empty', '-m', (f'commit {n} ' + 'lý do dài của thay đổi này, ' * 30)[:500])
        self.git('commit', '-q', '--allow-empty', '-m', 'newest: ngắn')  # git_log lists the newest first
        from onecrew.work_tools import ws_root  # noqa: F401  (the workspace exists for a work job)
        worker = CapFollower(self.ledger, [action('git_log', directory='')], [10200, 10200, 10200, 15000, 10200, 10200, 15000, 15000, 15000, 15000])
        runtime, task, worker, state = self.run_job(self.contract(edit=True, commands=True), [], steps=40, worker=worker)
        self.assertEqual(state['phase'], 'running', 'RED-P6: ' + str(state.get('message')))
        commits = json.loads(runtime.store.read_blob(runtime.state(task)[1]['receipts'][0]['blob']))['result']['commits']
        pieces = []
        for latest in worker.latest:
            for page in latest.get('page') or []:
                if page['field'] != 'commits': continue
                for n, item in enumerate((latest.get('result') or {}).get('commits') or []): pieces.append((page['offset'] + n, 0, canonical(item)))
                if page.get('item'): pieces.append((page['item']['index'], page['item']['offset'], page['item']['text']))
        check_exact(self, commits, pieces)

    def test_a_runner_restart_between_a_mixed_page_and_its_continuation_loses_nothing(self):
        self.addCleanup(Owned.PROMPT_LIMITS.update, dict(Owned.PROMPT_LIMITS))
        entries = [{'path': 'p0', 'kind': 'file'}, {'path': text(9000, 'cuối'), 'kind': 'file'}, {'path': 'p2', 'kind': 'file'}]
        real = Owned._work_tool
        def tool(self_, task_id, state, name, args, profile):
            if name == 'list': return {'directory': '', 'entries': entries, 'next_cursor': None}
            return real(self_, task_id, state, name, args, profile)
        self.commit({'docs/a.txt': 'a\n'})
        worker = CapFollower(self.ledger, [action('list', directory='')], [10600, 10600, 10600, 15000, 15000, 15000, 15000])
        with patch.object(Owned, '_work_tool', tool):
            runtime, task, worker, _ = self.run_job(self.contract(edit=True, commands=True), [], steps=0, worker=worker)
            runtime.run(task, steps=2)  # the list, then the first continuation request is the next response
            real_tool = Owned._tool
            stopped = []
            def stop(self_, task_id, state, name, args, profile):
                if name == 'receipt' and args.get('item_offset') and not stopped:
                    stopped.append(dict(args)); raise KeyboardInterrupt('runner stopped before the continuation ran')
                return real_tool(self_, task_id, state, name, args, profile)
            with patch.object(Owned, '_tool', stop):
                try: runtime.run(task, steps=3)
                except KeyboardInterrupt: pass
            self.assertTrue(stopped, 'the continuation request was reached')
            runtime = Owned(self.ledger, worker); worker.runtime = runtime
            for _ in range(40):
                state = runtime.run(task, steps=1)
                if worker.done or state['phase'] != 'running': break
        self.assertEqual(state['phase'], 'running', str(state.get('message')))
        check_exact(self, entries, self.pieces_of(worker))


# --- R1: the completion reviewer and evidence that does not fit ---------------------------------------------------------------

def next_request(ev, index):
    """The request a reviewer makes from the `next` of the page it was given for receipt `index` (None when no page has a next)."""
    for entry in ev.get('requested_pages') or []:
        if entry.get('index') != index: continue
        for page in entry.get('page') or []:
            nxt = page.get('next')
            if nxt and nxt['action'] == 'receipt':
                a = nxt['arguments']
                return {'index': a['index'], 'field': a.get('field'), 'offset': a.get('offset', 0), 'item_offset': a.get('item_offset', 0)}
    return None


def evidence_text(ev, index, field='text'):
    """What this prompt shows of receipt `index`: the whole record's field, or the page of it (None: nothing)."""
    for item in ev.get('full_receipts') or []:
        if item['index'] == index: return (item['record'].get('result') or {}).get(field)
    for entry in ev.get('requested_pages') or []:
        if entry.get('index') == index and isinstance(entry.get('result'), dict): return entry['result'].get(field)
    return None


class PageReader:
    """A STATELESS completion reviewer: it sees only the prompt, as a real one does. It wants the whole file (receipt `index`) before it
    judges, asks for the next page with the `next` it was given, writes what it verified in `feedback` (its notes come back as
    review_notes), rejects when what it read contains `marker`, accepts otherwise. If nothing arrives for what it asked, it asks again
    (what a reviewer that cannot see the evidence can do)."""
    def __init__(self, marker=None, index=0):
        self.marker, self.index = marker, index

    def __call__(self, worker, prompt, ctx):
        ev, notes = ctx['evidence'], ctx.get('review_notes') or []
        shown = evidence_text(ev, self.index)
        if shown is None:
            return {'accepted': False, 'evidence_requests': ev.get('requested') or [self.index],
                    'feedback': f'NOTE: I need receipt {self.index} (the file) to check C1..C8.'}
        flagged = bool(self.marker) and (self.marker in shown or any(self.marker in n for n in notes))
        nxt = next_request(ev, self.index)
        if nxt:
            return {'accepted': False, 'evidence_requests': [nxt],
                    'feedback': f'NOTE: read up to offset {nxt["offset"]}' + (f'; {self.marker} seen' if flagged else '') + '.'}
        if flagged:
            return {'accepted': False, 'evidence_requests': [], 'feedback': f'The file contains {self.marker}: C3 is not met.'}
        return {'accepted': True, 'evidence_requests': [], 'feedback': 'I read the whole file; C1..C8 are supported.'}


def ask_again(worker, prompt, ctx):
    return {'accepted': False, 'evidence_requests': [0], 'feedback': 'NOTE: I still need receipt 0.'}


def never_done(worker, prompt, ctx):
    """Asks for the next page again and again, never deciding (a reviewer that would read a whole repository)."""
    nxt = next_request(ctx['evidence'], 0)
    return {'accepted': False, 'evidence_requests': [nxt if nxt else 0], 'feedback': 'NOTE: more.'}


class ReviewerWorker(FlowWorker):
    """FlowWorker whose completion reviewer is `policy(worker, prompt, context)`; records every review prompt and answer.
    after_review(n) runs once the n-th review answer is given (before the next prompt is built)."""
    def __init__(self, ledger, script, policy, after_review=None):
        super().__init__(ledger, script, None)
        self.policy, self.review_log, self.after_review = policy, [], after_review

    def run(self, attempt, prompt, schema, profile):
        if not prompt.startswith('COMPLETION REVIEW'): return super().run(attempt, prompt, schema, profile)
        ctx = context(prompt); reply = self.policy(self, prompt, ctx)
        self.reviews.append((prompt, canonical(schema))); self.review_log.append((ctx, reply)); self.calls.append('owned_review')
        self.control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        self.control.finish(attempt['id'], attempt['generation'], {'fixture': reply})
        if self.after_review: self.after_review(len(self.reviews))


PATH = 'app/lib/utils/dinh_dang_tien.dart'


class ReviewRoundsBase(BudgetFixture):
    def flow(self, report='C1..C8: receipt 0 (the file), 1 (edit), 3 (test passed); branch fix/money (5).'):
        py = python()
        def edit(w):
            from onecrew import work_tools as wt
            data = (wt.ws_root(w.runtime.state(w.task)[1]) / PATH).read_bytes()
            return action('edit', path=PATH, expected_sha256=hashlib.sha256(data).hexdigest(), old='// KẾT-THÚC-TỆP', new='// KẾT-THÚC-ĐÃ-SỬA')
        check = ('import pathlib\ntext = pathlib.Path("app/lib/utils/dinh_dang_tien.dart").read_text(encoding="utf-8")\n'
                 'assert "KẾT-THÚC-ĐÃ-SỬA" in text\nprint("xong")\n')
        return [action('read', path=PATH), edit, action('write', path='kiem_tra_tien.py', expected_sha256=None, text=check),
                action('run', argv=[py, 'kiem_tra_tien.py']), action('workspace_commit', message='Sửa định dạng tiền (fixture)'),
                action('export_branch', name='fix/money'),
                action('finish', report=report, verification=[{'argv': [py, 'kiem_tra_tien.py'], 'cwd': ''}])]

    def contract_(self):
        contract = s1_contract()
        contract['checks'] = [{'kind': 'command', 'argv': [python(), '-c', 'print(1)'], 'cwd': ''}]
        return contract

    def make_job(self, worker, key='p6'):
        from onecrew.owned_intake import submit
        task = submit(self.ledger, None, key, mode='work', provider='kiro', model='claude-sonnet-5', contract=self.contract_())['id']
        runtime = Owned(self.ledger, worker); runtime.enable(task)
        worker.runtime, worker.task = runtime, task
        return task

    def review_job(self, source, policy, after_review=None, steps=240, script=None):
        """The S1-shape contract under Kiro's cap; the file is synthetic (generated), the tools, the core and the paging are real."""
        self.commit({PATH: source})
        self.addCleanup(Owned.PROMPT_LIMITS.update, dict(Owned.PROMPT_LIMITS))
        worker = ReviewerWorker(self.ledger, script or self.flow(), policy, after_review)
        runtime, task, worker, state = self.run_job(self.contract_(), [], steps=steps, worker=worker)
        for prompt, schema in worker.reviews:
            self.assertLessEqual(len(prompt) + len(schema) + 40, CAP, 'a review prompt is within the cap')
        return runtime, task, worker, state

    def receipt_text(self, runtime, task, index=0):
        state = runtime.state(task)[1]
        return json.loads(runtime.store.read_blob(state['receipts'][index]['blob']))['result']['text']

    def received(self, worker, index=0, field='text'):
        """Every page of receipt `index` the reviewer was given, in delivery order: (offset, text, page entry, requested_pages entry)."""
        out = []
        for ctx, _ in worker.review_log:
            for entry in ctx['evidence'].get('requested_pages') or []:
                if entry.get('index') != index: continue
                for page in entry.get('page') or []:
                    if page['field'] == field: out.append((page['offset'], entry['result'].get(field) or '', page, entry))
                if entry.get('complete'): out.append((0, entry['result'].get(field) or '', {'eof': True}, entry))
        return out

    def assert_put_back_together(self, worker, expected, index=0, field='text'):
        got, position = [], 0
        for offset, piece, page, entry in self.received(worker, index, field):
            self.assertEqual(offset, position, f'a page starts at {offset} after {position} characters were received (gap or repeat)')
            got.append(piece); position += len(piece)
        self.assertEqual(sha(''.join(got)), sha(expected), 'the pages put back together are the receipt, hash included')


class ReviewEvidencePagesTests(ReviewRoundsBase):
    """R1, through the real core (verification, review loop, prompt fitting, paging) with a scripted stateless reviewer."""

    def test_a_reviewer_gets_a_large_receipt_page_by_page_and_the_job_completes(self):
        source = vietnamese_source(11000, 'KẾT-THÚC-TỆP')  # synthetic Vietnamese source file, ~11,000 characters (the size Codex used)
        runtime, task, worker, state = self.review_job(source, PageReader())
        self.assertEqual(state['phase'], 'completed', 'RED-P6: ' + str(state.get('message')))
        text = self.receipt_text(runtime, task)
        self.assertGreaterEqual(len(text), 10500)
        self.assert_put_back_together(worker, text)
        pages = self.received(worker)
        self.assertGreaterEqual(len(pages), 3, 'a file this size does not fit one page under the cap')
        self.assertTrue(pages[-1][2]['eof'] and all(not p[2]['eof'] for p in pages[:-1]), 'EOF exactly at the last page')
        self.assertLessEqual(len(worker.reviews), 11, "bounded: the rounds of one review")
        self.assertEqual(worker.review_log[-1][0]['evidence']['not_included'], [])
        self.assertFalse([r for r in state['receipts'] if r['action'] == 'finish' and not r.get('successful')], 'no rejection on the way')

    def test_pages_are_bound_to_the_receipt_and_the_hash_of_the_whole_field(self):
        runtime, task, worker, state = self.review_job(vietnamese_source(11000, 'KẾT-THÚC-TỆP'), PageReader())
        self.assertEqual(state['phase'], 'completed', 'RED-P6: ' + str(state.get('message')))
        text = self.receipt_text(runtime, task)
        blob = state['receipts'][0]['blob']
        pages = self.received(worker)
        self.assertTrue(pages, 'RED-P6: no page was delivered')
        for offset, piece, page, entry in pages:
            self.assertEqual(entry['blob'], blob, 'every page names the receipt it belongs to')
            self.assertEqual(entry['field_sha256'], {'text': sha(text)}, 'and the sha256 of the whole field')
            self.assertEqual((page['total'], entry['index']), (len(text), 0))

    def test_a_reviewer_that_has_read_every_page_still_rejects_a_wrong_fix(self):
        marker = 'BUG-MARKER: formatCompactWords trả sai'
        source = vietnamese_source(10200, 'KẾT-THÚC-TỆP')
        source = source[:-len('// KẾT-THÚC-TỆP\n')] + f'// {marker}\n' + '// KẾT-THÚC-TỆP\n'  # visible only on the last pages
        runtime, task, worker, state = self.review_job(source, PageReader(marker=marker))
        self.assertEqual(state['phase'], 'running', 'a rejection goes back to the worker: ' + str(state.get('message')))
        finish = [r for r in state['receipts'] if r['action'] == 'finish']
        self.assertEqual(len(finish), 1)
        error = json.loads(runtime.store.read_blob(finish[0]['blob']))['result']['error']
        self.assertIn('Final evidence review', error)
        self.assertIn(marker, error, "RED-P6: the rejection is the reviewer's, from evidence it read")
        progress = state['progress']
        self.assertEqual(progress.get('review_rejections_v2', progress.get('review_rejections')), 1, 'counted as a rejection')
        self.assert_put_back_together(worker, self.receipt_text(runtime, task))

    def test_a_reviewer_that_asks_for_the_same_page_again_ends_in_evidence_incomplete_not_in_a_rejection(self):
        runtime, task, worker, state = self.review_job(vietnamese_source(11000, 'KẾT-THÚC-TỆP'), ask_again)
        self.assertEqual(state['phase'], 'blocked')
        self.assertEqual((state.get('recovery') or {}).get('kind'), 'review_evidence', 'RED-P6: ' + str(state.get('message')))
        self.assertTrue(state['message'].startswith('Review evidence incomplete'))
        self.assertIn('NOT judged defective', state['message']); self.assertNotIn('smaller source pages', state['message'])
        self.assertFalse([r for r in state['receipts'] if r['action'] == 'finish'], 'the finish was not rejected: no receipt, no worker feedback')
        self.assertEqual((state.get('progress') or {}).get('review_rejections_v2', 0), 0)
        self.assertEqual(len(worker.reviews), 2, 'one round for the page, one that asked again: bounded, no third call')
        self.assertNotIn('review_requests', state, 'a resume reviews afresh, not on a stale request')

    def test_the_rounds_of_one_review_are_bounded_and_end_in_evidence_incomplete(self):
        entries = [{'path': f'docs/f{i:04d}.txt', 'kind': 'file', 'note': text(110, str(i))} for i in range(150)]  # synthetic listing, ~28 KB (more than 10 reviewer pages)
        real = Owned._work_tool
        def tool(self_, task_id, state, name, args, profile):
            if name == 'list': return {'directory': '', 'entries': entries, 'next_cursor': None}
            return real(self_, task_id, state, name, args, profile)
        script = [action('list', directory=''), action('write', path='new_file.txt', expected_sha256=None, text='// stub\n'),
                  action('finish', report='Xong; receipt 0.', verification=[{'argv': [python(), '-c', 'print(1)'], 'cwd': ''}])]
        self.commit({'docs/a.txt': 'a\n'})
        worker = ReviewerWorker(self.ledger, script, never_done)
        with patch.object(Owned, '_work_tool', tool):
            runtime, task, worker, state = self.run_job(self.contract_(), [], steps=240, worker=worker)
        self.assertEqual(state['phase'], 'blocked')
        self.assertEqual((state.get('recovery') or {}).get('kind'), 'review_evidence', 'RED-P6: ' + str(state.get('message')))
        self.assertIn('evidence rounds of one review were used', state['message'])
        self.assertEqual(len(worker.reviews), 11, "the first look plus MAX_ROUNDS pages: an explicit bound")
        offsets = [p[0] for p in self.received(worker, 0, 'entries')]
        self.assertEqual(offsets, sorted(set(offsets)), 'every page is new: none repeated')

    def test_a_runner_restart_between_pages_keeps_the_position_and_the_counters(self):
        self.commit({PATH: vietnamese_source(11000, 'KẾT-THÚC-TỆP')})
        worker = ReviewerWorker(self.ledger, self.flow(), PageReader())
        task = self.make_job(worker)
        runtime = worker.runtime
        real = Owned._work_review_prompt
        builds = []
        def dying(self_, task_id, state, profile, value):
            builds.append(state.get('review_evidence_rounds', 0))
            if len(builds) == 3 and not getattr(dying, 'died', False):
                dying.died = True
                raise KeyboardInterrupt('runner stopped while the third review prompt was being built')
            return real(self_, task_id, state, profile, value)
        died, state = False, None
        with patch.object(Owned, '_work_review_prompt', dying):
            for _ in range(240):
                try: state = runtime.run(task, steps=1)
                except KeyboardInterrupt:
                    died = True
                    checkpoint = runtime.state(task)[1]
                    self.assertEqual(checkpoint.get('review_evidence_rounds'), 2, 'RED-P6: the counter is in the checkpoint')
                    self.assertEqual(len(checkpoint.get('review_seen') or []), 2); self.assertTrue(checkpoint.get('review_notes'))
                    runtime = Owned(self.ledger, worker); worker.runtime = runtime  # a new runner from the durable checkpoint
                    continue
                if state['phase'] != 'running': break
        self.assertTrue(died, 'the runner was stopped')
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assert_put_back_together(worker, self.receipt_text(runtime, task))
        self.assertEqual(runtime.control.status(task)['used_calls'], len(worker.calls), 'no call lost or repeated')

    def test_the_cap_changing_between_review_rounds_loses_and_repeats_nothing(self):
        caps = [15000, 14800, 15000, 14700, 15000, 14900, 15000, 14750, 15000, 15000]  # all >= the least cap that still holds a valid page
        # (F2/F3 of the P6 probe: the review schema now carries findings and resolved, and a prompt that carries a page the findings
        # rule: 14,500 gave a largest page of 985 of the 1,000 characters a valid page needs, so the lowest cap of the list is 14,700)
        def after(n):
            if caps: Owned.PROMPT_LIMITS['kiro'] = caps.pop(0)
        runtime, task, worker, state = self.review_job(vietnamese_source(11000, 'KẾT-THÚC-TỆP'), PageReader(), after_review=after)
        self.assertEqual(state['phase'], 'completed', 'RED-P6: ' + str(state.get('message')))
        self.assert_put_back_together(worker, self.receipt_text(runtime, task))
        sizes = [len(p[1]) for p in self.received(worker)]
        self.assertGreater(len(set(sizes[:-1])), 1, 'the room changed between the pages: ' + str(sizes))

    def test_a_request_no_valid_page_can_serve_blocks_before_the_call_naming_the_parts(self):
        def after(n):
            Owned.PROMPT_LIMITS['kiro'] = 9000  # the room of the next review round shrinks below its fixed part
        runtime, task, worker, state = self.review_job(vietnamese_source(11000, 'KẾT-THÚC-TỆP'), PageReader(), after_review=after)
        self.assertEqual(state['phase'], 'blocked')
        self.assertEqual((state.get('recovery') or {}).get('kind'), 'prompt_budget', 'RED-P6: ' + str(state.get('message')))
        self.assertIn('cannot be given the evidence it asked for', state['message'])
        self.assertRegex(state['message'], r'work_contract \d+')
        self.assertEqual(len(worker.reviews), 1, 'the second review was refused before any call')
        self.assertFalse([r for r in state['receipts'] if r['action'] == 'finish'])

    def test_even_a_small_receipt_requested_by_index_reaches_the_reviewer_under_the_s1_shape_cap(self):
        # 1,500 characters: on d83b834 it did not fit the evidence left by the S1-shape review prompt either (a repro, not a control)
        runtime, task, worker, state = self.review_job(vietnamese_source(1500, 'KẾT-THÚC-TỆP'), PageReader())
        self.assertEqual(state['phase'], 'completed', 'RED-P6: ' + str(state.get('message')))
        self.assertEqual(evidence_text(worker.review_log[-1][0]['evidence'], 0), self.receipt_text(runtime, task))

    # --- controls: green with or without the fix ----------------------------------------------------------------------------

    def test_control_a_reviewer_that_needs_nothing_accepts_in_one_call(self):
        runtime, task, worker, state = self.review_job(vietnamese_source(1500, 'KẾT-THÚC-TỆP'), lambda w, p, c: dict(ACCEPT))
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assertEqual(len(worker.reviews), 1)


DEFECT = 'số tiền âm bị bỏ qua khi làm tròn (C3 không đạt)'  # a synthetic defect statement


def source_with(defect, at, size=11000):
    """The synthetic file with a line that states `defect` inserted at about character `at` (on a line boundary)."""
    source = vietnamese_source(size, 'KẾT-THÚC-TỆP')
    cut = source.index('\n', at) + 1
    return source[:cut] + f'  // LỖI: {defect}\n' + source[cut:]


def finding_ids(ctx):
    """The ids of the open findings a review prompt carries (entries are {id, claim,...}; ids alone when the room was smallest)."""
    return [e['id'] if isinstance(e, dict) else e for e in ctx.get('open_findings') or []]


class FindingReader(PageReader):
    """A STATELESS completion reviewer that reads receipt `index` page by page and REPORTS what it sees: when a page shows `defect` it
    writes it in findings ("r0: ...") - and, as a reviewer that has not yet decided would, in its note - and goes on reading. At the end
    of the file (no next page):
      forgets         accepts, ignoring open_findings (a reviewer that lost track of what it saw);
      rejects         answers accepted=false with no request;
      closes          closes every id of open_findings citing receipt `cite`, then accepts;
      after_reconcile accepts without closing, and closes them (citing `cite`) only when its prompt carries review_reconcile.
    `note` is the length of the note it writes every round (a chatty reviewer)."""
    def __init__(self, defect=DEFECT, ending='forgets', cite=0, how='the end of the file defines it, receipt 0', note=0, index=0,
                 malformed=False):
        super().__init__(None, index)
        self.defect, self.ending, self.cite, self.how, self.note, self.malformed = defect, ending, cite, how, note, malformed

    def __call__(self, worker, prompt, ctx):
        ev = ctx['evidence']
        shown = evidence_text(ev, self.index)
        if shown is None:
            return {'accepted': False, 'evidence_requests': ev.get('requested') or [self.index], 'findings': [], 'resolved': [],
                    'feedback': f'NOTE: I need receipt {self.index} (the file) to check C1..C8.'}
        findings = [f'r{self.index}: {self.defect}'] if self.defect in shown else []
        feedback = (f'NOTE: this page shows {self.defect}; C3 fails. ' if findings else 'NOTE: page read, nothing wrong. ')
        feedback += ('lý giải thêm ' * 80)[:self.note] if self.note else ''
        nxt = next_request(ev, self.index)
        if nxt:
            return {'accepted': False, 'evidence_requests': [nxt], 'feedback': feedback, 'findings': findings, 'resolved': []}
        closing = self.ending == 'closes' or (self.ending == 'after_reconcile' and ctx.get('review_reconcile'))
        resolved = []
        if closing:
            for ident in finding_ids(ctx):
                resolved.append(f'{ident}:{self.cite}:{self.how}' if not self.malformed else f'{ident} is fine')
        if self.ending == 'rejects':
            return {'accepted': False, 'evidence_requests': [], 'feedback': f'C3 is not met: {self.defect}', 'findings': findings, 'resolved': []}
        return {'accepted': True, 'evidence_requests': [], 'feedback': 'I read the whole file; C1..C8 are supported.',
                'findings': findings, 'resolved': resolved}


class ReviewFindingsTests(ReviewRoundsBase):
    """F2 and F3 of the P6 probe: what the reviewer notices across the rounds of one review. The reviewer is stateless; the notes it
    wrote used to come back as the last three, at up to 700 characters each, so (F3) a defect noticed on one page was gone from the
    prompt a few rounds later and the review accepted, and (F2) three long notes left no room for a valid page and a normal review
    was blocked. Now the core keeps every finding whole in the checkpoint (id, where the reviewer was looking, status), the prompt
    carries a bounded rendering of them, and the core - not the model - refuses to accept while one is open and closes one only on
    evidence the reviewer was given. Synthetic file and reviewer; the core, paging and prompt fitting are the product's."""

    def rejection_error(self, runtime, state):
        finish = [r for r in state['receipts'] if r['action'] == 'finish']
        self.assertTrue(finish, 'RED-P6: no finish was rejected; phase ' + state['phase'] + ': ' + str(state.get('message')))
        return json.loads(runtime.store.read_blob(finish[-1]['blob']))['result'].get('error') or ''

    def assert_defect_carried_to_a_rejection(self, source, reader=None, label=''):
        runtime, task, worker, state = self.review_job(source, reader or FindingReader(ending='forgets'))
        self.assertEqual(state['phase'], 'running', f'RED-P6: {label} the review accepted over a defect it had seen ({state.get("message")})')
        error = self.rejection_error(runtime, state)
        self.assertIn('Final evidence review', error)
        self.assertIn('RF1', error); self.assertIn(DEFECT, error, 'the worker is told the defect itself, not a count')
        record = state['reviews'][-1]
        self.assertFalse(record['accepted'])
        found = record['findings']
        self.assertEqual([(f['id'], f['status']) for f in found], [('RF1', 'open')])
        self.assertIn(DEFECT, found[0]['claim']); self.assertEqual(found[0]['chars'], len(found[0]['claim']))
        self.assertTrue(found[0]['source']['pages'], 'the evidence it was looking at is recorded with it')
        rounds_with = [n for n, (ctx, _) in enumerate(worker.review_log) if 'RF1' in finding_ids(ctx)]
        first_seen = next(n for n, (ctx, reply) in enumerate(worker.review_log) if reply['findings']) + 1
        self.assertEqual(rounds_with, list(range(first_seen, len(worker.review_log))),
                         'every prompt after the page that showed it carries the finding, however many rounds have passed')
        self.assertTrue(worker.review_log[-1][0].get('review_reconcile'), 'the reviewer was asked once to close it or reject')
        return runtime, task, worker, state

    def test_a_defect_on_the_first_page_is_not_accepted_over_when_the_reviewer_forgets_it(self):
        self.assert_defect_carried_to_a_rejection(source_with(DEFECT, 300, 8000), label='first page:')

    def test_a_defect_on_a_middle_page_is_not_accepted_over_when_the_reviewer_forgets_it(self):
        _, _, worker, _ = self.assert_defect_carried_to_a_rejection(source_with(DEFECT, 5200, 11000), label='middle page:')
        self.assertGreaterEqual(len(worker.review_log), 8, 'many rounds passed after the defect was seen')

    def test_a_finding_survives_a_runner_restart_between_rounds_and_is_still_open(self):
        self.commit({PATH: source_with(DEFECT, 300, 8000)})
        worker = ReviewerWorker(self.ledger, self.flow(), FindingReader(ending='forgets'))
        task = self.make_job(worker)
        runtime = worker.runtime
        real = Owned._work_review_prompt
        died = []
        def dying(self_, task_id, state, profile, value, *a, **k):
            if not died and state.get('review_evidence_rounds', 0) >= 4 and state.get('review_findings'):
                died.append(canonical(state['review_findings']))
                raise KeyboardInterrupt('runner stopped while a later review prompt was being built')
            return real(self_, task_id, state, profile, value, *a, **k)
        state = None
        with patch.object(Owned, '_work_review_prompt', dying):
            for _ in range(240):
                try: state = runtime.run(task, steps=1)
                except KeyboardInterrupt:
                    held = runtime.state(task)[1].get('review_findings')
                    self.assertEqual(canonical(held), died[0], 'RED-P6: the checkpoint holds the findings as they were')
                    self.assertEqual([(f['id'], f['status']) for f in held], [('RF1', 'open')])
                    runtime = Owned(self.ledger, worker); worker.runtime = runtime  # a new runner from the durable checkpoint
                    continue
                if worker.done or state['phase'] != 'running': break
        self.assertTrue(died, 'RED-P6: no finding was in the checkpoint when the runner stopped')
        self.assertEqual(state['phase'], 'running', 'not accepted: ' + str(state.get('message')))
        self.assertIn(DEFECT, self.rejection_error(runtime, state))
        self.assertEqual(runtime.control.status(task)['used_calls'], len(worker.calls), 'no call lost or repeated')

    def test_findings_of_a_review_that_ended_without_a_verdict_are_open_in_the_next_review_of_the_same_work(self):
        self.commit({PATH: source_with(DEFECT, 300, 8000)})

        def records_then_asks_again(worker_, prompt, ctx):  # sees a page, records the defect, asks for the same page again: no verdict
            if evidence_text(ctx['evidence'], 0) is None:
                return {'accepted': False, 'evidence_requests': [0], 'feedback': 'NOTE: need the file', 'findings': [], 'resolved': []}
            return {'accepted': False, 'evidence_requests': [0], 'feedback': 'NOTE: again', 'findings': [f'r0: {DEFECT}'], 'resolved': []}
        worker = ReviewerWorker(self.ledger, self.flow(), records_then_asks_again)
        task = self.make_job(worker)
        runtime = worker.runtime
        for _ in range(60):
            state = runtime.run(task, steps=1)
            if state['phase'] != 'running': break
        self.assertEqual((state['phase'], (state.get('recovery') or {}).get('kind')), ('blocked', 'review_evidence'), str(state.get('message')))
        self.assertIn('RF1', state['message']); self.assertIn('stay open', state['message'])
        self.assertEqual([(f['id'], f['status']) for f in state.get('review_findings') or []], [('RF1', 'open')],
                         'RED-P6: a review that was not decided keeps what its reviewer reported')
        self.assertFalse(state.get('review_notes') or state.get('review_seen') or state.get('review_requests'), 'the rest of its memory is dropped')
        before = len(worker.review_log)
        worker.policy = FindingReader(ending='closes', cite=0)  # an operator resumes; the next reviewer is able to close what was recorded
        runtime.resume(task)
        for _ in range(240):
            state = runtime.run(task, steps=1)
            if worker.done or state['phase'] != 'running': break
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        first = worker.review_log[before][0]
        self.assertEqual(finding_ids(first), ['RF1'], 'the first prompt of the next review already carries the open finding')
        self.assertEqual([(f['id'], f['status']) for f in state['reviews'][-1]['findings']], [('RF1', 'resolved')])
        self.assertNotIn('review_findings', state, 'decided: the memory goes with the review')

    def test_a_finding_is_closed_by_evidence_the_reviewer_was_given_and_the_work_is_then_accepted(self):
        runtime, task, worker, state = self.review_job(source_with(DEFECT, 300, 8000), FindingReader(ending='closes', cite=0))
        self.assertEqual(state['phase'], 'completed', 'RED-P6: ' + str(state.get('message')))
        record = state['reviews'][-1]
        self.assertTrue(record['accepted'])
        found = record['findings']
        self.assertEqual([(f['id'], f['status']) for f in found], [('RF1', 'resolved')])
        self.assertEqual(found[0]['resolution']['receipt'], 0)
        self.assertIn('end of the file', found[0]['resolution']['how'])
        self.assertIn(DEFECT, found[0]['claim'], 'the finding is kept whole after it is closed')

    def test_a_closure_that_cites_a_receipt_the_reviewer_was_never_given_is_refused_and_the_finding_stays_open(self):
        runtime, task, worker, state = self.review_job(source_with(DEFECT, 300, 8000), FindingReader(ending='closes', cite=1))
        shown = set()  # read from the prompts the reviewer was sent, not from the code under test
        for ctx, _ in worker.review_log:
            shown |= {r['index'] for r in ctx['evidence'].get('full_receipts') or []}
            shown |= {e['index'] for e in ctx['evidence'].get('requested_pages') or []}
        self.assertNotIn(1, shown, 'the premise: receipt 1 (the edit) was never in a review prompt')
        self.assertEqual(state['phase'], 'running', f'RED-P6: closed with evidence nobody gave the reviewer ({state.get("message")})')
        found = state['reviews'][-1]['findings']
        self.assertEqual([(f['id'], f['status']) for f in found], [('RF1', 'open')])
        self.assertIn('receipt 1 was not shown', found[0]['closure_refused'])
        self.assertTrue(any(isinstance(e, dict) and e.get('closure_refused') for e in worker.review_log[-1][0].get('open_findings') or []),
                        'the next prompt tells the reviewer why it stays open')

    def test_a_closure_that_is_not_in_the_form_asked_closes_nothing(self):
        runtime, task, worker, state = self.review_job(source_with(DEFECT, 300, 8000), FindingReader(ending='closes', malformed=True))
        self.assertEqual(state['phase'], 'running', f'RED-P6: ({state.get("message")})')
        self.assertEqual([f['status'] for f in state['reviews'][-1]['findings']], ['open'])

    def test_a_reviewer_that_closes_only_when_asked_again_is_asked_once_and_the_work_is_then_accepted(self):
        runtime, task, worker, state = self.review_job(source_with(DEFECT, 300, 8000), FindingReader(ending='after_reconcile'))
        self.assertEqual(state['phase'], 'completed', 'RED-P6: ' + str(state.get('message')))
        self.assertEqual([f['status'] for f in state['reviews'][-1]['findings']], ['resolved'])
        self.assertEqual(sum(1 for ctx, _ in worker.review_log if ctx.get('review_reconcile')), 1, 'asked exactly once')

    def test_when_the_prompt_for_asking_again_does_not_fit_the_review_is_decided_and_not_blocked(self):
        # the gate must never wedge a job: asking the reviewer once more is best effort; without room the review is a rejection
        real = Owned._work_review_prompt
        def refuse_reconcile(self_, task_id, state, profile, value):
            if state.get('review_reconcile'): raise PromptBudgetError('Prompt budget: (test) the prompt for asking again does not fit')
            return real(self_, task_id, state, profile, value)
        with patch.object(Owned, '_work_review_prompt', refuse_reconcile):
            runtime, task, worker, state = self.review_job(source_with(DEFECT, 300, 8000), FindingReader(ending='forgets'))
        self.assertEqual(state['phase'], 'running', 'RED-P6: a rejection goes back to the worker, the job is not blocked or completed: ' + str(state.get('message')))
        error = self.rejection_error(runtime, state)
        self.assertIn('RF1', error); self.assertIn(DEFECT, error)
        self.assertFalse(any(ctx.get('review_reconcile') for ctx, _ in worker.review_log), 'it was not asked: it could not be')

    def test_a_reviewer_that_rejects_with_an_open_finding_sends_the_finding_to_the_worker_whole(self):
        runtime, task, worker, state = self.review_job(source_with(DEFECT, 300, 8000), FindingReader(ending='rejects'))
        self.assertEqual(state['phase'], 'running')
        error = self.rejection_error(runtime, state)
        self.assertIn('RF1', error); self.assertIn(DEFECT, error)
        self.assertEqual((state.get('progress') or {}).get('review_rejections_v2'), 1)

    def test_long_notes_every_round_neither_starve_the_page_nor_are_lost(self):
        # F2: 700-character notes, 8 rounds. At d83b834+P6 the third prompt had no valid page left and the review was blocked.
        kept = []
        def watch(n):
            for note in runtime_box[0].state(task_box[0])[1].get('review_notes') or []:
                if isinstance(note, dict): kept.append((note['id'], note['chars'], len(note['text'])))
        runtime_box, task_box = [None], [None]
        self.commit({PATH: vietnamese_source(11000, 'KẾT-THÚC-TỆP')})
        worker = ReviewerWorker(self.ledger, self.flow(), FindingReader(defect='không có lỗi nào như vậy', note=700), after_review=watch)
        task = self.make_job(worker); task_box[0], runtime_box[0] = task, worker.runtime
        self.addCleanup(Owned.PROMPT_LIMITS.update, dict(Owned.PROMPT_LIMITS))
        state = None
        for _ in range(240):
            state = worker.runtime.run(task, steps=1)
            if worker.done or state['phase'] != 'running': break
        self.assertEqual(state['phase'], 'completed', 'RED-P6: ' + str(state.get('message')))
        from onecrew.review_evidence import MEMORY_TIERS
        for ctx, _ in worker.review_log:
            memory = len(canonical({k: ctx[k] for k in ('open_findings', 'review_notes', 'findings_closed') if k in ctx}))
            self.assertLessEqual(memory, MEMORY_TIERS[0] + 40, 'the review memory in a prompt is bounded')
        self.assertTrue(kept, 'RED-P6: no note was kept in the checkpoint')
        self.assertTrue(all(chars == length or length == 2000 for _, chars, length in kept), 'notes are kept whole: ' + str(kept[:3]))
        self.assertGreaterEqual(max(length for _, _, length in kept), 700)

    def test_notes_that_do_not_fit_the_prompt_are_named_not_dropped_without_a_word(self):
        runtime, task, worker, state = self.review_job(vietnamese_source(11000, 'KẾT-THÚC-TỆP'),
                                                       FindingReader(defect='không có lỗi nào như vậy', note=700))
        self.assertEqual(state['phase'], 'completed', 'RED-P6: ' + str(state.get('message')))
        elided = [n for ctx, _ in worker.review_log for n in ctx.get('review_notes') or [] if 'kept in the review state' in n]
        self.assertTrue(elided, 'RED-P6: eight 700-character notes cannot all be in the prompt; what is not there is said to be kept')

    def test_control_a_review_with_nothing_to_report_is_as_before(self):
        runtime, task, worker, state = self.review_job(vietnamese_source(11000, 'KẾT-THÚC-TỆP'), FindingReader(defect='không có lỗi nào như vậy'))
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))
        self.assertTrue(all('open_findings' not in ctx for ctx, _ in worker.review_log))
        self.assertEqual(len(worker.review_log[-1][0]['evidence'].get('requested_pages') or []) > 0, True)


class ReviewMemoryTests(unittest.TestCase):
    """review_evidence.record_round / memory / findings_text: the functions the review loop uses, on a plain checkpoint dict."""

    def state(self):
        return {'review_requests': [{'index': 0, 'field': 'text', 'offset': 1700, 'item_offset': 0}]}

    def test_a_finding_keeps_its_whole_claim_its_source_and_a_stable_id(self):
        from onecrew.review_evidence import record_round, KEPT
        state, long_claim = self.state(), ' '.join(['lỗi'] * 700)  # 2,799 characters
        claim = 'r0: ' + long_claim
        result = record_round(state, {'findings': [claim, 'một lỗi khác']}, shown={0}, round_no=2)
        self.assertEqual(result['opened'], ['RF1', 'RF2'])
        first = state['review_findings'][0]
        self.assertEqual((first['id'], first['status'], first['round'], first['source']['receipt']), ('RF1', 'open', 2, 0))
        self.assertEqual(first['source']['pages'], state['review_requests'])
        self.assertEqual(first['chars'], len(long_claim)); self.assertEqual(len(first['claim']), KEPT)
        self.assertEqual(first['claim'], long_claim[:KEPT])
        record_round(state, {'findings': ['một lỗi mới']}, shown={0}, round_no=3)
        self.assertEqual([f['id'] for f in state['review_findings']], ['RF1', 'RF2', 'RF3'], 'ids only go forward')

    def test_the_same_defect_reported_again_is_one_finding(self):
        from onecrew.review_evidence import record_round
        state = self.state()
        record_round(state, {'findings': ['Số tiền  âm bị bỏ qua']}, shown={0}, round_no=1)
        record_round(state, {'findings': ['số tiền âm bị bỏ qua', 'r0: số tiền âm bị bỏ qua']}, shown={0}, round_no=2)
        self.assertEqual(len(state['review_findings']), 1)

    def test_what_the_reviewer_reports_is_never_dropped_for_its_shape(self):
        from onecrew.review_evidence import record_round
        state = self.state()
        record_round(state, {'findings': {'claim': 'x'}}, shown=set(), round_no=1)
        record_round(state, {'findings': ['', '   ', {'claim': 'y', 'receipt': 0}, 7]}, shown=set(), round_no=2)
        self.assertEqual(len(state['review_findings']), 3, 'an object or a number is kept as the text of itself; empty strings are nothing')

    def test_a_review_holds_a_bounded_number_of_findings_and_counts_the_rest(self):
        from onecrew.review_evidence import record_round, MAX_FINDINGS, findings_text
        state = self.state()
        record_round(state, {'findings': [f'lỗi số {n}' for n in range(MAX_FINDINGS + 5)]}, shown=set(), round_no=1)
        self.assertEqual(len(state['review_findings']), MAX_FINDINGS)
        self.assertEqual(state['review_findings_unrecorded'], 5)
        self.assertIn('5 more finding(s)', findings_text(state))

    def test_closing_needs_an_open_finding_a_receipt_shown_in_this_review_and_a_reason(self):
        from onecrew.review_evidence import record_round
        state = self.state()
        record_round(state, {'findings': ['lỗi một', 'lỗi hai', 'lỗi ba']}, shown={0}, round_no=1)
        tries = {'resolved': ['RF1:0:the page refutes it', 'RF2:5:nothing shows it', 'RF9:0:no such finding', 'RF3:0:', 'closes everything']}
        result = record_round(state, tries, shown={0}, round_no=2)
        self.assertEqual(result['closed'], ['RF1'])
        self.assertEqual({f['id']: f['status'] for f in state['review_findings']}, {'RF1': 'resolved', 'RF2': 'open', 'RF3': 'open'})
        self.assertEqual(len(result['refused']), 4)
        self.assertEqual(state['review_findings'][0]['resolution'], {'round': 2, 'receipt': 0, 'how': 'the page refutes it', 'chars': 19})
        again = record_round(state, {'resolved': ['RF1:0:again']}, shown={0}, round_no=3)
        self.assertEqual(again['closed'], [], 'a closed finding is not closed twice')

    def test_the_memory_is_within_its_budget_and_never_loses_an_open_finding(self):
        from onecrew.review_evidence import record_round, keep_note, memory, MEMORY_TIERS
        for count, size, notes, note_size in ((0, 0, 0, 0), (1, 90, 3, 80), (3, 400, 6, 700), (12, 2000, 10, 700), (12, 20, 0, 0)):
            state = self.state()
            record_round(state, {'findings': [f'lỗi {n} ' + 'x' * size for n in range(count)]}, shown=set(), round_no=1)
            for n in range(notes): keep_note(state, f'ghi chú {n} ' + 'y' * note_size, n)
            for budget in MEMORY_TIERS:
                with self.subTest(count=count, size=size, notes=notes, budget=budget):
                    shown, lines, closed = memory(state, budget)
                    out = len(canonical({'open_findings': shown, 'review_notes': lines}))
                    self.assertLessEqual(out, budget)
                    ids = [e['id'] if isinstance(e, dict) else e for e in shown]
                    self.assertEqual(ids, [f'RF{n + 1}' for n in range(count)], 'every open finding, in order')
                    self.assertEqual((shown, lines, closed), memory(state, budget), 'deterministic')
                    if notes and lines:
                        self.assertTrue(any('kept in the review state' in line for line in lines) or len(lines) == notes,
                                        'a note that is not shown whole is said to be kept')

    def test_findings_text_puts_every_open_finding_in_front_of_the_reviewers_feedback(self):
        from onecrew.review_evidence import record_round, with_findings
        state = self.state()
        record_round(state, {'findings': ['r0: lỗi một', 'lỗi hai']}, shown={0}, round_no=1)
        text = with_findings(state, 'feedback of the reviewer')
        self.assertTrue(text.startswith('2 finding(s) recorded in this review'))
        self.assertIn('RF1 (round 1, receipt 0): lỗi một', text); self.assertIn('RF2 (round 1): lỗi hai', text)
        self.assertTrue(text.endswith('feedback of the reviewer'))

    def test_the_review_schema_stays_small(self):
        # it is subtracted from the room of every review prompt under a cap (S1 shape: ~900 characters of slack in all)
        from onecrew.owned import REVIEW_SCHEMA
        self.assertLessEqual(len(canonical(REVIEW_SCHEMA)), 640)
        self.assertTrue({'findings', 'resolved'} <= set(REVIEW_SCHEMA['required']))


class ReviewRoomProofTests(ReviewRoundsBase):
    """F1 of the P6 probe: a finish whose report fits the prompt of the FIRST look but leaves no room for the page the reviewer will
    ask for used to be refused only after the reviewer was called (a wasted call, a rejection counted against the worker). Now the
    first prompt of a review is sent only when the largest receipt the reviewer could ask for still gets a valid page, and the refusal
    says how long the report may be."""
    LONG = 'C1..C8: receipt 0 (the file), 1 (edit), 3 (test passed); branch fix/money (5). ' + 'bằng chứng nằm trong các receipt; ' * 80

    def flow_with(self, first_report, second):
        script = self.flow(report=first_report)
        script.append(second)
        return script

    def refinish(self, w):
        import re
        state = w.runtime.state(w.task)[1]
        error = json.loads(w.runtime.store.read_blob(state['receipts'][-1]['blob']))['result'].get('error') or ''
        found = re.search(r'at most (\d+) characters', error)
        if not found: raise AssertionError('RED-P6: the refusal does not say how long the report may be: ' + error[:200])
        self.limit = int(found.group(1))
        return action('finish', report=self.LONG[:self.limit], verification=[{'argv': [python(), 'kiem_tra_tien.py'], 'cwd': ''}])

    def test_a_report_that_leaves_no_room_for_a_page_is_refused_before_any_reviewer_call(self):
        runtime, task, worker, state = self.review_job(vietnamese_source(11000, 'KẾT-THÚC-TỆP'), PageReader(),
                                                       script=self.flow(report=self.LONG[:1900]), steps=80)
        self.assertEqual(len(worker.reviews), 0, 'RED-P6: the reviewer was called before the finish was found not to fit a page')
        self.assertEqual(state['phase'], 'running')
        error = json.loads(runtime.store.read_blob([r for r in state['receipts'] if r['action'] == 'finish'][-1]['blob']))['result']['error']
        self.assertIn('cannot carry this finish', error); self.assertRegex(error, r'at most \d+ characters')

    def test_the_length_the_refusal_names_is_one_the_review_then_completes_with(self):
        self.limit = None
        script = self.flow_with(self.LONG[:1900], self.refinish)
        # 8,000 characters: at the longest report the pages are the smallest valid ones, and the review's round bound (MAX_ROUNDS) is
        # a separate, explicit outcome (evidence incomplete) for a file it cannot read in that many pages
        runtime, task, worker, state = self.review_job(vietnamese_source(8000, 'KẾT-THÚC-TỆP'), PageReader(), script=script, steps=120)
        self.assertEqual(state['phase'], 'completed', f'RED-P6: report of {self.limit} characters: ' + str(state.get('message')))
        self.assertGreater(self.limit, 100)
        self.assertEqual(sum(1 for r in state['receipts'] if r['action'] == 'finish'), 2, 'one refusal, then the accepted finish')
        self.assertTrue(worker.review_log[-1][1]['accepted'])

    def test_the_review_that_was_proven_to_have_room_never_starves_a_page_later(self):
        # the report at its longest, a reviewer that records findings and writes 700-character notes in every round: no round of the
        # review is blocked for the room the core itself used (the memory yields to the page, ids and counts never do)
        self.limit = None
        script = self.flow_with(self.LONG[:1900], self.refinish)
        runtime, task, worker, state = self.review_job(source_with(DEFECT, 300, 8000),
                                                       FindingReader(ending='closes', cite=0, note=700), script=script, steps=160)
        self.assertEqual(state['phase'], 'completed', f'RED-P6: report of {self.limit}: ' + str(state.get('message')))
        self.assertNotEqual((state.get('recovery') or {}).get('kind'), 'prompt_budget')

    def test_control_a_short_report_is_reviewed_without_a_refusal(self):
        runtime, task, worker, state = self.review_job(vietnamese_source(11000, 'KẾT-THÚC-TỆP'), PageReader())
        self.assertEqual(state['phase'], 'completed', str(state.get('message')))


class ReviewPacketTests(unittest.TestCase):
    """review_evidence.requests / packet on synthetic receipts, called as the core calls them. A receipt larger than the packet
    (MAX_CONTENT) used to be 'not_included' for ever; it now comes page by page."""

    def setUp(self):
        from tests import test_owned as fixtures
        self.f = fixtures.OwnedTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.run_, task, worker = self.f.runtime([])
        self.state = self.run_.state(task)[1]
        self.big = vietnamese_source(52000, 'KẾT-THÚC-TỆP')  # synthetic, larger than the whole review packet
        self.add({'action': 'read', 'arguments': {'path': 'big.txt'}, 'result': {'path': 'big.txt', 'cursor': 0, 'text': self.big,
                                                                                  'next_cursor': None, 'sha256': sha(self.big)}})

    def add(self, record):
        blob = self.run_.store.blob(canonical(record).encode())
        self.state['receipts'].append({'index': len(self.state['receipts']), 'action': record['action'], 'blob': blob})

    def ask(self, *items):
        from onecrew.review_evidence import requests
        try: wanted = requests({'accepted': False, 'evidence_requests': list(items)}, self.state)
        except LedgerError as error: self.fail(f'RED-P6: a request {items} is refused: {error}')
        self.state['review_requests'] = wanted
        from onecrew.review_evidence import packet
        return packet(self.run_, self.state)

    def test_a_requested_receipt_larger_than_the_packet_comes_page_by_page_bound_to_its_blob_and_hash(self):
        blob, got, request, hops = self.state['receipts'][0]['blob'], [], 0, 0
        while request is not None:
            hops += 1; self.assertLess(hops, 20)
            bundle = self.ask(request)
            self.assertEqual(bundle['not_included'], [], 'RED-P6: nothing came for the request')
            entry = (bundle.get('requested_pages') or [None])[0]
            self.assertIsNotNone(entry, 'RED-P6: no page for the receipt that does not fit')
            self.assertEqual((entry['index'], entry['blob']), (0, blob)); self.assertEqual(entry['field_sha256'], {'text': sha(self.big)})
            page = entry['page'][0]
            self.assertEqual(page['offset'], sum(len(x) for x in got), 'the page starts where the previous one ended')
            got.append(entry['result']['text'])
            nxt = page.get('next')
            request = None if page['eof'] else {'index': 0, 'field': 'text', 'offset': nxt['arguments']['offset'], 'item_offset': 0}
        self.assertEqual(sha(''.join(got)), sha(self.big)); self.assertGreaterEqual(hops, 4)

    def test_a_cursor_less_request_for_a_receipt_that_fits_is_still_whole(self):
        self.add({'action': 'read', 'arguments': {'path': 's.txt'}, 'result': {'path': 's.txt', 'cursor': 0, 'text': 'nhỏ\n' * 40, 'next_cursor': None}})
        bundle = self.ask(1)
        self.assertEqual([x['index'] for x in bundle['full_receipts']][:1], [1]); self.assertFalse(bundle.get('requested_pages'))

    def test_requests_accept_page_arguments_and_refuse_wrong_ones(self):
        from onecrew.review_evidence import requests
        ok = {'accepted': False}
        def accepted(*items):
            try: return requests(dict(ok, evidence_requests=list(items)), self.state)
            except LedgerError as error: self.fail(f'RED-P6: a request {items} is refused: {error}')
        self.assertEqual(accepted(0, {'index': 0, 'field': None, 'offset': 0, 'item_offset': 0}), [0],
                         'an index and the same request spelled with all four keys are one request')
        self.assertEqual(accepted({'index': 0, 'field': 'text', 'offset': 3000, 'item_offset': 0}),
                         [{'index': 0, 'field': 'text', 'offset': 3000, 'item_offset': 0}])
        for wrong in ([{'index': 9, 'field': 'text', 'offset': 0, 'item_offset': 0}], [{'index': 0, 'field': 'text', 'offset': -1, 'item_offset': 0}],
                      [{'index': 0, 'field': None, 'offset': 5, 'item_offset': 0}], [{'index': 0, 'field': 'text', 'extra': 1}],
                      [{'index': True, 'field': 'text'}], [{'index': 0, 'field': 5}], ['0'], [0, 0, 0, 0, 0], [{'field': 'text'}]):
            with self.subTest(wrong=wrong), self.assertRaises(LedgerError): requests(dict(ok, evidence_requests=wrong), self.state)
        with self.assertRaises(LedgerError): requests({'accepted': True, 'evidence_requests': [0]}, self.state)

    def test_a_request_for_a_field_the_receipt_does_not_have_is_answered_with_an_error_not_starved(self):
        bundle = self.ask({'index': 0, 'field': 'nope', 'offset': 0, 'item_offset': 0})
        entry = (bundle.get('requested_pages') or [None])[0]
        self.assertIsNotNone(entry, 'RED-P6: no answer to a wrong request')
        self.assertIn('nope', entry['error']); self.assertEqual(bundle['not_included'], [])

    def test_a_lookup_of_a_receipt_is_paged_as_the_original(self):
        self.add({'action': 'receipt', 'arguments': {'index': 0}, 'result': json.loads(self.run_.store.read_blob(self.state['receipts'][0]['blob']))})
        bundle = self.ask({'index': 1, 'field': 'text', 'offset': 0, 'item_offset': 0})
        entry = (bundle.get('requested_pages') or [None])[0]
        self.assertIsNotNone(entry, 'RED-P6: no page')
        self.assertEqual(entry['page'][0]['next']['arguments']['index'], 0, 'the page points at the original receipt')

    def test_two_requests_share_the_room_and_each_gets_a_page(self):
        self.add({'action': 'run', 'arguments': {}, 'result': {'argv': ['x'], 'exit_code': 1, 'stdout': vietnamese_source(52000, 'RA'), 'stderr': ''}})
        bundle = self.ask(0, 1)
        entries = bundle.get('requested_pages') or []
        self.assertEqual(sorted(e['index'] for e in entries), [0, 1], 'RED-P6: ' + str(bundle.get('not_included')))
        self.assertLessEqual(sum(len(canonical(e)) for e in entries), 12000 + 2000, 'within the room, not twice the room each')


if __name__ == '__main__':
    unittest.main()
