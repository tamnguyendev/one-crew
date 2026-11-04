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
from onecrew.v2 import compat
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

    def scenario(self, release, tag='new', **over):
        """One fixture BEHAVIOUR scenario record of the shape tests.wf_scenarios.run_scenario writes: assertions, requirements (task ids of the release
        inventory), the inventory kinds as expected and observed events, modules from the venv, the venv interpreter, a sandboxed state root."""
        table = check.inventory(release); venv = str(Path(self.sandbox)/tag)
        value = {'kind': 'behavior', 'scenario': f'{release.lower()}-fixture', 'release': release, 'requirements': [t + ' fixture requirement' for t in table['tasks']],
                 'expected_events': list(table['kinds']), 'no_new_events': table.get('none_reason'), 'observed_events': list(table['kinds']) + ['plan.proposed'],
                 'assertions': [{'name': 'state is passed', 'ok': True, 'detail': ''}, {'name': 'text rendered', 'ok': True, 'detail': ''}],
                 'boundary_violations': [], 'modules': [{'name': 'onecrew.v2.example', 'path': str(Path(venv)/'site-packages'/'onecrew'/'v2'/'example.py')}],
                 'command': [str(Path(venv)/'python.exe'), '-I', '-c', '<scenario>'], 'state_root': str(Path(self.sandbox)/'scenarios'/release/'state'),
                 'result': 'pass', 'reasons': [], **identity(self.current)}
        value.update(over); return value

    def events_receipt(self, release):
        table = check.inventory(release)
        new_events = [{'kind': k, 'class': compat.event_class(k), 'anchor': 'plan-ns:P1' if compat.event_class(k) == 'B' else 'plan:legacy', 'payload': {'plan': 'legacy', 'revision': 1}}
                      for k in table['kinds']]
        neutral = [k for k in table['kinds'] if compat.event_class(k) == 'A']
        extra = {} if table['kinds'] else {'none_reason': table['none_reason'], 'regression_scenarios': [f'{release.lower()}-fixture']}
        return self.receipt(kind='events', release=release, old_artifact=identity(self.previous), expected_kinds=list(table['kinds']),
                            observed_kinds=list(table['kinds']) + ['plan.proposed'], new_events=new_events,
                            comparisons=[{'kind': k, 'before': {'S': 'approved', 'G': 'allowed', 'C': 'continue'}, 'after': {'S': 'approved', 'G': 'allowed', 'C': 'continue'}} for k in neutral], **extra)

    def installed(self, artifact, tag, at='2026-10-24T12:00:00Z', release='R01'):
        venv = str(Path(self.sandbox)/tag)
        site = str(Path(venv)/'site-packages'); path = str(Path(site)/'onecrew/v2/example.py')
        with ZipFile(self.root/artifact['wheel']) as archive: sha = hashlib.sha256(archive.read('onecrew/v2/example.py')).hexdigest()
        return self.receipt(artifact, kind='installed', at=at, release=release, command=[str(Path(venv)/'python.exe'), '-m', 'onecrew.v2.cli', 'plan', 'show', 'legacy'],
            exit_code=0, venv=venv, fresh_venv=True, state_root=str(Path(self.sandbox)/'copy'),
            site=[site], checkout=str(self.root/'checkout'), boundary_violations=[], checkout_control_refused=True,
            new_modules=['onecrew/v2/example.py'], loaded=[{'name':'onecrew.v2.example','path':path,'archive_path':'onecrew/v2/example.py','sha256':sha}],
            scenarios=[self.scenario(release, tag)])

    def retarget(self, release):
        """Point the fixture bundle at another release: every receipt names it; installed and events are rebuilt from that release's inventory."""
        self.bundle['release'] = release
        for name in check.CHECKS: self.change(name, lambda r: r.update(release=release))
        self.bundle['checks']['installed'] = self.installed(self.current, 'new', release=release)
        self.bundle['checks']['events'] = self.events_receipt(release)
        self.change('rollback', lambda r: r.update(forward_run=self.installed(self.current, 'forward', '2026-10-24T11:59:00Z', release=release)))

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
                'events':self.events_receipt('R01'),
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
        self.retarget('R05')
        self.change('rollback',lambda r:r.update(intent_events=[{'seq':1,'kind':'reconciled','intent':'ATT-A'}, {'seq':2,'kind':'continued','intent':'ATT-A'}]))
        self.assertEqual(self.result()['decision'],'pass',self.result())
        self.change('rollback',lambda r:r.update(intent_events=[{'seq':1,'kind':'effect','intent':'ATT-A'}, {'seq':2,'kind':'reconciled','intent':'ATT-A'}]))
        self.refused('T54.4')

    def test_receipt_hash_and_reference_escape_refused(self):
        ref=self.bundle['checks']['installed']; (self.root/ref['path']).write_text('{}')
        self.refused('T54.1')
        self.bundle['checks']['installed']={'path':'../outside.json','sha256':'f'*64}; self.refused('T54.1')

    def test_rp_uses_shared_matrix_rule_without_requiring_future_pilot_reviewer(self):
        self.retarget('RP')
        rows,items=[],[]
        for provider in ('claude','codex','kiro'):
            for role in ('reviewer','advisor'):
                key=provider+':'+role; usable=key=='codex:advisor'
                row={'id':key,'provider':provider,'role':role,'model':'fixture-model','vendor':'fixture-vendor',
                     'cli_sha256':'e'*64,'cli_files':{'fixture.exe':'e'*64},'status':'usable' if usable else 'unverified'}
                rows.append(row)
                original=self.receipt(kind='behavior',item=key,provider=provider,role=role,model=row['model'],vendor=row['vendor'],
                    result='pass' if usable else 'blocked',reason='fixture account absent',pins_source='fixture program kit',
                    cli_identity={'provider':provider,'path':'fixture.exe','argv':['fixture.exe'],'sha256':'e'*64,
                                  'files':row['cli_files'],'version':'fixture-1'})
                items.append({'id':key,'original':original,'supplements':[]})
        from wfkit.provider_evidence import decisions, decisions_line, render   # round 8 H (T40c [E30]): decisions before/after + notes line
        record=decisions(rows,'fixture program kit')
        self.bundle['provider_bundle']={'artifacts':{'pilot':self.current,'final':self.current},'providers':rows,'comparison':{'items':items},
                                        'decisions':{'before':record,'after':record}}
        states=check.providers(rows,items,check.Receipts(self.root,True),self.current,self.current)
        # round 7 D (T40c [E29]): the notes carry the rendered per-cell lines
        self.change('notes',lambda r:r.update(provider_states=states,subset=['codex:advisor'],p1_count=1,p1_label='subset',
                                              matrix_markdown=chr(10).join(render(states)+[decisions_line(record)])))
        self.assertEqual(self.result()['decision'],'pass',self.result())
        self.change('notes',lambda r:r.update(subset=['codex:advisor','kiro:reviewer']))
        self.refused('T54.5')

    def test_rx_adapter_scenario_is_required_on_delivered_build(self):
        self.retarget('RX1')
        self.change('installed',lambda r:r.update(adapter_runs=[{'adapter':'doc','root':'plan-ns:Doc',
            'result':'pass','artifact':'d'*64,**identity(self.current)}]))
        self.assertEqual(self.result()['decision'],'pass',self.result())
        self.change('installed',lambda r:r.update(adapter_runs=[])); self.refused('T54.1')

    def test_t54_1_import_only_or_disabled_feature_or_shadowed_module_or_wrong_wheel_is_refused(self):
        """Review a2476ab P1: an installed scenario proves a feature only through assertions on behaviour and the events it writes."""
        original=copy.deepcopy(self.bundle)
        mutations={'no scenario at all':lambda r:r.update(scenarios=[]),
            'import-only (no assertion)':lambda r:r['scenarios'][0].update(assertions=[]),
            'feature disabled (assertion failed)':lambda r:r['scenarios'][0]['assertions'].append({'name':'card shown','ok':False,'detail':'nothing shown'}),
            'feature silent (event not written)':lambda r:r['scenarios'][0].update(observed_events=['plan.proposed']),
            'empty result claimed pass':lambda r:r['scenarios'][0].update(result='fail',reasons=['failed assertions: x']),
            'checkout shadows the module':lambda r:r['scenarios'][0]['modules'].append({'name':'onecrew.v2.plan','path':str(self.root/'checkout/onecrew/v2/plan.py')}),
            'boundary violation':lambda r:r['scenarios'][0].update(boundary_violations=[['onecrew.v2.plan','checkout']]),
            'wrong wheel/revision':lambda r:r['scenarios'][0].update(wheel_sha256='e'*64),
            'not the venv interpreter':lambda r:r['scenarios'][0].update(command=[sys.executable,'-c','x']),
            'a release task without a scenario':lambda r:r['scenarios'][0].update(requirements=['W99 something else'])}
        for label,fn in mutations.items():
            with self.subTest(label):
                self.bundle=copy.deepcopy(original); self.change('installed',fn); self.refused('T54.1')
        self.bundle=copy.deepcopy(original); self.assertEqual(self.result()['decision'],'pass')

    def test_t54_3_inventory_is_the_validators_and_every_kind_must_be_observed_classified_and_compared(self):
        """Review a2476ab P1: the expected inventory comes from wfkit/release_events.json, not from the producer; dropping a kind, a silent
        feature, a wrong class/payload/anchor, a missing comparison or another release's inventory is refused even when result says pass."""
        original=copy.deepcopy(self.bundle)
        table=check.inventory('R01'); first=table['kinds'][0]
        mutations={'kind dropped from receipt':lambda r:r.update(new_events=[e for e in r['new_events'] if e['kind']!=first]),
            'feature did not emit (not observed)':lambda r:r.update(observed_kinds=[k for k in r['observed_kinds'] if k!=first]),
            'wrong class':lambda r:r['new_events'][0].update(**{'class':'B'}),
            'class B on a legacy anchor':lambda r:r['new_events'].append({'kind':'node.started','class':'B','anchor':'plan:legacy','payload':{}}),
            'class-0 payload without its field':lambda r:r['new_events'].append({'kind':'plan.approved','class':'0','anchor':'plan:legacy','payload':{'plan':'legacy'}}),
            'comparison dropped':lambda r:r.update(comparisons=r['comparisons'][1:]),
            'another release inventory':lambda r:r.update(expected_kinds=check.inventory('R02')['kinds']),
            'inventory narrowed by the producer':lambda r:r.update(expected_kinds=r['expected_kinds'][1:])}
        for label,fn in mutations.items():
            with self.subTest(label):
                self.bundle=copy.deepcopy(original); self.change('events',fn); self.refused('T54.3')
        # a release without new kinds: the declared reason and a passing regression scenario are required
        self.bundle=copy.deepcopy(original); self.retarget('R07'); self.assertEqual(self.result()['decision'],'pass',self.result())
        self.change('events',lambda r:r.update(none_reason='whatever')); self.refused('T54.3')
        self.bundle=copy.deepcopy(original); self.retarget('R07'); self.change('events',lambda r:r.update(regression_scenarios=['not-run'])); self.refused('T54.3')

    # -- first delivery (bootstrap) path: directive section 6 ------------------------------------------------------------------------------
    def bootstrap(self, **over):
        """An ordinary bundle turned into a FIRST release: no gate history, and the previous build pinned as the compat baseline (never delivered)."""
        self.bundle['gate_history'] = []
        baseline = {**identity(self.previous), 'role': 'compat-baseline', 'delivered': False, 'accepted': False}
        baseline.update(over)
        self.bundle['first_release'] = {'baseline': baseline, 'reason': 'no release of this program has been delivered'}

    def inputs_reasons(self, result):
        return [r['detail'] for r in result['reasons'] if r['code'] in ('INPUTS', 'INPUTS(bootstrap)')]

    def test_bootstrap_i_pinned_baseline_passes_inputs_via_the_bootstrap_condition_only(self):
        self.bootstrap(); result = self.result()
        self.assertEqual(result['decision'], 'pass', result)
        self.assertTrue(result['conditions']['INPUTS(bootstrap)'], result)
        self.assertNotIn('INPUTS', result['conditions'])                 # never reported as an ordinary delivered-history INPUTS
        self.assertTrue(result['first_release'])
        self.assertEqual(result['first_release_baseline'], {**identity(self.previous), 'role': 'compat-baseline', 'delivered': False, 'accepted': False})
        self.assertFalse(result['owner_acceptance'])
        self.assertIn('first release', result['proves'])

    def test_bootstrap_ii_baseline_identity_differs_from_previous_artifact_is_refused(self):
        original = copy.deepcopy(self.bundle)
        for over in ({'commit': 'c' * 40}, {'wheel_sha256': 'e' * 64}):
            with self.subTest(over):
                self.bundle = copy.deepcopy(original); self.bootstrap(**over)
                self.refused('INPUTS(bootstrap)')
                self.assertIn('baseline is not the previous artifact', ' '.join(self.inputs_reasons(self.result())))

    def test_bootstrap_iii_baseline_not_the_build_the_drills_ran_is_refused(self):
        original = copy.deepcopy(self.bundle); other = identity(self.wheel('other', 'c' * 40))
        mutations = {'upgrade from another build': ('upgrade', lambda r: r.update(**{'from': other})),
                     'event comparator on another build': ('events', lambda r: r.update(old_artifact=other)),
                     'scanner modelled another version': ('rollback', lambda r: r['allowed']['scan'].update(old_version='c' * 40)),
                     'old run installed another wheel': ('rollback', lambda r: r['allowed'].update(old_run=self.installed(self.current, 'old', '2026-10-24T11:58:00Z')))}
        for label, (name, fn) in mutations.items():
            with self.subTest(label):
                self.bundle = copy.deepcopy(original); self.bootstrap(); self.change(name, fn)
                self.refused('INPUTS(bootstrap)')

    def test_bootstrap_iv_a_bundle_with_gate_history_is_not_a_first_release(self):
        history = self.bundle['gate_history']; self.bootstrap(); self.bundle['gate_history'] = history     # passing CG-R00 of the previous build
        self.refused('INPUTS(bootstrap)')
        self.assertIn('not a first release', ' '.join(self.inputs_reasons(self.result())))
        self.assertFalse(self.result().get('first_release'))
        # and the ordinary bundle with that history is still judged by the normal rule
        del self.bundle['first_release']; result = self.result()
        self.assertEqual(result['decision'], 'pass', result); self.assertTrue(result['conditions']['INPUTS'])
        self.assertNotIn('INPUTS(bootstrap)', result['conditions']); self.assertFalse(result['first_release'])

    def test_bootstrap_v_ordinary_bundle_without_history_keeps_the_old_refusal(self):
        self.bundle['gate_history'] = []; result = self.result()
        self.assertEqual(result['decision'], 'refused')
        self.assertFalse(result['conditions']['INPUTS']); self.assertNotIn('INPUTS(bootstrap)', result['conditions'])
        self.assertEqual([r['detail'] for r in result['reasons'] if r['code'] == 'INPUTS'], ['previous delivered gate history missing'])
        self.assertFalse(result['first_release'])

    def test_bootstrap_vi_baseline_labelled_delivered_or_accepted_or_malformed_is_refused(self):
        original = copy.deepcopy(self.bundle)
        for over in ({'delivered': True}, {'accepted': True}, {'delivered': 0}, {'role': 'delivered-release'}, {'owner_acceptance': True}):
            with self.subTest(over):
                self.bundle = copy.deepcopy(original); self.bootstrap(**over); self.refused('INPUTS(bootstrap)')
        for value in (None, {}, {'baseline': None}, True):
            with self.subTest(value):
                self.bundle = copy.deepcopy(original); self.bundle['gate_history'] = []; self.bundle['first_release'] = value
                self.refused('INPUTS(bootstrap)')

    def test_bootstrap_still_needs_monitored_files_and_delivery_order(self):
        original = copy.deepcopy(self.bundle)
        self.bootstrap(); self.bundle['monitored_files'][0]['after'] = 'e' * 64; self.refused('INPUTS(bootstrap)')
        self.bundle = copy.deepcopy(original); self.bootstrap(); self.bundle['monitored_files'] = []; self.refused('INPUTS(bootstrap)')
        self.bundle = copy.deepcopy(original); self.bootstrap(); self.bundle['deliveries'] = [{**identity(self.current), 'at': '2026-10-24T11:00:01Z'}]
        self.refused('INPUTS(bootstrap)')

    def test_cli_empty_bundle_is_structured_refusal(self):
        path=self.root/'empty.json'; path.write_text('{}')
        result=subprocess.run([sys.executable,'-m','wfkit.release_check',str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,1); self.assertEqual(json.loads(result.stdout)['decision'],'refused')
