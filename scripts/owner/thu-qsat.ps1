# QSAT (M2): THU bo quan sat phien Claude moi o THU MUC THU rieng, voi goi dung tu commit da qua M1.
# Khong dung so that, ho so Claude that, runtime da cai hay hook toan may. Moi lenh onecrew o day dung thu muc may thu rieng
# (LOCALAPPDATA/APPDATA trong thu muc thu) va so thu rieng; bo quan sat duoc cai vao mot tep settings THU, khong phai settings cua ban.
#
# Mac dinh la CHAY THU: chi kiem va in ra se lam gi, khong ghi gi. Chay that: them -ApDung. Chay trong terminal cua ban, khong chay trong phien AI.
#   (khong cong tac)  dung hai repo thu A, B (moi repo mot so thu), init bang runtime thu, de xuat hai plan thu, BAN duyet bang loi cua ban
#                     (script hoi bang Read-Host), bat che do ghi (owner enforce --mode log), cai bo quan sat vao tep settings thu,
#                     roi day cac su kien mo phong cua mot phien o A: giao viec (mo ta co khoa gia), doc mot tep o B, ket thuc luot.
#                     In ra: dong tom tat da che; phien van gan plan cua A; so B khong co dong nao.
#   -QuayVe           go bo quan sat khoi tep settings thu va doi ten thu muc thu thanh <thu muc thu>-cu-<gio> (khong xoa).
# Tham so cho nguoi dieu phoi thu script: -RuntimeThu -ThuGoc.
param(
  [switch]$ApDung,
  [switch]$QuayVe,
  [string]$RuntimeThu = 'D:\OneCrewRuns\qsat\runtime-thu\Scripts\onecrew.exe',
  [string]$ThuGoc = 'D:\OneCrewRuns\qsat\thu'
)
$ErrorActionPreference = 'Continue'
$RepoA = Join-Path $ThuGoc 'a'
$RepoB = Join-Path $ThuGoc 'b'
$SoA = Join-Path $ThuGoc 'so-a'
$SoB = Join-Path $ThuGoc 'so-b'
$MayThu = Join-Path $ThuGoc 'may'
$HoSo = Join-Path $ThuGoc 'ho-so'
$SettingsThu = Join-Path $HoSo 'settings.json'
$Marker = Join-Path $ThuGoc 'THU-MUC-THU-QSAT.txt'
$Helper = Join-Path $PSScriptRoot 'thu-qsat.py'
$PlanA = 'QSAT-THU-A'
$PlanB = 'QSAT-THU-B'
function Stop-Here([string]$why) { Write-Host ('KHONG DAT: ' + $why) -ForegroundColor Red; exit 1 }

if (($ApDung) -and ($env:CLAUDE_CODE_CHILD_SESSION -or $env:CLAUDECODE)) {
  Write-Host 'KHONG DAT: dang o trong phien AI; mo terminal rieng cua ban roi chay lai.' -ForegroundColor Red; exit 2 }
$full = [IO.Path]::GetFullPath($ThuGoc).TrimEnd('\')
if (-not $full.StartsWith('D:\OneCrewRuns\qsat\', [StringComparison]::OrdinalIgnoreCase)) { Stop-Here ('thu muc thu phai nam duoi D:\OneCrewRuns\qsat\, dang la ' + $full) }

# Dau van tay cac tep cua ban ma script khong duoc dung toi: hai tep settings Claude (noi bo quan sat va hook that duoc cai), danh ba du an va
# tep khoa quan sat cua OneCrew tren may (%LOCALAPPDATA%\OneCrew\hook-projects.json, observation-keys.json). Script phai de nguyen chung.
# (So cua may trong %LOCALAPPDATA%\OneCrew khong nam trong dau van tay: phien Claude dang mo cua ban ghi vao do bat cu luc nao.)
function Get-RealPrint {
  $files = @((Join-Path $env:USERPROFILE '.claude\settings.json'), (Join-Path $env:USERPROFILE '.claude\settings.local.json'),
             (Join-Path $env:LOCALAPPDATA 'OneCrew\hook-projects.json'), (Join-Path $env:LOCALAPPDATA 'OneCrew\observation-keys.json'))
  $parts = foreach ($p in $files) {
    if (Test-Path -LiteralPath $p -PathType Leaf) { $p + '=' + (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash } else { $p + '=khong co' } }
  $parts -join ';'
}
$printBefore = Get-RealPrint

# Lenh onecrew (hay python cua runtime thu) voi thu muc may thu; moi bien moi truong tra lai ngay sau lenh. Text = dau ra, Err = dong loi.
function Invoke-Thu([string]$exe, [string[]]$rest, [string]$where) {
  $keep = @{ L = $env:LOCALAPPDATA; R = $env:APPDATA; U = $env:PYTHONUTF8; P = $env:CLAUDE_PROJECT_DIR }
  $errFile = [IO.Path]::GetTempFileName()
  $env:LOCALAPPDATA = Join-Path $MayThu 'local'; $env:APPDATA = Join-Path $MayThu 'roaming'; $env:PYTHONUTF8 = '1'; $env:CLAUDE_PROJECT_DIR = $null
  if ($where) { Push-Location -LiteralPath $where }
  try { $text = (& $exe @rest 2> $errFile) -join "`n"; $code = $LASTEXITCODE }
  finally {
    if ($where) { Pop-Location }
    $env:LOCALAPPDATA = $keep.L; $env:APPDATA = $keep.R; $env:PYTHONUTF8 = $keep.U; $env:CLAUDE_PROJECT_DIR = $keep.P }
  $errText = [IO.File]::ReadAllText($errFile)
  [IO.File]::Delete($errFile)
  return @{ Code = $code; Text = $text; Err = $errText }
}
function Show-Step($step) { if ($step.Text) { Write-Host $step.Text }; if ($step.Err) { Write-Host $step.Err } }

# ---- kiem truoc (moi che do) ---------------------------------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $RuntimeThu)) { Stop-Here ('chua co runtime thu ' + $RuntimeThu + ' (nguoi dieu phoi dung goi tu commit da qua M1).') }
$PyThu = Join-Path (Split-Path -Parent $RuntimeThu) 'python.exe'
if (-not (Test-Path -LiteralPath $PyThu)) { Stop-Here ('khong thay python cua runtime thu ' + $PyThu) }
if (-not (Test-Path -LiteralPath $Helper)) { Stop-Here ('thieu ' + $Helper) }
$versionThu = ((& $RuntimeThu --version 2>&1) -join ' ').Trim()
Write-Host ('Runtime thu: ' + $RuntimeThu + ' (' + $versionThu + ')')
Write-Host ('Thu muc thu: ' + $ThuGoc + ' (repo A ' + $RepoA + ', repo B ' + $RepoB + ', so thu ' + $SoA + ' va ' + $SoB + ', settings thu ' + $SettingsThu + ')')

# ---- -QuayVe ------------------------------------------------------------------------------------------------------------------
if ($QuayVe) {
  if (-not (Test-Path -LiteralPath $ThuGoc)) { Write-Host 'Khong co thu muc thu; khong co gi de don.' -ForegroundColor Green; exit 0 }
  if (-not (Test-Path -LiteralPath $Marker)) { Stop-Here ('thu muc ' + $ThuGoc + ' khong co dau ' + $Marker + '; script khong dung thu muc nay.') }
  $newName = (Split-Path -Leaf $ThuGoc) + '-cu-' + (Get-Date -Format 'yyyyMMddHHmmss')
  Write-Host ('Se lam: (1) hook user uninstall cho tep settings thu; (2) doi ten ' + $ThuGoc + ' thanh ' + $newName + ' (khong xoa).')
  if (-not $ApDung) { Write-Host 'CHAY THU: chua ghi gi. Chay lai voi -QuayVe -ApDung de don.' -ForegroundColor Green; exit 0 }
  if (Test-Path -LiteralPath $SettingsThu) {
    $step = Invoke-Thu $RuntimeThu @('hook', 'user', 'uninstall', '--settings-file', $SettingsThu) $null
    if ($step.Code -ne 0) { Show-Step $step; Stop-Here ('hook user uninstall loi ' + $step.Code) }
  }
  Rename-Item -LiteralPath $ThuGoc -NewName $newName
  if (Test-Path -LiteralPath $ThuGoc) { Stop-Here 'chua doi ten duoc thu muc thu (co tep dang mo?).' }
  if ((Get-RealPrint) -ne $printBefore) { Stop-Here 'tep settings Claude, danh ba du an hay tep khoa quan sat cua ban da doi trong luc chay; bao nguoi dieu phoi.' }
  Write-Host ('DAT: da go bo quan sat thu va doi ten thu muc thu thanh ' + $newName + '; settings Claude, danh ba du an va tep khoa quan sat cua ban khong doi.') -ForegroundColor Green
  exit 0
}

# ---- thu bo quan sat ------------------------------------------------------------------------------------------------------------
if (Test-Path -LiteralPath $ThuGoc) { Stop-Here ('da co ' + $ThuGoc + '; chay -QuayVe -ApDung truoc de don lan thu cu.') }
Write-Host 'Se lam: (1) tao repo thu A va B; (2) runtime thu: init --yes cho tung repo (moi repo mot so thu);'
Write-Host '        (3) plan propose QSAT-THU-A, QSAT-THU-B; (4) BAN duyet hai plan thu bang loi cua ban; (5) owner enforce --mode log cho ca hai;'
Write-Host '        (6) hook user install --observe vao tep settings THU; (7) day su kien mo phong cua mot phien o A; (8) in ket qua.'
if (-not $ApDung) {
  Write-Host 'CHAY THU: chua ghi gi. Chay lai voi -ApDung de thu.' -ForegroundColor Green
  exit 0
}

$Loi = (Read-Host 'Go loi duyet hai plan thu cua ban (it nhat 8 ky tu, chu cua chinh ban), roi Enter').Trim()
if ($Loi.Length -lt 8) { Stop-Here 'loi duyet qua ngan; chua ghi gi.' }
if ($Loi -match '^\.+$' -or $Loi -match '(?i)loi cua ban|<|>|vi du') { Stop-Here 'loi duyet con chu mau; go loi cua chinh ban.' }

New-Item -ItemType Directory -Force -Path $RepoA, $RepoB, $SoA, $SoB, $HoSo, (Join-Path $MayThu 'local'), (Join-Path $MayThu 'roaming') | Out-Null
[IO.File]::WriteAllText($Marker, "Thu muc thu QSAT (scripts/owner/thu-qsat.ps1). Don bang -QuayVe -ApDung.`r`n")
foreach ($repo in @(@($RepoA, 'A'), @($RepoB, 'B'))) {
  & git -C $repo[0] init -q
  if ($LASTEXITCODE -ne 0) { Stop-Here ('git init loi o ' + $repo[0]) }
  [IO.File]::WriteAllText((Join-Path $repo[0] 'README.md'), ('Repo thu QSAT ' + $repo[1] + ".`n"))
  & git -C $repo[0] add README.md
  & git -C $repo[0] -c user.name=owner -c user.email=owner@localhost commit -q -m ('repo thu QSAT ' + $repo[1])
  if ($LASTEXITCODE -ne 0) { Stop-Here ('git commit loi o ' + $repo[0]) }
}

foreach ($side in @(@($RepoA, $SoA, $PlanA, 'A'), @($RepoB, $SoB, $PlanB, 'B'))) {
  $repo = $side[0]; $so = $side[1]; $name = $side[2]
  $step = Invoke-Thu $RuntimeThu @('--project', $repo, '--state-root', $so, 'init', '--yes') $null
  if ($step.Code -ne 0 -and $step.Code -ne 1) { Show-Step $step; Stop-Here ('init loi ' + $step.Code + ' o ' + $repo) }
  $planFile = Join-Path $ThuGoc ('plan-' + $side[3] + '.json')
  $step = Invoke-Thu $PyThu @('-I', '-B', '-X', 'utf8', $Helper, 'plan', $name, $planFile, ('repo thu ' + $side[3])) $null
  if ($step.Code -ne 0) { Show-Step $step; Stop-Here 'khong viet duoc plan thu' }
  $step = Invoke-Thu $RuntimeThu @('--project', $repo, '--state-root', $so, 'plan', 'propose', $name, '--file', $planFile, '--author', 'claude-opus-5-5') $null
  if ($step.Code -ne 0) { Show-Step $step; Stop-Here ('plan propose ' + $name + ' loi') }
  $step = Invoke-Thu $RuntimeThu @('--project', $repo, '--state-root', $so, 'owner', 'approve', $name, '--revision', '1', '--reference', $Loi, '--human') $null
  Show-Step $step
  $show = Invoke-Thu $RuntimeThu @('--project', $repo, '--state-root', $so, 'plan', 'show', $name) $null
  try { $view = $show.Text | ConvertFrom-Json } catch { Stop-Here ('khong doc duoc plan show ' + $name + ': ' + $show.Text) }
  if ($view.approved_revision -ne 1) { Stop-Here ('so thu chua ghi duyet ' + $name + ' (xem dong loi o tren).') }
  $step = Invoke-Thu $RuntimeThu @('--project', $repo, '--state-root', $so, 'owner', 'enforce', $name, '--mode', 'log', '--human') $null
  Show-Step $step
  if (-not (Test-Path -LiteralPath (Join-Path $repo '.onecrew\active-plan.json'))) { Stop-Here ('chua co active-plan.json o ' + $repo) }
}

$step = Invoke-Thu $RuntimeThu @('hook', 'user', 'install', '--observe', '--settings-file', $SettingsThu, '--program', $RuntimeThu) $null
Show-Step $step
if ($step.Code -ne 0) { Stop-Here ('hook user install --observe vao settings thu loi ' + $step.Code) }

$Phien = (Invoke-Thu $PyThu @('-I', '-B', '-X', 'utf8', $Helper, 'phien') $null).Text.Trim()
$step = Invoke-Thu $PyThu @('-I', '-B', '-X', 'utf8', $Helper, 'day', '--exe', $RuntimeThu, '--settings', $SettingsThu, '--a', $RepoA, '--b', $RepoB, '--session', $Phien) $RepoA
Show-Step $step
if ($step.Code -ne 0) { Stop-Here 'day su kien mo phong loi (xem dong o tren).' }
$step = Invoke-Thu $PyThu @('-I', '-B', '-X', 'utf8', $Helper, 'xem', '--so-a', $SoA, '--so-b', $SoB, '--session', $Phien, '--plan-a', $PlanA) $null
Show-Step $step
if ((Get-RealPrint) -ne $printBefore) { Stop-Here 'tep settings Claude, danh ba du an hay tep khoa quan sat cua ban da doi trong luc chay; bao nguoi dieu phoi.' }
if ($step.Code -ne 0) { Stop-Here 'bo quan sat thu chua lam dung (xem cac dong TRUOT o tren).' }
Write-Host ('DAT: dong tom tat da che, phien ' + $Phien + ' van gan ' + $PlanA + ', so B khong co dong nao; settings Claude, danh ba du an va tep khoa quan sat cua ban khong doi.') -ForegroundColor Green
Write-Host 'Xong thi ghi ket qua bang script nghiem thu, roi don bang: thu-qsat.ps1 -QuayVe (thu truoc), roi -QuayVe -ApDung.'
