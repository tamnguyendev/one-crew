import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from onecrew.providers import doctor, ClaudeArtifact
from onecrew.subscription import environment, CODEX_AUTH_ARGS, CLAUDE_AUTH_ARGS
from onecrew.workflow import CodexArtifact


class SubscriptionTests(unittest.TestCase):
    def test_child_environment_preserves_oauth_and_host_without_mutation(self):
        source = {'Path':'native', 'SYSTEMROOT':'windows', 'CODEX_HOME':'account',
                  'CLAUDE_CODE_OAUTH_TOKEN':'subscription', 'openai_api_key':'paid',
                  'ANTHROPIC_AUTH_TOKEN':'paid', 'ANTHROPIC_BASE_URL':'alternate',
                  'CLAUDE_CODE_USE_BEDROCK':'1', 'CODEX_API_KEY':'paid',
                  'CHATGPT_BASE_URL':'alternate', 'CLAUDE_CODE_CLIENT_DATA_URL':'managed-policy'}
        result = environment(source)
        self.assertEqual(set(result), {'Path','SYSTEMROOT','CODEX_HOME','CLAUDE_CODE_OAUTH_TOKEN','CLAUDE_CODE_CLIENT_DATA_URL'})
        self.assertEqual(source['openai_api_key'], 'paid')

    def test_codex_rejects_api_unknown_failed_auth_and_uses_clean_environment(self):
        for status, code, available in [(b'Logged in using ChatGPT\n',0,True),
                                       (b'Logged in using an API key',0,False),
                                       (b'Logged in using ChatGPT',1,False),
                                       (b'unknown',0,False)]:
            with self.subTest(status=status,code=code), \
                 patch('onecrew.providers.executable',return_value='native.exe'), \
                 patch('onecrew.providers.subprocess.check_output',return_value=b'codex-cli 0.160.0'), \
                 patch.dict(os.environ,{'OPENAI_API_KEY':'fixture-secret'}), \
                 patch('onecrew.providers.subprocess.run',return_value=SimpleNamespace(returncode=code,stdout=b'',stderr=status)) as run:
                result = doctor('codex')
                self.assertEqual(result['available'], available and os.name == 'nt')
                self.assertNotIn('OPENAI_API_KEY',run.call_args.kwargs['env'])
                self.assertEqual(run.call_args.args[0][1:-2],CODEX_AUTH_ARGS)
                self.assertNotIn('fixture-secret',str(result))

    def test_claude_auth_must_be_subscription_and_successful(self):
        for method, code, expected in [('claude.ai',0,True),('api_key',0,False),('oauth',1,False)]:
            import json
            with patch('onecrew.providers.executable',return_value='native.exe'), \
                 patch('onecrew.providers.subprocess.check_output',return_value=b'2.1.286 (Claude Code)'), \
                 patch('onecrew.providers.subprocess.run',return_value=SimpleNamespace(returncode=code,stdout=json.dumps({'loggedIn':True,'authMethod':method}).encode())) as run:
                self.assertEqual(doctor('claude')['available'],expected and os.name == 'nt')
                self.assertEqual(run.call_args.args[0][1:-3], CLAUDE_AUTH_ARGS)

    def test_worker_launches_receive_auth_flags_and_clean_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fixture','OPENAI_API_KEY':'fixture'}):
            control = SimpleNamespace(ledger=SimpleNamespace(state_root=Path(directory)))
            codex = CodexArtifact(control)
            with patch.object(codex,'capability'), patch('onecrew.workflow.Supervisor.run') as run:
                codex.run({'id':'codex'},'prompt',{}, {'model':'fixture','step_seconds':10})
                argv = run.call_args.args[1]
                self.assertIn('forced_login_method="chatgpt"',argv)
                self.assertIn('model_provider="openai"',argv)
                self.assertNotIn('OPENAI_API_KEY',run.call_args.kwargs['env'])
            claude = ClaudeArtifact(control)
            with patch.object(claude,'capability'), patch('onecrew.providers.Supervisor.run') as run:
                claude.run({'id':'claude'},'prompt',{}, {'model':'fixture','step_seconds':10})
                argv = run.call_args.args[1]
                self.assertIn('--safe-mode',argv)
                self.assertIn('--restricted',argv)
                self.assertNotIn('--bare',argv)  # bare cannot use subscription OAuth
                self.assertNotIn('ANTHROPIC_API_KEY',run.call_args.kwargs['env'])

    def test_claude_diagnostics_identify_cli_without_exposing_auth_payload(self):
        import json
        data = {'loggedIn':False,'authMethod':'none','email':'private@example.invalid','token':'secret-fixture'}
        with patch('onecrew.providers.executable',return_value='C:/native/claude.exe'), \
             patch('onecrew.providers.subprocess.check_output',return_value=b'2.1.286 (Claude Code)'), \
             patch('onecrew.providers.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout=json.dumps(data).encode())):
            result = doctor('claude')
        self.assertEqual(result['executable'],'C:/native/claude.exe')
        self.assertEqual(result['login_argv'],['C:/native/claude.exe','auth','login','--claudeai'])
        self.assertIn('Desktop/browser',result['reason'])
        self.assertNotIn('private@',json.dumps(result))
        self.assertNotIn('secret-fixture',json.dumps(result))

    def test_claude_malformed_auth_is_unavailable_without_traceback(self):
        for raw in (b'[]',b'null',b'false',b'not-json',b'{"loggedIn":"true","authMethod":"oauth"}'):
            with self.subTest(raw=raw), \
                 patch('onecrew.providers.executable',return_value='native.exe'), \
                 patch('onecrew.providers.subprocess.check_output',return_value=b'2.1.286 (Claude Code)'), \
                 patch('onecrew.providers.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=raw)):
                result = doctor('claude')
                self.assertFalse(result['available'])
                self.assertFalse(result['live_verified'])
