# Move Docker Desktop WSL data disk (docker-desktop-data) to D:\DockerDesktop.
# Preserves images/build cache inside the exported vhdx. Requires Docker stopped.
param(
    [string]$TargetRoot = "D:\DockerDesktop",
    [string]$ExportTar = "D:\docker-export\docker-desktop-data-export.tar",
    [int]$DiskSizeMiB = 184320
)

$ErrorActionPreference = "Stop"
$settings = Join-Path $env:APPDATA "Docker\settings.json"

function Stop-DockerDesktop {
    @("Docker Desktop", "com.docker.backend", "com.docker.proxy", "docker-sandbox") | ForEach-Object {
        Stop-Process -Name $_ -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
    wsl --shutdown 2>$null | Out-Null
    Start-Sleep -Seconds 2
}

function Get-WslListText {
    return ((wsl -l -v 2>&1) | ForEach-Object { $_ }) -join "`n" -replace "`0", ""
}
function Test-WslDistro($name) {
    return (Get-WslListText) -match [regex]::Escape($name)
}

New-Item -ItemType Directory -Force -Path $TargetRoot, (Split-Path $ExportTar) | Out-Null

Stop-DockerDesktop

$imported = $false
if (-not (Test-WslDistro "docker-desktop-data")) {
    Write-Warning "docker-desktop-data WSL distro not found; only updating settings."
} else {
    if (Test-Path $ExportTar) {
        Write-Host "Reusing existing export: $ExportTar"
    } else {
        Write-Host "Exporting docker-desktop-data (may take 15-60 min)..."
        wsl --export docker-desktop-data $ExportTar
        if ($LASTEXITCODE -ne 0) { throw "wsl --export failed" }
    }
    Write-Host "Unregistering docker-desktop-data..."
    wsl --unregister docker-desktop-data
    if ($LASTEXITCODE -ne 0) { throw "wsl --unregister failed" }
    $importDir = Join-Path $TargetRoot "data"
    if (Test-Path $importDir) {
        Remove-Item -Recurse -Force $importDir
    }
    New-Item -ItemType Directory -Force -Path $importDir | Out-Null
    Write-Host "Importing to $importDir ..."
    wsl --import docker-desktop-data $importDir $ExportTar --version 2
    if ($LASTEXITCODE -ne 0) { throw "wsl --import failed" }
    $imported = $true
}

if (-not (Test-Path $settings)) { throw "Missing $settings" }
$escJson = $TargetRoot.Replace('\', '\\')
$content = Get-Content $settings -Raw
if ($content -match '"customWslDistroDir"') {
    $content = $content -replace '"customWslDistroDir"\s*:\s*"[^"]*"', ('"customWslDistroDir": "' + $escJson + '"')
} else {
    $content = $content -replace '("wslEngineEnabled"\s*:\s*true)', ('"customWslDistroDir": "' + $escJson + '",' + "`r`n  `$1")
}
$content = $content -replace '"diskSizeMiB"\s*:\s*\d+', "`"diskSizeMiB`": $DiskSizeMiB"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($settings, $content, $utf8NoBom)

$oldVhdx = Join-Path $env:LOCALAPPDATA "Docker\wsl\data\ext4.vhdx"
if ($imported -and (Test-Path $oldVhdx)) {
    $bak = "$oldVhdx.migrated-$((Get-Date -Format 'yyyyMMddHHmmss'))"
    Write-Host "Removing stale C: vhdx after import -> $bak"
    Rename-Item -Path $oldVhdx -NewName (Split-Path $bak -Leaf) -Force
}

$dd = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
if (Test-Path $dd) {
    Write-Host "Starting Docker Desktop..."
    Start-Process $dd
    $deadline = (Get-Date).AddMinutes(20)
    $ready = $false
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    while ((Get-Date) -lt $deadline) {
        docker info 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 8
    }
    $ErrorActionPreference = $prevEap
    if (-not $ready) { throw "Docker did not become ready in time" }
    Write-Host "Docker is up."
    Start-Process powershell -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "resume-ollama-vision-build.ps1")
    ) -WindowStyle Hidden
    Start-Process powershell -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "wait-and-save-ollama-vision.ps1")
    ) -WindowStyle Hidden
} else {
    Write-Host "Start Docker Desktop manually, then run resume-ollama-vision-build.ps1"
}
Write-Host "Optional: remove $ExportTar after verify to free space on D:"
