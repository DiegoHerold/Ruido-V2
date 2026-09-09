$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ProfileRoot = Join-Path $ProjectRoot ".chrome-automation-profile"
$ProfileName = "Default"
$localState = Join-Path $ProfileRoot "Local State"
if (Test-Path -LiteralPath $localState) {
    try {
        $json = Get-Content -Raw -LiteralPath $localState | ConvertFrom-Json
        if ($json.profile.last_used) {
            $ProfileName = $json.profile.last_used
        }
    }
    catch {
        $ProfileName = "Default"
    }
}

$chromeCandidates = @(
    "$env:PROGRAMFILES\Google\Chrome\Application\chrome.exe",
    "${env:PROGRAMFILES(X86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$Chrome = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Chrome) {
    Write-Host "Google Chrome nao encontrado nos caminhos padrao." -ForegroundColor Red
    exit 2
}

New-Item -ItemType Directory -Force -Path $ProfileRoot | Out-Null

Write-Host "Abrindo perfil da automacao: $ProfileRoot"
Write-Host "Instale/ative a extensao Redtrust nesta janela. Depois feche o Chrome e rode .\run.ps1"

Start-Process -FilePath $Chrome -ArgumentList @(
    "--user-data-dir=$ProfileRoot",
    "--profile-directory=$ProfileName",
    "--start-maximized",
    "chrome://extensions"
)
