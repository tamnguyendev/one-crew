"""T43a (W24) [E4], [E5], [E14], [E15]: the owner notices go through the v1 desktop channel only, open the right page, and wake no heartbeat.

[E14] a criteria grep over the W24 modules: no email/smtp/zalo/chat/webhook/outbound HTTP; the registered channel is the desktop one.
[E4]  the same modules name no heartbeat/scheduler switch, and publishing writes no heartbeat or automation configuration under the state root.
[E15] the approval, stopped and verified notices open the `plan present` page of their plan (open_content == render_present).
[E5]  publishing goes through v1's desktop core/outbox (integration counter), one launch per record, and a replay adds no second notice.
"""
import re
from pathlib import Path
from unittest.mock import patch

from onecrew import desktop_core, desktop_notifications as desktop
from onecrew.v2 import plan, report, verdict
from tests.test_v2_l1 import plan_json, milestone, BAD
from tests.test_wf_exceptions import ExceptionTests

ROOT = Path(__file__).resolve().parents[1]
MODULES = ['onecrew/v2/exceptions.py', 'onecrew/v2/notification_cli.py', 'onecrew/v2/notification_window.py',
           'onecrew/desktop_notifications.py', 'onecrew/desktop_core.py', 'onecrew/desktop_window.py', 'onecrew/notifications.py']
FORBIDDEN = re.compile(r'\b(smtp|smtplib|zalo|webhook|sendmail|email\.message|requests\.(post|get)|urllib\.request|http\.client|slack|telegram|discord)\b', re.I)
HEARTBEAT = re.compile(r'heartbeat|automation_update|schedule_heartbeat|CronCreate', re.I)


class ChannelTests(ExceptionTests):
    def test_e14_e4_only_the_desktop_channel_and_no_heartbeat_switch_in_the_notification_code(self):
        for rel in MODULES:
            text = (ROOT / rel).read_text(encoding='utf-8')
            self.assertFalse(FORBIDDEN.search(text), f'{rel}: {FORBIDDEN.search(text) and FORBIDDEN.search(text).group(0)}')   # [E14]
            self.assertFalse(HEARTBEAT.search(text), rel)                                                                     # [E4]

    def test_e15_e5_notices_open_plan_present_through_v1_desktop_core_once_per_record(self):
        desktop.configure(self.ledger, True)
        self.propose()                                                                                     # approval notice
        plan.approve(self.ledger, 'P1', 'owner', 'fixture')
        verdict.run(self.ledger, 'P1', 'M1')                                                               # verified notice
        self.approved('STOP', plan_json(milestones=[milestone(argv=BAD, max_repairs=0)]))
        verdict.run(self.ledger, 'STOP', 'M1')                                                             # stopped notice
        notices = {n['status']: n for n in self.notices()}
        self.assertEqual(set(notices), {'verified', 'stopped'})
        for status, notice in notices.items():
            self.assertEqual(notice['open_content'], report.render_present(self.ledger.state_root, notice['plan']), status)   # [E15]
        with patch.object(desktop_core, 'publish', wraps=desktop_core.publish) as core:
            desktop.publish(self.ledger)
            self.assertGreaterEqual(core.call_count, 1)                                                    # [E5] through the v1 core, not around it
        records = desktop.status(self.ledger)['records']
        self.assertEqual(len(records), 2); self.assertEqual(self.launch.call_count, 2)                     # one launch per record
        pages = {Path(record['report']).read_text(encoding='utf-8') for record in records}
        self.assertEqual(pages, {report.render_present(self.ledger.state_root, 'P1'), report.render_present(self.ledger.state_root, 'STOP')})   # [E15] the opened pages
        desktop.publish(self.ledger)                                                                       # replay
        self.assertEqual(len(desktop.status(self.ledger)['records']), 2); self.assertEqual(self.launch.call_count, 2)   # [E5] no second notice
        state_root = Path(self.ledger.state_root)
        configs = [p for p in state_root.rglob('*') if p.is_file() and HEARTBEAT.search(p.name)]
        self.assertEqual(configs, [])                                                                      # [E4] nothing enabled a heartbeat
        self.assertEqual(plan.show(self.ledger, 'STOP')['status'], 'stopped_with_report')                  # [E11] no acceptance from a notice
