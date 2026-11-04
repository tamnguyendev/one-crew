"""Reusable exact-byte Git delivery with journaled effects and read-only reconciliation."""
import json
import os
from pathlib import Path
import re
import uuid
from types import SimpleNamespace

from .discovery import Discovery, EXCLUDED
from .integration import Integration
from .ledger import LedgerError
from .snapshots import scoped_path


from .effects_core import EffectUnknown

def bindings(runtime, remote):
    if not remote: return {}
    found={};count=0
    for directory,dirs,_ in os.walk(runtime.ledger.project,followlinks=False):
        count+=1
        if count>2000: raise LedgerError('Repository discovery limit reached; use a narrower project root.')
        root=Path(directory)
        dirs[:]=[d for d in dirs if d.lower() not in EXCLUDED and not (root/d).is_symlink()
                 and not (hasattr(root/d,'is_junction') and (root/d).is_junction())]
        if (root/'.git').exists():
            relative=root.relative_to(runtime.ledger.project).as_posix()
            adapter=GitDelivery(runtime,None,{},'' if relative=='.' else relative)
            raw=adapter.git('remote','get-url','--push','--all',remote,allow_failure=True)
            if raw:
                urls=raw.decode().strip().splitlines()
                if len(urls)!=1 or '::' in urls[0] or re.search(r'https?://[^/]*@',urls[0]):
                    raise LedgerError('Unsupported or credential-bearing remote URL.')
                found[adapter.directory]=urls[0]
    if not found: raise LedgerError('No authorized remote found under project root.')
    return found


class GitDelivery:
    def __init__(self,runtime,task_id,profile,directory):
        self.runtime=runtime;self.task_id=task_id;self.profile=profile;self.directory=directory
        self.root=runtime.ledger.project if not directory else Discovery(runtime.ledger.project).path(directory)
        if not self.root.is_dir(): raise LedgerError('Repository directory not found.')
        ledger=SimpleNamespace(project=self.root,state_root=runtime.ledger.state_root)
        self.integration=Integration(SimpleNamespace(ledger=ledger,store=runtime.store))
        top=self.git('rev-parse','--show-toplevel').decode().strip()
        if Path(top).resolve()!=self.root.resolve(): raise LedgerError('Select a repository root, not a subdirectory.')

    def git(self,*args,**kwargs):
        # Even a status probe must not refresh/write the user's index stat cache.
        return self.integration.git('--no-optional-locks',*args,**kwargs)

    def status(self):
        data=self.git('status','--porcelain=v1','-z','--untracked-files=all')
        if len(data)>32000: raise LedgerError('Git status exceeds bound; select a narrower repository/task.')
        entries=[]
        raw=data.split(b'\0');i=0
        while i<len(raw):
            item=raw[i];i+=1
            if not item: continue
            status=item[:2].decode();path=item[3:].decode('utf-8')
            rename=bool(set(status)&{'R','C'})
            if rename: i+=1
            try: Discovery(self.root).path(path)
            except LedgerError: continue
            entries.append({'status':status,'path':path,'rename':rename})
        branch=self.git('symbolic-ref','--quiet','--short','HEAD',allow_failure=True)
        return {'repository':self.directory,'head':self.git('rev-parse','HEAD').decode().strip(),
                'branch':branch.decode().strip() if branch else None,'detached':not bool(branch),
                'dirty':bool(data),'changes':entries}

    def diff(self,path):
        import difflib
        from .discovery import scan_text
        target=Discovery(self.root).path(path)
        old=self.git('show','HEAD:'+scoped_path(path),allow_failure=True) or b''
        new=Discovery(self.root).data(path) if target.exists() else b''
        # Never invoke external diff drivers or expose credential-bearing historical blobs.
        before=scan_text(old);after=scan_text(new)
        value=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile=path,tofile=path))
        return {'path':path,'diff':value[:12000],'truncated':len(value)>12000}

    def _check(self,payload):
        from .sandbox_gate import task_guard
        task_guard(self.runtime.control,self.task_id)()
        remote=self.git('remote','get-url','--push','--all',self.profile['remote']).decode().strip()
        if remote!=payload['remote']: raise LedgerError('Remote changed after authorization.')
        if self.runtime.store.capture(self.root,payload['paths'])!=payload['source_snapshot']:
            raise LedgerError('Source HEAD/index/working bytes changed after sealing.')

    def _observe(self,payload):
        raw=self.git('ls-remote','--refs',payload['remote'],payload['ref'])
        target=raw.decode().strip().split()
        local=self.git('show-ref','--verify','--hash',payload['ref'],allow_failure=True)
        return {'verified':bool(target and target[0]==payload['commit'] and local and local.decode().strip()==payload['commit']),
                'commit':payload['commit'],'ref':payload['ref'],'remote':payload['remote'],
                'paths':payload['paths'],'directory':self.directory,'source_modified':False,'candidate_snapshot':payload.get('candidate_snapshot')}

    def deliver(self,paths,message,key,candidate=None):
        if not isinstance(paths,list) or not 1<=len(paths)<=100 or len(set(paths))!=len(paths):
            raise LedgerError('Delivery requires 1-100 unique relative file paths.')
        if not isinstance(message,str) or not 1<=len(message)<=500: raise LedgerError('Invalid commit message.')
        config=self.runtime.control.status(self.task_id)['configuration']
        remote=config.get('remote_bindings',{}).get(self.directory)
        if not remote: raise LedgerError('Repository remote was not authorized at enable.')
        control=self.runtime.control
        with self.runtime.ledger.transaction() as conn:
            old=conn.execute('SELECT * FROM actions WHERE task_id=? AND request_key=?',(self.task_id,key)).fetchone()
        if old:
            action=dict(old);payload=json.loads(action['payload'])
            if sorted(paths)!=payload['paths'] or self.directory!=payload['directory'] or message!=payload['message']:
                raise LedgerError('Delivery replay differs from sealed intent.')
        else:
            for path in paths:
                scoped_path(path)
                # Scan bytes before snapshots, including selected index versions.
                target=Discovery(self.root).path(path)
                if target.exists(): Discovery(self.root).data(path)
                elif not candidate and not self.git('ls-tree','HEAD','--',path).strip():
                    raise LedgerError('Selected missing path is not a tracked deletion.')
            snapshot=self.runtime.store.capture(self.root,paths)
            manifest=self.runtime.store.load(snapshot)
            from .discovery import scan_text
            for item in manifest['files'].values():
                for row in item['index']: scan_text(self.runtime.store.read_blob(row['blob']))
            if candidate:
                for path,item in manifest['files'].items():
                    rootpath=(self.directory+'/'+path).lstrip('/')
                    if rootpath not in candidate['files'] or item['working']!=candidate['original'].get(rootpath):
                        raise LedgerError('Candidate source changed or file was not captured.')
                    item['working']=candidate['files'][rootpath]
            if not manifest['head']: raise LedgerError('Delivery requires existing HEAD.')
            ref='refs/heads/'+self.profile['branch']
            if self.git('show-ref','--verify','--hash',ref,allow_failure=True) or self.git('ls-remote','--refs',remote,ref).strip():
                raise LedgerError('Delivery branch already exists; it will not be overwritten.')
            directory=self.runtime.ledger.state_root/'integration'/uuid.uuid4().hex
            directory.mkdir(parents=True)
            tree=self.integration.tree(manifest,manifest['head'],directory/'index')
            if tree==self.git('rev-parse',manifest['head']+'^{tree}').decode().strip(): raise LedgerError('Selected files have no changes.')
            commit=self.git('commit-tree',tree,'-p',manifest['head'],'-m',message).decode().strip()
            payload={'directory':self.directory,'remote':remote,'ref':ref,'commit':commit,'tree':tree,
                     'paths':sorted(paths),'source_snapshot':snapshot,'message':message,
                     'candidate_snapshot':candidate['snapshot'] if candidate else None}
            self._check(payload)
            action=control.propose_action(self.task_id,key,payload)
        if action['status']=='proposed':
            control.authorize_action(action['id'],action['revision']);action['status']='authorized'
        if action['status'] in ('unknown','executing'):
            return control.reconcile_action(action['id'],action['revision'],self._observe)
        if action['status']=='verified':
            if not self._observe(payload)['verified']: raise LedgerError('Published ref moved; receipt is stale.')
            return json.loads(action['receipt'])
        def apply(value):
            self._check(value)
            self.git('update-ref',value['ref'],value['commit'],'0'*len(value['commit']))
            self._check(value)
            # An empty expected old SHA requires remote absence, even if another publisher races us.
            self.git('-c','push.followTags=false','push','--no-verify','--recurse-submodules=no',
                     '--force-with-lease='+value['ref']+':',value['remote'],value['commit']+':'+value['ref'])
            return self._observe(value)
        return control.execute_action(action['id'],apply)
