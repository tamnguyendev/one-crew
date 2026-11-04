# Open only the generated OBS-2 synthetic trial, pinned to the exact viewer instance.
param([Parameter(Mandatory=$true)][string]$Package, [Parameter(Mandatory=$true)][string]$Work, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'viewer_obs2.ps1') -Mode Open -Package $Package -Work $Work -NoBrowser:$NoBrowser
exit $LASTEXITCODE
