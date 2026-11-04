"""Same behavioural probes on old/new installed wheels. Only synthetic fresh state.

Run with the installed venv's python -I -B check_review_fixes.py NEW_WORK_DIR.
No provider, real registry, owner terminal or project is used.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from onecrew.ledger import Ledger
from onecrew.control_core import Control
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, plan, internal_plan, tracking, tracking_web, tracking_work_web, hook_cli


def main(work):
    work=Path(work).resolve(); work.mkdir(exist_ok=False)
    spec=importlib.util.spec_from_file_location('fixture',Path(__file__).with_name('scenario_obs2.py'))
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    made=fixture.create(work)
    ledger=Ledger(made['project'],made['state_root']); store=Snapshots(ledger.state_root); control=Control(ledger)
    for name, all_checked in [('WAIT',False),('CHECKED',True)]:
        root=plan.propose(ledger,name,fixture.contract('code.py','Synthetic review regression'), 'fixture',workflow=True,
            capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
        plan.approve(ledger,name,'owner','Synthetic fixture, not user approval')
        internal_plan.revise(ledger,name,[fixture.node('C','code.py'),fixture.node('I','code.py',True)],reason='fixture split',evidence=['code.py:1'])
        def execute(ledger, control, task, item, attempt):
            control.launched(attempt['id'],attempt['generation'],{'fixture':True})
            a=store.blob(b'fixture output');r=store.blob(b'fixture executor')
            control.finish(attempt['id'],attempt['generation'],{'artifact':a})
            return {'artifact':a,'receipt':r}
        def checker(item, artifact):
            return {'artifact':artifact,'checks':[{'id':c['id'],'result':'pass','evidence':store.blob(b'text evidence')} for c in item['checks']]}
        engine.step(ledger,name,execute,control=control);engine.verify(ledger,name,'C',checker)
        if all_checked:
            engine.step(ledger,name,execute,control=control);engine.verify(ledger,name,'I',checker)
        else:
            ledger.create_request(root['anchor_task'],'choice',{'schema_version':1,'question':'Choose fixture option','reason':'fixture',
                'impact':'fixture','options':[{'id':'a','label':'A'},{'id':'b','label':'B'}], 'recommendation':'a',
                'action':{'type':'clarify_retention','parameters':{'unit':'days'}}})
    # Explicitly bind this disposable fixture even on dev5, whose create() predates binding.
    exe=Path(sys.executable).with_name('onecrew.exe'); settings=Path(made['project'])/'.claude/settings.local.json'
    settings.parent.mkdir(exist_ok=True)
    bound=json.dumps(hook_cli.portable_settings(exe,ledger.state_root))
    settings.write_text(bound,encoding='utf8')
    results=[]
    def check(name, ok, detail=None): results.append({'name':name,'pass':bool(ok),'detail':detail})
    def js(expression):
        source=tracking_web.PAGE
        helpers=source[source.index('function tms(t)'):source.index('function repaintGantt()')]
        code=tracking_work_web.SCRIPT+'\n'+helpers+'\nconsole.log(JSON.stringify('+expression+'));'
        done=subprocess.run(['node','-'],input=code,text=True,encoding='utf8',capture_output=True,timeout=20)
        if done.returncode: raise RuntimeError(done.stderr[-1000:])
        return json.loads(done.stdout)
    before=hashlib.sha256((ledger.state_root/'ledger.sqlite3').read_bytes()).hexdigest()
    wait=tracking.detail(ledger.state_root,'WAIT'); checked=tracking.detail(ledger.state_root,'CHECKED')
    check('P2-1 no false checking lane',js('workStage('+json.dumps(wait)+')')=='doing')
    check('P2-2 no false acceptance lane',js('workStage('+json.dumps(checked)+')')!='accept')
    check('P2-2 all root indicators agree',checked['status']['kind']!='done' and not any(n['kind']=='accept' for n in checked['needs_user']) and 'chờ bạn nghiệm thu' not in (checked['current_step'] or ''),checked['current_step'])
    code=tracking.detail(ledger.state_root,'CODE'); w=code['work']
    check('P3-1 finding readable',w['findings'][0]['text'].startswith('Không đạt:'))
    check('P3-2 valid text not unreadable',not any('Không đọc được receipt/definition/register' in s for s in w['limitations']))
    check('P3-3 initial plan labelled',w['changes'][0]['kind']=='initial')
    for days in (4.7,5,6,12):
        ticks=js('gTicks({w0:0,w1:'+str(days*86400000)+'})')
        check('P3-4 day ticks '+str(days),3<=len(ticks)<=6 and 'ngày' in ticks[-1]['label'],ticks)
    check('P2-3 same runtime permits template',bool(code['needs_user'][0]['human_command']))
    for mode in ('other-runtime','other-state','missing'):
        if mode=='missing': settings.unlink()
        else: settings.write_text(json.dumps(hook_cli.portable_settings(
            exe if mode!='other-runtime' else exe.with_name('other.exe'),
            ledger.state_root if mode!='other-state' else work/'different-state')),encoding='utf8')
        for name in ('CODE','WAIT'):
            d=tracking.detail(ledger.state_root,name)
            entries=[e for n in d['needs_user'] for e in [n,*n.get('options',[])]]
            check('P2-3 '+mode+' '+name,all(not e.get('human_command') and not e.get('reply_command') and not (e.get('action') or {}).get('enabled') for e in entries))
    settings.write_text(bound,encoding='utf8')
    check('read operations preserve ledger',before==hashlib.sha256((ledger.state_root/'ledger.sqlite3').read_bytes()).hexdigest())
    report={'origin':tracking.__file__,'installed':Path(tracking.__file__).is_relative_to(Path(sys.prefix)),
            'passed':sum(x['pass'] for x in results),'total':len(results),'checks':results}
    (work/'review-fixes.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':report['passed'],'total':report['total'],'report':str(work/'review-fixes.json')},ensure_ascii=False))
    return 0 if report['installed'] and report['passed']==report['total'] else 1


if __name__=='__main__': raise SystemExit(main(sys.argv[1]))
