"""WK0 + WK00 — the shared release-gate kit: kit-guard, the delivery gate (T45a) and the document self-check command (T38a).

Written from 05 (## T45 part T45a, ## T38 part T38a) BEFORE the code.

* SIMULATED receipts below (marked "simulated": true) prove ONLY the gate RULE (T45a: "Biên nhận giả lập ở selftest: chỉ chứng minh luật cổng").
  A real gate run (`python wfkit/gate.py R00 --out DIR`) refuses simulated receipts and judges its own, real ones.
* The install-origin tests ([E5], [E7]) are REAL: they build the wheel by hand, install it offline into a fresh venv, run the install scenario
  and judge the module path actually loaded (installed vs checkout).
* The T38a tests use a SMALL FAKE document directory with a fake section 7: they prove the wrapper (extraction, pin, verdict, read-only),
  not the document. The real document check is run by the gate on the real 06 document and is NOT modified or extended here.
"""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import tests.wf_wheel as wh
from wfkit import doccheck, gate, kitguard

REPO = Path(__file__).resolve().parents[1]
FENCE = chr(96) * 3


def _tmp():
    base = Path(os.environ.get('TEMP') or tempfile.gettempdir()) / 'wfkit' / uuid.uuid4().hex[:6]
    base.mkdir(parents=True)
    return base


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    return path


# --------------------------------------------------------------------------------------------------------------------
# kit-guard
# --------------------------------------------------------------------------------------------------------------------

def make_kit(root):
    """A tiny kit tree: two test modules + one kit file + a testcases.json with release R00 (and an UNFROZEN R01)."""
    write(root / 'tests' / 'test_a.py', 'ONE = 1\n')
    write(root / 'tests' / 'test_b.py', 'TWO = 2\n')
    write(root / 'wfkit' / 'kitfile.py', 'KIT = True\n')
    cfg = {'version': 1, 'releases': {
        'R00': {'kit_files': ['wfkit/kitfile.py'],
                'testcases': {'TA': {'kind': 'unittest', 'modules': ['tests.test_a']},
                              'TB': {'kind': 'unittest', 'modules': ['tests.test_b']}}}}}
    write(root / 'wfkit' / 'testcases.json', json.dumps(cfg, indent=1))
    return cfg


def u1(root, uid, file, old, new, reason='the owner accepted this weakening on 24/10 (test fixture)'):
    rec = {'id': uid, 'reason': reason, 'file': file, 'old_sha256': old, 'new_sha256': new, 'by': 'owner (fixture)', 'at': '2026-10-24T00:00:00Z'}
    write(root / 'wfkit' / 'u1' / (uid + '.json'), json.dumps(rec, indent=1))
    return rec


class KitGuardTests(unittest.TestCase):

    def setUp(self):
        self.root = _tmp()
        make_kit(self.root)
        res = kitguard.freeze(self.root, 'R00', commit='c0ffee0')
        self.assertTrue(res['ok'], res)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _codes(self, res):
        return sorted(p['code'] for p in res['problems'])

    def test_freeze_pins_kit_and_test_files_and_cases_with_provenance(self):
        m = json.loads((self.root / 'wfkit' / 'manifest.json').read_text(encoding='utf-8'))
        pins = m['releases']['R00']['pins']
        self.assertIn('tests/test_a.py', pins)
        self.assertIn('tests/test_b.py', pins)
        self.assertIn('wfkit/kitfile.py', pins)
        self.assertIn('wfkit/testcases.json#R00/TA', pins)
        self.assertEqual(pins['tests/test_a.py']['sha256'], sha('ONE = 1\n'))
        self.assertEqual(pins['tests/test_a.py']['commit'], 'c0ffee0')                 # provenance
        self.assertTrue(pins['tests/test_a.py']['added_at'])
        self.assertTrue(kitguard.verify(self.root)['ok'])

    def test_line_endings_alone_do_not_change_a_pin(self):
        (self.root / 'tests' / 'test_a.py').write_bytes(b'ONE = 1\r\n')                   # the same text checked out with autocrlf
        self.assertTrue(kitguard.verify(self.root)['ok'])

    def test_edited_pinned_test_file_is_refused(self):
        write(self.root / 'tests' / 'test_a.py', 'ONE = 1\nassert True  # weakened\n')
        res = kitguard.verify(self.root)
        self.assertFalse(res['ok'])
        self.assertEqual(self._codes(res), ['changed'])
        p = res['problems'][0]
        self.assertEqual(p['pin'], 'tests/test_a.py')
        self.assertEqual(p['pinned_sha256'], sha('ONE = 1\n'))                           # old hash named
        self.assertNotEqual(p['actual_sha256'], p['pinned_sha256'])                      # new hash named

    def test_deleted_pinned_file_is_refused(self):
        (self.root / 'tests' / 'test_b.py').unlink()
        res = kitguard.verify(self.root)
        self.assertFalse(res['ok'])
        self.assertEqual(self._codes(res), ['deleted'])

    def test_adding_new_files_after_freeze_passes(self):
        write(self.root / 'tests' / 'test_new.py', 'NEW = 3\n')
        write(self.root / 'wfkit' / 'another_kit_file.py', 'X = 1\n')
        res = kitguard.verify(self.root)
        self.assertTrue(res['ok'], res)

    def test_adding_a_testcase_to_a_frozen_release_passes_but_changing_or_removing_one_is_refused(self):
        cfg_path = self.root / 'wfkit' / 'testcases.json'
        cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        cfg['releases']['R00']['testcases']['TC'] = {'kind': 'unittest', 'modules': ['tests.test_a']}
        write(cfg_path, json.dumps(cfg, indent=1))
        self.assertTrue(kitguard.verify(self.root)['ok'])                                 # an addition
        cfg['releases']['R00']['testcases']['TA']['modules'] = []                         # weakened: runs nothing
        write(cfg_path, json.dumps(cfg, indent=1))
        res = kitguard.verify(self.root)
        self.assertEqual(self._codes(res), ['changed'])
        self.assertEqual(res['problems'][0]['pin'], 'wfkit/testcases.json#R00/TA')
        del cfg['releases']['R00']['testcases']['TA']                                     # removed
        write(cfg_path, json.dumps(cfg, indent=1))
        self.assertEqual(self._codes(kitguard.verify(self.root)), ['deleted'])

    def test_a_valid_u1_lets_the_change_pass_and_is_reported(self):
        old = sha('ONE = 1\n')
        write(self.root / 'tests' / 'test_a.py', 'ONE = 1\nTWO = 2\n')
        u1(self.root, 'U1-001', 'tests/test_a.py', old, sha('ONE = 1\nTWO = 2\n'))
        res = kitguard.verify(self.root)
        self.assertTrue(res['ok'], res)
        self.assertEqual([r['id'] for r in res['u1_used']], ['U1-001'])
        self.assertEqual(res['u1_used'][0]['file'], 'tests/test_a.py')
        self.assertEqual(res['u1_used'][0]['old_sha256'], old)
        self.assertEqual(res['u1_used'][0]['new_sha256'], sha('ONE = 1\nTWO = 2\n'))

    def test_u1_chain_and_u1_for_a_deletion(self):
        a, b, c = 'ONE = 1\n', 'ONE = 2\n', 'ONE = 3\n'
        write(self.root / 'tests' / 'test_a.py', c)
        u1(self.root, 'U1-010', 'tests/test_a.py', sha(a), sha(b))
        u1(self.root, 'U1-011', 'tests/test_a.py', sha(b), sha(c))
        res = kitguard.verify(self.root)
        self.assertTrue(res['ok'], res)
        self.assertEqual(sorted(r['id'] for r in res['u1_used']), ['U1-010', 'U1-011'])
        (self.root / 'tests' / 'test_b.py').unlink()
        self.assertFalse(kitguard.verify(self.root)['ok'])
        u1(self.root, 'U1-012', 'tests/test_b.py', sha('TWO = 2\n'), None)
        self.assertTrue(kitguard.verify(self.root)['ok'])

    def test_an_invalid_u1_does_not_count(self):
        new = 'ONE = 1\nTWO = 2\n'
        write(self.root / 'tests' / 'test_a.py', new)
        # wrong old hash
        u1(self.root, 'U1-020', 'tests/test_a.py', sha('SOMETHING ELSE\n'), sha(new))
        self.assertFalse(kitguard.verify(self.root)['ok'])
        # wrong new hash
        u1(self.root, 'U1-021', 'tests/test_a.py', sha('ONE = 1\n'), sha('NOT THE FILE\n'))
        self.assertFalse(kitguard.verify(self.root)['ok'])
        # empty reason
        u1(self.root, 'U1-022', 'tests/test_a.py', sha('ONE = 1\n'), sha(new), reason='   ')
        res = kitguard.verify(self.root)
        self.assertFalse(res['ok'])
        self.assertTrue(res['u1_invalid'])                                                # reported, not silently dropped
        # record whose id does not match its file name
        rec = u1(self.root, 'U1-023', 'tests/test_a.py', sha('ONE = 1\n'), sha(new))
        (self.root / 'wfkit' / 'u1' / 'U1-023.json').rename(self.root / 'wfkit' / 'u1' / 'other-name.json')
        self.assertFalse(kitguard.verify(self.root)['ok'])
        # and a record for a DIFFERENT file does not cover this one
        u1(self.root, 'U1-024', 'tests/test_b.py', sha('ONE = 1\n'), sha(new))
        self.assertFalse(kitguard.verify(self.root)['ok'])
        self.assertEqual(rec['id'], 'U1-023')

    def test_kit_guard_never_creates_a_u1(self):
        write(self.root / 'tests' / 'test_a.py', 'changed\n')
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        res = kitguard.verify(self.root)
        self.assertFalse(res['ok'])
        kitguard.freeze(self.root, 'R00', commit='c0ffee1')                                # a conflicting re-freeze must not write a U1 either
        after = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        self.assertEqual(before, after)
        self.assertFalse((self.root / 'wfkit' / 'u1').exists())

    def test_refreeze_only_adds_and_refuses_on_a_conflict(self):
        write(self.root / 'tests' / 'test_c.py', 'THREE = 3\n')
        cfg_path = self.root / 'wfkit' / 'testcases.json'
        cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        cfg['releases']['R00']['testcases']['TC'] = {'kind': 'unittest', 'modules': ['tests.test_c']}
        write(cfg_path, json.dumps(cfg, indent=1))
        res = kitguard.freeze(self.root, 'R00', commit='c0ffee2')
        self.assertTrue(res['ok'], res)
        self.assertIn('tests/test_c.py', res['added'])
        self.assertNotIn('tests/test_a.py', res['added'])                                 # existing pins untouched
        m = json.loads((self.root / 'wfkit' / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(m['releases']['R00']['pins']['tests/test_a.py']['commit'], 'c0ffee0')
        write(self.root / 'tests' / 'test_a.py', 'drifted\n')
        res = kitguard.freeze(self.root, 'R00', commit='c0ffee3')
        self.assertFalse(res['ok'])                                                       # will not re-pin a drifted file
        m2 = json.loads((self.root / 'wfkit' / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(m2['releases']['R00']['pins']['tests/test_a.py']['sha256'], sha('ONE = 1\n'))

    def test_a_second_release_pins_only_new_files_and_an_unfrozen_release_is_refused(self):
        write(self.root / 'tests' / 'test_r1.py', 'R1 = 1\n')
        cfg_path = self.root / 'wfkit' / 'testcases.json'
        cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        cfg['releases']['R01'] = {'testcases': {'T50a': {'kind': 'unittest', 'modules': ['tests.test_r1', 'tests.test_a']}}}
        write(cfg_path, json.dumps(cfg, indent=1))
        self.assertTrue(kitguard.verify(self.root, ['R00'])['ok'])
        res = kitguard.verify(self.root, ['R01'])
        self.assertEqual(self._codes(res), ['not-frozen'])
        fr = kitguard.freeze(self.root, 'R01', commit='c0ffee4')
        self.assertTrue(fr['ok'], fr)
        self.assertIn('tests/test_r1.py', fr['added'])
        self.assertNotIn('tests/test_a.py', fr['added'])                                  # already owned by R00
        self.assertTrue(kitguard.verify(self.root, ['R01'])['ok'])
        write(self.root / 'tests' / 'test_r1.py', 'R1 = 2\n')
        self.assertFalse(kitguard.verify(self.root, ['R01'])['ok'])
        self.assertFalse(kitguard.verify(self.root, ['R00'])['ok'])                       # every frozen release is checked

    def test_removing_a_pin_from_the_manifest_is_a_weakening_when_git_knows_the_old_one(self):
        if subprocess.run(['git', '--version'], capture_output=True).returncode != 0:
            self.skipTest('git required')
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
        run = lambda *a: subprocess.run(['git', *a], cwd=self.root, env=env, capture_output=True, text=True, check=True)
        run('init', '-q'); run('add', '-A'); run('commit', '-q', '-m', 'frozen')
        self.assertTrue(kitguard.verify(self.root)['ok'])
        mp = self.root / 'wfkit' / 'manifest.json'
        m = json.loads(mp.read_text(encoding='utf-8'))
        del m['releases']['R00']['pins']['tests/test_b.py']                               # delete the pin (not the file)
        write(mp, json.dumps(m, indent=1))
        res = kitguard.verify(self.root)
        self.assertFalse(res['ok'])
        self.assertIn('pin-removed', self._codes(res))
        m = json.loads(run('show', 'HEAD:wfkit/manifest.json').stdout)
        m['releases']['R00']['pins']['tests/test_a.py']['sha256'] = sha('a different hash\n')   # rewrite a pin to match a weakened file
        write(mp, json.dumps(m, indent=1))
        write(self.root / 'tests' / 'test_a.py', 'a different hash\n')
        self.assertIn('pin-rewritten', self._codes(kitguard.verify(self.root)))

    def test_cli_freeze_and_verify_exit_codes(self):
        shutil.rmtree(self.root / 'wfkit' / 'manifest.json', ignore_errors=True)
        (self.root / 'wfkit' / 'manifest.json').unlink()
        r = subprocess.run([sys.executable, str(REPO / 'wfkit' / 'kitguard.py'), '--root', str(self.root), 'freeze', 'R00'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([sys.executable, str(REPO / 'wfkit' / 'kitguard.py'), '--root', str(self.root), 'verify'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        write(self.root / 'tests' / 'test_a.py', 'changed\n')
        r = subprocess.run([sys.executable, str(REPO / 'wfkit' / 'kitguard.py'), '--root', str(self.root), 'verify'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('tests/test_a.py', r.stdout)


# --------------------------------------------------------------------------------------------------------------------
# the delivery gate rule (T45a) — SIMULATED receipts: they prove the RULE only
# --------------------------------------------------------------------------------------------------------------------

W1 = 'a1' * 32          # the wheel hash the gate built
W2 = 'b2' * 32          # a different build
COMMIT = '1234567890abcdef1234567890abcdef12345678'
CONFIG = {'version': 1, 'releases': {
    'R00': {'testcases': {'T33a': {'kind': 'unittest', 'modules': ['tests.test_wf_packaging']},
                          'T13b': {'kind': 'unittest', 'modules': ['tests.test_wf_rollback']},
                          'T49b': {'kind': 'unittest', 'modules': ['tests.test_wf_rollback']}}},
    'R01': {'testcases': {'T33b': {'kind': 'unittest', 'modules': ['tests.test_wf_r01']}}}}}


def receipt(testcase, *, release='R00', commit=COMMIT, wheel=W1, run=4, passed=4, errors=0, skipped=0, result='pass', **more):
    r = {'testcase': testcase, 'release': release, 'commit': commit, 'wheel_sha256': wheel, 'command': 'python -m unittest tests.test_x',
         'tests_run': run, 'tests_passed': passed, 'tests_errors': errors, 'tests_skipped': skipped, 'result': result,
         'at': '2026-10-24T00:00:00Z', 'simulated': True}
    r.update(more)
    return r


def good_state():
    build = {'release': 'R00', 'commit': COMMIT, 'dirty': [], 'wheel_sha256': W1, 'wheel': 'onecrew.whl'}
    receipts = {t: receipt(t) for t in ('T33a', 'T13b', 'T49b')}
    install = {'ok': True, 'problems': [], 'control_refused': True, 'wheel_sha256': W1}
    kit = {'ok': True, 'problems': [], 'u1_used': [], 'manifest_sha256': 'm' * 64}
    return build, receipts, install, kit


def decide(build, receipts, install, kit, release='R00', config=None):
    return gate.decide(release, config or CONFIG, build, receipts, install, kit, allow_simulated=True)


def reasons(dec, code=None):
    rs = dec['reasons']
    return [r for r in rs if code is None or r['code'] == code]


class GateRuleTests(unittest.TestCase):
    """T45a [E1]: the R00 trial is delivered only with the T33a, T13b and T49b receipts of the SAME build; [E5]/[E7] below."""

    def test_all_three_receipts_with_the_same_hash_pass(self):
        dec = decide(*good_state())
        self.assertEqual(dec['decision'], 'pass', dec['reasons'])
        self.assertEqual(dec['reasons'], [])
        self.assertTrue(dec['simulated_receipts_used'])                                   # said out loud: it proves the rule only

    def test_missing_t33a_receipt_is_refused_and_named(self):
        build, receipts, install, kit = good_state()
        del receipts['T33a']
        dec = decide(build, receipts, install, kit)
        self.assertEqual(dec['decision'], 'refused')
        rs = reasons(dec, 'missing-receipt')
        self.assertEqual([r['testcase'] for r in rs], ['T33a'])

    def test_t13b_or_t49b_from_another_build_is_refused_naming_both_hashes(self):
        for tc in ('T13b', 'T49b'):
            build, receipts, install, kit = good_state()
            receipts[tc] = receipt(tc, wheel=W2)
            dec = decide(build, receipts, install, kit)
            self.assertEqual(dec['decision'], 'refused', tc)
            rs = reasons(dec, 'wheel-hash')
            self.assertEqual([r['testcase'] for r in rs], [tc])
            self.assertIn(W1, rs[0]['detail'])
            self.assertIn(W2, rs[0]['detail'])

    def test_a_receipt_that_is_present_but_not_pass_is_refused(self):
        for bad in (dict(result='fail', passed=3, errors=1), dict(result='error', run=0, passed=0),
                    dict(result='pass', passed=3, errors=1),                                   # says pass but counts disagree
                    dict(result='pass', run=0, passed=0),                                      # ran nothing
                    dict(result='pass', run=4, passed=1, skipped=3)):                          # everything skipped is not a pass
            build, receipts, install, kit = good_state()
            receipts['T13b'] = receipt('T13b', **bad)
            dec = decide(build, receipts, install, kit)
            self.assertEqual(dec['decision'], 'refused', bad)
            self.assertEqual([r['testcase'] for r in reasons(dec, 'not-pass')], ['T13b'], bad)

    def test_a_skip_is_allowed_only_when_the_testcase_says_so(self):
        cfg = copy.deepcopy(CONFIG)
        build, receipts, install, kit = good_state()
        receipts['T33a'] = receipt('T33a', run=5, passed=4, skipped=1)
        self.assertEqual(decide(build, receipts, install, kit, config=cfg)['decision'], 'refused')
        cfg['releases']['R00']['testcases']['T33a']['allow_skips'] = 1
        self.assertEqual(decide(build, receipts, install, kit, config=cfg)['decision'], 'pass')

    def test_receipt_of_another_release_or_commit_is_not_accepted(self):
        build, receipts, install, kit = good_state()
        receipts['T49b'] = receipt('T49b', release='R01')
        dec = decide(build, receipts, install, kit)
        self.assertEqual(dec['decision'], 'refused')
        self.assertEqual([r['testcase'] for r in reasons(dec, 'missing-receipt')], ['T49b'])
        build, receipts, install, kit = good_state()
        receipts['T49b'] = receipt('T49b', commit='f' * 40)
        dec = decide(build, receipts, install, kit)
        self.assertEqual([r['testcase'] for r in reasons(dec, 'commit')], ['T49b'])

    def test_a_test_that_used_another_wheel_than_the_gate_wheel_is_refused(self):
        build, receipts, install, kit = good_state()
        receipts['T33a'] = receipt('T33a', wheel_used=[W2])
        dec = decide(build, receipts, install, kit)
        self.assertEqual(dec['decision'], 'refused')
        self.assertEqual([r['testcase'] for r in reasons(dec, 'wheel-hash')], ['T33a'])
        build, receipts, install, kit = good_state()
        receipts['T33a'] = receipt('T33a', wheel_used=[W1])
        self.assertEqual(decide(build, receipts, install, kit)['decision'], 'pass')

    def test_the_gate_does_not_ask_for_a_later_release(self):
        build, receipts, install, kit = good_state()
        # R01 (T33b) has no receipt; the R00 gate must not care ([E1]: Cổng không đòi kết quả của release sau)
        dec = decide(build, receipts, install, kit, release='R00')
        self.assertEqual(dec['decision'], 'pass')
        self.assertNotIn('T33b', json.dumps(dec['reasons']))

    def test_kit_guard_failure_is_refused_with_its_problem(self):
        build, receipts, install, kit = good_state()
        kit = {'ok': False, 'problems': [{'code': 'changed', 'pin': 'tests/test_wf_packaging.py'}], 'u1_used': [], 'manifest_sha256': 'm'}
        dec = decide(build, receipts, install, kit)
        self.assertEqual(dec['decision'], 'refused')
        self.assertIn('tests/test_wf_packaging.py', json.dumps(reasons(dec, 'kit-guard')))

    def test_a_valid_u1_is_written_into_the_decision(self):
        build, receipts, install, kit = good_state()
        kit['u1_used'] = [{'id': 'U1-001', 'file': 'tests/test_a.py', 'old_sha256': 'x', 'new_sha256': 'y', 'reason': 'r'}]
        dec = decide(build, receipts, install, kit)
        self.assertEqual(dec['decision'], 'pass')
        self.assertEqual([r['id'] for r in dec['u1_used']], ['U1-001'])

    def test_a_dirty_tree_is_refused(self):
        build, receipts, install, kit = good_state()
        build['dirty'] = [' M onecrew/v2/plan.py']
        dec = decide(build, receipts, install, kit)
        self.assertEqual(dec['decision'], 'refused')
        self.assertTrue(reasons(dec, 'dirty'))

    def test_simulated_receipts_are_refused_by_a_real_gate(self):
        build, receipts, install, kit = good_state()
        dec = gate.decide('R00', CONFIG, build, receipts, install, kit)                    # allow_simulated defaults to False
        self.assertEqual(dec['decision'], 'refused')
        self.assertTrue(reasons(dec, 'simulated-receipt'))

    def test_install_origin_failure_is_refused(self):
        build, receipts, install, kit = good_state()
        install = {'ok': False, 'problems': ['onecrew.v2.plan loaded from the checkout'], 'control_refused': True}
        dec = decide(build, receipts, install, kit)
        self.assertEqual(dec['decision'], 'refused')
        self.assertTrue(reasons(dec, 'run-from-checkout'))
        build, receipts, install, kit = good_state()
        install['control_refused'] = False                                                # the check cannot tell checkout from install
        self.assertEqual(decide(build, receipts, install, kit)['decision'], 'refused')
        build, receipts, install, kit = good_state()
        install['wheel_sha256'] = W2                                                      # the installed wheel is not the gate's wheel
        self.assertEqual(decide(build, receipts, install, kit)['decision'], 'refused')

    def test_judge_origin_installed_vs_checkout_paths(self):
        site = ['C:/venv/Lib/site-packages']
        checkout = 'D:/work/repo'
        ok = {'modules': {'onecrew': 'C:/venv/Lib/site-packages/onecrew/__init__.py',
                          'onecrew.v2.plan': 'C:/venv/Lib/site-packages/onecrew/v2/plan.py'}, 'site': site}
        self.assertEqual(gate.judge_origin(ok, checkout), [])
        bad = copy.deepcopy(ok)
        bad['modules']['onecrew.v2.plan'] = 'D:/work/repo/onecrew/v2/plan.py'
        probs = gate.judge_origin(bad, checkout)
        self.assertTrue(any('onecrew.v2.plan loaded from the checkout' in p for p in probs), probs)
        self.assertTrue(gate.judge_origin({'modules': {}, 'site': site}, checkout))        # nothing loaded: not an install scenario
        elsewhere = {'modules': {'onecrew': 'E:/somewhere/onecrew/__init__.py'}, 'site': site}
        self.assertTrue(gate.judge_origin(elsewhere, checkout))                            # not under the installed site-packages either

    def test_cli_decide_only_on_receipts_in_a_directory(self):
        root = _tmp()
        try:
            write(root / 'wfkit' / 'testcases.json', json.dumps(CONFIG))
            for mod in ('test_wf_packaging', 'test_wf_rollback'):
                write(root / 'tests' / (mod + '.py'), 'X = 1' + chr(10))
            self.assertTrue(kitguard.freeze(root, 'R00', commit='c0ffee0')['ok'])
            out = root / 'out'
            build, receipts, install, kit = good_state()
            write(out / 'build.json', json.dumps(build))
            write(out / 'install-scenario.json', json.dumps(install))
            for t, r in receipts.items():
                write(out / 'receipts' / (t + '.json'), json.dumps(r))
            code = gate.main(['R00', '--out', str(out), '--root', str(root), '--decide-only', '--allow-simulated'])
            self.assertEqual(code, 0)
            dec = json.loads((out / 'decision.json').read_text(encoding='utf-8'))
            self.assertEqual(dec['decision'], 'pass')
            (out / 'receipts' / 'T33a.json').unlink()
            self.assertEqual(gate.main(['R00', '--out', str(out), '--root', str(root), '--decide-only', '--allow-simulated']), 1)
            dec = json.loads((out / 'decision.json').read_text(encoding='utf-8'))
            self.assertEqual(dec['decision'], 'refused')
            self.assertEqual(reasons(dec, 'missing-receipt')[0]['testcase'], 'T33a')
        finally:
            shutil.rmtree(root, ignore_errors=True)


class GateConfigTests(unittest.TestCase):
    """The real testcases.json: R00 maps the testcases of docs/wf/R00-DONE.md to their test modules."""

    def test_r00_testcase_map(self):
        cfg = json.loads((REPO / 'wfkit' / 'testcases.json').read_text(encoding='utf-8'))
        tcs = cfg['releases']['R00']['testcases']
        expect = {'T20': 'tests.test_wf_decisions', 'T13a': 'tests.test_wf_events', 'T49a': 'tests.test_wf_compat_scan',
                  'T48a': 'tests.test_wf_plan_names', 'T09a': 'tests.test_wf_advisor_errors', 'T33a': 'tests.test_wf_packaging',
                  'T13b': 'tests.test_wf_rollback', 'T49b': 'tests.test_wf_rollback'}
        for tc, mod in expect.items():
            self.assertEqual(tcs[tc]['modules'], [mod], tc)
            self.assertTrue((REPO / (mod.replace('.', '/') + '.py')).is_file(), mod)
        self.assertIn('T45a', tcs)
        self.assertEqual(tcs['T38a']['kind'], 'doccheck')
        for tc in tcs.values():
            self.assertFalse(tc.get('optional'), 'every R00 testcase is required')


# --------------------------------------------------------------------------------------------------------------------
# the wheel handed to tests (WF_WHEEL) and the REAL install-origin scenario ([E5], [E7])
# --------------------------------------------------------------------------------------------------------------------

class InstallOriginRealTests(unittest.TestCase):
    """REAL: hand-built wheel, offline install into a fresh venv, the scenario run from the INSTALLED command and from the checkout."""

    @classmethod
    def setUpClass(cls):
        cls.runs = _tmp()
        cls.whl, cls.version, _ = wh.build_wheel(cls.runs)                                 # honours WF_WHEEL when the gate ran us
        cls.py = wh.make_venv(cls.runs)
        wh.install(cls.py, cls.whl)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_installed_scenario_loads_only_installed_onecrew_modules(self):
        rep = gate.install_scenario(self.py, cwd=self.runs)
        self.assertTrue(rep['modules'], rep)
        self.assertEqual(gate.judge_origin(rep, str(REPO)), [], rep)
        for name, path in rep['modules'].items():
            self.assertIn('site-packages', path.replace('\\', '/'), name)                  # the real loaded path is recorded

    def test_scenario_run_from_the_checkout_is_refused(self):
        rep = gate.install_scenario(self.py, cwd=self.runs, flags=(), env_extra={'PYTHONPATH': str(REPO)})
        probs = gate.judge_origin(rep, str(REPO))
        self.assertTrue(probs, rep)
        self.assertTrue(any('loaded from the checkout' in p for p in probs), probs)
        loaded = [path for path in rep['modules'].values() if path]
        self.assertTrue(loaded and all(str(REPO).lower() in path.lower() for path in loaded), loaded)   # the recorded REAL path is the checkout's

    def test_check_install_gives_ok_and_a_refused_control(self):
        res = gate.check_install(self.py, str(REPO), self.runs)
        self.assertTrue(res['ok'], res)
        self.assertTrue(res['control_refused'], res)                                       # the control run from the checkout WAS refused
        self.assertTrue(res['loaded'])

    def test_wf_wheel_reuses_the_gate_wheel_and_logs_its_hash(self):
        runs2 = _tmp()
        try:
            digest = hashlib.sha256(self.whl.read_bytes()).hexdigest()
            log = runs2 / 'used.log'
            env_keep = {k: os.environ.get(k) for k in ('WF_WHEEL', 'WF_WHEEL_SHA256', 'WF_WHEEL_USED_LOG')}
            os.environ.update({'WF_WHEEL': str(self.whl), 'WF_WHEEL_SHA256': digest, 'WF_WHEEL_USED_LOG': str(log)})
            try:
                got, version, (mods, pkgs) = wh.build_wheel(runs2)
                self.assertEqual(hashlib.sha256(Path(got).read_bytes()).hexdigest(), digest)   # NOT rebuilt: same bytes
                self.assertEqual(version, self.version)
                self.assertTrue(mods)
                self.assertEqual(log.read_text(encoding='utf-8').split(), [digest])
                os.environ['WF_WHEEL_SHA256'] = '0' * 64                                   # a wheel that is not the one the gate hashed
                with self.assertRaises(RuntimeError):
                    wh.build_wheel(runs2)
            finally:
                for k, v in env_keep.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        finally:
            shutil.rmtree(runs2, ignore_errors=True)

    def test_without_wf_wheel_it_still_builds(self):
        keep = {k: os.environ.pop(k, None) for k in ('WF_WHEEL', 'WF_WHEEL_SHA256', 'WF_WHEEL_USED_LOG')}   # the gate sets all three
        try:
            runs2 = _tmp()
            got, version, _ = wh.build_wheel(runs2)
            self.assertTrue(Path(got).is_file())
            shutil.rmtree(runs2, ignore_errors=True)
        finally:
            for k, v in keep.items():
                if v is not None:
                    os.environ[k] = v


# --------------------------------------------------------------------------------------------------------------------
# T38a — the embedded document self-check run as a kit command, through kit-guard (FAKE document directory)
# --------------------------------------------------------------------------------------------------------------------

def fake_doc(root, *, problems=0, lines=None, extra_block=False, write_file=False, exit_code=0, header='# wf-doc-check v3'):
    """A small stand-in for the workflow-chung folder: a 06 document whose section 7 holds ONE python block with canned output."""
    lines = lines if lines is not None else ['  BẮT           K-LINK    một phản chứng', '  BẮT           K-ID      hai', '  ĐÚNG          không báo  đối chứng']
    body = [header,
            'import os, sys',
            "print('wf-doc-check v3')",
            "print('PROBLEMS: %d')" % problems,
            "print('phản chứng và đối chứng:')"]
    body += ["print(%r)" % ln for ln in lines]
    n_caught = sum(1 for ln in lines if ln.strip().startswith('BẮT') and 'SAI' not in ln)
    n_total = sum(1 for ln in lines if 'không báo' not in ln and not ln.strip().startswith('KHÔNG'))
    body += ["print('phản chứng bị bắt đúng lý do: %d/%d; đối chứng không bị báo: 1/1')" % (n_caught, n_total)]
    if write_file:
        body += ["open(os.path.join(os.getcwd(), 'written-by-checker.txt'), 'w').write('x')"]
    body += ['sys.exit(%d)' % exit_code]
    block = '\n'.join(body) + '\n'
    doc = ['# 06 — fake', '', '## 6. Not this one', '', FENCE + 'python', 'print("NOT THE BLOCK")', FENCE, '',
           '## 7. Phụ lục tái lập bộ tự kiểm', '', 'Hash: see manifest.', '', FENCE + 'python', block + FENCE, '']
    if extra_block:
        doc += [FENCE + 'python', 'print("second block")', FENCE, '']
    write(root / '06-TRUY-VET-VA-TU-KIEM.vi.md', '\n'.join(doc))
    write(root / '00-other.md', 'other\n')
    return block


class DocCheckTests(unittest.TestCase):
    """T38a: the self-check of 06 section 7 is a kit command: PROBLEMS: 0, every counterexample caught, through kit-guard, hash in the receipt."""

    def setUp(self):
        self.base = _tmp()
        self.docs = self.base / 'workflow-chung'
        self.docs.mkdir()
        self.kit = self.base / 'kit'
        make_kit(self.kit)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def _register(self, block):
        """Register the block hash with kit-guard the way `freeze --doc-dir` does."""
        res = kitguard.freeze(self.kit, 'R00', commit='c0ffee0', doc_dir=self.docs)
        self.assertTrue(res['ok'], res)
        self.assertIn('doc:wf-doc-check', res['added'])
        return res

    def _run(self):
        return doccheck.run(self.docs, self.kit)

    def test_clean_run_passes_and_the_receipt_carries_the_block_hash(self):
        block = fake_doc(self.docs)
        self._register(block)
        rec = self._run()
        self.assertEqual(rec['result'], 'pass', rec)
        self.assertEqual(rec['testcase'], 'T38a')
        self.assertEqual(rec['block_sha256'], sha(block))
        self.assertEqual(rec['problems'], 0)
        self.assertEqual(rec['counterexamples']['missed'], [])
        self.assertEqual(rec['counterexamples']['caught'], 2)
        self.assertTrue(rec['kit_guard']['ok'])
        self.assertIn('PROBLEMS: 0', rec['command'] + rec['output_tail'])

    def test_problems_above_zero_fail(self):
        block = fake_doc(self.docs, problems=2)
        self._register(block)
        rec = self._run()
        self.assertEqual(rec['result'], 'fail')
        self.assertEqual(rec['problems'], 2)

    def test_a_counterexample_that_slips_through_fails(self):
        block = fake_doc(self.docs, lines=['  BẮT           K-LINK    một', '  LỌT           K-ID      hai', '  ĐÚNG          không báo  đối chứng'])
        self._register(block)
        rec = self._run()
        self.assertEqual(rec['result'], 'fail')
        self.assertEqual(len(rec['counterexamples']['missed']), 1)
        self.assertIn('K-ID', rec['counterexamples']['missed'][0])

    def test_caught_for_the_wrong_reason_and_unapplicable_are_reported_separately(self):
        block = fake_doc(self.docs, lines=['  BẮT           K-LINK    một', '  BẮT SAI LÝ DO K-ID      hai', '  KHÔNG ÁP ĐƯỢC —         ba lý do', '  ĐÚNG          không báo  đối chứng'])
        self._register(block)
        rec = self._run()
        self.assertEqual(rec['result'], 'fail')                                              # wrong reason is not "caught"
        self.assertEqual(len(rec['counterexamples']['wrong_reason']), 1)
        self.assertEqual(len(rec['counterexamples']['not_applicable']), 1)

    def test_no_counterexample_section_at_all_fails(self):
        block = fake_doc(self.docs, lines=[])
        self._register(block)
        rec = self._run()
        self.assertEqual(rec['result'], 'fail')                                              # an empty counterexample run proves nothing

    def test_unregistered_or_changed_block_is_refused_by_kit_guard(self):
        block = fake_doc(self.docs)
        rec = self._run()                                                                    # never registered
        self.assertEqual(rec['result'], 'refused', rec)
        self._register(block)
        self.assertEqual(self._run()['result'], 'pass')
        fake_doc(self.docs, lines=['  BẮT           K-LINK    một'])                          # the checker was edited after the freeze
        rec = self._run()
        self.assertEqual(rec['result'], 'refused', rec)
        self.assertFalse(rec['kit_guard']['ok'])
        self.assertIn('doc:wf-doc-check', json.dumps(rec['kit_guard']))

    def test_the_section_must_hold_exactly_one_python_block(self):
        block = fake_doc(self.docs, extra_block=True)
        rec = self._run()
        self.assertEqual(rec['result'], 'refused')
        self.assertIn('exactly one', rec['reason'])

    def test_a_checker_that_writes_into_the_document_folder_fails(self):
        block = fake_doc(self.docs, write_file=True)
        self._register(block)
        rec = self._run()
        self.assertEqual(rec['result'], 'fail')
        self.assertIn('written-by-checker.txt', json.dumps(rec['changed_in_doc_dir']))

    def test_nonzero_exit_or_missing_problems_line_fails(self):
        block = fake_doc(self.docs, exit_code=3)
        self._register(block)
        self.assertEqual(self._run()['result'], 'fail')

    def test_missing_doc_dir_is_refused(self):
        rec = doccheck.run(self.base / 'nope', self.kit)
        self.assertEqual(rec['result'], 'refused')

    def test_the_embedded_hash_extraction_matches_the_documented_rule(self):
        block = fake_doc(self.docs)
        got = kitguard.extract_doc_block(self.docs)
        self.assertEqual(got['sha256'], sha(block))
        self.assertEqual(got['count'], 1)


if __name__ == '__main__':
    unittest.main()
