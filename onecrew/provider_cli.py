import argparse
import json

from .providers import doctor


def main(argv=None):
    parser = argparse.ArgumentParser(prog='onecrew provider')
    parser.add_argument('command', choices=('doctor',))
    parser.add_argument('provider', nargs='?', choices=('codex', 'claude', 'kiro'))
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps({'providers': [doctor(p) for p in ([args.provider] if args.provider else ['codex', 'claude', 'kiro'])]}, indent=2))
    return 0
