# kiem-goi.ps1 - kiem goi OneCrew OBS-2 da giai nen, chi doc: moi file khop SHA256SUMS cua goi, khong co file la,
#   manifest.json va wheel dung version / commit / SHA256 cua ban phat hanh (mac dinh: 2.5.0.dev10, c4951f6..., 57445419...).
#
#   powershell -ExecutionPolicy Bypass -File kiem-goi.ps1 -Goi <thu muc goi da giai nen, vd ...\onecrew-2.5.0.dev10-obs2-c4951f6>
#
# Thoat 0 + "DAT" khi khop het; 1 + "KHONG DAT: <ly do>" khi khong.
param([Parameter(Mandatory=$true)][string]$Goi,
      [string]$Version = '2.5.0.dev10',
      [string]$Commit = 'c4951f6ee1bc8ab41d055e0091246d95233fae28',
      [string]$WheelSha = '57445419e7c616f8e7c9f00039c7ac1b8ccc384c4cf464a27e3bc04b9d6879a1')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
function Fail([string]$t) { Write-Host ('KHONG DAT: ' + $t) -ForegroundColor Red; exit 1 }
function Sha([string]$p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() }
if (-not (Test-Path -LiteralPath (Join-Path $Goi 'SHA256SUMS'))) { Fail "khong thay $Goi\SHA256SUMS (chon dung thu muc goi da giai nen)" }
$Goi = (Resolve-Path -LiteralPath $Goi).ProviderPath
$listed = @{}
foreach ($line in [IO.File]::ReadAllLines((Join-Path $Goi 'SHA256SUMS'))) {
    if (-not $line.Trim()) { continue }
    if ($line -notmatch '^([0-9a-fA-F]{64}) [ *](.+)$') { Fail "dong la trong SHA256SUMS: $line" }
    $listed[$Matches[2].Trim().Replace('/', '\')] = $Matches[1].ToLowerInvariant()
}
$bad = @()
foreach ($rel in $listed.Keys) {
    $p = Join-Path $Goi $rel
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { $bad += "thieu $rel"; continue }
    if ((Sha $p) -ne $listed[$rel]) { $bad += "sai hash $rel" }
}
$extra = @(Get-ChildItem -LiteralPath $Goi -Recurse -File | ForEach-Object { $_.FullName.Substring($Goi.Length).TrimStart('\') } |
    Where-Object { $_ -ne 'SHA256SUMS' -and -not $listed.ContainsKey($_) })
if ($extra.Count) { $bad += ('file khong co trong SHA256SUMS: ' + ($extra -join ', ')) }
if ($bad.Count) { Fail ($bad -join '; ') }
$m = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Goi 'manifest.json') | ConvertFrom-Json
$wheel = Join-Path $Goi ('wheel\' + $m.wheel.name)
$whs = Sha $wheel
if ($m.version -ne $Version) { Fail "manifest version $($m.version), mong doi $Version" }
if ($m.code_commit -ne $Commit) { Fail "manifest commit $($m.code_commit), mong doi $Commit" }
if ($whs -ne $WheelSha -or $m.wheel.sha256 -ne $WheelSha) { Fail "wheel sha256 $whs (manifest $($m.wheel.sha256)), mong doi $WheelSha" }
Write-Host ("DAT: goi {0} | {1} file khop SHA256SUMS | onecrew {2} | commit {3} | wheel {4} sha256 {5}" -f $Goi, $listed.Count, $m.version, $m.code_commit, $m.wheel.name, $whs) -ForegroundColor Green
exit 0
