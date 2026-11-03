"""OBS-1 UX — the INTERACTION layer: the real page in a real headless Chrome/Edge, driven by the same-origin harness (tests/obs1_ux_harness.py)
over the UX data set (tests/obs1_ux_fixture.py) served by the real tracking server. Skipped (never passed) when no browser on this machine
executes a page's script headlessly. Every scenario counts real polls; `ux01` also has the Python side write to the ledger while the reader
looks at an open section. Results and screenshots go to $OBS1_UX_DIR when set (the owner's evidence folder), else to the temp dir.
"""
import json
import os
import threading
import time
from pathlib import Path

from onecrew.v2 import tracking_web
from tests import obs1_ux_harness as ux
from tests.obs1_ux_fixture import populate
from tests.test_obs1_tracking import QUESTION
from tests.test_obs1_web import find_browser
from tests.test_wf_engine import EngineFixture

SCENARIOS = [('ux01', 'desktop'), ('ux02', 'desktop'), ('ux03', 'desktop'), ('ux04', 'desktop'), ('ux05', 'desktop'), ('ux06', 'desktop'), ('ux07', 'desktop'),
             ('ux08', 'desktop'), ('ux08', 'split'), ('ux08', 'mobile'), ('ux04', 'mobile'), ('ux01', 'mobile'), ('race', 'desktop'), ('disc', 'desktop'),
             ('clock', 'desktop'), ('ux03b', 'desktop'), ('ux03b', 'mobile'), ('gantt', 'desktop'), ('gantt', 'mobile'), ('p2a', 'desktop'), ('gantt_now', 'desktop'), ('evid', 'desktop'),
             ('stale_detail', 'desktop'), ('stale_detail', 'mobile')]


class BrowserUX(EngineFixture):
    def setUp(self):
        super().setUp()
        self.profile = Path(self.temp.name) / 'browser profile'
        self.browser = find_browser(self.profile)
        if not self.browser: self.skipTest('no headless Chrome/Edge executes script on this machine')
        populate(self)
        self.server = tracking_web.make_server(self.ledger.state_root, interval=1.0)
        threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.writes = []
        self.proxy = ux.Proxy(tracking_web.url_of(self.server), on_signal=self.signal); self.addCleanup(self.proxy.stop)
        self.out = Path(os.environ.get('OBS1_UX_DIR') or self.temp.name); self.out.mkdir(parents=True, exist_ok=True)

    def signal(self, name, params=None):
        if name == 'write':                                   # a second owner question on P1 while the page shows P1: the ledger seq moves
            request = self.ledger.create_request(self.root_view['anchor_task'], f'retention-{len(self.writes) + 2}', dict(QUESTION, question=f'Câu hỏi thứ {len(self.writes) + 2} (đến trong lúc đang đọc)?'))
            self.writes.append(request['id']); return request['id']
        if name == 'answer':                                  # the owner answers one question (fixture owner on the trial ledger) while the page is open
            from onecrew.v2 import questions
            from unittest.mock import patch
            row = self.ledger.request(params['id'])
            with patch.dict(os.environ):
                os.environ.pop('ONECREW_ACTOR', None); os.environ.pop('CLAUDE_CODE_CHILD_SESSION', None)
                questions.answer(self.ledger, params['id'], row['revision'], (row['question'].get('options') or [{'id': 'seven'}])[0]['id'], 'fixture owner answered while reading')
            return params['id']
        return None

    def run_one(self, scenario, size, **kw):
        width, height = ux.SIZES[size]
        result = ux.run(self.browser, self.proxy.url, scenario, width, height, self.profile, **kw)
        (self.out / f'ux-{scenario}-{size}.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
        return result

    def test_every_scenario_at_its_sizes(self):
        failures = []
        only = [x for x in (os.environ.get('OBS1_UX_ONLY') or '').split(',') if x]          # e.g. OBS1_UX_ONLY=gantt_now,evid while developing
        for scenario, size in SCENARIOS:
            if only and scenario not in only: continue
            result = self.run_one(scenario, size, budget=150000 if scenario == 'stale_detail' else 45000 if scenario in ('ux01', 'disc', 'clock', 'gantt', 'p2a', 'gantt_now', 'evid') else 30000)
            if not result.get('ok'): failures.append((scenario, size, result.get('error'), result.get('notes'), result.get('checks')))
            elif scenario == 'ux01': self.assertGreaterEqual(result.get('polls', 0), 5, result)
        self.assertEqual(failures, [], json.dumps(failures, ensure_ascii=False, indent=1))
        if not only: self.assertEqual(len(self.writes), 2)   # ux01 ran twice (desktop, mobile): two writes while reading

    def test_screenshots_of_the_states(self):
        shots = {}
        for name, scenario, size, extra in (('overview-desktop', 'shot-list', 'desktop', ''), ('detail-P4-desktop', 'shot-detail', 'desktop', '&plan=P4'), ('detail-P1-questions-desktop', 'shot-detail', 'desktop', '&plan=P1&open=need'), ('detail-P1-questions-mobile', 'shot-detail', 'mobile', '&plan=P1&open=need'),
                                            ('detail-P1-split', 'shot-detail', 'split', '&plan=P1'), ('overview-mobile', 'shot-list', 'mobile', ''), ('detail-P4-mobile', 'shot-detail', 'mobile', '&plan=P4')):
            width, height = ux.SIZES[size]
            shots[name] = ux.screenshot(self.browser, self.proxy.url, scenario, width, height, self.profile, self.out / f'ux-{name}.png', extra=extra)
        self.assertTrue(all(shots.values()), shots)
