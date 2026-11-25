# VAI3 moc M2: THU phan nhac khi chu go thang vao phien duoi plan thuong truc, o THU MUC THU rieng.
# Khong dung thu muc dieu phoi, so that, runtime da cai hay hook toan may. Moi lenh onecrew cua phan thu dung so thu va thu muc may thu rieng.
#
# Mac dinh la CHAY THU: chi kiem va in ra se lam gi, khong ghi gi. Chay that: them -ApDung. Chay trong terminal cua ban, khong chay trong phien AI.
#   (khong cong tac)  kiem moc M1 da dat, dung goi tu commit HEAD cua worktree vao venv thu, tao du-an + so thu, `init`, de xuat plan thu thuong
#                     truc, BAN duyet bang loi cua ban (script hoi bang Read-Host), bat che do GHI.
#   -TomTat           chi doc: dem dong nhac owner_prompt trong nhat ky thu. Dat khi dung 1 dong sau khi ban go 1 cau VA mot phien khac gui 1 tin.
#   -QuayVe           tro hook cua du an thu ve runtime da phat hanh (them -ApDung de lam that). Plan thu het han sau 1 ngay.
param(
  [switch]$ApDung,
  [switch]$TomTat,
  [switch]$QuayVe,
  [string]$Nguon = '',
  [string]$ThuGoc = 'D:\OneCrewRuns\vai3\thu',
  [string]$Python = 'D:\OneCrewRuns\ui-mockup\py312\python.exe',
  [string]$RuntimeCu = 'D:\OneCrewRuns\runtime-dev33\Scripts\onecrew.exe',
  [string]$SoPhatTrien = 'D:\OneCrewRuns\onecrew-development'
)
$ErrorActionPreference = 'Continue'
if (-not $Nguon) { $Nguon = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path }
$DuAn = Join-Path $ThuGoc 'du-an'
$SoThu = Join-Path $ThuGoc 'so-thu'
$MayThu = Join-Path $ThuGoc 'may'
$RuntimeThu = Join-Path $ThuGoc 'runtime\Scripts\onecrew.exe'
$PlanName = 'VAI3-THU'
$LogFile = Join-Path $DuAn '.onecrew\violations.jsonl'
$SettingsFile = Join-Path $DuAn '.claude\settings.local.json'
function Stop-Here([string]$why) { Write-Host ('KHONG DAT: ' + $why) -ForegroundColor Red; exit 1 }

if ($ApDung -and ($env:CLAUDE_CODE_CHILD_SESSION -or $env:CLAUDECODE)) {
  Write-Host 'KHONG DAT: dang o trong phien AI; mo terminal rieng cua ban roi chay lai.' -ForegroundColor Red; exit 2 }
if ($TomTat -and $QuayVe) { Stop-Here 'chon mot: -TomTat hoac -QuayVe.' }

# onecrew voi mot du an, mot so va mot thu muc may rieng (LOCALAPPDATA/APPDATA tra lai ngay sau lenh).
function Invoke-OneCrew([string]$exe, [string]$project, [string]$state, [string]$machine, [string[]]$rest) {
  $keepLocal = $env:LOCALAPPDATA; $keepRoaming = $env:APPDATA; $keepUtf8 = $env:PYTHONUTF8; $keepOut = [Console]::OutputEncoding
  $errFile = [IO.Path]::GetTempFileName()
  $env:LOCALAPPDATA = Join-Path $machine 'local'; $env:APPDATA = Join-Path $machine 'roaming'; $env:PYTHONUTF8 = '1'
  try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $text = (& $exe --project $project --state-root $state @rest 2> $errFile) -join "`n"; $code = $LASTEXITCODE }
  finally { $env:LOCALAPPDATA = $keepLocal; $env:APPDATA = $keepRoaming; $env:PYTHONUTF8 = $keepUtf8; [Console]::OutputEncoding = $keepOut }
  $errText = [IO.File]::ReadAllText($errFile)
  [IO.File]::Delete($errFile)
  return @{ Code = $code; Text = $text; Err = $errText }
}
function Invoke-Thu([string]$exe, [string[]]$rest) { return Invoke-OneCrew $exe $DuAn $SoThu $MayThu $rest }

# ---- -TomTat: chi doc --------------------------------------------------------------------------------------------------------
if ($TomTat) {
  if (-not (Test-Path -LiteralPath $LogFile)) { Stop-Here ('chua co nhat ky ' + $LogFile + '; mo phien Claude o ' + $DuAn + ' va go mot cau truoc.') }
  $lines = @(Get-Content -LiteralPath $LogFile -Encoding UTF8 | Where-Object { $_.Trim() } | ForEach-Object { try { $_ | ConvertFrom-Json } catch { $null } } | Where-Object { $_ })
  $nhac = @($lines | Where-Object { $_.event -eq 'reminded' -and $_.rule -eq 'owner_prompt' })
  Write-Host ('Nhat ky ' + $LogFile + ': ' + $lines.Count + ' dong; dong nhac loi chu (owner_prompt): ' + $nhac.Count)
  foreach ($line in ($nhac | Select-Object -Last 5)) { Write-Host ('  nhac ' + $line.at + ' phien ' + $line.session + ' che do ' + $line.mode) }
  if ($nhac.Count -eq 1) {
    Write-Host 'DAT: dung 1 dong nhac. Chi tinh la dat neu ban da go DUNG 1 cau VA tin cua phien khac DA HIEN trong phien thu truoc khi chay lenh nay.' -ForegroundColor Green
    exit 0 }
  Stop-Here ('can dung 1 dong nhac (ban go 1 cau; tin cua phien khac khong duoc them dong nao), dang co ' + $nhac.Count + '.')
}

# ---- -QuayVe ------------------------------------------------------------------------------------------------------------------
if ($QuayVe) {
  if (-not (Test-Path -LiteralPath $SettingsFile)) { Stop-Here ('chua co du an thu o ' + $DuAn + '; khong co gi de quay ve.') }
  if (-not (Test-Path -LiteralPath $RuntimeCu)) { Stop-Here ('khong thay runtime da phat hanh ' + $RuntimeCu) }
  Write-Host ('Se lam: runtime da phat hanh chay `init` trong du an thu (tro hook ve ' + $RuntimeCu + '), roi kiem settings.')
  if (-not $ApDung) { Write-Host 'CHAY THU: chua ghi gi. Chay lai voi -QuayVe -ApDung de quay ve.' -ForegroundColor Green; exit 0 }
  $r = Invoke-Thu $RuntimeCu @('init', '--yes')
  if ($r.Code -ne 0 -and $r.Code -ne 1) { Write-Host $r.Text; Write-Host $r.Err; Stop-Here ('init cua runtime da phat hanh loi ' + $r.Code) }
  $settings = Get-Content -LiteralPath $SettingsFile -Raw -Encoding UTF8
  if ($settings.Contains((Join-Path $ThuGoc 'runtime').Replace('\', '\\'))) { Stop-Here 'settings cua du an thu van con chuong trinh thu.' }
  Write-Host ('DAT: hook du an thu chay ' + $RuntimeCu + '.') -ForegroundColor Green
  exit 0
}

# ---- kiem truoc ---------------------------------------------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $Python)) { Stop-Here ('khong thay Python ' + $Python) }
if (-not (Test-Path -LiteralPath $RuntimeCu)) { Stop-Here ('khong thay runtime da phat hanh ' + $RuntimeCu) }
$dirty = @(& git -C $Nguon status --porcelain -- onecrew pyproject.toml)
if ($LASTEXITCODE -ne 0) { Stop-Here ('git status loi o ' + $Nguon) }
if ($dirty.Count -gt 0) { Stop-Here ('ma nguon co thay doi chua commit: ' + ($dirty -join '; ')) }
$head = ((& git -C $Nguon rev-parse HEAD) -join '').Trim()
$show = Invoke-OneCrew $RuntimeCu $Nguon (Join-Path $SoPhatTrien 'state') (Join-Path $SoPhatTrien 'machine') @('plan', 'show', 'VAI3')
if ($show.Code -ne 0) { Write-Host $show.Err; Stop-Here 'khong doc duoc plan VAI3 trong so phat trien.' }
try { $vai3 = $show.Text | ConvertFrom-Json } catch { Stop-Here 'plan show VAI3 khong tra JSON.' }
$m1 = @($vai3.milestones | Where-Object { $_.id -eq 'M1' })[0]
if ($null -eq $m1 -or $m1.state -ne 'passed') { Stop-Here ('moc M1 chua dat (dang: ' + $m1.state + '); bao nguoi dieu phoi.') }
Write-Host ('Moc M1 da dat. Goi thu dung tu commit ' + $head.Substring(0, 12) + ' cua ' + $Nguon)
Write-Host ('Thu muc thu: ' + $ThuGoc + ' (du an ' + $DuAn + ', so thu ' + $SoThu + ')')
Write-Host 'Se lam: (1) xuat commit, tao venv thu va cai goi; (2) tao repo du-an; (3) init --yes; (4) de xuat plan VAI3-THU (thuong truc, het han 1 ngay);'
Write-Host '        (5) BAN duyet plan thu bang loi cua ban; (6) owner enforce VAI3-THU --mode log; (7) kiem hook va active-plan.json.'
if (-not $ApDung) { Write-Host 'CHAY THU: chua ghi gi. Chay lai voi -ApDung de dung thu muc thu.' -ForegroundColor Green; exit 0 }
if (Test-Path -LiteralPath $LogFile) { Stop-Here ('thu muc thu da co nhat ky cu (' + $LogFile + '); doi ten thu muc ' + $ThuGoc + ' roi chay lai.') }

$Loi = (Read-Host 'Go loi duyet plan thu cua ban (it nhat 8 ky tu, chu cua chinh ban), roi Enter').Trim()
if ($Loi.Length -lt 8) { Stop-Here 'loi duyet qua ngan; chua ghi gi.' }
if ($Loi -match '^\.+$' -or $Loi -match '(?i)loi cua ban|<|>|vi du') { Stop-Here 'loi duyet con chu mau; go loi cua chinh ban.' }

# ---- goi thu ------------------------------------------------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $DuAn, $SoThu, (Join-Path $MayThu 'local'), (Join-Path $MayThu 'roaming') | Out-Null
$src = Join-Path $ThuGoc ('nguon-' + $head.Substring(0, 12))
New-Item -ItemType Directory -Force -Path $src | Out-Null
$tar = $src + '.tar'
& git -C $Nguon -c core.autocrlf=false archive --format=tar -o $tar $head -- onecrew pyproject.toml README.md
if ($LASTEXITCODE -ne 0) { Stop-Here 'git archive loi' }
& tar -xf $tar -C $src
if ($LASTEXITCODE -ne 0) { Stop-Here 'giai nen loi' }
& $Python -m venv (Join-Path $ThuGoc 'runtime')
if ($LASTEXITCODE -ne 0) { Stop-Here 'tao venv thu loi' }
& (Join-Path $ThuGoc 'runtime\Scripts\python.exe') -m pip install --quiet --force-reinstall $src
if ($LASTEXITCODE -ne 0) { Stop-Here 'cai goi thu loi (xem dong loi cua pip o tren)' }
if (-not (Test-Path -LiteralPath $RuntimeThu)) { Stop-Here ('khong thay ' + $RuntimeThu + ' sau khi cai') }

# ---- du an thu va plan thu ------------------------------------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath (Join-Path $DuAn '.git'))) {
  & git -C $DuAn init -q
  if ($LASTEXITCODE -ne 0) { Stop-Here 'git init loi' }
  [IO.File]::WriteAllText((Join-Path $DuAn 'README.md'), "Thu muc thu VAI3: phien Claude o day chay duoi plan thu thuong truc VAI3-THU.`n")
  & git -C $DuAn add README.md
  & git -C $DuAn -c user.name=owner -c user.email=owner@localhost commit -q -m 'thu muc thu VAI3'
  if ($LASTEXITCODE -ne 0) { Stop-Here 'git commit loi' }
}
$planFile = Join-Path $ThuGoc 'plan-vai3-thu.json'
$planText = @'
{
 "schema_version": 2,
 "title": "Plan thu thuong truc cua VAI3: chu go thang vao phien thi co dong nhac, tin phien khac thi khong",
 "size": "S",
 "standing": true,
 "origin": {"at": "2026-11-25 21:40", "by": "owner", "quote": "Plan nay chi dung de thu phan nhac cua VAI3 o thu muc thu."},
 "understanding": {
  "restated_goal": "Thu phan nhac khi chu go thang vao phien duoi plan thuong truc, o thu muc thu rieng voi so thu rieng.",
  "target": {"repo": ".", "ref": "HEAD", "paths": ["README.md"]},
  "assumptions": [], "confidence": "high", "unknowns": []
 },
 "preconditions": [{"id": "P1", "check": "path_exists", "args": {"path": "README.md"}, "why": "Thu muc thu da co repo va tep dau tien."}],
 "output": ["Go mot cau thi nhat ky thu co mot dong nhac; tin cua phien khac thi khong."],
 "scope": {"owned": ["ghi-chu/"]},
 "non_goals": ["Dung thu muc dieu phoi, so that, runtime da cai hay hook toan may"],
 "items": [{"id": "I1", "title": "Thu nhac loi chu o thu muc thu", "tier": "must", "milestone": "M1", "source": "origin"}],
 "milestones": [{"id": "M1", "title": "Chu thu o thu muc thu", "verifier": {"type": "owner-manual", "config": {}}, "covers": ["O1"]}],
 "budget": {"max_calls": 100, "time": 1440},
 "attention": {"questions": 1},
 "profile_version": null,
 "presentation": {
  "request": "Thu phan nhac khi ban go thang vao phien, o thu muc thu rieng.",
  "user_sees": ["Go mot cau thi nhat ky co mot dong nhac; tin cua phien khac thi khong."],
  "acceptance_steps": ["Mo phien Claude o thu muc thu va go mot cau.", "Cho mot phien khac gui mot tin, roi chay script voi -TomTat."],
  "not_doing": "Khong doi thu muc dieu phoi, so that hay hook toan may; plan thu het han sau mot ngay."
 }
}
'@
[IO.File]::WriteAllText($planFile, $planText, (New-Object System.Text.UTF8Encoding $false))
$step = Invoke-Thu $RuntimeThu @('init', '--yes')
if ($step.Code -ne 0 -and $step.Code -ne 1) { Write-Host $step.Text; Write-Host $step.Err; Stop-Here ('init loi ' + $step.Code) }
$show = Invoke-Thu $RuntimeThu @('plan', 'show', $PlanName)
if ($show.Code -ne 0) {
  $step = Invoke-Thu $RuntimeThu @('plan', 'propose', $PlanName, '--file', $planFile, '--author', 'claude-sonnet-5-5')
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
$step = Invoke-Thu $RuntimeThu @('owner', 'enforce', $PlanName, '--mode', 'log', '--human')
Write-Host $step.Text; if ($step.Err) { Write-Host $step.Err }
$active = Get-Content -LiteralPath (Join-Path $DuAn '.onecrew\active-plan.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($active.mode -ne 'log' -or -not $active.standing) { Stop-Here ('active-plan.json: che do ' + $active.mode + ', standing ' + $active.standing + '; can log va true.') }
$settings = Get-Content -LiteralPath $SettingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
$promptHooks = @(foreach ($entry in @($settings.hooks.UserPromptSubmit)) { foreach ($h in @($entry.hooks)) { if ((@($h.args) -join ' ') -eq 'hook prompt') { $h.command } } })
if ($promptHooks.Count -ne 1) { Stop-Here ('du an thu co ' + $promptHooks.Count + ' muc hook prompt, can dung 1.') }
Write-Host ('DAT: thu muc thu san sang. Plan ' + $PlanName + ' thuong truc, che do ghi, het han ' + $active.expires + '.') -ForegroundColor Green
Write-Host ('Tiep theo: (1) mo phien Claude MOI o ' + $DuAn + ' va go DUNG MOT cau; (2) nho phien dieu phoi gui mot tin vao phien do va doi tin hien ra;')
Write-Host '  (3) chay script nay voi -TomTat; (4) chay -QuayVe, roi -QuayVe -ApDung.'
