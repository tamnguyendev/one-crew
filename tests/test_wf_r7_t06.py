"""T06 (R05, round 7): counter-examples for the stale rules of W07 (onecrew.v2.verification_evidence).

Each rule is written once as a predicate over the decision function, run on the real `assess`/`bind` (green) and on a mutant of the
product function (red), so the counter-example of the testcase is shown to turn the check red:
  [E2] a changed file outside every input, with no recorded reuse basis, leaves EV1 stale, and the reason names the artifact change
       and the missing basis; mutant: "keep EV1 valid whenever the changed file is not an input".
  [E3] right after the interface input I1 changes (the artifact of N itself unchanged: I1 is another node's interface), EV1 is no
       longer valid; mutant: a receipt that does not bind its inputs.
  [E4] every stale reason names what changed (I1, the checker configuration C, the environment component V); mutant: a generic reason.
"""
import unittest
from unittest.mock import patch

from onecrew.v2 import verification_evidence as evidence

A, B = 'a' * 40, 'b' * 40


def baseline(bind=None, **changes):
    data = dict(artifact=A, revision=1, acceptance={'O1': 'Required output'},
                inputs={'I1': 'interface-A', 'I2': 'source-A'}, configuration={'checker': 'v1'},
                environment={'V': 'runtime-A'}, checks=['C1', 'C2'])
    data.update(changes)
    return (bind or evidence.bind)(**data)


def e2_holds(assess):
    out = assess(baseline(), baseline(artifact=B), changed_paths=['unrelated.txt'])
    text = '; '.join(out['reasons'])
    return (out['status'] == 'stale' and not out['reusable'] and out['checks_to_rerun'] == ['C1', 'C2']
            and 'artifact changed' in text and 'reuse basis' in text)


def e3_holds(assess, bind=None):
    old = baseline(bind)
    out = assess(old, baseline(bind, inputs={'I1': 'interface-B', 'I2': 'source-A'}))
    return out['status'] == 'stale' and not out['reusable'] and set(old['checks']) <= set(out['checks_to_rerun'])


def e4_holds(assess):
    old = baseline()
    for changes, name in (({'inputs': {'I1': 'interface-B', 'I2': 'source-A'}}, 'I1'),
                          ({'configuration': {'checker': 'v2'}}, 'configuration'),
                          ({'environment': {'V': 'runtime-B'}}, 'V')):
        out = assess(old, baseline(**changes))
        if out['reusable'] or not out['reasons'] or not all(name in reason for reason in out['reasons']):
            return False
    return True


class T06CounterExampleTests(unittest.TestCase):
    def test_e2_outside_input_change_without_basis_is_stale_and_the_keep_valid_mutant_is_red(self):
        self.assertTrue(e2_holds(evidence.assess))
        def keep_valid(previous, current, **kw):           # counter-example: an outside-input change keeps EV1 valid
            out = evidence.assess(previous, current, **kw)
            if out['reasons'] and all(r.startswith('artifact changed') for r in out['reasons']):
                return dict(out, status='current', reusable=True, reasons=[], checks_to_rerun=[])
            return out
        self.assertFalse(e2_holds(keep_valid))

    def test_e3_interface_change_invalidates_ev1_and_a_receipt_not_bound_to_inputs_is_red(self):
        self.assertTrue(e3_holds(evidence.assess))
        real_bind = evidence.bind
        def unbound(**data):                               # counter-example: the receipt does not bind its inputs
            return real_bind(**dict(data, inputs={'unbound': 'same'}))
        self.assertFalse(e3_holds(evidence.assess, bind=unbound))
        with patch.object(evidence, 'bind', unbound):      # the same mutant patched into the product module
            self.assertFalse(e3_holds(evidence.assess, bind=evidence.bind))

    def test_e4_each_reason_names_what_changed_and_a_generic_reason_is_red(self):
        self.assertTrue(e4_holds(evidence.assess))
        def generic(previous, current, **kw):              # counter-example: "evidence stale" with no name
            out = evidence.assess(previous, current, **kw)
            return dict(out, reasons=['evidence stale'] if out['reasons'] else [])
        self.assertFalse(e4_holds(generic))


if __name__ == '__main__':
    unittest.main()
