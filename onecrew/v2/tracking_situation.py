"""Where a tracked root stands, in the owner's words, from the sources tracking.py already reads (UX of 13/11).

One place decides the stage shown on the page: the browser renders `situation`, it does not derive a stage of its own. Every field is built from
the ledger values `tracking._item` already holds (plan state, milestone views, verdict runs, engine view, attempts, requests, acceptance); nothing
here reads a new source, writes anything or guesses:

* `stage` / `label`   the phase of the work (Chưa bắt đầu, Đang thực hiện, Chờ kiểm, Cần sửa, Chờ nghiệm thu, Hoàn tất, plus Đã dừng, Đã đóng,
                      Chưa xác định). It is not the activity: "Đang thực hiện" with nothing running says so in `activity`.
* `reason`            why it is in that stage, one short sentence.
* `next` / `next_by`  the next step and who takes it when a source names them; without one `next_by` is None and `next_by_text` says
                      "Chưa có thông tin người xử lý". A failed check never becomes "AI đang sửa".
* `activity`          what the ledger shows running now (an attempt, a verdict run), or that nothing runs. No decision for the owner is
                      never "everything progresses".
* `milestones`        "đạt x/y mốc": a count of milestones, never a percentage of the work.

`milestone_checks` lists every milestone of the current contract with its checks (verdict runs and recorded verdicts) and their sourced
times, for the Tiến độ tab of a root without an engine. A check's time is the verifier run (run_started -> receipt), not development time;
a gap between two checks is not a wait.
"""
import datetime as dt

STAGES = {'todo': 'Chưa bắt đầu', 'doing': 'Đang thực hiện', 'check': 'Chờ kiểm', 'fix': 'Cần sửa', 'accept': 'Chờ nghiệm thu',
          'done': 'Hoàn tất', 'stopped': 'Đã dừng', 'closed': 'Đã đóng', 'unknown': 'Chưa xác định'}
NO_HANDLER = 'Chưa có thông tin người xử lý'
OWNER = 'Bạn'
CHECKER = 'Bộ kiểm OneCrew'
NOTHING_RUNS = 'Không có lượt chạy hay lần kiểm nào đang diễn ra trong sổ.'
MILESTONE_STATES = {'passed': 'Đạt', 'failed': 'Không đạt', 'recheck': 'Cần kiểm lại', 'checking': 'Đang kiểm', 'pending': 'Chưa kiểm',
                    'stopped': 'Đã dừng'}
RUN_KINDS = ('verdict.run_started', 'verdict.receipt_issued', 'verdict.run_abandoned', 'verdict.recorded')


def _at(text):
    if not text: return None
    try: value = dt.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError: return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _iso(value):
    return value.astimezone(dt.timezone.utc).isoformat() if value else None


def _names(ids):
    ids = [str(i) for i in ids if i]
    return ', '.join(ids[:4]) + (f' và {len(ids) - 4} mốc khác' if len(ids) > 4 else '')


def _who(pin):
    """The executor a plan assigns to a node (engine definition), worded as an assignment: it does not prove who ran."""
    if not isinstance(pin, dict): return None
    words = [str(pin[k]) for k in ('provider', 'model') if pin.get(k)]
    return ('Được giao theo kế hoạch: ' + ' · '.join(words)) if words else None


def _milestone_state(view, checking):
    if view['id'] in checking: return 'checking'
    if view.get('needs_recheck') or (view.get('stale') and view['state'] != 'failed'): return 'recheck'
    return view['state'] if view['state'] in MILESTONE_STATES else 'pending'


def milestone_checks(views, history, revision, now, lost):
    """Every milestone of the contract revision `revision` with its checks, from verdict.* events of the root (sourced times only).

    `lost(run)` names why an open run is lost (verdict.lost_reason) or None while it lives. A check is one verdict run (start, end, result) or
    a verdict recorded without a run; its `seconds` is the run's own span, None when either end has no time."""
    runs, by_run, loose = {}, {}, []
    for seq, kind, p, at in history:
        if kind not in RUN_KINDS or p.get('revision') != revision: continue
        mid, rid = p.get('milestone'), p.get('run_id')
        if kind == 'verdict.run_started':
            check = {'run_id': rid, 'milestone': mid, 'seq': seq, 'started': _iso(_at(p.get('started')) or _at(at)), 'ended': None, 'receipt': None,
                     'result': None, 'state': 'open', 'kind': p.get('kind'), 'deadline': p.get('deadline'), 'pid': p.get('pid'), 'host': p.get('host')}
            runs.setdefault(mid, []).append(check); by_run[rid] = check
        elif kind == 'verdict.receipt_issued':
            check = by_run.get(rid) or next((c for c in reversed(runs.get(mid, [])) if c['state'] == 'open' and c['receipt'] is None), None)
            if check is not None: check.update(ended=_iso(_at(at)), receipt=p.get('receipt'), state='receipt')
        elif kind == 'verdict.run_abandoned':
            check = by_run.get(rid)
            if check is not None and check['state'] == 'open': check.update(ended=_iso(_at(at)), state='abandoned', reason=str(p.get('reason') or '')[:120])
        elif kind == 'verdict.recorded':
            check = next((c for c in reversed(runs.get(mid, [])) if c['receipt'] and c['receipt'] == p.get('receipt') and c['result'] is None), None)
            if check is not None:
                check.update(result=p.get('result'), recorded=_iso(_at(at)), by=p.get('by'), state='done')
            else:
                loose.append({'milestone': mid, 'seq': seq, 'run_id': None, 'started': None, 'ended': None, 'recorded': _iso(_at(at)),
                              'result': p.get('result'), 'by': p.get('by'), 'state': 'done', 'receipt': p.get('receipt')})
    for check in loose: runs.setdefault(check['milestone'], []).append(check)
    rows, checking = [], set()
    for mid, items in runs.items():
        for c in items:
            if c['state'] == 'open':
                why = lost(c)
                if why: c.update(state='lost', lost=why)
                else: checking.add(mid)
            a, b = _at(c.get('started')), _at(c.get('ended'))
            c['seconds'] = (b - a).total_seconds() if a and b and b >= a else None
        items.sort(key=lambda c: c['seq'])
    for v in views:
        mine = runs.get(v['id'], [])
        state = _milestone_state(v, checking)
        last = next((c for c in reversed(mine) if c.get('result')), None)
        timed = [c['seconds'] for c in mine if isinstance(c.get('seconds'), (int, float))]
        rows.append({'id': v['id'], 'title': v.get('title'), 'state': state, 'label': MILESTONE_STATES[state],
                     'checks': [{k: c.get(k) for k in ('run_id', 'seq', 'started', 'ended', 'recorded', 'result', 'state', 'seconds', 'by', 'lost', 'reason')}
                                for c in mine],
                     'failures': len([c for c in mine if c.get('result') and c['result'] != 'pass']),
                     'last_result': last.get('result') if last else None, 'last_at': (last.get('recorded') or last.get('ended')) if last else None,
                     'check_seconds': sum(timed) if timed else None, 'untimed_checks': len(mine) - len(timed),
                     'note': v.get('recheck_note') or (('bằng chứng không còn khớp bản hiện tại: ' + '; '.join(map(str, v.get('stale_reasons') or [])))[:200]
                                                      if v.get('stale') else None)})
    return {'revision': revision, 'rows': rows, 'timed': any(c.get('started') and c.get('ended') for r in rows for c in r['checks']),
            'basis': 'verdict.run_started → verdict.receipt_issued (thời gian chạy bộ kiểm) và verdict.recorded (kết quả); '
                     'không phải thời gian làm việc; khoảng trống giữa hai lần kiểm không phải thời gian chờ'}


def _engine(state, engine_view, active, needs, acceptance, level, progress=None):
    nodes = engine_view.get('nodes') or {}
    defs = {n.get('id'): n for n in ((engine_view.get('definition') or {}).get('nodes') or [])}
    def title(nid): return f"{nid} — {defs[nid]['goal']}"[:120] if defs.get(nid, {}).get('goal') else nid
    held = [nid for nid, r in nodes.items() if r.get('phase') == 'held']
    failed = sorted(set((engine_view.get('failed_blockers') or {})) | {nid for nid, r in nodes.items() if r.get('verification_result') == 'fail' and r.get('state') != 'verified'})
    produced = [nid for nid, r in nodes.items() if r.get('state') == 'produced']
    pending = [nid for nid, r in nodes.items() if r.get('phase') == 'pending']
    assigned = lambda nid: _who((defs.get(nid) or {}).get('executor'))
    if held or failed:
        target = (held or failed)[0]
        why = ('Phần việc ' + ', '.join(held) + ' bị giữ' + (': ' + str(nodes[held[0]].get('reason'))[:120] if nodes[held[0]].get('reason') else '')) if held \
            else 'Phần việc ' + ', '.join(failed) + ' kiểm không đạt'
        return 'fix', why, 'Sửa ' + title(target) + ' rồi kiểm lại', assigned(target), 'assigned' if assigned(target) else None
    stalled = [nid for nid, p in (progress or {}).items() if p.get('status') == 'blocked' and nodes.get(nid, {}).get('phase') == 'running']
    if stalled:                     # the running attempt's own executor reported it is blocked: still running, not "needs a fix"
        why = (progress[stalled[0]].get('reason') or '')[:160]
        return 'doing', 'Phần việc ' + ', '.join(stalled) + ' đang chạy nhưng báo bị chặn' + (': ' + why if why else ''), \
            'Gỡ chặn cho ' + title(stalled[0]), assigned(stalled[0]), 'assigned' if assigned(stalled[0]) else None
    if active:
        target = next((a.get('node') for a in active if a.get('node')), None)
        return 'doing', 'Đang có lượt chạy' + (' của phần việc ' + target if target else ''), \
            ('Chờ lượt chạy của ' + title(target) + ' kết thúc') if target else 'Chờ lượt chạy kết thúc', assigned(target) if target else None, \
            'assigned' if target and assigned(target) else None
    if produced:
        return 'check', 'Phần việc ' + ', '.join(produced) + ' đã có đầu ra, chưa kiểm', 'Kiểm đầu ra của ' + title(produced[0]), CHECKER, 'checker'
    if level == 'verified':
        if acceptance.get('ready'): return 'accept', 'Mọi phần việc đã kiểm đạt', 'Bạn nghiệm thu hoặc nêu điều chưa đạt', OWNER, 'owner'
        return 'check', acceptance.get('reason') or 'Chờ kiểm đủ điều kiện bàn giao', 'Hoàn tất kiểm bàn giao', CHECKER, 'checker'
    if not nodes:
        return 'todo', 'Đã duyệt, chưa có kế hoạch nội bộ', 'Lập kế hoạch nội bộ (engine revise)', None, None
    started = any(r.get('attempt') or r.get('state') not in (None, 'none') for r in nodes.values())
    if pending:
        return ('doing' if started else 'todo'), ('Chờ bắt đầu phần việc ' + ', '.join(pending)) if started else 'Đã duyệt, chưa phần việc nào bắt đầu', \
            'Bắt đầu ' + title(pending[0]), assigned(pending[0]), 'assigned' if assigned(pending[0]) else None
    return 'unknown', 'Không có phần việc đang chạy, bị giữ hay chờ; sổ không đủ để kết luận', None, None, None


def _plain(views, rows, acceptance, level, has_started):
    by_id = {r['id']: r for r in rows}
    failed = [v['id'] for v in views if by_id.get(v['id'], {}).get('state') == 'failed']
    checking = [v['id'] for v in views if by_id.get(v['id'], {}).get('state') == 'checking']
    recheck = [v['id'] for v in views if by_id.get(v['id'], {}).get('state') == 'recheck']
    left = [v['id'] for v in views if by_id.get(v['id'], {}).get('state') == 'pending']
    if checking:
        return 'check', 'Đang kiểm mốc ' + _names(checking), 'Chờ kết quả kiểm ' + _names(checking), CHECKER, 'checker'
    if failed:
        return 'fix', 'Mốc ' + _names(failed) + ' kiểm không đạt', 'Sửa và kiểm lại mốc ' + _names(failed), None, None
    if recheck:
        return 'check', 'Mốc ' + _names(recheck) + ' cần kiểm lại (bằng chứng cũ không còn được tính)', 'Kiểm lại mốc ' + _names(recheck), None, None
    if level == 'verified' or not left:
        if acceptance.get('ready'): return 'accept', 'Mọi mốc đã kiểm đạt', 'Bạn nghiệm thu hoặc nêu điều chưa đạt', OWNER, 'owner'
        return 'check', acceptance.get('reason') or 'Mọi mốc có kết quả đạt, chưa đủ điều kiện nghiệm thu', 'Hoàn tất kiểm bàn giao', None, None
    if not has_started:
        return 'todo', 'Đã duyệt, chưa có lần kiểm nào', 'Làm và kiểm mốc ' + left[0], None, None
    return 'doing', 'Chưa kiểm mốc ' + _names(left), 'Làm và kiểm mốc ' + left[0], None, None


def situation(*, state, views, checks, engine_view, attempts, active, requests, needs, acceptance, level, has_started, guidance, status_kind, status_reason,
              progress=None):
    """The `situation` of one root (see the module docstring). `checks` is milestone_checks(...) for a root without an engine, else None."""
    acceptance = acceptance or {}
    rows = (checks or {}).get('rows') or []
    unknown_attempts = [a for a in attempts if a.get('status') == 'unknown']
    lost_checks = [(r['id'], c) for r in rows for c in r['checks'] if c.get('state') == 'lost']
    live_checks = [r['id'] for r in rows if r['state'] == 'checking']
    by, by_text, next_text, src = None, None, None, ['tracking.situation']
    if state['status'] == 'accepted':
        stage, reason = 'done', 'Bạn đã nghiệm thu'
    elif state['status'] == 'closed':
        stage, reason = 'closed', 'Plan đã đóng; đóng không phải nghiệm thu'
    elif state['status'] == 'stopped_with_report' or ((guidance or {}).get('state') == 'stopped' and not active):
        stage = 'stopped'
        reason = ('Dừng có báo cáo ở mốc ' + str((state['stopped'].get(state['latest']) or {}).get('milestone') or '?')) if state['status'] == 'stopped_with_report' \
            else str((guidance or {}).get('reason') or 'OneCrew đã dừng việc này')[:200]
        next_text = 'Đọc báo cáo dừng và quyết định đi tiếp hay kết thúc'
    elif state['status'] == 'proposed' and not has_started:
        stage, reason = 'todo', f"Kế hoạch bản {state['latest']} chưa được duyệt"
    elif unknown_attempts:
        stage, reason = 'unknown', 'Lượt chạy ' + ', '.join(str(a.get('id'))[:16] for a in unknown_attempts[:2]) + ' mất tín hiệu: kết quả chưa xác định'
        next_text = 'Đối chiếu lượt chạy trước khi làm tiếp (engine reconcile)'
    elif lost_checks and not live_checks:
        mid, c = lost_checks[-1]
        stage, reason = 'unknown', f"Lần kiểm mốc {mid} mất tín hiệu ({'tiến trình không còn' if c.get('lost') == 'process_gone' else 'quá hạn chạy'}): kết quả chưa xác định"
        next_text = 'Kiểm lại mốc ' + mid
    elif engine_view is not None:
        stage, reason, next_text, by_text, by = _engine(state, engine_view, active, needs, acceptance, level, progress)
    elif views:
        stage, reason, next_text, by_text, by = _plain(views, rows, acceptance, level, has_started)
    else:
        stage, reason = 'unknown', status_reason or 'Hợp đồng không đọc được; không suy được trạng thái'
    owner_needs = [n for n in (needs or []) if n.get('kind') in ('approve', 'request', 'accept', 'stopped')]
    if owner_needs:
        n = owner_needs[0]
        by, by_text = 'owner', OWNER
        next_text = n.get('owner_ask') or {'approve': 'Duyệt hoặc yêu cầu sửa kế hoạch', 'accept': 'Nghiệm thu hoặc nêu điều chưa đạt',
                                          'stopped': 'Quyết định sau khi dừng', 'request': 'Trả lời câu hỏi'}[n['kind']] \
            + (': ' + str(n.get('question'))[:140] if n['kind'] == 'request' and n.get('question') else '')
        src.append('needs_user:' + n['kind'])
    if stage in ('done', 'closed'): next_text, by, by_text = None, None, None
    if not by_text and next_text: by_text = NO_HANDLER
    running = [a for a in active if a.get('status') in ('reserved', 'running')]
    if running:
        names = [('phần việc ' + a['node']) if a.get('node') else ('lượt ' + str(a.get('attempt'))[:12]) for a in running]
        # the latest sourced signal of a running attempt: its start or its executor's last progress observation; how old it is, not a verdict on it
        signals = [a.get('since') for a in running] + [((progress or {}).get(a.get('node')) or {}).get('observed_at') or ((progress or {}).get(a.get('node')) or {}).get('received_at')
                                                        for a in running if a.get('node')]
        stamps = [t for t in (_at(x) for x in signals if x) if t]
        activity = {'running': True, 'text': 'Sổ ghi lượt chạy đang mở: ' + ', '.join(names), 'since': min((a.get('since') for a in running if a.get('since')), default=None),
                    'last_signal': _iso(max(stamps)) if stamps else None}
    elif live_checks:
        starts = [c.get('started') for r in rows if r['id'] in live_checks for c in r['checks'] if c.get('state') == 'open']
        activity = {'running': True, 'text': 'Đang chạy bộ kiểm mốc ' + _names(live_checks), 'since': min([s for s in starts if s], default=None)}
    elif status_kind == 'running':
        activity = {'running': True, 'text': 'Có hoạt động đang chạy theo sổ', 'since': None}
    else:
        activity = {'running': False, 'text': NOTHING_RUNS, 'since': None}
    activity.setdefault('last_signal', None)
    passed = len([v for v in views if v.get('state') == 'passed']) if views and engine_view is None else None
    milestones = {'passed': passed, 'total': len(views), 'text': f'Đạt {passed}/{len(views)} mốc',
                  'note': 'số mốc đạt, không phải phần trăm công việc'} if passed is not None else None
    return {'stage': stage, 'label': STAGES[stage], 'reason': reason, 'next': next_text, 'next_by': by,
            'next_by_text': by_text if next_text else None, 'activity': activity, 'milestones': milestones,
            'no_owner_decision': not owner_needs, 'source': src}
