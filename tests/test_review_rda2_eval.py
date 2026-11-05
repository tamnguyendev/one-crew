"""RD-A2 controlled scenarios: false-SKIP count, calls and latency added, over a labelled case set.

A fake provider proves the structure (no path from an answer to a skipped mandatory check, bounded calls, bounded spend, stale
records not reused). It proves NOTHING about the quality of a real model's advice: 'good' and 'wrong' are labels the fixture
gives its own answers. Set RDA2_EVAL_OUT to a folder to keep the JSON report.
"""
import json
import os
import time
import unittest
from pathlib import Path

from onecrew.v2 import review_advice
from tests.test_review_rda2_lifecycle import AdviceRoot, Provider, GRANT

REPORT = []


def measure(test, name, label, provider, expected, **changes):
    """Run one advice request on a fresh root; record what it cost and whether the base policy survived."""
    used_before, calls_before = test.group()['used_calls'], provider.calls
    started = time.monotonic()
    result, _ = test.advise(provider, **changes)
    wall = (time.monotonic() - started) * 1000
    row = {'case': name, 'label': label, 'status': result['status'], 'reason': result['reason'], 'effective_action': result['effective_action'],
           'baseline_action': (result['baseline'] or {}).get('action'), 'provider_calls': provider.calls - calls_before,
           'root_calls_charged': test.group()['used_calls'] - used_before, 'latency_ms': round(wall),
           'latency_added_ms': round(max(0.0, wall - provider.delay * 1000)), 'cache': result['cache'],
           'proposal_option': ((result['proposal'] or {}).get('option') or {}).get('id'),
           'proposal_action': ((result['proposal'] or {}).get('option') or {}).get('action'),
           'events_written': len(test.advice_events()), 'grants_authority': result['grants_authority']}
    # false SKIP: the effective action was SKIP where the labelled policy requires a review, or a SKIP proposal survived there.
    row['false_skip'] = int(expected['required'] == 'REVIEW' and (row['effective_action'] == 'SKIP' or row['proposal_action'] == 'SKIP'))
    row['blocked_skip_attempt'] = int(provider.mode == 'skip' and result['proposal'] is None)
    row['expected_status'] = expected['status']
    REPORT.append(row)
    test.assertEqual(row['status'], expected['status'], row)
    test.assertEqual(row['false_skip'], 0, row)
    test.assertEqual(row['effective_action'], expected.get('effective', 'REVIEW'), row)
    test.assertLessEqual(row['provider_calls'], expected['calls'], row)
    test.assertEqual(row['root_calls_charged'], row['provider_calls'], row)      # every call went through the root budget, none around it
    test.assertFalse(row['grants_authority'])
    return result, row


class Good(AdviceRoot):
    def test_good(self):
        measure(self, 'good', 'good answer', Provider('good'), {'status': 'proposal', 'required': 'REVIEW', 'calls': 1})

    def test_wrong_but_valid_answer_cannot_change_the_policy(self):
        _, row = measure(self, 'wrong', 'valid but poor choice', Provider('wrong'), {'status': 'proposal', 'required': 'REVIEW', 'calls': 1})
        self.assertEqual(row['proposal_option'], 'mechanical')       # a poor suggestion is still only a suggestion

    def test_slow(self):
        _, row = measure(self, 'slow', 'answers after 0.4 s', Provider('good', delay=.4), {'status': 'proposal', 'required': 'REVIEW', 'calls': 1})
        self.assertGreaterEqual(row['latency_ms'], 400)

    def test_timeout(self):
        measure(self, 'timeout', 'provider timeout', Provider('error'), {'status': 'fallback', 'required': 'REVIEW', 'calls': 1})

    def test_malformed(self):
        measure(self, 'malformed', 'bad schema', Provider('malformed'), {'status': 'fallback', 'required': 'REVIEW', 'calls': 1})

    def test_suggests_skip_of_a_mandatory_milestone(self):
        _, row = measure(self, 'skip-mandatory', 'answers skip for a mandatory node', Provider('skip'),
                         {'status': 'fallback', 'required': 'REVIEW', 'calls': 1}, review_id='M1', mandatory=True)
        self.assertEqual(row['blocked_skip_attempt'], 1)

    def test_suggests_skip_where_standard_policy_requires_review(self):
        _, row = measure(self, 'skip-standard', 'answers skip under a standard policy', Provider('skip'),
                         {'status': 'fallback', 'required': 'REVIEW', 'calls': 1})
        self.assertEqual(row['blocked_skip_attempt'], 1)

    def test_repeat_is_served_from_the_record(self):
        provider = Provider('good')
        measure(self, 'first', 'first request', provider, {'status': 'proposal', 'required': 'REVIEW', 'calls': 1})
        _, row = measure(self, 'repeat', 'same input again', provider, {'status': 'proposal', 'required': 'REVIEW', 'calls': 0})
        self.assertEqual((row['cache'], row['provider_calls'], row['root_calls_charged']), ('hit', 0, 0))

    def test_stale_record_is_not_reused_after_the_contract_changes(self):
        provider = Provider('good')
        measure(self, 'before-change', 'first request', provider, {'status': 'proposal', 'required': 'REVIEW', 'calls': 1})
        self.amend_root()
        before = provider.calls
        result, _ = self.advise(provider)
        REPORT.append({'case': 'stale-cache', 'label': 'contract amended, same input', 'status': result['status'], 'cache': result['cache'],
                       'provider_calls': provider.calls - before, 'false_skip': 0, 'stale_reused': int(result['cache'] == 'hit')})
        self.assertEqual((result['cache'], provider.calls - before), ('miss', 1))


class OutOfAuthority(AdviceRoot):
    authority = {'edit': True, 'commands': False, 'granted_actions': ['review_advice:suggest']}

    def test_out_of_authority_option_is_never_offered(self):
        options = review_advice.default_options() + [
            {'id': 'bounded2', 'label': 'Second bounded look', 'action': 'REVIEW', 'method': 'bounded_review', 'checkpoint': 'after-output'}]
        provider = Provider('wrong')              # picks the FIRST offered option; it must not be the command one
        _, row = measure(self, 'out-of-authority', 'command option without commands grant', provider,
                         {'status': 'proposal', 'required': 'REVIEW', 'calls': 1}, options=options)
        self.assertEqual(row['proposal_option'], 'bounded')
        self.assertNotIn('mechanical', json.dumps(provider.bodies[0]))


class NoGrant(AdviceRoot):
    authority = {'edit': True, 'commands': True}

    def test_no_grant(self):
        measure(self, 'no-grant', 'root does not grant advice', Provider('good'), {'status': 'skipped', 'required': 'REVIEW', 'calls': 0})


class LightPolicy(AdviceRoot):
    depth = 'light'

    def test_light_policy_skip_is_the_approved_baseline_not_a_false_skip(self):
        # Light + optional: the approved policy itself permits SKIP, so this is not "false". A proposal may only be MORE careful.
        _, row = measure(self, 'light-good', 'light policy, good answer', Provider('good'),
                         {'status': 'proposal', 'required': 'SKIP', 'calls': 1, 'effective': 'SKIP'})
        self.assertEqual(row['proposal_action'], 'REVIEW')


class Summary(unittest.TestCase):
    """Runs last (name order): totals and the report file."""
    def test_zz_totals(self):
        rows = [r for r in REPORT if 'false_skip' in r]
        total = {'cases': len(rows), 'false_skip': sum(r['false_skip'] for r in rows),
                 'provider_calls': sum(r['provider_calls'] for r in rows),
                 'blocked_skip_attempts': sum(r.get('blocked_skip_attempt', 0) for r in rows),
                 'stale_reused': sum(r.get('stale_reused', 0) for r in rows),
                 'provider': 'fake-only; says nothing about real-model quality'}
        out = os.environ.get('RDA2_EVAL_OUT')
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / 'rda2-eval.json').write_text(json.dumps({'total': total, 'cases': REPORT}, ensure_ascii=False, indent=2), encoding='utf-8')
        self.assertEqual((total['false_skip'], total['stale_reused']), (0, 0))


if __name__ == '__main__':
    unittest.main()
