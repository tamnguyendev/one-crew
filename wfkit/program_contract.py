"""The program contract of the transition mode (03 §2.3) and its shape check (T39 [E10], [E11]).

One v2 plan runs the whole program on the EXISTING v2 supervisor: four command milestones M1–M4, each calling the kit
through kit-guard with the kit-guard script's sha256 pinned in the argv (a contract pins argv, not script bytes), and
M5 = owner-manual last (the owner runs the Codex review of the whole program and records it in the same final
acceptance). No reviewer milestone: the automatic reviewer never reads a diff over 120 000 bytes. The defaults the
owner still has to settle (ROADMAP §10: A8 per-project plan storage, A10 local evidence refs without push) travel in
`decisions`, settled by the one program approval, never as separate questions.
"""
import hashlib
import json
import sys
from pathlib import Path

GROUPS = [('M1', 'R00,RP,RX1', 'R00, RP và RX1 qua cổng giao'),
          ('M2', 'R01,R02,R03,KN-R01-R02,KN-R02-R03', 'R01, R02, R03 và hai kiểm tích hợp qua cổng giao'),
          ('M3', 'R04,R05,RX2,KN-R03-R04', 'R04, R05, RX2 và KN-R03-R04 qua cổng giao'),
          ('M4', 'R06,R07,R08,PL,KET', 'R06, R07, R08, bộ kiểm pilot và cổng cuối CG-KET đạt')]
# Runs `script` only after its sha256 matches the pinned one; the script then sees `argv` as its own command line.
BOOTSTRAP = ('import hashlib, runpy, sys; p = sys.argv[1]; want = sys.argv[2]; got = hashlib.sha256(open(p, "rb").read()).hexdigest(); '
             'sys.exit("kit-guard sha256 mismatch: " + got) if got != want else None; sys.argv = [p] + sys.argv[3:]; runpy.run_path(p, run_name="__main__")')


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def kit_argv(script, sha256, *args, python=None):
    """argv of a command milestone: the pinned sha256 is checked before the kit-guard script runs with `args`."""
    return [python or sys.executable, '-c', BOOTSTRAP, str(script), sha256, *args]


def build(*, kitguard_script, kitguard_sha256, python=None, max_calls=1800, time_minutes=13000, origin=None,
          owned=('onecrew/', 'tests/', 'wfkit/', 'pyproject.toml', 'docs/wf/')):
    """The program plan (schema 2) for `plan propose`. Outputs are program-level results, items are the release groups.
    `origin` is the owner's assignment message {by, at, quote} (03 §2.4 row 1): every item points at it (source "origin")."""
    origin = origin or {'by': 'owner', 'at': 'chat', 'quote': 'Trình chương trình workflow chung để duyệt.'}
    outputs = [title for _, _, title in GROUPS] + ['AC1–AC5 có báo cáo theo phiên bản; review Codex toàn chương trình đã ghi (M5)']
    milestones = []
    for index, (mid, releases, title) in enumerate(GROUPS, start=1):
        milestones.append({'id': mid, 'title': 'Cổng ' + title, 'covers': ['O%d' % index], 'max_repairs': 3,
                           'verifier': {'type': 'command', 'config': {
                               'argv': kit_argv(kitguard_script, kitguard_sha256, 'verify', '--releases', releases, python=python),
                               'max_minutes': 50}}})
    milestones.append({'id': 'M5', 'title': 'Review Codex toàn chương trình và nghiệm thu (chủ sở hữu)', 'covers': ['O5'],
                       'verifier': {'type': 'owner-manual'}, 'max_repairs': 1})
    items = [{'id': 'I%d' % i, 'title': title, 'tier': 'must', 'milestone': mid, 'source': 'origin'} for i, (mid, _, title) in enumerate(GROUPS, start=1)]
    items.append({'id': 'I5', 'title': 'Review toàn chương trình và nghiệm thu một lần', 'tier': 'must', 'milestone': 'M5', 'source': 'origin'})
    return {'schema_version': 2, 'title': 'Chương trình workflow chung (chế độ chuyển tiếp)', 'size': 'S',
            'understanding': {'restated_goal': 'Xây workflow chung theo 00–06 trên năng lực v2 hiện có; mỗi mốc gom một nhóm release và gọi kit qua kit-guard.',
                              'target': {'repo': '.', 'ref': 'HEAD', 'paths': list(owned)}, 'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': str(owned[0])}, 'why': 'mã nguồn của chương trình ở đây'}],
            'output': outputs, 'scope': {'owned': list(owned)},
            'non_goals': ['Không push, tag, publish', 'Không đổi bộ giám sát đang dùng', 'Không migration sổ thật'],
            'items': items, 'milestones': milestones, 'budget': {'max_calls': max_calls, 'time': time_minutes},
            'attention': {'questions': 1}, 'profile_version': None,
            'origin': {'by': str(origin['by']), 'at': str(origin['at']), 'quote': str(origin['quote'])[:500]},
            'decisions': [
                {'id': 'D1', 'choice': 'A8: root mới lưu theo project (plans/<project_id>/<tên>, anchor plan-ns:)',
                 'alternative': 'Giữ một không gian tên chung cho mọi project', 'cost': 'Không: chọn trong cùng lần duyệt chương trình'},
                {'id': 'D2', 'choice': 'A10: giữ bằng chứng bằng ref Git cục bộ, không push',
                 'alternative': 'Push bằng chứng lên remote', 'cost': 'Không: chọn trong cùng lần duyệt chương trình'}]}


def check(contract):
    """Why `contract` is not the transition-mode program contract; [] when it is (T39 [E10], [E11])."""
    problems = []
    milestones = contract.get('milestones') or []
    if len(milestones) != 5: problems.append('expected 5 milestones, found %d' % len(milestones))
    for mid, expected in zip([m.get('id') for m in milestones], ['M1', 'M2', 'M3', 'M4', 'M5']):
        if mid != expected: problems.append('milestone order must be M1..M5, found ' + str(mid))
    for m in milestones[:4]:
        verifier = m.get('verifier') or {}
        argv = (verifier.get('config') or {}).get('argv') or []
        if verifier.get('type') != 'command': problems.append(m.get('id', '?') + ' is not a command milestone')
        elif not (len(argv) >= 5 and argv[1] == '-c' and argv[2] == BOOTSTRAP and 'kitguard' in str(argv[3]) and len(argv[4]) == 64):
            problems.append(m.get('id', '?') + ' does not call kit-guard through the sha256-pinned bootstrap')
    if milestones and (milestones[-1].get('verifier') or {}).get('type') != 'owner-manual':
        problems.append('the last milestone must be owner-manual')
    reviewers = [m['id'] for m in milestones if (m.get('verifier') or {}).get('type') == 'reviewer']
    if reviewers: problems.append('reviewer milestones are not allowed in the program contract: ' + ', '.join(reviewers))
    decisions = {d.get('choice', '')[:3]: d for d in contract.get('decisions') or []}
    for tag in ('A8:', 'A10'):
        hit = next((d for d in (contract.get('decisions') or []) if d.get('choice', '').startswith(tag)), None)
        if hit is None or not hit.get('alternative'): problems.append('decisions must settle ' + tag.rstrip(':') + ' with a default and an alternative')
    return problems


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'check'])
    parser.add_argument('--kitguard', default='wfkit/kitguard.py')
    parser.add_argument('--out')
    parser.add_argument('--file')
    args = parser.parse_args(argv)
    if args.command == 'build':
        script = Path(args.kitguard).resolve()
        contract = build(kitguard_script=script, kitguard_sha256=sha256_file(script))
        text = json.dumps(contract, ensure_ascii=False, indent=2)
        if args.out: Path(args.out).write_text(text + '\n', encoding='utf-8')
        else: print(text)
        return 0
    problems = check(json.loads(Path(args.file).read_text(encoding='utf-8')))
    print(json.dumps({'ok': not problems, 'problems': problems}, ensure_ascii=False))
    return 0 if not problems else 1


if __name__ == '__main__':
    raise SystemExit(main())
