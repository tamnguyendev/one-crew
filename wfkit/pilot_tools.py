"""Local tools that close the LOCAL part of pilot tasks W38b, W38c, W38d (no pilot, provider or owner decision is involved).

Run ``python -m wfkit.pilot_tools <command> ...``:

* ``report``      -- W38b/W38c interim (T35b) pilot-report GENERATOR. Reads a pilot ledger READ-ONLY (``onecrew.v2.metrics.measure_all``
  for the figures, ``onecrew.v2.outcome.outcomes`` for the outcome rows) and a manifest naming the three pilot jobs, and writes
  ``interim-report.json`` + ``interim-report.md`` that ``wfkit.pilot_report.check_report`` accepts. Deterministic (no clock, no
  random). Whatever has no source stays ``không có dữ liệu`` (never 0); group B comes only from the owner's notes, group C only from
  the chat log, both given in the manifest as ``observations``. Provenance (state root, commit, wheel sha, fixture|real) is written
  into both files; the report never claims acceptance and never claims pilot evidence. Kind ``aggregate`` (T35c, ten jobs) is NOT
  generated here: it needs the PL-B sources (skip records, providers, continuation trial) that exist only after a real pilot.
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
from datetime import datetime, timezone
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
    need(m.get('kind') == 'interim', 'manifest: only kind "interim" (T35b) is generated here; the aggregate (T35c) needs a real PL-B')
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


def finish(metric, n):
    k = len(pr.values(metric))
    metric.update(k=k, n=n, status=pr.status_for(k, n), label=pr.label_for(k, n, 'interim'))
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
    rp.add_argument('--project', type=Path, required=True)
    rp.add_argument('--state-root', type=Path, required=True)
    rp.add_argument('--manifest', type=Path, required=True)
    rp.add_argument('--out-dir', type=Path, required=True)
    rc = sub.add_parser('rerun-check')
    rc.add_argument('analysis', type=Path)
    rs = sub.add_parser('supp-run')
    rs.add_argument('spec', type=Path)
    rs.add_argument('--root', type=Path, default=None, help='Directory the spec paths are relative to (default: the spec directory).')
    rs.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'report':
            from onecrew.v2.lint import ReadOnlyLedger
            report, text = generate_interim(ReadOnlyLedger(args.project, args.state_root), load(args.manifest))
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
