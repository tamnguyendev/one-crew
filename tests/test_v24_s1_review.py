"""2.4-S1 after the independent review of 1c81f5d (D:/OneCrewRuns/v24/review-s1/review-s1.md): one counterexample per finding.

R01 secrets beyond display_core.safe; R02 the support anchor / a foreign task as --task; R03 the bundle cap over every source; R04 in_progress
only for an approved open plan; R05 a spooled report keeps its reporting runtime; R06 a malformed spool file never blocks the others, and a
report spooled from a subfolder is found; R07 the deny rule and owner claims inside an AI session; R08 a resend without --key is the same
feedback; P3a the support anchor is never executable; P3c the fallback names the real error class; P3e an export through a link.
"""
import json
import os
import shutil
from pathlib import Path
from unittest.mock import patch

from onecrew import task_intake
from onecrew.control_core import Control, migrate
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import hook_cli, plan as plans
from tests.test_v24_s1_bundle import link_dir
from tests.test_v24_s1_intake import FailedNodeFixture, S1Fixture, support

SECRETS = ['Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.BEARERSECRETPAYLOAD.sig',
           'GET https://acct.blob.core.windows.net/c/f?sv=2020-08-04&sig=SASSIGNATURESECRET123',
           'clone https://TOKENONLYSECRET123456@git.example/x.git',
           'curl -H "X-Api-Key: XAPIKEYSECRET99999" https://api.example',
           'export AWS_SECRET_ACCESS_KEY=AWSSECRETKEYVALUE1234',
           '--password hunter2HUNTERSECRET']
MARKERS = (b'BEARERSECRETPAYLOAD', b'SASSIGNATURESECRET123', b'TOKENONLYSECRET123456', b'XAPIKEYSECRET99999', b'AWSSECRETKEYVALUE1234',
           b'HUNTERSECRET')


def exported(made):
    folder = Path(made['export'])
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file()}


class BundleReviewTests(FailedNodeFixture):
    def setUp(self):
        super().setUp()
        self.logs = self.ledger.state_root / 'attempts' / self.attempt
        self.logs.mkdir(parents=True, exist_ok=True)

    def bundle(self, fb, out=None):
        code, made = self.cli('support', 'bundle', fb, *(['--out', str(out)] if out else []))
        self.assertEqual(code, 0, made)
        return made

    def test_r01_six_secret_forms_withheld_rest_of_line_kept(self):
        (self.logs / 'stdout.txt').write_text('\n'.join(['ok line one', *SECRETS, 'ok line two']) + '\n', encoding='utf-8')
        code, made = self.report('--text', 'my call failed: Authorization: Bearer REPORTTEXTBEARER123456', '--attempt', self.attempt,
                                 '--expected', 'export GITHUB_TOKEN=ghp_' + 'A' * 30)
        bundle = self.bundle(made['id'], Path(self.temp.name) / 'export')
        whole = b''.join(exported(bundle).values())
        for marker in MARKERS + (b'REPORTTEXTBEARER123456', b'ghp_' + b'A' * 30): self.assertNotIn(marker, whole)
        stdout = next(v for k, v in exported(bundle).items() if k.endswith('stdout.txt')).decode('utf-8')
        self.assertIn('ok line one', stdout); self.assertIn('ok line two', stdout)
        self.assertIn('acct.blob.core.windows.net/c/f?sv=2020-08-04&sig=[withheld]', stdout)      # only the secret part goes
        self.assertIn('export AWS_SECRET_ACCESS_KEY=[withheld]', stdout)
        entry = next(s for s in bundle['manifest']['sources'] if s['source'] == 'attempt.stdout')
        self.assertEqual(entry['redaction']['lines_withheld'], 6)
        self.assertIn('not a guarantee', bundle['manifest']['redaction'])
        feedback = next(v for k, v in exported(bundle).items() if k.endswith('feedback.json')).decode('utf-8')
        self.assertIn('my call failed: Authorization: [withheld]', feedback)

    def test_r01_pem_block_withheld(self):
        (self.logs / 'stdout.txt').write_text('before\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktPEMBODY\n-----END OPENSSH PRIVATE KEY-----\n'
                                              'after\n', encoding='utf-8')
        code, made = self.report('--text', 'key in log', '--attempt', self.attempt)
        stdout = next(v for k, v in exported(self.bundle(made['id'], Path(self.temp.name) / 'pem')).items() if k.endswith('stdout.txt'))
        self.assertNotIn(b'PEMBODY', stdout); self.assertIn(b'before', stdout); self.assertIn(b'after', stdout)

    def test_r02_anchor_or_job_task_is_not_a_ref_and_other_reports_stay_out(self):
        code, private = self.report('--text', 'PRIVATE-OTHER-USER-REPORT about my login')
        with self.ledger.transaction() as conn:
            anchor = support()._anchor(conn, self.ledger.project_id)
        code, mine = self.report('--text', 'mine', '--task', anchor)
        self.assertNotIn('task', mine['refs']); self.assertIn('task', mine['refs_unresolved'])
        job = task_intake.submit(self.ledger, 'A v1 job', 'v1-job', mode='audit')['id']
        code, other = self.report('--text', 'about a job', '--task', job)
        self.assertIn('task', other['refs_unresolved'])
        code, child = self.report('--text', 'about the child', '--task', self.child)
        self.assertEqual((child['refs']['task'], child['refs']['root_task']), (self.child, self.root_task))
        whole = b''.join(exported(self.bundle(mine['id'], Path(self.temp.name) / 'r02')).values())
        self.assertNotIn(b'PRIVATE-OTHER-USER-REPORT', whole)

    def test_r03_cap_applies_to_every_source_oldest_first(self):
        (self.logs / 'stdout.txt').write_text('x' * 40000 + '\n', encoding='utf-8')
        code, made = self.report('--text', 'cap me', '--plan', 'P1', '--attempt', self.attempt)
        from onecrew.v2 import diagnostics
        with patch.object(diagnostics, 'BUNDLE_CAP', 9000):
            bundle = self.bundle(made['id'], Path(self.temp.name) / 'cap')
        sources = bundle['manifest']['sources']
        events = [s for s in sources if s['source'] == 'ledger.events']
        self.assertTrue(any(s['status'] == 'truncated' and 'bundle cap' in s['reason'] for s in events), events)
        files = sum(len(v) for k, v in exported(bundle).items() if k != 'manifest.json')
        self.assertEqual(files, bundle['total_bytes'])
        self.assertTrue(bundle['total_bytes'] <= 9000 or bundle['manifest']['over_cap'], bundle['total_bytes'])
        kept = [s for s in sources if s['file']]
        self.assertTrue(all(s['source'] in ('runtime', 'feedback', 'support.records', 'doctor') for s in kept) or bundle['total_bytes'] <= 9000)
        self.assertEqual(bundle['manifest']['caps']['bundle_bytes'], 9000)

    def test_p3e_export_through_a_link_refused(self):
        code, made = self.report('--text', 'link export')
        real = Path(self.temp.name) / 'real-out'; real.mkdir()
        link = Path(self.temp.name) / 'out-link'
        link_dir(link, real)
        code, refused = self.cli('support', 'bundle', made['id'], '--out', str(link))
        self.assertEqual(code, 2, refused); self.assertIn('link', refused['error'])
        into_state = Path(self.temp.name) / 'state-link'
        link_dir(into_state, self.ledger.state_root)
        code, refused = self.cli('support', 'bundle', made['id'], '--out', str(into_state / 'sub'))
        self.assertEqual(code, 2, refused)
        self.assertEqual(list(real.iterdir()), [])


class StatusReviewTests(S1Fixture):
    def test_r04_in_progress_only_for_an_approved_open_plan(self):
        code, made = self.report('--text', 'something broke')
        plans.propose(self.ledger, 'P9', __import__('tests.test_v2_l1', fromlist=['x']).plan_json(), 'claude')
        self.cli('support', 'link', made['id'], '--plan', 'P9')
        state = self.cli('support', 'status', made['id'], '--json')[1]
        self.assertFalse(state['in_progress']['value']); self.assertEqual(state['linked'][0]['status'], 'proposed')
        plans.approve(self.ledger, 'P9', 'owner', 'fixture approval')
        self.assertTrue(self.cli('support', 'status', made['id'], '--json')[1]['in_progress']['value'])
        with self.ledger.transaction(write=True) as conn:
            task = plans.derive(self.ledger, conn, 'P9')['task_id']
            plans.emit(self.ledger, conn, task, 'milestone.stopped', {'plan': 'P9', 'revision': 1, 'milestone': 'M1', 'report': 'fixture'})
        state = self.cli('support', 'status', made['id'], '--json')[1]
        self.assertEqual(state['linked'][0]['status'], 'stopped_with_report'); self.assertFalse(state['in_progress']['value'])

    def test_r07_deny_rule_and_owner_claims_in_an_ai_session(self):
        deny = hook_cli.deny_rules(self.ledger.state_root)
        self.assertIn('Bash(*support confirm*)', deny); self.assertIn('PowerShell(*support confirm*)', deny)
        code, made = self.report('--text', 'who decides')
        for marker in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE'):
            with patch.dict(os.environ, {marker: '1'}):
                code, refused = self.cli('support', 'classify', made['id'], '--class', 'unclear', '--basis', 'x', '--by', 'owner')
                self.assertEqual(code, 2, refused)
                code, ok = self.cli('support', 'classify', made['id'], '--class', 'unclear', '--basis', 'x', '--by', 'claude')
                self.assertEqual(code, 0, ok); self.assertEqual(ok['by'], 'claude')
        code, owner = self.cli('support', 'classify', made['id'], '--class', 'unclear', '--basis', 'x', '--by', 'owner')
        self.assertEqual((code, owner['by']), (0, 'owner'))

    def test_r08_resend_without_key_is_the_same_feedback(self):
        code, first = self.report('--text', 'The build fails at step 3')
        code, again = self.report('--text', 'the build   fails at step 3')
        self.assertEqual((again['id'], again['duplicate']), (first['id'], True))
        code, other = self.report('--text', 'The build fails at step 4')
        self.assertNotEqual(other['id'], first['id'])
        from onecrew.v2 import support_spool
        lone = support_spool.record(text='spooled first, then sent again', project=self.root, state_root=self.ledger.state_root, reason='fixture')
        support_spool.spool(lone, project=self.root, state_root=self.ledger.state_root)
        code, direct = self.report('--text', 'spooled first, then sent again')
        code, imported = self.cli('support', 'import-spool')
        # S2-R05 (decision 01/11): a spooled report keeps its spool id as its key, so a planted spool file can never take a direct report's
        # key; the two are suggested as possible duplicates, never merged
        self.assertEqual(imported['imported'], [lone['id']])
        same = [e for e in self.support_events() if e['text'] == 'spooled first, then sent again']
        self.assertEqual(len(same), 2); self.assertIn(direct['id'], same[1]['possible_duplicates'])

    def test_p3a_the_support_anchor_is_never_executable(self):
        self.report('--text', 'records only')
        migrate(self.ledger)
        with self.ledger.transaction() as conn:
            row = conn.execute('SELECT id, revision FROM tasks WHERE request_key=?', (support().ANCHOR_KEY,)).fetchone()
        from onecrew.control import Control as LegacyControl
        for control in (Control(self.ledger), LegacyControl(self.ledger)):
            with self.assertRaises(LedgerError) as caught:
                control.configure(row['id'], row['revision'], {'max_calls': 1})
            self.assertIn('never executed', str(caught.exception))
        with self.ledger.transaction() as conn:
            self.assertIsNone(conn.execute('SELECT 1 FROM executions WHERE task_id=?', (row['id'],)).fetchone())


class SpoolReviewTests(S1Fixture):
    def corrupt(self):
        self.ledger.state_root.mkdir(parents=True, exist_ok=True)
        self.ledger.path.write_bytes(b'garbage, not sqlite' * 100)

    def test_r05_spooled_report_keeps_its_reporting_runtime(self):
        self.corrupt()
        code, made = self.report('--text', 'crash under the old build', '--key', 'rt-1')
        path = Path(made['path'])
        document = json.loads(path.read_text(encoding='utf-8'))
        self.assertIn('code_probe', document['runtime_probe']); self.assertIn('installed_vs_running', document['runtime_probe'])
        document['runtime_probe'].update(dist_version='2.3.0-THE-ONE-THAT-FAILED', installed_vs_running='same')
        path.write_text(json.dumps(document), encoding='utf-8')
        self.ledger.path.unlink()
        self.cli('support', 'import-spool')
        feedback = self.support_events()[0]
        self.assertEqual((feedback['runtime']['dist_version'], feedback['runtime']['source']), ('2.3.0-THE-ONE-THAT-FAILED', 'spool'))
        self.assertEqual(feedback['runtime_at_report'], feedback['runtime'])
        self.assertEqual(feedback['runtime_at_import']['source'], 'import')
        code, later = self.report('--text', 'crash under the old build', '--key', 'rt-2')
        self.assertEqual(later['possible_duplicates'], [])                       # another version: not suggested

    def test_r06_malformed_spool_rejected_the_rest_imported(self):
        from onecrew.v2 import support_spool
        good = support_spool.record(text='a valid spooled report', project=self.root, state_root=self.ledger.state_root, reason='fixture')
        folder = self.ledger.state_root / 'support-spool'
        support_spool.spool(good, project=self.root, state_root=self.ledger.state_root)
        bad = dict(good, id='FB-' + '0' * 32, client_key='bad-1', refs='x')
        (folder / (bad['id'] + '.json')).write_text(json.dumps(bad), encoding='utf-8')
        worse = dict(good, id='FB-' + '1' * 32, client_key='bad-2', image={'name': 'a', 'sha256': 'f' * 64, 'bytes': 'many'})
        (folder / (worse['id'] + '.json')).write_text(json.dumps(worse), encoding='utf-8')
        huge = dict(good, id='FB-' + '2' * 32, client_key='bad-3', error={'type': 'X', 'text': 'y' * 200000})
        (folder / (huge['id'] + '.json')).write_text(json.dumps(huge), encoding='utf-8')
        (folder / ('FB-' + '3' * 32 + '.json')).write_text('not json', encoding='utf-8')
        code, imported = self.cli('support', 'import-spool')
        self.assertEqual(code, 0, imported)
        self.assertEqual(imported['imported'], [good['id']])
        self.assertEqual(imported['counts'], {'imported': 1, 'already': 0, 'rejected': 4, 'skipped': 0})
        self.assertTrue((folder / 'rejected' / (bad['id'] + '.json')).is_file())
        self.assertIn('refs', (folder / 'rejected' / (bad['id'] + '.json.reason.txt')).read_text(encoding='utf-8'))
        self.assertEqual(len(self.support_events()), 1)

    def test_r13_report_spooled_from_a_subfolder_is_imported_from_the_root(self):
        from onecrew.v2 import support_spool
        sub = self.root / 'sub'; sub.mkdir()
        record = support_spool.record(text='from the subfolder', project=sub, state_root=self.ledger.state_root, reason='fixture')
        support_spool.spool(record, project=sub, state_root=self.ledger.state_root)
        code, imported = self.cli('support', 'import-spool')
        self.assertEqual(imported['imported'], [record['id']])

    def test_p3c_reason_names_the_real_error_class(self):
        self.corrupt()
        code, made = self.report('--text', 'database broken')
        self.assertTrue(made['reason'].startswith('DatabaseError'), made['reason'])
        blocker = Path(self.temp.name) / 'a-file'; blocker.write_text('x')
        code, made = self.cli('support', 'report', '--text', 'disk broken', '--json', state=blocker / 'state')
        self.assertTrue(made['reason'].startswith('OSError'), made['reason'])
        with patch.object(support(), 'report', side_effect=KeyError('a bug')):
            self.ledger.path.unlink()
            code, made = self.report('--text', 'code broken')
        self.assertTrue(made['spooled']); self.assertTrue(made['reason'].startswith('RuntimeError'), made['reason'])


class ReviewS2RedactionAndSpoolTests(S1Fixture):
    def test_s2_r11_more_secret_forms_withheld_rest_kept(self):
        from onecrew.v2.diagnostics import redact_line
        lines = {'DB_PASS=dbpasssecret123': 'DB_PASS=',
                 'DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=AZUREACCOUNTKEYSECRET==;EndpointSuffix=core.windows.net': 'EndpointSuffix=core.windows.net',
                 'Endpoint=sb://x.servicebus.windows.net/;SharedAccessKey=SBKEYSECRET123=': 'Endpoint=sb://x.servicebus.windows.net/',
                 '"output": "{\\"password\\": \\"escapedjsonsecret1\\"}"': '"output"',
                 'mysql -u root -pMYSQLINLINESECRET db': 'mysql -u root -p',
                 'authToken: authtokensecret123': 'authToken:',
                 'npm_TOKENSECRETnpmABCDEFGHIJKLMNOPQRSTUVWXYZ0123 in .npmrc': 'in .npmrc',
                 'glpat-GITLABSECRET1234567890 for the CI': 'for the CI'}
        for line, kept in lines.items():
            clean, hidden = redact_line(line)
            self.assertTrue(hidden, line); self.assertIn(kept, clean)
            for marker in ('dbpasssecret', 'AZUREACCOUNTKEY', 'SBKEYSECRET', 'escapedjsonsecret', 'MYSQLINLINE', 'authtokensecret', 'TOKENSECRETnpm', 'GITLABSECRET'):
                self.assertNotIn(marker, clean)
        self.assertEqual(redact_line('"author": "claude", "exit_code": 0, "client_key": "k1"'), ('"author": "claude", "exit_code": 0, "client_key": "k1"', False))

    def test_s2_r05_a_planted_spool_file_never_takes_a_direct_report_key(self):
        from onecrew.v2 import support_spool, support
        victim = support_spool.content_key('my real report', None, {}, support.runtime_probe()['dist_version'], None)
        planted = support_spool.record(text='planted text', key=victim, project=self.root, state_root=self.ledger.state_root, reason='planted')
        support_spool.spool(planted, project=self.root, state_root=self.ledger.state_root)
        code, imported = self.cli('support', 'import-spool')
        self.assertEqual(imported['counts']['rejected'], 1, imported)
        code, real = self.report('--text', 'my real report')
        self.assertEqual(code, 0, real)
