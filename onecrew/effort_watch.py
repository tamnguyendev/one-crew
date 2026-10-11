"""Checkpoint effort warnings: deterministic inbox decisions, never AI polling."""
import datetime as dt
from .ledger import LedgerError
from .usage import summarize

POLICY = {'calls': 20, 'seconds': 600}


def check(runtime, task_id, seq, state):
    control = runtime.control.status(task_id)
    from .delivery_store import root_id
    with runtime.ledger.transaction() as conn: root=root_id(conn,task_id)
    if root and root!=task_id:return seq,False  # The parent owns shared-budget warnings.
    if root:
        goal=control['budget']['goal']
        if goal['active_attempts']:return seq,False
        control=dict(control,used_calls=goal['used_calls'],reserved_calls=goal['reserved_calls'])
    if (control['cancel_requested'] or control['status'] == 'paused'
            or state['phase'] in ('completed','cancelled','failed','blocked','waiting_operation')
            or state.get('pending') or any(a['status'] != 'settled' for a in control['attempts'])):
        return seq, False
    now = runtime.control.clock()
    if 'effort_watch' not in state:
        task = runtime.ledger.task(task_id,full=True)
        from .budget_policy import watch_policy
        policy = task['handoff'].get('owned_execution',{}).get('budget_policy')
        state['effort_watch'] = {'round':0, 'started_at':task['created_at'], 'calls':0,
                                 'policy':watch_policy(policy,control['budget']['limits']['max_calls'],
                                                       (dt.datetime.fromisoformat(control['deadline'])-dt.datetime.fromisoformat(task['created_at'])).total_seconds()), 'request':None}
    watch = state['effort_watch']
    parameters = {'round':watch['round'], 'started_at':watch['started_at']}
    # Recovers a crash after request creation but before checkpoint persistence.
    request = next((r for r in runtime.ledger.requests(task_id)
                    if r['question']['action'] == {'type':'job.effort_warning','parameters':parameters}), None)
    if request:
        watch['request'] = request['id']
        if request['state'] == 'pending':
            state.update(phase='waiting', waiting_reason='user', message='Effort warning: awaiting user decision.')
            return runtime.persist(task_id,seq,state), True
        answer = request['answer']; choice = answer['choice']
        if choice not in ('continue','pause','stop'):
            raise LedgerError('Unknown effort-warning choice; no continuation authorized.')
        watch.update(round=watch['round']+1, started_at=now.isoformat(), calls=control['used_calls'], request=None)
        if watch['policy'].get('version') == 2:
            from .budget_policy import watch_policy
            watch['policy']=watch_policy({'version':2,'warning_fraction':watch['policy']['fraction']},
                max(0,control['budget']['limits']['max_calls']-control['used_calls']-control['reserved_calls']),
                max(0,(dt.datetime.fromisoformat(control['deadline'])-now).total_seconds()))
        state.setdefault('consumed_replies',[]).append({'request_id':request['id'],'reply_id':answer['id'],
            'effect':'Effort warning: '+choice+'; hard budget, scope and prior evidence unchanged.'})
        state.pop('waiting_reason',None)
        if choice == 'stop':
            runtime.control.cancel(task_id)
            state.update(phase='cancelled', message='Stopped by user after effort warning; evidence retained.')
        elif choice == 'pause':
            runtime.control.pause(task_id)
            state.update(phase='paused', message='Paused by user for review or scope clarification.')
        else:
            state.update(phase='running', message='User chose to continue within the existing grant.')
        return runtime.persist(task_id,seq,state), choice != 'continue'
    if runtime.ledger.requests(task_id,pending=True): return seq, True
    # Hard exhaustion is handled by dispatch gates, not a misleading offer to
    # continue with no budget. Already pending questions remain pending above.
    if (control['used_calls']+control['reserved_calls'] >= control['budget']['limits']['max_calls']
            or now >= dt.datetime.fromisoformat(control['deadline'])): return seq, False
    elapsed = max(0, (now-dt.datetime.fromisoformat(watch['started_at'])).total_seconds())
    calls = control['used_calls']-watch['calls']
    time_due = not control['budget'].get('time_unlimited') and elapsed >= watch['policy']['seconds']
    if calls < watch['policy']['calls'] and not time_due: return seq, False
    usage = summarize(state.get('usage',[]),control['attempts'])
    tokens = usage['totals_observed_only']['total_tokens']
    remaining = max(0,control['budget']['limits']['max_calls']-control['used_calls']-control['reserved_calls'])
    native=state.get('native_change',{})
    assessment={'used_calls':control['used_calls'],'remaining_calls':remaining,'deadline':control['deadline'],
                'snapshot':state.get('snapshot'),'tests_passed':sum(t.get('passed') is True for t in state.get('tests',[])),
                'tests_failed':sum(t.get('passed') is False for t in state.get('tests',[])),
                'outputs':len(state.get('outputs',[])), 'native_stage':native.get('stage'),
                'repair_rounds':native.get('repairs'), 'remaining_scope':'unknown; see worker plan and evidence',
                'automatic_extension':False}
    watch['assessment']=assessment
    question = {'schema_version':1,
        'question':('Task đã tới mốc đánh giá 70% ngân sách được cấp. Anh muốn tiếp tục, tạm dừng hay dừng?'
                    if watch['policy'].get('version')==2 else 'Task đã kéo dài hoặc dùng nhiều lượt. Anh muốn tiếp tục, tạm dừng để điều chỉnh, hay dừng?'),
        'reason':f"Từ mốc theo dõi: {int(elapsed//60)} phút (có thể gồm thời gian chờ), {calls} lượt model. "
                 f"Toàn task: {control['used_calls']} lượt; {tokens} token quan sát; "
                 f"{len(usage['unknown_attempts'])} lượt chưa đo được token. "
                 f"Đã đọc {len(state.get('files',{}))} file; {len(state.get('tests',[]))} kết quả kiểm thử; "
                 f"{len(state.get('outputs',[]))} phần bàn giao. Test đạt/lỗi: {assessment['tests_passed']}/{assessment['tests_failed']}; "
                 f"giai đoạn native: {assessment['native_stage']}; vòng sửa: {assessment['repair_rounds']}. "
                 f"Chưa có ước lượng chắc chắn cho phần còn lại. Kế hoạch do worker báo: {str(state.get('plan',''))[:800]}",
        'impact':f"Chờ tại checkpoint, không gọi thêm AI. Còn tối đa {remaining} lượt trong hard budget; "
                 f"deadline {control['deadline']}. Tiếp tục chỉ đặt lại mốc cảnh báo, không tăng ngân sách. "
                 'Tạm dừng giữ kết quả để trao đổi lại phạm vi. Bỏ qua/ack không phải câu trả lời.',
        'options':[{'id':'continue','label':'Tiếp tục tới mốc cảnh báo kế tiếp'},
                   {'id':'pause','label':'Tạm dừng để xem kết quả hoặc thu hẹp yêu cầu'},
                   {'id':'stop','label':'Dừng task, giữ kết quả đã có'}],
        'recommendation':'pause',
        'action':{'type':'job.effort_warning','parameters':parameters}}
    request = runtime.ledger.create_request(task_id,'effort-warning:'+str(watch['round']),question)
    watch['request'] = request['id']
    state.update(phase='waiting',waiting_reason='user',message='Effort warning: awaiting user decision.')
    return runtime.persist(task_id,seq,state), True
