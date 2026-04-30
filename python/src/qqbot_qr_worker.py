"""
HermesDesk: run QQ Bot scan-to-configure in a short-lived child process.

Spawned by Tauri with the same bundled ``python.exe`` as ``desktop_entrypoint.py``.
Writes ``qqbot_qr_progress.json`` and ``qqbot_qr_result.json`` under ``HERMESDESK_DATA_DIR``.

Env (required):
  HERMESDESK_BUNDLE_DIR, HERMESDESK_DATA_DIR, HERMESDESK_WORKSPACE
"""

from __future__ import annotations

import builtins
import json
import os
import sys
import traceback
from pathlib import Path

_ORIGINAL_PRINT = builtins.print


def _wire_sys_path() -> None:
    here = Path(__file__).resolve().parent
    for sub in ("hermes", "site-packages"):
        p = here / sub
        if p.is_dir():
            sys.path.insert(0, str(p))


def _data_dir() -> Path:
    return Path(os.environ["HERMESDESK_DATA_DIR"])


def _write_progress(obj: dict) -> None:
    path = _data_dir() / "qqbot_qr_progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_result(obj: dict) -> None:
    path = _data_dir() / "qqbot_qr_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _real_print(*args, **kwargs):
    _ORIGINAL_PRINT(*args, **kwargs)


def main() -> int:
    _wire_sys_path()
    data_dir = _data_dir()
    hermes_home = data_dir / "hermes-home"
    hermes_home.mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HOME"] = str(hermes_home)

    _write_progress({"phase": "starting", "qr_url": None, "message": None})
    captured_url: list[str] = []

    def _patched_print(*args, **kwargs):
        _real_print(*args, **kwargs)
        if not args:
            return
        line = " ".join(str(a) for a in args).strip()
        for token in line.split():
            if token.startswith(("http://", "https://")):
                captured_url.clear()
                captured_url.append(token)
                _write_progress(
                    {
                        "phase": "waiting_scan",
                        "qr_url": token,
                        "message": None,
                    }
                )
                break

    builtins.print = _patched_print  # type: ignore[assignment]

    try:
        import asyncio

        from gateway.platforms.qqbot.onboard import (
            create_bind_task,
            poll_bind_result,
            build_connect_url,
        )
        from gateway.platforms.qqbot.onboard import BindStatus
        from gateway.platforms.qqbot.crypto import decrypt_secret
        from gateway.platforms.qqbot.constants import ONBOARD_POLL_INTERVAL
        from hermes_cli.config import get_env_value, remove_env_value, save_env_value

        # 1. Create bind task → get task_id and AES key
        _write_progress({"phase": "connecting", "qr_url": None, "message": "Creating bind task..."})
        try:
            task_id, aes_key = asyncio.run(create_bind_task())
        except Exception as e:
            _write_result({"ok": False, "error": f"create_bind_task failed: {e}"})
            _write_progress({"phase": "error", "qr_url": None, "message": str(e)})
            return 1

        # 2. Build QR URL and print
        qr_url = build_connect_url(task_id)
        print(qr_url)
        _write_progress({"phase": "waiting_scan", "qr_url": qr_url, "message": None})

        # 3. Poll until scan completes, expires, or user cancels
        deadline = 480  # seconds
        elapsed = 0.0
        last_status = None
        while elapsed < deadline:
            try:
                status, bot_appid, encrypted_secret, user_openid = asyncio.run(
                    poll_bind_result(task_id)
                )
            except Exception as e:
                _write_result({"ok": False, "error": f"poll failed: {e}"})
                _write_progress({"phase": "error", "qr_url": qr_url, "message": str(e)})
                return 1

            if status != last_status:
                last_status = status
                if status == BindStatus.PENDING:
                    _write_progress({"phase": "waiting_scan", "qr_url": qr_url, "message": "Waiting for scan..."})
                elif status == BindStatus.COMPLETED:
                    _write_progress({"phase": "scanned", "qr_url": qr_url, "message": "Scan confirmed, decrypting credentials..."})
                elif status == BindStatus.EXPIRED:
                    _write_result({"ok": False, "error": "QR code expired"})
                    _write_progress({"phase": "expired", "qr_url": qr_url, "message": "QR code expired"})
                    return 1

            if status == BindStatus.COMPLETED:
                if not bot_appid or not encrypted_secret:
                    _write_result({"ok": False, "error": "Bind completed but missing credentials"})
                    _write_progress({"phase": "error", "qr_url": qr_url, "message": "Missing credentials in bind result"})
                    return 1

                # 4. Decrypt client_secret
                try:
                    client_secret = decrypt_secret(encrypted_secret, aes_key)
                except Exception as e:
                    _write_result({"ok": False, "error": f"decrypt_secret failed: {e}"})
                    _write_progress({"phase": "error", "qr_url": qr_url, "message": str(e)})
                    return 1

                # 5. Remove stale values before writing
                for _key in ("QQ_APP_ID", "QQ_CLIENT_SECRET", "QQ_HOME_CHANNEL"):
                    try:
                        remove_env_value(_key)
                    except Exception:
                        pass

                # 6. Save credentials to .env
                save_env_value("QQ_APP_ID", bot_appid)
                save_env_value("QQ_CLIENT_SECRET", client_secret)
                if user_openid:
                    save_env_value("QQBOT_HOME_CHANNEL", user_openid)

                # 7. HermesDesk defaults: allow all DMs (same as WeChat fix)
                save_env_value("QQ_ALLOW_ALL_USERS", "true")
                save_env_value("QQ_ALLOWED_USERS", "")

                _write_result({"ok": True, "app_id": bot_appid, "user_openid": user_openid or None})
                _write_progress({"phase": "done", "qr_url": qr_url, "message": None})
                return 0

            if status == BindStatus.PENDING:
                print(".", end="", flush=True)

            asyncio.run(asyncio.sleep(ONBOARD_POLL_INTERVAL))
            elapsed += ONBOARD_POLL_INTERVAL

        _write_result({"ok": False, "error": "Scan timed out"})
        _write_progress({"phase": "timeout", "qr_url": qr_url, "message": "Scan timed out"})
        return 1

    except BaseException as e:
        _write_result({"ok": False, "error": str(e), "traceback": traceback.format_exc()[-4000:]})
        _write_progress({"phase": "error", "qr_url": captured_url[0] if captured_url else None, "message": str(e)})
        return 1
    finally:
        builtins.print = _ORIGINAL_PRINT  # type: ignore[assignment]


if __name__ == "__main__":
    raise SystemExit(main())
