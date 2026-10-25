"""T35b / T35c — script kiểm báo cáo pilot (kit task WKPL), on FIXTURE reports only.

No pilot has run and no report generator exists: every report below is built in
this file (simulated=True) and rendered by a test-side renderer, then mutated
into the counter-examples of 05 T35 (m1–m5, E11) and the other named breaks.
Passing proves the checker's rules, never a real pilot result or acceptance.
y1/y2 belong to T45e (script kiểm đối chiếu) and are not tested here.
"""
import contextlib
import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from wfkit import pilot_report as pr

H = 'a' * 64
UNIT = {'time_to_usable': 'phút', 'exec_time': 'phút', 'wait_time': 'phút', 'owner_minutes': 'phút', 'verify_cost': 'phút'}
SOURCE = {'A': 'sổ pilot', 'B': 'ghi chép của chủ sở hữu', 'C': 'nhật ký chat'}
DEFAULT = {'time_to_usable': 40, 'exec_time': 25, 'wait_time': 15, 'owner_decisions': 2, 'actual_actions': 4,
           'rework_rounds': 1, 'owner_keystrokes': 2, 'verify_cost': 6, 'owner_retries': 1}


def cells_for(mid, jobs, missing=()):
    return {j: ({'no_data': missing[j]} if j in missing else {'value': DEFAULT.get(mid, 0)}) for j in jobs}


def finish(metric, kind, n):
    k = len(pr.values(metric))
    metric.update(k=k, n=n, status=pr.status_for(k, n), label=pr.label_for(k, n, kind))
    metric['summary'] = ({'value': sum(pr.values(metric).values()), 'unit': UNIT.get(metric['id'], 'lần')} if k
                         else {'no_data': pr.NO_NOTES})
    if kind == 'aggregate' and metric['id'] in pr.TARGETS:
        metric['target'] = pr.TARGETS[metric['id']]
        total = sum(pr.values(metric).values())
        metric['target_status'] = pr.target_status(metric['target'], total, k, n) or 'không đạt'
    if kind == 'aggregate':
        metric['computed_from'] = [{'job': j, 'ledger': 'L1', 'root': f'plan:{j.lower()}'} for j in sorted(pr.values(metric))]
        metric['missing'] = sorted(set(metric['cells']) - set(pr.values(metric)))


SKIPS = {'J2': ['HD20-1'], 'J5': ['HD20-2']}          # the two SKIP (HD-20) records of the fixture aggregate


def identify(r):
    """W38c identity of the fixture aggregate: provenance, one detail row per job, then the figures digest (last)."""
    roots = [f'plan:{j.lower()}' for j in r['jobs']]
    r['provenance'] = {'kind': 'synthetic', 'generator': 'test fixture',
                       'ledgers': [{'id': 'L1', 'state_root': 'FIXTURE-STATE-ROOT', 'commit': 'c' * 40, 'wheel_sha256': H,
                                    'synthetic': True, 'roots': roots, 'excluded': []}]}
    r['jobs_detail'] = [{'job': j, 'ledger': 'L1', 'root': f'plan:{j.lower()}', 'status': 'accepted', 'wheel_sha256': H,
                         'skip_records': SKIPS.get(j, [])} for j in r['jobs']]
    r['figures_sha256'] = pr.figures_digest(r)
    return r


def build(kind):
    n = 3 if kind == 'interim' else 10
    jobs = [f'J{i}' for i in range(1, n + 1)]
    gaps = {'owner_minutes': {j: pr.NO_NOTES for j in jobs} if kind == 'aggregate' else {'J2': pr.NO_NOTES},
            'missed_wait_1h_owner': {'J7': pr.NO_NOTES} if kind == 'aggregate' else {},
            'actual_actions': {'J2': 'thiếu nhật ký chat'} if kind == 'aggregate' else {}}
    metrics = []
    for mid, group in pr.CATALOG.items():
        if kind == 'interim' and mid == 'skip_leak':
            continue
        m = {'id': mid, 'group': group, 'source': SOURCE[group], 'cells': cells_for(mid, jobs, gaps.get(mid, {}))}
        if mid == 'amend_requirement_change':
            m['cells']['J1'] = {'value': 1}
        finish(m, kind, n)
        metrics.append(m)
    r = {'schema': 1, 'kind': kind, 'phase': 'PL-A' if kind == 'interim' else 'PL-B', 'simulated': True,
         'jobs': jobs, 'metrics': metrics,
         'owner_notes_missing': {mid: sorted(g) for mid, g in gaps.items() if pr.CATALOG[mid] == 'B' and g},
         'outcomes': {'roots': [{'root': f'plan:{j.lower()}', 'job': j, 'plan': f'plan:{j.lower()}', 'revision': 1,
                                 'final_outcome': 'accepted', 'outcome_rows': 1} for j in jobs], 'missing': [], 'target': 0}}
    if kind == 'interim':
        rows = [{'job': j, 'column': c, 'ledger': 1, 'chat': 1, 'match': True} for j in jobs
                for c in ('decision', 'intervention', 'outcome')]
        rows[4].update(chat=2, match=False, reason='nhật ký chat ghi cả lệnh thử lại')
        r['ledger_columns'] = {'command': 'onecrew plan report --ledger', 'ledger_sha256': H, 'hand_filled': 0, 'rows': rows}
        r['desktop_window'] = {'event_id': 'EV-17', 'emitted_at': '2026-11-02T09:00:00+07:00',
                               'shown_at': '2026-11-02T09:00:04+07:00', 'delivery_status': 'đã giao'}
        return r
    r['tiers'] = {
        'tier1': {'limits': ['nhóm việc khác (v2.1 so với WF)', 'cỡ mẫu nhỏ', 'cách đếm khớp 20/10'],
                  'comparisons': [comparison(r, name) for name in pr.TIER1]},
        'tier2': {'metrics': sorted(pr.TIER2), 'conclusion': pr.NO_REDUCTION},
        'tier3': {'conclusion': pr.NO_REDUCTION, 'comparison_group': None}}
    actions = []
    for i, j in enumerate(jobs):
        actions.append({'job': j, 'at': f'2026-11-1{i % 10}T08:00:00+07:00', 'verb': 'approve', 'kind': 'root_approval', 'sources': ['ledger', 'chat']})
        actions.append({'job': j, 'at': f'2026-11-1{i % 10}T15:00:00+07:00', 'verb': 'accept', 'kind': 'acceptance', 'sources': ['ledger']})
    per_job = {j: {'root_approval': 1, 'acceptance': 1} for j in jobs}
    r['owner_decisions'] = {'actions': actions, 'per_job': per_job,
                            'mismatches': [{'job': 'J3', 'at': '2026-11-12T15:00:00+07:00', 'ledger': 'accept', 'chat': 'không thấy', 'reason': 'chat cắt'}],
                            'ac1': {'max_per_job': 2, 'outside_u1_u4': 0, 'status': 'đạt'}}
    r['skip_leak'] = {'skip_count': 2, 'links': [], 'invalid_links': [], 'source': 'decision.recorded: review_policy SKIP (HD-20) x finding_skip_link',
                      'target': 0}
    next(m for m in metrics if m['id'] == 'false_pass')['skip_leak_part'] = 0
    r['manual_fixes'] = {'decision_log_rows': [], 'interventions': 0}
    r['providers'] = [{'provider': 'codex', 'calls': 12, 'failures': 1, 'reasons': {'hạn mức': 1}, 'inconclusive_receipts': 1},
                      {'provider': 'claude', 'calls': 20, 'failures': 0, 'reasons': {}, 'inconclusive_receipts': 0}]
    r['continuation_trial'] = {'job': 'J4', 'tool': 'kiro', 'package_sha256': H, 'coordinator_model': 'claude-fable-5',
                               'grader': {'identity': 'agent-codex', 'model': 'gpt-5.5'}, 'result': 'đạt',
                               'answers': [{'question': q, 'correct': True} for q in pr.QUESTIONS]}
    return identify(r)


def comparison(r, name):
    base, parts = pr.TIER1[name]
    # fixture input in the round-7 shape: one job set per composite (the jobs with a value for every part)
    cells = {p: next(m for m in r['metrics'] if m['id'] == p)['cells'] for p in parts}
    frm = sorted(j for j in r['jobs'] if all('value' in cells[p][j] for p in parts))
    per_job = {j: sum(cells[p][j]['value'] for p in parts) for j in frm}
    missing = {p: sorted(j for j in r['jobs'] if 'value' not in cells[p][j]) for p in parts}
    k, total = len(frm), sum(per_job.values())
    return {'metric': name, 'baseline_count': base, 'baseline_jobs': 11, 'baseline_per_job': round(base / 11, 3),
            'pilot_count': total, 'pilot_jobs': k, 'pilot_per_job': round(total / k, 3), 'source': 'DO-DIEU-KIEN-DUNG-V2-20261020 (00 §9.2)',
            'parts': list(parts), 'computed_from': frm, 'per_job': per_job, 'missing': {p: v for p, v in missing.items() if v},
            'pilot_denominator': len(r['jobs']), 'complete': k == len(r['jobs'])}


def render(r):
    n, out = len(r['jobs']), []
    if r['kind'] == 'aggregate':
        groups = {'đủ': [], 'thiếu': [], 'không có': []}
        for m in sorted(r['metrics'], key=lambda m: m['id']):
            groups[pr.status_for(m['k'], n)].append(m['id'])
        a_short = [f'{j} {m["id"]}' for m in sorted(r['metrics'], key=lambda m: m['id']) if m['group'] == 'A'
                   for j in r['jobs'] if 'value' not in m['cells'][j]]
        out.append('# Báo cáo tổng hợp PL-B (fixture)')
        out.append(pr.AC5 + ('đạt' if not a_short else 'không đạt: nhóm A thiếu ' + ', '.join(a_short)))
        out.append('Baseline: {} chỉ số đủ 10/10 ({}), {} thiếu ({}), {} không có ({})'.format(
            len(groups['đủ']), ', '.join(groups['đủ']), len(groups['thiếu']), ', '.join(groups['thiếu']),
            len(groups['không có']), ', '.join(groups['không có'])))
        if 'provenance' in r:
            out.append(f'Nguồn dữ liệu: {pr.SYNTHETIC_LINE}.')
            for led in r['provenance']['ledgers']:
                out.append(f'Sổ {led["id"]}: state root {led["state_root"]}; commit {led["commit"]}; wheel sha256 {led["wheel_sha256"]}.')
    else:
        out.append('# Báo cáo giữa kỳ PL-A (fixture)')
    out.append('## Chỉ số')
    for m in r['metrics']:
        s = m['summary']
        shown = f'không có dữ liệu: {s["no_data"]}' if 'no_data' in s else f'{s["value"]} {s["unit"]}'
        cells = '; '.join(f'{j}: ' + (f'không có dữ liệu: {c["no_data"]}' if 'no_data' in c else str(c['value']))
                          for j, c in m['cells'].items())
        extra = f' | mục tiêu {m["target"]}: {m["target_status"]}' if 'target' in m else ''
        if m['id'] == 'skip_leak':
            extra += f' | {len(r["skip_leak"]["links"])}/{r["skip_leak"]["skip_count"]} SKIP'
        out.append(f'| `{m["id"]}` | nhóm {m["group"]} | {m["source"]} | {m["k"]}/{n} | {m["status"]} | {m["label"]} | {shown} | {cells}{extra} |')
    missing = r['outcomes']['missing']
    out.append('Root thiếu outcome: ' + (', '.join(missing) if missing else 'rỗng'))
    if r['kind'] == 'interim':
        d = r['desktop_window']
        out.append(f'Cửa sổ Windows: sự kiện {d["event_id"]} phát {d["emitted_at"]}, hiện {d["shown_at"]}, {d["delivery_status"]}')
        return '\n'.join(out) + '\n'
    out.append('## Tầng 1 — so với số đếm 20/10')
    for c in r['tiers']['tier1']['comparisons']:
        out.append(f'- {c["metric"]}: 20/10: {c["baseline_count"]} trên 11 việc; pilot {c["pilot_count"]} trên {c["pilot_jobs"]} việc; '
                   f'tính từ {c["pilot_jobs"]}/{c["pilot_denominator"]} việc'
                   + ('' if c['complete'] else '; so sánh một phần, thiếu ' + '; '.join(f'{p}: {", ".join(v)}' for p, v in c['missing'].items())))
    out.append('Giới hạn: ' + '; '.join(r['tiers']['tier1']['limits']) + '. Không suy ra thời gian từ số đếm 20/10.')
    out.append('## Tầng 2 — pilot')
    out.append(f'Kết luận tầng 2: {r["tiers"]["tier2"]["conclusion"]}')
    out.append('## Tầng 3 — so sánh')
    out.append(f'Kết luận tầng 3: {r["tiers"]["tier3"]["conclusion"]}')
    out.append('## Khác')
    out.append('AC1: tối đa 2 quyết định mỗi việc, 0 ngoài U1–U4: ' + r['owner_decisions']['ac1']['status'])
    for p in r['providers']:
        out.append(f'Provider {p["provider"]}: {p["failures"]}/{p["calls"]} lần không chạy được')
    sk = r['skip_leak']
    out.append(f'SKIP (HD-20): {sk["skip_count"]} bản ghi; lỗi lọt qua nối được: {len(sk["links"])}/{sk["skip_count"]} SKIP; mục tiêu 0; nguồn {sk["source"]}'
               + ''.join(f'; {x.get("job")}: finding {x["finding"]} <- SKIP {x["skip_record"]}' for x in sk['links']))
    return '\n'.join(out) + '\n'


def metric(r, mid):
    return next(m for m in r['metrics'] if m['id'] == mid)


class Base(unittest.TestCase):
    def refused(self, r, needle, text=None):
        res = pr.check_report(r, render(r) if text is None else text)
        self.assertEqual(res['result'], 'refused', res)
        self.assertTrue(any(needle in p for p in res['problems']), res['problems'])
        return res


class InterimT35b(Base):
    def test_good_interim_passes(self):  # E7, E25, E26, E28
        r = build('interim')
        res = pr.check_report(r, render(r))
        self.assertEqual(res, {'result': 'pass', 'problems': [], 'kind': 'interim', 'simulated': True,
                               'owner_acceptance': False, 'pilot_evidence': False})

    def test_e7_baseline_word_refused(self):
        r = build('interim')
        self.refused(r, 'E7 báo cáo giữa kỳ không ghi baseline', render(r) + 'Ghi chú: đã có baseline sơ bộ.\n')
        metric(r, 'exec_time')['label'] = 'baseline một phần (3/3)'
        self.refused(r, 'E7 exec_time: báo cáo giữa kỳ không ghi baseline')

    def test_e7_missing_fields_refused(self):
        r = build('interim')
        text = render(r)
        del metric(r, 'wait_time')['source']
        self.refused(r, 'E7 wait_time: source missing', text)
        r = build('interim')
        metric(r, 'exec_time')['n'] = 10
        self.refused(r, 'E7 exec_time: denominator must be k/3')
        r = build('interim')
        r['metrics'] = [m for m in r['metrics'] if m['id'] != 'verify_cost']
        self.refused(r, 'E7 metrics missing: verify_cost')

    def test_e25_unlisted_missing_outcome_refused(self):
        r = build('interim')
        r['outcomes']['roots'][1]['outcome_rows'] = 0
        self.refused(r, 'E25 root thiếu outcome không được liệt kê')
        r['outcomes']['missing'] = ['plan:j2']
        self.refused(r, 'E25 root thiếu learning.outcome: plan:j2 (mục tiêu 0)')
        r = build('interim')
        r['outcomes']['roots'][0]['outcome_rows'] = 2
        self.refused(r, 'E25 plan:j1: khoá (plan, revision, kết cục) có 2 dòng')

    def test_e26_hand_filled_and_mismatch_refused(self):
        r = build('interim')
        r['ledger_columns']['hand_filled'] = 1
        self.refused(r, 'E26 số ô điền tay phải = 0')
        r = build('interim')
        del r['ledger_columns']['rows'][4]['reason']
        self.refused(r, 'dòng lệch phải ghi cả hai nguồn và lý do')

    def test_e28_desktop_window_required(self):
        r = build('interim')
        text = render(r)
        r['desktop_window']['delivery_status'] = 'chưa giao'
        self.refused(r, 'E28 notification status', text)
        r = build('interim')
        self.refused(r, 'E28 report line about the desktop window missing',
                     '\n'.join(l for l in render(r).splitlines() if 'Cửa sổ' not in l))


class AggregateT35c(Base):
    def test_good_aggregate_passes(self):  # E6, E20–E24, E29–E34, E38, E27; B/C short does not block (E33)
        r = build('aggregate')
        text = render(r)
        self.assertIn('chưa lập baseline (0/10)', text)
        self.assertIn('J7: không có dữ liệu: thiếu ghi chép của chủ sở hữu', text)
        res = pr.check_report(r, text)
        self.assertEqual(res['problems'], [])
        self.assertEqual(res['result'], 'pass')

    def test_m1_zero_minutes_refused(self):  # E35
        r = build('aggregate')
        metric(r, 'owner_minutes')['summary'] = {'value': 0, 'unit': 'phút'}
        res = self.refused(r, 'E35 ô không có dữ liệu hiện 0')
        self.assertTrue(any('owner_minutes' in p and '"0 phút"' in p for p in res['problems']), res['problems'])

    def test_m2_partial_labelled_baseline_refused(self):  # E36
        r = build('aggregate')
        m = metric(r, 'owner_minutes')
        for j in ('J1', 'J2', 'J3', 'J4'):
            m['cells'][j] = {'value': 5}
        finish(m, 'aggregate', 10)
        m['label'] = 'đã lập baseline'
        r['owner_notes_missing']['owner_minutes'] = [f'J{i}' for i in range(5, 11)]
        self.refused(r, 'E36 baseline khi mẫu số 4/10')

    def test_m3_missing_cell_as_zero_refused(self):  # E35
        r = build('aggregate')
        metric(r, 'missed_wait_1h_owner')['cells']['J7'] = {'value': 0}
        self.refused(r, 'E35 ô không có dữ liệu hiện 0: missed_wait_1h_owner J7')

    def test_m4_blanket_baseline_refused(self):  # E37
        r = build('aggregate')
        self.refused(r, 'E37 kết luận baseline đầy đủ khi còn chỉ số thiếu', render(r) + 'Kết luận: baseline đầy đủ.\n')
        self.refused(r, 'E37', render(r) + 'Mọi chỉ số đã lập baseline.\n')

    def test_m5_reduction_without_comparison_group_refused(self):  # E12
        r = build('aggregate')
        for mid in ('owner_minutes', 'missed_wait_1h_owner', 'actual_actions'):
            m = metric(r, mid)
            m['cells'] = cells_for(mid, r['jobs'])
            finish(m, 'aggregate', 10)
        r['owner_notes_missing'] = {}
        r['tiers']['tier1']['comparisons'] = [comparison(r, n) for n in pr.TIER1]
        identify(r)                                                          # a legitimate regeneration refreshes the figures digest
        self.assertEqual(pr.check_report(r, render(r))['result'], 'pass')  # all 10/10 is fine on its own
        r['tiers']['tier3']['conclusion'] = 'giảm 30% thời gian tới đầu ra'
        self.refused(r, 'E12 kết luận giảm khi chưa có nhóm so sánh')

    def test_e11_time_conclusion_from_2010_refused(self):
        r = build('aggregate')
        self.refused(r, 'E11 kết luận về thời gian từ số đếm 20/10',
                     render(r) + 'So với 20/10, chủ sở hữu tiết kiệm 60 phút mỗi việc.\n')
        r['tiers']['tier1']['comparisons'][0]['time_conclusion'] = 'giảm 60 phút'
        self.refused(r, 'E11 kết luận về thời gian từ số đếm 20/10: owner_keystrokes')

    def test_e6_tiers_and_labels_required(self):
        r = build('aggregate')
        r['tiers']['tier1']['limits'] = ['cỡ mẫu nhỏ']
        self.refused(r, 'E6 tier 1 must state the limits')
        r = build('aggregate')
        metric(r, 'actual_actions')['label'] = 'baseline một phần'
        self.refused(r, "E6 actual_actions: label must be 'baseline một phần (9/10)'")

    def test_e20_noise_lines_target_zero(self):
        r = build('aggregate')
        metric(r, 'noise_stop_hook')['target'] = 5
        self.refused(r, 'E20 noise_stop_hook: target must be 0')
        r = build('aggregate')
        metric(r, 'noise_notifications')['cells']['J1'] = {'value': 3}
        finish(metric(r, 'noise_notifications'), 'aggregate', 10)
        metric(r, 'noise_notifications')['target_status'] = 'đạt'
        self.refused(r, "E20 noise_notifications: status vs target must be 'không đạt'")

    def test_e21_amend_causes_and_tier1_total(self):
        r = build('aggregate')
        r['metrics'] = [m for m in r['metrics'] if m['id'] != 'amend_emergent']
        self.refused(r, 'E6 metrics missing: amend_emergent')
        r = build('aggregate')
        r['tiers']['tier1']['comparisons'][1]['baseline_count'] = 20
        self.refused(r, 'E6 tier 1 amend_total: baseline must be 23')

    def test_e22_false_pass_separates_skip_leak(self):
        r = build('aggregate')
        del metric(r, 'false_pass')['skip_leak_part']
        self.refused(r, 'E22 cho qua sai phải tách số lỗi lọt qua SKIP')

    def test_e23_minutes_from_wait_time_refused(self):
        r = build('aggregate')
        m = metric(r, 'owner_minutes')
        m['cells'] = {j: {'value': 15, 'derived_from': 'wait_time'} for j in r['jobs']}
        finish(m, 'aggregate', 10)
        r['owner_notes_missing'] = {'missed_wait_1h_owner': ['J7']}
        self.refused(r, 'E23 owner_minutes J1: phút chủ động suy ra từ wait_time')

    def test_e24_double_counted_action_refused(self):
        r = build('aggregate')
        dup = dict(r['owner_decisions']['actions'][0], sources=['chat'])
        r['owner_decisions']['actions'].append(dup)
        r['owner_decisions']['per_job']['J1']['root_approval'] = 2
        self.refused(r, 'E24 hành động bị đếm hai lần: J1')

    def test_e29_skip_leak_links(self):
        r = build('aggregate')
        r['skip_leak']['links'] = [{'finding': 'F-3', 'skip_record': 'HD20-1'}]
        self.refused(r, 'E29 skip leak count differs from the linked findings')

    def test_e29_link_must_name_a_skip_record_of_its_job_once_and_be_rendered(self):  # round 7 F4
        r = build('aggregate')
        cell = metric(r, 'skip_leak')['cells']
        cell['J2'] = {'value': 1}
        finish(metric(r, 'skip_leak'), 'aggregate', 10)
        r['skip_leak']['links'] = [{'job': 'J2', 'finding': 'RF1', 'skip_record': 'HD20-1'}]
        next(m for m in r['metrics'] if m['id'] == 'false_pass')['skip_leak_part'] = 1
        identify(r)
        self.assertEqual(pr.check_report(r, render(r))['problems'], [])
        bad = json.loads(json.dumps(r)); bad['skip_leak']['links'][0]['skip_record'] = 'HD20-2'        # J5's SKIP, not J2's
        self.refused(identify(bad), 'E29 link RF1: SKIP record HD20-2 is not a SKIP record of job J2')
        bad = json.loads(json.dumps(r)); bad['skip_leak']['links'].append(dict(bad['skip_leak']['links'][0]))
        self.refused(identify(bad), 'E29 lỗi lọt qua SKIP bị đếm hai lần: J2 RF1')
        text = render(r).replace('; J2: finding RF1 <- SKIP HD20-1', '')
        self.refused(r, 'E29 the SKIP line must show', text)

    def test_e30_manual_fixes_zero_with_log_rows_refused(self):
        r = build('aggregate')
        r['manual_fixes'] = {'decision_log_rows': [{'at': '2026-11-12T10:00:00+07:00', 'job': 'J2', 'before': 'running',
                                                    'after': 'verified', 'reason': 'sổ kẹt'}], 'interventions': 1}
        self.refused(r, 'E30 sửa tay trạng thái sổ ghi 0 khi nhật ký quyết định có 1 dòng')
        r = build('aggregate')
        r['metrics'] = [m for m in r['metrics'] if m['id'] != 'ledger_manual_fixes']
        self.refused(r, 'E30 dòng ledger_manual_fixes bị bỏ khỏi báo cáo')

    def test_e31_pl_b_missing_outcome_refused(self):
        r = build('aggregate')
        r['outcomes']['roots'][5]['outcome_rows'] = 0
        r['outcomes']['missing'] = ['plan:j6']
        self.refused(r, 'E31 root thiếu learning.outcome: plan:j6')

    def test_e32_group_a_short_not_pass(self):
        r = build('aggregate')
        m = metric(r, 'time_to_usable')
        m['cells']['J3'] = {'no_data': 'bộ ghi bỏ sự kiện'}
        finish(m, 'aggregate', 10)
        text = render(r)
        self.assertIn('không đạt: nhóm A thiếu J3 time_to_usable', text)
        self.refused(r, 'E32 AC5 — năng lực đo: không đạt: nhóm A thiếu J3 time_to_usable', text)
        self.refused(r, 'E32 AC5 line says đạt', text.replace('không đạt: nhóm A thiếu J3 time_to_usable', 'đạt'))

    def test_e33_partial_b_c_does_not_block(self):
        r = build('aggregate')
        self.assertEqual(metric(r, 'owner_minutes')['label'], 'chưa lập baseline (0/10)')
        self.assertEqual(metric(r, 'actual_actions')['label'], 'baseline một phần (9/10)')
        self.assertEqual(pr.check_report(r, render(r))['result'], 'pass')

    def test_e34_header_must_match_table(self):
        r = build('aggregate')
        text = render(r).replace('2 thiếu (actual_actions, missed_wait_1h_owner)', '1 thiếu (actual_actions)')
        self.refused(r, 'E34 Baseline line thiếu', text)

    def test_e38_provider_failures_match_receipts(self):
        r = build('aggregate')
        r['providers'][0]['inconclusive_receipts'] = 2
        self.refused(r, 'E38 codex: count differs from inconclusive receipts')

    def test_e27_grader_same_model_refused(self):
        r = build('aggregate')
        r['continuation_trial']['grader']['model'] = 'claude-fable-5'
        self.refused(r, 'E27 người chấm phải độc lập')


class NotEvidence(unittest.TestCase):
    def test_checker_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for kind in ('interim', 'aggregate'):
                r = build(kind)
                (root / f'{kind}.json').write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8')
                (root / f'{kind}.md').write_text(render(r), encoding='utf-8')

            def snap():
                return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in root.iterdir()}
            before = snap()
            for kind in ('interim', 'aggregate'):
                self.assertEqual(pr.check_files(root / f'{kind}.json', root / f'{kind}.md')['result'], 'pass')
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(pr.main([str(root / 'aggregate.json'), str(root / 'aggregate.md')]), 0)
            self.assertEqual(json.loads(out.getvalue())['result'], 'pass')
            self.assertEqual(snap(), before)

    def test_acceptance_or_real_pilot_claim_is_not_evidence(self):
        r = build('aggregate')
        r['simulated'] = False
        text = render(r) + 'Chủ sở hữu đã nghiệm thu. Pilot thật đã chạy trên sổ thật.\n'
        res = pr.check_report(r, text)
        self.assertIs(res['owner_acceptance'], False)
        self.assertIs(res['pilot_evidence'], False)
        r['owner_acceptance'] = True
        res = pr.check_report(r, text)
        self.assertEqual(res['result'], 'refused')
        self.assertIs(res['owner_acceptance'], False)
        self.assertIs(res['pilot_evidence'], False)


if __name__ == '__main__':
    unittest.main()
