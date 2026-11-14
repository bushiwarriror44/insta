# Remove all Docker data except image insta-gpu:ollama-vision. Requires running Docker daemon.
$ErrorActionPreference = "Stop"
$Keep = "insta-gpu:ollama-vision"

$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$info = docker info 2>&1 | Out-String
$ErrorActionPreference = $prevEap
if ($info -notmatch "Server Version") {
    throw "Docker daemon is not running. Free space on D: and start Docker Desktop first."
}

docker image inspect $Keep 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Image not found: $Keep (build or load it before cleanup)." }

# Pin image so prune never drops it
$pin = "insta-gpu-keep-pin"
docker rm -f $pin 2>$null | Out-Null
docker create --name $pin $Keep | Out-Null

Write-Host "Stopping other containers..."
docker ps -q | ForEach-Object {
    if ((docker inspect -f '{{.Name}}' $_) -ne "/$pin") {
        docker stop $_ 2>$null | Out-Null
    }
}

Write-Host "Removing containers (except pin)..."
docker ps -aq | ForEach-Object {
    if ((docker inspect -f '{{.Name}}' $_) -ne "/$pin") {
        docker rm -f $_ 2>$null | Out-Null
    }
}

Write-Host "Removing other images..."
docker images --format "{{.Repository}}:{{.Tag}} {{.ID}}" | ForEach-Object {
    $parts = $_ -split " ", 2
    $ref = $parts[0]
    $id = $parts[1]
    if ($ref -eq $Keep) { return }
    docker rmi -f $id 2>$null | Out-Null
}

Write-Host "Build cache..."
docker builder prune -af

Write-Host "Unused networks..."
docker network prune -f

Write-Host "Unused volumes (not tied to $Keep)..."
docker volume prune -f

docker rm -f $pin 2>$null | Out-Null

Write-Host "---"
docker images
docker system df
Write-Host "Kept image: $Keep"
