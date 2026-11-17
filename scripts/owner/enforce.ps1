<#
.SYNOPSIS
  Owner verb: switch the hook mode of a plan, enforce (block) or log (onecrew owner enforce).
.DESCRIPTION
  Run this in the owner's OWN terminal, not in an AI session: the script and the CLI both refuse inside one.
  Calls the installed OneCrew (default: the 2.5.0.dev30 runtime of this machine), then reads the exported active plan
  (<project>\.onecrew\active-plan.json, the file the hooks read) and reports what it holds.
  -Project: the repository of the plan (default: the current folder). -StateRoot: the ledger (default: the real one of this machine).
  -MachineDir: for the OneCrew development ledger, the folder holding local\ and roaming\ (sets LOCALAPPDATA/APPDATA for the call only).
  Exit 0 = the hooks now read the plan in that mode; 1 = refused or not exported; 2 = run inside an AI session.
.EXAMPLE
  .\scripts\owner\enforce.ps1 -Plan hello-onecrew
.EXAMPLE
  .\scripts\owner\enforce.ps1 -Plan hello-onecrew -Mode log -Reference "owner: watch only while testing"
#>
param(
    [Parameter(Mandatory)][string]$Plan,
    [ValidateSet('enforce', 'log')][string]$Mode = 'enforce',
    [string]$Reference = '',
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
    $cliArgs = @('--project', $Project, '--state-root', $StateRoot, 'owner', 'enforce', $Plan, '--mode', $Mode, '--human')
    if ($Reference) { $cliArgs += @('--reference', $Reference) }
    & $OneCrew @cliArgs | Out-Host
    $file = Join-Path $Project '.onecrew\active-plan.json'
    $active = $null
    if (Test-Path -LiteralPath $file) { try { $active = Get-Content -Raw -Encoding UTF8 -LiteralPath $file | ConvertFrom-Json } catch { $active = $null } }
    if ($active -and $active.plan -eq $Plan -and $active.mode -eq $Mode) {
        Write-Host ('DAT: hook cua ' + $Project + ' doc ' + $Plan + ' ban ' + $active.revision + ', che do ' + $Mode + '.') -ForegroundColor Green; exit 0
    }
    $seen = if ($active) { $active.plan + ' / ' + $active.mode } else { 'khong co tep' }
    Write-Host ('KHONG DAT: tep plan cua hook la ' + $seen + ' (xem dong loi o tren).') -ForegroundColor Red; exit 1
}
finally { $env:LOCALAPPDATA, $env:APPDATA = $saved }
