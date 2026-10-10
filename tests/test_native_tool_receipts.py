import copy
import json
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.native_audit import NativeClaude, check_native_tools


def denied_events():
    return [
        {'type':'system','subtype':'init','tools':['Read','Glob','Grep','StructuredOutput']},
        {'type':'assistant','message':{'content':[{'type':'tool_use','name':'Edit','id':'edit-1','input':{}}]}},
        {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'edit-1','is_error':True,
            'content':'<tool_use_error>Error: No such tool available: Edit. Edit is disabled for this session, in subagents as well as here.</tool_use_error>'}]}}
    ]


class NativeToolReceiptTests(unittest.TestCase):
    def test_system_permission_denial_string_does_not_crash_or_excuse_unknown_tools(self):
        events=denied_events()
        events.insert(2,{'type':'system','subtype':'permission_denied','message':'denied','tool_use_id':'edit-1'})
        self.assertEqual(len(check_native_tools(events)[1]),1)
        events.pop()
        with self.assertRaises(LedgerError):check_native_tools(events)

    def test_malformed_messages_are_errors_not_python_attribute_crashes(self):
        for message in (None,'text',{'content':[None]},{'content':42}):
            with self.subTest(message=message),self.assertRaises(LedgerError):
                check_native_tools([{'type':'assistant','message':message}])
        with self.assertRaises(LedgerError):check_native_tools([None])
        class Recorded:
            def stdout(self,attempt):return 'null\n'
        with self.assertRaises(LedgerError):NativeClaude.result(Recorded(),{})

    def test_exact_cli_denial_retained_in_result_telemetry(self):
        events=denied_events()+[{'type':'result','is_error':False,'subtype':'success',
            'structured_output':{'report':'Patch awaiting tests','files':[],'question':''}}]
        class Recorded:
            def stdout(self,attempt): return '\n'.join(json.dumps(e) for e in events)
        value,_=NativeClaude.result(Recorded(),{'result':json.dumps({'stdout':'fixture.jsonl'})})
        self.assertEqual(value['_native']['denied_tool_calls'][0]['name'],'Edit')
        self.assertEqual(value['_native']['tool_calls'],1)

    def test_success_generic_error_missing_duplicate_and_wrong_id_remain_blocked(self):
        for variation in ('success','generic_error','missing','duplicate','wrong_id','before_call','assistant_claim'):
            with self.subTest(variation=variation):
                events=denied_events();result=events[2]['message']['content'][0]
                if variation=='success':result['is_error']=False
                elif variation=='generic_error':result['content']='Permission denied after writing file'
                elif variation=='missing':events.pop()
                elif variation=='duplicate':events.append(copy.deepcopy(events[2]))
                elif variation=='wrong_id':result['tool_use_id']='other'
                elif variation=='before_call':events[1],events[2]=events[2],events[1]
                else:events[2]['type']='assistant'
                with self.assertRaises(LedgerError):check_native_tools(events)

    def test_missing_or_expanded_session_capability_cannot_be_excused(self):
        for variation in ('no_init','duplicate_init','edit_available','shell_available','malformed'):
            with self.subTest(variation=variation):
                events=denied_events()
                if variation=='no_init':events.pop(0)
                elif variation=='duplicate_init':events.append(copy.deepcopy(events[0]))
                elif variation=='edit_available':events[0]['tools'].append('Edit')
                elif variation=='shell_available':events[0]['tools'].append('Bash')
                else:events[0]['tools']=[{}]
                with self.assertRaises(LedgerError):check_native_tools(events)

    def test_denial_text_cannot_hide_successful_unknown_tool_or_duplicate_call(self):
        for duplicate in (False,True):
            events=denied_events()
            events.append({'type':'assistant','message':{'content':[{'type':'tool_use','name':'Edit',
                'id':'edit-1' if duplicate else 'edit-2'}]}})
            with self.assertRaises(LedgerError):check_native_tools(events)

    def test_read_only_calls_remain_compatible_with_older_logs(self):
        events=[{'type':'assistant','message':{'content':[{'type':'tool_use','name':'Read','id':'read-1'}]}}]
        calls,denied=check_native_tools(events)
        self.assertEqual(len(calls),1);self.assertEqual(denied,[])

    def test_single_text_block_denial_supported_but_embedded_quoted_denial_rejected(self):
        events=denied_events();result=events[2]['message']['content'][0];text=result['content']
        result['content']=[{'type':'text','text':text}]
        self.assertEqual(len(check_native_tools(events)[1]),1)
        result['content']='File contents: '+text
        with self.assertRaises(LedgerError):check_native_tools(events)


if __name__=='__main__':unittest.main()
