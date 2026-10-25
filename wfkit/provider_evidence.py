"""Shared PV1/HL provider evidence validation, extracted from finalgate KQ6.

This checks six recorded cells and their CLI identity. Capability requirements
(independent reviewer, pins, nonempty subset) remain the caller's gate rules.
No providers are invoked; fixture evidence remains explicitly simulated.
"""
import hashlib
import json
import re
from wfkit.finalgate import CELLS, evidence_status, identity, require


def evaluate(rows, items, evidence, source, target, comparison=None):
    states = {}
    require(isinstance(rows, list) and len(rows) == 6 and {r['id'] for r in rows} == CELLS, 'six-cell provider matrix missing')
    for row in rows:
        key = row['id']
        require(key == f"{row['provider']}:{row['role']}" and all(isinstance(row.get(k), str) and row[k].strip() for k in ('model', 'vendor')), 'provider identity/model vendor missing')
        item = items
        item = next(r for r in item if r['id'] == key)
        original, attempts = evidence.read(item['original']), [evidence.read(r) for r in item['supplements']]
        for rec in [original] + attempts:
            require(rec.get('item') == key and all(rec.get(k) == row[k] for k in ('provider', 'role', 'model', 'vendor')), f'{key}: receipt provider/model mismatch')
            if rec.get('result') == 'pass':
                cli = rec.get('cli_identity', {})
                require(isinstance(cli, dict) and not cli.get('identity_errors'), f'{key}: CLI identity unavailable')
                require(isinstance(row.get('cli_sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', row['cli_sha256']), f'{key}: pinned CLI hash missing')
                require(cli.get('provider') == row['provider'] and cli.get('sha256') == row['cli_sha256'], f'{key}: CLI hash/provider mismatch')
                require(cli.get('path') and isinstance(cli.get('argv'), list) and cli['argv'] and cli['argv'][0] == cli['path'], f'{key}: CLI executable/argv mismatch')
                require(isinstance(cli.get('files'), dict) and cli['files'].get(cli['path']) == cli['sha256'] and all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v) for v in cli['files'].values()), f'{key}: CLI file hashes incomplete')
                require(isinstance(row.get('cli_files'), dict) and cli['files'] == row['cli_files'], f'{key}: CLI prefix-file hashes differ from pin')
                require(isinstance(cli.get('version'), str) and cli['version'].strip() and not cli['version'].startswith('unavailable:'), f'{key}: CLI version unavailable')
        require(identity(original) == identity(source),
                f"{key}: original hash changed: evidence not valid for the delivered build (receipt {identity(original).get('wheel_sha256')}, "
                f"matrix build {identity(source).get('wheel_sha256')}; no valid inheritance comparison)")
        require(all(identity(r) == identity(target) for r in attempts), f'{key}: rerun on wrong artifact')
        states[key] = evidence_status(original, attempts, target, comparison, key)
        require(row['status'] == states[key]['status'], f'{key}: reported status differs from evidence')
    return states


# T40c [E29]/[E30]: the words of each status for the delivered build, and the one rendering of the six cells used by the RP notes
# receipt and the matrix file delivered with it (release_bundle) and re-checked by release_check.
STATUS_WORDS = {'usable': 'dùng được', 'recheck': 'cần kiểm lại', 'unverified': 'chưa kiểm chứng', 'failed': 'không đạt'}


def render(states):
    """One line per cell: a usable cell with its validity and origin hash, any other cell with its status and reason."""
    lines = []
    for key in sorted(states):
        state = states[key]
        if state['status'] == 'usable':
            how = state['validity'] + (' qua đối chiếu ' + state['comparison_id'] if state.get('comparison_id') else '')
            lines.append(f"- {key}: dùng được ({how}; hash gốc {state['evidence']['wheel_sha256']}, commit {state['evidence']['commit']})")
        else:
            require(isinstance(state.get('reason'), str) and state['reason'].strip(), f'{key}: a cell that is not usable must carry its status and reason')
            lines.append(f"- {key}: chưa dùng được: {state['reason']} ({STATUS_WORDS.get(state['status'], state['status'])}, {state['status']})")
    return lines


# T40c [E30] (round 8 H): "decisions của hợp đồng trước/sau: không đổi". The program contract's provider/model decision for each cell is the
# pin the W45 matrix ran with (matrix rows; every receipt names where those pins come from in `pins_source`; while the program contract is
# not approved that is the program kit). One record = the five decision fields of each cell + that provenance + the sha256 of their canonical
# JSON. release_bundle takes it before the subset is computed and again after the provider verdict; release_check re-derives it from the
# delivered rows and refuses any difference, naming the cell.
DECISION_FIELDS = ('provider', 'role', 'model', 'vendor')
DECISION_CHANGED = 'quyết định hợp đồng trước/sau đã đổi'


def _decision_hash(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def decisions(rows, pins_source):
    """The [E30] decision record of the provider rows (provider, role, model, vendor per cell) with the provenance of their pins."""
    require(isinstance(pins_source, str) and pins_source.strip(), 'E30 evidence missing: the provenance of the provider/model pins (pins_source)')
    require(isinstance(rows, list) and rows and all(isinstance(r, dict) and isinstance(r.get('id'), str) for r in rows), 'E30 evidence missing: provider rows')
    body = {'pins_source': pins_source,
            'decisions': sorted(({'cell': r['id'], **{k: r.get(k) for k in DECISION_FIELDS}} for r in rows), key=lambda d: d['cell'])}
    return {**body, 'sha256': _decision_hash(body)}


def verify_decisions(record, label):
    """The record is well formed and its hash is the hash of its content."""
    require(isinstance(record, dict) and set(record) == {'pins_source', 'decisions', 'sha256'} and isinstance(record['decisions'], list),
            f'E30 evidence missing: the {label} decision record is incomplete')
    require(record['sha256'] == _decision_hash({'pins_source': record['pins_source'], 'decisions': record['decisions']}),
            f'E30 decision record ({label}): sha256 hash does not match its content')
    require(sorted(d.get('cell') for d in record['decisions'] if isinstance(d, dict)) == sorted(CELLS) == [d['cell'] for d in record['decisions']],
            f'E30 decision record ({label}): not the six cells')
    return record


def decision_changes(before, after):
    """Each cell whose decision differs, with the field and both values; a different pin provenance too."""
    one, two = ({d['cell']: d for d in r['decisions']} for r in (before, after))
    changes = [f"{key} {field} {one[key].get(field)!r} -> {two[key].get(field)!r}" for key in sorted(set(one) & set(two))
               for field in DECISION_FIELDS if one[key].get(field) != two[key].get(field)]
    changes += [f'{key} only on one side' for key in sorted(set(one) ^ set(two))]
    if before['pins_source'] != after['pins_source']:
        changes.append(f"pins_source {before['pins_source']!r} -> {after['pins_source']!r}")
    return changes


def decisions_line(record):
    """The RP notes line of an unchanged record (the hash and the provenance of the pins)."""
    return f"- quyết định hợp đồng trước/sau: không đổi (sha256 {record['sha256']}; nguồn pin: {record['pins_source']})"
