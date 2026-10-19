<#
.SYNOPSIS
  Owner verb: accept the result of a OneCrew v2 plan (plan accept --by owner).
.DESCRIPTION
  Type this in the owner's OWN terminal, not in an AI session: the CLI refuses it when CLAUDE_CODE_CHILD_SESSION is set.
  Only calls onecrew_cli.py; --by is always owner. The CLI refuses while a milestone lacks a passing verdict, or when
  -ArtifactSha is not the artifact every milestone passed on. Prints the status line, exits non-zero on a refusal.
  Defaults for -Project (the repo holding this script), -StateRoot and -Python are for THIS machine: override them
  with parameters on another machine or another account. The working directory is restored when the script ends.
.EXAMPLE
  .\scripts\owner\accept.ps1 -Plan v21-handover -ArtifactSha <40-hex commit> -Reference "chu so huu nghiem thu 20/10"
#>
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$Reference,
    [Parameter(Mandatory)][string]$ArtifactSha,
    [string]$Project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,                                   # default: the repo of this script
    [string]$StateRoot = 'D:\OneCrewRuns\state-v2-real',                                                        # default of this machine: override elsewhere
    [string]$Python = 'D:\TamNT\Workspace\9.VMAgent\onecrew\.venv\Scripts\python.exe'                           # default of this machine: override elsewhere
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

    $out = & $Python -X utf8 $cli --project $Project --state-root $StateRoot plan accept $Plan --by owner --artifact-sha $ArtifactSha --reference $Reference
    $code = $LASTEXITCODE
    $lines = $out | Select-String '"status"|"error"|refus|Cannot|cannot'
    $lines
    if ($code -ne 0) { [Console]::Error.WriteLine("CLI tu choi (exit $code): plan accept $Plan"); exit $code }
    if (-not $lines) { [Console]::Error.WriteLine("CLI exit 0 nhung khong co dong status; doc ket qua bang: plan show $Plan") }
}
finally { Pop-Location }
exit $exitCode
