"""T54 release-bundle PRODUCER (W40-R01 … W40-RX2, one shared framework): python -m wfkit.release_bundle R05 --out <new dir under OS temp>

It runs the five points of T54 for one release on REAL local observations and writes the bundle `wfkit.release_check` validates:
  1. installed  — the release scenario runs from the installed wheel in the drill's venv (module boundary, bytes == wheel, checkout control refused);
  2. upgrade    — the generated fixture ledger is upgraded previous -> current on a COPY (ID / revision / budget / evidence / unknown attempt rows);
  3. events     — the kinds the current code really writes on a legacy `plan:` anchor, classified by the event-class table, with the old
                  binary's S/G/C before/after (the W11a comparator) — class B only on `plan-ns:`;
  4. rollback   — the drill's refused branch (blocks) and allowed branch (0 blocks, same ledger hash), old run and roll-forward run, and for
                  R05/R08 the reconcile-before-continue order of the unknown intent;
  5. notes      — the release's Markdown notes (docs/wf/release-notes/<release>.md) with the four evidence states on separate lines.
Everything reuses the W41 drill (`wfkit.upgrade_drill.Drill`), the W40 wheel/venv helpers (`tests.wf_wheel`) and the W11a comparator
(`tests.wf_oldversion`). Nothing here touches a real state root, a monitor, a provider or an owner verb.

What it cannot supply, and says so: `gate_history` (receipts of a PASSING delivery gate of the previous build). No release of this program
has been delivered, so the previous build is the scanner-supported baseline d3120c6 and `release_check` refuses the INPUTS condition
('previous delivered gate history missing'); T54.1–T54.5 are still judged on the real receipts. The bundle is evidence for the
development handover, not a delivery, and never owner acceptance.

Only when explicitly asked (`--first-release`, Producer(first_release=True)) the bundle carries the first-delivery claim
`first_release: {baseline: {commit, wheel_sha256 of the previous artifact, role: 'compat-baseline', delivered: false, accepted: false}, reason}`
and `release_check` judges it under its own condition INPUTS(bootstrap) (the baseline must be the build every drill ran). It is never
written by default, and the baseline is never called delivered or accepted.

Stable baseline pin (`--baseline-wheel <path>`, Producer(baseline_wheel=...)): the drills REUSE one stored baseline wheel instead of rebuilding
it (the hand-built wheel is not byte-reproducible, so each rebuild had a new sha256). The stored wheel is verified first
(`verify_baseline_wheel`): onecrew-<version>-py3-none-any.whl whose METADATA names that version, a sidecar `<wheel>.json` whose commit is the
baseline and whose sha256 is the file's, and every packaged module equal to the baseline commit's git blob (modulo the CRLF git archive writes under core.autocrlf).
`build_baseline_wheel` writes such a wheel + sidecar once
(python -c "from wfkit import release_bundle as b; b.build_baseline_wheel('D:/OneCrewRuns/wf-baseline-d3120c6')").
Without --baseline-wheel the behaviour is unchanged (the baseline is rebuilt).
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

from onecrew.ledger import LedgerError, content_hash
from onecrew.v2 import compat
from tests import wf_oldversion as old
from tests import wf_rollback as rollback
from tests import wf_wheel as wheel
from wfkit import release_check
from wfkit import gate_history as history
from wfkit.upgrade_drill import Drill, ROOT, sha, build_source
from tests import wf_scenarios as scenarios

RELEASES = tuple(release_check.PARTS)
NOTES_DIR = ROOT / 'docs' / 'wf' / 'release-notes'

# Per-release probes run INSIDE the installed venv after the common steps (plan show / digest / compat scan / report). Each line is a real
# call of a module the release added; a bare import only proves the module is in the wheel and is labelled so in the receipt.
SCENARIOS = {
    'R01': "assert 'legacy' in report.render_present(state, 'legacy'); steps.append({'probe': 'report.render_present (R01 W23a)'})",
    'R02': "import onecrew.v2.outcome, onecrew.v2.resume_pack, onecrew.v2.context; steps.append({'probe': 'import only: outcome, resume_pack, context (R02)'})",
    'R03': "estimates.reforecast(ledger, 'plan:legacy', 'eta-r03', [30, 60], 'probe', ['fixture:eta']); exceptions.observe(ledger, 'plan:legacy'); steps.append({'probe': 'estimates.reforecast + exceptions.observe (R03)'})",
    'R04': "import onecrew.v2.namespaces, onecrew.v2.authority, onecrew.v2.internal_plan, onecrew.v2.test_integrity; steps.append({'probe': 'import only: namespaces, authority, internal_plan, test_integrity (R04)'})",
    'R05': "assert len(findings.list_findings(ledger, 'findings', open_only=True)) == 1; steps.append({'probe': 'findings.list_findings on the drill finding root (R05 W17)'})",
    'R06': "import onecrew.v2.lessons, onecrew.v2.incidents, onecrew.v2.learning_cli; steps.append({'probe': 'import only: lessons, incidents, learning_cli (R06)'})",
    'R07': "import onecrew.v2.localization, onecrew.v2.messages; steps.append({'probe': 'import only: localization, messages (R07)'})",
    'R08': "import onecrew.v2.managed_executor, onecrew.v2.engine; steps.append({'probe': 'import only: managed_executor, engine (R08)'})",
    'RP': "import onecrew.v2.providers; steps.append({'probe': 'import only: providers (RP); no provider CLI is called'})",
    'RX1': "import onecrew.v2.verifiers.doc; steps.append({'probe': 'doc adapter: see adapter_runs (RX1)'})",
    'RX2': "import onecrew.v2.verifiers.data, onecrew.v2.verifiers.ops; steps.append({'probe': 'data/ops adapters: see adapter_runs (RX2)'})",
}


def now():
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def preservation_rows(state, ids=None):
    """The T54.2 rows: one per task anchor — id, revision, budget, evidence refs, attempts (status kept). `ids` restricts the rows to the
    anchors that existed before the upgrade (the retained state the drill must preserve; roots the drill creates afterwards are not it)."""
    conn = sqlite3.connect((Path(state) / 'ledger.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = []
        for task in conn.execute('SELECT id FROM tasks ORDER BY id'):
            tid = task['id']
            if ids is not None and tid not in ids: continue
            revision, evidence = 1, []
            for event in conn.execute('SELECT kind, payload FROM events WHERE task_id=? ORDER BY seq', (tid,)):
                payload = json.loads(event['payload']) if event['payload'] else {}
                if isinstance(payload.get('revision'), int): revision = max(revision, payload['revision'])
                for key in ('receipt', 'evidence', 'artifact_sha', 'sha'):
                    value = payload.get(key)
                    if isinstance(value, str) and value: evidence.append(f"{event['kind']}:{key}={value}")
            budget = {'used_calls': 0, 'reserved_calls': 0, 'executions': 0}
            try:
                for ex in conn.execute('SELECT used_calls, reserved_calls FROM executions WHERE task_id=?', (tid,)):
                    budget['used_calls'] += int(ex['used_calls'] or 0); budget['reserved_calls'] += int(ex['reserved_calls'] or 0); budget['executions'] += 1
            except sqlite3.OperationalError:
                pass
            attempts = []
            try:
                attempts = [{'id': a['id'], 'status': a['status']} for a in conn.execute('SELECT id, status FROM attempts WHERE task_id=? ORDER BY id', (tid,))]
            except sqlite3.OperationalError:
                pass
            rows.append({'id': tid, 'revision': revision, 'budget': budget, 'evidence': sorted(set(evidence)), 'attempts': attempts})
        return rows
    finally:
        conn.close()


INPUTS_BLOCKER = {'condition': 'INPUTS', 'kind': 'external', 'detail': 'No release of this program has been delivered (no passing CG- gate receipt of a '
                  'previous build exists). The previous build used here is the scanner-supported baseline d3120c6, not a delivered build. '
                  'Only the owner\'s delivery of an earlier release can supply gate_history.'}
FIRST_RELEASE_REASON = ('No release of this program has been delivered, so no passing CG- delivery gate of a previous build exists. The previous '
                        'artifact is the compat baseline the scanner models and the drills install; it is not delivered and not accepted.')



SIDECAR_KEYS = {'commit', 'sha256', 'version', 'built_at', 'source'}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)


def verify_baseline_wheel(path, baseline_commit, repo=ROOT):
    """The stored baseline wheel is the build of `baseline_commit`: name/METADATA version agree, the sidecar names this commit and these bytes,
    and every packaged file equals the commit's git blob (so a wheel of another commit is refused even with a forged sidecar)."""
    path = Path(path)
    if not path.is_file(): raise LedgerError('baseline wheel missing: ' + str(path))
    m = re.fullmatch(r'onecrew-(.+)-py3-none-any\.whl', path.name)
    if not m: raise LedgerError('baseline wheel name is not onecrew-<version>-py3-none-any.whl: ' + path.name)
    version, digest = m.group(1), sha(path)
    sidecar_path = path.with_name(path.name + '.json')
    if not sidecar_path.is_file(): raise LedgerError('baseline wheel has no sidecar ' + sidecar_path.name)
    sidecar = json.loads(sidecar_path.read_text(encoding='utf-8'))
    if not isinstance(sidecar, dict) or set(sidecar) != SIDECAR_KEYS: raise LedgerError('baseline sidecar must be exactly ' + ', '.join(sorted(SIDECAR_KEYS)))
    if sidecar['commit'] != baseline_commit: raise LedgerError('baseline sidecar names commit ' + str(sidecar['commit']) + ', the baseline is ' + baseline_commit)
    if sidecar['sha256'] != digest: raise LedgerError('baseline wheel bytes differ from its sidecar sha256')
    if sidecar['version'] != version: raise LedgerError('baseline sidecar version differs from the wheel name')
    history.wheel_matches_commit(path, baseline_commit, repo)            # every packaged file is the commit's git blob
    pyproject = git(repo, 'show', baseline_commit + ':pyproject.toml').decode('utf-8')
    modules = re.findall(r'"([\w.]+)"', re.search(r'py-modules\s*=\s*\[(.*?)\]', pyproject, re.S).group(1))
    with zipfile.ZipFile(path) as archive:
        names = [i.filename for i in archive.infolist() if not i.is_dir()]
    missing = [mod for mod in modules if mod.replace('.', '/') + '.py' not in names]
    if missing: raise LedgerError('baseline wheel lacks modules of ' + baseline_commit[:12] + ': ' + ', '.join(missing[:5]))
    return {'wheel': str(path), 'wheel_sha256': digest, 'commit': baseline_commit, 'sidecar': str(sidecar_path)}


def build_baseline_wheel(target, repo=ROOT, baseline='d3120c6'):
    """Build the baseline wheel ONCE with the drill's own builder (git archive of the commit -> tests.wf_wheel.build_wheel) into `target`, with
    its sidecar. Refuses to overwrite a stored wheel: the point is one stable pin."""
    import tempfile
    commit = git(repo, 'rev-parse', baseline).decode().strip()
    target = Path(target); target.mkdir(parents=True, exist_ok=True)
    if any(target.glob('onecrew-*.whl')): raise LedgerError('a baseline wheel is already stored in ' + str(target) + '; verify it, do not rebuild')
    with tempfile.TemporaryDirectory(prefix='wf-baseline-') as scratch:
        archived = old.archive(commit, repo, scratch)
        with build_source(archived):
            path, version, _ = wheel.build_wheel(target)
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    sidecar = {'commit': commit, 'sha256': sha(path), 'version': version, 'built_at': now(),
               'source': 'release_bundle baseline builder at ' + head}
    Path(str(path) + '.json').write_text(json.dumps(sidecar, ensure_ascii=False, indent=1), encoding='utf-8')
    return verify_baseline_wheel(path, commit, repo)


def prerequisite_fields(first_release, previous):
    """The INPUTS part of a bundle: by default nothing is claimed and the external blocker is recorded; only when explicitly asked, the
    first-release claim pins the previous artifact as a compat baseline (never delivered, never accepted)."""
    if first_release is not True:
        return {}, [dict(INPUTS_BLOCKER)]
    baseline = {'commit': previous['commit'], 'wheel_sha256': previous['wheel_sha256'], 'role': 'compat-baseline', 'delivered': False, 'accepted': False}
    return ({'first_release': {'baseline': baseline, 'reason': FIRST_RELEASE_REASON}},
            [{'condition': 'INPUTS(bootstrap)', 'kind': 'first-release', 'detail': 'First delivery: judged against the pinned compat baseline '
              + previous['commit'][:12] + '; it is not a delivered build and gives no delivery or owner acceptance.'}])


class Producer(Drill):
    """The W41 drill plus the four other T54 points, written as release_check receipts."""

    def __init__(self, release, out, repo=ROOT, baseline='d3120c6', gate=None, adapters=None, matrix=None, first_release=False, baseline_wheel=None, gate_history=None):
        if release not in RELEASES: raise LedgerError('unsupported release ' + str(release))
        if gate_history and first_release is True: raise LedgerError('a bundle with delivery gate history is not a first release')
        super().__init__(out, repo, baseline)
        self.history_paths = [Path(p) for p in gate_history or []]
        if self.history_paths:
            # the NORMAL rule: the previous build is the latest PASSING CG- delivery gate, not a chosen baseline. Its wheel bytes must be at hand
            # (the receipt's `wheel`, else --baseline-wheel) with that sha256 and the commit's blobs.
            latest, _ = history.select_previous(self.history_paths)
            if latest['commit'] != self.baseline:
                raise LedgerError('the latest passing delivery gate is ' + latest['commit'][:12] + '; the compatibility scanner models only '
                                  + self.baseline[:12] + ', so this upgrade cannot be drilled from it yet')
            wheel_path = Path(latest.get('wheel') or baseline_wheel or '')
            if not wheel_path.is_file() or sha(wheel_path) != latest['wheel_sha256']:
                raise LedgerError('the wheel of the latest delivered build (sha256 ' + latest['wheel_sha256'][:12] + ') is not at hand')
            history.wheel_matches_commit(wheel_path, latest['commit'], self.repo)
            self.baseline_pin = {'wheel': str(wheel_path), 'wheel_sha256': latest['wheel_sha256'], 'commit': latest['commit'], 'from_history': True}
        else:
            # stable pin: verified BEFORE any drill step; None keeps the old behaviour (rebuild the baseline)
            self.baseline_pin = verify_baseline_wheel(baseline_wheel, self.baseline, self.repo) if baseline_wheel else None
        self.release, self.gate_decision, self.adapters = release, gate, adapters
        self.first_release = first_release is True                          # bootstrap claim only when explicitly asked
        self.matrix_dir = Path(matrix) if matrix else None               # RP: the W45 real matrix (wfkit.provider_matrix output) for T54i [E7]
        # The CURRENT artifact is the gate's own wheel when a gate is cited: same bytes, same sha256, identified by the gate's commit (the snapshot
        # worktree of that commit built it). Without a gate the drill builds a wheel from this checkout and names HEAD.
        self.gate_build = None
        if gate and gate.get('snapshot', {}).get('log'):
            build_path = Path(gate['snapshot']['log']).parent / 'gate' / 'build.json'
            if build_path.exists():
                self.gate_build = json.loads(build_path.read_text(encoding='utf-8'))
                if sha(self.gate_build['wheel']) != self.gate_build['wheel_sha256']: raise LedgerError('gate wheel bytes changed since the gate')
                if self.gate_build['commit'] != gate['snapshot']['commit']: raise LedgerError('gate build.json and decision name different commits')
        self.receipts_dir = self.out / 'receipts'; self.receipts_dir.mkdir()
        self.archived = None; self.event_log = []
        self._monitored_before = {str(p): sha(p) for p in self.monitored_paths() if p.exists()}

    # -- bookkeeping -------------------------------------------------------------------------------------------------------------------
    def capture(self, label, body, expect=0):
        result = super().capture(label, body, expect)
        self.records[-1]['at'] = now()
        return result

    def build(self):
        if self.baseline_pin:
            return self._build_pinned()
        if self.gate_build:
            saved = {k: os.environ.get(k) for k in ('WF_WHEEL', 'WF_WHEEL_SHA256')}
            os.environ['WF_WHEEL'] = self.gate_build['wheel']; os.environ['WF_WHEEL_SHA256'] = self.gate_build['wheel_sha256']
            try:
                super().build()
            finally:
                for k, v in saved.items():
                    if v is None: os.environ.pop(k, None)
                    else: os.environ[k] = v
            if self.artifacts['current']['wheel_sha256'] != self.gate_build['wheel_sha256']: raise LedgerError('the drill did not reuse the gate wheel')
            self.artifacts['current']['commit'] = self.gate_build['commit']
            self.artifacts['current']['built_by'] = 'development snapshot gate ' + self.gate_build['commit'][:12]
        else:
            super().build()
        self.archived = old.archive(self.baseline, self.repo, self.out / 'old-archive')     # the comparator runs the UNMODIFIED old tree

    def _build_pinned(self):
        """Drill.build with the PREVIOUS wheel reused from the verified stored pin (same bytes, same sha256) instead of rebuilt; the current
        wheel follows the same rule as before (the gate's wheel when a gate is cited, else built from this checkout)."""
        archived = old.archive(self.baseline, self.repo, self.out)
        keys = ('WF_WHEEL', 'WF_WHEEL_SHA256')
        saved = {k: os.environ.get(k) for k in keys}
        try:
            for name, repo, commit, pin in [('previous', archived, self.baseline, (self.baseline_pin['wheel'], self.baseline_pin['wheel_sha256'])),
                                            ('current', self.repo, self.git('rev-parse', 'HEAD'),
                                             (self.gate_build['wheel'], self.gate_build['wheel_sha256']) if self.gate_build else None)]:
                for k, v in saved.items():
                    if v is None: os.environ.pop(k, None)
                    else: os.environ[k] = v
                if pin: os.environ['WF_WHEEL'], os.environ['WF_WHEEL_SHA256'] = pin
                folder = self.out / name; folder.mkdir()
                with build_source(repo, use_gate_wheel=pin is not None or name == 'current'):
                    path, _, spec = wheel.build_wheel(folder)
                self.artifacts[name] = {'wheel': str(path), 'wheel_sha256': sha(path), 'commit': commit,
                                        'source_dirty': self.git('status', '--porcelain').splitlines() if name == 'current' else [],
                                        'source': str(repo), 'modules': sorted(spec[0]), 'packages': sorted(spec[1])}
        finally:
            for k, v in saved.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
        if self.artifacts['previous']['wheel_sha256'] != self.baseline_pin['wheel_sha256']: raise LedgerError('the drill did not reuse the pinned baseline wheel')
        self.artifacts['previous']['pinned_from'] = self.baseline_pin['wheel']
        if self.gate_build:
            if self.artifacts['current']['wheel_sha256'] != self.gate_build['wheel_sha256']: raise LedgerError('the drill did not reuse the gate wheel')
            self.artifacts['current']['commit'] = self.gate_build['commit']
            self.artifacts['current']['built_by'] = 'development snapshot gate ' + self.gate_build['commit'][:12]
        runtime = self.out / 'runtime'; runtime.mkdir()
        self.python = wheel.make_venv(runtime)
        self.install('previous', fresh=True)
        self.archived = old.archive(self.baseline, self.repo, self.out / 'old-archive')     # the comparator runs the UNMODIFIED old tree

    def artifact(self, name):
        art = self.artifacts[name]
        rel = Path('wheels') / name / Path(art['wheel']).name
        target = self.out / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(art['wheel'], target)
        row = {'commit': art['commit'], 'wheel_sha256': art['wheel_sha256'], 'wheel': rel.as_posix()}
        if art.get('pinned_from'): row['pinned_from'] = art['pinned_from']
        return row

    def identity(self, name='current'):
        return {'commit': self.artifacts[name]['commit'], 'wheel_sha256': self.artifacts[name]['wheel_sha256']}

    def receipt(self, name, **fields):
        body = {'kind': name, 'release': self.release, 'result': 'pass', 'simulated': False, 'at': fields.pop('at', now()),
                'provenance': {'kind': 'real', 'source': 'wfkit.release_bundle on generated temporary fixtures (installed wheel, ledger copy)'},
                **self.identity(fields.pop('artifact', 'current')), **fields}
        path = self.receipts_dir / f'{name}.json'
        if path.exists():
            path = self.receipts_dir / f"{name}-{self.counter:02}.json"
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1).encode('utf-8')
        path.write_bytes(raw)
        return {'path': path.relative_to(self.out).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest()}

    def install_receipt(self, record, artifact_name, extra=None, name='installed'):
        """A release_check install observation from one drill capture record."""
        art = self.artifacts[artifact_name]
        with zipfile.ZipFile(art['wheel']) as archive: members = set(archive.namelist())
        new_modules = sorted(members - self.previous_members) if artifact_name == 'current' else sorted(members)
        new_modules = [m for m in new_modules if m.endswith('.py')] or sorted(m for m in members if m.endswith('.py'))
        control = self.checkout_control()
        fields = {'exit_code': record['exit_code'], 'command': [str(self.python), '-I', '-c', '<recorded bootstrap>'], 'venv': str(self.python.parent.parent),
                  'fresh_venv': True, 'state_root': str(self.state), 'site': [str(Path(s)) for s in self.sites], 'checkout': str(self.repo),
                  'boundary_violations': record['boundary_violations'], 'checkout_control_refused': control['refused'], 'checkout_control': control,
                  'new_modules': new_modules, 'loaded': record['loaded'], 'label': record['label'], 'script_sha256': record['script_sha256'],
                  'log': record['log'], 'log_sha256': record['log_sha256'], 'at': record['at']}
        fields.update(extra or {})
        return self.receipt(name, artifact=artifact_name, **fields)

    def checkout_control(self):
        """The negative control of T33a: the same import run with the checkout on sys.path must be REFUSED by the boundary check."""
        if getattr(self, '_control', None): return self._control
        body = 'import onecrew.v2.plan, onecrew.v2.compat_scan\n'
        dump, tail = wheel.run_case(self.python, body, env_extra={'PYTHONPATH': str(self.repo)}, flags=(), cwd=self.repo)
        with build_source(self.artifacts['current']['source']):
            ctx = wheel.build_ctx(self.python, self.artifacts['current']['modules'], self.artifacts['current']['packages'])
        from onecrew.v2 import boundary
        violations = boundary.violations(dump['end'], ctx) if dump else ['no module inventory: ' + tail[-200:]]
        self._control = {'refused': bool(violations), 'violations': violations[:5], 'command': [str(self.python), '-c', '<checkout import>'], 'pythonpath': str(self.repo)}
        return self._control

    # -- the five points -------------------------------------------------------------------------------------------------------------------
    def execute(self):
        drill = super().execute()                                 # build, upgrade, blocked scan, allowed scan, old install, roll-forward, reconcile, finding
        with zipfile.ZipFile(self.artifacts['previous']['wheel']) as archive: self.previous_members = set(archive.namelist())
        self.sites = self._sites_of('rolled-forward-read')
        self.pristine_ids = {row['id'] for row in preservation_rows(self.out / 'source-state')}
        bundle = {'schema': 1, 'release': self.release, 'mode': 'real', 'sandbox': str(self.out),
                  'artifacts': {'previous': self.artifact('previous'), 'current': self.artifact('current')},
                  'gate_history': [], 'deliveries': [], 'monitored_files': self.monitored(), 'checks': {}}
        bundle['checks']['installed'] = self.point_installed()
        bundle['checks']['upgrade'] = self.point_upgrade(drill)
        bundle['checks']['events'] = self.point_events()
        bundle['checks']['rollback'] = self.point_rollback(drill)
        if self.release == 'RP':
            bundle['provider_bundle'], self.provider_notes = self.provider_bundle()
        bundle['checks']['notes'] = self.point_notes()
        if self.history_paths:
            bundle['gate_history'] = self.history_refs(); bundle['blockers'] = []          # judged by the ordinary INPUTS rule
        else:
            fields, bundle['blockers'] = prerequisite_fields(self.first_release, self.identity('previous'))
            bundle.update(fields)
        (self.out / 'bundle.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding='utf-8')
        verdict = release_check.decide(bundle, self.out, allow_simulated=False)
        verdict['drill_receipt'] = str(self.out / 'receipt.json'); verdict['bundle'] = str(self.out / 'bundle.json')
        (self.out / 'release-check.json').write_text(json.dumps(verdict, ensure_ascii=False, indent=1), encoding='utf-8')
        return verdict

    def history_refs(self):
        """The CG- receipts copied byte-for-byte into the bundle (release_check reads them by relative path + sha256)."""
        refs, folder = [], self.out / 'history'
        folder.mkdir(exist_ok=True)
        for i, path in enumerate(self.history_paths):
            raw = path.read_bytes(); target = folder / f'{i:02}-{path.name}'
            target.write_bytes(raw)
            refs.append({'path': target.relative_to(self.out).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest(), 'source': str(path)})
        return refs

    def _sites_of(self, label):
        rec = next(r for r in self.records if r['label'] == label)
        sites = set()
        for module in rec['loaded']:
            path = Path(module['path'])
            sites.add(str(path.parents[len(Path(module['archive_path']).parts) - 1]))
        return sorted(sites)

    def monitored_paths(self):
        """Live inventory: files OUTSIDE the sandbox that the drill must not touch — the repo's frozen manifests and, READ-ONLY (hash only), the
        owner's real ledger if it exists on this machine. Their hashes before == after is what release_check demands."""
        paths = [self.repo / 'wfkit' / 'development-manifest.json', self.repo / 'wfkit' / 'manifest.json']
        real = Path(os.environ.get('ONECREW_REAL_STATE_ROOT', r'D:\TamNT\Workspace\11.OneCrew\state-v2-real')) / 'ledger.sqlite3'
        if real.exists(): paths.append(real)
        return paths

    def monitored(self):
        return [{'path': p, 'before': h, 'after': sha(p)} for p, h in self._monitored_before.items()]

    def point_installed(self):
        """T54.1 (review a2476ab P1): the release's declared BEHAVIOUR scenarios (tests/wf_scenarios_*.py) run on the installed current wheel in the
        drill's venv — each with assertions on results and the event kinds it must write — plus the common installed steps on the drill ledger.
        The receipt carries every scenario record; release_check judges them against its own inventory (an import-only probe cannot pass)."""
        with build_source(self.artifacts['current']['source']):
            ctx = wheel.build_ctx(self.python, self.artifacts['current']['modules'], self.artifacts['current']['packages'])
        self.scenario_receipts = scenarios.run_release(self.release, self.python, ctx, self.out / 'scenarios', self.artifacts['current']['commit'],
                                                       self.artifacts['current']['wheel_sha256'])
        failed = [r for r in self.scenario_receipts if r['result'] != 'pass']
        (self.out / 'scenarios' / 'summary.json').write_text(json.dumps([{k: r[k] for k in ('scenario', 'result', 'reasons', 'requirements', 'expected_events', 'missing_events')}
                                                                           for r in self.scenario_receipts], ensure_ascii=False, indent=1), encoding='utf-8')
        if failed: raise LedgerError('installed behaviour scenarios failed: ' + '; '.join(f"{r['scenario']}: {r['reasons']}" for r in failed)[:900])
        exe = self.python.with_name('onecrew' + ('.exe' if os.name == 'nt' else ''))
        probes = SCENARIOS.get(self.release, '')
        body = f'''
import json, os, sys, subprocess, tempfile, hashlib
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import plan, verdict, compat, compat_scan, report, findings, estimates, context, exceptions
root = Path({str(self.project)!r}); state = Path({str(self.state)!r}); ledger = Ledger(root, state)
exe = {str(exe)!r}
assert Path(exe).exists(), exe
steps = []
def cli(*args, expect=0):
    done = subprocess.run([exe, '--project', str(root), '--state-root', str(state), *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                          env={{**os.environ, 'PYTHONUTF8': '1'}})
    steps.append({{'command': [exe, *args], 'exit_code': done.returncode, 'tail': (done.stdout + done.stderr)[-300:]}})
    assert done.returncode == expect, (args, done.returncode, done.stdout[-400:], done.stderr[-400:])
    return done.stdout
cli('plan', 'show', 'legacy')
cli('plan', 'digest')
cli('compat', 'scan', '--json')
assert 'legacy' in report.render_report(state, 'legacy')
{probes}
_RESULT = {{'steps': steps, 'release': {self.release!r}}}
'''
        result, _ = self.capture(f'installed-scenario-{self.release}', body)
        extra = {'scenario': result, 'scenarios': self.scenario_receipts,
                 'requirements_map': {r['scenario']: r['requirements'] for r in self.scenario_receipts}}
        if self.release in ('RX1', 'RX2'):
            extra['adapter_runs'] = self.adapter_runs()
        return self.install_receipt(self.records[-1], 'current', extra)

    def adapter_runs(self):
        """RX1/RX2: the doc / data / ops roots run end to end from the installed build (tests.wf_installed_adapters, W40-RX1/RX2)."""
        from tests import wf_installed_adapters as ia
        with build_source(self.artifacts['current']['source']):
            ctx = wheel.build_ctx(self.python, self.artifacts['current']['modules'], self.artifacts['current']['packages'])
        wanted = ('doc',) if self.release == 'RX1' else ('data', 'ops')
        runs_dir = self.out / 'adapter-runs'; runs_dir.mkdir(exist_ok=True)
        rows = ia.run_installed_adapters(self.python, runs_dir, ctx, adapters=wanted, commit=self.artifacts['current']['commit'],
                                         wheel_sha256=self.artifacts['current']['wheel_sha256'])
        for row in rows:
            if row['result'] != 'pass' or row['boundary_violations']: raise LedgerError('installed adapter scenario did not pass: ' + json.dumps(row)[:300])
        return rows

    def point_upgrade(self, drill):
        before = preservation_rows(self.out / 'source-state')              # the pristine fixture (what the previous build wrote + the seeded rows)
        after = [row for row in self._after_upgrade_rows if row['id'] in self.pristine_ids]
        return self.receipt('upgrade', **{'from': self.identity('previous'), 'to': self.identity('current')}, state_root=str(self.state),
                            source_state_root=str(self.out / 'source-state'), before=before, after=after,
                            at=next(r['at'] for r in self.records if r['label'] == 'upgraded-read'))

    def point_events(self):
        """T54.3: write the current code's events on a COPY of the legacy root and classify what was really written; S/G/C of the old binary
        before and after (comparator on the archived previous build)."""
        work = rollback.copy_ledger(self.out / 'source-state', self.out / 'events-state')
        binary = old.OldVersion(self.archived)
        reading_before = old.read(binary, self.project, rollback.copy_ledger(work, self.out / 'events-before'), 'legacy')
        result, _ = self.capture('events-written-by-current', f'''
import json, sys
from onecrew.ledger import Ledger
from onecrew.v2 import plan, verdict, compat, context, estimates, exceptions
ledger = Ledger({str(self.project)!r}, {str(work)!r})
with ledger.transaction() as conn:
    task = plan.anchor_events(ledger, conn, 'plan:legacy')['task_id']
    before = [r[0] for r in conn.execute('SELECT seq FROM events WHERE task_id=? ORDER BY seq', (task,))]
shown = verdict.run(ledger, 'plan:legacy', 'M1', {str(self.project)!r})
route = None
with ledger.transaction() as conn:
    first_verdict = plan.anchor_events(ledger, conn, 'plan:legacy')['verdicts'][-1]
if first_verdict.get('result') == 'inconclusive' and 'no approved baseline' in str((first_verdict.get('test_integrity') or {{}}).get('error') or ''):
    # the fixture approval (old harness) carries no time that any commit precedes: the P1-D route -- the owner records the baseline from the
    # commit the root was approved against (here the project's first commit), then the milestone is checked again against it
    import subprocess as _sp
    first_commit = _sp.run(['git', '-C', {str(self.project)!r}, 'rev-list', '--max-parents=0', 'HEAD'], capture_output=True, text=True).stdout.split()[0]
    recorded = verdict.record_baseline(ledger, 'plan:legacy', first_commit, 'owner', 'bundle drill: fixture approval predates every commit; baseline = first commit of the sample project', {str(self.project)!r})
    shown = verdict.run(ledger, 'plan:legacy', 'M1', {str(self.project)!r})
    route = {{'first_verdict': first_verdict.get('result'), 'reason': (first_verdict.get('test_integrity') or {{}}).get('error'), 'baseline': recorded,
             'second_verdict': shown['milestones'][0]['state']}}
with ledger.transaction() as conn:
    passed = conn.execute("SELECT seq FROM events WHERE task_id=? AND kind='milestone.passed'", (task,)).fetchone()
if passed:
    context.observe(ledger, 'plan:legacy', {{'type': 'task_done', 'text': 'M1 done', 'source': {{'type': 'event', 'id': passed[0]}}}})
estimates.reforecast(ledger, 'plan:legacy', 'eta1', [30, 60], 'half done', ['fixture:eta'])
exceptions.observe(ledger, 'plan:legacy')
verdict.status(ledger, 'plan:legacy')
with ledger.transaction() as conn:
    rows = [dict(r) for r in conn.execute('SELECT seq, kind, payload FROM events WHERE task_id=? ORDER BY seq', (task,))]
written = [{{'seq': r['seq'], 'kind': r['kind'], 'payload': json.loads(r['payload'] or '{{}}'), 'anchor': 'plan:legacy', 'class': compat.event_class(r['kind'])}}
           for r in rows if r['seq'] not in before]
recorded = next((e['payload'] for e in reversed(written) if e['kind'] == 'verdict.recorded'), {{}})
integrity = recorded.get('test_integrity') or {{}}
# the namespaced roots of the drill (future, findings): every kind the current code wrote there, class B allowed on plan-ns:
ns = []
for name in ('future', 'findings'):
    try:
        with ledger.transaction() as conn:
            root = plan.anchor_events(ledger, conn, name); tid = root['task_id']
            for r in conn.execute('SELECT seq, kind, payload FROM events WHERE task_id=? ORDER BY seq', (tid,)):
                ns.append({{'seq': r['seq'], 'kind': r['kind'], 'payload': json.loads(r['payload'] or '{{}}'), 'anchor': root['selector'], 'class': compat.event_class(r['kind'])}})
    except Exception as error:   # noqa: BLE001
        ns.append({{'root': name, 'error': str(error)[:200]}})
_RESULT = {{'written': written, 'namespaced': [e for e in ns if 'kind' in e], 'milestone': shown['milestones'][0]['state'], 'baseline_route': route,
           'verdict_result': recorded.get('result'), 'integrity_classification': integrity.get('classification'), 'integrity_error': integrity.get('error')}}
''')
        reading_after = old.read(binary, self.project, rollback.copy_ledger(work, self.out / 'events-after'), 'legacy')
        # T54.3 (review a2476ab P1): the inventory is the validator's (wfkit/release_events.json); the observed kinds come from the installed behaviour
        # scenarios of this release plus what the current code wrote on the legacy anchor; each inventory kind is carried with a REAL sample event
        table = release_check.inventory(self.release)
        samples = {}
        for e in result['written']: samples.setdefault(e['kind'], {'kind': e['kind'], 'payload': e['payload'], 'anchor': 'plan:legacy', 'class': e['class'], 'source': 'legacy anchor, current code'})
        for e in result['namespaced']: samples.setdefault(e['kind'], {'kind': e['kind'], 'payload': e['payload'], 'anchor': e['anchor'], 'class': e['class'], 'source': 'drill namespaced root'})
        observed = {e['kind'] for e in result['written']} | {e['kind'] for e in result['namespaced']}
        for r in getattr(self, 'scenario_receipts', []):
            observed |= set(r['observed_events'])
            for e in r.get('event_samples', []):
                if e['kind'] not in samples and compat.event_class(e['kind']) is not None:
                    samples[e['kind']] = {'kind': e['kind'], 'payload': e['payload'], 'anchor': e['anchor'], 'class': compat.event_class(e['kind']), 'source': 'scenario ' + r['scenario']}
        new_events = [samples[k] for k in sorted(samples) if compat.event_class(k) in ('A', 'B') and (k in table['kinds'] or samples[k]['source'].startswith('legacy'))]
        # class A of the inventory: the old binary's S/G/C must be identical with the kind on the legacy anchor (W11a R0+A probe with the REAL sample payload)
        comparisons, probes = [], {}
        for kind in sorted(set(table['kinds']) | {e['kind'] for e in result['written'] if e['class'] == 'A'}):
            if compat.event_class(kind) != 'A': continue
            if kind in {e['kind'] for e in result['written']}:
                comparisons.append({'kind': kind, 'before': reading_before, 'after': reading_after, 'compare': old.compare(reading_before, reading_after), 'probe': 'written by the current code on the legacy anchor'})
                continue
            sample = samples.get(kind, {'payload': {'plan': 'legacy', 'revision': 1}})
            probe_state = rollback.copy_ledger(self.out / 'source-state', self.out / f'probe-{kind.replace(".", "-")}')
            before_probe = old.read(binary, self.project, rollback.copy_ledger(probe_state, self.out / f'probe-{kind.replace(".", "-")}-before'), 'legacy')
            self.capture(f'probe-{kind.replace(".", "-")}', f'''
import json
from onecrew.ledger import Ledger
from onecrew.v2 import plan, compat
ledger = Ledger({str(self.project)!r}, {str(probe_state)!r})
payload = dict({json.dumps(sample['payload'])!r} and json.loads({json.dumps(sample['payload'])!r}) or {{}}, plan='legacy', revision=1)
with ledger.transaction(write=True) as conn:
    task = plan.anchor_events(ledger, conn, 'plan:legacy')['task_id']
    plan.emit(ledger, conn, task, {kind!r}, payload)
_RESULT = {{'kind': {kind!r}, 'class': compat.event_class({kind!r}), 'payload': payload}}
''')
            after_probe = old.read(binary, self.project, rollback.copy_ledger(probe_state, self.out / f'probe-{kind.replace(".", "-")}-after'), 'legacy')
            comparisons.append({'kind': kind, 'before': before_probe, 'after': after_probe, 'compare': old.compare(before_probe, after_probe), 'probe': 'sample event with the scenario payload on a legacy anchor copy'})
            probes[kind] = str(probe_state)
        self.event_log = result
        # Known limit (recorded, not hidden): a legacy root approved by the OLD build has no approval base artifact, so the W05 test-integrity
        # check of the new build cannot be established and a passing command is recorded `inconclusive` (milestone `failed`), never `passed`.
        # The events written (verdict.run_started, receipt_issued, recorded, learning.outcome, estimate.eta …) and the old binary's S/G/C are
        # what T54.3 judges; the milestone state is reported as observed, with the integrity reason.
        extra = {}
        if not table['kinds']:
            extra = {'none_reason': table['none_reason'], 'regression_scenarios': [r['scenario'] for r in getattr(self, 'scenario_receipts', []) if r['result'] == 'pass']}
        return self.receipt('events', old_artifact=self.identity('previous'), old_binary='git archive ' + self.baseline + ' (unmodified)',
                            expected_kinds=list(table['kinds']), observed_kinds=sorted(observed), inventory_tasks=table['tasks'],
                            new_events=new_events, comparisons=comparisons, probes=probes, legacy_milestone=result['milestone'], baseline_route=result.get('baseline_route'),
                            legacy_verdict={'result': result['verdict_result'], 'test_integrity': result['integrity_classification'], 'reason': result['integrity_error']},
                            class_b_on_legacy_anchor=[e['kind'] for e in result['written'] if e['class'] == 'B'], **extra)

    def _scan(self, scan):
        """The scanner names its rollback target by the short revision it models (compat_scan.OLD_REVISION); the bundle compares it with the
        previous artifact's full commit, so the same commit is written in full and the scanned form is kept beside it."""
        scan = dict(scan)
        if self.git('rev-parse', scan['old_version']) != self.baseline:
            raise LedgerError('the scanner models ' + scan['old_version'] + ', the previous artifact is ' + self.baseline)
        scan['old_version_as_scanned'] = scan['old_version']; scan['old_version'] = self.baseline
        return scan

    def point_rollback(self, drill):
        rec = {r['label']: r for r in self.records}
        rejected = {'scan': self._scan(drill['rejected']['scan']), 'ledger_at_switch': drill['rejected']['scan']['ledger_sha'], 'inputs_at_switch': drill['rejected']['scan']['inputs_sha'], 'switched': False}
        allowed = {'scan': self._scan(drill['allowed']['scan']), 'ledger_at_switch': drill['allowed']['scan']['ledger_sha'], 'inputs_at_switch': drill['allowed']['scan']['inputs_sha'], 'switched': True,
                   'old_run': self.install_receipt(rec['rolled-back-read'], 'previous', name='rollback-old-run')}
        forward = self.install_receipt(rec['rolled-forward-read'], 'current', name='rollback-forward-run')
        retained = [row for row in self._after_upgrade_rows if row['id'] in self.pristine_ids]
        after_rows = preservation_rows(self.state, self.pristine_ids)                 # taken at roll-forward completion, before any reconcile
        fields = {'rejected': rejected, 'allowed': allowed, 'forward_run': forward, 'before': retained, 'after': after_rows,
                  'frozen_active_copies': drill['frozen_active_copies']}
        if self.release in ('R05', 'R08'):
            # T54e [E6]: every intent that was `unknown` in the retained state is reconciled before its root continues. The drill's own unknown
            # action (root `future`) was reconciled, then continued (drill['reconcile']); the retained fixture attempt ATT-fixture is reconciled
            # here through the real Supervisor/Control path — its launch identity is unavailable, so the recorded outcome is "manual
            # reconciliation required" and NOTHING continues it (no effect, no retry). Both are in the timeline with their ledger sequence.
            timeline, unknown = [], drill['reconcile']
            for e in unknown['events']:
                payload = json.loads(e['payload']) if isinstance(e['payload'], str) else e['payload']
                kind = 'reconciled' if e['kind'] == 'action.reconciled' else 'continued'
                timeline.append({'seq': e['seq'], 'kind': kind, 'intent': payload.get('id') or payload.get('action') or 'ATT-fixture'})
            retained_unknown = [a['id'] for row in retained for a in row['attempts'] if a['status'] == 'unknown']
            result, _ = self.capture('reconcile-retained-unknown', f'''
import json
from onecrew.ledger import Ledger
from onecrew.control_core import Control
from onecrew.process_core import Supervisor
ledger = Ledger({str(self.project)!r}, {str(self.state)!r}); control = Control(ledger)
out = {{}}
for attempt_id in {retained_unknown!r}:
    before = control.attempt(attempt_id)['status']
    outcome = Supervisor(control).reconcile(attempt_id)
    after = control.attempt(attempt_id)
    with ledger.transaction() as conn:
        seq = conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
        task_events = [r[0] for r in conn.execute("SELECT kind FROM events WHERE task_id=? ORDER BY seq", (after['task_id'],))]
    out[attempt_id] = {{'before': before, 'outcome': outcome, 'status_after': after['status'], 'seq': int(seq),
                       'continued': any(k in ('action.executing', 'node.resumed', 'node.started') for k in task_events[-3:])}}
_RESULT = out
''')
            for attempt_id, row in result.items():
                if row['continued']: raise LedgerError('a retained unknown intent was continued: ' + attempt_id)
                timeline.append({'seq': row['seq'] + len(timeline), 'kind': 'reconciled', 'intent': attempt_id, 'outcome': row['outcome'],
                                 'status_after': row['status_after'], 'continued': False})
            fields['intent_events'] = timeline
            fields['retained_unknown_reconcile'] = result
            fields['effect_replays_before_reconcile'] = unknown['effect_replays_before_reconcile']
        return self.receipt('rollback', **fields)

    def provider_bundle(self):
        """RP / T54i [E7]: the six real cells of W45 (matrix.json + receipts copied into this bundle so release_check reads them by hash), judged by the
        shared evaluator; the notes receipt carries the same states, the usable subset and the P1.0 count/label ('subset' unless 6/6)."""
        if not self.matrix_dir or not (self.matrix_dir / 'matrix.json').exists():
            raise LedgerError('RP needs --matrix <wfkit.provider_matrix output>: the six provider cells must be real receipts (W45)')
        matrix = json.loads((self.matrix_dir / 'matrix.json').read_text(encoding='utf-8'))
        source = {'commit': matrix['commit'], 'wheel_sha256': matrix['wheel_sha256']}
        # HL validity (03 §5.2, review a2476ab §9): a cell receipt is evidence of the build it ran on. When this bundle's artifact is another
        # build, the receipts keep their own identity (never re-hashed), the source artifact is the matrix build, and the shared evaluator
        # gives `recheck` for every pass without a comparison proving the cell's path unchanged — not `usable`. No paid provider is re-run here.
        inherited = source == self.identity('current')
        target = self.out / 'provider-matrix'; target.mkdir()
        items = []
        for item in matrix['items']:
            src = self.matrix_dir / item['original']['path']
            dst = target / Path(item['original']['path']).name; dst.write_bytes(src.read_bytes())
            if hashlib.sha256(dst.read_bytes()).hexdigest() != item['original']['sha256']: raise LedgerError('matrix receipt hash changed: ' + item['id'])
            items.append({'id': item['id'], 'original': {'path': dst.relative_to(self.out).as_posix(), 'sha256': item['original']['sha256']}, 'supplements': []})
        rows = [{k: v for k, v in row.items() if k not in ('receipt',)} for row in matrix['rows']]
        from wfkit import provider_evidence
        from wfkit.finalgate import evidence_status
        reader = release_check.Receipts(self.out, False)
        for row, item in zip(rows, items):                       # the status claimed for THIS artifact is what the shared rule gives, never the old label
            row['status_on_matrix_build'] = row['status']
            row['status'] = evidence_status(reader.read(item['original']), [], self.identity('current'), None, row['id'])['status']
        states = provider_evidence.evaluate(rows, items, reader, source, self.identity('current'), None)
        eligible = sorted(k for k, st in states.items() if st['status'] == 'usable')
        bundle = {'artifacts': {'final': self.identity('current'), 'pilot': source}, 'providers': rows, 'comparison': {'items': items},
                  'source': {'matrix': str(self.matrix_dir / 'matrix.json'), 'at': matrix['at'], 'task': 'W45', 'same_build': inherited,
                             'note': None if inherited else 'matrix receipts are evidence of build ' + source['commit'][:12] + '; for this build every passed cell is `recheck` until W45 runs on it (owner permission for that run)'}}
        notes = {'provider_states': states, 'subset': eligible, 'p1_count': len(eligible), 'p1_label': 'full' if len(eligible) == 6 else 'subset'}
        return bundle, notes

    def point_notes(self):
        path = NOTES_DIR / f'{self.release}.md'
        if not path.exists(): raise LedgerError('release notes missing: ' + str(path))
        text = path.read_text(encoding='utf-8')
        extra = getattr(self, 'provider_notes', None) or {}
        return self.receipt('notes', markdown=text, notes_path=str(path.relative_to(self.repo)), notes_sha256=sha(path), real_checks=[],
                            gate_decision=self.gate_decision, **extra)

    # -- the drill, with the preservation rows taken at the right moments ------------------------------------------------------------------
    def install(self, name, fresh=False):
        super().install(name, fresh)
        if name == 'current' and getattr(self, 'state', None) and not hasattr(self, '_after_upgrade_rows') and (Path(self.state) / 'ledger.sqlite3').exists():
            self._after_upgrade_rows = preservation_rows(self.state)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('release', choices=RELEASES); result.add_argument('--out', required=True)
    result.add_argument('--gate', help='decision.json of the development snapshot gate this bundle cites')
    result.add_argument('--matrix', help='RP only: output dir of wfkit.provider_matrix (the real W45 six-cell matrix)')
    result.add_argument('--gate-history', action='append', help='a CG- delivery gate receipt (repeatable): the latest PASSING one is the previous build (normal rule)')
    result.add_argument('--baseline-wheel', help='reuse this stored, verified baseline wheel (sidecar <wheel>.json) instead of rebuilding the baseline')
    result.add_argument('--first-release', action='store_true',
                        help='claim the FIRST delivery: pin the previous artifact as a compat baseline (never delivered/accepted); judged as INPUTS(bootstrap)')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    gate = json.loads(Path(args.gate).read_text(encoding='utf-8')) if args.gate else None
    try:
        verdict = Producer(args.release, args.out, gate=gate, matrix=args.matrix, first_release=args.first_release, baseline_wheel=args.baseline_wheel,
                           gate_history=args.gate_history).execute()
        print(json.dumps({'release': args.release, 'decision': verdict['decision'], 'conditions': verdict['conditions'],
                          'reasons': verdict['reasons'], 'out': args.out}, ensure_ascii=False))
        return 0 if verdict['decision'] == 'pass' else 2
    except (OSError, ValueError, RuntimeError, LedgerError, subprocess.SubprocessError) as error:
        print(json.dumps({'release': args.release, 'decision': 'refused', 'reason': str(error)[-800:]}, ensure_ascii=False)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
