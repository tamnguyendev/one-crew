"""Readable spec review and content-bound local decisions, using only stdlib."""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import getpass
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

SECTIONS = ("Kết quả", "Phạm vi", "Không làm", "Nghiệm thu", "Lưu ý", "Ngân sách", "Cần quyết định")
STATUSES = {
    "draft": "CHỜ DUYỆT", "approved": "ĐÃ DUYỆT",
    "changes_requested": "CẦN SỬA", "needs_review": "CẦN DUYỆT LẠI",
}
QUICK = "\n## Duyệt nhanh\n"
DETAILS = "\n## Chi tiết cho AI\n"
MAX_BRIEF_WORDS = 350
SCHEMA = """CREATE TABLE IF NOT EXISTS decisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('approved', 'changes_requested')),
    revision TEXT NOT NULL, snapshot TEXT NOT NULL,
    actor TEXT NOT NULL, comment TEXT NOT NULL, created_at TEXT NOT NULL
)"""


class SpecError(Exception):
    pass


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def contained(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise SpecError(f"Đường dẫn nằm ngoài project: {path}")
    return resolved


def clean_text(text: str) -> bool:
    return not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text)


@dataclass(frozen=True)
class Spec:
    id: str
    title: str
    text: str
    brief: str
    details: str
    questions: tuple[str, ...]
    path: Path

    @property
    def revision(self) -> str:
        return digest(self.text)

    @classmethod
    def parse(cls, text: str, path: Path) -> Spec:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not clean_text(text):
            raise SpecError(f"{path.name}: có ký tự điều khiển không hợp lệ.")
        if text.count(QUICK) != 1 or text.count(DETAILS) != 1:
            raise SpecError(f"{path.name}: cần đúng một mục 'Duyệt nhanh' và 'Chi tiết cho AI'.")
        heading, _, tail = text.partition(QUICK)
        match = re.fullmatch(r"# (SPEC-\d{3,6}) — ([^\n]{1,160})", heading.strip())
        if not match:
            raise SpecError(f"{path.name}: dòng đầu phải là '# SPEC-001 — Tên dễ hiểu'.")
        sid, title = match.groups()
        if not (path.stem == sid or path.stem.startswith(sid + "-")):
            raise SpecError(f"{path.name}: tên file phải bắt đầu bằng {sid}.")
        quick, _, details = tail.partition(DETAILS)
        headings = list(re.finditer(r"^### ([^\n]+)\n", quick, re.MULTILINE))
        if tuple(m.group(1) for m in headings) != SECTIONS:
            raise SpecError(f"{path.name}: bảy mục bản nhanh phải đúng thứ tự: {', '.join(SECTIONS)}.")
        if quick[:headings[0].start()].strip():
            raise SpecError(f"{path.name}: nội dung bản nhanh cần nằm trong bảy mục.")
        values = {}
        for i, m in enumerate(headings):
            end = headings[i + 1].start() if i + 1 < len(headings) else len(quick)
            value = quick[m.end():end].strip()
            if not value:
                raise SpecError(f"{path.name}: mục '{m.group(1)}' chưa có nội dung.")
            values[m.group(1)] = value
        words = len(quick.split())
        if words > MAX_BRIEF_WORDS:
            raise SpecError(f"{path.name}: bản nhanh có {words} từ; tối đa {MAX_BRIEF_WORDS}. Hãy viết gọn hoặc chia lát.")
        if not details.strip():
            raise SpecError(f"{path.name}: thiếu chi tiết cho AI.")
        questions = []
        if values["Cần quyết định"] != "Không có.":
            for line in values["Cần quyết định"].splitlines():
                m = re.fullmatch(r"- \[([ xX])\] (\S.*)", line)
                if not m:
                    raise SpecError(f"{path.name}: câu hỏi dùng '- [ ]', '- [x]' hoặc 'Không có.'.")
                if m.group(1) == " ":
                    questions.append(m.group(2))
        brief = f"# {sid} — {title}\n\n{quick.strip()}\n"
        return cls(sid, title, text, brief, details.strip(), tuple(questions), path)


class Project:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if not self.root.is_dir():
            raise SpecError(f"Không có thư mục project: {self.root}")
        self.spec_dir = contained(self.root, self.root / "specs")
        self.db_path = contained(self.root, self.root / ".onecrew" / "spec-reviews.sqlite3")

    def specs(self) -> dict[str, Spec]:
        specs = {}
        for path in sorted(self.spec_dir.glob("SPEC-*.md")):
            actual = contained(self.root, path)
            if actual.stat().st_size > 1024 * 1024:
                raise SpecError(f"{path.name}: spec vượt giới hạn 1 MiB.")
            spec = Spec.parse(actual.read_text(encoding="utf-8-sig"), path)
            if spec.id in specs:
                raise SpecError(f"Trùng ID {spec.id}: {specs[spec.id].path.name} và {path.name}.")
            specs[spec.id] = spec
        return specs

    def find(self, sid: str) -> Spec:
        specs = self.specs()
        if sid not in specs:
            raise SpecError(f"Không tìm thấy {sid} trong {self.spec_dir}.")
        return specs[sid]

    @staticmethod
    def _validate(row: dict) -> dict:
        if row["kind"] not in ("approved", "changes_requested") or digest(row["snapshot"]) != row["revision"]:
            raise SpecError("Sổ quyết định không nhất quán; chưa thể xác nhận trạng thái duyệt.")
        return row

    def decisions(self, sid: str | None = None) -> list[dict]:
        if not self.db_path.exists():
            return []
        # Read commands do not create the DB or change its journal mode.
        connection = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            query = "SELECT * FROM decisions"
            params = ()
            if sid is not None:
                query += " WHERE spec_id = ?"
                params = (sid,)
            return [self._validate(dict(r)) for r in connection.execute(query + " ORDER BY seq DESC", params)]
        finally:
            connection.close()

    @staticmethod
    def status(spec: Spec, latest: dict | None) -> str:
        if latest is None:
            return "draft"
        return latest["kind"] if latest["revision"] == spec.revision else "needs_review"

    def decide(self, spec: Spec, revision: str, kind: str, actor: str, comment: str) -> dict:
        if revision not in (spec.revision, spec.revision[:12]):
            raise SpecError("Spec đã đổi hoặc mã phiên bản không đúng. Chạy review/diff rồi duyệt bản mới.")
        if kind == "approved" and spec.questions:
            raise SpecError("Chưa thể duyệt: còn quyết định chưa chốt: " + "; ".join(spec.questions))
        actor, comment = actor.strip(), comment.strip()
        if not actor or not clean_text(actor) or not clean_text(comment):
            raise SpecError("Tên người ghi nhận và comment phải là văn bản hợp lệ.")
        if kind == "changes_requested" and not comment:
            raise SpecError("Yêu cầu sửa cần --comment có nội dung.")
        # Re-read before persisting. Approval still binds to the stored snapshot,
        # so a subsequent external file edit is always reported as needs_review.
        if self.find(spec.id).revision != spec.revision:
            raise SpecError("Spec vừa thay đổi; hãy review lại trước khi ghi quyết định.")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                connection.execute(SCHEMA)
                connection.execute("BEGIN IMMEDIATE")
                latest = connection.execute("SELECT * FROM decisions WHERE spec_id = ? ORDER BY seq DESC LIMIT 1", (spec.id,)).fetchone()
                if latest:
                    latest = self._validate(dict(latest))
                    if all(latest[k] == v for k, v in {"revision": spec.revision, "kind": kind, "actor": actor, "comment": comment}.items()):
                        return latest
                cursor = connection.execute(
                    "INSERT INTO decisions (spec_id, kind, revision, snapshot, actor, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (spec.id, kind, spec.revision, spec.text, actor, comment, dt.datetime.now(dt.timezone.utc).isoformat()),
                )
                return dict(connection.execute("SELECT * FROM decisions WHERE seq = ?", (cursor.lastrowid,)).fetchone())
        finally:
            connection.close()


def public_decision(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "snapshot"}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="onecrew", description="Duyệt spec nhanh; lưu quyết định local, chưa chạy agent.")
    ap.add_argument("--project", type=Path, default=Path.cwd(), help="Project chứa thư mục specs (mặc định: thư mục hiện tại).")
    groups = ap.add_subparsers(dest="group", required=True)
    sp = groups.add_parser("spec", help="Danh sách, review và quyết định spec.")
    commands = sp.add_subparsers(dest="command", required=True)
    ls = commands.add_parser("list", help="Liệt kê spec và trạng thái duyệt.")
    ls.add_argument("--pending", action="store_true")
    for name, help_text in (
        ("review", "Đọc bản ngắn hoặc toàn bộ spec."),
        ("diff", "Xem thay đổi so với quyết định gần nhất."),
        ("approve", "Duyệt đúng nội dung đã xem; không chạy AI."),
        ("request-changes", "Ghi yêu cầu sửa spec."),
        ("history", "Xem lịch sử quyết định."),
    ):
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument("id")
        if name in ("review", "diff"):
            cmd.add_argument("--full", action="store_true")
        if name in ("approve", "request-changes"):
            cmd.add_argument("--revision", required=True, help="Mã phiên bản hiện khi review.")
            cmd.add_argument("--by", default=None, help="Nhãn người ghi nhận (mặc định: tài khoản OS; chưa xác thực).")
            cmd.add_argument("--comment", default="", required=name == "request-changes")
    for cmd in commands.choices.values():
        cmd.add_argument("--json", action="store_true", help="Xuất JSON.")
    return ap


def execute(args: argparse.Namespace) -> tuple[dict, str]:
    project = Project(args.project)
    if args.command == "list":
        decisions = project.decisions()
        latest = {}
        for row in decisions:
            latest.setdefault(row["spec_id"], row)
        rows = []
        for spec in project.specs().values():
            status = project.status(spec, latest.get(spec.id))
            if not args.pending or status != "approved":
                rows.append({"id": spec.id, "title": spec.title, "status": status, "revision": spec.revision, "open_questions": len(spec.questions)})
        lines = [f"{r['id']:<12} {STATUSES[r['status']]:<17} {r['title']}" for r in rows]
        return {"specs": rows}, "\n".join(lines) if lines else "Không có spec phù hợp."

    spec = project.find(args.id)
    if args.command in ("approve", "request-changes"):
        kind = "approved" if args.command == "approve" else "changes_requested"
        row = project.decide(spec, args.revision, kind, args.by if args.by is not None else getpass.getuser(), args.comment)
        data = public_decision(row)
        return data, f"{STATUSES[kind]}: {spec.id} / {spec.revision[:12]} — {row['actor']}\nĐã ghi quyết định. Chưa khởi chạy agent."

    decisions = project.decisions(spec.id)
    latest = decisions[0] if decisions else None
    status = project.status(spec, latest)
    if args.command == "review":
        content = spec.text if args.full else spec.brief
        data = {"id": spec.id, "status": status, "revision": spec.revision, "review_code": spec.revision[:12], "content": content, "open_questions": list(spec.questions)}
        footer = f"\nTrạng thái: {STATUSES[status]} | Mã bản duyệt: {spec.revision[:12]}"
        if spec.questions:
            footer += f"\nCòn {len(spec.questions)} quyết định chưa chốt; chưa thể approve."
        else:
            footer += f"\nLệnh duyệt: spec approve {spec.id} --revision {spec.revision[:12]}"
        return data, content.rstrip() + "\n" + footer
    if args.command == "history":
        rows = [public_decision(r) for r in decisions]
        lines = [f"{r['created_at']} | {STATUSES[r['kind']]} | {r['revision'][:12]} | {r['actor']}" + (f"\n  {r['comment']}" if r['comment'] else "") for r in rows]
        return {"id": spec.id, "decisions": rows}, "\n".join(lines) if lines else "Chưa có quyết định."
    if latest is None:
        return {"id": spec.id, "baseline": None, "diff": None}, "Chưa có quyết định để so sánh. Hãy chạy spec review."
    previous = Spec.parse(latest["snapshot"], spec.path)
    before = previous.text if args.full else previous.brief
    after = spec.text if args.full else spec.brief
    delta = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=f"{spec.id} đã {latest['kind']} ({previous.revision[:12]})", tofile=f"{spec.id} hiện tại ({spec.revision[:12]})"))
    details_changed = previous.details != spec.details
    data = {"id": spec.id, "baseline": previous.revision, "revision": spec.revision, "diff": delta, "details_changed": details_changed}
    text = delta or "Không đổi trong phần đang xem."
    if details_changed and not args.full:
        text += "\nChi tiết cho AI đã đổi. Dùng spec diff " + spec.id + " --full để xem."
    return data, text


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        data, text = execute(args)
        print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else text)
        return 0
    except (SpecError, OSError, UnicodeError, sqlite3.Error) as error:
        message = f"Không thể thực hiện: {error}"
        if args.json:
            print(json.dumps({"error": message}, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
        return 2
