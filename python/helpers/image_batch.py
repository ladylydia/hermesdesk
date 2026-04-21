"""Lightweight image ops when Pillow is available; otherwise stub."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def run(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "info").lower()
    folder = str(args.get("folder") or ".").strip() or "."
    ws = Path(os.environ.get("HERMESDESK_WORKSPACE", ".")).resolve()
    root = (ws / folder).resolve()
    try:
        root.relative_to(ws)
    except ValueError:
        return {"ok": False, "error": "folder must stay inside the workspace"}
    if not root.is_dir():
        return {"ok": False, "error": f"not a directory: {root}"}

    try:
        from PIL import Image  # type: ignore
    except Exception:
        return {
            "ok": False,
            "skipped": True,
            "reason": "Pillow is not installed in this HermesDesk bundle; image_batch is a no-op.",
        }

    if action == "info":
        exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
        files = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in exts]
        return {"ok": True, "action": "info", "count": len(files), "folder": str(root.relative_to(ws))}

    if action != "thumbnail":
        return {"ok": False, "error": f"unknown action {action!r}; try 'info' or 'thumbnail'"}

    max_size = int(args.get("max_size") or 256)
    out_dir = root / "_thumbs"
    if not bool(args.get("dry_run")):
        out_dir.mkdir(parents=True, exist_ok=True)
    processed = []
    for p in sorted(root.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        target = out_dir / (p.stem + "_thumb.jpg")
        if bool(args.get("dry_run")):
            processed.append(str(p.relative_to(ws)))
            continue
        with Image.open(p) as im:
            im.thumbnail((max_size, max_size))
            rgb = im.convert("RGB")
            rgb.save(target, "JPEG", quality=85)
        processed.append(str(target.relative_to(ws)))
    return {"ok": True, "action": "thumbnail", "written": processed, "dry_run": bool(args.get("dry_run"))}
