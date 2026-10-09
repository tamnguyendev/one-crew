from copy import deepcopy
import datetime as dt
import unittest

from onecrew.ledger import LedgerError
from onecrew.routing import choose, validate_decision

NOW = dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc)


def candidate(name, tier, cost, provider='codex'):
    return {'id': name, 'provider': provider, 'model': name, 'tier': tier, 'cost_rank': cost,
            'capability_verified': True, 'auth_mode': 'subscription', 'quota': {
                'observed_at': NOW.isoformat(), 'expires_at': (NOW+dt.timedelta(minutes=5)).isoformat(),
                'source': 'fixture', 'windows': [{'name': name, 'remaining': 50, 'reserved': 2,
                    'keep_for_chat': 10, 'estimated_call': 1, 'resets_at': (NOW+dt.timedelta(hours=hours)).isoformat()}
                    for name,hours in [('five_hour',5),('weekly',168)]]}}


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.work = {'complexity': 1, 'risk': 'low', 'allowed_providers': ['codex','claude','kiro']}
        self.models = [candidate('small',1,1),candidate('large',3,10),candidate('medium',2,4)]

    def test_light_work_prefers_small_but_risk_or_complexity_sets_floor(self):
        self.assertEqual(choose(self.work,self.models,NOW)['selected']['id'],'small')
        self.work['risk']='high'
        self.assertEqual(choose(self.work,self.models,NOW)['selected']['id'],'large')
        self.work.update(risk='low',complexity=2)
        self.assertEqual(choose(self.work,self.models,NOW)['selected']['id'],'medium')

    def test_exhausted_week_blocks_even_with_short_window_available(self):
        self.models[0]['quota']['windows'][1]['remaining']=0
        result=choose(self.work,self.models,NOW)
        self.assertEqual(result['selected']['id'],'medium')
        self.assertIn('quota_insufficient:weekly',result['rejected'][0]['reasons'])

    def test_unknown_stale_reset_and_reserve_are_not_unlimited(self):
        for mode in ('unknown','stale','reset','reserve'):
            item=candidate('only',1,1)
            if mode=='unknown': item['quota']=None
            if mode=='stale': item['quota']['expires_at']=NOW.isoformat()
            if mode=='reset': item['quota']['windows'][0]['resets_at']=NOW.isoformat()
            if mode=='reserve': item['quota']['windows'][0]['reserved']=40
            with self.subTest(mode=mode):
                self.assertEqual(choose(self.work,[item],NOW)['status'],'blocked')

    def test_paid_api_unverified_capability_or_unauthorized_provider_rejected(self):
        for field,value in (('auth_mode','api_key'),('capability_verified',False),('provider','unknown')):
            item=candidate('only',1,1); item[field]=value
            self.assertIsNone(choose(self.work,[item],NOW)['selected'])

    def test_strict_boolean_nonfinite_and_naive_timestamp_rejected(self):
        for field,value in (('tier',True),('cost_rank',float('nan')),('capability_verified','true')):
            item=candidate('only',1,1); item[field]=value
            with self.assertRaises(LedgerError): choose(self.work,[item],NOW)
        item=candidate('only',1,1); item['quota']['observed_at']='2026-10-09T00:00:00'
        with self.assertRaises(LedgerError): choose(self.work,[item],NOW)

    def test_ai_proposal_cannot_invent_authority_actions_or_evidence(self):
        value={'action':'repair','confidence':.9,'reason':'Gate C1 failed.','evidence':['C1']}
        self.assertEqual(validate_decision(value,['repair','ask'],['C1'])['authority'],'proposal_only')
        value['action']='deploy'
        with self.assertRaises(LedgerError): validate_decision(value,['repair','ask'],['C1'])
        value['action']='repair'; value['confidence']='0.9'
        with self.assertRaises(LedgerError): validate_decision(value,['repair','ask'],['C1'])
        value['confidence']=.2; value['evidence']=['invented']
        with self.assertRaises(LedgerError): validate_decision(value,['repair','ask'],['C1'])


if __name__ == '__main__':
    unittest.main()
