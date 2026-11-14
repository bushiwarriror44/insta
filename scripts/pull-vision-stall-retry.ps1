# Pull one Ollama model with stall detection (restart if disk/progress idle).
param(
    [string]$Image = "insta-gpu:ollama-base",
    [string]$ModelsDir = "D:\OllamaModels",
    [string]$Container = "ov-model-pull",
    [string]$Model = "qwen2.5vl:7b",
    [int]$StallSeconds = 180,
    [int]$MaxAttempts = 40
)

$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

function Get-ModelsBytes {
    $m = Get-ChildItem $ModelsDir -Recurse -File -EA SilentlyContinue | Measure-Object Length -Sum
    if ($null -eq $m.Sum) { return 0 }
    return [int64]$m.Sum
}

function Test-ModelPresent {
    $list = docker exec $Container ollama list 2>$null | Out-String
    return [bool]($list -match [regex]::Escape($Model))
}

function Start-PullContainer {
    docker rm -f $Container 2>$null | Out-Null
    $mount = ($ModelsDir -replace '\\', '/')
    docker run -d --name $Container `
        -e OLLAMA_MODELS=/models `
        -e OLLAMA_HOST=0.0.0.0:11434 `
        -v "${mount}:/models" `
        $Image `
        ollama serve | Out-Null
    for ($i = 1; $i -le 90; $i++) {
        docker exec $Container curl -sf http://127.0.0.1:11434/ 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep 2
    }
    throw "ollama serve not ready"
}

Start-PullContainer
if (Test-ModelPresent) {
    Write-Host "already present: $Model"
    docker exec $Container ollama list
    exit 0
}

# Confirm chat model survived remount
docker exec $Container ollama list

for ($a = 1; $a -le $MaxAttempts; $a++) {
    Write-Host "=== $Model attempt $a / $MaxAttempts $(Get-Date -Format o) ==="
    docker exec $Container sh -c "pkill -9 -f 'ollama pull' 2>/dev/null || true" | Out-Null
    Start-Sleep 2

    $p = Start-Process -FilePath "docker" -ArgumentList @("exec", $Container, "ollama", "pull", $Model) `
        -NoNewWindow -PassThru -RedirectStandardOutput "D:\docker-export\vision-pull-out.log" `
        -RedirectStandardError "D:\docker-export\vision-pull-err.log"

    $lastBytes = Get-ModelsBytes
    $lastGrowth = Get-Date
    while (-not $p.HasExited) {
        Start-Sleep 20
        if (Test-ModelPresent) {
            Write-Host "OK: $Model"
            try { Stop-Process -Id $p.Id -Force -EA SilentlyContinue } catch {}
            docker exec $Container ollama list
            "Models ready"
            exit 0
        }
        $bytes = Get-ModelsBytes
        $gb = [math]::Round($bytes / 1GB, 2)
        if ($bytes -gt $lastBytes + 1MB) {
            $lastBytes = $bytes
            $lastGrowth = Get-Date
            Write-Host "$(Get-Date -Format HH:mm:ss) growing ${gb}GB (+$([math]::Round(($bytes-$lastBytes)/1MB,1)) check)"
        } else {
            $idle = [int]((Get-Date) - $lastGrowth).TotalSeconds
            Write-Host "$(Get-Date -Format HH:mm:ss) idle ${idle}s size=${gb}GB pid=$($p.Id)"
            if ($idle -ge $StallSeconds) {
                Write-Host "STALL — kill pull and retry"
                try { Stop-Process -Id $p.Id -Force -EA SilentlyContinue } catch {}
                docker exec $Container sh -c "pkill -9 -f 'ollama pull' 2>/dev/null || true" | Out-Null
                # bounce ollama serve occasionally after repeated stalls
                if (($a % 3) -eq 0) {
                    Write-Host "restarting container..."
                    Start-PullContainer
                }
                break
            }
        }
    }

    if ($p.HasExited -and (Test-ModelPresent)) {
        Write-Host "OK: $Model"
        docker exec $Container ollama list
        "Models ready"
        exit 0
    }
    Start-Sleep 5
}

throw "Failed to pull $Model after $MaxAttempts stall-retries"
