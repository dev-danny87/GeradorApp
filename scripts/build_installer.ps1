# Build Gerador_Redmine.exe (flet pack) and Gerador_Redmine_Setup.exe (Inno Setup)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Flet = Join-Path $Root ".venv\Scripts\flet.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}
if (-not (Test-Path $Flet)) {
    $Flet = "flet"
}

Write-Host "==> flet pack..."
& $Flet pack main.py --name "Gerador_Redmine" --icon "icon.ico" -y --product-version "1.0.0" --file-version "1.0.0"
if ($LASTEXITCODE -ne 0) { throw "flet pack failed" }

$Exe = Join-Path $Root "dist\Gerador_Redmine.exe"
if (-not (Test-Path $Exe)) {
    throw "Missing $Exe after flet pack"
}

$IsccCandidates = @(
    "${env:LocalAppData}\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup ISCC.exe not found. Install with: winget install JRSoftware.InnoSetup"
}

Write-Host "==> Compiling installer with $Iscc ..."
& $Iscc (Join-Path $Root "installer\Gerador_Redmine.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }

$Setup = Join-Path $Root "dist_installer\Gerador_Redmine_Setup.exe"
if (-not (Test-Path $Setup)) {
    throw "Missing $Setup"
}

Write-Host "OK: $Setup"
