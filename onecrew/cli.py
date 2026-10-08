"""Keep existing spec CLI backwards compatible; add autonomous task commands."""
import sys
from . import specs

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    index=0
    while index < len(args):
        if args[index] in ('--project', '--state-root'):
            index += 2
        elif args[index].startswith(('--project=', '--state-root=')):
            index += 1
        else:
            break
    if len(args) <= index or args[index] in ('--help', '-h'):
        print('OneCrew: --project <path> <group> <command> [options]\n'
              '  spec       list / review / diff / approve / request-changes / history\n'
              '  task       submit / queue / connect / events / status (durable TASK- IDs)\n'
              '  task       run / list / status / cancel / outputs / preview (CV RUN- IDs)\n'
              '  request    create / list / show / revise / reply\n'
              '  decision   JEV credential and connectivity commands\n'
              'Use <group> <command> --help for options. Durable commands accept --state-root before group.')
        return 0
    if len(args)>index and args[index]=='request':
        from .ledger_cli import main as ledger_main
        return ledger_main(args)
    if len(args)>index and args[index]=='decision':
        from .jev import main as decision_main
        return decision_main(args[index+1:])
    if len(args)>index and args[index]=='task':
        command = args[index+1] if len(args)>index+1 else ''
        if command in ('', '--help', '-h'):
            print('task submit / queue / connect / events / status: durable ledger, no worker dispatch.\n'
                  'task run / list / status / cancel / outputs / preview: existing CV runtime.\n'
                  'Use task <command> --help. Status accepts TASK- ledger IDs or RUN- runtime IDs.')
            return 0
        durable_status = command == 'status' and any(a.startswith('TASK-') for a in args[index+2:])
        if command in ('submit', 'connect', 'queue', 'events') or durable_status:
            from .ledger_cli import main as ledger_main
            return ledger_main(args)
        if len(args)>index+1 and args[index+1]=='preview':
            from .preview import main as preview_main
            return preview_main(args[:index]+args[index+2:])
        from .runtime import main as task_main
        return task_main(args)
    return specs.main(args)
