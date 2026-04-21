"""Summarize text from PDF files in a workspace folder (non-recursive, capped)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def run(args: dict[str, Any]) -> dict[str, Any]:
    folder = str(args.get("folder") or ".").strip() or "."
    max_files = max(1, min(50, int(args.get("max_files") or 10)))
    max_pages = max(1, min(20, int(args.get("max_pages_per_file") or 3)))
    preview_chars = max(80, min(2000, int(args.get("preview_chars") or 480)))

    ws = Path(os.environ.get("HERMESDESK_WORKSPACE", ".")).resolve()
    root = (ws / folder).resolve()
    try:
        root.relative_to(ws)
    except ValueError:
        return {"ok": False, "error": "folder must stay inside the workspace"}
    if not root.is_dir():
        return {"ok": False, "error": f"not a directory: {root}"}

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover
        return {
            "ok": False,
            "skipped": True,
            "reason": f"pypdf not available in this bundle: {exc}",
        }

    pdfs = sorted(
        p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
    )
    if not pdfs:
        return {"ok": True, "folder": str(root.relative_to(ws)) if root != ws else ".", "files": []}

    out: list[dict[str, Any]] = []
    for p in pdfs[:max_files]:
        try:
            reader = PdfReader(str(p))
            n_pages = len(reader.pages)
            take = min(max_pages, n_pages)
            chunks: list[str] = []
            for i in range(take):
                try:
                    t = reader.pages[i].extract_text() or ""
                except Exception:
                    t = ""
                if t.strip():
                    chunks.append(t.strip())
            blob = "\n\n".join(chunks).strip()
            preview = blob[:preview_chars] + ("…" if len(blob) > preview_chars else "")
            out.append(
                {
                    "name": p.name,
                    "path": str(p.relative_to(ws)),
                    "pages_total": n_pages,
                    "pages_read": take,
                    "chars": len(blob),
                    "preview": preview,
                }
            )
        except Exception as e:
            out.append({"name": p.name, "path": str(p.relative_to(ws)), "error": str(e)})

    return {"ok": True, "folder": str(root.relative_to(ws)) if root != ws else ".", "files": out}
