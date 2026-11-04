# Stop exactly the viewer this trial pinned. Never stop a worker or scan process names.
param([Parameter(Mandatory=$true)][string]$Package, [Parameter(Mandatory=$true)][string]$Work)
& (Join-Path $PSScriptRoot 'viewer_obs2.ps1') -Mode Stop -Package $Package -Work $Work
exit $LASTEXITCODE
