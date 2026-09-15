# Build the setup wizard for Windows (onefile exe).
# Run from the project root:  powershell -ExecutionPolicy Bypass -File build\build_windows.ps1

param(
    [string]$Name = "Claude-Multi-Setup"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python not found. Install from https://www.python.org"
}

Write-Host "Installing PyInstaller..."
python -m pip install --quiet --upgrade pyinstaller

Write-Host "Building $Name.exe ..."
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name $Name `
    --collect-submodules app `
    app\main.py

Write-Host "Done -> dist\$Name.exe"