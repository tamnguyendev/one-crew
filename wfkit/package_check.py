"""Verify a handover package FROM THE ARTIFACT, and judge the result from the recorded facts (Codex review P1).

Two halves:

  judge(report)  pure. Recomputes the overall result from the MANDATORY steps only. It never trusts the report's own `result`: a report that
                 claims `pass` while a mandatory step is ok=false (or a rollback fact is wrong) is REFUSED as incoherent. A deliberate negative
                 test is modelled as an expectation (exit codes + the reason text it must show); failing for a DIFFERENT reason (encoding
                 error, missing exe, traceback) is a failure, never a pass.
                 P1-1: the ORACLE is this module's, never the report's. Which steps are mandatory (BASE_REQUIRED/ROLLBACK_REQUIRED), what
                 each step's `ok` means in terms of its recorded facts (_POSITIVE) and every negative expectation (NEGATIVE_EXPECT) are
                 fixed here; each mandatory `ok` is recomputed from the facts and a report that demotes, duplicates, re-specifies or
                 contradicts them is refused.
                 P1-3 (round 6): the SCOPE of mandatory steps is the package's, never the report's. `judge(report, scope)` takes the scope
                 `package_scope(pkg)` derives from the manifest + the on-disk artifact (manifest kind -> PACKAGE_KINDS; a rollback kind needs
                 manifest.previous_wheel whose file is present with the pinned sha256 -> ROLLBACK_REQUIRED mandatory; the first-release kind
                 declares no previous wheel -> BASE scope only). The report's `previous_wheel_present` is an observation that must AGREE; the
                 report's `package_identity` (package path, kind, manifest/wheel/previous-wheel sha256, verifier file hashes) must equal the
                 scope's; rollback steps or facts under a BASE scope are a contradiction. Any disagreement or an unverifiable manifest is refused.
  run(pkg, work) the runner: clean venv outside the checkout, wheel installed after a hash check, one code root through the venv console
                 script, every onecrew module loaded from the venv, then the rollback drill on TWO ledger copies: `state-blocked` (the scan
                 reports a block, so rollback must be REFUSED with zero pip install/uninstall) and `state-clear` (0 blocks, rollback allowed,
                 old build reads, roll-forward restores the same installed build).

Every child runs with a UTF-8 environment; stdout/stderr tails are recorded; an unexpected nonzero exit or a traceback in any step fails the check.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parents[1]

# Markers that are never an acceptable outcome of any child (a negative test must not "pass" by crashing).
FORBIDDEN_MARKERS = ('UnicodeEncodeError', 'UnicodeDecodeError', 'Traceback (most recent call last)', "codec can't encode", "codec can't decode")
TAIL_KEYS = ('tail', 'stdout_tail', 'stderr_tail')

BASE_REQUIRED = ('sha256sums', 'wheel_sha', 'venv', 'pip_install', 'help', 'smoke_body', 'verdict_run', 'plan_report', 'modules_from_venv',
                 'checkout_not_on_path')
ROLLBACK_REQUIRED = ('blocked_copy_built', 'blocked_scan', 'blocked_refused_no_pip', 'blocked_installed_unchanged', 'blocked_copy_unchanged',
                     'clear_scan', 'clear_uninstall_current', 'clear_install_previous', 'clear_old_digest', 'clear_old_cannot_read_plan_ns',
                     'clear_old_copy_unchanged', 'clear_uninstall_previous', 'clear_reinstall_current', 'clear_same_build_restored',
                     'clear_roll_forward_reads', 'clear_roll_forward_copy_unchanged')

# Which previous build can read a `plan-ns:` root is a property of THAT build, not an assumption (round 10). Defined here, once: the first
# 2.2.0 dev version whose reader lists/shows namespaced roots is dev4. The dev3 wheel the earlier packages carried is the compat baseline
# (d3120c6, "NOT a delivered build") and predates namespaces; dev8 and later read them. The version comes from the previous wheel's file name
# in the manifest; the scope records the derived capability (identity key `previous_reads_plan_ns`), so the judge binds to the manifest.
PLAN_NS_FIRST_READER = ((2, 2, 0), 4)            # (release tuple, first dev number); a final release of that tuple or later also reads them
STEP_PREVIOUS_CANNOT_READ = 'clear_old_cannot_read_plan_ns'      # previous build predates namespaces: the root is invisible to it (negative)
STEP_PREVIOUS_READS = 'clear_old_reads_plan_ns'                  # previous build has namespaces: it reads the root (positive)
ROLLBACK_REQUIRED_NS = tuple(STEP_PREVIOUS_READS if i == STEP_PREVIOUS_CANNOT_READ else i for i in ROLLBACK_REQUIRED)
_ROLLBACK_ANY = tuple(dict.fromkeys(ROLLBACK_REQUIRED + ROLLBACK_REQUIRED_NS))
_WHEEL_VERSION = re.compile(r'^onecrew-(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?-')


def previous_reads_plan_ns(wheel_file):
    """-> True/False: does the build in this wheel file read `plan-ns:` roots? None when the version cannot be read from the file name."""
    m = _WHEEL_VERSION.match(Path(str(wheel_file or '')).name)
    if not m:
        return None
    rel, dev = (int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4)
    first_rel, first_dev = PLAN_NS_FIRST_READER
    if rel != first_rel:
        return rel > first_rel
    return dev is None or int(dev) >= first_dev


def wheel_metadata_version(wheel_path):
    """-> the `Version:` the wheel's own METADATA declares, or None when the file is not a readable wheel (round 11: the previous build's
    capability comes from what the pinned wheel IS, not only from what its file name says)."""
    try:
        with zipfile.ZipFile(wheel_path) as z:
            name = next((n for n in z.namelist() if n.count('/') == 1 and n.endswith('.dist-info/METADATA')), None)
            if name is None:
                return None
            for line in z.read(name).decode('utf-8', 'replace').splitlines():
                if line.startswith('Version:'):
                    return line.split(':', 1)[1].strip() or None
                if not line.strip():
                    break
    except (OSError, zipfile.BadZipFile, KeyError):
        pass
    return None


def commit_matches(a, b):
    """Two commit ids name the same commit: both hex, at least 7 characters, one a prefix of the other (short sha vs full sha)."""
    ok = lambda x: isinstance(x, str) and len(x) >= 7 and re.fullmatch(r'[0-9a-f]+', x) is not None
    return ok(a) and ok(b) and (a.startswith(b) or b.startswith(a))


def _json_file(path):
    try:
        v = json.loads(Path(path).read_text(encoding='utf-8'))
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _read_json_strict(path):
    """-> (object, None) or (None, why): unreadable, not UTF-8, invalid JSON or a non-object are all reported, never skipped."""
    try:
        v = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        return None, f'unreadable or invalid JSON ({type(e).__name__}: {e})'
    return (v, None) if isinstance(v, dict) else (None, 'not a JSON object')


def required_receipt_names(decision, registry):
    """-> ({receipt file name: installed?} | None, source). The receipts the GATE itself expected, strongest source first (round 12 P2-D):
    1. the registry snapshot (development-testcases.json) x decision.releases: every check of every judged release -> '<release>-<key>.json'; trusted only
       when its size equals decision.implementation_checks.expected (a partial `only` run, or a registry that is not the gate's, is not trusted);
    2. otherwise None: the receipts directory listing is the set, and its size must equal decision.implementation_checks.receipted."""
    checks = decision.get('implementation_checks') if isinstance(decision, dict) else None
    releases = decision.get('releases') if isinstance(decision, dict) else None
    rel_doc = registry.get('releases') if isinstance(registry, dict) else None
    fallback = (None, 'receipts directory listing')
    if not (isinstance(checks, dict) and isinstance(releases, list) and releases and isinstance(rel_doc, dict)):
        return fallback
    names = {}
    for r in releases:
        body = rel_doc.get(r)
        tcs = body.get('testcases') if isinstance(body, dict) else None
        if not isinstance(tcs, dict):
            return fallback
        for key, entry in tcs.items():
            if isinstance(entry, dict) and entry.get('modules'):
                names[(r + '/' + key).replace('/', '-') + '.json'] = bool(entry.get('installed'))
    if len(names) != checks.get('expected'):
        return fallback
    return names, 'registry snapshot x decision.releases'


def receipt_problems(rdir, commit, wsha, decision=None, registry=None, label='gate/receipts'):
    """-> [reason, ...]. EVERY gate receipt must carry the commit AND the wheel sha256 of the build (manifest / gate build.json): the receipt never
    picks its own identity. A receipt that is unreadable, invalid JSON, not an object, or lacks `commit` / `wheel_sha256` is refused (never skipped);
    `wheel_used`, when present, must be a list naming only that wheel. The required set is the gate's own expectation (required_receipt_names): a
    missing one is refused, and a receipt on disk outside it is refused too. A correct checksum elsewhere proves bytes only, never that these agree."""
    rdir = Path(rdir)
    out = []
    names, source = required_receipt_names(decision, registry)
    on_disk = sorted(f.name for f in rdir.glob('*.json')) if rdir.is_dir() else []
    checks = decision.get('implementation_checks') if isinstance(decision, dict) else None
    if names is not None:
        for n in sorted(set(names) - set(on_disk)):
            out.append(f'{label}/{n}: required by the gate ({source}) but missing')
        for n in sorted(set(on_disk) - set(names)):
            out.append(f'{label}/{n}: not an expected check of this gate ({source}): a receipt from another run?')
    elif isinstance(checks, dict):
        if isinstance(checks.get('receipted'), int) and not isinstance(checks.get('receipted'), bool) and checks['receipted'] != len(on_disk):
            out.append(f'{label}: the gate decision says {checks["receipted"]} receipts, the directory holds {len(on_disk)}')
    for n in on_disk:
        r, why = _read_json_strict(rdir / n)
        if r is None:
            out.append(f'{label}/{n}: {why}')
            continue
        if not isinstance(r.get('commit'), str):
            out.append(f'{label}/{n}: receipt has no commit')
        elif not commit_matches(r['commit'], commit):
            out.append(f'{label}/{n}: receipt commit {r["commit"]!r} is not the build commit {commit!r}')
        if not isinstance(r.get('wheel_sha256'), str):
            out.append(f'{label}/{n}: receipt has no wheel_sha256')
        elif r['wheel_sha256'] != wsha:
            out.append(f'{label}/{n}: receipt wheel sha256 {r["wheel_sha256"]!r} ≠ manifest/build wheel {wsha!r}')
        installed = bool(names and names.get(n))
        if 'wheel_used' in r:
            used = r['wheel_used']
            if not isinstance(used, list) or any(u != wsha for u in used):
                out.append(f'{label}/{n}: receipt wheel_used {used!r} is not (only) the build wheel {wsha!r}')
            elif installed and not used:
                out.append(f'{label}/{n}: installed check recorded no consumed wheel')
        elif installed:
            out.append(f'{label}/{n}: installed check has no wheel_used')
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# Round 13 P2-B: the evidence chain INSIDE a bundle. A correct SHA256SUMS proves bytes only; the receipts a bundle certifies its result with
# (bundles/<R>/receipts/*.json) must name the right build by their ROLE.
#
# Required set (strongest source first): bundle.json `checks` = {installed, upgrade, events, rollback, notes} -> {path, sha256}, the bundle's
# own declaration, which release_check.decide reads the same way. Every declared file must exist, hash to the declared sha256 and be a JSON
# object; the receipts those name by hash are followed too (rollback.allowed.old_run / forward_run, notes.real_checks, bundle.json
# gate_history, comparison.items[*].original). A receipt on disk that no declaration reaches is refused for a produced bundle. Every
# reference is judged on its own against the file's bytes (round 13b): two references to one file with different sha256 can never
# both hold, and the one that does not match is named; a malformed reference is refused for a produced bundle, never skipped.
# Roles (the receipt writer, wfkit/release_bundle.Producer.receipt(artifact=...), fixes them):
#   current  : installed (+ scenarios[*], adapter_runs[*]), upgrade (+ `to`), events, rollback, notes (+ gate_decision), rollback-forward-run
#   previous : rollback-old-run (rollback.allowed.old_run), upgrade.from, events.old_artifact, rollback.{allowed,rejected}.scan.old_version (commit)
# `current` = the package's manifest commit/wheel; `previous` = bundle.json artifacts.previous, which is itself pinned: bundle.first_release.baseline
# == release-check.first_release_baseline == manifest.bundles[R].first_release_baseline, or, for a bundle that is not a first release, the
# manifest.previous_wheel of the package. Nested identity-looking fields outside this table (e.g. provider-matrix cells of RP, which keep the
# identity of the build they ran on) are not judged here. A bundle refused by its producer (produced:false) keeps whatever receipts it has:
# they are read and judged by role where they exist; nothing is required of them, and with no bundle.json the previous-role statements
# must at least agree with each other.
_BUNDLE_CHECKS = ('installed', 'upgrade', 'events', 'rollback', 'notes')
_NAME_ROLE = {'installed': 'current', 'upgrade': 'current', 'events': 'current', 'rollback': 'current', 'notes': 'current',
              'rollback-old-run': 'previous', 'rollback-forward-run': 'current'}
_HEX64 = re.compile(r'[0-9a-f]{64}')


def _is_ref(x):
    return isinstance(x, dict) and isinstance(x.get('path'), str) and isinstance(x.get('sha256'), str) and bool(_HEX64.fullmatch(x['sha256']))


def _same_build(a, b):
    """a, b = {'commit','wheel_sha256'} dicts of the same build (commit by the prefix rule, wheel exactly)."""
    return (isinstance(a, dict) and isinstance(b, dict) and commit_matches(a.get('commit'), b.get('commit'))
            and isinstance(a.get('wheel_sha256'), str) and a.get('wheel_sha256') == b.get('wheel_sha256'))


def bundle_receipt_problems(bdir, rel, commit, wsha, produced=True, previous_wheel=None, baseline=None, label=None):
    """-> [reason, ...]: the evidence chain of ONE bundle directory (shipped bundles/<R>/ or the producer's output dir before the build).

    commit/wsha = the build the package is made of; produced = not refused by the producer; previous_wheel = manifest.previous_wheel (or the
    provenance about to be written) for a bundle that is not a first release; baseline = manifest.bundles[R].first_release_baseline."""
    bdir = Path(bdir)
    label = label or f'bundles/{rel}'
    out = []
    cur = {'commit': commit, 'wheel_sha256': wsha}
    bj = None
    if (bdir / 'bundle.json').exists():
        bj, why = _read_json_strict(bdir / 'bundle.json')
        if bj is None:
            out.append(f'{label}/bundle.json: {why}')
    elif produced:
        out.append(f'{label}/bundle.json is missing although the bundle is produced: its receipts have no declaration to be judged by')
    prev = None                                    # the previous build, pinned: {'commit','wheel_sha256'}; None = unpinned
    if bj is not None:
        arts = bj.get('artifacts') if isinstance(bj.get('artifacts'), dict) else {}
        bcur = arts.get('current')
        if not isinstance(bcur, dict):
            out.append(f'{label}/bundle.json names no artifacts.current build')
        else:
            for k, name in (('commit', 'commit'), ('wheel_sha256', 'wheel sha256')):
                v = bcur.get(k)
                good = commit_matches(v, commit) if k == 'commit' else (isinstance(v, str) and isinstance(wsha, str) and v == wsha)
                if not good:
                    out.append(f'package mixes builds: {label}/bundle.json artifacts.current {k} is {v!r}, the manifest {name} is {commit if k == "commit" else wsha!r}')
        bprev = arts.get('previous')
        if not (isinstance(bprev, dict) and isinstance(bprev.get('commit'), str) and isinstance(bprev.get('wheel_sha256'), str)):
            out.append(f'{label}/bundle.json names no usable artifacts.previous build (commit + wheel_sha256)')
        else:
            prev = {'commit': bprev['commit'], 'wheel_sha256': bprev['wheel_sha256']}
            pins = []                              # every other statement of the previous build that pins it
            if 'first_release' in bj:
                claim = bj['first_release']
                pins.append((f'{label}/bundle.json first_release.baseline', claim.get('baseline') if isinstance(claim, dict) else None))
                rc = _json_file(bdir / 'release-check.json')
                if rc is not None and isinstance(rc.get('first_release_baseline'), dict):
                    pins.append((f'{label}/release-check.json first_release_baseline', rc.get('first_release_baseline')))
                if baseline is not None:
                    pins.append((f'manifest.bundles[{rel}].first_release_baseline', baseline))
            elif isinstance(previous_wheel, dict):
                pc = previous_wheel.get('commit')          # a manifest that does not know the previous commit (or writes prose) is matched by the wheel alone
                pins.append(('manifest.previous_wheel', {'commit': pc if isinstance(pc, str) and re.fullmatch(r'[0-9a-f]{7,}', pc) else prev['commit'],
                                                         'wheel_sha256': previous_wheel.get('sha256')}))
            for what, pin in pins:
                if not _same_build(prev, pin):
                    out.append(f'{label}/bundle.json artifacts.previous ({prev["commit"][:12]}, {prev["wheel_sha256"][:12]}) is not the previous build pinned by {what} ({pin!r})')
    roles = {}                                     # path relative to bdir (posix) -> role of the file
    declared = {}                                  # path -> check name
    refs = []                                      # (path, expected sha256, where it was named)

    def add_ref(ref, where, role, name=None):
        if not _is_ref(ref):
            out.append(f'{label}/bundle.json {where} is not {{path, sha256}}: {ref!r}')
            return
        p = Path(ref['path'])
        if p.is_absolute() or '..' in p.parts:
            out.append(f'{label}/bundle.json {where} points outside the bundle: {ref["path"]}')
            return
        refs.append((p.as_posix(), ref['sha256'], f'{label}/bundle.json {where}'))
        if role:
            roles.setdefault(p.as_posix(), role)
        if name:
            declared.setdefault(p.as_posix(), name)

    if bj is not None:
        checks = bj.get('checks')
        if not isinstance(checks, dict):
            out.append(f'{label}/bundle.json declares no checks ({", ".join(_BUNDLE_CHECKS)})')
            checks = {}
        for name in _BUNDLE_CHECKS:
            if name in checks:
                add_ref(checks[name], f'checks.{name}', 'current', name)
            elif produced:
                out.append(f'{label}/bundle.json declares no {name} receipt')
        for name in sorted(set(checks) - set(_BUNDLE_CHECKS)):
            add_ref(checks[name], f'checks.{name}', None)
        for i, ref in enumerate(bj.get('gate_history') or []):
            add_ref(ref, f'gate_history[{i}]', None)
        comp = bj.get('comparison')
        for i, item in enumerate((comp.get('items') or []) if isinstance(comp, dict) else []):
            if isinstance(item, dict):
                add_ref(item.get('original'), f'comparison.items[{i}].original', None)
        for i, d in enumerate(bj.get('deliveries') or []):
            if isinstance(d, dict):
                for k, n in (('commit', 'commit'), ('wheel_sha256', 'wheel sha256')):
                    v = d.get(k)
                    if not (commit_matches(v, commit) if k == 'commit' else (isinstance(v, str) and v == wsha)):
                        out.append(f'{label}/bundle.json deliveries[{i}] {n} is {v!r}, the manifest {n} is {commit if k == "commit" else wsha!r}')
    bodies = {}
    hashes = {}                                    # path -> sha256 of the bytes on disk (None = missing); computed once per file

    def load(path, want_sha, where):
        # Round 13b: the file is read once, but EVERY reference to it is judged against its bytes. Memoising the verdict by path let a
        # second reference to the same file with another sha256 (notes.real_checks, gate_history, comparison, checks.<extra>, rollback
        # forward_run/old_run) pass unexamined, so a chain whose statements contradict each other looked consistent (Codex, 27/10).
        full = bdir / path
        if path not in bodies:
            body = None
            if full.is_file():
                hashes[path] = sha(full)
                body, why = _read_json_strict(full)
                if body is None:
                    out.append(f'{label}/{path}: {why}')
            else:
                hashes[path] = None
            bodies[path] = body
        if hashes[path] is None:
            if produced or want_sha:
                out.append(f'{label}/{path}: named by {where} but missing')
        elif want_sha and hashes[path] != want_sha:
            out.append(f'{label}/{path}: bytes do not match the sha256 that {where} references ({want_sha[:12]}…)')
        return bodies[path]

    for path, want_sha, where in list(refs):       # follow the references a declared receipt itself makes by hash
        body = load(path, want_sha, where)
        if body is None:
            continue
        if declared.get(path) == 'rollback':
            allowed = body.get('allowed') if isinstance(body.get('allowed'), dict) else {}
            for key, ref, role in (('allowed.old_run', allowed.get('old_run'), 'previous'), ('forward_run', body.get('forward_run'), 'current')):
                p = Path(ref['path']) if _is_ref(ref) else None
                if p is None:
                    if produced:
                        out.append(f'{label}/{path}: {key} is not {{path, sha256}}: {ref!r}')
                elif p.is_absolute() or '..' in p.parts:
                    out.append(f'{label}/{path}: {key} points outside the bundle: {ref["path"]}')
                else:
                    roles.setdefault(p.as_posix(), role)
                    load(p.as_posix(), ref['sha256'], f'{label}/{path} {key}')
        elif declared.get(path) == 'notes' and isinstance(body.get('real_checks'), list):
            for i, ref in enumerate(body['real_checks']):
                where = f'{label}/{path} real_checks[{i}]'
                if not _is_ref(ref):               # round 13b: a reference that cannot be checked is refused, not skipped
                    if produced:
                        out.append(f'{where} is not {{path, sha256}}: {ref!r}')
                    continue
                p = Path(ref['path'])
                if p.is_absolute() or '..' in p.parts:
                    out.append(f'{where} points outside the bundle: {ref["path"]}')
                    continue
                load(p.as_posix(), ref['sha256'], where)
    rdir = bdir / 'receipts'
    for f in sorted(rdir.glob('*.json')) if rdir.is_dir() else []:
        path = f.relative_to(bdir).as_posix()
        if path not in bodies:
            if produced and bj is not None:
                out.append(f'{label}/{path}: not declared by bundle.json (checks and the receipts they reference): a receipt from another run?')
            load(path, None, 'the receipts directory')
            if _NAME_ROLE.get(f.stem):
                roles.setdefault(path, _NAME_ROLE[f.stem])
    prev_seen = []

    def judge_id(path, obj, role, what=''):
        where = f'{label}/{path}' + (f' {what}' if what else '')
        c, s = (obj.get('commit'), obj.get('wheel_sha256')) if isinstance(obj, dict) else (None, None)
        if not isinstance(obj, dict):
            out.append(f'{where}: not an object, cannot carry the {role} build identity')
            return
        if not isinstance(c, str):
            out.append(f'{where}: no commit')
        if not isinstance(s, str):
            out.append(f'{where}: no wheel_sha256')
        if not (isinstance(c, str) and isinstance(s, str)):
            return
        want = cur if role == 'current' else prev
        if want is None:
            prev_seen.append((where, c, s))
            return
        src = 'the manifest' if role == 'current' else 'bundle.json artifacts.previous'
        if not commit_matches(c, want['commit']):
            out.append(f'{where}: commit {c!r} is not the {role} build commit {want["commit"]!r} ({src})')
        if s != want['wheel_sha256']:
            out.append(f'{where}: wheel sha256 {s!r} ≠ the {role} build wheel {want["wheel_sha256"]!r} ({src})')

    for path, body in sorted(bodies.items()):
        role = roles.get(path)
        if not isinstance(body, dict) or role is None:
            continue                               # unreadable (already reported) or no role (history / matrix evidence): hash + readability only
        if isinstance(body.get('release'), str) and body['release'] != rel:
            out.append(f'{label}/{path}: receipt belongs to release {body["release"]!r}, not {rel!r}')
        name = declared.get(path) or (Path(path).stem if Path(path).stem in _BUNDLE_CHECKS and path == f'receipts/{Path(path).stem}.json' else None)
        if name and isinstance(body.get('kind'), str) and body['kind'] != name:
            out.append(f'{label}/{path}: receipt kind {body["kind"]!r} is not the declared {name!r}')
        judge_id(path, body, role)
        if name == 'installed':
            for key in ('scenarios', 'adapter_runs'):
                for i, row in enumerate(body[key] if isinstance(body.get(key), list) else []):
                    judge_id(path, row, 'current', f'{key}[{i}]')
        elif name == 'upgrade':
            judge_id(path, body.get('from'), 'previous', 'from')
            judge_id(path, body.get('to'), 'current', 'to')
        elif name == 'events':
            judge_id(path, body.get('old_artifact'), 'previous', 'old_artifact')
        elif name == 'rollback':
            for br in ('rejected', 'allowed'):
                scan = body[br].get('scan') if isinstance(body.get(br), dict) else None
                v = scan.get('old_version') if isinstance(scan, dict) else None
                if prev is not None and isinstance(v, str) and not commit_matches(v, prev['commit']):
                    out.append(f'{label}/{path} {br}.scan.old_version: {v!r} is not the previous build commit {prev["commit"]!r} (bundle.json artifacts.previous)')
        elif name == 'notes' and isinstance(body.get('gate_decision'), dict):
            gd = body['gate_decision']
            if 'commit' in gd or 'wheel_sha256' in gd:
                judge_id(path, gd, 'current', 'gate_decision')
            if isinstance(gd.get('snapshot'), dict) and 'commit' in gd['snapshot'] and not commit_matches(gd['snapshot']['commit'], commit):
                out.append(f'{label}/{path} gate_decision.snapshot: commit {gd["snapshot"]["commit"]!r} is not the current build commit {commit!r} (the manifest)')
    if prev is None and len({(c, s) for _, c, s in prev_seen}) > 1:      # no pin: the previous-build statements must at least agree
        out.append(f'{label}: the previous-build statements of its receipts contradict each other: ' + '; '.join(f'{w} {c[:12]}/{s[:12]}' for w, c, s in prev_seen))
    return out


def identity_problems(pkg, manifest):
    """-> [reason, ...]: everything in the package that names a commit or a wheel digest must agree with manifest.commit / manifest.wheel
    (round 11 D: a package assembled from a later snapshot's audit table, another build's bundles or another commit's receipts is mixed).
    Checked when present: tasks_92_commit, docs/audit-92.json, docs/AUDIT-92.md, gate/gate-build.json, gate/snapshot.json, gate/receipts/*.json,
    manifest.bundles[*], bundles/<R>/release-check.json (commit + wheel sha256 + decision) and, round 13 P2-B, bundles/<R>/bundle.json with every receipt
    under bundles/<R>/receipts/ (bundle_receipt_problems: judged by role against the current or the pinned previous build). A package with nothing comparable has no problems."""
    pkg = Path(pkg)
    out = []
    commit = manifest.get('commit')
    wheel = manifest.get('wheel')
    wsha = wheel.get('sha256') if isinstance(wheel, dict) else None
    seen = []                     # (label, kind, value) every statement found in the package
    if 'tasks_92_commit' in manifest:
        seen.append(('manifest.tasks_92_commit', 'commit', manifest.get('tasks_92_commit')))
    audit = _json_file(pkg / 'docs' / 'audit-92.json')
    if audit is not None:
        seen.append(('docs/audit-92.json commit', 'commit', audit.get('commit')))
    md = pkg / 'docs' / 'AUDIT-92.md'
    if md.is_file():
        m = re.search(r'Commit kiểm: `([^`]*)`', md.read_text(encoding='utf-8', errors='replace'))
        seen.append(('docs/AUDIT-92.md "Commit kiểm"', 'commit', m.group(1) if m else None))
    gb = _json_file(pkg / 'gate' / 'gate-build.json')
    if gb is not None:
        seen.append(('gate/gate-build.json commit', 'commit', gb.get('commit')))
        seen.append(('gate/gate-build.json wheel_sha256', 'sha', gb.get('wheel_sha256')))
    sn = _json_file(pkg / 'gate' / 'snapshot.json')
    if sn is not None and 'commit' in sn:
        seen.append(('gate/snapshot.json commit', 'commit', sn.get('commit')))
    for dn in ('decision.json', 'gate-decision.json'):
        dd = _json_file(pkg / 'gate' / dn)
        if dd is not None:
            for k, kind in (('commit', 'commit'), ('wheel_sha256', 'sha')):
                if k in dd:
                    seen.append((f'gate/{dn} {k}', kind, dd.get(k)))
    decision = _json_file(pkg / 'gate' / 'decision.json')
    registry = _json_file(pkg / 'docs' / 'development-testcases.json')
    rdir = pkg / 'gate' / 'receipts'
    if rdir.is_dir() or (decision is not None and isinstance(decision.get('implementation_checks'), dict)):
        out.extend(receipt_problems(rdir, commit, wsha, decision, registry))           # round 12 P2-D: commit AND wheel of every receipt, none skipped
    bundles = manifest.get('bundles')
    for rel, ent in sorted(bundles.items()) if isinstance(bundles, dict) else []:
        if not isinstance(ent, dict):
            out.append(f'manifest.bundles[{rel}] is not an object')
            continue
        if ent.get('produced', True) is not False:
            if 'commit' in ent:
                seen.append((f'manifest.bundles[{rel}] commit', 'commit', ent.get('commit')))
            if 'wheel_sha256' in ent:
                seen.append((f'manifest.bundles[{rel}] wheel_sha256', 'sha', ent.get('wheel_sha256')))
        bdir = pkg / 'bundles' / rel
        res = _json_file(bdir / 'bundle-result.json')
        if res is not None and (('decision' in ent and res.get('decision') != ent.get('decision'))
                                or ('produced' in res and (res.get('produced') is not False) != (ent.get('produced', True) is not False))):
            out.append(f'bundle {rel}: manifest says decision {ent.get("decision")!r} produced={ent.get("produced")!r}, '
                       f'bundles/{rel}/bundle-result.json says {res.get("decision")!r} produced={res.get("produced")!r}')
        if ent.get('produced', True) is not False:
            for k in ('commit', 'wheel_sha256'):
                if not isinstance(ent.get(k), str):
                    out.append(f'manifest.bundles[{rel}] has no {k}')
        if bdir.is_dir():                       # round 13 P2-B: bundle.json + every receipt the bundle certifies its result with, by role
            out.extend(bundle_receipt_problems(bdir, rel, commit, wsha, produced=ent.get('produced', True) is not False,
                                               previous_wheel=manifest.get('previous_wheel'), baseline=ent.get('first_release_baseline'), label=f'bundles/{rel}'))
        disk = _json_file(bdir / 'release-check.json')
        if disk is None and (bdir / 'release-check.json').is_file():
            out.append(f'bundles/{rel}/release-check.json is unreadable or not a JSON object')
        elif disk is None and ent.get('produced', True) is not False and bdir.is_dir():
            out.append(f'bundle {rel} is produced in the manifest but bundles/{rel}/release-check.json is missing')
        if disk is not None:
            seen.append((f'bundles/{rel}/release-check.json commit', 'commit', disk.get('commit')))
            seen.append((f'bundles/{rel}/release-check.json wheel_sha256', 'sha', disk.get('wheel_sha256')))
            if 'decision' in ent and disk.get('decision') != ent.get('decision'):
                out.append(f'bundle {rel}: manifest decision {ent.get("decision")!r} differs from bundles/{rel}/release-check.json {disk.get("decision")!r}')
        elif (pkg / 'bundles').is_dir() and not (pkg / 'bundles' / rel).is_dir():
            out.append(f'bundle {rel} is in the manifest but missing from bundles/')
    for label, kind, value in seen:
        want = commit if kind == 'commit' else wsha
        good = commit_matches(value, want) if kind == 'commit' else (isinstance(value, str) and isinstance(want, str) and value == want)
        if not good:
            out.append(f'package mixes builds: {label} is {value!r}, the manifest {"commit" if kind == "commit" else "wheel sha256"} is {want!r}')
    return out


def required_steps(rollback, previous_ns=False):
    return list(BASE_REQUIRED) + ((list(ROLLBACK_REQUIRED_NS) if previous_ns else list(ROLLBACK_REQUIRED)) if rollback else [])


# Package kinds this verifier evaluates, and the scope each one declares (P1-3). The kind is written by the package builder into the manifest;
# a report flag can never choose the scope.
PACKAGE_KINDS = {
    'development-handover-package': 'rollback',        # carries the previous wheel: the rollback drill is mandatory
    'first-release-handover-package': 'base',          # first release (build_package --first-release): no earlier build exists to roll back to
}
IDENTITY_KEYS = ('package', 'kind', 'manifest_sha256', 'wheel_sha256', 'previous_wheel_sha256', 'previous_reads_plan_ns', 'verifier_files')


def _norm_path(p):
    return os.path.normcase(os.path.abspath(str(p)))


def _verified_file(pkg, entry, label, reasons):
    """-> the pinned sha256 when entry = {'file','sha256'} names a file inside pkg whose bytes hash to it; else None (+ a reason)."""
    if not isinstance(entry, dict) or not isinstance(entry.get('file'), str) or not isinstance(entry.get('sha256'), str) or not entry['sha256']:
        reasons.append(f'manifest {label} entry is not {{file, sha256}}: {entry!r}')
        return None
    rel = Path(entry['file'])
    p = pkg / rel
    if rel.is_absolute() or '..' in rel.parts:
        reasons.append(f'manifest {label} file is outside the package: {entry["file"]}')
        return None
    if not p.is_file():
        reasons.append(f'{label} file missing from the package: {entry["file"]}')
        return None
    if sha(p) != entry['sha256']:
        reasons.append(f'{label} file bytes do not match the manifest sha256: {entry["file"]}')
        return None
    return entry['sha256']


def package_scope(pkg, expected_verifier=None):
    """-> the evaluation scope, derived ONLY from <pkg>/manifest.json and the files on disk (P1-3). Never from a report.

    {'package', 'kind', 'rollback': True|False|None, 'manifest_sha256', 'wheel_sha256', 'previous_wheel_sha256', 'verifier_files', 'reasons'}.
    `reasons` non-empty == unverifiable: judge refuses. The verifier binding is required only when the manifest declares `verifier`
    (packages built before the shipped verifier, e.g. wf-handover-6366137, have none: verifier_files is then None and must be None in the
    report too). `expected_verifier` = the verify/ files a shipped launcher has already checked; the manifest must pin exactly those."""
    pkg = Path(pkg).resolve()
    reasons = []
    scope = {'package': _norm_path(pkg), 'kind': None, 'rollback': None, 'manifest_sha256': None, 'wheel_sha256': None,
             'previous_wheel_sha256': None, 'previous_reads_plan_ns': None, 'verifier_files': None, 'reasons': reasons}
    try:
        raw = (pkg / 'manifest.json').read_bytes()
        manifest = json.loads(raw.decode('utf-8'))
        if not isinstance(manifest, dict):
            raise ValueError('manifest is not a JSON object')
    except Exception as e:
        reasons.append(f'manifest missing or unreadable: {type(e).__name__}: {e}')
        return scope
    scope['manifest_sha256'] = hashlib.sha256(raw).hexdigest()
    kind = scope['kind'] = manifest.get('kind')
    mode = PACKAGE_KINDS.get(kind) if isinstance(kind, str) else None
    if mode is None:
        reasons.append(f'manifest kind {kind!r} is not a package kind this verifier evaluates ({", ".join(sorted(PACKAGE_KINDS))})')
    scope['wheel_sha256'] = _verified_file(pkg, manifest.get('wheel'), 'wheel', reasons)
    prev = manifest.get('previous_wheel')
    if mode == 'rollback':
        scope['rollback'] = True
        if not prev:
            reasons.append(f'manifest kind {kind!r} requires a previous wheel but manifest.previous_wheel is empty')
        else:
            scope['previous_wheel_sha256'] = _verified_file(pkg, prev, 'previous wheel', reasons)
            scope['previous_reads_plan_ns'] = previous_reads_plan_ns(prev.get('file') if isinstance(prev, dict) else None)
            if scope['previous_reads_plan_ns'] is None:
                reasons.append('previous wheel file name carries no readable version (onecrew-X.Y.Z[.devN]-...): its plan-ns capability is unknown')
            elif scope['previous_wheel_sha256'] is not None:
                # the branch follows what the pinned wheel IS: its METADATA version (when it is a real wheel) and the manifest's declared
                # version must both agree with the file name, otherwise the name was chosen to pick the weaker/other oracle
                meta = wheel_metadata_version(pkg / prev['file'])
                if meta is not None:
                    by_meta = previous_reads_plan_ns(f'onecrew-{meta}-x.whl')
                    if by_meta is None or by_meta != scope['previous_reads_plan_ns'] or not Path(prev['file']).name.startswith(f'onecrew-{meta}-'):
                        reasons.append(f'previous wheel METADATA version {meta} disagrees with its file name {Path(prev["file"]).name}: the plan-ns capability cannot be derived')
                        scope['previous_reads_plan_ns'] = None
                declared = prev.get('version')
                if declared is not None and not Path(prev['file']).name.startswith(f'onecrew-{declared}-'):
                    reasons.append(f'manifest previous_wheel declares version {declared} but the pinned file is {Path(prev["file"]).name}')
    elif mode == 'base':
        scope['rollback'] = False
        if prev is not None:
            reasons.append(f'manifest kind {kind!r} declares no previous wheel but manifest.previous_wheel is set (contradiction)')
    reasons.extend(identity_problems(pkg, manifest))         # round 11 D: one commit, one wheel across table / bundles / gate / receipts
    if 'verifier' in manifest:
        v = manifest['verifier']
        files = v.get('files') if isinstance(v, dict) else None
        if not isinstance(files, dict) or not files:
            reasons.append('manifest.verifier declares no files')
        else:
            for rel, want in sorted(files.items()):
                p = pkg / rel
                if not isinstance(want, str) or '..' in Path(rel).parts or Path(rel).parts[:1] != ('verify',) or not p.is_file() or sha(p) != want:
                    reasons.append(f'verifier file missing, outside verify/ or modified: {rel}')
            scope['verifier_files'] = dict(files)
    if expected_verifier is not None and scope['verifier_files'] != dict(expected_verifier):
        reasons.append('the verifier that ran is not the verifier this package manifest pins (manifest.verifier.files differ)')
    return scope


def identity(scope):
    """The package identity the runner records in its report (copied from the derived scope)."""
    return {k: json.loads(json.dumps(scope.get(k))) for k in IDENTITY_KEYS}


def check_binding(report, scope):
    """-> (reasons, rollback). Shared by every package judge: the scope must be a verified package scope, the report's recorded
    package identity must equal it, and the report's previous_wheel_present observation must agree with the manifest-derived scope."""
    if not isinstance(scope, dict) or not isinstance(scope.get('reasons'), list):
        return ['no verified package scope (manifest missing or unverifiable): judge needs package_scope(pkg)'], None
    if scope['reasons']:
        return [f'package scope unverifiable: {x}' for x in scope['reasons']], None
    rollback = scope.get('rollback')
    if not isinstance(rollback, bool):
        return ['package scope does not say whether a previous wheel is mandatory'], None
    reasons = []
    present = report.get('previous_wheel_present')
    if not isinstance(present, bool):
        reasons.append('report does not say whether the package carries a previous wheel (previous_wheel_present)')
    elif present != rollback:
        reasons.append(f'previous_wheel_present misdeclared: the report says {present}, the package manifest says {rollback}')
    rid = report.get('package_identity')
    if not isinstance(rid, dict):
        reasons.append('report records no package identity (package_identity)')
    else:
        for k in IDENTITY_KEYS:
            got, want = rid.get(k, _MISSING), scope.get(k)
            if k == 'package' and isinstance(got, str):
                got = _norm_path(got)
            if got is _MISSING or got != want:
                reasons.append(f'package identity differs from the manifest: {k} (report {"<missing>" if got is _MISSING else got!r}, manifest {want!r})')
    return reasons, rollback


def rollback_decision(blocking_total):
    """The one rule: any block in the scan refuses the rollback."""
    return 'refused' if blocking_total > 0 else 'allowed'


def _text(step):
    return '\n'.join(str(step.get(k, '')) for k in TAIL_KEYS)


# ---------------------------------------------------------------------------------------------------------------------------------
# The oracle (Codex P1-1). It belongs to the evaluator: which steps are mandatory, what each step's `ok` means in terms of its recorded
# facts, and the expectation of every negative test. The report supplies observations (exit codes, tails, facts) only; its `mandatory`,
# `expect` and `ok` are compared with the oracle and a disagreement is refused, never obeyed.

_MISSING = object()


class _Facts:
    """Reads the recorded facts of one step; remembers which are missing (a missing fact cannot be recomputed, so it is refused)."""

    def __init__(self, step, rollback, previous_ns=False):
        self.step, self.rollback, self.missing = step, rollback if isinstance(rollback, dict) else {}, []
        self.previous_ns = previous_ns

    def __call__(self, key):
        v = self.step.get(key, _MISSING)
        if v is _MISSING:
            self.missing.append(key)
            return None
        return v

    def rb(self, branch, key):
        b = self.rollback.get(branch)
        v = b.get(key, _MISSING) if isinstance(b, dict) else _MISSING
        if v is _MISSING:
            self.missing.append(f'rollback.{branch}.{key}')
            return None
        return v

    def needle(self, word):
        n = self.step.get('needles')
        if not isinstance(n, dict) or not isinstance(n.get(word), bool):
            self.missing.append(f'needles.{word}')
            return None
        return n[word]


def _exit0(f):
    return f('exit') == 0


def _total(f):
    b = f('blocking')
    return b.get('total') if isinstance(b, dict) and isinstance(b.get('total'), int) else None


def _same(*vals):
    return all(isinstance(v, str) and v for v in vals) and len(set(vals)) == 1


# id -> f(facts) -> bool: the recomputed `ok`. Each check reads only recorded facts (the step's fields or the report's rollback block).
_POSITIVE = {
    'sha256sums': lambda f: isinstance(f('files'), int) and f('files') > 0 and f('bad') == [],
    'wheel_sha': lambda f: _same(f('sha256'), f('actual_sha256')),
    'venv': _exit0,
    'pip_install': _exit0,
    'help': lambda f: _exit0(f) and f.needle('plan') is True,
    'smoke_body': lambda f: _exit0(f) and f('observation') is True,
    'verdict_run': lambda f: _exit0(f) and f('m1') == 'passed',
    'plan_report': lambda f: f('rendered') is True,
    'modules_from_venv': lambda f: isinstance(f('modules'), int) and f('modules') > 5 and f('outside') == {},
    'checkout_not_on_path': lambda f: f('on_path') == [],
    'blocked_copy_built': lambda f: _exit0(f) and f.needle('built') is True,
    'blocked_scan': lambda f: _exit0(f) and isinstance(_total(f), int) and _total(f) > 0 and _total(f) == f.rb('blocked', 'scan_total'),
    'blocked_refused_no_pip': lambda f: (f('pip_invocations') == 0 and f.rb('blocked', 'pip_invocations') == 0
                                         and f.rb('blocked', 'decision') == 'refused'),
    'blocked_installed_unchanged': lambda f: _same(f('installed'), f.rb('blocked', 'installed_before'), f.rb('blocked', 'installed_after')),
    'blocked_copy_unchanged': lambda f: _same(f('tree_sha'), f.rb('blocked', 'copy_before'), f.rb('blocked', 'copy_after')),
    'clear_scan': lambda f: _exit0(f) and _total(f) == 0 and f.rb('clear', 'scan_total') == 0,
    'clear_uninstall_current': _exit0,
    'clear_install_previous': lambda f: _exit0(f) and _same(f('sha256'), f('actual_sha256')),
    'clear_old_digest': lambda f: _exit0(f) and f.needle('smoke') is f.previous_ns,      # listed iff the previous build has namespaces
    STEP_PREVIOUS_READS: lambda f: _exit0(f) and f.needle('smoke') is True and f.previous_ns is True,
    'clear_old_copy_unchanged': lambda f: _same(f('tree_sha'), f('copy_before'), f.rb('clear', 'copy_before')),
    'clear_uninstall_previous': _exit0,
    'clear_reinstall_current': _exit0,
    'clear_same_build_restored': lambda f: _same(f('installed'), f.rb('clear', 'installed_before'), f.rb('clear', 'installed_after')),
    'clear_roll_forward_reads': lambda f: _exit0(f) and f.needle('smoke') is True,
    'clear_roll_forward_copy_unchanged': lambda f: _same(f('tree_sha'), f.rb('clear', 'copy_before'), f.rb('clear', 'copy_after')),
}
# Negative tests: the step must fail, with one of these exits, BECAUSE of one of these reasons. The runner records this same expectation.
NEGATIVE_EXPECT = {
    STEP_PREVIOUS_CANNOT_READ: {'exits': [1, 2], 'reason_any': ['No plan named']},
}
assert set(_POSITIVE) | set(NEGATIVE_EXPECT) == set(BASE_REQUIRED) | set(_ROLLBACK_ANY) and not set(_POSITIVE) & set(NEGATIVE_EXPECT)


def _negative(sid, s, text, reasons):
    """-> recomputed ok of a negative step, from the oracle's expectation only."""
    want = NEGATIVE_EXPECT[sid]
    if s.get('kind') != 'negative':
        reasons.append(f'negative test "{sid}" is not recorded as negative (kind={s.get("kind")!r})')
    if 'expect' not in s:
        reasons.append(f'negative test "{sid}" has no recorded expectation (the oracle expects {want})')
    elif s['expect'] != want:
        reasons.append(f'negative test "{sid}": expectation replaced by the report ({s["expect"]}; the oracle expects {want})')
    ok = True
    if s.get('exit') not in want['exits']:
        reasons.append(f'negative test "{sid}" exited {s.get("exit")}, expected one of {want["exits"]}')
        ok = False
    if not any(m in text for m in want['reason_any']):
        reasons.append(f'negative test "{sid}" failed for a different reason (none of {want["reason_any"]} in its output)')
        ok = False
    return ok


def judge(report, scope):
    """-> {'result': 'pass'|'refused', 'reasons': [...]} (+ 'optional': [...] only when a step outside the oracle failed).

    Pure. `scope` = package_scope(pkg): the manifest-derived scope (P1-3); without a verified scope the report is refused. The mandatory
    steps are BASE_REQUIRED, plus ROLLBACK_REQUIRED when the SCOPE says the package carries a previous wheel; their pass/fail semantics and
    the negative expectations are this module's (_POSITIVE, NEGATIVE_EXPECT); the report cannot add, drop, demote or redefine them. Each
    mandatory step's `ok` is RECOMPUTED from its recorded facts and must agree with the recorded `ok` in both directions. Refused: a scope
    or package identity that differs from the report's, a misdeclared previous_wheel_present, rollback steps/facts under a BASE scope, a
    missing required step, a duplicate step id, a required step demoted to mandatory=False, a replaced expectation, a missing fact, a
    forbidden marker in a mandatory tail. Steps outside the oracle never decide; their failures are listed under 'optional'. The report's
    own `result` (and anything else it says about itself) is only compared (incoherent if it differs)."""
    reasons, optional = [], []
    steps = report.get('steps')
    bound, rollback = check_binding(report, scope)
    reasons += bound
    if rollback is None:
        return {'result': 'refused', 'reasons': reasons}
    if not isinstance(steps, list) or not steps:
        return {'result': 'refused', 'reasons': reasons + ['report has no steps']}
    previous_ns = bool(rollback and scope.get('previous_reads_plan_ns') is True)      # a hand-built scope without it = the legacy previous build
    required = required_steps(rollback, previous_ns)
    by_id, dups = {}, []
    for s in steps:
        if not isinstance(s, dict):
            reasons.append('malformed step entry')
        elif not isinstance(s.get('id'), str) or not s['id']:
            reasons.append(f'step without id: "{s.get("step", "?")}"')
        elif s['id'] in by_id:
            if s['id'] not in dups:
                dups.append(s['id'])
                reasons.append(f'duplicate step id (ambiguous): {s["id"]}')
        else:
            by_id[s['id']] = s
    for rid in required:
        if rid not in by_id:
            reasons.append(f'expected step missing: {rid}')
    if not rollback:
        extra = [i for i in _ROLLBACK_ANY if i in by_id]
        if extra:
            reasons.append(f'rollback steps recorded although the package manifest declares no previous wheel: {", ".join(extra)}')
        rb = report.get('rollback')
        if rb is not None and (not isinstance(rb, dict) or set(rb) - {'skipped'}):
            reasons.append('rollback facts recorded although the package manifest declares no previous wheel (contradiction)')
    # the recorded wheel identities in the steps are the manifest's (a step about another wheel proves nothing about this package)
    if 'wheel_sha' in by_id and by_id['wheel_sha'].get('sha256') != scope['wheel_sha256']:
        reasons.append('step "wheel_sha" checked a different wheel than the package manifest pins')
    if rollback and 'clear_install_previous' in by_id and by_id['clear_install_previous'].get('sha256') != scope['previous_wheel_sha256']:
        reasons.append('step "clear_install_previous" installed a different previous wheel than the package manifest pins')
    if rollback:
        other = STEP_PREVIOUS_CANNOT_READ if previous_ns else STEP_PREVIOUS_READS
        if other in by_id:
            reasons.append(f'step "{other}" belongs to the other previous-build capability (the manifest says the previous build '
                           f'{"reads" if previous_ns else "predates"} plan-ns roots)')
    for sid, s in by_id.items():
        if sid not in required:
            if sid not in _ROLLBACK_ANY and s.get('ok') is not True:
                optional.append(f'optional step failed (not deciding): {sid}')
            continue
        text = _text(s)
        if s.get('mandatory', True) is not True:
            reasons.append(f'mandatory step demoted: {sid} (the report says mandatory={s.get("mandatory")!r}; the oracle requires it)')
        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                reasons.append(f'step "{sid}" shows "{marker}" in its output')
                break
        if sid in NEGATIVE_EXPECT:
            computed = _negative(sid, s, text, reasons)
        else:
            if s.get('kind') == 'negative' or 'expect' in s:
                reasons.append(f'step "{sid}" carries a negative expectation the oracle does not hold')
            facts = _Facts(s, report.get('rollback'), previous_ns)
            computed = bool(_POSITIVE[sid](facts))
            if facts.missing:
                reasons.append(f'fact missing for step "{sid}": {", ".join(dict.fromkeys(facts.missing))}')
                continue
            if 'exit' in s and s['exit'] != 0:
                reasons.append(f'unexpected nonzero exit {s["exit"]} in step "{sid}"')
        if not computed:
            reasons.append(f'mandatory step failed: {sid}')
        recorded = s.get('ok')
        if not isinstance(recorded, bool):
            reasons.append(f'step "{sid}" records no boolean ok')
        elif recorded != computed:
            reasons.append(f'step "{sid}": recorded ok={recorded} disagrees with the recorded facts (ok={computed})')
    reasons += _judge_rollback(report.get('rollback'), rollback)
    result = 'refused' if reasons else 'pass'
    claimed = report.get('result')
    if claimed in ('pass', 'refused') and claimed != result:
        reasons.append(f'incoherent report: it claims "{claimed}" but the recorded facts give "{result}"')
        result = 'refused'
    out = {'result': result, 'reasons': reasons}
    if optional:
        out['optional'] = optional
    return out


def _judge_rollback(rb, present):
    if present is not True:
        return []
    if not isinstance(rb, dict):
        return ['rollback facts missing although the package carries a previous wheel']
    out = []
    blocked, clear = rb.get('blocked'), rb.get('clear')
    if not isinstance(blocked, dict):
        out.append('rollback: the blocked branch was not exercised')
    else:
        total = blocked.get('scan_total')
        if not (isinstance(total, int) and total > 0):
            out.append('rollback: the blocked copy has no block (scan total must be > 0)')
        if blocked.get('decision') != 'refused' or blocked.get('decision') != rollback_decision(total if isinstance(total, int) else 0):
            out.append('rollback: a scan with blocks must REFUSE the rollback')
        if blocked.get('pip_invocations') != 0:
            out.append(f'rollback refused branch ran {blocked.get("pip_invocations")} pip install/uninstall (must be 0)')
        if not blocked.get('installed_before') or blocked.get('installed_before') != blocked.get('installed_after'):
            out.append('rollback refused branch changed the installed build')
        if not blocked.get('copy_before') or blocked.get('copy_before') != blocked.get('copy_after'):
            out.append('rollback refused branch changed the ledger copy')
    if not isinstance(clear, dict):
        out.append('rollback: the allowed branch was not exercised')
    else:
        if clear.get('scan_total') != 0:
            out.append('rollback: the clear copy must have 0 blocks')
        if clear.get('decision') != 'allowed':
            out.append('rollback: a scan with 0 blocks must allow the rollback')
        if not isinstance(clear.get('pip_invocations'), int) or clear['pip_invocations'] < 4:
            out.append('rollback allowed branch must uninstall/install twice (previous, then current)')
        if not clear.get('installed_before') or clear.get('installed_before') != clear.get('installed_after'):
            out.append('roll-forward did not restore the same installed build')
        if not clear.get('copy_before') or clear.get('copy_before') != clear.get('copy_after'):
            out.append('rollback allowed branch changed the ledger copy')
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# runner

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_sha(root):
    """Content hash of every file under root (names + bytes)."""
    h = hashlib.sha256()
    root = Path(root)
    for p in sorted(x for x in root.rglob('*') if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode('utf-8'))
        h.update(b'\0')
        h.update(sha(p).encode())
        h.update(b'\n')
    return h.hexdigest()


def installed_fingerprint(venv):
    """Hash of the installed onecrew build: its package .py files and dist-info metadata under the venv's site-packages."""
    h = hashlib.sha256()
    sites = [p for p in [Path(venv) / 'Lib' / 'site-packages', *Path(venv).glob('lib/python*/site-packages')] if p.is_dir()]
    for site in sites:
        files = list((site / 'onecrew').rglob('*.py')) if (site / 'onecrew').is_dir() else []
        for d in site.glob('onecrew-*.dist-info'):
            files += [d / 'METADATA', d / 'WHEEL', d / 'entry_points.txt']      # not RECORD: it lists the .pyc files each run compiled
        for p in sorted(f for f in files if f.is_file()):
            h.update(p.relative_to(site).as_posix().encode('utf-8'))
            h.update(b'\0')
            h.update(sha(p).encode())
            h.update(b'\n')
    return h.hexdigest()


class Runner:
    """Runs children with a UTF-8 environment, keeps tails, and counts pip install/uninstall invocations."""

    def __init__(self):
        self.pip_invocations = 0
        env = dict(os.environ)
        for key in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'PYTHONPATH', 'PYTHONHOME'):
            env.pop(key, None)
        env.update({'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
        self.env = env

    def run(self, cmd, **kw):
        argv = [str(c) for c in cmd]
        if len(argv) > 3 and argv[1:3] == ['-m', 'pip'] and ('install' in argv[3:] or 'uninstall' in argv[3:]):
            self.pip_invocations += 1
        r = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', env=self.env, **kw)
        return r.returncode, r.stdout, r.stderr


class Abort(Exception):
    pass


def run(pkg, work, out=print, expected_verifier=None):
    """`expected_verifier`: the verify/ files a shipped launcher already checked (bound into the scope; None from a checkout)."""
    pkg, work = Path(pkg).resolve(), Path(work).resolve()
    if work.exists():
        raise SystemExit('work dir must be new')
    if work.is_relative_to(CHECKOUT):
        raise SystemExit('work dir must be OUTSIDE the checkout')
    work.mkdir(parents=True)
    scope = package_scope(pkg, expected_verifier)          # P1-3: the scope comes from the manifest + artifact, before anything runs
    report = {'package': str(pkg), 'work': str(work), 'package_identity': identity(scope), 'steps': [], 'result': None,
              'previous_wheel_present': None}
    runner = Runner()

    def tails(code=None, so='', se=''):
        d = {'stdout_tail': so[-500:], 'stderr_tail': se[-500:]}
        if code is not None:
            d['exit'] = code
        return d

    def step(sid, name, ok, **facts):
        report['steps'].append({'id': sid, 'step': name, 'ok': bool(ok), 'mandatory': True, **facts})
        out(('OK   ' if ok else 'FAIL ') + name)
        if not ok:
            raise Abort(name)

    if scope['reasons']:
        out('REFUSED before running: the package manifest/artifact is unverifiable: ' + '; '.join(scope['reasons']))
    else:
        try:
            _verify(pkg, work, report, runner, step, tails, out)
        except Abort as stop:
            out(f'ABORT after failed step: {stop}')
    j = judge(report, scope)
    report['result'], report['judge'] = j['result'], j
    (work / 'verification').mkdir(exist_ok=True)
    (work / 'verification' / 'verify-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    out(json.dumps({'result': j['result'], 'reasons': j['reasons'], 'report': str(work / 'verification' / 'verify-report.json')}, ensure_ascii=False))
    return report


def _verify(pkg, work, report, runner, step, tails, out):
    manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))
    sums = dict(line.split('  ', 1)[::-1] for line in (pkg / 'SHA256SUMS').read_text(encoding='utf-8').splitlines() if line.strip())
    bad = [f for f, h in sums.items() if not (pkg / f).exists() or sha(pkg / f) != h]
    step('sha256sums', 'SHA256SUMS: every listed file present and unchanged', not bad, files=len(sums), bad=bad[:5])
    wheel = pkg / manifest['wheel']['file']
    actual = sha(wheel)
    step('wheel_sha', 'wheel sha256 == manifest', actual == manifest['wheel']['sha256'], sha256=manifest['wheel']['sha256'], actual_sha256=actual)
    venv = work / 'venv'
    code, so, se = runner.run([sys.executable, '-m', 'venv', venv])
    step('venv', 'venv created outside the checkout', code == 0 and not venv.resolve().is_relative_to(CHECKOUT), path=str(venv), **tails(code, so, se))
    win = os.name == 'nt'
    py = venv / ('Scripts' if win else 'bin') / ('python.exe' if win else 'python')
    exe = py.with_name('onecrew' + ('.exe' if win else ''))
    pip_cur = [py, '-m', 'pip', 'install', '--no-index', '--no-build-isolation', wheel]
    code, so, se = runner.run(pip_cur)
    step('pip_install', 'pip install --no-index from the package wheel', code == 0, **tails(code, so, se))
    code, so, se = runner.run([exe, '--help'])
    step('help', 'onecrew --help from the venv console script', code == 0 and 'plan' in so, needles={'plan': 'plan' in so}, **tails(code, so, se))

    project, state = work / 'project', work / 'state'
    project.mkdir()
    for args in (['init', '-q'], ['config', 'user.name', 'verify'], ['config', 'user.email', 'verify@localhost']):
        subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)
    (project / 'a.txt').write_text('base\n')
    subprocess.run(['git', '-C', str(project), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(project), 'commit', '-qm', 'base'], check=True, capture_output=True)
    contract = {'schema_version': 2, 'title': 'Package smoke', 'size': 'S',
                'understanding': {'restated_goal': 'Smoke the installed build.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']}, 'assumptions': [], 'confidence': 'high', 'unknowns': []},
                'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file is there'}],
                'output': ['The sample exists'], 'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
                'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'}],
                'milestones': [{'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': [str(py), '-c', 'print("ok")']}}, 'covers': ['O1']}],
                'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None}
    (work / 'contract.json').write_text(json.dumps(contract), encoding='utf-8')
    body = f'''
import json, os, sys, subprocess
for key in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(key, None)
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan, verdict, report
ledger = Ledger(Path({str(project)!r}), Path({str(state)!r}))
plan.propose(ledger, 'smoke', json.load(open({str(work / 'contract.json')!r}, encoding='utf-8')), 'package-verify', workflow=True)
plan.approve(ledger, 'smoke', 'owner', 'package smoke on a temporary ledger; not an owner action')
done = subprocess.run([{str(exe)!r}, '--project', {str(project)!r}, '--state-root', {str(state)!r}, 'verdict', 'run', '--plan', 'smoke', '--milestone', 'M1'],
                      capture_output=True, text=True, encoding='utf-8', errors='replace', env={{**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}})
state_m1 = plan.show(ledger, 'smoke')['milestones'][0]['state']
page = report.render_report(Path({str(state)!r}), 'smoke')
mods = {{n: getattr(m, '__file__', None) for n, m in sys.modules.items() if n == 'onecrew' or n.startswith('onecrew.')}}
print('@@' + json.dumps({{'verdict_exit': done.returncode, 'tail': (done.stdout + done.stderr)[-300:], 'm1': state_m1, 'report_ok': 'smoke' in page, 'modules': mods, 'sys_path': sys.path}}))
'''
    code, so, se = runner.run([py, '-I', '-c', body], cwd=str(work))
    line = next((l for l in so.splitlines() if l.startswith('@@')), None)
    step('smoke_body', 'smoke body ran', code == 0 and line is not None, observation=line is not None, **tails(code, so, se))
    obs = json.loads(line[2:])
    step('verdict_run', 'verdict run through the venv console script passed M1', obs['verdict_exit'] == 0 and obs['m1'] == 'passed',
         m1=obs['m1'], tail=obs['tail'], exit=obs['verdict_exit'])
    step('plan_report', 'plan report renders', obs['report_ok'], rendered=obs['report_ok'] is True)
    outside = {n: p for n, p in obs['modules'].items() if p and not Path(p).resolve().is_relative_to(venv.resolve())}
    step('modules_from_venv', 'every onecrew module loaded from the venv, none from a checkout', not outside and len(obs['modules']) > 5,
         modules=len(obs['modules']), outside=outside)
    on_path = [p for p in obs['sys_path'] if p and Path(p).resolve().is_relative_to(CHECKOUT)]
    step('checkout_not_on_path', 'checkout is not on sys.path', not on_path, sys_path=obs['sys_path'][:6], on_path=on_path)

    prev = manifest.get('previous_wheel')
    report['previous_wheel_present'] = bool(prev)
    if not prev:
        report['rollback'] = {'skipped': 'package carries no previous wheel'}
        return
    _rollback(pkg, work, report, runner, step, tails, out, venv=venv, py=py, exe=exe, project=project, state=state, prev=prev, pip_cur=pip_cur)


def _scan(runner, exe, project, copy):
    code, so, se = runner.run([exe, '--project', project, '--state-root', copy, 'compat', 'scan', '--json'])
    scan = {}
    if code == 0 and '{' in so:
        try:
            scan = json.loads(so[so.index('{'):])
        except ValueError:
            scan = {}
    return code, so, se, scan


def _rollback(pkg, work, report, runner, step, tails, out, *, venv, py, exe, project, state, prev, pip_cur):
    rb = report['rollback'] = {}
    blocked_dir, clear_dir = work / 'state-blocked', work / 'state-clear'
    shutil.copytree(state, clear_dir)
    shutil.copytree(state, blocked_dir)
    # (a) a REAL block built with the installed build's own APIs: a second plan, approved and not accepted, exports an approved active plan
    # the previous build cannot see (compat_scan B1). The venv body is the product itself; nothing is edited by hand.
    body = f'''
import json
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.v2 import plan
ledger = Ledger(Path({str(project)!r}), Path({str(blocked_dir)!r}))
c = json.load(open({str(work / 'contract.json')!r}, encoding='utf-8')); c['title'] = 'Open plan that blocks rollback'
plan.propose(ledger, 'blocked-open', c, 'package-verify', workflow=True)
plan.approve(ledger, 'blocked-open', 'owner', 'package verify: an approved, unaccepted root on a temporary ledger copy; not an owner action')
print('built')
'''
    code, so, se = runner.run([py, '-I', '-c', body], cwd=str(work))
    step('blocked_copy_built', 'state-blocked: approved, unaccepted root added with the installed build', code == 0 and 'built' in so,
         needles={'built': 'built' in so}, **tails(code, so, se))

    # ---- refused branch (blocked copy) ----
    code, so, se, scan = _scan(runner, exe, project, blocked_dir)
    total = (scan.get('blocking') or {}).get('total', 0) if scan else 0
    step('blocked_scan', 'compat scan on state-blocked reports blocks', code == 0 and total > 0, blocking=scan.get('blocking'),
         block_ids=sorted({b['id'] for r in scan.get('roots', []) for b in r.get('blocks', [])}), **tails(code, so, se))
    decision = rollback_decision(total)
    fp_before, copy_before, pips_before = installed_fingerprint(venv), tree_sha(blocked_dir), runner.pip_invocations
    if decision == 'refused':
        out('rollback refused: the scan has blockers; no uninstall/install runs in this branch')
    else:                                            # unreachable: the step above fails first
        raise Abort('blocked copy has no block; the refused branch cannot be shown')
    fp_after, copy_after, pips = installed_fingerprint(venv), tree_sha(blocked_dir), runner.pip_invocations - pips_before
    rb['blocked'] = {'copy': str(blocked_dir), 'scan_total': total, 'decision': decision, 'pip_invocations': pips,
                     'installed_before': fp_before, 'installed_after': fp_after, 'copy_before': copy_before, 'copy_after': copy_after}
    step('blocked_refused_no_pip', 'rollback refused on the blocked copy: 0 pip uninstall/install invocations', decision == 'refused' and pips == 0, pip_invocations=pips)
    step('blocked_installed_unchanged', 'refused branch: installed build unchanged', fp_before == fp_after, installed=fp_after)
    step('blocked_copy_unchanged', 'refused branch: nothing in state-blocked changed', copy_before == copy_after, tree_sha=copy_after)

    # ---- allowed branch (clear copy) ----
    code, so, se, scan = _scan(runner, exe, project, clear_dir)
    total = (scan.get('blocking') or {}).get('total', 1) if scan else 1
    step('clear_scan', 'compat scan on state-clear reports 0 blocks', code == 0 and total == 0, blocking=scan.get('blocking'), **tails(code, so, se))
    decision = rollback_decision(total)
    fp_before, copy_before, pips_before = installed_fingerprint(venv), tree_sha(clear_dir), runner.pip_invocations
    code, so, se = runner.run([py, '-m', 'pip', 'uninstall', '--yes', 'onecrew'])
    step('clear_uninstall_current', 'uninstall current', code == 0, **tails(code, so, se))
    prev_wheel = pkg / prev['file']
    code, so, se = runner.run([py, '-m', 'pip', 'install', '--no-index', '--no-build-isolation', prev_wheel])
    prev_actual = sha(prev_wheel)
    step('clear_install_previous', 'install previous wheel from the package', code == 0 and prev_actual == prev['sha256'],
         sha256=prev['sha256'], actual_sha256=prev_actual, **tails(code, so, se))
    # What the previous build can see depends on THAT build (manifest-derived: previous_reads_plan_ns), not on an assumption.
    reads_ns = previous_reads_plan_ns(prev.get('file'))
    report['previous_reads_plan_ns'] = reads_ns          # the branch taken, beside the identity the judge binds to the manifest
    code, so, se = runner.run([exe, '--project', project, '--state-root', clear_dir, 'plan', 'digest'])
    if reads_ns:
        step('clear_old_digest', 'previous build (has plan namespaces): plan digest exits 0 and lists the namespaced smoke root',
             code == 0 and 'smoke' in so, needles={'smoke': 'smoke' in so}, **tails(code, so, se))
        code, so, se = runner.run([exe, '--project', project, '--state-root', clear_dir, 'plan', 'show', 'smoke'])
        step(STEP_PREVIOUS_READS, 'previous build (has plan namespaces) reads the plan-ns root: plan show smoke exits 0 and names it',
             code == 0 and 'smoke' in so, needles={'smoke': 'smoke' in so}, **tails(code, so, se))
    else:
        # The previous build predates plan namespaces: `plan digest` lists only legacy roots, so it exits 0 and the namespaced root is NOT listed.
        step('clear_old_digest', 'previous build: plan digest exits 0 (legacy roots only; the namespaced smoke root is not listed)',
             code == 0 and 'smoke' not in so, needles={'smoke': 'smoke' in so}, **tails(code, so, se))
        # Deliberate negative test: the previous build cannot read the plan-ns root. It must fail BECAUSE no such plan exists for it.
        code, so, se = runner.run([exe, '--project', project, '--state-root', clear_dir, 'plan', 'show', 'smoke'])
        expect = json.loads(json.dumps(NEGATIVE_EXPECT[STEP_PREVIOUS_CANNOT_READ]))      # the oracle's expectation, recorded as is
        ok = code in expect['exits'] and any(m in so + se for m in expect['reason_any']) and not any(m in so + se for m in FORBIDDEN_MARKERS)
        step(STEP_PREVIOUS_CANNOT_READ, 'previous build cannot read the plan-ns root (plan show smoke refused: No plan named)', ok,
             kind='negative', expect=expect, **tails(code, so, se))
    old_copy = tree_sha(clear_dir)
    step('clear_old_copy_unchanged', 'previous build changed nothing in state-clear', old_copy == copy_before, tree_sha=old_copy, copy_before=copy_before)
    code, so, se = runner.run([py, '-m', 'pip', 'uninstall', '--yes', 'onecrew'])
    step('clear_uninstall_previous', 'uninstall previous', code == 0, **tails(code, so, se))
    code, so, se = runner.run(pip_cur)
    step('clear_reinstall_current', 'roll-forward: current wheel reinstalled', code == 0, **tails(code, so, se))
    fp_after = installed_fingerprint(venv)
    step('clear_same_build_restored', 'roll-forward restored the identical installed build', fp_after == fp_before, installed=fp_after)
    code, so, se = runner.run([exe, '--project', project, '--state-root', clear_dir, 'plan', 'show', 'smoke'])
    step('clear_roll_forward_reads', 'roll-forward reads the root again', code == 0 and 'smoke' in so, needles={'smoke': 'smoke' in so}, **tails(code, so, se))
    copy_after = tree_sha(clear_dir)
    step('clear_roll_forward_copy_unchanged', 'roll-forward changed nothing in state-clear', copy_after == copy_before, tree_sha=copy_after)
    rb['clear'] = {'copy': str(clear_dir), 'scan_total': total, 'decision': decision, 'pip_invocations': runner.pip_invocations - pips_before,
                   'installed_before': fp_before, 'installed_after': fp_after, 'copy_before': copy_before, 'copy_after': copy_after}


def main(argv=None, verifier_files=None):
    """`verifier_files`: passed by the shipped launcher (the verify/ files it verified against this manifest)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        sys.exit('usage: verify_package.py <package dir> <work dir (new, outside the checkout)>')
    return 0 if run(argv[0], argv[1], expected_verifier=verifier_files)['result'] == 'pass' else 1
