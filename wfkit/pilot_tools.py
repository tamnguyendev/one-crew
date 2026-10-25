"""Local tools that close the LOCAL part of pilot tasks W38b, W38c, W38d (no pilot, provider or owner decision is involved).

Run ``python -m wfkit.pilot_tools <command> ...``:

* ``report``      -- W38b/W38c interim (T35b) pilot-report GENERATOR. Reads a pilot ledger READ-ONLY (``onecrew.v2.metrics.measure_all``
  for the figures, ``onecrew.v2.outcome.outcomes`` for the outcome rows) and a manifest naming the three pilot jobs, and writes
  ``interim-report.json`` + ``interim-report.md`` that ``wfkit.pilot_report.check_report`` accepts. Deterministic (no clock, no
  random). Whatever has no source stays ``không có dữ liệu`` (never 0); group B comes only from the owner's notes, group C only from
  the chat log, both given in the manifest as ``observations``. Provenance (state root, commit, wheel sha, fixture|real) is written
  into both files; the report never claims acceptance and never claims pilot evidence.
  ``report --kind aggregate`` -- W38c (T35c, PL-B, ten jobs): the same pipeline (measure_all, outcome rows, the interim cell mapping for
  group B/C, check_report) over one or more pilot ledgers named in the manifest, plus the PL-B sections read from the ledgers by code:
  owner decisions by kind (root approval, acceptance, U1-U4 from the request's class, other), SKIP records (HD-20 decision records of
  review_policy) and the findings recorded as missed by them (findings.link_skip records, read back through findings.skip_view), provider calls/failures (verdict events with a provider error), hook noise and
  wrong-scope blocks, notices with nothing for the owner to do, owner waits missed for more than 60 minutes. A job skipped with a
  reason stays in the denominator (every cell "không có dữ liệu"). Every figure lists the job/ledger/root it was computed from; every
  plan root of a pilot ledger is a job or excluded with a reason. Writes ``aggregate-report.json`` + ``aggregate-report.md``.
* ``verify``     -- regenerates a report from the same manifest and ledgers and refuses unless the files are byte-identical (a
  figure edited after generation) and check_report passes.
* ``rerun-check``-- W38d (T45e, E23-E26) checker of the re-run plan "not the whole pilot": from the A->B analysis it computes which
  pilot jobs are affected (``onecrew.dependency_core.affected_tasks`` over the pinned dependency map; a changed file outside the
  map affects every item, E21) and refuses a plan that re-runs everything, skips an affected job, re-runs an unaffected one, lacks
  the analysis, keeps evidence under another hash or leaves an affected item without a supplementary check.
* ``supp-run``   -- W38d tool that RUNS the supplementary checks named for the affected items on the FINAL artifact and writes one
  receipt per check in the ``wfkit.finalgate`` receipt shape (read back through ``Evidence.read``). It first verifies the wheel file
  hash against the artifact AND against the receipt it is given, and refuses before running anything when they differ.

Manifest for ``report`` (schema 1): ``kind`` "interim"; ``fixture`` bool; ``provenance`` {state_root, commit, wheel_sha256};
``jobs`` [{id, root}] (three); ``chat_log`` {job: {decision, intervention, outcome}} (the chat side of the E26 comparison; required);
``observations`` {metric id (group B/C): {job: number}}; ``amend_causes`` is not supported (a cause stays unknown);
``desktop_window`` {event_id, emitted_at, shown_at, delivery_status}.

Manifest for ``report --kind aggregate`` (schema 1): ``kind`` "aggregate"; ``synthetic`` bool (true whenever any ledger is synthetic);
``ledgers`` [{id, project, state_root, commit, wheel_sha256, [wheel], synthetic}] (``wheel`` = a path whose sha256 must equal
wheel_sha256); ``jobs`` ten rows, each {id, ledger, root, type (code|docs|data|ops), final_outcome, [wheel_sha256]} or {id, skipped:
reason}; ``excluded`` [{ledger, root, reason}] (other plan roots of a pilot ledger); ``chat_log`` {job: {decision}} (the chat side of
E24, every job that ran); ``observations`` as interim; ``decision_log`` [{at, job, before, after, reason}] (the coordinator's manual
ledger fixes; absent = no data); ``continuation_trial`` {job, tool, package_sha256, [package], answers: [{question, correct}],
grader {identity, model}, coordinator_model} (the result is computed, never taken). Missing sources are reported, never invented.

Rerun analysis (schema 1): ``source`` / ``target`` {commit, wheel_sha256}; ``changed_files``; ``items`` [{id, owned, depends_on}]; ``jobs``
[{id, items}] (the pilot jobs and the dependency-map items each exercised); ``evidence`` [{job, wheel_sha256}] (what the plan keeps);
``plan`` {rerun_jobs, supplements: {item: [check ids]}}. Everything here is read-only except the files named by --out-dir.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wfkit import pilot_report as pr
from wfkit.finalgate import Evidence, identity, require

UNKNOWN = 'unknown'
NO_SOURCE = 'chưa có nguồn trong sổ'
NO_CHAT = 'thiếu nhật ký chat'
UNIT = {'time_to_usable': 'phút', 'exec_time': 'phút', 'wait_time': 'phút', 'owner_minutes': 'phút', 'verify_cost': 'phút'}
SOURCE = {'A': 'sổ pilot', 'B': 'ghi chép của chủ sở hữu', 'C': 'nhật ký chat'}
ENDS = ('accepted', 'stopped_with_report', 'failed')
COLUMNS = ('decision', 'intervention', 'outcome')


class ReportError(ValueError):
    """The generator cannot produce an honest report from what it was given."""


def need(ok, message):
    if not ok:
        raise ReportError(message)


def clean(value):
    if isinstance(value, float):
        value = round(value, 2)
        return int(value) if value == int(value) else value
    return value


def sha_of(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


# ---- W38b / W38c: interim report generator ----------------------------------------------------------------------------

def facts_of(ledger, name):
    """What measure_all does not carry, taken from the root's own events: verdicts, interventions, open findings."""
    from onecrew.v2 import namespaces, plan as plans
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        rows = conn.execute('SELECT kind, payload FROM events WHERE task_id=?', (state['task_id'],)).fetchall()
        capability = namespaces.has_capability(state, 'finding-register')
    verdicts = {'pass': 0, 'fail': 0}
    interventions = 0
    for row in rows:
        if row['kind'] == 'control.intervention':
            interventions += 1
        elif row['kind'] == 'verdict.recorded':
            verdicts['pass' if json.loads(row['payload']).get('result') == 'pass' else 'fail'] += 1
    open_findings = UNKNOWN
    if capability:
        from onecrew.v2.findings import list_findings
        open_findings = len(list_findings(ledger, name, task_id=state['task_id'], open_only=True))
    return {'verdicts': verdicts, 'interventions': interventions, 'open_findings': open_findings}


def validate_manifest(m):
    need(isinstance(m, dict) and m.get('schema') == 1, 'manifest: schema must be 1')
    need(m.get('kind') == 'interim', 'manifest: only kind "interim" (T35b) is generated by generate_interim; kind aggregate (T35c) is '
                                     'generate_aggregate (report --kind aggregate)')
    need(type(m.get('fixture')) is bool, 'manifest: fixture must be declared (true|false)')
    prov = m.get('provenance')
    need(isinstance(prov, dict) and isinstance(prov.get('state_root'), str) and prov['state_root']
         and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', str(prov.get('commit'))) and re.fullmatch(r'[0-9a-f]{64}', str(prov.get('wheel_sha256'))),
         'manifest: provenance needs state_root, commit and wheel_sha256')
    jobs = m.get('jobs')
    need(isinstance(jobs, list) and len(jobs) == 3 and all(isinstance(j, dict) and j.get('id') and j.get('root') for j in jobs)
         and len({j['id'] for j in jobs}) == 3 and len({j['root'] for j in jobs}) == 3, 'manifest: jobs must be three distinct {id, root}')
    ids = [j['id'] for j in jobs]
    chat = m.get('chat_log')
    need(isinstance(chat, dict) and set(chat) == set(ids) and all(isinstance(chat[j], dict) and set(chat[j]) == set(COLUMNS)
         and all(isinstance(chat[j][c], int) and not isinstance(chat[j][c], bool) and chat[j][c] >= 0 for c in COLUMNS) for j in ids),
         'manifest: chat_log needs decision, intervention, outcome counts for each job (the E26 comparison is not hand-filled)')
    obs = m.get('observations', {})
    need(isinstance(obs, dict), 'manifest: observations must be an object')
    for mid, cells in obs.items():
        need(pr.CATALOG.get(mid) in ('B', 'C'), f'manifest: observations may only supply group B/C metrics, not {mid}')
        need(isinstance(cells, dict) and set(cells) <= set(ids) and all(pr.number(v) and v >= 0 for v in cells.values()),
             f'manifest: observations for {mid} must map jobs to non-negative numbers')
    d = m.get('desktop_window')
    need(isinstance(d, dict) and all(isinstance(d.get(k), str) and d[k] for k in ('event_id', 'emitted_at', 'shown_at', 'delivery_status')),
         'manifest: desktop_window record is required')
    return jobs, chat, obs


def cell_a(root, mid, facts):
    t, rework, cost = root['time_to_output'], root['rework'], root['check_cost']
    pick = {'time_to_usable': t['wall_minutes'], 'exec_time': t['excluding_owner_wait_minutes'],
            'wait_time': root['waits']['owner']['minutes'], 'owner_decisions': root['owner_decisions']['total'],
            'rework_rounds': rework['repair_rounds']}
    if mid in pick:
        value = pick[mid]
        return {'value': clean(value)} if pr.number(value) else {'no_data': 'chưa đủ mốc trong sổ để tính'}
    if mid == 'verify_cost':
        if cost['runs'] and not cost['unknown_runs']:
            return {'value': clean(cost['seconds'] / 60)}
        return {'no_data': 'biên nhận kiểm không đủ thời gian' if cost['runs'] else 'chưa có lần kiểm nào'}
    return {'no_data': NO_SOURCE}


def cell_for(root, job, mid, obs, facts):
    group = pr.CATALOG[mid]
    if group == 'A':
        return cell_a(root, mid, facts)
    given = obs.get(mid, {}).get(job)
    if given is not None:
        return {'value': clean(given)}
    if group == 'B':
        return {'no_data': pr.NO_NOTES}
    if mid.startswith('amend_') and root['rework']['amends'] == 0:
        return {'value': 0}                                    # no amend happened in the ledger: no cause to classify
    if mid.startswith('amend_'):
        return {'no_data': 'nguyên nhân amend không có trong sổ'}
    if mid == 'ledger_manual_fixes':
        return {'no_data': NO_SOURCE}
    return {'no_data': NO_CHAT}


def finish(metric, n, kind='interim'):
    k = len(pr.values(metric))
    metric.update(k=k, n=n, status=pr.status_for(k, n), label=pr.label_for(k, n, kind))
    if k:
        metric['summary'] = {'value': clean(sum(pr.values(metric).values())), 'unit': UNIT.get(metric['id'], 'lần')}
    else:
        metric['summary'] = {'no_data': next(iter(metric['cells'].values()))['no_data']}


def build_interim(roots, facts, outcomes, manifest, jobs, chat, obs):
    """Pure: the report dict from measured roots. roots/facts/outcomes are keyed by job id."""
    ids = [j['id'] for j in jobs]
    metrics, missing_notes = [], {}
    for mid, group in pr.CATALOG.items():
        if mid == 'skip_leak':
            continue                                            # T35c only (HD-20 of R05)
        cells = {j: cell_for(roots[j], j, mid, obs, facts[j]) for j in ids}
        m = {'id': mid, 'group': group, 'source': SOURCE[group], 'cells': cells}
        finish(m, 3)
        metrics.append(m)
        if group == 'B' and any('no_data' in c for c in cells.values()):
            missing_notes[mid] = sorted(j for j, c in cells.items() if 'no_data' in c)
    rows = []
    for j in ids:
        r = roots[j]
        ledger_values = {'decision': r['owner_decisions']['total'], 'intervention': facts[j]['interventions'], 'outcome': outcomes[j]['rows']}
        for column in COLUMNS:
            ledger, other = ledger_values[column], chat[j][column]
            row = {'job': j, 'column': column, 'ledger': ledger, 'chat': other, 'match': ledger == other}
            if ledger != other:
                row['reason'] = 'chưa giải thích: nhật ký chat và sổ khác nhau (cần người đối chiếu)'
            rows.append(row)
    root_rows = [{'root': roots[j]['plan'], 'job': j, 'plan': roots[j]['selector'], 'revision': roots[j]['revision'],
                  'final_outcome': roots[j]['status'], 'outcome_rows': outcomes[j]['rows']} for j in ids]
    prov = manifest['provenance']
    report = {'schema': 1, 'kind': 'interim', 'phase': 'PL-A', 'simulated': manifest['fixture'], 'jobs': ids, 'metrics': metrics,
              'owner_notes_missing': missing_notes,
              'outcomes': {'roots': root_rows, 'missing': sorted(r['root'] for r in root_rows if r['outcome_rows'] == 0), 'target': 0},
              'ledger_columns': {'command': 'onecrew eval plan-metrics --json (measure_all) + learning.outcome rows',
                                 'ledger_sha256': sha_of({'roots': [roots[j] for j in ids], 'facts': facts, 'outcomes': outcomes}),
                                 'hand_filled': 0, 'rows': rows},
              'desktop_window': dict(manifest['desktop_window']),
              'jobs_detail': [{'job': j, 'root': roots[j]['plan'], 'revision': roots[j]['revision'], 'status': roots[j]['status'],
                               'verdicts': facts[j]['verdicts'], 'interventions': facts[j]['interventions'],
                               'time_to_usable_minutes': roots[j]['time_to_output']['wall_minutes'],
                               'check_seconds': roots[j]['check_cost']['seconds'], 'open_findings': facts[j]['open_findings'],
                               'unknowns': sorted(m['id'] for m in metrics if 'no_data' in m['cells'][j])} for j in ids],
              'provenance': {'kind': 'fixture' if manifest['fixture'] else 'real', 'state_root': prov['state_root'],
                             'commit': prov['commit'], 'wheel_sha256': prov['wheel_sha256'], 'generator': 'wfkit.pilot_tools report'},
              'owner_acceptance': False, 'pilot_evidence': False}
    return report


def render_interim(r):
    n, out = 3, []
    p = r['provenance']
    out.append('# Báo cáo giữa kỳ PL-A' + (' (fixture)' if r['simulated'] else ''))
    out.append(f'Nguồn dữ liệu: {"fixture, không phải pilot thật" if p["kind"] == "fixture" else "sổ pilot thật"}; '
               f'state root {p["state_root"]}; commit {p["commit"]}; wheel sha256 {p["wheel_sha256"]}.')
    out.append('Báo cáo này không phải nghiệm thu và không phải bằng chứng pilot: chủ sở hữu nghiệm thu bằng lệnh của mình trong sổ.')
    out.append('## Chỉ số')
    for m in r['metrics']:
        s = m['summary']
        shown = f'không có dữ liệu: {s["no_data"]}' if 'no_data' in s else f'{s["value"]} {s["unit"]}'
        cells = '; '.join(f'{j}: ' + (f'không có dữ liệu: {c["no_data"]}' if 'no_data' in c else str(c['value'])) for j, c in m['cells'].items())
        out.append(f'| `{m["id"]}` | nhóm {m["group"]} | {m["source"]} | {m["k"]}/{n} | {m["status"]} | {m["label"]} | {shown} | {cells} |')
    out.append('## Từng việc')
    for d in r['jobs_detail']:
        out.append(f'- {d["job"]}: gốc {d["root"]}, bản {d["revision"]}, kết cục {d["status"]}; kiểm đạt {d["verdicts"]["pass"]}, hỏng {d["verdicts"]["fail"]}; '
                   f'can thiệp {d["interventions"]}; tới đầu ra {d["time_to_usable_minutes"]} phút; kiểm {d["check_seconds"]} s; '
                   f'phát hiện còn mở {d["open_findings"]}; chưa biết: {", ".join(d["unknowns"]) or "không"}')
    out.append('## Đối chiếu sổ và chat')
    for row in r['ledger_columns']['rows']:
        out.append(f'- {row["job"]} {row["column"]}: sổ {row["ledger"]}, chat {row["chat"]}, ' + ('khớp' if row['match'] else 'lệch: ' + row['reason']))
    missing = r['outcomes']['missing']
    out.append('Root thiếu outcome: ' + (', '.join(missing) if missing else 'rỗng'))
    d = r['desktop_window']
    out.append(f'Cửa sổ Windows: sự kiện {d["event_id"]} phát {d["emitted_at"]}, hiện {d["shown_at"]}, {d["delivery_status"]}')
    return '\n'.join(out) + '\n'


def generate_interim(ledger, manifest):
    """(report, markdown) from a pilot ledger (read-only) and a manifest. Raises ReportError rather than invent a figure."""
    from onecrew.v2 import metrics as v2metrics, outcome
    jobs, chat, obs = validate_manifest(manifest)
    measured = v2metrics.measure_all(ledger)['roots']
    roots, facts, outcomes = {}, {}, {}
    for job in jobs:
        found = [r for r in measured if job['root'] in (r['plan'], r['selector'])]
        need(len(found) == 1, f'job {job["id"]}: root {job["root"]} is not exactly one plan root of this ledger')
        root = found[0]
        need(root['status'] in ENDS, f'job {job["id"]}: root {job["root"]} has not ended (status {root["status"]}); there is no final outcome to report')
        roots[job['id']] = root
        facts[job['id']] = facts_of(ledger, root['selector'])
        rows = [o for o in outcome.outcomes(ledger, root['selector']) if o.get('plan_revision') == root['revision'] and o.get('end') == root['status']]
        outcomes[job['id']] = {'rows': len(rows)}
    report = build_interim(roots, facts, outcomes, manifest, jobs, chat, obs)
    return report, render_interim(report)


def write_report(report, text, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'interim-report.json').write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    (out / 'interim-report.md').write_text(text, encoding='utf-8')
    return out / 'interim-report.json', out / 'interim-report.md'


# ---- W38c: aggregate (T35c, PL-B) report generator ------------------------------------------------------------------

AGG_N = 10
OWNER = ('owner', 'user')
JOB_TYPES = ('code', 'docs', 'data', 'ops')
EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
NOT_SCOPE_RULES = ('stopped', 'hook_error')                  # a stopped plan refuses everything; a hook error is not a scope judgement
PROVIDER_REASON = {'quota_exhausted': 'hạn mức', 'provider_unavailable': 'lỗi công cụ', 'timeout': 'lỗi công cụ'}
BASELINE_SOURCE = 'DO-DIEU-KIEN-DUNG-V2-20261020.md (00 §9.2): 11 việc ngày 20/10'
TIER1_LIMITS = ['nhóm việc khác (việc v2.1 so với việc dưới WF)', 'cỡ mẫu nhỏ', 'cách đếm phải khớp cách đếm 20/10']
SKIPPED = 'việc bị bỏ'
WAIT_LIMIT_MINUTES = 60
AGG_FILES = ('aggregate-report.json', 'aggregate-report.md')
HASH_RE = re.compile(r'[0-9a-f]{64}')
COMMIT_RE = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})')


def _when(text):
    value = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_aggregate_manifest(m):
    need(isinstance(m, dict) and m.get('schema') == 1, 'manifest: schema must be 1')
    need(m.get('kind') == 'aggregate', 'manifest: kind must be "aggregate" (T35c)')
    need(type(m.get('synthetic')) is bool, 'manifest: synthetic must be declared (true|false)')
    ledgers = m.get('ledgers')
    need(isinstance(ledgers, list) and ledgers and all(isinstance(x, dict) for x in ledgers), 'manifest: ledgers (pilot state roots) required')
    for x in ledgers:
        need(isinstance(x.get('id'), str) and x['id'] and all(isinstance(x.get(k), str) and x[k] for k in ('project', 'state_root'))
             and COMMIT_RE.fullmatch(str(x.get('commit'))) and HASH_RE.fullmatch(str(x.get('wheel_sha256'))) and type(x.get('synthetic')) is bool,
             f'manifest: ledger {x.get("id")} needs id, project, state_root, commit, wheel_sha256 and synthetic (true|false)')
    ids = [x['id'] for x in ledgers]
    need(len(set(ids)) == len(ids), 'manifest: duplicate ledger id')
    need(m['synthetic'] or not any(x['synthetic'] for x in ledgers),
         'manifest: a synthetic ledger cannot make a real report (synthetic must be true)')
    jobs = m.get('jobs')
    need(isinstance(jobs, list) and len(jobs) == AGG_N and all(isinstance(j, dict) and isinstance(j.get('id'), str) and j['id'] for j in jobs),
         f'manifest: jobs must be {AGG_N} rows with an id (PL-B)')
    names = [j['id'] for j in jobs]
    twice = sorted({j for j in names if names.count(j) > 1})
    need(not twice, f'manifest: duplicate job rows: {", ".join(twice)}')
    seen = {}
    for j in jobs:
        if 'skipped' in j:
            need(isinstance(j['skipped'], str) and j['skipped'].strip() and 'root' not in j,
                 f'manifest: skipped job {j["id"]} needs its reason and no root')
            continue
        need(j.get('ledger') in ids, f'manifest: job {j["id"]} names ledger {j.get("ledger")!r}, which is not a pilot ledger of this manifest')
        need(isinstance(j.get('root'), str) and j['root'], f'manifest: job {j["id"]} needs its plan root')
        need(j.get('type') in JOB_TYPES, f'manifest: job {j["id"]} type must be one of {", ".join(JOB_TYPES)}')
        need(j.get('final_outcome') in ENDS, f'manifest: job {j["id"]} final_outcome must be one of {", ".join(ENDS)}')
        need('wheel_sha256' not in j or HASH_RE.fullmatch(str(j['wheel_sha256'])), f'manifest: job {j["id"]} wheel_sha256 must be a sha256')
        key = (j['ledger'], j['root'])
        need(key not in seen, f'manifest: duplicate job rows: {seen.get(key)} and {j["id"]} name the same root {key[0]}/{key[1]}')
        seen[key] = j['id']
    excluded = m.get('excluded', [])
    need(isinstance(excluded, list) and all(isinstance(x, dict) and x.get('ledger') in ids and isinstance(x.get('root'), str) and x['root']
         and isinstance(x.get('reason'), str) and x['reason'].strip() for x in excluded), 'manifest: excluded roots need ledger, root and reason')
    for x in excluded:
        need((x['ledger'], x['root']) not in seen, f'manifest: root {x["ledger"]}/{x["root"]} is both a job and excluded')
    ran = [j['id'] for j in jobs if 'skipped' not in j]
    chat = m.get('chat_log')
    need(isinstance(chat, dict) and set(chat) == set(ran) and all(isinstance(chat[j], dict) and isinstance(chat[j].get('decision'), int)
         and not isinstance(chat[j]['decision'], bool) and chat[j]['decision'] >= 0 for j in ran),
         'manifest: chat_log needs the decision count of every job that ran (the E24 cross-check is not hand-filled)')
    obs = m.get('observations', {})
    need(isinstance(obs, dict), 'manifest: observations must be an object')
    for mid, cells in obs.items():
        need(pr.CATALOG.get(mid) in ('B', 'C') and mid != 'ledger_manual_fixes', f'manifest: observations may only supply group B/C metrics, not {mid}')
        need(isinstance(cells, dict) and set(cells) <= set(ran) and all(pr.number(v) and v >= 0 for v in cells.values()),
             f'manifest: observations for {mid} must map jobs that ran to non-negative numbers')
    log = m.get('decision_log')
    need(log is None or (isinstance(log, list) and all(isinstance(r, dict) and r.get('job') in ran and all(isinstance(r.get(k), str) and r[k]
         for k in ('at', 'before', 'after', 'reason')) for r in log)), 'manifest: decision_log rows need at, job, before, after, reason')
    trial = m.get('continuation_trial')
    if trial is not None:
        need(isinstance(trial, dict) and trial.get('job') in ran and isinstance(trial.get('tool'), str) and trial['tool']
             and HASH_RE.fullmatch(str(trial.get('package_sha256'))) and isinstance(trial.get('answers'), list)
             and all(isinstance(a, dict) and isinstance(a.get('question'), str) and type(a.get('correct')) is bool for a in trial['answers'])
             and isinstance(trial.get('grader'), dict) and isinstance(trial.get('coordinator_model'), str),
             'manifest: continuation_trial needs job, tool, package_sha256, answers, grader and coordinator_model')
        need('result' not in trial, 'manifest: continuation_trial.result is computed from the answers, never given')
    return ledgers, jobs, chat, obs


def _events_of(conn, task_id):
    return [{'seq': r['seq'], 'kind': r['kind'], 'p': json.loads(r['payload']), 'at': r['created_at']}
            for r in conn.execute('SELECT seq, kind, payload, created_at FROM events WHERE task_id=? ORDER BY seq', (task_id,))]


def _inside_scope(subject, owned, project):
    import fnmatch
    import posixpath
    text = str(subject).replace('\\', '/')
    try:
        path = Path(subject)
        if path.is_absolute():
            text = path.resolve().relative_to(Path(project).resolve()).as_posix()
    except (ValueError, OSError):
        return False                                          # outside the project: not inside the approved scope
    if not text:
        return False
    text = posixpath.normpath(text)
    while text.startswith('./'):
        text = text[2:]
    return any(text == p or fnmatch.fnmatch(text, p) or text.startswith(p.rstrip('/') + '/') for p in owned)


def aggregate_facts(ledger, root, desktop_records=()):
    """The PL-B facts of one measured root, read from its events only (nothing is written, no model, no clock). Each figure is
    {'value', 'derived_from'} or {'no_data': reason}; a missing source is a reason, never 0."""
    from onecrew.v2 import namespaces, plan as plans
    from onecrew.v2.authority import U_IDS
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, root['selector'])
        events = _events_of(conn, state['task_id'])
        contract = plans.load(ledger, state, root['revision'])[0]
        capability = namespaces.has_capability(state, 'finding-register')
    task = state['task_id']
    names = {state['name'], state['selector'], root['plan']}
    verified = root['time_to_output']['verified_at']
    out = {'task': task}
    # owner decisions, one action per owner verb / answer, classified by the request's own class (U1-U4) where it has one
    created = {e['p'].get('id'): e['p'] for e in events if e['kind'] == 'request.created'}
    actions = []
    for e in events:
        k, p = e['kind'], e['p']
        if k == 'plan.approved' and p.get('by') in OWNER:
            actions.append({'verb': 'approve', 'kind': 'root_approval', 'at': e['at']})
        elif k == 'plan.accepted' and p.get('by') in OWNER:
            actions.append({'verb': 'accept', 'kind': 'acceptance', 'at': e['at']})
        elif k == 'verdict.recorded' and p.get('by') == 'owner':
            actions.append({'verb': 'record', 'kind': 'other', 'at': e['at']})
        elif k == 'request.answered':
            params = (((created.get(p.get('request_id')) or {}).get('question') or {}).get('action') or {}).get('parameters') or {}
            cls = params.get('class') or params.get('reason_class')
            actions.append({'verb': 'answer', 'kind': cls if cls in U_IDS else 'other', 'at': p.get('recorded_at') or e['at'],
                            'request': p.get('request_id')})
    out['actions'] = actions
    out['interventions'] = sum(1 for e in events if e['kind'] == 'control.intervention')
    verdicts = [e for e in events if e['kind'] == 'verdict.recorded']
    out['verdicts'] = {'pass': sum(1 for e in verdicts if e['p'].get('result') == 'pass'),
                       'fail': sum(1 for e in verdicts if e['p'].get('result') == 'fail'),
                       'inconclusive': sum(1 for e in verdicts if e['p'].get('result') == 'inconclusive')}
    open_findings = UNKNOWN
    rows = []
    if capability:
        from onecrew.v2.findings import list_findings
        rows = list_findings(ledger, root['selector'], task_id=task)
        open_findings = sum(1 for r in rows if r.get('status') == 'open')
    out['open_findings'] = open_findings
    # false pass (rework d): a fail after a pass of the same milestone and revision, plus a finding registered after verification
    passed, late = set(), []
    for e in verdicts:
        key = (e['p'].get('revision'), e['p'].get('milestone'))
        if e['p'].get('result') == 'pass':
            passed.add(key)
        elif e['p'].get('result') == 'fail' and key in passed:
            late.append({'seq': e['seq'], 'kind': 'verdict', 'id': f'verdict@{e["seq"]}', 'node': key[1]})
    if capability and verified:
        late += [{'seq': e['seq'], 'kind': 'finding', 'id': f'finding@{e["seq"]}', 'node': None} for e in events
                 if e['kind'] == 'finding.registered' and _when(e['at']) > _when(verified)]
    source = 'verdict.recorded' + ('+finding.registered' if capability else '')
    out['false_pass'] = {'value': len(late), 'derived_from': source}
    # SKIP leak (E29): read from the recorded links (findings.link_skip), each re-validated against its HD-20 SKIP record
    defects = [d for d in late if d['kind'] == 'verdict']
    if capability and verified:
        defects += [{'seq': e['seq'], 'kind': 'finding', 'id': fid} for e in events
                    if e['kind'] == 'finding.registered' and _when(e['at']) > _when(verified) for fid in (e['p'].get('opened') or [])]
    out.update(skip_leak_of(ledger, root['selector'], defects))
    # hooks: the spool must be imported (onecrew hook sync) before the ledger can be the source
    spool = Path(ledger.project) / '.onecrew' / 'violations.jsonl'
    imported = {e['p'].get('spool_id') for e in events if e['kind'].startswith('hook.')}
    pending = 0
    if spool.exists():
        for line in spool.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get('plan') in names and item.get('id') not in imported:
                pending += 1
    hook_gap = {'no_data': f'nhật ký hook có {pending} dòng chưa nhập sổ (onecrew hook sync)'} if pending else None
    issued = [e for e in events if e['kind'] == 'verdict.receipt_issued']
    answered = {e['p'].get('request_id'): _when(e['p'].get('recorded_at') or e['at']) for e in events if e['kind'] == 'request.answered'}
    requests = [(e['p'].get('id'), _when(e['p'].get('created_at') or e['at'])) for e in events if e['kind'] == 'request.created']
    noise = 0
    for e in events:
        if e['kind'] != 'hook.stop_blocked':
            continue
        t = _when(e['p'].get('recorded_at') or e['at'])
        waiting_receipt = any(_when(r['at']) <= t and not any(v['p'].get('receipt') == r['p'].get('receipt') and _when(v['at']) <= t for v in verdicts)
                              for r in issued)
        waiting_owner = any(at <= t and not (rid in answered and answered[rid] <= t) for rid, at in requests)
        noise += bool(waiting_receipt or waiting_owner)
    out['noise_stop_hook'] = hook_gap or {'value': noise, 'derived_from': 'hook.stop_blocked while a receipt or an owner question waits'}
    owned = contract.get('scope', {}).get('owned', [])
    blocks = [e for e in events if e['kind'] == 'hook.blocked' and e['p'].get('rule') not in NOT_SCOPE_RULES]
    shell = [e for e in blocks if e['p'].get('tool') not in EDIT_TOOLS]
    if hook_gap:
        out['wrong_scope_block'] = hook_gap
    elif shell:
        out['wrong_scope_block'] = {'no_data': f'{len(shell)} lần chặn lệnh shell: sổ không ghi đường dẫn để đối chiếu scope'}
    else:
        wrong = sum(1 for e in blocks if _inside_scope(e['p'].get('subject') or '', owned, ledger.project))
        out['wrong_scope_block'] = {'value': wrong, 'derived_from': 'hook.blocked x contract scope.owned'}
    out['noise_notifications'] = {'value': sum(1 for e in events if e['kind'] == 'notice.exception' and e['p'].get('user_action') is None),
                                  'derived_from': 'notice.exception without a user action'}
    # owner waits missed for more than 60 minutes: an owner question neither answered nor shown by the desktop channel within 60 min
    horizon = max((_when(e['at']) for e in events), default=None)
    shown = [_when(r['shown_at']) for r in desktop_records if r.get('task') == task and r.get('status') in ('shown', 'closed') and r.get('shown_at')]
    missed = 0
    for rid, at in requests:
        limit = at + timedelta(minutes=WAIT_LIMIT_MINUTES)
        delivered = (rid in answered and answered[rid] <= limit) or any(at <= s <= limit for s in shown)
        missed += not delivered and ((rid in answered) or (horizon is not None and horizon >= limit))
    out['missed_wait_1h'] = {'value': missed, 'derived_from': 'request.created x request.answered x desktop status'}
    # provider calls and failures (E38): verdict events that name their provider
    providers = {}
    for e in verdicts:
        name = e['p'].get('provider')
        if not name:
            continue
        row = providers.setdefault(name, {'calls': 0, 'failures': 0, 'reasons': {}, 'inconclusive_receipts': 0})
        row['calls'] += 1
        reason = PROVIDER_REASON.get(e['p'].get('provider_error'))
        if e['p'].get('result') == 'inconclusive' and reason:
            row['failures'] += 1
            row['inconclusive_receipts'] += 1
            row['reasons'][reason] = row['reasons'].get(reason, 0) + 1
    out['providers'] = providers
    return out


def skip_leak_of(ledger, selector, late=()):
    """E29 measure of one root: the defects recorded as missed by a SKIP. Reads the HD-20 SKIP records of review_policy and the
    finding->SKIP link records through onecrew.v2.findings.skip_view (a link is counted only when its SKIP record and its finding hold).
    `late` = defects found after verification ({seq, kind, id}); one that came after a SKIP and is not linked leaves the figure unknown
    (it may or may not be a leak: nothing is attributed automatically, and nothing is assumed to be 0).
    Returns {'skip_records': [id], 'skip_links': [{finding, skip_record, ...}], 'skip_links_invalid': [...], 'skip_leak': cell}."""
    from onecrew.v2 import findings
    view = findings.skip_view(ledger, selector)
    links = view['links']
    linked = {link['finding'] for link in links}
    first = min((s['seq'] for s in view['skip_records'].values()), default=None)
    unattributed = sorted(d['id'] for d in late if first is not None and d['seq'] > first and d['id'] not in linked)
    out = {'skip_records': sorted(view['skip_records']), 'skip_links': links, 'skip_links_invalid': view['invalid']}
    if unattributed:
        out['skip_leak'] = {'no_data': f'{len(unattributed)} lỗi tìm thấy sau SKIP chưa nối được với bản ghi SKIP (HD-20) bằng mã: '
                                       + ', '.join(unattributed)}
    else:
        out['skip_leak'] = {'value': len(links), 'derived_from': 'decision.recorded(review_policy SKIP) x decision.recorded(finding_skip_link)'}
    return out


def aggregate_cell(root, job, mid, obs, facts, decision_log):
    if mid in ('false_pass', 'skip_leak', 'noise_stop_hook', 'wrong_scope_block', 'noise_notifications', 'missed_wait_1h'):
        return dict(facts[mid])
    if mid == 'ledger_manual_fixes':
        if decision_log is None:
            return {'no_data': 'không có nhật ký quyết định của người điều phối'}
        return {'value': sum(1 for r in decision_log if r['job'] == job)}
    if pr.CATALOG[mid] == 'A':
        return cell_a(root, mid, facts)
    return cell_for(root, job, mid, obs, facts)


def build_aggregate(ledgers, jobs, measured, facts, outcomes, manifest, chat, obs, roots_of):
    """Pure: the aggregate report dict. measured/facts/outcomes are keyed by job id (jobs that ran); roots_of: ledger id -> plan roots."""
    ids = [j['id'] for j in jobs]
    ran = [j['id'] for j in jobs if 'skipped' not in j]
    by_job = {j['id']: j for j in jobs}
    log = manifest.get('decision_log')
    metrics, missing_notes = [], {}
    for mid, group in pr.CATALOG.items():
        cells = {}
        for j in ids:
            if j not in ran:
                cells[j] = {'no_data': pr.NO_NOTES + f' ({SKIPPED}: {by_job[j]["skipped"]})' if group == 'B' else f'{SKIPPED}: {by_job[j]["skipped"]}'}
            else:
                cells[j] = aggregate_cell(measured[j], j, mid, obs, facts[j], log)
        m = {'id': mid, 'group': group, 'source': SOURCE[group], 'cells': cells}
        finish(m, AGG_N, 'aggregate')
        have = sorted(pr.values(m))
        m['computed_from'] = [{'job': j, 'ledger': by_job[j]['ledger'], 'root': measured[j]['plan']} for j in have]
        m['missing'] = sorted(set(ids) - set(have))
        if mid in pr.TARGETS:
            m['target'] = pr.TARGETS[mid]
            total = sum(pr.values(m).values())
            m['target_status'] = pr.target_status(m['target'], total, m['k'], AGG_N) or 'không đạt'
        metrics.append(m)
        if group == 'B' and any('no_data' in c for c in cells.values()):
            missing_notes[mid] = sorted(j for j, c in cells.items() if 'no_data' in c)
    by = {m['id']: m for m in metrics}
    sl = by['skip_leak']
    if 'value' in sl['summary']:
        by['false_pass']['skip_leak_part'] = sl['summary']['value']
    comparisons = []
    for name, (base, parts) in pr.TIER1.items():
        # Composite rule (round 7 F3): numerator, denominator and computed_from come from ONE job set, the jobs with a value for every
        # part. A job missing any part is out of the composite entirely (its other parts are not counted, a missing cell is never 0) and
        # is listed per part under 'missing'; an observed 0 is a value and counts. Fewer than AGG_N jobs = a partial comparison.
        cells = {p: by[p]['cells'] for p in parts}
        frm = sorted(j for j in ids if all('value' in cells[p][j] for p in parts))
        per_job = {j: clean(sum(cells[p][j]['value'] for p in parts)) for j in frm}
        missing = {p: sorted(j for j in ids if 'value' not in cells[p][j]) for p in parts}
        k, total = len(frm), clean(sum(per_job.values()))
        c = {'metric': name, 'baseline_count': base, 'baseline_jobs': 11, 'baseline_per_job': round(base / 11, 3), 'source': BASELINE_SOURCE,
             'parts': list(parts), 'computed_from': frm, 'per_job': per_job, 'missing': {p: v for p, v in missing.items() if v},
             'pilot_denominator': AGG_N, 'complete': k == AGG_N}
        c.update({'pilot_count': total, 'pilot_jobs': k, 'pilot_per_job': round(total / k, 3)} if k else
                 {'pilot_count': None, 'pilot_jobs': 0, 'pilot_per_job': None, 'no_data': 'không việc nào có dữ liệu cho mọi phần của chỉ số này'})
        comparisons.append(c)
    actions, per_job, mismatches = [], {}, []
    for j in ran:
        mine = facts[j]['actions']
        need(len(mine) == measured[j]['owner_decisions']['total'],
             f'job {j}: {len(mine)} owner actions read from the ledger, measure_all counts {measured[j]["owner_decisions"]["total"]}')
        agree = chat[j]['decision'] == len(mine)
        for a in mine:
            actions.append({'job': j, 'at': a['at'], 'verb': a['verb'], 'kind': a['kind'], 'sources': ['ledger', 'chat'] if agree else ['ledger'],
                            **({'request': a['request']} if a.get('request') else {})})
        if not agree:
            mismatches.append({'job': j, 'at': None, 'ledger': len(mine), 'chat': chat[j]['decision'],
                               'reason': 'chưa giải thích: số quyết định trong sổ và nhật ký chat khác nhau (cần người đối chiếu)'})
        per_job[j] = {k: sum(1 for a in mine if a['kind'] == k) for k in pr.KINDS}
    for j in ids:
        per_job.setdefault(j, dict.fromkeys(pr.KINDS, 0))
    ok = all(sum(c.values()) <= 2 and c['other'] == 0 for c in per_job.values())
    links = [dict(link, job=j) for j in ran for link in facts[j]['skip_links']]
    invalid_links = [dict(x, job=j) for j in ran for x in facts[j].get('skip_links_invalid', [])]
    interventions = sum(facts[j]['interventions'] for j in ran)
    rows_log = [dict(r) for r in log] if log is not None else []
    manual = {'decision_log_rows': rows_log, 'interventions': interventions}
    if interventions != len(rows_log):
        manual['mismatch_reason'] = (f'nhật ký quyết định có {len(rows_log)} dòng, sổ có {interventions} control.intervention'
                                     + ('' if log is not None else ' (không có nhật ký quyết định)') + ': cần người đối chiếu')
    providers = {}
    for j in ran:
        for name, row in facts[j]['providers'].items():
            acc = providers.setdefault(name, {'provider': name, 'calls': 0, 'failures': 0, 'reasons': {}, 'inconclusive_receipts': 0, 'computed_from': []})
            for key in ('calls', 'failures', 'inconclusive_receipts'):
                acc[key] += row[key]
            for reason, count in row['reasons'].items():
                acc['reasons'][reason] = acc['reasons'].get(reason, 0) + count
            acc['computed_from'].append({'job': j, 'ledger': by_job[j]['ledger'], 'root': measured[j]['plan']})
    trial = manifest.get('continuation_trial')
    if trial is None:
        continuation = {'missing': 'chưa có lần thử gói tiếp tục do người chấm độc lập chấm'}
    else:
        answers = [{'question': a['question'], 'correct': a['correct']} for a in trial['answers']]
        right = [a['question'] for a in answers] == list(pr.QUESTIONS) and all(a['correct'] for a in answers)
        continuation = {'job': trial['job'], 'tool': trial['tool'], 'package_sha256': trial['package_sha256'], 'answers': answers,
                        'grader': dict(trial['grader']), 'coordinator_model': trial['coordinator_model'], 'result': 'đạt' if right else 'không đạt'}
    root_rows = [{'root': measured[j]['plan'], 'ledger': by_job[j]['ledger'], 'job': j, 'plan': measured[j]['selector'],
                  'revision': measured[j]['revision'], 'final_outcome': measured[j]['status'], 'outcome_rows': outcomes[j]['rows']} for j in ran]
    detail = []
    for j in ids:
        if j not in ran:
            detail.append({'job': j, 'skipped': by_job[j]['skipped'], 'unknowns': sorted(pr.CATALOG)})
            continue
        r, f = measured[j], facts[j]
        ledger_row = next(x for x in ledgers if x['id'] == by_job[j]['ledger'])
        detail.append({'job': j, 'ledger': ledger_row['id'], 'root': r['plan'], 'plan': r['selector'], 'revision': r['revision'], 'status': r['status'],
                       'type': by_job[j]['type'], 'wheel_sha256': by_job[j].get('wheel_sha256', ledger_row['wheel_sha256']),
                       'verdicts': f['verdicts'], 'interventions': f['interventions'], 'open_findings': f['open_findings'],
                       'skip_records': f['skip_records'], 'time_to_usable_minutes': r['time_to_output']['wall_minutes'],
                       'check_seconds': r['check_cost']['seconds'], 'decisions': per_job[j],
                       'unknowns': sorted(m['id'] for m in metrics if 'no_data' in m['cells'][j])})
    synthetic = manifest['synthetic']
    prov_ledgers = []
    for x in ledgers:
        prov_ledgers.append({'id': x['id'], 'project': x['project'], 'state_root': x['state_root'], 'commit': x['commit'],
                             'wheel_sha256': x['wheel_sha256'], 'wheel_verified': bool(x.get('wheel')), 'synthetic': x['synthetic'],
                             'roots': roots_of[x['id']],
                             'excluded': [{'root': e['root'], 'reason': e['reason']} for e in manifest.get('excluded', []) if e['ledger'] == x['id']]})
    report = {'schema': 1, 'kind': 'aggregate', 'phase': 'PL-B', 'simulated': synthetic, 'jobs': ids, 'metrics': metrics,
              'owner_notes_missing': missing_notes,
              'outcomes': {'roots': root_rows, 'missing': sorted(r['root'] for r in root_rows if r['outcome_rows'] == 0), 'target': 0},
              'tiers': {'tier1': {'comparisons': comparisons, 'limits': list(TIER1_LIMITS)},
                        'tier2': {'metrics': sorted(pr.TIER2), 'conclusion': pr.NO_REDUCTION},
                        'tier3': {'conclusion': pr.NO_REDUCTION, 'comparison_group': None}},
              'owner_decisions': {'actions': actions, 'mismatches': mismatches, 'per_job': per_job,
                                  'ac1': {'max_per_job': 2, 'outside_u1_u4': 0, 'status': 'đạt' if ok else 'không đạt'}},
              'skip_leak': {'skip_count': sum(len(facts[j]['skip_records']) for j in ran), 'links': links, 'invalid_links': invalid_links,
                             'source': 'decision.recorded: review_policy SKIP (HD-20) x finding_skip_link', 'target': 0},
              'manual_fixes': manual, 'providers': [providers[n] for n in sorted(providers)], 'continuation_trial': continuation,
              'skipped_jobs': [{'job': j, 'reason': by_job[j]['skipped']} for j in ids if j not in ran],
              'jobs_detail': detail,
              'case_k': 'không áp dụng: ca K (T55 C1) thuộc cổng vào PL-B (T45c), không phải báo cáo tổng hợp',
              'provenance': {'kind': 'synthetic' if synthetic else 'real', 'generator': 'wfkit.pilot_tools report --kind aggregate',
                             'ledgers': prov_ledgers, 'manifest_sha256': sha_of(manifest)},
              'owner_acceptance': False, 'pilot_evidence': False}
    report['figures_sha256'] = pr.figures_digest(report)
    return report


def _cells_text(m):
    return '; '.join(f'{j}: ' + (f'không có dữ liệu: {c["no_data"]}' if 'no_data' in c else str(c['value'])) for j, c in m['cells'].items())


def render_aggregate(r):
    n, out = AGG_N, []
    groups = {'đủ': [], 'thiếu': [], 'không có': []}
    for m in sorted(r['metrics'], key=lambda m: m['id']):
        groups[pr.status_for(m['k'], n)].append(m['id'])
    a_short = [f'{j} {m["id"]}' for m in sorted(r['metrics'], key=lambda m: m['id']) if m['group'] == 'A'
               for j in r['jobs'] if 'value' not in m['cells'][j]]
    p = r['provenance']
    out.append('# Báo cáo tổng hợp PL-B' + (' (synthetic)' if r['simulated'] else ''))
    out.append(pr.AC5 + ('đạt' if not a_short else 'không đạt: nhóm A thiếu ' + ', '.join(a_short) + ' (lỗi bộ ghi)'))
    out.append('Baseline: {} chỉ số đủ 10/10 ({}), {} thiếu ({}), {} không có ({})'.format(
        len(groups['đủ']), ', '.join(groups['đủ']), len(groups['thiếu']), ', '.join(groups['thiếu']),
        len(groups['không có']), ', '.join(groups['không có'])))
    out.append('Nguồn dữ liệu: ' + (pr.SYNTHETIC_LINE if p['kind'] == 'synthetic' else 'sổ của các state-root pilot') +
               f'; mã băm số liệu {r["figures_sha256"]}; manifest {p["manifest_sha256"]}.')
    for x in p['ledgers']:
        out.append(f'Sổ {x["id"]}: state root {x["state_root"]}; commit {x["commit"]}; wheel sha256 {x["wheel_sha256"]}'
                   f' ({"đã đối chiếu file wheel" if x["wheel_verified"] else "chưa đối chiếu file wheel"}); root: {", ".join(x["roots"])}'
                   + ('; loại: ' + ', '.join(f'{e["root"]} ({e["reason"]})' for e in x['excluded']) if x['excluded'] else '') + '.')
    out.append('Báo cáo này không phải nghiệm thu và không phải bằng chứng pilot: chủ sở hữu nghiệm thu bằng lệnh của mình trong sổ.')
    out.append('## Chỉ số')
    for m in r['metrics']:
        s = m['summary']
        shown = f'không có dữ liệu: {s["no_data"]}' if 'no_data' in s else f'{s["value"]} {s["unit"]}'
        extra = f' | mục tiêu {m["target"]}: {m["target_status"]}' if 'target' in m else ''
        if m['id'] == 'skip_leak':
            extra += f' | {len(r["skip_leak"]["links"])}/{r["skip_leak"]["skip_count"]} SKIP'
        if 'skip_leak_part' in m:
            extra += f' | trong đó lọt qua SKIP: {m["skip_leak_part"]}'
        frm = ', '.join(x['job'] for x in m['computed_from']) or 'không việc nào'
        out.append(f'| `{m["id"]}` | nhóm {m["group"]} | {m["source"]} | {m["k"]}/{n} | {m["status"]} | {m["label"]} | {shown} | '
                   f'{_cells_text(m)}{extra} | tính từ: {frm} |')
    out.append('## Từng việc')
    for d in r['jobs_detail']:
        if 'skipped' in d:
            out.append(f'- {d["job"]}: {SKIPPED}: {d["skipped"]} (vẫn trong mẫu số {n})')
            continue
        out.append(f'- {d["job"]} ({d["type"]}): sổ {d["ledger"]}, gốc {d["root"]}, bản {d["revision"]}, kết cục {d["status"]}; wheel {d["wheel_sha256"]}; '
                   f'kiểm đạt {d["verdicts"]["pass"]}, hỏng {d["verdicts"]["fail"]}, chưa rõ {d["verdicts"]["inconclusive"]}; can thiệp {d["interventions"]}; '
                   f'phát hiện còn mở {d["open_findings"]}; chưa biết: {", ".join(d["unknowns"]) or "không"}')
    missing = r['outcomes']['missing']
    out.append('Root thiếu outcome: ' + (', '.join(missing) if missing else 'rỗng'))
    out.append('## Tầng 1 — so với số đếm 20/10')
    for c in r['tiers']['tier1']['comparisons']:
        pilot = (f'pilot {c["pilot_count"]} trên {c["pilot_jobs"]} việc ({c["pilot_per_job"]} mỗi việc); '
                 f'tính từ {c["pilot_jobs"]}/{c["pilot_denominator"]} việc: {", ".join(c["computed_from"])}' if c['pilot_jobs']
                 else f'pilot: không có dữ liệu ({c["no_data"]})')
        if not c['complete']:
            pilot += '; so sánh một phần, thiếu ' + '; '.join(f'{p}: {", ".join(js)}' for p, js in c['missing'].items())
        out.append(f'- {c["metric"]}: 20/10: {c["baseline_count"]} trên {c["baseline_jobs"]} việc ({c["baseline_per_job"]} mỗi việc); {pilot}')
    out.append('Giới hạn: ' + '; '.join(r['tiers']['tier1']['limits']) + '. Không suy ra thời gian từ số đếm 20/10.')
    out.append('## Tầng 2 — pilot')
    out.append(f'Kết luận tầng 2: {r["tiers"]["tier2"]["conclusion"]} (trạng thái từng chỉ số ở bảng trên)')
    out.append('## Tầng 3 — so sánh')
    out.append(f'Kết luận tầng 3: {r["tiers"]["tier3"]["conclusion"]} (chưa có nhóm việc tương đương, E1 sau chương trình)')
    out.append('## Quyết định của chủ sở hữu')
    out.append('AC1: tối đa 2 quyết định mỗi việc, 0 ngoài U1–U4: ' + r['owner_decisions']['ac1']['status'])
    for j, c in r['owner_decisions']['per_job'].items():
        out.append(f'- {j}: ' + ', '.join(f'{k} {v}' for k, v in c.items()))
    for mm in r['owner_decisions']['mismatches']:
        out.append(f'- lệch {mm["job"]}: sổ {mm["ledger"]}, chat {mm["chat"]}: {mm["reason"]}')
    out.append('## SKIP, sửa tay, provider, gói tiếp tục')
    sk = r['skip_leak']
    out.append(f'SKIP (HD-20): {sk["skip_count"]} bản ghi; lỗi lọt qua nối được: {len(sk["links"])}/{sk["skip_count"]} SKIP; mục tiêu {sk["target"]}; '
               f'nguồn {sk["source"]}' + ''.join(f'; {x["job"]}: finding {x["finding"]} <- SKIP {x["skip_record"]}' for x in sk['links'])
               + ''.join(f'; không tính {x["job"]} {x["record"]}: {x["reason"]}' for x in sk['invalid_links']))
    mf = r['manual_fixes']
    out.append(f'Sửa tay trạng thái sổ: nhật ký quyết định {len(mf["decision_log_rows"])} dòng; control.intervention {mf["interventions"]}'
               + (f'; lệch: {mf["mismatch_reason"]}' if 'mismatch_reason' in mf else ''))
    for prow in r['providers']:
        reasons = ', '.join(f'{k} {v}' for k, v in sorted(prow['reasons'].items())) or 'không'
        out.append(f'Provider {prow["provider"]}: {prow["failures"]}/{prow["calls"]} lần không chạy được ({reasons})')
    if not r['providers']:
        out.append('Provider: không có dữ liệu (không có lần gọi reviewer hay cố vấn nào trong sổ)')
    c = r['continuation_trial']
    if 'missing' in c:
        out.append(f'Gói tiếp tục: không có dữ liệu: {c["missing"]}')
    else:
        out.append(f'Gói tiếp tục: việc {c["job"]}, công cụ {c["tool"]}, gói {c["package_sha256"]}; người chấm {c["grader"].get("identity")} '
                   f'({c["grader"].get("model")}), người điều phối {c["coordinator_model"]}; '
                   f'{sum(1 for a in c["answers"] if a["correct"])}/{len(c["answers"])} câu đúng: {c["result"]}')
    out.append(f'Ca K: {r["case_k"]}')
    return '\n'.join(out) + '\n'


def open_read_only(entry):
    from onecrew.v2.lint import ReadOnlyLedger
    return ReadOnlyLedger(Path(entry['project']), Path(entry['state_root']))


def generate_aggregate(manifest, open_ledger=open_read_only, base=None):
    """(report, markdown) from the pilot ledgers named by the manifest (read-only). Raises ReportError rather than drop or invent a sample."""
    from onecrew import desktop_core
    from onecrew.v2 import metrics as v2metrics, outcome
    ledgers, jobs, chat, obs = validate_aggregate_manifest(manifest)
    base = Path(base) if base else Path.cwd()
    trial = manifest.get('continuation_trial')
    if trial and trial.get('package'):
        package = Path(trial['package'])
        actual = file_sha256(package if package.is_absolute() else base / package)
        need(actual == trial['package_sha256'], f'continuation_trial: package {trial["package"]} has sha256 {actual}, the trial names '
                                                f'{trial["package_sha256"]} (wrong artifact)')
    opened, measured_all, roots_of, desktop = {}, {}, {}, {}
    for entry in ledgers:
        ledger = open_ledger(entry)
        stated = Path(entry['state_root'])
        stated = stated if stated.is_absolute() else base / stated
        need(stated.resolve() == Path(ledger.state_root).resolve(),
             f'ledger {entry["id"]}: the manifest names state root {entry["state_root"]}, the ledger opened is {ledger.state_root} (contradictory data)')
        if entry.get('wheel'):
            wheel = Path(entry['wheel'])
            wheel = wheel if wheel.is_absolute() else base / wheel
            actual = file_sha256(wheel)
            need(actual == entry['wheel_sha256'], f'ledger {entry["id"]}: wheel {entry["wheel"]} has sha256 {actual}, the manifest pins '
                                                  f'{entry["wheel_sha256"]} (wrong artifact)')
        opened[entry['id']] = ledger
        measured_all[entry['id']] = v2metrics.measure_all(ledger)['roots']
        roots_of[entry['id']] = sorted(r['plan'] for r in measured_all[entry['id']])
        desktop[entry['id']] = [r for r in desktop_core.status(ledger)['records'] if isinstance(r, dict)]
    for x in manifest.get('excluded', []):
        need(any(x['root'] in (r['plan'], r['selector']) for r in measured_all[x['ledger']]),
             f'manifest: excluded root {x["ledger"]}/{x["root"]} is not a plan root of that ledger')
    measured, facts, outcomes, claimed = {}, {}, {}, {}
    for job in jobs:
        if 'skipped' in job:
            continue
        entry = next(x for x in ledgers if x['id'] == job['ledger'])
        found = [r for r in measured_all[job['ledger']] if job['root'] in (r['plan'], r['selector'])]
        need(len(found) == 1, f'job {job["id"]}: root {job["root"]} is not exactly one plan root of ledger {job["ledger"]}')
        root = found[0]
        key = (job['ledger'], root['plan'])
        need(key not in claimed, f'duplicate job rows: {claimed.get(key)} and {job["id"]} are the same root {key[0]}/{key[1]}')
        claimed[key] = job['id']
        need(root['status'] in ENDS, f'job {job["id"]}: root {job["root"]} has not ended (status {root["status"]}); there is no final outcome to report')
        need(root['status'] == job['final_outcome'], f'job {job["id"]}: the manifest says final outcome {job["final_outcome"]}, ledger {job["ledger"]} '
                                                     f'root {root["plan"]} says {root["status"]} (contradictory data)')
        need(job.get('wheel_sha256', entry['wheel_sha256']) == entry['wheel_sha256'],
             f'job {job["id"]}: pinned wheel {job.get("wheel_sha256")} is not the wheel {entry["wheel_sha256"]} of ledger {entry["id"]} (wrong artifact)')
        measured[job['id']] = root
        facts[job['id']] = aggregate_facts(opened[job['ledger']], root, desktop[job['ledger']])
        rows = [o for o in outcome.outcomes(opened[job['ledger']], root['selector'])
                if o.get('plan_revision') == root['revision'] and o.get('end') == root['status']]
        outcomes[job['id']] = {'rows': len(rows)}
    for entry in ledgers:
        named = {r for (lid, r) in claimed if lid == entry['id']}
        excluded = {x['root'] for x in manifest.get('excluded', []) if x['ledger'] == entry['id']}
        outside = sorted(r['plan'] for r in measured_all[entry['id']] if r['plan'] not in named and r['plan'] not in excluded
                         and r['selector'] not in excluded)
        need(not outside, f'ledger {entry["id"]}: plan root(s) {", ".join(outside)} are neither pilot jobs nor excluded with a reason '
                          '(wrong scope: a sample is never dropped silently)')
    report = build_aggregate(ledgers, jobs, measured, facts, outcomes, manifest, chat, obs, roots_of)
    return report, render_aggregate(report)


def write_named(report, text, out_dir, names):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / names[0]).write_bytes((json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8'))   # bytes: no CRLF
    (out / names[1]).write_bytes(text.encode('utf-8'))
    return out / names[0], out / names[1]


def verify_aggregate(manifest, report_dir, open_ledger=open_read_only, base=None):
    """Regenerate from the same manifest and ledgers; refuse unless both written files are byte-identical and check_report passes."""
    report, text = generate_aggregate(manifest, open_ledger, base)
    want_json = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    want_md = text.encode('utf-8')
    problems = []
    for name, want in zip(AGG_FILES, (want_json, want_md)):
        path = Path(report_dir) / name
        got = path.read_bytes() if path.exists() else None
        if got != want:
            problems.append(f'ID {name} khác bản sinh lại từ sổ (số liệu bị sửa hay sinh từ nguồn khác)' if got is not None else f'ID {name} missing')
    checked = pr.check_files(Path(report_dir) / AGG_FILES[0], Path(report_dir) / AGG_FILES[1])
    problems += checked['problems']
    return {'result': 'refused' if problems else 'pass', 'problems': problems, 'owner_acceptance': False, 'pilot_evidence': False}


# ---- W38d: re-run plan checker (T45e) ---------------------------------------------------------------------------------

def affected_items(analysis):
    from onecrew.dependency_core import affected_tasks
    items = analysis['items']
    changed = set(analysis['changed_files'])
    mapped = {p for row in items for p in row['owned']}
    outside = sorted(changed - mapped)
    if outside:
        return {row['id'] for row in items}, outside                     # E21: a file outside the map affects every item
    selected = [row['id'] for row in items if set(row['owned']) & changed]
    return (affected_tasks({'tasks': items}, selected) if selected else set()), []


def check_rerun_plan(analysis, plan=None):
    """Pure. {'result': 'pass'|'refused', 'problems': [...], 'affected_items', 'rerun_required', 'outside_map'}."""
    problems = []
    result = {'result': 'refused', 'problems': problems, 'affected_items': [], 'rerun_required': [], 'outside_map': [],
              'owner_acceptance': False, 'pilot_evidence': False}
    try:
        require(isinstance(analysis, dict) and analysis.get('schema') == 1, 'INPUT: analysis schema must be 1')
        source, target = identity(analysis.get('source')), identity(analysis.get('target'))
        items = analysis.get('items')
        require(isinstance(items, list) and items and all(isinstance(r, dict) and r.get('id') and isinstance(r.get('owned'), list)
                and isinstance(r.get('depends_on'), list) for r in items), 'INPUT: dependency map items missing')
        require(isinstance(analysis.get('changed_files'), list) and all(isinstance(x, str) for x in analysis['changed_files']), 'INPUT: changed_files missing')
        jobs = analysis.get('jobs')
        ids = {r['id'] for r in items}
        require(isinstance(jobs, list) and jobs and all(isinstance(j, dict) and j.get('id') and isinstance(j.get('items'), list) and j['items']
                and set(j['items']) <= ids for j in jobs) and len({j['id'] for j in jobs}) == len(jobs), 'INPUT: pilot jobs must each name known items')
    except (ValueError, KeyError, TypeError) as exc:
        problems.append(str(exc))
        return result
    if not (isinstance(plan, dict) and plan):
        problems.append('kế thừa không có phân tích: the plan to check is missing')
        return result
    try:
        affected, outside = affected_items(analysis)
    except Exception as exc:                                   # dependency_core raises LedgerError on an invalid selection
        problems.append(f'INPUT: impact analysis failed: {exc}')
        return result
    required = sorted(j['id'] for j in jobs if set(j['items']) & affected)
    result.update(affected_items=sorted(affected), rerun_required=required, outside_map=outside)
    rerun = plan.get('rerun_jobs')
    if not (isinstance(rerun, list) and all(isinstance(x, str) for x in rerun) and len(set(rerun)) == len(rerun)):
        problems.append('INPUT: plan.rerun_jobs must be a list of distinct job ids')
        return result
    every = sorted(j['id'] for j in jobs)
    unknown = sorted(set(rerun) - set(every))
    if unknown:
        problems.append(f'INPUT: plan names jobs that are not pilot jobs: {", ".join(unknown)}')
    if sorted(rerun) == every and len(required) < len(every):
        problems.append(f'chạy lại toàn bộ pilot không theo phân tích: {len(every)} việc chạy lại, chỉ {len(required)} bị ảnh hưởng ({", ".join(required) or "không việc nào"})')
    else:
        skipped = sorted(set(required) - set(rerun))
        extra = sorted((set(rerun) & set(every)) - set(required))
        if skipped:
            problems.append(f'bỏ qua việc bị ảnh hưởng: {", ".join(skipped)}')
        if extra:
            problems.append(f'chạy lại việc không bị ảnh hưởng (không theo phân tích): {", ".join(extra)}')
    for row in plan.get('kept_evidence', analysis.get('evidence', [])) if isinstance(plan.get('kept_evidence', analysis.get('evidence', [])), list) else []:
        if isinstance(row, dict) and row.get('wheel_sha256') != source['wheel_sha256']:
            problems.append(f'hash bằng chứng bị đổi: việc {row.get("job")} giữ {source["wheel_sha256"]} nhưng nay ghi {row.get("wheel_sha256")}')
    supplements = plan.get('supplements', {})
    if not isinstance(supplements, dict):
        problems.append('INPUT: plan.supplements must be an object')
    else:
        for item in sorted(affected):
            if not (isinstance(supplements.get(item), list) and supplements[item]):
                problems.append(f'mục bị ảnh hưởng thiếu kiểm bổ sung: {item}')
    if source == target:
        problems.append('đối chiếu sai cặp hash: nguồn và đích cùng một artifact')
    result['result'] = 'refused' if problems else 'pass'
    return result


# ---- W38d: run the supplementary checks on the final artifact ----------------------------------------------------------

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def run_supplements(spec, root, out_dir, now=utc_now):
    """Run each named supplementary check on the final artifact and write its receipt. Refuses (raises ValueError, nothing run) when the
    wheel on disk does not match the artifact or the receipt given. Returns {'receipts': {check id: ref}, 'results': {...}}."""
    require(isinstance(spec, dict) and spec.get('schema') == 1, 'spec: schema must be 1')
    require(spec.get('mode') in ('fixture', 'real'), 'spec: mode must be fixture|real')
    fixture = spec['mode'] == 'fixture'
    art = spec.get('artifact')
    final = identity(art)
    require(isinstance(art.get('wheel'), str) and art['wheel'], 'spec: artifact.wheel path missing')
    wheel = Path(root) / art['wheel']
    actual = hashlib.sha256(wheel.read_bytes()).hexdigest()
    require(actual == final['wheel_sha256'], f'wheel content hash {actual} differs from the artifact {final["wheel_sha256"]}')
    ev = Evidence(root, fixture)
    given = ev.read(spec.get('final_receipt'))
    require(identity(given) == final, f'wheel sha of the receipt given ({given.get("wheel_sha256")}) differs from the final artifact ({final["wheel_sha256"]})')
    checks = spec.get('checks')
    require(isinstance(checks, list) and checks and all(isinstance(c, dict) and c.get('id') and c.get('item') and isinstance(c.get('argv'), list)
            and c['argv'] and all(isinstance(a, str) for a in c['argv']) for c in checks), 'spec: checks need id, item and argv')
    require(len({c['id'] for c in checks}) == len(checks), 'spec: duplicate check id')
    affected = spec.get('affected', [])
    require(isinstance(affected, list) and all(isinstance(a, str) for a in affected), 'spec: affected must be a list of item ids')
    missing = sorted(set(affected) - {c['item'] for c in checks})
    require(not missing, f'mục bị ảnh hưởng thiếu kiểm bổ sung: {", ".join(missing)}')
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    refs, results = {}, {}
    env_note = {'ONECREW_FINAL_WHEEL': str(wheel), 'ONECREW_FINAL_WHEEL_SHA256': final['wheel_sha256']}
    for check in checks:
        started, exit_code, reason, digest = time.monotonic(), None, None, hashlib.sha256(b'').hexdigest()
        try:
            import os
            proc = subprocess.run(check['argv'], cwd=str(root), capture_output=True, timeout=check.get('timeout', 120), shell=False,
                                  env=dict(os.environ, **env_note))
            exit_code, digest = proc.returncode, hashlib.sha256(proc.stdout + b'\0' + proc.stderr).hexdigest()
            outcome = 'pass' if exit_code == check.get('expect_exit', 0) else 'fail'
        except subprocess.TimeoutExpired:
            outcome, reason = 'blocked', 'timeout'
        except OSError as exc:
            outcome, reason = 'blocked', f'cannot start: {type(exc).__name__}'
        receipt = {'kind': 'supplement', 'item': check['item'], 'result': outcome, **final, 'at': now(), 'simulated': fixture,
                   'provenance': {'kind': 'fixture' if fixture else 'real', 'source': 'wfkit.pilot_tools supp-run'},
                   'check': {'id': check['id'], 'argv': check['argv'], 'exit_code': exit_code, 'output_sha256': digest,
                             'seconds': round(time.monotonic() - started, 3)}}
        if reason:
            receipt['reason'] = reason
        raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
        path = out / f'supplement-{check["id"]}.json'
        path.write_bytes(raw)
        ref = {'path': str(path.relative_to(root)).replace('\\', '/') if path.is_relative_to(Path(root)) else str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
        read_back = ev.read(ref)                                # the receipt must satisfy the final-gate reader
        require(identity(read_back) == final, 'receipt does not carry the final artifact hash')
        refs[check['id']], results[check['id']] = ref, outcome
    return {'receipts': refs, 'results': results, 'artifact': final, 'owner_acceptance': False, 'pilot_evidence': False,
            'all_pass': all(v == 'pass' for v in results.values())}


# ---- CLI ---------------------------------------------------------------------------------------------------------------

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    rp = sub.add_parser('report')
    rp.add_argument('--kind', choices=('interim', 'aggregate'), default='interim',
                    help='interim (T35b, one ledger: --project/--state-root) or aggregate (T35c, ledgers named in the manifest).')
    rp.add_argument('--project', type=Path)
    rp.add_argument('--state-root', type=Path)
    rp.add_argument('--manifest', type=Path, required=True)
    rp.add_argument('--out-dir', type=Path, required=True)
    rv = sub.add_parser('verify')
    rv.add_argument('--kind', choices=('aggregate',), default='aggregate')
    rv.add_argument('--manifest', type=Path, required=True)
    rv.add_argument('--report-dir', type=Path, required=True)
    rc = sub.add_parser('rerun-check')
    rc.add_argument('analysis', type=Path)
    rs = sub.add_parser('supp-run')
    rs.add_argument('spec', type=Path)
    rs.add_argument('--root', type=Path, default=None, help='Directory the spec paths are relative to (default: the spec directory).')
    rs.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            result = verify_aggregate(load(args.manifest), args.report_dir, base=args.manifest.parent)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result['result'] == 'pass' else 1
        if args.command == 'report':
            manifest = load(args.manifest)
            if not isinstance(manifest, dict) or manifest.get('kind') != args.kind:
                raise ReportError(f'manifest kind {manifest.get("kind") if isinstance(manifest, dict) else None!r} differs from --kind {args.kind}')
            if args.kind == 'aggregate':
                report, text = generate_aggregate(manifest, base=args.manifest.parent)
                files = write_named(report, text, args.out_dir, AGG_FILES)
            else:
                from onecrew.v2.lint import ReadOnlyLedger
                if not (args.project and args.state_root):
                    raise ReportError('report --kind interim needs --project and --state-root')
                report, text = generate_interim(ReadOnlyLedger(args.project, args.state_root), manifest)
                files = write_report(report, text, args.out_dir)
            checked = pr.check_report(report, text)
            print(json.dumps({'written': [str(f) for f in files], 'check': checked}, ensure_ascii=False, sort_keys=True))
            return 0 if checked['result'] == 'pass' else 1
        if args.command == 'rerun-check':
            data = load(args.analysis)
            result = check_rerun_plan(data, data.get('plan') if isinstance(data, dict) else None)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result['result'] == 'pass' else 1
        root = args.root or args.spec.parent
        result = run_supplements(load(args.spec), root, args.out_dir)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result['all_pass'] else 1
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'result': 'refused', 'problems': [f'{type(exc).__name__}: {exc}']}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
