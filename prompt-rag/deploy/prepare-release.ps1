param(
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseRoot = if ($OutputDirectory) {
    [System.IO.Path]::GetFullPath($OutputDirectory)
} else {
    Join-Path $ProjectRoot "release"
}
$Stage = Join-Path $ReleaseRoot "prompt-rag"
$Archive = Join-Path $ReleaseRoot "prompt-rag-release.zip"

$projectPrefix = $ProjectRoot.TrimEnd('\') + '\'
$releasePrefix = [System.IO.Path]::GetFullPath($ReleaseRoot).TrimEnd('\') + '\'
if (-not $releasePrefix.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and -not $OutputDirectory) {
    throw "Default release directory must stay inside the project root."
}

if (Test-Path -LiteralPath $Stage) {
    $resolvedStage = [System.IO.Path]::GetFullPath($Stage)
    if (-not $resolvedStage.StartsWith($releasePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a staging directory outside the release root."
    }
    Remove-Item -LiteralPath $resolvedStage -Recurse -Force
}
New-Item -ItemType Directory -Path $Stage -Force | Out-Null

foreach ($item in @("src", "web", "deploy", "pyproject.toml", "README.md")) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $item) -Destination $Stage -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $Stage "web-v2") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "web-v2\dist") -Destination (Join-Path $Stage "web-v2") -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $Stage "data") -Force | Out-Null

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project .venv is missing: $Python"
}
& $Python (Join-Path $ProjectRoot "deploy\sanitize_database.py") `
    (Join-Path $ProjectRoot "data\prompt_rag.db") `
    (Join-Path $Stage "data\prompt_rag.db")
if ($LASTEXITCODE -ne 0) { throw "Database sanitization failed." }

if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Archive -CompressionLevel Optimal

$archiveSize = [math]::Round((Get-Item -LiteralPath $Archive).Length / 1MB, 2)
Write-Output "Release directory: $Stage"
Write-Output "Release archive: $Archive ($archiveSize MB)"
