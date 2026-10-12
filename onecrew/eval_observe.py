"""Conservative, read-only evaluation of recorded task evidence, never a dispatch."""
import collections
import json
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

from .ledger import content_hash, utcnow

TASK = re.compile(r'TASK-[0-9a-f]{32}\Z')
GATES = ('tests', 'review', 'apply', 'build', 'device', 'handover', 'notification')


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


def project_state(state):
    """Only structured receipts, never mine free-text model reports for success."""
    native = state.get('native_change') or {}
    tests = state.get('tests') or []
    gates = dict.fromkeys(GATES, 'unverified')
    if tests:
        bound = all(t.get('evidence',{}).get('snapshot') == state.get('snapshot') and state.get('snapshot') for t in tests)
        gates['tests'] = ('recorded_pass' if bound and all(t.get('passed') is True for t in tests)
                          else 'recorded_failure' if any(t.get('passed') is False for t in tests) else 'unverified')
    if native.get('review_accepted') is True:
        gates['review'] = 'recorded_pass'
    if state.get('workspace_applied') is True:
        gates['apply'] = 'recorded_pass'
    build = native.get('apk_build') or {}
    if build.get('status') == 'passed' and build.get('artifact',{}).get('sha256'):
        gates['build'] = 'recorded_pass'
    if state.get('phase') == 'completed' and state.get('outputs'):
        gates['handover'] = 'recorded_report'
    delivery = state.get('delivery') or {}
    grouped = collections.defaultdict(list)
    test_counts = []
    for node in (state.get('plan') or {}).get('nodes', []) if isinstance(state.get('plan'),dict) else []:
        row = delivery.get('nodes',{}).get(node['id'],{})
        receipt = row.get('receipt') or {}
        kind = {'regression':'tests','review':'review','build':'build','device':'device','handover':'handover','change':'apply'}.get(node.get('kind'))
        if kind:
            source = delivery.get('source',{}).get('hash')
            good = bool(row.get('phase') == 'passed' and receipt.get('passed') is True and
                        source and receipt.get('source') == source)
            grouped[kind].append(good)
            if kind == 'tests':
                counts = receipt.get('counts',{})
                if good and all(type(counts.get(k)) is int and counts[k]>=0 for k in ('passed','failed','skipped')):
                    test_counts.append(counts)
    for kind, values in grouped.items():
        gates[kind] = 'recorded_pass' if all(values) else 'unverified'
    counted = bool(grouped['tests']) and len(test_counts)==len(grouped['tests'])
    return gates, {'test_receipts':len(tests),
                   'test_cases_passed':sum(c['passed'] for c in test_counts) if counted else None,
                   'test_cases_skipped':sum(c['skipped'] for c in test_counts) if counted else None,
                   'skip_coverage':'recorded' if counted else 'unknown', 'timeout_checkpoints':len(native.get('timeout_checkpoints') or []),
                   'worker_repair_rounds':native.get('repairs'), 'parent_repairs':len(delivery.get('repairs') or []),
                   'build_variant':build.get('variant'), 'apk_sha256':build.get('artifact',{}).get('sha256')}


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
            if execution_entries and gates['device']=='unverified': gates['device']='entry_evidence_only'
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
            # Match the current outcome identity, not an earlier shown blocker notice.
            notice = None
            pending = conn.execute("SELECT id,revision FROM requests WHERE task_id=? AND state='pending' ORDER BY id",(task,)).fetchall()
            if checkpoint and not pending:
                first = phases[-1]['seq']
                key = content_hash({'task':task,'outcome':{'phase':state.get('phase'),'first':first}})[:32]
                from .desktop_notifications import directory
                file = directory(SimpleNamespace(state_root=Path(state_root)))/(key+'.json')
                if file.is_file():
                    raw = file.read_bytes(); n = json.loads(raw)
                    if n.get('id') == key and n.get('task') == task and n.get('phase') == state.get('phase'):
                        notice = {'id':key,'status':n.get('status'),'record_sha256':content_hash(n)}
                        if n.get('status') in ('shown','closed'): gates['notification']='recorded_shown'
            gaps = [k for k,v in gates.items() if v not in ('recorded_pass','recorded_report','recorded_shown')]
            result['tasks'].append({'task':task,'project_id':owner['project_id'], 'phase':state.get('phase','unknown'),
                                    'snapshot':state.get('snapshot'),'verification':state.get('verification') if isinstance(state.get('verification'),str) else 'unknown',
                                    'acceptance':state.get('acceptance') if isinstance(state.get('acceptance'),str) else 'unknown', 'gates':gates,'metrics':metrics,
                                    'assistance':'recorded' if assistance else 'unknown', 'assistance_kinds':sorted(assistance),
                                    'members':members,'recorded_interventions':recorded,
                                    'entry_events':dict(collections.Counter(e['kind'] for e in entries)),
                                    'pending_requests':[dict(r) for r in pending], 'phase_episodes':phases,
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
