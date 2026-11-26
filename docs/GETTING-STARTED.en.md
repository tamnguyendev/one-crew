# Getting started with OneCrew

This walkthrough targets **Windows and OneCrew `2.5.0.dev31`**, the current beta. Start with a disposable Git project and a separate ledger. You do not need to move an existing project's hooks or state to try it.

You need PowerShell 5.1+, Python 3.10+ with the `py` launcher, Git 2.40+, and a working, authenticated Claude Code CLI. `py -0p`, `git --version`, and `claude --version` help check installed tools. Real assistant work uses your provider account and may incur charges under that account.

You will use two windows: **your PowerShell terminal** for setup and owner decisions, and **Claude Code** for preparing and doing the task. Keep the PowerShell window open so its variables remain available. Commands below are for PowerShell, not Git Bash or Command Prompt.

Terms used here: a **plan** is the agreed scope and checks; a **milestone** is a checkpoint; a **verdict** is its check result; the **state directory** holds the local ledger and evidence. Approval authorizes the work; acceptance confirms you are satisfied with its checked result.

## 1. Download and install

From the [dev31 release](https://github.com/tamnguyendev/one-crew/releases/tag/v2.5.0.dev31), download `onecrew-2.5.0.dev31-py3-none-any.whl` and `SHA256SUMS`.

Also download the [English first-task template](../examples/hello-onecrew.template.json) using GitHub's **Raw / Download raw file** control, and save it as `hello-onecrew.template.json` beside the wheel. Download the JSON content, not the HTML page. It is documentation supplied here, not an extra release asset.

Open PowerShell in that download directory and verify the published wheel hash:

```powershell
$ErrorActionPreference = 'Stop'
$Wheel = (Resolve-Path '.\onecrew-2.5.0.dev31-py3-none-any.whl').Path
$TemplateDownload = (Resolve-Path '.\hello-onecrew.template.json').Path
$Expected = '1e0a5f9704b54fe90b580d58d01c1267b828a34dcaeb4743764db85fddadd892'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Wheel).Hash -ne $Expected) {
    throw 'Wheel checksum mismatch. Do not install this file.'
}
```

Compare the value with the release's `SHA256SUMS` too. This hash is for dev31, not the separate MR-R wheel.

Create a new environment. Keep these variables in the same PowerShell window for the walkthrough:

```powershell
$Demo = Join-Path $env:LOCALAPPDATA ('OneCrewDemo\trial-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $Demo) { throw 'Choose an unused demo directory.' }
$Venv = Join-Path $Demo 'venv'
$Project = Join-Path $Demo 'project'
$State = Join-Path $Demo 'state'
py -3 -m venv $Venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
& "$Venv\Scripts\python.exe" -m pip install --no-index $Wheel
if ($LASTEXITCODE -ne 0) { throw 'Installation failed.' }
$OneCrew = Join-Path $Venv 'Scripts\onecrew.exe'
$ContractTemplate = Join-Path $Demo 'hello-onecrew.template.json'
Copy-Item -LiteralPath $TemplateDownload -Destination $ContractTemplate
Get-Content -Raw -LiteralPath $ContractTemplate | ConvertFrom-Json | Out-Null
& $OneCrew --version
$env:ONECREW_LANG = 'en'
```

Expected: `onecrew 2.5.0.dev31`. Hooks reference this executable by path, so keep the venv in place while using them.

Stop on any error. If the template fails JSON parsing, download the raw JSON again. `ONECREW_LANG=en` selects English for translated commands; it does not translate every UI message. The guide uses JSON owner-command output because the beta's `--human` formatter still includes Vietnamese text.

## 2. Create a disposable project

```powershell
New-Item -ItemType Directory -Path $Project | Out-Null
git -C $Project init
if ($LASTEXITCODE -ne 0) { throw 'Git initialization failed.' }
@('.onecrew/', '.claude/settings.local.json', '.claude/settings.local.json.bak') |
    Set-Content -Encoding ASCII -LiteralPath (Join-Path $Project '.gitignore')
git -C $Project add .gitignore
if ($LASTEXITCODE -ne 0) { throw 'Could not stage the demo file.' }
git -C $Project -c user.name='OneCrew Demo' -c user.email='demo@example.invalid' commit -m 'Create disposable demo'
if ($LASTEXITCODE -ne 0) { throw 'The project needs an initial commit.' }
& $OneCrew --project $Project --state-root $State init
```

Read the proposed changes, then answer `y` in your terminal. `init` creates or updates:

| Location | Purpose |
|---|---|
| `$State` | Local ledger and owner rules. Keep it outside the project. |
| `$Project\.onecrew\config.json` | The state-directory binding. Keep it out of version control. |
| `$Project\.claude\settings.local.json` | Claude Code hooks, merged with existing settings; a backup is kept when changed. |
| `$Project\docs\wiki` | Project-context and lessons skeleton, preserving existing content. |
| `%LOCALAPPDATA%\OneCrew\hook-projects.json` | A local registry entry mapping the project to its state directory. |

The demo has its own project, venv, and ledger, but ordinary `init` registers it in the user's hook registry. This is not a zero-write sandbox. It does not authorize changing another project's hooks or runtime.

```powershell
& $OneCrew --project $Project --state-root $State doctor
```

Expected: no `FAIL` checks. Investigate relevant warnings. `init` can write configuration and still exit nonzero if the Claude CLI is unavailable or not authenticated; inspect the output rather than assuming nothing was written.

Open a **new Claude Code session rooted at `$Project`** so its hooks are loaded. In a second PowerShell window, paste the project path printed below, change into it with `Set-Location -LiteralPath 'the printed path'`, and run `claude`. Do not open the parent demo directory instead. Keep your first PowerShell terminal for owner commands. Configuration checks are not live proof that a hook intercepted a tool call.

## 3. Give the assistant a small first task

Supply the full values of `$OneCrew`, `$Project`, and `$State` to the new session. Display them with:

```powershell
[ordered]@{ OneCrew = $OneCrew; Project = $Project; StateRoot = $State; ContractTemplate = $ContractTemplate } | ConvertTo-Json
```

Then give the assistant this request:

```text
Use the executable, project, state root, and English ContractTemplate I supplied.
Read the template and save an adapted contract beside it, outside the project.
Prepare a schema-v2 plan named hello-onecrew for this disposable project.
Goal: create docs/hello-onecrew.md with the single line Hello OneCrew,
optionally followed by one final newline.
Own only that output file. Do not change other project files.
Use one milestone, M1, with a command verifier that checks the exact content.
Use the real request, date, and your actual model identifier as provenance.
Replace the template's origin placeholders with this request and its actual date.
Keep its content-check command; lint the adapted file and propose it with
your actual model ID as --author. Run plan precheck hello-onecrew and resolve
any precondition failure before asking me to approve. Do not claim a different
model identity or weaken a check.
Explain the scope and check to me. Do not run owner commands or implement
the output until I have approved and enforced the plan in my terminal.
After approval, do the task and run M1. Report evidence and failures honestly.
```

The template is only for this greeting task. The assistant must fill its provenance before proposing it. It must not weaken the check to make a failure pass. Keep the template and adapted contract outside the project so they do not become extra project outputs.

The assistant runs `plan lint` and `plan propose` with its actual model ID. Read the proposed plan:

```powershell
& $OneCrew --project $Project --state-root $State plan show hello-onecrew
```

Check the editable path, output, milestone command, and budget before approving. The verifier must test the output, not just print a success message.

## 4. Approve, work, and check

When the plan matches your request, run these in **your own terminal**, not an assistant's tool shell:

```powershell
& $OneCrew --project $Project --state-root $State owner approve hello-onecrew --reference 'Reviewed the greeting task scope and exact-content check'
if ($LASTEXITCODE -ne 0) { throw 'Inspect the approval result before continuing.' }
& $OneCrew --project $Project --state-root $State owner enforce hello-onecrew
if ($LASTEXITCODE -ne 0) { throw 'Inspect the enforcement result before continuing.' }
```

Read the JSON result: approval should refer to `hello-onecrew`, and enforcement should report `mode: enforce`. If a command refuses, read its reason and stop before implementation. Do not remove a check to force approval.

Tell the assistant the plan is approved and enforced. It can do the authorized work and run:

```powershell
& $OneCrew --project $Project --state-root $State verdict run --plan hello-onecrew --milestone M1
& $OneCrew --project $Project --state-root $State plan report hello-onecrew
```

Expected: M1 has a passing result tied to the checked artifact. Failed or inconclusive checks are not passes. Repairs must stay inside the grant. This simple command check does not require an extra model reviewer. Do not edit project files between the passing check and acceptance: that can change the artifact and require a new check.

## 5. See progress and accept the result

```powershell
& $OneCrew --project $Project --state-root $State track open
```

The local page lists recorded tasks and shows the selected plan's solution, changes, results, and timeline. Owner actions may have copyable commands when the runtime/project binding is verified; the page does not execute them.

The dashboard is currently primarily Vietnamese. These labels help you navigate it:

| Label | Meaning |
|---|---|
| `Tổng quan` | Overview |
| `Thay đổi` | Changes |
| `Kết quả & kiểm chứng` | Results and verification |
| `Tiến độ` | Progress |
| `Cần bạn` | Your action is needed; open the item for the specific decision. |
| `Đang chờ` | Waiting; read the reason to find out who or what it is waiting for. |
| `Bị chặn` | Blocked |
| `Đã nghiệm thu` | Accepted by the owner |

For this one-file task, expect one task and one check, not a populated repair history or subagent graph. If the browser does not open, use the loopback URL printed by the command. The viewer is optional; `plan report` remains available in the terminal. Closing the tab does not terminate the viewer. When finished, stop the viewer for this demo state:

```powershell
& $OneCrew --project $Project --state-root $State track stop
```

This stops the viewer, not the task or its worker. If it refuses to identify the server, inspect `track status`; do not stop unrelated Python processes.

**If `track open` times out:** inspect its error and cleanup result before retrying. During this documentation check, detached startup timed out in the review environment, while foreground serving worked. This is not a demonstrated failure on every machine. If the error confirms no server was left running, use the foreground alternative:

```powershell
& $OneCrew --project $Project --state-root $State track serve
```

Open the printed loopback URL in your browser. Keep that terminal open while viewing; press **Ctrl+C** there to stop this server and continue with acceptance below. Use Ctrl+C for `track serve`, and `track stop` for a server started by `track open`. Neither stops the task's worker.

Read `docs/hello-onecrew.md` and confirm that all required milestones passed. Obtain the current artifact hash:

```powershell
& $OneCrew --project $Project --state-root $State verdict artifact --plan hello-onecrew
```

Only accept the hash matching the current passing evidence. In your terminal:

```powershell
$ArtifactSha = Read-Host 'Paste the artifact SHA that matches the passing check'
& $OneCrew --project $Project --state-root $State owner accept hello-onecrew --artifact-sha $ArtifactSha --reference 'Read the greeting file and checked M1 evidence'
& $OneCrew --project $Project --state-root $State plan show hello-onecrew
```

Expected: `plan show` reports `status: accepted`. If an owner command reports an ambiguous result, inspect the recorded plan before retrying; a nonzero exit does not necessarily mean no write occurred. Completing this demo validates this small path, not every workflow in the release.

For a second task in the same project, reuse the executable and state directory, choose a new plan name, and ask the assistant to prepare a new contract. You do not need a new venv or another `init` for every task. Starting on an existing production project is a separate decision; do not copy this demo's plan or ledger into it.

## Working with three roles (optional)

Not needed for the demo above. This applies to a version that contains VAI3; earlier releases have no owner reminder.

For longer work you can split the sessions: the **owner** (requests, approves, answers, accepts), an **exchange session** (where the owner talks; it logs the words and passes work on) and a **coordinator session** (runs under a standing plan and by default only delegates). Add a verifier session when you want an independent check. Copy the matching template into the folder's `CLAUDE.md`: [exchange](vai3/trao-doi.en.md), [coordinator](vai3/dieu-phoi.en.md), [verifier](vai3/kiem.en.md). The roles are documentation and templates: OneCrew does not assign roles in code, does not forward messages between sessions, and does not change who decides.

When the session's plan is standing (`"standing": true` in the contract) and the owner types straight into it, the `hook prompt` entry that `onecrew init` writes reminds Claude to log the words and tell the exchange session, and adds one `reminded` line (rule `owner_prompt`, without the typed text). It never blocks. Messages from other sessions and app events (text starting with the `cross-session-message`, `system-reminder`, `task-notification`, `side-sessions-event` or `ci-monitor-event` wrapper, or with an app notice headed `[Cross-session `, such as `[Cross-session delivery notice]` or `[Cross-session idle notice]`) are not reminded; this relies on how the app wraps them today. Edit the reminder in `<state>/plans/mau-loi-chu.md`; an empty file turns it off; without the file the built-in text is used (`ONECREW_LANG=vi` for Vietnamese).

Details:

- **The recorded line.** One JSON line in `<project>/.onecrew/violations.jsonl` with `event` `reminded`, `rule` `owner_prompt`, `tool` `UserPromptSubmit`, the time, plan, revision, mode and session id. The typed text is not stored; match the time against the request log. The line shows that the reminder was given, not that Claude followed it.
- **Changing the text.** The owner edits the file; the whole file (up to 4000 characters, lines starting with `#` included) is given to Claude from the next turn on. Delete the file to return to the built-in text.
- **Self-work switch.** The coordinator only delegates by default. To let it change code itself, add the line `Coordinator self-work: on` to that session's `CLAUDE.md`; remove the line to turn it off. It is a written rule only: no hook checks it, and the contract's scope and the owner's authority stay as they are.
- **Limits.** Reminders only, never a block; Claude can ignore them. Nothing proves who typed the text. Words the app places after one of its wrappers in the same turn are not reminded.
- **Trying it.** With an approved standing plan, type one sentence into the session and check that one `owner_prompt` line appears; then have another session send it a message and check that no line is added.

## Troubleshooting

| Symptom | Next step |
|---|---|
| Python version rejected | Use Python 3.10+ and create a new venv with that interpreter. |
| No Git repository or no commit | Check the selected directory and initial commit. Do not initialize a parent folder to wrap several existing repos. |
| `doctor` reports a stale hook | Check the executable path and installed version. A moved or deleted venv breaks its hook command. |
| Owner command refused in an AI session | Run it in your own terminal. Do not remove AI-session markers to bypass the check. |
| Hook does not block an operation | Check the enforced plan and session root; test a supported operation in the disposable project. Missing coverage is not permission. |
| Dashboard is empty | Confirm project/state binding and that a plan exists. Untracked chats do not appear automatically. |
| A plan is waiting | Read the reason: approval, a required answer, a check, and a dependency need different actions. |

For diagnostics, start with `& $OneCrew support --help`. Inspect bundles before sharing them. See the [known issues](obs2/su-dung/LOI-DA-BIET.vi.md) for further caveats.

## Upgrading an existing project

An upgrade is separate from this fresh-install walkthrough. Inventory every project and worktree sharing the runtime or ledger; preserve open plans and unresolved executions.

1. Record the current runtime, hook commands, state path, and active work.
2. Back up settings and state consistently. Copying only an open SQLite database file can omit WAL data; use the release's backup procedure.
3. Install the candidate into a new venv and check its release-specific compatibility instructions.
4. Test the supported migration path before switching consumers. A copied ledger can still contain original project paths; changing `--project` alone does not establish isolation.
5. Switch only when migration preconditions are satisfied, then verify hooks, task continuation, and recovery.

Do not close plans just to pass an upgrade check, or assume an old runtime can safely read state written by a newer one. Keep the old environment and backup until the transition is verified. The [existing-project guide](obs2/su-dung/REPO-DANG-DUNG-ONECREW.vi.md) is a version-specific Vietnamese reference; some commands target dev10 and are not a dev31 migration recipe.

## Removing a demo

Stop its workers and viewer first. Remove only OneCrew entries from the demo project's Claude settings; preserve unrelated hooks and permissions. Do not blindly restore a `.bak` over settings changed since that backup.

Keep the ledger if you want the history. Remove the demo venv only after no remaining hook references it. Project-registry cleanup is separate: do not delete the shared registry file, and do not assume a `hook unregister` command exists in this release.

Return to the [README](../README.md) for feature and release status.
