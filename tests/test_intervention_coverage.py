"""Every mutating CLI subcommand records control.intervention (A2, 12/10/2026).

The scorecard reads "no recorded intervention" as zero only for a traced runtime; an unrecorded mutating command
would make entry help invisible. This walks each covered CLI's argparse tree: every leaf is either on its explicit
read-only allowlist or recorded, and running each recorded leaf (business logic stubbed) leaves a record attributed
to ONECREW_ACTOR, on its task or, for task-less commands, at project scope."""
import argparse
import ast
import contextlib
import inspect
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

from onecrew import (android_build, cli, conversation_cli, control_cli, delegations, delivery_cli, desktop_notifications,
                     entry_cli, evaluation, interventions as iv, ledger_cli, owned_cli, workflow_cli)
from onecrew import eval_scorecard as sc
from tests.test_interventions import LedgerFixture

COVERED = (ledger_cli, owned_cli, delivery_cli, workflow_cli, conversation_cli, control_cli, evaluation, delegations,
           desktop_notifications, android_build, entry_cli)
# Every (group, module) cli.main reaches outside a COVERED module, with why it is not a task intervention and its
# commands pinned: a new group, or a new command in an exempt module, is red until someone classifies it.
EXEMPT_GROUPS = {
    ('spec', 'specs'): ('spec-level review and approval, not task-scoped',
                        {'spec list', 'spec review', 'spec diff', 'spec approve', 'spec request-changes', 'spec history'}),
    ('task', 'runtime'): ('CV runtime RUN- ids, not ledger tasks',
                          {'task run', 'task list', 'task status', 'task cancel', 'task outputs'}),
    ('task', 'preview'): ('local demo of a delivered RUN- output (CV runtime), not a ledger task', {'task preview'}),
    ('skills', 'skills'): ('project skill catalogue evidence; nothing is promoted to routing or injected into a task',
                           {'skills list', 'skills scan', 'skills review', 'skills approve', 'skills reject'}),
    ('learning', 'learning'): ('project lessons and budget advice; evidence only, never injected into a task',
                               {'learning outcomes', 'learning lessons', 'learning propose', 'learning budget'}),
    ('notifications', 'notifications'): ('host notification transport and receipts; the final desktop notice is the covered desktop group',
                                         {'notifications ' + n for n in ('pull', 'ack', 'deliver', 'feed', 'watch', 'begin-delivery',
                                                                          'confirm-delivery', 'delivery-missing', 'redeliver')}),
    ('monitor', 'monitor'): ('read-only view (it may open a terminal window; no task state)', {'monitor'}),
    ('provider', 'provider_cli'): ('global provider configuration and preferences, no task',
                                   {'provider ' + n for n in ('doctor', 'choose', 'quota', 'prefer', 'preference')}),
    ('decision', 'jev'): ('external evaluator credentials and connectivity, no task', {'decision configure', 'decision doctor'}),
}
# These record inside their own flow (before a continuation or launch can fail); exercised one by one below.
SELF_RECORDED = {delivery_cli: set(delivery_cli.RECORDED), evaluation: set(evaluation.RECORDED),
                 ledger_cli: set(ledger_cli.SELF_RECORDED)}
IDS = ('task', 'id', 'conversation', 'solution', 'consultation', 'from_task')


def leaves(parser, path=()):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from leaves(sub, path + (name,))
            return
    yield path, parser


def top_groups(parser):
    return next((set(a.choices) for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def commands(parser):
    """Leaf commands of a parser; one without groups is named by its prog (cli strips the group for it)."""
    prefix = () if top_groups(parser) else tuple(parser.prog.split()[1:])
    found = set()
    for path, leaf in leaves(parser):
        choices = next((a.choices for a in leaf._actions if a.dest == 'command' and not a.option_strings and a.choices), None)
        found |= {' '.join(prefix + path + (c,)) for c in choices} if choices else {' '.join(prefix + path)}
    return found


class Reached(BaseException):
    pass


def reached(argv):
    """The module (and parser) cli.main hands argv to; parse_args is intercepted, so no command ever runs."""
    def grab(parser, *args, **kwargs):
        raise Reached(sys._getframe(1).f_globals['__name__'].removeprefix('onecrew.'), parser)
    with patch.object(argparse.ArgumentParser, 'parse_args', grab), contextlib.redirect_stdout(io.StringIO()):
        try: cli.main(['--project', '.', *argv])
        except Reached as hit: return hit.args
    return None


def dispatched():
    """Group names cli.main compares args[index] against, and every other word it compares (the task commands)."""
    groups, words = set(), set()
    for node in ast.walk(ast.parse(inspect.getsource(cli.main))):
        if isinstance(node, ast.Compare):
            values = {k.value for c in node.comparators for k in (c.elts if isinstance(c, (ast.Tuple, ast.List, ast.Set)) else [c])
                      if isinstance(k, ast.Constant) and isinstance(k.value, str) and not k.value.startswith('-')}
            (groups if ast.unparse(node.left) == 'args[index]' else words).update(values)
    return groups, words


UNMATCHED = 'zz-unclassified-group'


def routes(groups, words):
    """group -> {module: parser} for every dispatched group and an unmatched one, probed with each dispatch word."""
    table = {}
    for group in sorted(groups | {UNMATCHED}):
        for tail in [()] + [t for w in sorted(words | {'zz'}) for t in ((w,), (w, 'TASK-' + '0' * 32))]:
            hit = reached([group, *tail])
            if hit is None: continue
            module, parser = hit
            names = top_groups(parser)
            for name in ([group] if names is None or group in names else names):  # the fallback serves its own groups
                table.setdefault(name, {})[module] = parser
    return table


def unclassified(groups, table):
    covered = {m.__name__.removeprefix('onecrew.'): m for m in COVERED}
    problems = [f'{g}: dispatched by cli.main but reaches no argparse parser' for g in sorted(groups - set(table))]
    for group, modules in sorted(table.items()):
        for module, parser in sorted(modules.items()):
            if module in covered:
                if group not in (top_groups(covered[module].parser()) or ()):
                    problems.append(f'{group} -> {module}: not a group of the covered parser')
            elif (group, module) not in EXEMPT_GROUPS:
                problems.append(f'{group} -> {module}: neither a COVERED module nor in EXEMPT_GROUPS')
            elif commands(parser) != EXEMPT_GROUPS[group, module][1]:
                problems.append(f'{group} -> {module}: commands changed {sorted(commands(parser) ^ EXEMPT_GROUPS[group, module][1])}')
    return problems


def argv_for(path, parser, task, file):
    args = list(path)
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction) or (action.option_strings and not action.required):
            continue
        value = (action.choices[0] if action.choices else '1' if action.type is int else str(file) if action.type is not None
                 else task if action.dest in IDS else 'x')
        args += [action.option_strings[0], value] if action.option_strings else [value]
    return args


class Coverage(unittest.TestCase):
    def setUp(self):
        self.f = LedgerFixture(self); self.task = self.f.task()
        self.file = self.f.base/'input.json'; self.file.write_text('{}', encoding='utf-8')

    def run_cli(self, module, args, actor='claude'):
        out = io.StringIO()
        with patch.dict(os.environ, {'ONECREW_ACTOR': actor} if actor else {}), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            return module.main(['--project', str(self.f.project), '--state-root', str(self.f.state_root), *args]), out.getvalue()

    def recorded(self, command, task=None):
        rows = [e['payload'] for e in self.f.events(task or self.task, 'control.intervention')] + iv.project_records(self.f.ledger)
        return [r for r in rows if r['command'] == command]


class CoverageTests(Coverage):
    def test_every_mutating_cli_records(self):
        seen = 0
        for module in COVERED:
            read_only, recorded = module.READ_ONLY, module.RECORDED
            for path, parser in leaves(module.parser()):
                with self.subTest(module=module.__name__, leaf=path):
                    self.assertTrue((path in read_only) != (path in recorded),
                                    f'{module.__name__} {" ".join(path)}: neither recorded nor on the read-only allowlist (or both)')
                    if path not in recorded or path in SELF_RECORDED.get(module, ()):
                        continue
                    seen += 1
                    task = self.f.task('leaf-' + str(seen))  # keyed records (a replayed submit) are per task
                    stub = {'id': task, 'task_id': task, 'task': task, 'revision': 'r', 'affected_tasks': [task], 'status': 'stub'}
                    with patch.object(module, 'execute', return_value=stub):
                        code, _ = self.run_cli(module, argv_for(path, parser, task, self.file))
                    self.assertEqual(code, 0)
                    rows = self.recorded(recorded[path], task)
                    self.assertTrue(rows, f'{" ".join(path)} left no intervention record')
                    self.assertEqual({r['actor'] for r in rows}, {'claude'})
        self.assertGreater(seen, 40)
        for module, leaves_ in SELF_RECORDED.items():
            self.assertTrue(leaves_ <= set(module.RECORDED))

    def test_read_only_commands_record_nothing(self):
        for args in (('task', 'status', self.task), ('task', 'events', self.task), ('request', 'list')):
            self.assertEqual(self.run_cli(ledger_cli, args + ('--json',))[0], 0)
        self.assertEqual(self.run_cli(owned_cli, ('job', 'status', self.task))[0], 0)
        self.assertEqual(self.run_cli(control_cli, ('core', 'status', self.task))[0], 0)
        self.assertEqual(self.f.events(self.task, 'control.intervention'), [])
        self.assertEqual(iv.project_records(self.f.ledger), [])

    def test_unset_actor_is_unknown_and_failures_record_nothing(self):
        question = self.f.base/'question.json'
        question.write_text(json.dumps({'schema_version': 1, 'question': 'Q?', 'reason': 'r', 'impact': 'i',
                                        'options': [{'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}], 'recommendation': 'a',
                                        'action': {'type': 'noop', 'parameters': {}}}), encoding='utf-8')
        args = ('request', 'create', '--task', self.task, '--request-id', 'q', '--file', str(question), '--json')
        self.assertEqual(self.run_cli(ledger_cli, args, actor=None)[0], 0)
        self.assertEqual(self.run_cli(ledger_cli, args, actor=None)[0], 0)  # a replayed create is one intervention
        self.assertEqual([(r['command'], r['actor']) for r in self.recorded('request.create')], [('request.create', 'unknown')])
        self.assertEqual(self.run_cli(ledger_cli, ('request', 'create', '--task', 'TASK-' + '0' * 32, '--request-id', 'q2',
                                                   '--file', str(question), '--json'))[0], 2)
        self.assertEqual(len(self.recorded('request.create')), 1)


class DispatchTests(unittest.TestCase):
    def test_every_cli_group_is_covered_or_exempt_with_a_reason(self):
        groups, words = dispatched()
        self.assertGreaterEqual(groups, {'eval', 'delegation', 'desktop', 'delivery', 'skills', 'learning', 'notifications', 'monitor',
                                         'android', 'conversation', 'solution', 'consultation', 'job', 'entry', 'provider', 'work',
                                         'core', 'request', 'decision', 'task'})
        table = routes(groups, words)
        self.assertNotIn(UNMATCHED, table)
        self.assertEqual(set(table['spec']), {'specs'})  # an unmatched group falls back to the spec CLI
        self.assertEqual(set(table['task']), {'ledger_cli', 'runtime', 'preview'})
        self.assertEqual(unclassified(groups, table), [])
        self.assertTrue(all(reason.strip() for reason, _ in EXEMPT_GROUPS.values()))
        used = {(g, m) for g, modules in table.items() for m in modules}
        self.assertEqual(set(EXEMPT_GROUPS) - used, set())  # no stale exemption

    def test_a_new_group_or_exempt_command_is_red(self):
        groups, words = dispatched()
        table = routes(groups, words)
        self.assertEqual(unclassified(groups | {'newgroup'}, table), ['newgroup: dispatched by cli.main but reaches no argparse parser'])
        skills = table['skills']['skills']
        self.assertEqual(unclassified(groups, dict(table, newgroup={'skills': skills})),
                         ['newgroup -> skills: neither a COVERED module nor in EXEMPT_GROUPS'])
        group = next(a for a in skills._actions if isinstance(a, argparse._SubParsersAction)).choices['skills']
        next(a for a in group._actions if isinstance(a, argparse._SubParsersAction)).add_parser('promote')
        self.assertEqual(unclassified(groups, table), ["skills -> skills: commands changed ['skills promote']"])


class TaskScopedTests(Coverage):
    def test_android_build_and_cancel_record_on_the_task(self):
        def run(*args): return self.run_cli(android_build, ('android', *args, '--from-task', self.task, '--key', 'apk'))[0]
        build = ('build', '--flutter-root', str(self.file), '--android-sdk', str(self.file), '--allow-trusted-native-build')
        with patch('onecrew.android_jobs.dispatch', return_value={'status': 'queued'}), \
             patch('onecrew.android_jobs.cancel', return_value={'status': 'cancelling'}), \
             patch('onecrew.android_jobs.status', return_value={'status': 'queued'}):
            self.assertEqual([run(*build), run(*build), run('status'), run('cancel')], [0, 0, 0, 0])
        rows = [(r['command'], r['actor'], r.get('key')) for r in (e['payload'] for e in self.f.events(self.task, 'control.intervention'))]
        self.assertEqual(rows, [('android.build', 'claude', 'android.build:apk'), ('android.cancel', 'claude', None)])
        self.assertEqual([sc.role({'actor': a, 'command': c}) for c, a, _ in rows], ['entry', 'entry'])
        with patch('onecrew.android_jobs.dispatch', return_value={'status': 'blocked'}):
            self.assertEqual(self.run_cli(android_build, ('android', *build, '--from-task', self.task, '--key', 'apk2'))[0], 2)
        with patch('onecrew.android_jobs.dispatch', side_effect=ValueError('refused')):
            self.assertEqual(self.run_cli(android_build, ('android', *build, '--from-task', self.task, '--key', 'apk3'))[0], 2)
        keys = [e['payload'].get('key') for e in self.f.events(self.task, 'control.intervention')]
        self.assertEqual(keys[2:], ['android.build:apk2'])  # a started build that then blocks is help; a refused one records nothing

    def test_entry_note_records_once_on_the_task_and_connect_records_nothing(self):
        code, out = self.run_cli(entry_cli, ('entry', 'connect', self.task, '--json'))
        self.assertEqual(code, 0)
        self.assertEqual(self.f.events(self.task, 'control.intervention'), [])
        note = self.f.base/'note.txt'; note.write_text('Use the staging HIS URL.', encoding='utf-8')
        args = ('entry', 'note', self.task, '--revision', json.loads(out)['revision'], '--request-id', 'n' * 128,
                '--kind', 'proposal', '--file', str(note), '--source', 'claude', '--reference', 'chat')
        self.assertEqual([self.run_cli(entry_cli, args)[0] for _ in range(2)], [0, 0])  # a replayed note is one intervention
        rows = [e['payload'] for e in self.f.events(self.task, 'control.intervention')]
        self.assertEqual([(r['command'], r['actor']) for r in rows], [('entry.note', 'claude')])
        self.assertTrue(rows[0]['key'].startswith('entry.note:sha256:'))  # an over-long request id still fits the key
        self.assertEqual(sc.role(rows[0]), 'entry')


class McpCoverageTests(Coverage):
    def test_every_mutating_mcp_tool_records(self):
        from onecrew import conversation_mcp, mcp_entry
        for name in mcp_entry.TOOLS:
            self.assertTrue((name in mcp_entry.READ_ONLY) != (name in mcp_entry.COMMANDS), name)
        for name in conversation_mcp.TOOLS:
            mutating = name in conversation_mcp.LEAVES or name == 'solution_decide'
            self.assertTrue((name in conversation_mcp.READ) != mutating, name)
        server = mcp_entry.Server(self.f.ledger, True, 'claude-entry', allow_discussion=True)
        conversation = server.call('conversation_create', {'title': 'Contract', 'key': 'c1'})['id']
        server.call('conversation_create', {'title': 'Contract', 'key': 'c1'})  # replay
        server.call('conversation_read', {'conversation': conversation})
        rows = [(r['command'], r['actor'], r['channel'], r['scope'], r['scope_id']) for r in iv.project_records(self.f.ledger)]
        self.assertEqual(rows, [('conversation.create', 'claude', 'mcp', 'conversation', conversation)])


class SelfRecordedTests(Coverage):
    def test_delivery_commands_record_once_per_handoff(self):
        from onecrew.solution_delivery import Delivery
        with patch('onecrew.solution_delivery.submit', return_value={'id': self.task}), \
             patch.object(Delivery, 'enable', return_value={'phase': 'running'}), patch.object(Delivery, 'resume'), \
             patch('onecrew.runner.start', return_value={'status': 'starting'}):
            submit = ('delivery', 'submit', '--solution', 'SOL-x', '--revision', 'r', '--goal', 'Goal', '--key', 'k', '--start')
            for _ in range(2):  # a retried submit is the same handoff
                self.assertEqual(self.run_cli(delivery_cli, submit)[0], 0)
            for command in ('start', 'resume', 'cancel'):
                self.assertEqual(self.run_cli(delivery_cli, ('delivery', command, self.task, '--reason', 'r'))[0], 0)
        rows = [(r['command'], r['actor']) for r in (e['payload'] for e in self.f.events(self.task, 'control.intervention'))]
        self.assertEqual(rows, [('delivery.submit', 'claude'), ('delivery.start', 'claude'), ('delivery.resume', 'claude'),
                                ('delivery.cancel', 'claude')])

    def test_eval_assistance_and_trials_record(self):
        args = ('eval', 'assistance', '--task', self.task, '--key', 'fix-1', '--actor', 'claude', '--category', 'runtime', '--reason', 'Fixed runner')
        for _ in range(2):
            self.assertEqual(self.run_cli(evaluation, args)[0], 0)
        self.assertEqual(len(self.recorded('eval.assistance')), 1)
        self.assertEqual(sc.role({'actor': 'claude', 'command': 'eval.assistance'}), 'evidence')  # the note itself is not help
        fake = {'tree': 'a' * 64, 'git': 'b' * 40, 'dirty': False}
        with patch('onecrew.interventions.revision', return_value=fake):
            code, out = self.run_cli(evaluation, ('eval', 'trial', 'open', '--key', 'trial-root'))
            self.assertEqual(code, 0)
            trial = json.loads(out)['id']
            self.assertEqual(self.run_cli(evaluation, ('eval', 'trial', 'close', trial))[0], 0)
            self.assertEqual(self.run_cli(evaluation, ('eval', 'trial', 'show', trial))[0], 0)
        rows = [(r['command'], r['scope'], r['scope_id']) for r in iv.project_records(self.f.ledger, 'trial')]
        self.assertEqual(rows, [('eval.trial.open', 'trial', trial), ('eval.trial.close', 'trial', trial)])

    def test_reply_records_itself_with_its_receipt_key(self):
        from tests.test_interventions import QUESTION
        req = self.f.ledger.create_request(self.task, 'q', QUESTION)
        code, out = self.run_cli(ledger_cli, ('request', 'reply', req['id'], '--revision', req['revision'], '--choice', 'a', '--json'))
        self.assertEqual(code, 0)
        self.assertEqual([r['key'] for r in self.recorded('request.reply')], [json.loads(out)['id']])

    def test_desktop_show_by_the_entry_is_recorded(self):
        with patch.object(desktop_notifications, 'publish', return_value={'enabled': True, 'launched': []}):
            self.assertEqual(self.run_cli(desktop_notifications, ('desktop', 'show', '--task', self.task))[0], 0)
        self.assertEqual([r['actor'] for r in self.recorded('desktop.show')], ['claude'])
        self.assertEqual(sc.role({'actor': 'claude', 'command': 'desktop.show'}), 'entry')


class HandoffTests(unittest.TestCase):
    def test_repeat_submit_is_entry(self):
        def i(command, actor='claude'): return {'actor': actor, 'channel': 'cli', 'command': command}
        first = [i('delivery.submit'), i('delivery.start')]
        self.assertFalse(sc.repeated_handoff(first))
        self.assertEqual([sc.role(x) for x in first], ['handoff', 'handoff'])
        for extra in (i('delivery.start'), i('job.start'), i('job.submit'), i('work.start', 'user')):
            self.assertTrue(sc.repeated_handoff(first + [extra]), extra)
        self.assertFalse(sc.repeated_handoff(first + [i('delivery.start', 'onecrew')]))  # OneCrew's own start is runtime
        from tests.test_autonomy_round2 import done
        self.assertEqual(sc.assistance_level(done(interventions=first)), ('autonomous', []))
        self.assertEqual(sc.assistance_level(done(interventions=first + [i('delivery.start')])), ('assisted', ['repeat_handoff']))


if __name__ == '__main__':
    unittest.main()
