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
              '  request    create / list / show / revise / reply / defer\n'
              '  notifications pull / ack / deliver / feed / watch (bounded host watch; never approves)\n'
              '  desktop    enable / disable / status / show / retry (event-driven Windows results)\n'
              '  entry      connect / note (portable local context, no dispatch)\n'
              '  conversation create / list / read / attach / append / summary / question / reply\n'
              '  solution   propose / review / diff / select / approve / request-changes / bind\n'
              '  consultation route / submit / start / show / cancel / reconcile / feedback\n'
              '  learning   outcomes / lessons / propose (evidence only; no automatic routing promotion)\n'
              '  eval       cases / replay / compare / observe / assistance (evidence, no auto-promotion)\n'
              '  skills     list / scan / review / approve / reject (recurring-task evidence)\n'
              '  job        submit / start / run / status / outputs / cancel / resume (runtime-owned goals)\n'
              '  qc         submit / status (judge a candidate branch built outside OneCrew: scope, fixed gate, independent review)\n'
              '  plan       propose / show / approve / accept / amend / enforce (v2 AI work contract; owner-only approval and acceptance)\n'
              '  verdict    record / run (v2 milestone verdicts with receipts)\n'
              '  hook       check / prompt / stop / session / sync / export / mode / install --print (v2 Claude Code hooks)\n'
              '  host       install / register / start / stop / status / uninstall / run (runs jobs outside chat sessions)\n'
              '  delivery   submit / start / resume / status / cancel (solution-level execution)\n'
              '  core       migrate / status / cancel / reconcile\n'
              '  work       enable / plan / run / start / runner / status / outputs / cancel / pause / resume / switch\n'
              '  work       group / vector / quota / extend / amend / triage / request-changes / recheck / reorder / review / export / branch / merge\n'
              '  provider   doctor / quota / prefer / preference / choose --file <policy.json> [--jev --brief ...]\n'
              '  decision   JEV credential and connectivity commands\n'
              '  android    build / status / cancel (background native debug APK; --foreground to wait)\n'
              '  monitor    grouped workers / --verbose / --terminal / --all-projects\n'
              'Use <group> <command> --help for options. Durable commands accept --state-root before group.')
        return 0
    if len(args)>index and args[index]=='host':
        from .host import main as host_main
        return host_main(args[index:])
    if len(args)>index and args[index]=='eval':
        from .evaluation import main as eval_main
        return eval_main(args)
    if len(args)>index and args[index]=='desktop':
        from .desktop_notifications import main as desktop_main
        return desktop_main(args)
    if len(args)>index and args[index]=='delivery':
        from .delivery_cli import main as delivery_main
        return delivery_main(args)
    if len(args)>index and args[index]=='skills':
        from .skills import main as skills_main
        return skills_main(args)
    if len(args)>index and args[index]=='learning':
        from .learning import main as learning_main
        return learning_main(args)
    if len(args)>index and args[index]=='notifications':
        from .notifications import main as notifications_main
        return notifications_main(args)
    if len(args)>index and args[index]=='monitor':
        from .monitor import main as monitor_main
        return monitor_main(args)
    if len(args)>index and args[index]=='android':
        from .android_build import main as android_main
        return android_main(args)
    if len(args)>index and args[index] in ('conversation','solution','consultation'):
        from .conversation_cli import main as conversation_main
        return conversation_main(args)
    if len(args)>index and args[index]=='job':
        from .owned_cli import main as job_main
        return job_main(args)
    if len(args)>index and args[index]=='qc':
        from .qc_cli import main as qc_main
        return qc_main(args)
    if len(args)>index and args[index]=='hook':  # v2 L2: Claude Code hooks for the active plan
        from .v2.hook_cli import main as hook_main
        return hook_main(args)
    if len(args)>index and args[index] in ('plan','verdict'):  # v2 (docs/v2-vs-v1.vi.md); no v1 verb is named plan or verdict
        from .v2.plan_cli import main as v2_main
        return v2_main(args)
    if len(args)>index and args[index]=='entry':
        from .entry_cli import main as entry_main
        return entry_main(args)
    if len(args)>index and args[index]=='provider':
        from .provider_cli import main as provider_main
        return provider_main(args[:index]+args[index+1:])
    if len(args)>index and args[index]=='work':
        from .workflow_cli import main as work_main
        return work_main(args)
    if len(args)>index and args[index]=='core':
        from .control_cli import main as core_main
        return core_main(args)
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
