from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from onecrew.specs import main

REPO = Path(__file__).resolve().parents[1]
SANDBOXES = REPO / ".onecrew" / "test-sandboxes"
SAMPLE = (REPO / "specs" / "SPEC-001-duyet-spec.md").read_text(encoding="utf-8")


class SpecReviewTests(unittest.TestCase):
    def setUp(self):
        SANDBOXES.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="duyệt spec ", dir=SANDBOXES)).resolve()
        (self.root / "specs").mkdir()
        self.path = self.root / "specs" / "SPEC-001-duyet-spec.md"
        self.path.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self):
        # Verify the absolute recursive deletion target before cleanup on Windows.
        resolved = self.root.resolve()
        self.assertTrue(resolved.is_relative_to(SANDBOXES.resolve()))
        self.assertNotEqual(resolved, SANDBOXES.resolve())
        shutil.rmtree(resolved)

    def invoke(self, *args, expected=0):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            result = main(["--project", str(self.root), "spec", *args, "--json"])
        self.assertEqual(result, expected, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue())

    def review_code(self):
        return self.invoke("review", "SPEC-001")["review_code"]

    def approve(self):
        return self.invoke("approve", "SPEC-001", "--revision", self.review_code(), "--by", "Test reviewer")

    def test_brief_and_full_share_revision_without_creating_state(self):
        brief = self.invoke("review", "SPEC-001")
        full = self.invoke("review", "SPEC-001", "--full")
        self.assertEqual(brief["revision"], full["revision"])
        self.assertIn("### Nghiệm thu", brief["content"])
        self.assertNotIn("### Dữ liệu và hiển thị", brief["content"])
        self.assertIn("### Dữ liệu và hiển thị", full["content"])
        self.assertEqual(self.invoke("list")["specs"][0]["status"], "draft")
        self.assertEqual(self.invoke("history", "SPEC-001")["decisions"], [])
        self.assertIsNone(self.invoke("diff", "SPEC-001")["baseline"])
        self.assertFalse((self.root / ".onecrew").exists())

    def test_approve_pending_filter_and_idempotent_repeat(self):
        approved = self.approve()
        self.assertEqual(approved["kind"], "approved")
        self.assertEqual(approved["actor"], "Test reviewer")
        self.assertEqual(self.invoke("list")["specs"][0]["status"], "approved")
        self.assertEqual(self.invoke("list", "--pending")["specs"], [])
        self.approve()
        self.assertEqual(len(self.invoke("history", "SPEC-001")["decisions"]), 1)

    def test_changed_scope_rejects_old_review_code_and_preserves_decision(self):
        old = self.review_code()
        self.approve()
        self.path.write_text(SAMPLE.replace("Anh xem đề xuất ngắn", "Nhóm vận hành xem đề xuất ngắn"), encoding="utf-8")
        self.invoke("approve", "SPEC-001", "--revision", old, expected=2)
        current = self.invoke("list", "--pending")["specs"][0]
        self.assertEqual(current["status"], "needs_review")
        delta = self.invoke("diff", "SPEC-001")
        self.assertIn("+Nhóm vận hành", delta["diff"])
        self.assertFalse(delta["details_changed"])
        self.assertEqual(len(self.invoke("history", "SPEC-001")["decisions"]), 1)

    def test_details_only_change_is_visible_and_invalidates_approval(self):
        self.approve()
        self.path.write_text(SAMPLE + "\n### Chi tiết bổ sung\nMột thay đổi kỹ thuật mới.\n", encoding="utf-8")
        delta = self.invoke("diff", "SPEC-001")
        self.assertEqual(delta["diff"], "")
        self.assertTrue(delta["details_changed"])
        self.assertIn("+Một thay đổi kỹ thuật mới.", self.invoke("diff", "SPEC-001", "--full")["diff"])
        self.assertEqual(self.invoke("list")["specs"][0]["status"], "needs_review")

    def test_change_request_retains_previous_approval_and_comment(self):
        self.approve()
        self.invoke("request-changes", "SPEC-001", "--revision", self.review_code(), "--comment", "Tách dashboard sang bản sau", "--by", "Test reviewer")
        history = self.invoke("history", "SPEC-001")["decisions"]
        self.assertEqual([r["kind"] for r in history], ["changes_requested", "approved"])
        self.assertEqual(history[0]["comment"], "Tách dashboard sang bản sau")
        self.assertEqual(self.invoke("list", "--pending")["specs"][0]["status"], "changes_requested")

    def test_open_questions_block_approval_but_allow_change_request(self):
        self.path.write_text(SAMPLE.replace("Không có.", "- [ ] Dùng giới hạn nào?"), encoding="utf-8")
        code = self.review_code()
        self.assertEqual(len(self.invoke("review", "SPEC-001")["open_questions"]), 1)
        self.invoke("approve", "SPEC-001", "--revision", code, expected=2)
        self.assertFalse((self.root / ".onecrew").exists())
        self.invoke("request-changes", "SPEC-001", "--revision", code, "--comment", "Ghi đề xuất giới hạn")

    def test_resolved_questions_allow_approval(self):
        self.path.write_text(SAMPLE.replace("Không có.", "- [x] Dùng giới hạn đã chốt."), encoding="utf-8")
        self.assertEqual(self.approve()["kind"], "approved")

    def test_newline_only_conversion_does_not_invalidate_approval(self):
        self.approve()
        self.path.write_bytes(SAMPLE.replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(self.invoke("list")["specs"][0]["status"], "approved")

    def test_invalid_specs_fail_without_state(self):
        for content in (
            SAMPLE.replace("### Phạm vi", "### Đổi tên mục"),
            SAMPLE.replace("Không có.", "Còn một câu hỏi chưa trả lời"),
            SAMPLE.replace("Anh xem đề xuất ngắn", "\x1b[2JAnh xem đề xuất ngắn"),
            SAMPLE.replace("### Kết quả\n", "### Kết quả\n" + "dài " * 351),
            SAMPLE.partition("## Chi tiết cho AI")[0],
            SAMPLE.replace("Anh xem đề xuất ngắn rồi duyệt hoặc yêu cầu sửa ngay trong terminal.", ""),
        ):
            with self.subTest(content=content[:60]):
                self.path.write_text(content, encoding="utf-8")
                self.invoke("review", "SPEC-001", expected=2)
                self.assertFalse((self.root / ".onecrew").exists())

    def test_duplicate_id_and_unknown_id_rejected(self):
        self.invoke("review", "SPEC-999", expected=2)
        duplicate = self.root / "specs" / "SPEC-001-duplicate.md"
        duplicate.write_text(SAMPLE, encoding="utf-8")
        self.invoke("list", expected=2)

    def test_invalid_neighbor_does_not_block_review_or_decision(self):
        neighbor = self.root / "specs" / "SPEC-002-draft.md"
        neighbor.write_text("# SPEC-002 — Đang soạn\n", encoding="utf-8")
        listed = self.invoke("list", expected=2)
        self.assertEqual([r["id"] for r in listed["specs"]], ["SPEC-001"])
        self.assertEqual(listed["errors"][0]["id"], "SPEC-002")
        self.assertEqual(listed["errors"][0]["path"], "specs/SPEC-002-draft.md")
        brief = self.invoke("review", "SPEC-001")
        self.assertEqual(brief["revision"], self.invoke("review", "SPEC-001", "--full")["revision"])
        self.assertFalse((self.root / ".onecrew").exists())
        self.approve()
        pending = self.invoke("list", "--pending", expected=2)
        self.assertEqual(pending["specs"], [])
        self.assertEqual(len(pending["errors"]), 1)
        self.assertEqual(self.invoke("diff", "SPEC-001")["diff"], "")
        self.invoke("request-changes", "SPEC-001", "--revision", brief["review_code"], "--comment", "Sửa câu mô tả")
        self.assertEqual(len(self.invoke("history", "SPEC-001")["decisions"]), 2)

    def test_mixed_inventory_never_reports_invalid_spec_as_approved(self):
        self.approve()
        self.path.write_text("# SPEC-001 — Đang sửa\n", encoding="utf-8")
        neighbor = self.root / "specs" / "SPEC-002-valid.md"
        neighbor.write_text(SAMPLE.replace("SPEC-001", "SPEC-002"), encoding="utf-8")
        for options in ((), ("--pending",)):
            listed = self.invoke("list", *options, expected=2)
            self.assertEqual([(r["id"], r["status"]) for r in listed["specs"]], [("SPEC-002", "draft")])
            self.assertEqual(listed["errors"][0]["id"], "SPEC-001")

    def test_duplicate_id_isolated_but_target_approval_refused(self):
        old = self.approve()["revision"]
        duplicate = self.root / "specs" / "SPEC-001-duplicate.md"
        duplicate.write_text("# SPEC-001 — Chưa viết xong\n", encoding="utf-8")
        neighbor = self.root / "specs" / "SPEC-002-valid.md"
        neighbor.write_text(SAMPLE.replace("SPEC-001", "SPEC-002"), encoding="utf-8")
        listed = self.invoke("list", expected=2)
        self.assertEqual([r["id"] for r in listed["specs"]], ["SPEC-002"])
        self.assertEqual([r["id"] for r in listed["errors"]], ["SPEC-001", "SPEC-001"])
        self.assertTrue(all("Trùng ID" in r["error"] for r in listed["errors"]))
        self.invoke("review", "SPEC-001", expected=2)
        self.invoke("approve", "SPEC-001", "--revision", old, expected=2)
        code = self.invoke("review", "SPEC-002")["review_code"]
        self.invoke("approve", "SPEC-002", "--revision", code)
        self.assertEqual(len(self.invoke("history", "SPEC-001")["decisions"]), 1)

    def test_invalid_file_bytes_and_size_are_isolated(self):
        neighbor = self.root / "specs" / "SPEC-002-draft.md"
        for content in (b"\xff", b"x" * (1024 * 1024 + 1)):
            with self.subTest(content_size=len(content)):
                neighbor.write_bytes(content)
                listed = self.invoke("list", expected=2)
                self.assertEqual([r["id"] for r in listed["specs"]], ["SPEC-001"])
                self.assertEqual(listed["errors"][0]["id"], "SPEC-002")
                self.assertEqual(self.invoke("review", "SPEC-001")["status"], "draft")
        self.assertFalse((self.root / ".onecrew").exists())

    def test_history_survives_malformed_and_missing_current_spec(self):
        approved = self.approve()
        db = self.root / ".onecrew" / "spec-reviews.sqlite3"
        stored = db.read_bytes()
        self.path.write_text("# SPEC-001 — Đang sửa\n", encoding="utf-8")
        self.assertEqual(self.invoke("history", "SPEC-001")["decisions"], [approved])
        self.path.unlink()
        self.assertEqual(self.invoke("history", "SPEC-001")["decisions"], [approved])
        self.assertEqual(db.read_bytes(), stored)

    def test_history_without_decisions_does_not_create_state(self):
        self.path.write_text("# SPEC-001 — Đang soạn\n", encoding="utf-8")
        for sid in ("SPEC-001", "SPEC-999"):
            self.assertEqual(self.invoke("history", sid)["decisions"], [])
        self.invoke("history", "invalid-id", expected=2)
        self.assertFalse((self.root / ".onecrew").exists())

    def test_history_still_rejects_corrupt_ledger(self):
        self.approve()
        self.path.write_text("# SPEC-001 — Đang sửa\n", encoding="utf-8")
        db = self.root / ".onecrew" / "spec-reviews.sqlite3"
        with contextlib.closing(sqlite3.connect(db)) as con:
            with con:
                con.execute("UPDATE decisions SET snapshot = ?", ("corrupt",))
        self.assertIn("Sổ quyết định", self.invoke("history", "SPEC-001", expected=2)["error"])
        db.write_bytes(b"not sqlite data")
        self.assertIn("database", self.invoke("history", "SPEC-001", expected=2)["error"])

    def test_plain_text_inventory_keeps_valid_and_invalid_entries(self):
        neighbor = self.root / "specs" / "SPEC-002-draft.md"
        neighbor.write_text("# SPEC-002 — Đang soạn\n", encoding="utf-8")
        process = subprocess.run([sys.executable, "-m", "onecrew", "--project", str(self.root), "spec", "list"], cwd=REPO, capture_output=True, encoding="utf-8")
        self.assertEqual(process.returncode, 2)
        self.assertIn("SPEC-001", process.stdout)
        self.assertIn("CHỜ DUYỆT", process.stdout)
        self.assertIn("SPEC-002-draft.md", process.stdout)
        self.assertIn("LỖI", process.stdout)
        self.assertEqual(process.stderr, "")

    def test_wrong_code_empty_actor_or_comment_do_not_write(self):
        code = self.review_code()
        self.invoke("approve", "SPEC-001", "--revision", "0" * 12, expected=2)
        self.invoke("approve", "SPEC-001", "--revision", code, "--by", " ", expected=2)
        self.invoke("request-changes", "SPEC-001", "--revision", code, "--comment", " ", expected=2)
        self.assertFalse((self.root / ".onecrew").exists())

    def test_corrupt_database_is_not_reported_as_draft_or_approved(self):
        state = self.root / ".onecrew"
        state.mkdir()
        (state / "spec-reviews.sqlite3").write_bytes(b"not sqlite data")
        self.invoke("list", expected=2)
        self.invoke("review", "SPEC-001", expected=2)

    def test_inconsistent_snapshot_is_rejected(self):
        self.approve()
        with contextlib.closing(sqlite3.connect(self.root / ".onecrew" / "spec-reviews.sqlite3")) as con:
            with con:
                con.execute("UPDATE decisions SET snapshot = ?", ("corrupt",))
        self.invoke("list", expected=2)

    def test_project_path_with_unicode_spaces_and_real_module_entry(self):
        process = subprocess.run([sys.executable, "-m", "onecrew", "--project", str(self.root), "spec", "list", "--json"], cwd=REPO, capture_output=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["specs"][0]["id"], "SPEC-001")

    @unittest.skipUnless(os.name == "nt", "Windows launcher")
    def test_powershell_launcher_preserves_cwd_and_project_argument(self):
        environment = dict(os.environ, ONECREW_PYTHON=sys.executable)
        launcher = ["powershell.exe", "-NoProfile", "-File", str(REPO / "onecrew.ps1")]
        for options in (["spec", "list", "--json"], ["--project", str(self.root), "spec", "list", "--json"]):
            process = subprocess.run([*launcher, *options], cwd=self.root, env=environment, capture_output=True, encoding="utf-8")
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)["specs"][0]["id"], "SPEC-001")

    def test_path_guard_rejects_escape(self):
        from onecrew.specs import contained, SpecError
        with self.assertRaises(SpecError):
            contained(self.root, self.root / ".." / "outside")


if __name__ == "__main__":
    unittest.main()
