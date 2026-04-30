#!/usr/bin/env python3
"""
One-shot probe: call iLink ``get_bot_qrcode`` once (no polling, no login).

Use this to validate that the **same interpreter + sys.path** you ship in HermesDesk
can import ``gateway.platforms.weixin`` and reach ``ilinkai.weixin.qq.com``.

Run from repo root (dev submodule on path):

  PowerShell:
    $env:PYTHONPATH = (Resolve-Path .\\hermes)
    py -3.11 python\\tools\\weixin_ilink_qr_probe.py

Bundled runtime (after ``.\\python\\build_bundle.ps1``), from ``python\\dist\\runtime``:

  .\\python\\python.exe ..\\..\\..\\tools\\weixin_ilink_qr_probe.py

  Or set an explicit Hermes tree root (folder that **contains** ``gateway``):

    $env:HERMESDESK_WEIXIN_PROBE_ROOT = (Resolve-Path .\\hermes)
    py -3.11 ..\\..\\..\\tools\\weixin_ilink_qr_probe.py

Optional: ``--json`` prints raw JSON only (for piping).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _ensure_hermes_on_path() -> None:
    env = os.environ.get("HERMESDESK_WEIXIN_PROBE_ROOT", "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    repo = here.parents[2]
    candidates.append(repo / "hermes")
    for p in candidates:
        if (p / "gateway").is_dir():
            root = str(p.resolve())
            if root not in sys.path:
                sys.path.insert(0, root)
            return
    print(
        "ERROR: could not find Hermes ``gateway`` package. Set HERMESDESK_WEIXIN_PROBE_ROOT "
        "to the directory that contains ``gateway`` (usually the ``hermes`` submodule root).",
        file=sys.stderr,
    )
    sys.exit(2)


async def _run(*, json_only: bool) -> int:
    _ensure_hermes_on_path()
    try:
        from gateway.platforms.weixin import (  # type: ignore[import-not-found]
            EP_GET_BOT_QR,
            ILINK_BASE_URL,
            _api_get,
            _make_ssl_connector,
        )
    except ImportError as e:
        print(f"ERROR: import failed: {e}", file=sys.stderr)
        print(
            "HINT: use the bundled interpreter from python\\dist\\runtime\\python\\python.exe "
            "after .\\python\\build_bundle.ps1 (dev-only ``PYTHONPATH=hermes`` often misses yaml, etc.).",
            file=sys.stderr,
        )
        return 1

    try:
        import aiohttp
    except ImportError:
        print("ERROR: aiohttp is required (same as Hermes weixin adapter).", file=sys.stderr)
        return 1

    bot_type = os.environ.get("HERMESDESK_WEIXIN_BOT_TYPE", "3").strip() or "3"
    endpoint = f"{EP_GET_BOT_QR}?bot_type={bot_type}"

    async with aiohttp.ClientSession(trust_env=True, connector=_make_ssl_connector()) as session:
        data = await _api_get(
            session,
            base_url=ILINK_BASE_URL,
            endpoint=endpoint,
            timeout_ms=35_000,
        )

    if json_only:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    qrcode = data.get("qrcode")
    img = data.get("qrcode_img_content")
    qrcode_s = qrcode if isinstance(qrcode, str) else json.dumps(qrcode, ensure_ascii=False)
    img_s = img if isinstance(img, str) else json.dumps(img, ensure_ascii=False)

    def _kind(s: str) -> str:
        t = (s or "").strip()
        if not t:
            return "(empty)"
        if t.startswith("http://") or t.startswith("https://"):
            return "http(s) URL string"
        if t.startswith("data:"):
            return "data: URL (likely base64-inlined)"
        if len(t) < 200 and all(c in "0123456789abcdefABCDEF" for c in t):
            return "hex-like token"
        return f"other string (len={len(t)}, prefix={t[:48]!r}…)"

    print("iLink get_bot_qrcode — field summary (see docs/gateway-route-c-weixin-validation.md)")
    print(f"  endpoint: {ILINK_BASE_URL.rstrip('/')}/{endpoint}")
    print(f"  qrcode:           {_kind(qrcode_s)}")
    print(f"  qrcode_img_content: {_kind(img_s)}")
    print()
    print("Hermes ``qr_login`` uses:")
    print("  - ``qrcode`` as opaque token for get_qrcode_status polling.")
    print("  - ``qrcode_img_content`` when non-empty as the **payload to embed in a QR** (liteapp URL);")
    print("    otherwise it encodes ``qrcode`` alone (fallback).")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Probe iLink get_bot_qrcode once.")
    p.add_argument("--json", action="store_true", help="Print raw JSON only.")
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(json_only=args.json)))


if __name__ == "__main__":
    main()
