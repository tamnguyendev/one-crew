<#
.SYNOPSIS
  Owner verb: approve a OneCrew plan (onecrew owner approve).
.DESCRIPTION
  Run this in the owner's OWN terminal, not in an AI session: the script and the CLI both refuse inside one.
  Calls the installed OneCrew (default: the 2.5.0.dev30 runtime of this machine), then reads the ledger again and reports
  what it holds: the --human text of the CLI may say "not confirmed" after a successful write.
  -Project: the repository of the plan (default: the current folder). -StateRoot: the ledger (default: the real one of this machine).
  -MachineDir: for the OneCrew development ledger, the folder holding local\ and roaming\ (sets LOCALAPPDATA/APPDATA for the call only).
  Exit 0 = the ledger shows the plan approved; 1 = refused or not recorded; 2 = run inside an AI session.
.EXAMPLE
  .\scripts\owner\approve.ps1 -Plan hello-onecrew -Revision 1 -Reference "owner said yes in chat 18/11"
.EXAMPLE
  .\scripts\owner\approve.ps1 -Plan DOCS30 -Revision 1 -Choose rewrite -Reference "..." -StateRoot D:\OneCrewRuns\onecrew-development\state -MachineDir D:\OneCrewRuns\onecrew-development\machine
#>
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$Reference,
    [int]$Revision,
    [string]$Choose,
    [string[]]$Tick = @(),
    [string]$Project = (Get-Location).Path,
    [string]$StateRoot = 'D:\TamNT\Workspace\11.OneCrew\state-v2-real',
    [string]$OneCrew = 'D:\OneCrewRuns\runtime-dev30\Scripts\onecrew.exe',
    [string]$MachineDir = ''
)
$ErrorActionPreference = 'Stop'
if ($env:CLAUDE_CODE_CHILD_SESSION -or $env:CLAUDECODE) { Write-Host 'KHONG DAT: dang o trong phien AI; mo terminal rieng cua ban roi chay lai.' -ForegroundColor Red; exit 2 }
foreach ($path in @($OneCrew, $Project, $StateRoot)) { if (-not (Test-Path -LiteralPath $path)) { Write-Host ('KHONG DAT: khong tim thay ' + $path) -ForegroundColor Red; exit 1 } }
$saved = @($env:LOCALAPPDATA, $env:APPDATA)
$savedEncoding = [Console]::OutputEncoding      # ENC30: OneCrew writes UTF-8; read it as UTF-8 while it runs, give the console its own code page back after
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
if ($MachineDir) { $env:LOCALAPPDATA = Join-Path $MachineDir 'local'; $env:APPDATA = Join-Path $MachineDir 'roaming' }
try {
    $base = @('--project', $Project, '--state-root', $StateRoot)
    function Show { try { (& $OneCrew @base plan show $Plan 2>$null) -join "`n" | ConvertFrom-Json } catch { $null } }
    $before = Show
    if (-not $before) { Write-Host ('KHONG DAT: khong doc duoc plan ' + $Plan + ' trong ' + $StateRoot) -ForegroundColor Red; exit 1 }
    $cliArgs = @('owner', 'approve', $Plan, '--reference', $Reference, '--human')
    if ($PSBoundParameters.ContainsKey('Revision')) { $cliArgs += @('--revision', "$Revision") }
    if ($Choose) { $cliArgs += @('--choose', $Choose) }
    foreach ($item in $Tick) { $cliArgs += @('--tick', $item) }
    & $OneCrew @base @cliArgs | Out-Host
    $after = Show
    $okRevision = -not $PSBoundParameters.ContainsKey('Revision') -or $after.approved_revision -eq $Revision
    if ($after -and $after.status -eq 'approved' -and $okRevision) {
        Write-Host ('DAT: so ghi ' + $Plan + ' ban ' + $after.approved_revision + ' da duyet.') -ForegroundColor Green; exit 0
    }
    Write-Host ('KHONG DAT: so van ghi ' + $Plan + ' la ' + $after.status + ' (xem dong loi o tren).') -ForegroundColor Red; exit 1
}
finally { $env:LOCALAPPDATA, $env:APPDATA = $saved; try { [Console]::OutputEncoding = $savedEncoding } catch { } }
