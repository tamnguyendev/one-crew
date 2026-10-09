"""Small deterministic review cards; no model call for summaries or status."""
import json


def compact(text, limit=180):
    value = ' '.join(str(text or '').split())
    return value if len(value) <= limit else value[:limit-1]+'…'


def status(value):
    state, control = value['state'], value['control']
    if not state:
        return 'Chưa enable workflow.'
    plan = (state.get('plan') or {}).get('tasks', [])
    done = set(state['done'])
    ready = [r['id'] for r in plan if r['id'] not in done and r['id'] not in state.get('branch_errors', {}) and set(r['depends_on']) <= done]
    active = [a for a in control['attempts'] if a['status'] != 'settled']
    limits = control['budget']['limits']
    lines = [f"{control['task_id']} | {control['status']} | {len(done)}/{len(plan)} việc",
             f"Kiểm chứng: {state['verification']} | Nghiệm thu: {state['acceptance']}",
             f"Calls: {control['used_calls']}/{limits['max_calls']} đã dùng; {control['reserved_calls']} đang giữ | attempts active/unknown: {len(active)}",
             f"Deadline: {control['deadline']}",
             'Sẵn sàng theo dependency: '+(', '.join(ready) or 'không có')]
    if state.get('message'):
        lines.append('Vấn đề: '+compact(state['message']))
    if state.get('waiting_reason'):
        lines.append('Đang chờ: '+state['waiting_reason'])
    usage = value.get('usage_summary')
    if usage:
        totals = usage['totals_observed_only']
        lines.append(f"Usage đã quan sát: {totals['total_tokens']} Codex tokens; {totals['kiro_credits']:.6f} Kiro credits; {len(usage['unknown_attempts'])} attempts chưa rõ usage.")
    if state.get('quota_binding'):
        binding = state['quota_binding']
        lines.append(f"Quota: {binding['provider']}/{binding['bucket']} | observation hết hạn {binding['quota']['expires_at']} | có reservation dự toán")
    lines += [f"Workflow revision: {value['workflow_revision']}",
              f"Plan revision: {value['plan_revision'] or 'chưa có'}",
              f"Budget revision: {control['budget']['revision']}",
              f"Xem kết quả: work outputs {control['task_id']} | Câu hỏi: request list --pending"]
    return '\n'.join(lines)


def outputs(value, full=False):
    lines = [f"{value['task_id']} | {value.get('execution', value['phase'])}",
             f"Kiểm chứng: {value['verification']} | Nghiệm thu: {value['acceptance']}"]
    if value.get('message'):
        lines.append('Vấn đề: '+compact(value['message']))
    if not value['outputs']:
        lines.append('Chưa có output được công bố.')
    for index, item in enumerate(value['outputs'], 1):
        lines += ['', f"{index}. {item['stage']} — {compact(item['summary'])}",
                  f"   Gate: {item['verification']} | Review: {item['acceptance']}",
                  f"   Revision: {item['revision']}"]
        if full:
            lines += [item['diff'] or '(Không có diff)']
    checks = value.get('checks')
    if checks:
        rows = checks.get('checks', [])
        lines += ['', f"Checks được cấu hình: {sum(r['passed'] is True for r in rows)}/{len(rows)} đạt."]
        for row in rows:
            lines.append(f"  {'PASS' if row['passed'] is True else 'FAIL'} {row['id']}: {compact(row['detail'])}")
        if full:
            lines.append(json.dumps(checks, ensure_ascii=False, indent=2))
    if value['reviews']:
        lines += ['', f"Lịch sử review: {len(value['reviews'])} ý kiến/quyết định."]
        for row in value['reviews'][-5:]:
            lines.append(f"  {row['revision'][:12]} {row['decision']}: {compact(row['comment'])}")
    if value['backlog']:
        lines += ['', 'Ngoài phạm vi, chưa thực hiện:'] + ['  - '+compact(x) for x in value['backlog']]
    if value.get('integration_issues'):
        lines += ['', 'Lịch sử ghép Git có lỗi/conflict (khác gate của snapshot gốc):']
        for item in value['integration_issues']:
            lines.append('  '+item['kind']+' | '+item['target']+' | base '+item['expected'][:12])
    if value.get('deliveries'):
        lines += ['', 'Git delivery:']
        for item in value['deliveries']:
            lines.append('  '+item['id']+' | '+item['status'])
    lines += ['', f"Chi tiết diff/evidence: work outputs {value['task_id']} --full",
              f"Góp ý: work review {value['task_id']} --revision <revision ở trên> --decision feedback --comment <nội dung>",
              'Chỉ accept revision hiện tại đã pass gate. Pass test chưa phải khách hàng nghiệm thu.']
    return '\n'.join(lines)
