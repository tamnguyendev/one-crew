# Shared small wrapper: only the synthetic work created by verify_obs2.py, then the unchanged OBS-1 identity lifecycle.
param([Parameter(Mandatory=$true)][ValidateSet('Open','Stop')][string]$Mode,
      [Parameter(Mandatory=$true)][string]$Package, [Parameter(Mandatory=$true)][string]$Work, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$pkg = (Resolve-Path -LiteralPath $Package).ProviderPath
$trialRoot = (Resolve-Path -LiteralPath $Work).ProviderPath
$manifest = Get-Content -LiteralPath (Join-Path $pkg 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$trial = Get-Content -LiteralPath (Join-Path $trialRoot 'trial.json') -Raw -Encoding UTF8 | ConvertFrom-Json
function Norm([string]$path) { [IO.Path]::GetFullPath($path).TrimEnd('\').ToLowerInvariant() }
if ($manifest.kind -ne 'obs2-local-trial' -or $trial.kind -ne 'obs2-synthetic-state' -or
    (Norm $trial.package) -ne (Norm $pkg) -or $trial.code_commit -ne $manifest.code_commit -or
    $trial.wheel_sha256 -ne $manifest.wheel.sha256 -or $trial.version -ne $manifest.version -or
    (Norm $trial.state_root) -ne (Norm (Join-Path $trialRoot 'state')) -or
    (Norm $trial.project) -ne (Norm (Join-Path $trialRoot 'project'))) {
    throw 'Trial/package identity mismatch. Only generated synthetic OBS-2 trial state is supported.'
}
$venv = Join-Path $trialRoot 'venv'
$exe = Join-Path $venv 'Scripts\onecrew.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Trial venv is missing; run verify_obs2.py first.' }
$version = (& $exe --version) -join ' '
if ($LASTEXITCODE -ne 0 -or $version.Trim() -ne ('onecrew ' + $manifest.version)) { throw 'Installed version differs from package.' }
$wheelHash = (Get-FileHash -LiteralPath (Join-Path $pkg ('wheel\' + $manifest.wheel.name)) -Algorithm SHA256).Hash.ToLowerInvariant()
if ($wheelHash -ne $manifest.wheel.sha256) { throw 'Wheel hash differs from manifest.' }
foreach ($module in $manifest.module_sha256.PSObject.Properties) {
    $installed = Join-Path (Join-Path $venv 'Lib\site-packages') $module.Name.Replace('/', '\')
    $hash = (Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $module.Value) { throw ('Installed module differs from pinned snapshot: ' + $module.Name) }
}
$settings = @{ LOCALAPPDATA = (Join-Path $trialRoot 'local'); APPDATA = (Join-Path $trialRoot 'roaming')
    TEMP = (Join-Path $trialRoot 'temp'); TMP = (Join-Path $trialRoot 'temp'); ONECREW_TRACK_MARKER_DIR = (Join-Path $trialRoot 'markers') }
$previous = @{}
foreach ($key in $settings.Keys) { $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process') }
try {
    foreach ($key in $settings.Keys) { [Environment]::SetEnvironmentVariable($key, $settings[$key], 'Process') }
    $arguments = @{ Venv = $venv; Project = $trial.project; StateRoot = $trial.state_root
        PinFile = (Join-Path $trialRoot 'viewer-pin.json') }
    Write-Host 'DU LIEU THU OBS-2: so tong hop co lap, khong phai cong viec/provider that.'
    if ($Mode -eq 'Open') {
        $arguments.ProjectOnly = $true
        if ($NoBrowser) { $arguments.NoBrowser = $true }
        & (Join-Path $pkg 'verify\mo-trang-obs1.ps1') @arguments
    } else {
        & (Join-Path $pkg 'verify\dung-trang-obs1.ps1') @arguments
    }
    $resultCode = $LASTEXITCODE
} finally {
    foreach ($key in $settings.Keys) { [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process') }
}
exit $resultCode
