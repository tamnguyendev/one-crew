"""T55a named cases (05-TESTCASES.vi.md, section T55): C1-C9, N0, CK1-CK25, z1-z12.

Each test builds base N0 plus the columns of its case, runs the real evaluators
(wfkit.finalgate.decide/compare/evidence_status/provider_capability and the
shared wfkit.provider_evidence.evaluate) and asserts what the table row says.
Fixture construction is copied from tests/test_wf_finalgate.py (its helpers are
TestCase methods), parameterised per case. All receipts are simulated fixtures.

Status mapping used in assertions (table -> evaluator):
  "dung duoc (B)"           -> status usable, validity direct, evidence hash B
  "dung duoc (A, ke thua)"  -> status usable, validity inherited, evidence hash A, comparison_id
  "chua kiem chung"         -> status unverified
  "can kiem lai"            -> status recheck
  "4 o"/"3 o"/"6 o"         -> eligible cells published identically in T40c/T54i/T40d
  P1.0 "chi phan: X"/"du"   -> T40d label partial with missing X / label full

Counter-examples z1-z12 are faulty evaluators. They are expressed here as the
forbidden result (E8-E14, E19-E23) NOT occurring on the real evaluator for the
cases the evidence column names.

Not expressible:
  CK12 - C8 + "PL-B chua bat dau" expects only KQ3; decide() also refuses KQ4
         (history_check fails on started_at=None, and the C8 pin re-evaluation
         writes KQ4), so the reason set cannot equal the table's {KQ3}.
  CK21 - C7 + "PL-B chua bat dau" expects exactly {KQ3, KQ6}; decide() adds KQ4
         ("timestamp missing" from history_check).
  (C7 note) decide() does not re-evaluate the PL-B entry provider condition when
         KQ6 already fails (the KQ6 require raises first), so C7's "chua dat" at
         the PL-B entry is asserted through provider_capability on A receipts only.
  CK23 - "thieu ma tran T40b" expects only KQ6; decide() also refuses KQ7
         ("provider eligibility unavailable"), so the reason set differs.
  z1-z12 detector reports - the "bao '...', neu ca va o" outputs belong to the
         doc self-check (K-HL/K-KET) run against mutant evaluators; no such
         detector or mutant set exists in code. Only the forbidden-result side
         is asserted.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from wfkit.finalgate import (BASE_ITEMS, CELLS, GATES, Evidence, compare, decide,
                             evidence_status, provider_capability)
from wfkit.provider_evidence import evaluate

CR, XR, KR = 'claude:reviewer', 'codex:reviewer', 'kiro:reviewer'
CA, XA, KA = 'claude:advisor', 'codex:advisor', 'kiro:advisor'
REVIEWERS = [CR, XR, KR]
ADVISORS = [CA, XA, KA]
ADAPTER = 'W43-adapter'

# Inputs of the C1-C9 cell table: (on A, check on B); None = "khong chay".
# 'acct' = "chan: thieu tai khoan" / "chua kiem chung", 'quota' = "chan: het han muc".
P, ACCT, QUOTA = 'pass', 'acct', 'quota'
ALL_PASS_A = {CR: (P, P), XR: (P, P), KR: (P, P), CA: (P, None), XA: (P, None), KA: (P, None)}
CASES = {
    'C1': dict(cells={CR: (P, P), XR: (P, P), KR: (ACCT, ACCT), CA: (P, None), XA: (P, None), KA: (ACCT, None)},
               changed={'reviewer'}, pins=[XR], comparison='valid'),
    'C2': dict(cells={CR: (P, P), XR: (P, QUOTA), KR: (ACCT, None), CA: (P, None), XA: (P, None), KA: (ACCT, None)},
               changed={'reviewer'}, pins=[XR], comparison='valid'),
    'C3': dict(cells=ALL_PASS_A, changed={'reviewer'}, pins=[XR], comparison='valid'),
    'C4': dict(cells=ALL_PASS_A, changed={'reviewer'}, pins=[XR], comparison='missing'),
    'C5': dict(cells=ALL_PASS_A, changed={'reviewer'}, pins=[XR], comparison='wrong_pair'),
    'C6': dict(cells=ALL_PASS_A, changed={'reviewer', 'adapter'}, pins=[XR], comparison='dropped_dependency'),
    'C7': dict(cells={CR: (P, None), XR: (ACCT, None), KR: (P, None), CA: (P, None), XA: (ACCT, None), KA: (ACCT, None)},
               changed={'AC1'}, pins=[], comparison='valid'),
    'C8': dict(cells={CR: (P, P), XR: (P, P), KR: (ACCT, ACCT), CA: (P, None), XA: (P, None), KA: (ACCT, None)},
               changed={'reviewer'}, pins=[XR, KR], comparison='valid'),
    'C9': dict(cells={k: (P, P) for k in CELLS}, changed={'reviewer', 'advisor'}, pins=[XR], comparison='valid'),
}
# Expected "Cho B" column: B=direct, A=inherited, U=unverified, R=recheck.
EXPECTED_CELLS = {
    'C1': {CR: 'B', XR: 'B', KR: 'U', CA: 'A', XA: 'A', KA: 'U'},
    'C2': {CR: 'B', XR: 'R', KR: 'U', CA: 'A', XA: 'A', KA: 'U'},
    'C3': {CR: 'B', XR: 'B', KR: 'B', CA: 'A', XA: 'A', KA: 'A'},
    'C4': {CR: 'B', XR: 'B', KR: 'B', CA: 'R', XA: 'R', KA: 'R'},
    'C5': {CR: 'B', XR: 'B', KR: 'B', CA: 'R', XA: 'R', KA: 'R'},
    'C6': {CR: 'B', XR: 'B', KR: 'B', CA: 'R', XA: 'R', KA: 'R'},
    'C7': {CR: 'A', XR: 'U', KR: 'A', CA: 'A', XA: 'U', KA: 'U'},
    'C8': {CR: 'B', XR: 'B', KR: 'U', CA: 'A', XA: 'A', KA: 'U'},
    'C9': {k: 'B' for k in CELLS},
}
STATUS = {'B': 'usable', 'A': 'usable', 'U': 'unverified', 'R': 'recheck'}
# Provider-condition table: (PL-B entry on A ok, KQ6 ok, subset size, P1.0 missing; [] = "du").
EXPECTED_CONDITIONS = {
    'C1': (True, True, 4, [KR, KA]),
    'C2': (True, False, 3, [XR, KR, KA]),
    'C3': (True, True, 6, []),
    'C4': (True, True, 3, [CA, XA, KA]),
    'C5': (True, True, 3, [CA, XA, KA]),
    'C6': (True, True, 3, [CA, XA, KA]),
    'C7': (False, False, 3, [XR, XA, KA]),
    'C8': (False, True, 4, [KR, KA]),
    'C9': (True, True, 6, []),
}
# "Duong doi A->B" column (true closure), plus AC1 which depends on codex reviewer / owns AC1.py.
TRUE_AFFECTED = {
    'C7': {'AC1'},
    'C6': {'AC1', ADAPTER} | set(REVIEWERS) | set(ADVISORS),
    'C9': {'AC1'} | set(CELLS),
}


class Fixture:
    """Base N0 plus the cell inputs of one C case (copied from test_wf_finalgate)."""

    def __init__(self, root, case):
        self.root, self.case, self.count = Path(root), case, 0
        spec = CASES[case]
        changed = spec['changed']
        base = {'onecrew/reviewer.py': 'old', 'onecrew/advisor.py': 'old'}
        base.update({f'onecrew/{i}.py': 'same' for i in BASE_ITEMS})
        if 'adapter' in changed:
            base['onecrew/provider_adapter.py'] = 'old'
        final = dict(base)
        for name, path in (('reviewer', 'onecrew/reviewer.py'), ('advisor', 'onecrew/advisor.py'),
                           ('AC1', 'onecrew/AC1.py'), ('adapter', 'onecrew/provider_adapter.py')):
            if name in changed:
                final[path] = 'new'
        self.a = self.wheel('a', 'a' * 40, base)
        self.b = self.wheel('b', 'b' * 40, final)
        self.a2 = self.wheel('a2', 'c' * 40, dict(base, **{'onecrew/other.py': "A'"}))  # A' for "sai cap hash"
        self.bundle = self.make_bundle(spec)

    def wheel(self, name, commit, files):
        path = self.root / f'{name}.whl'
        with ZipFile(path, 'w') as archive:
            for member, content in sorted(files.items()):
                archive.writestr(member, content)
        return {'commit': commit, 'wheel_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'wheel': path.name}

    def ref(self, value):
        self.count += 1
        path = self.root / f'r{self.count}.json'
        raw = json.dumps(value, sort_keys=True).encode()
        path.write_bytes(raw)
        return {'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def receipt(self, artifact, **kw):
        value = {k: artifact[k] for k in ('commit', 'wheel_sha256')}
        value.update({'result': 'pass', 'at': '2026-10-24T12:00:00Z', 'simulated': True,
                      'provenance': {'kind': 'fixture', 'source': 'T55a cases'}})
        value.update(kw)
        return self.ref(value)

    def edit(self, ref, **changes):
        value = json.loads((self.root / ref['path']).read_text())
        value.update(changes)
        new = self.ref(value)
        ref.clear()
        ref.update(new)

    def load(self, ref):
        return json.loads((self.root / ref['path']).read_text())

    def item(self, key):
        return next(i for i in self.bundle['comparison']['items'] if i['id'] == key)

    def cell_receipt(self, artifact, info, outcome):
        if outcome == P:
            return self.receipt(artifact, **info, result='pass', reason='')
        reason = 'account unavailable' if outcome == ACCT else 'quota exhausted'
        return self.receipt(artifact, **info, result='blocked', reason=reason)

    def make_bundle(self, spec):
        adapter = 'adapter' in spec['changed']
        items = []
        for key in sorted(BASE_ITEMS):
            items.append({'id': key, 'owned': [f'onecrew/{key}.py'],
                          'depends_on': [XR] if key == 'AC1' else [],
                          'original': self.receipt(self.a, kind='behavior', item=key),
                          'supplements': [self.receipt(self.b, kind='supplement', item=key)] if key == 'AC1' else []})
        if adapter:
            items.append({'id': ADAPTER, 'owned': ['onecrew/provider_adapter.py'], 'depends_on': [],
                          'original': self.receipt(self.a, kind='behavior', item=ADAPTER),
                          'supplements': [self.receipt(self.b, kind='supplement', item=ADAPTER)]})
        rows = []
        expected = EXPECTED_CELLS[self.case]
        for key in sorted(CELLS):
            provider, role = key.split(':')
            on_a, on_b = spec['cells'][key]
            info = {'item': key, 'provider': provider, 'role': role, 'model': 'model-' + provider,
                    'vendor': 'OpenAI' if provider == 'codex' else 'Anthropic', 'kind': 'behavior'}
            info['cli_identity'] = {'provider': provider, 'path': f'{provider}.exe', 'argv': [f'{provider}.exe'],
                                    'sha256': '1' * 64, 'files': {f'{provider}.exe': '1' * 64}, 'version': 'fixture-1'}
            original = self.cell_receipt(self.a, info, on_a)
            extra = [self.cell_receipt(self.b, info, on_b)] if on_b else []
            # C6: the advisor depends on the shared provider adapter file created by W43.
            depends = [ADAPTER] if adapter and role == 'advisor' else []
            items.append({'id': key, 'owned': [f'onecrew/{role}.py'], 'depends_on': depends, 'original': original, 'supplements': extra})
            rows.append({k: info[k] for k in ('provider', 'role', 'model', 'vendor')} | {
                'id': key, 'cli_sha256': '1' * 64, 'cli_files': copy.deepcopy(info['cli_identity']['files']),
                'status': STATUS[expected[key]]})
        gates = {}
        for name in GATES:
            gates[name] = {'receipt': self.receipt(self.b, gate=name, manifest_sha256='c' * 64),
                           'doccheck': self.receipt(self.b, testcase='T38a', problems=0, kit_guard={'ok': True, 'manifest_sha256': 'c' * 64},
                                                  manifest_sha256='c' * 64, block_sha256='d' * 64,
                                                  command=['python', '-m', 'wfkit.kitguard', 'doccheck']),
                           'evidence': [{'item': 'AC1', 'receipt': items[0]['supplements'][0], 'validity': 'direct'}]}
        phases = {}
        for name, entry, completion, start, finish in (
                ('PL-A', 'T45b', ['T35b'], '10:00:00', '11:00:00'),
                ('PL-B', 'T45c', ['T35c', 'T14c'], '13:00:00', '14:00:00')):
            phases[name] = {'artifact': self.a, 'started_at': f'2026-10-23T{start}Z', 'completed_at': f'2026-10-23T{finish}Z',
                'entry': self.receipt(self.a, testcase=entry, at='2026-10-23T09:00:00Z'),
                'releases': {g: self.receipt(self.a, gate=g, at='2026-10-23T08:00:00Z') for g in GATES},
                'completion': {t: self.receipt(self.a, kind='pilot', testcase=t, at='2026-10-23T12:00:00Z' if name == 'PL-A' else '2026-10-23T15:00:00Z') for t in completion},
                'pinned_cells': list(spec['pins']), 'author_vendor': 'Anthropic'}
        eligible = sorted(k for k, v in expected.items() if v in 'AB')
        label = 'full' if len(eligible) == len(CELLS) else 'partial'
        affected = TRUE_AFFECTED.get(self.case, {'AC1'} | set(REVIEWERS))
        claimed = set(affected)
        if spec['comparison'] == 'dropped_dependency':
            # "doi chieu chi xet file chinh cua muc, nen ghi khong doi du closure co doi"
            claimed -= set(ADVISORS)
        comparison = {'id': 'comparison-A-B', 'source': self.a, 'target': self.b,
                      'mapping': self.receipt(self.a, kind='impact-map', tasks=[{k: copy.deepcopy(i[k]) for k in ('id', 'owned', 'depends_on')} for i in items]),
                      'changed_files': sorted(p for p in ('onecrew/reviewer.py', 'onecrew/advisor.py', 'onecrew/AC1.py', 'onecrew/provider_adapter.py')
                                              if p.split('/')[1].split('.')[0].replace('provider_', '') in spec['changed']),
                      'affected': sorted(claimed), 'items': items}
        self.true_affected = affected
        if spec['comparison'] == 'missing':
            # No comparison record: only the evidence index (items) remains.
            comparison = {'items': items}
        elif spec['comparison'] == 'wrong_pair':
            comparison['source'] = self.a2  # comparison of A'->B
        return {'schema': 1, 'mode': 'fixture', 'artifacts': {'pilot': self.a, 'final': self.b},
                'comparison': comparison, 'gates': gates, 'phases': phases, 'author_vendor': 'Anthropic', 'providers': rows,
                'monitored_files': [{'path': '.claude/hooks.json', 'before_sha256': 'e' * 64, 'after_sha256': 'e' * 64}],
                'publications': {p: {'cells': list(eligible), 'missing': sorted(CELLS - set(eligible)), 'label': label}
                                 for p in ('T40c', 'T54i', 'T40d')}}

    def run(self):
        return decide(self.bundle, self.root, allow_simulated=True)

    def shared_states(self):
        """The shared evaluator as the gate wires it: structural proof or none."""
        ev = Evidence(self.root, True)
        try:
            proof = compare(self.bundle, ev)
        except (ValueError, KeyError, TypeError):
            proof = None
        return proof, evaluate(self.bundle['providers'], self.bundle['comparison']['items'], ev, self.a, self.b, proof)

    def entry_capability(self):
        """Provider condition at the PL-B entry gate, from direct A receipts."""
        ev = Evidence(self.root, True)
        originals = {k: evidence_status(ev.read(self.item(k)['original']), [], self.a) for k in CELLS}
        phase = self.bundle['phases']['PL-B']
        return provider_capability(self.bundle['providers'], originals, phase['author_vendor'], phase['pinned_cells'])


# --- CK mutations: N0 + "khac nen" columns -----------------------------------------
def _ck4(f):
    del f.bundle['gates']['CG-R07']                      # "CG-R07: thieu"


def _ck5(f):
    f.edit(f.bundle['gates']['CG-R06']['receipt'], commit=f.a['commit'], wheel_sha256=f.a['wheel_sha256'])  # "CG-R06: hash A"


def _ck6(f):
    f.edit(f.bundle['gates']['KN-R03-R04']['receipt'], result='fail')  # "KN-R03-R04: khong dat"


def _ck10(f):
    f.item('AC1')['supplements'] = []                    # "muc bi anh huong thieu kiem bo sung"


def _ck11(f):
    f.edit(f.item('AC2')['original'], commit=f.b['commit'], wheel_sha256=f.b['wheel_sha256'])  # "doi hash bang chung sang B"


def _ck13(f):
    f.edit(f.bundle['phases']['PL-B']['entry'], result='refused')  # "PL-B bat dau du cong vao tu choi"


def _ck14(f):
    del f.bundle['phases']['PL-B']['completion']['T35c']  # "thieu bien nhan T35c"


def _ck15(f):
    f.edit(f.bundle['phases']['PL-B']['entry'], at='2026-10-23T13:30:00Z')  # entry passed after start 13:00


def _ck16(f):
    for ref in f.bundle['phases']['PL-B']['releases'].values():  # delivery gates on A', PL-B ran on A
        f.edit(ref, commit=f.a2['commit'], wheel_sha256=f.a2['wheel_sha256'])


def _ck17(f):
    f.bundle['monitored_files'][0]['after_sha256'] = 'f' * 64  # "doi khong co U2"


def _ck19(f):
    for name in ('T40c', 'T54i'):                         # "them kiro reviewer"
        f.bundle['publications'][name]['cells'].append(KR)


def _ck20(f):
    f.bundle['publications']['T40d']['label'] = 'full'   # "P1.0 ghi du"


def _ck22(f):
    f.bundle['phases']['PL-B']['completed_at'] = None    # "chua hoan thanh"


def _ck24(f):
    f.edit(f.bundle['gates']['CG-R03']['doccheck'], command=[])  # "CG-R03: thieu lenh bo tu kiem"


def _ck25(f):
    f.edit(f.bundle['phases']['PL-A']['entry'], at='2026-10-23T10:30:00Z')  # PL-A start 10:00


def _none(f):
    pass


# CK: (cell case, mutation, expected refusal codes; empty = "cho qua")
CK = {
    'CK1': ('C9', _none, set()), 'CK2': ('C1', _none, set()), 'CK3': ('C3', _none, set()),
    'CK4': ('C1', _ck4, {'KQ1'}), 'CK5': ('C1', _ck5, {'KQ1'}), 'CK6': ('C1', _ck6, {'KQ1'}),
    'CK7': ('C4', _none, {'KQ2'}), 'CK8': ('C5', _none, {'KQ2'}), 'CK9': ('C6', _none, {'KQ2'}),
    'CK10': ('C1', _ck10, {'KQ2'}), 'CK11': ('C1', _ck11, {'KQ2'}),
    'CK13': ('C8', _ck13, {'KQ4'}), 'CK14': ('C1', _ck14, {'KQ3'}), 'CK15': ('C1', _ck15, {'KQ4'}),
    'CK16': ('C1', _ck16, {'KQ4'}), 'CK17': ('C1', _ck17, {'KQ5'}), 'CK18': ('C2', _none, {'KQ6'}),
    'CK19': ('C1', _ck19, {'KQ7'}), 'CK20': ('C1', _ck20, {'KQ7'}), 'CK22': ('C1', _ck22, {'KQ3'}),
    'CK24': ('C1', _ck24, {'KQ1'}), 'CK25': ('C1', _ck25, {'KQ4'}),
}


class T55CaseTests(unittest.TestCase):
    def fixture(self, case):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Fixture(tmp.name, case)

    # --- C1-C9: cell table + provider-condition table ---------------------------------
    def check_cell_case(self, case):
        f = self.fixture(case)
        proof, states = f.shared_states()
        expected = EXPECTED_CELLS[case]
        for key, code in expected.items():
            state = states[key]
            self.assertEqual(STATUS[code], state['status'], (case, key, state))
            if code == 'B':
                self.assertEqual('direct', state['validity'])
                self.assertEqual(f.b['wheel_sha256'], state['evidence']['wheel_sha256'])
            if code == 'A':
                self.assertEqual('inherited', state['validity'])
                self.assertEqual(f.a['wheel_sha256'], state['evidence']['wheel_sha256'])
                self.assertEqual('comparison-A-B', state['comparison_id'])
        entry_ok, final_ok, size, missing = EXPECTED_CONDITIONS[case]
        entry = f.entry_capability()
        self.assertEqual(entry_ok, entry['ok'], (case, entry))
        final = provider_capability(f.bundle['providers'], states, f.bundle['author_vendor'])
        self.assertEqual(final_ok, final['ok'], (case, final))
        self.assertEqual(size, len(final['eligible']))
        self.assertEqual(sorted(CELLS - set(missing)), final['eligible'])
        # Same evaluation at the final gate; published T40c/T54i/T40d set equals it (KQ7).
        result = f.run()
        self.assertEqual(states, result['provider_states'])
        self.assertTrue(result['conditions']['KQ7'], result)
        self.assertEqual(final_ok, result['conditions']['KQ6'], result)
        self.assertEqual(sorted(missing), f.bundle['publications']['T40d']['missing'])
        self.assertEqual('full' if not missing else 'partial', f.bundle['publications']['T40d']['label'])
        return f, proof, states, entry, final, result

    def test_c1_partial_valid_kiro_unverified_does_not_block(self):
        # C1 | chi phan hop le | codex reviewer | dat | 4 o | dat | chi phan: kiro reviewer, kiro co van
        f, proof, _, entry, final, result = self.check_cell_case('C1')
        self.assertIsNotNone(proof)
        self.assertTrue(entry['independent_reviewer'])
        # E2: kiro appears in no reason and has no re-run obligation.
        self.assertFalse(any('kiro' in r['detail'] for r in result['reasons']), result)
        self.assertEqual('pass', result['decision'], result)

    def test_c2_required_independent_reviewer_missing_on_b(self):
        # C2 | thieu bat buoc tren B | codex reviewer | dat | 3 o | chua dat: thieu reviewer khac hang
        f, _, states, entry, final, result = self.check_cell_case('C2')
        self.assertFalse(final['independent_reviewer'])
        self.assertNotIn(XR, final['eligible'])
        self.assertTrue(entry['independent_reviewer'])
        self.assertIn('independent model-vendor reviewer', next(r['detail'] for r in result['reasons'] if r['code'] == 'KQ6'))

    def test_c3_valid_inheritance_all_six(self):
        # C3 | ke thua hop le | codex reviewer | dat | 6 o | dat | du
        f, _, states, _, _, result = self.check_cell_case('C3')
        self.assertEqual('full', f.bundle['publications']['T40d']['label'])
        self.assertEqual({'inherited'}, {states[k]['validity'] for k in ADVISORS})
        self.assertEqual([], [ref for k in ADVISORS for ref in f.item(k)['supplements']])  # not re-run

    def test_c4_no_inheritance_comparison_missing(self):
        # C4 | khong ke thua: thieu doi chieu | codex reviewer | dat | 3 o | dat | chi phan: 3 o co van
        f, proof, _, _, _, result = self.check_cell_case('C4')
        self.assertIsNone(proof)
        self.assertFalse(result['conditions']['KQ2'])

    def test_c5_no_inheritance_wrong_hash_pair(self):
        # C5 | khong ke thua: sai cap hash | codex reviewer | dat | 3 o | dat | chi phan: 3 o co van
        f, proof, _, _, _, result = self.check_cell_case('C5')
        self.assertIsNone(proof)
        self.assertIn('wrong artifact pair', next(r['detail'] for r in result['reasons'] if r['code'] == 'KQ2'))
        # The same A receipt with an A'->B proof is not inherited.
        ev = Evidence(f.root, True)
        original = ev.read(f.item(XA)['original'])
        bad = {'id': 'comparison-A2-B', 'source': {k: f.a2[k] for k in ('commit', 'wheel_sha256')},
               'target': {k: f.b[k] for k in ('commit', 'wheel_sha256')}, 'affected': []}
        self.assertEqual('recheck', evidence_status(original, [], f.b, bad, XA)['status'])

    def test_c6_no_inheritance_dependency_changed(self):
        # C6 | khong ke thua: dependency doi | codex reviewer | dat | 3 o | dat | chi phan: 3 o co van
        f, proof, _, _, _, result = self.check_cell_case('C6')
        self.assertIsNone(proof)
        self.assertIn('dependency impact', next(r['detail'] for r in result['reasons'] if r['code'] == 'KQ2'))
        # "Duong doi A->B: co" for the advisors: the true closure includes them.
        f.bundle['comparison']['affected'] = sorted(f.true_affected)
        self.assertTrue(set(ADVISORS) <= set(compare(f.bundle, Evidence(f.root, True))['affected']))

    def test_c7_pilot_lacks_independent_reviewer(self):
        # C7 | PL-B thieu reviewer khac hang | - | chua dat: thieu reviewer khac hang | 3 o | chua dat
        f, _, _, entry, final, result = self.check_cell_case('C7')
        self.assertFalse(entry['independent_reviewer'])
        self.assertFalse(final['independent_reviewer'])

    def test_c8_pilot_pinned_cell_unusable(self):
        # C8 | PL-B o pin chua dung duoc | codex reviewer, kiro reviewer | chua dat: o pin kiro reviewer | 4 o | dat
        f, _, _, entry, final, result = self.check_cell_case('C8')
        self.assertTrue(entry['independent_reviewer'])
        self.assertEqual([KR], entry['missing_pins'])
        self.assertTrue(final['ok'])
        self.assertFalse(result['conditions']['KQ4'])

    def test_c9_all_direct(self):
        # C9 | du truc tiep | codex reviewer | dat | 6 o | dat | du
        f, _, states, _, _, _ = self.check_cell_case('C9')
        self.assertEqual({'direct'}, {s['validity'] for s in states.values()})

    # --- N0 ----------------------------------------------------------------------------
    def test_n0_declares_every_input_and_passes(self):
        # N0: 12 CG + 3 KN receipts on B with doccheck; T45e (A,B); PL-A/PL-B ok; hook unchanged; 6-row matrix
        f = self.fixture('C1')
        self.assertEqual(set(GATES), set(f.bundle['gates']))
        self.assertEqual(15, len(GATES))
        self.assertEqual(6, len(f.bundle['providers']))
        result = f.run()
        self.assertEqual('pass', result['decision'], result)
        self.assertTrue(all(result['conditions'].values()))

    # --- CK1-CK25 ----------------------------------------------------------------------
    def run_ck(self, name):
        case, mutate, codes = CK[name]
        f = self.fixture(case)
        before = copy.deepcopy(f.bundle)
        mutate(f)
        result = f.run()
        if codes:
            self.assertEqual('refused', result['decision'], (name, result))
        else:
            self.assertEqual('pass', result['decision'], (name, result))
            # E16: passing writes no plan.accepted and no owner verb; input untouched.
            self.assertNotIn('plan.accepted', json.dumps(result))
            self.assertEqual(before, f.bundle)
            self.assertIn('no real pilot claim', result['proves'])
        self.assertEqual(codes, {r['code'] for r in result['reasons']}, (name, result))
        self.assertEqual(len(result['reasons']), len({r['code'] for r in result['reasons']}))
        # E17: except CK18, the provider condition still holds when CG-KET refuses.
        self.assertEqual(name != 'CK18', result['conditions']['KQ6'], (name, result))
        # E7: gate receipt carries hash B.
        self.assertEqual(f.b['wheel_sha256'], result['wheel_sha256'])
        return f, result

    def test_ck1_all_conditions_pass(self):
        # CK1 | du moi dieu kien | C9 | ... | dat | cho qua
        self.run_ck('CK1')

    def test_ck2_partial_optional_unverified_passes(self):
        # CK2 | P1.0 chi phan, o tuy chon chua kiem chung | C1 | dat | cho qua
        self.run_ck('CK2')

    def test_ck3_valid_inheritance_no_rerun_passes(self):
        # CK3 | ke thua hop le, khong chay lai o khong bi anh huong | C3 | dat | cho qua
        f, result = self.run_ck('CK3')
        self.assertEqual({'inherited'}, {result['provider_states'][k]['validity'] for k in ADVISORS})
        self.assertEqual(0, sum(len(f.item(k)['supplements']) for k in ADVISORS))

    def test_ck4_missing_required_receipt(self):
        # CK4 | CG-R07: thieu | tu choi: KQ1: CG-R07 thieu
        _, result = self.run_ck('CK4')
        self.assertIn('CG-R07', result['reasons'][0]['detail'])

    def test_ck5_receipt_wrong_artifact(self):
        # CK5 | CG-R06: hash A | tu choi: KQ1: CG-R06 sai artifact (hash A)
        _, result = self.run_ck('CK5')
        self.assertIn('CG-R06: wrong artifact', result['reasons'][0]['detail'])

    def test_ck6_receipt_present_not_pass(self):
        # CK6 | KN-R03-R04: khong dat | tu choi: KQ1: KN-R03-R04 khong dat
        _, result = self.run_ck('CK6')
        self.assertIn('KN-R03-R04: not pass', result['reasons'][0]['detail'])

    def test_ck7_comparison_missing(self):
        # CK7 | C4 | doi chieu thieu | tu choi: KQ2: doi chieu T45e thieu
        _, result = self.run_ck('CK7')
        self.assertIn('comparison missing', result['reasons'][0]['detail'])

    def test_ck8_comparison_wrong_hash_pair(self):
        # CK8 | C5 | sai cap hash | tu choi: KQ2: doi chieu T45e sai cap hash
        _, result = self.run_ck('CK8')
        self.assertIn('wrong artifact pair', result['reasons'][0]['detail'])

    def test_ck9_comparison_dropped_dependency(self):
        # CK9 | C6 | bo dependency | tu choi: KQ2: doi chieu T45e bo dependency
        _, result = self.run_ck('CK9')
        self.assertIn('dependency impact', result['reasons'][0]['detail'])

    def test_ck10_affected_item_missing_supplement(self):
        # CK10 | muc bi anh huong thieu kiem bo sung | tu choi: KQ2
        _, result = self.run_ck('CK10')
        self.assertIn('missing supplemental checks', result['reasons'][0]['detail'])

    def test_ck11_evidence_hash_rewritten_to_b(self):
        # CK11 | doi hash bang chung sang B | tu choi: KQ2
        _, result = self.run_ck('CK11')
        self.assertIn('historical evidence changed artifact', result['reasons'][0]['detail'])

    def test_ck13_pilot_started_despite_refused_entry(self):
        # CK13 | C8 | PL-B bat dau du cong vao tu choi | tu choi: KQ4
        self.run_ck('CK13')

    def test_ck14_pilot_missing_completion_receipt(self):
        # CK14 | PL-B thieu bien nhan T35c | tu choi: KQ3
        self.run_ck('CK14')

    def test_ck15_entry_passed_after_start(self):
        # CK15 | PL-B bat dau truoc khi cong vao dat | tu choi: KQ4
        _, result = self.run_ck('CK15')
        self.assertIn('entry gate did not pass before start', result['reasons'][0]['detail'])

    def test_ck16_pilot_ran_on_other_hash_than_delivery_gate(self):
        # CK16 | PL-B chay tren hash khac cong giao | tu choi: KQ4
        _, result = self.run_ck('CK16')
        self.assertIn('wrong artifact', result['reasons'][0]['detail'])

    def test_ck17_hook_changed_without_u2(self):
        # CK17 | hook doi khong co U2 | tu choi: KQ5
        self.run_ck('CK17')

    def test_ck18_missing_independent_reviewer(self):
        # CK18 | C2 | chua dat: thieu reviewer khac hang | tu choi: KQ6
        _, result = self.run_ck('CK18')
        self.assertIn('independent model-vendor reviewer', result['reasons'][0]['detail'])

    def test_ck19_publication_exceeds_evidence(self):
        # CK19 | them kiro reviewer | tu choi: KQ7: cong bo vuot bang chung (kiro reviewer)
        _, result = self.run_ck('CK19')
        self.assertIn('published subset differs', result['reasons'][0]['detail'])

    def test_ck20_p10_label_exceeds_evidence(self):
        # CK20 | P1.0 ghi du | tu choi: KQ7: nhan P1.0 vuot bang chung
        _, result = self.run_ck('CK20')
        self.assertIn('P1.0 label wrong', result['reasons'][0]['detail'])

    def test_ck22_pilot_not_completed(self):
        # CK22 | PL-B chua hoan thanh | tu choi: KQ3
        self.run_ck('CK22')

    def test_ck24_receipt_missing_selfcheck_command(self):
        # CK24 | CG-R03: thieu lenh bo tu kiem | tu choi: KQ1
        _, result = self.run_ck('CK24')
        self.assertIn('CG-R03: doccheck command missing', result['reasons'][0]['detail'])

    def test_ck25_pla_entry_passed_after_start(self):
        # CK25 | PL-A bat dau truoc khi cong vao dat | tu choi: KQ4
        _, result = self.run_ck('CK25')
        self.assertIn('PL-A: entry gate did not pass before start', result['reasons'][0]['detail'])

    # --- z1-z12: forbidden results do not occur ----------------------------------------
    def test_z1_optional_unverified_cell_does_not_block(self):
        # E8: "Cong bi chan chi vi o tuy chon chua kiem chung" must not happen (C1/CK2).
        f = self.fixture('C1')
        self.assertTrue(f.entry_capability()['ok'])
        result = f.run()
        self.assertEqual('pass', result['decision'], result)
        self.assertEqual('unverified', result['provider_states'][KR]['status'])

    def test_z2_missing_required_capability_not_passed_even_if_partial(self):
        # E9: no pass when required capability missing, even with P1.0 "chi phan" (C2, C7).
        f = self.fixture('C2')
        self.assertEqual('partial', f.bundle['publications']['T40d']['label'])
        result = f.run()
        self.assertEqual('refused', result['decision'])
        self.assertFalse(result['conditions']['KQ6'])
        self.assertFalse(self.fixture('C7').entry_capability()['ok'])

    def test_z3_affected_cell_not_usable_with_a_receipt(self):
        # E10: affected cell published usable by A receipt must not happen.
        f = self.fixture('C2')
        self.assertEqual('recheck', f.run()['provider_states'][XR]['status'])
        for pub in f.bundle['publications'].values():
            pub['cells'].append(XR)
            pub['missing'].remove(XR)
        self.assertFalse(f.run()['conditions']['KQ7'])
        # An affected item's A receipt used as inherited gate evidence is refused.
        g = self.fixture('C1')
        g.bundle['gates']['CG-R00']['evidence'] = [{'item': 'AC1', 'receipt': g.item('AC1')['original'],
                                                    'validity': 'inherited', 'comparison_id': 'comparison-A-B'}]
        result = g.run()
        self.assertEqual({'KQ1'}, {r['code'] for r in result['reasons']}, result)
        self.assertIn('invalid inherited evidence', result['reasons'][0]['detail'])

    def test_z4_inherited_evidence_never_carries_hash_b(self):
        # E11: inherited evidence keeps hash A; gate receipt carries hash B.
        f = self.fixture('C3')
        result = f.run()
        for k in ADVISORS:
            self.assertEqual(f.a['wheel_sha256'], result['provider_states'][k]['evidence']['wheel_sha256'])
        self.assertEqual(f.b['wheel_sha256'], result['wheel_sha256'])
        # Rewriting an inherited cell's original receipt to hash B is refused.
        f.edit(f.item(XA)['original'], commit=f.b['commit'], wheel_sha256=f.b['wheel_sha256'])
        result = f.run()
        self.assertEqual('refused', result['decision'])
        self.assertTrue({'KQ2', 'KQ6'} <= {r['code'] for r in result['reasons']}, result)
        # A B-hashed copy labelled "inherited" in gate evidence is refused.
        g = self.fixture('C3')
        rec = g.load(g.item('AC2')['original'])
        rec.update(commit=g.b['commit'], wheel_sha256=g.b['wheel_sha256'])
        g.bundle['gates']['CG-R00']['evidence'] = [{'item': 'AC2', 'receipt': g.ref(rec), 'validity': 'inherited',
                                                    'comparison_id': 'comparison-A-B'}]
        result = g.run()
        self.assertIn('direct evidence mislabeled', next(r['detail'] for r in result['reasons'] if r['code'] == 'KQ1'))

    def test_z5_no_inheritance_without_valid_comparison(self):
        # E12: no inheritance when comparison missing / wrong pair / dropped dependency (C4, C5, C6).
        for case in ('C4', 'C5', 'C6'):
            with self.subTest(case=case):
                states = self.fixture(case).run()['provider_states']
                self.assertEqual({'recheck'}, {states[k]['status'] for k in ADVISORS})
                self.assertNotIn('inherited', {s.get('validity') for s in states.values()})

    def test_z6_t40d_and_t40c_t54i_cannot_disagree(self):
        # E13: T40d counts an inherited cell while T40c/T54i drop it, or the reverse.
        for dropped in (('T40c', 'T54i'), ('T40d',)):
            with self.subTest(dropped=dropped):
                f = self.fixture('C1')
                for name in dropped:
                    f.bundle['publications'][name]['cells'].remove(XA)
                    f.bundle['publications'][name]['missing'] = sorted(f.bundle['publications'][name]['missing'] + [XA])
                result = f.run()
                self.assertEqual({'KQ7'}, {r['code'] for r in result['reasons']}, result)

    def test_z7_blocked_attempt_is_not_a_pass(self):
        # E14: blocked for missing account or quota is not a passing behaviour check.
        self.assertEqual('unverified', self.fixture('C1').run()['provider_states'][KR]['status'])
        self.assertEqual('recheck', self.fixture('C2').run()['provider_states'][XR]['status'])
        f = self.fixture('C1')
        next(r for r in f.bundle['providers'] if r['id'] == KR)['status'] = 'usable'
        result = f.run()
        self.assertEqual('refused', result['decision'])
        self.assertIn('reported status differs', next(r['detail'] for r in result['reasons'] if r['code'] == 'KQ6'))
        g = self.fixture('C1')
        g.bundle['gates']['CG-R00']['evidence'] = [{'item': KR, 'receipt': g.item(KR)['supplements'][0], 'validity': 'direct'}]
        self.assertIn('evidence not pass', next(r['detail'] for r in g.run()['reasons'] if r['code'] == 'KQ1'))

    def test_z8_provider_condition_alone_does_not_pass(self):
        # E19: CG-KET must not pass just because KQ6 holds.
        for name, (case, mutate, codes) in CK.items():
            if codes and name != 'CK18':
                with self.subTest(ck=name):
                    f = self.fixture(case)
                    mutate(f)
                    result = f.run()
                    self.assertTrue(result['conditions']['KQ6'])
                    self.assertEqual('refused', result['decision'])

    def test_z9_every_kq_is_evaluated(self):
        # E20: each KQ has a case wrong only in that KQ; that KQ alone fails.
        for kq, name in (('KQ1', 'CK4'), ('KQ2', 'CK7'), ('KQ3', 'CK14'), ('KQ4', 'CK15'),
                         ('KQ5', 'CK17'), ('KQ6', 'CK18'), ('KQ7', 'CK19')):
            with self.subTest(kq=kq):
                case, mutate, _ = CK[name]
                f = self.fixture(case)
                mutate(f)
                conditions = f.run()['conditions']
                self.assertEqual({kq}, {k for k, ok in conditions.items() if not ok})

    def test_z10_present_failing_receipt_not_counted_as_pass(self):
        # E21: at CK6 the receipt is present but not pass.
        f = self.fixture('C1')
        _ck6(f)
        self.assertIn('KN-R03-R04', f.bundle['gates'])
        self.assertEqual('fail', f.load(f.bundle['gates']['KN-R03-R04']['receipt'])['result'])
        self.assertFalse(f.run()['conditions']['KQ1'])

    def test_z11_entry_passed_after_start_not_accepted(self):
        # E22: at CK15.
        f = self.fixture('C1')
        _ck15(f)
        self.assertFalse(f.run()['conditions']['KQ4'])

    def test_z12_other_artifact_or_bad_comparison_not_accepted(self):
        # E23: at CK5 (wrong artifact), CK8 (wrong hash pair), CK9 (dropped dependency).
        for name, kq in (('CK5', 'KQ1'), ('CK8', 'KQ2'), ('CK9', 'KQ2')):
            with self.subTest(ck=name):
                case, mutate, _ = CK[name]
                f = self.fixture(case)
                mutate(f)
                result = f.run()
                self.assertEqual('refused', result['decision'])
                self.assertFalse(result['conditions'][kq])


if __name__ == '__main__':
    unittest.main()
