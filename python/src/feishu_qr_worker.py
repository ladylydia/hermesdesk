"""
HermesDesk Route C: run Feishu / Lark scan-to-create QR flow in a short-lived child process.

Spawned by Tauri with the same bundled ``python.exe`` as ``desktop_entrypoint.py``.
Writes ``feishu_qr_progress.json`` and ``feishu_qr_result.json`` under ``HERMESDESK_DATA_DIR``.

Env (required):
  HERMESDESK_BUNDLE_DIR, HERMESDESK_DATA_DIR, HERMESDESK_WORKSPACE
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def _wire_sys_path() -> None:
    here = Path(__file__).resolve().parent
    for sub in ("hermes", "site-packages"):
        p = here / sub
        if p.is_dir():
            sys.path.insert(0, str(p))


def _data_dir() -> Path:
    return Path(os.environ["HERMESDESK_DATA_DIR"])


def _write_progress(obj: dict) -> None:
    path = _data_dir() / "feishu_qr_progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_result(obj: dict) -> None:
    path = _data_dir() / "feishu_qr_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    _wire_sys_path()
    data_dir = _data_dir()
    hermes_home = data_dir / "hermes-home"
    hermes_home.mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HOME"] = str(hermes_home)

    _write_progress({"phase": "starting", "qr_url": None, "message": None})

    try:
        import builtins as _builtins

        from env_validate import validate_env_value
        from gateway.platforms.feishu import (
            _begin_registration,
            _init_registration,
            _poll_registration,
            probe_bot,
        )
        from hermes_cli.config import get_env_value, save_env_value

        _ORIGINAL_PRINT = _builtins.print

        def _silent_print(*args, **kwargs):
            pass

        _builtins.print = _silent_print  # type: ignore[assignment]

        _write_progress({"phase": "connecting", "qr_url": None, "message": None})

        _init_registration("feishu")
        begin = _begin_registration("feishu")
        qr_url = begin["qr_url"]

        _write_progress({
            "phase": "waiting_scan",
            "qr_url": qr_url,
            "message": None,
        })

        result = _poll_registration(
            device_code=begin["device_code"],
            interval=begin["interval"],
            expire_in=begin["expire_in"],
            domain="feishu",
        )

        _builtins.print = _ORIGINAL_PRINT  # type: ignore[assignment]

        if not result:
            _write_result({"ok": False, "error": "QR registration timed out or was denied"})
            return 1

        app_id = result["app_id"]
        app_secret = result["app_secret"]
        domain = result.get("domain", "feishu")
        open_id = result.get("open_id")

        validate_env_value(app_id)
        validate_env_value(app_secret)
        save_env_value("FEISHU_APP_ID", app_id)
        save_env_value("FEISHU_APP_SECRET", app_secret)
        save_env_value("FEISHU_DOMAIN", domain)
        save_env_value("FEISHU_CONNECTION_MODE", "websocket")
        save_env_value("FEISHU_ALLOW_ALL_USERS", "true")
        save_env_value("FEISHU_ALLOWED_USERS", "")
        save_env_value("FEISHU_GROUP_POLICY", "open")

        bot_name = None
        try:
            bot_info = probe_bot(app_id, app_secret, domain)
            if bot_info:
                bot_name = bot_info.get("bot_name")
        except Exception:
            pass

        _write_result({
            "ok": True,
            "app_id": app_id,
            "domain": domain,
            "open_id": open_id or None,
            "bot_name": bot_name,
        })
        _write_progress({"phase": "done", "qr_url": qr_url, "message": None})
        return 0

    except BaseException as e:
        _write_result({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()[-4000:],
        })
        _write_progress({
            "phase": "error",
            "qr_url": None,
            "message": str(e),
        })
        return 1
    finally:
        try:
            _builtins.print = _ORIGINAL_PRINT  # type: ignore[assignment]
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
