"""T20 [E5] (W03): no path lets an AI session record a decision in the owner's name — the ledger reply included.

`ledger.reply(decided_by='user')` and `reply(by='owner')` are refused inside an AI tool session (CLAUDE_CODE_CHILD_SESSION), through the
API and through `onecrew ledger request reply --decided-by user`; the request stays pending and no reply event exists. The entry's own
reply (`decided_by='entry'`) is recorded under its own name; the owner's reply from their own terminal (no session marker) is recorded.
"""
import contextlib
import io
import os

from onecrew import ledger_cli
from onecrew.ledger import LedgerError
from onecrew.v2 import plan
from tests.test_v2_l1 import Fixture

QUESTION = {'schema_version': 1, 'question': 'Allow the scoped write?', 'reason': 'The required output needs write permission.',
            'impact': 'Only M2 waits.', 'options': [{'id': 'yes', 'label': 'Allow'}, {'id': 'no', 'label': 'Keep blocked'}],
            'recommendation': 'no', 'action': {'type': 'authorize', 'parameters': {}}}


class ReplyGuardTests(Fixture):
    def setUp(self):
        super().setUp()
        self.propose()
        self.task = plan.show(self.ledger, 'P1')['anchor_task']
        self.req = self.ledger.create_request(self.task, 'write', QUESTION)
        self.saved = dict(os.environ)
        os.environ['CLAUDE_CODE_CHILD_SESSION'] = '1'                                                 # an AI tool session
        os.environ['ONECREW_ACTOR'] = 'codex'

    def tearDown(self):
        os.environ.clear(); os.environ.update(self.saved)
        super().tearDown()

    def cli(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = ledger_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'request', 'reply', self.req['id'],
                                        '--revision', str(self.req['revision']), '--choice', 'no', *extra])
            except LedgerError as error:
                return 'raised', str(error)
        return code, out.getvalue()

    def test_e5_a_reply_attributed_to_the_user_is_refused_in_an_ai_session_by_api_and_cli(self):
        for kwargs in ({'decided_by': 'user'}, {'by': 'owner'}, {'by': 'user'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(LedgerError) as refused:
                self.ledger.reply(self.req['id'], self.req['revision'], 'no', **kwargs)
            self.assertIn('AI tool session', str(refused.exception))
        code, text = self.cli('--decided-by', 'user')
        self.assertTrue(code == 'raised' or code not in (0, None), text)
        self.assertIn('AI tool session', text)
        self.assertEqual(self.ledger.request(self.req['id'])['state'], 'pending')                         # nothing recorded
        self.assertEqual([k for k, _ in self.events() if k == 'request.answered'], [])

    def test_the_entry_may_answer_under_its_own_name_and_the_owner_from_their_own_terminal(self):
        receipt = self.ledger.reply(self.req['id'], self.req['revision'], 'no', decided_by='entry')
        self.assertEqual(self.ledger.request(self.req['id'])['state'], 'answered')
        self.assertEqual(receipt.get('provenance', {}).get('decided_by', 'entry'), 'entry')
        other = self.ledger.create_request(self.task, 'write-2', QUESTION)
        os.environ.pop('CLAUDE_CODE_CHILD_SESSION'); os.environ.pop('ONECREW_ACTOR')                      # the owner's own terminal
        self.ledger.reply(other['id'], other['revision'], 'yes', decided_by='user', by='user')
        self.assertEqual(self.ledger.request(other['id'])['state'], 'answered')
