"""The `onecrew` command of the installed package: the v2 router (plan | verdict | hook).

The same routing the full checkout uses (onecrew/cli.py hands these three groups to `route` here), so there is one definition of it. The v1
groups (job, work, delivery, ...) are not in the wheel; they run from a checkout through onecrew_cli.py (docs/v2-core.vi.md).
"""
import sys

GROUPS = ('plan', 'verdict', 'hook', 'init', 'doctor', 'owner')
HELP_LINES = ('  plan       propose / show / approve / accept / amend / enforce (v2 AI work contract; owner-only approval and acceptance)\n'
              '  verdict    record / run (v2 milestone verdicts with receipts)\n'
              '  hook       check / prompt / stop / session / sync / export / mode / install --print (v2 Claude Code hooks)\n'
              '  init       set a repo up: ledger, owner rules, Claude Code hooks (from an installed copy)\n'
              '  doctor     check this machine and repo: one PASS/WARN/FAIL line per check\n'
              '  owner      approve / accept / enforce / record (the owner\'s verbs; refused inside an AI session)\n')


def route(args, index):
    """Run the v2 group named by args[index]; `args` still holds the global options (--project, --state-root) before it."""
    from .ownership import refuse_argv  # C3: the owner's verbs are refused inside an AI tool session
    refused = refuse_argv(args[index:])
    if refused: return refused
    if args[index] == 'hook':
        from .hook_cli import main as hook_main
        return hook_main(args)
    if args[index] in ('init', 'doctor'):
        from .install import main as install_main
        return install_main(args)
    if args[index] == 'owner':
        from .owner_cli import main as owner_main
        return owner_main(args)
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
        print('OneCrew: --project <path> <group> <command> [options]\n' + HELP_LINES +
              'Use <group> <command> --help for options. Durable commands accept --state-root before group.')
        return 0
    if args[index] in GROUPS: return route(args, index)
    print(f'onecrew: unknown group "{args[index]}". This install has: {", ".join(GROUPS)}. The other groups run from a checkout (onecrew_cli.py).',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
