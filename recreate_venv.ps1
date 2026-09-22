#!/usr/bin/env pwsh
# recreate_venv.ps1 — Recria o .venv e instala todas as dependencias do projeto.

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir    = Join-Path $ProjectRoot ".venv"

# ---------------------------------------------------------------------------
# 1. Localiza um Python 3.11+ disponivel no sistema
# ---------------------------------------------------------------------------
function Find-SystemPython {
    $candidates = @(
        "python",
        "py",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe"
    )
    foreach ($c in $candidates) {
        try {
            $out = & $c --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $out -match "Python 3\.(1[1-9]|[2-9]\d)") {
                return $c
            }
        } catch { }
    }
    return $null
}

$SystemPython = Find-SystemPython
if (-not $SystemPython) {
    Write-Host ""
    Write-Host "ERRO: Python 3.11+ nao foi encontrado no sistema." -ForegroundColor Red
    Write-Host "Instale Python 3.11 ou superior e marque 'Add python.exe to PATH'."
    exit 2
}

Write-Host "Python do sistema : $SystemPython" -ForegroundColor Cyan
Write-Host "Versao            : $(& $SystemPython --version 2>&1)" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 2. Remove o .venv antigo (se existir)
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $VenvDir) {
    Write-Host ""
    Write-Host "Removendo .venv antigo..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force -LiteralPath $VenvDir
    Write-Host "Removido." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 3. Cria novo .venv
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Criando novo .venv..." -ForegroundColor Yellow
& $SystemPython -m venv "$VenvDir"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO ao criar o venv." -ForegroundColor Red
    exit 1
}
Write-Host "Venv criado." -ForegroundColor Green

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"

# ---------------------------------------------------------------------------
# 4. Atualiza pip e setuptools dentro do venv
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Atualizando pip e setuptools..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO ao atualizar pip." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 5. Instala dependencias do requirements.txt
# ---------------------------------------------------------------------------
$ReqFile = Join-Path $ProjectRoot "requirements.txt"
Write-Host ""
Write-Host "Instalando dependencias de '$ReqFile'..." -ForegroundColor Yellow
& $VenvPython -m pip install -r "$ReqFile"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO ao instalar dependencias." -ForegroundColor Red
    exit 1
}
Write-Host "Dependencias instaladas." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 6. Instala o pacote local em modo editavel (se houver pyproject.toml)
# ---------------------------------------------------------------------------
$PyProject = Join-Path $ProjectRoot "pyproject.toml"
if (Test-Path -LiteralPath $PyProject) {
    Write-Host ""
    Write-Host "Instalando pacote local (editable)..." -ForegroundColor Yellow
    & $VenvPython -m pip install -e "$ProjectRoot"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "AVISO: instalacao em modo editavel falhou (nao critico)." -ForegroundColor Yellow
    } else {
        Write-Host "Pacote local instalado." -ForegroundColor Green
    }
}

# ---------------------------------------------------------------------------
# 7. Instala o browser do Playwright (Chrome)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Instalando browser Playwright (chrome)..." -ForegroundColor Yellow
& $VenvPython -m playwright install chrome
if ($LASTEXITCODE -ne 0) {
    Write-Host "AVISO: falha ao instalar browser Playwright." -ForegroundColor Yellow
} else {
    Write-Host "Browser Playwright instalado." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 8. Resumo
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " Venv recriado com sucesso!" -ForegroundColor Green
Write-Host " Python : $VenvPython"
Write-Host " Para usar: .\.venv\Scripts\Activate.ps1"
Write-Host " Ou rode  : .\run.ps1"
Write-Host "================================================" -ForegroundColor Cyan
