"""Checkpoint effort warnings: deterministic inbox decisions, never AI polling."""
import datetime as dt
from .ledger import LedgerError
from .usage import summarize

POLICY = {'calls': 20, 'seconds': 600}


def check(runtime, task_id, seq, state):
    control = runtime.control.status(task_id)
    if (control['cancel_requested'] or control['status'] == 'paused'
            or state['phase'] in ('completed','cancelled','failed','blocked','waiting_operation')
            or state.get('pending') or any(a['status'] != 'settled' for a in control['attempts'])):
        return seq, False
    now = runtime.control.clock()
    if 'effort_watch' not in state:
        task = runtime.ledger.task(task_id)
        state['effort_watch'] = {'round':0, 'started_at':task['created_at'], 'calls':0,
                                 'policy':dict(POLICY), 'request':None}
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
    elapsed = max(0, (now-dt.datetime.fromisoformat(watch['started_at'])).total_seconds())
    calls = control['used_calls']-watch['calls']
    if calls < watch['policy']['calls'] and elapsed < watch['policy']['seconds']: return seq, False
    usage = summarize(state.get('usage',[]),control['attempts'])
    tokens = usage['totals_observed_only']['total_tokens']
    remaining = max(0,control['budget']['limits']['max_calls']-control['used_calls']-control['reserved_calls'])
    question = {'schema_version':1,
        'question':'Task đã kéo dài hoặc dùng nhiều lượt. Anh muốn tiếp tục, tạm dừng để điều chỉnh, hay dừng?',
        'reason':f"Từ mốc theo dõi: {int(elapsed//60)} phút (có thể gồm thời gian chờ), {calls} lượt model. "
                 f"Toàn task: {control['used_calls']} lượt; {tokens} token quan sát; "
                 f"{len(usage['unknown_attempts'])} lượt chưa đo được token. "
                 f"Đã đọc {len(state.get('files',{}))} file; {len(state.get('tests',[]))} kết quả kiểm thử; "
                 f"{len(state.get('outputs',[]))} phần bàn giao. Kế hoạch do worker báo: {str(state.get('plan',''))[:800]}",
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
