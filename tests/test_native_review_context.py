import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from onecrew.ledger import LedgerError, canonical
from onecrew.native_review_context import packet, PROMPT_LIMIT
from onecrew.snapshots import bytes_hash
from onecrew.workspace_worker import inventory


class NativeReviewContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'source.dart').write_text('original source')
        self.state={'snapshot':'preserved','tests':[{'passed':True}],
                    'native_change':{'workspace':str(self.root),'tool_baseline':inventory(self.root)}}

    def test_large_diff_pages_are_complete_unicode_and_keep_tests(self):
        diff='- old\n+ sửa Cloud Auth\n'*3600
        values={'goal':'Review complete patch','diff':diff,'tests':{'passed':True,'count':53}}
        result=packet(None,self.state,values)
        self.assertLessEqual(len(canonical(result)),PROMPT_LIMIT)
        ref=result['diff']['external_evidence']
        data=b''.join((self.root/p['path']).read_bytes() for p in ref['pages'])
        self.assertEqual(data.decode(),diff)
        self.assertEqual(bytes_hash(data),ref['sha256'])
        self.assertEqual(result['tests'],values['tests'])
        self.assertEqual(self.state['snapshot'],'preserved')
        self.assertEqual(self.state['native_change']['tool_baseline'],inventory(self.root))
        self.assertFalse(ref['truncated'])
        self.assertEqual(packet(None,self.state,values),result)

    def test_large_structured_evidence_remains_retrievable_json(self):
        values={'result':{'details':['detail '*1000]*20}}
        result=packet(None,self.state,values)
        ref=result['result']['external_evidence']
        raw=''.join((self.root/p['path']).read_text(encoding='utf8') for p in ref['pages'])
        self.assertEqual(json.loads(raw),values['result'])

    def test_tampered_evidence_is_rejected_not_overwritten(self):
        values={'diff':'x'*81000}
        result=packet(None,self.state,values)
        p=self.root/result['diff']['external_evidence']['pages'][0]['path']
        p.write_text('tampered')
        with self.assertRaisesRegex(LedgerError,'evidence changed'):
            packet(None,self.state,values)
        self.assertEqual(p.read_text(),'tampered')

    def test_small_context_is_unchanged_without_side_effects(self):
        before=dict(self.state['native_change'])
        values={'diff':'small','tests':{'passed':True}}
        self.assertEqual(packet(None,self.state,values),values)
        self.assertEqual(self.state['native_change'],before)

    def test_read_only_review_without_workspace_worker_baseline(self):
        self.state['native_change'].pop('tool_baseline')
        result=packet(None,self.state,{'diff':'x'*81000})
        self.assertIn('external_evidence',result['diff'])
        self.assertNotIn('tool_baseline',self.state['native_change'])
