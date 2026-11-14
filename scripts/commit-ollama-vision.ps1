# Copy host-pulled models into image filesystem and tag insta-gpu:ollama-vision.
param(
    [string]$BaseImage = "insta-gpu:ollama-base",
    [string]$ModelsDir = "D:\OllamaModels",
    [string]$OutImage = "insta-gpu:ollama-vision",
    [string]$PackContainer = "ov-model-pack"
)

$ErrorActionPreference = "Continue"
if (-not (Test-Path $ModelsDir)) { throw "Models dir missing: $ModelsDir" }

docker rm -f $PackContainer 2>$null | Out-Null
$mount = ($ModelsDir -replace '\\', '/')
$cid = docker create --name $PackContainer `
    -e OLLAMA_MODELS=/opt/ollama/models `
    -v "${mount}:/models:ro" `
    $BaseImage `
    sleep infinity 2>&1
if ($LASTEXITCODE -ne 0) { throw "docker create failed: $cid" }
docker start $PackContainer | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker start failed" }

Write-Host "Copying models into container filesystem (may take several minutes)..."
docker exec $PackContainer bash -lc "mkdir -p /opt/ollama/models && cp -a /models/. /opt/ollama/models/ && du -sh /opt/ollama/models"
if ($LASTEXITCODE -ne 0) { throw "copy models failed" }

Write-Host "Committing $OutImage ..."
docker commit `
    -c "ENV OLLAMA_MODELS=/opt/ollama/models" `
    -c "CMD [`"/opt/gpu/start.sh`"]" `
    $PackContainer $OutImage
if ($LASTEXITCODE -ne 0) { throw "docker commit failed" }

docker rm -f $PackContainer 2>$null | Out-Null
docker images $OutImage
Write-Host "Done: $OutImage"
$ErrorActionPreference = "Stop"
