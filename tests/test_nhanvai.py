"""NHANVAI: an optional role label on each sub-task of an internal plan ("role": "backend"), shown as @role under the sub-task on the
tracking page with its status words ("xong · cổng đạt" / "đang làm" / "chờ task 2, 3"), carried by `engine state` with the sub-tasks it
still waits for; option nhan-co-vung: the plan's roles table (role -> file area) and a report of a sub-task that writes outside its area.

Rule of these cases (contract NHANVAI, checker kiem-nhanvai.py): a case of new behaviour fails BY ASSERTION on the base 2.5.0.dev33
(191a58f): a missing name or a refused field is turned into self.fail, never an error. Real temporary ledger, Git and Control attempts
(tests.test_wf_engine.EngineFixture); the page cases run the shipped page script under node, as tests.test_tracking_situation does.
"""
import json
import shutil
import subprocess

from onecrew.ledger import LedgerError
from onecrew.v2 import engine, internal_plan as ip, tracking
from onecrew.v2.tracking_web import PAGE
from tests.test_wf_engine import EngineFixture, node


def labelled(nid, role=None, dependencies=(), integration=False, write=('a.txt',)):
    """node() of test_wf_engine with the NHANVAI label; dependencies are (node, requires) pairs."""
    value = node(nid, integration=integration, write=write)
    value['depends'] = [{'node': upstream, 'requires': requires} for upstream, requires in dependencies]
    if role is not None: value['role'] = role
    return value


def picture(roles=True):
    """The owner's picture of 25/11 22:34: two backend sub-tasks, one frontend, the lead's integration that needs the second accepted."""
    role = (lambda r: r) if roles else (lambda r: None)
    return [labelled('BE1', role('backend'), write=('a.txt',)),
            labelled('BE2', role('backend'), [('BE1', 'verified')], write=('a.txt',)),
            labelled('FE', role('frontend'), [('BE1', 'verified')], write=('b.txt',)),
            labelled('LEAD', role('lead'), [('BE1', 'verified'), ('BE2', 'accepted'), ('FE', 'verified')], integration=True, write=())]


class TestNhanVai(EngineFixture):
    def revise_or_fail(self, nodes, **kw):
        """The base refuses a node field it does not know (or a keyword it does not take): that is the missing behaviour, so a FAILURE."""
        try:
            return self.ip.revise(self.ledger, 'P1', nodes, reason='Split work inside the approved scope', evidence=['a.txt:1'], **kw)
        except (LedgerError, TypeError) as error:
            self.fail('an internal plan with role labels (or a roles table) is not accepted: ' + str(error)[:300])

    def definition(self):
        return self.ip.current(self.ledger, 'P1')['definition']

    def js(self, expr, extra=''):
        runner = shutil.which('node')
        if not runner: self.skipTest('Node unavailable; not verified')
        start = PAGE.index('<script>') + 8; body = PAGE[start:PAGE.rindex('</script>')].replace('@@INTERVAL@@', '2000')
        body = body.replace('(function(){', '', 1); body = body[:body.rindex('})();')]
        stub = ("var document={querySelector:function(){return {addEventListener:function(){},value:'',options:[],style:{}}},querySelectorAll:function(){return []},addEventListener:function(){}};"
                "var window={matchMedia:function(){return {matches:false,addEventListener:function(){}}},addEventListener:function(){},scrollTo:function(){},scrollY:0};"
                "var location={search:'',pathname:'/'};var history={pushState:function(){}};var localStorage={getItem:function(){return null},setItem:function(){}};"
                "function setInterval(){};function setTimeout(){};function fetch(){return {then:function(){return {then:function(){return {catch:function(){return {then:function(){}}}}}}}}};")
        result = subprocess.run([runner, '-'], input=stub + body + extra + '\nconsole.log(JSON.stringify(' + expr + '));', text=True, encoding='utf8',
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return json.loads(result.stdout.strip().splitlines()[-1])

    # ---- I1: the label -------------------------------------------------------------------------------------------------------------
    def test_node_with_role_label_is_accepted(self):
        self.revise_or_fail([labelled('C', 'backend'), labelled('I', 'lead', [('C', 'verified')], integration=True, write=())])
        nodes = {n['id']: n for n in self.definition()['nodes']}
        self.assertEqual(nodes['C'].get('role'), 'backend')
        self.assertEqual(nodes['I'].get('role'), 'lead')
        self.assertNotIn('executor', nodes['C'])                  # the label is not an executor pin
        self.step(); self.verify('C')                             # it runs exactly as an unlabelled node
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'verified')

    def test_bad_role_label_is_refused(self):
        for bad in ('Backend', 'back end', 'x' * 25, '-backend', '', 'bé', 'a_b', 5, None, ['backend']):
            with self.subTest(role=bad):
                with self.assertRaisesRegex(LedgerError, 'role'):
                    self.revise([labelled('C', 'backend') | {'role': bad}, labelled('I', None, [('C', 'verified')], integration=True, write=())])
        self.assertEqual(self.ip.current(self.ledger, 'P1')['internal_revision'], 0)      # nothing was published
        self.revise([labelled('C', 'a' * 24), labelled('I', '9-lead', [('C', 'verified')], integration=True, write=())])   # the longest form is taken

    def test_executor_role_stays_worker(self):
        item = labelled('C', 'backend') | {'executor': {'role': 'backend', 'provider': 'claude', 'model': 'claude-sonnet-5-5'}}
        with self.assertRaisesRegex(LedgerError, 'role=worker'):
            self.revise([item, labelled('I', None, [('C', 'verified')], integration=True, write=())])

    def test_plan_without_role_unchanged(self):
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        definition = self.definition()
        self.assertEqual(set(definition), {'version', 'nodes', 'acceptance'})            # no roles table key in an old-style plan
        self.assertFalse(any('role' in n for n in definition['nodes']))
        self.step(); self.verify('C')
        view = engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['C']['state'], view['nodes']['C']['generation']), ('verified', 0))
        self.assertEqual([t['id'] for t in engine.ready(self.ledger, 'P1')], ['I'])

    # ---- I2: a label is display only ------------------------------------------------------------------------------------------------
    def test_role_change_does_not_bump_generation(self):
        first = [labelled('C', 'backend'), labelled('I', 'lead', [('C', 'verified')], integration=True, write=())]
        self.revise_or_fail(first)
        self.step(); self.verify('C')
        before = engine.state(self.ledger, 'P1')['nodes']['C']
        relabelled = [dict(first[0], role='frontend'), dict(first[1])]
        relabelled[1].pop('role')                                 # a label removed is also only a label
        self.revise_or_fail(relabelled)
        after = engine.state(self.ledger, 'P1')
        self.assertEqual(after['internal_revision'], 2)
        self.assertEqual((after['nodes']['C']['generation'], after['nodes']['C']['state'], after['nodes']['C']['artifact']),
                         (before['generation'], 'verified', before['artifact']), 'relabelling moved the node: it would run again')
        self.assertEqual(after['nodes']['I']['generation'], 0)
        self.assertEqual([n.get('role') for n in after['definition']['nodes']], ['frontend', None])
        changed = [dict(relabelled[0], goal='Produce other evidence for O1'), relabelled[1]]
        self.revise(changed)                                      # control: a real change still moves the node
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['generation'], 1)

    def test_projection_ignores_role(self):
        bare, roled = picture(roles=False), picture(roles=True)
        self.assertEqual(ip.projection(bare), ip.projection(roled))
        self.assertEqual(ip.influence_projection(bare), ip.influence_projection(roled))

    # ---- I3: engine state and the tracking detail -----------------------------------------------------------------------------------
    def test_engine_state_nodes_carry_role_and_waits_for(self):
        self.revise_or_fail(picture())
        view = engine.state(self.ledger, 'P1')
        got = lambda: {nid: (r.get('role'), r.get('waits_for')) for nid, r in engine.state(self.ledger, 'P1')['nodes'].items()}
        self.assertEqual(got(), {'BE1': ('backend', []), 'BE2': ('backend', ['BE1']), 'FE': ('frontend', ['BE1']),
                                 'LEAD': ('lead', ['BE1', 'BE2', 'FE'])})
        self.step(); self.verify('BE1')
        self.assertEqual(got()['LEAD'], ('lead', ['BE2', 'FE']))
        self.assertEqual(got()['FE'], ('frontend', []))
        self.step(); self.verify('BE2')                           # verified is not the accepted LEAD requires of BE2: still waited for
        self.assertEqual(got()['LEAD'], ('lead', ['BE2', 'FE']), 'waits_for must follow the declared requires and order')
        self.assertIn('BE1', view['nodes'])

    def test_tracking_task_nodes_carry_role_and_waits_for(self):
        self.revise_or_fail(picture())
        self.step(); self.verify('BE1')
        nodes = tracking.detail(self.ledger.state_root, 'P1')['nodes']
        self.assertEqual(list(nodes), ['BE1', 'BE2', 'FE', 'LEAD'])                     # plan order: the page numbers the rows by it
        self.assertEqual({nid: (n.get('role'), n.get('waits_for')) for nid, n in nodes.items()},
                         {'BE1': ('backend', []), 'BE2': ('backend', []), 'FE': ('frontend', []), 'LEAD': ('lead', ['BE2', 'FE'])})
        overview = tracking.overview(self.ledger.state_root)['projects'][0]['tasks'][0]
        self.assertNotIn('nodes', overview)                       # the list stays light: the labels are in the task detail only

    # ---- I4: the page ---------------------------------------------------------------------------------------------------------------
    def page_data(self):
        return {'node_titles': {'BE1': 'BE viết hợp đồng API', 'BE2': 'BE làm API', 'FE': 'FE làm giao diện', 'LEAD': 'Lead kiểm tích hợp, ghi quyết định'},
                'nodes': {'BE1': {'phase': 'complete', 'state': 'verified', 'generation': 0, 'role': 'backend', 'waits_for': []},
                          'BE2': {'phase': 'complete', 'state': 'accepted', 'generation': 0, 'role': 'backend', 'waits_for': []},
                          'FE': {'phase': 'running', 'state': 'none', 'generation': 0, 'role': 'frontend', 'waits_for': []},
                          'LEAD': {'phase': 'pending', 'state': 'none', 'generation': 0, 'role': 'lead', 'waits_for': ['BE2', 'FE']}}}

    def test_page_shows_role_and_status_words(self):
        d = self.page_data()
        html, nodes_html = self.js("[typeof taskList==='function'?taskList(d):null, legacyNodes(d)]", '\nvar d=' + json.dumps(d) + ';')
        self.assertIsNotNone(html, 'the page has no "Danh sách task" block')
        self.assertIn('Danh sách task', html)
        for wanted in ('@backend', '@frontend', '@lead', 'xong · cổng đạt', 'đang làm', 'chờ task 2, 3', 'BE viết hợp đồng API', '<b>4.</b>'):
            self.assertIn(wanted, html)
        self.assertEqual(html.count('xong · cổng đạt'), 2)
        rows = html.split('<li')[1:]
        self.assertEqual(len(rows), 4)
        self.assertLess(rows[0].index('BE viết'), rows[0].index('@backend'))           # the label under the name
        self.assertIn('class="tl-st ok"', rows[0]); self.assertIn('class="tl-st run"', rows[2]); self.assertIn('class="tl-st wait"', rows[3])
        self.assertLess(nodes_html.index('Danh sách task'), nodes_html.index('<h3>Phần việc</h3>'))   # the table stays, under the block

    def test_page_escapes_and_old_nodes_show_no_label(self):
        d = self.page_data()
        d['node_titles']['BE1'] = '<img src=x onerror=alert(1)>'
        for n in d['nodes'].values(): n.pop('role')
        html = self.js("typeof taskList==='function'?taskList(d):''", '\nvar d=' + json.dumps(d) + ';')
        if not html: self.fail('the page has no "Danh sách task" block')
        self.assertNotIn('<img', html); self.assertIn('&lt;img', html)
        self.assertNotIn('tl-role', html)                         # an unlabelled sub-task has no @ line
        self.assertEqual(self.js("typeof taskList==='function'?taskList({nodes:{}}):'x'"), '')

    # ---- I5 (option nhan-co-vung): the roles table --------------------------------------------------------------------------------
    def test_write_outside_role_area_is_reported(self):
        report_of = getattr(ip, 'role_area_report', None)
        if report_of is None: self.fail('the internal plan has no roles table report (option nhan-co-vung)')
        nodes = picture()
        nodes[2]['write'] = ['a.txt', 'b.txt']                    # FE also writes the backend's file
        nodes[3]['role'] = 'qa'                                   # a label the table does not name
        table = {'backend': ['a.txt'], 'frontend': ['b.*'], 'lead': ['docs/']}
        result = self.revise_or_fail(nodes, roles=table)
        expected = [{'node': 'FE', 'role': 'frontend', 'kind': 'outside_area', 'paths': ['a.txt']},
                    {'node': 'LEAD', 'role': 'qa', 'kind': 'role_not_in_table', 'paths': []}]
        self.assertEqual(result.get('role_area_report'), expected)                       # reported when the plan is made
        self.assertEqual(self.definition().get('roles'), table)
        self.assertEqual(engine.state(self.ledger, 'P1').get('role_area_report'), expected)   # and in engine state
        self.assertEqual(tracking.detail(self.ledger.state_root, 'P1')['nodes']['FE'].get('role_area'), {'kind': 'outside_area', 'paths': ['a.txt']})
        self.step(); self.verify('BE1')                           # reported, not refused: the plan runs as without the table
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['BE1']['state'], 'verified')
        self.assertEqual(report_of(nodes, {}), [])

    def test_roles_table_kept_by_a_nodes_only_revision_and_removed_by_an_empty_one(self):
        self.revise_or_fail(picture(), roles={'backend': ['a.txt'], 'frontend': ['b.txt'], 'lead': ['a.txt', 'b.txt']})
        again = picture(); again[0]['goal'] = 'Write the API contract for O1'
        self.revise(again)                                        # a revision that passes nodes only (repair, recovery) keeps the table
        self.assertEqual(self.definition().get('roles'), {'backend': ['a.txt'], 'frontend': ['b.txt'], 'lead': ['a.txt', 'b.txt']})
        self.assertEqual(engine.state(self.ledger, 'P1')['role_area_report'], [])
        self.revise_or_fail(again, roles={})
        self.assertNotIn('roles', self.definition())

    def test_bad_roles_table_is_refused(self):
        for bad in ({'Backend': ['a.txt']}, {'backend': []}, {'backend': 'a.txt'}, {'backend': ['../x']}, {'backend': ['C:/x']}, ['backend'],
                    {'r%d' % i: ['a.txt'] for i in range(41)}):
            with self.subTest(roles=bad):
                with self.assertRaises((LedgerError, TypeError)):
                    self.ip.revise(self.ledger, 'P1', picture(), reason='Split work inside the approved scope', evidence=['a.txt:1'], roles=bad)
        self.assertEqual(self.ip.current(self.ledger, 'P1')['internal_revision'], 0)
