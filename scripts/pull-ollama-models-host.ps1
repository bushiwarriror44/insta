# Pull Ollama models into a host folder via a long-lived container (resumable).
param(
    [string]$Image = "insta-gpu:ollama-base",
    [string]$ModelsDir = "D:\OllamaModels",
    [string]$Container = "ov-model-pull",
    [string]$ChatModel = "qwen3:8b",
    [string]$VisionModel = "qwen2.5vl:7b",
    [int]$TimeoutSec = 1200
)

$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

docker image inspect $Image 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Missing image $Image — build Dockerfile.ollama-base first." }

docker rm -f $Container 2>$null | Out-Null
$mount = ($ModelsDir -replace '\\', '/')
docker run -d --name $Container `
    -e OLLAMA_MODELS=/models `
    -e OLLAMA_HOST=0.0.0.0:11434 `
    -v "${mount}:/models" `
    $Image `
    ollama serve | Out-Null

Write-Host "Waiting for ollama..."
$ready = $false
for ($i = 1; $i -le 90; $i++) {
    docker exec $Container curl -sf http://127.0.0.1:11434/ 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep 2
}
if (-not $ready) { throw "ollama serve did not become ready in $Container" }

function Test-ModelPresent([string]$Name) {
    $list = docker exec $Container ollama list 2>$null | Out-String
    return [bool]($list -match [regex]::Escape($Name))
}

function Pull-Model([string]$Name) {
    if (Test-ModelPresent $Name) {
        Write-Host "already present: $Name"
        return
    }
    for ($a = 1; $a -le 40; $a++) {
        Write-Host "=== pull $Name attempt $a (timeout ${TimeoutSec}s) $(Get-Date -Format o) ==="
        $p = Start-Process -FilePath "docker" -ArgumentList @("exec", $Container, "ollama", "pull", $Name) `
            -NoNewWindow -PassThru
        $finished = $p.WaitForExit($TimeoutSec * 1000)
        if (-not $finished) {
            Write-Host "timeout — killing docker exec pid $($p.Id)"
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
            docker exec $Container sh -c "pkill -9 -f 'ollama pull' 2>/dev/null || true" | Out-Null
        } else {
            Write-Host "pull process exit=$($p.ExitCode)"
        }
        if (Test-ModelPresent $Name) {
            Write-Host "OK: $Name"
            return
        }
        Start-Sleep 8
    }
    throw "Failed to pull $Name after retries"
}

Pull-Model $ChatModel
Pull-Model $VisionModel
Write-Host "Models ready in $ModelsDir"
docker exec $Container ollama list
Get-ChildItem $ModelsDir -Recurse -File -ErrorAction SilentlyContinue |
    Measure-Object -Property Length -Sum |
    ForEach-Object { "host models bytes=$($_.Sum) files=$($_.Count)" }
