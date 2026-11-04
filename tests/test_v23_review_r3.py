"""Review round 3 probes (8709bfa). Each test asserts the EXPECTED behaviour; a failure = defect reproduced."""
from onecrew.v2 import knowledge
from tests.test_v23_a1_knowledge import fence
from tests.test_v23_review_r1 import Base, say


class R3(Base):
    def test_r3a_contradiction_reason_carries_text_of_a_record_the_reader_may_not_read(self):
        self.page('rules.md', '## a.txt rule\n' + fence({'id': 'a-rule', 'kind': 'constraint', 'label': 'verified', 'applies_to': ['a.txt'],
                  'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + 'a.txt keeps one line.\n')
        self.revise([self.item('C', read=('a.txt', 'b.txt')), dict(__import__('tests.test_wf_engine', fromlist=['node']).node('I', ['C'], integration=True, write=()),
                                                                   executor=dict(__import__('tests.test_v23_a1_knowledge', fromlist=['PIN']).PIN))])
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'right\n'}], 'backlog': [],
                            'knowledge': {'used': [], 'requests': [], 'new': [],
                                          'rejected': [{'id': 'a-rule', 'why': 'b.txt holds the PRIVATE-B token, so a-rule is wrong'}]}})
        produced = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(produced['state'], 'produced', produced)
        def checker(item, artifact):
            return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'pass', 'evidence': self.store.blob(b'ok')} for c in item['checks']]}
        self.verify('C', checker)
        d = self.pkg(self.root_b('P2'), self.item('D', read=('a.txt',)))       # node D may not read b.txt
        rule = next((e for e in d['entries'] if e['id'] == 'a-rule'), None)
        leaked = [r for r in (rule or {}).get('applicability', {}).get('reasons', []) if 'PRIVATE-B' in r]
        say('r3a a-rule for node D (reads a.txt only)', rule and (rule['use'], rule['applicability']), 'by_reason', d['omitted']['by_reason'])
        self.assertFalse(leaked, 'text of a record outside the read scope reached the reader through a reason')

    def test_r3b_entry_superseded_by_a_record_the_reader_cannot_read_is_delivered_as_a_plain_fact(self):
        ev = self.event()
        r1 = knowledge.record(self.ledger, 'P1', kind='constraint', text='a.txt keeps one line', must=True, applies_to=['a.txt'],
                              evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}, {'type': 'file', 'path': 'a.txt', 'revision': 'HEAD'}]})
        knowledge.record(self.ledger, 'P1', kind='constraint', text='a.txt keeps one line unless b.txt says otherwise', must=True,
                         supersedes=[r1['id']], scope_paths=['a.txt', 'b.txt'],
                         evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        p = self.pkg(self.root_b('P2'), self.item('D', read=('a.txt',)))
        e = next((x for x in p['entries'] if x['id'] == r1['id']), None)
        say('r3b superseded r1 for node D', e and (e['use'], e['must'], e['applicability']), p['omitted']['by_reason'])
        self.assertTrue(e is None or e['use'] != 'fact' or any('supersed' in r for r in e['applicability']['reasons']),
                        'superseded knowledge delivered as a current fact with no marker')


class R3CorrectionBase(Base):
    def test_r3c_a_correction_based_on_the_withdrawal_is_the_next_version_not_contested(self):
        ev = self.event()
        ent = lambda text, base: knowledge.record(self.ledger, 'P1', kind='decision', key='fmt9', base=base, text=text, applies_to=['a.txt'],
                                                  evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        v1 = ent('a.txt uses VALUE: one', '')
        knowledge.withdraw(self.ledger, 'P1', v1['id'], reason='wrong value', evidence={'sources': [{'type': 'event', 'id': ev}]})
        state = {r['id']: r for r in knowledge.records(self.ledger, history=True)}[v1['id']]
        self.assertNotEqual(state['state_version'], v1['version'])          # the withdrawal is the subject's newest state
        fixed = ent('a.txt uses VALUE: two (corrected)', state['state_version'])
        self.assertFalse(fixed.get('conflict')); self.assertEqual(fixed['id'], v1['id'])
        delivered = {e['text']: e for e in self.pkg()['entries']}
        self.assertEqual(delivered['a.txt uses VALUE: two (corrected)']['use'], 'fact')
        stale = ent('a.txt uses VALUE: one (stale)', v1['version'])           # N13 still holds: a write from before the withdrawal conflicts
        self.assertTrue(stale.get('conflict'))
        delivered = {e['text']: e for e in self.pkg()['entries']}
        corrected = delivered['a.txt uses VALUE: two (corrected)']
        self.assertEqual(corrected['use'], 'lead')                           # and the concurrent stale version is kept, contesting it
        self.assertTrue(any('contested' in r for r in corrected['applicability']['reasons']))
