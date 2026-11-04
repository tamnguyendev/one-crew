"""Real interaction tests. Browser absent means skipped, never passed."""
import json
import os
import threading
import tempfile
import unittest
import runpy
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import tracking_web
from tests import obs1_ux_harness as ux
from tests.obs2_ux_harness import HARNESS
from tests.test_obs1_web import find_browser


class WorkBrowser(unittest.TestCase):
    def test_work_views_desktop_and_mobile(self):
        temp = tempfile.TemporaryDirectory(prefix='obs2-browser-')
        self.addCleanup(temp.cleanup)
        profile = Path(temp.name) / 'browser'
        browser = find_browser(profile)
        if not browser:
            self.skipTest('No executable browser')
        scenario = Path(__file__).resolve().parents[1] / 'docs/obs2/tools/scenario_obs2.py'
        fixture = runpy.run_path(str(scenario))['create'](temp.name)
        server = tracking_web.make_server(fixture['state_root'], interval=1)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        out = Path(os.environ.get('OBS2_UX_DIR', temp.name))
        out.mkdir(parents=True, exist_ok=True)
        with patch.object(ux, 'HARNESS', HARNESS):
            proxy = ux.Proxy(tracking_web.url_of(server))
            self.addCleanup(proxy.stop)
            for size in ('desktop', 'mobile'):
                width, height = ux.SIZES[size]
                result = ux.run(browser, proxy.url, 'work', width, height, profile, budget=45000)
                (out / (size+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                self.assertTrue(result.get('ok'), result)
