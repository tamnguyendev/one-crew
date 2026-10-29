"""Independent review probes for 2.3-A1/A2 (written by the reviewer on snapshot e7a2aa9, D:\\OneCrewRuns\\v23\\review-a1a2.md). Each test
asserts the EXPECTED behaviour; on e7a2aa9 21 of 23 failed (defects reproduced). Kept in the repo as the r1 regression set; adjusted only
where the fix took another expected behaviour the review itself offered (p02 refuse at write, p15 refuse the cursor, p09/p10 pass the
candidate files, p14 look in `requested`). Every probe prints a 'PROBE <id>' line with what it observed."""
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import context, knowledge, plan as plans
from onecrew.v2.verifiers import command
from tests.test_v2_l1 import plan_json
from tests.test_v23_a1_knowledge import PIN, fence
from tests.test_v23_a2_knowledge import A2Fixture
from tests.test_wf_engine import node


def say(tag, *values):
    print(f'\nPROBE {tag}:', *[v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)[:1500] for v in values], flush=True)


class Base(A2Fixture):
    def event(self):
        with self.ledger.transaction() as conn:
            return conn.execute("SELECT MAX(e.seq) FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=?",
                                (self.ledger.project_id,)).fetchone()[0]

    def pkg(self, plan='P1', item=None, cap=12000, ledger=None, requested=()):
        ledger = ledger or self.ledger
        return knowledge.package(ledger, knowledge.consumer(ledger, plan, node=item or self.item()), cap_chars=cap, requested=requested)

    def second_project(self):
        other = Path(self.temp.name) / 'other'; other.mkdir()
        g = lambda *a: subprocess.run(['git', '-C', str(other), *a], check=True, capture_output=True, text=True).stdout.strip()
        g('init', '-q'); g('config', 'user.email', 't@localhost'); g('config', 'user.name', 'T')
        (other / 'a.txt').write_text('other\n')
        g('add', '.'); g('commit', '-qm', 'o')
        head = g('rev-parse', 'HEAD')
        (other / 'docs' / 'wiki').mkdir(parents=True)
        (other / 'docs' / 'wiki' / 'rules.md').write_text('## a.txt keeps one line\n' + fence({
            'id': 'one-line', 'kind': 'constraint', 'label': 'verified', 'must': True, 'applies_to': ['a.txt'],
            'sources': [{'type': 'file', 'path': 'a.txt', 'revision': head}]}) + 'Project 2: never split a.txt.\n', encoding='utf-8')
        g('add', '.'); g('commit', '-qm', 'wiki')
        second = Ledger(other, self.ledger.state_root)
        plans.propose(second, 'Q1', plan_json(), 'codex')
        return second


class P01DeclarationLimits(Base):
    def test_p01_claim_text_over_600_loses_the_whole_attempt(self):
        say('p01 schema for knowledge.new[].text', knowledge.SCHEMA['properties']['new']['items']['properties']['text'])
        self.revise([self.item('C', read=('a.txt', 'b.txt')), dict(node('I', ['C'], integration=True, write=()), executor=dict(PIN))])
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'right\n'}], 'backlog': [],
                            'knowledge': {'used': [], 'rejected': [], 'requests': [], 'new': [{'kind': 'finding', 'text': 'x' * 601}]}})
        produced = self.engine.step(self.ledger, 'P1', self.adapter)
        say('p01 step result', {k: produced.get(k) for k in ('state', 'reason')}, 'worker calls:', len(self.calls))
        self.assertEqual(produced['state'], 'produced')


class P02CrossProject(Base):
    def test_p02_general_record_supersedes_and_survives_withdrawal_in_another_project(self):
        second = self.second_project()
        before = self.pkg('Q1', ledger=second)
        say('p02 project-2 package before', [e['id'] for e in before['entries']])
        ev = self.event()
        with self.assertRaises(LedgerError):            # r1 #2: a general record carrying project detail is refused at write
            knowledge.record(self.ledger, 'P1', kind='lesson', text='Produce evidence only after the declared output is checked twice.',
                             scope='general', conditions=['when a node produces evidence'], must=True, supersedes=['one-line'],
                             applies_to=['a.txt'], title='Project one internal hint',
                             evidence={'status': 'verified', 'property': 'seen in review',
                                       'sources': [{'type': 'event', 'id': ev}, {'type': 'file', 'path': 'a.txt', 'revision': 'HEAD'}]})
        g = knowledge.record(self.ledger, 'P1', kind='lesson', text='Produce evidence only after the declared output is checked twice.',
                             scope='general', conditions=['when a node produces evidence'],
                             evidence={'status': 'verified', 'property': 'seen in review', 'sources': [{'type': 'event', 'id': ev}]})
        say('p02 clean general record', g)
        seen = g['id'] + '@' + knowledge.project_tags(self.ledger)[self.ledger.project_id]   # Codex dev5 P2-B: the id project two knows it by
        after = self.pkg('Q1', ledger=second)
        self.assertIn(seen, [e['id'] for e in after['entries']] + [r['id'] for r in after['omitted']['index']])   # shared before withdrawal
        delivered = {e['id']: e for e in after['entries']}
        say('p02 project-2 package after the general record', {i: {k: e[k] for k in ('must', 'use', 'source', 'title')} for i, e in delivered.items()},
            after['omitted']['by_reason'])
        knowledge.withdraw(self.ledger, 'P1', g['id'], reason='wrong', evidence={'sources': [{'type': 'event', 'id': ev}]})
        p1 = self.pkg('P1')
        later = self.pkg('Q1', ledger=second)
        say('p02 after withdrawal in project 1: in project-1 package?', g['id'] in [e['id'] for e in p1['entries']],
            'in project-2 package?', seen in [e['id'] for e in later['entries']], 'project-2 ids:', [e['id'] for e in later['entries']])
        self.assertIn('one-line', delivered, 'project 2 lost its own mandatory constraint to another project')
        self.assertNotIn(seen, [e['id'] for e in later['entries']], 'withdrawn general record still delivered in project 2')
        self.assertNotIn(seen, [r['id'] for r in later['omitted']['index']], 'withdrawn general record still listed in project 2')
        self.assertGreaterEqual(later['omitted']['by_reason'].get('withdrawn', 0), 1)


class P03RootPrivateSupersedes(Base):
    def test_p03_root_private_entry_supersedes_for_every_root(self):
        self.page('rules.md', '## a.txt rule\n' + fence({'id': 'a-rule', 'kind': 'constraint', 'label': 'verified', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + 'a.txt keeps one line.\n')
        ev = self.event()
        knowledge.record(self.ledger, 'P1', kind='note', text='P1 scratch replacing a-rule here', visibility='root', supersedes=['a-rule'],
                         evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': ev}]})
        b = self.pkg(self.root_b())
        say('p03 root B ids', [e['id'] for e in b['entries']], b['omitted']['by_reason'])
        self.assertIn('a-rule', [e['id'] for e in b['entries']])


class P04SummaryConditions(Base):
    def test_p04_summary_is_a_fact_where_its_source_is_not_applicable_or_a_lead(self):
        ev = self.event()
        e1 = knowledge.record(self.ledger, 'P1', kind='finding', text='a.txt parser needs the lib quirk handled', applies_to=['a.txt'],
                              conditions=[{'type': 'file_contains', 'path': 'requirements.txt', 'text': 'lib==1.0'}],
                              evidence={'status': 'verified', 'property': 'reproduced', 'sources': [{'type': 'event', 'id': ev}]})
        e2 = knowledge.record(self.ledger, 'P1', kind='finding', text='a.txt parser is fast enough on windows', applies_to=['a.txt'],
                              conditions=['only on the CI machine'],
                              evidence={'status': 'verified', 'property': 'measured', 'sources': [{'type': 'event', 'id': ev}]})
        s1 = knowledge.summarize(self.ledger, 'P1', [e1['id']], text='a.txt parser: handle the lib quirk')
        s2 = knowledge.summarize(self.ledger, 'P1', [e2['id']], text='a.txt parser: fast enough')
        (self.root / 'requirements.txt').write_text('lib==2.0\n')
        p = self.pkg()
        got = {e['id']: (e['use'], e['applicability']['state']) for e in p['entries']}
        say('p04 delivered (use, applicability)', {'e1': got.get(e1['id']), 's1': got.get(s1['id']), 'e2': got.get(e2['id']), 's2': got.get(s2['id'])},
            p['omitted']['by_reason'])
        self.assertNotEqual(got.get(s1['id'], ('absent',))[0], 'fact')
        self.assertNotEqual(got.get(s2['id'], ('absent',))[0], 'fact')


class P05Keys(Base):
    def test_p05_update_of_a_subject_from_another_root_is_dropped(self):
        ev = self.event()
        v1 = knowledge.record(self.ledger, 'P1', kind='decision', key='fmt', base='', text='a.txt uses VALUE: one', applies_to=['a.txt'],
                              evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        p2 = self.root_b('P2')
        with_base = knowledge.record(self.ledger, p2, kind='decision', key='fmt', base=v1['version'], text='a.txt uses VALUE: two',
                                     applies_to=['a.txt'], evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        say('p05 root-B update with the base it read', {k: with_base.get(k) for k in ('id', 'conflict')})
        no_base = knowledge.record(self.ledger, p2, kind='decision', key='fmt', base='', text='a.txt uses VALUE: three',
                                   applies_to=['a.txt'], evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        say('p05 root-B write of the same key with base ""', {k: no_base.get(k) for k in ('id', 'recorded', 'conflict')})
        p3 = self.pkg(self.root_b('P3'))
        say('p05 root C delivered texts', [e['text'] for e in p3['entries']], 'problems', p3['problems'])
        self.assertIn('a.txt uses VALUE: three', [e['text'] for e in p3['entries']], 'newest write of the subject lost')

    def test_p06_long_key_contested_version_collides_with_the_subject_id(self):
        ev = self.event()
        key = 'decision-about-the-a-txt-format-and-its-version-line-v1'          # 55 chars: allowed by key_field (<=128)
        ent = lambda text, base: knowledge.record(self.ledger, 'P1', kind='decision', key=key, base=base, text=text, applies_to=['a.txt'],
                                                  evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        v1 = ent('a.txt uses VALUE: one', '')
        v2 = ent('a.txt uses VALUE: two', v1['version'])
        v3 = ent('a.txt uses VALUE: three', v1['version'])
        say('p06 ids', {'v1': v1['id'], 'v2': v2['id'], 'v3': v3['id'], 'v3 conflict': v3.get('conflict')})
        p = self.pkg()
        say('p06 delivered texts', [e['text'] for e in p['entries']], 'problems', p['problems'])
        self.assertIn('a.txt uses VALUE: three', [e['text'] for e in p['entries']], 'contested version lost')

    def test_p07_revert_to_an_earlier_text_is_silently_not_written(self):
        ev = self.event()
        ent = lambda text, base: knowledge.record(self.ledger, 'P1', kind='decision', key='rv', base=base, text=text, applies_to=['a.txt'],
                                                  evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        v1 = ent('a.txt uses VALUE: one', '')
        v2 = ent('a.txt uses VALUE: two', v1['version'])
        v3 = ent('a.txt uses VALUE: one', v2['version'])
        say('p07 revert result', {k: v3.get(k) for k in ('recorded', 'version', 'conflict')}, 'v1 version', v1['version'])
        p = self.pkg()
        say('p07 delivered', [e['text'] for e in p['entries']])
        self.assertIn('a.txt uses VALUE: one', [e['text'] for e in p['entries']])

    def test_p08_base_without_key(self):
        ev = self.event()
        try:
            out = knowledge.record(self.ledger, 'P1', kind='note', text='some note', base='abc',
                                   evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': ev}]})
            say('p08 result', out)
        except LedgerError as error:
            say('p08 LedgerError (expected)', str(error))
        except Exception as error:                   # noqa
            say('p08 UNEXPECTED', type(error).__name__, str(error))
            raise


class P09Engine(Base):
    def test_p09_a_later_observation_hides_the_verified_project_record(self):
        claim = {'kind': 'finding', 'text': 'a.txt must hold VALUE: right', 'applies_to': ['a.txt'], 'check': 'check-C'}
        self.produce_and_verify([claim])
        p2 = self.root_b('P2')
        reader = self.item('D', read=('a.txt', 'b.txt'))   # r1 #1: a reader of the producer's whole scope (node C read a.txt and b.txt)
        b = self.pkg(p2, reader)
        mine = [e for e in b['entries'] if e['text'] == claim['text']]
        say('p09 root B entry (keys delivered)', sorted(mine[0]) if mine else None, mine[0]['use'] if mine else None)
        knowledge.record_claims(self.ledger, 'P1', self.item('D'), self.store.blob(b'a later attempt receipt'),
                                [{'kind': 'finding', 'text': claim['text'], 'applies_to': ['a.txt'], 'sources': []}], {'a.txt': 'right\n'})
        b2 = self.pkg(p2, reader)
        say('p09 root B after a later observation of the same text in root A',
            [e['use'] for e in b2['entries'] if e['text'] == claim['text']], b2['omitted']['by_reason'])
        self.assertTrue([e for e in b2['entries'] if e['text'] == claim['text']], 'verified project knowledge lost')

    def test_p10_claim_about_a_file_not_in_HEAD_is_dropped_silently(self):
        written = knowledge.record_claims(self.ledger, 'P1', {'read': ['new.txt'], 'write': ['new.txt']}, self.store.blob(b'r'),
                                          [{'kind': 'finding', 'text': 'new.txt holds the parser table', 'sources': ['new.txt']}],
                                          {'new.txt': 'the parser table\n'})
        say('p10 written ids', written)
        self.assertTrue(written)

    def test_p11_claim_without_sources_bypasses_read_permission_and_stays_a_fact(self):
        claim = {'kind': 'finding', 'text': 'b.txt holds the PRIVATE-B format two', 'applies_to': ['a.txt'], 'check': 'check-C'}
        self.produce_and_verify([claim])                            # node C reads a.txt and b.txt
        self.page('x.md', '## unrelated\nunrelated\n')            # a new commit; a.txt untouched
        (self.root / 'a.txt').write_text('completely different\n'); self.git('commit', '-qam', 'a.txt rewritten')
        d = self.pkg(self.root_b('P2'), self.item('D', read=('a.txt',)))   # node D may not read b.txt
        hit = [(e['use'], e['applicability']['state']) for e in d['entries'] if 'PRIVATE-B' in e['text']]
        say('p11 root B node D (read a.txt only) receives', hit)
        self.assertFalse(hit, 'content learned from b.txt reached a node without read access to b.txt')

    def test_p12_dependent_node_judged_on_working_tree_not_on_what_it_sees(self):
        self.page('rules.md', '## a.txt value\n' + fence({'id': 'a-value', 'kind': 'finding', 'label': 'verified', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + 'a.txt holds VALUE: one.\n')
        self.produce_and_verify([], content='right\n')
        self.values.append({'summary': 'integrated', 'evidence': []})
        out = self.engine.step(self.ledger, 'P1', self.adapter)
        body = json.loads(self.calls[-1]['prompt'].split('\n', 1)[1])
        entry = next((e for e in body.get('knowledge', {}).get('entries', []) if e['id'] == 'a-value'), None)
        seen = (body['source'].get('a.txt'), body['input_artifacts']['C'].get('outputs_in_source'))
        say('p12 node I', out.get('state'), 'a.txt the worker sees:', seen, 'a-value delivered as:',
            entry and (entry['use'], entry['applicability']))
        self.assertNotEqual(entry and entry['use'], 'fact')


class P13PromptCap(Base):
    def run_c(self, with_wiki):
        (self.root / 'a.txt').write_text('x' * 74000 + '\n'); self.git('commit', '-qam', 'big a.txt')
        if with_wiki:
            text = ''.join(f'## a.txt note {i}\n' + fence({'id': f'n{i}', 'kind': 'note', 'applies_to': ['a.txt']}) + (f'a.txt detail{i} ' * 110) + '\n'
                           for i in range(4))
            self.page('notes.md', text)
        self.revise([self.item('C', read=('a.txt', 'b.txt')), dict(node('I', ['C'], integration=True, write=()), executor=dict(PIN))])
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'right\n'}], 'backlog': []})
        return self.engine.step(self.ledger, 'P1', self.adapter)

    def test_p13a_control_without_wiki_runs(self):
        out = self.run_c(False)
        say('p13a without wiki', out.get('state'), 'prompt chars', len(self.calls[-1]['prompt']) if self.calls else None)
        self.assertEqual(out['state'], 'produced')

    def test_p13b_optional_wiki_notes_block_the_same_node(self):
        out = self.run_c(True)
        say('p13b with 4 optional notes', out.get('state'), str(out.get('reason'))[:160], 'worker calls', len(self.calls), 'prompt chars', len(self.calls[-1]['prompt']) if self.calls else None, 'knowledge ids', [e['id'] for e in json.loads(self.calls[-1]['prompt'].split(chr(10), 1)[1]).get('knowledge', {}).get('entries', [])] if self.calls else None)
        self.assertEqual(out['state'], 'produced')


class P14Reader(Base):
    def test_p14_truncated_relevant_entry_cannot_be_requested_whole(self):
        self.page('long.md', '## a.txt long rule\n' + fence({'id': 'long-rule', 'kind': 'constraint', 'applies_to': ['a.txt']}) + ('word ' * 700) + '\n')
        first = self.pkg()
        e = next(e for e in first['entries'] if e['id'] == 'long-rule')
        p = self.pkg(requested=['long-rule'])
        whole = next((r for r in p['requested'] if r['id'] == 'long-rule'), None)
        say('p14 delivered', e.get('text_truncated'), 'requested', [r['id'] for r in p['requested']], 'refused', p['requests_refused'])
        self.assertTrue(e.get('text_truncated'))
        self.assertTrue(p['requested'] or p['requests_refused'], 'request silently ignored')
        self.assertIsNotNone(whole); self.assertNotIn('text_truncated', whole)

    def test_p15_cursor_accepted_for_a_changed_task_skips_entries(self):
        text = ''.join(f'## n{i}\n' + fence({'id': f'n{i}', 'kind': 'note'}) + (('alpha bravo charlie' if i < 3 else 'delta echo foxtrot') + f' item {i}') + '\n'
                       for i in range(6))
        self.page('t.md', text)
        c1 = knowledge.consumer(self.ledger, 'P1', node=self.item(goal='alpha bravo charlie work'))
        c2 = knowledge.consumer(self.ledger, 'P1', node=self.item(goal='delta echo foxtrot work'))
        first = knowledge.package(self.ledger, c1, cap_chars=12000)
        with self.assertRaises(LedgerError):            # r1 #21: the cursor is bound to the task it was made for
            knowledge.read(self.ledger, c2, first['omitted']['cursor'], cap_chars=12000)
        nxt = knowledge.read(self.ledger, c1, first['omitted']['cursor'], cap_chars=12000)
        say('p15 page1(c1)', [e['id'] for e in first['entries']], 'page2 read with c1', [e['id'] for e in nxt['entries']], 'eof', nxt['omitted']['eof'])
        self.assertEqual(sorted(e['id'] for e in first['entries'] + nxt['entries']), [f'n{i}' for i in range(6)])

    def test_p16_dedupe_keeps_the_non_mandatory_twin(self):
        self.page('dup.md', '## Note A\n' + fence({'id': 'note-a', 'kind': 'constraint'}) + 'Never split a.txt into two lines.\n'
                  '## Rule B\n' + fence({'id': 'rule-b', 'kind': 'constraint', 'must': True, 'applies_to': ['a.txt']}) + 'Never split a.txt into two lines.\n'
                  '## Cond C\n' + fence({'id': 'cond-c', 'kind': 'finding', 'conditions': [{'type': 'file_contains', 'path': 'requirements.txt', 'text': 'lib==9'}]})
                  + 'b rule text.\n'
                  '## Plain D\n' + fence({'id': 'plain-d', 'kind': 'finding', 'applies_to': ['a.txt']}) + 'b rule text.\n')
        p = self.pkg()
        say('p16 delivered', [(e['id'], e['must']) for e in p['entries']], p['omitted']['by_reason'])
        self.assertIn('rule-b', [e['id'] for e in p['entries'] if e['must']], 'mandatory constraint lost as a copy')
        self.assertIn('plain-d', [e['id'] for e in p['entries']], 'applicable entry lost as a copy of an inapplicable twin')

    def test_p18_one_malformed_page_drops_every_mandatory_constraint(self):
        self.page('good.md', '## a.txt keeps one line\n' + fence({'id': 'one-line', 'kind': 'constraint', 'label': 'verified', 'must': True,
                  'applies_to': ['a.txt'], 'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + 'Never split a.txt.\n')
        self.page('typo.md', '## other\n```onecrew\n{"id": "typo", "sources": 1}\n```\nunrelated\n')
        view, record = knowledge.for_native(self.ledger, self.store, 'P1', self.item(), PIN)
        say('p18 for_native view', None if view is None else [e['id'] for e in view['entries']], 'record', {k: record.get(k) for k in ('error', 'delivered')})
        self.assertIsNotNone(view, 'the healthy page mandatory constraint was not delivered')

    def test_p19_wiki_source_at_HEAD_never_rechecks(self):
        self.page('h.md', '## a.txt value\n' + fence({'id': 'a-head', 'kind': 'finding', 'label': 'verified', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'file', 'path': 'a.txt', 'revision': 'HEAD'}]}) + 'a.txt holds VALUE: one.\n'
                  '## a.txt value pinned\n' + fence({'id': 'a-pin', 'kind': 'finding', 'label': 'verified', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + 'a.txt holds VALUE: one (pinned).\n')
        (self.root / 'a.txt').write_text('two\n'); self.git('commit', '-qam', 'a.txt changed')
        p = self.pkg()
        say('p19', {e['id']: (e['use'], e['applicability']['state']) for e in p['entries']})
        self.assertNotEqual(next(e for e in p['entries'] if e['id'] == 'a-head')['use'], 'fact')


class P20Cost(Base):
    def test_p20_git_processes_grow_with_history_not_with_files(self):
        ev = self.event()
        for i in range(30):
            (self.root / 'a.txt').write_text(f'version {i}\n'); self.git('commit', '-qam', f'c{i}')
            knowledge.record(self.ledger, 'P1', kind='finding', text=f'a.txt version {i} parses', applies_to=['a.txt'],
                             evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': ev}, {'type': 'file', 'path': 'a.txt', 'revision': 'HEAD'}]})
        calls = []
        real = command._git
        def counted(*args, **kw):
            calls.append(args[1] if len(args) > 1 else '?')
            return real(*args, **kw)
        with patch.object(command, '_git', counted):
            started = time.perf_counter()
            p = self.pkg()
            seconds = time.perf_counter() - started
        kinds = {}
        for c in calls: kinds[c] = kinds.get(c, 0) + 1
        say('p20 30 records citing ONE file at 30 commits', 'git processes per package:', len(calls), kinds, 'seconds', round(seconds, 2),
            'candidates', p['cost']['candidates'])


class P21Lifecycle(Base):
    def test_p21_supersession_chain_depends_on_candidate_order(self):
        self.page('chain.md', '## c\n' + fence({'id': 'rule-c', 'kind': 'constraint', 'applies_to': ['a.txt'], 'supersedes': ['rule-b']}) + 'a.txt rule version C.\n'
                  '## b\n' + fence({'id': 'rule-b', 'kind': 'constraint', 'applies_to': ['a.txt'], 'supersedes': ['rule-a']}) + 'a.txt rule version B.\n'
                  '## a\n' + fence({'id': 'rule-a', 'kind': 'constraint', 'applies_to': ['a.txt']}) + 'a.txt rule version A.\n')
        p = self.pkg()
        say('p21 delivered', [e['id'] for e in p['entries']], p['omitted']['by_reason'])
        self.assertEqual([e['id'] for e in p['entries']], ['rule-c'])

    def test_p22_correction_of_a_withdrawn_subject_is_hidden(self):
        ev = self.event()
        ent = lambda text, base: knowledge.record(self.ledger, 'P1', kind='decision', key='fmt2', base=base, text=text, applies_to=['a.txt'],
                                                  evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        v1 = ent('a.txt uses VALUE: one', '')
        knowledge.withdraw(self.ledger, 'P1', v1['id'], reason='wrong value', evidence={'sources': [{'type': 'event', 'id': ev}]})
        v2 = ent('a.txt uses VALUE: two (corrected)', v1['version'])
        p = self.pkg()
        say('p22 correction write', {k: v2.get(k) for k in ('recorded', 'id', 'conflict')}, 'delivered', [e['text'] for e in p['entries']],
            p['omitted']['by_reason'])
        self.assertIn('a.txt uses VALUE: two (corrected)', [e['text'] for e in p['entries']])

    def test_p24_wiki_fact_from_an_event_id_that_does_not_exist(self):
        self.page('ev.md', '## a.txt decided\n' + fence({'id': 'ghost', 'kind': 'decision', 'label': 'verified', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'event', 'id': 987654}, {'type': 'receipt', 'key': 'no-such-receipt'}]}) + 'a.txt must never change.\n')
        p = self.pkg()
        e = next(e for e in p['entries'] if e['id'] == 'ghost')
        say('p24 ghost', e['use'], e['applicability'], 'problems', p['problems'])
        self.assertNotEqual(e['use'], 'fact')
