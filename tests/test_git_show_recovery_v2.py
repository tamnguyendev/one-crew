import unittest, json, copy
import tests.test_owned as fixtures
import tests.test_work_contract as wc
from onecrew.git_history import History
from onecrew import progress as P
from onecrew.owned import Owned, canonical, contract as make_contract
from onecrew.owned_intake import submit
from tests.test_workflow import FixtureWorker


def _directive_in_prompt(prompt):
    """The git_show_mode recovery directive as it would reach the adapter: parse the trailing JSON object and find the
    file_list_exhausted signal wherever the prompt of that job mode carries it - a WORK prompt renders it under
    recovery.git_show_mode (full prose at the loose tier, terse signal at compact/tighter; owned._work_prompt), a JOB prompt
    (audit/branch) delivers the progress dict whole under progress_limits (owned.run). The prompt STRING is parsed, never
    the handler's return value. A prompt may carry several JSON objects (a JOB prompt renders the state and the instruction
    as separate objects), so every object in the string is parsed; returns (the object holding the directive, or the last
    one, the directive or None)."""
    def walk(node):
        if isinstance(node, dict):
            if node.get('kind') == 'file_list_exhausted' and 'hint' in node: return node
            for v in node.values():
                found = walk(v)
                if found is not None: return found
        elif isinstance(node, list):
            for v in node:
                found = walk(v)
                if found is not None: return found
        return None
    decoder = json.JSONDecoder(); objects = []; i = prompt.find('{')
    while i != -1:
        try:
            value, end = decoder.raw_decode(prompt, i); objects.append(value); i = prompt.find('{', end)
        except ValueError:
            i = prompt.find('{', i + 1)
    for obj in objects:
        g = (obj.get('recovery') or {}).get('git_show_mode') if isinstance(obj, dict) else None
        if g is None: g = walk(obj)
        if g is not None: return obj, g
    return (objects[-1] if objects else {}), None


class V2Bug1HintReachesAdapterTests(unittest.TestCase):
    """BUG 1: owned._recovery dropped git_show_mode under the tight prompt cap ('and not compact'), so the directive the
    worker must act on never reached the adapter. Fix: keep it under compact, reduced to its actionable signal at tighter.
    Driven through the REAL _recovery and the REAL _work_prompt (model stubbed), not a copy of the handler."""

    def _run(self):
        t = wc.WorkFixture(); t.setUp(); self.addCleanup(t.doCleanups)
        task = submit(t.ledger, None, 'work', mode='work', provider='kiro', model='claude-sonnet-5', contract=t.contract())['id']
        run = Owned(t.ledger, FixtureWorker(t.ledger, [])); run.enable(task)
        control = run.control.status(task); profile = control['configuration']['profile']
        seq, state = run.state(task)
        return t, run, task, profile, control, state

    @staticmethod
    def _gshow(state, commit='c' * 40):
        prog = state.setdefault('progress', {})
        prog['git_show_mode'] = {'kind': 'file_list_exhausted', 'commit': commit, 'total_files': 166,
            'hint': ('You reached the end of the changed-file LIST for this commit (git_show with no path). Re-calling the list returns the same result. '
                     'To read a file diff, call git_show with the same commit and path=one of the filenames already listed (cursor=0) -- pick the file yourself. '
                     'The LIST total and a single file diff are different things; do not re-request the exhausted list.')}
        return prog['git_show_mode']

    def test_1_hint_present_in_recovery_at_compact_and_tighter(self):
        # RED on baseline: 'and not compact' drops git_show_mode entirely at compact (and so at tighter). GREEN on fix: present at both.
        t, run, task, profile, control, state = self._run()
        self._gshow(state)
        loose = run._recovery(state, control, compact=False, tighter=False).get('git_show_mode')
        compact = run._recovery(state, control, compact=True, tighter=False).get('git_show_mode')
        tight = run._recovery(state, control, compact=True, tighter=True).get('git_show_mode')
        self.assertIsNotNone(loose, 'hint must be present when roomy')
        self.assertIsNotNone(compact, 'BUG1: hint must survive the compact tier')
        self.assertIsNotNone(tight, 'BUG1: hint must survive the tightest tier')
        self.assertEqual(tight['kind'], 'file_list_exhausted')     # the actionable signal is kept
        self.assertTrue(tight['hint'])                             # a short self-contained directive remains
        self.assertLess(len(tight['hint']), len(loose['hint']))    # long prose yields at the tightest tier (no starving)

    def test_1b_hint_is_bounded_not_full_prose_at_tighter(self):
        # Condition (1): the signal that lands at the tightest tier is the terse directive, not the full deterministic prose.
        t, run, task, profile, control, state = self._run()
        self._gshow(state)
        tight = run._recovery(state, control, compact=True, tighter=True).get('git_show_mode')
        self.assertIsNotNone(tight, 'BUG1: hint must survive the tightest tier')  # clean RED on baseline (dropped)
        self.assertNotIn('do not re-request the exhausted list', tight['hint'])  # verbose prose dropped
        self.assertIn('pick one listed path', tight['hint'])                     # terse actionable form kept

    def test_2_hint_reaches_the_actual_prompt_within_cap_valid_page(self):
        # Condition (1), end-to-end: build the ACTUAL prompt (level-selected) with a git_show_mode hint active and a big
        # latest result; the directive appears in the prompt the adapter receives, the prompt fits the cap, and the latest
        # result still gets a valid page. Model stubbed; real _work_prompt (raises if starved).
        t = wc.WorkFixture(); t.setUp(); self.addCleanup(t.doCleanups)
        big = chr(10).join('row %05d %s' % (i, 'q' * 70) for i in range(1600))
        (t.root / 'big.txt').write_text(big); t.git('add', 'big.txt'); t.git('commit', '-q', '-m', 'big')
        def act(name, plan, **a): return {'plan': plan, 'action': name, 'arguments': json.dumps(a)}
        resp = [act('read', 'P', path='big.txt'), act('receipt', 'page it', index=0, offset=0)]
        task = submit(t.ledger, None, 'work', mode='work', provider='kiro', model='claude-sonnet-5', contract=t.contract())['id']
        run = Owned(t.ledger, FixtureWorker(t.ledger, resp)); run.enable(task)
        run.run(task, steps=2)
        seq, state = run.state(task)
        self._gshow(state)
        control = run.control.status(task); profile = control['configuration']['profile']
        tp, tsch, _ = make_contract(profile)
        with t.ledger.transaction() as conn:
            notes = [json.loads(r['payload']) for r in conn.execute(
                "SELECT payload FROM events WHERE task_id=? AND kind='entry.note' ORDER BY seq DESC LIMIT 5", (task,))]
        # V2-tests (F2): under the production 15000 cap this small fixture stays at the LOOSE tier, where even a04c812 kept
        # the hint - so the test did not exercise BUG1. Emulate a tighter provider cap on THIS runtime object only (the class
        # attribute is untouched): the level-selector then descends to the compact tier, which is the condition of BUG1.
        run.PROMPT_LIMITS = {profile['provider']: 10000}
        prompt = run._work_prompt(task, state, profile, control, tp, tsch, notes)
        cap = run.PROMPT_LIMITS[profile['provider']]
        self.assertLessEqual(len(canonical(tsch)) + len(prompt) + 40, cap)   # within the provider cap
        obj, g = _directive_in_prompt(prompt)
        note = (obj.get('recovery') or {}).get('note') or ''
        self.assertTrue(note.startswith('From the checkpoint') or note.startswith('Trimmed'),
                        'the selector must have chosen the compact/tighter tier, or this test proves nothing about BUG1: ' + note[:60])
        self.assertIsNotNone(g, 'BUG1: the git_show_mode directive must be in the prompt the adapter receives')
        self.assertEqual(g['kind'], 'file_list_exhausted')
        self.assertIn('pick one listed path', g['hint'])   # the bounded signal, not the full prose, at the tight tier
        lr = obj.get('latest_result') or {}
        self.assertTrue(lr.get('complete') or run._page_content >= run.MIN_PAGE_CONTENT,
                        'latest result must get a VALID page, not be starved by the hint')


class V2Bug2HintTerminatesTests(unittest.TestCase):
    """BUG 2: after the worker picks a path and gets a diff, the file_list_exhausted hint still persisted (the old clear only
    fired for a non-git_show action). Fix: a SUCCESSFUL file_diff read of the matching commit resolves the warning; a tool
    error does not; a stale warning is not carried to an unrelated commit; the guard/history are never reset. Real
    History.show on a real temp repo + real progress.observe."""

    def setUp(self):
        self.f = fixtures.OwnedTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.setup_git()
        self.base = self.f.git('rev-parse', 'HEAD').decode().strip()
        for i in range(135):
            (self.f.root / ('file_%03d.txt' % i)).write_text('hello %d\n' % i)
        self.f.git('add', '-A'); self.f.git('commit', '-q', '-m', 'many files')
        self.change = self.f.git('rev-parse', 'HEAD').decode().strip()
        self.run, self.task, self.worker = self.f.runtime([], mode='branch', branch='onecrew/pre-ui')
        self.profile = self.run.control.status(self.task)['configuration']['profile']
        self.history = History(self.run, self.task, self.profile, '')
        self.total = self.history.show(self.change, self.change, None, 0)['total_paths']
        self.assertGreater(self.total, 100)

    def _raise_hint(self, st):
        res1 = self.history.show(self.change, self.change, None, 100)   # eof list
        P.observe(st, 'git_show', {'commit': self.change, 'cursor': 100}, res1)
        P.observe(st, 'git_show', {'commit': self.change, 'cursor': 100}, res1)
        self.assertIsNotNone((st.get('progress') or {}).get('git_show_mode'))
        return res1

    def test_1_successful_diff_read_resolves_the_hint(self):
        # Condition (2): list exhausted -> warning -> worker picks a path -> diff returns OK -> warning gone from state.
        st = {'phase': 'running', 'step': 1, 'work': {}}
        self._raise_hint(st)
        pick = self.history.show(self.change, self.change, None, 100)['paths'][0]
        diff = self.history.show(self.change, self.change, pick, 0)
        self.assertEqual(diff['mode'], 'file_diff')
        P.observe(st, 'git_show', {'commit': self.change, 'path': pick, 'cursor': 0}, diff)
        self.assertIsNone((st.get('progress') or {}).get('git_show_mode'), 'BUG2: a successful diff must clear the warning')

    def test_2_failed_diff_is_not_a_successful_recovery(self):
        # Control: a tool ERROR on the diff read does NOT resolve the warning (not reported as success).
        st = {'phase': 'running', 'step': 1, 'work': {}}
        self._raise_hint(st)
        P.observe(st, 'git_show', {'commit': self.change, 'path': 'missing', 'cursor': 0}, {'error': 'no such path'})
        self.assertIsNotNone((st.get('progress') or {}).get('git_show_mode'), 'an errored diff must not clear the warning')

    def test_3_stale_warning_not_carried_to_unrelated_commit(self):
        # Condition (2): the warning is scoped to its commit; working a DIFFERENT commit's list drops the stale warning.
        st = {'phase': 'running', 'step': 1, 'work': {}}
        self._raise_hint(st)
        other = self.history.show(self.base, self.base, None, 0)   # a different commit's list
        P.observe(st, 'git_show', {'commit': self.base, 'cursor': 0}, other)
        self.assertIsNone((st.get('progress') or {}).get('git_show_mode'), 'a stale warning must not cling across commits')

    def test_4_next_prompt_has_no_stale_hint_after_diff(self):
        # Condition (2) at the prompt level: after the diff clears the hint, the next _recovery carries no git_show_mode.
        st = {'phase': 'running', 'step': 1, 'work': {}}
        self._raise_hint(st)
        pick = self.history.show(self.change, self.change, None, 100)['paths'][0]
        diff = self.history.show(self.change, self.change, pick, 0)
        P.observe(st, 'git_show', {'commit': self.change, 'path': pick, 'cursor': 0}, diff)
        # a minimal state the recovery render tolerates
        full = {'phase': 'running', 'step': 2, 'work': {}, 'receipts': [], 'progress': st.get('progress') or {}}
        control = self.run.control.status(self.task)
        # V2-tests (F3): check the LOOSE tier first - at the tight tier a04c812 dropped every hint (the BUG1 symptom), so a
        # tight-only check was green on the baseline for the wrong reason and did not isolate BUG2.
        loose = self.run._recovery(full, control, compact=False, tighter=False)
        self.assertIsNone(loose.get('git_show_mode'), 'BUG2: no stale hint may ride in the next prompt after a successful diff')
        rec = self.run._recovery(full, control, compact=True, tighter=True)
        self.assertIsNone(rec.get('git_show_mode'), 'BUG2: no stale hint may ride in the next (tight) prompt after a successful diff')

    def test_5_repetition_still_blocks_finitely_guard_not_reset(self):
        # Control: clearing-by-result does NOT weaken the same-result guard; genuine repetition still blocks finitely.
        st = {'phase': 'running', 'step': 1, 'work': {}}
        res1 = self._raise_hint(st)
        P.observe(st, 'git_show', {'commit': self.change, 'cursor': 100}, res1)
        self.assertEqual(st['phase'], 'blocked')
        self.assertEqual(st['recovery']['kind'], 'no_progress')

    def test_6_cross_core_flow_public_resume_pick_path_resolves(self):
        # Cross-core flow through the REAL runner (model stubbed), in the order the live CTS loop happened:
        #   multi-page list -> the EXHAUSTED list is re-called once more (same result, count 2: the hint is RAISED while the
        #   same-result guard, limit 3, has not blocked yet) -> RESTART the runtime object and resume via the SUPPORTED public
        #   Owned.resume (not a JSON substitute) -> the hint survives the restart -> the new stubbed worker RECEIVES the
        #   directive in the prompt the adapter is given and picks a path among the listed files -> the diff is right -> the
        #   warning resolves; used_calls counted, never reset; the job is not blocked.
        # V2-tests (F1): the first version of this test never re-called the exhausted list, so the hint was never raised and
        # its final assertIsNone passed vacuously (green on a04c812 too). The hint-raised assertions below make it a real flow.
        def act(name, plan, **a): return {'plan': plan, 'action': name, 'arguments': json.dumps(a)}

        class RecordingWorker(FixtureWorker):   # keeps the prompt the adapter actually receives, per call
            def __init__(self, ledger, responses):
                super().__init__(ledger, responses); self.prompts = []
            def run(self, attempt, prompt, schema, profile):
                self.prompts.append(prompt); return super().run(attempt, prompt, schema, profile)

        # a FRESH fixture (its own repo + submission key) so the second task does not collide with setUp's task
        g = fixtures.OwnedTests(); g.setUp(); self.addCleanup(g.doCleanups); g.setup_git()
        for i in range(135):
            (g.root / ('file_%03d.txt' % i)).write_text('hello %d\n' % i)
        g.git('add', '-A'); g.git('commit', '-q', '-m', 'many files')
        change = g.git('rev-parse', 'HEAD').decode().strip()
        run, task, _ = g.runtime([], mode='branch', branch='onecrew/pre-ui2')
        hist = History(run, task, run.control.status(task)['configuration']['profile'], '')
        first_file = hist.show(change, change, None, 100)['paths'][0]
        # re-point the worker with the real git_show sequence (no second submit, so the key does not collide)
        run.worker = FixtureWorker(run.ledger, [
            act('git_show', 'list all changed files', commit=change, cursor=0),
            act('git_show', 'the rest of the list', commit=change, cursor=100),
            act('git_show', 'the rest of the list', commit=change, cursor=100)])   # the exhausted list AGAIN (count 2)
        run.run(task, steps=3)
        seq, state = run.state(task)
        hint = (state.get('progress') or {}).get('git_show_mode')
        self.assertIsNotNone(hint, 'the re-called exhausted list must RAISE the recovery hint')
        self.assertEqual(hint['kind'], 'file_list_exhausted')
        self.assertEqual(state['phase'], 'running', 'count 2 warns; the guard blocks at 3 - the job must still be running')
        used_before = run.control.status(task).get('used_calls'); self.assertEqual(used_before, 3)
        # restart the runtime object and resume via the SUPPORTED public API (not a JSON substitute)
        worker2 = RecordingWorker(run.ledger, [act('git_show', 'now read one file diff', commit=change, path=first_file, cursor=0)])
        restarted = Owned(run.ledger, worker2)
        self.assertIsNotNone(restarted.resume(task))
        seq2, state2 = restarted.state(task)
        self.assertIsNotNone((state2.get('progress') or {}).get('git_show_mode'), 'the hint must survive restart + public resume')
        restarted.run(task, steps=1)
        # adapter side: the directive was in the prompt the worker received for the step in which it picked the path. This
        # fixture is a JOB (branch) runtime with no provider cap, whose prompt carries the progress dict whole; the capped
        # WORK-prompt rendering (the BUG1 tier condition) is Bug1 test_2's subject, not this flow's.
        self.assertEqual(len(worker2.prompts), 1)
        obj, directive = _directive_in_prompt(worker2.prompts[0])
        self.assertIsNotNone(directive, 'the directive must reach the adapter in the prompt after the resume')
        self.assertEqual(directive['kind'], 'file_list_exhausted')
        # core side: the right diff came back, the warning resolved, usage counted (not reset), guard did not block
        seq3, state3 = restarted.state(task)
        last = json.loads(restarted.store.read_blob(state3['receipts'][-1]['blob']))['result']
        self.assertEqual(last.get('mode'), 'file_diff'); self.assertEqual(last.get('path'), first_file)
        self.assertEqual(last.get('commit'), change); self.assertNotIn('error', last)
        self.assertIsNone((state3.get('progress') or {}).get('git_show_mode'),
                          'after a successful diff read the warning is resolved across a public resume')
        self.assertEqual(hint.get('commit'), change, 'the raised hint is scoped to the commit it was raised for')
        self.assertEqual(state3['phase'], 'running')
        self.assertEqual(restarted.control.status(task).get('used_calls'), used_before + 1)  # usage counted, never reset


class V2CTSCopyNoPromptBudgetRegressionTests(unittest.TestCase):
    """Control: the V2 recovery-section change (git_show_mode now kept under the compact/tighter cap) must NOT reintroduce
    a prompt_budget block on the CURRENT live CTS checkpoint, whatever step it sits at. Driven on a COPY via the REAL
    _work_prompt (no model call, no write to the original state). Skips (NOT a pass) when the live state is not on this host."""
    CTS_STATE = r"D:\OneCrewRuns\live-task-e76c703\state-live1"
    CTS_PROJECT = r"D:\TamNT\Workspace\1.Vimes\7.SRM\source\flutter_srm"
    TID = "TASK-8b938053d4804e32be5176e8d7fabec0"

    def _copy_runtime(self):
        import os, tempfile, shutil
        if not os.path.isdir(self.CTS_STATE): self.skipTest('CTS live state not present on this host')
        if not os.path.isdir(self.CTS_PROJECT): self.skipTest('CTS project repo not present on this host')
        tmp = tempfile.mkdtemp(prefix='cts-v2-'); self.addCleanup(shutil.rmtree, tmp, True)
        dst = os.path.join(tmp, 'state-live1'); shutil.copytree(self.CTS_STATE, dst)
        from onecrew.ledger import Ledger
        return Owned(Ledger(self.CTS_PROJECT, dst), None), dst

    def test_current_checkpoint_build_does_not_reintroduce_prompt_budget(self):
        from onecrew.owned import contract as C, PromptBudgetError
        from onecrew.paging import MIN_PAGE
        run, dst = self._copy_runtime()
        status = run.control.status(self.TID); seq, st = run.state(self.TID)
        used_before = status.get('used_calls')
        self.assertIsInstance(used_before, int); self.assertGreater(used_before, 0)
        prof = dict(status['configuration']['profile'], provider=(st.get('worker') or {}).get('provider') or 'kiro',
                    model=(st.get('worker') or {}).get('model') or 'claude-sonnet-4.5')
        tp, tsch, _ = C(prof)
        with run.ledger.transaction() as conn:
            notes = [json.loads(r['payload']) for r in conn.execute(
                "SELECT payload FROM events WHERE task_id=? AND kind='entry.note' ORDER BY seq DESC LIMIT 5", (self.TID,))]
        try:
            prompt = run._work_prompt(self.TID, st, prof, status, tp, tsch, notes)
        except PromptBudgetError as e:
            self.fail('V2 change reintroduced a prompt_budget block on the current CTS checkpoint: %s' % e)
        # The point of THIS control is only that the V2 recovery-section change does not reintroduce a prompt_budget
        # block: the build above completed without PromptBudgetError. Assert the prompt also fits the provider cap and
        # carries a latest_result section. (A page's size at a no_progress block is step-specific - a small exhausted
        # list page is legitimate here - so MIN_PAGE applies to the prompt_budget STARVATION class, proven by the
        # self-contained Bug1 test_2, not to this live no_progress checkpoint.)
        cap = run.PROMPT_LIMITS[prof['provider']]
        self.assertLessEqual(len(canonical(tsch)) + len(prompt) + 40, cap)   # within the provider cap, no starvation
        obj = json.loads('{' + prompt.rpartition(chr(10) + '{')[2])
        self.assertIn('latest_result', obj)
        self.assertEqual(run.control.status(self.TID).get('used_calls'), used_before)  # original untouched, no reset


if __name__ == '__main__':
    unittest.main()
