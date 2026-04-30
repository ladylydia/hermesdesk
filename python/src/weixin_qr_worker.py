"""
HermesDesk Route C: run Weixin iLink ``qr_login`` in a short-lived child process.

Spawned by Tauri with the same bundled ``python.exe`` as ``desktop_entrypoint.py``.
Writes ``weixin_qr_progress.json`` and ``weixin_qr_result.json`` under ``HERMESDESK_DATA_DIR``.

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

# Must keep a reference to the real ``print`` before we monkeypatch ``builtins.print``,
# otherwise ``_real_print`` would call the patched function and recurse infinitely.
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
    path = _data_dir() / "weixin_qr_progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_result(obj: dict) -> None:
    path = _data_dir() / "weixin_qr_result.json"
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

    _write_progress({"phase": "starting", "liteapp_url": None, "message": None})
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
                        "liteapp_url": token,
                        "message": None,
                    }
                )
                break

    builtins.print = _patched_print  # type: ignore[assignment]

    try:
        import asyncio

        from gateway.platforms.weixin import qr_login
        from hermes_cli.config import get_env_value, remove_env_value, save_env_value

        _write_progress({"phase": "connecting", "liteapp_url": captured_url[0] if captured_url else None, "message": None})

        creds = asyncio.run(qr_login(str(hermes_home)))
        if not creds:
            _write_result({"ok": False, "error": "qr_login returned no credentials (timeout or cancelled)"})
            return 1

        account_id = str(creds.get("account_id", ""))
        token = str(creds.get("token", ""))
        base_url = str(creds.get("base_url", ""))
        user_id = str(creds.get("user_id", ""))

        # Drop legacy / tutorial keys and remove duplicate WEIXIN_ACCOUNT_ID / WEIXIN_TOKEN lines
        # so ``save_env_value`` (which only replaces the *first* match) cannot leave a stale second line
        # that still overrides at parse time — see docs/troubleshooting.md §13.
        for _legacy in ("WEIXIN_APP_ID", "WEIXIN_APP_SECRET"):
            try:
                remove_env_value(_legacy)
            except Exception:
                pass
        for _primary in ("WEIXIN_ACCOUNT_ID", "WEIXIN_TOKEN"):
            try:
                remove_env_value(_primary)
            except Exception:
                pass

        save_env_value("WEIXIN_ACCOUNT_ID", account_id)
        save_env_value("WEIXIN_TOKEN", token)
        if base_url:
            save_env_value("WEIXIN_BASE_URL", base_url)
        save_env_value(
            "WEIXIN_CDN_BASE_URL",
            get_env_value("WEIXIN_CDN_BASE_URL") or "https://novac2c.cdn.weixin.qq.com/c2c",
        )
        # HermesDesk is a non-technical product — allow all DMs by default after QR login
        # so users never need to manually approve pairing codes from the CLI.
        save_env_value("WEIXIN_DM_POLICY", "open")
        save_env_value("WEIXIN_ALLOW_ALL_USERS", "true")
        save_env_value("WEIXIN_ALLOWED_USERS", "")
        save_env_value("WEIXIN_GROUP_POLICY", "disabled")
        save_env_value("WEIXIN_GROUP_ALLOWED_USERS", "")
        if user_id:
            save_env_value("WEIXIN_HOME_CHANNEL", user_id)

        _write_result({"ok": True, "account_id": account_id, "user_id": user_id or None})
        _write_progress({"phase": "done", "liteapp_url": captured_url[0] if captured_url else None, "message": None})
        return 0
    except BaseException as e:
        _write_result({"ok": False, "error": str(e), "traceback": traceback.format_exc()[-4000:]})
        _write_progress({"phase": "error", "liteapp_url": captured_url[0] if captured_url else None, "message": str(e)})
        return 1
    finally:
        builtins.print = _ORIGINAL_PRINT  # type: ignore[assignment]


if __name__ == "__main__":
    raise SystemExit(main())
