"""R07 CLI in an isolated offline wheel, including its actual import boundary."""
import json
import shutil
import unittest

from onecrew.v2 import boundary
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json


class InstalledLocalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = wh._runs()
        cls.wheel, _, (modules, packages) = wh.build_wheel(cls.runs)
        cls.python = wh.make_venv(cls.runs)
        wh.install(cls.python, cls.wheel)
        cls.ctx = wh.build_ctx(cls.python, modules, packages)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_installed_issue_lookup_and_explicit_map_keep_pinned_evidence_and_honest_image_fallback(self):
        body = '''
import contextlib, io, json, subprocess, tempfile
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan
from onecrew.v2.cli import main
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir()
    def git(*args):
        return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
    git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
    (root/'.gitignore').write_text('.onecrew/\\n')
    (root/'a.txt').write_text('base\\n')
    (root/'ui.html').write_text('<button data-handler="ReportController.export">Export report</button>\\n')
    (root/'reports.py').write_text('class ReportController:\\n    def export(self, month):\\n        return ExportService().build(month)\\n\\nclass ExportService:\\n    def build(self, month):\\n        return 31\\n')
    (root/'test_reports.py').write_text('def test_export_build():\\n    assert ExportService().build(2) == 28\\n')
    git('add','.'); git('commit','-qm','before repair'); pinned=git('rev-parse','HEAD')
    state=Path(temp)/'state'; ledger=Ledger(root,state)
    contract=json.loads(CONTRACT)
    plan.propose(ledger,'P1',contract,'codex')
    task=plan.show(ledger,'P1')['anchor_task']
    def cli(*args):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            code=main(['--project',str(root),'--state-root',str(state),*args])
        assert code==0, output.getvalue()
        return json.loads(output.getvalue())
    before=ledger.events(task)
    indexed=cli('issue','map','P1','--revision',pinned)
    assert indexed['recorded'] and indexed['complete'] and indexed['files']>=4, indexed
    assert len(ledger.events(task))==len(before)+1
    assert not cli('issue','map','P1','--revision',pinned)['recorded']
    (root/'reports.py').write_text('class FutureRename:\\n    def renamed(self):\\n        return 28\\n')
    git('add','.'); git('commit','-qm','future repair')
    before=ledger.events(task)
    result=cli('issue','localize','Click "Export report" gives 500 for month 2.','--name','P1','--revision',pinned,'--image',str(root/'nonexistent.png'))
    assert result['revision']==pinned, result
    suspects={s['method']:s for s in result['suspects']}
    for method in ('ReportController.export','ExportService.build'):
        item=suspects[method]
        assert item['file']=='reports.py' and item['source']['line']>0 and item['source']['revision']==pinned, item
        assert item['reason'] and item['label']=='hypothesis', item
        assert 'test_export_build' in item['next_check']['tests'], item
    assert result['image']['read'] is False and 'vision' in result['image']['reason'], result['image']
    assert not any(o['source']['type']=='image' for o in result['observations'])
    assert not result['proposed_changes'] and result['search_receipts']
    assert ledger.events(task)==before
'''.replace('CONTRACT', repr(json.dumps(plan_json())))
        dump, tail = wh.run_case(self.python, body, cwd=self.runs)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)
