"""OBS-1 dev12, lane R23 — the Codex release review findings R2 and R3 of 03/11/2026 (D:/OneCrewRuns/codex-obs1-release-review/review.json,
api-audit.json, http-redaction.json, audit.py), as red-before-green tests over the real path: a real temporary ledger, the real engine,
executors.observe / progress_track.observe, the HTTP server of tracking_web and the `track` CLI.

R2 (project-only scope leaks another project's registry metadata): a model or a server scoped to project A answers with nothing of any other
project — no path, no state root, no project_id, no title — anywhere in the body (overview, task, error bodies), the untracked registry list
included. The scope is compared by the ledger's own identity (Ledger.project_id = digest(normcase(resolved path))), never by a string prefix.
All-projects mode keeps listing every registry project without a plan; an all-projects server narrowed with ?project_id=A behaves like scope A;
a project registered without a plan still sees its own entry under its own scope.

R3 (a known secret pattern bypasses redaction through observation references): no known secret shape that the ledger holds in any free-text
field the tracking model projects comes out raw in overview/detail JSON, the HTTP bodies or the `track list/show` JSON and text; normal
references, ids, paths, blob keys and reply templates come out unchanged.
"""
import contextlib
import io
import json
import os
import re
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, executors, plan as plans, progress_track, tracking, tracking_cli, tracking_web
from tests.test_v2_l1 import Fixture, plan_json
from tests.test_wf_engine import EngineFixture, node


class Managed(executors.Executor):
    declaration = executors.Declaration('fixture-managed', 'managed', ('measure',), ('time',))


def _forms(needle):
    """The ways a value can be spelled in a body: as is, JSON-escaped (a Windows path doubles its backslashes) and with forward slashes."""
    return {needle.casefold(), json.dumps(needle, ensure_ascii=False)[1:-1].casefold(), needle.replace('\\', '/').casefold()}


def leaks(text, needles):
    low = text.casefold()
    return sorted({n for n in needles if any(f in low for f in _forms(n))})


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r: return r.status, r.read().decode('utf-8')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8')


def serve(case, state_root, project_id=None):
    server = tracking_web.make_server(state_root, project_id=project_id)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True); thread.start()
    def stop():
        server.shutdown(); server.server_close(); thread.join(5)
    case.addCleanup(stop)
    return tracking_web.url_of(server)


def cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = tracking_cli.main(list(args))
    return code, out.getvalue()


def git_project(path):
    path.mkdir(parents=True); (path / 'a.txt').write_text('test')
    for args in (('init', '-q'), ('config', 'user.name', 'T'), ('config', 'user.email', 't@local'), ('add', '.'), ('commit', '-qm', 'init')):
        subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True)
    return path


# ---- R2: the project scope covers the whole returned model ---------------------------------------------------------------------------

class R2ScopeCoversEverything(Fixture):
    maxDiff = None
    """Ledger S holds project A (plan P1) and project B (plan P2, a private title). The registry (an isolated LOCALAPPDATA) knows A — spelled
    through a `..` segment, the same identity — plus B, OTHER-PRIVATE-PROJECT with its own OTHER-PRIVATE-LEDGER, a sibling whose path merely
    starts with A's path, and C, registered on S without any plan."""
    def setUp(self):
        super().setUp()
        base = Path(self.temp.name)
        self.propose('P1')
        self.ledger_b = Ledger(git_project(base / 'projectB'), self.ledger.state_root)
        plans.propose(self.ledger_b, 'P2', plan_json(title='PROJECT B PRIVATE GOAL'), 'claude')
        self.other_project, self.other_ledger = base / 'OTHER-PRIVATE-PROJECT', base / 'OTHER-PRIVATE-LEDGER'
        self.sibling = Path(str(self.root) + '-sibling-private')
        self.c_path = base / 'registered-C-no-plan'
        self.c_id = Ledger(git_project(self.c_path), self.ledger.state_root).project_id
        self.a_spelled = str(base / 'zz' / '..' / 'project')                  # not the ledger's string, the same project
        os.environ['LOCALAPPDATA'] = str(base / 'lad')
        registry = base / 'lad' / 'OneCrew'; registry.mkdir(parents=True)
        (registry / 'hook-projects.json').write_text(json.dumps({'projects': {
            self.a_spelled: str(self.ledger.state_root), self.ledger_b.project_path: str(self.ledger.state_root),
            str(self.other_project): str(self.other_ledger), str(self.sibling): str(self.ledger.state_root),
            str(self.c_path): str(self.ledger.state_root)}}), encoding='utf-8')
        self.a, self.b = self.ledger.project_id, self.ledger_b.project_id

    def outside_a(self):
        """Everything that belongs to another project than A: paths, state roots, ids (full and the 12-char prefix the messages use), titles."""
        return [self.ledger_b.project_path, self.b, self.b[:12], 'PROJECT B PRIVATE', str(self.other_project), str(self.other_ledger), 'OTHER-PRIVATE',
                str(self.sibling), 'sibling-private', str(self.c_path), self.c_id, self.c_id[:12], 'registered-C-no-plan']

    def registry_list(self, value):
        return sorted(os.path.normcase(r['project']) for r in value['untracked']['registry_projects_without_plan'])

    def test_model_scoped_to_a_holds_nothing_of_another_project(self):
        value = tracking.overview(self.ledger.state_root, project_id=self.a)
        body = json.dumps(value, ensure_ascii=False)
        self.assertEqual(leaks(body, self.outside_a()), [], 'scope A overview carries other projects: ' + json.dumps(value['untracked']['registry_projects_without_plan'], ensure_ascii=False))
        self.assertEqual(leaks(tracking.render_overview(value), self.outside_a()), [], 'scope A text carries other projects')
        self.assertEqual(value['untracked']['registry_projects_without_plan'], [], 'A has a plan: its own entry (another spelling, same identity) is not "without plan"')
        self.assertEqual([t['plan'] for p in value['projects'] for t in p['tasks']], ['P1'])
        detail = tracking.detail(self.ledger.state_root, 'P1', project_id=self.a)
        self.assertEqual(leaks(json.dumps(detail, ensure_ascii=False), self.outside_a()), [])
        self.assertEqual(leaks(tracking.render_detail(detail), self.outside_a()), [])

    def test_model_all_projects_lists_every_registered_project_without_a_plan(self):
        value = tracking.overview(self.ledger.state_root)
        expected = sorted(os.path.normcase(str(p)) for p in (self.other_project, self.sibling, self.c_path))
        self.assertEqual(self.registry_list(value), expected,
                         'all projects: the registry projects without a plan in this ledger (B has P2, A has P1 under another spelling of its path)')
        other = next(r for r in value['untracked']['registry_projects_without_plan'] if 'OTHER-PRIVATE' in r['project'])
        self.assertEqual(other['state_root'], str(self.other_ledger)); self.assertFalse(other['same_state_root'])

    def test_a_project_registered_without_a_plan_still_sees_its_own_entry(self):
        value = tracking.overview(self.ledger.state_root, project_id=self.c_id)
        self.assertEqual(self.registry_list(value), [os.path.normcase(str(self.c_path))])
        self.assertEqual(value['projects'], [])
        body = json.dumps(value, ensure_ascii=False)
        self.assertEqual(leaks(body, [self.ledger.project_path, self.a, self.ledger_b.project_path, self.b, 'OTHER-PRIVATE', 'sibling-private', 'PROJECT B PRIVATE']), [])

    def test_a_project_only_server_never_shows_another_project_anywhere(self):
        base = serve(self, self.ledger.state_root, self.a)
        key = Snapshots(self.ledger.state_root).blob(b'not named by P1')
        paths = ['api/overview', 'api/overview?project_id=' + self.a, 'api/task?plan=P1', 'api/task?plan=P2', 'api/task?plan=NOPE', 'api/health',
                 f'api/evidence?plan=P1&key={key}', 'api/evidence?plan=P1&key=zz', 'api/task', 'api/nowhere',
                 'api/overview?project_id=' + self.b, 'api/task?plan=P2&project_id=' + self.b, 'api/overview?project_id=' + self.c_id]
        found = {}
        for path in paths:
            status, body = get(base + path)
            bad = leaks(body, self.outside_a())
            if path.endswith(('project_id=' + self.b, 'project_id=' + self.c_id)):
                self.assertEqual(status, 403, path)                                         # a query may narrow, never widen (P2-04 kept)
            if bad: found[path] = (status, bad)
        self.assertEqual(found, {}, 'a project-only server for A shows other projects')
        status, body = get(base + 'api/overview')
        self.assertEqual(status, 200); self.assertEqual(json.loads(body)['untracked']['registry_projects_without_plan'], [])

    def test_an_all_projects_server_lists_them_and_narrowed_to_a_hides_them(self):
        base = serve(self, self.ledger.state_root, None)
        status, body = get(base + 'api/overview')
        self.assertEqual(status, 200)
        self.assertEqual(self.registry_list(json.loads(body)), sorted(os.path.normcase(str(p)) for p in (self.other_project, self.sibling, self.c_path)))
        for path in ('api/overview?project_id=' + self.a, 'api/task?plan=P1&project_id=' + self.a, 'api/task?plan=P2&project_id=' + self.a):
            status, body = get(base + path)
            self.assertEqual(leaks(body, self.outside_a()), [], path)
        self.assertEqual(json.loads(get(base + 'api/overview?project_id=' + self.a)[1])['untracked']['registry_projects_without_plan'], [])

    def test_track_list_of_a_project_holds_nothing_of_another(self):
        common = ['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'track']
        for args in (['list', '--json'], ['list'], ['show', 'P1', '--json'], ['show', 'P1'], ['show', 'P2']):
            code, out = cli(*common, *args)
            self.assertEqual(leaks(out, self.outside_a()), [], args)
        code, out = cli(*common, 'list', '--json', '--all-projects')
        self.assertIn('OTHER-PRIVATE-PROJECT', out)                                          # all projects: authorized, kept


# ---- R3: no known secret shape leaves through any projection --------------------------------------------------------------------------

CODEX_REF = 'password=codex_synthetic_secret_9281'
CODEX_SECRET = 'codex_synthetic_secret_9281'
ANT = 'sk-ant-' + 'SYNTHant' + 'Q' * 24
SHAPES = {                         # the text written into the ledger -> the raw part that must never come out
    'password': ('password=SYNTHpw7711zz', 'SYNTHpw7711zz'),
    'token': ('token: SYNTHtok8822zz', 'SYNTHtok8822zz'),
    'bearer': ('Authorization: Bearer SYNTHbearer9933zz', 'SYNTHbearer9933zz'),
    'anthropic': (ANT, ANT[7:]),
    'userinfo': ('https://deploy:SYNTHurlpw4455@example.invalid/repo.git', 'SYNTHurlpw4455'),
}
RAW = [raw for _, raw in SHAPES.values()] + [CODEX_SECRET]
NORMAL_REFS = ['codex-history-fixture-12', 'tool_call:toolu_01ABCdef-2', 'D:/Some Folder/with space/receipt 1.txt', 'https://example.invalid/a/b?x=1&y=2']


def where(text, secrets_=RAW):
    """Each raw secret found, with a little context: the assertion message shows the defect."""
    out = []
    for raw in secrets_:
        i = text.find(raw)
        if i >= 0: out.append(f'{raw} ...{text[max(0, i - 60):i + len(raw) + 10]}...')
    return out


class R3Fixture(EngineFixture):
    maxDiff = None
    def anchor(self, name='P1'):
        with self.ledger.transaction() as conn:
            return plans.anchor_events(self.ledger, conn, name)['task_id']

    def emit(self, kind, payload, name='P1'):
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, plans.anchor_events(self.ledger, conn, name)['task_id'], kind, payload)

    def settled_attempt(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        self.step()
        return tracking.detail(self.ledger.state_root, 'P1')['nodes']['A']['attempt']

    def wait(self, attempt, ref, at='2026-11-03T10:00:00+00:00', until='2026-11-03T10:00:01+00:00'):
        return executors.observe(self.ledger, 'P1', Managed(), attempt, 'wait', source='tool_call', ref=ref, at=at, until=until, wait_reason='external_service')

    def outputs(self, server=True):
        """Every projection a reader gets: the model's JSON, its text, the HTTP bodies, the CLI JSON and text."""
        root, state = str(self.root), str(self.ledger.state_root)
        out = {'overview.json': json.dumps(tracking.overview(self.ledger.state_root), ensure_ascii=False),
               'overview.text': tracking.render_overview(tracking.overview(self.ledger.state_root)),
               'detail.json': json.dumps(tracking.detail(self.ledger.state_root, 'P1', timeline_limit=5000), ensure_ascii=False),
               'detail.text': tracking.render_detail(tracking.detail(self.ledger.state_root, 'P1', timeline_limit=5000))}
        common = ['--project', root, '--state-root', state, 'track']
        for label, args in (('cli.list.json', ['list', '--json', '--all-projects']), ('cli.list.text', ['list', '--all-projects']),
                            ('cli.show.json', ['show', 'P1', '--json', '--timeline', '5000']), ('cli.show.text', ['show', 'P1', '--timeline', '5000'])):
            out[label] = cli(*common, *args)[1]
        if server:
            base = serve(self, self.ledger.state_root, None)
            for path in ('api/overview', 'api/task?plan=P1', 'api/task?plan=P1&timeline=5000', 'api/health'):
                out['http ' + path] = get(base + path)[1]
        return out

    def assertNoSecret(self, outputs, secrets_=RAW):
        found = {label: where(text, secrets_) for label, text in outputs.items()}
        found = {k: v for k, v in found.items() if v}
        self.assertEqual(found, {}, 'raw secrets in the outward projections:\n' + json.dumps(found, ensure_ascii=False, indent=1))


class R3CodexCase(R3Fixture):
    def test_the_codex_wait_reference_is_masked_in_every_projection(self):
        attempt = self.settled_attempt()
        self.wait(attempt, CODEX_REF)
        self.assertEqual(tracking.clean(CODEX_REF), 'password=[withheld]')               # the existing redaction knows this shape
        d = tracking.detail(self.ledger.state_root, 'P1')
        self.assertEqual([w['ref'] for w in d['waits'] if w['source'] == 'executor.observed'], ['password=[withheld]'], d['waits'])
        self.assertEqual([w['ref'] for w in d['measure']['executor_waits']], ['password=[withheld]'], d['measure']['executor_waits'])
        self.assertNoSecret(self.outputs(), [CODEX_SECRET])

    def test_the_ledger_keeps_the_original_reference(self):
        attempt = self.settled_attempt()
        self.wait(attempt, CODEX_REF)
        self.outputs(server=False)
        with self.ledger.transaction() as conn:
            refs = [json.loads(r[0]).get('basis', {}).get('ref') for r in conn.execute("SELECT payload FROM events WHERE kind='executor.observed'")]
        self.assertIn(CODEX_REF, refs)                                                      # reading redacts the view, never the ledger


class R3Sweep(R3Fixture):
    def test_secret_shapes_in_every_projected_free_text_field_never_come_out_raw(self):
        attempt = self.settled_attempt()
        base = Path(self.temp.name)
        for i, (name, (text, raw)) in enumerate(SHAPES.items()):
            self.wait(attempt, text[:200], at=f'2026-11-03T10:0{i}:00+00:00', until=f'2026-11-03T10:0{i}:30+00:00')            # waits[].ref, executor_waits[].ref
            progress_track.observe(self.ledger, 'P1', 'A', Managed(), attempt, 'k-' + name, {'kind': 'tool', 'action': 'read', 'args': {'path': 'a.txt'}, 'result': {'text': 'one'}, 'snapshot': 'snap-' + name},
                                   source='tool_call', ref=text[:200])                                                         # progress basis ref
        joined = ' | '.join(SHAPES[k][0] for k in ('password', 'token', 'anthropic', 'userinfo', 'bearer'))   # the header shape LAST: it hides the rest of its line
        # raw ledger events in free-text fields the model projects (the ledger may hold text written by any version or writer)
        self.emit('executor.observed', {**Managed.declaration.view(), 'received_at': '2026-11-03T11:05:00+00:00', 'plan': 'P1', 'attempt': attempt, 'what': 'wait', 'observed_at': '2026-11-03T11:00:00+00:00', 'time_source': 'tool_call',
                                        'basis': {'type': 'tool_call', 'ref': 'wait-raw-1'}, 'wait': {'reason': 'reason ' + joined, 'until': '2026-11-03T11:00:05+00:00'}})
        self.emit('executor.observed', {**Managed.declaration.view(), 'received_at': '2026-11-03T11:05:00+00:00', 'plan': 'P1', 'attempt': attempt, 'what': 'progress', 'node': 'A', 'generation': 0, 'observed_at': '2026-11-03T11:01:00+00:00',
                                        'time_source': 'tool_call', 'basis': {'type': 'tool_call', 'ref': 'basis ' + joined},
                                        'observation': {'kind': 'kind ' + SHAPES['password'][0]},
                                        'checkpoint': {'status': 'progressing', 'reason': 'progress ' + joined}})
        self.emit('workflow.mode', {'node': 'I', 'mode': 'wait', 'mode_reasons': ['mode ' + joined]})
        self.emit('notice.exception', {'category': 'cat ' + SHAPES['token'][0], 'reason': 'notice ' + joined, 'user_action': 'do ' + joined,
                                       'evidence': [t for t, _ in SHAPES.values()]})
        self.emit('decision.recorded', {'subject': {'component': 'comp ' + SHAPES['password'][0]}, 'basis': 'Q9 ' + joined, 'scope': 'I'})
        self.emit('workflow.checkpoint', {'phase': 'phase ' + SHAPES['password'][0], 'message': 'checkpoint ' + joined})
        with self.ledger.transaction(write=True) as conn:                                                        # verification results and verdicts
            view = engine.state(self.ledger, 'P1', conn)
            engine._event(self.ledger, conn, view, 'A', 'node.verification', receipt='0' * 64, result='fail ' + joined)
        self.emit('verdict.recorded', {'milestone': 'M1 ' + SHAPES['token'][0], 'result': 'fail ' + joined, 'by': 'reviewer ' + SHAPES['password'][0], 'receipt': None})
        with self.ledger.transaction(write=True) as conn:
            view = engine.state(self.ledger, 'P1', conn)
            engine._event(self.ledger, conn, view, 'I', 'node.held', reason='held ' + joined, classification='class ' + SHAPES['token'][0])
        question = {'schema_version': 1, 'question': 'question ' + joined, 'reason': 'why ' + joined, 'impact': 'impact ' + joined,
                    'options': [{'id': 'seven', 'label': 'label ' + joined}, {'id': 'thirty', 'label': SHAPES['bearer'][0]}],
                    'recommendation': 'seven', 'action': {'type': 'clarify', 'parameters': {'note': joined}}}
        self.ledger.create_request(self.anchor(), 'retention-secret', question)
        value = plan_json(); value['title'] = 'title ' + joined
        value['understanding']['restated_goal'] = 'goal ' + joined
        plans.propose(self.ledger, 'P2', value, 'codex', workflow=True, capabilities=self.engine_caps)
        from onecrew.task_intake import submit
        v1 = submit(self.ledger, 'v1 title ' + joined, 'v1-secret-job')
        with self.ledger.transaction(write=True) as conn:
            self.ledger._event(conn, v1['id'], 'workflow.checkpoint', {'phase': 'phase ' + SHAPES['token'][0], 'message': 'm', 'verification': {}, 'acceptance': 'x', 'snapshot': None})
        hook = self.root / '.onecrew'; hook.mkdir(exist_ok=True)
        (hook / 'hook-state.json').write_text(json.dumps({SHAPES['password'][0]: {'stop_blocks': 1}, 'session ' + SHAPES['token'][0]: {'stop_blocks': 0}}), encoding='utf-8')
        os.environ['LOCALAPPDATA'] = str(base / 'lad')
        registry = base / 'lad' / 'OneCrew'; registry.mkdir(parents=True)
        (registry / 'hook-projects.json').write_text(json.dumps({'projects': {str(base / 'proj password=SYNTHpw7711zz'): 'D:/state token: SYNTHtok8822zz'}}), encoding='utf-8')
        outputs = self.outputs()
        base_url = serve(self, self.ledger.state_root, None)
        for path in ('api/task?plan=' + urllib.parse.quote(SHAPES['password'][0]), 'api/evidence?plan=P1&key=' + urllib.parse.quote(SHAPES['token'][0])):
            outputs['http error ' + path] = get(base_url + path)[1]
        self.assertNoSecret(outputs)
        d = json.loads(outputs['detail.json'])
        self.assertTrue(d['waits'] and d['measure'].get('executor_waits') and d['notices'] and d['requests'] and d['needs_user'], 'the sweep reached the projected fields: ' + json.dumps(d['measure'], ensure_ascii=False)[:600])


class R3NormalValuesStay(R3Fixture):
    def test_normal_references_ids_paths_keys_and_reply_templates_come_out_unchanged(self):
        attempt = self.settled_attempt()
        from tests.obs2_binding_fixture import bind
        bind(self, self.ledger)
        for i, ref in enumerate(NORMAL_REFS):
            self.wait(attempt, ref, at=f'2026-11-03T10:0{i}:00+00:00', until=f'2026-11-03T10:0{i}:30+00:00')
        request = self.ledger.create_request(self.anchor(), 'retention', {'schema_version': 1, 'question': 'Giữ CV bao lâu?', 'reason': 'r', 'impact': 'i',
                                                                          'options': [{'id': 'seven', 'label': '7 ngày'}, {'id': 'thirty', 'label': '30 ngày'}], 'recommendation': 'seven',
                                                                          'action': {'type': 'clarify', 'parameters': {}}})
        d = tracking.detail(self.ledger.state_root, 'P1')
        self.assertEqual(sorted(w['ref'] for w in d['waits'] if w['source'] == 'executor.observed'), sorted(NORMAL_REFS))
        self.assertEqual(sorted(w['ref'] for w in d['measure']['executor_waits']), sorted(NORMAL_REFS))
        self.assertEqual(d['id'], self.anchor()); self.assertEqual(d['project'], self.ledger.project_path); self.assertEqual(d['project_id'], self.ledger.project_id)
        self.assertEqual(d['nodes']['A']['attempt'], attempt); self.assertRegex(attempt, r'^ATT-[0-9a-f]{32}$')
        self.assertIn(d['nodes']['A']['receipt'], d['evidence_keys'])
        self.assertTrue(all(re.fullmatch(r'[0-9a-f]{64}', k) for k in d['evidence_keys']) and d['evidence_keys'])
        need = next(n for n in d['needs_user'] if n['kind'] == 'request')
        prefix = tracking._runtime() + f" --project {tracking._quote(self.ledger.project_path)} --state-root {tracking._quote(str(self.ledger.state_root))}"
        self.assertEqual(need['id'], request['id'])
        self.assertEqual(need['reply_command'], f"{prefix} question answer {request['id']} --revision {request['revision']} --choice <option-id> --reference '{tracking.REFERENCE_PLACEHOLDER}'")
        self.assertEqual(need['options'][0]['reply_command'], need['reply_command'].replace('<option-id>', 'seven'))
        text = tracking.render_detail(d)
        self.assertIn(need['reply_command'], text)
        for ref in NORMAL_REFS: self.assertIn(ref, json.dumps(d, ensure_ascii=False))
        self.assertNotIn('[withheld]', json.dumps(d, ensure_ascii=False))
        base = serve(self, self.ledger.state_root, None)
        http = json.loads(get(base + 'api/task?plan=P1')[1])
        self.assertEqual(http['needs_user'], d['needs_user'])
        self.assertEqual(sorted(w['ref'] for w in http['waits'] if w['source'] == 'executor.observed'), sorted(NORMAL_REFS))
        self.assertEqual(http['evidence_keys'], d['evidence_keys'])


if __name__ == '__main__':
    import unittest
    unittest.main()
