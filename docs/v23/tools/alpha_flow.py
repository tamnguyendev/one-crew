r"""alpha_flow.py <package dir> <work dir> [--owner-step auto|fixture] - the 2.3 ALPHA flow FROM A BUILT PACKAGE, with the INSTALLED onecrew CLI.

Stdlib only; run it with `python -I` from anywhere (it never imports a checkout). Four stages on a new sample Git project and a new ledger:
  S1 init + wiki: `onecrew init` creates the wiki skeleton (docs/wiki: README.md, project.md, lessons.md); a second `init` changes no byte of it
     (reuse); a page of project rules is added; `wiki pages` reads its entries and no problem.
  S2 a task gets the knowledge it may use: plan P1 (a.txt must hold the required word), node C reads a.txt + spec.txt and writes a.txt;
     `wiki show` gives C the rule `a-value` as a mandatory fact.
  S3 a checked result becomes knowledge with evidence: C's worker claims "VALUE: right" citing spec.txt under check M1; the check really runs
     on C's candidate and passes; `wiki history` then holds the record, visible to the project, with its evidence.
  S4 a new root uses it, within permission: plan P2 node D (reads a.txt, b.txt, spec.txt; writes b.txt) is given the record; its worker, whose
     own default is wrong, follows it and D's check passes; node E of plan P3, which can read only c.txt, is given neither the record nor the rule.
  S5 the alpha guards (AL-01, AL-02): a wiki page that is a hard link to a file outside the project is not read and is named; a node whose scope
     holds such a file is not started, the step names the hard link, and nothing of the file reaches the ledger.
Worker: the package's fake `claude` (verify/onecrew_fake_claude.py, a test double: no model, no login, no provider call). It proves the path,
the labels and the guards; it never proves that a model understands or uses knowledge.
Owner step: `onecrew owner approve` is the owner's verb and is refused in an AI tool session. --owner-step auto (default): outside such a session
the real verb runs; inside one, the approval is the fixture approval of the package drills (plan.approve(..., 'owner', ...) on this run's own
temporary ledger) and the log says `fixture`. --owner-step fixture forces that.
Isolation (checked): every command runs with TEMP/TMP/LOCALAPPDATA/APPDATA inside <work>\env, without PYTHON*, ONECREW_*, GIT_* and AI-session
variables, from a fresh venv under <work> (a path with spaces), on a project and a ledger under <work>. The user's real
%LOCALAPPDATA%\OneCrew\hook-projects.json and %USERPROFILE%\.claude\settings.json are only read: their SHA256 before and after must match.
Writes <work>\alpha-flow-log.json and <work>\feedback-alpha.zip (this run's logs and wiki pages: send it back with any feedback).
Exit 0 when every stage passed, 1 when one failed, 2 when it refused to start (missing file, work folder not empty)."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

AI_MARKERS = ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDE_CODE_ENTRYPOINT')
DROPPED = re.compile(r'^(PYTHON|ONECREW_|GIT_|VIRTUAL_ENV)', re.I)
CAPS = ['--capability', 'namespaced-storage', '--capability', 'root-budget', '--capability', 'internal-plan', '--capability', 'sequential-engine']
SKELETON = ('README.md', 'project.md', 'lessons.md')
CLAIM = 'Files of this project hold the required word VALUE: right (spec.txt).'
SECRET, TOKEN = 'API_KEY=alpha-do-not-read', 'alpha-do-not-read'
STAGES = ['S0', 'S1', 'S2', 'S3', 'S4', 'S5']


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def sha_file(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def tree_hashes(folder):
    return {p.relative_to(folder).as_posix(): sha_file(p) for p in sorted(Path(folder).rglob('*')) if p.is_file()}


class Flow:
    def __init__(self, pkg, work, owner_step):
        self.pkg, self.work = pkg, work
        self.logs = work / 'logs'; self.logs.mkdir(parents=True)
        self.venv = work / 'venv with space'
        self.proj = work / 'project mau'
        self.ledger = work / 'so thu'
        self.onecrew = self.venv / 'Scripts' / 'onecrew.exe'
        self.vpy = self.venv / 'Scripts' / 'python.exe'
        self.n = 0
        self.commands = []
        env_dir = work / 'env'
        for sub in ('temp', 'localappdata', 'appdata'): (env_dir / sub).mkdir(parents=True)
        base = {k: v for k, v in os.environ.items() if not DROPPED.match(k) and k not in AI_MARKERS}
        base.update(TEMP=str(env_dir / 'temp'), TMP=str(env_dir / 'temp'), LOCALAPPDATA=str(env_dir / 'localappdata'), APPDATA=str(env_dir / 'appdata'),
                    PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        self.env = base
        in_ai = any(os.environ.get(k) for k in AI_MARKERS)
        self.owner_mode = 'fixture' if owner_step == 'fixture' or in_ai else 'real'
        self.in_ai_session = in_ai

    def run(self, label, argv, *, env=None, ok=(0,), cwd=None):
        self.n += 1
        done = subprocess.run([str(a) for a in argv], capture_output=True, env=env or self.env, cwd=str(cwd or self.work), timeout=600)
        out, err = done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace')
        name = f'{self.n:02d}-{label}.txt'
        (self.logs / name).write_text(f'$ {" ".join(str(a) for a in argv)}\nexit {done.returncode}\n--- stdout\n{out}\n--- stderr\n{err}', encoding='utf-8')
        self.commands.append({'label': label, 'exit': done.returncode, 'log': name})
        if done.returncode not in ok:
            raise StageFailed(f'{label}: exit {done.returncode}: {(err or out).strip()[-400:]}')
        return out

    def oc(self, label, *args, ok=(0,), env=None):
        return self.run(label, [self.onecrew, '--project', self.proj, '--state-root', self.ledger, *args], ok=ok, env=env)

    def oc_json(self, label, *args, env=None):
        text = self.oc(label, *args, env=env)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise StageFailed(f'{label}: the output is not JSON: {text.strip()[:300]}')

    def git(self, *args):
        return self.run('git', ['git', '-C', self.proj, *args]).strip()

    def approve(self, name):
        if self.owner_mode == 'real':
            value = self.oc_json(f'owner-approve-{name}', 'owner', 'approve', name, '--reference', f'owner approves the alpha flow plan {name}')
            return value.get('status')
        code = ('import sys; from onecrew.ledger import Ledger; from onecrew.v2 import plan; '
                'print(plan.approve(Ledger(sys.argv[1], sys.argv[2]), sys.argv[3], "owner", '
                '"fixture: the alpha flow approval in an AI session, on its own temporary ledger; not an owner action")["status"])')
        return self.run(f'fixture-approve-{name}', [self.vpy, '-I', '-c', code, self.proj, self.ledger, name]).strip()

    def receipt(self, key):
        return json.loads((self.ledger / 'snapshots' / 'blobs' / key).read_text(encoding='utf-8'))

    def policy(self, name, **value):
        path = self.work / f'policy-{name}.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        env = dict(self.env, PATH=str(self.venv / 'Scripts') + os.pathsep + self.env.get('PATH', ''), ONECREW_FAKE_POLICY=str(path),
                   ONECREW_FAKE_LOG=str(self.work / 'fake.jsonl'))
        return env


class StageFailed(Exception):
    pass


def contract(template, target, python):
    value = json.loads(template)
    text = json.dumps(value).replace('PYTHON_EXE', python.replace('\\', '/')).replace('a.txt', target)
    value = json.loads(text)
    value['title'] = f'Write {target} by the project knowledge (alpha flow)'
    value['authority']['apply_to_project'] = True          # the checked result is delivered into the sample project, so later roots see it there
    return value


def nodes(nid, read, write):
    pin = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
    common = {'input': [], 'output': [f'{write} holds the required value'], 'acceptance': ['O1'], 'resources': [], 'estimate_seconds': [5, 120],
              'execution_cap_seconds': 180, 'budget_calls': 1, 'executor': dict(pin)}
    item = dict(common, id=nid, goal=f'Write {write} with the value the project requires.', depends=[], read=read, write=[write],
                checks=[{'id': 'M1', 'spec': f'{write} holds the value the project requires.'}], integration=False)
    integ = dict(common, id='I', goal=f'Integrate: read the result of node {nid} and report. Write nothing.', depends=[{'node': nid, 'requires': 'verified'}],
                 read=[write], write=[], checks=[{'id': 'M1', 'spec': f'{write} holds the value the project requires.'}], integration=True)
    return {'reason': f'alpha flow: node {nid} writes {write}, node I integrates', 'evidence': [f'{write}:1'], 'nodes': [item, integ]}


def entries_of(package):
    return {e.get('id'): e for e in (package.get('entries') or [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('package'); ap.add_argument('work'); ap.add_argument('--owner-step', choices=['auto', 'fixture'], default='auto')
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):                 # a cp1252 console never stops the run: what it cannot show is escaped
        try: stream.reconfigure(errors='backslashreplace')
        except (AttributeError, ValueError): pass
    pkg, work = Path(args.package).resolve(), Path(args.work).resolve()
    manifest_path = pkg / 'manifest.json'
    if not manifest_path.is_file():
        print(f'KHONG DAT: no manifest.json in {pkg}'); return 2
    if work.exists() and any(work.iterdir()):
        print(f'KHONG DAT: the work folder is not empty, an old result is never read as this one: {work}'); return 2
    if pkg == work or pkg in work.parents:
        print(f'KHONG DAT: the work folder is inside the package: {work}'); return 2
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    wheel = pkg / 'wheel' / manifest['wheel']['name']
    ex = pkg / 'examples' / 'first-task'
    for needed in (wheel, ex / 'contract.json', ex / 'docs' / 'wiki' / 'rules.md', pkg / 'verify' / 'make_fake_claude_wheel.py'):
        if not Path(needed).is_file():
            print(f'KHONG DAT: the package lacks {needed}'); return 2
    work.mkdir(parents=True, exist_ok=True)
    real = {'hook-projects.json': Path(os.environ.get('LOCALAPPDATA', '')) / 'OneCrew' / 'hook-projects.json',
            'claude settings.json': Path(os.environ.get('USERPROFILE', '')) / '.claude' / 'settings.json'}
    before = {k: sha_file(p) for k, p in real.items()}
    pkg_before = tree_hashes(pkg)
    log = {'kind': 'alpha-flow-log', 'package': str(pkg), 'work': str(work), 'started': now(), 'manifest': manifest,
           'worker': 'fake claude (test double): no model, no provider call', 'stages': [], 'proves': [
               'the four alpha stages run from the installed wheel, outside any checkout, on a sample project and a temporary ledger',
               'knowledge is given by permission and applicability; a result becomes knowledge only with a check that really ran'],
           'does_not_prove': ['that a real model understands or uses the wiki', 'use with the real ledger, other providers, a real project']}
    flow = Flow(pkg, work, args.owner_step)
    log.update(owner_step_mode=flow.owner_mode, in_ai_session=flow.in_ai_session)
    stage = None

    def begin(sid, title):
        nonlocal stage
        stage = {'id': sid, 'title': title, 'result': 'fail', 'observed': {}}
        log['stages'].append(stage)
        print(f'{sid} {title}')

    def check(condition, what):
        stage['observed'].setdefault('checks', []).append({'what': what, 'ok': bool(condition)})
        if not condition: raise StageFailed(what)

    try:
        # ---- setup: venv, wheel, fake claude, sample project
        begin('S0', 'venv with the package wheel, the fake claude, a sample Git project')
        flow.run('venv', [sys.executable, '-m', 'venv', flow.venv])
        flow.run('pip-onecrew', [flow.vpy, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', wheel])
        version = flow.run('version', [flow.vpy, '-I', '-c', "import importlib.metadata as m; print(m.version('onecrew'))"]).strip()
        origin = flow.run('origin', [flow.vpy, '-I', '-c', 'import onecrew, pathlib; print(pathlib.Path(onecrew.__file__).resolve())']).strip()
        flow.run('fake-wheel', [sys.executable, '-I', pkg / 'verify' / 'make_fake_claude_wheel.py', work / 'fake'])
        fake_whl = next((work / 'fake').glob('onecrew_fake_claude-*.whl'))
        flow.run('pip-fake', [flow.vpy, '-I', '-m', 'pip', 'install', '--no-index', '--no-build-isolation', fake_whl])
        claude = shutil.which('claude', path=str(flow.venv / 'Scripts'))
        log['onecrew_version'] = version
        stage['observed'].update(version=version, module=origin, claude=claude)
        check(version == manifest['version'], f'the installed onecrew is {version}, the manifest says {manifest["version"]}')
        check('site-packages' in origin and str(flow.venv).lower() in origin.lower(), 'onecrew is imported from the venv, not from a checkout')
        flow.proj.mkdir()
        flow.git('init', '-q'); flow.git('config', 'user.name', 'alpha flow'); flow.git('config', 'user.email', 'alpha-flow@localhost')
        flow.git('config', 'core.autocrlf', 'false')
        for name, text in (('a.txt', 'base\n'), ('b.txt', 'base\n'), ('c.txt', 'base\n'),
                           ('spec.txt', 'The project requires one word, the same in a.txt and b.txt; the wiki and the checks say which.\n'),
                           ('.gitignore', '.onecrew/\n.claude/\n')):
            (flow.proj / name).write_bytes(text.encode('utf-8'))
        flow.git('add', '.'); flow.git('commit', '-q', '-m', 'base')
        stage['result'] = 'pass'

        # ---- S1
        begin('S1', 'init creates the wiki, a second init reuses it unchanged, a rules page is read')
        flow.run('init', [flow.onecrew, 'init', '--project', flow.proj, '--state-root', flow.ledger, '--yes'], ok=(0, 1))
        wiki = flow.proj / 'docs' / 'wiki'
        created = sorted(p.name for p in wiki.iterdir()) if wiki.is_dir() else []
        check(created == sorted(SKELETON), f'init created the wiki skeleton {sorted(SKELETON)}, found {created}')
        first = flow.oc_json('wiki-pages-empty', 'wiki', 'pages')
        pages = first.get('pages') or []
        stage['observed']['skeleton_pages'] = [(p.get('path'), len(p.get('entries') or [])) for p in pages]
        check(len(pages) == 3 and all(not p.get('entries') for p in pages) and not first.get('problems'), 'the skeleton has 3 pages, no entry, no problem')
        hashes = tree_hashes(wiki)
        flow.run('init-again', [flow.onecrew, 'init', '--project', flow.proj, '--state-root', flow.ledger, '--yes'], ok=(0, 1))
        check(tree_hashes(wiki) == hashes, 'a second init changes no byte of the wiki')
        sha = flow.git('rev-parse', 'HEAD')
        page = (ex / 'docs' / 'wiki' / 'rules.md').read_text(encoding='utf-8').replace('"revision": "HEAD"', f'"revision": "{sha}"')
        (wiki / 'rules.md').write_bytes(page.encode('utf-8'))
        flow.git('add', 'docs'); flow.git('commit', '-q', '-m', 'wiki rules')
        second = flow.oc_json('wiki-pages', 'wiki', 'pages')
        ids = sorted(e.get('id') for p in second.get('pages') or [] for e in p.get('entries') or [] if e.get('id'))
        stage['observed'].update(entry_ids=ids, problems=second.get('problems'))
        check('a-value' in ids and 'no-two-lines' in ids and not second.get('problems'), 'the rules page gives a-value and no-two-lines, no problem')
        stage['result'] = 'pass'

        template = (ex / 'contract.json').read_text(encoding='utf-8')
        py = str(flow.vpy)

        def plan(name, target, nid, read):
            path = work / f'contract-{name}.json'
            path.write_text(json.dumps(contract(template, target, py), ensure_ascii=False), encoding='utf-8')
            flow.oc('propose-' + name, 'plan', 'propose', name, '--file', path, '--author', 'alpha-flow', '--workflow', *CAPS)
            status = flow.approve(name)
            node_file = work / f'nodes-{name}.json'
            node_file.write_text(json.dumps(nodes(nid, read, target)), encoding='utf-8')
            flow.oc('revise-' + name, 'engine', 'revise', name, '--file', node_file)
            return status

        # ---- S2
        begin('S2', 'plan P1: node C is given the rule it may use')
        status = plan('P1', 'a.txt', 'C', ['a.txt', 'b.txt', 'spec.txt'])
        shown = flow.oc_json('wiki-show-P1-C', 'wiki', 'show', '--plan', 'P1', '--node', 'C')
        given = entries_of(shown)
        stage['observed'].update(approval=status, owner_step=flow.owner_mode, given={k: [v.get('use'), v.get('must')] for k, v in given.items()})
        check(status == 'approved', f'P1 is approved ({flow.owner_mode}), status {status}')
        check(given.get('a-value', {}).get('use') == 'fact' and given['a-value'].get('must'), 'C is given a-value as a mandatory fact')
        flow.oc('wiki-show-P1-C-text', 'wiki', 'show', '--plan', 'P1', '--node', 'C', '--text')
        stage['result'] = 'pass'

        # ---- S3
        begin('S3', "C's checked result becomes knowledge with evidence")
        env = flow.policy('P1', target='a.txt', default='naive', careful=True,
                          claims=[{'kind': 'finding', 'text': CLAIM, 'applies_to': ['a.txt'], 'sources': ['spec.txt'], 'check': 'M1'}])
        which = flow.run('which-claude', ['where.exe', 'claude'], env=env).splitlines()
        check(which and str(flow.venv).lower() in which[0].lower(), f'the claude on PATH is the fake one of the venv: {which[:1]}')
        step = json.loads(flow.oc('step-P1-C', 'engine', 'step', 'P1', env=env))
        receipt = flow.receipt(step['receipt'])
        used = (receipt.get('knowledge_use') or {}).get('used') or []
        verdict = json.loads(flow.oc('verify-P1-C', 'engine', 'verify', 'P1', 'C', env=env))
        history = flow.oc_json('wiki-history-1', 'wiki', 'history')
        records = [r for r in (history.get('records') or history.get('entries') or []) if CLAIM.split(' (')[0] in (r.get('text') or '')]
        brief = [{k: r.get(k) for k in ('id', 'label', 'visibility', 'status', 'status_reason', 'evidence')} for r in records]
        stage['observed'].update(used=used, verify=verdict.get('result'), records=brief)
        check('a-value' in used, 'C declares it used a-value')
        check(verdict.get('result') == 'pass', f'the check of C passed on its candidate: {verdict.get("result")}')
        active = [r for r in records if r.get('status') == 'active']
        check(len(active) == 1, f'one active knowledge record holds the claim, found {len(active)}')
        record = active[0]
        evidence = record.get('evidence') or {}
        check(record.get('label') == 'verified' and evidence.get('status') == 'verified' and 'check M1' in (evidence.get('property') or ''),
              f'the record is verified by the check that ran: {evidence.get("property")}')
        check(record.get('visibility') == 'project', f'the record is visible to the project: {record.get("visibility")}')
        check(any(s.get('type') == 'receipt' for s in record.get('sources') or []), 'the record cites the receipts of the run and the check')
        observed = [r for r in records if r.get('label') == 'observed']
        check(all(r.get('status') == 'superseded' and record['id'] in (r.get('status_reason') or '') for r in observed) and observed,
              'the worker claim was first an observation of the root, superseded by the verified record')
        env = flow.policy('P1-I', target='a.txt', default='naive', careful=True)
        flow.oc('step-P1-I', 'engine', 'step', 'P1', env=env)
        integ = json.loads(flow.oc('verify-P1-I', 'engine', 'verify', 'P1', 'I', env=env))
        check(integ.get('result') == 'pass', 'the integration node of P1 passed')
        handoff = json.loads(flow.oc('handoff-P1', 'engine', 'handoff', 'P1', env=env))
        delivered = (flow.proj / 'a.txt').read_text(encoding='utf-8').strip()
        stage['observed'].update(handoff={k: handoff.get(k) for k in ('state', 'artifact', 'applied', 'files') if k in handoff}, project_a=delivered)
        check(delivered == 'right', f'the handoff of P1 put the checked a.txt into the project: {delivered!r}')
        flow.git('add', 'a.txt'); flow.git('commit', '-q', '-m', 'the checked result of P1')
        stage['result'] = 'pass'

        # ---- S4
        begin('S4', 'a new root uses the record; a node that cannot read its source is not given it')
        rid = record.get('id')
        status2 = plan('P2', 'b.txt', 'D', ['a.txt', 'b.txt', 'spec.txt'])
        status3 = plan('P3', 'c.txt', 'E', ['c.txt'])
        check(status2 == 'approved' and status3 == 'approved', f'P2 and P3 approved ({flow.owner_mode})')
        given_d = entries_of(flow.oc_json('wiki-show-P2-D', 'wiki', 'show', '--plan', 'P2', '--node', 'D'))
        given_e = entries_of(flow.oc_json('wiki-show-P3-E', 'wiki', 'show', '--plan', 'P3', '--node', 'E'))
        flow.oc('wiki-show-P2-D-text', 'wiki', 'show', '--plan', 'P2', '--node', 'D', '--text')
        env = flow.policy('P2', target='b.txt', default='naive', careful=True)
        step = json.loads(flow.oc('step-P2-D', 'engine', 'step', 'P2', env=env))
        receipt = flow.receipt(step['receipt'])
        used = (receipt.get('knowledge_use') or {}).get('used') or []
        verdict = json.loads(flow.oc('verify-P2-D', 'engine', 'verify', 'P2', 'D', env=env))
        stage['observed'].update(record=rid, given_e=sorted(given_e), used=used, verify=verdict.get('result'))
        uses_d = {k: [v.get('use'), (v.get('applicability') or {}).get('state')] for k, v in given_d.items()}
        stage['observed']['given_d'] = uses_d
        check(uses_d.get(rid) == ['fact', 'applies'], f'node D of the new root P2 is given the record as an applicable fact: {uses_d}')
        check(uses_d.get('a-value', [None])[0] != 'fact', 'the wiki rule checked on the old a.txt is no longer a fact for D (its source changed)')
        check(rid in used, "D's worker, whose own default is wrong, declares it used the record")
        check(verdict.get('result') == 'pass', f'the check of D passed on its candidate: {verdict.get("result")}')
        check(rid not in given_e and 'a-value' not in given_e, 'node E (reads only c.txt) is given neither the record nor a-value')
        stage['result'] = 'pass'

        # ---- S5
        begin('S5', 'guards: a wiki page or a scope file that has another name on the disk (a hard link) is never read')
        outside = work / 'outside'; outside.mkdir()
        secret = '# Secret\n\n## Key\n```onecrew\n{"id": "leak", "kind": "note", "label": "unverified"}\n```\n' + SECRET + '\n'
        (outside / 'secret.md').write_bytes(secret.encode('utf-8'))
        missed = []                                     # both guards are judged, each on its own, before the stage is decided

        def soft(condition, what):
            stage['observed'].setdefault('checks', []).append({'what': what, 'ok': bool(condition)})
            if not condition: missed.append(what)
        try:
            os.link(outside / 'secret.md', wiki / 'linked.md')
        except OSError as error:
            raise StageFailed(f'this volume cannot make a hard link, the guards cannot be shown here: {error}')
        text = flow.oc('wiki-pages-linked', 'wiki', 'pages')
        named = [p for p in json.loads(text).get('problems') or [] if p.get('path') == 'docs/wiki/linked.md']
        stage['observed']['wiki_problem'] = named
        read_pages = [p.get('path') for p in json.loads(text).get('pages') or []]
        soft('docs/wiki/linked.md' not in read_pages and TOKEN not in text, f'AL-02: the linked wiki page is not among the pages read: {read_pages}')
        soft(any('hard link' in (p.get('problem') or '') for p in named), 'AL-02: the linked wiki page is named as not read (a hard link)')
        os.remove(wiki / 'linked.md')
        (flow.proj / 'notes.txt').write_bytes(b'plain notes\n')       # an ordinary file when the plan is approved (approval refuses a link already there)
        status4 = plan('P4', 'c.txt', 'F', ['c.txt', 'notes.txt'])
        check(status4 == 'approved', f'P4 approved ({flow.owner_mode})')
        os.remove(flow.proj / 'notes.txt')
        os.link(outside / 'secret.md', flow.proj / 'notes.txt')       # the name becomes another name of a file outside the project after approval
        env = flow.policy('P4', target='c.txt', default='right', careful=True)
        out = flow.oc('step-P4-F', 'engine', 'step', 'P4', env=env, ok=(0, 1, 2))
        fake = (work / 'fake.jsonl').read_text(encoding='utf-8').splitlines() if (work / 'fake.jsonl').is_file() else []
        ran_f = [line for line in fake if json.loads(line).get('node') == 'F']
        leaked = [p.relative_to(flow.ledger).as_posix() for p in flow.ledger.rglob('*') if p.is_file() and TOKEN.encode() in p.read_bytes()]
        stage['observed'].update(step_f=out.strip()[:600], worker_ran_f=len(ran_f), ledger_files_with_secret=leaked[:5])
        soft(not leaked, f'AL-01: nothing of the linked file is in the ledger: {leaked[:3]}')
        soft(not ran_f, 'AL-01: no worker was started for node F')
        soft('hard link' in out, 'AL-01: the step of node F names the hard link')
        os.remove(flow.proj / 'notes.txt')
        if missed: raise StageFailed('; '.join(missed))
        stage['result'] = 'pass'
    except StageFailed as failure:
        stage['observed']['failure'] = str(failure)[:600]
        print(f'   KHONG DAT: {failure}')
    except Exception as error:                      # a crash of this tool is a failure of the run, with the reason
        stage['observed']['failure'] = f'{type(error).__name__}: {str(error)[:500]}'
        print(f'   KHONG DAT ({type(error).__name__}): {str(error)[:300]}')
    after = {k: sha_file(p) for k, p in real.items()}
    log['real_files'] = {k: {'path': str(real[k]), 'before': before[k], 'after': after[k], 'unchanged': before[k] == after[k]} for k in real}
    log['package_unchanged'] = tree_hashes(pkg) == pkg_before
    log['commands'] = flow.commands
    passed = [s['id'] for s in log['stages'] if s['result'] == 'pass']
    log['result'] = 'pass' if passed == STAGES and all(v['unchanged'] for v in log['real_files'].values()) and log['package_unchanged'] else 'fail'
    log['finished'] = now()
    (work / 'alpha-flow-log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
    with zipfile.ZipFile(work / 'feedback-alpha.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(work / 'alpha-flow-log.json', 'alpha-flow-log.json')
        for p in sorted(flow.logs.glob('*.txt')): z.write(p, 'logs/' + p.name)
        if (flow.proj / 'docs' / 'wiki').is_dir():
            for p in sorted((flow.proj / 'docs' / 'wiki').rglob('*.md')): z.write(p, 'wiki/' + p.relative_to(flow.proj / 'docs' / 'wiki').as_posix())
        if (work / 'fake.jsonl').is_file(): z.write(work / 'fake.jsonl', 'fake.jsonl')
    for s in log['stages']: print(f"   {s['id']}: {s['result']}")
    for k, v in log['real_files'].items(): print(f"   {k} that (chi doc): {'khong doi' if v['unchanged'] else 'DA DOI'}")
    print(f"RESULT {log['result']} {len([s for s in passed if s != 'S0'])}/{len(STAGES) - 1} owner_step={flow.owner_mode}")
    print(f"feedback: {work / 'feedback-alpha.zip'}")
    return 0 if log['result'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
