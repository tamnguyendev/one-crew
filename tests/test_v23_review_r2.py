"""Review round 2 probes (written by the reviewer on a9b1d1d, D:\OneCrewRuns\v23\review-a1a2-r2.md): new defects suspected in the r1 fixes. Each test asserts the EXPECTED behaviour; a failure = defect
reproduced. Prints 'PROBE <id>' lines."""
import copy
import json

from onecrew.v2 import context, knowledge, plan as plans, runtime_unknowns
from tests.test_v23_a1_knowledge import PIN, fence
from tests.test_v23_review_r1 import Base, say
from tests.test_wf_engine import node


def ev_of(case):
    return case.event()


class N1Withdrawal(Base):
    def rec(self, key, text, base, plan='P1', **kw):
        return knowledge.record(self.ledger, plan, kind='decision', key=key, base=base, text=text, applies_to=['a.txt'],
                                evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': self.event()}]}, **kw)

    def test_n1_summary_of_a_withdrawn_version_revives_with_the_correction(self):
        v1 = self.rec('fmt3', 'a.txt uses VALUE: one', '')
        s = knowledge.summarize(self.ledger, 'P1', [v1['id']], text='Summary: a.txt is VALUE one')
        knowledge.withdraw(self.ledger, 'P1', v1['id'], reason='wrong value', evidence={'sources': [{'type': 'event', 'id': self.event()}]})
        mid = [e['text'] for e in self.pkg()['entries']]
        self.rec('fmt3', 'a.txt uses VALUE: two (corrected)', v1['version'])
        after = [e['text'] for e in self.pkg()['entries']]
        say('n1 after withdrawal', mid, 'after correction', after)
        self.assertNotIn('Summary: a.txt is VALUE one', after, 'summary of the withdrawn version is live again')

    def test_n13_a_stale_update_silently_undoes_a_withdrawal(self):
        v1 = self.rec('fmt4', 'a.txt uses VALUE: one', '')
        p2 = self.root_b('P2')
        knowledge.withdraw(self.ledger, p2, v1['id'], reason='VALUE one is wrong', evidence={'sources': [{'type': 'event', 'id': self.event()}]})
        tweak = self.rec('fmt4', 'a.txt uses VALUE: one (typo fixed)', v1['version'])      # root A, base read before the withdrawal
        texts = [e['text'] for e in self.pkg(self.root_b('P3'))['entries']]
        say('n13 stale update after withdrawal', {k: tweak.get(k) for k in ('recorded', 'conflict')}, 'root C delivered', texts)
        self.assertTrue(tweak.get('conflict') or 'a.txt uses VALUE: one (typo fixed)' not in texts, 'withdrawal undone without a conflict')


class N2GeneralArchive(Base):
    def test_n2_archive_of_a_general_entry_is_a_no_op(self):
        g = knowledge.record(self.ledger, 'P1', kind='lesson', text='Produce evidence only after the declared output is checked twice.',
                             scope='general', conditions=['when a node produces evidence'],
                             evidence={'status': 'verified', 'property': 'seen in review', 'sources': [{'type': 'event', 'id': self.event()}]})
        out = knowledge.archive(self.ledger, 'P1', g['id'], reason='no longer relevant')
        p = self.pkg()
        ids = [e['id'] for e in p['entries']] + [r['id'] for r in p['omitted']['index']]
        say('n2 archive result', {k: out.get(k) for k in ('recorded', 'id')}, 'general still listed?', g['id'] in ids, p['omitted']['by_reason'])
        self.assertNotIn(g['id'], ids)


class N16Pack(Base):
    def test_n16_resume_pack_shows_a_withdrawn_root_private_record(self):
        r = knowledge.record(self.ledger, 'P1', kind='note', text='P1 working note: a.txt is VALUE one', visibility='root', applies_to=['a.txt'],
                             evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': self.event()}]})
        knowledge.withdraw(self.ledger, 'P1', r['id'], reason='wrong', evidence={'sources': [{'type': 'event', 'id': self.event()}]})
        in_pkg = r['id'] in [e['id'] for e in self.pkg()['entries']]
        pack = [e['text'] for e in context.for_pack(self.ledger, 'P1')]
        say('n16 withdrawn root note: in package?', in_pkg, 'in resume pack?', 'P1 working note: a.txt is VALUE one' in pack, 'id', r['id'])
        self.assertNotIn('P1 working note: a.txt is VALUE one', pack)


class N19Supersede(Base):
    def test_n19_a_superseder_the_consumer_cannot_use_removes_its_mandatory_constraint(self):
        ev = self.event()
        r1 = knowledge.record(self.ledger, 'P1', kind='constraint', text='a.txt keeps one line', must=True,
                              evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        knowledge.record(self.ledger, 'P1', kind='constraint', text='a.txt keeps one line unless b.txt says otherwise', must=True,
                         supersedes=[r1['id']], scope_paths=['a.txt', 'b.txt'],
                         evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        p = self.pkg(self.root_b('P2'), self.item('D', read=('a.txt',)))
        say('n19 node D (reads a.txt) mandatory entries', [e['id'] for e in p['entries'] if e['must']], p['omitted']['by_reason'])
        self.assertTrue([e for e in p['entries'] if e['must']], 'no mandatory constraint left, nothing held')


class N5LessonScope(Base):
    def test_n5_lesson_about_a_file_reaches_a_node_that_cannot_read_it(self):
        with self.ledger.transaction(write=True) as conn:
            root = plans.anchor_events(self.ledger, conn, 'P1')
            plans.emit(self.ledger, conn, root['task_id'], 'learning.lesson',
                       {'version': 1, 'lesson': 'sec1', 'scope': 'project', 'status': 'verified', 'text': 'Produce evidence of the declared output: b.txt PRIVATE-B token format is X',
                        'location': {'path': 'b.txt', 'line': 1, 'revision': self.head}, 'file_blob': self.git('rev-parse', 'HEAD:b.txt'),
                        'id': 'L9', 'task': root['task_id'], 'plan': 'P1'})
            lesson_event = conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
        context.add(self.ledger, 'P1', kind='note', label='verified', text='Produce evidence of the declared output: b.txt PRIVATE-B token format is X', key='lesson-sec1',
                    source={'type': 'event', 'id': lesson_event})
        p = self.pkg(self.root_b('P2'), self.item('D', read=('a.txt',)))
        hit = [e['use'] for e in p['entries'] if 'PRIVATE-B' in e['text']] + [r['reason'] for r in p['omitted']['index'] if 'PRIVATE-B' in r['title']]
        say('n5 node D (reads a.txt only) receives the b.txt lesson', hit)
        self.assertFalse(hit)


class N3Chain(Base):
    hooks = None

    def factory(self, control, provider):
        case = self
        class Worker:
            def capability(self): return {'provider': provider, 'mode': 'fixture-no-tools'}
            def run(self, attempt, prompt, schema, profile):
                case.calls.append({'prompt': prompt, 'schema': schema})
                control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                if case.hooks: case.hooks.pop(0)()
                control.finish(attempt['id'], attempt['generation'], {'exit_code': 0, 'fixture': True})
            def result(self, attempt):
                return copy.deepcopy(case.values.pop(0)), [{'source': 'fixture'}]
        return Worker()

    def test_n3_claims_of_a_discarded_retained_attempt_are_promoted(self):
        c = self.item('C', read=('a.txt', 'b.txt'))
        self.revise([c, dict(node('I', ['C'], integration=True, write=()), executor=dict(PIN))])
        claim = {'kind': 'finding', 'text': 'a.txt holds VALUE: one (claimed by the discarded attempt)', 'applies_to': ['a.txt'],
                 'sources': ['a.txt'], 'check': 'check-C'}
        self.values.append({'summary': 'gen1', 'files': [{'path': 'a.txt', 'content': 'one\n'}], 'backlog': [], 'knowledge': {'new': [claim]}})
        self.hooks = [lambda: runtime_unknowns.open_unknown(self.ledger, 'P1', 'late-fact', question='Which input?', affected=['C', 'I'],
                                                             required_by=['C'], resolver='doc', evidence=['a.txt:1'])]
        first = self.engine.step(self.ledger, 'P1', self.adapter)
        runtime_unknowns.resolve(self.ledger, 'P1', 'late-fact', by='doc', evidence='a.txt:1', answer='The node changes')
        c2 = dict(c, goal='Produce evidence for O1, rewritten')
        self.revise([c2, dict(node('I', ['C'], integration=True, write=()), executor=dict(PIN))], reason='Rewrite node C after the answer')
        self.values.append({'summary': 'gen2', 'files': [{'path': 'a.txt', 'content': 'right\n'}], 'backlog': []})
        second = self.engine.step(self.ledger, 'P1', self.adapter)
        say('n3 steps', first.get('state'), second.get('state'), 'worker calls', len(self.calls))
        if second.get('state') != 'produced':
            self.skipTest('scenario not reachable in the fixture: ' + json.dumps({k: second.get(k) for k in ('state', 'reason')})[:200])
        def checker(item, artifact):
            return {'artifact': artifact, 'checks': [{'id': x['id'], 'result': 'pass', 'evidence': self.store.blob(b'ok')} for x in item['checks']]}
        self.engine.verify(self.ledger, 'P1', 'C', checker)
        published = [r for r in knowledge.records(self.ledger) if r['text'] == claim['text'] and r['visibility'] == 'project']
        say('n3 claim of the discarded gen-1 attempt published as', [(r['label'], r['evidence'].get('property')) for r in published])
        self.assertFalse(published, 'a claim about a discarded candidate was published as verified for another artifact')
