# Mẫu hợp đồng kiểm theo phần thay đổi

Ví dụ này dành cho dự án có gói `catalog` và thư mục `tests` có `__init__.py`. Mốc đầu kiểm phần tìm kiếm. Mốc giao chạy toàn bộ bài thử. Điền lời giao việc của chủ, tên gói, tên test và đường dẫn tuyệt đối trên máy trước khi chạy `plan lint`.

```json
{
  "schema_version": 2, "title": "Tìm sách theo tên", "size": "S",
  "origin": {"by": "owner", "at": "<ngày giao>", "quote": "<lời chủ>"},
  "presentation": {
    "request": "Tìm một cuốn sách bằng tên.",
    "user_sees": ["Gõ tên và thấy các sách khớp."],
    "acceptance_steps": ["Tìm một tên đã có và một tên chưa có."],
    "not_doing": "Giữ nguyên cách thêm sách."
  },
  "understanding": {
    "restated_goal": "Tìm sách theo tên và kiểm lại các chức năng của danh mục.",
    "target": {"repo": ".", "ref": "HEAD", "paths": ["catalog", "tests"]},
    "assumptions": [], "confidence": "high", "unknowns": []
  },
  "preconditions": [{"id": "P1", "check": "ref_resolves", "args": {"repo": ".", "ref": "HEAD"}, "why": "Có bản gốc để so."}],
  "output": ["Danh sách sách khớp tên", "Bản giao qua bộ thử của danh mục"],
  "scope": {"owned": ["catalog/**", "tests/**"]}, "non_goals": ["Đổi cách thêm sách"],
  "items": [
    {"id": "I1", "title": "Tìm theo tên", "tier": "must", "milestone": "M1", "source": "origin"},
    {"id": "I2", "title": "Kiểm bản giao", "tier": "must", "milestone": "M2", "source": "origin"}
  ],
  "milestones": [
    {"id": "M1", "title": "Kiểm tìm kiếm", "covers": ["O1"], "verifier": {"type": "command", "config": {
      "argv": ["python", "-I", "D:/checks/verify.py", "tests.test_search"],
      "inputs": ["catalog", "tests/__init__.py", "tests/test_search.py"],
      "env_inputs": ["D:/checks/verify.py"]
    }}},
    {"id": "M2", "title": "Kiểm toàn bộ danh mục", "covers": ["O2"], "verifier": {"type": "command", "config": {
      "argv": ["python", "-I", "D:/checks/verify.py", "--all"],
      "env_inputs": ["D:/checks/verify.py"]
    }}}
  ],
  "budget": {"max_calls": 20, "time": 60}, "attention": {"questions": 1}, "profile_version": null
}
```

Lưu đoạn dưới thành `verify.py` ở vị trí đã khai trong `env_inputs`. Thay cả bốn đường dẫn tới script bằng vị trí trên máy và chọn trình thông dịch đã cài. Bộ kiểm in từng ca và trả mã lỗi nếu có ca trượt, bị bỏ qua hoặc không tìm thấy ca nào. Khi thêm `--base <cây gốc>`, bộ kiểm chạy cùng bộ test trên cây gốc để biết ca nào đã đỏ từ trước (xem mục cuối).

```python
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

USAGE = "Supply test modules or --all (optional: --base <base tree> [--base-red-max <n>])"
CASE_RED = ("failure", "error")
RED = CASE_RED + ("broken",)


class Record(unittest.TextTestResult):
    """One status per case: pass, skip, failure, error, or broken (a module or a set-up that did not run its cases)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = {}

    def note(self, test, status):
        name = test.id()
        not_run = type(test).__name__ == "_FailedTest" or name.startswith(("setUpClass (", "setUpModule ("))
        if status in CASE_RED and not_run:
            status = "broken"
        if self.cases.get(name) in (None, "pass") or status in RED:
            self.cases[name] = status

    def addSuccess(self, test):
        super().addSuccess(test)
        self.note(test, "pass")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.note(test, "pass")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.note(test, "failure")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.note(test, "failure")

    def addError(self, test, err):
        super().addError(test, err)
        self.note(test, "error")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.note(test, "skip")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.note(subtest, "failure" if issubclass(err[0], test.failureException) else "error")


def run(targets):
    sys.path.insert(0, os.getcwd())
    loader = unittest.defaultTestLoader
    if targets == ["--all"]:
        suite = loader.discover("tests", top_level_dir=".")
    else:
        suite = loader.loadTestsFromNames(targets)
    return unittest.TextTestRunner(verbosity=2, resultclass=Record).run(suite)


def option(args, name):
    if name not in args:
        return None
    at = args.index(name)
    if at + 1 == len(args):
        sys.exit(USAGE)
    value = args[at + 1]
    del args[at:at + 2]
    return value


def start(tree, targets, report, output=None):
    """The same targets in one tree, in a new process of the same interpreter."""
    flags = ["-B"] + (["-I"] if sys.flags.isolated else []) + (["-X", "utf8"] if sys.flags.utf8_mode else [])
    command = [sys.executable, *flags, os.path.abspath(__file__), "--report", report, *targets]
    return subprocess.Popen(command, cwd=tree, stdout=output, stderr=output)


def finish(process, report):
    """The case statuses of one tree, or None when its run did not reach the end."""
    if process.wait() not in (0, 1) or not os.path.isfile(report):
        return None
    with open(report, encoding="utf-8") as handle:
        return json.load(handle)


def show(title, names):
    if names:
        print(f"{title}: {len(names)}")
        for name in sorted(names):
            print("  " + name)


def judge(new, base, red_max, base_log):
    base_red = [name for name, status in (base or {}).items() if status in RED]
    suspect = None
    if base is None:
        suspect = "cây gốc chạy hỏng, không có kết quả"
    elif all(status in ("broken", "skip") for status in base.values()):
        suspect = "cây gốc không có ca nào chạy được"
    elif len(base_red) > red_max:
        suspect = f"cây gốc đỏ {len(base_red)} ca, quá ngưỡng {red_max}"
    if suspect:
        print(f"TRƯỢT, nền nghi lỗi: {suspect}. Sửa môi trường hoặc cây gốc rồi chạy lại.")
        show("Đỏ ở cây gốc", base_red)
        print("Cuối log của cây gốc:\n" + base_log)
        return 1
    if not new:
        print("TRƯỢT: bản đang kiểm chạy hỏng hoặc không có ca nào.")
        return 1
    excused = [name for name, status in new.items() if status in CASE_RED and base.get(name) in CASE_RED]
    fresh = [name for name, status in new.items() if status in CASE_RED and name not in excused]
    broken = [name for name, status in new.items() if status == "broken"]
    skipped = [name for name, status in new.items() if status == "skip"]
    show("Đỏ nền (đỏ cả ở cây gốc, đo cùng lượt này), không tính", excused)
    show("TRƯỢT, đỏ mới (cây gốc không đỏ)", fresh)
    show("TRƯỢT, module hoặc bước chuẩn bị không chạy được (không bao giờ là đỏ nền)", broken)
    show("TRƯỢT, ca bị bỏ qua", skipped)
    passed = not (fresh or broken or skipped)
    print("ĐẠT" if passed else "TRƯỢT")
    return 0 if passed else 1


def compare(base_tree, red_max, targets):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not os.path.isdir(base_tree) or os.path.samefile(base_tree, os.getcwd()):
        print("TRƯỢT, nền nghi lỗi: --base phải là thư mục cây gốc, khác thư mục đang kiểm.")
        return 1
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        # The base tests run in a copy, so a test that writes files leaves the declared base tree as it was.
        copy = shutil.copytree(base_tree, os.path.join(tmp, "tree"), ignore=shutil.ignore_patterns("__pycache__"))
        new_report, base_report = os.path.join(tmp, "new.json"), os.path.join(tmp, "base.json")
        log_path = os.path.join(tmp, "base.log")
        with open(log_path, "wb") as log:
            new_process = start(os.getcwd(), targets, new_report)
            base_process = start(copy, targets, base_report, log)
            new, base = finish(new_process, new_report), finish(base_process, base_report)
        with open(log_path, encoding="utf-8", errors="replace") as log:
            base_log = log.read()[-3000:]
    return judge(new, base, red_max, base_log)


def main(args):
    report = option(args, "--report")  # used by the two processes that --base starts
    base = option(args, "--base")
    red_max = option(args, "--base-red-max")
    if not args:
        sys.exit(USAGE)
    if base is not None:
        return compare(base, 3 if red_max is None else int(red_max), args)
    result = run(args)
    if report:
        with open(report, "w", encoding="utf-8") as handle:
            json.dump(result.cases, handle)
    return 0 if result.testsRun and result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Ở M1, khai thêm fixture, module hỗ trợ và mọi gói mà test import. Nếu bộ kiểm đọc dữ liệu ngoài repo, thêm đường dẫn đó vào `env_inputs`. Mỗi lần sửa cần có ca hồi quy trong các module mốc thực sự chạy. Với sản phẩm giao bằng wheel, dành bước dựng và cài sạch cho mốc giao, rồi chạy mọi test mới và các module chịu ảnh hưởng trên bản cài.

## Ca đỏ nền: đo cùng lượt trên cây gốc

Ca đỏ nền là ca đã đỏ ở mã gốc, trước khi bạn sửa gì. Đừng đo một lần rồi lưu danh sách ra tệp: một lần đo trong môi trường lỗi ghi cả loạt ca vào danh sách, và từ đó lỗi thật ở những ca ấy lọt qua. `plan lint` nhắc khi bộ kiểm nhắc tới một tệp dữ liệu có tên chứa `baseline`.

Ở mốc kiểm hồi quy, đưa cho bộ kiểm cây gốc để nó đo nền cùng lượt, bằng cùng trình thông dịch:

```json
{"argv": ["python", "-I", "D:/checks/verify.py", "--base", "D:/checks/base", "--all"],
 "env_inputs": ["D:/checks/verify.py", "D:/checks/base"]}
```

Cây gốc là một thư mục riêng ngoài repo, chứa mã của commit gốc. Tạo nó trước khi trình duyệt, ví dụ:

```text
git -c core.autocrlf=false -c core.eol=lf archive --format=tar --output=D:/checks/base.tar <commit gốc>
mkdir D:/checks/base
tar -xf D:/checks/base.tar -C D:/checks/base
```

Khi có `--base`, bộ kiểm chạy cùng các đích song song trên bản đang kiểm và trên một bản sao tạm của cây gốc:

- Ca đỏ ở cả hai là đỏ nền: bộ kiểm in tên và không tính.
- Ca đỏ chỉ ở bản đang kiểm thì trượt. Ca bị bỏ qua vẫn trượt.
- Module không tải được, hoặc bước chuẩn bị của lớp hay module bị lỗi, thì trượt kể cả khi cây gốc cũng vậy: các ca trong đó chưa được đo.
- Cây gốc chạy hỏng, không có ca nào chạy được, hoặc đỏ nhiều hơn 3 ca thì trượt với lời "nền nghi lỗi". Mỗi module không tải được hay bước chuẩn bị lỗi ở cây gốc tính là một ca đỏ. Đổi ngưỡng bằng `--base-red-max <số>`, ghi ngay trong lệnh để người duyệt thấy.

Không có `--base` thì bộ kiểm xử như đã nói ở trên: trượt khi có ca đỏ, ca bị bỏ qua hoặc không có ca nào.

Giới hạn cần biết:

- So theo tên ca. Ca đã đỏ ở gốc mà bản mới làm hỏng theo kiểu khác thì không bị bắt; đọc danh sách đỏ nền được in ra.
- Ca bị xóa khỏi bản đang kiểm không bị báo; khi soát, xem phần đổi của thư mục test.
- Mỗi lượt phải nạp mã của chính cây đó. Nếu gói đã cài sẵn vào Python (cài kiểu editable, mã nằm trong `src`), hai lượt chạy cùng một mã và nền vô nghĩa.
- Hai lượt chạy song song: test dùng chung cổng mạng, tệp hay dịch vụ cố định có thể đỏ do tranh nhau.
- Module test mới chưa có ở gốc sẽ không tải được ở đó và tính vào ngưỡng. Chạy module mới ở mốc không có `--base`, hoặc dùng `--all`.
