# Build a portable Windows release folder (PyInstaller one-dir bundle).
# See README — Building from source.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Require-Command($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $name"
    }
}

Require-Command python
Write-Host "==> Verifying bundled_credentials.py is empty (CI guard)..."
python scripts/generate_bundled_credentials.py --check-empty

Write-Host "==> Generating bundled credentials..."
python scripts/generate_bundled_credentials.py

try {
    try {
        python -c "import PyInstaller" 2>$null
    } catch {
        Write-Host "PyInstaller not installed. Run: pip install -r requirements-build.txt"
        exit 1
    }

    Write-Host "==> Running PyInstaller..."
    python -m PyInstaller scripts/multistream_revenue_tracker.spec --noconfirm

    $OutDir = Join-Path $Root "dist\MultistreamRevenueTracker"
    $Exe = Join-Path $OutDir "MultistreamRevenueTracker.exe"
    if (-not (Test-Path $Exe)) {
        throw "Build failed: expected $Exe"
    }

    Write-Host ""
    Write-Host "Release build ready:"
    Write-Host "  $OutDir"
    Write-Host ""
    Write-Host "Ship the whole MultistreamRevenueTracker folder. First run creates config.json and data/ beside the exe."
} finally {
    Write-Host "==> Restoring empty bundled_credentials.py..."
    git checkout -- src/multistream_revenue_tracker/bundled_credentials.py
}
