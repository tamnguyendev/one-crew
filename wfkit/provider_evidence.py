"""Shared PV1/HL provider evidence validation, extracted from finalgate KQ6.

This checks six recorded cells and their CLI identity. Capability requirements
(independent reviewer, pins, nonempty subset) remain the caller's gate rules.
No providers are invoked; fixture evidence remains explicitly simulated.
"""
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
