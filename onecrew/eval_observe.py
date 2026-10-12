"""Conservative, read-only evaluation of recorded task evidence, never a dispatch."""
import collections
import json
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

from .delivery_recovery import GUIDANCE, POLICY
from .ledger import content_hash, utcnow

TASK = re.compile(r'TASK-[0-9a-f]{32}\Z')
GATES = ('tests', 'review', 'apply', 'build', 'apk_audit', 'device', 'handover', 'notification')
NODE_GATES = {'regression':'tests','review':'review','build':'build','apk_audit':'apk_audit','device':'device','handover':'handover','change':'apply'}
# The classes the recovery policy itself stores, so a new class never collapses into 'other'.
FAILURE_CLASSES = (set(POLICY) | set(GUIDANCE)) - {'unknown'}
IDENT = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,49}\Z')
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,63}\Z')
SIGNALS = ('runner.started','coordinator.restarted','control.intervention','request.answered')


def reference(row):
    return {'seq':row['seq'], 'task':row['task_id'], 'kind':row['kind'], 'at':row['created_at'],
            'payload_sha256':content_hash(json.loads(row['payload']))}


def assistance_note(ledger, task, key, actor, category, reason):
    """Append an attributed intervention, not an execution grant or task mutation."""
    from .ledger import key_field, text_field
    from .discovery import scan_text
    key_field(key); text_field(reason,'reason',800); scan_text(reason.encode())
    if actor not in ('codex','claude','human','other-entry') or category not in (
            'runtime','environment','product-code','tests','build','device','decision'):
        raise ValueError('Unsupported assistance actor/category.')
    with ledger.transaction(write=True) as conn:
        ledger._task(conn,task)
        value={'key':key,'actor':actor,'category':category,'reason':reason}
        old=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='eval.assistance' AND json_extract(payload,'$.key')=?",(task,key)).fetchone()
        if old:
            previous=json.loads(old['payload'])
            if any(previous.get(k)!=v for k,v in value.items()):raise ValueError('Assistance key already bound to different evidence.')
            return previous
        row=conn.execute("SELECT seq FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(task,)).fetchone()
        value['checkpoint']=row['seq'] if row else None
        value['source']='operator-recorded; not independently verified'
        ledger._event(conn,task,'eval.assistance',value)
        return value


def label(value):
    # Structured labels only; anything that could be free text is collapsed.
    return 'unknown' if value is None else value if isinstance(value,str) and LABEL.fullmatch(value) else 'other'


def failure_class(record):
    c = record.get('class') if isinstance(record,dict) else None
    return c if c in FAILURE_CLASSES else 'unclassified' if c in (None,'unknown') else 'other'


def delivery_metrics(delivery):
    """Parent fields as the runtime wrote them. A field it never wrote stays None."""
    names = ('parent_repairs','parent_repair_events','automatic_recoveries','failure_classes','escalations','plan_provenance')
    if not isinstance(delivery,dict) or not delivery: return dict.fromkeys(names)
    repairs, history, failures = delivery.get('repairs'), delivery.get('history'), delivery.get('failures')
    rows = list(failures.values()) if isinstance(failures,dict) else failures if isinstance(failures,list) else None
    planning = delivery.get('planning')
    mode = planning.get('mode') if isinstance(planning,dict) else None
    def count(key): return len(delivery[key]) if isinstance(delivery.get(key),list) else None
    return dict(zip(names,(
        repairs if type(repairs) is int else len(repairs) if isinstance(repairs,list) else None,
        sum(isinstance(h,dict) and ('repair' in h or 'clean_rebuild' in h) for h in history) if isinstance(history,list) else None,
        count('recoveries'), dict(collections.Counter(map(failure_class,rows))) if rows is not None else None, count('escalations'),
        # Before the planner existed every parent plan was entry-authored.
        'entry' if not planning else mode if mode in ('onecrew','entry') else None)))


def delivery_summary(state):
    """Node/criterion IDs and phases only; acceptance text and receipts stay private."""
    delivery = state.get('delivery')
    if not isinstance(delivery,dict) or not delivery: return None
    kinds = {n.get('id'):n.get('kind') for n in (state.get('plan') or {}).get('nodes', [])
             if isinstance(n,dict)} if isinstance(state.get('plan'),dict) else {}
    nodes = delivery.get('nodes') if isinstance(delivery.get('nodes'),dict) else {}
    criteria = delivery.get('criteria') if isinstance(delivery.get('criteria'),dict) else {}
    verified = delivery.get('technical_verified')
    return {'technical_verified':verified if type(verified) is bool else None,
            'criteria':{k:label(v) for k,v in criteria.items() if isinstance(k,str) and IDENT.fullmatch(k)},
            'nodes':{k:{'kind':label(kinds.get(k)),'phase':label(v.get('phase') if isinstance(v,dict) else None),
                        'skipped':isinstance(v,dict) and isinstance(v.get('receipt'),dict) and v['receipt'].get('skipped') is True}
                     for k,v in nodes.items() if isinstance(k,str) and IDENT.fullmatch(k)}}


def pending_questions(conn, task):
    """IDs/revisions of the questions desktop_notifications.questions groups into one episode."""
    rows = [{'id':r['id'],'revision':r['revision']} for r in conn.execute("SELECT id,revision FROM requests WHERE task_id=? AND state='pending'",(task,))]
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_questions'").fetchone():
        rows += [{'id':r['id'],'revision':r['revision']} for r in conn.execute("SELECT id,revision,payload FROM conversation_questions WHERE state='pending'")
                 if task in (json.loads(r['payload']).get('affected_tasks') or [])]
    return sorted(rows, key=lambda q:q['id'])


def signals(rows, root):
    """Runtime-recorded restarts, revisions, interventions and decisions; never reason text."""
    trees, starts, children, restarted, interventions, answered = set(), [], collections.Counter(), 0, [], 0
    for row in rows:
        v = json.loads(row['payload'])
        if not isinstance(v,dict): continue
        if row['kind'] == 'runner.started':
            tree = v['runtime'].get('tree') if isinstance(v.get('runtime'),dict) else None
            if isinstance(tree,str) and tree: trees.add(tree)
            # A runtime that predates launcher attribution is unrecorded, not an 'unknown' (entry) launcher.
            who = label(v.get('initiator')) if 'initiator' in v else 'unrecorded'
            if row['task_id'] == root: starts.append(who)
            else: children[who] += 1  # the coordinator starts its children as 'onecrew'
        elif row['kind'] == 'coordinator.restarted': restarted += 1  # written only by the keeper
        elif row['kind'] == 'control.intervention':
            interventions.append({k:label(v.get(k)) for k in ('actor','channel','command')})
        else: answered += 1
    # A runtime that records its tree also records restarts/interventions: only then is absence zero.
    # The first root start is the launch; later ones are restarts, attributed by recorded initiator.
    traced, restarts = bool(trees), collections.Counter(starts[1:])
    return {'runtime_revisions':len(trees) if traced else None,
            'coordinator_restarts':restarted if traced or restarted else None,
            'coordinator_restarts_by_initiator':dict(restarts) if traced or restarts else None,
            'child_starts_by_initiator':dict(children) if traced or children else None,
            'interventions':interventions if traced or interventions else None,
            'decisions_answered':answered}


def project_state(state):
    """Only structured receipts, never mine free-text model reports for success."""
    native = state.get('native_change') or {}
    tests = state.get('tests') or []
    gates = dict.fromkeys(GATES, 'unverified')
    if tests:
        bound = all((t.get('evidence') or {}).get('snapshot') == state.get('snapshot') and state.get('snapshot') for t in tests)
        gates['tests'] = ('recorded_pass' if bound and all(t.get('passed') is True for t in tests)
                          else 'recorded_failure' if any(t.get('passed') is False for t in tests) else 'unverified')
    if native.get('review_accepted') is True:
        gates['review'] = 'recorded_pass'
    if state.get('workspace_applied') is True:
        gates['apply'] = 'recorded_pass'
    build = native.get('apk_build') or {}
    if build.get('status') == 'passed' and (build.get('artifact') or {}).get('sha256'):
        gates['build'] = 'recorded_pass'
    if state.get('phase') == 'completed' and state.get('outputs'):
        gates['handover'] = 'recorded_report'
    delivery = state.get('delivery') or {}
    grouped = collections.defaultdict(list)
    test_counts = []
    for node in (state.get('plan') or {}).get('nodes', []) if isinstance(state.get('plan'),dict) else []:
        row = (delivery.get('nodes') or {}).get(node['id']) or {}
        receipt = row.get('receipt') or {}
        kind = NODE_GATES.get(node.get('kind'))
        if kind:
            source = (delivery.get('source') or {}).get('hash')
            # A skipped optional stage is written as phase 'passed'; it is still not run.
            good = bool(row.get('phase') == 'passed' and receipt.get('passed') is True and receipt.get('skipped') is not True and
                        source and receipt.get('source') == source)
            grouped[kind].append('pass' if good else 'skipped' if receipt.get('skipped') is True else 'missing')
            if kind == 'tests':
                counts = receipt.get('counts') or {}
                if good and all(type(counts.get(k)) is int and counts[k]>=0 for k in ('passed','failed','skipped')):
                    test_counts.append(counts)
    for kind, values in grouped.items():
        gates[kind] = 'recorded_pass' if set(values) == {'pass'} else 'unverified' if 'missing' in values else 'not_run'
    counted = bool(grouped['tests']) and len(test_counts)==len(grouped['tests'])
    return gates, {'test_receipts':len(tests),
                   'test_cases_passed':sum(c['passed'] for c in test_counts) if counted else None,
                   'test_cases_skipped':sum(c['skipped'] for c in test_counts) if counted else None,
                   'skip_coverage':'recorded' if counted else 'unknown', 'timeout_checkpoints':len(native.get('timeout_checkpoints') or []),
                   'worker_repair_rounds':native.get('repairs'), **delivery_metrics(delivery),
                   'build_variant':build.get('variant'), 'apk_sha256':(build.get('artifact') or {}).get('sha256')}


def observe(state_root, task_ids):
    if not task_ids or len(task_ids)>100 or len(set(task_ids)) != len(task_ids) or not all(TASK.fullmatch(t) for t in task_ids):
        raise ValueError('Provide 1..100 unique complete TASK IDs.')
    path = Path(state_root).resolve()/'ledger.sqlite3'
    conn = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    result = {'version':1, 'type':'task_observation', 'created_at':utcnow(),
              'ledger_identity':content_hash(str(path).casefold()), 'tasks':[],
              'product_autonomy_rate':None, 'unassisted_completion_verified':0,
              'limits':['Recorded evidence only; no tests/build/device rerun and no artifact revalidation.',
                        'Explicit task sample, not a random population; no causal before/after inference.',
                        'Unknown assistance is not zero. Missing/skipped test counts cannot imply full coverage.',
                        'Entry device/server evidence is assistance, not autonomous worker E2E.',
                        'No report text/credentials exported. Windows shown is not user attention.',
                        'Recovery/restart/intervention metrics exist only where the runtime recorded them; null is unknown, not zero.',
                        'No prospective held-out eval enrollment: unassisted rate remains null.']}
    try:
        conn.execute('BEGIN')
        result['ledger_max_seq'] = conn.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
        for task in task_ids:
            owner = conn.execute('SELECT project_id FROM tasks WHERE id=?',(task,)).fetchone()
            if not owner: raise ValueError('Task not found: '+task)
            members=[task]
            lineage=conn.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_children'").fetchone()
            if lineage:members += [r[0] for r in conn.execute('SELECT task_id FROM delivery_children WHERE root=? ORDER BY task_id',(task,))]
            marks=','.join('?' for _ in members)
            checkpoint = conn.execute("SELECT * FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(task,)).fetchone()
            state = json.loads(checkpoint['payload']) if checkpoint else {}
            gates,metrics = project_state(state)
            evidence = [reference(checkpoint)] if checkpoint else []
            # Any past explicit assistance is retained even if the latest state omits it.
            history = conn.execute(f"SELECT * FROM events WHERE task_id IN ({marks}) AND kind IN ('workflow.checkpoint','learning.outcome') ORDER BY seq",members).fetchall()
            assistance = set(); repairs = set(); phases = []
            for event in history:
                payload = json.loads(event['payload'])
                value = payload.get('assistance')
                if isinstance(value,str) and value not in ('unknown','none','unassisted'):
                    assistance.add(value if value in ('entry-runtime-repair','entry-environment-repair','entry-product-repair') else 'other-recorded-assistance')
                    evidence.append(reference(event))
                for key in ('entry_repairs','runtime_repairs'):
                    for repair in payload.get(key) or []: repairs.add(content_hash(repair))
                if event['task_id']==task and event['kind']=='workflow.checkpoint' and (not phases or phases[-1]['phase'] != payload.get('phase')):
                    phases.append({'seq':event['seq'],'phase':payload.get('phase')})
            entries = conn.execute(f"SELECT * FROM events WHERE task_id IN ({marks}) AND kind LIKE 'entry.%' ORDER BY seq",members).fetchall()
            notes = conn.execute(f"SELECT * FROM events WHERE task_id IN ({marks}) AND kind='eval.assistance' ORDER BY seq",members).fetchall()
            recorded=[]
            for note in notes:
                v=json.loads(note['payload'])
                recorded.append({'task':note['task_id'],'seq':note['seq'],'actor':v.get('actor'),'category':v.get('category'),'checkpoint':v.get('checkpoint')})
                assistance.add('operator-recorded-intervention');evidence.append(reference(note))
            execution_entries = [e for e in entries if any(x in e['kind'] for x in ('verification','e2e','physical','login'))]
            if execution_entries: assistance.add('entry-device-or-server-verification')
            if repairs: assistance.add('entry-runtime-repair')
            if execution_entries and gates['device'] in ('unverified','not_run'): gates['device']='entry_evidence_only'
            evidence += [reference(e) for e in execution_entries]
            outcome = conn.execute("SELECT * FROM events WHERE task_id=? AND kind='learning.outcome' ORDER BY seq DESC LIMIT 1",(task,)).fetchone()
            if outcome:
                payload = json.loads(outcome['payload']); evidence.append(reference(outcome))
                current = payload.get('snapshot') == state.get('snapshot') and payload.get('phase') == state.get('phase')
                metrics.update(managed_calls=payload.get('managed_calls') if current else None,
                               wall_seconds=(payload.get('timing') or {}).get('wall_seconds') if current else None,
                               outcome_current=current)
            else: metrics.update(managed_calls=None, wall_seconds=None, outcome_current=False)
            if len(members)>1:
                total=conn.execute(f'SELECT SUM(used_calls) FROM executions WHERE task_id IN ({marks})',members).fetchone()[0]
                metrics['managed_calls']=total
                metrics['calls_scope']='parent-and-children'
            metrics['entry_repairs'] = len(repairs)
            metrics.update(signals(conn.execute(f"SELECT task_id,kind,payload FROM events WHERE task_id IN ({marks}) AND kind IN ({','.join('?' for _ in SIGNALS)}) ORDER BY seq",members+list(SIGNALS)),task))
            # Same identity desktop_notifications.snapshots uses: pending questions (root, then
            # children in its query order) define a decision episode, else the current phase run.
            notice = None
            pending = pending_questions(conn,task)
            from .delivery_store import root_id
            if root_id(conn,task) == task:
                for child in conn.execute('SELECT task_id FROM delivery_children WHERE root=?',(task,)):
                    pending.extend(pending_questions(conn,child[0]))
            escalations = state['delivery'].get('escalations') if isinstance(state.get('delivery'),dict) else None
            asked = {q['id'] for q in pending}
            metrics['pending_escalations'] = (dict(collections.Counter(failure_class(e) for e in escalations if isinstance(e,dict) and e.get('request') in asked))
                                              if isinstance(escalations,list) else None)
            if checkpoint:
                identity = pending or {'phase':state.get('phase'),'first':phases[-1]['seq']}
                key = content_hash({'task':task,'outcome':identity})[:32]
                from .desktop_notifications import directory
                file = directory(SimpleNamespace(state_root=Path(state_root)))/(key+'.json')
                if file.is_file():
                    raw = file.read_bytes(); n = json.loads(raw)
                    # A decision notice is keyed by its questions, not by the phase at launch.
                    if n.get('id') == key and n.get('task') == task and (pending or n.get('phase') == state.get('phase')):
                        notice = {'id':key,'status':n.get('status'),'record_sha256':content_hash(n),'episode':'decision' if pending else 'outcome'}
                        if n.get('status') in ('shown','closed'): gates['notification']='recorded_shown'
            gaps = [k for k,v in gates.items() if v not in ('recorded_pass','recorded_report','recorded_shown')]
            result['tasks'].append({'task':task,'project_id':owner['project_id'], 'phase':state.get('phase','unknown'),
                                    'snapshot':state.get('snapshot'),'verification':state.get('verification') if isinstance(state.get('verification'),str) else 'unknown',
                                    'acceptance':state.get('acceptance') if isinstance(state.get('acceptance'),str) else 'unknown', 'gates':gates,'metrics':metrics,
                                    'assistance':'recorded' if assistance else 'unknown', 'assistance_kinds':sorted(assistance),
                                    'members':members,'recorded_interventions':recorded,
                                    'entry_events':dict(collections.Counter(e['kind'] for e in entries)),
                                    'pending_requests':pending, 'phase_episodes':phases, 'delivery':delivery_summary(state),
                                    'evidence':list({r['seq']:r for r in evidence}.values()),'windows':notice,'gaps':gaps,
                                    'required_next_evidence':gaps+([] if metrics['skip_coverage']=='recorded' else ['test_case_counts_and_skips'])+['prospective_intervention_trace']})
    finally:
        conn.close()
    result['counts'] = {'tasks':len(result['tasks']),
                        'recorded_completed':sum(t['phase']=='completed' for t in result['tasks']),
                        'with_recorded_assistance':sum(t['assistance']=='recorded' for t in result['tasks']),
                        'assistance_unknown':sum(t['assistance']=='unknown' for t in result['tasks'])}
    return result


def markdown(value):
    lines = ['# OneCrew: bằng chứng task thật', '',
             'Đây là đọc ledger, không chạy lại test hoặc xác minh artifact/thiết bị.',
             '**Tỷ lệ tự hoàn thành độc lập: chưa đo được.**', '',
             '| Task | Trạng thái | Calls | Hỗ trợ | Chưa có bằng chứng OneCrew tự làm |', '|---|---|---:|---|---|']
    for t in value['tasks']:
        lines.append(f"| {t['task']} | {t['phase']} | {t['metrics']['managed_calls']} | {', '.join(t['assistance_kinds']) or 'unknown'} | {', '.join(t['gaps']) or 'Cần nghiệm thu độc lập'} |")
    lines += ['', *['- '+s for s in value['limits']]]
    return '\n'.join(lines)+'\n'
