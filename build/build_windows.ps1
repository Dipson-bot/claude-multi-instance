param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python not found. Install from https://www.python.org"
}

$Name = if ($env:CLAUDE_SETUP_NAME) { $env:CLAUDE_SETUP_NAME } else { "Claude-Multi-Setup" }

Write-Host "Installing PyInstaller..."
python -m pip install --quiet --upgrade pyinstaller

Write-Host "Building $Name.exe ..."
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name $Name `
    --icon icon.ico `
    --paths . `
    run.py

Write-Host "Done -> dist\$Name.exe"
