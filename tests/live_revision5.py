"""Explicit integration trial; never imported by unittest discovery. Uses subscription calls."""
import datetime as dt
import json
import tempfile
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.owned import Owned
from onecrew.owned_intake import submit
from onecrew.owned_cli import output_card


def main():
    import subprocess
    base=Path(tempfile.mkdtemp(prefix='onecrew-v5-trial-')).resolve()
    project=base/'project';project.mkdir()
    (project/'calculator.py').write_text('def total(values):\n    return len(values)\n',encoding='utf-8')
    (project/'test_calculator.py').write_text('import unittest\nfrom calculator import total\nclass Tests(unittest.TestCase):\n def test_empty(self): self.assertEqual(total([]),0)\n def test_values(self): self.assertEqual(total([2,3,8]),13)\n def test_signed(self): self.assertEqual(total([-2,5]),3)\n',encoding='utf-8')
    image=subprocess.check_output(['docker','image','inspect','python:3.13-alpine','--format','{{.Id}}'],text=True).strip()
    ledger=Ledger(project,base/'state')
    task=submit(ledger,'Fix total(values) to return the sum of the given numbers, including empty and negative values. Inspect the project yourself, reproduce with existing tests, fix only the function, run the original tests and provide evidence. Do not add documentation or new features. Preserve original checkout; deliver isolated candidate.',
        'revision5-live',mode='change',provider='codex',model='gpt-6-luna',image=image,max_calls=12,max_seconds=600)
    print(json.dumps({'task':task['id'],'base':str(base),'budget':{'calls':12,'seconds':600}}),flush=True)
    runtime=Owned(ledger);runtime.enable(task['id']);state=runtime.run(task['id'])
    card=output_card(runtime,task['id'],state)
    evidence={'recorded_at':dt.datetime.now(dt.timezone.utc).isoformat(),'task':task['id'],
        'runtime_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'workspace':str(base),'result':card,'assistance':'none during this trial',
        'original_preserved':(project/'calculator.py').read_text()=='def total(values):\n    return len(values)\n'}
    import hashlib
    evidence['runtime_source_hashes']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('onecrew').glob('*.py'))}
    path=Path('docs/revision5-live-evidence-'+task['id'][5:13]+'.json');path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'phase':state['phase'],'calls':runtime.control.status(task['id'])['used_calls'],
        'message':state['message'],'evidence':str(path.resolve())}),flush=True)
    return 0 if state['phase']=='completed' and evidence['original_preserved'] else 1


if __name__=='__main__': raise SystemExit(main())
