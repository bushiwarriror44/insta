# Single docker build on D: context; logs on D:. Run after Docker is up.
$ErrorActionPreference = "Continue"
$runLog = "D:\docker-export\build-ollama-vision-run.log"
$src = "D:\insta-build\docker\salad-gpu"
New-Item -ItemType Directory -Force -Path (Split-Path $runLog), $src | Out-Null
$repoGpu = Join-Path (Split-Path $PSScriptRoot -Parent) "docker\salad-gpu"
Copy-Item -Force (Join-Path $repoGpu "*") -Destination $src
docker buildx use default 2>$null | Out-Null
$env:DOCKER_BUILDKIT = "1"
Push-Location $src
try {
    Add-Content -Path $runLog -Value "`n===== resume $(Get-Date -Format o) ====="
    docker build -f Dockerfile.ollama-only `
        --build-arg AGENT_MODEL=qwen3:8b `
        --build-arg AGENT_VISION_MODEL=qwen2.5vl:7b `
        -t insta-gpu:ollama-vision `
        --progress=plain `
        . 2>&1 | Tee-Object -FilePath $runLog -Append
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
