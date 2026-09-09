$ErrorActionPreference = "SilentlyContinue"
$ChromeRoot = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data"

if (-not (Test-Path -LiteralPath $ChromeRoot)) {
    Write-Host "Chrome User Data nao encontrado: $ChromeRoot"
    exit 2
}

Get-ChildItem -LiteralPath $ChromeRoot -Directory | ForEach-Object {
    $profile = $_
    $extensionsRoot = Join-Path $profile.FullName "Extensions"
    if (-not (Test-Path -LiteralPath $extensionsRoot)) {
        return
    }

    Get-ChildItem -LiteralPath $extensionsRoot -Recurse -Filter manifest.json | ForEach-Object {
        $manifestPath = $_.FullName
        try {
            $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
        }
        catch {
            return
        }

        $extensionPath = Split-Path -Parent $manifestPath
        [PSCustomObject]@{
            Profile = $profile.Name
            Name = $manifest.name
            Description = $manifest.description
            Path = $extensionPath
        }
    }
} | Sort-Object Profile,Name | Format-Table -AutoSize -Wrap
