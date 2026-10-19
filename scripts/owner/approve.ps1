<#
.SYNOPSIS
  Owner verb: approve a OneCrew v2 plan (plan approve --by owner).
.DESCRIPTION
  Type this in YOUR OWN terminal, not in an AI session: the CLI refuses it when CLAUDE_CODE_CHILD_SESSION is set.
  Only calls onecrew_cli.py; --by is always owner. Prints the status line, exits non-zero on a missing plan or a refusal.
  -Reference: where you said yes (recorded, max 500 chars). Keep it ASCII if your console garbles diacritics.
.EXAMPLE
  .\scripts\owner\approve.ps1 -Plan v21-handover -Reference "chu so huu duyet trong chat 20/10"
#>
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$Reference,
    [string]$Project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$StateRoot = 'D:\OneCrewRuns\state-v2-real',
    [string]$Python = 'D:\TamNT\Workspace\9.VMAgent\onecrew\.venv\Scripts\python.exe',
    [int]$Revision,
    [string[]]$Tick = @(),
    [string]$Choose
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

$cliArgs = @('plan', 'approve', $Plan, '--by', 'owner', '--reference', $Reference)
if ($PSBoundParameters.ContainsKey('Revision')) { $cliArgs += @('--revision', "$Revision") }
foreach ($item in $Tick) { $cliArgs += @('--tick', $item) }
if ($Choose) { $cliArgs += @('--choose', $Choose) }

$out = & $Python -X utf8 $cli --project $Project --state-root $StateRoot @cliArgs
$code = $LASTEXITCODE
$lines = $out | Select-String '"status"|"error"|refus|Cannot|cannot'
if ($code -ne 0) { $lines; [Console]::Error.WriteLine("CLI tu choi (exit $code): plan approve $Plan"); exit $code }
$lines
