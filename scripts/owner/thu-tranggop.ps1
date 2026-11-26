<#
.SYNOPSIS
  TRANGGOP M2: mo trang gop (ba so tren mot trang) bang runtime thu, cong rieng 9699.
.DESCRIPTION
  Mac dinh = CHAY THU: in se ghi gi va mo gi, khong ghi, khong mo.
  -ApDung (chi trong terminal rieng cua chu; trong phien AI bi tu choi):
    1. ghi tracking.json cua so that: giu "port" dang co, them "so" (so phat trien, so rieng dieu phoi), "de_xuat_tu" (tep lo trinh)
       va "phien_claude_thu_muc" (cac thu muc nhat ky dang co trong danh sach); ban cu duoc chep thanh tracking.json.truoc-tranggop;
    2. mo trang bang runtime thu o http://127.0.0.1:9699/ (server dang chay o 9692 khong bi dung; dau cua server thu nam ngoai so).
  -QuayVe -ApDung: dung server thu va tra tracking.json ve nhu cu (xoa neu truoc do khong co). -QuayVe mot minh la chay thu cua no.
  Exit 0 = dat; 1 = mot buoc khong dat; 2 = -ApDung trong phien AI.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\owner\thu-tranggop.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\owner\thu-tranggop.ps1 -ApDung
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\owner\thu-tranggop.ps1 -QuayVe -ApDung
#>
param(
    [switch]$ApDung,
    [switch]$QuayVe,
    [string]$OneCrew = 'D:\OneCrewRuns\tranggop\runtime-thu\Scripts\onecrew.exe',
    [string]$Project = 'D:\TamNT\Workspace\11.OneCrew\onecrew',
    [string]$RealState = 'D:\TamNT\Workspace\11.OneCrew\state-v2-real',
    [string]$DevState = 'D:\OneCrewRuns\onecrew-development\state',
    [string]$CoordState = 'D:\OneCrewRuns\dieu-phoi-state',
    [string]$Proposals = 'D:\TamNT\Workspace\11.OneCrew\outputs\onecrew-as-qc\ROADMAP.vi.md',
    [string[]]$TranscriptNames = @('D--OneCrewRuns-dieu-phoi', 'D--OneCrewRuns-gsdp-a-thu-gan-du-an', 'D--TamNT-Workspace-11-OneCrew-onecrew', 'D--TamNT-Workspace-9-VMAgent-onecrew'),
    [string]$MarkerDir = 'D:\OneCrewRuns\tranggop\marker',
    [int]$Port = 9699
)
$ErrorActionPreference = 'Continue'
if ($ApDung -and ($env:CLAUDE_CODE_CHILD_SESSION -or $env:CLAUDECODE)) { Write-Host 'KHONG DAT: -ApDung dang o trong phien AI; mo terminal rieng cua ban roi chay lai.' -ForegroundColor Red; exit 2 }
$noBom = New-Object System.Text.UTF8Encoding $false
$file = Join-Path $RealState 'tracking.json'
$backup = Join-Path $RealState 'tracking.json.truoc-tranggop'
$mode = if ($ApDung) { 'CHAY THAT' } else { 'CHAY THU (khong ghi gi, khong mo gi)' }
Write-Host ('TRANGGOP M2 - ' + $mode + $(if ($QuayVe) { ' - QUAY VE' } else { '' }))

$missing = @($OneCrew, $Project, $RealState) | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) { foreach ($m in $missing) { Write-Host ('KHONG DAT: khong tim thay ' + $m) -ForegroundColor Red }; exit 1 }

$savedMarker = $env:ONECREW_TRACK_MARKER_DIR
$savedIo = $env:PYTHONIOENCODING
$savedEncoding = [Console]::OutputEncoding
try {
    $env:ONECREW_TRACK_MARKER_DIR = $MarkerDir
    $env:PYTHONIOENCODING = 'utf-8'
    try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

    if ($QuayVe) {
        if (-not $ApDung) {
            Write-Host ('[thu] se chay: track stop (server thu cua so that)')
            if (Test-Path -LiteralPath $backup) { Write-Host ('[thu] se tra ' + $file + ' ve ban trong ' + $backup) }
            elseif (Test-Path -LiteralPath ($backup + '.khong-co')) { Write-Host ('[thu] se xoa ' + $file + ' (truoc do khong co)') }
            else { Write-Host '[thu] khong co ban cu nao do script nay ghi: khong doi tracking.json.' }
            exit 0
        }
        & $OneCrew --project $Project --state-root $RealState track stop | Write-Host
        if (Test-Path -LiteralPath $backup) {
            Copy-Item -LiteralPath $backup -Destination $file -Force
            Remove-Item -LiteralPath $backup -Force
            Write-Host ('Da tra ' + $file + ' ve ban cu.')
        } elseif (Test-Path -LiteralPath ($backup + '.khong-co')) {
            Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath ($backup + '.khong-co') -Force
            Write-Host ('Da xoa ' + $file + ' (truoc do khong co).')
        } else { Write-Host 'Khong co ban cu nao do script nay ghi: khong doi tracking.json.' }
        Write-Host 'XONG quay ve.' -ForegroundColor Green
        exit 0
    }

    $value = New-Object psobject
    $had = Test-Path -LiteralPath $file
    if ($had) {
        try { $value = [IO.File]::ReadAllText($file, [Text.Encoding]::UTF8) | ConvertFrom-Json }
        catch { Write-Host ('KHONG DAT: ' + $file + ' khong doc duoc; khong ghi gi.') -ForegroundColor Red; exit 1 }
    }
    if (-not $value.port) { $value | Add-Member -NotePropertyName port -NotePropertyValue 9692 -Force }     # ban dang cai chi doc duoc tep co "port"
    $others = @($DevState, $CoordState) | Where-Object { Test-Path -LiteralPath $_ }
    $projects = Join-Path $env:USERPROFILE '.claude\projects'
    $folders = @($TranscriptNames | ForEach-Object { Join-Path $projects $_ } | Where-Object { Test-Path -LiteralPath $_ })
    $value | Add-Member -NotePropertyName so -NotePropertyValue @($others) -Force
    if (Test-Path -LiteralPath $Proposals) { $value | Add-Member -NotePropertyName de_xuat_tu -NotePropertyValue $Proposals -Force }
    else { Write-Host ('Luu y: khong thay tep de xuat ' + $Proposals + ' (muc "De xuat cho ban" se trong).') -ForegroundColor Yellow }
    $value | Add-Member -NotePropertyName phien_claude_thu_muc -NotePropertyValue @($folders) -Force
    $text = $value | ConvertTo-Json -Depth 5

    Write-Host ('Se ghi ' + $file + ':')
    Write-Host $text
    Write-Host ('Nhat ky phien se duoc trang doc (chi cac thu muc nay): ' + $folders.Count)
    if (-not $ApDung) {
        Write-Host ('[thu] se chay: ' + $OneCrew + ' --project ' + $Project + ' --state-root ' + $RealState + ' track open --port ' + $Port)
        Write-Host 'Chay thu xong: khong ghi gi, khong mo gi. Chay lai voi -ApDung trong terminal cua ban.'
        exit 0
    }

    if (-not (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath ($backup + '.khong-co'))) {
        if ($had) { Copy-Item -LiteralPath $file -Destination $backup }
        else { [IO.File]::WriteAllText($backup + '.khong-co', '', $noBom) }
    }
    [IO.File]::WriteAllText($file, $text, $noBom)
    Write-Host ('Da ghi ' + $file)
    New-Item -ItemType Directory -Force $MarkerDir | Out-Null
    & $OneCrew --project $Project --state-root $RealState track open --port $Port | Write-Host
    if ($LASTEXITCODE -ne 0) { Write-Host 'KHONG DAT: khong mo duoc trang (xem dong tren).' -ForegroundColor Red; exit 1 }
    Write-Host ''
    Write-Host ('DAT neu trinh duyet mo http://127.0.0.1:' + $Port + '/ va ban thay: nut loc ba so; tab Cong viec co viec cua ca ba so (co nhan so, viec cu ghi "kieu cu");') -ForegroundColor Green
    Write-Host 'tab Phien Claude co dai Viec (bam mo dung viec), the phien, lan va so, luong giao viec, buoc agent tu bao, De xuat cho ban. So voi mockup MOCKTHAT.'
    Write-Host 'Xem xong: chay lai script nay voi -QuayVe -ApDung.'
    exit 0
} finally {
    $env:ONECREW_TRACK_MARKER_DIR = $savedMarker
    $env:PYTHONIOENCODING = $savedIo
    [Console]::OutputEncoding = $savedEncoding
}
