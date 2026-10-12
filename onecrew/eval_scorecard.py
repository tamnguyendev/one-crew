"""Three separate scorecard axes over recorded evidence. Never one merged number or a dispatch."""
import collections
import re

from .eval_observe import label, observe
from .ledger import LedgerError, content_hash, utcnow

REPLAY = 'known-case fixture replay; not task completion'
CHANGES = {'regressed', 'capability_added', 'recovered', 'inconclusive', 'unchanged'}
# Relaying a user's answer is a legitimate decision and submitting/starting is the handoff itself;
# OneCrew's own processes are not the entry. Every other mutating command is entry assistance.
DECISIONS = {'reply', 'answer', 'defer'}
HANDOFF = {'submit', 'start'}
RUNTIME = {'onecrew', 'keeper'}
# Runner starts by these initiators are OneCrew's own continuation: keeper/reply restart the root and the
# root coordinator starts its children as 'onecrew'. Any other launcher, 'unknown' included, is the entry.
CONTINUATION = {'keeper', 'reply', 'onecrew'}
UNRECORDED = 'unrecorded'
ROLES = ('entry', 'decision', 'handoff', 'runtime')
OUTCOMES = ('autonomous_complete', 'assisted_complete', 'partial_complete', 'correct_block', 'incomplete', 'unknown')
COMPLETION_LEVELS = ('complete', 'partial', 'blocked', 'incomplete', 'unknown')
ASSISTANCE_LEVELS = ('autonomous', 'assisted', 'unknown')
LIMITS = ['Axes are separate: no combined score, rate or ranking is derived from them.',
          'Axis 1 replays known historical fixtures; it never counts toward task completion.',
          'Axes 2-3 read recorded ledger state only; no unit test or replay count enters them.',
          'Unknown provenance, runtime trace or intervention trace is never treated as autonomous.',
          'Completion level and assistance level are judged separately; only complete+autonomous is autonomous_complete.',
          'A completed phase with partial verification, criteria not passed or skipped nodes is partial, never complete.',
          'Answered user decisions and the initial submit/start handoff are reported separately from entry interventions.',
          'No reasons, prompts, reports or private values are exported.']


def role(intervention):
    words = set(re.split(r'[^a-z]+', intervention['command'].lower()))
    return ('runtime' if intervention['actor'] in RUNTIME else 'decision' if words & DECISIONS
            else 'handoff' if words & HANDOFF else 'entry')


def classified(counts):
    return any(k not in ('unclassified', 'other') for k in counts or {})


def runtime_axis(comparison):
    if comparison is None:
        return {'status':'not_provided', 'label':REPLAY}
    from .evaluation import STATUSES
    rows = comparison.get('rows')
    if (comparison.get('type') != 'runtime_comparison' or not isinstance(rows, list) or not rows or
            any(not isinstance(r, dict) or r.get('change') not in CHANGES or r.get('after') not in STATUSES for r in rows)):
        raise LedgerError('Replay comparison must be an eval compare result.')
    return {'status':'recorded', 'label':REPLAY, 'comparison_sha256':content_hash(comparison),
            'before_run':comparison.get('before_run'), 'after_run':comparison.get('after_run'),
            'corpus_hash':comparison.get('corpus_hash'), 'historical':comparison.get('historical'), 'trials':len(rows),
            'by_change':dict(collections.Counter(r['change'] for r in rows)),
            'by_after_status':dict(collections.Counter(r['after'] for r in rows))}


def assistance_level(t):
    """Who carried the work, from positive evidence only; independent of how far the work got."""
    m = t['metrics']
    entry = [i for i in m['interventions'] or [] if role(i) == 'entry']
    restarts, children = (set(m[k] or ()) for k in ('coordinator_restarts_by_initiator', 'child_starts_by_initiator'))
    assisted = [code for code, hit in (('entry_intervention', bool(entry)), ('entry_restart', bool(restarts-CONTINUATION-{UNRECORDED})),
                ('entry_child_start', bool(children-CONTINUATION-{UNRECORDED})), ('entry_plan', m['plan_provenance'] == 'entry'),
                ('runtime_changed', (m['runtime_revisions'] or 0) > 1), ('assistance_recorded', t['assistance'] == 'recorded')) if hit]
    if assisted: return 'assisted', assisted
    missing = [code for code, hit in (('plan_provenance_unknown', m['plan_provenance'] != 'onecrew'),
               ('runtime_trace_missing', m['runtime_revisions'] is None),
               ('intervention_trace_missing', m['interventions'] is None),
               ('start_initiator_missing', UNRECORDED in restarts | children)) if hit]
    return ('unknown', missing) if missing else ('autonomous', [])


def completion_level(t):
    """How much of the declared work is verified, independent of who helped."""
    m, phase, d = t['metrics'], t['phase'], t.get('delivery')
    if phase == 'completed':
        gaps = [] if t.get('verification') == 'passed' else ['verification_'+str(t.get('verification'))]
        if isinstance(d, dict):
            criteria, nodes = d.get('criteria') or {}, d.get('nodes') or {}
            gaps += [code for code, hit in (('technical_not_verified', d.get('technical_verified') is not True),
                     ('criteria_not_run', any(v == 'not_run' for v in criteria.values())),
                     ('criteria_not_passed', any(v not in ('passed', 'not_run') for v in criteria.values())),
                     ('nodes_skipped', any(v.get('skipped') for v in nodes.values())),
                     ('nodes_not_passed', any(v.get('phase') != 'passed' for v in nodes.values()))) if hit]
        return ('partial', gaps) if gaps else ('complete', [])
    if phase in ('blocked', 'waiting'):
        if not m['pending_escalations']: return 'incomplete', ['no_pending_escalation']
        if not (classified(m['pending_escalations']) and classified(m['failure_classes'])): return 'incomplete', ['no_classified_failure']
        return 'blocked', []
    return ('unknown', ['no_checkpoint']) if phase == 'unknown' else ('incomplete', [])


def outcome(t):
    """Class plus reason codes; both levels stay visible in completion()."""
    level, gaps = completion_level(t)
    helped, reasons = assistance_level(t)
    if level == 'complete':
        if helped == 'autonomous': return 'autonomous_complete', []
        return ('assisted_complete', reasons) if helped == 'assisted' else ('unknown', reasons)
    if level == 'partial': return 'partial_complete', gaps
    if level == 'blocked': return 'correct_block', []
    return level, gaps


def completion(t):
    d = t['delivery'] or {}
    nodes, criteria, m = d.get('nodes') or {}, d.get('criteria') or {}, t['metrics']
    kind, reasons = outcome(t)
    return {'task':t['task'], 'phase':t['phase'], 'technical_verified':d.get('technical_verified'),
            'criteria':criteria, 'criteria_counts':dict(collections.Counter(criteria.values())), 'gates':t['gates'],
            'missing_evidence':t['gaps'], 'not_run':sorted(k for k, v in nodes.items() if v['phase'] == 'pending' or v.get('skipped')),
            'unresolved_nodes':{k:v['phase'] for k, v in sorted(nodes.items()) if v['phase'] not in ('passed', 'pending')},
            'pending_requests':len(t['pending_requests']), 'automatic_recoveries':m['automatic_recoveries'],
            'failure_classes':m['failure_classes'], 'escalations':m['escalations'], 'pending_escalations':m['pending_escalations'],
            'completion_level':completion_level(t)[0], 'completion_gaps':completion_level(t)[1],
            'assistance_level':assistance_level(t)[0], 'assistance_reasons':assistance_level(t)[1],
            'outcome':kind, 'outcome_reasons':reasons}


def dependencies(t):
    m = t['metrics']
    grouped = None
    if m['interventions'] is not None:
        grouped = collections.defaultdict(collections.Counter)
        for i in m['interventions']: grouped[i['actor']][i['command']] += 1
        grouped = {k:dict(v) for k, v in sorted(grouped.items())}
    revisions = m['runtime_revisions']
    roles = None if m['interventions'] is None else {k:sum(role(i) == k for i in m['interventions']) for k in ROLES}
    return {'task':t['task'], 'interventions':grouped, 'intervention_roles':roles,
            'entry_interventions':None if roles is None else roles['entry'],
            'assistance_notes':dict(collections.Counter(label(r['category']) for r in t['recorded_interventions'])),
            'assistance':t['assistance'], 'assistance_kinds':t['assistance_kinds'], 'plan_provenance':m['plan_provenance'],
            'runtime_revisions':revisions, 'runtime_changes':None if revisions is None else max(0, revisions-1),
            'coordinator_restarts':m['coordinator_restarts_by_initiator'], 'keeper_restart_events':m['coordinator_restarts'],
            'child_starts':m['child_starts_by_initiator'],
            'user_decisions_answered':m['decisions_answered']}


def scorecard(state_root, task_ids, comparison=None):
    runtime = runtime_axis(comparison)
    observed = observe(state_root, task_ids)
    completed = [completion(t) for t in observed['tasks']]
    return {'version':1, 'type':'task_scorecard', 'created_at':utcnow(), 'ledger_identity':observed['ledger_identity'],
            'ledger_max_seq':observed['ledger_max_seq'], 'tasks':list(task_ids), 'combined_score':None, 'product_autonomy_rate':None,
            'axes':{'runtime_tests':runtime,
                    'task_completion':{'label':'recorded task state; nothing rerun', 'tasks':completed,
                                       'outcomes':{k:sum(c['outcome'] == k for c in completed) for k in OUTCOMES},
                                       'completion_levels':{k:sum(c['completion_level'] == k for c in completed) for k in COMPLETION_LEVELS},
                                       'assistance_levels':{k:sum(c['assistance_level'] == k for c in completed) for k in ASSISTANCE_LEVELS}},
                    'entry_dependencies':{'label':'recorded entry/runtime dependencies; decisions counted separately',
                                          'tasks':[dependencies(t) for t in observed['tasks']]}},
            'limits':LIMITS}


def cell(value):
    if isinstance(value, dict): return ', '.join(f'{k} ({cell(v)})' if isinstance(v, dict) else f'{k}: {cell(v)}' for k, v in value.items()) or '-'
    if isinstance(value, list): return ', '.join(map(str, value)) or '-'
    return '-' if value is None else str(value)


def markdown(value):
    axes = value['axes']; runtime = axes['runtime_tests']
    lines = ['# OneCrew scorecard: ba trục riêng', '', 'Ba trục chấm độc lập; không gộp thành một điểm hay tỷ lệ.', '',
             '## Trục 1 — Runtime tests', '', f"*{runtime['label']}*", '']
    if runtime['status'] == 'not_provided':
        lines.append('Không có file so sánh replay (`--replay-compare`).')
    else:
        lines += [f"Replay {runtime['before_run']} → {runtime['after_run']}, {runtime['trials']} case-trials.", '',
                  '| Phân loại thay đổi | Số |', '|---|---:|', *[f'| {k} | {v} |' for k, v in sorted(runtime['by_change'].items())], '',
                  '| Trạng thái sau | Số |', '|---|---:|', *[f'| {k} | {v} |' for k, v in sorted(runtime['by_after_status'].items())]]
    lines += ['', '## Trục 2 — Hoàn thành task', '',
              '| Task | Phase | Technical verified | Tiêu chí | Chưa chạy | Thiếu bằng chứng | Mức hoàn thành | Mức hỗ trợ | Kết quả |',
              '|---|---|---|---|---|---|---|---|---|']
    for t in axes['task_completion']['tasks']:
        level = t['completion_level']+(' ('+', '.join(t['completion_gaps'])+')' if t['completion_gaps'] else '')
        helped = t['assistance_level']+(' ('+', '.join(t['assistance_reasons'])+')' if t['assistance_reasons'] else '')
        lines.append(f"| {t['task']} | {t['phase']} | {cell(t['technical_verified'])} | {cell(t['criteria_counts'])} | "
                     f"{cell(t['not_run'])} | {cell(t['missing_evidence'])} | {level} | {helped} | {t['outcome']} |")
    lines += ['', '## Trục 3 — Phụ thuộc entry', '',
              '| Task | Can thiệp (actor/lệnh) | Can thiệp entry | Ghi chú hỗ trợ | Plan | Runtime (bản) | Restart coordinator | Khởi động task con | Quyết định người dùng |',
              '|---|---|---:|---|---|---:|---|---|---:|']
    for t in axes['entry_dependencies']['tasks']:
        lines.append(f"| {t['task']} | {cell(t['interventions'])} | {cell(t['entry_interventions'])} | {cell(t['assistance_notes'])} | "
                     f"{cell(t['plan_provenance'])} | {cell(t['runtime_revisions'])} | {cell(t['coordinator_restarts'])} | {cell(t['child_starts'])} | "
                     f"{t['user_decisions_answered']} |")
    lines += ['', *['- '+s for s in value['limits']]]
    return '\n'.join(lines)+'\n'
