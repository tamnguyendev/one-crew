"""Structured T54 validators over explicit fixtures, never a release claim."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from onecrew.ledger import content_hash
from wfkit import release_check as check
from wfkit.finalgate import identity


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.count = 0
        self.previous = self.wheel('previous', 'a' * 40)
        self.current = self.wheel('current', 'b' * 40)
        self.sandbox = str(self.root/'isolated')
        self.snapshot = [{'id': 'TASK-A', 'revision': 'rev-A', 'budget': {'calls_used': 2, 'max_calls': 9},
                          'evidence': ['receipt-original'], 'attempts': [{'id': 'ATT-A', 'status': 'unknown'}]}]
        self.bundle = self.make_bundle()

    def wheel(self, name, commit):
        path = self.root/(name+'.whl')
        with ZipFile(path, 'w') as archive: archive.writestr('onecrew/v2/example.py', name)
        return {'wheel': path.name, 'commit': commit, 'wheel_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def ref(self, value):
        self.count += 1; path = self.root/f'receipt-{self.count}.json'
        raw = json.dumps(value, sort_keys=True).encode(); path.write_bytes(raw)
        return {'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def receipt(self, artifact=None, **values):
        return self.ref({**identity(artifact or self.current), 'at': '2026-10-24T12:00:00Z',
            'result': 'pass', 'release': 'R01', 'simulated': True,
            'provenance': {'kind': 'fixture', 'source': 'T54 validator self-test'}, **values})

    def read(self, ref): return json.loads((self.root/ref['path']).read_text())

    def change(self, name, fn):
        value = self.read(self.bundle['checks'][name]); fn(value)
        self.bundle['checks'][name] = self.ref(value)

    def installed(self, artifact, tag, at='2026-10-24T12:00:00Z'):
        venv = str(Path(self.sandbox)/tag)
        site = str(Path(venv)/'site-packages'); path = str(Path(site)/'onecrew/v2/example.py')
        with ZipFile(self.root/artifact['wheel']) as archive: sha = hashlib.sha256(archive.read('onecrew/v2/example.py')).hexdigest()
        return self.receipt(artifact, kind='installed', at=at, command=[str(Path(venv)/'python.exe'), '-m', 'onecrew.v2.cli', 'plan', 'show', 'legacy'],
            exit_code=0, venv=venv, fresh_venv=True, state_root=str(Path(self.sandbox)/'copy'),
            site=[site], checkout=str(self.root/'checkout'), boundary_violations=[], checkout_control_refused=True,
            new_modules=['onecrew/v2/example.py'], loaded=[{'name':'onecrew.v2.example','path':path,'archive_path':'onecrew/v2/example.py','sha256':sha}])

    def scan(self, blocked):
        hashes = {str(Path(self.sandbox)/'copy/plans/legacy/v1.json'): 'c'*64}
        scan = {'read_only': True, 'old_version': self.previous['commit'], 'state_root': str(Path(self.sandbox)/'copy'), 'ledger_sha': 'd'*64,
            'input_hashes': hashes, 'inputs_sha': content_hash(hashes),
            'roots': [{'anchor':'plan:legacy','blocks':[{'id':'B4','type':'read'}] if blocked else []}],
            'blocking': {'read': int(blocked), 'continue': 0, 'total': int(blocked)}}
        return {'scan':scan, 'ledger_at_switch':scan['ledger_sha'], 'inputs_at_switch':scan['inputs_sha'], 'switched':not blocked}

    def make_bundle(self):
        allowed = self.scan(False); allowed['old_run'] = self.installed(self.previous, 'old', '2026-10-24T11:58:00Z')
        notes = '\n\n'.join('## '+title+'\n'+body for title,body in zip(check.SECTIONS,
            ['Observed outcome.', 'Fixture only.', 'Use an isolated venv.', 'Use the pinned previous wheel.',
             'Code: present\nFixture checks: passed\nReal checks: not-run\nAcceptance: not-requested']))
        return {'schema':1,'mode':'fixture','release':'R01','sandbox':self.sandbox,
            'artifacts':{'previous':self.previous,'current':self.current},
            'gate_history':[self.receipt(self.previous, gate='CG-R00', decision='pass', at='2026-10-24T11:00:00Z')],
            'monitored_files':[{'path':str(self.root/'live-ledger.sqlite3'),'before':'f'*64,'after':'f'*64}],
            'checks':{
                'installed':self.installed(self.current,'new'),
                'upgrade':self.receipt(kind='upgrade', at='2026-10-24T11:57:00Z', **{'from':identity(self.previous),'to':identity(self.current)},
                    state_root=str(Path(self.sandbox)/'copy'), source_state_root=str(self.root/'source'), before=copy.deepcopy(self.snapshot),after=copy.deepcopy(self.snapshot)),
                'events':self.receipt(kind='events', old_artifact=identity(self.previous),new_events=[
                    {'kind':'learning.outcome','class':'A','anchor':'plan:legacy','payload':{'phase':'completed'}}],
                    comparisons=[{'kind':'learning.outcome','before':{'S':'approved','G':'allowed','C':'continue'},'after':{'S':'approved','G':'allowed','C':'continue'}}]),
                'rollback':self.receipt(kind='rollback',rejected=self.scan(True),allowed=allowed,
                    forward_run=self.installed(self.current,'forward','2026-10-24T11:59:00Z'),before=copy.deepcopy(self.snapshot),after=copy.deepcopy(self.snapshot)),
                'notes':self.receipt(kind='notes',markdown=notes)}}

    def result(self): return check.decide(self.bundle,self.root,True)
    def refused(self, code):
        result=self.result(); self.assertEqual(result['decision'],'refused',result)
        self.assertIn(code,{r['code'] for r in result['reasons']},result)

    def test_complete_fixture_validates_only_rules_and_never_accepts(self):
        result=self.result(); self.assertEqual(result['decision'],'pass',result)
        self.assertFalse(result['owner_acceptance']); self.assertIn('rules only',result['proves'])
        self.assertEqual(check.decide(self.bundle,self.root)['decision'],'refused')
        self.bundle['mode']='real'; self.assertEqual(self.result()['decision'],'refused')

    def test_each_required_part_missing_fails_closed(self):
        original=copy.deepcopy(self.bundle)
        for i,name in enumerate(check.CHECKS,1):
            self.bundle=copy.deepcopy(original); del self.bundle['checks'][name]
            with self.subTest(name=name): self.refused('T54.'+str(i))
        for value in ({},None,[],{'schema':1}): self.assertEqual(check.decide(value,self.root)['decision'],'refused')

    def test_wrong_wheel_hash_checkout_origin_or_missing_module_refused(self):
        original=copy.deepcopy(self.bundle)
        mutations=[lambda r:r.update(wheel_sha256='e'*64),
            lambda r:r['loaded'][0].update(path=str(self.root/'checkout/onecrew/v2/example.py')),
            lambda r:r['loaded'][0].update(sha256='e'*64),
            lambda r:r.update(new_modules=['onecrew/v2/missing.py']),
            lambda r:r.update(checkout_control_refused=False)]
        for fn in mutations:
            self.bundle=copy.deepcopy(original); self.change('installed',fn); self.refused('T54.1')

    def test_upgrade_detects_budget_reset_evidence_loss_and_unknown_attempt_loss(self):
        original=copy.deepcopy(self.bundle)
        for field,value in [('budget',{'calls_used':0}),('evidence',[]),('attempts',[]),('revision','new-revision')]:
            self.bundle=copy.deepcopy(original); self.change('upgrade',lambda r:r['after'][0].update({field:value})); self.refused('T54.2')

    def test_event_class_unknown_legacy_b_and_changed_sgc_refused(self):
        original=copy.deepcopy(self.bundle)
        for fn in [lambda r:r['new_events'][0].update(kind='unknown.event'),
                   lambda r:r['new_events'][0].update(kind='node.started',**{'class':'B'}),
                   lambda r:r['comparisons'][0]['after'].update(G='blocked'),
                   lambda r:r.update(comparisons=[])]:
            self.bundle=copy.deepcopy(original); self.change('events',fn); self.refused('T54.3')

    def test_rollback_requires_both_branches_fresh_ledger_and_config_scan(self):
        original=copy.deepcopy(self.bundle)
        for fn in [lambda r:r['rejected'].update(switched=True),lambda r:r['allowed'].update(switched=False),
                   lambda r:r['allowed'].update(ledger_at_switch='e'*64),lambda r:r['allowed'].update(inputs_at_switch='e'*64),
                   lambda r:r['allowed']['scan']['blocking'].update(total=9),
                   lambda r:r['after'][0].update(revision='lost')]:
            self.bundle=copy.deepcopy(original); self.change('rollback',fn); self.refused('T54.4')

    def test_live_state_and_early_delivery_and_wrong_previous_gate_refused(self):
        original=copy.deepcopy(self.bundle)
        self.bundle['monitored_files'][0]['after']='e'*64; self.refused('INPUTS')
        self.bundle=copy.deepcopy(original); self.bundle['deliveries']=[{**identity(self.current),'at':'2026-10-24T11:00:01Z'}]; self.refused('INPUTS')
        self.bundle=copy.deepcopy(original); self.bundle['gate_history'].append(self.receipt(self.current,gate='CG-R00',decision='pass')); self.refused('INPUTS')

    def test_notes_keep_four_states_separate_and_real_claims_need_real_receipts(self):
        original=copy.deepcopy(self.bundle)
        for before,after in [('Acceptance: not-requested','Acceptance: accepted'),('Real checks: not-run','Real checks: passed'),
                             ('Fixture checks: passed\nReal checks: not-run','Fixture checks / Real checks: passed'),
                             ('## Rollback\nUse the pinned previous wheel.','## Rollback\n')]:
            self.bundle=copy.deepcopy(original); self.change('notes',lambda r:r.update(markdown=r['markdown'].replace(before,after))); self.refused('T54.5')

    def test_r05_rollforward_reconciles_before_continue_or_effect(self):
        self.bundle['release']='R05'
        for name in check.CHECKS: self.change(name,lambda r:r.update(release='R05'))
        self.change('rollback',lambda r:r.update(intent_events=[{'seq':1,'kind':'reconciled','intent':'ATT-A'}, {'seq':2,'kind':'continued','intent':'ATT-A'}]))
        self.assertEqual(self.result()['decision'],'pass',self.result())
        self.change('rollback',lambda r:r.update(intent_events=[{'seq':1,'kind':'effect','intent':'ATT-A'}, {'seq':2,'kind':'reconciled','intent':'ATT-A'}]))
        self.refused('T54.4')

    def test_receipt_hash_and_reference_escape_refused(self):
        ref=self.bundle['checks']['installed']; (self.root/ref['path']).write_text('{}')
        self.refused('T54.1')
        self.bundle['checks']['installed']={'path':'../outside.json','sha256':'f'*64}; self.refused('T54.1')

    def test_rp_uses_shared_matrix_rule_without_requiring_future_pilot_reviewer(self):
        self.bundle['release']='RP'
        for name in check.CHECKS: self.change(name,lambda r:r.update(release='RP'))
        rows,items=[],[]
        for provider in ('claude','codex','kiro'):
            for role in ('reviewer','advisor'):
                key=provider+':'+role; usable=key=='codex:advisor'
                row={'id':key,'provider':provider,'role':role,'model':'fixture-model','vendor':'fixture-vendor',
                     'cli_sha256':'e'*64,'cli_files':{'fixture.exe':'e'*64},'status':'usable' if usable else 'unverified'}
                rows.append(row)
                original=self.receipt(kind='behavior',item=key,provider=provider,role=role,model=row['model'],vendor=row['vendor'],
                    result='pass' if usable else 'blocked',reason='fixture account absent',
                    cli_identity={'provider':provider,'path':'fixture.exe','argv':['fixture.exe'],'sha256':'e'*64,
                                  'files':row['cli_files'],'version':'fixture-1'})
                items.append({'id':key,'original':original,'supplements':[]})
        self.bundle['provider_bundle']={'artifacts':{'pilot':self.current,'final':self.current},'providers':rows,'comparison':{'items':items}}
        states=check.providers(rows,items,check.Receipts(self.root,True),self.current,self.current)
        self.change('notes',lambda r:r.update(provider_states=states,subset=['codex:advisor'],p1_count=1,p1_label='subset'))
        self.assertEqual(self.result()['decision'],'pass',self.result())
        self.change('notes',lambda r:r.update(subset=['codex:advisor','kiro:reviewer']))
        self.refused('T54.5')

    def test_rx_adapter_scenario_is_required_on_delivered_build(self):
        self.bundle['release']='RX1'
        for name in check.CHECKS: self.change(name,lambda r:r.update(release='RX1'))
        self.change('installed',lambda r:r.update(adapter_runs=[{'adapter':'doc','root':'plan-ns:Doc',
            'result':'pass','artifact':'d'*64,**identity(self.current)}]))
        self.assertEqual(self.result()['decision'],'pass',self.result())
        self.change('installed',lambda r:r.update(adapter_runs=[])); self.refused('T54.1')

    def test_cli_empty_bundle_is_structured_refusal(self):
        path=self.root/'empty.json'; path.write_text('{}')
        result=subprocess.run([sys.executable,'-m','wfkit.release_check',str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,1); self.assertEqual(json.loads(result.stdout)['decision'],'refused')
