from copy import deepcopy
import unittest

from onecrew.usage import record, summarize


class UsageTests(unittest.TestCase):
    def test_replayed_receipt_and_cached_input_are_not_counted_twice(self):
        state = {'usage': []}
        tokens = {'input_tokens':100, 'cached_input_tokens':60, 'output_tokens':20}
        for _ in range(3):
            record(state,'first',[tokens,tokens],'codex','fixture')
        summary = summarize(state['usage']*2)
        self.assertEqual(summary['attempts'],1)
        self.assertEqual(summary['totals_observed_only']['total_tokens'],120)
        self.assertEqual(summary['totals_observed_only']['uncached_input_tokens'],40)
        self.assertEqual(summary['totals_observed_only']['cached_input_tokens'],60)
        record(state,'second',[tokens],'codex','fixture')
        self.assertEqual(summarize(state['usage'])['totals_observed_only']['total_tokens'],240)

    def test_conflicting_cumulative_and_missing_reports_are_unknown_not_free(self):
        state = {'usage': []}
        tokens = {'input_tokens':100, 'cached_input_tokens':60, 'output_tokens':20}
        record(state,'first',[tokens],'codex','fixture')
        record(state,'first',[dict(tokens,input_tokens=200)],'codex','fixture')
        record(state,'cumulative',[tokens,dict(tokens,input_tokens=200)],'codex','fixture')
        record(state,'legacy',[],None,'fixture')
        summary = summarize(state['usage'], [{'id':'failed-no-report','status':'settled','charged':1},
            {'id':'unknown-launch','status':'unknown','charged':0}, {'id':'not-started','status':'settled','charged':0}])
        self.assertEqual(set(summary['unknown_attempts']),{'first','cumulative','legacy','failed-no-report','unknown-launch'})
        self.assertEqual(summary['measured_attempts'],[])
        self.assertIsNone(summary['cost_usd'])

    def test_kiro_credits_separate_and_invalid_token_types_never_coerced(self):
        state = {'usage': []}
        meter = {'metering':[{'unit':'credit','value':.125}]}
        record(state,'kiro',[meter,meter],'kiro','fixture')
        for index,invalid in enumerate((True,-1,1.5,120)):
            record(state,str(index),[{'input_tokens':100,'cached_input_tokens':invalid,'output_tokens':20}],'codex','fixture')
        summary = summarize(state['usage'])
        self.assertEqual(summary['totals_observed_only']['kiro_credits'],.125)
        self.assertEqual(summary['measured_attempts'],['kiro'])
        self.assertEqual(len(summary['unknown_attempts']),4)


if __name__ == '__main__':
    unittest.main()
