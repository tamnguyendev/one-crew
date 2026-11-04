"""Actual installed upgrade/rollback drill on GENERATED temporary fixtures only.

python -m wfkit.upgrade_drill --out <new-directory-under-OS-temp>
The archived d3120c6 baseline is chosen for the scanner's pre-namespace contract;
it is NOT represented as the nearest delivered build. One venv is reinstalled
old -> current -> old -> current. Receipts record wheel bytes, checkout base
commit/dirty state, installed origins, SQL/blob preservation and real local
Control reconcile order. No providers, live ledgers, monitor or owner verbs run.
This creates fixture evidence, not a release gate, pilot or owner acceptance.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from tests import wf_oldversion as old
from tests import wf_rollback as rollback
from tests import wf_wheel as wheel
from onecrew.ledger import LedgerError, canonical, content_hash
from onecrew.v2 import boundary, compat_scan

ROOT = Path(__file__).resolve().parents[1]


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(state):
    """Full retained SQL rows plus file hashes, excluding SQLite transient files."""
    state = Path(state)
    conn = sqlite3.connect((state/'ledger.sqlite3').as_uri()+'?mode=ro', uri=True)
    try:
        conn.execute('PRAGMA query_only=ON')
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        rows = {}
        for table in tables:
            quoted = '"'+table.replace('"','""')+'"'
            rows[table] = sorted([list(row) for row in conn.execute('SELECT * FROM '+quoted)], key=canonical)
    finally: conn.close()
    files = {p.relative_to(state).as_posix():sha(p) for p in state.rglob('*') if p.is_file()
             and p.name not in ('ledger.sqlite3','ledger.sqlite3-wal','ledger.sqlite3-shm')}
    return {'tables':rows,'files':files}


def guard_swap(state, expected_scan):
    """Reuse the existing rollback harness, adding a fresh ledger/input fence.

    `expected_scan` is the installed build's `compat scan --json` report: it decides too (W41). The swap is
    allowed only when BOTH the checkout scan and that report show zero blocks on the same fenced ledger."""
    total = (expected_scan.get('blocking') or {}).get('total') if isinstance(expected_scan, dict) else None
    if type(total) is not int or total < 0:
        raise LedgerError('The installed compat scan report has no blocking total; refuse installation swap.')
    current = rollback.rollback_drill(state)
    if not current['ran']: return current
    if any(current['scan'].get(key) != expected_scan.get(key) for key in ('ledger_sha','inputs_sha','old_version')):
        raise LedgerError('State or compatibility inputs changed after scan; refuse installation swap.')
    if total > 0:
        blocks = [b for root in expected_scan.get('roots', []) for b in root.get('blocks', [])]
        return {'ran': False, 'reason': 'installed_scan_blocked', 'blocks': blocks,
                'conditions': sorted({b.get('id') for b in blocks if b.get('id')}), 'scan': expected_scan,
                'checkout_scan': current['scan']}
    return current


@contextlib.contextmanager
def build_source(repo, use_gate_wheel=False, record_used=None):
    """Point the wheel builder at `repo`. use_gate_wheel keeps WF_WHEEL/WF_WHEEL_SHA256 (reuse a prebuilt wheel); record_used (default:
    same as use_gate_wheel) keeps WF_WHEEL_USED_LOG. A comparator/previous/baseline wheel is built with record_used=False: the gate's
    used-log proves which wheel the check CONSUMED as the build under test, and a rollback target is not that wheel."""
    original = wheel.REPO; saved = {key:os.environ.get(key) for key in ('WF_WHEEL','WF_WHEEL_SHA256','WF_WHEEL_USED_LOG')}
    wheel.REPO = Path(repo)
    if record_used is None: record_used = use_gate_wheel
    if not use_gate_wheel:
        for key in ('WF_WHEEL','WF_WHEEL_SHA256'): os.environ.pop(key,None)
    if not record_used: os.environ.pop('WF_WHEEL_USED_LOG',None)
    try: yield
    finally:
        wheel.REPO = original
        for key,value in saved.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value


@contextlib.contextmanager
def old_fixture_connections():
    """Old harness helpers predate explicit connection closing (needed on Windows)."""
    original = old._db
    with contextlib.ExitStack() as stack:
        def opened(*args, **kwargs):
            return stack.enter_context(contextlib.closing(original(*args, **kwargs)))
        old._db = opened
        try: yield
        finally: old._db = original


class Drill:
    def __init__(self, out, repo=ROOT, baseline='d3120c6'):
        self.out=Path(out).resolve(); self.repo=Path(repo).resolve()
        if not self.out.is_relative_to(Path(tempfile.gettempdir()).resolve()) or self.out.exists():
            raise LedgerError('Drill output must be a NEW directory under OS temp; no existing state-root is accepted.')
        self.out.mkdir(parents=True)
        self.baseline=self.git('rev-parse',baseline)
        if self.baseline != self.git('rev-parse',compat_scan.OLD_REVISION):
            raise LedgerError('The current compatibility scanner only models baseline '+compat_scan.OLD_REVISION+'.')
        self.records=[]; self.installs=[]; self.artifacts={}; self.counter=0

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],stderr=subprocess.PIPE).decode().strip()

    def build(self):
        archived=old.archive(self.baseline,self.repo,self.out)
        for name,repo,commit in [('previous',archived,self.baseline),('current',self.repo,self.git('rev-parse','HEAD'))]:
            folder=self.out/name; folder.mkdir()
            with build_source(repo,use_gate_wheel=name=='current'):
                path,_,spec=wheel.build_wheel(folder)
            self.artifacts[name]={'wheel':str(path),'wheel_sha256':sha(path),'commit':commit,
                'source_dirty':self.git('status','--porcelain').splitlines() if name=='current' else [],
                'source':str(repo),'modules':sorted(spec[0]),'packages':sorted(spec[1])}
        runtime=self.out/'runtime'; runtime.mkdir()
        self.python=wheel.make_venv(runtime)
        self.install('previous',fresh=True)

    def install(self,name,fresh=False):
        artifact=self.artifacts[name]
        if sha(artifact['wheel']) != artifact['wheel_sha256']: raise LedgerError('Wheel bytes changed before installation.')
        commands=[]
        if not fresh:
            command=[str(self.python),'-m','pip','uninstall','--yes','onecrew']
            result=subprocess.run(command,capture_output=True,text=True)
            if result.returncode: raise LedgerError('Uninstall failed: '+result.stderr[-500:])
            commands.append(command)
        wheel.install(self.python,artifact['wheel'])
        commands.append([str(self.python),'-m','pip','install','--no-index','--no-build-isolation',artifact['wheel']])
        self.installs.append({'artifact':name,'wheel_sha256':artifact['wheel_sha256'],'commands':commands})
        self.active=name
        with build_source(artifact['source']):
            self.ctx=wheel.build_ctx(self.python,artifact['modules'],artifact['packages'])

    def capture(self,label,body,expect=0):
        self.counter+=1
        trailer='''
import hashlib, sysconfig
_loaded=[]
_sites=sorted({sysconfig.get_paths()[k] for k in ('purelib','platlib')})
for _name,_module in sorted(sys.modules.items()):
    if _name=='onecrew' or _name.startswith('onecrew.'):
        _path=getattr(_module,'__file__',None)
        if _path:
            _loaded.append({'name':_name,'path':_path,'sha256':hashlib.sha256(Path(_path).read_bytes()).hexdigest()})
print('@@DRILL@@'+json.dumps({'result':globals().get('_RESULT'), 'loaded':_loaded,'site':_sites,'modules':_dump()}))
'''
        code=wheel._DUMP+'\nfrom pathlib import Path\nimport os, traceback\n_rc=0\n'
        code+="for _key in ('ONECREW_ACTOR','CLAUDECODE','CLAUDE_CODE_CHILD_SESSION','ONECREW_V2_REQUIRE_PLAN'): os.environ.pop(_key,None)\n"
        code+='try:\n'+''.join('    '+line+'\n' for line in body.splitlines())
        code+='except SystemExit as _error:\n    _rc=int(_error.code or 0)\nexcept BaseException:\n    traceback.print_exc(); _rc=1\n'
        code+=trailer+'\nraise SystemExit(_rc)\n'
        script=self.out/f'{self.counter:02}-{label}.py'; script.write_text(code,encoding='utf-8',newline='\n')
        command=[str(self.python),'-I','-c',code]
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',cwd=self.out,timeout=180)
        line=next((line for line in result.stdout.splitlines() if line.startswith('@@DRILL@@')),None)
        observed=json.loads(line[len('@@DRILL@@'):]) if line else None
        log=self.out/f'{self.counter:02}-{label}.log'; log.write_text(result.stdout+result.stderr,encoding='utf-8')
        if not observed: raise LedgerError(label+' produced no installed observation: '+result.stderr[-700:])
        violations=boundary.violations(observed['modules'],self.ctx)
        if violations: raise LedgerError(label+' import boundary: '+str(violations))
        artifact=self.artifacts[self.active]
        with __import__('zipfile').ZipFile(artifact['wheel']) as archive:
            for module in observed['loaded']:
                path=Path(module['path']).resolve()
                sites=[Path(site).resolve() for site in observed['site'] if path.is_relative_to(Path(site).resolve())]
                if not sites: raise LedgerError('Module was not installed: '+str(path))
                member=path.relative_to(sites[0]).as_posix()
                if hashlib.sha256(archive.read(member)).hexdigest()!=module['sha256']:
                    raise LedgerError('Installed module bytes do not match wheel: '+member)
                module['archive_path']=member
        self.records.append({'label':label,'artifact':self.active,'commit':artifact['commit'],'wheel_sha256':artifact['wheel_sha256'],
            'exit_code':result.returncode,'result':observed['result'],'loaded':observed['loaded'],'boundary_violations':violations,
            'command':[str(self.python),'-I','-c','<recorded bootstrap>'],'script_sha256':hashlib.sha256(code.encode()).hexdigest(),
            'script':str(script),
            'log':str(log),'log_sha256':sha(log)})
        if result.returncode!=expect:
            diagnostic=result.stdout.split('@@DRILL@@')[0]+result.stderr
            raise LedgerError(f'{label} exit {result.returncode}, expected {expect}: '+diagnostic[-900:])
        return observed['result'],result.stdout.split('@@DRILL@@')[0].strip()

    def cli(self,label,*args,expect=0):
        full=['--project',str(self.project),'--state-root',str(self.state),*args]
        body='import runpy\nsys.argv='+repr(['onecrew',*full])+"\nrunpy.run_module('onecrew.v2.cli',run_name='__main__')"
        _,text=self.capture(label,body,expect)
        try: return json.loads(text)
        except ValueError: return {'text':text}

    def execute(self):
        self.build(); self.project=old.git_project(self.out,'project'); self.state=self.out/'source-state'
        contract=old.contract('Legacy preservation fixture')
        path=self.out/'legacy.json'; path.write_text(json.dumps(contract),encoding='utf-8')
        self.cli('old-create','plan','propose','legacy','--file',str(path),'--author','fixture')
        # Existing old-version harness writes exact fixture approval events, never owner verbs.
        with old_fixture_connections():
            pid=old.project_id(self.state,self.project); anchor=old.anchor_id(self.state,pid,'plan:legacy')
            old.make_approved(self.state,anchor,'legacy')
        from onecrew.control_core import SCHEMA
        self.capture('seed-preservation-fixture',f'''
from onecrew.ledger import Ledger,canonical,utcnow
from onecrew.snapshots import Snapshots
ledger=Ledger({str(self.project)!r},{str(self.state)!r})
proof=Snapshots(ledger.state_root).blob(b'fixture evidence retained across actual installations')
with ledger.transaction(write=True) as conn:
    for ddl in {SCHEMA!r}: conn.execute(ddl)
    conn.execute('PRAGMA user_version=2')
    conn.execute('INSERT INTO executions(task_id,configuration,revision,status,used_calls,reserved_calls) VALUES(?,?,?,?,?,?)',
                 ({anchor!r},'{{}}','fixture-revision','running',2,1))
    conn.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
        ('ATT-fixture',{anchor!r},'fixture','{{}}','fixture-operation',1,'unknown',0,None,None,utcnow(),utcnow()))
    ledger._event(conn,{anchor!r},'control.intervention',{{'fixture':True,'evidence':proof,'attempt':'ATT-fixture'}})
_RESULT={{'proof':proof,'unknown_attempt':'ATT-fixture','used_calls':2}}
''')
        source_before=snapshot(self.state)
        self.state=rollback.copy_ledger(self.state,self.out/'copy-state')
        before=snapshot(self.state); old_read=self.cli('old-read','plan','show','legacy')
        self.install('current'); new_read=self.cli('upgraded-read','plan','show','legacy')
        if snapshot(self.state)!=before: raise LedgerError('Upgrade changed preserved SQL/files.')
        # New presentation fields are additive; every old observable remains exact.
        if any(new_read.get(key)!=value for key,value in old_read.items()):
            raise LedgerError('Installed legacy plan projection changed across upgrade.')
        unknown=self.prepare_unknown()
        finding=self.open_finding()
        before_scan=snapshot(self.state)
        rejected=self.cli('blocked-scan','compat','scan','--json')
        blocked=guard_swap(self.state,rejected)
        if snapshot(self.state)!=before_scan: raise LedgerError('Rejected compatibility scan changed fixture state.')
        if blocked['ran'] or rejected['blocking']['total']==0: raise LedgerError('Expected actual namespace rollback block.')
        install_count=len(self.installs)
        # Freeze only active copies created by this generated fixture, with retained bytes.
        frozen=[]
        for path in [self.project/'.onecrew/active-plan.json',self.state/'plans'/pid/'active-plan.json']:
            if path.exists():
                if not path.resolve().is_relative_to(self.out): raise LedgerError('Refusing to move non-fixture active copy.')
                target=self.out/('frozen-'+str(len(frozen))+'.json'); before_sha=sha(path); path.replace(target)
                frozen.append({'path':str(path),'retained':str(target),'sha256':before_sha})
        before_scan=snapshot(self.state)
        allowed=self.cli('allowed-scan','compat','scan','--json'); gate=guard_swap(self.state,allowed)
        if snapshot(self.state)!=before_scan: raise LedgerError('Allowed compatibility scan changed fixture state.')
        if not gate['ran']: raise LedgerError('Fixture did not reach zero-block rollback: '+str(gate))
        if len(self.installs)!=install_count: raise LedgerError('Rejected rollback changed installation.')
        rollback_before=snapshot(self.state)
        self.install('previous'); self.cli('rolled-back-read','plan','show','legacy')
        self.cli('rolled-back-hidden-root','plan','show','future',expect=2)
        if snapshot(self.state)!=rollback_before: raise LedgerError('Old installation changed frozen retained state.')
        self.install('current'); self.cli('rolled-forward-read','plan','show','legacy')
        if snapshot(self.state)!=rollback_before: raise LedgerError('Roll-forward changed retained state before reconcile.')
        reconciled=self.reconcile_unknown(unknown)
        kept=self.finding_after(finding)
        if snapshot(self.out/'source-state')!=source_before: raise LedgerError('Pristine source fixture was changed.')
        result={'schema':1,'result':'pass','kind':'installed-upgrade-drill','provenance':{'kind':'real','source':'local installed CLI/Control observations'},
            'scenario':'generated fixture, not pilot','owner_acceptance':False,'release_gate':False,
            'baseline_selection':'chosen scanner-supported pre-namespace baseline; not claimed nearest delivered',
            'artifacts':self.artifacts,'installs':self.installs,'observations':self.records,
            'upgrade_preserved':before,'rollback_preserved':rollback_before,'source_unchanged':True,
            'rejected':{'switched':False,'scan':rejected},'allowed':{'switched':True,'scan':allowed},
            'frozen_active_copies':frozen,'reconcile':reconciled,'finding':{'before':finding,'after':kept}}
        (self.out/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2),encoding='utf-8')
        return result

    def prepare_unknown(self):
        contract=old.contract('New unknown-effect fixture'); path=self.out/'future.json'; path.write_text(json.dumps(contract),encoding='utf-8')
        self.cli('new-create','plan','propose','future','--file',str(path),'--author','fixture','--workflow')
        # Explicitly seeded fixture approval, matching the established rollback harness.
        self.capture('new-fixture-approved',f'''
from onecrew.ledger import Ledger
from onecrew.v2 import plan,active_plan
ledger=Ledger({str(self.project)!r},{str(self.state)!r})
with ledger.transaction(write=True) as conn:
    root=plan.anchor_events(ledger,conn,'future'); contract,sha=plan.load(ledger,root)
    plan.emit(ledger,conn,root['task_id'],'plan.approved',{{'plan':'future','revision':1,'sha':sha,'by':'owner','reference':'synthetic fixture event; not an owner action','ticked':[]}})
active_plan.export(ledger,'future')
''')
        marker=self.out/'effect-marker.txt'
        result,_=self.capture('unknown-effect-created',f'''
from onecrew.ledger import Ledger
from onecrew.control_core import Control,migrate
from onecrew.task_intake import submit
ledger=Ledger({str(self.project)!r},{str(self.state)!r}); migrate(ledger); control=Control(ledger)
task=submit(ledger,'Fixture local marker effect','fixture-effect',plan_selector='plan-ns:future',max_calls=2,max_seconds=600)
control.configure(task['id'],task['revision'],{{'mode':'fixture'}})
action=control.propose_action(task['id'],'first',{{'kind':'fixture-marker'}}); control.authorize_action(action['id'],action['revision'])
def effect(_):
    Path({str(marker)!r}).write_text('once')
    raise OSError('fixture result lost after local effect')
receipt=control.execute_action(action['id'],effect); assert receipt['status']=='unknown'
_RESULT={{'task':task['id'],'action':action['id'],'revision':action['revision'],'marker':{str(marker)!r}}}
''')
        return result

    def open_finding(self):
        """T13b [E3]: a REAL open finding (a doc check that fails on the current build) in a namespaced root, so the drill proves that the
        finding, its evidence receipt and its ID survive rollback to the previous build and roll-forward unchanged."""
        (self.project/'guide.md').write_text('# Guide\n[reference](missing.txt)\n',encoding='utf-8')
        for args in (['add','guide.md'],['-c','user.name=t','-c','user.email=t@t','commit','-q','-m','guide']):
            subprocess.run(['git',*args],cwd=self.project,check=True,capture_output=True)
        contract=old.contract('Finding preservation fixture')
        contract['milestones']=[{'id':'M1','title':'Check guide','mode':'until_pass','max_repairs':3,
                                 'verifier':{'type':'doc','config':{'docs':['guide.md']}},'covers':['O1']}]
        contract['scope']={'owned':['guide.md']}; contract['understanding']['target']['paths']=['guide.md']
        contract['preconditions']=[{'id':'P1','check':'path_exists','args':{'path':'guide.md'},'why':'the guide is there'}]
        path=self.out/'finding.json'; path.write_text(json.dumps(contract),encoding='utf-8')
        self.cli('finding-root-create','plan','propose','findings','--file',str(path),'--author','fixture','--workflow')
        result,_=self.capture('finding-opened',f'''
import json, hashlib
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import plan,verdict,findings
ledger=Ledger({str(self.project)!r},{str(self.state)!r})
plan.approve(ledger,'findings','owner','fixture approval on a temporary generated ledger; not an owner action')   # seals the budget the verifier needs
shown=verdict.run(ledger,'findings','M1')
last=shown['milestones'][0]['last_verdict']; assert last['result']=='fail',last
rows=findings.list_findings(ledger,'findings',open_only=True); assert len(rows)==1 and rows[0]['criterion']=='links',rows
receipt=Snapshots(ledger.state_root).read_blob(rows[0]['source']['receipt'])
_RESULT={{'id':rows[0]['id'],'criterion':rows[0]['criterion'],'receipt':rows[0]['source']['receipt'],'receipt_sha256':hashlib.sha256(receipt).hexdigest(),
          'state':rows[0].get('state') or rows[0].get('status'),'row':rows[0]}}
''')
        return result

    def finding_after(self,finding):
        result,_=self.capture('finding-kept-after-roll-forward',f'''
import json, hashlib
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import findings
ledger=Ledger({str(self.project)!r},{str(self.state)!r}); before={finding!r}
rows=findings.list_findings(ledger,'findings',open_only=True)
assert [row['id'] for row in rows]==[before['id']],rows
assert rows[0]==before['row'],(rows[0],before['row'])
receipt=Snapshots(ledger.state_root).read_blob(before['receipt'])
assert hashlib.sha256(receipt).hexdigest()==before['receipt_sha256']
_RESULT={{'id':rows[0]['id'],'row':rows[0],'receipt_sha256':hashlib.sha256(receipt).hexdigest(),'same':rows[0]==before['row']}}
''')
        return result

    def reconcile_unknown(self,unknown):
        result,_=self.capture('forward-reconcile-before-retry',f'''
from onecrew.ledger import Ledger,LedgerError
from onecrew.control_core import Control
ledger=Ledger({str(self.project)!r},{str(self.state)!r}); control=Control(ledger); data={unknown!r}
marker=Path(data['marker']); assert marker.read_text()=='once'
calls=[]
def forbidden(_): calls.append('replayed'); marker.write_text('BAD'); return {{'verified':True}}
assert control.execute_action(data['action'],forbidden)['status']=='unknown'
next_action=control.propose_action(data['task'],'after-reconcile',{{'kind':'fixture-marker-next'}})
control.authorize_action(next_action['id'],next_action['revision'])
try: control.execute_action(next_action['id'],forbidden)
except LedgerError: pass
else: raise AssertionError('Unknown prior intent must block a second effect')
assert not calls and marker.read_text()=='once'
receipt=control.reconcile_action(data['action'],data['revision'],lambda _:{{'verified':marker.read_text()=='once','source':'actual marker observation'}})
assert receipt['status']=='verified'
def after(_): marker.write_text(marker.read_text()+',after-reconcile'); return {{'verified':True}}
assert control.execute_action(next_action['id'],after)['status']=='verified'
with ledger.transaction() as conn:
    events=[dict(row) for row in conn.execute("SELECT seq,kind,payload FROM events WHERE task_id=? AND kind IN ('action.reconciled','action.executing') ORDER BY seq",(data['task'],))]
reconcile=next(e['seq'] for e in events if e['kind']=='action.reconciled')
continued=next(e['seq'] for e in events if e['kind']=='action.executing' and json.loads(e['payload'])['id']==next_action['id'])
assert reconcile<continued and marker.read_text()=='once,after-reconcile'
_RESULT={{'reconcile_seq':reconcile,'continued_seq':continued,'effect_replays_before_reconcile':len(calls),'marker':marker.read_text(),'events':events}}
''')
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--out',required=True)
    parser.add_argument('--baseline',default='d3120c6'); args=parser.parse_args(argv)
    try:
        result=Drill(args.out,baseline=args.baseline).execute()
        print(json.dumps({'result':result['result'],'receipt':str(Path(args.out)/'receipt.json'),'release_gate':False}))
        return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print(json.dumps({'result':'refused','reason':str(error),'release_gate':False})); return 1


if __name__=='__main__': raise SystemExit(main())
