# GSDP-A (#63 luot dau): THU gan mot phien Claude vao plan thuong truc o THU MUC THU rieng, truoc khi gan that phien dieu phoi.
# Khong dung thu muc dieu phoi (D:\OneCrewRuns\dieu-phoi), so that, runtime da cai hay hook toan may. Moi lenh onecrew o day dung so thu va
# thu muc may thu rieng (LOCALAPPDATA/APPDATA trong thu muc thu), nen so dang ky du an cua may cung khong doi.
#
# Mac dinh la CHAY THU: chi kiem va in ra se lam gi, khong ghi gi. Chay that: them -ApDung. Chay trong terminal cua ban, khong chay trong phien AI.
#   (khong cong tac)  dung thu muc thu: repo du-an, so so-thu, `init --remind on` bang runtime thu (muc nhac rieng + tep mau giao viec),
#                     de xuat plan thu thuong truc (thu-gsdp-a.json, canh script nay), BAN duyet bang loi cua ban (script hoi bang Read-Host),
#                     roi bat che do GHI (owner enforce --mode log). Xong thi mo phien Claude o thu muc du-an va giao mot viec thieu muc.
#   -TomTat           chi doc: tom tat nhat ky cua thu muc thu (dong nhac, dong dung luot). Dat khi co dong nhac va khong co dong dung luot.
#   -QuayVe           go muc nhac (`init --remind off` bang runtime thu), tro hook cua du an thu ve runtime da phat hanh, kiem settings
#                     khong con muc nhac va khong con chuong trinh thu. Plan thu de nguyen trong so thu (het han sau 1 ngay).
# Tham so cho nguoi dieu phoi thu script: -RuntimeThu -RuntimeCu -ThuGoc.
#
# Buoc gan THAT (sau khi ban phat hanh co GSDP-A duoc nghiem thu; script nay KHONG lam): so rieng D:\OneCrewRuns\dieu-phoi-state (D1),
# chep tep mau vao so do, `init --remind on` cho dieu-phoi bang runtime moi, plan DIEUPHOI them "standing": true va ban duyet lai,
# `owner enforce DIEUPHOI --mode log` (che do ghi 3 ngay, D2), kiem bao cao kiem doc lap nam ngoai dieu-phoi (D4), memory va CLAUDE.md
# cua dieu-phoi da co (D5). Cach thoat: owner enforce DIEUPHOI --mode log. Xoa khoi hook KHONG phai cach thoat.
param(
  [switch]$ApDung,
  [switch]$TomTat,
  [switch]$QuayVe,
  [string]$RuntimeThu = 'D:\OneCrewRuns\gsdp-a\runtime-thu\Scripts\onecrew.exe',
  [string]$RuntimeCu = 'D:\OneCrewRuns\runtime-dev33\Scripts\onecrew.exe',
  [string]$ThuGoc = 'D:\OneCrewRuns\gsdp-a\thu-gan'
)
$ErrorActionPreference = 'Continue'
$DuAn = Join-Path $ThuGoc 'du-an'
$SoThu = Join-Path $ThuGoc 'so-thu'
$MayThu = Join-Path $ThuGoc 'may'
$PlanFile = Join-Path $PSScriptRoot 'thu-gsdp-a.json'
$PlanName = 'GSDP-A-THU'
$DieuPhoi = 'D:\OneCrewRuns\dieu-phoi'
$SettingsFile = Join-Path $DuAn '.claude\settings.local.json'
$LogFile = Join-Path $DuAn '.onecrew\violations.jsonl'
function Stop-Here([string]$why) { Write-Host ('KHONG DAT: ' + $why) -ForegroundColor Red; exit 1 }

if (($ApDung) -and ($env:CLAUDE_CODE_CHILD_SESSION -or $env:CLAUDECODE)) {
  Write-Host 'KHONG DAT: dang o trong phien AI; mo terminal rieng cua ban roi chay lai.' -ForegroundColor Red; exit 2 }
if ($TomTat -and $QuayVe) { Stop-Here 'chon mot: -TomTat hoac -QuayVe.' }
$full = [IO.Path]::GetFullPath($ThuGoc).TrimEnd('\')
if ($full.StartsWith([IO.Path]::GetFullPath($DieuPhoi).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) { Stop-Here 'thu muc thu nam trong dieu-phoi; script khong dung dieu-phoi.' }

# Dau van tay cac tep cau hinh cua dieu-phoi: script phai de nguyen chung.
function Get-DieuPhoiPrint {
  $parts = foreach ($name in @('.claude\settings.local.json', '.claude\settings.json', '.onecrew\active-plan.json', '.onecrew\config.json')) {
    $p = Join-Path $DieuPhoi $name
    if (Test-Path -LiteralPath $p) { $name + '=' + (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash } else { $name + '=khong co' } }
  $parts -join ';'
}
$printBefore = Get-DieuPhoiPrint

# Lenh onecrew voi so thu va thu muc may thu (LOCALAPPDATA/APPDATA tra lai ngay sau lenh). Text = dau ra chuan (JSON doc duoc), Err = dong loi.
function Invoke-Thu([string]$exe, [string[]]$rest) {
  $keepLocal = $env:LOCALAPPDATA; $keepRoaming = $env:APPDATA; $keepUtf8 = $env:PYTHONUTF8
  $errFile = [IO.Path]::GetTempFileName()
  $env:LOCALAPPDATA = Join-Path $MayThu 'local'; $env:APPDATA = Join-Path $MayThu 'roaming'; $env:PYTHONUTF8 = '1'
  try { $text = (& $exe --project $DuAn --state-root $SoThu @rest 2> $errFile) -join "`n"; $code = $LASTEXITCODE }
  finally { $env:LOCALAPPDATA = $keepLocal; $env:APPDATA = $keepRoaming; $env:PYTHONUTF8 = $keepUtf8 }
  $errText = [IO.File]::ReadAllText($errFile)
  [IO.File]::Delete($errFile)
  return @{ Code = $code; Text = $text; Err = $errText }
}

# Cac muc hook cua du an thu: (so muc nhac, cac chuong trinh hook ma OneCrew cai).
function Read-HookEntries {
  if (-not (Test-Path -LiteralPath $SettingsFile)) { return @{ Remind = 0; Programs = @() } }
  $data = Get-Content -LiteralPath $SettingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
  $remindCount = 0; $programs = @()
  foreach ($eventName in @('PreToolUse', 'UserPromptSubmit', 'Stop', 'SessionStart')) {
    foreach ($entry in @($data.hooks.$eventName)) {
      foreach ($handler in @($entry.hooks)) {
        if ($null -eq $handler -or $null -eq $handler.args) { continue }
        $argText = (@($handler.args) -join ' ')
        if ($argText -like 'hook *') { $programs += [string]$handler.command }
        if ($argText -eq 'hook remind') { $remindCount += 1 }
      } } }
  return @{ Remind = $remindCount; Programs = @($programs | Sort-Object -Unique) }
}

# ---- -TomTat: chi doc --------------------------------------------------------------------------------------------------------
if ($TomTat) {
  if (-not (Test-Path -LiteralPath $LogFile)) { Stop-Here ('chua co nhat ky ' + $LogFile + '; mo phien Claude o ' + $DuAn + ' va giao mot viec truoc.') }
  $lines = @(Get-Content -LiteralPath $LogFile -Encoding UTF8 | Where-Object { $_.Trim() } | ForEach-Object { try { $_ | ConvertFrom-Json } catch { $null } } | Where-Object { $_ })
  $nhac = @($lines | Where-Object { $_.event -eq 'reminded' -and $_.rule -like 'delegation_missing*' })
  $dung = @($lines | Where-Object { $_.tool -eq 'Stop' })
  Write-Host ('Nhat ky ' + $LogFile + ': ' + $lines.Count + ' dong; dong nhac giao viec: ' + $nhac.Count + '; dong dung luot (Stop): ' + $dung.Count)
  foreach ($line in ($nhac | Select-Object -Last 5)) { Write-Host ('  nhac ' + $line.at + ' ' + $line.tool + ' che do ' + $line.mode + ': ' + $line.rule) }
  foreach ($line in ($dung | Select-Object -Last 5)) { Write-Host ('  dung luot ' + $line.at + ' ' + $line.event + ': ' + $line.rule) }
  if ($nhac.Count -ge 1 -and $dung.Count -eq 0) { Write-Host 'DAT: co dong nhac khi giao viec thieu muc, khong co dong dung luot.' -ForegroundColor Green; exit 0 }
  Stop-Here 'can it nhat mot dong nhac va khong dong dung luot nao.'
}

# ---- kiem truoc (moi che do) ---------------------------------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $RuntimeThu)) { Stop-Here ('chua co runtime thu ' + $RuntimeThu + ' (nguoi dieu phoi dung wheel tu commit da qua M1).') }
$versionThu = ((& $RuntimeThu --version 2>&1) -join ' ').Trim()
Write-Host ('Runtime thu: ' + $RuntimeThu + ' (' + $versionThu + ')')

# ---- -QuayVe ------------------------------------------------------------------------------------------------------------------
if ($QuayVe) {
  if (-not (Test-Path -LiteralPath $RuntimeCu)) { Stop-Here ('khong thay runtime da phat hanh ' + $RuntimeCu) }
  $before = Read-HookEntries
  Write-Host ('Hien tai: ' + $before.Remind + ' muc nhac; chuong trinh hook: ' + ($before.Programs -join ', '))
  Write-Host 'Se lam: (1) runtime thu: init --remind off (go muc nhac); (2) runtime da phat hanh: init (tro hook du an thu ve no); (3) kiem settings.'
  if (-not $ApDung) { Write-Host 'CHAY THU: chua ghi gi. Chay lai voi -QuayVe -ApDung de quay ve.' -ForegroundColor Green; exit 0 }
  $r1 = Invoke-Thu $RuntimeThu @('init', '--yes', '--remind', 'off')
  if ($r1.Code -ne 0 -and $r1.Code -ne 1) { Write-Host $r1.Text; Write-Host $r1.Err; Stop-Here ('init --remind off loi ' + $r1.Code) }
  $r2 = Invoke-Thu $RuntimeCu @('init', '--yes')
  if ($r2.Code -ne 0 -and $r2.Code -ne 1) { Write-Host $r2.Text; Write-Host $r2.Err; Stop-Here ('init cua runtime da phat hanh loi ' + $r2.Code) }
  $after = Read-HookEntries
  $wanted = [IO.Path]::GetFullPath($RuntimeCu)
  $stray = @($after.Programs | Where-Object { [IO.Path]::GetFullPath($_) -ne $wanted })
  if ($after.Remind -ne 0) { Stop-Here 'settings van con muc nhac.' }
  if ($stray.Count -gt 0) { Stop-Here ('settings van con chuong trinh hook khac runtime da phat hanh: ' + ($stray -join ', ')) }
  if ((Get-DieuPhoiPrint) -ne $printBefore) { Stop-Here 'tep cau hinh cua dieu-phoi da doi trong luc chay; bao nguoi dieu phoi.' }
  Write-Host ('DAT: da go muc nhac; hook du an thu chay ' + $RuntimeCu + '; dieu-phoi khong doi.') -ForegroundColor Green
  exit 0
}

# ---- dung thu muc thu ---------------------------------------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $PlanFile)) { Stop-Here ('thieu plan thu ' + $PlanFile) }
Write-Host ('Thu muc thu: ' + $ThuGoc + ' (du an ' + $DuAn + ', so thu ' + $SoThu + ')')
Write-Host 'Se lam: (1) tao repo du-an neu chua co; (2) runtime thu: init --yes --remind on; (3) plan propose GSDP-A-THU (thuong truc, het han 1 ngay);'
Write-Host '        (4) BAN duyet plan thu bang loi cua ban; (5) owner enforce GSDP-A-THU --mode log; (6) kiem settings va active-plan.json.'
try { $planDoc = Get-Content -LiteralPath $PlanFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { Stop-Here ('plan thu khong phai JSON: ' + $PlanFile) }
if ($planDoc.standing -ne $true) { Stop-Here 'plan thu khong co "standing": true.' }
Write-Host ('Plan thu: ' + $PlanFile + ' (thuong truc, het han sau ' + $planDoc.budget.time + ' phut ke tu luc ban duyet).')
if (-not $ApDung) {
  Write-Host 'CHAY THU: chua ghi gi. Chay lai voi -ApDung de dung thu muc thu.' -ForegroundColor Green
  exit 0
}

$Loi = (Read-Host 'Go loi duyet plan thu cua ban (it nhat 8 ky tu, chu cua chinh ban), roi Enter').Trim()
if ($Loi.Length -lt 8) { Stop-Here 'loi duyet qua ngan; chua ghi gi.' }
if ($Loi -match '^\.+$' -or $Loi -match '(?i)loi cua ban|<|>|vi du') { Stop-Here 'loi duyet con chu mau; go loi cua chinh ban.' }

New-Item -ItemType Directory -Force -Path $DuAn, $SoThu, (Join-Path $MayThu 'local'), (Join-Path $MayThu 'roaming') | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $DuAn '.git'))) {
  & git -C $DuAn init -q
  if ($LASTEXITCODE -ne 0) { Stop-Here 'git init loi' }
  [IO.File]::WriteAllText((Join-Path $DuAn 'README.md'), "Thu muc thu GSDP-A: phien Claude o day chay duoi plan thu thuong truc GSDP-A-THU.`n")
  New-Item -ItemType Directory -Force -Path (Join-Path $DuAn 'ghi-chu') | Out-Null
  & git -C $DuAn add README.md
  & git -C $DuAn -c user.name=owner -c user.email=owner@localhost commit -q -m 'thu muc thu GSDP-A'
  if ($LASTEXITCODE -ne 0) { Stop-Here 'git commit loi' }
}
$step = Invoke-Thu $RuntimeThu @('init', '--yes', '--remind', 'on')
if ($step.Code -ne 0 -and $step.Code -ne 1) { Write-Host $step.Text; Write-Host $step.Err; Stop-Here ('init --remind on loi ' + $step.Code) }
$hooks = Read-HookEntries
if ($hooks.Remind -ne 1) { Stop-Here ('settings co ' + $hooks.Remind + ' muc nhac, can dung 1.') }
Write-Host ('Hook du an thu: 1 muc nhac; chuong trinh ' + ($hooks.Programs -join ', '))

$show = Invoke-Thu $RuntimeThu @('plan', 'show', $PlanName)
if ($show.Code -ne 0) {
  $step = Invoke-Thu $RuntimeThu @('plan', 'propose', $PlanName, '--file', $PlanFile, '--author', 'claude-opus-5-5')
  if ($step.Code -ne 0) { Write-Host $step.Text; Write-Host $step.Err; Stop-Here 'plan propose loi' }
  $show = Invoke-Thu $RuntimeThu @('plan', 'show', $PlanName)
}
try { $view = $show.Text | ConvertFrom-Json } catch { Stop-Here ('khong doc duoc plan show: ' + $show.Text) }
if ($view.approved_revision -ne 1) {
  $step = Invoke-Thu $RuntimeThu @('owner', 'approve', $PlanName, '--revision', '1', '--reference', $Loi, '--human')
  Write-Host $step.Text; if ($step.Err) { Write-Host $step.Err }
  $view = (Invoke-Thu $RuntimeThu @('plan', 'show', $PlanName)).Text | ConvertFrom-Json
  if ($view.approved_revision -ne 1) { Stop-Here 'so chua ghi duyet plan thu (xem dong loi o tren).' }
}
if (-not $view.contract.standing) { Stop-Here 'plan thu khong phai plan thuong truc (runtime thu chua co GSDP-A?).' }
$step = Invoke-Thu $RuntimeThu @('owner', 'enforce', $PlanName, '--mode', 'log', '--human')
Write-Host $step.Text; if ($step.Err) { Write-Host $step.Err }
$active = Get-Content -LiteralPath (Join-Path $DuAn '.onecrew\active-plan.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($active.mode -ne 'log' -or -not $active.standing) { Stop-Here ('active-plan.json: che do ' + $active.mode + ', standing ' + $active.standing + '; can log va true.') }
if ((Get-DieuPhoiPrint) -ne $printBefore) { Stop-Here 'tep cau hinh cua dieu-phoi da doi trong luc chay; bao nguoi dieu phoi.' }
Write-Host ('DAT: thu muc thu san sang. Plan ' + $PlanName + ' thuong truc, che do ghi, het han ' + $active.expires + '; dieu-phoi khong doi.') -ForegroundColor Green
Write-Host ('Tiep theo: mo phien Claude moi o ' + $DuAn + ', go: "nho mot agent doc README.md roi tom tat" (khong neu muc tieu hay cach kiem);')
Write-Host '  khi agent xong, hoi Claude vua nhan loi nhac gi. Roi chay script nay voi -TomTat, cuoi cung -QuayVe (thu truoc, roi -QuayVe -ApDung).'
