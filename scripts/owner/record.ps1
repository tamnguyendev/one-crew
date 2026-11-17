<#
.SYNOPSIS
  Owner verb: record the owner's own verdict on an owner-manual milestone (onecrew owner record).
.DESCRIPTION
  Run this in the owner's OWN terminal, not in an AI session: the script and the CLI both refuse inside one.
  -ReceiptFile is stored as the receipt (write in it what the owner looked at and decided). Only owner-manual milestones take
  a receipt from the owner; command and reviewer milestones are verified by `verdict run`. Milestones go in order.
  Calls the installed OneCrew (default: the 2.5.0.dev30 runtime of this machine), then reads the ledger again: the milestone
  must show this result, by the owner, with this very receipt (its SHA256).
  -Project: the repository of the plan (default: the current folder). -StateRoot: the ledger (default: the real one of this machine).
  -MachineDir: for the OneCrew development ledger, the folder holding local\ and roaming\ (sets LOCALAPPDATA/APPDATA for the call only).
  Exit 0 = the ledger shows the verdict; 1 = refused or not recorded; 2 = run inside an AI session.
.EXAMPLE
  .\scripts\owner\record.ps1 -Plan hello-onecrew -Milestone M2 -Result pass -ArtifactSha <40-hex> -ReceiptFile .\m2.txt -Reference "read it 18/11"
#>
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$Milestone,
    [Parameter(Mandatory)][ValidateSet('pass', 'fail', 'inconclusive')][string]$Result,
    [Parameter(Mandatory)][string]$ArtifactSha,
    [Parameter(Mandatory)][string]$ReceiptFile,
    [Parameter(Mandatory)][string]$Reference,
    [string]$Project = (Get-Location).Path,
    [string]$StateRoot = 'D:\TamNT\Workspace\11.OneCrew\state-v2-real',
    [string]$OneCrew = 'D:\OneCrewRuns\runtime-dev30\Scripts\onecrew.exe',
    [string]$MachineDir = ''
)
$ErrorActionPreference = 'Stop'
if ($env:CLAUDE_CODE_CHILD_SESSION -or $env:CLAUDECODE) { Write-Host 'KHONG DAT: dang o trong phien AI; mo terminal rieng cua ban roi chay lai.' -ForegroundColor Red; exit 2 }
foreach ($path in @($OneCrew, $Project, $StateRoot, $ReceiptFile)) { if (-not (Test-Path -LiteralPath $path)) { Write-Host ('KHONG DAT: khong tim thay ' + $path) -ForegroundColor Red; exit 1 } }
$receipt = (Resolve-Path -LiteralPath $ReceiptFile).Path
$receiptSha = (Get-FileHash -LiteralPath $receipt -Algorithm SHA256).Hash.ToLower()
$saved = @($env:LOCALAPPDATA, $env:APPDATA)
$savedEncoding = [Console]::OutputEncoding      # ENC30: OneCrew writes UTF-8; read it as UTF-8 while it runs, give the console its own code page back after
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
if ($MachineDir) { $env:LOCALAPPDATA = Join-Path $MachineDir 'local'; $env:APPDATA = Join-Path $MachineDir 'roaming' }
try {
    $base = @('--project', $Project, '--state-root', $StateRoot)
    function Show { try { (& $OneCrew @base plan show $Plan 2>$null) -join "`n" | ConvertFrom-Json } catch { $null } }
    if (-not (Show)) { Write-Host ('KHONG DAT: khong doc duoc plan ' + $Plan + ' trong ' + $StateRoot) -ForegroundColor Red; exit 1 }
    & $OneCrew @base owner record --plan $Plan --milestone $Milestone --result $Result --artifact-sha $ArtifactSha --receipt-file $receipt --reference $Reference --human | Out-Host
    $m = (Show).milestones | Where-Object { $_.id -eq $Milestone }
    if ($m -and $m.last_verdict.by -eq 'owner' -and $m.last_verdict.result -eq $Result -and $m.last_verdict.receipt -eq $receiptSha) {
        Write-Host ('DAT: so ghi ' + $Plan + ' ' + $Milestone + ' = ' + $Result + ' do chu ghi (receipt ' + $receiptSha + ').') -ForegroundColor Green; exit 0
    }
    Write-Host ('KHONG DAT: so khong co verdict ' + $Milestone + ' = ' + $Result + ' voi receipt nay (xem dong loi o tren).') -ForegroundColor Red; exit 1
}
finally { $env:LOCALAPPDATA, $env:APPDATA = $saved; try { [Console]::OutputEncoding = $savedEncoding } catch { } }
