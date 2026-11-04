"""A real settings binding in a disposable project; no registry or init calls."""
import json
from pathlib import Path
from unittest.mock import patch
from onecrew.v2 import hook_cli, tracking


def bind(test, ledger):
    exe=Path(test.temp.name)/'onecrew.exe'
    exe.write_bytes(b'fixture identity only; never execute')
    path=Path(ledger.project)/'.claude'/'settings.local.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(hook_cli.portable_settings(exe, ledger.state_root)),encoding='utf8')
    mocked=patch('onecrew.v2.tracking._runtime_exe',return_value=exe)
    mocked.start(); test.addCleanup(mocked.stop)
    test.assertTrue(tracking._runtime_binding(ledger.project,ledger.state_root)['verified'])
