"""`onecrew owner approve|accept|enforce|record` (G2): the owner's verbs under one name, in place of the four scripts/owner/*.ps1.

Each one is the older command with `--by owner` fixed, run through the same code, so the output and the checks are the same:
  owner approve <plan> --reference R [--choose X] [--tick I]... [--revision N]   = plan approve --by owner
  owner accept <plan> --artifact-sha S --reference R                            = plan accept --by owner
  owner enforce <plan> [--mode log|enforce] [--reference R]                     = hook mode <mode> --by owner --plan <plan>
  owner record --plan P --milestone M --result pass|fail|inconclusive --artifact-sha S --receipt-file F --reference R
                                                                                = verdict record --by owner
They are refused inside an AI tool session: ownership.OWNER_VERBS names these four, and the code they call refuses too (C3, C11).
"""
import argparse
import contextlib
import io
import json
from pathlib import Path

from ..display_core import safe
from .messages import t


def _parser():
    parser = argparse.ArgumentParser(prog='onecrew owner', description=t('owner.description'))
    verbs = parser.add_subparsers(dest='verb', required=True)
    p = verbs.add_parser('approve', help=t('owner.approve'))
    p.add_argument('plan'); p.add_argument('--reference', required=True, help=t('owner.reference')); p.add_argument('--choose', metavar=t('owner.metavar_option'))
    p.add_argument('--tick', action='append', default=[], metavar=t('owner.metavar_item')); p.add_argument('--revision', type=int)
    p.add_argument('--estimate-file', type=Path)
    p = verbs.add_parser('answer', help='Record a choice on a current request; it does not approve a plan.')
    p.add_argument('request'); p.add_argument('--revision', required=True)
    p.add_argument('--choice', required=True); p.add_argument('--reference', required=True)
    p = verbs.add_parser('accept', help=t('owner.accept'))
    p.add_argument('plan'); p.add_argument('--artifact-sha', required=True); p.add_argument('--reference', required=True, help=t('owner.reference'))
    p.add_argument('--revision', type=int, help='Refuse acceptance when the current revision differs.')
    p = verbs.add_parser('enforce', help=t('owner.enforce'))
    p.add_argument('plan'); p.add_argument('--mode', choices=['enforce', 'log'], default='enforce'); p.add_argument('--reference', default=t('owner.enforce_reference'))
    p = verbs.add_parser('record', help=t('owner.record'))
    p.add_argument('--plan', required=True); p.add_argument('--milestone', required=True); p.add_argument('--result', required=True, choices=['pass', 'fail', 'inconclusive'])
    p.add_argument('--artifact-sha', required=True); p.add_argument('--receipt-file', required=True, type=Path); p.add_argument('--reference', required=True, help=t('owner.reference'))
    parser.add_argument('--human', action='store_true', default=argparse.SUPPRESS, help='Human-readable result; JSON remains the default.')
    for command in verbs.choices.values():
        command.add_argument('--human', action='store_true', default=argparse.SUPPRESS)
    return parser


def translate(args):
    """(module, argv) of the older command a parsed `owner` verb stands for (--by owner fixed)."""
    if args.verb == 'answer':
        return 'questions', ['question', 'answer', args.request, '--revision', str(args.revision), '--choice', args.choice, '--reference', args.reference]
    if args.verb == 'approve':
        argv = ['plan', 'approve', args.plan, '--by', 'owner', '--reference', args.reference]
        argv += ['--revision', str(args.revision)] if args.revision is not None else []
        argv += [x for tick in args.tick for x in ('--tick', tick)]
        argv += ['--choose', args.choose] if args.choose else []
        argv += ['--estimate-file', str(args.estimate_file)] if args.estimate_file else []
        return 'plan_cli', argv
    if args.verb == 'accept':
        argv = ['plan', 'accept', args.plan, '--by', 'owner', '--reference', args.reference, '--artifact-sha', args.artifact_sha]
        return 'plan_cli', argv + (['--revision', str(args.revision)] if args.revision is not None else [])
    if args.verb == 'enforce':
        return 'hook_cli', ['hook', 'mode', args.mode, '--by', 'owner', '--plan', args.plan, '--reference', args.reference]
    return 'plan_cli', ['verdict', 'record', '--plan', args.plan, '--milestone', args.milestone, '--result', args.result, '--by', 'owner',
                        '--artifact-sha', args.artifact_sha, '--receipt-file', str(args.receipt_file), '--reference', args.reference]


def _human_result(parsed, code, output, errors='', *, refused=False):
    """Only a typed receipt supports success; an exit code alone never does."""
    try: value = json.loads(output)
    except (ValueError, TypeError): value = None
    success = None
    if code == 0 and isinstance(value, dict) and not value.get('error'):
        revision = value.get('approved_revision')
        if parsed.verb == 'approve' and value.get('status') in ('approved', 'accepted') and revision is not None and (parsed.revision is None or parsed.revision == revision):
            success = f'Đã ghi nhận duyệt {parsed.plan}, bản {revision}. Việc duyệt không xác nhận worker đã bắt đầu.'
        elif parsed.verb == 'accept' and value.get('status') == 'accepted':
            success = f'Đã ghi nhận nghiệm thu {parsed.plan}, bản {value.get("revision")}. Đại diện bởi artifact {parsed.artifact_sha}.'
        elif parsed.verb == 'answer' and value.get('request_id') == parsed.request and str(value.get('revision')) == str(parsed.revision) and value.get('choice') == parsed.choice:
            success = f'Đã ghi nhận lựa chọn {parsed.choice} cho câu hỏi {parsed.request}. Đây không phải là duyệt phương án.'
        elif parsed.verb == 'enforce' and value.get('mode') == parsed.mode and value.get('exported') is True:
            success = f'Đã bật chế độ {parsed.mode} và xuất quyền của {parsed.plan}. Cấu hình này chưa chứng minh hook đã chạy trong phiên làm việc.'
    if success:
        print(safe(success, 1000))
        if value.get('post_commit_errors'):
            print(safe('Phần đồng bộ sau khi ghi chưa hoàn tất: ' + json.dumps(value['post_commit_errors'], ensure_ascii=False), 2000))
        print('Bước tiếp theo: xem lại task trên trang theo dõi; trạng thái dựa trên lần đọc sổ mới.')
        if value.get('state_root'): print(safe('Sổ: ' + str(value['state_root']), 1000))
    else:
        detail = value.get('error') if isinstance(value, dict) else output
        if parsed.verb == 'enforce' and isinstance(value, dict) and value.get('mode_committed') is True:
            print(safe('Chế độ ' + str(value.get('mode')) + ' đã ghi; quyền của plan chưa xuất xong. Đọc lại sổ và xử lý lỗi xuất trước khi tiếp tục.', 1000))
        elif refused and 'AI tool session' in str(detail):
            print('Chưa ghi nhận: thao tác này cần terminal của chủ sở hữu.')
        elif refused:
            print('Chưa ghi nhận: cần điền lựa chọn và lý do của chính bạn.')
        elif str(detail).startswith(('Only the latest revision (', 'Cannot accept: expected revision ', 'Stale request revision')):
            print('Chưa ghi nhận lựa chọn ở bản cũ; hãy đọc lại bản hiện tại.')
        else:
            print('Chưa xác nhận được kết quả của lệnh; cần đọc lại sổ trước khi thử lại.')
        if detail: print(safe(detail, 2000))
        if errors: print(safe(errors, 2000))
        if refused: print('Chạy lệnh đã điền đầy đủ trong terminal của bạn; giữ nguyên các chốt quyền hiện có.')
        if code == 0: code = 1  # No valid receipt: never offer a successful process exit to another consumer.
    return code


def main(args):
    """`args` is the whole command line, global options (--project, --state-root) first, then `owner <verb> ...`."""
    index = 0
    while index < len(args) and args[index] != 'owner': index += 1
    glob, rest = list(args[:index]), list(args[index + 1:])
    human = '--human' in rest
    if human:
        errors = io.StringIO()
        try:
            with contextlib.redirect_stderr(errors): parsed = _parser().parse_args(rest)
        except SystemExit as result:
            if result.code:
                print('Chưa ghi nhận: tham số lệnh chưa đầy đủ hoặc không hợp lệ.')
                print(safe(errors.getvalue(), 2000))
            return result.code
    else:
        parsed = _parser().parse_args(rest)
    module, argv = translate(parsed)
    if module == 'questions':
        from .questions import main as run
    elif module == 'hook_cli':
        from .hook_cli import main as run
    else:
        from .plan_cli import main as run
    if not human: return run(glob + argv)
    from . import ownership
    output, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output): refused = ownership.refuse_argv(['owner', *rest])
    if refused: return _human_result(parsed, refused, output.getvalue(), refused=True)
    from .tracking import REFERENCE_PLACEHOLDER
    if getattr(parsed, 'reference', None) == REFERENCE_PLACEHOLDER or getattr(parsed, 'choose', None) == '<option-id>':
        return _human_result(parsed, 2, json.dumps({'error': 'Điền lựa chọn và --reference của chính bạn thay cho placeholder trước khi chạy.'}), refused=True)
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors): code = run(glob + argv)
    except SystemExit as result:
        code = result.code
    except Exception as error:
        code = 1
        output.write(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False))
    return _human_result(parsed, code, output.getvalue(), errors.getvalue())
