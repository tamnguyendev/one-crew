"""Host-owned black-box checks; product code never receives the Docker socket."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
import shutil
import socket
import time
from .runtime import Halt, save

PDF=b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'

class DockerGate:
    def __init__(self,runner):
        self.r=runner; self.docker=shutil.which('docker'); self.image=None
        self.network='onecrew-'+runner.id.lower(); self.names=[]

    def docker_cmd(self,*args,timeout=30,cleanup=False):
        return self.r.command([self.docker,*args],timeout=timeout,cleanup=cleanup)

    def preflight(self):
        if not self.docker or not shutil.which('codex'): raise Halt('blocked','Docker and Codex CLI are required before dispatch.')
        code,out,err=self.docker_cmd('info','--format','{{.OSType}}',timeout=15)
        if code or out.strip()!='linux': raise Halt('blocked','Docker Linux Engine unavailable; zero model calls made. Start Engine, then create a new run.')
        code,out,err=self.docker_cmd('image','inspect','node:24-alpine','--format','{{.Id}}')
        if code:
            code,out,err=self.docker_cmd('pull','node:24-alpine',timeout=180)
            if code: raise Halt('blocked','Cannot obtain official Node container image.')
            code,out,err=self.docker_cmd('image','inspect','node:24-alpine','--format','{{.Id}}')
        if code or not out.strip().startswith('sha256:'): raise Halt('blocked','Cannot pin Node image identity.')
        self.image=out.strip(); self.r.state['image_id']=self.image; self.r.event('preflight_passed',image=self.image)

    def start(self,mode='demo'):
        with socket.socket() as s: s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        name=f'{self.network}-{mode}-{self.r.state["repairs"]}'
        self.names.append(name)
        save(self.r.root/'resources.json',{'network':self.network,'containers':self.names,'label':self.r.id})
        args=['run','-d','--name',name,'--label',f'onecrew.run={self.r.id}',
            '--network',self.network,'--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--pids-limit','64','--memory','256m','--cpus','1','--user','1000:1000',
            '--tmpfs','/data:rw,noexec,nosuid,size=300m,uid=1000,gid=1000,mode=0700',
            '--mount',f'type=bind,source={self.r.output},target=/app,readonly','--workdir','/app',
            '-p',f'127.0.0.1:{port}:8080','-e','PORT=8080','-e','HOST=0.0.0.0','-e','DATA_DIR=/data',
            '-e',f'APP_ORIGIN={origin}','-e',f'CV_GUARD_MODE={mode}',self.image,'node','server.mjs']
        code,out,err=self.docker_cmd(*args)
        if code: raise AssertionError('Container startup: '+err[-1500:])
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            self.r.check()
            try:
                if self.request(port,'GET','/')[0] ==200: return port
            except (OSError,http.client.HTTPException): pass
            time.sleep(.25)
        code,out,err=self.docker_cmd('logs','--tail','30',name)
        raise AssertionError('Server did not become healthy: '+(out+err)[-3000:])

    def request(self,port,method,path,body=None,headers=None):
        self.r.check()
        data=json.dumps(body,ensure_ascii=False).encode('utf-8') if isinstance(body,dict) else body
        hs={'Origin':f'http://127.0.0.1:{port}'}
        if isinstance(body,dict): hs['Content-Type']='application/json'
        hs.update(headers or {})
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        try:
            conn.request(method,path,body=data,headers=hs); response=conn.getresponse()
            content=response.read(1000000); result=content.decode('utf-8',errors='replace')
            if 'json' in response.getheader('content-type',''):
                try: result=json.loads(result)
                except ValueError: pass
            return response.status,dict((k.lower(),v) for k,v in response.getheaders()),result
        finally: conn.close()

    def setup(self):
        code,out,err=self.docker_cmd('network','create','--internal','--label',f'onecrew.run={self.r.id}',self.network)
        if code: raise Halt('blocked','Cannot create isolated Docker internal network: '+err[-500:])
        code,out,err=self.docker_cmd('network','inspect',self.network,'--format','{{.Internal}}')
        if code or out.strip()!='true': raise Halt('blocked','Docker internal network isolation not confirmed.')

    def cleanup(self):
        errors=[]
        for name in self.names:
            code,out,err=self.docker_cmd('rm','-f',name,timeout=20,cleanup=True)
            if code and 'No such container' not in err: errors.append(err[-500:])
        self.names=[]
        code,out,err=self.docker_cmd('network','rm',self.network,timeout=20,cleanup=True)
        if code and 'not found' not in err: errors.append(err[-500:])
        if errors: raise Halt('blocked','Container cleanup not confirmed: '+'; '.join(errors))

    def verify(self):
        passed=[]; failures=[]
        def case(name,ac,fn):
            try: fn(); passed.append(name)
            except Halt: raise
            except (AssertionError,KeyError,ValueError,TypeError,OSError,http.client.HTTPException) as e:
                failures.append({'requirement':ac,'test':name,'error':str(e) or 'assertion failed'})
        try:
            self.setup()
            try: port=self.start()
            except AssertionError as e: return {'passed':False,'checks':[],'failures':[{'requirement':'CV-UI','test':'server-start','error':str(e)}]}
            def session():
                status,headers,data=self.request(port,'POST','/api/session')
                assert status==200,f'session status={status} body={data}'
                cookie=headers['set-cookie']; assert 'httponly' in cookie.lower() and 'samesite=strict' in cookie.lower()
                return {'Cookie':cookie.split(';')[0],'X-CSRF-Token':data['nonce']}
            def prepare(h,content=PDF):
                payload={'name':'Ứng viên Mẫu','email':'test@example.com','role':'Kỹ sư phần mềm','consent':True,
                    'file':{'name':'sample.pdf','size':len(content),'sha256':hashlib.sha256(content).hexdigest()}}
                status,_,data=self.request(port,'POST','/api/prepare',payload,h)
                assert status==200,f'prepare status={status} body={data}'
                return {**h,'X-CV-Pending':data['pendingId']}
            def verified(h):
                status,_,data=self.request(port,'POST','/api/verify',{'token':'local-demo-confirmed'},h)
                assert status==200,f'verify status={status} body={data}'
                return {**h,'X-Action-Permit':data['permit'],'Content-Type':'application/pdf'}
            def html():
                status,headers,body=self.request(port,'GET','/')
                assert status==200 and isinstance(body,str)
                assert '<form' in body.lower() and 'type="file"' in body.lower() and '<label' in body.lower(),'Missing accessible form/file input in SSR HTML'
                status,_,config=self.request(port,'GET','/api/config'); assert status==200 and config['mode']=='demo'
                assert 'no-store' in headers.get('cache-control','') and headers.get('x-content-type-options')=='nosniff'
                assert "frame-ancestors 'none'" in headers.get('content-security-policy','')
            case('SSR form, mode and security headers','CV-UI',html)
            def origin():
                assert self.request(port,'POST','/api/session',headers={'Origin':'https://evil.test'})[0]==403
                assert self.request(port,'POST','/api/commit',PDF,{'Content-Type':'application/pdf'})[0]==403
            case('Cross-origin and direct upload denied','CV-SESSION',origin)
            def no_permit():
                h=prepare(session()); assert self.request(port,'POST','/api/commit',PDF,{**h,'Content-Type':'application/pdf'})[0]==403
                assert self.request(port,'POST','/api/verify',{'token':'bad-token'},h)[0]==403
            case('Missing permit and invalid challenge denied','CV-CHALLENGE',no_permit)
            def happy():
                h=verified(prepare(session()))
                one=self.request(port,'POST','/api/commit',PDF,h); two=self.request(port,'POST','/api/commit',PDF,h)
                assert one[0]==201,f'first commit={one}'
                assert two[0]==200 and one[2]['receipt']==two[2]['receipt'],'Replay creates another result'
                assert one[2]['status']=='quarantined_unscanned'
                assert self.request(port,'GET','/api/receipt',headers=h)[2]['receipt']==one[2]['receipt']
            case('Submission, quarantine, idempotency and receipt','CV-COMMIT',happy)
            def changed():
                h=verified(prepare(session())); assert self.request(port,'POST','/api/commit',PDF+b'changed',h)[0]==409
            case('Changed bytes after prepare denied','CV-COMMIT',changed)
            def wrong_session():
                h=verified(prepare(session())); other=session(); h.update(other)
                assert self.request(port,'POST','/api/commit',PDF,h)[0] in (403,409)
            case('Valid second session cannot reuse pending','CV-SESSION',wrong_session)
            def concurrent():
                h=verified(prepare(session()))
                with ThreadPoolExecutor(max_workers=4) as pool: rows=list(pool.map(lambda _:self.request(port,'POST','/api/commit',PDF,h),range(4)))
                assert sorted(x[0] for x in rows)==[200,200,200,201],str(rows)
                assert len({x[2]['receipt'] for x in rows})==1
            case('Concurrent replay has one effect','CV-COMMIT',concurrent)
            def invalid_pdf():
                content=b'not really a PDF document at all'
                h=verified(prepare(session(),content)); assert self.request(port,'POST','/api/commit',content,h)[0]==400
            case('PDF masquerade denied','CV-FILE',invalid_pdf)
            def oversize():
                h=verified(prepare(session()))
                status=self.request(port,'POST','/api/commit',b'x'*(5242880+1),h)[0]
                assert status==413,f'oversize={status}'
            case('Upload body cap','CV-FILE',oversize)
            def private():
                for path in ('/.data/cv.sqlite','/data/cv.sqlite','/../server.mjs','/server.mjs'):
                    assert self.request(port,'GET',path)[0] in (400,403,404),path
            case('Private source/data not served','CV-FILE',private)
            def limits():
                h=session(); statuses=[]
                for _ in range(32):
                    statuses.append(self.request(port,'POST','/api/prepare',{},h))
                limited=[x for x in statuses if x[0]==429]
                assert limited and int(limited[0][1].get('retry-after','0'))>0,'No session quota/Retry-After'
            case('Session rate limit','CV-RATE',limits)
            def locked():
                locked_port=self.start('locked')
                assert self.request(locked_port,'POST','/api/session')[0]==503
            case('Locked mode fails closed','CV-CHALLENGE',locked)
            return {'passed':not failures,'checks':passed,'failures':failures}
        finally:
            self.cleanup()

class WindowsGate(DockerGate):
    """Native OS write confinement + Node resource guards; not a malicious-code VM."""
    def __init__(self,runner):
        super().__init__(runner)
        self.codex=shutil.which('codex'); self.node=shutil.which('node'); self.children=[]

    def sandbox_args(self,data):
        return [self.codex,'--no-daemon','sandbox','-P',':workspace','-C',str(self.r.output),
                self.node,'--permission',f'--allow-fs-read={self.r.output}',f'--allow-fs-write={data}']

    def preflight(self):
        if not self.codex or not self.node: raise Halt('blocked','Codex and Node are required.')
        data=self.r.output/'.data-probe'; data.mkdir()
        sentinel=self.r.root/'boundary-sentinel.txt'; sentinel.write_text('host-only probe',encoding='utf-8')
        probe='''const fs=require('node:fs');let denied=0;for(const op of [()=>fs.readFileSync(process.argv[1]),()=>fs.writeFileSync(process.argv[1],'changed'),()=>require('node:child_process').spawn('whoami')]){try{op()}catch(e){denied++}}fs.writeFileSync(process.argv[2]+'/ok','ok');if(denied!==3)process.exit(8);console.log('NODE_GUARDS_OK');'''
        code,out,err=self.r.command(self.sandbox_args(data)+['-e',probe,str(sentinel),str(data)],timeout=30)
        if code or 'NODE_GUARDS_OK' not in out or sentinel.read_text(encoding='utf-8')!='host-only probe': raise Halt('blocked','Native resource guards not confirmed: '+err[-700:])
        # Independent OS check, without the Node permission flags.
        os_probe="try{require('node:fs').writeFileSync(process.argv[1],'changed');process.exit(8)}catch(e){console.log('OS_WRITE_DENIED')}"
        code,out,err=self.r.command([self.codex,'--no-daemon','sandbox','-P',':workspace','-C',str(self.r.output),self.node,'-e',os_probe,str(sentinel)],timeout=30)
        if code or 'OS_WRITE_DENIED' not in out or sentinel.read_text(encoding='utf-8')!='host-only probe': raise Halt('blocked','Native OS write confinement failed.')
        self.r.state['execution_adapter']='codex-windows-sandbox+node-permission'
        self.r.state['isolation_note']='OS confines writes to workspace; Node guards fs reads/child processes. Native code is not treated as a malicious-code security VM. No production secrets supplied.'
        self.r.event('preflight_passed',adapter=self.r.state['execution_adapter'])

    def setup(self): pass

    def start(self,mode='demo'):
        import os,subprocess
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        data=self.r.output/f'.data-{self.r.state["repairs"]}-{mode}';data.mkdir()
        origin=f'http://127.0.0.1:{port}'
        # Only explicit app settings are injected. Clear common model/cloud secret variables.
        env={k:v for k,v in os.environ.items() if not any(word in k.upper() for word in ('TOKEN','SECRET','PASSWORD','API_KEY','AWS_','AZURE_','GOOGLE_','NODE_OPTIONS'))}
        env.update(PORT=str(port),HOST='127.0.0.1',DATA_DIR=str(data),APP_ORIGIN=origin,CV_GUARD_MODE=mode)
        prefix=self.r.root/f'native-{self.r.state["repairs"]}-{mode}'
        out=prefix.with_suffix('.stdout').open('wb');err=prefix.with_suffix('.stderr').open('wb')
        args=self.sandbox_args(data)+['server.mjs']
        child=subprocess.Popen(args,cwd=self.r.output,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        self.children.append((child,out,err));save(self.r.root/'native-resources.json',{'processes':[c.pid for c,_,_ in self.children],'run':self.r.id})
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            self.r.check()
            if child.poll() is not None:break
            try:
                if self.request(port,'GET','/')[0]==200:return port
            except (OSError,http.client.HTTPException):pass
            time.sleep(.25)
        out.flush();err.flush()
        raise AssertionError('Native server did not start: '+prefix.with_suffix('.stderr').read_text(encoding='utf-8',errors='replace')[-3000:])

    def cleanup(self):
        from .runtime import kill_tree
        try:
            for child,out,err in self.children:
                try:kill_tree(child)
                finally:out.close();err.close()
        finally:self.children=[]
