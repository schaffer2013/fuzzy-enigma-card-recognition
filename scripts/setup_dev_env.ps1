param(
    [string]$Python = "python",
    [string]$VenvPath = ".venv",
    [string]$Extras = "ocr,ui,moss,dev",
    [switch]$Update,
    [switch]$SkipSubmodules,
    [switch]$SkipCatalog,
    [switch]$PrehashArt
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

try {
    if (-not $SkipSubmodules) {
        $git = Get-Command git -ErrorAction SilentlyContinue
        if ($null -ne $git) {
            Write-Host "Syncing git submodules..."
            & git submodule sync --recursive
            & git submodule update --init --recursive
        } else {
            Write-Warning "git not found; skipping submodule sync."
        }
    }

    if (-not (Test-Path $VenvPath)) {
        Write-Host "Creating virtual environment at $VenvPath..."
        & $Python -m venv $VenvPath
    } elseif ($Update) {
        Write-Host "Reusing existing virtual environment at $VenvPath..."
    }

    $pythonExe = Join-Path $VenvPath "Scripts/python.exe"
    if (-not (Test-Path $pythonExe)) {
        throw "Virtual environment python not found at $pythonExe"
    }

    Write-Host "Upgrading packaging tools..."
    & $pythonExe -m pip install --upgrade pip setuptools wheel

    $editableTarget = "."
    if (-not [string]::IsNullOrWhiteSpace($Extras)) {
        $editableTarget = ".[{0}]" -f $Extras
    }

    Write-Host "Installing editable package $editableTarget..."
    & $pythonExe -m pip install -e $editableTarget

    if (-not $SkipCatalog) {
        $catalogDb = Join-Path $RepoRoot "data/catalog/cards.sqlite3"
        $catalogJson = Join-Path $RepoRoot "data/catalog/default-cards.json"
        if ($Update -or -not (Test-Path $catalogDb) -or -not (Test-Path $catalogJson)) {
            Write-Host "Building local catalog..."
            & $pythonExe scripts/build_catalog.py --download
        } else {
            Write-Host "Catalog already present; skipping rebuild."
        }
    }

    if ($PrehashArt) {
        Write-Host "Prehashing missing art references..."
        & $pythonExe scripts/prehash_missing_art_refs.py
    }

    Write-Host ""
    Write-Host "Environment ready."
    Write-Host "Activate with: $VenvPath\\Scripts\\Activate.ps1"
    Write-Host "Run tests with: $pythonExe -m pytest --engine-only"
} finally {
    Pop-Location
}
