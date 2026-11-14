$ErrorActionPreference = "Stop"
$out = "D:\docker-export\insta-gpu-ollama-vision.tar"
$status = "D:\docker-export\save-status.txt"
$state = "D:\docker-export\build-state.json"
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
$deadline = (Get-Date).AddHours(24)
while ((Get-Date) -lt $deadline) {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
  docker image inspect insta-gpu:ollama-vision 2>$null | Out-Null
    $ready = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $prevEap
    if ($ready) {
        docker save insta-gpu:ollama-vision -o $out
        "SAVE_OK $(Get-Date -Format o)" | Set-Content $status
        Get-Item $out | Format-List Name, Length
        exit 0
    }
    Start-Sleep 45
}
"SAVE_TIMEOUT" | Set-Content $status
exit 1
