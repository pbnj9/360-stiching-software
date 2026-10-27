$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$buildPath = Join-Path $env:TEMP "Gear360StitcherBuild"
python -m PyInstaller `
    --noconfirm `
    --clean `
    --workpath $buildPath `
    --onefile `
    --windowed `
    --name "Gear-360-Stitcher" `
    --add-data "calibration_profiles;calibration_profiles" `
    main.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Created: $projectRoot\dist\Gear-360-Stitcher.exe"
