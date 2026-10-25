"""T22 (R05, round 7): reuse needs a recorded valid basis - counter-examples for W08 (onecrew.v2.verification_evidence.assess).

The fixture artifacts of the testcase, one pure decision each, over a baseline evidence E of artifact A:
  (a) a changed unrelated file whose basis is path-only; (b) the same change with no basis; (c) the checker configuration changed;
  (d) only paths under the contract's declared scope.neutral changed; (e) a "behavioral" basis that points to no evidence.
[E3] no "reuse" decision exists without a basis record (reusable on a changed artifact => requires_record and a scope.neutral basis);
     mutant "reuse whenever the changed file is not an input" turns the check red at (b).
[E6] no "reuse" decision rests on a path-only basis or a behavioral basis with empty evidence; mutant "accept a path-only basis"
     turns the check red at (a).
"""
import unittest

from onecrew.v2 import verification_evidence as evidence

A, B = 'a' * 40, 'b' * 40


def bound(**changes):
    data = dict(artifact=A, revision=1, acceptance={'O1': 'Required output'}, inputs={'I1': 'interface-A'},
                configuration={'checker': 'v1'}, environment={'V': 'runtime-A'}, checks=['C1', 'C2'])
    data.update(changes)
    return evidence.bind(**data)


CASES = {
    'a': (dict(artifact=B), dict(changed_paths=['docs/unrelated.md'], basis={'kind': 'path', 'path': 'docs/unrelated.md'})),
    'b': (dict(artifact=B), dict(changed_paths=['docs/unrelated.md'])),
    'c': (dict(artifact=B, configuration={'checker': 'v2'}), dict(changed_paths=['docs/unrelated.md'], neutral=['docs/**'])),
    'd': (dict(artifact=B, revision=2), dict(changed_paths=['docs/unrelated.md'], neutral=['docs/**'])),
    'e': (dict(artifact=B), dict(changed_paths=['src/main.py'], basis={'kind': 'behavioral', 'evidence': []})),
}


def decisions(assess):
    old = bound()
    return {case: assess(old, bound(**cur), **kw) for case, (cur, kw) in CASES.items()}


def e3_holds(assess):
    out = decisions(assess)
    if out['b']['reusable']:
        return False
    unrecorded = [c for c, r in out.items() if r['reusable'] and not (
        r.get('requires_record') and r.get('reuse_basis') and r['reuse_basis'].get('kind') == 'scope.neutral')]
    return not unrecorded and out['d']['reusable']


def e6_holds(assess):
    out = decisions(assess)
    weak = [c for c, r in out.items() if r['reusable'] and (CASES[c][1].get('basis') or {}).get('kind') in ('path', 'behavioral')]
    return not weak and not out['a']['reusable'] and not out['e']['reusable']


class T22CounterExampleTests(unittest.TestCase):
    def test_e3_every_reuse_has_a_recorded_basis_and_the_reuse_when_not_an_input_mutant_is_red_at_b(self):
        self.assertTrue(e3_holds(evidence.assess))
        out = decisions(evidence.assess)
        self.assertEqual([c for c, r in out.items() if r['reusable']], ['d'])
        def reuse_outside_inputs(previous, current, **kw):    # counter-example: reuse whenever the changed file is not an input
            result = evidence.assess(previous, current, **kw)
            if result['reasons'] and all(r.startswith('artifact changed') for r in result['reasons']):
                return dict(result, status='reuse_eligible', reusable=True, reasons=[], checks_to_rerun=[])
            return result
        self.assertFalse(e3_holds(reuse_outside_inputs))
        self.assertTrue(decisions(reuse_outside_inputs)['b']['reusable'])

    def test_e6_no_reuse_on_path_only_or_evidence_free_behavioral_basis_and_the_path_only_mutant_is_red_at_a(self):
        self.assertTrue(e6_holds(evidence.assess))
        def accept_path_only(previous, current, **kw):        # counter-example: a path-only assertion authorizes reuse
            basis = kw.get('basis')
            if basis and basis.get('kind') == 'path':
                return {'status': 'reuse_eligible', 'reusable': True, 'reasons': [], 'checks_to_rerun': [],
                        'reuse_basis': dict(basis), 'requires_record': True}
            return evidence.assess(previous, current, **kw)
        self.assertFalse(e6_holds(accept_path_only))
        self.assertTrue(decisions(accept_path_only)['a']['reusable'])


if __name__ == '__main__':
    unittest.main()
