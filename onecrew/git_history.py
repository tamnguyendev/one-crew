"""Read commit evidence and create an authorized local branch before a selected change."""
import json
import re
from .ledger import LedgerError
from .discovery import Discovery, scan_text
from .owned_git import GitDelivery


class History(GitDelivery):
    def commit(self,value):
        if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',value):
            raise LedgerError('Use a full commit SHA returned by history tools.')
        resolved=self.git('rev-parse','--verify',value+'^{commit}').decode().strip()
        if resolved!=value: raise LedgerError('Commit identity mismatch.')
        return value

    def head(self): return self.git('rev-parse','HEAD').decode().strip()

    def log(self,head,cursor=0,query=''):
        self.commit(head)
        if type(cursor) is not int or not 0<=cursor<=100000: raise LedgerError('Invalid history cursor.')
        if not isinstance(query,str) or len(query)>100: raise LedgerError('Invalid literal message filter.')
        args=['log','--first-parent','--format=%H%x00%P%x00%aI%x00%s','--max-count=21','--skip='+str(cursor)]
        if query: args+=['--fixed-strings','--regexp-ignore-case','--grep='+query]
        data=self.git(*args,head,'--').decode('utf-8',errors='replace')
        rows=[]
        for line in data.splitlines():
            values=line.split('\0',3)
            if len(values)!=4: raise LedgerError('Unexpected history record.')
            commit,parents,date,subject=values
            try: subject=scan_text(subject.encode())[:500]
            except LedgerError: subject='[message withheld by content policy]'
            rows.append(dict(commit=commit,parents=parents.split(),date=date,subject=subject))
        return {'head':head,'traversal':'first-parent','commits':rows[:20],
                'next_cursor':cursor+20 if len(rows)>20 else None,'query':query}

    def show(self,head,commit,path=None,cursor=0):
        self.commit(commit)
        if self.git('merge-base','--is-ancestor',commit,self.commit(head),allow_failure=True) is None:
            raise LedgerError('Commit is outside the captured HEAD ancestry.')
        if type(cursor) is not int or cursor<0: raise LedgerError('Invalid history cursor.')
        meta=self.git('show','-s','--format=%H%x00%P%x00%aI%x00%s',commit).decode('utf-8',errors='replace').strip().split('\0',3)
        result={'commit':meta[0],'parents':meta[1].split(),'date':meta[2],'subject':scan_text(meta[3].encode())[:500]}
        parent=result['parents'][0] if result['parents'] else None
        if path is None:
            args=['diff-tree','--no-commit-id','--name-only','-r','-z']
            raw=self.git(*args,*([parent,commit] if parent else ['--root',commit]))
            paths=[]
            for name in raw.decode('utf-8').split('\0'):
                if not name: continue
                try: Discovery(self.root).path(name)
                except LedgerError: continue
                paths.append(name)
            window=paths[cursor:cursor+100]
            nc=cursor+100 if cursor+100<len(paths) else None
            na=('More filenames: git_show same commit with cursor=%s (still the file LIST, not a diff).' % nc) if nc is not None else ('File list complete (all %d filenames returned). To see a file diff, call git_show with the same commit and path=<one of these filenames>, cursor=0; pick the file yourself. Re-calling this list returns the same result.' % len(paths))
            result.update(paths=window,total_paths=len(paths),next_cursor=nc,
                mode='changed_file_list',cursor_unit='file index (100 filenames per page)',
                returned_files=[cursor,cursor+len(window)],next_action=na)
        else:
            Discovery(self.root).path(path)
            import difflib
            before=self.git('show',parent+':'+path,allow_failure=True) if parent else b''
            after=self.git('show',commit+':'+path,allow_failure=True)
            if max(len(before or b''),len(after or b''))>200000: raise LedgerError('Historical file exceeds 200 KB.')
            diff=''.join(difflib.unified_diff(scan_text(before or b'').splitlines(True),scan_text(after or b'').splitlines(True),fromfile='parent/'+path,tofile=commit[:12]+'/'+path))
            nd=cursor+12000 if cursor+12000<len(diff) else None
            na2=('More of this file diff: git_show same commit+path with cursor=%s.' % nd) if nd is not None else ('This file diff is complete; pick another path or act on the evidence.')
            result.update(path=path,diff=diff[cursor:cursor+12000],next_cursor=nd,
                mode='file_diff',cursor_unit='character offset into this file diff',total_diff_chars=len(diff),
                returned_diff_chars=[cursor,min(cursor+12000,len(diff))],next_action=na2)
        return result

    def observe_branch(self,payload):
        value=self.git('show-ref','--verify','--hash',payload['ref'],allow_failure=True)
        return dict(payload,verified=value is not None and value.decode().strip()==payload['commit'],
                    checkout_modified=False,index_modified=False,pushed=False)

    def branch_before(self,head,first_change,key):
        if self.profile.get('mode')!='branch': raise LedgerError('Local historical branch is not authorized.')
        detail=self.show(head,first_change)
        if not detail['parents']: raise LedgerError('Root commit has no earlier state.')
        base=detail['parents'][0];ref='refs/heads/'+self.profile['branch']
        self.git('check-ref-format',ref)
        control=self.runtime.control
        with self.runtime.ledger.transaction() as conn:
            old=conn.execute('SELECT * FROM actions WHERE task_id=? AND request_key=?',(self.task_id,key)).fetchone()
        payload=dict(kind='historical_branch',directory=self.directory,head=head,first_change=first_change,commit=base,ref=ref)
        if old:
            action=dict(old)
            if json.loads(action['payload'])!=payload: raise LedgerError('Branch intent differs from existing action.')
        else:
            if self.head()!=head: raise LedgerError('HEAD moved since history inspection; start a fresh review.')
            if self.git('show-ref','--verify','--hash',ref,allow_failure=True): raise LedgerError('Branch already exists; will not overwrite it.')
            action=control.propose_action(self.task_id,key,payload)
        if action['status']=='proposed':
            control.authorize_action(action['id'],action['revision']);action['status']='authorized'
        if action['status'] in ('unknown','executing'):
            return control.reconcile_action(action['id'],action['revision'],self.observe_branch)
        if action['status']=='verified':
            if not self.observe_branch(payload)['verified']: raise LedgerError('Historical branch moved after receipt.')
            return json.loads(action['receipt'])
        def apply(value):
            from .sandbox_gate import task_guard
            task_guard(control,self.task_id)()
            if self.head()!=head: raise LedgerError('HEAD changed before branch creation.')
            self.git('update-ref',ref,base,'0'*len(base))
            return self.observe_branch(value)
        return control.execute_action(action['id'],apply)
