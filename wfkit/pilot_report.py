"""Read-only checker for the two pilot reports (kit task WKPL; T35b and T35c).

Run ``python -m wfkit.pilot_report report.json report.md``. Nothing is written,
no ledger is opened, no provider or pilot job runs. The generator of both kinds
is ``wfkit.pilot_tools report``; no real pilot has run, so these RULES are proven
on fixture and synthetic reports only. The result always carries ``owner_acceptance: False`` and
``pilot_evidence: False``: a report (whatever it says, "nghiệm thu" included)
is never owner acceptance nor evidence that a real pilot happened.

Input = a JSON document plus its rendered Markdown text. JSON schema (schema=1):

* ``schema`` 1; ``kind`` "interim" (T35b, after PL-A, N=3) or "aggregate"
  (T35c, after PL-B, N=10); ``phase`` "PL-A" / "PL-B" (must match kind);
  ``simulated`` bool; ``jobs`` list of N distinct job IDs.
* ``metrics``: list of {id, group, source, n, k, status, label, summary, cells,
  [target, target_status, skip_leak_part]}. ``id`` from CATALOG (00 §9.1; group
  fixed by the catalog). ``cells`` maps every job to {"value": number,
  [derived_from]} or {"no_data": reason}. ``summary`` is {"value", "unit"} or
  {"no_data": reason}. ``status``: đủ (k=N) / thiếu (0<k<N) / không có (k=0).
  ``label``: interim "giữa kỳ k/3"; aggregate the 00 §9.3 words.
* ``owner_notes_missing``: {metric id (group B): [jobs without owner notes]}.
* ``outcomes``: {roots: [{root, job, plan, revision, final_outcome, outcome_rows}],
  missing: [root], target: 0}.
* interim only: ``ledger_columns`` {command, ledger_sha256, hand_filled,
  rows: [{job, column (decision|intervention|outcome), ledger, chat, match, [reason]}]};
  ``desktop_window`` {event_id, emitted_at, shown_at, delivery_status}.
* aggregate only: ``tiers`` {tier1: {comparisons: [{metric, baseline_count,
  baseline_jobs, baseline_per_job, pilot_count, pilot_jobs, pilot_per_job,
  source, parts, computed_from: [job], per_job: {job: sum of parts}, missing:
  {part: [job]}, pilot_denominator, complete}], limits: [str]} (a composite is
  counted over ONE job set: the jobs with a value for every part; a job missing a
  part is out of numerator and denominator and named on the line, which then says
  "so sánh một phần"), tier2: {metrics: [ids], conclusion},
  tier3: {conclusion, comparison_group}}; ``owner_decisions`` {actions: [{job, at,
  verb, kind, sources}], mismatches: [{job, at, ledger, chat, reason}],
  per_job: {job: {kind: count}}, ac1: {max_per_job, outside_u1_u4, status}};
  ``skip_leak`` {skip_count, links: [{job, finding, skip_record, ...}], invalid_links,
  source, target 0} (links read from the finding_skip_link decision records, each
  re-validated against its HD-20 SKIP record; a link names a SKIP record of its own
  job, a defect counts once, and the "SKIP (HD-20):" line shows count/SKIP, target,
  source and every "finding F <- SKIP S");
  ``manual_fixes`` {decision_log_rows: [{at, job, before, after, reason}],
  interventions, [mismatch_reason]}; ``providers`` [{provider, calls, failures,
  reasons: {"hạn mức": n, "lỗi công cụ": n}, inconclusive_receipts}];
  ``continuation_trial`` {job, tool, package_sha256, answers: [{question,
  correct}], grader: {identity, model}, coordinator_model, result}.

Markdown: each metric is rendered on ONE line containing its id in backticks,
"k/N", the status, the label, "không có dữ liệu" when the summary has no data,
and "<job>: không có dữ liệu: thiếu ghi chép của chủ sở hữu" for each job
listed in owner_notes_missing. Aggregate: the first two non-heading lines are
"AC5 — năng lực đo: đạt|không đạt ..." and "Baseline: m chỉ số đủ 10/10 (ids),
n thiếu (ids), p không có (ids)"; sections "## Tầng 1/2/3" exist.

Readings (narrowest, from 05 T35 and 00 §9.1–§9.3):
* E7 interim: every catalog metric except skip_leak (needs HD-20 of R05, T35c)
  has value or no-data, k/3, source, group, status; no line and no label
  contains the word "baseline". Group A completeness is NOT enforced at T35b
  (E7 does not ask it; AC5 is an aggregate header).
* E25/E31: every root has exactly one outcome row for its final outcome; a
  root with 0 rows must be listed under ``missing``; a non-empty list is a
  failed expectation (target 0), so the report is refused, naming the roots.
* E26: 3 jobs x 3 columns rows; match must equal ledger==chat; a mismatched row
  carries both sources and a reason; hand_filled must be 0. Structural only:
  the checker cannot re-read the pilot ledger.
* E28: one desktop window record with delivery status "đã giao".
* E6/E33/E36: label "đã lập baseline (10/10)" only when k=10, else
  "baseline một phần (k/10)" or "chưa lập baseline (0/10)"; B/C short never
  blocks. E32: group A k<10 -> AC5 "không đạt" naming job and metric, and the
  report is refused (the gate cannot pass), even when the header says so.
* E35 (m1/m3): k=0 summary must be no-data (never "0 phút"); a job listed as
  missing owner notes must have a no-data cell (never 0); k must equal the
  number of value cells. E37 (m4): "baseline đầy đủ", or "đã lập baseline"
  outside a 10/10 metric line, while a metric is short. E12 (m5): any tier-3
  conclusion other than "chưa kết luận giảm" (the comparison group of E1 only
  exists after the programme). E11: a tier-1 comparison carrying a time
  conclusion, or a line citing 20/10 that claims a time reduction.
* E20–E24, E29, E30, E38 as structural/consistency checks on their sections.
  E23: owner minutes never ``derived_from`` wait time or event gaps.
* Target status (E20–E22, E29, E30): "đạt" only when every job has data and the
  total is 0; a positive total is "không đạt"; a zero total over fewer than N
  jobs is "không có dữ liệu" (a missing sample never passes a target).
* Tier 1 with k = 0: the comparison carries ``no_data`` and no pilot count/rate.
* Identity of an aggregate (W38c, round 6 P2; rules prefixed "ID"):
  ``provenance`` {kind synthetic|real, generator, ledgers: [{id, state_root, commit,
  wheel_sha256, synthetic, roots, excluded: [{root, reason}]}]}; ``jobs_detail``
  one row per job {job, ledger, root, status, wheel_sha256, ...} or {job, skipped};
  each metric lists ``computed_from`` [{job, ledger, root}] (exactly the jobs with a
  value) and ``missing`` (the others: still in the denominator); the summary equals
  the sum of its cells; ``figures_sha256`` = figures_digest(report). Refused: a
  duplicate job row or root, a root outside the ledgers named, an unaccounted plan
  root of a pilot ledger (wrong scope), a job wheel that differs from its ledger
  (wrong artifact), a job status that differs from its outcome row (contradiction),
  a skipped job with a value, a figure changed after generation, and a synthetic
  source claiming a real pilot, pilot evidence or acceptance.
y1/y2 belong to T45e (script kiểm đối chiếu), not T35, and are not checked here.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

CATALOG = {
    'time_to_usable': 'A', 'exec_time': 'A', 'wait_time': 'A', 'owner_minutes': 'B',
    'owner_decisions': 'A', 'actual_actions': 'C', 'rework_rounds': 'A',
    'amend_authoring_error': 'C', 'amend_requirement_change': 'C', 'amend_emergent': 'C',
    'owner_retries': 'C', 'false_pass': 'A', 'skip_leak': 'A', 'owner_keystrokes': 'C',
    'ledger_manual_fixes': 'C', 'noise_stop_hook': 'A', 'noise_notifications': 'A',
    'wrong_scope_block': 'A', 'missed_wait_1h': 'A', 'missed_wait_1h_owner': 'B', 'verify_cost': 'A',
}
TARGETS = {'noise_stop_hook': 0, 'noise_notifications': 0, 'missed_wait_1h': 0, 'missed_wait_1h_owner': 0,
           'false_pass': 0, 'wrong_scope_block': 0, 'skip_leak': 0, 'ledger_manual_fixes': 0,
           'amend_authoring_error': 0, 'amend_emergent': '≈0'}
TIER1 = {'owner_keystrokes': (33, ('owner_keystrokes',)), 'amend_total': (23, ('amend_authoring_error',
         'amend_requirement_change', 'amend_emergent')), 'noise_stop_hook': (81, ('noise_stop_hook',)),
         'false_pass': (2, ('false_pass',))}
TIER2 = frozenset(('time_to_usable', 'owner_minutes', 'wait_time', 'rework_rounds', 'actual_actions', 'owner_retries'))
LIMITS = ('nhóm việc khác', 'cỡ mẫu', 'cách đếm')
KINDS = ('root_approval', 'acceptance', 'U1', 'U2', 'U3', 'U4', 'other')
OUTCOMES = ('accepted', 'stopped_with_report', 'failed')
QUESTIONS = ('bước kế', 'việc của chủ sở hữu', 'việc không được làm', 'mốc thiếu', 'câu hỏi mở')
NO_NOTES = 'thiếu ghi chép của chủ sở hữu'
NO_REDUCTION = 'chưa kết luận giảm'
AC5 = 'AC5 — năng lực đo: '
BASELINE_RE = re.compile(r'^Baseline: (\d+) chỉ số đủ 10/10 \(([^)]*)\), (\d+) thiếu \(([^)]*)\), (\d+) không có \(([^)]*)\)$')
NO_DATA_TARGET = 'không có dữ liệu'
SYNTHETIC_LINE = 'dữ liệu tổng hợp (synthetic), không phải pilot thật'
SHA256_RE = re.compile(r'[0-9a-f]{64}')
COMMIT_RE = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})')


def figures_digest(report):
    """sha256 of the report's own content (everything but this digest). The generator writes it; the checker recomputes it."""
    body = {k: v for k, v in report.items() if k != 'figures_sha256'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def target_status(target, total, k, n):
    """Status of a metric against its target: a missing sample never makes "đạt"."""
    if total > 0 and target == 0:
        return 'không đạt'
    if k < n and total == 0:
        return NO_DATA_TARGET
    return 'đạt' if total == 0 else None                       # '≈0' with a positive total: the report states it


def require(ok, message):
    if not ok:
        raise ValueError(message)


def status_for(k, n):
    return 'đủ' if k == n else ('không có' if k == 0 else 'thiếu')


def label_for(k, n, kind):
    if kind == 'interim':
        return f'giữa kỳ {k}/{n}'
    return {'đủ': f'đã lập baseline ({k}/{n})', 'thiếu': f'baseline một phần ({k}/{n})',
            'không có': f'chưa lập baseline (0/{n})'}[status_for(k, n)]


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def timestamp(value):
    require(isinstance(value, str), 'timestamp missing')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None, 'timestamp needs timezone')
    return result


def values(metric):
    return {j: c['value'] for j, c in metric['cells'].items() if 'value' in c}


class Checker:
    def __init__(self, report, text):
        self.report, self.text, self.problems = report, text, []
        self.lines = text.splitlines()

    def add(self, message):
        if message not in self.problems:
            self.problems.append(message)

    def check(self, fn, *args):
        try:
            fn(*args)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            self.add(str(exc) if isinstance(exc, ValueError) else f'INPUT: {type(exc).__name__}: {exc}')

    def metric_line(self, mid):
        found = [line for line in self.lines if f'`{mid}`' in line]
        return found[0] if len(found) == 1 else None

    # --- top level -----------------------------------------------------------------------------------
    def top(self):
        r = self.report
        require(r.get('schema') == 1, 'INPUT: schema must be 1')
        require(r.get('kind') in ('interim', 'aggregate'), 'INPUT: kind must be interim|aggregate')
        self.kind = r['kind']
        self.n = 3 if self.kind == 'interim' else 10
        require(r.get('phase') == ('PL-A' if self.kind == 'interim' else 'PL-B'), 'INPUT: phase does not match kind')
        require(type(r.get('simulated')) is bool, 'INPUT: simulated must be declared')
        jobs = r.get('jobs')
        require(isinstance(jobs, list) and all(isinstance(j, str) and j for j in jobs) and len(set(jobs)) == len(jobs)
                and len(jobs) == self.n, f'INPUT: jobs must be {self.n} distinct IDs')
        self.jobs = jobs
        metrics = r.get('metrics')
        require(isinstance(metrics, list) and all(isinstance(m, dict) for m in metrics), 'INPUT: metrics missing')
        ids = [m.get('id') for m in metrics]
        require(len(ids) == len(set(ids)), 'INPUT: duplicate metric id')
        self.metrics = {m['id']: m for m in metrics}

    # --- per metric (E7 / E6 / E33 / E35 / E36) ------------------------------------------------------
    def metric(self, m):
        mid, eid = m.get('id'), 'E7' if self.kind == 'interim' else 'E6'
        require(mid in CATALOG, f'{eid} unknown metric {mid!r}')
        require(m.get('group') == CATALOG[mid], f'{eid} {mid}: group must be {CATALOG[mid]} (00 §9.1)')
        require(isinstance(m.get('source'), str) and m['source'].strip(), f'{eid} {mid}: source missing')
        require(CATALOG[mid] != 'A' or m['source'].startswith('sổ'), f'{eid} {mid}: group A source must be the ledger (sổ)')
        require(m.get('n') == self.n, f'{eid} {mid}: denominator must be k/{self.n}')
        cells = m.get('cells')
        require(isinstance(cells, dict) and set(cells) == set(self.jobs), f'{eid} {mid}: one cell per job required')
        for job, cell in cells.items():
            ok = isinstance(cell, dict) and (('value' in cell) != ('no_data' in cell))
            require(ok, f'{eid} {mid} {job}: cell needs a value or "không có dữ liệu"')
            if 'value' in cell:
                require(number(cell['value']) and cell['value'] >= 0, f'{eid} {mid} {job}: value must be a number')
            else:
                require(isinstance(cell['no_data'], str) and cell['no_data'], f'{eid} {mid} {job}: no-data needs a reason')
            if mid == 'owner_minutes':
                require(cell.get('derived_from') not in ('wait_time', 'event_gap'),
                        f'E23 owner_minutes {job}: phút chủ động suy ra từ {cell.get("derived_from")} (cấm)')
        k = m.get('k')
        require(isinstance(k, int) and 0 <= k <= self.n, f'{eid} {mid}: k must be 0..{self.n}')
        summary = m.get('summary')
        require(isinstance(summary, dict) and ('value' in summary) != ('no_data' in summary), f'{eid} {mid}: summary missing')
        if k == 0 and 'value' in summary:
            self.add(f'E35 ô không có dữ liệu hiện {summary["value"]} {summary.get("unit", "")}'.rstrip()
                     + f': {mid} 0/{self.n} phải ghi "không có dữ liệu"')
        require(len(values(m)) == k, f'E35 ô không có dữ liệu hiện số: {mid} có {len(values(m))} ô giá trị nhưng mẫu số {k}/{self.n}')
        require(m.get('status') == status_for(k, self.n), f'{eid} {mid}: status must be {status_for(k, self.n)!r} for {k}/{self.n}')
        label, want = m.get('label'), label_for(k, self.n, self.kind)
        if self.kind == 'interim':
            require('baseline' not in str(label).lower(), f'E7 {mid}: báo cáo giữa kỳ không ghi baseline')
        elif isinstance(label, str) and label.startswith('đã lập baseline') and k < self.n:
            raise ValueError(f'E36 baseline khi mẫu số {k}/{self.n}: {mid}')
        require(label == want, f'{eid} {mid}: label must be {want!r}')
        line = self.metric_line(mid)
        require(line is not None, f'{eid} {mid}: exactly one rendered line required')
        require(f'{k}/{self.n}' in line and m['status'] in line and want in line, f'{eid} {mid}: rendered line lacks k/N, status or label')
        if 'no_data' in summary:
            require('không có dữ liệu' in line, f'{eid} {mid}: rendered line must say "không có dữ liệu"')
        if k == 0 and re.search(r'(?<![\d/.,])0\s*phút', line):
            self.add(f'E35 ô không có dữ liệu hiện 0: {mid} dòng 0/{self.n} ghi "0 phút"')
        if self.kind == 'aggregate' and mid in TARGETS:
            require(m.get('target') == TARGETS[mid], f'{self.target_eid(mid)} {mid}: target must be {TARGETS[mid]}')
            total = sum(values(m).values())
            want_status = target_status(TARGETS[mid], total, k, self.n)
            if want_status is None:
                want_status = m.get('target_status') if m.get('target_status') in ('đạt', 'không đạt') else 'không đạt'
            require(m.get('target_status') in ('đạt', 'không đạt', NO_DATA_TARGET) and m['target_status'] == want_status,
                    f'{self.target_eid(mid)} {mid}: status vs target must be {want_status!r}')

    @staticmethod
    def target_eid(mid):
        return {'false_pass': 'E22', 'wrong_scope_block': 'E22', 'skip_leak': 'E29', 'ledger_manual_fixes': 'E30',
                'amend_authoring_error': 'E21', 'amend_emergent': 'E21'}.get(mid, 'E20')

    def metrics_all(self):
        required = set(CATALOG) - ({'skip_leak'} if self.kind == 'interim' else set())
        missing = sorted(required - set(self.metrics))
        if missing:
            self.add(('E7' if self.kind == 'interim' else 'E6') + f' metrics missing: {", ".join(missing)}')
            for mid, eid in (('ledger_manual_fixes', 'E30'), ('skip_leak', 'E29'), ('false_pass', 'E22')):
                if mid in missing and self.kind == 'aggregate':
                    self.add(f'{eid} dòng {mid} bị bỏ khỏi báo cáo')
        for m in self.metrics.values():
            self.check(self.metric, m)

    def owner_notes(self):
        missing = self.report.get('owner_notes_missing', {})
        require(isinstance(missing, dict), 'INPUT: owner_notes_missing must be an object')
        for mid, jobs in missing.items():
            require(CATALOG.get(mid) == 'B' and mid in self.metrics, f'INPUT: owner_notes_missing names non-B metric {mid}')
            line = self.metric_line(mid) or ''
            for job in jobs:
                cell = self.metrics[mid]['cells'].get(job, {})
                if 'value' in cell:
                    self.add(f'E35 ô không có dữ liệu hiện {cell["value"]}: {mid} {job} (thiếu ghi chép của chủ sở hữu)')
                elif NO_NOTES not in cell.get('no_data', ''):
                    self.add(f'E23 {mid} {job}: lý do phải là "{NO_NOTES}"')
                if f'{job}: không có dữ liệu: {NO_NOTES}' not in line:
                    self.add(f'E23 {mid} {job}: ô phải ghi "không có dữ liệu: {NO_NOTES}"')

    # --- outcomes (E25 interim, E31 aggregate) -------------------------------------------------------
    def outcomes(self):
        eid = 'E25' if self.kind == 'interim' else 'E31'
        o = self.report.get('outcomes')
        require(isinstance(o, dict) and isinstance(o.get('roots'), list) and o['roots'], f'{eid} outcomes section missing')
        require(o.get('target') == 0, f'{eid} outcomes: target must be 0')
        zero = []
        for row in o['roots']:
            require(row.get('job') in self.jobs and row.get('root') and row.get('plan') and isinstance(row.get('revision'), int),
                    f'{eid} outcome row needs root, job, plan, revision')
            require(row.get('final_outcome') in OUTCOMES, f'{eid} {row["root"]}: final outcome must be one of {OUTCOMES}')
            rows = row.get('outcome_rows')
            require(isinstance(rows, int) and rows >= 0, f'{eid} {row["root"]}: outcome_rows missing')
            if rows > 1:
                self.add(f'{eid} {row["root"]}: khoá (plan, revision, kết cục) có {rows} dòng learning.outcome')
            if rows == 0:
                zero.append(row['root'])
        require(set(self.jobs) <= {r['job'] for r in o['roots']}, f'{eid} every job needs its root outcome')
        listed = o.get('missing')
        require(isinstance(listed, list) and sorted(listed) == sorted(zero), f'{eid} root thiếu outcome không được liệt kê đúng: {sorted(zero)}')
        line = next((l for l in self.lines if l.startswith('Root thiếu outcome:')), None)
        require(line is not None and all(r in line for r in zero), f'{eid} dòng "Root thiếu outcome:" missing')
        if zero:
            self.add(f'{eid} root thiếu learning.outcome: {", ".join(sorted(zero))} (mục tiêu 0)')

    # --- interim only --------------------------------------------------------------------------------
    def no_baseline_text(self):
        for line in self.lines:
            require('baseline' not in line.lower(), f'E7 báo cáo giữa kỳ không ghi baseline: {line.strip()[:80]}')

    def ledger_columns(self):
        lc = self.report.get('ledger_columns')
        require(isinstance(lc, dict), 'E26 ledger_columns missing')
        require(isinstance(lc.get('command'), str) and lc['command'] and re.fullmatch(r'[0-9a-f]{64}', str(lc.get('ledger_sha256'))),
                'E26 ledger command and ledger hash required')
        rows = lc.get('rows')
        require(isinstance(rows, list), 'E26 rows missing')
        keys = [(r.get('job'), r.get('column')) for r in rows]
        want = {(j, c) for j in self.jobs for c in ('decision', 'intervention', 'outcome')}
        require(len(keys) == len(set(keys)) and set(keys) == want, 'E26 need one row per job and column (3 x 3)')
        for r in rows:
            require(r.get('ledger') is not None, f'E26 {r["job"]} {r["column"]}: ledger value missing (not taken by code)')
            require(r.get('match') is (r.get('ledger') == r.get('chat')), f'E26 {r["job"]} {r["column"]}: match flag inconsistent')
            if not r['match']:
                require(r.get('chat') is not None and isinstance(r.get('reason'), str) and r['reason'],
                        f'E26 {r["job"]} {r["column"]}: dòng lệch phải ghi cả hai nguồn và lý do')
        require(lc.get('hand_filled') == 0, f'E26 số ô điền tay phải = 0 (got {lc.get("hand_filled")})')

    def desktop_window(self):
        d = self.report.get('desktop_window')
        require(isinstance(d, dict) and isinstance(d.get('event_id'), str) and d['event_id'], 'E28 desktop window record missing')
        require(timestamp(d.get('shown_at')) >= timestamp(d.get('emitted_at')), 'E28 window shown before the event')
        require(d.get('delivery_status') == 'đã giao', 'E28 notification status must be "đã giao"')
        require(any(d['event_id'] in l and 'Cửa sổ Windows' in l for l in self.lines), 'E28 report line about the desktop window missing')

    # --- aggregate only ------------------------------------------------------------------------------
    def header(self):
        body = [l.strip() for l in self.lines if l.strip() and not l.lstrip().startswith('#')]
        require(len(body) >= 2, 'E34 header lines missing')
        ac5, base = body[0], body[1]
        groups = {'đủ': [], 'thiếu': [], 'không có': []}
        for mid, m in sorted(self.metrics.items()):
            if isinstance(m.get('k'), int):
                groups[status_for(m['k'], self.n)].append(mid)
        a_short = [(job, mid) for mid, m in sorted(self.metrics.items()) if CATALOG.get(mid) == 'A'
                   for job in self.jobs if 'value' not in m.get('cells', {}).get(job, {'value': 0})]
        for job, mid in a_short:
            self.add(f'E32 AC5 — năng lực đo: không đạt: nhóm A thiếu {job} {mid} (lỗi bộ ghi)')
        others = [p for p in self.problems if not p.startswith(('E32', 'E34'))]
        ok = not a_short and not others
        require(ac5.startswith(AC5), 'E34 first line must be "AC5 — năng lực đo: đạt/không đạt"')
        verdict = ac5[len(AC5):]
        if ok:
            require(verdict == 'đạt', f'E34 AC5 line says {verdict!r} but the table gives đạt')
        else:
            require(verdict.startswith('không đạt'), 'E32 AC5 line says đạt but the report does not meet AC5')
            for job, mid in a_short:
                require(job in verdict and mid in verdict, f'E32 AC5 line must name {job} {mid}')
        match = BASELINE_RE.match(base)
        require(match, 'E34 second line must be "Baseline: m chỉ số đủ 10/10 (…), n thiếu (…), p không có (…)"')
        for i, key in enumerate(('đủ', 'thiếu', 'không có')):
            count, names = int(match.group(2 * i + 1)), [x.strip() for x in match.group(2 * i + 2).split(',') if x.strip()]
            require(count == len(groups[key]) and sorted(names) == groups[key],
                    f'E34 Baseline line {key}: says {count} ({", ".join(names)}), table has {len(groups[key])} ({", ".join(groups[key])})')

    def blanket_baseline(self):
        short = [mid for mid, m in self.metrics.items() if m.get('k') != self.n]
        metric_lines = {self.metric_line(mid): mid for mid in self.metrics}
        for line in self.lines:
            low = line.lower()
            if 'baseline đầy đủ' in low or ('đã lập baseline' in low and line not in metric_lines):
                if short:
                    self.add(f'E37 kết luận baseline đầy đủ khi còn chỉ số thiếu: {", ".join(sorted(short))}')
            elif 'đã lập baseline' in low and line in metric_lines:
                m = self.metrics[metric_lines[line]]
                if m.get('k') != self.n:
                    self.add(f'E36 baseline khi mẫu số {m.get("k")}/{self.n}: {metric_lines[line]}')

    def section(self, title):
        out, inside = [], False
        for line in self.lines:
            if line.startswith('## '):
                inside = line.startswith(f'## {title}')
                continue
            if inside:
                out.append(line)
        return out

    def tiers(self):
        t = self.report.get('tiers')
        require(isinstance(t, dict) and all(isinstance(t.get(x), dict) for x in ('tier1', 'tier2', 'tier3')), 'E6 three tiers required')
        for title in ('Tầng 1', 'Tầng 2', 'Tầng 3'):
            require(any(l.startswith(f'## {title}') for l in self.lines), f'E6 section "## {title}" missing')
        t1 = t['tier1']
        limits = ' '.join(t1.get('limits', []))
        require(all(x in limits for x in LIMITS), f'E6 tier 1 must state the limits: {", ".join(LIMITS)}')
        comps = t1.get('comparisons')
        require(isinstance(comps, list), 'E6 tier 1 comparisons missing')
        by = {c.get('metric'): c for c in comps}
        require(set(by) == set(TIER1) and len(by) == len(comps), f'E6 tier 1 compares exactly {", ".join(sorted(TIER1))}')
        for name, c in by.items():
            require('time_conclusion' not in c, f'E11 kết luận về thời gian từ số đếm 20/10: {name}')
            base, parts = TIER1[name]
            require(c.get('baseline_count') == base and c.get('baseline_jobs') == 11 and isinstance(c.get('source'), str) and c['source'],
                    f'E6 tier 1 {name}: baseline must be {base} trên 11 việc with source')
            require(abs(c.get('baseline_per_job', -1) - base / 11) < 0.01, f'E6 tier 1 {name}: per-job baseline rate wrong')
            ms = [self.metrics.get(p) for p in parts]
            require(all(ms), f'E6 tier 1 {name}: part metric missing ({", ".join(p for p, m in zip(parts, ms) if not m)})')
            # One job set (round 7 F3), recomputed here from the parts' per-job cells, not from the comparison's own numbers: the jobs
            # with a value for EVERY part; a job missing a part is out of numerator and denominator alike and is listed per part.
            cells = {p: m.get('cells') or {} for p, m in zip(parts, ms)}
            have = lambda p, j: isinstance(cells[p].get(j), dict) and 'value' in cells[p][j] and number(cells[p][j]['value'])
            frm = sorted(j for j in self.jobs if all(have(p, j) for p in parts))
            sums = {j: sum(cells[p][j]['value'] for p in parts) for j in frm}
            missing = {p: sorted(j for j in self.jobs if not have(p, j)) for p in parts}
            missing = {p: js for p, js in missing.items() if js}
            k, total = len(frm), sum(sums.values())
            require(isinstance(c.get('computed_from'), list) and sorted(c['computed_from']) == frm,
                    f'E6 tier 1 {name}: computed_from must be exactly the jobs with every part ({", ".join(frm) or "none"})')
            per_job = c.get('per_job')
            require(isinstance(per_job, dict) and sorted(per_job) == frm and all(number(per_job[j]) and abs(per_job[j] - sums[j]) < 0.011 for j in frm),
                    f'E6 tier 1 {name}: per_job must hold, for each job of computed_from, the sum of its part cells')
            require(c.get('missing') == missing, f'E6 tier 1 {name}: missing must list, per part, every job without data ({missing})')
            require(c.get('pilot_denominator') == self.n and c.get('complete') is (k == self.n),
                    f'E6 tier 1 {name}: pilot_denominator must be {self.n} and complete {k == self.n} ({k}/{self.n} jobs have every part)')
            line = next((l for l in self.lines if l.startswith(f'- {name}:')), None)
            require(line is not None, f'E6 tier 1 {name}: rendered line missing')
            if k:
                require(c.get('pilot_jobs') == k and number(c.get('pilot_count')) and abs(c['pilot_count'] - total) < 0.011,
                        f'E6 tier 1 {name}: pilot count/denominator must be {round(total, 2)} trên {k} việc (one job set)')
                require(number(c.get('pilot_per_job')) and abs(c['pilot_per_job'] - total / k) < 0.01, f'E6 tier 1 {name}: per-job pilot rate wrong')
                require(f'pilot {c["pilot_count"]} trên {k} việc' in line and f'tính từ {k}/{self.n} việc' in line,
                        f'E6 tier 1 {name}: rendered line must show the pilot count over {k} việc and "tính từ {k}/{self.n} việc"')
            else:
                require(c.get('pilot_jobs') == 0 and c.get('pilot_count') is None and c.get('pilot_per_job') is None
                        and isinstance(c.get('no_data'), str) and c['no_data'],
                        f'E35 tier 1 {name}: 0 việc có dữ liệu phải ghi "không có dữ liệu", không ghi số')
                require('không có dữ liệu' in line, f'E35 tier 1 {name}: rendered line must say "không có dữ liệu"')
            if k < self.n:
                require('so sánh một phần' in line and all(re.search(rf'\b{re.escape(j)}\b', line) for js in missing.values() for j in js),
                        f'E6 tier 1 {name}: {k}/{self.n} jobs: the line must say "so sánh một phần" and name the missing jobs')
            else:
                require('một phần' not in line, f'E6 tier 1 {name}: a full comparison must not be called partial')
        for line in self.lines:
            low = line.lower()
            if '20/10' in low and re.search(r'phút|thời gian|giờ', low) and re.search(r'giảm|nhanh|tiết kiệm|ít hơn', low) and 'không' not in low:
                self.add(f'E11 kết luận về thời gian từ số đếm 20/10: {line.strip()[:80]}')
        t2 = t['tier2']
        require(TIER2 <= set(t2.get('metrics', [])), f'E23 tier 2 must list {", ".join(sorted(TIER2))}')
        require(t2.get('conclusion') == NO_REDUCTION, f'E23 tier 2 must say "{NO_REDUCTION}"')
        require(any(NO_REDUCTION in l for l in self.section('Tầng 2')), f'E23 tier 2 text must say "{NO_REDUCTION}"')
        t3 = t['tier3']
        text3 = [l for l in self.section('Tầng 3') if 'giảm' in l.lower() and NO_REDUCTION not in l.lower()]
        if t3.get('conclusion') != NO_REDUCTION or text3:
            why = 'khi chưa có nhóm so sánh' if not t3.get('comparison_group') else 'trong báo cáo pilot (nhóm tương đương chỉ có sau E1)'
            self.add(f'E12 kết luận giảm {why}')
        require(any(NO_REDUCTION in l for l in self.section('Tầng 3')), f'E6 tier 3 text must say "{NO_REDUCTION}"')

    def false_pass(self):
        fp, sl = self.metrics.get('false_pass'), self.metrics.get('skip_leak')
        if fp and sl and 'value' in sl['summary']:
            require(fp.get('skip_leak_part') == sl['summary']['value'], 'E22 cho qua sai phải tách số lỗi lọt qua SKIP khỏi tổng')

    def decisions(self):
        d = self.report.get('owner_decisions')
        require(isinstance(d, dict), 'E24 owner_decisions missing')
        seen, counts = set(), {j: dict.fromkeys(KINDS, 0) for j in self.jobs}
        for a in d.get('actions', []):
            require(a.get('job') in self.jobs and a.get('kind') in KINDS and isinstance(a.get('verb'), str) and a['verb'],
                    'E24 action needs job, kind, verb')
            timestamp(a.get('at'))
            src = a.get('sources')
            require(isinstance(src, list) and src and set(src) <= {'ledger', 'chat'}, 'E24 action needs its source')
            key = (a['job'], a['at'], a['verb'])
            if key in seen:
                self.add(f'E24 hành động bị đếm hai lần: {a["job"]} {a["at"]} {a["verb"]}')
            seen.add(key)
            counts[a['job']][a['kind']] += 1
        for mm in d.get('mismatches', []):
            require(mm.get('ledger') is not None and mm.get('chat') is not None and mm.get('reason'),
                    'E24 dòng lệch phải ghi cả hai nguồn và lý do')
        per_job = d.get('per_job')
        require(isinstance(per_job, dict) and set(per_job) == set(self.jobs), 'E24 per-job decision table missing')
        for job in self.jobs:
            got = {k: per_job[job].get(k, 0) for k in KINDS}
            require(got == counts[job], f'E24 {job}: decision table {got} does not match the actions {counts[job]}')
        metric = self.metrics.get('owner_decisions')
        if metric:
            for job, v in values(metric).items():
                require(v == sum(counts[job].values()), f'E24 {job}: owner_decisions cell {v} differs from the action count')
        ac1 = d.get('ac1', {})
        ok = all(sum(c.values()) <= 2 and c['other'] == 0 for c in counts.values())
        require(ac1.get('max_per_job') == 2 and ac1.get('outside_u1_u4') == 0, 'E24 AC1 target must be ≤ 2 per job, 0 outside U1–U4')
        require(ac1.get('status') == ('đạt' if ok else 'không đạt'), 'E24 AC1 status inconsistent with the table')
        require(any(l.startswith('AC1') for l in self.lines), 'E24 AC1 line missing')

    def skip_leak(self):
        s, m = self.report.get('skip_leak'), self.metrics.get('skip_leak')
        require(isinstance(s, dict) and isinstance(s.get('skip_count'), int) and isinstance(s.get('links'), list), 'E29 skip_leak section missing')
        for link in s['links']:
            require(link.get('finding') and link.get('skip_record'), 'E29 each leak links a finding to its SKIP (HD-20) record')
        require(len({l['skip_record'] for l in s['links']}) <= s['skip_count'], 'E29 more SKIP records than SKIPs')
        if m:
            require(sum(values(m).values()) == len(s['links']), 'E29 skip leak count differs from the linked findings')
            line = self.metric_line('skip_leak') or ''
            require(f'{len(s["links"])}/{s["skip_count"]} SKIP' in line, 'E29 line must show count/SKIP denominator')

    def skip_link_records(self):
        s, m = self.report.get('skip_leak'), self.metrics.get('skip_leak')
        require(isinstance(s, dict) and isinstance(s.get('links'), list), 'E29 skip_leak section missing')
        # round 7 F4: each link names its job and the SKIP record of THAT job (jobs_detail.skip_records), a defect counts once,
        # and the rendered SKIP line carries count/denominator, target 0, source and both IDs of every link
        skips = {d.get('job'): set(d.get('skip_records') or []) for d in self.report.get('jobs_detail', []) if isinstance(d, dict)}
        require(sum(len(v) for v in skips.values()) == s['skip_count'], 'E29 skip_count must be the SKIP records of the jobs (jobs_detail)')
        seen = set()
        for link in s['links']:
            require(link.get('skip_record') in skips.get(link.get('job'), set()),
                    f'E29 link {link.get("finding")}: SKIP record {link.get("skip_record")} is not a SKIP record of job {link.get("job")}')
            key = (link.get('job'), link.get('finding'))
            require(key not in seen, f'E29 lỗi lọt qua SKIP bị đếm hai lần: {key[0]} {key[1]}')
            seen.add(key)
        require(s.get('target') == 0 and isinstance(s.get('source'), str) and s['source'], 'E29 skip_leak needs its source and target 0')
        line = next((l for l in self.lines if l.startswith('SKIP (HD-20):')), '')
        require(f'{len(s["links"])}/{s["skip_count"]} SKIP' in line and 'mục tiêu 0' in line and s['source'] in line
                and all(f'finding {x["finding"]} <- SKIP {x["skip_record"]}' in line for x in s['links']),
                'E29 the SKIP line must show count/SKIP denominator, target 0, source and each finding <- SKIP record')
        if m:
            for job, v in values(m).items():
                mine = sum(1 for x in s['links'] if x.get('job') == job)
                require(v == mine, f'E29 {job}: skip_leak cell {v} differs from its {mine} linked finding(s)')

    def manual_fixes(self):
        s, m = self.report.get('manual_fixes'), self.metrics.get('ledger_manual_fixes')
        require(isinstance(s, dict) and isinstance(s.get('decision_log_rows'), list), 'E30 manual_fixes section missing')
        for row in s['decision_log_rows']:
            require(all(row.get(k) for k in ('at', 'job', 'before', 'after', 'reason')), 'E30 decision-log row needs time, job, before, after, reason')
        rows = len(s['decision_log_rows'])
        if s.get('interventions') != rows:
            require(s.get('mismatch_reason'), 'E30 nhật ký quyết định lệch control.intervention: ghi cả hai nguồn và lý do')
        if m:
            got = sum(values(m).values())
            require(got == rows, f'E30 sửa tay trạng thái sổ ghi {got} khi nhật ký quyết định có {rows} dòng')

    def providers(self):
        p = self.report.get('providers')
        require(isinstance(p, list) and p, 'E38 provider failure table missing')
        for row in p:
            name, calls, fails = row.get('provider'), row.get('calls'), row.get('failures')
            require(name and isinstance(calls, int) and calls > 0 and isinstance(fails, int) and 0 <= fails <= calls,
                    f'E38 {name}: failures and denominator (calls) required')
            reasons = row.get('reasons', {})
            require(set(reasons) <= {'hạn mức', 'lỗi công cụ'} and sum(reasons.values()) == fails, f'E38 {name}: reasons must add up')
            require(row.get('inconclusive_receipts') == fails, f'E38 {name}: count differs from inconclusive receipts')
            require(any(l.startswith(f'Provider {name}: {fails}/{calls}') for l in self.lines), f'E38 {name}: report line missing')

    def continuation(self):
        c = self.report.get('continuation_trial')
        require(isinstance(c, dict) and c.get('job') in self.jobs and c.get('tool'), 'E27 continuation trial missing')
        require(re.fullmatch(r'[0-9a-f]{64}', str(c.get('package_sha256'))), 'E27 package hash required')
        answers = c.get('answers', [])
        require([a.get('question') for a in answers] == list(QUESTIONS), 'E27 five questions required in order')
        grader = c.get('grader', {})
        require(grader.get('identity') and grader.get('model'), 'E27 grader identity and model required')
        require(grader['identity'] == 'owner' or grader['model'] != c.get('coordinator_model'),
                'E27 người chấm phải độc lập (khác model với người điều phối, hoặc chủ sở hữu)')
        all_ok = all(a.get('correct') is True for a in answers)
        require(c.get('result') == ('đạt' if all_ok else 'không đạt'), 'E27 "đạt" only when all five answers are correct')

    # --- aggregate identity (W38c): provenance, scope, artifact, denominators, figures ---------------------
    def identity(self):
        r = self.report
        p = r.get('provenance')
        require(isinstance(p, dict) and p.get('kind') in ('synthetic', 'real') and isinstance(p.get('generator'), str) and p['generator'],
                'ID provenance missing: kind (synthetic|real) and generator required')
        ledgers = p.get('ledgers')
        require(isinstance(ledgers, list) and ledgers and all(isinstance(x, dict) for x in ledgers), 'ID provenance: ledgers (state roots) missing')
        by = {}
        for led in ledgers:
            require(isinstance(led.get('id'), str) and led['id'] and isinstance(led.get('state_root'), str) and led['state_root']
                    and COMMIT_RE.fullmatch(str(led.get('commit'))) and SHA256_RE.fullmatch(str(led.get('wheel_sha256')))
                    and type(led.get('synthetic')) is bool and isinstance(led.get('roots'), list),
                    f'ID ledger {led.get("id")}: state root, commit, wheel sha256, synthetic flag and roots required')
            require(led['id'] not in by, f'ID sổ trùng: {led["id"]}')
            by[led['id']] = led
            if not any(led['id'] in line and led['state_root'] in line and led['wheel_sha256'] in line for line in self.lines):
                self.add(f'ID ledger {led["id"]}: rendered provenance line (state root, wheel sha256) missing')
        if r.get('pilot_evidence'):
            self.add('INPUT: a report is never pilot evidence by itself')
        if any(led['synthetic'] for led in ledgers) or p['kind'] == 'synthetic':
            if p['kind'] == 'real' or r.get('simulated') is not True:
                self.add('ID dữ liệu synthetic không chứng minh pilot thật: provenance hay simulated ghi "real"')
            if r.get('pilot_evidence') or r.get('owner_acceptance'):
                self.add('ID báo cáo synthetic ghi bằng chứng pilot hay nghiệm thu')
            if not any(SYNTHETIC_LINE in line for line in self.lines):
                self.add(f'ID dòng "{SYNTHETIC_LINE}" missing')
            for line in self.lines:
                low = line.lower()
                if ('pilot thật' in low or 'nghiệm thu' in low) and 'không' not in low:
                    self.add(f'ID báo cáo synthetic tự nhận pilot thật hay nghiệm thu: {line.strip()[:80]}')
        detail = r.get('jobs_detail')
        require(isinstance(detail, list) and all(isinstance(d, dict) for d in detail), 'ID jobs_detail missing')
        names = [d.get('job') for d in detail]
        twice = sorted({j for j in names if names.count(j) > 1})
        if twice:
            self.add(f'ID dòng việc trùng: {", ".join(map(str, twice))}')
        require(set(names) == set(self.jobs), 'ID jobs_detail needs one row per job')
        outcome_by = {row.get('job'): row for row in (r.get('outcomes') or {}).get('roots', []) if isinstance(row, dict)}
        where, roots_seen = {}, {}
        for d in detail:
            job = d['job']
            if 'skipped' in d:
                require(isinstance(d['skipped'], str) and d['skipped'].strip(), f'ID {job}: a skipped job needs its reason')
                for mid, m in sorted(self.metrics.items()):
                    if 'value' in (m.get('cells') or {}).get(job, {}):
                        self.add(f'ID việc bị bỏ {job} có số ở {mid}')
                continue
            led = by.get(d.get('ledger'))
            if led is None:
                self.add(f'ID sai phạm vi: {job} ở sổ {d.get("ledger")} không có trong provenance')
                continue
            key = (led['id'], d.get('root'))
            if d.get('root') not in led['roots']:
                self.add(f'ID sai phạm vi: root {d.get("root")} của {job} không thuộc sổ {led["id"]}')
            if key in roots_seen:
                self.add(f'ID dòng việc trùng: {roots_seen[key]} và {job} cùng root {key[0]}/{key[1]}')
            roots_seen[key] = job
            where[job] = key
            if d.get('wheel_sha256') != led['wheel_sha256']:
                self.add(f'ID sai artifact: {job} ghi wheel {d.get("wheel_sha256")}, sổ {led["id"]} ghi {led["wheel_sha256"]}')
            o = outcome_by.get(job)
            if o is not None and (o.get('root') != d.get('root') or o.get('final_outcome') != d.get('status') or o.get('ledger', led['id']) != led['id']):
                self.add(f'ID dữ liệu mâu thuẫn: {job} có kết cục {d.get("status")} ở {key[0]}/{key[1]}, dòng outcome ghi '
                         f'{o.get("final_outcome")} ở {o.get("ledger")}/{o.get("root")}')
        for led in ledgers:
            excluded = led.get('excluded', [])
            require(isinstance(excluded, list) and all(isinstance(x, dict) and x.get('root') and isinstance(x.get('reason'), str)
                    and x['reason'].strip() for x in excluded), f'ID ledger {led["id"]}: excluded roots need a reason')
            accounted = {k[1] for k in roots_seen if k[0] == led['id']} | {x['root'] for x in excluded}
            outside = sorted(set(led['roots']) - accounted)
            if outside:
                self.add(f'ID root ngoài phạm vi pilot ở sổ {led["id"]}: {", ".join(outside)} (không là việc pilot, không có lý do loại)')
        for mid, m in sorted(self.metrics.items()):
            cells = m.get('cells') if isinstance(m.get('cells'), dict) else {}
            have = sorted(j for j, c in cells.items() if isinstance(c, dict) and 'value' in c)
            cf = m.get('computed_from')
            if not (isinstance(cf, list) and all(isinstance(x, dict) for x in cf) and sorted(x.get('job') for x in cf) == have):
                self.add(f'ID {mid}: computed_from must list exactly the jobs with a value ({", ".join(have) or "none"})')
            else:
                for x in cf:
                    if where.get(x['job']) != (x.get('ledger'), x.get('root')):
                        self.add(f'ID {mid}: computed_from {x["job"]} names {x.get("ledger")}/{x.get("root")}, the job row says {where.get(x["job"])}')
            if not (isinstance(m.get('missing'), list) and sorted(m['missing']) == sorted(set(cells) - set(have))):
                self.add(f'ID {mid}: missing must list every job without data (they stay in the denominator)')
            s = m.get('summary')
            if isinstance(s, dict) and 'value' in s and have and number(s['value']):
                total = sum(cells[j]['value'] for j in have if number(cells[j]['value']))
                if abs(s['value'] - total) > 0.011:
                    self.add(f'ID số liệu giả: {mid} tổng {s["value"]} khác tổng các ô {round(total, 2)}')
        if r.get('figures_sha256') != figures_digest(r):
            self.add('ID figures_sha256 không khớp nội dung báo cáo (số liệu bị sửa sau khi sinh)')

    def run(self):
        try:
            self.top()
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            self.add(str(exc) if isinstance(exc, ValueError) else f'INPUT: {exc}')
            return
        if self.report.get('owner_acceptance'):
            self.add('INPUT: a report cannot record owner acceptance (owner verb in the ledger only)')
        self.metrics_all()
        self.check(self.owner_notes)
        self.check(self.outcomes)
        if self.kind == 'interim':
            for fn in (self.no_baseline_text, self.ledger_columns, self.desktop_window):
                self.check(fn)
        else:
            for fn in (self.blanket_baseline, self.tiers, self.false_pass, self.decisions, self.skip_leak, self.skip_link_records,
                       self.manual_fixes, self.providers, self.continuation, self.identity):
                self.check(fn)
            self.check(self.header)


def check_report(report, text):
    """Validate one pilot report. Pure function: reads its arguments only."""
    c = Checker(report if isinstance(report, dict) else {}, text if isinstance(text, str) else '')
    c.run()
    return {'result': 'refused' if c.problems else 'pass', 'problems': c.problems,
            'kind': c.report.get('kind'), 'simulated': c.report.get('simulated'),
            'owner_acceptance': False, 'pilot_evidence': False}


def check_files(json_path, md_path):
    try:
        report = json.loads(Path(json_path).read_text(encoding='utf-8'))
        text = Path(md_path).read_text(encoding='utf-8')
    except (OSError, ValueError) as exc:
        return {'result': 'refused', 'problems': [f'INPUT: {exc}'], 'kind': None, 'simulated': None,
                'owner_acceptance': False, 'pilot_evidence': False}
    return check_report(report, text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('report_json')
    parser.add_argument('report_md')
    args = parser.parse_args(argv)
    result = check_files(args.report_json, args.report_md)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['result'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
