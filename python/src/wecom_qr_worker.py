"""
HermesDesk Route C: run WeCom scan-to-create QR flow in a short-lived child process.

Spawned by Tauri with the same bundled ``python.exe`` as ``desktop_entrypoint.py``.
Writes ``wecom_qr_progress.json`` and ``wecom_qr_result.json`` under ``HERMESDESK_DATA_DIR``.

Env (required):
  HERMESDESK_BUNDLE_DIR, HERMESDESK_DATA_DIR, HERMESDESK_WORKSPACE
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

_QR_GENERATE_URL = "https://work.weixin.qq.com/ai/qc/generate"
_QR_QUERY_URL = "https://work.weixin.qq.com/ai/qc/query_result"
_QR_CODE_PAGE = "https://work.weixin.qq.com/ai/qc/gen?source=hermes&scode="
_QR_POLL_INTERVAL = 3
_QR_POLL_TIMEOUT = 300


def _wire_sys_path() -> None:
    here = Path(__file__).resolve().parent
    for sub in ("hermes", "site-packages"):
        p = here / sub
        if p.is_dir():
            sys.path.insert(0, str(p))


def _data_dir() -> Path:
    return Path(os.environ["HERMESDESK_DATA_DIR"])


def _write_progress(obj: dict) -> None:
    path = _data_dir() / "wecom_qr_progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_result(obj: dict) -> None:
    path = _data_dir() / "wecom_qr_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    _wire_sys_path()
    data_dir = _data_dir()
    hermes_home = data_dir / "hermes-home"
    hermes_home.mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HOME"] = str(hermes_home)

    _write_progress({"phase": "starting", "message": None})

    try:
        from env_validate import validate_env_value
        from hermes_cli.config import save_env_value

        # ── Step 1: Fetch QR code ──
        _write_progress({"phase": "connecting", "message": "Fetching QR code from WeCom..."})
        generate_url = f"{_QR_GENERATE_URL}?source=hermes"
        try:
            req = urllib.request.Request(generate_url, headers={"User-Agent": "HermesAgent/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            _write_result({"ok": False, "error": f"Failed to fetch QR code: {exc}"})
            return 1

        data = raw.get("data") or {}
        scode = str(data.get("scode") or "").strip()
        auth_url = str(data.get("auth_url") or "").strip()
        if not scode or not auth_url:
            _write_result({"ok": False, "error": "Unexpected response from WeCom QR API"})
            return 1

        page_url = f"{_QR_CODE_PAGE}{urllib.parse.quote(scode)}"

        # ── Step 2: Waiting for scan ──
        _write_progress({
            "phase": "waiting_scan",
            "message": "Scan the QR code or open the link in WeCom on your phone",
            "url": page_url,
        })

        # ── Step 3: Poll for result ──
        deadline = time.time() + _QR_POLL_TIMEOUT
        query_url = f"{_QR_QUERY_URL}?scode={urllib.parse.quote(scode)}"
        while time.time() < deadline:
            try:
                req = urllib.request.Request(query_url, headers={"User-Agent": "HermesAgent/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
            except Exception:
                time.sleep(_QR_POLL_INTERVAL)
                continue

            result_data = result.get("data") or {}
            status = str(result_data.get("status") or "").lower()
            if status == "success":
                bot_info = result_data.get("bot_info") or {}
                bot_id = str(bot_info.get("botid") or bot_info.get("bot_id") or "").strip()
                secret = str(bot_info.get("secret") or "").strip()
                if bot_id and secret:
                    validate_env_value(bot_id)
                    validate_env_value(secret)
                    save_env_value("WECOM_BOT_ID", bot_id)
                    save_env_value("WECOM_SECRET", secret)
                    save_env_value("WECOM_DM_POLICY", "open")
                    save_env_value("WECOM_ALLOW_ALL_USERS", "true")
                    save_env_value("WECOM_ALLOWED_USERS", "")
                    save_env_value("WECOM_SETUP_METHOD", "qr")
                    _write_result({"ok": True, "bot_id": bot_id})
                    _write_progress({"phase": "done", "message": "WeCom bot created successfully"})
                    return 0
                _write_result({"ok": False, "error": "Scan reported success but no credentials returned"})
                return 1
            time.sleep(_QR_POLL_INTERVAL)

        _write_result({"ok": False, "error": f"QR scan timed out ({_QR_POLL_TIMEOUT // 60} minutes)"})
        return 1

    except BaseException as e:
        _write_result({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()[-4000:],
        })
        _write_progress({"phase": "error", "message": str(e)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
