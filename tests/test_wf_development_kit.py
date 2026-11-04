"""Development registry rules only: fabricated receipts never qualify a release.

These tests do not run registered suites recursively or call real providers.
The real runner smoke is a separate selected installed check against its wheel.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from wfkit import development_gate as dev, kitguard


class DevelopmentRegistryTests(unittest.TestCase):
    def test_registered_groups_and_source_mapping_are_explicit(self):
        config=dev.load()
        self.assertEqual(set(config['releases']), {'R01','R02','R03','R04','R05','R06','R07','R08','RP','RX1','RX2','KN','PL'})
        for group,body in config['releases'].items():
            self.assertTrue(body['acceptance'])
            self.assertTrue(all(not key.startswith('T') for key in body['testcases']))
        self.assertEqual(config['releases']['RP']['acceptance']['T40b']['status'],'blocked')
        self.assertTrue(all(c['status']=='blocked' for c in config['releases']['PL']['acceptance'].values()))

    def test_selector_rejects_unknown_and_preserves_cross_feature_group_identity(self):
        config=dev.load()
        selected=dev.select(config,['R04','R05'],['R04/check.engine','R05/check.engine'])
        self.assertEqual(len(selected),2)
        with self.assertRaisesRegex(ValueError,'Unknown'): dev.select(config,['R99'])
        with self.assertRaisesRegex(ValueError,'Unknown'): dev.select(config,['R04'],['R05/check.engine'])

    def test_legacy_guard_globals_restore_even_after_error(self):
        before=kitguard.CONFIG,kitguard.MANIFEST
        with self.assertRaises(RuntimeError):
            with dev.layout():
                self.assertEqual(kitguard.CONFIG,dev.CONFIG)
                raise RuntimeError('fixture')
        self.assertEqual((kitguard.CONFIG,kitguard.MANIFEST),before)

    def test_acceptance_snapshot_is_pinned_and_not_silently_changed(self):
        config=dev.load()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'wfkit').mkdir()
            (root/'wfkit/manifest.json').write_bytes((dev.ROOT/'wfkit/manifest.json').read_bytes())
            source=root/config['source']['path']; source.parent.mkdir(parents=True)
            source.write_bytes((dev.ROOT/config['source']['path']).read_bytes())
            config['releases']={'R01':config['releases']['R01']}
            case = config['releases']['R01']['acceptance']['T24a']           # flip whatever the real status is: the snapshot must then mismatch
            case['status'] = 'partial' if case['status'] == 'complete' else 'complete'
            (root/dev.CONFIG).write_text(json.dumps(config),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'case-pinned'): dev.load(root)


class DevelopmentDecisionTests(unittest.TestCase):
    def setUp(self):
        self.config={'releases':{'R':{'testcases':{'check.installed':{'installed':True}},
            'acceptance':{'T1':{'status':'partial','checks':['check.installed'],
                'gaps':[{'kind':'acceptance-audit','detail':'One counterexample remains unverified.'}]}}}}}
        self.build={'commit':'a'*40,'wheel_sha256':'b'*64,'dirty':[]}
        self.receipts={'R/check.installed':dict(self.build, result='pass',tests_run=1,tests_passed=1,tests_errors=0,
                                               tests_skipped=0,wheel_used=['b'*64])}
        self.install={'ok':True,'control_refused':True,'wheel_sha256':'b'*64}
        self.guards={'ok':True}

    def judge(self,only=None):
        return dev.decide(self.config,['R'],self.build,self.receipts,self.install,self.guards,only)

    def test_passing_implementation_checks_never_clear_incomplete_acceptance(self):
        result=self.judge()
        self.assertFalse(result['release_delivery']); self.assertFalse(result['owner_acceptance'])
        self.assertEqual(result['implementation_checks']['failed'],[])
        self.assertIn('acceptance-partial',{p['kind'] for p in result['problems']})

    def test_wrong_wheel_empty_installed_use_simulated_skip_and_missing_fail_closed(self):
        original=copy.deepcopy(self.receipts)
        for change in ({'wheel_sha256':'c'*64},{'wheel_used':[]},{'wheel_used':['c'*64]},
                       {'simulated':True},{'tests_skipped':1},{'tests_run':0}):
            with self.subTest(change=change):
                self.receipts=copy.deepcopy(original); self.receipts['R/check.installed'].update(change)
                self.assertTrue(self.judge()['implementation_checks']['failed'])
        self.receipts={}; self.assertTrue(self.judge()['implementation_checks']['failed'])

    def test_bad_guards_origins_dirty_build_and_selected_run_each_refuse(self):
        for field,value in [('guards',{'ok':False}),('install',{}),('build',dict(self.build,dirty=['fixture']))]:
            original=getattr(self,field); setattr(self,field,value)
            self.assertGreater(len(self.judge()['problems']),1); setattr(self,field,original)
        self.assertIn('selected-only',{p['kind'] for p in self.judge(['R/check.installed'])['problems']})

    def test_live_provider_and_pilot_are_blocked_even_with_green_fake_tests(self):
        self.config['releases']['R']['acceptance']['T1']['status']='blocked'
        self.assertIn('acceptance-blocked',{p['kind'] for p in self.judge()['problems']})
        self.assertFalse(self.judge()['pilot_passed'])


if __name__=='__main__': unittest.main()
