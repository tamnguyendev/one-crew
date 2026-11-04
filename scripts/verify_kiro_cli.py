"""Verify an installed Kiro CLI against the OneCrew Kiro adapter BEFORE supporting its version.

Checks, in order, and writes evidence JSON (no identity/token is recorded):
1. `kiro-cli --version` and `kiro-cli whoami` exit status (authentication only, identity withheld);
2. every flag the adapter passes is still documented by `kiro-cli chat --help`;
3. the exact no-tools agent configuration of the adapter passes `kiro-cli agent validate`;
4. `chat --list-models --format json` contains the requested model (no implicit default-model fallback);
5. ONE minimal live call with the adapter's own argv (providers.kiro_argv) parsed by the adapter's own stream parser
   (providers.kiro_stream): typed JSON back, terminal success, no truncation, no tool activity, metering recorded.

Usage: python scripts/verify_kiro_cli.py --model claude-haiku-4.5 --output docs/kiro-cli-<version>-evidence.json
The single live call is the verification itself, not a demonstration of model use."""
import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from onecrew.ledger import canonical  # noqa: E402
from onecrew.providers import KIRO_AGENT, KIRO_PROMPT_CAP, executable, kiro_argv, kiro_stream  # noqa: E402
from onecrew.subscription import environment  # noqa: E402

FLAGS = ('--agent', '--agent-engine', '--no-interactive', '--trust-tools', '--model', '--output-format', 'stream-json',
         '--list-models', '--format')


def run(argv, cwd=None, timeout=30):
    done = subprocess.run(argv, capture_output=True, timeout=timeout, env=environment(), cwd=cwd)
    return done.returncode, done.stdout.decode('utf-8', errors='replace'), done.stderr.decode('utf-8', errors='replace')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--no-live', action='store_true', help='Static checks only (no model call).')
    args = parser.parse_args()
    binary = executable('kiro')
    evidence = {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'executable': binary, 'checks': {}}
    if not binary: raise SystemExit('kiro-cli not installed')
    code, out, _ = run([binary, '--version']); evidence['version'] = out.strip(); evidence['checks']['version_exit'] = code
    code, _, _ = run([binary, 'whoami']); evidence['checks']['authenticated'] = code == 0
    code, out, err = run([binary, 'chat', '--help']); text = out + err
    evidence['checks']['flags_documented'] = {flag: flag in text for flag in FLAGS}
    evidence['checks']['agent_engine_v2'] = '--agent-engine' in text and 'v2' in text
    with tempfile.TemporaryDirectory() as temp:
        agent = Path(temp) / '.kiro/agents/onecrew-artifact.json'; agent.parent.mkdir(parents=True)
        agent.write_text(canonical(KIRO_AGENT), encoding='utf-8')
        code, out, err = run([binary, 'agent', 'validate', '--path', str(agent)])
        evidence['checks']['agent_validate'] = code == 0
        code, out, _ = run([binary, 'chat', '--list-models', '--format', 'json'])
        try: models = {m['model_id'] for m in json.loads(out)['models']}
        except (ValueError, KeyError, TypeError): models = set()
        evidence['checks']['model_listed'] = args.model in models
        static_ok = (evidence['checks']['authenticated'] and all(evidence['checks']['flags_documented'].values())
                     and evidence['checks']['agent_validate'] and evidence['checks']['model_listed'])
        evidence['static_ok'] = static_ok
        if static_ok and not args.no_live:
            schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}, 'echo': {'type': 'string'}},
                      'required': ['ok', 'echo'], 'additionalProperties': False}
            prompt = ('Protocol verification for an automation adapter. Return exactly {"ok": true, "echo": "onecrew-kiro-check"}.'
                      '\nREQUIRED JSON SCHEMA\n' + canonical(schema))
            assert len(prompt) <= KIRO_PROMPT_CAP
            code, out, err = run(kiro_argv(binary, args.model, prompt), cwd=temp, timeout=180)
            live = {'exit_code': code, 'stdout_events': len([l for l in out.splitlines() if l.strip()])}
            try:
                value, usages = kiro_stream(out)
                live.update(parsed=value, value_ok=value == {'ok': True, 'echo': 'onecrew-kiro-check'},
                            metering=[u.get('metering') for u in usages if 'metering' in u])
            except Exception as error:  # the adapter's own refusal is the evidence
                live.update(parsed=None, value_ok=False, parser_error=type(error).__name__ + ': ' + str(error)[:300],
                            stderr_tail=err[-500:])
            evidence['live'] = live
    evidence['verified'] = bool(evidence.get('static_ok') and (args.no_live or evidence.get('live', {}).get('value_ok')))
    Path(args.output).write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({k: evidence[k] for k in ('version', 'static_ok', 'verified')}))
    return 0 if evidence['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
