<#
.SYNOPSIS
  Owner verb: switch the hook of a plan to enforce (hook mode enforce --by owner) so it blocks instead of only logging.
  Typed AFTER approve.ps1 (plan approve, then hook mode enforce --plan <name>).
.DESCRIPTION
  Type this in the owner's OWN terminal, not in an AI session: the CLI refuses it when CLAUDE_CODE_CHILD_SESSION is set.
  Only calls onecrew_cli.py; --by is always owner. Prints the mode line, exits non-zero on a missing plan or a refusal.
  -Mode log goes back to logging only. The separate state-root gate (plan enforce on|off) is not done here.
  Defaults for -Project (the repo holding this script), -StateRoot and -Python are for THIS machine: override them
  with parameters on another machine or another account. The working directory is restored when the script ends.
.EXAMPLE
  .\scripts\owner\enforce.ps1 -Plan v21-handover -Reference "chu so huu 20/10: chan that"
#>
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$Reference,
    [string]$Project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,                                   # default: the repo of this script
    [string]$StateRoot = 'D:\OneCrewRuns\state-v2-real',                                                        # default of this machine: override elsewhere
    [string]$Python = 'D:\TamNT\Workspace\9.VMAgent\onecrew\.venv\Scripts\python.exe',                          # default of this machine: override elsewhere
    [ValidateSet('enforce', 'log')][string]$Mode = 'enforce'
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$cli = Join-Path $repo 'onecrew_cli.py'
$exitCode = 0
Push-Location -LiteralPath $repo
try {
    foreach ($path in @($Python, $cli, $StateRoot)) {
        if (-not (Test-Path -LiteralPath $path)) { [Console]::Error.WriteLine("Khong tim thay: $path"); exit 1 }
    }
    $null = & $Python -X utf8 $cli --project $Project --state-root $StateRoot plan show $Plan
    if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine("Plan '$Plan' khong ton tai trong $StateRoot (hoac CLI tu choi doc no)."); exit 1 }

    $out = & $Python -X utf8 $cli --project $Project --state-root $StateRoot hook mode $Mode --by owner --reference $Reference --plan $Plan
    $code = $LASTEXITCODE
    $lines = $out | Select-String '"mode"|"exported"|"error"|refus'
    $lines
    if ($code -ne 0) { [Console]::Error.WriteLine("CLI tu choi (exit $code): hook mode $Mode cho plan $Plan"); exit $code }
    if (-not $lines) { [Console]::Error.WriteLine("CLI exit 0 nhung khong co dong mode; kiem tra bang: hook install --print / plan show $Plan") }
}
finally { Pop-Location }
exit $exitCode
