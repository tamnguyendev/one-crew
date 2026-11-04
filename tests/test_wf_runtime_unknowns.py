"""T02: runtime unknowns hold only required nodes, not independent work."""
from onecrew.ledger import LedgerError
from tests.test_wf_engine import EngineFixture, node


class RuntimeUnknownTests(EngineFixture):
    def setUp(self):
        super().setUp()
        from onecrew.v2 import runtime_unknowns
        self.unknowns = runtime_unknowns
        self.revise([node('B1a'), node('B1b', ['B1a']), node('B2', write=('b.txt',)),
                     node('B3', write=('b.txt',)), node('I', ['B1a','B1b','B2','B3'], integration=True, write=())])

    def opened(self, key='U-local', affected=None, required=None):
        return self.unknowns.open_unknown(self.ledger, 'P1', key, question='Which input format is supported?',
            affected=affected or ['B1a','B1b'], required_by=required or ['B1b'], resolver='doc', evidence=['a.txt:1'])

    def test_local_and_global_unknowns_preserve_independent_execution(self):
        self.opened()
        self.assertEqual(self.unknowns.blockers(self.ledger, 'P1'), {'B1b':['U-local']})
        self.assertEqual(self.step()['node'], 'B1a'); self.verify('B1a')
        self.assertEqual(self.step()['node'], 'B2'); self.verify('B2')
        self.opened('U-global', affected='root', required=['B3','I'])
        self.assertEqual(self.engine.ready(self.ledger, 'P1'), [])
        self.assertEqual(self.unknowns.blockers(self.ledger, 'P1'), {'B1b':['U-local'],'B3':['U-global'],'I':['U-global']})
        self.unknowns.resolve(self.ledger, 'P1', 'U-local', by='doc', evidence='a.txt:1', answer='The existing input is plain text.')
        self.assertEqual(self.step()['node'], 'B1b')

    def test_resolution_requires_correct_role_and_resolving_evidence(self):
        self.opened()
        for by, evidence in [('poc','a.txt:1'),('doc','resolved'),('doc','missing.txt:99')]:
            with self.subTest(by=by,evidence=evidence), self.assertRaises(LedgerError):
                self.unknowns.resolve(self.ledger,'P1','U-local',by=by,evidence=evidence,answer='resolved')
        self.assertEqual(self.unknowns.blockers(self.ledger,'P1'), {'B1b':['U-local']})
        self.assertEqual(self.ledger.requests(self.root_view['anchor_task']), [])

    def test_idempotency_and_internal_revision_cannot_erase_an_open_unknown(self):
        opened=self.opened()
        self.assertEqual(self.opened()['event'], opened['event'])
        changed=self.ip.current(self.ledger,'P1')['definition']['nodes']
        changed[2]['goal']+=' independently refined'
        self.revise(changed)
        self.assertEqual(self.unknowns.blockers(self.ledger,'P1'), {'B1b':['U-local']})
        self.unknowns.resolve(self.ledger,'P1','U-local',by='doc',evidence='a.txt:1',answer='text confirmed')
        self.assertEqual(self.unknowns.blockers(self.ledger,'P1'), {})

    def test_estimate_unknown_requires_bounded_readonly_survey_dependency(self):
        with self.assertRaisesRegex(LedgerError, 'survey'):
            self.unknowns.open_unknown(self.ledger,'P1','U-est',question='Unknown data size',affected=['B1b'],
                required_by=['B1b'],resolver='poc',evidence=['a.txt:1'],blocks_estimate=True)

    def test_cli_and_present_expose_precise_hold_without_writes_on_read(self):
        import contextlib, io, json
        from onecrew.v2 import cli, report, resume_pack
        self.opened()
        before=self.ledger.events(self.root_view['anchor_task'])
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=cli.main(['--project',str(self.root),'--state-root',str(self.ledger.state_root),'unknown','list','--plan','P1'])
        self.assertEqual(code,0,out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['blocked_nodes'], {'B1b':['U-local']})
        shown=report.render_present(self.ledger.state_root,'P1')
        self.assertIn('giữ B1b',shown)
        pack=resume_pack.build(self.ledger,'P1')
        self.assertEqual(pack['runtime_unknowns'][0]['resolver'],'doc')
        self.assertEqual(self.ledger.events(self.root_view['anchor_task']),before)

    def test_estimate_unknown_runs_survey_before_implementation_and_requires_its_receipt(self):
        definition=self.ip.current(self.ledger,'P1')['definition']['nodes']
        definition.insert(0,node('Survey',write=()))
        definition[2]['depends'].append({'node':'Survey','requires':'verified'})
        definition[-1]['depends'].append({'node':'Survey','requires':'verified'})
        self.revise(definition)
        self.unknowns.open_unknown(self.ledger,'P1','U-est',question='Unknown data size',affected=['B1b'],
            required_by=['B1b'],resolver='poc',evidence=['a.txt:1'],blocks_estimate=True,survey_node='Survey')
        with self.assertRaisesRegex(LedgerError,'survey'):
            self.unknowns.resolve(self.ledger,'P1','U-est',by='poc',evidence='a.txt:1',answer='bounded')
        self.assertEqual(self.step()['node'],'Survey'); self.verify('Survey')
        with self.assertRaisesRegex(LedgerError,'survey evidence'):
            self.unknowns.resolve(self.ledger,'P1','U-est',by='poc',evidence='a.txt:1',answer='bounded')
        record=self.engine.state(self.ledger,'P1')['nodes']['Survey']
        self.unknowns.resolve(self.ledger,'P1','U-est',by='poc',evidence=record['verification_receipt'],answer='Bounded survey completed with evidence.')
        self.assertEqual(self.unknowns.blockers(self.ledger,'P1'),{})

    def test_removing_required_node_does_not_erase_open_unknown(self):
        self.opened()
        definition=self.ip.current(self.ledger,'P1')['definition']['nodes']
        definition=[n for n in definition if n['id']!='B1b']
        definition[-1]['depends']=[e for e in definition[-1]['depends'] if e['node']!='B1b']
        with self.assertRaises(LedgerError): self.revise(definition)
        self.assertEqual(self.unknowns.blockers(self.ledger,'P1'), {'B1b':['U-local']})
