# Test the handover package FROM THE ARTIFACT (directive I). Thin CLI: the logic and the verdict (`judge`) live in wfkit/package_check.py.
#   python docs/wf/audit/tools/verify_package.py <package dir> <work dir (new, outside the checkout)>
# Writes <work>/verification/verify-report.json (steps, rollback facts and judge's verdict). Exit 0 only when judge says pass.
# The scope (which steps are mandatory) and the identity the report is bound to come from <package>/manifest.json + the files on disk
# (package_check.package_scope), never from the report (Codex P1-3).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from wfkit import package_check  # noqa: E402

if __name__ == '__main__':
    sys.exit(package_check.main())
