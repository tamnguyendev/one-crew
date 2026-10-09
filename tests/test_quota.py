import datetime as dt
import json
import unittest

from onecrew.ledger import LedgerError
from onecrew.quota import ReadOnlyRPC, codex, normalize, routing_quota
from onecrew.routing import choose

NOW = dt.datetime(2026,10,9,tzinfo=dt.timezone.utc)


def raw(weekly_used=40):
    def window(used, hours):
        return {'usedPercent':used, 'windowDurationMins':hours*60,
                'resetsAt':int((NOW+dt.timedelta(hours=hours)).timestamp())}
    return {'rateLimits': {'limitId':'wrong-legacy','primary':window(0,5)},
            'rateLimitsByLimitId': {'codex':{'primary':window(20,5),'secondary':window(weekly_used,168),
                                           'spendControlReached':False}},
            'accountEmail':'private@example.invalid', 'rateLimitResetCredits':{'availableCount':5}}


class FakeRPC:
    def __init__(self, argv):
        self.methods = []
        self.closed = False
        self.auth = 'chatgpt'

    def request(self, method, params):
        self.methods.append(method)
        if method == 'initialize':
            return {}
        if method == 'account/read':
            return {'account':{'type':self.auth,'email':'private@example.invalid'}}
        return raw()

    def initialized(self):
        self.methods.append('initialized')

    def close(self):
        self.closed = True


class QuotaTests(unittest.TestCase):
    def test_multi_bucket_preferred_and_every_window_counts_for_routing(self):
        observation = normalize(raw(100), NOW)
        self.assertEqual(set(observation['buckets']), {'codex'})
        quota = routing_quota(observation, 'codex', ['primary','secondary'], 1, 10)
        candidate = {'id':'small','provider':'codex','model':'fixture','tier':1,'cost_rank':1,
                     'capability_verified':True,'auth_mode':'subscription','quota':quota}
        choice = choose({'complexity':1,'risk':'low','allowed_providers':['codex']}, [candidate], NOW)
        self.assertEqual(choice['status'], 'blocked')
        self.assertIn('quota_insufficient:secondary', choice['rejected'][0]['reasons'])
        self.assertNotIn('private@', json.dumps(observation))
        self.assertNotIn('ResetCredit', json.dumps(observation))

    def test_missing_and_stale_are_not_unlimited_and_estimate_must_be_positive(self):
        payload = raw()
        payload['rateLimitsByLimitId']['codex']['secondary'] = None
        observation = normalize(payload, NOW)
        with self.assertRaisesRegex(LedgerError, 'unavailable'):
            routing_quota(observation, 'codex', ['primary','secondary'], 1, 10)
        with self.assertRaises(LedgerError):
            routing_quota(observation, 'codex', ['primary'], 0, 10)
        quota = routing_quota(observation, 'codex', ['primary'], 1, 10)
        candidate = {'id':'small','provider':'codex','model':'fixture','tier':1,'cost_rank':1,
                     'capability_verified':True,'auth_mode':'subscription','quota':quota}
        choice = choose({'complexity':1,'risk':'low','allowed_providers':['codex']}, [candidate], NOW+dt.timedelta(minutes=3))
        self.assertEqual(choice['status'], 'blocked')

    def test_server_spend_control_and_strict_types_fail_closed(self):
        for value in (True, None):
            payload = raw()
            payload['rateLimitsByLimitId']['codex']['spendControlReached'] = value
            with self.assertRaises(LedgerError):
                routing_quota(normalize(payload, NOW), 'codex', ['primary'], 1, 10)
        for value in ('false', 0):
            payload = raw()
            payload['rateLimitsByLimitId']['codex']['spendControlReached'] = value
            with self.assertRaises(LedgerError):
                normalize(payload, NOW)
        payload = raw()
        payload['rateLimitsByLimitId']['codex']['primary']['usedPercent'] = True
        with self.assertRaises(LedgerError):
            normalize(payload, NOW)

    def test_invalid_individual_timestamp_is_a_controlled_error(self):
        payload = raw()
        payload['rateLimitsByLimitId']['codex']['individualLimit'] = {
            'remainingPercent': 50, 'resetsAt': 10**100}
        with self.assertRaisesRegex(LedgerError, 'individual reset'):
            normalize(payload, NOW)

    def test_transport_never_starts_turn_or_spends_credits_and_closes(self):
        rpc = FakeRPC([])
        result = codex(lambda argv: rpc, {'available':True})
        self.assertEqual(rpc.methods, ['initialize','initialized','account/read','account/rateLimits/read'])
        self.assertTrue(rpc.closed)
        self.assertEqual(result['model_calls'], 0)
        rpc.auth = 'apiKey'
        with self.assertRaisesRegex(LedgerError, 'no API-key fallback'):
            codex(lambda argv: rpc, {'available':True})
        unstarted = ReadOnlyRPC.__new__(ReadOnlyRPC)
        for method in ('turn/start','account/rateLimitResetCredit/consume','account/sendAddCreditsNudgeEmail','account/login/start'):
            with self.assertRaisesRegex(LedgerError, 'read-only'):
                unstarted.request(method,{})


if __name__ == '__main__':
    unittest.main()
