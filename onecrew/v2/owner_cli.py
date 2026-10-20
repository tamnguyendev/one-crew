"""`onecrew owner approve|accept|enforce|record` (G2): the owner's verbs under one name, in place of the four scripts/owner/*.ps1.

Each one is the older command with `--by owner` fixed, run through the same code, so the output and the checks are the same:
  owner approve <plan> --reference R [--choose X] [--tick I]... [--revision N]   = plan approve --by owner
  owner accept <plan> --artifact-sha S --reference R                            = plan accept --by owner
  owner enforce <plan> [--mode log|enforce] [--reference R]                     = hook mode <mode> --by owner --plan <plan>
  owner record --plan P --milestone M --result pass|fail|inconclusive --artifact-sha S --receipt-file F --reference R
                                                                                = verdict record --by owner
They are refused inside an AI tool session: ownership.OWNER_VERBS names these four, and the code they call refuses too (C3, C11).
"""
import argparse
from pathlib import Path

from .messages import t


def _parser():
    parser = argparse.ArgumentParser(prog='onecrew owner', description=t('owner.description'))
    verbs = parser.add_subparsers(dest='verb', required=True)
    p = verbs.add_parser('approve', help=t('owner.approve'))
    p.add_argument('plan'); p.add_argument('--reference', required=True, help=t('owner.reference')); p.add_argument('--choose', metavar=t('owner.metavar_option'))
    p.add_argument('--tick', action='append', default=[], metavar=t('owner.metavar_item')); p.add_argument('--revision', type=int)
    p = verbs.add_parser('accept', help=t('owner.accept'))
    p.add_argument('plan'); p.add_argument('--artifact-sha', required=True); p.add_argument('--reference', required=True, help=t('owner.reference'))
    p = verbs.add_parser('enforce', help=t('owner.enforce'))
    p.add_argument('plan'); p.add_argument('--mode', choices=['enforce', 'log'], default='enforce'); p.add_argument('--reference', default=t('owner.enforce_reference'))
    p = verbs.add_parser('record', help=t('owner.record'))
    p.add_argument('--plan', required=True); p.add_argument('--milestone', required=True); p.add_argument('--result', required=True, choices=['pass', 'fail', 'inconclusive'])
    p.add_argument('--artifact-sha', required=True); p.add_argument('--receipt-file', required=True, type=Path); p.add_argument('--reference', required=True, help=t('owner.reference'))
    return parser


def translate(args):
    """(module, argv) of the older command a parsed `owner` verb stands for (--by owner fixed)."""
    if args.verb == 'approve':
        argv = ['plan', 'approve', args.plan, '--by', 'owner', '--reference', args.reference]
        argv += ['--revision', str(args.revision)] if args.revision is not None else []
        argv += [x for tick in args.tick for x in ('--tick', tick)]
        argv += ['--choose', args.choose] if args.choose else []
        return 'plan_cli', argv
    if args.verb == 'accept':
        return 'plan_cli', ['plan', 'accept', args.plan, '--by', 'owner', '--reference', args.reference, '--artifact-sha', args.artifact_sha]
    if args.verb == 'enforce':
        return 'hook_cli', ['hook', 'mode', args.mode, '--by', 'owner', '--plan', args.plan, '--reference', args.reference]
    return 'plan_cli', ['verdict', 'record', '--plan', args.plan, '--milestone', args.milestone, '--result', args.result, '--by', 'owner',
                        '--artifact-sha', args.artifact_sha, '--receipt-file', str(args.receipt_file), '--reference', args.reference]


def main(args):
    """`args` is the whole command line, global options (--project, --state-root) first, then `owner <verb> ...`."""
    index = 0
    while index < len(args) and args[index] != 'owner': index += 1
    glob, rest = list(args[:index]), list(args[index + 1:])
    parsed = _parser().parse_args(rest)
    module, argv = translate(parsed)
    if module == 'hook_cli':
        from .hook_cli import main as run
    else:
        from .plan_cli import main as run
    return run(glob + argv)
