"""HTTP that the panel posts to as WAN_BASE_URL (prompt → mp4).

Salad's public gateway drops a silent HTTPS response after ~100s (HTTP 524).
The panel therefore posts with ``X-Async: 1`` and polls ``GET /generate/jobs/{id}``.
A direct Wan host can still POST ``/generate`` and wait for the mp4.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

WAN_DIR = Path(os.environ.get("WAN_DIR", "/opt/wan"))
WAN_CKPT = Path(os.environ.get("WAN_CKPT", "/opt/wan/Wan2.1-T2V-1.3B"))
lock = threading.Lock()
jobs_guard = threading.Lock()
jobs: dict[str, dict[str, object]] = {}
app = FastAPI()


@app.get("/")
@app.get("/generate")
def health() -> dict[str, bool]:
    """Panel liveness probe. Does not take the GPU lock or start a render."""
    return {"ok": True}


class Request(BaseModel):
    prompt: str = Field(min_length=1, max_length=1500)
    negative_prompt: str = ""
    duration_s: float = 5
    width: int = 720
    height: int = 1280
    seed: int | None = None


def _size(width: int, height: int) -> str:
    # Wan 1.3B is 480p only. Official tags are width*height.
    if height >= width:
        return "480*832"
    return "832*480"


def _frames(duration_s: float) -> int:
    seconds = 10 if duration_s >= 7.5 else 5
    # 16 fps, 4n+1 as Wan requires.
    return 161 if seconds == 10 else 81


def _command(body: Request, out: Path) -> list[str]:
    prompt = body.prompt.strip()
    cmd = [
        "python",
        str(WAN_DIR / "generate.py"),
        "--task",
        "t2v-1.3B",
        "--size",
        _size(body.width, body.height),
        "--ckpt_dir",
        str(WAN_CKPT),
        "--frame_num",
        str(_frames(body.duration_s)),
        "--offload_model",
        "True",
        "--t5_cpu",
        "--sample_shift",
        "8",
        "--sample_guide_scale",
        "6",
        "--save_file",
        str(out),
        "--prompt",
        prompt,
    ]
    if body.seed is not None:
        cmd.extend(["--base_seed", str(int(body.seed))])
    return cmd


def _ready() -> None:
    script = WAN_DIR / "generate.py"
    if not script.is_file() or not WAN_CKPT.is_dir():
        raise HTTPException(503, "Wan weights are missing in this image")


def _run(body: Request, work: Path, out: Path) -> None:
    """Run Wan. Raises HTTPException on failure. Caller holds ``lock``."""
    try:
        ran = subprocess.run(
            _command(body, out),
            cwd=str(WAN_DIR),
            capture_output=True,
            text=True,
            timeout=840,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "wan timed out") from exc
    if ran.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        detail = (ran.stderr or ran.stdout or "wan failed")[-1500:]
        raise HTTPException(500, detail)


def _set_job(job_id: str, **fields: object) -> None:
    with jobs_guard:
        row = jobs.get(job_id)
        if row is None:
            return
        row.update(fields)


def _render_job(job_id: str, body: Request, work: Path, out: Path) -> None:
    """Background render. ``lock`` is already held by the request that queued us."""
    try:
        _set_job(job_id, status="running")
        _run(body, work, out)
        _set_job(job_id, status="done", path=str(out), work=str(work))
    except HTTPException as exc:
        _Cleanup(work)()
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        _set_job(job_id, status="failed", error=detail)
    except Exception as exc:
        _Cleanup(work)()
        _set_job(job_id, status="failed", error=str(exc)[:1500])
    finally:
        lock.release()


def _enqueue(body: Request) -> JSONResponse:
    _ready()
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "prompt is empty")
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "GPU already rendering")
    job_id = uuid.uuid4().hex
    work = Path(tempfile.mkdtemp(prefix="wan-"))
    out = work / "clip.mp4"
    with jobs_guard:
        jobs[job_id] = {"status": "queued", "error": "", "path": "", "work": str(work)}
    threading.Thread(
        target=_render_job,
        args=(job_id, body, work, out),
        name=f"wan-{job_id[:8]}",
        daemon=True,
    ).start()
    return JSONResponse({"job_id": job_id, "status": "queued"}, status_code=202)


def _wants_async(header: str | None, query: str | None) -> bool:
    return (header or "").strip() == "1" or (query or "").strip() == "1"


@app.post("/", response_model=None)
@app.post("/generate", response_model=None)
def generate(
    body: Request,
    x_async: str | None = Header(default=None, alias="X-Async"),
    async_query: str | None = Query(default=None, alias="async"),
) -> FileResponse | JSONResponse:
    if _wants_async(x_async, async_query):
        return _enqueue(body)
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "prompt is empty")
    _ready()
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "GPU already rendering")
    work = Path(tempfile.mkdtemp(prefix="wan-"))
    out = work / "clip.mp4"
    try:
        _run(body, work, out)
        return FileResponse(
            out,
            media_type="video/mp4",
            filename="clip.mp4",
            background=BackgroundTask(_Cleanup(work)),
        )
    except HTTPException:
        _Cleanup(work)()
        raise
    finally:
        lock.release()


@app.get("/generate/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, str]:
    with jobs_guard:
        row = jobs.get(job_id)
        if row is None:
            raise HTTPException(404, "job not found")
        return {
            "job_id": job_id,
            "status": str(row.get("status") or ""),
            "error": str(row.get("error") or ""),
        }


@app.get("/generate/jobs/{job_id}/file")
def job_file(job_id: str) -> FileResponse:
    with jobs_guard:
        row = jobs.get(job_id)
        if row is None:
            raise HTTPException(404, "job not found")
        status = str(row.get("status") or "")
        path = Path(str(row.get("path") or ""))
        work = Path(str(row.get("work") or "")) if row.get("work") else None
    if status != "done" or not path.is_file():
        raise HTTPException(409, "job is not ready")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename="clip.mp4",
        background=BackgroundTask(_DropJob(job_id, work)),
    )


class _Cleanup:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def __call__(self) -> None:
        if not self.folder.exists():
            return
        for path in self.folder.glob("*"):
            try:
                path.unlink()
            except OSError:
                pass
        try:
            self.folder.rmdir()
        except OSError:
            pass


class _DropJob:
    def __init__(self, job_id: str, folder: Path | None) -> None:
        self.job_id = job_id
        self.folder = folder

    def __call__(self) -> None:
        with jobs_guard:
            jobs.pop(self.job_id, None)
        if self.folder is not None:
            _Cleanup(self.folder)()
