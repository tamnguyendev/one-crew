"""Shared worker ports and their legacy APIs use one implementation."""
import unittest
from unittest.mock import patch

from onecrew import artifact_provider_core as workers, process_core, providers, supervisor, workflow
from onecrew.ledger import LedgerError


class SharedWorkerPortsTests(unittest.TestCase):
    def test_legacy_worker_types_and_process_ports_are_the_shared_objects(self):
        self.assertIs(workflow.CodexArtifact, workers.CodexArtifact)
        for name in ('ClaudeArtifact', 'KiroArtifact', 'kiro_stream', 'json_object', 'make_worker'):
            self.assertIs(getattr(providers, name), getattr(workers, name))
        for name in ('Supervisor', 'Job', 'identity', 'probe', 'native_python', 'validate_executable'):
            self.assertIs(getattr(supervisor, name), getattr(process_core, name))
        for provider, cls in [('codex', workers.CodexArtifact), ('claude', workers.ClaudeArtifact), ('kiro', workers.KiroArtifact)]:
            self.assertIs(type(workers.make_worker(None, provider)), cls)
        with self.assertRaises(LedgerError): workers.make_worker(None, 'unconfigured')

    def test_legacy_and_core_capability_probes_keep_explicit_ports(self):
        with patch.object(providers, 'executable', return_value=None) as legacy:
            self.assertFalse(providers.doctor('codex')['available'])
            legacy.assert_called_once_with('codex')
        calls = []
        self.assertFalse(workers.doctor('claude', executable_fn=lambda name: calls.append(name))['available'])
        self.assertEqual(calls, ['claude'])
