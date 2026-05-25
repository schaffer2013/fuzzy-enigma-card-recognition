param(
    [string]$SubmodulePath = "third_party/moss-machine"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$submoduleRoot = Join-Path $repoRoot $SubmodulePath

if (-not (Test-Path -LiteralPath $submoduleRoot)) {
    git -C $repoRoot submodule update --init --depth 1 --filter=blob:none -- $SubmodulePath
}

if (-not (Test-Path -LiteralPath $submoduleRoot)) {
    throw "Moss Machine submodule not found at $submoduleRoot"
}

$patterns = @(
    "/README.md",
    "/Current version/optimized_scanner.py",
    "/Current version/card_collection_manager.py",
    "/Current version/mtg_symbol_recognizer.py",
    "/Current version/requirements.txt"
)

git -C $submoduleRoot sparse-checkout init --no-cone
$patterns | git -C $submoduleRoot sparse-checkout set --no-cone --stdin
git -C $repoRoot submodule update --init --depth 1 --filter=blob:none -- $SubmodulePath

Write-Host "Configured sparse checkout for $SubmodulePath"
