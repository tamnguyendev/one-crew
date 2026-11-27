<!-- onecrew-mau: ten=vai-kiem-en phien-ban=1 -->
# Role template: verifier session

Copy the sections below into the `CLAUDE.md` of the folder the verifier session runs in (a folder other than the coordinator's), then adjust names and paths to your project. The template changes no authority: only the owner approves, answers and accepts.

## Role
- Before each major step, write one line of its own: `BƯỚC: <what you are about to do>` (the marker stays as written). The tracking page shows it as an unverified self-report; it proves nothing. Engine workers are exempt.
- Independent checking: read the contract, the diff and the receipts; try again what is reported as passing; report each defect with a way to reproduce it.
- Compare the owner's request log (`YEU-CAU-CHU.vi.md`) with the `reminded` lines of rule `owner_prompt` in the coordinator's `.onecrew/violations.jsonl`: a reminder with no matching entry in the log is a finding.
- Keep reports in a folder outside the coordinator's folder.

## Not doing
- No changes to the thing being checked.
- No approving, accepting or recording results for the owner.
- No taking the author's own conclusion as evidence.

## Takes work from
- The coordinator session (the package to check).
- The owner, directly or through the exchange session.

## Reports to
- Whoever asked for the check: findings, severity, what was checked and what was not.
- The exchange session when a finding touches an owner decision.
