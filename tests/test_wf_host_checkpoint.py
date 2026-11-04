"""T30 reads the existing host registry/lease without installing or starting it."""
import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest

from onecrew import host, host_status_core
from onecrew.process_core import identity


class HostCheckpointTests(unittest.TestCase):
    def test_missing_registration_is_read_only_and_never_claims_reboot_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / 'not-created'
            value = host_status_core.status(Path(temp) / 'state', base)
            self.assertFalse(value['registered']); self.assertFalse(value['alive']); self.assertFalse(value['served'])
            self.assertFalse(value['automatic_restart_after_reboot']); self.assertIn('reboot', value['text'])
            self.assertFalse(base.exists())

    def test_existing_v1_registration_and_real_pid_lease_are_the_source(self):
        with tempfile.TemporaryDirectory() as temp:
            base, state = Path(temp) / 'host', Path(temp) / 'state'
            base.mkdir(); state.mkdir(); host.register(state, base)
            record = {'identity': identity(os.getpid()), 'heartbeat': dt.datetime.now(dt.timezone.utc).isoformat(),
                      'roots_seen': {str(state.resolve()): {}}}
            host._write(base / 'lease.json', record)
            value = host_status_core.status(state, base)
            self.assertTrue(value['registered'] and value['alive'] and value['served'])
            self.assertFalse(value['automatic_restart_after_reboot'])
            host._write(base / 'lease.json', dict(record, heartbeat=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()))
            stale = host_status_core.status(state, base)
            self.assertTrue(stale['registered']); self.assertFalse(stale['alive']); self.assertFalse(stale['served'])
