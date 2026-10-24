"""Read-only T54 release-evidence validator: python -m wfkit.release_check bundle.json.

Validates recorded observations, not document labels. It does not execute an
upgrade, swap installations, accept a release, or certify a pilot. A fixture
bundle needs --allow-simulated and proves this validator's rules only.

Schema 1: release, mode, artifacts(previous/current), gate_history receipt refs,
sandbox absolute path, monitored_files(before/after SHA), and checks mapping
installed/upgrade/events/rollback/notes to SHA-pinned JSON receipts. Every receipt
uses finalgate.Evidence provenance and artifact identity. Notes contain actual
Markdown. Optional provider_bundle reuses finalgate's wheel comparison and the
shared provider evaluator; it is required for RP, without PL-B prerequisites.
"""
import argparse
import json
import re
from pathlib import Path
from zipfile import BadZipFile

from onecrew.ledger import content_hash
from onecrew.v2 import compat
from wfkit import gate
from wfkit.finalgate import Evidence, identity, passed, require, strings, timestamp, wheel_files, compare
from wfkit.provider_evidence import evaluate as providers

PARTS = {**{f'R{i:02}': f'T54{chr(96+i)}' for i in range(1, 9)}, 'RP': 'T54i', 'RX1': 'T54j', 'RX2': 'T54k'}
CHECKS = ('installed', 'upgrade', 'events', 'rollback', 'notes')
SECTIONS = ('Usable outcomes', 'Limits', 'Install', 'Rollback', 'Evidence status')


def digest(value, label):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) and set(value) != {'0'}, label + ': invalid SHA-256')
    return value


def under(path, root):
    return Path(path).is_absolute() and Path(root).is_absolute() and Path(path).resolve().is_relative_to(Path(root).resolve())


class Receipts(Evidence):
    def read(self, ref):
        path = Path(ref['path'])
        require(not path.is_absolute() and '..' not in path.parts and under(self.root / path, self.root), 'receipt escapes evidence directory')
        digest(ref['sha256'], 'receipt')
        return super().read(ref)


def preserved(rows):
    require(isinstance(rows, list) and bool(rows), 'preservation snapshot is empty')
    result = {}
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'id', 'revision', 'budget', 'evidence', 'attempts'}, 'incomplete preservation row')
        require(isinstance(row['id'], str) and row['id'] and row['id'] not in result, 'duplicate or missing preserved ID')
        require(isinstance(row['revision'], (str, int)) and not isinstance(row['revision'], bool), 'revision identity missing')
        require(isinstance(row['budget'], dict) and row['budget'], 'budget snapshot missing')
        require(isinstance(row['evidence'], list) and isinstance(row['attempts'], list), 'evidence/attempt snapshot missing')
        result[row['id']] = row
    require(any(row['evidence'] for row in rows), 'no evidence to exercise preservation')
    require(any(any(a.get('status') == 'unknown' for a in row['attempts']) for row in rows), 'no unreconciled attempt in preservation fixture')
    return result


def install_observation(receipt, artifact, archive, sandbox):
    passed(receipt, artifact)
    require(receipt.get('exit_code') == 0 and type(receipt.get('exit_code')) is int, 'installed command failed')
    command = receipt['command']
    require(isinstance(command, list) and command and all(isinstance(x, str) and x for x in command), 'installed command missing')
    require(under(receipt['venv'], sandbox) and under(command[0], receipt['venv']), 'command is outside isolated venv')
    require(under(receipt['state_root'], sandbox) and receipt['fresh_venv'] is True, 'scenario is not isolated')
    require(receipt['boundary_violations'] == [], 'module boundary violations')
    loaded = receipt['loaded']
    require(isinstance(loaded, list) and loaded, 'loaded module inventory missing')
    modules = {row['name']: row['path'] for row in loaded}
    require(len(modules) == len(loaded), 'duplicate loaded module')
    require(not gate.judge_origin({'modules': modules, 'site': receipt['site']}, receipt['checkout']), 'module loaded outside installed site')
    require(all(under(site, receipt['venv']) for site in receipt['site']), 'site-packages outside venv')
    for row in loaded:
        require(row['archive_path'] in archive and row['sha256'] == archive[row['archive_path']], 'installed module bytes differ from wheel')
    require(receipt['checkout_control_refused'] is True, 'checkout negative control missing')


def scan_observation(branch, sandbox):
    scan = branch['scan']
    require(scan['read_only'] is True and under(scan['state_root'], sandbox), 'scan did not target an isolated copy')
    digest(scan['ledger_sha'], 'scan ledger')
    require(scan['ledger_sha'] == branch['ledger_at_switch'], 'rollback used a stale ledger scan')
    require(content_hash(scan['input_hashes']) == scan['inputs_sha'] == branch['inputs_at_switch'], 'rollback used stale config/contract inputs')
    blocks = [b for root in scan['roots'] for b in root['blocks']]
    require(all(b['type'] in ('read', 'continue') and b['id'] in ('B1','B2','B3','B4') for b in blocks), 'unknown rollback block')
    counts = {'read': sum(b['type'] == 'read' for b in blocks), 'continue': sum(b['type'] == 'continue' for b in blocks), 'total': len(blocks)}
    require(scan['blocking'] == counts, 'scan block counts do not match root observations')
    return counts['total']


def decide(bundle, root='.', allow_simulated=False):
    result = {'decision': 'refused', 'conditions': {}, 'reasons': [], 'owner_acceptance': False}
    errors, receipts = {}, {}
    def check(code, function):
        try: function()
        except (ValueError, TypeError, KeyError, AttributeError, OSError, BadZipFile, StopIteration) as error:
            errors[code] = str(error) or type(error).__name__
    try:
        require(type(bundle['schema']) is int and bundle['schema'] == 1, 'bundle schema must be 1')
        release = bundle['release']; require(release in PARTS, 'unsupported release')
        require(bundle['mode'] in ('fixture', 'real'), 'mode missing')
        fixture = bundle['mode'] == 'fixture'
        require(not fixture or allow_simulated, 'fixture bundle needs --allow-simulated')
        evidence = Receipts(Path(root).resolve(), fixture)
        previous, current = bundle['artifacts']['previous'], bundle['artifacts']['current']
        for artifact in (previous, current):
            identity(artifact); digest(artifact['wheel_sha256'], 'wheel')
            require(set(artifact['commit']) != {'0'}, 'null commit')
            path = Path(artifact['wheel'])
            require(not path.is_absolute() and '..' not in path.parts, 'wheel escapes evidence directory')
        archives = [wheel_files(evidence.root, artifact) for artifact in (previous, current)]
        sandbox = bundle['sandbox']; require(Path(sandbox).is_absolute(), 'sandbox must be absolute')
        result.update({'release': release, 'testcase': PARTS[release], **identity(current)})
    except (ValueError, TypeError, KeyError, AttributeError, OSError, BadZipFile) as error:
        result['reasons'] = [{'code': 'INPUT', 'detail': str(error)}]
        return result

    def receipt(name):
        if name not in receipts:
            value = evidence.read(bundle['checks'][name]); passed(value, current)
            require(value['kind'] == name and value['release'] == release, 'wrong release/check receipt')
            receipts[name] = value
        return receipts[name]

    def prerequisites():
        history = [evidence.read(ref) for ref in bundle['gate_history']]
        require(history, 'previous delivered gate history missing')
        require(all(h.get('decision', h.get('result')) == 'pass' and h.get('gate', '').startswith('CG-') for h in history), 'history has no passing delivery gate')
        latest = max(history, key=lambda r: timestamp(r['at']))
        require(identity(latest) == identity(previous), 'rollback build is not the latest recorded passing delivery artifact')
        require(timestamp(latest['at']) <= timestamp(receipt('installed')['at']), 'upgrade predates previous delivery gate')
        monitored = bundle['monitored_files']
        require(isinstance(monitored, list) and monitored, 'live state/monitor inventory missing')
        for row in monitored:
            require(not under(row['path'], sandbox), 'live inventory incorrectly points inside sandbox')
            require(digest(row['before'], 'live before') == digest(row['after'], 'live after'), 'live state or monitor changed')
        for delivery in bundle.get('deliveries', []):
            require(identity(delivery) == identity(current), 'delivery names a different build')
            require(all(timestamp(delivery['at']) >= timestamp(receipt(name)['at']) for name in CHECKS), 'release delivered before its T54 evidence completed')
    check('INPUTS', prerequisites)

    def installed():
        row = receipt('installed'); install_observation(row, current, archives[1], sandbox)
        modules = strings(row['new_modules'], 'new modules', True)
        require(modules <= archives[1].keys(), 'release module missing from wheel')
        if release in ('RX1', 'RX2'):
            expected = {'doc'} if release == 'RX1' else {'data', 'ops'}
            require({r['adapter'] for r in row['adapter_runs']} >= expected, 'installed adapter scenario missing')
            for run in row['adapter_runs']:
                require(run['root'] and run['result'] == 'pass' and run['artifact'] and identity(run) == identity(current), 'adapter did not complete on this artifact')
    check('T54.1', installed)

    def upgrade():
        row = receipt('upgrade')
        require(identity(row['from']) == identity(previous) and identity(row['to']) == identity(current), 'upgrade artifact pair mismatch')
        require(under(row['state_root'], sandbox) and row['state_root'] != row['source_state_root'], 'upgrade did not use a ledger copy')
        require(preserved(row['before']) == preserved(row['after']), 'upgrade changed ID/revision/budget/evidence/unreconciled attempt')
    check('T54.2', upgrade)

    def events():
        row = receipt('events')
        require(identity(row['old_artifact']) == identity(previous), 'event comparator used wrong old build')
        require(isinstance(row['new_events'], list), 'event classification inventory missing')
        neutral = set()
        for event in row['new_events']:
            classification = compat.event_class(event['kind'])
            require(classification is not None and classification == event['class'], 'unknown or misclassified event')
            compat.check_write(event['kind'], event['payload'], event['anchor'])
            require(classification != 'B' or event['anchor'].startswith('plan-ns:'), 'class B event on legacy anchor')
            if classification == 'A': neutral.add(event['kind'])
        comparisons = row['comparisons']
        require(isinstance(comparisons, list) and comparisons, 'old behavior comparison missing')
        require(neutral <= {r['kind'] for r in comparisons}, 'class A behavior comparison missing')
        for comparison in comparisons:
            require(set(comparison['before']) >= {'S','G','C'} and set(comparison['after']) >= {'S','G','C'}, 'incomplete S/G/C observation')
            require(all(comparison['before'][key] == comparison['after'][key] for key in ('S','G','C')), 'old S/G/C behavior changed')
    check('T54.3', events)

    def rollback():
        row = receipt('rollback')
        rejected, allowed = row['rejected'], row['allowed']
        require(scan_observation(rejected, sandbox) > 0 and rejected['switched'] is False, 'blocked rollback was not refused')
        require(scan_observation(allowed, sandbox) == 0 and allowed['switched'] is True, 'zero-block rollback was not exercised')
        require(all(branch['scan']['old_version'] == previous['commit'] for branch in (rejected, allowed)), 'scan targets a different rollback version')
        old_run = evidence.read(allowed['old_run']); install_observation(old_run, previous, archives[0], sandbox)
        forward = evidence.read(row['forward_run']); install_observation(forward, current, archives[1], sandbox)
        require(old_run['state_root'] == forward['state_root'] == allowed['scan']['state_root'], 'old/new runs did not use the scanned ledger copy')
        require(timestamp(receipt('upgrade')['at']) <= timestamp(old_run['at']), 'rollback happened before upgrade evidence')
        require(timestamp(old_run['at']) <= timestamp(forward['at']) <= timestamp(row['at']), 'roll-forward chronology invalid')
        require(preserved(row['before']) == preserved(receipt('upgrade')['after']), 'rollback uses a different upgraded snapshot')
        require(preserved(row['before']) == preserved(row['after']), 'roll-forward lost retained state')
        if release in ('R05', 'R08'):
            timeline = row['intent_events']; require(isinstance(timeline, list) and timeline, 'reconcile sequence missing')
            require(all(type(e['seq']) is int and e['seq'] > 0 and e['kind'] in ('reconciled','continued','effect') for e in timeline)
                    and len({e['seq'] for e in timeline}) == len(timeline), 'invalid/duplicate intent event sequence')
            unresolved = {attempt['id'] for root in row['before'] for attempt in root['attempts'] if attempt['status'] == 'unknown'}
            reconciled = set()
            for event in sorted(timeline, key=lambda e: e['seq']):
                if event['kind'] == 'reconciled': reconciled.add(event['intent'])
                if event['kind'] in ('continued', 'effect'):
                    require(event['intent'] not in unresolved or event['intent'] in reconciled, 'root continued or effect repeated before reconcile')
            require(unresolved <= reconciled, 'unknown intents not reconciled before roll-forward completion')
    check('T54.4', rollback)

    def notes():
        row = receipt('notes'); text = row['markdown']
        require(isinstance(text, str), 'release-note text missing')
        for title in SECTIONS:
            section = re.search(r'^## ' + re.escape(title) + r'[^\S\n]*\n((?:(?!^## ).)*)', text, re.M | re.S)
            require(section is not None and section.group(1).strip(), 'release-note section missing: ' + title)
        statuses = dict(re.findall(r'^(Code|Fixture checks|Real checks|Acceptance): ([^\n]+)$', text, re.M))
        require(set(statuses) == {'Code','Fixture checks','Real checks','Acceptance'}, 'four evidence states must be separate lines')
        require(statuses['Code'] == 'present' and statuses['Fixture checks'] == 'passed', 'code/fixture state not established')
        require(statuses['Acceptance'] == 'not-requested', 'a release cannot claim owner acceptance')
        require(statuses['Real checks'] in ('not-run','partial','passed'), 'real-check state invalid')
        if statuses['Real checks'] != 'not-run':
            behavioral = [evidence.read(ref) for ref in row['real_checks']]
            require(behavioral and all(r.get('kind') == 'behavior' and r.get('result') == 'pass' and r['simulated'] is False for r in behavioral), 'real-check claim lacks real behavioral receipts')
        if release == 'RP':
            provider_bundle = bundle['provider_bundle']
            require(identity(provider_bundle['artifacts']['final']) == identity(current), 'RP matrix targets wrong artifact')
            source = provider_bundle['artifacts']['pilot']
            comparison = compare(provider_bundle, evidence) if identity(source) != identity(current) else None
            states = providers(provider_bundle['providers'], provider_bundle['comparison']['items'], evidence, source, current, comparison)
            eligible = {key for key, state in states.items() if state['status'] == 'usable'}
            require(eligible, 'RP subset is empty')
            require(row['provider_states'] == states and strings(row['subset'], 'RP subset') == eligible, 'RP notes disagree with shared provider evidence')
            require(row['p1_count'] == len(eligible) and row['p1_label'] == 'subset', 'release cannot claim program P1.0 full')
    check('T54.5', notes)
    result.update({'decision': 'refused' if errors else 'pass',
        'conditions': {code: code not in errors for code in ('INPUTS', *(f'T54.{i}' for i in range(1, 6)))},
        'reasons': [{'code': code, 'detail': detail} for code, detail in errors.items()],
        'simulated_receipts_used': fixture,
        'proves': 'validator rules only; no release or pilot execution' if fixture else 'supplied T54 observations validated; not owner acceptance'})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle'); parser.add_argument('--allow-simulated', action='store_true')
    args = parser.parse_args(argv); path = Path(args.bundle)
    try: result = decide(json.loads(path.read_text(encoding='utf-8')), path.parent, args.allow_simulated)
    except (OSError, ValueError) as error:
        result = {'decision': 'refused', 'reasons': [{'code': 'INPUT', 'detail': str(error)}]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['decision'] == 'pass' else 1


if __name__ == '__main__': raise SystemExit(main())
