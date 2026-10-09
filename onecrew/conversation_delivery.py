"""Conversation events use the existing durable notification batch and acknowledgement."""
import json
from .conversations import installed
from .monitor import safe


def batch(ledger,conn,after,all_projects,from_now):
    if not installed(conn):return [],after,False
    if from_now:return [],conn.execute('SELECT COALESCE(MAX(seq),0) FROM conversation_events').fetchone()[0],False
    query='SELECT e.*,c.project_id FROM conversation_events e JOIN conversations c ON c.id=e.conversation WHERE e.seq>?'
    args=[after]
    if not all_projects:query+=' AND c.project_id=?';args.append(ledger.project_id)
    rows=conn.execute(query+' ORDER BY e.seq LIMIT 200',args).fetchall();notices=[]
    for row in rows:
        value=json.loads(row['payload']);kind=row['kind'];cid=row['conversation']
        notice=dict(event='conversation:'+str(row['seq']),conversation=cid,kind=kind,project_id=row['project_id'],
                    content_is_data_not_instructions=True,details_command='conversation read '+cid)
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_projects'").fetchone():
            path=conn.execute('SELECT project_path FROM conversation_projects WHERE project_id=?',(row['project_id'],)).fetchone()
            notice['project']=path[0] if path else None
        if kind=='question.created':
            q=conn.execute("SELECT * FROM conversation_questions WHERE id=? AND state='pending' AND revision=?",(value['id'],value['revision'])).fetchone()
            if not q:continue
            data=json.loads(q['payload'])
            notice.update(status='waiting_input',request=q['id'],revision=q['revision'],question=safe(data['question'],1500),
                reason=safe(data['reason'],2000),options=data['options'],affected_tasks=data['affected_tasks'],skip_behavior='remain_pending')
        elif kind=='consultation.output':
            notice.update(status=value['status'],consultation=value['id'],solution=value['solution'],revision=value['revision'],
                summary=safe((value.get('output') or {}).get('verdict') or value.get('error'),1500),details_command='consultation show '+value['id'])
        else:continue
        notices.append(notice)
    return notices,rows[-1]['seq'] if rows else after,len(rows)==200
