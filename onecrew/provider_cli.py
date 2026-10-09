import argparse
import json
from pathlib import Path

from .providers import doctor
from .ledger import read_json
from .routing import choose


def main(argv=None):
    parser = argparse.ArgumentParser(prog='onecrew provider')
    parser.add_argument('command', choices=('doctor', 'choose', 'quota'))
    parser.add_argument('provider', nargs='?', choices=('codex', 'claude', 'kiro'))
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--file', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'choose':
            if not args.file:
                raise ValueError('choose requires --file with workload and candidate quota evidence.')
            payload = read_json(args.file)
            result = choose(payload['workload'], payload['candidates'])
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
