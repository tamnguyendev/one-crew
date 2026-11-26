"""TACHPHIEN: `hook prompt` reminds the owner to split a long session: a large context, a large context past the cache lifetime, and a phase boundary.
One `reminded` line per note (rule split_session:big|idle|boundary), a cap per session, silence when the transcript does not tell, and no turn is ever
blocked. The hooks run as subprocesses with the documented stdin JSON; only modules the base has are imported, so a new behaviour is red BY ASSERTION
there.
"""
import contextlib
import datetime as dt
import io
import json
import os

from onecrew.v2 import cli
from tests.test_gsdp_a_standing import StandingFixture

BIG, MEDIUM, SMALL = 900_000, 120_000, 4_000
HOUR_AGO = 2 * 3600                              # past the built-in cache lifetime of one hour


class TestTachPhien(StandingFixture):
    def setUp(self):
        super().setUp()
        os.environ.pop('ONECREW_LANG', None)
        os.environ.pop('CLAUDE_PROJECT_DIR', None)

    # ---- fixtures ----------------------------------------------------------------------------------------------------------------

    def transcript(self, tokens, age=0, padding=3_000_000, name='transcript.jsonl', extra=()):
        """A session transcript: `padding` bytes of user rows, then one assistant turn whose input is `tokens`, `age` seconds old."""
        at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=age)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        filler = json.dumps({'type': 'user', 'sessionId': 's1', 'message': {'role': 'user', 'content': 'x' * 9_900}})
        turn = {'type': 'assistant', 'sessionId': 's1', 'timestamp': at,
                'message': {'id': 'msg_1', 'role': 'assistant', 'content': [{'type': 'text', 'text': 'ok'}],
                            'usage': {'input_tokens': 10, 'cache_creation_input_tokens': tokens // 10, 'cache_read_input_tokens': tokens - tokens // 10 - 10,
                                      'output_tokens': 50}}}
        path = self.state / name
        path.write_text('\n'.join([filler] * (padding // 10_000) + [json.dumps(turn), *(json.dumps(row) for row in extra)]) + '\n', encoding='utf-8')
        return path

    def config(self, **values):
        path = self.state / 'plans' / 'tach-phien.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values), encoding='utf-8')
        return path

    def turn(self, path, prompt='Làm tiếp nhé.', session='s1'):
        event = {'session_id': session, 'cwd': str(self.root), 'hook_event_name': 'UserPromptSubmit', 'prompt': prompt}
        if path is not None: event['transcript_path'] = str(path)
        code, out, err = self.run_hook('prompt', event)
        self.assertEqual(code, 0, err)
        return out

    def split_rules(self):
        return [v['rule'] for v in self.violations() if str(v.get('rule')).startswith('split_session:')]

    def context(self, out):
        self.assertTrue(out.strip(), 'the hook gave Claude no context')
        reply = json.loads(out)
        self.assertNotIn('decision', reply)
        self.assertNotIn('permissionDecision', reply['hookSpecificOutput'])
        return reply['hookSpecificOutput']['additionalContext']

    def pass_one_milestone(self):
        for path in self.copies():
            document = json.loads(path.read_text(encoding='utf-8'))
            next(m for m in document['milestones'] if m['state'] != 'passed')['state'] = 'passed'
            path.write_text(json.dumps(document), encoding='utf-8')

    # ---- the three notes ---------------------------------------------------------------------------------------------------------

    def test_big_context_owner_turn_warns(self):
        self.plain(mode='enforce')
        out = self.turn(self.transcript(BIG), prompt='chữ-của-chủ-5521')
        self.assertEqual(self.split_rules(), ['split_session:big'])
        text = self.context(out)
        self.assertIn('onecrew continue P1', text)
        self.assertIn('900k', text)
        line = [v for v in self.violations() if v['rule'] == 'split_session:big'][0]
        self.assertEqual((line['event'], line['tool'], line['plan'], line['session']), ('reminded', 'UserPromptSubmit', 'P1', 's1'))
        self.assertNotIn('chữ-của-chủ-5521', (self.root / '.onecrew' / 'violations.jsonl').read_text(encoding='utf-8'))
        os.environ['ONECREW_LANG'] = 'vi'
        self.assertIn('tách phiên', self.context(self.turn(self.transcript(BIG))))

    def test_idle_over_ttl_says_idle(self):
        self.plain(mode='log')
        path = self.transcript(BIG, age=HOUR_AGO)
        text = self.context(self.turn(path))
        self.assertEqual(self.split_rules(), ['split_session:idle'])
        self.assertIn('whole context again', text)
        self.assertIn('onecrew continue P1', text)
        self.config(ttl_seconds=3 * 3600)                                    # the owner's longer lifetime: the same turn is only "big"
        self.turn(path, session='s2')
        self.assertEqual(self.split_rules(), ['split_session:idle', 'split_session:big'])

    def test_boundary_suggestion_once_per_state(self):
        self.plain(mode='enforce')
        path = self.transcript(MEDIUM)
        self.assertIn('onecrew continue P1', self.context(self.turn(path)))
        self.assertEqual(self.split_rules(), ['split_session:boundary'])
        out = self.turn(path)
        self.assertEqual(self.split_rules(), ['split_session:boundary'])
        self.assertNotIn('onecrew continue', out)

    def test_milestone_passed_is_a_new_boundary(self):
        self.plain(mode='enforce')
        path = self.transcript(MEDIUM)
        self.turn(path)
        self.pass_one_milestone()
        self.assertIn('onecrew continue P1', self.context(self.turn(path)))
        self.assertEqual(self.split_rules(), ['split_session:boundary'] * 2)
        self.turn(path)
        self.assertEqual(self.split_rules(), ['split_session:boundary'] * 2)

    def test_cap_per_session(self):
        self.plain(mode='enforce')
        path = self.transcript(BIG)
        for _ in range(4): self.turn(path)
        self.assertEqual(self.split_rules(), ['split_session:big'] * 3)          # the built-in cap
        self.config(max_reminders=1)
        for _ in range(3): self.turn(path, session='s2')
        self.assertEqual(self.split_rules(), ['split_session:big'] * 4)
        self.config(off=True)
        self.assertNotIn('onecrew continue', self.turn(path, session='s3'))
        self.assertEqual(self.split_rules(), ['split_session:big'] * 4)

    def test_owner_note_and_split_note_together(self):
        self.standing(mode='enforce')
        text = self.context(self.turn(self.transcript(BIG)))                    # one JSON reply holds both
        self.assertIn('YEU-CAU-CHU.vi.md', text)
        self.assertIn('onecrew continue P1', text)
        rules = [v['rule'] for v in self.violations()]
        self.assertIn('owner_prompt', rules)
        self.assertIn('split_session:big', rules)

    # ---- never a gate, and silence -----------------------------------------------------------------------------------------------

    def test_never_blocks(self):
        self.plain(mode='enforce')
        self.config(tokens=1, ttl_seconds=0, max_reminders=99)
        for path in (self.transcript(BIG, age=HOUR_AGO), self.transcript(BIG)):
            out = self.turn(path)
            self.assertNotIn('"decision"', out)
            self.assertNotIn('permissionDecision', out)
        (self.state / 'plans' / 'tach-phien.json').write_text('{broken', encoding='utf-8')
        out = self.turn(self.transcript(BIG))
        self.assertNotIn('permissionDecision', out)

    def test_not_owner_typed_silent(self):
        self.plain(mode='enforce')
        path = self.transcript(BIG, age=HOUR_AGO)
        for prompt in ('<cross-session-message from="local_x">\nlàm tiếp\n</cross-session-message>', '<task-notification>x</task-notification>',
                       '<system-reminder>x</system-reminder>', '[Cross-session idle notice] idle'):
            self.assertNotIn('onecrew continue', self.turn(path, prompt=prompt))
        self.assertEqual(self.split_rules(), [])

    def test_bad_transcript_silent(self):
        self.plain(mode='enforce')
        garbage, empty = self.state / 'garbage.jsonl', self.state / 'empty.jsonl'
        garbage.write_bytes(b'\x00\xff not json\n[1, 2]\n{"type": "assistant", "message": {"usage": "many"}}\n')
        empty.write_bytes(b'')
        compacted = self.transcript(BIG, name='compacted.jsonl', extra=[{'type': 'system', 'subtype': 'compact_boundary'}])
        for path in (None, self.state / 'missing.jsonl', self.state, garbage, empty, compacted):
            self.assertNotIn('onecrew continue', self.turn(path), str(path))
        self.assertEqual(self.split_rules(), [])

    def test_idle_small_context_silent(self):
        self.plain(mode='enforce')
        self.assertNotIn('onecrew continue', self.turn(self.transcript(SMALL, age=HOUR_AGO)))
        self.assertEqual(self.split_rules(), [])

    # ---- the owner's option do-usage: the tokens of the last assistant turn count, not the size of the file -----------------------

    def test_option_usage_small_file_big_usage_warns(self):
        self.plain(mode='enforce')
        self.config(tokens=500_000)
        self.turn(self.transcript(600_000, padding=0))
        self.assertEqual(self.split_rules(), ['split_session:big'])

    def test_option_usage_big_file_small_usage_silent(self):
        self.plain(mode='enforce')
        self.turn(self.transcript(SMALL, padding=6_000_000))
        self.assertEqual(self.split_rules(), [])

    # ---- controls ----------------------------------------------------------------------------------------------------------------

    def test_small_context_no_split_note(self):
        self.plain(mode='enforce')
        self.assertNotIn('onecrew continue', self.turn(self.transcript(SMALL, padding=0)))
        self.assertEqual(self.split_rules(), [])

    def test_continue_command_exists(self):
        self.plain(mode='log')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.state), 'continue', 'P1'])
        self.assertEqual(code, 0, output.getvalue())
        self.assertIn('P1', output.getvalue())
