"""The words of `onecrew init`, `onecrew doctor` and `onecrew owner`: one table, two languages.

English is the default; ONECREW_LANG=vi switches to Vietnamese. Only these three commands read this table; the older output (plan report,
plan digest, the hook messages) keeps the wording it always had. Every key has both languages (tests/test_g2_install.py checks it).
"""
import os

LANGS = ('en', 'vi')

TEXT = {
    # ---- init
    'init.no_git': {'en': 'No git repository found at or above {path}. Run `onecrew init` inside the repo you want to put under a contract (or pass --project).',
                    'vi': 'Không thấy repo git ở {path} hoặc thư mục cha. Chạy `onecrew init` trong repo cần đặt dưới hợp đồng (hoặc dùng --project).'},
    'init.no_exe': {'en': 'Cannot find the installed `onecrew` command to put in the hooks. Run `onecrew init` from an installed copy (pip install the wheel), not from a checkout.',
                    'vi': 'Không tìm thấy lệnh `onecrew` đã cài để ghi vào hook. Chạy `onecrew init` từ bản đã cài (pip install wheel), không chạy từ checkout.'},
    'init.bad_settings': {'en': '{reason} Nothing was changed; fix or move the file and run init again.',
                          'vi': '{reason} Chưa đổi gì; sửa hoặc dời file rồi chạy init lại.'},
    'settings.json_error': {'en': '{path} is not valid JSON (line {line}, column {col}).', 'vi': '{path} không phải JSON hợp lệ (dòng {line}, cột {col}).'},
    'settings.not_object': {'en': '{path} is valid JSON but its top level is not an object.', 'vi': '{path} là JSON hợp lệ nhưng cấp ngoài cùng không phải một đối tượng.'},
    'settings.unreadable': {'en': '{path} cannot be read ({code}).', 'vi': '{path} không đọc được ({code}).'},
    'settings.shape': {'en': '{path} has the wrong shape: "{field}" must be {expected}.', 'vi': '{path} sai hình: "{field}" phải là {expected}.'},
    'shape.object': {'en': 'an object', 'vi': 'một đối tượng'},
    'shape.list': {'en': 'a list', 'vi': 'một danh sách'},
    'why.exit': {'en': 'exit code {code}', 'vi': 'mã thoát {code}'},
    'init.plan_title': {'en': 'OneCrew init will, for project {project}:', 'vi': 'OneCrew init sẽ làm cho dự án {project}:'},
    'init.step_state': {'en': '  - use the state root {path}{note}', 'vi': '  - dùng sổ tại {path}{note}'},
    'init.step_rules': {'en': '  - write the owner rules to {path}', 'vi': '  - ghi quy tắc của chủ sở hữu vào {path}'},
    'init.step_config': {'en': '  - write {path} (state_root)', 'vi': '  - ghi {path} (state_root)'},
    'init.step_settings': {'en': '  - {verb} the hooks in {path}{bak}', 'vi': '  - {verb} hook trong {path}{bak}'},
    'init.verb_create': {'en': 'create', 'vi': 'tạo'},
    'init.verb_merge': {'en': 'merge', 'vi': 'gộp'},
    'init.bak_note': {'en': ' (a .bak copy is kept first)', 'vi': ' (giữ bản .bak trước)'},
    'init.note_new': {'en': ' (new)', 'vi': ' (mới)'},
    'init.note_exists': {'en': ' (exists)', 'vi': ' (đã có)'},
    'init.nothing': {'en': 'Everything is already in place; nothing to change.', 'vi': 'Mọi thứ đã sẵn sàng; không có gì để đổi.'},
    'init.ask': {'en': 'Proceed? [y/N] ', 'vi': 'Tiếp tục? [y/N] '},
    'init.cancelled': {'en': 'Cancelled; nothing was written.', 'vi': 'Đã hủy; chưa ghi gì.'},
    'init.done': {'en': 'Done. State root: {state}. Hooks: {settings} ({command}). Owner rules: {rules}.',
                  'vi': 'Xong. Sổ: {state}. Hook: {settings} ({command}). Quy tắc: {rules}.'},
    'init.error': {'en': 'init stopped: {error}', 'vi': 'init dừng: {error}'},
    # ---- the command line (argparse help, the top-level help lines)
    'cli.init': {'en': 'Create the ledger, the owner rules and the Claude Code hooks for this repo (safe to run again).',
                 'vi': 'Tạo sổ, quy tắc của chủ sở hữu và hook Claude Code cho repo này (chạy lại được).'},
    'cli.doctor': {'en': 'One PASS/WARN/FAIL line per check of this machine and repo; exit 1 on any FAIL.',
                   'vi': 'Mỗi kiểm tra của máy và repo một dòng PASS/WARN/FAIL; exit 1 khi có FAIL.'},
    'cli.shared': {'en': 'Write .claude/settings.json (shared with the team) instead of settings.local.json.',
                   'vi': 'Ghi .claude/settings.json (chia sẻ với nhóm) thay vì settings.local.json.'},
    'cli.yes': {'en': 'Do not ask before writing.', 'vi': 'Không hỏi trước khi ghi.'},
    'cli.line_init': {'en': 'set a repo up: ledger, owner rules, Claude Code hooks (from an installed copy)',
                      'vi': 'cài một repo: sổ, quy tắc, hook Claude Code (từ bản đã cài)'},
    'cli.line_doctor': {'en': 'check this machine and repo: one PASS/WARN/FAIL line per check', 'vi': 'kiểm máy và repo: mỗi kiểm tra một dòng PASS/WARN/FAIL'},
    'cli.line_owner': {'en': "approve / accept / enforce / record (the owner's verbs; refused inside an AI session)",
                       'vi': 'approve / accept / enforce / record (động từ của chủ sở hữu; bị từ chối trong phiên AI)'},
    'init.claude_ok': {'en': 'Claude CLI: found ({path}) and logged in.', 'vi': 'Claude CLI: đã thấy ({path}) và đã đăng nhập.'},
    'init.claude_missing': {'en': 'Claude CLI: not found. The ledger and hooks are written, but reviewers and `plan advise` need it. Install it, then run `claude` once to log in.',
                            'vi': 'Claude CLI: không thấy. Sổ và hook đã ghi, nhưng reviewer và `plan advise` cần nó. Cài nó, rồi chạy `claude` một lần để đăng nhập.'},
    'init.claude_logged_out': {'en': 'Claude CLI: found ({path}) but not logged in. Run `claude` and log in yourself; init never logs in for you.',
                               'vi': 'Claude CLI: đã thấy ({path}) nhưng chưa đăng nhập. Tự chạy `claude` để đăng nhập; init không tự đăng nhập hộ.'},
    'init.claude_unknown': {'en': 'Claude CLI: found ({path}); could not tell whether it is logged in ({why}).',
                            'vi': 'Claude CLI: đã thấy ({path}); không xác định được đã đăng nhập chưa ({why}).'},
    'init.next': {'en': 'Next: onecrew doctor, then write your first contract (docs/README.en.md).', 'vi': 'Tiếp: onecrew doctor, rồi viết hợp đồng đầu tiên (docs/README.en.md).'},
    'init.config_note': {'en': 'Note: .onecrew/config.json names a path on this machine; do not commit it.', 'vi': 'Lưu ý: .onecrew/config.json ghi đường dẫn của máy này; đừng commit nó.'},
    # ---- doctor
    'doctor.python': {'en': 'python', 'vi': 'python'},
    'doctor.python_ok': {'en': '{version} (needs 3.10 or newer)', 'vi': '{version} (cần 3.10 trở lên)'},
    'doctor.python_old': {'en': '{version}; OneCrew needs Python 3.10 or newer', 'vi': '{version}; OneCrew cần Python 3.10 trở lên'},
    'doctor.git': {'en': 'git', 'vi': 'git'},
    'doctor.git_ok': {'en': '{path}', 'vi': '{path}'},
    'doctor.git_missing': {'en': 'git is not on PATH; verdicts and the diff checks need it', 'vi': 'không thấy git trên PATH; verdict và kiểm diff cần nó'},
    'doctor.claude': {'en': 'Claude CLI found', 'vi': 'Claude CLI tìm thấy'},
    'doctor.claude_ok': {'en': '{path}', 'vi': '{path}'},
    'doctor.claude_missing': {'en': 'not found; reviewers and `plan advise` need it (install it, then run `claude` once)', 'vi': 'không thấy; reviewer và `plan advise` cần nó (cài rồi chạy `claude` một lần)'},
    'doctor.login': {'en': 'Claude CLI logged in', 'vi': 'Claude CLI đã đăng nhập'},
    'doctor.login_ok': {'en': 'yes', 'vi': 'đã đăng nhập'},
    'doctor.login_no': {'en': 'not logged in; run `claude` and log in yourself', 'vi': 'chưa đăng nhập; tự chạy `claude` để đăng nhập'},
    'doctor.login_unknown': {'en': 'could not tell ({why})', 'vi': 'không xác định được ({why})'},
    'doctor.login_skip': {'en': 'skipped: no Claude CLI', 'vi': 'bỏ qua: không có Claude CLI'},
    'doctor.state': {'en': 'state root readable and writable', 'vi': 'sổ đọc và ghi được'},
    'doctor.state_ok': {'en': '{path}{ledger}', 'vi': '{path}{ledger}'},
    'doctor.state_ledger': {'en': ' (ledger present)', 'vi': ' (đã có sổ cái)'},
    'doctor.state_noledger': {'en': ' (no ledger yet; the first plan creates it)', 'vi': ' (chưa có sổ cái; plan đầu tiên sẽ tạo)'},
    'doctor.state_bad': {'en': '{path} cannot be written ({why})', 'vi': '{path} không ghi được ({why})'},
    'doctor.state_missing': {'en': '{path} does not exist; run `onecrew init`', 'vi': '{path} chưa tồn tại; chạy `onecrew init`'},
    'doctor.config': {'en': 'repo config.json', 'vi': 'config.json của repo'},
    'doctor.config_ok': {'en': '{path} (state_root {state})', 'vi': '{path} (state_root {state})'},
    'doctor.config_missing': {'en': '{path} is missing; run `onecrew init`', 'vi': 'thiếu {path}; chạy `onecrew init`'},
    'doctor.hook': {'en': 'hook in Claude Code settings', 'vi': 'hook trong settings của Claude Code'},
    'doctor.hook_ok': {'en': '{path} matches what init writes', 'vi': '{path} khớp với bản init ghi'},
    'doctor.hook_missing': {'en': 'no OneCrew hook in {paths}; run `onecrew init`', 'vi': 'không có hook OneCrew trong {paths}; chạy `onecrew init`'},
    'doctor.hook_differs': {'en': '{path} has OneCrew hooks that differ from what init would write; run `onecrew init` to refresh them', 'vi': '{path} có hook OneCrew khác với bản init sẽ ghi; chạy `onecrew init` để làm mới'},
    'doctor.hook_stale': {'en': '{path} points at {command}, which does not exist; run `onecrew init` again from the current install', 'vi': '{path} trỏ vào {command}, file này không tồn tại; chạy lại `onecrew init` từ bản cài hiện tại'},
    'doctor.plan': {'en': 'active plan', 'vi': 'plan đang mở'},
    'doctor.plan_ok': {'en': '{name} revision {revision}, hook mode {mode}', 'vi': '{name} revision {revision}, hook mode {mode}'},
    'doctor.plan_none': {'en': 'none (no .onecrew/active-plan.json)', 'vi': 'không có (không có .onecrew/active-plan.json)'},
    'doctor.plan_bad': {'en': 'active-plan.json cannot be read ({why})', 'vi': 'không đọc được active-plan.json ({why})'},
    'doctor.project': {'en': 'project', 'vi': 'dự án'},
    'doctor.project_ok': {'en': '{path}', 'vi': '{path}'},
    'doctor.project_none': {'en': 'no git repository at or above {path}', 'vi': 'không có repo git ở {path} hoặc thư mục cha'},
    'doctor.summary': {'en': '{fails} FAIL, {warns} WARN, {passes} PASS', 'vi': '{fails} FAIL, {warns} WARN, {passes} PASS'},
    # ---- owner
    'owner.description': {'en': "The owner's verbs: approve a plan, accept the result, switch the hook mode, record an owner verdict. Run them in a terminal of your own, never from an AI session.",
                          'vi': 'Các động từ của chủ sở hữu: duyệt plan, nghiệm thu kết quả, đổi chế độ hook, ghi verdict của chủ sở hữu. Gõ trong terminal của chính bạn, không từ phiên AI.'},
    'owner.approve': {'en': 'Approve a plan (= plan approve --by owner).', 'vi': 'Duyệt một plan (= plan approve --by owner).'},
    'owner.accept': {'en': 'Accept the finished plan (= plan accept --by owner).', 'vi': 'Nghiệm thu plan đã xong (= plan accept --by owner).'},
    'owner.enforce': {'en': 'Switch the hook mode of a plan (= hook mode enforce|log --by owner).', 'vi': 'Đổi chế độ hook của plan (= hook mode enforce|log --by owner).'},
    'owner.record': {'en': 'Record an owner verdict (= verdict record --by owner).', 'vi': 'Ghi verdict của chủ sở hữu (= verdict record --by owner).'},
    'owner.reference': {'en': 'Where you said yes (a message, a ticket, a date).', 'vi': 'Nơi bạn đã đồng ý (tin nhắn, ticket, ngày).'},
    'owner.enforce_reference': {'en': 'onecrew owner enforce', 'vi': 'onecrew owner enforce'},
}


def lang():
    """'vi' when ONECREW_LANG=vi, else 'en'."""
    return 'vi' if os.environ.get('ONECREW_LANG', '').strip().lower() == 'vi' else 'en'


def t(key, **values):
    """The text of `key` in the current language, with {name} placeholders filled."""
    return TEXT[key][lang()].format(**values)
