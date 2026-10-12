"""Bounded recovery for the delivery coordinator: classify, act inside the grant, ask once.

Policy is code; no model chooses a recovery. No action widens scope, budget, deadline or device
authority, and counters survive resume and coordinator restarts (they live in the checkpoint)."""
import datetime as dt
import re

from .ledger import LedgerError, content_hash, utcnow

POLICY_VERSION = 1
# class -> (automatic action, automatic attempts per failure signature before asking the user)
POLICY = {
    'transient': ('retry', 3),
    'interrupted': ('replay', 1),
    'environment': ('retry', 2),
    'product': ('repair', 2),
    'review': ('repair', 2),
    # A selector of a OneCrew-planned scenario that did not resolve on the live UI: recalibrate from its snapshot.
    'scenario_selector': ('calibrate', 2),
    # A pinned exact selector that does not match on a real device: stop at once with masked evidence.
    'selector_mismatch': ('ask', 0),
    'side_effect_unknown': ('reconcile', 1),
    'decision_pending': ('wait', 0),
    'permission': ('ask', 0),
    'budget': ('ask', 0),
    'drift': ('ask', 0),
    'artifact': ('ask', 0),
    'runtime_bug': ('ask', 0),
    'unknown': ('ask', 0),
}
BACKOFF = (15, 60, 180)
# Native work of these kinds writes only into fresh OneCrew captures, so an interrupted run can replay.
REPLAY_SAFE = {'regression', 'review', 'build', 'apk_audit', 'handover'}

# Ordered, first match wins. Typed exceptions are checked before this table; unknown text asks.
MESSAGES = [
    (r'deadline exhausted|budget exhausted|call cap|calls? exhausted|quota|continuation bound exhausted', 'budget'),
    (r'solution decision pending|pending question|pending root question|resolve the child question', 'decision_pending'),
    (r'stopped by a solution decision|approval is missing|requires a bound approved solution|exceeds the dispatch grant|'
     r'private references must be outside|outside the approved envelope|device permission expired|'
     r'requires permission not granted', 'permission'),
    (r'source drift|source changed|source differs|external edits|toolchain/scenario changed|changed since approval|'
     r'private (configuration|scenario inputs) changed|apk changed', 'drift'),
    (r'provider did not complete|supervisor_interrupted|interrupted native operation|prior launch must be reconciled|'
     r'container gate stopped by root', 'interrupted'),
    (r'native command deadline exceeded|adb operation failed|device offline|workflow changed concurrently|'
     r'hierarchy unavailable|already owns|winerror 32|being used by another process', 'transient'),
    (r'device not ready|android device unavailable|device viewport unavailable|java unavailable|android sdk unavailable|'
     r'tool unavailable|dependency cache unavailable|dependency graph missing|insufficient free space|path too long|'
     r'workspace unavailable|source root unavailable|reference unavailable|explicit materialization|'
     r'another window has foreground focus|keyboard bounds unknown|flutter sdk|not responding|'
     r'not usable after granted recovery|emulator', 'environment'),
    (r'operation outcome unknown|unknown device effect|an operation may have run', 'side_effect_unknown'),
    (r'exceeds the sealed plan|durable coordinator intent|missing current source provenance|stale verification evidence|'
     r'no ready delivery node|required criteria unresolved|controller error|lacks reviewed application evidence', 'runtime_bug'),
]
CHILD_PRODUCT = (r'invalid (report|patch|native review)|did not invoke the authorized|changed an unowned path|repair limit|'
                 r'narrow the goal|no new source/test progress|no_progress|turn limit')


def normalize(text):
    text=str(text or '').lower()
    text=re.sub(r'[a-z]:\\[^\s:\'"]+|/[^\s:\'"]*/[^\s:\'"]+','<path>',text)
    text=re.sub(r'\b(task|att|req|creq|sol)-[0-9a-f]{8,}\b',r'\1-#',text)
    text=re.sub(r'[0-9a-f]{12,}','#',text);text=re.sub(r'\d+','0',text)
    return re.sub(r'\s+',' ',text).strip()[:300]


def classify_error(error):
    from .provider_limits import QuotaExhausted
    if isinstance(error,QuotaExhausted):return 'budget'
    text=str(error).lower()
    if text.startswith('child task-'):return 'unknown'  # Callers lift the child's own state first.
    for pattern,name in MESSAGES:
        if re.search(pattern,text):return name
    return 'unknown'


FENCE=r'delivery root has a pending question|delivery root is stopped|delivery root not running'


def classify_child(child_state, pending):
    if pending:return 'decision_pending'
    if not child_state:return 'unknown'
    if re.search(FENCE,str(child_state.get('message') or ''),re.I):return 'fenced'  # stopped by the root itself, not a failure
    if child_state['phase'] in ('failed','cancelled'):return 'runtime_bug'
    recovery=child_state.get('recovery') or {}
    kind=recovery.get('kind')
    if kind in ('quota',):return 'budget'
    if kind in ('auth',):return 'permission'
    if kind=='environment':return 'environment'
    if kind=='controller':return 'runtime_bug'
    message=str(child_state.get('message') or '')
    if kind in ('no_progress','native_change','native_timeout') or re.search(CHILD_PRODUCT,message,re.I) or (child_state.get('native_change') or {}).get('pending_repair'):
        return 'product'
    found=classify_error(message)
    return found if found!='unknown' else 'unknown'


def build_class(log_text):
    """Compile errors in Dart sources are repairable product failures; Gradle/daemon hiccups are transient."""
    if re.search(r'(?m)^\S*?(lib|test)/\S+\.dart:\d+:\d+: Error:',log_text or ''):return 'product'
    if re.search(r'daemon (has )?(disappeared|terminated unexpectedly)|connection reset|timed out waiting|could not resolve|'
                 r'unable to (download|resolve)|network is unreachable',log_text or '',re.I):return 'transient'
    return 'environment'


def classify_receipt(node, receipt):
    """(class, signature key) of a failed node receipt; structured fields only, prose last."""
    kind=receipt.get('failure_kind')
    if receipt.get('uncertain'):return 'side_effect_unknown',normalize(receipt.get('detail'))
    if kind=='test':
        names=sorted({normalize(e.get('name')) for e in receipt.get('errors',[])})
        red=sorted(r['test'] for r in receipt.get('red',[]) if not r.get('behavioral_failure'))
        return 'product',{'failing':names,'red_missing':red,'counts':receipt.get('counts')}
    if kind=='review':
        verdict=receipt.get('verdict') or {}
        unresolved=sorted(normalize(x) for x in verdict.get('unresolved_required',[]) or [])
        failed=sorted(c.get('id','') for c in verdict.get('checks',[]) or [] if c.get('status')!='passed')
        if verdict.get('verdict')=='blocked' or any(c.get('status')=='blocked' for c in verdict.get('checks',[]) or []):
            return 'decision_needed',{'unresolved':unresolved,'checks':failed}
        return 'review',{'unresolved':unresolved,'checks':failed,'verdict':verdict.get('verdict')}
    if kind=='environment':
        text=''
        if receipt.get('log'):
            try:
                from pathlib import Path
                text=Path(receipt['log']).read_text(encoding='utf-8',errors='replace')[-200000:]
            except OSError:pass
        return build_class(text),normalize(receipt.get('detail'))
    if kind=='artifact':return 'artifact',normalize(receipt.get('detail'))
    if kind=='selector':
        # Only a scenario OneCrew planned is recalibrated, and only when rerunning it is safe.
        failure=receipt.get('selector_failure') or {}
        rerun=node['config'].get('replay_safe') or not receipt.get('steps')
        if receipt.get('selector_mode')=='exact':
            return 'selector_mismatch',{'step':failure.get('step'),'reason':failure.get('reason')}
        if node['config'].get('calibration')=='onecrew' and rerun and not receipt.get('uncertain'):
            return 'scenario_selector',{'step':failure.get('step'),'reason':failure.get('reason')}
        return 'device_assertion',normalize(receipt.get('detail'))
    if kind=='product':return 'product',normalize(receipt.get('detail'))
    detail=receipt.get('detail') or ''
    found=classify_error(detail)
    if node['kind']=='device':
        cls=found if found in ('transient','environment','drift','permission') else 'device_assertion'
        # Once a scenario step ran, a transport/focus failure is not a free retry: replay needs a replay-safe scenario.
        if cls in ('transient','environment') and (receipt.get('scenario_started') or receipt.get('steps')) and not node['config'].get('replay_safe'):
            cls='device_assertion'
        return cls,normalize(detail)
    return found,normalize(detail)


def signature(node_id, cls, key):
    return content_hash({'node':node_id,'class':cls,'key':key})[:24]


def progress(d, runtime_tree=None):
    passed=sorted(n for n,r in (d.get('nodes') or {}).items() if r.get('phase')=='passed')
    tools=(d.get('preflight') or {}).get('tools')
    return content_hash({'source':(d.get('source') or {}).get('hash'),'env':content_hash(tools) if tools else None,
                         'runtime':runtime_tree,'passed':passed,'generation':d.get('generation')})[:24]


def runtime_tree():
    try:
        from .interventions import runtime_revision
        return runtime_revision().get('tree')
    except (ImportError,ValueError,OSError,AttributeError):
        return None


def migrate(d):
    for key,value in (('failures',{}),('recoveries',[]),('escalations',[])):d.setdefault(key,value)
    return d


def decide(d, node_id, cls, key, detail, now=None, policy=None):
    """Record the failure and return (action, record). Never resets counters."""
    migrate(d);now=now or utcnow()
    sig=signature(node_id,cls,key);fp=progress(d,runtime_tree())
    rec=d['failures'].setdefault(sig,{'class':cls,'node':node_id,'detail':str(detail)[:500],'count':0,
        'attempts':[],'allowance':0,'first_at':now,'last_at':now,'status':'open'})
    action,limit=POLICY.get(policy or cls,('ask',0))
    if action=='wait' and rec['attempts'] and rec['attempts'][-1]['action']=='wait':
        return action,dict(rec,signature=sig,progress=fp)  # Still waiting on the same answer: no new history.
    rec['count']+=1;rec['last_at']=now;rec['detail']=str(detail)[:500]
    # Waiting for a live attempt to settle is not a recovery attempt; it never spends the allowance.
    automatic=[a for a in rec['attempts'] if a['action'] not in ('ask','wait','wait_settle')]
    if action=='wait':pass
    elif action!='ask' and len(automatic)>=limit+rec['allowance']:action='ask'
    # Same failure on the same material state means the last recovery made no progress.
    elif action in ('repair','replay','reconcile') and any(a['progress']==fp for a in automatic):action='ask'
    rec['attempts'].append({'at':now,'action':action,'progress':fp})
    rec['status']='escalated' if action=='ask' else 'waiting' if action=='wait' else 'recovering'
    return action,dict(rec,signature=sig,progress=fp)


def backoff(record):
    automatic=[a for a in record['attempts'] if a['action'] in ('retry','wait_settle')]
    return BACKOFF[min(max(len(automatic)-1,0),len(BACKOFF)-1)]


def schedule_retry(s, record, clock):
    seconds=backoff(record)
    s['delivery']['retry_after']=(clock+dt.timedelta(seconds=seconds)).isoformat()
    s.update(phase='waiting_operation',waiting_reason='recovery',
             message=f"Automatic recovery ({record['class']}): retry in {seconds}s, attempt "
                     f"{len([a for a in record['attempts'] if a['action']=='retry'])}; evidence retained.")


def due(s, clock):
    after=s['delivery'].get('retry_after')
    return not after or clock>=dt.datetime.fromisoformat(after)


GUIDANCE = {
    'environment':'Môi trường thiếu hoặc chưa sẵn sàng. Xử lý mục nêu trong chi tiết (cài/chuẩn bị đúng công cụ, thiết bị, bộ nhớ) rồi chọn thử lại.',
    'transient':'Lỗi tạm thời lặp lại quá giới hạn tự thử. Kiểm tra kết nối/thiết bị rồi chọn thử lại.',
    'drift':'Nguồn, công cụ hoặc cấu hình riêng đã thay đổi so với lúc niêm phong. OneCrew không tự chấp nhận thay đổi ngoài; khôi phục hoặc dừng.',
    'permission':'Thao tác vượt quyền/phạm vi đã duyệt. Cần duyệt lại solution/envelope; OneCrew không tự mở rộng.',
    'budget':'Hết ngân sách hoặc deadline. Chỉ người dùng được gia hạn (work extend); sau đó chọn thử lại, hoặc dừng.',
    'side_effect_unknown':'Có thể đã có tác động trên thiết bị nhưng không chứng minh được. Kiểm tra thiết bị/ứng dụng rồi chọn thử lại, hoặc dừng.',
    'artifact':'APK không đạt chính sách (chữ ký/package/16KB/kích thước). Cần quyết định về cấu hình build hoặc phụ thuộc.',
    'product':'Lỗi sản phẩm vẫn còn sau số vòng sửa cho phép. Xem bằng chứng; thử lại chỉ chạy lại, không tăng số vòng sửa.',
    'review':'Review chưa chấp nhận sau số vòng sửa cho phép.',
    'decision_needed':'Reviewer cần thông tin hoặc quyết định nghiệp vụ.',
    'device_assertion':'Kịch bản thiết bị không đạt ở bước kiểm tra. Có thể do sản phẩm, kịch bản hoặc thiết bị; cần người dùng xem.',
    'scenario_selector':'Selector của kịch bản vẫn không khớp UI thật sau số lần OneCrew tự hiệu chỉnh cho phép. Xem ảnh chụp UI trong bằng chứng.',
    'selector_mismatch':('Selector ghim (khớp chính xác) không khớp UI trên thiết bị thật. OneCrew không tự hiệu chỉnh và không gửi dữ '
                         'liệu màn hình cho model. Bằng chứng đã che (ui-<bước>.json): cấu trúc node và mức khớp so với giá trị mong đợi.'),
    'runtime_bug':'Lỗi runtime OneCrew. Cần sửa runtime; mọi can thiệp sẽ được ghi lại.',
    'unknown':'Lỗi chưa phân loại được.',
}


def question(record, node_id, left, episode, needs=None):
    cls=record['class']
    automatic=len([a for a in record['attempts'] if a['action'] not in ('ask','wait','wait_settle')])
    retry='Đã gia hạn/xử lý; tiếp tục trong grant hiện có' if cls=='budget' else 'Đã xử lý nguyên nhân; thử lại trong ngân sách hiện có'
    text=f"Task tổng dừng ở bước {node_id or 'chuẩn bị'} ({cls}). Anh muốn thử lại hay dừng?"
    reason=GUIDANCE.get(cls,GUIDANCE['unknown'])+' Chi tiết: '+record['detail']
    recommendation='retry'
    if needs:
        listed='; '.join(n.get('need','')[:200] for n in needs)
        text='OneCrew cần làm việc ngoài envelope đã duyệt: '+listed[:600]+'. Tiếp tục mà KHÔNG làm các việc này, hay dừng?'
        reason=('Các nhu cầu: '+'; '.join(n.get('need','')+' ('+n.get('reason','')+')' for n in needs)+
                '. Envelope duyệt sau không áp dụng cho task này; muốn mở rộng phạm vi thì dừng và giao task mới từ revision mới.')
        retry='Tiếp tục trong envelope hiện tại, KHÔNG làm: '+listed[:400]
        recommendation='stop'
    return {'schema_version':1,'question':text[:1900],'reason':reason[:1900],
        'impact':(f"Đợt hỏi {max(episode,1)} cho lỗi này; đã tự xử lý {automatic} lần. Không gọi thêm AI khi chờ. "
                  f"Còn khoảng {left} calls; deadline không tự gia hạn. "
                  'Thử lại giữ nguyên phạm vi, lịch sử lỗi và ngân sách. Bỏ qua/đóng cửa sổ không phải câu trả lời.')[:1900],
        'options':[{'id':'retry','label':retry[:500]},{'id':'stop','label':'Dừng task, giữ toàn bộ bằng chứng'}],
        'recommendation':recommendation,
        'action':{'type':'delivery.recovery','parameters':{'signature':record['signature'],'progress':record['progress'],
                                                           'node':node_id,'class':cls,'episode':episode}}}


def escalate(runtime, task_id, s, record, node_id, needs=None):
    """One single-use request per decision episode. A crash before the checkpoint reuses the same pending
    request; a blocker that returns after a consumed answer opens a new episode, never the answered request."""
    d=migrate(s['delivery'])
    stored=d['failures'].get(record['signature'])
    episode=len([a for a in (stored or record)['attempts'] if a['action']=='ask'])
    c=runtime.control.status(task_id);goal=c['budget'].get('goal')
    left=goal['remaining_calls'] if goal else max(0,c['budget']['limits']['max_calls']-c['used_calls']-c['reserved_calls'])
    payload=question(record,node_id,left,episode,needs)
    base='recovery:'+content_hash({'signature':record['signature'],'episode':episode})[:32]
    request=None
    for suffix in ('',':1',':2',':3'):
        key=base+suffix
        with runtime.ledger.transaction() as conn:
            old=conn.execute('SELECT id,state,revision FROM requests WHERE task_id=? AND request_key=?',(task_id,key)).fetchone()
        if old is None:request=runtime.ledger.create_request(task_id,key,payload);break
        if old['state']=='pending':
            current=runtime.ledger.request(old['id'])
            request=current if current['question']==payload else runtime.ledger.revise_request(old['id'],old['revision'],payload)
            break
        # Answered under this key already: a consumed decision is never adopted as the new one.
    if request is None:raise LedgerError('Recovery request keys exhausted for one episode; runtime defect.')
    d['escalation']={'request':request['id'],'signature':record['signature'],'class':record['class'],'node':node_id,'episode':episode}
    if needs is not None:d['escalation']['needs']=needs
    if not any(e['request']==request['id'] for e in d['escalations']):
        d['escalations'].append({'request':request['id'],'signature':record['signature'],'class':record['class'],
                                 'node':node_id,'at':utcnow()})
    s.pop('waiting_reason',None)
    s.update(phase='waiting',waiting_reason='decision',
             message=f"Cần quyết định ({record['class']}) ở {node_id or 'chuẩn bị'}: {record['detail'][:600]}")
    return request
