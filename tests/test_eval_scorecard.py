import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from types import SimpleNamespace

from onecrew.desktop_notifications import directory
from onecrew.eval_scorecard import scorecard, markdown
from onecrew.evaluation import compare, main, read_result, seal
from onecrew.ledger import LedgerError, content_hash
from tests.test_evaluation import run_value

# A full flutter_android loop (A2, 12/10): change through handover; add() also writes the report and the shown notice.
NODES = [{'id':'change','kind':'change'},{'id':'tests','kind':'regression'},{'id':'review','kind':'review'},{'id':'build','kind':'build'},
         {'id':'audit','kind':'apk_audit'},{'id':'device','kind':'device'},{'id':'done','kind':'handover'}]
SECRET = 'PRIVATE_SENTINEL'


def task(n):
    return 'TASK-'+format(n,'032x')


def state(phase='completed', blocked=None, **delivery):
    done = phase == 'completed'
    ran = lambda n: done or n in ('change','tests','review')
    d = {'version':1,'generation':0,'repairs':0,'history':[],'source':{'hash':'src'},
         'criteria':{'AC1':'passed' if done else 'pending','AC2':'passed' if done else 'blocked' if blocked else 'pending'},
         'nodes':{n['id']:{'phase':'passed' if ran(n['id']) else 'pending','child':None,
                           'receipt':{'passed':True,'source':'src','counts':{'passed':50,'failed':0,'skipped':0}} if ran(n['id']) else None}
                  for n in NODES}}
    if blocked: d['nodes'][blocked]['phase'] = 'blocked'
    if done: d.update(technical_verified=True, product_acceptance='not_requested')
    d.update(delivery)
    return {'phase':phase,'snapshot':'s','verification':'passed' if done else 'pending','message':SECRET,'report':SECRET,
            'plan':{'nodes':NODES,'acceptance':[{'id':'AC1','text':SECRET,'nodes':['tests']},{'id':'AC2','text':SECRET,'nodes':['device']}]},
            'delivery':d,'outputs':[{'summary':SECRET}] if done else []}


def answered(sender, decided_by=None, legacy=False):
    """A reply as ledger.reply + ledger_cli/mcp_entry record it; legacy receipts carry no by/decided_by."""
    provenance = {'actor':SECRET,'reference':SECRET} if legacy else {'actor':SECRET,'reference':SECRET,'by':sender,'decided_by':decided_by}
    return [('request.answered',{'id':'REPLY-'+sender,'request_id':'REQ-x','choice':'yes','provenance':provenance}),
            ('control.intervention',{'actor':sender,'channel':'cli','command':'request.reply','key':'REPLY-'+sender,
                                     'details':{'choice':'yes','decided_by':decided_by},'reason':SECRET})]


# Event shapes as written by delivery_cli/ledger_cli (interventions), runner.loop and the keeper.
START = [('control.intervention',{'actor':'codex','channel':'cli','command':'delivery submit','reason':SECRET,'details':None}),
         ('runner.started',{'identity':{'pid':1},'runtime':{'tree':'t1','git':None,'dirty':None},'initiator':'codex'}),
         ('runner.started',{'identity':{'pid':2},'runtime':{'tree':'t1','git':None,'dirty':None},'initiator':'keeper'}),
         ('coordinator.restarted',{'cause':'runner_dead','restart_count':1,'runner':{'status':'starting','error':SECRET}})]
RESTART = [('runner.started',{'identity':{'pid':3},'runtime':{'tree':'t1','git':None,'dirty':None},'initiator':'reply'})]
# The user answered OneCrew's question themselves: a decision, not assistance.
TRACED = START+answered('user','user')+RESTART


class ScorecardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'state'; self.root.mkdir(); self.db = self.root/'ledger.sqlite3'
        self.c = sqlite3.connect(self.db); self.addCleanup(self.c.close)
        self.c.executescript('''CREATE TABLE tasks(id TEXT, project_id TEXT);
            CREATE TABLE events(seq INTEGER PRIMARY KEY, task_id TEXT, kind TEXT, payload TEXT, created_at TEXT);
            CREATE TABLE requests(id TEXT, revision TEXT, task_id TEXT, state TEXT);
            CREATE TABLE delivery_roots(task_id TEXT PRIMARY KEY, plan TEXT, revision TEXT);
            CREATE TABLE delivery_children(task_id TEXT PRIMARY KEY, root TEXT NOT NULL, node TEXT NOT NULL, generation INTEGER NOT NULL, UNIQUE(root,node,generation));
            CREATE TABLE executions(task_id TEXT, used_calls INTEGER);''')
        env = patch.dict('os.environ', {'ONECREW_DESKTOP_HOME':str(self.root/'desktop')}); env.start(); self.addCleanup(env.stop)
        self.ids = {}
        self.add('autonomous', state(planning={'mode':'onecrew'}), TRACED)
        child = 'TASK-'+'f'*32
        self.add('intervened', state(planning={'mode':'onecrew'}), TRACED, children=[child])
        self.event(child, 'control.intervention', {'actor':'claude','channel':'mcp','command':'task.resume','reason':SECRET})
        self.add('entry_plan', state(), TRACED)
        self.add('runtime_changed', state(planning={'mode':'onecrew'}), TRACED+[('runner.started',{'runtime':{'tree':'t2'},'initiator':'keeper'})])
        self.add('noted', state(planning={'mode':'onecrew'}), TRACED+[('eval.assistance',{'key':'k','actor':'codex','category':'build','reason':SECRET,'checkpoint':1})])
        self.add('entry_restart', state(planning={'mode':'onecrew'}), TRACED+[('runner.started',{'runtime':{'tree':'t1'},'initiator':'claude'})])
        self.add('escalated', state('waiting', blocked='device', planning={'mode':'onecrew'},
                                    escalations=[{'request':'REQ-old','class':'transient'},{'request':'REQ-e','signature':'sig','class':'environment','node':'device'}],
                                    failures={'sig':{'class':'environment','detail':SECRET}}, recoveries=[{'class':'environment','action':'retry'}]), TRACED)
        self.request('REQ-e', 'escalated'); self.request('REQ-old', 'escalated', 'answered')
        self.add('silent_block', state('blocked', blocked='build', planning={'mode':'onecrew'}, failures={'sig':{'class':'product'}}), TRACED)
        self.add('unclassified', state('waiting', planning={'mode':'onecrew'}, escalations=[{'request':'REQ-u','class':'unknown'}],
                                       failures={'sig':{'class':'unknown'}}), TRACED)
        self.request('REQ-u', 'unclassified')
        self.add('answered', state('waiting', planning={'mode':'onecrew'}, escalations=[{'request':'REQ-a','class':'budget'}],
                                   failures={'sig':{'class':'budget'}}), TRACED)
        self.request('REQ-a', 'answered', 'answered')
        self.add('running', state('running', planning={'mode':'onecrew'}), TRACED)
        self.add('no_checkpoint', None, [])
        self.add('untraced', state(planning={'mode':'onecrew'}), [])
        # The root coordinator starts children as 'onecrew'; any other launcher of a child is the entry.
        started = 'TASK-'+'e'*32
        self.add('child_entry_start', state(planning={'mode':'onecrew'}), TRACED, children=[started])
        for who in ('onecrew', 'unknown'): self.event(started, 'runner.started', {'runtime':{'tree':'t1'},'initiator':who})
        # Receipt shape SolutionDelivery._skip_optional writes for an unavailable optional device stage.
        skipped = state(planning={'mode':'onecrew'}); skipped['delivery']['criteria']['AC2'] = 'not_run'
        skipped['delivery']['nodes']['device']['receipt'] = {'passed':True,'skipped':True,'source':'src','detail':'Optional device stage not run: '+SECRET}
        self.add('skipped_device', skipped, TRACED)
        self.add('device_block', state('waiting', blocked='device', planning={'mode':'onecrew'}, escalations=[{'request':'REQ-d','class':'device_assertion'}],
                                       failures={'sig':{'class':'device_assertion'}}), TRACED)
        self.request('REQ-d', 'device_block')
        self.add('garbage_class', state('waiting', planning={'mode':'onecrew'}, escalations=[{'request':'REQ-g','class':'made-up'}],
                                        failures={'sig':{'class':'made-up'}}), TRACED)
        self.request('REQ-g', 'garbage_class')
        # A restart by a runtime that predates launcher attribution: unknown, neither entry nor OneCrew.
        self.add('legacy_start', state(planning={'mode':'onecrew'}), TRACED+[('runner.started',{'identity':{'pid':9}})])
        # Codex review 2026-10-12: an entry deciding 'retry' under delegation was scored autonomous_complete.
        self.add('entry_decided', state(planning={'mode':'onecrew'}), START+answered('claude','entry')+RESTART)
        self.add('relayed', state(planning={'mode':'onecrew'}), START+answered('claude','user')+RESTART)
        self.add('unattributed', state(planning={'mode':'onecrew'}), START+answered('codex',legacy=True)+RESTART)
        self.c.commit()

    def add(self, name, value, events, children=()):
        t = self.ids[name] = task(len(self.ids)+1)
        self.c.execute('INSERT INTO tasks VALUES (?,?)', (t,'project'))
        self.c.execute('INSERT INTO delivery_roots VALUES (?,?,?)', (t,'{}','r'))
        for n, child in enumerate(children):
            self.c.execute('INSERT INTO tasks VALUES (?,?)', (child,'project'))
            self.c.execute('INSERT INTO delivery_children VALUES (?,?,?,0)', (child,t,'node'+str(n)))
        if value and value['phase'] == 'completed':
            report = self.root/('handover-'+t+'.txt'); report.write_text('report', encoding='utf-8')
            value['delivery']['nodes']['done']['receipt'].update(report=str(report), sha256=hashlib.sha256(report.read_bytes()).hexdigest())
        if value: seq = self.event(t, 'workflow.checkpoint', value)
        if value and value['phase'] == 'completed':  # the final-outcome notice the runtime showed
            key = content_hash({'task':t,'outcome':{'phase':'completed','first':seq}})[:32]
            folder = directory(SimpleNamespace(state_root=self.root)); folder.mkdir(parents=True, exist_ok=True)
            (folder/(key+'.json')).write_text(json.dumps({'id':key,'task':t,'phase':'completed','status':'shown'}))
        for kind, payload in events: self.event(t, kind, payload)

    def request(self, rid, name, status='pending'):
        self.c.execute('INSERT INTO requests VALUES (?,?,?,?)', (rid,'1',self.ids[name],status))

    def event(self, t, kind, value):
        seq = self.c.execute('INSERT INTO events(task_id,kind,payload,created_at) VALUES (?,?,?,?)', (t,kind,json.dumps(value),'2026-10-12T00:00:00Z')).lastrowid
        self.c.commit()
        return seq

    def card(self, comparison=None):
        return scorecard(self.root, list(self.ids.values()), comparison)

    def by_task(self, value, axis):
        names = {v:k for k, v in self.ids.items()}
        return {names[t['task']]:t for t in value['axes'][axis]['tasks']}

    def test_each_outcome_class_needs_positive_evidence(self):
        before = self.db.read_bytes(); value = self.card()
        self.assertEqual(before, self.db.read_bytes())
        rows = self.by_task(value, 'task_completion')
        # A2 (12/10): complete is now full_loop; a relay without the user's quote is unknown provenance.
        expected = {'autonomous':'autonomous_full_loop','intervened':'assisted_full_loop','entry_plan':'assisted_full_loop',
                    'runtime_changed':'assisted_full_loop','noted':'assisted_full_loop','entry_restart':'assisted_full_loop',
                    'escalated':'correct_block','silent_block':'incomplete','unclassified':'incomplete','answered':'incomplete',
                    'running':'incomplete','no_checkpoint':'unknown','untraced':'unknown','child_entry_start':'assisted_full_loop',
                    'skipped_device':'partial_complete','device_block':'correct_block','garbage_class':'incomplete','legacy_start':'unknown',
                    'entry_decided':'assisted_full_loop','relayed':'unknown','unattributed':'unknown'}
        self.assertEqual({k:v['outcome'] for k, v in rows.items()}, expected)
        self.assertEqual(rows['intervened']['outcome_reasons'], ['entry_intervention'])
        self.assertEqual(rows['entry_plan']['outcome_reasons'], ['entry_plan'])
        self.assertEqual(rows['runtime_changed']['outcome_reasons'], ['runtime_changed'])
        self.assertEqual(rows['noted']['outcome_reasons'], ['assistance_recorded'])
        self.assertEqual(rows['entry_restart']['outcome_reasons'], ['entry_restart'])
        self.assertEqual(rows['silent_block']['outcome_reasons'], ['no_pending_escalation'])
        self.assertEqual(rows['answered']['outcome_reasons'], ['no_pending_escalation'])
        self.assertEqual(rows['unclassified']['outcome_reasons'], ['no_classified_failure'])
        self.assertEqual(rows['untraced']['outcome_reasons'], ['runtime_trace_missing','intervention_trace_missing'])
        self.assertEqual(rows['child_entry_start']['outcome_reasons'], ['entry_child_start'])
        self.assertEqual(rows['garbage_class']['outcome_reasons'], ['no_classified_failure'])
        self.assertEqual(rows['legacy_start']['outcome_reasons'], ['start_initiator_missing'])
        self.assertEqual(rows['device_block']['pending_escalations'], {'device_assertion':1})
        self.assertEqual(rows['entry_decided']['outcome_reasons'], ['entry_undelegated_decision'])
        self.assertEqual(rows['relayed']['outcome_reasons'], ['decision_provenance_unknown'])
        self.assertEqual(rows['unattributed']['outcome_reasons'], ['decision_provenance_unknown'])
        self.assertEqual(value['axes']['task_completion']['outcomes'],
                         {'autonomous_full_loop':1,'assisted_full_loop':7,'plan_complete':0,'partial_complete':1,'tests_only':0,
                          'correct_block':2,'incomplete':5,'unknown':5})
        # A skipped optional stage is not run: never a device pass, whatever the node phase says, and the task is
        # partial (Codex review 2026-10-12) even though nobody helped: completion and assistance are separate levels.
        skip = rows['skipped_device']
        self.assertEqual((skip['completion_level'], skip['assistance_level']), ('partial', 'autonomous'))
        self.assertEqual((skip['not_run'], skip['gates']['device'], skip['criteria']['AC2']), (['device'], 'not_run', 'not_run'))
        self.assertIn('device', skip['missing_evidence'])
        done, block = rows['autonomous'], rows['escalated']
        self.assertEqual((done['technical_verified'], done['criteria'], done['not_run']), (True, {'AC1':'passed','AC2':'passed'}, []))
        self.assertEqual(done['gates']['apk_audit'], 'recorded_pass')
        self.assertEqual(block['criteria_counts'], {'pending':1,'blocked':1})
        self.assertEqual((block['not_run'], block['unresolved_nodes']), (['audit','build','done'], {'device':'blocked'}))
        self.assertEqual((block['failure_classes'], block['escalations'], block['pending_escalations'], block['automatic_recoveries'], block['pending_requests']),
                         ({'environment':1}, 2, {'environment':1}, 1, 1))
        self.assertIn('device', block['missing_evidence'])

    def test_entry_dependencies_separate_decisions_from_interventions(self):
        rows = self.by_task(self.card(), 'entry_dependencies')
        a = rows['autonomous']
        self.assertEqual(a['interventions'], {'codex':{'delivery submit':1},'user':{'request.reply':1}}); self.assertEqual(a['entry_interventions'], 0)
        zero = {'user':0,'relayed':0,'delegated':0,'undelegated':0,'observed':0,'unknown':0}
        self.assertEqual(a['decisions_by_source'], dict(zero, user=1))
        self.assertEqual(rows['entry_decided']['decisions_by_source'], dict(zero, undelegated=1))
        self.assertEqual(rows['relayed']['decisions_by_source'], dict(zero, unknown=1))  # no user reference
        # Legacy receipt: the sender comes from the reply's intervention record, the decider is unknown.
        self.assertEqual(rows['unattributed']['decisions_by_source'], dict(zero, unknown=1))
        self.assertEqual(a['intervention_roles'], {'entry':0,'decision':1,'handoff':1,'runtime':0})
        self.assertEqual((a['user_decisions_answered'], a['coordinator_restarts'], a['keeper_restart_events'], a['plan_provenance']),
                         (1, {'keeper':1,'reply':1}, 1, 'onecrew'))
        self.assertEqual((a['runtime_revisions'], a['runtime_changes'], a['assistance_notes']), (1, 0, {}))
        # A child-task intervention belongs to its parent's dependencies.
        self.assertEqual(rows['intervened']['interventions'], {'claude':{'task.resume':1},'codex':{'delivery submit':1},'user':{'request.reply':1}})
        self.assertEqual(rows['intervened']['entry_interventions'], 1)
        self.assertEqual(rows['entry_restart']['coordinator_restarts'], {'keeper':1,'reply':1,'claude':1})
        self.assertEqual((rows['entry_plan']['plan_provenance'], rows['runtime_changed']['runtime_changes']), ('entry', 1))
        self.assertEqual(rows['noted']['assistance_notes'], {'build':1})
        self.assertEqual((a['child_starts'], rows['child_entry_start']['child_starts']), ({}, {'onecrew':1,'unknown':1}))
        self.assertEqual(rows['legacy_start']['coordinator_restarts'], {'keeper':1,'reply':1,'unrecorded':1})
        u = rows['untraced']
        self.assertEqual((u['interventions'], u['entry_interventions'], u['runtime_revisions'], u['coordinator_restarts'], u['child_starts']), (None,)*5)

    def test_axes_stay_separate_and_replay_never_enters_task_axes(self):
        comparison = compare(run_value('assertion_failed'), run_value())
        with_replay, without = self.card(comparison), self.card()
        runtime = with_replay['axes']['runtime_tests']
        self.assertEqual((runtime['status'], runtime['by_change'], runtime['by_after_status']), ('recorded', {'recovered':1}, {'passed':1}))
        self.assertEqual(runtime['label'], 'known-case fixture replay; not task completion')
        for axis in ('task_completion','entry_dependencies'):
            self.assertEqual(with_replay['axes'][axis], without['axes'][axis])
            text = json.dumps(with_replay['axes'][axis])
            for leak in ('test_cases_passed','test_receipts','by_change','recovered','trials'):
                self.assertNotIn(leak, text)
        self.assertIsNone(with_replay['combined_score']); self.assertIsNone(with_replay['product_autonomy_rate'])
        self.assertEqual(set(with_replay['axes']), {'runtime_tests','task_completion','entry_dependencies'})

    def test_no_reason_report_acceptance_or_actor_text_is_exported(self):
        self.event(self.ids['autonomous'], 'control.intervention', {'actor':SECRET+' typed a long free-text note | with pipes and more','channel':'cli','command':'delivery resume'})
        value = self.card(compare(run_value(), run_value()))
        for text in (json.dumps(value), markdown(value)):
            self.assertNotIn(SECRET, text)
        self.assertEqual(self.by_task(value, 'entry_dependencies')['autonomous']['interventions']['other'], {'delivery resume':1})
        self.assertEqual(self.by_task(value, 'task_completion')['autonomous']['outcome'], 'assisted_full_loop')

    def test_missing_or_invalid_compare_and_cli_outputs(self):
        value = self.card()
        self.assertEqual(value['axes']['runtime_tests']['status'], 'not_provided')
        self.assertIn('Không có file so sánh replay', markdown(value))
        with self.assertRaises(LedgerError): self.card(run_value())
        out = Path(self.tmp.name)/'card'; args = ['--state-root',str(self.root),'eval','scorecard','--task',self.ids['autonomous'],'--task',self.ids['escalated']]
        def run(argv):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()): return main(argv)
        self.assertEqual(run(args+['--output',str(out),'--replay-compare',str(Path(self.tmp.name)/'missing.json')]), 2)
        self.assertFalse(out.exists() and any(out.iterdir()))
        tampered = Path(self.tmp.name)/'tampered.json'; sealed = seal(compare(run_value(), run_value())); sealed['trials'] = 9
        tampered.write_text(json.dumps(sealed)); self.assertEqual(run(args+['--output',str(out),'--replay-compare',str(tampered)]), 2)
        self.assertEqual(run(args+['--output',str(out)]), 0)
        card = read_result(out/'scorecard.json')
        self.assertEqual(card['axes']['runtime_tests']['status'], 'not_provided')
        self.assertEqual([t['outcome'] for t in card['axes']['task_completion']['tasks']], ['autonomous_full_loop','correct_block'])
        report = (out/'scorecard.md').read_text(encoding='utf-8')
        for heading in ('## Trục 1', '## Trục 2', '## Trục 3'): self.assertIn(heading, report)
        self.assertEqual(run(args+['--output',str(out)]), 2)  # never overwrites earlier evidence
        good = Path(self.tmp.name)/'compare.json'; good.write_text(json.dumps(seal(compare(run_value('capability_unavailable'), run_value()))))
        self.assertEqual(run(args+['--output',str(out/'with'),'--replay-compare',str(good)]), 0)
        self.assertEqual(read_result(out/'with/scorecard.json')['axes']['runtime_tests']['by_change'], {'capability_added':1})
        self.assertEqual(run(['eval','scorecard','--task',self.ids['autonomous'],'--output',str(out/'nostate')]), 2)


if __name__ == '__main__':
    unittest.main()
