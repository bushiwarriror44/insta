"""Token-gated HTTP download of generate_server.py for Salad startup scripts."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import get_settings
from app.services.salad_gpu_patch import generate_server_source_path

router = APIRouter(tags=["salad-gpu-patch"])


@router.get("/api/salad-gpu/generate_server.py", include_in_schema=False)
def download_generate_server(token: str = Query(default="")) -> FileResponse:
    settings = get_settings()
    expected = (settings.salad_gpu_patch_token or "").strip()
    if not expected or token != expected:
        raise HTTPException(status_code=404, detail="Not Found")
    path = generate_server_source_path()
    if not path.is_file():
        raise HTTPException(status_code=503, detail="generate_server.py missing on panel host")
    return FileResponse(path, media_type="text/x-python", filename="generate_server.py")
