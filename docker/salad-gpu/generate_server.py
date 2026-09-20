"""HTTP that the panel posts to as WAN_BASE_URL (prompt → mp4)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

WAN_DIR = Path(os.environ.get("WAN_DIR", "/opt/wan"))
WAN_CKPT = Path(os.environ.get("WAN_CKPT", "/opt/wan/Wan2.1-T2V-1.3B"))
lock = threading.Lock()
app = FastAPI()


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


@app.post("/")
@app.post("/generate")
def generate(body: Request) -> FileResponse:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "prompt is empty")
    script = WAN_DIR / "generate.py"
    if not script.is_file() or not WAN_CKPT.is_dir():
        raise HTTPException(503, "Wan weights are missing in this image")
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "GPU already rendering")
    work = Path(tempfile.mkdtemp(prefix="wan-"))
    out = work / "clip.mp4"
    cmd = [
        "python",
        str(script),
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
    try:
        ran = subprocess.run(
            cmd,
            cwd=str(WAN_DIR),
            capture_output=True,
            text=True,
            timeout=840,
            check=False,
        )
        if ran.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
            detail = (ran.stderr or ran.stdout or "wan failed")[-1500:]
            raise HTTPException(500, detail)
        return FileResponse(
            out,
            media_type="video/mp4",
            filename="clip.mp4",
            background=_Cleanup(work),
        )
    except HTTPException:
        _Cleanup(work)()
        raise
    except subprocess.TimeoutExpired as exc:
        _Cleanup(work)()
        raise HTTPException(504, "wan timed out") from exc
    finally:
        lock.release()


class _Cleanup:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def __call__(self) -> None:
        for path in self.folder.glob("*"):
            try:
                path.unlink()
            except OSError:
                pass
        try:
            self.folder.rmdir()
        except OSError:
            pass
