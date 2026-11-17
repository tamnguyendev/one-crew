# OneCrew in one page

OneCrew is a work contract for AI: the AI works only inside a plan the owner approved, every milestone needs an independent verdict, and only a human accepts the result.

Current version: `2.5.0.dev30` (beta, prerelease), tested on Windows 10/11 only. Always install from a release tag, not from `main`. The full guide (in Vietnamese) is the root [README.md](../README.md).

## 1. Install (Windows, once per machine)

You need Python 3.10+ from python.org (not the Microsoft Store alias), git 2.40+, PowerShell 5.1+, and the Claude CLI, logged in.

```powershell
python -m venv D:\OneCrew\venv
D:\OneCrew\venv\Scripts\python.exe -m pip install "git+https://github.com/tamnguyendev/one-crew.git@v2.5.0.dev30"
D:\OneCrew\venv\Scripts\onecrew.exe --version      # onecrew 2.5.0.dev30
```

Keep the venv where it is: the hooks written into your repo call its `onecrew.exe`.

Alternatives: download the release wheel `onecrew-2.5.0.dev30-py3-none-any.whl` and check it against `SHA256SUMS` (compare the hash with `Get-FileHash`, not the file name) before installing it with pip; or `git clone --branch v2.5.0.dev30 https://github.com/tamnguyendev/one-crew.git` and run `pip install .` in it. Linux and macOS are not tested.

## 2. Set up a repo

Use a git repository with at least one commit. Below, `onecrew` stands for the full path to `onecrew.exe`.

```powershell
onecrew --project <repo> --state-root <ledger-folder> init      # asks y/N
```

`init` creates the ledger in the state root (keep it outside the repo), writes `plans/owner-rules.md`, records the state root in `<repo>\.onecrew\config.json`, merges the Claude Code hooks into `.claude\settings.local.json` (`--shared`: `settings.json`) and adds a small wiki skeleton under `docs\wiki\`. Your other hooks and permissions stay; a `.bak` copy is kept; running it again changes nothing. It checks the Claude CLI but never logs in for you (exit 1 if missing or logged out; the files are still written). Set `ONECREW_LANG=vi` for Vietnamese output.

`init` also writes `.onecrew/.gitignore`, so git ignores that folder (the config holds a path specific to your machine); your own `.gitignore` is not touched.

## 3. Check

```powershell
onecrew --project <repo> --state-root <ledger-folder> doctor    # one PASS / WARN / FAIL line per check; exit 1 on any FAIL
```

Then **open a NEW Claude Code session in the repo**: Claude Code loads hooks only at session start.

### Install the user hook (once per machine, from your own terminal)

The hook `init` writes lives in the repo, so a Claude Code session opened **outside** it (in another repo, say) and its subagents are not checked against this repo's contract when they write here. To check them:

```powershell
onecrew hook user install      # remove: hook user uninstall; look: hook user status
```

It adds exactly one PreToolUse entry to `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR\settings.json`), keeps every other setting, copies the file to `.bak` once, and refuses to run inside an AI session. From then on every Claude Code session on this machine, and its subagents, is checked against the plan of the project it writes in when it uses Edit/Write/MultiEdit/NotebookEdit/Bash/PowerShell; a project with no plan runs as before. `doctor` has a `user hook` line. Open a new Claude Code session after installing.

Not covered: other AI tools, programs that write files without those tools, and the hook is not an OS sandbox. `cd "$VAR"` and interpreter code with a computed path are refused, but only where a plan governs the place. If the `onecrew` program the hook names is deleted or moved, every write is blocked until you reinstall or uninstall (`doctor` shows FAIL).

## 4. Your first contract

Describe the job to the AI in the new session. It writes a contract file; a sample that lints clean is [docs/obs2/su-dung/mau-hop-dong.json](obs2/su-dung/mau-hop-dong.json). Then (every command takes `--project <repo> --state-root <ledger-folder>`):

```powershell
onecrew ... plan lint --file contract.json --author <model id>
onecrew ... plan propose my-job --file contract.json --author <model id>
onecrew ... owner approve my-job --reference "said yes in chat" --human   # you, in your own terminal
onecrew ... owner enforce my-job --human                                  # hooks start blocking edits outside the contract
# ... the AI works inside the contract ...
onecrew ... verdict run --plan my-job --milestone M1                      # independent check of each milestone
onecrew ... plan report my-job
onecrew ... verdict artifact --plan my-job                                # prints the sha to accept
onecrew ... owner accept my-job --artifact-sha <sha> --reference "tried it" --human
```

`owner approve | accept | enforce | record` are refused inside an AI session; they are yours. The sha from `verdict artifact` must match the passed milestone in `plan report`.

## 5. Watch progress

```powershell
onecrew ... track open
```

Opens a read-only page on `127.0.0.1` listing every job in the ledger, what waits for your approval, each milestone's verdict and the history. It runs nothing, and closing it does not stop the AI.

## 6. Uninstall

Delete the OneCrew entries from `.claude\settings.local.json` (or restore the `.bak` file), delete `.onecrew\` in the repo, and delete the venv. The ledger folder is yours to keep or delete. To upgrade, install the new tag into a fresh venv and run `init` again so the hooks point to it.
