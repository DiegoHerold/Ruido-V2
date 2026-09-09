param(
    [string]$InputFile = "",
    [string]$Company = "",
    [string]$CompanyCnpj = "",
    [switch]$InstallDeps,
    [switch]$Test,
    [switch]$ListChromeExtensions,
    [switch]$OpenChromeProfile,
    [switch]$SyncChromeProfile
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Find-Python {
    if ((Test-Path -LiteralPath $VenvPython) -and (Test-Python $VenvPython)) {
        return $VenvPython
    }

    $candidates = @(
        "python",
        "py",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Python $candidate) {
            return $candidate
        }
    }

    return $null
}

function Test-Python {
    param([string]$Candidate)

    try {
        $output = & $Candidate --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            return $false
        }
        return ($output -match "Python 3\.(1[1-9]|[2-9][0-9])")
    }
    catch {
        return $false
    }
}

function Show-MissingPythonHelp {
    Write-Host ""
    Write-Host "Python nao foi encontrado em um local utilizavel." -ForegroundColor Red
    Write-Host ""
    Write-Host "Instale Python 3.11 ou 3.12 e marque a opcao 'Add python.exe to PATH'."
    Write-Host "Depois abra um novo terminal nesta pasta e rode:"
    Write-Host "  .\run.ps1 -InstallDeps"
    Write-Host "  .\run.ps1"
    Write-Host ""
    Write-Host "Observacao: o .venv atual aponta para Python314, mas esse Python nao esta acessivel neste Windows."
}

$Python = Find-Python
if (-not $Python) {
    Show-MissingPythonHelp
    exit 2
}

Set-Location -LiteralPath $ProjectRoot
Write-Host "Python: $Python"

if ($ListChromeExtensions) {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\find_chrome_extensions.ps1")
    exit $LASTEXITCODE
}

if ($OpenChromeProfile) {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\open_chrome_automation_profile.ps1")
    exit $LASTEXITCODE
}

if ($SyncChromeProfile) {
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    & $Python (Join-Path $ProjectRoot "scripts\sync_chrome_profile.py")
    exit $LASTEXITCODE
}

if ($InstallDeps) {
    & $Python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m playwright install chrome
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($Test) {
    & $Python -m pytest
    exit $LASTEXITCODE
}

$argsList = @("run.py")
if ($InputFile) {
    $argsList += @("--input", $InputFile)
}
if ($Company) {
    $argsList += @("--company", $Company)
}
if ($CompanyCnpj) {
    $argsList += @("--company-cnpj", $CompanyCnpj)
}

& $Python @argsList
exit $LASTEXITCODE
