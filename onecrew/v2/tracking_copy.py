"""Run a temporary tracking viewer over a copy of one project's ledger data."""
import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path

from ..ledger import LedgerError
from . import tracking_web


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def _backup(source, target):
    # A read-only WAL connection may still create shared-memory sidecars.
    # The development ledger uses rollback journaling; refuse other formats here.
    with source.open('rb') as header:
        raw = header.read(20)
        if not raw.startswith(b'SQLite format 3\x00') or raw[18:20] != b'\x01\x01':
            raise LedgerError('Sổ nguồn phải dùng chế độ rollback journal để mở bản sao.')
    deadline = time.monotonic() + 30

    def progress(status, remaining, total):
        if status != sqlite3.SQLITE_DONE and time.monotonic() >= deadline:
            raise LedgerError('Sổ nguồn đang bận. Chưa tạo được bản sao.')

    with (closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as reader,
          closing(sqlite3.connect(target)) as writer):
        reader.backup(writer, pages=256, progress=progress)


def serve(state_root, project, project_id, clone, scratch, *, port=0, browser=True, idle_exit=1800):
    state_root, project, clone, scratch = (Path(path).resolve() for path in (state_root, project, clone, scratch))
    git_dir = clone / '.git'
    if not git_dir.is_dir() or git_dir.resolve() != git_dir or _overlap(clone, project) or _overlap(clone, state_root):
        raise LedgerError('--clone phải là bản clone Git riêng, nằm ngoài dự án và sổ nguồn.')
    if not scratch.is_dir() or any(_overlap(scratch, path) for path in (project, clone, state_root)):
        raise LedgerError('--scratch phải là thư mục có sẵn, tách khỏi dự án, clone và sổ nguồn.')

    with tempfile.TemporaryDirectory(prefix='onecrew-track-copy-', dir=scratch) as directory:
        copied = Path(directory)
        ledger = copied / 'ledger.sqlite3'
        try:
            _backup(state_root / ledger.name, ledger)
            with closing(sqlite3.connect(ledger)) as conn, conn:
                # Keep the project's logical ID so plan revisions, receipts and historical links still resolve.
                updated = conn.execute('UPDATE tasks SET project_path=? WHERE project_id=?',
                                       (os.path.normcase(str(clone)), project_id))
                if not updated.rowcount:
                    raise LedgerError('Sổ nguồn chưa có việc của dự án đã chọn.')
        except sqlite3.Error as error:
            raise LedgerError(f'Không sao chép được sổ nguồn: {error}') from error
        for name in ('plans', 'snapshots'):
            source = state_root / name
            if source.is_dir():
                shutil.copytree(source, copied / name)

        return tracking_web.serve(copied, project_id=project_id, port=port, comparison=False, browser=browser, idle_exit=idle_exit)
