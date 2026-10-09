"""Opt-in live acceptance. Seeds projects, submits only goals/grants, never does job work.

Run with native Python: tests/live_owned.py audit|change|delivery --output <new directory> --image <sha256>
Not discovered by unittest. Every run has its own <=20-call/20-minute ledger budget.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from onecrew.ledger import Ledger
from onecrew.owned_intake import submit
from onecrew.owned import Owned
from onecrew.runner import start


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['audit','change','delivery'])
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--image')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    root=args.output/'project';root.mkdir()
    source=root/'service';source.mkdir()
    (source/'__init__.py').write_text('')
    (source/'calculator.py').write_text('def add(a, b):\n    return a - b\n',encoding='utf-8')
    (root/'test_calculator.py').write_text('import unittest\nfrom service.calculator import add\n\nclass CalculatorTests(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n    def test_negative(self):\n        self.assertEqual(add(-2, 3), 1)\n',encoding='utf-8')
    (root/'README.md').write_text('# Calculator service\nSmall arithmetic library; public API adds two numbers.\nTests use Python unittest.\n',encoding='utf-8')
    options={}
    goal='Review the architecture and correctness of this project. Report evidence and limitations; do not modify it.'
    if args.mode=='change':
        goal='Fix the incorrect addition behavior in this project and verify the fix against its existing tests. Keep the change minimal.'
        options['image']=args.image
    if args.mode=='delivery':
        def git(*argv):
            subprocess.run(['git','-C',str(root),*argv],check=True,capture_output=True)
        git('init');git('config','user.name','OneCrew acceptance');git('config','user.email','acceptance@localhost')
        git('add','.');git('commit','-m','Initial calculator')
        remote=args.output/'remote.git';git('init','--bare',str(remote.resolve()))
        git('remote','add','origin',str(remote.resolve()))
        (source/'calculator.py').write_text('def add(a, b):\n    return a + b\n',encoding='utf-8')
        (root/'unrelated.txt').write_text('Unrelated draft, leave out of the delivery.\n')
        goal='Commit and push the existing correction to addition to the authorized new branch. Exclude unrelated draft files. Report exact commit and delivery evidence.'
        options.update(branch='onecrew/owned-acceptance',remote='origin')
    ledger=Ledger(root,args.output/'state')
    task=submit(ledger,goal,'live-acceptance',mode=args.mode,**options)
    Owned(ledger).enable(task['id'])
    result={'task':task['id'],'project':str(root.resolve()),'state_root':str(ledger.state_root),
            'mode':args.mode,'goal':goal,'runner':start(ledger,task['id']),
            'host_prepared_evidence':False,'host_prepared_plan':False,'host_task_intervention':False}
    (args.output/'submission.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
