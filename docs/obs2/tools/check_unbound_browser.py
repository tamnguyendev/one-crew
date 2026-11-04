"""Installed-wheel question UI with real missing/mismatched/bound hook files.

Run: installed-python -I -B check_unbound_browser.py NEW_WORK
Only a fresh proposed fixture, no owner approval, provider, registry or real data.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from onecrew.ledger import Ledger
from onecrew.v2 import tracking, tracking_web, plan, hook_cli

SCENARIO=r'''
if(S==='binding'){
  await select('P1'); $$('details.need').forEach(n=>n.open=true); await sleep(300);
  const bound=qs.get('bound')==='1', request=$$('details.need').find(n=>n.querySelectorAll('.opt').length===2);
  check('question and both options visible',!!request);
  const copies=request?Array.from(request.querySelectorAll('button.copy')).map(b=>b.dataset.copy):[];
  check('no empty copy buttons',!$$('button.copy').some(b=>!b.dataset.copy));
  check('write buttons agree with binding',bound?copies.length===2&&copies.every(Boolean):copies.length===0);
  check('PowerShell instructions agree with binding',!!request&&request.textContent.includes('Mở PowerShell')===bound);
  check('placeholder instructions agree with binding',!!request&&request.textContent.includes('Thay phần')===bound);
  check('unbound explains why',bound||!!request&&request.textContent.includes('Chưa xác minh hook'));
  check('no horizontal page overflow',d.documentElement.scrollWidth<=w.innerWidth+1);
  out.cards=$$('details.need').map(n=>({text:n.textContent,copies:Array.from(n.querySelectorAll('button.copy')).map(b=>b.dataset.copy)}));
}
'''


def main(work):
    work=Path(work).resolve(); work.mkdir(exist_ok=False)
    here=Path(__file__).resolve().parent
    registry=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'OneCrew/hook-projects.json'
    original_registry=registry.read_bytes() if registry.exists() else None
    for key,name in [('TEMP','tmp'),('TMP','tmp'),('LOCALAPPDATA','lad'),('APPDATA','ad')]:
        p=work/name;p.mkdir(exist_ok=True);os.environ[key]=str(p)
    spec=importlib.util.spec_from_file_location('fixture',here/'scenario_obs2.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    project=work/'project';project.mkdir();(project/'code.py').write_text('fixture\n')
    for args in [('init','-q'),('config','user.name','Fixture'),('config','user.email','fixture@localhost'),('add','code.py'),('commit','-qm','fixture')]:
        subprocess.run(['git','-C',str(project),*args],check=True,capture_output=True)
    ledger=Ledger(project,work/'state')
    root=plan.propose(ledger,'P1',fixture.contract('code.py','Question UI fixture'),'fixture')
    ledger.create_request(root['anchor_task'],'choice',{'schema_version':1,'question':'Choose retention','reason':'Fixture only','impact':'Fixture',
        'options':[{'id':'a','label':'7 ngày'},{'id':'b','label':'30 ngày'}],'recommendation':'a','action':{'type':'clarify','parameters':{}}})
    sys.path.insert(0,str(here))
    from tests import obs1_ux_harness as ux
    ux.HARNESS=ux.HARNESS.replace("if(S==='shot-list'){}","if(S==='shot-list'){}\n"+SCENARIO,1)
    browser='C:/Program Files/Google/Chrome/Application/chrome.exe'
    if not Path(browser).is_file(): raise RuntimeError('Chrome missing, not verified')
    exe=Path(sys.executable).with_name('onecrew.exe')
    settings=project/'.claude/settings.local.json';settings.parent.mkdir()
    db=ledger.state_root/'ledger.sqlite3';before=hashlib.sha256(db.read_bytes()).hexdigest()
    server=tracking_web.make_server(ledger.state_root,interval=1)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    proxy=ux.Proxy(tracking_web.url_of(server))
    report={'origin':tracking.__file__,'version':tracking_web.version(),'results':{},'ok':False}
    try:
        for mode in ('missing','other-runtime','other-state','bound'):
            if mode!='missing':
                settings.write_text(json.dumps(hook_cli.portable_settings(exe if mode!='other-runtime' else exe.with_name('other.exe'),
                    ledger.state_root if mode!='other-state' else work/'other-state')),encoding='utf8')
            for size in ('desktop','mobile'):
                width,height=ux.SIZES[size]
                result=ux.run(browser,proxy.url,'binding',width,height,work/'profile',budget=20000,extra='&bound='+('1' if mode=='bound' else '0'))
                report['results'][mode+'-'+size]=result
                (work/'browser-binding.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
                if not result.get('ok'): raise RuntimeError('Browser binding failed: '+mode+'-'+size)
                if mode=='other-state':
                    if not ux.screenshot(browser,proxy.url,'binding',width,height,work/'profile',work/(mode+'-'+size+'.png'),budget=20000,extra='&bound=0'):
                        raise RuntimeError('Screenshot failed')
        report['ledger_unchanged']=hashlib.sha256(db.read_bytes()).hexdigest()==before
        report['registry_unchanged']=(registry.read_bytes() if registry.exists() else None)==original_registry
        report['ok']=report['ledger_unchanged'] and report['registry_unchanged'] and Path(tracking.__file__).is_relative_to(Path(sys.prefix))
    finally:
        proxy.stop();server.shutdown();server.server_close();thread.join(10)
        (work/'browser-binding.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'ok':report['ok'],'cases':len(report['results']),'report':str(work/'browser-binding.json')}))
    return 0 if report['ok'] else 1

if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
