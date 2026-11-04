# hien-trang.ps1 - ghi lai hien trang OneCrew cua MOT repo, chi doc: runtime ma hook goi (duong dan, SHA256, version), file hook/config, so (state root).
#   Lan 1:                 powershell -ExecutionPolicy Bypass -File hien-trang.ps1 -DuAn <repo> -Ra <file .json moi>
#   Lan 2 (sau khi thu UI): powershell -ExecutionPolicy Bypass -File hien-trang.ps1 -DuAn <repo> -Ra <file .json moi khac> -SoSanh <file .json lan 1>
#     -> DAT khi runtime, hook va config KHONG doi. So (ledger) chi in de doc, khong so sanh: worker that cua repo co the van ghi so.
# Khong ghi gi vao repo hay so; chi chay "<runtime> --version". Thoat 0 = DAT; 1 = khong dat / thieu; 2 = repo khong co hook OneCrew.
param([Parameter(Mandatory=$true)][string]$DuAn, [Parameter(Mandatory=$true)][string]$Ra, [string]$SoSanh)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
function Fail([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; exit 1 }
function Sha([string]$p) { if (Test-Path -LiteralPath $p -PathType Leaf) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null } }
if (-not (Test-Path -LiteralPath $DuAn)) { Fail "khong thay repo $DuAn" }
$root = (Resolve-Path -LiteralPath $DuAn).ProviderPath
$Ra = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Ra)
if (Test-Path -LiteralPath $Ra) { Fail "$Ra da ton tai: dat ten file moi (khong ghi de)" }
$cfgPath = Join-Path $root '.onecrew\config.json'
$state = $null
if (Test-Path -LiteralPath $cfgPath) {
    try { $cfg = Get-Content -Raw -Encoding UTF8 -LiteralPath $cfgPath | ConvertFrom-Json; if ($cfg.state_root) { $state = [string]$cfg.state_root } } catch { Fail "khong doc duoc $cfgPath" }
}
$files = [ordered]@{}
foreach ($rel in '.claude\settings.local.json', '.claude\settings.json', '.onecrew\config.json') { $files[$rel] = Sha (Join-Path $root $rel) }
$commands = New-Object System.Collections.Generic.List[string]
foreach ($rel in '.claude\settings.local.json', '.claude\settings.json') {
    $p = Join-Path $root $rel
    if (-not (Test-Path -LiteralPath $p)) { continue }
    try { $data = Get-Content -Raw -Encoding UTF8 -LiteralPath $p | ConvertFrom-Json } catch { Fail "khong doc duoc $p" }
    if (-not $data.hooks) { continue }
    foreach ($event in $data.hooks.PSObject.Properties) {
        foreach ($entry in @($event.Value)) {
            foreach ($h in @($entry.hooks)) {
                if (-not $h -or -not $h.command) { continue }
                $isOurs = (@($h.args) -contains 'hook') -or ([string]$h.command -match 'onecrew')
                if ($isOurs -and -not $commands.Contains([string]$h.command)) { $commands.Add([string]$h.command) }
            }
        }
    }
}
if ($commands.Count -eq 0) {
    Write-Host "Repo $root khong co hook OneCrew (.claude\settings*.json). Day la repo chua dung OneCrew: xem huong dan Bat dau su dung." -ForegroundColor Yellow
    exit 2
}
$runtimes = @()
foreach ($c in $commands) {
    $r = [ordered]@{ command = $c; exists = (Test-Path -LiteralPath $c -PathType Leaf); sha256 = (Sha $c); version = $null }
    if ($r.exists -and ([IO.Path]::GetFileName($c) -match '^onecrew(\.exe|\.cmd)?$')) { try { $r.version = ((& $c --version) -join ' ').Trim() } catch { $r.version = 'loi: ' + $_.Exception.Message } }
    elseif ($r.exists) { $r.version = 'hook dang checkout (python + ma nguon), khong co --version' }
    $runtimes += [pscustomobject]$r
}
$ledger = $null
if ($state) {
    $lp = Join-Path $state 'ledger.sqlite3'
    if (Test-Path -LiteralPath $lp) { $i = Get-Item -LiteralPath $lp; $ledger = [ordered]@{ path = $lp; bytes = $i.Length; last_write_utc = $i.LastWriteTimeUtc.ToString('o') } }
}
$out = [ordered]@{ kind = 'onecrew-hien-trang'; at = (Get-Date).ToUniversalTime().ToString('o'); project = $root; state_root = $state
    files = $files; runtimes = $runtimes; ledger = $ledger }
$dir = Split-Path -Parent $Ra
if ($dir) { [void][IO.Directory]::CreateDirectory($dir) }
[IO.File]::WriteAllText($Ra, ($out | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding $false))
Write-Host "== repo $root"
Write-Host ("   so (state root): " + $(if ($state) { $state } else { '(khong co .onecrew\config.json: hook dung so mac dinh)' }))
foreach ($r in $runtimes) { Write-Host ("   hook goi: {0} | {1} | sha256 {2}" -f $r.command, $r.version, $r.sha256) }
if ($ledger) { Write-Host ("   so: {0} byte, ghi lan cuoi {1} (chi de doc, khong so sanh)" -f $ledger.bytes, $ledger.last_write_utc) }
Write-Host "   da ghi $Ra"
if (-not $SoSanh) { Write-Host 'DAT: da ghi hien trang.' -ForegroundColor Green; exit 0 }
if (-not (Test-Path -LiteralPath $SoSanh)) { Fail "khong thay $SoSanh" }
$old = Get-Content -Raw -Encoding UTF8 -LiteralPath $SoSanh | ConvertFrom-Json
$diff = @()
if ([string]$old.project -ne $root) { $diff += "repo khac ($($old.project))" }
if ([string]$old.state_root -ne [string]$state) { $diff += "state root: $($old.state_root) -> $state" }
foreach ($k in $files.Keys) { $was = $old.files.$k; if ([string]$was -ne [string]$files[$k]) { $diff += "$k doi ($was -> $($files[$k]))" } }
$a = @($old.runtimes | ForEach-Object { '{0}|{1}|{2}' -f $_.command, $_.sha256, $_.version }) | Sort-Object
$b = @($runtimes | ForEach-Object { '{0}|{1}|{2}' -f $_.command, $_.sha256, $_.version }) | Sort-Object
if (($a -join "`n") -ne ($b -join "`n")) { $diff += 'runtime ma hook goi da doi' }
if ($diff.Count) { Fail ('hien trang khac lan truoc: ' + ($diff -join '; ')) }
Write-Host 'DAT: runtime, hook va config khong doi so voi lan truoc.' -ForegroundColor Green
exit 0
