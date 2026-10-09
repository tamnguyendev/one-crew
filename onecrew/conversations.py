"""Project-scoped shared discussion in the existing ledger, without worker calls.

Local operator provenance is attribution, not multi-user authentication.
"""
import difflib
import json
import uuid

from .ledger import LedgerError, canonical, content_hash, key_field, text_field, utcnow, exact_fields
from .discovery import scan_text

DDL=(
    '''CREATE TABLE IF NOT EXISTS conversation_projects(project_id TEXT PRIMARY KEY, project_path TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
       request_key TEXT NOT NULL, initial_hash TEXT NOT NULL, title TEXT NOT NULL,
       status TEXT NOT NULL, current_solution TEXT, summary TEXT, created_at TEXT NOT NULL,
       UNIQUE(project_id,request_key))''',
    '''CREATE TABLE IF NOT EXISTS conversation_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
       id TEXT UNIQUE NOT NULL, conversation TEXT NOT NULL REFERENCES conversations(id),
       request_key TEXT NOT NULL, identity_hash TEXT NOT NULL, kind TEXT NOT NULL,
       payload TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(conversation,request_key))''',
    '''CREATE TABLE IF NOT EXISTS solutions(id TEXT PRIMARY KEY, conversation TEXT NOT NULL REFERENCES conversations(id),
       revision TEXT NOT NULL, parent TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS solution_decisions(id TEXT PRIMARY KEY, solution TEXT NOT NULL REFERENCES solutions(id),
       revision TEXT NOT NULL, choice TEXT NOT NULL, source TEXT NOT NULL, reference TEXT NOT NULL,
       created_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS conversation_questions(id TEXT PRIMARY KEY, conversation TEXT NOT NULL REFERENCES conversations(id),
       revision TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, answer TEXT, created_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS solution_bindings(task_id TEXT PRIMARY KEY REFERENCES tasks(id),
       conversation TEXT NOT NULL, solution TEXT NOT NULL, revision TEXT NOT NULL, decision TEXT NOT NULL)''',
)


def installed(conn):
    return bool(conn and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversations'").fetchone())


def ensure(conn):
    for statement in DDL: conn.execute(statement)


def clean(value,name,limit=12000):
    text_field(value,name,limit);scan_text(value.encode());return value


def _row(ledger,conn,cid):
    row=conn.execute('SELECT * FROM conversations WHERE id=? AND project_id=?',(cid,ledger.project_id)).fetchone() if installed(conn) else None
    if row is None: raise LedgerError('Unknown conversation in this project.')
    return row


def _solution(ledger,conn,sid,revision=None):
    row=conn.execute('SELECT s.* FROM solutions s JOIN conversations c ON c.id=s.conversation WHERE s.id=? AND c.project_id=?',(sid,ledger.project_id)).fetchone() if installed(conn) else None
    if row is None: raise LedgerError('Unknown solution in this project.')
    if revision is not None and row['revision']!=revision: raise LedgerError('Stale solution revision.')
    return dict(row,payload=json.loads(row['payload']))


def _event(conn,cid,key,kind,payload):
    key_field(key);digest=content_hash({'kind':kind,'payload':payload})
    row=conn.execute('SELECT * FROM conversation_events WHERE conversation=? AND request_key=?',(cid,key)).fetchone()
    if row:
        if row['identity_hash']!=digest: raise LedgerError('Conversation request key conflicts with prior contribution.')
        return dict(row,payload=json.loads(row['payload']),acknowledged=True)
    mid='MSG-'+uuid.uuid4().hex
    conn.execute('INSERT INTO conversation_events(id,conversation,request_key,identity_hash,kind,payload,created_at) VALUES(?,?,?,?,?,?,?)',
        (mid,cid,key,digest,kind,canonical(payload),utcnow()))
    return dict(conn.execute('SELECT * FROM conversation_events WHERE id=?',(mid,)).fetchone(),payload=payload,acknowledged=True)


def create(ledger,title,request_key,source='cli'):
    clean(title,'title',200);key_field(request_key);clean(source,'source',100)
    initial=content_hash({'title':title,'source':source})
    with ledger.transaction(write=True) as conn:
        ensure(conn)
        conn.execute('INSERT OR REPLACE INTO conversation_projects VALUES(?,?)',(ledger.project_id,ledger.project_path))
        old=conn.execute('SELECT * FROM conversations WHERE project_id=? AND request_key=?',(ledger.project_id,request_key)).fetchone()
        if old:
            if old['initial_hash']!=initial: raise LedgerError('Conversation key has different initial data.')
            return dict(old)
        cid='CONV-'+uuid.uuid4().hex
        conn.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?,?)',(cid,ledger.project_id,request_key,initial,title,'open',None,None,utcnow()))
        _event(conn,cid,'created','conversation.created',{'title':title,'source':source})
        return dict(_row(ledger,conn,cid))


def list_conversations(ledger):
    with ledger.transaction() as conn:
        if not installed(conn):return []
        return [dict(r) for r in conn.execute('SELECT id,title,status,current_solution,created_at FROM conversations WHERE project_id=? ORDER BY created_at DESC LIMIT 100',(ledger.project_id,))]


def append(ledger,cid,request_key,text,source,kind='proposal',reply_to=None,base_revision=None):
    if kind not in ('user_message','proposal','critique','clarification','evidence','assistant_message'):
        raise LedgerError('Contribution is data, not a decision or runtime command.')
    clean(text,'text');clean(source,'source',100)
    with ledger.transaction(write=True) as conn:
        ensure(conn);row=_row(ledger,conn,cid)
        if row['status']!='open':raise LedgerError('Conversation is archived.')
        if reply_to and not conn.execute('SELECT 1 FROM conversation_events WHERE id=? AND conversation=?',(reply_to,cid)).fetchone():
            raise LedgerError('Reply refers to a different or missing conversation event.')
        if base_revision and not conn.execute('SELECT 1 FROM solutions WHERE revision=? AND conversation=?',(base_revision,cid)).fetchone():
            raise LedgerError('Unknown base solution revision.')
        return _event(conn,cid,request_key,kind,dict(text=text,source=source,reply_to=reply_to,base_revision=base_revision,authority='none'))


def validate_solution(value):
    exact_fields(value,('brief','detail','acceptance','non_goals','assumptions','questions'),'Solution')
    clean(value['brief'],'brief',6000);clean(value['detail'],'detail',24000)
    if len(value['brief'].split())>350:raise LedgerError('Solution brief exceeds 350 words.')
    for field in ('acceptance','non_goals','assumptions','questions'):
        if not isinstance(value[field],list) or len(value[field])>30:raise LedgerError('Bounded solution lists required.')
        for item in value[field]:clean(item,field,1200)
    if not value['acceptance']:raise LedgerError('Solution requires acceptance criteria.')
    if len(canonical(value))>40000:raise LedgerError('Solution exceeds context bound.')
    return value


def propose(ledger,cid,request_key,payload,source,expected_current=None):
    validate_solution(payload);clean(source,'source',100)
    with ledger.transaction(write=True) as conn:
        ensure(conn);row=_row(ledger,conn,cid)
        identity={'payload':payload,'source':source,'expected_current':expected_current}
        old=conn.execute('SELECT payload FROM conversation_events WHERE conversation=? AND request_key=?',(cid,request_key)).fetchone()
        if old:
            data=json.loads(old['payload'])
            if data.get('identity')!=identity:raise LedgerError('Conflicting solution proposal key.')
            return data
        if expected_current:
            parent=_solution(ledger,conn,expected_current)
            if parent['conversation']!=cid:raise LedgerError('Parent solution belongs to another conversation.')
        sid='SOL-'+uuid.uuid4().hex;revision=content_hash(payload)
        conn.execute('INSERT INTO solutions VALUES(?,?,?,?,?,?)',(sid,cid,revision,expected_current,canonical(payload),utcnow()))
        selected=row['current_solution']==expected_current and row['status']=='open'
        if selected:conn.execute('UPDATE conversations SET current_solution=? WHERE id=?',(sid,cid))
        result=dict(id=sid,revision=revision,selected=selected,conflict=not selected,identity=identity)
        _event(conn,cid,request_key,'solution.proposed',result)
        return result


def select(ledger,cid,sid,expected_current,source):
    clean(source,'source',100)
    with ledger.transaction(write=True) as conn:
        row=_row(ledger,conn,cid);sol=_solution(ledger,conn,sid)
        if sol['conversation']!=cid:raise LedgerError('Wrong conversation.')
        if row['current_solution']!=expected_current:raise LedgerError('Current solution changed; review before selecting.')
        conn.execute('UPDATE conversations SET current_solution=? WHERE id=?',(sid,cid))
        return _event(conn,cid,'select:'+uuid.uuid4().hex,'solution.selected',{'solution':sid,'source':source})


def show_solution(ledger,sid):
    with ledger.transaction() as conn:
        sol=_solution(ledger,conn,sid)
        decision=conn.execute('SELECT * FROM solution_decisions WHERE solution=? ORDER BY rowid DESC LIMIT 1',(sid,)).fetchone()
        sol['decision']=dict(decision) if decision else None
        parent=_solution(ledger,conn,sol['parent']) if sol['parent'] else None
        render=lambda p:json.dumps(p,ensure_ascii=False,indent=2).splitlines(True)
        sol['diff']=''.join(difflib.unified_diff(render(parent['payload']) if parent else [],render(sol['payload']),fromfile=sol['parent'] or 'empty',tofile=sid))
        return sol


def decide(ledger,sid,revision,choice,source,reference):
    if choice not in ('approve','request_changes'):raise LedgerError('Invalid solution decision.')
    clean(source,'source',100);clean(reference,'actual user reference',1000)
    with ledger.transaction(write=True) as conn:
        sol=_solution(ledger,conn,sid,revision);row=_row(ledger,conn,sol['conversation'])
        if row['current_solution']!=sid:raise LedgerError('Cannot decide an outdated solution.')
        if choice=='approve' and sol['payload']['questions']:raise LedgerError('Resolve solution questions before approval.')
        old=conn.execute('SELECT * FROM solution_decisions WHERE solution=? ORDER BY rowid DESC LIMIT 1',(sid,)).fetchone()
        if old and all(old[k]==v for k,v in dict(revision=revision,choice=choice,source=source,reference=reference).items()):return dict(old)
        did='DEC-'+uuid.uuid4().hex
        conn.execute('INSERT INTO solution_decisions VALUES(?,?,?,?,?,?,?)',(did,sid,revision,choice,source,reference,utcnow()))
        result=dict(conn.execute('SELECT * FROM solution_decisions WHERE id=?',(did,)).fetchone())
        _event(conn,sol['conversation'],did,'solution.decision',result);return result


def approved(ledger,conn,sid,revision,current=True):
    sol=_solution(ledger,conn,sid,revision);row=_row(ledger,conn,sol['conversation'])
    if current and row['current_solution']!=sid:raise LedgerError('Submission requires current solution.')
    decision=conn.execute('SELECT * FROM solution_decisions WHERE solution=? ORDER BY rowid DESC LIMIT 1',(sid,)).fetchone()
    if not decision or decision['choice']!='approve' or decision['revision']!=revision:raise LedgerError('User approval of this solution revision is required.')
    return sol,dict(decision)


def summarize(ledger,cid,text,event_ids,covered_seq,source):
    clean(text,'summary',8000);clean(source,'source',100)
    if type(covered_seq) is not int or covered_seq<1 or not isinstance(event_ids,list) or not 1<=len(event_ids)<=100:
        raise LedgerError('Summary needs bounded source event references and covered_seq.')
    with ledger.transaction(write=True) as conn:
        _row(ledger,conn,cid)
        for mid in event_ids:
            if not conn.execute('SELECT 1 FROM conversation_events WHERE id=? AND conversation=? AND seq<=?',(mid,cid,covered_seq)).fetchone():raise LedgerError('Summary source outside conversation or covered range.')
        latest=conn.execute('SELECT MAX(seq) FROM conversation_events WHERE conversation=?',(cid,)).fetchone()[0]
        if covered_seq>latest:raise LedgerError('Summary cannot cover future events.')
        value=dict(text=text,event_ids=event_ids,covered_seq=covered_seq,source=source,authority='none',semantic_verification='unverified')
        conn.execute('UPDATE conversations SET summary=? WHERE id=?',(canonical(value),cid))
        return value


def read(ledger,cid,after=0,limit=20):
    if type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=100:raise LedgerError('Invalid conversation page.')
    with ledger.transaction() as conn:
        row=_row(ledger,conn,cid)
        rows=conn.execute('SELECT * FROM conversation_events WHERE conversation=? AND seq>? ORDER BY seq LIMIT ?',(cid,after,limit+1)).fetchall()
        events=[];size=0
        for event in rows[:limit]:
            if events and size+len(event['payload'])>60000:break
            events.append(dict(event,payload=json.loads(event['payload'])));size+=len(event['payload'])
        summary=json.loads(row['summary']) if row['summary'] else None
        latest=conn.execute('SELECT MAX(seq) FROM conversation_events WHERE conversation=?',(cid,)).fetchone()[0] or 0
        if after>latest:raise LedgerError('Cursor is beyond this conversation.')
        if summary:summary['stale']=summary['covered_seq']<latest
        sol=_solution(ledger,conn,row['current_solution']) if row['current_solution'] else None
        decision=conn.execute('SELECT * FROM solution_decisions WHERE solution=? ORDER BY rowid DESC LIMIT 1',(sol['id'],)).fetchone() if sol else None
        pending=[dict(q,payload=json.loads(q['payload'])) for q in conn.execute("SELECT * FROM conversation_questions WHERE conversation=? AND state='pending' ORDER BY created_at",(cid,))]
        bindings=[dict(b) for b in conn.execute('SELECT * FROM solution_bindings WHERE conversation=?',(cid,))]
        task_questions=[]
        for b in bindings:
            task_questions.extend(ledger._request_view(q) for q in conn.execute("SELECT * FROM requests WHERE task_id=? AND state='pending'",(b['task_id'],)))
        cursor=events[-1]['seq'] if events else after
        from .consultations import installed as consultations_installed,view as consultation_view
        reviews=[]
        if consultations_installed(conn):
            for q in conn.execute('SELECT id FROM consultations WHERE conversation=? ORDER BY rowid DESC LIMIT 20',(cid,)):
                review=consultation_view(ledger,q['id'],conn)
                reviews.append({k:review[k] for k in ('id','status','stale','actual_model')} | {
                    'solution':review['request']['solution'],'revision':review['request']['revision'],
                    'provider':review['request']['route']['provider'],'verdict':str((review['output'] or {}).get('verdict',''))[:500],
                    'details':'consultation show '+review['id']})
        return dict(id=cid,title=row['title'],status=row['status'],solution=sol,decision=dict(decision) if decision else None,
            summary=summary,events=events,cursor=cursor,latest_cursor=latest,has_more=cursor<latest,
            pending_questions=pending,pending_task_questions=task_questions,tasks=bindings,consultations=reviews,trust='local_attribution_only',private_chat_imported=False)
