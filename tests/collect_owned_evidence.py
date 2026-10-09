"""Read-only verifier for the opt-in owned-execution fixtures; never advances a task."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from onecrew.ledger import Ledger
from onecrew.owned import Owned
from onecrew.runner import status
from onecrew.usage import summarize


def collect():
    root=Path(__file__).resolve().parents[1]
    runs=[]
    for name in ('audit','change','audit-v2','change-v2','delivery','final-audit'):
        folder=root/'.onecrew'/('owned-live-'+name)
        submission=json.loads((folder/'submission.json').read_text())
        ledger=Ledger(submission['project'],submission['state_root']);runtime=Owned(ledger)
        task=submission['task'];state=runtime.state(task)[1];control=runtime.control.status(task)
        accepted=name not in ('audit','change')
        assert state['phase']=='completed', (name,state['phase'])
        assert status(ledger,task)['status']=='stopped', name
        if accepted: assert state['reviews'][-1]['accepted'] is True, name
        expected='def add(a, b):\n    return a + b\n' if name=='delivery' else 'def add(a, b):\n    return a - b\n'
        assert (ledger.project/'service/calculator.py').read_text()==expected, 'Source was modified'
        if name=='change-v2':
            assert [t['passed'] for t in state['tests']]==[False,True]
            assert state['tests'][-1]['evidence']['snapshot']==state['snapshot']
            candidate=runtime.store.context(state['snapshot'])['service/calculator.py']
            assert 'a + b' in candidate and 'a - b' not in candidate
        if name=='delivery':
            receipt=state['deliveries'][0]['result']
            assert receipt['verified'] and receipt['paths']==['service/calculator.py']
            def git(*args):
                return subprocess.check_output(['git','-C',str(ledger.project),*args]).decode().strip()
            assert git('diff','--cached','--name-only')==''
            assert git('rev-parse','HEAD')!=receipt['commit']
            assert git('diff-tree','--no-commit-id','--name-only','-r',receipt['commit'])=='service/calculator.py'
            assert git('ls-remote','--refs','origin',receipt['ref']).split()[0]==receipt['commit']
            assert (ledger.project/'unrelated.txt').is_file()
        runs.append({'name':name,'task':task,'mode':submission['mode'],'accepted_trial':accepted,
            'rejection_reason':None if accepted else ('Incorrect test-absence claim in report' if name=='audit' else
                'Report confused preserved source with absence of a candidate fix'),
            'host_prepared_evidence':False,'host_prepared_plan':False,'host_task_intervention':False,
            'calls':control['used_calls'],'usage':summarize(state['usage'],control['attempts']),
            'steps':state['step'],'phase':state['phase'],'source_preserved':True,'runner_stopped':True,
            'actions':[r['action'] for r in state['receipts']],
            'tests':state['tests'],'deliveries':state['deliveries'],'reviews':state.get('reviews',[]),
            'report':state['report']})
    calls=sum(r['calls'] for r in runs)
    assert calls<=60, calls
    return {'version':1,'proposal':'SPEC-007','managed_calls_total':calls,'managed_call_cap':60,
        'provider':'codex','model':'gpt-6-luna','auth':'existing subscription',
        'acceptance':'Three task types passed; initial report defects retained as rejected trials.',
        'limitations':['Live Git remote is local bare, not GitHub network authentication.',
            'Python unittest sandbox only; no eight-hour soak or native provider tools.',
            'Live trials ran during development; final-audit validates final runtime after durability fixes; fixture regression covers those changes.',
            'Provider-internal call cap remains unsupported; managed calls and observed token counters are separate.'],
        'runs':runs}


if __name__=='__main__':
    evidence=collect()
    path=Path(__file__).resolve().parents[1]/'docs/owned-execution-evidence.json'
    path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'evidence':str(path),'managed_calls_total':evidence['managed_calls_total'],
                      'accepted_trials':[r['name'] for r in evidence['runs'] if r['accepted_trial']]}))
