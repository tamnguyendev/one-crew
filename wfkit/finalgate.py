"""Read-only W38d / CG-KET validator. Run ``python -m wfkit.finalgate bundle.json``.

The JSON bundle has schema=1, mode=real|fixture, artifacts={pilot,final} (each
commit, wheel_sha256, wheel path), comparison (id, source/target identities,
changed_files, affected, items), gates, phases, monitored_files, providers,
author_vendor, and publications. Receipt references are {path, sha256}; paths
are relative to the bundle. Receipts retain their original commit/wheel hash.
All receipts explicitly declare simulated and provenance (kind, source).

Comparison mapping is a SHA-pinned impact-map receipt containing tasks (the
approved id/owned/depends_on graph on the source artifact); claimed item graphs
must equal that pinned map. Comparison items use that shape plus original
and supplements receipt references. Six AC/context items and six provider cells
are required. Gates wrap a gate.py decision as receipt, with a T38a doccheck ref
and evidence uses ({item, receipt, validity, comparison_id if inherited}).
Phases PL-A/PL-B name their artifact, started_at, completed_at, entry receipt,
release receipt map, and completion testcase receipt map. Providers are the six
{id, provider, role, model, vendor, cli_sha256, cli_files, status} rows; IDs are provider:role.
Passing provider receipts carry the providers.cli_identity() object and must
match the row's pinned CLI hash (including executable/prefix-file consistency).
Publications T40c/T54i/T40d contain the identical eligible-cell list plus label
full|partial and missing cells. This validates supplied evidence, not owner
acceptance, and never invokes providers, writes a ledger, or runs pilot jobs.
Fixture bundles require --allow-simulated and can only prove the gate rules.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from onecrew.dependency_core import affected_tasks

GATES = tuple(f'CG-R{i:02}' for i in range(9)) + ('CG-RP', 'CG-RX1', 'CG-RX2',
    'KN-R01-R02', 'KN-R02-R03', 'KN-R03-R04')
CELLS = frozenset(f'{p}:{r}' for p in ('claude', 'codex', 'kiro') for r in ('reviewer', 'advisor'))
BASE_ITEMS = frozenset(('AC1', 'AC2', 'AC3', 'AC4', 'AC5', 'context'))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def strings(value, name, nonempty=False):
    require(isinstance(value, list) and all(isinstance(x, str) and x for x in value), f'{name}: expected string list')
    require(len(value) == len(set(value)) and (value or not nonempty), f'{name}: empty or duplicate values')
    return set(value)


def identity(value):
    require(isinstance(value, dict), 'artifact identity missing')
    commit, wheel = value.get('commit'), value.get('wheel_sha256')
    require(isinstance(commit, str) and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', commit), 'invalid commit hash')
    require(isinstance(wheel, str) and re.fullmatch(r'[0-9a-f]{64}', wheel), 'invalid wheel hash')
    return {'commit': commit, 'wheel_sha256': wheel}


def timestamp(value):
    require(isinstance(value, str), 'timestamp missing')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None, 'timestamp needs timezone')
    return result


class Evidence:
    def __init__(self, root, fixture=False):
        self.root, self.fixture = Path(root), fixture

    def read(self, ref):
        require(isinstance(ref, dict) and isinstance(ref.get('path'), str), 'receipt reference missing')
        raw = (self.root / ref['path']).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == ref.get('sha256'), f"receipt hash changed: {ref['path']}")
        receipt = json.loads(raw)
        require(isinstance(receipt, dict), 'receipt must be an object')
        provenance = receipt.get('provenance', {})
        require(type(receipt.get('simulated')) is bool, 'receipt must declare simulated')
        require(isinstance(provenance, dict) and provenance.get('source'), 'receipt provenance missing')
        require(provenance.get('kind') == ('fixture' if receipt['simulated'] else 'real'), 'receipt provenance inconsistent')
        require(self.fixture or not receipt['simulated'], 'simulated evidence cannot prove a real gate')
        require(self.fixture or not receipt.get('simulated_receipts_used'), 'gate used simulated receipts')
        identity(receipt)
        timestamp(receipt.get('at'))
        return receipt


def passed(receipt, artifact, name=None):
    require(receipt.get('result', receipt.get('decision')) == 'pass', f'{name or "receipt"}: not pass')
    require(identity(receipt) == identity(artifact), f'{name or "receipt"}: wrong artifact')
    if name:
        actual = receipt.get('testcase', receipt.get('gate'))
        if actual is None and isinstance(receipt.get('release'), str):
            actual = 'CG-' + receipt['release']
        require(actual == name, f'{name}: wrong receipt name')


def wheel_files(root, artifact):
    identity(artifact)
    require(isinstance(artifact.get('wheel'), str), 'wheel path missing')
    path = Path(root) / artifact['wheel']
    require(hashlib.sha256(path.read_bytes()).hexdigest() == artifact['wheel_sha256'], 'wheel content hash mismatch')
    with ZipFile(path) as wheel:
        entries = [i for i in wheel.infolist() if not i.is_dir()]
        require(len(entries) == len({i.filename for i in entries}), 'duplicate wheel member')
        return {i.filename: hashlib.sha256(wheel.read(i)).hexdigest() for i in entries}


def compare(bundle, evidence):
    """Derive the actual archive diff and shared closure; reject claimed omissions."""
    source, target = bundle['artifacts']['pilot'], bundle['artifacts']['final']
    comp = bundle['comparison']
    require(isinstance(comp, dict) and isinstance(comp.get('id'), str) and comp['id'], 'comparison missing')
    require(identity(comp['source']) == identity(source) and identity(comp['target']) == identity(target), 'comparison wrong artifact pair')
    old, new = wheel_files(evidence.root, source), wheel_files(evidence.root, target)
    changed = {p for p in old.keys() | new.keys() if old.get(p) != new.get(p)}
    require(strings(comp['changed_files'], 'changed_files') == changed, 'changed_files differ from wheel diff')
    rows = comp['items']
    require(isinstance(rows, list) and all(isinstance(x, dict) for x in rows), 'comparison items missing')
    require(all(isinstance(r.get('id'), str) and r['id'] for r in rows), 'item ID missing')
    items = {r['id']: r for r in rows}
    require(len(items) == len(rows) and BASE_ITEMS | CELLS <= items.keys(), 'comparison items missing or duplicated')
    mapping = evidence.read(comp['mapping'])
    passed(mapping, source)
    require(mapping.get('kind') == 'impact-map' and isinstance(mapping.get('tasks'), list), 'pinned dependency map missing')
    expected = mapping['tasks']
    require(all(isinstance(r, dict) and set(r) == {'id', 'owned', 'depends_on'} for r in expected), 'invalid pinned dependency map')
    require({r['id'] for r in expected} == items.keys() and len(expected) == len(items), 'dependency map items differ')
    for entry in expected:
        require(all(entry[k] == items[entry['id']][k] for k in ('owned', 'depends_on')), 'claimed graph differs from pinned dependency map')
    for key, row in items.items():
        owned = strings(row['owned'], f'{key}.owned', True)
        require(all(not p.startswith(('/', '\\')) and '\\' not in p and '..' not in p.split('/') for p in owned), 'invalid owned wheel path')
        require(strings(row['depends_on'], f'{key}.depends_on') <= items.keys(), 'unknown dependency')
        require(isinstance(row.get('supplements'), list), 'supplement list missing')
    # A malformed cyclic dependency cannot establish an impact proof.
    pending, done = set(items), set()
    while pending:
        ready = {k for k in pending if set(items[k]['depends_on']) <= done}
        require(bool(ready), 'cyclic comparison dependencies')
        done |= ready
        pending -= ready
    mapped = {p for row in rows for p in row['owned']}
    selected = list(items) if changed - mapped else [r['id'] for r in rows if set(r['owned']) & changed]
    affected = affected_tasks({'tasks': rows}, selected) if selected else set()
    require(strings(comp['affected'], 'affected') == affected, 'comparison omitted or added dependency impact')
    return {'id': comp['id'], 'source': identity(source), 'target': identity(target), 'items': items,
            'changed_files': sorted(changed), 'affected': sorted(affected)}


def evidence_status(original, attempts, target, comparison=None, item=None):
    """HL2/HL5: one evaluator for RP, publication, pilot entry and final gate."""
    for receipt in [original] + attempts:
        require(isinstance(receipt, dict), 'missing behavioral evidence')
        require(receipt.get('kind') == 'behavior', 'evaluation receipt is not behavioral evidence')
        require(receipt.get('result') in ('pass', 'fail', 'blocked'), 'invalid behavior result')
        if receipt['result'] == 'blocked':
            require(isinstance(receipt.get('reason'), str) and receipt['reason'], 'blocked evidence needs reason')
    # T40c [E29]: every state that is not `usable` carries its `reason` (why the cell is not usable for the target build).
    relevant = sorted((r for r in [original] + attempts if identity(r) == identity(target)), key=lambda r: timestamp(r['at']))
    definitive = [r for r in relevant if r['result'] != 'blocked']
    if definitive:
        chosen = definitive[-1]
        if chosen['result'] == 'pass':
            return {'status': 'usable', 'validity': 'direct', 'evidence': identity(chosen)}
        return {'status': 'failed', 'reason': _receipt_reason(chosen, 'the check failed on build ' + identity(chosen)['wheel_sha256'])}
    if original['result'] == 'pass':
        if comparison and identity(original) == comparison['source'] and identity(target) == comparison['target'] and item not in comparison['affected']:
            return {'status': 'usable', 'validity': 'inherited', 'comparison_id': comparison['id'], 'evidence': identity(original)}
        why = ('no inheritance comparison' if not comparison
               else f"comparison {comparison.get('id')} marks this cell affected" if item in (comparison.get('affected') or [])
               else f"comparison {comparison.get('id')} does not cover this build pair")
        return {'status': 'recheck', 'reason': f"passed on build {identity(original)['wheel_sha256']}, not on the target build "
                                                f"{identity(target)['wheel_sha256']}; {why}"}
    if original['result'] == 'blocked':
        return {'status': 'unverified', 'reason': original['reason']}
    return {'status': 'failed', 'reason': _receipt_reason(original, 'the original receipt failed on build ' + identity(original)['wheel_sha256'])}


def _receipt_reason(receipt, default):
    reason = receipt.get('reason')
    return reason.strip() if isinstance(reason, str) and reason.strip() else default


HOOK_SEGMENTS = (('PL-A', 'PL-A', 'PL-A'), ('between', 'PL-A', 'PL-B'), ('PL-B', 'PL-B', 'PL-B'))


def _hook_changes(row, phases, ev):
    """T45d [E13] (KQ5): one monitored row checked PER PHASE. Its `phases` hold the before/after hash of PL-A and PL-B and join the
    program pair; each segment whose hash moved (inside PL-A, between the phases, inside PL-B) needs its own `changes[segment]` with the
    change time inside the segment's window and an owner U2 covering exactly that path and pair, granted before the change. Returns the
    (segment, path, U2 reference, U2 receipt) of every authorised change."""
    path, per, changes = row['path'], row['phases'], row.get('changes') or {}
    require(isinstance(changes, dict) and set(changes) <= {s for s, _, _ in HOOK_SEGMENTS}, f'{path}: unknown hook/config change segment')
    for name in ('PL-A', 'PL-B'):
        for key in ('before_sha256', 'after_sha256'):
            require(isinstance(per[name], dict) and isinstance(per[name].get(key), str) and re.fullmatch(r'[0-9a-f]{64}', per[name][key]),
                    f'{path}: {name} hook/config hash missing')
    require(per['PL-A']['before_sha256'] == row['before_sha256'] and per['PL-B']['after_sha256'] == row['after_sha256'],
            f'{path}: per-phase hashes do not join the program before/after')
    pairs = {'PL-A': (per['PL-A']['before_sha256'], per['PL-A']['after_sha256']),
             'between': (per['PL-A']['after_sha256'], per['PL-B']['before_sha256']),
             'PL-B': (per['PL-B']['before_sha256'], per['PL-B']['after_sha256'])}
    used = []
    for segment, first, last in HOOK_SEGMENTS:
        before, after = pairs[segment]
        label = 'between PL-A and PL-B' if segment == 'between' else segment
        if before == after:
            require(segment not in changes, f'{path}: {label}: a change is recorded but the hashes did not move')
            continue
        change = changes.get(segment)
        require(isinstance(change, dict) and change.get('authorization'), f'{path}: {label}: hook/config changed without U2')
        u2 = ev.read(change['authorization'])
        require(u2.get('kind') == 'U2' and u2.get('actor') == 'owner' and u2.get('path') == path and u2.get('result') == 'pass',
                f'{path}: {label}: hook/config changed without U2')
        require(u2.get('before_sha256') == before and u2.get('after_sha256') == after, f'{path}: {label}: U2 does not cover this change')
        at = timestamp(change.get('changed_at'))
        low = phases[first]['completed_at' if segment == 'between' else 'started_at']
        high = phases[last]['started_at' if segment == 'between' else 'completed_at']
        require(low and high and timestamp(low) <= at <= timestamp(high), f'{path}: {segment}: change time outside the phase window')
        require(timestamp(u2['at']) <= at, f'{path}: {label}: U2 granted after hook change')
        used.append((segment, path, change['authorization'], u2))
    return used


def _ac1_counts(used, phases, ev):
    """T45d [E13]/T45b [E10]: every U2 that authorises a hook/config change is an owner decision counted in AC1: the pilot report on the
    PL-B T35c completion receipt (`owner_decisions`, the wfkit.pilot_report schema) has exactly one U2 action naming that U2 receipt
    (`authorization` = its sha256) and the job's AC1 table counts it. One U2 authorises one change, so it is never counted twice."""
    if not used: return
    seen = {}
    for segment, path, ref, _ in used:
        require(ref['sha256'] not in seen, f'{path}: {segment}: one U2 authorises one change (already used for {seen.get(ref["sha256"])})')
        seen[ref['sha256']] = f'{path} {segment}'
    report = ev.read(phases['PL-B']['completion']['T35c'])
    decisions = report.get('owner_decisions')
    require(isinstance(decisions, dict) and isinstance(decisions.get('actions'), list), 'AC1 owner decisions missing from the T35c pilot report')
    actions = [a for a in decisions['actions'] if isinstance(a, dict) and a.get('kind') == 'U2']
    table = decisions.get('per_job') or {}
    for segment, path, ref, _ in used:
        mine = [a for a in actions if a.get('authorization') == ref['sha256']]
        require(mine, f'{path}: {segment}: U2 not counted in AC1')
        require(len(mine) == 1, f'{path}: {segment}: U2 counted {len(mine)} times in AC1')
        job = mine[0].get('job')
        counted = (table.get(job) or {}).get('U2', 0) if isinstance(table.get(job, {}), dict) else 0
        require(counted == sum(1 for a in actions if a.get('job') == job), f'AC1 table of {job} does not count its U2')


def provider_capability(rows, states, author_vendor, pinned=()):
    require(isinstance(author_vendor, str) and author_vendor.strip(), 'author model vendor missing')
    usable = {key for key, state in states.items() if state['status'] == 'usable'}
    independent = any(r['id'] in usable and r['role'] == 'reviewer' and r['vendor'].strip().casefold() != author_vendor.strip().casefold() for r in rows)
    return {'ok': independent and set(pinned) <= usable, 'eligible': sorted(usable),
            'independent_reviewer': independent, 'missing_pins': sorted(set(pinned) - usable)}


def decide(bundle, root='.', allow_simulated=False):
    errors, result = {}, {'gate': 'CG-KET', 'decision': 'refused', 'conditions': {}, 'reasons': []}
    def check(code, fn):
        try:
            fn()
        except (ValueError, KeyError, TypeError, AttributeError, OSError, BadZipFile, StopIteration) as exc:
            errors[code] = str(exc) or type(exc).__name__
    try:
        require(isinstance(bundle, dict) and type(bundle.get('schema')) is int and bundle['schema'] == 1, 'bundle schema must be 1')
        require(bundle.get('mode') in ('real', 'fixture'), 'bundle mode missing')
        require(bundle['mode'] != 'fixture' or allow_simulated, 'fixture bundle requires --allow-simulated')
        target, source = bundle['artifacts']['final'], bundle['artifacts']['pilot']
        identity(target); identity(source)
    except (ValueError, KeyError, TypeError) as exc:
        result['reasons'] = [{'code': 'INPUT', 'detail': str(exc)}]
        return result
    ev = Evidence(root, bundle['mode'] == 'fixture')
    computed = {}
    def comparison_check():
        computed.update(compare(bundle, ev))
        for key, row in computed['items'].items():
            original = ev.read(row['original'])
            require(identity(original) == identity(source), f'{key}: historical evidence changed artifact')
            require(original.get('item') == key, f'{key}: wrong evidence item')
            require(original.get('kind') == 'behavior', f'{key}: evaluation substituted for behavior')
            if key not in CELLS:
                passed(original, source)
                if key in computed['affected']:
                    supplements = [ev.read(r) for r in row['supplements']]
                    require(bool(supplements), f'{key}: affected item missing supplemental checks')
                    for rec in supplements:
                        passed(rec, target)
                        require(rec.get('item') == key, f'{key}: wrong supplemental item')
                        require(rec.get('kind') == 'supplement', f'{key}: supplemental checks are not historical pilot work')
    check('KQ2', comparison_check)
    # Structural proof may remain valid when only a supplemental check is missing.
    structural = computed if computed.get('items') else None
    def gates_check():
        gates = bundle['gates']
        require(isinstance(gates, dict), 'gate receipts missing')
        for name in GATES:
            entry = gates[name]
            receipt = ev.read(entry['receipt'])
            passed(receipt, target, name)
            require(isinstance(receipt.get('manifest_sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', receipt['manifest_sha256']), f'{name}: manifest hash missing')
            doc = ev.read(entry['doccheck'])
            passed(doc, target, 'T38a')
            require(doc.get('problems') == 0 and doc.get('kit_guard', {}).get('ok') is True, f'{name}: doccheck/kit guard failed')
            command = doc.get('command')
            require((isinstance(command, str) and command.strip()) or (isinstance(command, list) and command and all(isinstance(x, str) and x for x in command)), f'{name}: doccheck command missing')
            # doccheck.run records its actual subprocess string; kitguard runs
            # before that subprocess, so its proof is the structured receipt,
            # not the presence of the word "kitguard" in an arbitrary command.
            require(doc['kit_guard'].get('manifest_sha256') == receipt['manifest_sha256'], f'{name}: kit-guard manifest does not match')
            require(doc.get('manifest_sha256') == receipt['manifest_sha256'] and re.fullmatch(r'[0-9a-f]{64}', doc.get('block_sha256', '')), f'{name}: doccheck hash missing or mismatched')
            uses = entry['evidence']
            require(isinstance(uses, list) and bool(uses), f'{name}: HL4 evidence uses missing')
            for use in uses:
                rec = ev.read(use['receipt'])
                require(rec.get('item') == use['item'], f'{name}: evidence item mismatch')
                require(rec.get('result') == 'pass', f'{name}: evidence not pass')
                if identity(rec) == identity(target):
                    require(use.get('validity') == 'direct', f'{name}: direct evidence mislabeled')
                else:
                    require(structural and identity(rec) == structural['source'] and use['item'] in structural['items'] and use['item'] not in structural['affected'], f'{name}: invalid inherited evidence')
                    require(use.get('validity') == 'inherited' and use.get('comparison_id') == structural['id'], f'{name}: inheritance provenance missing')
    check('KQ1', gates_check)
    def pilot_check():
        phase = bundle['phases']['PL-B']
        require(phase.get('started_at') and phase.get('completed_at'), 'PL-B not started or not completed')
        require(timestamp(phase['completed_at']) >= timestamp(phase['started_at']), 'PL-B completed before start')
        for name in ('T35c', 'T14c'):
            rec = ev.read(phase['completion'][name])
            passed(rec, source, name)
            require(rec.get('kind') == 'pilot', f'{name}: fixture/evaluation is not real pilot behavior')
            require(timestamp(rec['at']) >= timestamp(phase['completed_at']), f'{name}: completion receipt precedes completion')
    check('KQ3', pilot_check)
    def history_check():
        phases = bundle['phases']
        require(set(phases) == {'PL-A', 'PL-B'}, 'phase history missing')
        for name, tc, required in (('PL-A', 'T45b', {'CG-R01', 'CG-R02', 'CG-R03', 'CG-RX1'}),
                                  ('PL-B', 'T45c', {'CG-R01', 'CG-R02', 'CG-R03', 'CG-R04', 'CG-R05', 'CG-RP', 'CG-RX1', 'CG-RX2'})):
            phase = phases[name]
            artifact = phase['artifact']
            wheel_files(ev.root, artifact)
            if name == 'PL-B':
                require(identity(artifact) == identity(source), f'{name}: pilot artifact differs')
            start = timestamp(phase['started_at'])
            entry = ev.read(phase['entry'])
            passed(entry, artifact, tc)
            require(timestamp(entry['at']) < start, f'{name}: entry gate did not pass before start')
            require(required <= phase['releases'].keys(), f'{name}: missing release gates')
            for gate, ref in phase['releases'].items():
                require(gate in GATES, 'unknown historical release gate')
                rec = ev.read(ref)
                passed(rec, artifact, gate)
                require(timestamp(rec['at']) <= timestamp(entry['at']), f'{name}: release gate passed too late')
        a = phases['PL-A']
        rec = ev.read(a['completion']['T35b'])
        passed(rec, a['artifact'], 'T35b')
        require(rec.get('kind') == 'pilot' and timestamp(a['started_at']) <= timestamp(a['completed_at']) <= timestamp(phases['PL-B']['started_at']), 'PL-A completion history invalid')
        require(timestamp(a['completed_at']) <= timestamp(rec['at']) < timestamp(phases['PL-B']['started_at']), 'PL-A completion receipt missing before PL-B start')
    check('KQ4', history_check)
    def hooks_check():
        rows = bundle['monitored_files']
        require(isinstance(rows, list) and bool(rows), 'monitored hook/config inventory missing')
        names, used = set(), []
        for row in rows:
            require(row.get('path') and row['path'] not in names, 'hook path missing/duplicate')
            names.add(row['path'])
            for key in ('before_sha256', 'after_sha256'):
                require(isinstance(row.get(key), str) and re.fullmatch(r'[0-9a-f]{64}', row[key]), 'hook/config hash missing')
            if 'phases' not in row and not any(k in row for k in ('changes', 'authorization', 'changed_at')):
                # An unchanged row keeps the two-hash format; a changed row without per-phase hashes cannot be located.
                require(row['before_sha256'] == row['after_sha256'], f"{row['path']}: per-phase hook/config hashes missing: "
                        'a change must be located inside PL-A, between the phases or inside PL-B')
                continue
            require(isinstance(row.get('phases'), dict) and set(row['phases']) == {'PL-A', 'PL-B'},
                    f"{row['path']}: per-phase hook/config hashes missing: before/after for PL-A and PL-B")
            used.extend(_hook_changes(row, bundle['phases'], ev))
        _ac1_counts(used, bundle['phases'], ev)
    check('KQ5', hooks_check)
    states, provider_rows = {}, []
    def providers_check():
        from wfkit.provider_evidence import evaluate
        rows = bundle['providers']
        states.update(evaluate(rows, bundle['comparison']['items'], ev, source, target, structural))
        provider_rows.extend(rows)
        capability = provider_capability(rows, states, bundle['author_vendor'])
        require(capability['ok'], 'missing independent model-vendor reviewer for final artifact')
        # Re-evaluate historical PL-B capability and pins from direct A receipts.
        originals = {r['id']: evidence_status(ev.read(next(i for i in bundle['comparison']['items'] if i['id'] == r['id'])['original']), [], source) for r in rows}
        pins = strings(bundle['phases']['PL-B']['pinned_cells'], 'pilot pinned_cells')
        require(pins <= CELLS, 'unknown pilot provider pin')
        historical = provider_capability(rows, originals, bundle['phases']['PL-B']['author_vendor'], pins)
        if not historical['ok']:
            errors['KQ4'] = 'PL-B began without required independent reviewer or pinned provider capability'
    check('KQ6', providers_check)
    def publications_check():
        require(set(states) == CELLS, 'provider eligibility unavailable')
        eligible = {k for k, value in states.items() if value['status'] == 'usable'}
        for name in ('T40c', 'T54i', 'T40d'):
            pub = bundle['publications'][name]
            require(strings(pub['cells'], name) == eligible, f'{name}: published subset differs from eligible cells')
            require(strings(pub['missing'], f'{name}.missing') == CELLS - eligible, f'{name}: missing-cell label wrong')
            require(pub.get('label') == ('full' if eligible == CELLS else 'partial'), f'{name}: P1.0 label wrong')
    check('KQ7', publications_check)
    result.update(identity(target))
    result.update({'decision': 'refused' if errors else 'pass', 'conditions': {f'KQ{i}': f'KQ{i}' not in errors for i in range(1, 8)},
                   'reasons': [{'code': k, 'detail': errors[k]} for k in sorted(errors)], 'provider_states': states,
                   'comparison': {k: v for k, v in computed.items() if k != 'items'},
                   'simulated_receipts_used': ev.fixture,
                   'proves': 'gate rules only; no real pilot claim' if ev.fixture else 'supplied evidence qualifies for submission; not owner acceptance'})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle')
    parser.add_argument('--allow-simulated', action='store_true')
    args = parser.parse_args(argv)
    path = Path(args.bundle)
    try:
        result = decide(json.loads(path.read_text(encoding='utf-8')), path.parent, args.allow_simulated)
    except (OSError, ValueError) as exc:
        result = {'gate': 'CG-KET', 'decision': 'refused', 'reasons': [{'code': 'INPUT', 'detail': str(exc)}]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['decision'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
