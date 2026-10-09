"""Explicit opt-in synthetic live consultation; writes only its isolated local fixture."""
import json
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew import conversations as c,consultations as q
from onecrew.runner import start

def main():
    root=Path(__file__).resolve().parents[1]/'.onecrew/rev9-live'
    (root/'project').mkdir(parents=True,exist_ok=True)
    ledger=Ledger(root/'project',root/'state')
    cid=c.create(ledger,'Synthetic solution review smoke test','live-rev9','codex-cli')['id']
    sol=c.propose(ledger,cid,'initial',{'brief':'Add a pure integer addition function.','detail':'Implement add(a,b) for integers. Reject bool and other types. No IO, no dependencies.',
        'acceptance':['add(2,3) returns 5','add(-2,2) returns 0','non-integer arguments raise TypeError'],
        'non_goals':['No web service'], 'assumptions':['Python 3.13'], 'questions':[]},'codex-cli')
    result=q.submit(ledger,cid,'claude-review',sol['id'],sol['revision'],'Review ambiguity, missing cases and testability. This is a synthetic smoke test; do not implement.',
        'codex-cli','User authorized implementation verification of OneCrew revision 9',provider='claude',model='sonnet',max_seconds=180)
    result['dispatch']=start(ledger,result['id']) if result['status'] in ('queued','running') else {'status':'not_restarted'}
    (root/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'id':result['id'],'status':result['status'],'dispatch':result['dispatch'],'fixture':str(root)}))

if __name__=='__main__':main()
