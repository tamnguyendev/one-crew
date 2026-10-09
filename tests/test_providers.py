import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.providers import ClaudeArtifact, KiroArtifact, doctor
from onecrew.workflow import validate_profile


class ProviderTests(unittest.TestCase):
    def test_kiro_acp_chunks_metering_and_terminal_are_parsed(self):
        events = [
            {'type': 'sessionUpdate', 'data': {'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': '```json\n{"answer":true}\n```'}}}},
            {'type': 'metadata', 'data': {'meteringUsage': [{'value': .01, 'unit': 'credit'}]}},
            {'type': 'runFinished', 'data': {'status': 'success', 'stopReason': 'end_turn', 'finalTextTruncated': False}}
        ]
        worker = KiroArtifact(None)
        with patch.object(worker, 'stdout', return_value='\n'.join(json.dumps(e) for e in events)):
            value, usage = worker.result({})
        self.assertIs(value['answer'], True)
        self.assertEqual(usage[0]['metering'][0]['value'], .01)

    def test_kiro_missing_terminal_truncated_or_tools_are_rejected(self):
        worker = KiroArtifact(None)
        for event in ({'type': 'sessionUpdate', 'data': {'update': {'sessionUpdate': 'tool_call'}}},
                      {'type': 'runFinished', 'data': {'status': 'success', 'stopReason': 'end_turn', 'finalTextTruncated': True}},
                      {'type': 'metadata', 'data': {}}):
            with self.subTest(event=event), patch.object(worker, 'stdout', return_value=json.dumps(event)):
                with self.assertRaises(LedgerError):
                    worker.result({})

    def test_claude_result_boolean_is_strict(self):
        worker = ClaudeArtifact(None)
        value = {'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': {'answer': True}, 'usage': {'input_tokens': 1}}
        with patch.object(worker, 'stdout', return_value=json.dumps(value)):
            self.assertEqual(worker.result({})[0], {'answer': True})
        value['is_error'] = 'false'
        with patch.object(worker, 'stdout', return_value=json.dumps(value)):
            with self.assertRaises(LedgerError):
                worker.result({})

    def test_unauthenticated_claude_and_changed_version_are_unavailable(self):
        with patch('onecrew.providers.executable', return_value='native.exe'), \
             patch('onecrew.providers.subprocess.check_output', return_value=b'2.1.286 (Claude Code)'), \
             patch('onecrew.providers.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'{"loggedIn":false}')):
            result = doctor('claude')
        self.assertFalse(result['available'])
        self.assertFalse(result['authenticated'])
        with patch('onecrew.providers.executable', return_value='native.exe'), \
             patch('onecrew.providers.subprocess.check_output', return_value=b'codex-cli 99.0.0'):
            self.assertFalse(doctor('codex')['available'])


if __name__ == '__main__':
    unittest.main()
