<#
.SYNOPSIS
  Owner verb: accept a finished plan on the artifact that was checked (onecrew owner accept).
.DESCRIPTION
  Run this in the owner's OWN terminal, not in an AI session: the script and the CLI both refuse inside one.
  -ArtifactSha: the artifact the milestones passed on (from the report, or `verdict artifact --plan <plan>`); the CLI refuses
  when the project changed since. Calls the installed OneCrew (default: the 2.5.0.dev30 runtime of this machine), then reads
  the ledger again and reports what it holds: the --human text of the CLI may say "not confirmed" after a successful write.
  -Project: the repository of the plan (default: the current folder). -StateRoot: the ledger (default: the real one of this machine).
  -MachineDir: for the OneCrew development ledger, the folder holding local\ and roaming\ (sets LOCALAPPDATA/APPDATA for the call only).
  Exit 0 = the ledger shows the plan accepted; 1 = refused or not recorded; 2 = run inside an AI session.
.EXAMPLE
  .\scripts\owner\accept.ps1 -Plan hello-onecrew -ArtifactSha <40-hex> -Reference "read the greeting file 18/11"
#>
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$ArtifactSha,
    [Parameter(Mandatory)][string]$Reference,
    [int]$Revision,
    [string]$Project = (Get-Location).Path,
    [string]$StateRoot = 'D:\TamNT\Workspace\11.OneCrew\state-v2-real',
    [string]$OneCrew = 'D:\OneCrewRuns\runtime-dev30\Scripts\onecrew.exe',
    [string]$MachineDir = ''
)
$ErrorActionPreference = 'Stop'
if ($env:CLAUDE_CODE_CHILD_SESSION -or $env:CLAUDECODE) { Write-Host 'KHONG DAT: dang o trong phien AI; mo terminal rieng cua ban roi chay lai.' -ForegroundColor Red; exit 2 }
foreach ($path in @($OneCrew, $Project, $StateRoot)) { if (-not (Test-Path -LiteralPath $path)) { Write-Host ('KHONG DAT: khong tim thay ' + $path) -ForegroundColor Red; exit 1 } }
$saved = @($env:LOCALAPPDATA, $env:APPDATA)
if ($MachineDir) { $env:LOCALAPPDATA = Join-Path $MachineDir 'local'; $env:APPDATA = Join-Path $MachineDir 'roaming' }
try {
    $base = @('--project', $Project, '--state-root', $StateRoot)
    function Show { try { (& $OneCrew @base plan show $Plan 2>$null) -join "`n" | ConvertFrom-Json } catch { $null } }
    $before = Show
    if (-not $before) { Write-Host ('KHONG DAT: khong doc duoc plan ' + $Plan + ' trong ' + $StateRoot) -ForegroundColor Red; exit 1 }
    if ($before.status -eq 'accepted') { Write-Host ('DAT: ' + $Plan + ' da nghiem thu tu truoc; khong ghi lai.') -ForegroundColor Green; exit 0 }
    $cliArgs = @('owner', 'accept', $Plan, '--artifact-sha', $ArtifactSha, '--reference', $Reference, '--human')
    if ($PSBoundParameters.ContainsKey('Revision')) { $cliArgs += @('--revision', "$Revision") }
    & $OneCrew @base @cliArgs | Out-Host
    $after = Show
    if ($after -and $after.status -eq 'accepted') { Write-Host ('DAT: so ghi ' + $Plan + ' da nghiem thu.') -ForegroundColor Green; exit 0 }
    Write-Host ('KHONG DAT: so van ghi ' + $Plan + ' la ' + $after.status + ' (xem dong loi o tren).') -ForegroundColor Red; exit 1
}
finally { $env:LOCALAPPDATA, $env:APPDATA = $saved }
