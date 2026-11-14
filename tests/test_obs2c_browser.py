"""OBS-2C on the real page: the tracking server over tests/obs2c_fixture's ledger, driven in a headless browser at 1280 and 390 px by the
shared harness (tests/obs1_ux_harness.py + the obs2c scenario): paging and load more, search beyond the loaded rows, the source filter, the
finished filter, the relation section of a repair, no horizontal overflow. A missing browser is a skip, never a pass."""
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import tracking_web
from tests import obs1_ux_harness as ux
from tests import obs2c_fixture as fx
from tests.obs2c_ux_harness import HARNESS
from tests.test_obs1_web import find_browser


class ListBrowser(unittest.TestCase):
    def test_list_paging_filters_and_relations_desktop_and_phone(self):
        work = tempfile.mkdtemp(prefix='obs2c-browser-')
        self.addCleanup(shutil.rmtree, work, True)
        profile = Path(work) / 'browser'
        browser = find_browser(profile)
        if not browser:
            self.skipTest('No executable browser')
        fixture = fx.create(Path(work) / 'data', 150)
        server = tracking_web.make_server(fixture['state_root'], interval=1)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        out = Path(os.environ.get('OBS2C_UX_DIR', work))
        out.mkdir(parents=True, exist_ok=True)
        with patch.object(ux, 'HARNESS', HARNESS):
            proxy = ux.Proxy(tracking_web.url_of(server))
            self.addCleanup(proxy.stop)
            for size in ('desktop', 'mobile'):
                width, height = ux.SIZES[size]
                result = ux.run(browser, proxy.url, 'obs2c', width, height, profile, budget=400000, realtime=True)
                (out / ('obs2c-' + size + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                self.assertTrue(result.get('ok'), json.dumps({k: result.get(k) for k in ('error', 'notes', 'checks', 'tail')}, ensure_ascii=False)[:3000])
                self.assertGreaterEqual(len(result['checks']), 20)


if __name__ == '__main__':
    unittest.main()
