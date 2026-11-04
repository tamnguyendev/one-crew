"""Two actual local supervised operations through public managed batch CLI."""
import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from onecrew.process_core import Supervisor,native_python
from onecrew.subscription import environment
from onecrew.v2.cli import main
from tests import test_wf_parallel_engine as fixture
from tests.test_wf_engine import node


class ParallelNativeTests(fixture.ParallelFixture):
    def test_public_batch_runs_two_scoped_native_processes_with_real_containment_receipts(self):
        definition=[node('A'),node('B',write=('b.txt',)),node('I',['A','B'],integration=True,write=())]
        for item in definition:item['executor']={'role':'worker','provider':'codex','model':'fixture-model'}
        self.revise(definition)
        ready=Path(self.temp.name)/'workers-ready';ready.mkdir();launches=[]
        def factory(control,provider):
            class Worker:
                def capability(self):return {'provider':provider,'mode':'local-fixture-artifact'}
                def run(self,attempt,prompt,schema,profile):
                    launches.append(attempt['id'])
                    directory=control.ledger.state_root/'worker-io'/attempt['id'];directory.mkdir(parents=True)
                    paths=schema['properties']['files']['items']['properties']['path']['enum']
                    value={'summary':'fixture isolated output','files':[{'path':path,'content':'candidate-'+path+'\n'} for path in paths],'backlog':[]}
                    script=('import pathlib,sys,time\n'
                            'ready=pathlib.Path(sys.argv[1]); (ready/sys.argv[2]).write_text("ready")\n'
                            'end=time.monotonic()+5\n'
                            'while len(list(ready.iterdir()))<2 and time.monotonic()<end:time.sleep(.02)\n'
                            'assert len(list(ready.iterdir()))==2,"second supervised slot never started"\n'
                            'pathlib.Path("answer.json").write_text(sys.argv[3])\n')
                    return Supervisor(control).run(attempt,[native_python(),'-c',script,str(ready),attempt['id'],json.dumps(value)],cwd=directory,timeout=8,env=environment())
                def result(self,attempt):
                    directory=control.ledger.state_root/'worker-io'/attempt['id']
                    return json.loads((directory/'answer.json').read_text()),[]
            return Worker()
        output=io.StringIO()
        with patch('onecrew.artifact_provider_core.make_worker',side_effect=factory),contextlib.redirect_stdout(output):
            code=main(['--project',str(self.root),'--state-root',str(self.ledger.state_root),'engine','batch','P1','--slots','2'])
        self.assertEqual(code,0,output.getvalue())
        batch=json.loads(output.getvalue())
        self.assertTrue(all(row['state']=='produced' for row in batch['results']),batch)
        self.assertEqual(len(launches),2)
        self.assertEqual((self.root/'a.txt').read_text(),'one\n');self.assertFalse((self.root/'b.txt').exists())
        for row in batch['results']:
            receipt=json.loads(self.store.read_blob(row['receipt']))
            attempt=self.control.attempt(receipt['attempt'])
            self.assertTrue(json.loads(attempt['identity'])['job_contained'])
            self.assertTrue(json.loads(attempt['result'])['tree_stopped'])
            self.assertEqual(set(self.store.context(row['artifact'])) & {'a.txt','b.txt'}, {'a.txt'} if row['node']=='A' else {'a.txt','b.txt'})
