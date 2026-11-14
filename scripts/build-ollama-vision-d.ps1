# Resumable build: insta-gpu:ollama-vision on D: with persistent BuildKit cache + retries.
param(
    [int]$MaxAttempts = 15,
    [string]$SrcRoot = "D:\insta-build\docker\salad-gpu",
    [string]$Log = "D:\docker-export\build-ollama-vision.log",
    [string]$StateFile = "D:\docker-export\build-state.json",
    [string]$CacheDir = "D:\docker-cache\buildkit",
    [string]$BuilderName = "insta-d",
    [string]$ChatModel = "qwen3:8b",
    [string]$VisionModel = "qwen2.5vl:7b"
)

$ErrorActionPreference = "Continue"
$tar = "D:\docker-export\insta-gpu-ollama-vision.tar"
New-Item -ItemType Directory -Force -Path (Split-Path $SrcRoot), (Split-Path $Log), $CacheDir | Out-Null

function Write-BuildState {
    param([hashtable]$Fields)
    $state = @{
        updated_at = (Get-Date -Format o)
        src        = $SrcRoot
        chat_model = $ChatModel
        vision_model = $VisionModel
        cache_dir  = $CacheDir
        log        = $Log
    }
    foreach ($k in $Fields.Keys) { $state[$k] = $Fields[$k] }
    $state | ConvertTo-Json -Depth 4 | Set-Content -Path $StateFile -Encoding UTF8
}

function Ensure-BuildxBuilder {
    docker buildx inspect $BuilderName 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        docker buildx create --name $BuilderName --driver docker-container --use | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-BuildState @{ status = "builder_fallback"; note = "using default docker driver" }
            docker buildx use default 2>$null | Out-Null
            return $false
        }
    } else {
        docker buildx use $BuilderName | Out-Null
    }
    return $true
}

function Invoke-ResumableBuild {
    param([bool]$UseBuildxCache)

    $args = @(
        "buildx", "build",
        "-f", "Dockerfile.ollama-only",
        "--build-arg", "AGENT_MODEL=$ChatModel",
        "--build-arg", "AGENT_VISION_MODEL=$VisionModel",
        "-t", "insta-gpu:ollama-vision",
        "--progress=plain"
    )
    if ($UseBuildxCache) {
        $args += @(
            "--cache-to", "type=local,dest=$CacheDir,mode=max",
            "--cache-from", "type=local,src=$CacheDir"
        )
    }
    $args += @("--load", ".")

    $session = "===== attempt $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="
    Add-Content -Path $Log -Value $session
    & docker @args 2>&1 | Tee-Object -FilePath $Log -Append
    return $LASTEXITCODE
}

$env:DOCKER_BUILDKIT = "1"
$useCache = Ensure-BuildxBuilder
Write-BuildState @{
    status     = "started"
    attempt    = 0
    buildx     = $useCache
    max_attempts = $MaxAttempts
}

Push-Location $SrcRoot
try {
    $exit = 1
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        Write-BuildState @{
            status  = "building"
            attempt = $attempt
            last_error = $null
        }
        $exit = Invoke-ResumableBuild -UseBuildxCache:$useCache
        if ($exit -eq 0) {
            Write-BuildState @{ status = "built"; attempt = $attempt; exit_code = 0 }
            break
        }
        Write-BuildState @{
            status     = "failed_attempt"
            attempt    = $attempt
            exit_code  = $exit
            last_error = "docker build exited $exit; cache at $CacheDir — retry without --no-cache"
        }
        Start-Sleep -Seconds ([Math]::Min(60, 10 * $attempt))
    }
    if ($exit -ne 0) {
        Write-BuildState @{ status = "gave_up"; exit_code = $exit }
        Write-Error "Build failed after $MaxAttempts attempts. Log: $Log State: $StateFile"
        exit $exit
    }
    docker save insta-gpu:ollama-vision -o $tar
    Write-BuildState @{ status = "saved"; tar = $tar; exit_code = 0 }
    Get-Item $tar | Format-List Name, Length, LastWriteTime
} finally {
    Pop-Location
}
