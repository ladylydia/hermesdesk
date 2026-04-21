"""Organize loose files in a workspace folder by extension into subfolders."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def _categories() -> dict[str, str]:
    return {
        ".jpg": "images",
        ".jpeg": "images",
        ".png": "images",
        ".gif": "images",
        ".webp": "images",
        ".bmp": "images",
        ".svg": "images",
        ".pdf": "documents",
        ".doc": "documents",
        ".docx": "documents",
        ".xls": "documents",
        ".xlsx": "documents",
        ".csv": "documents",
        ".txt": "documents",
        ".md": "documents",
        ".json": "data",
        ".yaml": "data",
        ".yml": "data",
        ".zip": "archives",
        ".7z": "archives",
        ".rar": "archives",
    }


def run(args: dict[str, Any]) -> dict[str, Any]:
    """
    Args:
        folder: optional relative path under workspace (default ``.``).
        dry_run: if true, only report planned moves.
    """
    ws = Path(os.environ.get("HERMESDESK_WORKSPACE", ".")).resolve()
    rel = str(args.get("folder") or args.get("target") or ".").strip() or "."
    root = (ws / rel).resolve()
    try:
        root.relative_to(ws)
    except ValueError:
        return {"ok": False, "error": "folder must stay inside the workspace"}
    if not root.is_dir():
        return {"ok": False, "error": f"not a directory: {root}"}

    dry = bool(args.get("dry_run"))
    cats = _categories()
    planned: list[dict[str, str]] = []
    done: list[dict[str, str]] = []

    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        ext = entry.suffix.lower()
        bucket = cats.get(ext, "other")
        dest_dir = root / bucket
        dest = dest_dir / entry.name
        if dest.resolve() == entry.resolve():
            continue
        if dest.exists():
            planned.append(
                {
                    "skip": entry.name,
                    "reason": f"target exists in {bucket}/",
                }
            )
            continue
        planned.append({"from": str(entry.relative_to(ws)), "to": str(dest.relative_to(ws))})
        if not dry:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(dest))
            done.append({"from": str(entry.relative_to(ws)), "to": str(dest.relative_to(ws))})

    return {
        "ok": True,
        "workspace": str(ws),
        "folder": str(root.relative_to(ws)) if root != ws else ".",
        "dry_run": dry,
        "planned": planned,
        "moved": done if not dry else [],
    }
