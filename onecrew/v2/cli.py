"""The `onecrew` command of the installed package: the v2 router (plan | verdict | hook).

The same routing the full checkout uses (onecrew/cli.py hands these three groups to `route` here), so there is one definition of it. The v1
groups (job, work, delivery, ...) are not in the wheel; they run from a checkout through onecrew_cli.py (docs/v2-core.vi.md).
"""
import sys

from .messages import t

GROUPS = ('plan', 'verdict', 'hook', 'init', 'doctor', 'owner', 'compat', 'findings', 'executor', 'outcome', 'continue', 'context', 'question', 'estimate', 'notifications', 'desktop', 'incident', 'lesson', 'issue', 'unknown', 'engine')
OLD_HELP_LINES = ('  plan       propose / show / approve / accept / amend / enforce (v2 AI work contract; owner-only approval and acceptance)\n'
                  '  verdict    record / run (v2 milestone verdicts with receipts)\n'
                  '  hook       check / prompt / stop / session / sync / export / mode / install --print (v2 Claude Code hooks)\n'
                  '  findings   list / review / resolve / reject (namespaced plan finding register)\n'
                  '  outcome    record / show / missing / reconcile / intervene (recorded results)\n'
                  '  continue   read-only resume pack; grants no authority\n'
                  '  context    add / observe / retrieve (project and shared knowledge)\n'
                  '  incident   list / observe / finalize (evidence of errors and repairs)\n'
                  '  lesson     list / record / general / withdraw (project lessons and general candidates)\n'
                  '  issue      localize / map (pinned file and method hypotheses)\n'
                  '  unknown    list / open / resolve (scoped execution questions)\n'
                  '  engine     revise / state / ready / step / verify / handoff (common workflow)\n'
                  '  engine     prepare-tests / repair / diagnose / replan (bounded in-grant work)\n'
                  '  question   list / show / answer (owner-only answers)\n'
                  '  estimate   show / update / additional (sourced ranges)\n'
                  '  notifications pull / ack (plan notices; delivery never answers or accepts)\n'
                  '  desktop    enable / disable / status / show / retry (shared local outbox)\n'
                  '  executor   list / observe / summary (declared capabilities and observed runs)\n')


def help_lines():
    """The v2 lines of the top-level help: the three older ones as they were, then init / doctor / owner in the language of ONECREW_LANG."""
    return OLD_HELP_LINES + ''.join(f'  {name:<10} {t("cli.line_" + name)}\n' for name in ('init', 'doctor', 'owner'))


HELP_LINES = help_lines()       # the full v1 router (onecrew/cli.py) imports this


def route(args, index):
    """Run the v2 group named by args[index]; `args` still holds the global options (--project, --state-root) before it."""
    from .ownership import refuse_argv  # C3: the owner's verbs are refused inside an AI tool session
    refused = refuse_argv(args[index:])
    if refused: return refused
    if args[index:index + 2] == ['eval', 'plan-metrics']:
        from .metrics import main as metrics_main
        return metrics_main(args)
    if args[index] == 'hook':
        from .hook_cli import main as hook_main
        return hook_main(args)
    if args[index] in ('init', 'doctor'):
        from .install import main as install_main
        return install_main(args)
    if args[index] == 'owner':
        from .owner_cli import main as owner_main
        return owner_main(args)
    if args[index] == 'compat':
        from .compat_cli import main as compat_main
        return compat_main(args)
    if args[index] == 'findings':
        from .findings import main as findings_main
        return findings_main(args[:index] + args[index + 1:])
    if args[index] == 'executor':
        from .executors import main as executor_main
        return executor_main(args)
    if args[index] in ('outcome', 'continue', 'context'):
        from .evidence_cli import main as evidence_main
        return evidence_main(args)
    if args[index] == 'question':
        from .questions import main as question_main
        return question_main(args)
    if args[index] == 'estimate':
        from .estimates import main as estimate_main
        return estimate_main(args)
    if args[index] in ('incident', 'lesson', 'issue'):
        from .learning_cli import main as learning_main
        return learning_main(args)
    if args[index] == 'unknown':
        from .unknown_cli import main as unknown_main
        return unknown_main(args)
    if args[index] == 'engine':
        from .engine_cli import main as engine_main
        return engine_main(args)
    if args[index] in ('notifications', 'desktop'):
        from .notification_cli import main as notification_main
        return notification_main(args)
    from .plan_cli import main as v2_main
    return v2_main(args)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    index = 0
    while index < len(args):
        if args[index] in ('--project', '--state-root'):
            index += 2
        elif args[index].startswith(('--project=', '--state-root=')):
            index += 1
        else:
            break
    if len(args) <= index or args[index] in ('--help', '-h'):
        print('OneCrew: --project <path> <group> <command> [options]\n' + help_lines() +
              'Use <group> <command> --help for options. Durable commands accept --state-root before group.')
        return 0
    if args[index] in GROUPS or args[index:index + 2] == ['eval', 'plan-metrics']: return route(args, index)
    print(f'onecrew: unknown group "{args[index]}". This install has: {", ".join(GROUPS)}. The other groups run from a checkout (onecrew_cli.py).',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
