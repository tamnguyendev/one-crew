"""DEV31 BG-A: background work (subagents, background shell commands) seen under a work item. Real behaviour: state shown, identity kept, nothing counted twice."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onecrew.v2 import background, hook_cli

PLAN = {'plan': 'P1', 'revision': 2, 'anchor': 'A1', 'owned': [], 'status': 'approved'}
T0 = '2026-11-18T10:00:00+00:00'
NOW = '2026-11-18T10:05:00+00:00'


def at(minutes):
    base = background._when(T0)
    import datetime as dt
    return (base + dt.timedelta(minutes=minutes)).isoformat(timespec='seconds')


def launch_agent(agent='ag1', session='s1', tool_use='tu1', status='async_launched', out='C:/out/ag1.txt', **extra):
    return dict({'hook_event_name': 'PostToolUse', 'session_id': session, 'tool_name': 'Agent', 'tool_use_id': tool_use,
                 'tool_input': {'description': 'scan', 'run_in_background': True, 'subagent_type': 'Explore'},
                 'tool_response': {'status': status, 'agentId': agent, 'outputFile': out}}, **extra)


def stop_agent(agent='ag1', session='s1'):
    return {'hook_event_name': 'SubagentStop', 'session_id': session, 'agent_id': agent, 'agent_type': 'Explore'}


def shell(tool_use='tu9', session='s1', command='npm test'):
    return {'hook_event_name': 'PostToolUse', 'session_id': session, 'tool_name': 'Bash', 'tool_use_id': tool_use,
            'tool_input': {'command': command, 'run_in_background': True}, 'tool_response': {}}


def parent_stop(session='s1'):
    return {'hook_event_name': 'Stop', 'session_id': session}


def session_end(session='s1'):
    return {'hook_event_name': 'SessionEnd', 'session_id': session, 'reason': 'other'}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / 'repo'
        (self.project / '.onecrew').mkdir(parents=True)

    def feed(self, event, minute, plan=PLAN, project=None):
        return background.note(event, project or self.project, plan, at=at(minute))

    def view(self, minute=5, **kw):
        return background.view(self.project, now_time=at(minute), **kw)

    def only(self, view=None, **kw):
        value = view or self.view(**kw)
        self.assertEqual(len(value['items']), 1, value['items'])
        return value['items'][0]


class Duplicate(Base):
    def test_duplicate_event_is_one_child_and_counted_once(self):
        first = self.feed(launch_agent(), 0)
        again = self.feed(launch_agent(), 0)
        self.assertEqual((first['written'], again['written'], again['duplicates']), (1, 0, 1))
        self.assertEqual(self.feed(stop_agent(), 3)['written'], 1)
        self.assertEqual(self.feed(stop_agent(), 3)['written'], 0)
        value = self.view()
        self.assertEqual(len(value['items']), 1)
        self.assertEqual(value['counts'], {'running': 0, 'waiting': 0, 'finished': 1, 'unknown': 0})
        self.assertEqual(self.only(value)['events'], 2)

    def test_duplicate_lines_already_in_the_file_are_not_double_counted(self):
        self.feed(launch_agent(), 0)
        path = background.path_of(self.project)
        line = path.read_text(encoding='utf-8')
        path.write_text(line + line + 'not json\n', encoding='utf-8')          # two writers raced; one line is garbage
        value = self.view()
        self.assertEqual(len(value['items']), 1)
        self.assertEqual(value['refused']['duplicate_lines'], 1)
        self.assertEqual(value['refused']['unreadable_lines'], 1)
        self.assertTrue(any('không đọc được' in line for line in value['unobserved']))


class OutOfOrder(Base):
    def test_out_of_order_stop_before_launch_stays_finished(self):
        self.feed(stop_agent(), 3)                               # the end arrives first
        self.feed(launch_agent(), 1)                             # the launch arrives late
        item = self.only()
        self.assertEqual(item['state'], 'finished')
        self.assertEqual(item['started_at'], at(1))
        self.assertEqual(item['finished_at'], at(3))
        self.assertEqual(item['onecrew']['plan'], 'P1')

    def test_out_of_order_same_result_in_either_arrival_order(self):
        for order in (((launch_agent(), 1), (stop_agent(), 3)), ((stop_agent(), 3), (launch_agent(), 1))):
            with self.subTest(order=[o[1] for o in order]):
                self.setUp()
                for event, minute in order: self.feed(event, minute)
                item = self.only()
                self.assertEqual((item['state'], item['started_at'], item['finished_at'], item['events']), ('finished', at(1), at(3), 2))

    def test_out_of_order_stop_without_any_launch_says_the_start_was_not_seen(self):
        self.feed(stop_agent(), 3)
        item = self.only()
        self.assertEqual(item['state'], 'finished')
        self.assertIsNone(item['started_at'])
        self.assertTrue(any('start was not observed' in n for n in item['notes']))


class Reconnect(Base):
    def test_reconnect_session_start_resume_does_not_revive_an_unknown_child(self):
        self.feed(launch_agent(), 0)
        self.feed(session_end(), 2)
        self.assertEqual(self.only(minute=3)['state'], 'unknown')
        self.feed({'hook_event_name': 'SessionStart', 'session_id': 's1', 'source': 'resume'}, 4)
        item = self.only(minute=5)
        self.assertEqual(item['state'], 'unknown')               # a reconnect is not evidence about the child
        self.assertEqual(item['last_observed'], at(0))

    def test_reconnect_activity_of_the_child_after_the_gap_is_running_again_with_the_same_identity(self):
        self.feed(launch_agent(), 0)
        self.feed(session_end(), 2)
        self.feed({'hook_event_name': 'PostToolUse', 'session_id': 's1', 'tool_name': 'Read', 'agent_id': 'ag1', 'agent_type': 'Explore', 'tool_use_id': 'x1'}, 4)
        item = self.only(minute=5)
        self.assertEqual(item['state'], 'running')
        self.assertEqual(item['last_observed'], at(4))
        self.assertEqual(item['host']['agent_id'], 'ag1')
        self.assertEqual(len(self.view()['items']), 1)

    def test_reconnect_does_not_undo_a_finished_child(self):
        self.feed(launch_agent(), 0)
        self.feed(stop_agent(), 1)
        self.feed(session_end(), 2)
        self.feed({'hook_event_name': 'SessionStart', 'session_id': 's1', 'source': 'resume'}, 3)
        self.assertEqual(self.only(minute=4)['state'], 'finished')


class ParentDoneChildRunning(Base):
    def test_parent_done_child_running_is_never_all_done(self):
        self.feed(launch_agent(), 0)
        self.feed(shell(), 1)
        self.feed(parent_stop(), 2)
        value = self.view(minute=3)
        self.assertTrue(value['parent_turn_ended'])
        self.assertFalse(value['all_observed_finished'])
        self.assertEqual(value['counts']['finished'], 0)
        for item in value['items']:
            self.assertEqual(item['state'], 'waiting')
            self.assertIn('parent turn ended', item['state_reason'])

    def test_parent_done_child_running_one_child_finishing_leaves_the_other(self):
        self.feed(launch_agent('ag1', tool_use='t1'), 0)
        self.feed(launch_agent('ag2', tool_use='t2'), 0)
        self.feed(parent_stop(), 1)
        self.feed(stop_agent('ag1'), 2)
        value = self.view(minute=3)
        states = {i['host']['agent_id']: i['state'] for i in value['items']}
        self.assertEqual(states, {'ag1': 'finished', 'ag2': 'waiting'})
        self.assertFalse(value['all_observed_finished'])

    def test_parent_done_child_running_only_when_every_child_has_its_own_end_is_it_all_finished(self):
        self.feed(launch_agent('ag1', tool_use='t1'), 0)
        self.feed(stop_agent('ag1'), 1)
        self.feed(parent_stop(), 2)
        self.assertTrue(self.view(minute=3)['all_observed_finished'])
        self.assertIsNone(background.view(Path(self.tmp.name), now_time=NOW)['all_observed_finished'])      # nothing observed: not "all done", not "none"

    def test_parent_done_child_running_a_later_turn_ending_is_kept_too(self):
        # coordinator review: the first turn's Stop must not swallow every later Stop of the same session (the payload has no turn id)
        self.feed(parent_stop(), 0)
        self.feed(launch_agent('ag2', tool_use='t2'), 1)
        self.feed(parent_stop(), 2)
        value = self.view(minute=3)
        self.assertEqual([i['state'] for i in value['items']], ['waiting'])


class WrongProject(Base):
    def test_wrong_project_lines_of_another_project_are_not_shown(self):
        other = Path(self.tmp.name) / 'other'
        (other / '.onecrew').mkdir(parents=True)
        self.feed(launch_agent('ag1', tool_use='t1'), 0)
        background.note(launch_agent('ag1', tool_use='t1'), other, dict(PLAN, plan='OTHER'), at=at(0))
        # a file copied between projects keeps lines that name the other one
        mixed = background.path_of(self.project).read_text(encoding='utf-8') + background.path_of(other).read_text(encoding='utf-8')
        background.path_of(self.project).write_text(mixed, encoding='utf-8')
        value = self.view()
        self.assertEqual([i['onecrew']['plan'] for i in value['items']], ['P1'])
        self.assertEqual(value['refused']['other_project_lines'], 1)
        self.assertEqual(background.view(other, now_time=at(5))['items'][0]['onecrew']['plan'], 'OTHER')

    def test_wrong_project_a_repo_without_onecrew_is_left_alone(self):
        bare = Path(self.tmp.name) / 'bare'
        bare.mkdir()
        self.assertEqual(background.note(launch_agent(), bare, PLAN)['written'], 0)
        self.assertFalse((bare / '.onecrew').exists())

    def test_wrong_project_plan_filter_does_not_leak_another_plan(self):
        self.feed(launch_agent('ag1', tool_use='t1'), 0, plan=PLAN)
        self.feed(launch_agent('ag2', tool_use='t2'), 0, plan=dict(PLAN, plan='P2'))
        self.assertEqual([i['host']['agent_id'] for i in self.view(plan='P1')['items']], ['ag1'])
        self.assertEqual([i['host']['agent_id'] for i in self.view(plan='P2')['items']], ['ag2'])
        self.assertEqual(self.view(plan='NOPE')['items'], [])


class WrongSession(Base):
    def test_wrong_session_same_agent_id_in_two_sessions_are_two_children(self):
        self.feed(launch_agent('ag1', session='s1', tool_use='t1'), 0)
        self.feed(launch_agent('ag1', session='s2', tool_use='t1'), 0)
        self.feed(stop_agent('ag1', session='s2'), 2)                # only the second session's child ends
        value = self.view(minute=3)
        states = {i['host']['session_id']: i['state'] for i in value['items']}
        self.assertEqual(states, {'s1': 'running', 's2': 'finished'})
        self.assertEqual(len(value['items']), 2)

    def test_wrong_session_a_stop_from_another_session_does_not_finish_this_one(self):
        self.feed(launch_agent('ag1', session='s1'), 0)
        self.feed(stop_agent('ag1', session='s9'), 1)
        value = self.view(minute=2, session='s1')
        self.assertEqual([(i['host']['session_id'], i['state']) for i in value['items']], [('s1', 'running')])
        self.assertEqual([(i['host']['session_id'], i['state']) for i in self.view(minute=2, session='s9')['items']], [('s9', 'finished')])

    def test_wrong_session_parent_stop_of_another_session_does_not_make_this_one_wait(self):
        self.feed(shell(session='s1'), 0)
        self.feed(parent_stop('s2'), 1)
        self.assertEqual(self.only(minute=2)['state'], 'running')

    def test_wrong_session_shell_task_ids_reused_across_sessions_stay_apart(self):
        self.feed(shell('same', 's1'), 0)
        self.feed(shell('same', 's2'), 0)
        self.feed(session_end('s2'), 1)
        states = {i['host']['session_id']: i['state'] for i in self.view(minute=2)['items']}
        self.assertEqual(states, {'s1': 'running', 's2': 'unknown'})


class UnknownOutcome(Base):
    def test_unknown_outcome_subagent_stop_is_finished_but_not_success(self):
        self.feed(launch_agent(), 0)
        self.feed(stop_agent(), 2)
        item = self.only()
        self.assertEqual(item['state'], 'finished')
        self.assertEqual(item['outcome'], 'unknown')
        self.assertIn('chưa biết thành công', item['outcome_label'])
        self.assertTrue(any('chưa biết thành công hay thất bại' in line for line in self.view()['unobserved']))
        self.assertIn('không phải verdict', item['next_step'])

    def test_unknown_outcome_host_completed_is_still_not_a_verified_result(self):
        self.feed(launch_agent(status='completed', out=None), 1)
        item = self.only()
        self.assertEqual((item['state'], item['outcome']), ('finished', 'host_reported_completed'))
        self.assertIn('chưa phải kết quả đã kiểm', item['outcome_label'])

    def test_unknown_outcome_failure_is_failure_and_another_status_is_unknown(self):
        self.feed(launch_agent('ag1', tool_use='t1', status='failed', out=None), 1)
        self.feed(launch_agent('ag2', tool_use='t2', status='weird', out=None), 1)
        by = {i['host']['agent_id']: i['outcome'] for i in self.view()['items']}
        self.assertEqual(by, {'ag1': 'failed', 'ag2': 'unknown'})

    def test_unknown_outcome_launch_failure_hook_is_failed(self):
        self.feed({'hook_event_name': 'PostToolUseFailure', 'session_id': 's1', 'tool_name': 'Agent', 'tool_use_id': 'tf', 'tool_input': {}}, 1)
        item = self.only()
        self.assertEqual((item['state'], item['outcome']), ('finished', 'failed'))


class ProcessGoneNotSuccess(Base):
    def test_process_gone_not_success_a_vanished_shell_task_is_unknown(self):
        self.feed(shell(), 0)
        background.write(self.project, [background.gone_record(self.project, 's1', 'shell', 'tu9', 'pid not found', PLAN, at=at(2))])
        item = self.only(minute=3)
        self.assertEqual(item['state'], 'unknown')
        self.assertNotEqual(item['state'], 'finished')
        self.assertEqual(item['outcome'], 'unknown')
        self.assertIn('not success', item['state_reason'])
        self.assertFalse(self.view(minute=3)['all_observed_finished'])

    def test_process_gone_not_success_session_end_without_an_end_signal_is_unknown(self):
        self.feed(shell(), 0)
        self.feed(session_end(), 1)
        item = self.only(minute=2)
        self.assertEqual((item['state'], item['outcome']), ('unknown', 'unknown'))

    def test_process_gone_not_success_silence_is_unknown_not_hung_and_not_done(self):
        self.feed(shell(), 0)
        fresh = self.only(minute=5)
        self.assertEqual(fresh['state'], 'running')
        stale = self.only(minute=120)
        self.assertEqual(stale['state'], 'unknown')
        self.assertIn('not "hung"', stale['state_reason'])
        self.assertEqual(stale['outcome'], 'unknown')

    def test_process_gone_not_success_shell_end_is_not_observable_and_says_so(self):
        self.feed(shell(), 0)
        item = self.only()
        self.assertTrue(any('no end or exit signal' in n for n in item['notes']))
        self.assertIsNone(item['host']['external_task_id'])


class Unobserved(Base):
    def test_unobserved_empty_view_does_not_claim_there_is_no_background_work(self):
        value = self.view()
        self.assertEqual(value['items'], [])
        self.assertIsNone(value['all_observed_finished'])
        text = background.render(value)
        self.assertIn('không có nghĩa là không có', text)
        self.assertTrue(any('chưa thấy sự kiện SubagentStart' in line for line in value['unobserved']))

    def test_unobserved_lists_the_limits_and_what_is_outside_any_contract(self):
        self.feed(launch_agent(), 0, plan=None)                  # no plan governs this call
        self.feed(shell(), 0)
        value = self.view()
        item_plans = {i['host']['agent_id'] or i['host']['tool_use_id']: i['onecrew'] for i in value['items']}
        self.assertFalse(item_plans['ag1']['bound'])
        self.assertIsNone(item_plans['ag1']['plan'])
        self.assertTrue(item_plans['tu9']['bound'])
        self.assertTrue(any('ngoài mọi hợp đồng' in line for line in value['unobserved']))
        self.assertTrue(any('hook không có tín hiệu' in line for line in value['unobserved']))
        self.assertTrue(any('transcript' in line for line in value['unobserved']))
        self.assertTrue(any('node/attempt' in line for line in value['unobserved']))
        text = background.render(value)
        self.assertIn('NGOÀI hợp đồng', text)
        self.assertIn('CHƯA quan sát', text)

    def test_unobserved_secrets_are_masked_and_nothing_hidden_is_stored(self):
        event = shell(command='curl -H "Authorization: Bearer abcdef123456" --password hunter2 https://x/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')
        event['tool_response'] = {'stdout': 'SECRET-OUTPUT'}
        self.feed(event, 0)
        stop = stop_agent()
        stop['last_assistant_message'] = 'PRIVATE-REASONING'
        stop['agent_transcript_path'] = 'C:/t/transcript.jsonl'
        self.feed(stop, 1)
        raw = background.path_of(self.project).read_text(encoding='utf-8')
        for leaked in ('hunter2', 'abcdef123456', 'SECRET-OUTPUT', 'PRIVATE-REASONING', 'transcript.jsonl', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'):
            self.assertNotIn(leaked, raw)

    def test_unobserved_output_reference_is_shown_but_marked_not_opened(self):
        self.feed(launch_agent(out='C:/out/ag1.txt'), 0)
        item = self.only()
        self.assertEqual(item['output_ref'], 'C:/out/ag1.txt')
        self.assertIn('did not open', item['output_note'])
        self.feed(launch_agent('ag2', tool_use='t2', out=None), 0)
        other = [i for i in self.view()['items'] if i['host']['agent_id'] == 'ag2'][0]
        self.assertIsNone(other['output_ref'])
        self.assertIn('no output reference', other['output_note'])

    def test_unobserved_missing_field_is_unknown_not_invented(self):
        self.feed({'hook_event_name': 'SubagentStop', 'session_id': 's1', 'agent_id': 'agx'}, 1)
        item = self.only()
        self.assertIsNone(item['host']['agent_type'])
        self.assertIsNone(item['onecrew']['attempt'])
        self.assertIsNone(item['host']['external_task_id'])
        self.assertEqual(background.records_from({'hook_event_name': 'SubagentStop', 'session_id': 's1'}, self.project), [])    # no agent_id: nothing to say
        self.assertEqual(background.records_from({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': 'x'}}, self.project), [])


class RestartKeepsBinding(Base):
    def test_restart_keeps_binding_to_the_plan_and_revision_of_the_launch(self):
        self.feed(launch_agent(), 0, plan=PLAN)
        # a new process, a newer revision (and later no plan at all) govern the call that reports the end
        self.feed(stop_agent(), 2, plan=dict(PLAN, revision=3))
        item = self.only()
        self.assertEqual((item['onecrew']['plan'], item['onecrew']['revision'], item['state']), ('P1', 2, 'finished'))
        self.feed(launch_agent('ag7', tool_use='t7'), 3, plan=PLAN)
        self.feed(stop_agent('ag7'), 4, plan=None)
        both = {i['host']['agent_id']: i['onecrew'] for i in self.view()['items']}
        self.assertEqual((both['ag7']['plan'], both['ag7']['revision'], both['ag7']['bound']), ('P1', 2, True))

    def test_restart_keeps_binding_through_a_fresh_reader_with_no_memory(self):
        self.feed(launch_agent(), 0)
        self.feed(shell(), 1)
        self.feed(parent_stop(), 2)
        before = json.dumps(self.view(minute=3), sort_keys=True)
        import importlib
        importlib.reload(background)                              # nothing but the file survives a restart
        after = json.dumps(background.view(self.project, now_time=at(3)), sort_keys=True)
        self.assertEqual(before, after)
        self.assertEqual({i['onecrew']['plan'] for i in background.view(self.project, now_time=at(3))['items']}, {'P1'})

    def test_restart_keeps_binding_unbound_child_is_not_adopted_by_a_later_plan(self):
        self.feed(launch_agent(), 0, plan=None)
        self.feed(stop_agent(), 1, plan=PLAN)                    # the first event had no plan; the end came under P1
        item = self.only()
        self.assertEqual((item['onecrew']['plan'], item['onecrew']['bound']), (None, False))     # stays outside the contract, whatever plan governs later
        self.assertTrue(any('later events were seen under plan P1' in n for n in item['notes']))
        self.assertEqual(item['state'], 'finished')


class HookEndToEnd(Base):
    """The real `hook background|stop` entry points, fed through stdin, write the same records the view reads."""

    def run_hook(self, verb, event):
        argv = ['--project', str(self.project), '--state-root', str(Path(self.tmp.name) / 'state'), 'hook', verb]
        with mock.patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(json.dumps(event).encode()), encoding='utf-8')), redirect_stdout(io.StringIO()) as out:
            code = hook_cli.main(argv)
        return code, out.getvalue()

    def setUp(self):
        super().setUp()
        plan = dict(PLAN, mode='log', non_goals=[], bash_deny=[], protected=[], scratch=[], milestones=[])
        (self.project / '.onecrew' / 'active-plan.json').write_text(json.dumps(plan), encoding='utf-8')

    def test_hook_background_records_launch_and_stop_and_binds_the_active_plan(self):
        self.assertEqual(self.run_hook('background', launch_agent())[0], 0)
        self.assertEqual(self.run_hook('background', stop_agent())[0], 0)
        self.assertEqual(self.run_hook('background', stop_agent())[0], 0)          # the same payload twice
        self.assertEqual(self.run_hook('background', {'hook_event_name': 'PreToolUse', 'tool_name': 'Read'})[0], 0)
        value = background.view(self.project, now_time=background.now())
        item = value['items'][0]
        self.assertEqual((len(value['items']), item['state'], item['onecrew']['plan'], item['onecrew']['revision']), (1, 'finished', 'P1', 2))
        self.assertEqual(item['events'], 2)

    def test_hook_stop_verb_also_notes_the_parent_turn(self):
        self.run_hook('background', shell())
        self.run_hook('stop', parent_stop())
        records, _ = background.load(self.project)
        self.assertIn('parent_stop', [r['ev'] for r in records])

    def test_hook_install_print_background_adds_events_and_default_is_unchanged(self):
        plain = hook_cli.settings(self.project, Path(self.tmp.name), Path(__file__).resolve().parents[1])
        more = hook_cli.settings(self.project, Path(self.tmp.name), Path(__file__).resolve().parents[1], background=True)
        self.assertEqual(set(plain['hooks']), {'PreToolUse', 'UserPromptSubmit', 'Stop', 'SessionStart'})
        self.assertEqual(set(more['hooks']) - set(plain['hooks']), {'PostToolUse', 'SubagentStart', 'SubagentStop', 'SessionEnd'})
        self.assertTrue(all(h['onFailure'] == 'continue' for e in ('PostToolUse', 'SubagentStart', 'SubagentStop', 'SessionEnd') for h in more['hooks'][e][0]['hooks']))

    def test_hook_track_background_cli_prints_the_view(self):
        from onecrew.v2 import tracking_cli
        self.feed(launch_agent(), 0)
        with redirect_stdout(io.StringIO()) as out:
            code = tracking_cli.main(['--project', str(self.project), '--state-root', str(Path(self.tmp.name) / 'state'), 'track', 'background', '--json'])
        data = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(data['items'][0]['host']['agent_id'], 'ag1')
        self.assertTrue(data['read_only'])


if __name__ == '__main__':
    unittest.main()
