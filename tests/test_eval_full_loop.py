"""Completion levels (A2, 12/10/2026): partial work, a skipped E2E or a tests-only green run is never a full loop.

full_loop needs every loop stage of the project kind in the plan, passed, not skipped and run on the final source;
a verified, unpushed commit where the kind requires one; the handover report; and the final-outcome notice shown."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from onecrew import eval_completion as ec
from onecrew import eval_scorecard as sc
from onecrew.desktop_notifications import directory
from onecrew.ledger import content_hash
from tests.test_autonomy_round2 import done

SHOWN = {'id': 'n', 'status': 'shown', 'episode': 'outcome'}
NODE = [('change-1', 'change'), ('regression', 'node_regression'), ('review', 'review'), ('version', 'version'),
        ('build', 'node_build'), ('mock', 'e2e_mock'), ('build-live', 'node_build_live'), ('live', 'e2e_live'),
        ('commit', 'commit'), ('handover', 'handover')]
FLUTTER = [('change', 'change'), ('tests', 'regression'), ('review', 'review'), ('build', 'build'), ('audit', 'apk_audit'),
           ('device', 'device'), ('done', 'handover')]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.report = Path(self.tmp.name)/'handover.txt'; self.report.write_text('handover report', encoding='utf-8')

    def state(self, nodes=NODE, kind='node_extension'):
        plan = {'version': 2, 'kind': kind, 'nodes': [{'id': i, 'kind': k} for i, k in nodes],
                'acceptance': [{'id': 'AC1', 'text': 'x', 'nodes': [nodes[1][0]]}]}
        if kind is None: plan = {'version': 1, 'nodes': plan['nodes'], 'acceptance': plan['acceptance']}
        rows = {}
        for i, k in nodes:
            receipt = {'passed': True, 'source': 'src'}
            if k == 'commit': receipt.update(commit='c' * 40, verified=True, pushed=False)
            if k == 'handover': receipt.update(report=str(self.report), sha256=hashlib.sha256(self.report.read_bytes()).hexdigest())
            rows[i] = {'phase': 'passed', 'receipt': receipt, 'child': None}
        return {'phase': 'completed', 'verification': 'passed', 'plan': plan,
                'delivery': {'source': {'hash': 'src'}, 'nodes': rows, 'criteria': {'AC1': 'passed'}, 'technical_verified': True}}

    def level(self, state, windows=SHOWN):
        return sc.completion_level(self.observed(state, windows))

    def observed(self, state, windows=SHOWN, **metrics):
        t = done(**metrics)
        t['delivery'] = {'technical_verified': state['delivery']['technical_verified'], 'criteria': state['delivery']['criteria'],
                         'nodes': {k: {'kind': dict((n['id'], n['kind']) for n in state['plan']['nodes'])[k], 'phase': v['phase'],
                                       'skipped': v['receipt'].get('skipped') is True} for k, v in state['delivery']['nodes'].items()}}
        t['loop'] = ec.evidence(state, windows)
        return t

    def without(self, state, *ids):
        state = copy.deepcopy(state)
        state['plan']['nodes'] = [n for n in state['plan']['nodes'] if n['id'] not in ids]
        for i in ids: state['delivery']['nodes'].pop(i)
        return state


class LevelTests(Fixture):
    def test_full_loop_requires_all_stages(self):
        self.assertEqual(ec.COMPLETION_LEVELS, ('full_loop', 'plan_complete', 'partial', 'tests_only', 'blocked', 'incomplete', 'unknown'))
        self.assertEqual(ec.LOOP['node_extension'], ('change', 'regression', 'review', 'build', 'e2e_mock', 'e2e_live', 'commit', 'handover', 'notice'))
        full = self.state()
        self.assertEqual(self.level(full), ('full_loop', []))
        loop = ec.evidence(full, SHOWN)
        self.assertEqual(loop['stages'], dict.fromkeys(('change', 'regression', 'review', 'build', 'e2e_mock', 'e2e_live', 'commit', 'handover'), 'passed'))
        for stage, ids, gap in (('change', ['change-1'], 'loop_stage_missing:change'), ('regression', ['regression'], 'loop_stage_missing:regression'),
                                ('review', ['review'], 'loop_stage_missing:review'), ('build', ['build', 'build-live'], 'loop_stage_missing:build'),
                                ('e2e_mock', ['mock'], 'loop_stage_missing:e2e_mock'), ('e2e_live', ['live'], 'loop_stage_missing:e2e_live'),
                                ('commit', ['commit'], 'commit_missing'), ('handover', ['handover'], 'loop_stage_missing:handover')):
            with self.subTest(stage=stage):
                level, gaps = self.level(self.without(full, *ids))
                self.assertEqual(level, 'plan_complete'); self.assertIn(gap, gaps)
        self.assertEqual(self.level(self.without(full, 'version')), ('full_loop', []))  # version is not a loop stage

    def test_node_plan_kinds_map_to_stages(self):
        full = self.state()
        stale = copy.deepcopy(full); stale['delivery']['nodes']['build-live']['receipt']['source'] = 'older'
        self.assertEqual(self.level(stale), ('plan_complete', ['loop_stage_stale:build']))  # both builds verify the final source
        stale = copy.deepcopy(full); stale['delivery']['nodes']['mock']['receipt']['source'] = 'older'
        self.assertEqual(self.level(stale), ('plan_complete', ['loop_stage_stale:e2e_mock']))
        moved = copy.deepcopy(full); moved['delivery']['nodes']['change-1']['receipt']['source'] = 'older'
        self.assertEqual(self.level(moved), ('full_loop', []))  # a change produces the source; it is not re-verified
        unknown = copy.deepcopy(full); unknown['plan']['kind'] = 'cobol_mainframe'
        self.assertIn('loop_kind_unknown', self.level(unknown)[1])

    def test_tests_only(self):
        tests_only = self.without(self.state(), 'build', 'build-live', 'mock', 'live')
        self.assertEqual(self.level(tests_only), ('tests_only', ['no_build_or_e2e']))
        standalone = dict(done(), delivery=None, loop=None)  # a standalone native_change job: tests at most
        self.assertEqual(sc.completion_level(standalone), ('tests_only', ['not_a_delivery_loop']))
        self.assertEqual(sc.outcome(standalone)[0], 'tests_only')
        self.assertEqual(sc.completion_level(dict(standalone, verification='partial'))[0], 'partial')

    def test_skipped_live_partial(self):
        skipped = self.state()
        skipped['delivery']['nodes']['live']['receipt'].update(skipped=True, detail='login window closed')
        level, gaps = self.level(skipped)
        self.assertEqual(level, 'partial')
        self.assertIn('e2e_live_not_run', gaps); self.assertIn('nodes_skipped', gaps)
        self.assertEqual(sc.outcome(self.observed(skipped))[0], 'partial_complete')

    def test_missing_commit_plan_complete(self):
        full = self.state()
        self.assertEqual(self.level(self.without(full, 'commit')), ('plan_complete', ['commit_missing']))
        for change in ({'pushed': True}, {'verified': False}, {'pushed': None}, {'commit': 'HEAD'}, {'commit': None, 'commits': []},
                       {'commit': None, 'commits': ['d' * 40, 'not-a-sha']}):
            bad = copy.deepcopy(full); bad['delivery']['nodes']['commit']['receipt'].update(change)
            self.assertEqual(self.level(bad), ('plan_complete', ['commit_unverified']), change)
        two = copy.deepcopy(full); two['delivery']['nodes']['commit']['receipt'].update(commit=None, commits=['d' * 40, 'e' * 40])
        self.assertEqual(self.level(two), ('full_loop', []))  # code then version: two verified local commits

    def test_missing_notice_plan_complete(self):
        full = self.state()
        for windows in (None, dict(SHOWN, status='pending'), dict(SHOWN, episode='decision'), dict(SHOWN, status='failed')):
            self.assertEqual(self.level(full, windows), ('plan_complete', ['notice_not_shown']), windows)
        self.assertEqual(self.level(full, dict(SHOWN, status='closed')), ('full_loop', []))

    def test_handover_report_must_exist_with_its_hash(self):
        full = self.state()
        self.report.write_text('edited after handover', encoding='utf-8')
        self.assertEqual(self.level(full), ('plan_complete', ['handover_report_missing']))
        self.report.unlink()
        self.assertEqual(self.level(full), ('plan_complete', ['handover_report_missing']))

    def test_flutter_loop_needs_no_commit(self):
        self.assertEqual(ec.LOOP['flutter_android'], ('change', 'regression', 'review', 'build', 'apk_audit', 'device', 'handover', 'notice'))
        flutter = self.state(FLUTTER, None)
        self.assertEqual(self.level(flutter), ('full_loop', []))
        self.assertEqual(self.level(self.without(flutter, 'audit')), ('plan_complete', ['loop_stage_missing:apk_audit']))
        self.assertEqual(self.level(self.without(flutter, 'change', 'device')),
                         ('plan_complete', ['loop_stage_missing:change', 'loop_stage_missing:device']))

    def test_relay_assisted_full_loop(self):
        full, zero = self.state(), {'user': 0, 'relayed': 0, 'delegated': 0, 'undelegated': 0, 'observed': 0, 'unknown': 0}
        self.assertEqual(sc.outcome(self.observed(full)), ('autonomous_full_loop', []))
        relayed = self.observed(full, decisions_answered=1, decisions_by_source=dict(zero, relayed=1))
        self.assertEqual(sc.outcome(relayed), ('assisted_full_loop', ['entry_relayed_decision']))
        unknown = self.observed(full, decisions_answered=1)
        self.assertEqual(sc.outcome(unknown), ('unknown', ['decision_provenance_unknown']))
        partial = self.observed(full, decisions_answered=1, decisions_by_source=dict(zero, relayed=1))
        partial['loop'] = ec.evidence(full, None)
        self.assertEqual(sc.outcome(partial), ('plan_complete', ['notice_not_shown']))  # never rounded up
        self.assertEqual(set(sc.OUTCOMES), {'autonomous_full_loop', 'assisted_full_loop', 'plan_complete', 'partial_complete',
                                            'tests_only', 'correct_block', 'incomplete', 'unknown'})


class ScorecardTests(Fixture):
    """The same rules through observe/scorecard over a ledger, with the notice the runtime wrote."""
    def setUp(self):
        super().setUp()
        self.root = Path(self.tmp.name)/'state'; self.root.mkdir()
        env = patch.dict('os.environ', {'ONECREW_DESKTOP_HOME': str(self.root/'desktop')}); env.start(); self.addCleanup(env.stop)
        self.c = sqlite3.connect(self.root/'ledger.sqlite3'); self.addCleanup(self.c.close)
        self.c.executescript('''CREATE TABLE tasks(id TEXT, project_id TEXT);
            CREATE TABLE events(seq INTEGER PRIMARY KEY, task_id TEXT, kind TEXT, payload TEXT, created_at TEXT);
            CREATE TABLE requests(id TEXT, revision TEXT, task_id TEXT, state TEXT);
            CREATE TABLE delivery_roots(task_id TEXT PRIMARY KEY, plan TEXT, revision TEXT);
            CREATE TABLE delivery_children(task_id TEXT PRIMARY KEY, root TEXT NOT NULL, node TEXT NOT NULL, generation INTEGER NOT NULL);
            CREATE TABLE executions(task_id TEXT, used_calls INTEGER);''')

    def add(self, n, state, events, notice=True):
        task = 'TASK-' + format(n, '032x')
        self.c.execute('INSERT INTO tasks VALUES (?,?)', (task, 'p')); self.c.execute('INSERT INTO delivery_roots VALUES (?,?,?)', (task, '{}', 'r'))
        seq = self.event(task, 'workflow.checkpoint', state)
        for kind, value in events: self.event(task, kind, value)
        if notice:
            key = content_hash({'task': task, 'outcome': {'phase': 'completed', 'first': seq}})[:32]
            folder = directory(SimpleNamespace(state_root=self.root)); folder.mkdir(parents=True, exist_ok=True)
            (folder/(key + '.json')).write_text(json.dumps({'id': key, 'task': task, 'phase': 'completed', 'status': 'shown'}))
        return task

    def event(self, task, kind, value):
        seq = self.c.execute('INSERT INTO events(task_id,kind,payload,created_at) VALUES (?,?,?,?)',
                             (task, kind, json.dumps(value), '2026-10-12T00:00:00+00:00')).lastrowid
        self.c.commit(); return seq

    def test_scorecard_reads_the_full_loop_and_entry_help(self):
        state = dict(self.state(), delivery=dict(self.state()['delivery'], planning={'mode': 'onecrew'}))
        trace = [('control.intervention', {'actor': 'claude', 'channel': 'cli', 'command': 'delivery.submit'}),
                 ('runner.started', {'runtime': {'tree': 't1', 'git': 'g', 'dirty': False}, 'initiator': 'claude'})]
        own = self.add(1, state, trace)
        shown_by_entry = self.add(2, state, trace + [('control.intervention', {'actor': 'claude', 'channel': 'cli', 'command': 'desktop.show'})])
        no_notice = self.add(3, state, trace, notice=False)
        repeated = self.add(4, state, trace + [('control.intervention', {'actor': 'claude', 'channel': 'cli', 'command': 'delivery.submit'})])
        rows = {t['task']: t for t in sc.scorecard(self.root, [own, shown_by_entry, no_notice, repeated])['axes']['task_completion']['tasks']}
        self.assertEqual((rows[own]['outcome'], rows[own]['completion_level']), ('autonomous_full_loop', 'full_loop'))
        self.assertEqual((rows[shown_by_entry]['outcome'], rows[shown_by_entry]['outcome_reasons']), ('assisted_full_loop', ['entry_intervention']))
        self.assertEqual((rows[no_notice]['outcome'], rows[no_notice]['completion_gaps']), ('plan_complete', ['notice_not_shown']))
        self.assertEqual((rows[repeated]['outcome'], rows[repeated]['outcome_reasons']), ('assisted_full_loop', ['repeat_handoff']))
        card = sc.scorecard(self.root, [own])
        self.assertEqual(card['axes']['task_completion']['completion_levels']['full_loop'], 1)
        self.assertNotIn(str(self.report), json.dumps(card))  # booleans and stage names only, never report paths


if __name__ == '__main__':
    unittest.main()
