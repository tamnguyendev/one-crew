"""OBS-1 R1 (Codex release review of dev11, P2): evidence identity, inheritance and bounded history are kept apart.

Blobs are content-addressed: two generations that write byte-identical output share ONE key, and a newer generation may legitimately produce
the very artifact it inherited. The tracking model therefore keeps one evidence entry per OCCURRENCE (event seq, key) with that event's own
kind, time, node, generation, attempt and role (where the key sits in the payload), built from the FULL history of the root and its child
tasks, never from the timeline display window; the evidence door checks membership against that same full history.

(a) identical bytes in two generations -> two occurrences, each with its own seq / kind / time / generation / attempt;
(b) resume from generation N's artifact K and produce K again in N+1 -> a `resume_artifact` occurrence (node.resumed) AND an `artifact`
    occurrence (node.produced of N+1 with its attempt); the current row inherits K from generation N with the source occurrence;
(c) a long history (310 appended observations; and > 5000 events for the door) -> the old generation keeps its outputs at any timeline limit,
    the door opens an old key, an event naming more than 6 keys keeps all of them;
(d) the provenance is identical for timeline limits 5, 300 and 5000.
"""
import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from onecrew.ledger import utcnow
from onecrew.v2 import engine, plan as plans, tracking, tracking_web
from tests.obs1_ux_fixture import Managed
from tests.test_wf_engine import EngineFixture, node


class Provenance(EngineFixture):
    def two_generations(self, resume_same=False):
        """Node A: generation 0 produces artifact-A / executor-A; a new generation (plain, or resuming from generation 0's own artifact)
        produces the very same bytes again. Returns (artifact key, receipt key, attempt of generation 0, attempt of generation 1)."""
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        self.step()
        artifact, receipt = self.store.blob(b'artifact-A'), self.store.blob(b'executor-A')
        att0 = tracking.detail(self.ledger.state_root, 'P1')['nodes']['A']['attempt']
        with self.ledger.transaction(write=True) as conn:
            view = engine.state(self.ledger, 'P1', conn)
            extra = {'resume_artifact': artifact, 'continues_attempt': att0} if resume_same else {}
            engine._event(self.ledger, conn, view, 'A', 'node.resumed', **extra)
        self.step()
        d = tracking.detail(self.ledger.state_root, 'P1', timeline_limit=5000)
        att1 = d['nodes']['A']['attempt']
        self.assertEqual((d['nodes']['A']['generation'], d['nodes']['A']['receipt']), (1, receipt))     # setup: same bytes, same key, next generation
        self.assertNotEqual(att0, att1)
        return artifact, receipt, att0, att1

    def root_task(self):
        with self.ledger.transaction() as conn:
            return plans.anchor_events(self.ledger, conn, 'P1')['task_id']

    def append_observations(self, count, attempt):
        with self.ledger.transaction(write=True) as conn:
            root = self.root_task()
            for i in range(count):
                plans.emit(self.ledger, conn, root, 'executor.observed', {**Managed.declaration.view(), 'plan': 'P1', 'attempt': attempt, 'what': 'progress', 'observed_at': None,
                                                                         'time_source': 'tool_call', 'received_at': utcnow(),
                                                                         'basis': {'type': 'tool_call', 'ref': f'r1-history-fixture-{i}'}, 'checkpoint': {'status': 'running'},
                                                                         'node': 'A', 'generation': 1})

    def http_detail(self, limit):
        server = tracking_web.make_server(self.ledger.state_root, interval=1.0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True); thread.start()
        try:
            url = tracking_web.url_of(server) + 'api/task?plan=P1&timeline=' + str(limit)
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode('utf-8'))
        finally:
            server.shutdown(); server.server_close()

    @staticmethod
    def events(d, kind, node_id='A'):
        return {e['generation']: e for e in d['timeline'] if e['kind'] == kind and e['node'] == node_id}

    @staticmethod
    def shape(x):
        return {k: x.get(k) for k in ('seq', 'key', 'kind', 'role', 'at', 'node', 'generation', 'attempt')}

    def test_a_identical_bytes_in_two_generations_stay_two_occurrences(self):
        artifact, receipt, att0, att1 = self.two_generations()
        d = tracking.detail(self.ledger.state_root, 'P1', timeline_limit=5000)
        produced, attempt = self.events(d, 'node.produced'), {0: att0, 1: att1}
        self.assertEqual(sorted(produced), [0, 1])
        for g in (0, 1):
            e = produced[g]
            occ = sorted((self.shape(x) for x in d['evidence_index'] if x['seq'] == e['seq']), key=lambda x: x['key'])
            want = sorted(({'seq': e['seq'], 'key': k, 'kind': 'node.produced', 'role': role, 'at': e['observed_at'] or e['at'], 'node': 'A', 'generation': g, 'attempt': attempt[g]}
                           for k, role in ((artifact, 'artifact'), (receipt, 'receipt'))), key=lambda x: x['key'])
            self.assertEqual(occ, want, f'node.produced #{e["seq"]} of generation {g}: each key of THIS event must carry this event\'s own seq/kind/time/'
                                        f'generation/attempt and role (blobs of both generations share the keys)')
        uses = sorted((x['generation'], x['attempt'], x['seq']) for x in d['evidence_index'] if x['key'] == receipt and x['kind'] == 'node.produced')
        self.assertEqual(uses, [(0, att0, produced[0]['seq']), (1, att1, produced[1]['seq'])], 'the shared receipt key is two occurrences, one per generation')
        for e in d['timeline']:                                     # the page labels every key an event names from that event's own occurrence
            have = {x['key'] for x in d['evidence_index'] if x['seq'] == e['seq']}
            self.assertTrue(set(e['evidence']) <= have, f'#{e["seq"]} {e["kind"]}: keys {sorted(set(e["evidence"]) - have)} have no occurrence of this event')
        page = self.http_detail(300)
        self.assertEqual([self.shape(x) for x in page['evidence_index']], [self.shape(x) for x in d['evidence_index']], 'CLI JSON = page JSON')

    def test_b_inherited_and_newly_produced_roles_of_one_key_coexist(self):
        artifact, receipt, att0, att1 = self.two_generations(resume_same=True)
        d = self.http_detail(300)
        produced = self.events(d, 'node.produced')
        of_key = [self.shape(x) for x in d['evidence_index'] if x['key'] == artifact]
        resumed = [x for x in of_key if x['kind'] == 'node.resumed']
        self.assertEqual([(x['role'], x['generation'], x['attempt']) for x in resumed], [('resume_artifact', 0, att0)],
                         f'the inheritance of {artifact[:12]} (node.resumed resume_artifact) must be its own occurrence, beside the production: {of_key}')
        mine = [x for x in of_key if x['kind'] == 'node.produced' and x['generation'] == 1]
        self.assertEqual([(x['role'], x['attempt'], x['seq']) for x in mine], [('artifact', att1, produced[1]['seq'])],
                         f'generation 1 produced {artifact[:12]} itself: an artifact occurrence with its attempt: {of_key}')
        cur = next(r for r in d['gantt']['rows'] if r['current'])
        self.assertEqual(cur['attempt'], att1)
        inh = [x for x in cur['inherits'] if x['key'] == artifact]
        self.assertEqual([(x['kind'], x['from_generation'], x['from_attempt']) for x in inh], [('resume_artifact', 0, att0)], cur['inherits'])
        src = inh[0].get('source_occurrence') or {}
        self.assertEqual((src.get('seq'), src.get('kind'), src.get('role'), src.get('generation'), src.get('attempt')), (produced[0]['seq'], 'node.produced', 'artifact', 0, att0),
                         'the inherited key names where it came from: the production of generation 0, not the latest use of the key')
        own = sorted((x['key'], x['role'], x['kind']) for x in d['evidence_index'] if x.get('output') and x['attempt'] == cur['attempt'] and x['kind'] == 'node.produced')
        self.assertEqual(own, sorted([(artifact, 'artifact', 'node.produced'), (receipt, 'receipt', 'node.produced')]),
                         'the outputs of the current attempt include the artifact it also inherited (the roles coexist)')

    def test_c_a_long_history_never_reads_as_no_output_and_the_door_opens_old_keys(self):
        artifact, receipt, att0, att1 = self.two_generations()
        full = tracking.detail(self.ledger.state_root, 'P1', timeline_limit=5000)
        gen0 = self.events(full, 'node.produced')[0]
        self.append_observations(310, att1)
        small = tracking.detail(self.ledger.state_root, 'P1', timeline_limit=300)
        self.assertGreater(small['timeline_total'], 300); self.assertEqual(len(small['timeline']), 300)
        self.assertNotIn(gen0['seq'], [e['seq'] for e in small['timeline']])           # setup: generation 0's production is outside the window
        for value, where in ((small, 'tracking.detail(timeline_limit=300)'), (self.http_detail(300), 'GET /api/task?timeline=300')):
            out0 = sorted((x['key'], x['seq']) for x in value['evidence_index'] if x['node'] == 'A' and x['generation'] == 0 and x['kind'] == 'node.produced')
            self.assertEqual(out0, sorted([(artifact, gen0['seq']), (receipt, gen0['seq'])]),
                             f'{where}: generation 0 still has its outputs although its events are older than the window ({value["timeline_total"]} events)')
            old = next(r for r in value['gantt']['rows'] if r['attempt'] == att0)
            self.assertTrue(any(m['kind'] == 'node.produced' for m in old['marks']))
        self.assertIs(small.get('timeline_complete'), False, 'the model says the timeline window is not the whole history (the page says so instead of implying no output)')

    def eight_keys(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        keys = [self.store.blob(f'r1 evidence blob {i}'.encode()) for i in range(8)]
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, self.root_task(), 'decision.recorded', {'plan': 'P1', 'subject': {'component': 'r1-fixture'}, 'basis': 'eight pieces of evidence',
                                                                                  'evidence': keys})
        d = tracking.detail(self.ledger.state_root, 'P1')
        return keys, next(e['seq'] for e in d['timeline'] if e['kind'] == 'decision.recorded' and 'r1-fixture' in e['summary'])

    def test_c_an_event_naming_more_than_six_keys_keeps_all_of_them(self):
        keys, seq = self.eight_keys()
        for limit in (50, 5000):
            d = tracking.detail(self.ledger.state_root, 'P1', timeline_limit=limit)
            named = sorted((x['key'], x.get('role')) for x in d['evidence_index'] if x['seq'] == seq)
            self.assertEqual(named, sorted((k, f'evidence[{i}]') for i, k in enumerate(keys)),
                             f'timeline {limit}: every key the event names is an occurrence with its role (the 6-key display cap of a timeline row is not the index)')

    def test_c_the_evidence_door_does_not_depend_on_any_window(self):
        keys, seq = self.eight_keys()
        self.step()
        att0 = tracking.detail(self.ledger.state_root, 'P1')['nodes']['A']['attempt']
        self.append_observations(5010, att0)
        refused = []
        for key in (keys[0], keys[7]):
            try:
                opened = tracking.evidence(self.ledger.state_root, 'P1', key)
                self.assertIn('r1 evidence blob', opened['text'])
            except PermissionError as error:
                refused.append((key[:12], str(error)))
        self.assertEqual(refused, [], 'the door opens keys named by an event older than 5000 newer events (membership = the full history of the root)')
        with self.assertRaises(PermissionError): tracking.evidence(self.ledger.state_root, 'P1', self.store.blob(b'not named by this root'))

    def test_d_the_provenance_is_the_same_at_every_timeline_limit(self):
        artifact, receipt, att0, att1 = self.two_generations(resume_same=True)
        self.append_observations(310, att1)
        views = {n: tracking.detail(self.ledger.state_root, 'P1', timeline_limit=n) for n in (5, 300, 5000)}
        index = {n: [self.shape(x) for x in v['evidence_index']] for n, v in views.items()}
        self.assertEqual(index[5], index[5000], 'evidence_index at timeline 5 vs 5000')
        self.assertEqual(index[300], index[5000], 'evidence_index at timeline 300 vs 5000')
        self.assertEqual(views[5]['evidence_keys'], views[5000]['evidence_keys'])
        inherits = {n: [r['inherits'] for r in v['gantt']['rows']] for n, v in views.items()}
        self.assertEqual(inherits[5], inherits[5000])

    def test_e_attempt_events_carry_the_node_generation_of_their_attempt(self):
        """Review round 1 (R1 closure): attempt.reserved/launched carry the attempt's CONTROL generation (the task's attempt counter, 1 for
        every child task) and the attempts table holds that same counter; neither is the node generation. Every occurrence of an attempt,
        including attempt.settled (an output kind) on the child task, must carry the node generation that attempt ran for (its node.started
        and Gantt row), in the model, over HTTP at a small window, in the timeline rows and in each row's outputs."""
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        self.step()
        for _ in range(2):
            with self.ledger.transaction(write=True) as conn:
                engine._event(self.ledger, conn, engine.state(self.ledger, 'P1', conn), 'A', 'node.resumed')
            self.step()
        for d in (tracking.detail(self.ledger.state_root, 'P1', timeline_limit=5000), self.http_detail(3)):
            rows = {r['attempt']: r for r in d['gantt']['rows'] if r['node'] == 'A'}
            self.assertEqual(sorted(r['generation'] for r in rows.values()), [0, 1, 2], 'setup: three generations of A, one attempt each')
            settled = [x for x in d['evidence_index'] if x['kind'] == 'attempt.settled' and x['attempt'] in rows]
            self.assertTrue(settled and all(x['output'] for x in settled), 'setup: the child attempts settle with a result naming blobs (an output kind)')
            bad = [(x['seq'], x['kind'], x['role'], 'occurrence gen', x['generation'], 'row gen', rows[x['attempt']]['generation'])
                   for x in d['evidence_index'] if x['attempt'] in rows and x['generation'] != rows[x['attempt']]['generation']]
            self.assertEqual(bad, [], 'every occurrence of an attempt carries the node generation of that attempt (its Gantt row)')
            for aid, r in rows.items():
                outs = [x for x in d['evidence_index'] if x['output'] and x['attempt'] == aid]
                self.assertTrue(outs, f'row of generation {r["generation"]} has outputs')
                self.assertEqual({x['generation'] for x in outs}, {r['generation']}, f'outputs of the generation-{r["generation"]} row')
                basis = {x['generation_basis'] for x in outs if x['kind'].startswith('attempt.')}
                self.assertTrue(basis and all(b.startswith('node.started:#') for b in basis), basis)
            rows_tl = [(e['seq'], e['kind'], e['generation'], rows[e['attempt']]['generation']) for e in d['timeline']
                       if e['kind'].startswith('attempt.') and e.get('attempt') in rows and e['generation'] != rows[e['attempt']]['generation']]
            self.assertEqual(rows_tl, [], 'the event log rows of attempt.* events show the node generation of their attempt')

    def test_f_an_old_row_keeps_what_it_inherited(self):
        """Review round 2 (R1 closure): inheritance is history, not only the engine's current node record. Generation 1 resumes from K of
        generation 0 and produces K again; generation 2 continues from generation 1's attempt without an artifact; generation 3 is a plain
        resume. Once newer generations exist, the generation-1 row still names K as inherited from generation 0 (with the source occurrence)
        beside its own production of K, the generation-2 row still says it continues from generation 1, and a plain generation inherits
        nothing; in the model and over HTTP at a small window."""
        artifact, receipt, att0, att1 = self.two_generations(resume_same=True)
        produced0 = self.events(tracking.detail(self.ledger.state_root, 'P1', timeline_limit=5000), 'node.produced')[0]
        def inh(r): return [(x['kind'], x['key'], x['from_attempt'], x['from_generation'], (x.get('source_occurrence') or {}).get('seq')) for x in r['inherits']]
        while_current = inh(next(r for r in tracking.detail(self.ledger.state_root, 'P1')['gantt']['rows'] if r['attempt'] == att1))
        self.assertEqual(while_current, [('resume_artifact', artifact, att0, 0, produced0['seq'])], 'setup: the current generation-1 row inherits K')
        with self.ledger.transaction(write=True) as conn:
            engine._event(self.ledger, conn, engine.state(self.ledger, 'P1', conn), 'A', 'node.resumed', continues_attempt=att1)
        self.step()
        att2 = tracking.detail(self.ledger.state_root, 'P1')['nodes']['A']['attempt']
        with self.ledger.transaction(write=True) as conn:
            engine._event(self.ledger, conn, engine.state(self.ledger, 'P1', conn), 'A', 'node.resumed')
        self.step()
        for d, where in ((tracking.detail(self.ledger.state_root, 'P1', timeline_limit=5000), 'model'), (self.http_detail(3), 'GET /api/task?timeline=3')):
            rows = {r['generation']: r for r in d['gantt']['rows'] if r['node'] == 'A'}
            self.assertEqual(sorted(rows), [0, 1, 2, 3], f'{where}: setup: four generations of A')
            self.assertFalse(rows[1]['current'] or rows[2]['current'])
            self.assertEqual(inh(rows[1]), while_current, f'{where}: the generation-1 row, now old, still names K inherited from generation 0 (as while it was current)')
            self.assertTrue(rows[1]['inherits'][0].get('source'), rows[1]['inherits'])
            own1 = [(x['kind'], x['role']) for x in d['evidence_index'] if x['key'] == artifact and x['output'] and x['attempt'] == att1]
            self.assertIn(('node.produced', 'artifact'), own1, f'{where}: and K is still its own output (the roles coexist on a history row)')
            self.assertEqual([(x['kind'], x['key'], x['from_attempt'], x['from_generation']) for x in rows[2]['inherits']], [('continues', None, att1, 1)],
                             f'{where}: the generation-2 row, now old, still continues from the generation-1 attempt')
            self.assertEqual(rows[2]['attempt'], att2)
            self.assertEqual((rows[0]['inherits'], rows[3]['inherits']), ([], []), f'{where}: the first and a plain generation inherit nothing')

    def http_get(self, path):
        server = tracking_web.make_server(self.ledger.state_root, interval=1.0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True); thread.start()
        try:
            try:
                with urllib.request.urlopen(tracking_web.url_of(server) + path, timeout=60) as r:
                    status, body = r.status, r.read().decode('utf-8')
            except urllib.error.HTTPError as error:
                status, body = error.code, error.read().decode('utf-8', 'replace')
            return status, body, server.track_stats['errors']
        finally:
            server.shutdown(); server.server_close()

    def test_g_an_identifier_is_not_blob_evidence_and_a_missing_blob_is_said_so(self):
        """Review round 2 (R1 same class): blob identity must not be conflated with any 64-hex identifier. A payload naming a project-id-like
        hex next to a real blob lists only the blob as evidence; identifiers (project_id, revision, plan sha ...) are neither counted, listed
        nor opened; an output whose blob is not in the store stays listed as an output, marked as not in the store, and the door answers
        404 'not in the store' for it and for an identifier instead of a 503 source error."""
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        real = self.store.blob(b'r1 real evidence blob')
        ident = hashlib.sha256(b'r1 a project id, not a blob').hexdigest()
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, self.root_task(), 'decision.recorded', {'plan': 'P1', 'subject': {'component': 'r1-ids'}, 'basis': 'one blob beside an id',
                                                                                  'project_ref': ident, 'evidence': [real]})
        self.step()
        receipt = tracking.detail(self.ledger.state_root, 'P1')['nodes']['A']['receipt']
        (self.store.root / 'blobs' / receipt).unlink()                 # an output whose blob is gone from the store
        d = tracking.detail(self.ledger.state_root, 'P1', timeline_limit=5000)
        blobs = self.store.root / 'blobs'
        self.assertIn(real, d['evidence_keys'])
        not_blobs = sorted(k for k in d['evidence_keys'] if not (blobs / k).is_file())
        self.assertEqual(not_blobs, [], f'evidence_keys (the blobs the page counts and opens) holds identifiers / missing blobs: {[k[:12] for k in not_blobs]}')
        ids = [(x['seq'], x['kind'], x['role']) for x in d['evidence_index'] if x['key'] == ident]
        self.assertEqual(ids, [], 'an identifier next to a real blob is not an evidence occurrence')
        listed_ids = [(x['seq'], x['kind'], x['role']) for x in d['evidence_index'] if not (blobs / x['key']).is_file() and not x.get('output')]
        self.assertEqual(listed_ids, [], 'no non-output occurrence of a key that is not a blob (project_id, revision, sha ...)')
        seq = next(e['seq'] for e in d['timeline'] if e['kind'] == 'decision.recorded' and 'r1-ids' in e['summary'])
        row = next(e for e in d['timeline'] if e['seq'] == seq)
        self.assertEqual((row['evidence'], row['evidence_count']), ([real], 1), 'the event row names only the blob')
        gone = [x for x in d['evidence_index'] if x['key'] == receipt and x['kind'] == 'node.produced']
        self.assertEqual([(x['role'], x['output'], x.get('blob')) for x in gone], [('receipt', True, False)],
                         'an output whose blob is missing stays an output occurrence, marked blob: false (never reads as no output)')
        self.assertTrue(all(x.get('blob') is True for x in d['evidence_index'] if x['key'] != receipt), 'every other listed occurrence is a blob in the store')
        self.assertIn(f"Bằng chứng mở được: {len(d['evidence_keys'])} blob", tracking.render_detail(d))
        for key in (ident, receipt):
            with self.assertRaises(tracking.LedgerError, msg=key[:12]): tracking.evidence(self.ledger.state_root, 'P1', key)
            status, body, errors = self.http_get('api/evidence?plan=P1&key=' + key + '&format=text')
            self.assertEqual((status, errors), (404, 0), f'{key[:12]}: the door says "not in the store" (404) instead of a source error: {body[:200]}')
            self.assertIn('không có', body)
        status, body, errors = self.http_get('api/evidence?plan=P1&key=' + real + '&format=text')
        self.assertEqual((status, errors), (200, 0)); self.assertIn('r1 real evidence blob', body)
