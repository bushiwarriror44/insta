# Run in elevated PowerShell after Docker is stopped. Reclaims sparse space in ext4.vhdx on D:.
$ErrorActionPreference = "Stop"
$vhd = "D:\DockerDesktop\data\ext4.vhdx"
if (-not (Test-Path $vhd)) { throw "Not found: $vhd" }

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script as Administrator."
}

Write-Host "Stopping WSL / Docker..."
wsl --shutdown
Start-Sleep -Seconds 3

Write-Host "Compacting $vhd (may take several minutes)..."
Optimize-VHD -Path $vhd -Mode Full

$len = (Get-Item $vhd).Length
Write-Host ("VHDX size: {0:N2} GB" -f ($len / 1GB))
fsutil volume diskfree D:
