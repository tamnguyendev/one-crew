"""Read and resolve scoped runtime unknowns without revising the root grant."""
import argparse
import json
from pathlib import Path

from ..ledger import LedgerError
from .evidence_cli import _ledger
from . import runtime_unknowns


def main(argv=None):
    parser=argparse.ArgumentParser(prog='onecrew unknown', allow_abbrev=False)
    parser.add_argument('--project',type=Path,default=Path.cwd()); parser.add_argument('--state-root',type=Path)
    groups=parser.add_subparsers(dest='group',required=True)
    sub=groups.add_parser('unknown').add_subparsers(dest='command',required=True)
    p=sub.add_parser('list'); p.add_argument('--plan',required=True)
    p=sub.add_parser('open'); p.add_argument('--plan',required=True); p.add_argument('key'); p.add_argument('--file',type=Path,required=True)
    p=sub.add_parser('resolve'); p.add_argument('--plan',required=True); p.add_argument('key')
    p.add_argument('--by',choices=('doc','poc','owner'),required=True); p.add_argument('--evidence',required=True); p.add_argument('--answer',required=True)
    args=parser.parse_args(argv)
    try:
        ledger=_ledger(args,args.command=='list')
        if args.command=='list': result={'unknowns':runtime_unknowns.read(ledger,args.plan),'blocked_nodes':runtime_unknowns.blockers(ledger,args.plan)}
        elif args.command=='resolve': result=runtime_unknowns.resolve(ledger,args.plan,args.key,by=args.by,evidence=args.evidence,answer=args.answer)
        else:
            if args.file.stat().st_size>65536: raise LedgerError('Unknown declaration exceeds 64 KiB.')
            value=json.loads(args.file.read_text(encoding='utf-8'))
            required={'question','affected','required_by','resolver','evidence'}
            if not isinstance(value,dict) or not required<=set(value) or set(value)-required-{'blocks_estimate','survey_node'}:
                raise LedgerError('Unknown declaration requires question, affected, required_by, resolver and evidence.')
            result=runtime_unknowns.open_unknown(ledger,args.plan,args.key,**value)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except (LedgerError,OSError,ValueError) as error:
        print(json.dumps({'error':str(error),'type':type(error).__name__},ensure_ascii=False)); return 2
