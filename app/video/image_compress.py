"""Server-side image compression for library uploads."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def compress_image_file(
    path: Path,
    *,
    max_edge: int = 1920,
    quality: int = 85,
) -> Path:
    """Resize and re-encode ``path`` as JPEG; return the final path.

    Converts RGBA/P/LA to RGB on a white background. Renames non-``.jpg``
    sources to ``.jpg`` (deletes the original after a successful write).
    """
    if max_edge < 1:
        raise ValueError("max_edge должен быть >= 1")
    if not 1 <= quality <= 95:
        raise ValueError("quality должен быть в диапазоне 1..95")

    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        else:
            img = img.convert("RGB")

        w, h = img.size
        longest = max(w, h)
        if longest > max_edge:
            scale = max_edge / float(longest)
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        out = path if path.suffix.lower() in {".jpg", ".jpeg"} else path.with_suffix(".jpg")
        if out != path and out.exists():
            stem = out.stem
            parent = out.parent
            n = 1
            while True:
                candidate = parent / f"{stem}-{n}.jpg"
                if not candidate.exists():
                    out = candidate
                    break
                n += 1

        img.save(out, format="JPEG", quality=quality, optimize=True)

    if out != path and path.exists():
        path.unlink(missing_ok=True)
    return out
