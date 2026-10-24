"""Pure v1 evidence classification, shared by checkout evaluation and the installed workflow CLI."""

import collections

import json

import re



LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,63}\Z')

def label(value):
    # Structured labels only; anything that could be free text is collapsed.
    return 'unknown' if value is None else value if isinstance(value,str) and LABEL.fullmatch(value) else 'other'

ENTRY_ACTORS = ('claude', 'codex', 'other-entry')

DECISION_SOURCES = ('user', 'relayed', 'entry', 'unknown')

def decision_source(receipt, sender=None):
    """Who decided one recorded answer: the user directly, the user relayed by an entry, or the entry itself.

    'by' is the attributed sender (legacy receipts fall back to the reply's intervention record) and
    'decided_by' the declared decider. Anything not positively attributable stays 'unknown'."""
    provenance = receipt.get('provenance') if isinstance(receipt, dict) and isinstance(receipt.get('provenance'), dict) else {}
    by, decided = provenance.get('by') or sender, provenance.get('decided_by')
    if decided == 'entry': return 'entry'
    if by == 'user': return 'user'
    if decided == 'user' and by in ENTRY_ACTORS: return 'relayed'
    return 'unknown'

def signals(rows, root):
    """Runtime-recorded restarts, revisions, interventions and decisions; never reason text."""
    trees, starts, children, restarted, interventions, answered = set(), [], collections.Counter(), 0, [], 0
    replies, senders = [], {}
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
            if isinstance(v.get('key'), str): senders[v['key']] = label(v.get('actor'))  # a reply's note is keyed by its receipt
        else: answered += 1; replies.append(v)
    # A runtime that records its tree also records restarts/interventions: only then is absence zero.
    # The first root start is the launch; later ones are restarts, attributed by recorded initiator.
    traced, restarts = bool(trees), collections.Counter(starts[1:])
    return {'runtime_revisions':len(trees) if traced else None,
            'coordinator_restarts':restarted if traced or restarted else None,
            'coordinator_restarts_by_initiator':dict(restarts) if traced or restarts else None,
            'child_starts_by_initiator':dict(children) if traced or children else None,
            'interventions':interventions if traced or interventions else None,
            'decisions_answered':answered,
            'decisions_by_source':{k:sum(decision_source(r, senders.get(r.get('id'))) == k for r in replies) for k in DECISION_SOURCES}}

DECISIONS = {'reply', 'answer', 'defer'}

HANDOFF = {'submit', 'start'}

RUNTIME = {'onecrew', 'keeper'}

CONTINUATION = {'keeper', 'reply', 'onecrew'}

UNRECORDED = 'unrecorded'

def role(intervention):
    words = set(re.split(r'[^a-z]+', intervention['command'].lower()))
    return ('runtime' if intervention['actor'] in RUNTIME else 'decision' if words & DECISIONS
            else 'handoff' if words & HANDOFF else 'entry')

def classified(counts):
    return any(k not in ('unclassified', 'other') for k in counts or {})

def decisions(m):
    """Answered decisions by source. A count without per-answer provenance is all 'unknown'."""
    by = m.get('decisions_by_source')
    if isinstance(by, dict) and sum(by.values()) == (m.get('decisions_answered') or 0): return by
    return {'user': 0, 'relayed': 0, 'entry': 0, 'unknown': m.get('decisions_answered') or 0}

def assistance_level(t):
    """Who carried the work, from positive evidence only; independent of how far the work got.

    The user's own decision is not assistance. An entry deciding under delegation, or carrying the user's
    answer for them, is; an answer whose decider or sender cannot be shown keeps the level unknown."""
    m = t['metrics']
    entry = [i for i in m['interventions'] or [] if role(i) == 'entry']
    restarts, children = (set(m[k] or ()) for k in ('coordinator_restarts_by_initiator', 'child_starts_by_initiator'))
    decided = decisions(m)
    assisted = [code for code, hit in (('entry_intervention', bool(entry)), ('entry_restart', bool(restarts-CONTINUATION-{UNRECORDED})),
                ('entry_child_start', bool(children-CONTINUATION-{UNRECORDED})), ('entry_plan', m['plan_provenance'] == 'entry'),
                ('entry_decision', decided['entry'] > 0), ('entry_relayed_decision', decided['relayed'] > 0),
                ('runtime_changed', (m['runtime_revisions'] or 0) > 1), ('assistance_recorded', t['assistance'] == 'recorded')) if hit]
    if assisted: return 'assisted', assisted
    missing = [code for code, hit in (('plan_provenance_unknown', m['plan_provenance'] != 'onecrew'),
               ('runtime_trace_missing', m['runtime_revisions'] is None),
               ('intervention_trace_missing', m['interventions'] is None),
               ('start_initiator_missing', UNRECORDED in restarts | children),
               ('decision_provenance_unknown', decided['unknown'] > 0)) if hit]
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
