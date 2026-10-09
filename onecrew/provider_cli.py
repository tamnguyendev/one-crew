import argparse
import json
from pathlib import Path

from .providers import doctor
from .ledger import Ledger, read_json, canonical
from .routing import choose


def main(argv=None):
    parser = argparse.ArgumentParser(prog='onecrew provider')
    parser.add_argument('--project',type=Path,default=Path.cwd())
    parser.add_argument('--state-root',type=Path)
    parser.add_argument('command', choices=('doctor', 'choose', 'quota', 'prefer', 'preference'))
    parser.add_argument('provider', nargs='?', choices=('codex', 'claude', 'kiro'))
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--file', type=Path)
    parser.add_argument('--model')
    parser.add_argument('--reset-hint',help='User-reported ISO timestamp only; never establishes quota.')
    parser.add_argument('--jev',action='store_true',help='One optional external evaluator call; shadow only, no dispatch.')
    parser.add_argument('--brief',help='Sanitized task description to send to Jev; no source or transcripts.')
    args = parser.parse_args(argv)
    try:
        from .model_preferences import read,save
        ledger=Ledger(args.project,args.state_root)
        if args.command=='prefer':
            if not args.provider or not args.model: raise ValueError('prefer requires provider and --model.')
            result=save(ledger,args.provider,args.model,args.reset_hint)
        elif args.command=='preference': result=dict(read(ledger),quota_verified=False)
        elif args.command == 'choose':
            if not args.file:
                raise ValueError('choose requires --file with workload and candidate quota evidence.')
            payload = read_json(args.file)
            pref=read(ledger)
            preferred=pref['provider'] if pref['source']!='built-in default' else None
            result = choose(payload['workload'], payload['candidates'],preferred_provider=preferred)
            result['preference']=dict(pref,quota_verified=False)
            if args.jev:
                if not args.brief: raise ValueError('--jev requires an explicit sanitized --brief.')
                from .model_advisor import advise
                from .jev import JevError
                try: result['jev']=advise(args.brief,payload['workload'],payload['candidates'],result,preferred)
                except JevError:
                    result['jev']={'status':'unavailable','automatic_application':False,'dispatch_enabled':False,
                                   'reason':'Credential/provider/schema failure; no retry, deterministic recommendation retained.'}
            from .snapshots import durable_write
            import uuid
            receipt=ledger.state_root/'routing-decisions'/('decision-'+uuid.uuid4().hex+'.json')
            # Do not persist the free-text brief or quota payload in the decision receipt.
            result['receipt']=str(receipt);durable_write(receipt,canonical(result).encode())
        elif args.command == 'quota':
            if args.provider != 'codex':
                raise ValueError('Only Codex has a verified quota feed; Claude/Kiro quota is unknown until supplied by an operator/verified connector.')
            from .quota import codex
            result = codex()
        else:
            result = {'providers': [doctor(p) for p in ([args.provider] if args.provider else ['codex', 'claude', 'kiro'])]}
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({'error': str(error)}))
        return 2
    return 0
