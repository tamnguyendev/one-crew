# OneCrew in one page

OneCrew is a work contract for AI: the AI works only inside a plan the owner approved, every milestone needs an independent verdict, and only a human accepts the result.

## 1. Install

You need Python 3.10+, git, and (for reviewers and `plan advise`) the Claude CLI, logged in.

```bash
python -m venv .venv
.venv/bin/pip install onecrew-2.2.0.dev2-py3-none-any.whl      # Windows: .venv\Scripts\pip
```

## 2. Set up a repo

```bash
cd your-repo                    # a git repository
onecrew init                    # asks y/N; --yes skips the question
```

`init` creates the ledger (default: `%LOCALAPPDATA%\OneCrew` on Windows, `~/.onecrew` elsewhere; `--state-root P` picks another place outside the repo), writes `plans/owner-rules.md` from a template, records the state root in `.onecrew/config.json`, and merges the Claude Code hooks into `.claude/settings.local.json` (`--shared`: `settings.json`). Your other hooks and permissions stay; a `.bak` copy is kept before the first change; running it again changes nothing. It checks the Claude CLI but never logs in for you (exit 1 if it is missing or logged out; the ledger and hooks are still written). Set `ONECREW_LANG=vi` for Vietnamese output.

## 3. Check

```bash
onecrew doctor                  # one PASS / WARN / FAIL line per check; exit 1 on any FAIL
```

## 4. Your first contract

Write a contract file (see `examples/v2-plan-l1.json`), then:

```bash
onecrew plan lint --file contract.json --author <model id>
onecrew plan propose my-job --file contract.json --author <model id>
onecrew owner approve my-job --reference "said yes in chat"     # you, in your own terminal
onecrew owner enforce my-job                                    # hooks start blocking edits outside the contract
# ... the AI works inside the contract ...
onecrew verdict run --plan my-job --milestone M1                # independent check of each milestone
onecrew plan report my-job
onecrew owner accept my-job --artifact-sha <sha> --reference "tried it"
```

`owner approve | accept | enforce | record` are refused inside an AI session; they are yours. Without `--project` and `--state-root`, commands use the repo you are in and the state root in its `.onecrew/config.json`.

## 5. Uninstall

Delete the OneCrew entries from `.claude/settings.local.json` (or restore the `.bak` file), delete `.onecrew/` in the repo, and `pip uninstall onecrew`. The ledger folder is yours to keep or delete.
