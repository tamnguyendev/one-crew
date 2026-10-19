<#
.SYNOPSIS
  Owner verb: record your own verdict on an owner-manual milestone (verdict record --by owner).
.DESCRIPTION
  Type this in YOUR OWN terminal, not in an AI session: the CLI refuses it when CLAUDE_CODE_CHILD_SESSION is set.
  Only calls onecrew_cli.py; --by is always owner. -ReceiptFile is stored as the receipt blob (write in it what you
  looked at and what you decided). Only owner-manual milestones take a receipt file; command and reviewer milestones
  are verified by `verdict run`. Milestones go in order. The CLI has no --reference for a verdict: put it in the receipt.
  Prints the status line, exits non-zero on a missing plan or a refusal.
.EXAMPLE
  .\scripts\owner\record.ps1 -Plan v21-handover -Milestone M3 -Result pass -ArtifactSha <40-hex commit> -ReceiptFile .\m3-receipt.txt
#>
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$Milestone,
    [Parameter(Mandatory)][ValidateSet('pass', 'fail', 'inconclusive')][string]$Result,
    [Parameter(Mandatory)][string]$ArtifactSha,
    [Parameter(Mandatory)][string]$ReceiptFile,
    [string]$Project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$StateRoot = 'D:\OneCrewRuns\state-v2-real',
    [string]$Python = 'D:\TamNT\Workspace\9.VMAgent\onecrew\.venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$cli = Join-Path $repo 'onecrew_cli.py'
foreach ($path in @($Python, $cli, $StateRoot, $ReceiptFile)) {
    if (-not (Test-Path -LiteralPath $path)) { [Console]::Error.WriteLine("Khong tim thay: $path"); exit 1 }
}
$receipt = (Resolve-Path -LiteralPath $ReceiptFile).Path
Set-Location -LiteralPath $repo

$null = & $Python -X utf8 $cli --project $Project --state-root $StateRoot plan show $Plan
if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine("Plan '$Plan' khong ton tai trong $StateRoot (hoac CLI tu choi doc no)."); exit 1 }

$out = & $Python -X utf8 $cli --project $Project --state-root $StateRoot verdict record --plan $Plan --milestone $Milestone --result $Result --by owner --artifact-sha $ArtifactSha --receipt-file $receipt
$code = $LASTEXITCODE
$lines = $out | Select-String '"status"|"result"|"state"|"error"|refus|Cannot|cannot'
if ($code -ne 0) { $lines; [Console]::Error.WriteLine("CLI tu choi (exit $code): verdict record $Plan $Milestone"); exit $code }
$lines
