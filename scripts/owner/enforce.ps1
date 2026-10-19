<#
.SYNOPSIS
  Owner verb: switch the hook of a plan to enforce (hook mode enforce --by owner) so it blocks instead of only logging.
.DESCRIPTION
  Type this in YOUR OWN terminal, not in an AI session: the CLI refuses it when CLAUDE_CODE_CHILD_SESSION is set.
  Only calls onecrew_cli.py; --by is always owner. Prints the mode line, exits non-zero on a missing plan or a refusal.
  -Mode log goes back to logging only. The separate state-root gate (plan enforce on|off) is not done here.
.EXAMPLE
  .\scripts\owner\enforce.ps1 -Plan v21-handover -Reference "chu so huu 20/10: chan that"
#>
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$Reference,
    [string]$Project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$StateRoot = 'D:\OneCrewRuns\state-v2-real',
    [string]$Python = 'D:\TamNT\Workspace\9.VMAgent\onecrew\.venv\Scripts\python.exe',
    [ValidateSet('enforce', 'log')][string]$Mode = 'enforce'
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$cli = Join-Path $repo 'onecrew_cli.py'
foreach ($path in @($Python, $cli, $StateRoot)) {
    if (-not (Test-Path -LiteralPath $path)) { [Console]::Error.WriteLine("Khong tim thay: $path"); exit 1 }
}
Set-Location -LiteralPath $repo

$null = & $Python -X utf8 $cli --project $Project --state-root $StateRoot plan show $Plan
if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine("Plan '$Plan' khong ton tai trong $StateRoot (hoac CLI tu choi doc no)."); exit 1 }

$out = & $Python -X utf8 $cli --project $Project --state-root $StateRoot hook mode $Mode --by owner --reference $Reference --plan $Plan
$code = $LASTEXITCODE
$lines = $out | Select-String '"mode"|"exported"|"error"|refus'
if ($code -ne 0) { $lines; [Console]::Error.WriteLine("CLI tu choi (exit $code): hook mode $Mode cho plan $Plan"); exit $code }
$lines
