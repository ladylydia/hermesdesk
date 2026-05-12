"""
Hermes Agent — Web UI server.

Provides a FastAPI backend serving the Vite/React frontend and REST API
endpoints for managing configuration, environment variables, and sessions.

Usage:
    python -m hermes_cli.main web          # Start on http://127.0.0.1:9119
    python -m hermes_cli.main web --port 8080
"""

import asyncio
import base64
import hmac
import io
import importlib.util
import json
import logging
import os
import queue
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from xml.etree import ElementTree as ET

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hermes_cli import __version__, __release_date__
from hermes_cli.config import (
    cfg_get,
    DEFAULT_CONFIG,
    OPTIONAL_ENV_VARS,
    get_config_path,
    get_env_path,
    get_hermes_home,
    load_config,
    load_env,
    save_config,
    save_env_value,
    remove_env_value,
    check_config_version,
    redact_key,
)
from gateway.status import get_running_pid, read_runtime_status

try:
    from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:
    raise SystemExit(
        "Web UI requires fastapi and uvicorn.\n"
        f"Install with: {sys.executable} -m pip install 'fastapi' 'uvicorn[standard]'"
    )

WEB_DIST = Path(os.environ["HERMES_WEB_DIST"]) if "HERMES_WEB_DIST" in os.environ else Path(__file__).parent / "web_dist"
_log = logging.getLogger(__name__)

app = FastAPI(title="Hermes Agent", version=__version__)

# ---------------------------------------------------------------------------
# Session token for protecting sensitive endpoints (reveal).
# Generated fresh on every server start — dies when the process exits.
# Injected into the SPA HTML so only the legitimate web UI can use it.
# ---------------------------------------------------------------------------
_SESSION_TOKEN = secrets.token_urlsafe(32)
_SESSION_HEADER_NAME = "X-Hermes-Session-Token"

# In-browser Chat tab (/chat, /api/pty, …).  Off unless ``hermes dashboard --tui``
# or HERMES_DASHBOARD_TUI=1.  Set from :func:`start_server`.
_DASHBOARD_EMBEDDED_CHAT_ENABLED = False

# Simple rate limiter for the reveal endpoint
_reveal_timestamps: List[float] = []
_REVEAL_MAX_PER_WINDOW = 5
_REVEAL_WINDOW_SECONDS = 30

# CORS: restrict to localhost origins only.  The web UI is intended to run
# locally; binding to 0.0.0.0 with allow_origins=["*"] would let any website
# read/modify config and secrets.

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Endpoints that do NOT require the session token.  Everything else under
# /api/ is gated by the auth middleware below.  Keep this list minimal —
# only truly non-sensitive, read-only endpoints belong here.
# ---------------------------------------------------------------------------
_PUBLIC_API_PATHS: frozenset = frozenset({
    "/api/status",
    "/api/config/defaults",
    "/api/config/schema",
    "/api/model/info",
    "/api/dashboard/themes",
    "/api/dashboard/plugins",
    "/api/dashboard/plugins/rescan",
})


def _has_valid_session_token(request: Request) -> bool:
    """True if the request carries a valid dashboard session token.

    The dedicated session header avoids collisions with reverse proxies that
    already use ``Authorization`` (for example Caddy ``basic_auth``). We still
    accept the legacy Bearer path for backward compatibility with older
    dashboard bundles.
    """
    session_header = request.headers.get(_SESSION_HEADER_NAME, "")
    if session_header and hmac.compare_digest(
        session_header.encode(),
        _SESSION_TOKEN.encode(),
    ):
        return True

    auth = request.headers.get("authorization", "")
    expected = f"Bearer {_SESSION_TOKEN}"
    return hmac.compare_digest(auth.encode(), expected.encode())


def _require_token(request: Request) -> None:
    """Validate the ephemeral session token.  Raises 401 on mismatch."""
    if not _has_valid_session_token(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


# Accepted Host header values for loopback binds. DNS rebinding attacks
# point a victim browser at an attacker-controlled hostname (evil.test)
# which resolves to 127.0.0.1 after a TTL flip — bypassing same-origin
# checks because the browser now considers evil.test and our dashboard
# "same origin". Validating the Host header at the app layer rejects any
# request whose Host isn't one we bound for. See GHSA-ppp5-vxwm-4cf7.
_LOOPBACK_HOST_VALUES: frozenset = frozenset({
    "localhost", "127.0.0.1", "::1",
})


def _is_accepted_host(host_header: str, bound_host: str) -> bool:
    """True if the Host header targets the interface we bound to.

    Accepts:
    - Exact bound host (with or without port suffix)
    - Loopback aliases when bound to loopback
    - Any host when bound to 0.0.0.0 (explicit opt-in to non-loopback,
      no protection possible at this layer)
    """
    if not host_header:
        return False
    # Strip port suffix. IPv6 addresses use bracket notation:
    #   [::1]         — no port
    #   [::1]:9119    — with port
    # Plain hosts/v4:
    #   localhost:9119
    #   127.0.0.1:9119
    h = host_header.strip()
    if h.startswith("["):
        # IPv6 bracketed — port (if any) follows "]:"
        close = h.find("]")
        if close != -1:
            host_only = h[1:close]  # strip brackets
        else:
            host_only = h.strip("[]")
    else:
        host_only = h.rsplit(":", 1)[0] if ":" in h else h
    host_only = host_only.lower()

    # 0.0.0.0 bind means operator explicitly opted into all-interfaces
    # (requires --insecure per web_server.start_server). No Host-layer
    # defence can protect that mode; rely on operator network controls.
    if bound_host in ("0.0.0.0", "::"):
        return True

    # Loopback bind: accept the loopback names
    bound_lc = bound_host.lower()
    if bound_lc in _LOOPBACK_HOST_VALUES:
        return host_only in _LOOPBACK_HOST_VALUES

    # Explicit non-loopback bind: require exact host match
    return host_only == bound_lc


@app.middleware("http")
async def host_header_middleware(request: Request, call_next):
    """Reject requests whose Host header doesn't match the bound interface.

    Defends against DNS rebinding: a victim browser on a localhost
    dashboard is tricked into fetching from an attacker hostname that
    TTL-flips to 127.0.0.1. CORS and same-origin checks don't help —
    the browser now treats the attacker origin as same-origin with the
    dashboard. Host-header validation at the app layer catches it.

    See GHSA-ppp5-vxwm-4cf7.
    """
    # Store the bound host on app.state so this middleware can read it —
    # set by start_server() at listen time.
    bound_host = getattr(app.state, "bound_host", None)
    if bound_host:
        host_header = request.headers.get("host", "")
        if not _is_accepted_host(host_header, bound_host):
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        "Invalid Host header. Dashboard requests must use "
                        "the hostname the server was bound to."
                    ),
                },
            )
    return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require the session token on all /api/ routes except the public list.

    When the Tauri shell calls Hermes over HTTP (no ``Authorization: Bearer`` in
    the webview), it passes ``X-HermesDesk-Auth`` equal to
    ``HERMESDESK_BRIDGE_SECRET``. Only the HermesDesk Python launcher sets that
    per-run secret, so if it is non-empty we always validate the header.
    """
    path = request.url.path
    if path.startswith("/api/") and path not in _PUBLIC_API_PATHS and not path.startswith("/api/plugins/"):
        if _has_valid_session_token(request):
            return await call_next(request)
        bridge_secret = (os.environ.get("HERMESDESK_BRIDGE_SECRET") or "").strip()
        if bridge_secret:
            desk_auth = (request.headers.get("x-hermesdesk-auth") or "").strip()
            if desk_auth and hmac.compare_digest(
                desk_auth.encode("utf-8"), bridge_secret.encode("utf-8")
            ):
                return await call_next(request)
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Config schema — auto-generated from DEFAULT_CONFIG
# ---------------------------------------------------------------------------

# Manual overrides for fields that need select options or custom types
_SCHEMA_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "model": {
        "type": "string",
        "description": "Default model (e.g. anthropic/claude-sonnet-4.6)",
        "category": "general",
    },
    "model_context_length": {
        "type": "number",
        "description": "Context window override (0 = auto-detect from model metadata)",
        "category": "general",
    },
    "terminal.backend": {
        "type": "select",
        "description": "Terminal execution backend",
        "options": ["local", "docker", "ssh", "modal", "daytona", "vercel_sandbox", "singularity"],
    },
    "terminal.vercel_runtime": {
        "type": "select",
        "description": "Vercel Sandbox runtime",
        "options": ["node24", "node22", "python3.13"],  # sync with _SUPPORTED_VERCEL_RUNTIMES in terminal_tool.py
    },
    "terminal.modal_mode": {
        "type": "select",
        "description": "Modal sandbox mode",
        "options": ["sandbox", "function"],
    },
    "tts.provider": {
        "type": "select",
        "description": "Text-to-speech provider",
        "options": ["edge", "elevenlabs", "openai", "neutts"],
    },
    "stt.provider": {
        "type": "select",
        "description": "Speech-to-text provider",
        "options": ["local", "openai", "mistral"],
    },
    "display.skin": {
        "type": "select",
        "description": "CLI visual theme",
        "options": ["default", "ares", "mono", "slate"],
    },
    "dashboard.theme": {
        "type": "select",
        "description": "Web dashboard visual theme",
        "options": ["default", "midnight", "ember", "mono", "cyberpunk", "rose"],
    },
    "display.resume_display": {
        "type": "select",
        "description": "How resumed sessions display history",
        "options": ["minimal", "full", "off"],
    },
    "display.busy_input_mode": {
        "type": "select",
        "description": "Input behavior while agent is running",
        "options": ["interrupt", "queue", "steer"],
    },
    "memory.provider": {
        "type": "select",
        "description": "Memory provider plugin",
        "options": ["builtin", "honcho"],
    },
    "approvals.mode": {
        "type": "select",
        "description": "Dangerous command approval mode",
        "options": ["ask", "yolo", "deny"],
    },
    "context.engine": {
        "type": "select",
        "description": "Context management engine",
        "options": ["default", "custom"],
    },
    "human_delay.mode": {
        "type": "select",
        "description": "Simulated typing delay mode",
        "options": ["off", "typing", "fixed"],
    },
    "logging.level": {
        "type": "select",
        "description": "Log level for agent.log",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    "agent.service_tier": {
        "type": "select",
        "description": "API service tier (OpenAI/Anthropic)",
        "options": ["", "auto", "default", "flex"],
    },
    "delegation.reasoning_effort": {
        "type": "select",
        "description": "Reasoning effort for delegated subagents",
        "options": ["", "low", "medium", "high"],
    },
}

# Categories with fewer fields get merged into "general" to avoid tab sprawl.
_CATEGORY_MERGE: Dict[str, str] = {
    "privacy": "security",
    "context": "agent",
    "skills": "agent",
    "cron": "agent",
    "network": "agent",
    "checkpoints": "agent",
    "approvals": "security",
    "human_delay": "display",
    "dashboard": "display",
    "code_execution": "agent",
    "prompt_caching": "agent",
    # Only `telegram.reactions` currently lives under telegram — fold it in
    # with the other messaging-platform config (discord) so it isn't an
    # orphan tab of one field.
    "telegram": "discord",
}

# Display order for tabs — unlisted categories sort alphabetically after these.
_CATEGORY_ORDER = [
    "general", "agent", "terminal", "display", "delegation",
    "memory", "compression", "security", "browser", "voice",
    "tts", "stt", "logging", "discord", "auxiliary",
]


def _infer_type(value: Any) -> str:
    """Infer a UI field type from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "string"


def _build_schema_from_config(
    config: Dict[str, Any],
    prefix: str = "",
) -> Dict[str, Dict[str, Any]]:
    """Walk DEFAULT_CONFIG and produce a flat dot-path → field schema dict."""
    schema: Dict[str, Dict[str, Any]] = {}
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key

        # Skip internal / version keys
        if full_key in ("_config_version",):
            continue

        # Category is the first path component for nested keys, or "general"
        # for top-level scalar fields (model, toolsets, timezone, etc.).
        if prefix:
            category = prefix.split(".")[0]
        elif isinstance(value, dict):
            category = key
        else:
            category = "general"

        if isinstance(value, dict):
            # Recurse into nested dicts
            schema.update(_build_schema_from_config(value, full_key))
        else:
            entry: Dict[str, Any] = {
                "type": _infer_type(value),
                "description": full_key.replace(".", " → ").replace("_", " ").title(),
                "category": category,
            }
            # Apply manual overrides
            if full_key in _SCHEMA_OVERRIDES:
                entry.update(_SCHEMA_OVERRIDES[full_key])
            # Merge small categories
            entry["category"] = _CATEGORY_MERGE.get(entry["category"], entry["category"])
            schema[full_key] = entry
    return schema


CONFIG_SCHEMA = _build_schema_from_config(DEFAULT_CONFIG)

# Inject virtual fields that don't live in DEFAULT_CONFIG but are surfaced
# by the normalize/denormalize cycle.  Insert model_context_length right after
# the "model" key so it renders adjacent in the frontend.
_mcl_entry = _SCHEMA_OVERRIDES["model_context_length"]
_ordered_schema: Dict[str, Dict[str, Any]] = {}
for _k, _v in CONFIG_SCHEMA.items():
    _ordered_schema[_k] = _v
    if _k == "model":
        _ordered_schema["model_context_length"] = _mcl_entry
CONFIG_SCHEMA = _ordered_schema


class ConfigUpdate(BaseModel):
    config: dict


class EnvVarUpdate(BaseModel):
    key: str
    value: str


class EnvVarDelete(BaseModel):
    key: str


class EnvVarReveal(BaseModel):
    key: str


class ModelAssignment(BaseModel):
    """Payload for POST /api/model/set — assign a provider/model to a slot.

    scope="main"        → writes model.provider + model.default
    scope="auxiliary"   → writes auxiliary.<task>.provider + auxiliary.<task>.model
    scope="auxiliary" with task=""  → applied to every auxiliary.* slot
    scope="auxiliary" with task="__reset__"  → resets every slot to provider="auto"
    """
    scope: str
    provider: str
    model: str
    task: str = ""


_GATEWAY_HEALTH_URL = os.getenv("GATEWAY_HEALTH_URL")
try:
    _GATEWAY_HEALTH_TIMEOUT = float(os.getenv("GATEWAY_HEALTH_TIMEOUT", "3"))
except (ValueError, TypeError):
    _log.warning(
        "Invalid GATEWAY_HEALTH_TIMEOUT value %r — using default 3.0s",
        os.getenv("GATEWAY_HEALTH_TIMEOUT"),
    )
    _GATEWAY_HEALTH_TIMEOUT = 3.0


def _probe_gateway_health() -> tuple[bool, dict | None]:
    """Probe the gateway via its HTTP health endpoint (cross-container).

    Uses ``/health/detailed`` first (returns full state), falling back to
    the simpler ``/health`` endpoint.  Returns ``(is_alive, body_dict)``.

    Accepts any of these as ``GATEWAY_HEALTH_URL``:
    - ``http://gateway:8642``                (base URL — recommended)
    - ``http://gateway:8642/health``         (explicit health path)
    - ``http://gateway:8642/health/detailed`` (explicit detailed path)

    This is a **blocking** call — run via ``run_in_executor`` from async code.
    """
    if not _GATEWAY_HEALTH_URL:
        return False, None

    # Normalise to base URL so we always probe the right paths regardless of
    # whether the user included /health or /health/detailed in the env var.
    base = _GATEWAY_HEALTH_URL.rstrip("/")
    if base.endswith("/health/detailed"):
        base = base[: -len("/health/detailed")]
    elif base.endswith("/health"):
        base = base[: -len("/health")]

    for path in (f"{base}/health/detailed", f"{base}/health"):
        try:
            req = urllib.request.Request(path, method="GET")
            with urllib.request.urlopen(req, timeout=_GATEWAY_HEALTH_TIMEOUT) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read())
                    return True, body
        except Exception:
            continue
    return False, None


@app.get("/api/status")
async def get_status():
    current_ver, latest_ver = check_config_version()

    # --- Gateway liveness detection ---
    # Try local PID check first (same-host).  If that fails and a remote
    # GATEWAY_HEALTH_URL is configured, probe the gateway over HTTP so the
    # dashboard works when the gateway runs in a separate container.
    gateway_pid = get_running_pid()
    gateway_running = gateway_pid is not None
    remote_health_body: dict | None = None

    if not gateway_running and _GATEWAY_HEALTH_URL:
        loop = asyncio.get_event_loop()
        alive, remote_health_body = await loop.run_in_executor(
            None, _probe_gateway_health
        )
        if alive:
            gateway_running = True
            # PID from the remote container (display only — not locally valid)
            if remote_health_body:
                gateway_pid = remote_health_body.get("pid")

    gateway_state = None
    gateway_platforms: dict = {}
    gateway_exit_reason = None
    gateway_updated_at = None
    configured_gateway_platforms: set[str] | None = None
    try:
        from gateway.config import load_gateway_config

        gateway_config = load_gateway_config()
        configured_gateway_platforms = {
            platform.value for platform in gateway_config.get_connected_platforms()
        }
    except Exception:
        configured_gateway_platforms = None

    # Prefer the detailed health endpoint response (has full state) when the
    # local runtime status file is absent or stale (cross-container).
    runtime = read_runtime_status()
    if runtime is None and remote_health_body and remote_health_body.get("gateway_state"):
        runtime = remote_health_body

    if runtime:
        gateway_state = runtime.get("gateway_state")
        gateway_platforms = runtime.get("platforms") or {}
        if configured_gateway_platforms is not None:
            gateway_platforms = {
                key: value
                for key, value in gateway_platforms.items()
                if key in configured_gateway_platforms
            }
        gateway_exit_reason = runtime.get("exit_reason")
        gateway_updated_at = runtime.get("updated_at")
        if not gateway_running:
            gateway_state = gateway_state if gateway_state in ("stopped", "startup_failed") else "stopped"
            gateway_platforms = {}
        elif gateway_running and remote_health_body is not None:
            # The health probe confirmed the gateway is alive, but the local
            # runtime status file may be stale (cross-container).  Override
            # stopped/None state so the dashboard shows the correct badge.
            if gateway_state in (None, "stopped"):
                gateway_state = "running"

    # If there was no runtime info at all but the health probe confirmed alive,
    # ensure we still report the gateway as running (no shared volume scenario).
    if gateway_running and gateway_state is None and remote_health_body is not None:
        gateway_state = "running"

    active_sessions = 0
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=50)
            now = time.time()
            active_sessions = sum(
                1 for s in sessions
                if s.get("ended_at") is None
                and (now - s.get("last_active", s.get("started_at", 0))) < 300
            )
        finally:
            db.close()
    except Exception:
        pass

    return {
        "version": __version__,
        "release_date": __release_date__,
        "hermes_home": str(get_hermes_home()),
        "config_path": str(get_config_path()),
        "env_path": str(get_env_path()),
        "config_version": current_ver,
        "latest_config_version": latest_ver,
        "gateway_running": gateway_running,
        "gateway_pid": gateway_pid,
        "gateway_health_url": _GATEWAY_HEALTH_URL,
        "gateway_state": gateway_state,
        "gateway_platforms": gateway_platforms,
        "gateway_exit_reason": gateway_exit_reason,
        "gateway_updated_at": gateway_updated_at,
        "active_sessions": active_sessions,
    }


# ---------------------------------------------------------------------------
# Gateway + update actions (invoked from the Status page).
#
# Both commands are spawned as detached subprocesses so the HTTP request
# returns immediately.  stdin is closed (``DEVNULL``) so any stray ``input()``
# calls fail fast with EOF rather than hanging forever.  stdout/stderr are
# streamed to a per-action log file under ``~/.hermes/logs/<action>.log`` so
# the dashboard can tail them back to the user.
# ---------------------------------------------------------------------------

_ACTION_LOG_DIR: Path = get_hermes_home() / "logs"

# Short ``name`` (from the URL) → absolute log file path.
_ACTION_LOG_FILES: Dict[str, str] = {
    "gateway-restart": "gateway-restart.log",
    "hermes-update": "hermes-update.log",
}

# ``name`` → most recently spawned Popen handle.  Used so ``status`` can
# report liveness and exit code without shelling out to ``ps``.
_ACTION_PROCS: Dict[str, subprocess.Popen] = {}


def _spawn_hermes_action(subcommand: List[str], name: str) -> subprocess.Popen:
    """Spawn ``hermes <subcommand>`` detached and record the Popen handle.

    Uses the running interpreter's ``hermes_cli.main`` module so the action
    inherits the same venv/PYTHONPATH the web server is using.
    """
    log_file_name = _ACTION_LOG_FILES[name]
    _ACTION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _ACTION_LOG_DIR / log_file_name
    log_file = open(log_path, "ab", buffering=0)
    log_file.write(
        f"\n=== {name} started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode()
    )

    cmd = [sys.executable, "-m", "hermes_cli.main", *subcommand]

    popen_kwargs: Dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "env": {**os.environ, "HERMES_NONINTERACTIVE": "1"},
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    _ACTION_PROCS[name] = proc
    return proc


def _tail_lines(path: Path, n: int) -> List[str]:
    """Return the last ``n`` lines of ``path``.  Reads the whole file — fine
    for our small per-action logs.  Binary-decoded with ``errors='replace'``
    so log corruption doesn't 500 the endpoint."""
    if not path.exists():
        return []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if n > 0 else lines


@app.post("/api/gateway/restart")
async def restart_gateway():
    """Kick off a ``hermes gateway restart`` in the background."""
    try:
        proc = _spawn_hermes_action(["gateway", "restart"], "gateway-restart")
    except Exception as exc:
        _log.exception("Failed to spawn gateway restart")
        raise HTTPException(status_code=500, detail=f"Failed to restart gateway: {exc}")
    return {
        "ok": True,
        "pid": proc.pid,
        "name": "gateway-restart",
    }


@app.post("/api/hermes/update")
async def update_hermes():
    """Kick off ``hermes update`` in the background."""
    try:
        proc = _spawn_hermes_action(["update"], "hermes-update")
    except Exception as exc:
        _log.exception("Failed to spawn hermes update")
        raise HTTPException(status_code=500, detail=f"Failed to start update: {exc}")
    return {
        "ok": True,
        "pid": proc.pid,
        "name": "hermes-update",
    }


# ---------------------------------------------------------------------------
# HermesDesk shell: track in-flight AIAgent for /api/desk/stop (interrupt).
# ---------------------------------------------------------------------------
_desk_active_agents: Dict[str, Any] = {}
_desk_active_lock = threading.Lock()
_DESK_MAX_ATTACHMENTS = 6
_DESK_MAX_ATTR_BYTES = 12 * 1024 * 1024
_DESK_MAX_INLINE_CHARS = 200_000


def _desk_register_active(session_id: str, agent: Any) -> None:
    with _desk_active_lock:
        _desk_active_agents[session_id] = agent


def _desk_unregister_active(session_id: str) -> None:
    with _desk_active_lock:
        _desk_active_agents.pop(session_id, None)


_DESK_PROGRESS_EVENT_CAP = 200


def _desk_progress_response(
    agent: Any,
    since: int = 0,
    events_override: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    progress = dict(getattr(agent, "_progress", {}) or {})
    events_out: List[Dict[str, Any]] = []
    next_seq = 0
    lock = getattr(agent, "_progress_event_lock", None)
    if lock is not None:
        with lock:
            all_events = list(getattr(agent, "_progress_events", []) or [])
            next_seq = int(getattr(agent, "_progress_event_seq", 0) or 0)
        if events_override is not None:
            events_out = events_override
        else:
            events_out = [e for e in all_events if int(e.get("seq", 0)) > int(since or 0)]
    progress["events"] = events_out
    progress["next_seq"] = next_seq
    return progress


def _desk_attach_progress_events(agent: Any, stream_emit: Optional[Any] = None) -> None:
    """Wire `tool_progress_callback` to record per-tool events on the agent.

    The frontend polls /api/desk/chat-preview/{sid}?since=N to render a live
    step list (tool name + preview + duration). Events are kept on the agent
    as a ring buffer; the callback only forwards `tool.started` / `tool.completed`.
    """
    agent._progress_events = []
    agent._progress_event_seq = 0
    agent._progress_event_lock = threading.Lock()

    def _cb(event_type, name, preview, args, duration=None, is_error=None):
        if event_type not in ("tool.started", "tool.completed"):
            return
        event_payload: Optional[Dict[str, Any]] = None
        try:
            with agent._progress_event_lock:
                agent._progress_event_seq += 1
                event_payload = {
                    "seq": agent._progress_event_seq,
                    "kind": event_type,
                    "tool": str(name) if name else "",
                    "preview": preview if isinstance(preview, str) else None,
                    "duration": float(duration) if duration is not None else None,
                    "is_error": bool(is_error) if is_error else False,
                    "ts": time.time(),
                }
                agent._progress_events.append(event_payload)
                if len(agent._progress_events) > _DESK_PROGRESS_EVENT_CAP:
                    agent._progress_events = agent._progress_events[-_DESK_PROGRESS_EVENT_CAP:]
        except Exception:
            _log.debug("desk progress event callback failed", exc_info=True)
        if stream_emit is not None and event_payload is not None:
            try:
                stream_emit({
                    "type": "progress",
                    "progress": _desk_progress_response(agent, events_override=[event_payload]),
                })
            except Exception:
                _log.debug("desk progress stream emit failed", exc_info=True)

    agent.tool_progress_callback = _cb


def _desk_prepare_active_agent(
    session_id: str,
    agent: Any,
    stream_delta_callback: Optional[Any] = None,
    progress_event_callback: Optional[Any] = None,
) -> None:
    """Make a desk agent visible to preview/stop before its worker thread starts."""
    if getattr(agent, "_desk_prepared_session_id", None) == session_id:
        return
    agent._progress = {
        "running": True,
        "status": "starting",
        "iteration": 0,
        "max_iterations": int(getattr(agent, "max_iterations", 0) or 0),
        "current_tool": None,
        "error": None,
    }
    _desk_attach_progress_events(agent, progress_event_callback)
    if stream_delta_callback is not None:
        agent.stream_delta_callback = stream_delta_callback
    agent._desk_prepared_session_id = session_id
    _desk_register_active(session_id, agent)


def _desk_parse_attachments_from_body(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = body.get("attachments")
    if not raw or not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in raw[:_DESK_MAX_ATTACHMENTS]:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "file")
        mime = (str(it.get("mime") or "application/octet-stream")).strip() or "application/octet-stream"

        # Path-based attachment (Rust saves to workspace, sends path)
        fpath = it.get("path")
        if isinstance(fpath, str) and fpath:
            if os.path.isfile(fpath):
                try:
                    rawb = Path(fpath).read_bytes()
                except Exception as e:
                    _log.warning("desk attachment read failed for %s: %s", fpath, e)
                    continue
                out.append({"name": name, "mime": mime.lower(), "data": rawb, "path": fpath})
                continue
            else:
                _log.warning("desk attachment path not found: %s", fpath)
                continue

        # Legacy base64 data field
        raw_d = it.get("data")
        if raw_d in (None, ""):
            continue
        b64 = str(raw_d).strip()
        if not b64:
            continue
        try:
            rawb = base64.b64decode(b64, validate=False)
        except Exception as e:
            _log.warning("desk attachment b64decode failed: %s", e)
            continue
        if not rawb or len(rawb) > _DESK_MAX_ATTR_BYTES:
            _log.warning("desk attachment skipped: empty=%s too_big=%s (limit=%s)",
                         not rawb, len(rawb) > _DESK_MAX_ATTR_BYTES if rawb else False, _DESK_MAX_ATTR_BYTES)
            continue
        out.append({"name": name, "mime": mime.lower(), "data": rawb})
    return out


def _desk_attachment_ext(name: str) -> str:
    return Path(name).suffix.lower()


def _desk_is_presentation(name: str, mime: str) -> bool:
    ext = _desk_attachment_ext(name)
    return ext in {".ppt", ".pptx"} or mime in {
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }


def _desk_pptx_sort_key(path: str) -> Tuple[int, str]:
    m = re.search(r"(\d+)", path)
    return (int(m.group(1)) if m else 0, path)


def _desk_extract_pptx_text(data: bytes) -> str:
    """Extract readable text from a PPTX using only stdlib zip/xml parsing."""
    slides: List[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = sorted(
            (
                n for n in zf.namelist()
                if n.startswith("ppt/slides/slide") and n.endswith(".xml")
            ),
            key=_desk_pptx_sort_key,
        )
        notes = sorted(
            (
                n for n in zf.namelist()
                if n.startswith("ppt/notesSlides/notesSlide") and n.endswith(".xml")
            ),
            key=_desk_pptx_sort_key,
        )
        for label, xml_names in (("Slide", names), ("Notes", notes)):
            for idx, n in enumerate(xml_names, 1):
                try:
                    root = ET.fromstring(zf.read(n))
                except Exception:
                    continue
                parts: List[str] = []
                for el in root.iter():
                    if el.tag.endswith("}t") and el.text:
                        txt = " ".join(el.text.split())
                        if txt:
                            parts.append(txt)
                if parts:
                    slides.append(f"{label} {idx}: " + "\n".join(parts))
    return "\n\n".join(slides)


def _desk_extract_legacy_ppt_text(data: bytes) -> str:
    """Best-effort text scrape for legacy binary .ppt files.

    This is intentionally conservative: it extracts printable UTF-16LE and
    ASCII runs without executing macros or relying on Office automation.
    """
    chunks: List[str] = []
    seen: set[str] = set()

    for raw in re.findall(rb"(?:[\x20-\x7e]\x00){4,}", data):
        txt = raw.decode("utf-16le", errors="ignore").strip()
        txt = " ".join(txt.split())
        if txt and txt not in seen:
            seen.add(txt)
            chunks.append(txt)

    for raw in re.findall(rb"[\x20-\x7e]{8,}", data):
        txt = raw.decode("latin-1", errors="ignore").strip()
        txt = " ".join(txt.split())
        if txt and txt not in seen:
            seen.add(txt)
            chunks.append(txt)

    return "\n".join(chunks)


def _desk_extract_presentation_text(name: str, mime: str, data: bytes) -> str:
    ext = _desk_attachment_ext(name)
    try:
        if ext == ".pptx" or mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
            return _desk_extract_pptx_text(data)
        if ext == ".ppt" or mime == "application/vnd.ms-powerpoint":
            return _desk_extract_legacy_ppt_text(data)
    except Exception as e:
        _log.warning("desk presentation extraction failed for %s: %s", name, e)
    return ""


def _desk_build_user_message(
    plain: str, atts: List[Dict[str, Any]]
) -> Optional[Tuple[Union[str, List[Dict[str, Any]]], Optional[str]]]:
    """persist_user_message is a clean string for logs/memory when user_message is multimodal."""
    plain = (plain or "").strip()
    if not atts:
        if not plain:
            return None
        return plain, None

    text_buf = plain if plain else "Please answer based on the attachments."
    image_parts: List[Dict[str, Any]] = []
    for p in atts:
        name = str(p.get("name") or "file")
        mime = (str(p.get("mime") or "")).lower()
        data: bytes = p.get("data") or b""
        if not data:
            continue
        if mime.startswith("image/"):
            b64d = base64.b64encode(data).decode("ascii")
            data_url = f"data:{mime};base64,{b64d}"
            image_parts.append({"type": "image_url", "image_url": {"url": data_url}})
        elif _desk_is_presentation(name, mime):
            t = _desk_extract_presentation_text(name, mime, data)
            if t:
                if len(t) > _DESK_MAX_INLINE_CHARS:
                    t = t[:_DESK_MAX_INLINE_CHARS] + "\n[truncated]"
                text_buf = f"{text_buf}\n\n--- {name} (presentation text) ---\n{t}".strip()
            else:
                text_buf = (
                    f"{text_buf}\n\n[file {name!r} type {mime!r} size {len(data)} bytes; "
                    f"presentation text could not be extracted.]"
                ).strip()
        elif mime.startswith("text/") or mime in ("application/json", "application/xml"):
            try:
                t = data.decode("utf-8")
            except UnicodeDecodeError:
                t = data.decode("utf-8", errors="replace")
            if len(t) > _DESK_MAX_INLINE_CHARS:
                t = t[:_DESK_MAX_INLINE_CHARS] + "\n[truncated]"
            text_buf = f"{text_buf}\n\n--- {name} ---\n{t}".strip()
        else:
            fpath = str(p.get("path") or "")
            if fpath:
                text_buf = (
                    f"{text_buf}\n\n[file {name!r} type {mime!r} size {len(data)} bytes "
                    f"saved to {fpath!r}; use read_file to inspect.]"
                ).strip()
            else:
                text_buf = (
                    f"{text_buf}\n\n[file {name!r} type {mime!r} size {len(data)} bytes; "
                    f"not inlined as text -- use workspace tools if needed.]"
                ).strip()

    if not image_parts:
        return text_buf, None
    user_content: List[Dict[str, Any]] = [{"type": "text", "text": text_buf}, *image_parts]
    n_img = len(image_parts)
    persist = plain if plain else f"[{n_img} image(s)]"
    return user_content, persist


def _desk_chat_build_agent(session_id: str, db: Any) -> Any:
    """Construct AIAgent using the same config + credentials as the CLI."""
    from run_agent import AIAgent
    from hermes_cli.config import load_config
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from hermes_cli.tools_config import _get_platform_tools

    try:
        from tools.terminal_tool import register_task_env_overrides
    except Exception:
        register_task_env_overrides = None
    if register_task_env_overrides:
        ws = (os.environ.get("HERMES_WORKSPACE") or os.environ.get("TERMINAL_CWD") or "").strip()
        if ws:
            try:
                register_task_env_overrides(session_id, {"cwd": ws})
            except Exception:
                _log.debug("desk chat: register_task_env_overrides failed", exc_info=True)

    config = load_config()
    model_cfg = config.get("model")
    default_model = ""
    config_provider: Optional[str] = None
    if isinstance(model_cfg, dict):
        default_model = str(model_cfg.get("default") or model_cfg.get("model") or "")
        config_provider = model_cfg.get("provider")
        if isinstance(config_provider, str):
            config_provider = config_provider.strip() or None
    elif isinstance(model_cfg, str) and model_cfg.strip():
        default_model = model_cfg.strip()

    agent_section = config.get("agent") or {}
    try:
        max_turns = int(agent_section.get("max_turns") or 90)
    except (TypeError, ValueError):
        max_turns = 90

    tool_list = sorted(_get_platform_tools(config, "cli"))
    if not tool_list:
        tool_list = None

    runtime = resolve_runtime_provider(requested=config_provider)
    api_key = str(runtime.get("api_key") or "").strip()
    if not api_key:
        raise ValueError(
            "No API credentials available. Configure a model key in Hermes (Settings / Keys or ~/.hermes)."
        )

    kwargs: Dict[str, Any] = {
        "model": default_model,
        "platform": "hermesdesk",
        "session_id": session_id,
        "session_db": db,
        "max_iterations": max_turns,
        "enabled_toolsets": tool_list,
        "quiet_mode": True,
        "provider": runtime.get("provider"),
        "api_mode": runtime.get("api_mode"),
        "base_url": runtime.get("base_url"),
        "api_key": runtime.get("api_key"),
        "command": runtime.get("command"),
        "args": list(runtime.get("args") or []),
        "credential_pool": runtime.get("credential_pool"),
    }
    if isinstance(model_cfg, dict):
        if model_cfg.get("reasoning_config") is not None:
            kwargs["reasoning_config"] = model_cfg.get("reasoning_config")
        if model_cfg.get("max_tokens") is not None:
            try:
                kwargs["max_tokens"] = int(model_cfg.get("max_tokens"))
            except (TypeError, ValueError):
                pass

    return AIAgent(**kwargs)


def _desk_chat_run_in_thread(
    agent: Any,
    user_message: Any,
    history: List[Dict[str, Any]],
    session_id: str,
    persist_user_message: Optional[str] = None,
    stream_delta_callback: Optional[Any] = None,
    progress_event_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    if getattr(agent, "_desk_prepared_session_id", None) != session_id:
        _desk_prepare_active_agent(
            session_id,
            agent,
            stream_delta_callback=stream_delta_callback,
            progress_event_callback=progress_event_callback,
        )
    try:
        if persist_user_message is not None:
            result = agent.run_conversation(
                user_message=user_message,
                conversation_history=history,
                task_id=session_id,
                persist_user_message=persist_user_message,
            )
        else:
            result = agent.run_conversation(
                user_message=user_message,
                conversation_history=history,
                task_id=session_id,
            )
        return {
            "result": result,
            "prompt_tokens": int(getattr(agent, "session_prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(agent, "session_completion_tokens", 0) or 0),
        }
    finally:
        _desk_unregister_active(session_id)


def _desk_strip_thinking_tags(text: str) -> str:
    if not text or "<think>" not in text:
        return text
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _desk_content_to_text(content: Any) -> str:
    """Normalize assistant content (str, list, or OpenAI-compat dict shapes) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        t = content.strip()
        if not t:
            return ""
        if t.startswith(("[", "{")):
            try:
                parsed = json.loads(t)
                if isinstance(parsed, (list, dict)):
                    return _desk_content_to_text(parsed)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        return _desk_strip_thinking_tags(t)
    if isinstance(content, (int, float, bool)):
        return str(content).strip()
    if isinstance(content, dict):
        inner = content.get("text")
        if inner is None:
            inner = content.get("content")
        if isinstance(inner, (dict, list)):
            return _desk_content_to_text(inner)
        if inner is not None:
            return _desk_strip_thinking_tags(str(inner).strip())
        return _desk_strip_thinking_tags(str(content).strip())
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, dict):
                pt = str(part.get("type") or "")
                if pt in ("text", "output_text") or "text" in part:
                    parts.append(str(part.get("text") or ""))
                elif isinstance(part.get("content"), str) and part.get("content", "").strip():
                    parts.append(str(part.get("content")))
            elif isinstance(part, str):
                parts.append(part)
        return _desk_strip_thinking_tags("\n".join(p for p in parts if p).strip())
    return _desk_strip_thinking_tags(str(content).strip())


def _desk_text_from_assistant_messages(messages: List[Any]) -> str:
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        t = _desk_content_to_text(msg.get("content"))
        if t:
            return t
    return ""


def _desk_extract_reply_text(conv_result: Any) -> str:
    """Best-effort assistant text from run_conversation return value."""
    if not isinstance(conv_result, dict):
        return str(conv_result).strip() if conv_result is not None else ""

    fr = conv_result.get("final_response")
    if isinstance(fr, str) and fr.strip():
        return _desk_strip_thinking_tags(fr.strip())
    if fr is not None and not isinstance(fr, str):
        s = str(fr).strip()
        if s:
            return _desk_strip_thinking_tags(s)

    messages: List[Dict[str, Any]] = conv_result.get("messages") or []
    t = _desk_text_from_assistant_messages(messages)
    if t:
        return t
    if conv_result.get("failed") and conv_result.get("error"):
        return str(conv_result.get("error")).strip()
    return ""


@app.post("/api/desk/stop")
async def desk_stop(request: Request):
    """Interrupt the agent for a desk chat session (best-effort)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = (body.get("session_id") or "").strip() if isinstance(body, dict) else ""
    if not session_id:
        return JSONResponse({"ok": False, "error": "missing_session_id"}, status_code=400)
    with _desk_active_lock:
        ag = _desk_active_agents.get(session_id)
    if ag is not None:
        try:
            ag.interrupt("User requested stop from HermesDesk")
        except Exception as e:
            _log.warning("desk stop: interrupt failed: %s", e)
        return JSONResponse({"ok": True, "interrupted": True})
    return JSONResponse({"ok": True, "interrupted": False, "detail": "no active agent for this session"})


@app.get("/api/desk/chat-preview/{session_id}")
async def desk_chat_preview(session_id: str, since: int = 0):
    """Return agent progress for the given session (lightweight poll target).

    Query: `since` — only return tool events with seq > since (frontend cursor).
    Response shape::

        {
            running: bool, status: str, iteration: int, max_iterations: int,
            current_tool: str|None, error: str|None,
            events: [{seq, kind, tool, preview, duration, is_error, ts}, ...],
            next_seq: int,
        }
    """
    with _desk_active_lock:
        ag = _desk_active_agents.get(session_id)
    if ag is None:
        return JSONResponse({
            "running": False, "status": "inactive",
            "events": [], "next_seq": 0,
        })
    progress = _desk_progress_response(ag, since=since)
    if not progress.get("running"):
        with _desk_active_lock:
            _desk_active_agents.pop(session_id, None)
    return JSONResponse(progress)


def _desk_sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


@app.post("/api/desk/chat-stream")
async def desk_chat_stream(request: Request):
    """HermesDesk: stream a real AIAgent turn as SSE events."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid_body"}, status_code=400)
    message = (body.get("message") or "").strip()
    atts = _desk_parse_attachments_from_body(body)
    built = _desk_build_user_message(message, atts)
    if built is None:
        return JSONResponse(
            {"ok": False, "error": "empty_message", "detail": "message and attachments are both empty"},
            status_code=400,
        )
    user_payload, persist_um = built
    session_id = (body.get("session_id") or "").strip() or str(uuid.uuid4())

    from hermes_state import SessionDB

    db = SessionDB()
    try:
        try:
            raw_history = db.get_messages_as_conversation(session_id)
        except Exception as e:
            _log.exception("desk stream: load history failed")
            db.close()
            return JSONResponse({"ok": False, "error": "session_db", "detail": str(e)}, status_code=500)
        history = [m for m in raw_history if m.get("role") != "session_meta"]

        try:
            agent = _desk_chat_build_agent(session_id, db)
        except ValueError as e:
            db.close()
            return JSONResponse({"ok": False, "error": "config", "detail": str(e)}, status_code=503)
        except Exception as e:
            _log.exception("desk stream: agent init failed")
            db.close()
            return JSONResponse({"ok": False, "error": "agent_init", "detail": str(e)}, status_code=500)

        event_q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        _recv_len = len(message) + sum(len(p.get("data") or b"") for p in atts)

        def emit(payload: Dict[str, Any]) -> None:
            payload.setdefault("session_id", session_id)
            event_q.put(payload)

        def on_delta(delta: Any) -> None:
            if isinstance(delta, str) and delta:
                emit({"type": "delta", "text": delta})
            elif delta is None:
                emit({"type": "boundary"})

        _desk_prepare_active_agent(
            session_id,
            agent,
            stream_delta_callback=on_delta,
            progress_event_callback=emit,
        )

        def worker() -> None:
            try:
                _log.info(
                    "desk stream: session=%s user_chars~%d history_msgs=%d attachments=%d",
                    session_id, _recv_len, len(history), len(atts),
                )
                payload = _desk_chat_run_in_thread(
                    agent,
                    user_payload,
                    history,
                    session_id,
                    persist_um,
                    stream_delta_callback=on_delta,
                    progress_event_callback=emit,
                )
                result = (payload or {}).get("result") or {}
                final_text = _desk_extract_reply_text(result)
                if not final_text:
                    try:
                        db_msgs = db.get_messages_as_conversation(session_id)
                        final_text = _desk_text_from_assistant_messages(db_msgs)
                    except Exception:
                        _log.debug("desk stream: could not re-read session messages for reply text", exc_info=True)

                ft = (final_text or "").strip()
                if ft in ("(empty)",):
                    ft = ""
                if not ft and isinstance(result, dict):
                    emit({
                        "type": "error",
                        "ok": False,
                        "error": "empty_model_response",
                        "detail": (
                            "The model returned no visible text this turn -- "
                            "check your API key, model ID, and network in Settings."
                        ),
                        "received_chars": max(1, _recv_len),
                    })
                    return

                _agent_model = getattr(agent, "model", "") or ""
                _result_model = ((payload or {}).get("result") or {}).get("model") or ""
                _effective_model = _agent_model or _result_model
                emit({
                    "type": "final",
                    "ok": True,
                    "proto": False,
                    "final_response": ft,
                    "received_chars": max(1, _recv_len),
                    "preview": (ft[:500] + "..." if len(ft) > 500 else ft) if ft else "",
                    "prompt_tokens": int((payload or {}).get("prompt_tokens") or 0),
                    "completion_tokens": int((payload or {}).get("completion_tokens") or 0),
                    "model": _effective_model,
                })
            except Exception as e:
                _log.exception("desk stream: run_conversation failed")
                emit({"type": "error", "ok": False, "error": "run_failed", "detail": str(e)})
            finally:
                try:
                    db.close()
                except Exception:
                    pass
                emit({"type": "done"})

        threading.Thread(target=worker, daemon=True, name=f"desk-chat-stream-{session_id[:8]}").start()

        async def event_generator():
            yield _desk_sse({
                "type": "start",
                "session_id": session_id,
                "progress": _desk_progress_response(agent),
            })
            last_progress = ""
            while True:
                try:
                    item = await asyncio.to_thread(event_q.get, True, 0.25)
                except queue.Empty:
                    progress = _desk_progress_response(agent)
                    encoded_progress = json.dumps(progress, sort_keys=True, default=str)
                    if encoded_progress != last_progress:
                        last_progress = encoded_progress
                        yield _desk_sse({"type": "progress", "session_id": session_id, "progress": progress})
                    else:
                        yield ": keepalive\n\n"
                    continue
                yield _desk_sse(item)
                if item.get("type") == "done":
                    break

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception:
        try:
            db.close()
        except Exception:
            pass
        raise


@app.post("/api/desk/chat-proto")
async def desk_chat_proto(request: Request):
    """HermesDesk: run a real AIAgent turn (same credentials + workspace as CLI).

    Request JSON: message (text), session_id (optional, for multi-turn),
    attachments (optional) list of {name, mime, data} with data base64-encoded.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid_body"}, status_code=400)
    message = (body.get("message") or "").strip()
    atts = _desk_parse_attachments_from_body(body)
    built = _desk_build_user_message(message, atts)
    if built is None:
        return JSONResponse(
            {"ok": False, "error": "empty_message", "detail": "message and attachments are both empty"},
            status_code=400,
        )
    user_payload, persist_um = built

    session_id = (body.get("session_id") or "").strip() or str(uuid.uuid4())

    from hermes_state import SessionDB

    db = SessionDB()
    try:
        try:
            raw_history = db.get_messages_as_conversation(session_id)
        except Exception as e:
            _log.exception("desk chat: load history failed")
            return JSONResponse(
                {"ok": False, "error": "session_db", "detail": str(e)},
                status_code=500,
            )
        history = [m for m in raw_history if m.get("role") != "session_meta"]

        try:
            agent = _desk_chat_build_agent(session_id, db)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": "config", "detail": str(e)}, status_code=503)
        except Exception as e:
            _log.exception("desk chat: agent init failed")
            return JSONResponse({"ok": False, "error": "agent_init", "detail": str(e)}, status_code=500)

        _recv_len = len(message) + sum(len(p.get("data") or b"") for p in atts)
        _log.info(
            "desk chat: session=%s user_chars~%d history_msgs=%d attachments=%d",
            session_id, _recv_len, len(history), len(atts),
        )
        try:
            _desk_prepare_active_agent(session_id, agent)
            payload = await asyncio.to_thread(
                _desk_chat_run_in_thread, agent, user_payload, history, session_id, persist_um
            )
        except Exception as e:
            _log.exception("desk chat: run_conversation failed")
            return JSONResponse({"ok": False, "error": "run_failed", "detail": str(e)}, status_code=500)

        result = (payload or {}).get("result") or {}
        final_text = _desk_extract_reply_text(result)
        if not final_text:
            try:
                db_msgs = db.get_messages_as_conversation(session_id)
                final_text = _desk_text_from_assistant_messages(db_msgs)
            except Exception:
                _log.debug("desk chat: could not re-read session messages for reply text", exc_info=True)

        ft = (final_text or "").strip()
        if ft in ("(empty)",):
            ft = ""
        if not ft and isinstance(result, dict):
            _log.warning(
                "desk chat: empty assistant text (session=%s completed=%s failed=%s keys=%s)",
                session_id, result.get("completed"), result.get("failed"), list(result.keys()),
            )
            return JSONResponse(
                {
                    "ok": False,
                    "error": "empty_model_response",
                    "detail": (
                        "The model returned no visible text this turn -- "
                        "check your API key, model ID, and network in Settings."
                    ),
                    "session_id": session_id,
                    "received_chars": max(1, _recv_len),
                }
            )

        _agent_model = getattr(agent, "model", "") or ""
        _result_model = ((payload or {}).get("result") or {}).get("model") or ""
        _effective_model = _agent_model or _result_model
        return JSONResponse(
            {
                "ok": True,
                "proto": False,
                "session_id": session_id,
                "final_response": ft,
                "received_chars": max(1, _recv_len),
                "preview": (ft[:500] + "..." if len(ft) > 500 else ft) if ft else "",
                "prompt_tokens": int((payload or {}).get("prompt_tokens") or 0),
                "completion_tokens": int((payload or {}).get("completion_tokens") or 0),
                "model": _effective_model,
            }
        )
    finally:
        try:
            db.close()
        except Exception:
            pass


@app.post("/api/desk/transcribe")
async def desk_transcribe(request: Request):
    """HermesDesk: transcribe audio to text using the configured STT provider.

    Request JSON: audio_b64 (base64-encoded audio), mime (MIME type string).
    Response JSON: {"transcript": "..."} on success.

    Data flow: the Rust shell POSTs raw base64 here; this handler decodes it,
    writes a temporary file, runs the synchronous transcribe_audio() in a
    thread-pool executor (to avoid blocking the event loop), then cleans up.

    The entire handler stays inside ``try``/``except`` so HermesDesk never leaks
    Starlette's plain-text ``Internal Server Error`` response (which Rust
    cannot parse as JSON).
    """
    tmp_path: Optional[str] = None
    try:
        from tools.transcription_tools import (
            _get_provider,
            _load_stt_config,
            is_stt_enabled,
            transcribe_audio,
        )

        _ensure_bundled_local_stt_env()
        _ensure_default_stt_provider()

        if not is_stt_enabled():
            return JSONResponse(
                {
                    "error": "stt_not_configured",
                    "detail": "请在设置中配置语音识别服务（Groq / OpenAI 等）。",
                },
                status_code=400,
            )

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "invalid_json", "detail": "Invalid JSON body"},
                status_code=400,
            )

        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid_body"}, status_code=400)

        audio_b64 = (body.get("audio_b64") or "").strip()
        mime = (body.get("mime") or "audio/webm").strip()

        if not audio_b64:
            return JSONResponse({"error": "missing_audio_b64"}, status_code=400)

        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception as exc:
            return JSONResponse(
                {"error": "invalid_base64", "detail": str(exc)}, status_code=400
            )

        _EXT_MAP = {
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "audio/mp4": ".mp4",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
        }
        base_mime = mime.split(";")[0].strip()
        ext = _EXT_MAP.get(base_mime, ".webm")

        stt_cfg = _load_stt_config()
        resolved = _get_provider(stt_cfg)

        if resolved == "none":
            return JSONResponse(
                {
                    "error": "no_stt_provider",
                    "detail": (
                        "未检测到可用的语音识别后端。请在 hermes-home/.env 或控制台 Keys 中配置 "
                        "GROQ_API_KEY、OPENAI_API_KEY（或 VOICE_TOOLS_OPENAI_KEY）、MISTRAL_API_KEY、"
                        "XAI_API_KEY 之一，或运行 python/build_bundle.ps1 打入 whisper.cpp 本地转写。"
                    ),
                },
                status_code=400,
            )

        tmp_parent: Optional[str] = None
        dvp = _desk_voice_paths_mod()
        if dvp is not None:
            vtmp = dvp.workspace_voice_tmp_dir()
            if vtmp is not None:
                vtmp.mkdir(parents=True, exist_ok=True)
                tmp_parent = str(vtmp)
        with tempfile.NamedTemporaryFile(
            suffix=ext, prefix="hermesdesk_stt_", delete=False, dir=tmp_parent
        ) as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_path = tmp_file.name

        loop = asyncio.get_running_loop()
        result: dict = await loop.run_in_executor(None, transcribe_audio, tmp_path)

        if not result.get("success"):
            err = result.get("error") or "transcription_failed"
            err_text = str(err)
            _log.warning("desk transcribe: STT failed: %s", err_text)
            if "STT_MODEL_MISSING" in err_text:
                return JSONResponse(
                    {
                        "error": "stt_model_missing",
                        "detail": "本地语音识别模型尚未下载，请先点击下载（约 60 MB）。",
                    },
                    status_code=400,
                )
            return JSONResponse(
                {"error": "transcription_failed", "detail": err_text},
                status_code=500,
            )

        transcript = (result.get("transcript") or "").strip()
        return JSONResponse({"transcript": transcript})

    except Exception as exc:
        _log.exception("desk transcribe: unexpected error")
        return JSONResponse(
            {
                "error": "transcribe_internal",
                "detail": f"{type(exc).__name__}: {exc}",
            },
            status_code=500,
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# Allow-list of env vars the desktop wizard's voice setup may write. Anything
# not in this set is silently dropped to prevent the renderer from poking at
# arbitrary keys via this endpoint.
_DESK_VOICE_ENV_ALLOWED = frozenset({
    # STT
    "GROQ_API_KEY",
    "VOICE_TOOLS_OPENAI_KEY",
    "OPENAI_API_KEY",
    "MISTRAL_API_KEY",
    "XAI_API_KEY",
    "HERMES_LOCAL_STT_COMMAND",
    "HERMES_LOCAL_STT_LANGUAGE",
    # TTS (mirrors CATALOG_TTS rows)
    "ELEVENLABS_API_KEY",
    "MINIMAX_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
})

_DESK_VOICE_PROVIDER_ALLOWED = {
    "stt": frozenset({"local", "local_command", "groq", "openai", "mistral", "xai"}),
    # Canonical ``tts.provider`` values per ``hermes_cli/config.py`` DEFAULT_CONFIG.tts.
    "tts": frozenset({
        "edge", "elevenlabs", "openai", "xai", "minimax", "mistral",
        "gemini", "neutts", "kittentts", "piper",
    }),
}


@app.post("/api/desk/save-voice-setup")
async def desk_save_voice_setup(request: Request):
    """HermesDesk: persist STT/TTS provider choice + secrets from the wizard.

    Request JSON: ``{section: "stt"|"tts", provider: str|null, env: {KEY: VALUE, ...}}``

    - ``provider`` (when non-null) is written to ``config.yaml`` at
      ``<section>.provider``; a value of ``null`` leaves the existing setting
      untouched (e.g. user picked "skip").
    - ``env`` entries are written via ``save_env_value`` (which both updates
      ``hermes-home/.env`` on disk and refreshes ``os.environ`` so the running
      process picks them up without a restart). Keys outside an internal
      allow-list are silently dropped; empty values are skipped (we never
      accidentally clear a saved key with a blank field).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid_body"}, status_code=400)

    section = (body.get("section") or "").strip()
    if section not in ("stt", "tts"):
        return JSONResponse({"error": "invalid_section"}, status_code=400)

    provider_raw = body.get("provider")
    provider: Optional[str] = None
    if isinstance(provider_raw, str):
        cand = provider_raw.strip()
        if cand:
            if cand not in _DESK_VOICE_PROVIDER_ALLOWED[section]:
                return JSONResponse(
                    {"error": "invalid_provider", "detail": cand},
                    status_code=400,
                )
            provider = cand

    env = body.get("env") or {}
    if not isinstance(env, dict):
        return JSONResponse({"error": "invalid_env"}, status_code=400)

    saved_env: List[str] = []
    for k_raw, v_raw in env.items():
        if not isinstance(k_raw, str) or not isinstance(v_raw, str):
            continue
        key = k_raw.strip()
        val = v_raw  # don't strip secret bodies; user might intentionally have leading/trailing whitespace
        if not key or not val:
            continue
        if key not in _DESK_VOICE_ENV_ALLOWED:
            continue
        try:
            save_env_value(key, val)
            saved_env.append(key)
        except Exception as exc:
            _log.warning("save-voice-setup: save_env_value(%s) failed: %s", key, exc)

    saved_provider = False
    if provider:
        try:
            cfg = load_config()
            sect = cfg.setdefault(section, {})
            if not isinstance(sect, dict):
                sect = {}
                cfg[section] = sect
            sect["provider"] = provider
            save_config(cfg)
            saved_provider = True
        except Exception as exc:
            _log.warning("save-voice-setup: save_config(%s.provider) failed: %s", section, exc)
            return JSONResponse(
                {"error": "save_config_failed", "detail": str(exc)},
                status_code=500,
            )

    return JSONResponse({
        "ok": True,
        "section": section,
        "saved_provider": saved_provider,
        "saved_env": saved_env,
    })


# ---------------------------------------------------------------------------
# HermesDesk TTS endpoint
# ---------------------------------------------------------------------------


@app.post("/api/desk/tts")
async def desk_tts(request: Request):
    """HermesDesk: generate TTS audio for the given text.

    Returns the audio file directly (MP3). The caller (Tauri shell proxy)
    streams the bytes to the webview for playback.
    """
    import json
    from tools.tts_tool import text_to_speech_tool

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid_body"}, status_code=400)

    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "text_required"}, status_code=400)

    # Run in thread pool -- text_to_speech_tool is synchronous
    result_str = await asyncio.to_thread(text_to_speech_tool, text=text)
    try:
        result = json.loads(result_str)
    except Exception:
        _log.exception("desk_tts: failed to parse tool result")
        return JSONResponse({"error": "parse_failed"}, status_code=500)

    if not result.get("success"):
        err = result.get("error", "tts_failed")
        return JSONResponse({"ok": False, "error": err}, status_code=500)

    file_path = result["file_path"]
    if not os.path.isfile(file_path):
        return JSONResponse({"error": "file_not_found"}, status_code=500)

    return FileResponse(file_path, media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# Local STT model lazy-download (HermesDesk only)
#
# HermesDesk ships ``stt-bin/whisper-cli.exe`` + ``ffmpeg.exe`` in the MSI but
# leaves the ~57 MB GGML model out so the installer stays small. The renderer
# polls /api/desk/stt-model/status; if the model is missing it shows a "first
# time setup, download ~60 MB?" prompt and POSTs to /download.
#
# Primary store: ``<HERMESDESK_WORKSPACE>/.hermesdesk/stt-models/`` (same tree as
# the agent default workspace). Legacy: ``HERMESDESK_DATA_DIR`` or
# ``%LOCALAPPDATA%\\HermesDesk\\stt-models`` — still discovered if the file
# exists so older installs work until re-download. Survives MSI upgrades
# (runtime/ is overwritten on each install).
# ---------------------------------------------------------------------------

# region agent log
def _agent_dbg_stt(line: dict) -> None:
    """Append one NDJSON line for debug session 914e79.

    Tries several paths so logs are findable in dev vs MSI bundle:
      * ``%HERMESDESK_DATA_DIR%/logs/`` (same folder as hermesdesk.log)
      * repo / runtime parent (legacy single-path behavior)
      * system temp as last resort
    """
    import json
    import time

    line.setdefault("sessionId", "914e79")
    line.setdefault("timestamp", int(time.time() * 1000))

    candidates: List[Path] = []
    data_dir = (os.environ.get("HERMESDESK_DATA_DIR") or "").strip()
    if data_dir:
        candidates.append(Path(data_dir) / "logs" / "debug-914e79.log")
    # Dev: hermes_core/hermes_cli/web_server.py -> parents[2] == repo root
    try:
        candidates.append(Path(__file__).resolve().parents[2] / "debug-914e79.log")
    except Exception:
        pass
    try:
        candidates.append(get_hermes_home() / "logs" / "debug-914e79.log")
    except Exception:
        pass
    candidates.append(Path(tempfile.gettempdir()) / "hermesdesk-debug-914e79.log")

    payload = json.dumps(line, ensure_ascii=False) + "\n"
    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as _f:
                _f.write(payload)
            return
        except Exception:
            continue


# endregion

_DESK_STT_MODEL_FILENAME = "ggml-base-q5_1.bin"
# Pinned mirror of the upstream HuggingFace snapshot. The base-q5_1 model is
# ~57 MB and Q5_1-quantised so it runs on a typical laptop CPU at ~real-time.
# Both URLs point at the exact same blob; HF mirror is a community China
# proxy used as a fallback when the primary is blocked.
_DESK_STT_MODEL_URLS = (
    f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{_DESK_STT_MODEL_FILENAME}",
    f"https://hf-mirror.com/ggerganov/whisper.cpp/resolve/main/{_DESK_STT_MODEL_FILENAME}",
)
# SHA-256 of the published file. Empty string skips verification (acceptable
# for dev; pin for production releases). The endpoint logs a warning when
# unverified so the bundle owner notices.
_DESK_STT_MODEL_SHA256 = ""


def _desk_voice_paths_mod():
    try:
        import desk_voice_paths  # type: ignore[import-untyped]
    except ImportError:
        return None
    return desk_voice_paths


def _desk_stt_model_path() -> Path:
    """Canonical GGML path for downloads and API ``path`` when the file is absent."""
    dvm = _desk_voice_paths_mod()
    if dvm is not None:
        return dvm.canonical_stt_model_path(
            _DESK_STT_MODEL_FILENAME, no_env_fallback_dir=get_hermes_home()
        )
    data_dir = os.environ.get("HERMESDESK_DATA_DIR") or os.environ.get(
        "LOCALAPPDATA"
    )
    if not data_dir:
        return get_hermes_home() / "stt-models" / _DESK_STT_MODEL_FILENAME
    base = Path(data_dir)
    if "LOCALAPPDATA" in os.environ and base == Path(os.environ["LOCALAPPDATA"]):
        base = base / "HermesDesk"
    return base / "stt-models" / _DESK_STT_MODEL_FILENAME


def _desk_stt_model_resolved() -> tuple[Path, bool]:
    """Return ``(path, downloaded)`` for status: on-disk file if any, else canonical."""
    dvm = _desk_voice_paths_mod()
    if dvm is not None:
        home = get_hermes_home()
        found = dvm.resolve_existing_stt_model(
            _DESK_STT_MODEL_FILENAME, no_env_fallback_dir=home
        )
        if found is not None:
            return found, True
        return (
            dvm.canonical_stt_model_path(
                _DESK_STT_MODEL_FILENAME, no_env_fallback_dir=home
            ),
            False,
        )
    p = _desk_stt_model_path()
    try:
        p.stat()
        return p, True
    except OSError:
        return p, False


@app.get("/api/desk/stt-model/status")
async def desk_stt_model_status():
    """Report whether the local STT model is downloaded.

    Frontend calls this before recording so it can prompt the user to
    download once. Returns ``downloaded`` and ``size`` so the UI can also
    show a stale/corrupt-file warning if the size is way off.
    """
    path, downloaded = _desk_stt_model_resolved()
    if not downloaded:
        return JSONResponse({
            "downloaded": False,
            "size": 0,
            "path": str(path),
        })
    try:
        st = path.stat()
        return JSONResponse({
            "downloaded": True,
            "size": int(st.st_size),
            "path": str(path),
        })
    except OSError as exc:
        return JSONResponse(
            {"error": "stat_failed", "detail": str(exc)},
            status_code=500,
        )


def _download_stt_model_blocking(dest: Path) -> Tuple[bool, Dict[str, Any]]:
    """Stream the GGML model to ``dest`` (atomic + verified).

    Tries each URL in ``_DESK_STT_MODEL_URLS`` in order. Writes to
    ``<dest>.tmp``, fsyncs, then renames over the final path. Verifies
    SHA-256 if pinned. Returns ``(ok, info_dict)``; on failure ``info_dict``
    contains ``error``/``detail`` keys.

    Synchronous on purpose so the FastAPI handler can offload it via
    ``run_in_executor``.
    """
    # region agent log
    _agent_dbg_stt(
        {
            "hypothesisId": "H1",
            "location": "_download_stt_model_blocking:enter",
            "message": "blocking worker started",
            "data": {"dest": str(dest)},
        }
    )
    # endregion
    import hashlib

    import httpx

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        # region agent log
        _agent_dbg_stt(
            {
                "hypothesisId": "H1",
                "location": "_download_stt_model_blocking:mkdir",
                "message": "mkdir failed (uncaught would yield plain 500)",
                "data": {"type": type(exc).__name__, "detail": repr(exc)},
            }
        )
        # endregion
        raise

    # region agent log
    _agent_dbg_stt(
        {
            "hypothesisId": "H1",
            "location": "_download_stt_model_blocking:mkdir_ok",
            "message": "parent dir ready",
            "data": {"parent": str(dest.parent)},
        }
    )
    # endregion

    tmp = dest.with_suffix(dest.suffix + ".tmp")

    last_err: Optional[str] = None
    for url in _DESK_STT_MODEL_URLS:
        try:
            hasher = hashlib.sha256() if _DESK_STT_MODEL_SHA256 else None
            total = 0
            with httpx.Client(
                timeout=httpx.Timeout(600.0, connect=30.0),
                follow_redirects=True,
            ) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        last_err = f"{url}: HTTP {resp.status_code}"
                        _log.warning("stt-model download: %s", last_err)
                        continue
                    with open(tmp, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=512 * 1024):
                            if not chunk:
                                continue
                            f.write(chunk)
                            total += len(chunk)
                            if hasher is not None:
                                hasher.update(chunk)
                        f.flush()
                        try:
                            os.fsync(f.fileno())
                        except OSError:
                            pass
            # SHA-256 check (skipped if not pinned).
            if hasher is not None:
                got = hasher.hexdigest().lower()
                expected = _DESK_STT_MODEL_SHA256.lower()
                if got != expected:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                    last_err = f"sha256 mismatch (got {got}, expected {expected})"
                    _log.warning("stt-model download: %s", last_err)
                    continue
            elif total < 1_000_000:
                # No hash pinned, but anything <1 MB is clearly not the
                # base-q5_1 model (real file is ~57 MB). Reject so a partial
                # / error-page download can't masquerade as success.
                try:
                    tmp.unlink()
                except OSError:
                    pass
                last_err = f"download too small ({total} bytes); likely not the model"
                _log.warning("stt-model download: %s", last_err)
                continue
            # Atomic rename over destination.
            os.replace(tmp, dest)
            # region agent log
            _agent_dbg_stt(
                {
                    "hypothesisId": "H2",
                    "location": "_download_stt_model_blocking:success",
                    "message": "download ok",
                    "data": {"size": total, "source": url},
                }
            )
            # endregion
            return True, {"size": total, "path": str(dest), "source": url}
        except Exception as exc:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            last_err = f"{url}: {exc}"
            _log.warning("stt-model download: %s", last_err)
            continue

    # region agent log
    _agent_dbg_stt(
        {
            "hypothesisId": "H2",
            "location": "_download_stt_model_blocking:all_urls_failed",
            "message": "returning controlled failure dict",
            "data": {"last_err": last_err or "unknown"},
        }
    )
    # endregion
    return False, {"error": "download_failed", "detail": last_err or "unknown"}


@app.post("/api/desk/stt-model/download")
async def desk_stt_model_download():
    """Download the local STT model (one-shot; idempotent if already present).

    Returns ``{ "ok": true, "size": ..., "path": ... }`` on success or
    ``{ "error": "...", "detail": "..." }`` with a 500 on failure. The
    download itself runs in the default thread-pool executor so the FastAPI
    event loop stays responsive.
    """
    import traceback

    try:
        dest = _desk_stt_model_path()
        # region agent log
        _agent_dbg_stt(
            {
                "hypothesisId": "H4",
                "location": "desk_stt_model_download:entry",
                "message": "POST /api/desk/stt-model/download",
                "data": {"dest": str(dest), "exists": dest.exists()},
            }
        )
        # endregion
        if dest.exists():
            try:
                size = dest.stat().st_size
            except OSError:
                size = 0
            return JSONResponse({"ok": True, "size": size, "path": str(dest), "already": True})

        if not _DESK_STT_MODEL_SHA256:
            _log.warning(
                "stt-model download proceeding without SHA-256 verification "
                "(_DESK_STT_MODEL_SHA256 not pinned); set it before shipping."
            )

        try:
            loop = asyncio.get_running_loop()
            # region agent log
            _agent_dbg_stt(
                {
                    "hypothesisId": "H4",
                    "location": "desk_stt_model_download:before_executor",
                    "message": "scheduling run_in_executor",
                    "data": {},
                }
            )
            # endregion
            ok, info = await loop.run_in_executor(None, _download_stt_model_blocking, dest)
        except Exception as exc:
            tb = traceback.format_exc()
            # region agent log
            _agent_dbg_stt(
                {
                    "hypothesisId": "H3",
                    "location": "desk_stt_model_download:executor_exception",
                    "message": "run_in_executor raised; return JSON instead of plain 500",
                    "data": {
                        "type": type(exc).__name__,
                        "detail": repr(exc),
                        "traceback": tb[:6000],
                    },
                }
            )
            # endregion
            _log.exception("stt-model download: executor failed")
            return JSONResponse(
                {
                    "error": "stt_model_download_executor_failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                },
                status_code=500,
            )

        # region agent log
        _agent_dbg_stt(
            {
                "hypothesisId": "H5",
                "location": "desk_stt_model_download:after_executor",
                "message": "executor returned",
                "data": {
                    "ok": ok,
                    "info_keys": list(info.keys()) if isinstance(info, dict) else "n/a",
                },
            }
        )
        # endregion
        if not ok:
            return JSONResponse(info, status_code=500)
        body = {"ok": True, **info}
        return JSONResponse(body)
    except Exception as exc:
        tb = traceback.format_exc()
        # region agent log
        _agent_dbg_stt(
            {
                "hypothesisId": "H5",
                "location": "desk_stt_model_download:outer_exception",
                "message": "unexpected failure in handler",
                "data": {
                    "type": type(exc).__name__,
                    "detail": repr(exc),
                    "traceback": tb[:6000],
                },
            }
        )
        # endregion
        _log.exception("stt-model download handler failed")
        return JSONResponse(
            {
                "error": "stt_model_download_internal",
                "detail": f"{type(exc).__name__}: {exc}",
            },
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Default STT provider auto-selection (HermesDesk only)
#
# When the user has never touched STT settings AND no cloud key is exported
# in env, we set ``stt.provider = local_command`` so transcribe_audio uses
# the bundled whisper.cpp wrapper (configured by desktop_entrypoint.py).
# Idempotent: only writes once per process; never overwrites a pre-existing
# config or an explicit user choice.
# ---------------------------------------------------------------------------
_DESK_STT_BUNDLE_ENV_WIRED = False


def _ensure_bundled_local_stt_env() -> None:
    """HermesDesk: set ``HERMES_LOCAL_STT_COMMAND`` from the runtime bundle.

    ``desktop_entrypoint._wire_local_stt`` already does this before importing
    ``web_server``.  If that step skipped (e.g. ``stt-bin`` missing in an older
    bundle, then added after ``build_bundle`` without restarting) or the env
    was lost, we mirror the same wiring here using ``HERMESDESK_BUNDLE_DIR``
    (set by the Tauri shell for the embedded Python).

    This allows ``stt.provider: local`` to fall through to ``local_command`` in
    ``transcription_tools._get_provider`` when faster-whisper is not installed
    (the default HermesDesk bundle).
    """
    global _DESK_STT_BUNDLE_ENV_WIRED
    if _DESK_STT_BUNDLE_ENV_WIRED:
        return
    if os.environ.get("HERMES_LOCAL_STT_COMMAND", "").strip():
        _DESK_STT_BUNDLE_ENV_WIRED = True
        return
    bundle = (os.environ.get("HERMESDESK_BUNDLE_DIR") or "").strip()
    if not bundle:
        _DESK_STT_BUNDLE_ENV_WIRED = True
        return
    root = Path(bundle)
    wrapper = root / "stt_wrapper.py"
    whisper = root / "stt-bin" / "whisper-cli.exe"
    if not wrapper.is_file() or not whisper.is_file():
        _log.info(
            "bundled whisper.cpp not found under HERMESDESK_BUNDLE_DIR "
            "(wrapper_ok=%s whisper_ok=%s); local STT unavailable until "
            "python/build_bundle.ps1 stages stt-bin/",
            wrapper.is_file(),
            whisper.is_file(),
        )
        _DESK_STT_BUNDLE_ENV_WIRED = True
        return
    os.environ["HERMES_LOCAL_STT_COMMAND"] = (
        f'"{sys.executable}" "{wrapper}" '
        f"{{input_path}} {{output_dir}} {{language}} {{model}}"
    )
    os.environ.setdefault("HERMES_LOCAL_STT_LANGUAGE", "auto")
    _log.info("HERMES_LOCAL_STT_COMMAND wired from bundle (second-chance web_server)")
    _DESK_STT_BUNDLE_ENV_WIRED = True


_DESK_STT_DEFAULT_APPLIED = False
_DESK_STT_CLOUD_KEY_ENV_VARS = (
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "VOICE_TOOLS_OPENAI_KEY",
    "MISTRAL_API_KEY",
    "XAI_API_KEY",
)


def _ensure_default_stt_provider() -> None:
    """If neither config nor env names a cloud STT, pick ``local_command``.

    Runs once per process (idempotent flag) on the first /api/desk/transcribe
    call, so the user sees a working mic even if they never opened the
    onboarding wizard.
    """
    global _DESK_STT_DEFAULT_APPLIED
    if _DESK_STT_DEFAULT_APPLIED:
        return
    _DESK_STT_DEFAULT_APPLIED = True

    # Only when the wrapper is wired up — otherwise we'd just be promising a
    # local STT we can't actually run.
    if not os.environ.get("HERMES_LOCAL_STT_COMMAND", "").strip():
        return

    try:
        cfg = load_config()
    except Exception as exc:
        _log.warning("ensure_default_stt_provider: load_config failed: %s", exc)
        return

    stt = cfg.get("stt") if isinstance(cfg, dict) else None
    if isinstance(stt, dict) and stt.get("provider"):
        return  # User already chose something; respect it.

    if any(os.environ.get(k, "").strip() for k in _DESK_STT_CLOUD_KEY_ENV_VARS):
        return  # Cloud key present — let _get_provider auto-resolve to it.

    try:
        new_stt = dict(stt) if isinstance(stt, dict) else {}
        new_stt["provider"] = "local_command"
        new_stt.setdefault("model", "base")
        cfg["stt"] = new_stt
        save_config(cfg)
        _log.info("ensure_default_stt_provider: set stt.provider=local_command")
    except Exception as exc:
        _log.warning("ensure_default_stt_provider: save_config failed: %s", exc)


@app.get("/api/actions/{name}/status")
async def get_action_status(name: str, lines: int = 200):
    """Tail an action log and report whether the process is still running."""
    log_file_name = _ACTION_LOG_FILES.get(name)
    if log_file_name is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {name}")

    log_path = _ACTION_LOG_DIR / log_file_name
    tail = _tail_lines(log_path, min(max(lines, 1), 2000))

    proc = _ACTION_PROCS.get(name)
    if proc is None:
        running = False
        exit_code: Optional[int] = None
        pid: Optional[int] = None
    else:
        exit_code = proc.poll()
        running = exit_code is None
        pid = proc.pid

    return {
        "name": name,
        "running": running,
        "exit_code": exit_code,
        "pid": pid,
        "lines": tail,
    }


@app.get("/api/sessions")
async def get_sessions(limit: int = 20, offset: int = 0, source: str = None):
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=limit, offset=offset, source=source)
            total = db.session_count()
            now = time.time()
            for s in sessions:
                s["is_active"] = (
                    s.get("ended_at") is None
                    and (now - s.get("last_active", s.get("started_at", 0))) < 300
                )
            return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}
        finally:
            db.close()
    except Exception:
        _log.exception("GET /api/sessions failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/sessions/search")
async def search_sessions(q: str = "", limit: int = 20):
    """Full-text search across session message content using FTS5."""
    if not q or not q.strip():
        return {"results": []}
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        try:
            # Auto-add prefix wildcards so partial words match
            # e.g. "nimb" → "nimb*" matches "nimby"
            # Preserve quoted phrases and existing wildcards as-is
            import re
            terms = []
            for token in re.findall(r'"[^"]*"|\S+', q.strip()):
                if token.startswith('"') or token.endswith("*"):
                    terms.append(token)
                else:
                    terms.append(token + "*")
            prefix_query = " ".join(terms)
            matches = db.search_messages(query=prefix_query, limit=limit)
            # Group by session_id — return unique sessions with their best snippet
            seen: dict = {}
            for m in matches:
                sid = m["session_id"]
                if sid not in seen:
                    seen[sid] = {
                        "session_id": sid,
                        "snippet": m.get("snippet", ""),
                        "role": m.get("role"),
                        "source": m.get("source"),
                        "model": m.get("model"),
                        "session_started": m.get("session_started"),
                    }
            return {"results": list(seen.values())}
        finally:
            db.close()
    except Exception:
        _log.exception("GET /api/sessions/search failed")
        raise HTTPException(status_code=500, detail="Search failed")


def _normalize_config_for_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize config for the web UI.

    Hermes supports ``model`` as either a bare string (``"anthropic/claude-sonnet-4"``)
    or a dict (``{default: ..., provider: ..., base_url: ...}``).  The schema is built
    from DEFAULT_CONFIG where ``model`` is a string, but user configs often have the
    dict form.  Normalize to the string form so the frontend schema matches.

    Also surfaces ``model_context_length`` as a top-level field so the web UI can
    display and edit it.  A value of 0 means "auto-detect".
    """
    config = dict(config)  # shallow copy
    model_val = config.get("model")
    if isinstance(model_val, dict):
        # Extract context_length before flattening the dict
        ctx_len = model_val.get("context_length", 0)
        config["model"] = model_val.get("default", model_val.get("name", ""))
        config["model_context_length"] = ctx_len if isinstance(ctx_len, int) else 0
    else:
        config["model_context_length"] = 0
    return config


@app.get("/api/config")
async def get_config():
    config = _normalize_config_for_web(load_config())
    # Strip internal keys that the frontend shouldn't see or send back
    return {k: v for k, v in config.items() if not k.startswith("_")}


@app.get("/api/config/defaults")
async def get_defaults():
    return DEFAULT_CONFIG


@app.get("/api/config/schema")
async def get_schema():
    return {"fields": CONFIG_SCHEMA, "category_order": _CATEGORY_ORDER}


_EMPTY_MODEL_INFO: dict = {
    "model": "",
    "provider": "",
    "auto_context_length": 0,
    "config_context_length": 0,
    "effective_context_length": 0,
    "capabilities": {},
}


@app.get("/api/model/info")
def get_model_info():
    """Return resolved model metadata for the currently configured model.

    Calls the same context-length resolution chain the agent uses, so the
    frontend can display "Auto-detected: 200K" alongside the override field.
    Also returns model capabilities (vision, reasoning, tools) when available.
    """
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")

        # Extract model name and provider from the config
        if isinstance(model_cfg, dict):
            model_name = model_cfg.get("default", model_cfg.get("name", ""))
            provider = model_cfg.get("provider", "")
            base_url = model_cfg.get("base_url", "")
            config_ctx = model_cfg.get("context_length")
        else:
            model_name = str(model_cfg) if model_cfg else ""
            provider = ""
            base_url = ""
            config_ctx = None

        if not model_name:
            return dict(_EMPTY_MODEL_INFO, provider=provider)

        # Resolve auto-detected context length (pass config_ctx=None to get
        # purely auto-detected value, then separately report the override)
        try:
            from agent.model_metadata import get_model_context_length
            auto_ctx = get_model_context_length(
                model=model_name,
                base_url=base_url,
                provider=provider,
                config_context_length=None,  # ignore override — we want auto value
            )
        except Exception:
            auto_ctx = 0

        config_ctx_int = 0
        if isinstance(config_ctx, int) and config_ctx > 0:
            config_ctx_int = config_ctx

        # Effective is what the agent actually uses
        effective_ctx = config_ctx_int if config_ctx_int > 0 else auto_ctx

        # Try to get model capabilities from models.dev
        caps = {}
        try:
            from agent.models_dev import get_model_capabilities
            mc = get_model_capabilities(provider=provider, model=model_name)
            if mc is not None:
                caps = {
                    "supports_tools": mc.supports_tools,
                    "supports_vision": mc.supports_vision,
                    "supports_reasoning": mc.supports_reasoning,
                    "context_window": mc.context_window,
                    "max_output_tokens": mc.max_output_tokens,
                    "model_family": mc.model_family,
                }
        except Exception:
            pass

        return {
            "model": model_name,
            "provider": provider,
            "auto_context_length": auto_ctx,
            "config_context_length": config_ctx_int,
            "effective_context_length": effective_ctx,
            "capabilities": caps,
        }
    except Exception:
        _log.exception("GET /api/model/info failed")
        return dict(_EMPTY_MODEL_INFO)


# ---------------------------------------------------------------------------
# Model assignment — pick provider+model for main slot or auxiliary slots.
# Mirrors the model.options JSON-RPC from tui_gateway but uses REST so the
# Models page (which has no chat PTY open) can drive it.
# ---------------------------------------------------------------------------

# Canonical auxiliary task slots. Keep in sync with DEFAULT_CONFIG["auxiliary"]
# in hermes_cli/config.py — listed here for deterministic ordering in the UI.
_AUX_TASK_SLOTS: Tuple[str, ...] = (
    "vision",
    "web_extract",
    "compression",
    "session_search",
    "skills_hub",
    "approval",
    "mcp",
    "title_generation",
    "curator",
)


@app.get("/api/model/options")
def get_model_options():
    """Return authenticated providers + their curated model lists.

    REST equivalent of the ``model.options`` JSON-RPC on tui_gateway, so the
    dashboard Models page can render the picker without a live chat session.
    The response shape matches ``model.options`` 1:1 so ``ModelPickerDialog``
    can share the same types.
    """
    try:
        from hermes_cli.model_switch import list_authenticated_providers

        cfg = load_config()
        model_cfg = cfg.get("model", {})
        if isinstance(model_cfg, dict):
            current_model = model_cfg.get("default", model_cfg.get("name", "")) or ""
            current_provider = model_cfg.get("provider", "") or ""
            current_base_url = model_cfg.get("base_url", "") or ""
        else:
            current_model = str(model_cfg) if model_cfg else ""
            current_provider = ""
            current_base_url = ""

        user_providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
        custom_providers = (
            cfg.get("custom_providers")
            if isinstance(cfg.get("custom_providers"), list)
            else []
        )

        providers = list_authenticated_providers(
            current_provider=current_provider,
            current_base_url=current_base_url,
            current_model=current_model,
            user_providers=user_providers,
            custom_providers=custom_providers,
            max_models=50,
        )
        return {
            "providers": providers,
            "model": current_model,
            "provider": current_provider,
        }
    except Exception:
        _log.exception("GET /api/model/options failed")
        raise HTTPException(status_code=500, detail="Failed to list model options")


@app.get("/api/model/auxiliary")
def get_auxiliary_models():
    """Return current auxiliary task assignments.

    Shape:
      {
        "tasks": [
          {"task": "vision", "provider": "auto", "model": "", "base_url": ""},
          ...
        ],
        "main": {"provider": "deepseek", "model": "deepseek-v4-flash"},
      }
    """
    try:
        cfg = load_config()
        aux_cfg = cfg.get("auxiliary", {})
        if not isinstance(aux_cfg, dict):
            aux_cfg = {}

        tasks = []
        for slot in _AUX_TASK_SLOTS:
            slot_cfg = aux_cfg.get(slot, {}) if isinstance(aux_cfg.get(slot), dict) else {}
            tasks.append({
                "task": slot,
                "provider": str(slot_cfg.get("provider", "auto") or "auto"),
                "model": str(slot_cfg.get("model", "") or ""),
                "base_url": str(slot_cfg.get("base_url", "") or ""),
            })

        model_cfg = cfg.get("model", {})
        if isinstance(model_cfg, dict):
            main = {
                "provider": str(model_cfg.get("provider", "") or ""),
                "model": str(model_cfg.get("default", model_cfg.get("name", "")) or ""),
            }
        else:
            main = {"provider": "", "model": str(model_cfg) if model_cfg else ""}

        return {"tasks": tasks, "main": main}
    except Exception:
        _log.exception("GET /api/model/auxiliary failed")
        raise HTTPException(status_code=500, detail="Failed to read auxiliary config")


@app.post("/api/model/set")
async def set_model_assignment(body: ModelAssignment):
    """Assign a model to the main slot or an auxiliary task slot.

    Writes to ``~/.hermes/config.yaml`` — applies to **new** sessions only.
    The currently running chat PTY (if any) is not affected; use the
    ``/model`` slash command inside a chat to hot-swap that specific session.
    """
    scope = (body.scope or "").strip().lower()
    provider = (body.provider or "").strip()
    model = (body.model or "").strip()
    task = (body.task or "").strip().lower()

    if scope not in ("main", "auxiliary"):
        raise HTTPException(status_code=400, detail="scope must be 'main' or 'auxiliary'")

    try:
        cfg = load_config()

        if scope == "main":
            if not provider or not model:
                raise HTTPException(status_code=400, detail="provider and model required for main")
            model_cfg = cfg.get("model", {})
            if not isinstance(model_cfg, dict):
                model_cfg = {}
            model_cfg["provider"] = provider
            model_cfg["default"] = model
            # Clear stale base_url so the resolver picks the provider's own default.
            if "base_url" in model_cfg and model_cfg.get("base_url"):
                model_cfg["base_url"] = ""
            # Also clear hardcoded context_length override — new model may have
            # a different context window.
            if "context_length" in model_cfg:
                model_cfg.pop("context_length", None)
            cfg["model"] = model_cfg
            save_config(cfg)
            return {"ok": True, "scope": "main", "provider": provider, "model": model}

        # scope == "auxiliary"
        aux = cfg.get("auxiliary")
        if not isinstance(aux, dict):
            aux = {}

        if task == "__reset__":
            # Reset every slot to provider="auto", model="" — keeps other fields intact.
            for slot in _AUX_TASK_SLOTS:
                slot_cfg = aux.get(slot)
                if not isinstance(slot_cfg, dict):
                    slot_cfg = {}
                slot_cfg["provider"] = "auto"
                slot_cfg["model"] = ""
                aux[slot] = slot_cfg
            cfg["auxiliary"] = aux
            save_config(cfg)
            return {"ok": True, "scope": "auxiliary", "reset": True}

        if not provider:
            raise HTTPException(status_code=400, detail="provider required for auxiliary")

        targets = [task] if task else list(_AUX_TASK_SLOTS)
        for slot in targets:
            if slot not in _AUX_TASK_SLOTS:
                raise HTTPException(status_code=400, detail=f"unknown auxiliary task: {slot}")
            slot_cfg = aux.get(slot)
            if not isinstance(slot_cfg, dict):
                slot_cfg = {}
            slot_cfg["provider"] = provider
            slot_cfg["model"] = model
            aux[slot] = slot_cfg

        cfg["auxiliary"] = aux
        save_config(cfg)
        return {
            "ok": True,
            "scope": "auxiliary",
            "tasks": targets,
            "provider": provider,
            "model": model,
        }
    except HTTPException:
        raise
    except Exception:
        _log.exception("POST /api/model/set failed")
        raise HTTPException(status_code=500, detail="Failed to save model assignment")




def _denormalize_config_from_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Reverse _normalize_config_for_web before saving.

    Reconstructs ``model`` as a dict by reading the current on-disk config
    to recover model subkeys (provider, base_url, api_mode, etc.) that were
    stripped from the GET response.  The frontend only sees model as a flat
    string; the rest is preserved transparently.

    Also handles ``model_context_length`` — writes it back into the model dict
    as ``context_length``.  A value of 0 or absent means "auto-detect" (omitted
    from the dict so get_model_context_length() uses its normal resolution).
    """
    config = dict(config)
    # Remove any _model_meta that might have leaked in (shouldn't happen
    # with the stripped GET response, but be defensive)
    config.pop("_model_meta", None)

    # Extract and remove model_context_length before processing model
    ctx_override = config.pop("model_context_length", 0)
    if not isinstance(ctx_override, int):
        try:
            ctx_override = int(ctx_override)
        except (TypeError, ValueError):
            ctx_override = 0

    model_val = config.get("model")
    if isinstance(model_val, str) and model_val:
        # Read the current disk config to recover model subkeys
        try:
            disk_config = load_config()
            disk_model = disk_config.get("model")
            if isinstance(disk_model, dict):
                # Preserve all subkeys, update default with the new value
                disk_model["default"] = model_val
                # Write context_length into the model dict (0 = remove/auto)
                if ctx_override > 0:
                    disk_model["context_length"] = ctx_override
                else:
                    disk_model.pop("context_length", None)
                config["model"] = disk_model
            else:
                # Model was previously a bare string — upgrade to dict if
                # user is setting a context_length override
                if ctx_override > 0:
                    config["model"] = {
                        "default": model_val,
                        "context_length": ctx_override,
                    }
        except Exception:
            pass  # can't read disk config — just use the string form
    return config


@app.put("/api/config")
async def update_config(body: ConfigUpdate):
    try:
        save_config(_denormalize_config_from_web(body.config))
        return {"ok": True}
    except Exception:
        _log.exception("PUT /api/config failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/env")
async def get_env_vars():
    env_on_disk = load_env()
    result = {}
    for var_name, info in OPTIONAL_ENV_VARS.items():
        value = env_on_disk.get(var_name)
        result[var_name] = {
            "is_set": bool(value),
            "redacted_value": redact_key(value) if value else None,
            "description": info.get("description", ""),
            "url": info.get("url"),
            "category": info.get("category", ""),
            "is_password": info.get("password", False),
            "tools": info.get("tools", []),
            "advanced": info.get("advanced", False),
        }
    return result


@app.put("/api/env")
async def set_env_var(body: EnvVarUpdate):
    try:
        save_env_value(body.key, body.value)
        return {"ok": True, "key": body.key}
    except Exception:
        _log.exception("PUT /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/api/env")
async def remove_env_var(body: EnvVarDelete):
    try:
        removed = remove_env_value(body.key)
        if not removed:
            raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")
        return {"ok": True, "key": body.key}
    except HTTPException:
        raise
    except Exception:
        _log.exception("DELETE /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/env/reveal")
async def reveal_env_var(body: EnvVarReveal, request: Request):
    """Return the real (unredacted) value of a single env var.

    Protected by:
    - Ephemeral session token (generated per server start, injected into SPA)
    - Rate limiting (max 5 reveals per 30s window)
    - Audit logging
    """
    # --- Token check ---
    _require_token(request)

    # --- Rate limit ---
    now = time.time()
    cutoff = now - _REVEAL_WINDOW_SECONDS
    _reveal_timestamps[:] = [t for t in _reveal_timestamps if t > cutoff]
    if len(_reveal_timestamps) >= _REVEAL_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many reveal requests. Try again shortly.")
    _reveal_timestamps.append(now)

    # --- Reveal ---
    env_on_disk = load_env()
    value = env_on_disk.get(body.key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")

    _log.info("env/reveal: %s", body.key)
    return {"key": body.key, "value": value}


# ---------------------------------------------------------------------------
# OAuth provider endpoints — status + disconnect (Phase 1)
# ---------------------------------------------------------------------------
#
# Phase 1 surfaces *which OAuth providers exist* and whether each is
# connected, plus a disconnect button. The actual login flow (PKCE for
# Anthropic, device-code for Nous/Codex) still runs in the CLI for now;
# Phase 2 will add in-browser flows. For unconnected providers we return
# the canonical ``hermes auth add <provider>`` command so the dashboard
# can surface a one-click copy.


def _truncate_token(value: Optional[str], visible: int = 6) -> str:
    """Return ``...XXXXXX`` (last N chars) for safe display in the UI.

    We never expose more than the trailing ``visible`` characters of an
    OAuth access token. JWT prefixes (the part before the first dot) are
    stripped first when present so the visible suffix is always part of
    the signing region rather than a meaningless header chunk.
    """
    if not value:
        return ""
    s = str(value)
    if "." in s and s.count(".") >= 2:
        # Looks like a JWT — show the trailing piece of the signature only.
        s = s.rsplit(".", 1)[-1]
    if len(s) <= visible:
        return s
    return f"…{s[-visible:]}"


def _anthropic_oauth_status() -> Dict[str, Any]:
    """Combined status across the three Anthropic credential sources we read.

    Hermes resolves Anthropic creds in this order at runtime:
    1. ``~/.hermes/.anthropic_oauth.json`` — Hermes-managed PKCE flow
    2. ``~/.claude/.credentials.json`` — Claude Code CLI credentials (auto)
    3. ``ANTHROPIC_TOKEN`` / ``ANTHROPIC_API_KEY`` env vars
    The dashboard reports the highest-priority source that's actually present.
    """
    try:
        from agent.anthropic_adapter import (
            read_hermes_oauth_credentials,
            read_claude_code_credentials,
            _HERMES_OAUTH_FILE,
        )
    except ImportError:
        read_claude_code_credentials = None  # type: ignore
        read_hermes_oauth_credentials = None  # type: ignore
        _HERMES_OAUTH_FILE = None  # type: ignore

    hermes_creds = None
    if read_hermes_oauth_credentials:
        try:
            hermes_creds = read_hermes_oauth_credentials()
        except Exception:
            hermes_creds = None
    if hermes_creds and hermes_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "hermes_pkce",
            "source_label": f"Hermes PKCE ({_HERMES_OAUTH_FILE})",
            "token_preview": _truncate_token(hermes_creds.get("accessToken")),
            "expires_at": hermes_creds.get("expiresAt"),
            "has_refresh_token": bool(hermes_creds.get("refreshToken")),
        }

    cc_creds = None
    if read_claude_code_credentials:
        try:
            cc_creds = read_claude_code_credentials()
        except Exception:
            cc_creds = None
    if cc_creds and cc_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code",
            "source_label": "Claude Code (~/.claude/.credentials.json)",
            "token_preview": _truncate_token(cc_creds.get("accessToken")),
            "expires_at": cc_creds.get("expiresAt"),
            "has_refresh_token": bool(cc_creds.get("refreshToken")),
        }

    env_token = os.getenv("ANTHROPIC_TOKEN") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if env_token:
        return {
            "logged_in": True,
            "source": "env_var",
            "source_label": "ANTHROPIC_TOKEN environment variable",
            "token_preview": _truncate_token(env_token),
            "expires_at": None,
            "has_refresh_token": False,
        }
    return {"logged_in": False, "source": None}


def _claude_code_only_status() -> Dict[str, Any]:
    """Surface Claude Code CLI credentials as their own provider entry.

    Independent of the Anthropic entry above so users can see whether their
    Claude Code subscription tokens are actively flowing into Hermes even
    when they also have a separate Hermes-managed PKCE login.
    """
    try:
        from agent.anthropic_adapter import read_claude_code_credentials
        creds = read_claude_code_credentials()
    except Exception:
        creds = None
    if creds and creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code_cli",
            "source_label": "~/.claude/.credentials.json",
            "token_preview": _truncate_token(creds.get("accessToken")),
            "expires_at": creds.get("expiresAt"),
            "has_refresh_token": bool(creds.get("refreshToken")),
        }
    return {"logged_in": False, "source": None}


# Provider catalog. The order matters — it's how we render the UI list.
# ``cli_command`` is what the dashboard surfaces as the copy-to-clipboard
# fallback while Phase 2 (in-browser flows) isn't built yet.
# ``flow`` describes the OAuth shape so the future modal can pick the
# right UI: ``pkce`` = open URL + paste callback code, ``device_code`` =
# show code + verification URL + poll, ``external`` = read-only (delegated
# to a third-party CLI like Claude Code or Qwen).
_OAUTH_PROVIDER_CATALOG: tuple[Dict[str, Any], ...] = (
    {
        "id": "anthropic",
        "name": "Anthropic (Claude API)",
        "flow": "pkce",
        "cli_command": "hermes auth add anthropic",
        "docs_url": "https://docs.claude.com/en/api/getting-started",
        "status_fn": _anthropic_oauth_status,
    },
    {
        "id": "claude-code",
        "name": "Claude Code (subscription)",
        "flow": "external",
        "cli_command": "claude setup-token",
        "docs_url": "https://docs.claude.com/en/docs/claude-code",
        "status_fn": _claude_code_only_status,
    },
    {
        "id": "nous",
        "name": "Nous Portal",
        "flow": "device_code",
        "cli_command": "hermes auth add nous",
        "docs_url": "https://portal.nousresearch.com",
        "status_fn": None,  # dispatched via auth.get_nous_auth_status
    },
    {
        "id": "openai-codex",
        "name": "OpenAI Codex (ChatGPT)",
        "flow": "device_code",
        "cli_command": "hermes auth add openai-codex",
        "docs_url": "https://platform.openai.com/docs",
        "status_fn": None,  # dispatched via auth.get_codex_auth_status
    },
    {
        "id": "qwen-oauth",
        "name": "Qwen (via Qwen CLI)",
        "flow": "external",
        "cli_command": "hermes auth add qwen-oauth",
        "docs_url": "https://github.com/QwenLM/qwen-code",
        "status_fn": None,  # dispatched via auth.get_qwen_auth_status
    },
    {
        "id": "minimax-oauth",
        "name": "MiniMax (OAuth)",
        "flow": "pkce",
        "cli_command": "hermes auth add minimax-oauth",
        "docs_url": "https://www.minimax.io",
        "status_fn": None,  # dispatched via auth.get_minimax_oauth_auth_status
    },
)


def _resolve_provider_status(provider_id: str, status_fn) -> Dict[str, Any]:
    """Dispatch to the right status helper for an OAuth provider entry."""
    if status_fn is not None:
        try:
            return status_fn()
        except Exception as e:
            return {"logged_in": False, "error": str(e)}
    try:
        from hermes_cli import auth as hauth
        if provider_id == "nous":
            raw = hauth.get_nous_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "nous_portal",
                "source_label": raw.get("portal_base_url") or "Nous Portal",
                "token_preview": _truncate_token(raw.get("access_token")),
                "expires_at": raw.get("access_expires_at"),
                "has_refresh_token": bool(raw.get("has_refresh_token")),
            }
        if provider_id == "openai-codex":
            raw = hauth.get_codex_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": raw.get("source") or "openai_codex",
                "source_label": raw.get("auth_mode") or "OpenAI Codex",
                "token_preview": _truncate_token(raw.get("api_key")),
                "expires_at": None,
                "has_refresh_token": False,
                "last_refresh": raw.get("last_refresh"),
            }
        if provider_id == "qwen-oauth":
            raw = hauth.get_qwen_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "qwen_cli",
                "source_label": raw.get("auth_store_path") or "Qwen CLI",
                "token_preview": _truncate_token(raw.get("access_token")),
                "expires_at": raw.get("expires_at"),
                "has_refresh_token": bool(raw.get("has_refresh_token")),
            }
        if provider_id == "minimax-oauth":
            raw = hauth.get_minimax_oauth_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "minimax_oauth",
                "source_label": f"MiniMax ({raw.get('region', 'global')})",
                "token_preview": None,
                "expires_at": raw.get("expires_at"),
                "has_refresh_token": True,
            }
    except Exception as e:
        return {"logged_in": False, "error": str(e)}
    return {"logged_in": False}


@app.get("/api/providers/oauth")
async def list_oauth_providers():
    """Enumerate every OAuth-capable LLM provider with current status.

    Response shape (per provider):
        id              stable identifier (used in DELETE path)
        name            human label
        flow            "pkce" | "device_code" | "external"
        cli_command     fallback CLI command for users to run manually
        docs_url        external docs/portal link for the "Learn more" link
        status:
          logged_in        bool — currently has usable creds
          source           short slug ("hermes_pkce", "claude_code", ...)
          source_label     human-readable origin (file path, env var name)
          token_preview    last N chars of the token, never the full token
          expires_at       ISO timestamp string or null
          has_refresh_token bool
    """
    providers = []
    for p in _OAUTH_PROVIDER_CATALOG:
        status = _resolve_provider_status(p["id"], p.get("status_fn"))
        providers.append({
            "id": p["id"],
            "name": p["name"],
            "flow": p["flow"],
            "cli_command": p["cli_command"],
            "docs_url": p["docs_url"],
            "status": status,
        })
    return {"providers": providers}


@app.delete("/api/providers/oauth/{provider_id}")
async def disconnect_oauth_provider(provider_id: str, request: Request):
    """Disconnect an OAuth provider. Token-protected (matches /env/reveal)."""
    _require_token(request)

    valid_ids = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider_id}. "
                   f"Available: {', '.join(sorted(valid_ids))}",
        )

    # Anthropic and claude-code clear the same Hermes-managed PKCE file
    # AND forget the Claude Code import. We don't touch ~/.claude/* directly
    # — that's owned by the Claude Code CLI; users can re-auth there if they
    # want to undo a disconnect.
    if provider_id in ("anthropic", "claude-code"):
        try:
            from agent.anthropic_adapter import _HERMES_OAUTH_FILE
            if _HERMES_OAUTH_FILE.exists():
                _HERMES_OAUTH_FILE.unlink()
        except Exception:
            pass
        # Also clear the credential pool entry if present.
        try:
            from hermes_cli.auth import clear_provider_auth
            clear_provider_auth("anthropic")
        except Exception:
            pass
        _log.info("oauth/disconnect: %s", provider_id)
        return {"ok": True, "provider": provider_id}

    try:
        from hermes_cli.auth import clear_provider_auth
        cleared = clear_provider_auth(provider_id)
        _log.info("oauth/disconnect: %s (cleared=%s)", provider_id, cleared)
        return {"ok": bool(cleared), "provider": provider_id}
    except Exception as e:
        _log.exception("disconnect %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# OAuth Phase 2 — in-browser PKCE & device-code flows
# ---------------------------------------------------------------------------
#
# Two flow shapes are supported:
#
#   PKCE (Anthropic):
#     1. POST /api/providers/oauth/anthropic/start
#          → server generates code_verifier + challenge, builds claude.ai
#            authorize URL, stashes verifier in _oauth_sessions[session_id]
#          → returns { session_id, flow: "pkce", auth_url }
#     2. UI opens auth_url in a new tab. User authorizes, copies code.
#     3. POST /api/providers/oauth/anthropic/submit { session_id, code }
#          → server exchanges (code + verifier) → tokens at console.anthropic.com
#          → persists to ~/.hermes/.anthropic_oauth.json AND credential pool
#          → returns { ok: true, status: "approved" }
#
#   Device code (Nous, OpenAI Codex):
#     1. POST /api/providers/oauth/{nous|openai-codex}/start
#          → server hits provider's device-auth endpoint
#          → gets { user_code, verification_url, device_code, interval, expires_in }
#          → spawns background poller thread that polls the token endpoint
#            every `interval` seconds until approved/expired
#          → stores poll status in _oauth_sessions[session_id]
#          → returns { session_id, flow: "device_code", user_code,
#                      verification_url, expires_in, poll_interval }
#     2. UI opens verification_url in a new tab and shows user_code.
#     3. UI polls GET /api/providers/oauth/{provider}/poll/{session_id}
#          every 2s until status != "pending".
#     4. On "approved" the background thread has already saved creds; UI
#        refreshes the providers list.
#
# Sessions are kept in-memory only (single-process FastAPI) and time out
# after 15 minutes. A periodic cleanup runs on each /start call to GC
# expired sessions so the dict doesn't grow without bound.

_OAUTH_SESSION_TTL_SECONDS = 15 * 60
_oauth_sessions: Dict[str, Dict[str, Any]] = {}
_oauth_sessions_lock = threading.Lock()

# Import OAuth constants from canonical source instead of duplicating.
# Guarded so hermes web still starts if anthropic_adapter is unavailable;
# Phase 2 endpoints will return 501 in that case.
try:
    from agent.anthropic_adapter import (
        _OAUTH_CLIENT_ID as _ANTHROPIC_OAUTH_CLIENT_ID,
        _OAUTH_TOKEN_URL as _ANTHROPIC_OAUTH_TOKEN_URL,
        _OAUTH_REDIRECT_URI as _ANTHROPIC_OAUTH_REDIRECT_URI,
        _OAUTH_SCOPES as _ANTHROPIC_OAUTH_SCOPES,
        _generate_pkce as _generate_pkce_pair,
    )
    _ANTHROPIC_OAUTH_AVAILABLE = True
except ImportError:
    _ANTHROPIC_OAUTH_AVAILABLE = False
_ANTHROPIC_OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"


def _gc_oauth_sessions() -> None:
    """Drop expired sessions. Called opportunistically on /start."""
    cutoff = time.time() - _OAUTH_SESSION_TTL_SECONDS
    with _oauth_sessions_lock:
        stale = [sid for sid, sess in _oauth_sessions.items() if sess["created_at"] < cutoff]
        for sid in stale:
            _oauth_sessions.pop(sid, None)


def _new_oauth_session(provider_id: str, flow: str) -> tuple[str, Dict[str, Any]]:
    """Create + register a new OAuth session, return (session_id, session_dict)."""
    sid = secrets.token_urlsafe(16)
    sess = {
        "session_id": sid,
        "provider": provider_id,
        "flow": flow,
        "created_at": time.time(),
        "status": "pending",  # pending | approved | denied | expired | error
        "error_message": None,
    }
    with _oauth_sessions_lock:
        _oauth_sessions[sid] = sess
    return sid, sess


def _save_anthropic_oauth_creds(access_token: str, refresh_token: str, expires_at_ms: int) -> None:
    """Persist Anthropic PKCE creds to both Hermes file AND credential pool.

    Mirrors what auth_commands.add_command does so the dashboard flow leaves
    the system in the same state as ``hermes auth add anthropic``.
    """
    from agent.anthropic_adapter import _HERMES_OAUTH_FILE
    payload = {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_ms,
    }
    _HERMES_OAUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HERMES_OAUTH_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Best-effort credential-pool insert. Failure here doesn't invalidate
    # the file write — pool registration only matters for the rotation
    # strategy, not for runtime credential resolution.
    try:
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid
        pool = load_pool("anthropic")
        # Avoid duplicate entries: delete any prior dashboard-issued OAuth entry
        existing = [e for e in pool.entries() if getattr(e, "source", "").startswith(f"{SOURCE_MANUAL}:dashboard_pkce")]
        for e in existing:
            try:
                pool.remove_entry(getattr(e, "id", ""))
            except Exception:
                pass
        entry = PooledCredential(
            provider="anthropic",
            id=uuid.uuid4().hex[:6],
            label="dashboard PKCE",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_pkce",
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at_ms=expires_at_ms,
        )
        pool.add_entry(entry)
    except Exception as e:
        _log.warning("anthropic pool add (dashboard) failed: %s", e)


def _start_anthropic_pkce() -> Dict[str, Any]:
    """Begin PKCE flow. Returns the auth URL the UI should open."""
    if not _ANTHROPIC_OAUTH_AVAILABLE:
        raise HTTPException(status_code=501, detail="Anthropic OAuth not available (missing adapter)")
    verifier, challenge = _generate_pkce_pair()
    sid, sess = _new_oauth_session("anthropic", "pkce")
    sess["verifier"] = verifier
    sess["state"] = verifier  # Anthropic round-trips verifier as state
    params = {
        "code": "true",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "scope": _ANTHROPIC_OAUTH_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": verifier,
    }
    auth_url = f"{_ANTHROPIC_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return {
        "session_id": sid,
        "flow": "pkce",
        "auth_url": auth_url,
        "expires_in": _OAUTH_SESSION_TTL_SECONDS,
    }


def _submit_anthropic_pkce(session_id: str, code_input: str) -> Dict[str, Any]:
    """Exchange authorization code for tokens. Persists on success."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess or sess["provider"] != "anthropic" or sess["flow"] != "pkce":
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    if sess["status"] != "pending":
        return {"ok": False, "status": sess["status"], "message": sess.get("error_message")}

    # Anthropic's redirect callback page formats the code as `<code>#<state>`.
    # Strip the state suffix if present (we already have the verifier server-side).
    parts = code_input.strip().split("#", 1)
    code = parts[0].strip()
    if not code:
        return {"ok": False, "status": "error", "message": "No code provided"}
    state_from_callback = parts[1] if len(parts) > 1 else ""

    exchange_data = json.dumps({
        "grant_type": "authorization_code",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "code": code,
        "state": state_from_callback or sess["state"],
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "code_verifier": sess["verifier"],
    }).encode()
    req = urllib.request.Request(
        _ANTHROPIC_OAUTH_TOKEN_URL,
        data=exchange_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "hermes-dashboard/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode())
    except Exception as e:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = f"Token exchange failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    access_token = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")
    expires_in = int(result.get("expires_in") or 3600)
    if not access_token:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = "No access token returned"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    expires_at_ms = int(time.time() * 1000) + (expires_in * 1000)
    try:
        _save_anthropic_oauth_creds(access_token, refresh_token, expires_at_ms)
    except Exception as e:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = f"Save failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}
    with _oauth_sessions_lock:
        sess["status"] = "approved"
    _log.info("oauth/pkce: anthropic login completed (session=%s)", session_id)
    return {"ok": True, "status": "approved"}


async def _start_device_code_flow(provider_id: str) -> Dict[str, Any]:
    """Initiate a device-code flow (Nous or OpenAI Codex).

    Calls the provider's device-auth endpoint via the existing CLI helpers,
    then spawns a background poller. Returns the user-facing display fields
    so the UI can render the verification page link + user code.
    """
    if provider_id == "nous":
        from hermes_cli.auth import _request_device_code, PROVIDER_REGISTRY
        import httpx
        pconfig = PROVIDER_REGISTRY["nous"]
        portal_base_url = (
            os.getenv("HERMES_PORTAL_BASE_URL")
            or os.getenv("NOUS_PORTAL_BASE_URL")
            or pconfig.portal_base_url
        ).rstrip("/")
        client_id = pconfig.client_id
        scope = pconfig.scope
        def _do_nous_device_request():
            with httpx.Client(timeout=httpx.Timeout(15.0), headers={"Accept": "application/json"}) as client:
                return _request_device_code(
                    client=client,
                    portal_base_url=portal_base_url,
                    client_id=client_id,
                    scope=scope,
                )
        device_data = await asyncio.get_event_loop().run_in_executor(None, _do_nous_device_request)
        sid, sess = _new_oauth_session("nous", "device_code")
        sess["device_code"] = str(device_data["device_code"])
        sess["interval"] = int(device_data["interval"])
        sess["expires_at"] = time.time() + int(device_data["expires_in"])
        sess["portal_base_url"] = portal_base_url
        sess["client_id"] = client_id
        threading.Thread(
            target=_nous_poller, args=(sid,), daemon=True, name=f"oauth-poll-{sid[:6]}"
        ).start()
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": str(device_data["user_code"]),
            "verification_url": str(device_data["verification_uri_complete"]),
            "expires_in": int(device_data["expires_in"]),
            "poll_interval": int(device_data["interval"]),
        }

    if provider_id == "openai-codex":
        # Codex uses fixed OpenAI device-auth endpoints; reuse the helper.
        sid, _ = _new_oauth_session("openai-codex", "device_code")
        # Use the helper but in a thread because it polls inline.
        # We can't extract just the start step without refactoring auth.py,
        # so we run the full helper in a worker and proxy the user_code +
        # verification_url back via the session dict. The helper prints
        # to stdout — we capture nothing here, just status.
        threading.Thread(
            target=_codex_full_login_worker, args=(sid,), daemon=True,
            name=f"oauth-codex-{sid[:6]}",
        ).start()
        # Block briefly until the worker has populated the user_code, OR error.
        deadline = time.time() + 10
        while time.time() < deadline:
            with _oauth_sessions_lock:
                s = _oauth_sessions.get(sid)
            if s and (s.get("user_code") or s["status"] != "pending"):
                break
            await asyncio.sleep(0.1)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(sid, {})
        if s.get("status") == "error":
            raise HTTPException(status_code=500, detail=s.get("error_message") or "device-auth failed")
        if not s.get("user_code"):
            raise HTTPException(status_code=504, detail="device-auth timed out before returning a user code")
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": s["user_code"],
            "verification_url": s["verification_url"],
            "expires_in": int(s.get("expires_in") or 900),
            "poll_interval": int(s.get("interval") or 5),
        }

    raise HTTPException(status_code=400, detail=f"Provider {provider_id} does not support device-code flow")


def _nous_poller(session_id: str) -> None:
    """Background poller that drives a Nous device-code flow to completion."""
    from hermes_cli.auth import _poll_for_token, refresh_nous_oauth_from_state
    from datetime import datetime, timezone
    import httpx
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        return
    portal_base_url = sess["portal_base_url"]
    client_id = sess["client_id"]
    device_code = sess["device_code"]
    interval = sess["interval"]
    expires_in = max(60, int(sess["expires_at"] - time.time()))
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0), headers={"Accept": "application/json"}) as client:
            token_data = _poll_for_token(
                client=client,
                portal_base_url=portal_base_url,
                client_id=client_id,
                device_code=device_code,
                expires_in=expires_in,
                poll_interval=interval,
            )
        # Same post-processing as _nous_device_code_login (mint agent key)
        now = datetime.now(timezone.utc)
        token_ttl = int(token_data.get("expires_in") or 0)
        auth_state = {
            "portal_base_url": portal_base_url,
            "inference_base_url": token_data.get("inference_base_url"),
            "client_id": client_id,
            "scope": token_data.get("scope"),
            "token_type": token_data.get("token_type", "Bearer"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "obtained_at": now.isoformat(),
            "expires_at": (
                datetime.fromtimestamp(now.timestamp() + token_ttl, tz=timezone.utc).isoformat()
                if token_ttl else None
            ),
            "expires_in": token_ttl,
        }
        full_state = refresh_nous_oauth_from_state(
            auth_state, min_key_ttl_seconds=300, timeout_seconds=15.0,
            force_refresh=False, force_mint=True,
        )
        from hermes_cli.auth import persist_nous_credentials
        persist_nous_credentials(full_state)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: nous login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("nous device-code poll failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = str(e)


def _codex_full_login_worker(session_id: str) -> None:
    """Run the complete OpenAI Codex device-code flow.

    Codex doesn't use the standard OAuth device-code endpoints; it has its
    own ``/api/accounts/deviceauth/usercode`` (JSON body, returns
    ``device_auth_id``) and ``/api/accounts/deviceauth/token`` (JSON body
    polled until 200). On success the response carries an
    ``authorization_code`` + ``code_verifier`` that get exchanged at
    CODEX_OAUTH_TOKEN_URL with grant_type=authorization_code.

    The flow is replicated inline (rather than calling
    _codex_device_code_login) because that helper prints/blocks/polls in a
    single function — we need to surface the user_code to the dashboard the
    moment we receive it, well before polling completes.
    """
    try:
        import httpx
        from hermes_cli.auth import (
            CODEX_OAUTH_CLIENT_ID,
            CODEX_OAUTH_TOKEN_URL,
            DEFAULT_CODEX_BASE_URL,
        )
        issuer = "https://auth.openai.com"

        # Step 1: request device code
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": CODEX_OAUTH_CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"deviceauth/usercode returned {resp.status_code}")
        device_data = resp.json()
        user_code = device_data.get("user_code", "")
        device_auth_id = device_data.get("device_auth_id", "")
        poll_interval = max(3, int(device_data.get("interval", "5")))
        if not user_code or not device_auth_id:
            raise RuntimeError("device-code response missing user_code or device_auth_id")
        verification_url = f"{issuer}/codex/device"
        with _oauth_sessions_lock:
            sess = _oauth_sessions.get(session_id)
            if not sess:
                return
            sess["user_code"] = user_code
            sess["verification_url"] = verification_url
            sess["device_auth_id"] = device_auth_id
            sess["interval"] = poll_interval
            sess["expires_in"] = 15 * 60  # OpenAI's effective limit
            sess["expires_at"] = time.time() + sess["expires_in"]

        # Step 2: poll until authorized
        deadline = time.time() + sess["expires_in"]
        code_resp = None
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            while time.time() < deadline:
                time.sleep(poll_interval)
                poll = client.post(
                    f"{issuer}/api/accounts/deviceauth/token",
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )
                if poll.status_code == 200:
                    code_resp = poll.json()
                    break
                if poll.status_code in (403, 404):
                    continue  # user hasn't authorized yet
                raise RuntimeError(f"deviceauth/token poll returned {poll.status_code}")

        if code_resp is None:
            with _oauth_sessions_lock:
                sess["status"] = "expired"
                sess["error_message"] = "Device code expired before approval"
            return

        # Step 3: exchange authorization_code for tokens
        authorization_code = code_resp.get("authorization_code", "")
        code_verifier = code_resp.get("code_verifier", "")
        if not authorization_code or not code_verifier:
            raise RuntimeError("device-auth response missing authorization_code/code_verifier")
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            token_resp = client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": f"{issuer}/deviceauth/callback",
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if token_resp.status_code != 200:
            raise RuntimeError(f"token exchange returned {token_resp.status_code}")
        tokens = token_resp.json()
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        if not access_token:
            raise RuntimeError("token exchange did not return access_token")

        # Persist via credential pool — same shape as auth_commands.add_command
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid as _uuid
        pool = load_pool("openai-codex")
        base_url = (
            os.getenv("HERMES_CODEX_BASE_URL", "").strip().rstrip("/")
            or DEFAULT_CODEX_BASE_URL
        )
        entry = PooledCredential(
            provider="openai-codex",
            id=_uuid.uuid4().hex[:6],
            label="dashboard device_code",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_device_code",
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=base_url,
        )
        pool.add_entry(entry)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: openai-codex login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("codex device-code worker failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(session_id)
            if s:
                s["status"] = "error"
                s["error_message"] = str(e)


@app.post("/api/providers/oauth/{provider_id}/start")
async def start_oauth_login(provider_id: str, request: Request):
    """Initiate an OAuth login flow. Token-protected."""
    _require_token(request)
    _gc_oauth_sessions()
    valid = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown provider {provider_id}")
    catalog_entry = next(p for p in _OAUTH_PROVIDER_CATALOG if p["id"] == provider_id)
    if catalog_entry["flow"] == "external":
        raise HTTPException(
            status_code=400,
            detail=f"{provider_id} uses an external CLI; run `{catalog_entry['cli_command']}` manually",
        )
    try:
        if catalog_entry["flow"] == "pkce":
            return _start_anthropic_pkce()
        if catalog_entry["flow"] == "device_code":
            return await _start_device_code_flow(provider_id)
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("oauth/start %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))
    raise HTTPException(status_code=400, detail="Unsupported flow")


class OAuthSubmitBody(BaseModel):
    session_id: str
    code: str


@app.post("/api/providers/oauth/{provider_id}/submit")
async def submit_oauth_code(provider_id: str, body: OAuthSubmitBody, request: Request):
    """Submit the auth code for PKCE flows. Token-protected."""
    _require_token(request)
    if provider_id == "anthropic":
        return await asyncio.get_event_loop().run_in_executor(
            None, _submit_anthropic_pkce, body.session_id, body.code,
        )
    raise HTTPException(status_code=400, detail=f"submit not supported for {provider_id}")


@app.get("/api/providers/oauth/{provider_id}/poll/{session_id}")
async def poll_oauth_session(provider_id: str, session_id: str):
    """Poll a device-code session's status (no auth — read-only state)."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if sess["provider"] != provider_id:
        raise HTTPException(status_code=400, detail="Provider mismatch for session")
    return {
        "session_id": session_id,
        "status": sess["status"],
        "error_message": sess.get("error_message"),
        "expires_at": sess.get("expires_at"),
    }


@app.delete("/api/providers/oauth/sessions/{session_id}")
async def cancel_oauth_session(session_id: str, request: Request):
    """Cancel a pending OAuth session. Token-protected."""
    _require_token(request)
    with _oauth_sessions_lock:
        sess = _oauth_sessions.pop(session_id, None)
    if sess is None:
        return {"ok": False, "message": "session not found"}
    return {"ok": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# Session detail endpoints
# ---------------------------------------------------------------------------


@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        session = db.get_session(sid) if sid else None
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    finally:
        db.close()


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = db.get_messages(sid)
        return {"session_id": sid, "messages": messages}
    finally:
        db.close()


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        if not db.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"ok": True}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Log viewer endpoint
# ---------------------------------------------------------------------------


@app.get("/api/logs")
async def get_logs(
    file: str = "agent",
    lines: int = 100,
    level: Optional[str] = None,
    component: Optional[str] = None,
    search: Optional[str] = None,
):
    from hermes_cli.logs import _read_tail, LOG_FILES

    log_name = LOG_FILES.get(file)
    if not log_name:
        raise HTTPException(status_code=400, detail=f"Unknown log file: {file}")
    log_path = get_hermes_home() / "logs" / log_name
    if not log_path.exists():
        return {"file": file, "lines": []}

    try:
        from hermes_logging import COMPONENT_PREFIXES
    except ImportError:
        COMPONENT_PREFIXES = {}

    # Normalize "ALL" / "all" / empty → no filter. _matches_filters treats an
    # empty tuple as "must match a prefix" (startswith(()) is always False),
    # so passing () instead of None silently drops every line.
    min_level = level if level and level.upper() != "ALL" else None
    if component and component.lower() != "all":
        comp_prefixes = COMPONENT_PREFIXES.get(component)
        if comp_prefixes is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown component: {component}. "
                       f"Available: {', '.join(sorted(COMPONENT_PREFIXES))}",
            )
    else:
        comp_prefixes = None

    has_filters = bool(min_level or comp_prefixes or search)
    result = _read_tail(
        log_path, min(lines, 500) if not search else 2000,
        has_filters=has_filters,
        min_level=min_level,
        component_prefixes=comp_prefixes,
    )
    # Post-filter by search term (case-insensitive substring match).
    # _read_tail doesn't support free-text search, so we filter here and
    # trim to the requested line count afterward.
    if search:
        needle = search.lower()
        result = [l for l in result if needle in l.lower()][-min(lines, 500):]
    return {"file": file, "lines": result}


# ---------------------------------------------------------------------------
# Cron job management endpoints
# ---------------------------------------------------------------------------


class CronJobCreate(BaseModel):
    prompt: str
    schedule: str
    name: str = ""
    deliver: str = "local"


class CronJobUpdate(BaseModel):
    updates: dict


@app.get("/api/cron/jobs")
async def list_cron_jobs():
    from cron.jobs import list_jobs
    return list_jobs(include_disabled=True)


@app.get("/api/cron/jobs/{job_id}")
async def get_cron_job(job_id: str):
    from cron.jobs import get_job
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs")
async def create_cron_job(body: CronJobCreate):
    from cron.jobs import create_job
    try:
        job = create_job(prompt=body.prompt, schedule=body.schedule,
                         name=body.name, deliver=body.deliver)
        return job
    except Exception as e:
        _log.exception("POST /api/cron/jobs failed")
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/cron/jobs/{job_id}")
async def update_cron_job(job_id: str, body: CronJobUpdate):
    from cron.jobs import update_job
    job = update_job(job_id, body.updates)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/pause")
async def pause_cron_job(job_id: str):
    from cron.jobs import pause_job
    job = pause_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/resume")
async def resume_cron_job(job_id: str):
    from cron.jobs import resume_job
    job = resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/trigger")
async def trigger_cron_job(job_id: str):
    from cron.jobs import trigger_job
    job = trigger_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.delete("/api/cron/jobs/{job_id}")
async def delete_cron_job(job_id: str):
    from cron.jobs import remove_job
    if not remove_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Skills & Tools endpoints
# ---------------------------------------------------------------------------


def _load_capability_policy():
    try:
        from capability_policy import CapabilityPolicy
    except ImportError:
        desk_src = PROJECT_ROOT.parent / "python" / "src"
        if desk_src.exists() and str(desk_src) not in sys.path:
            sys.path.insert(0, str(desk_src))
        from capability_policy import CapabilityPolicy
    return CapabilityPolicy


def _capability_policy():
    return _load_capability_policy()()


def _strip_internal_plugin_fields(plugin: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in plugin.items() if not k.startswith("_")}


def _desk_catalog_skills(policy) -> List[Dict[str, Any]]:
    from tools.skills_tool import _find_all_skills
    from hermes_cli.skills_config import get_disabled_skills

    config = load_config()
    disabled = get_disabled_skills(config)
    out: List[Dict[str, Any]] = []
    for skill in _find_all_skills(skip_disabled=True):
        visibility = policy.skill_visibility(skill)
        if not visibility["visible"]:
            continue
        item = dict(skill)
        item["enabled"] = item["name"] not in disabled
        item["roles"] = visibility["roles"]
        item["source"] = visibility["source"]
        item["trust"] = visibility["trust"]
        item["recommended"] = visibility["recommended"]
        item["risk"] = visibility["risk"]
        item["can_edit"] = visibility["can_edit"]
        item["action_mode"] = visibility["action_mode"]
        out.append(item)
    return sorted(out, key=lambda s: (s.get("category") or "", s.get("name") or ""))


@lru_cache(maxsize=256)
def _resolve_toolset_names_cached(name: str) -> Tuple[str, ...]:
    """Memoize toolset → tool names for desktop catalog (stable per process)."""
    from toolsets import resolve_toolset

    try:
        return tuple(sorted(set(resolve_toolset(name))))
    except Exception:
        return tuple()


def _desk_catalog_toolsets(policy) -> List[Dict[str, Any]]:
    from hermes_cli.tools_config import (
        _get_effective_configurable_toolsets,
        _get_platform_tools,
        _toolset_has_keys,
    )

    config = load_config()
    enabled_toolsets = _get_platform_tools(
        config,
        "cli",
        include_default_mcp_servers=False,
    )
    result: List[Dict[str, Any]] = []
    for name, label, desc in _get_effective_configurable_toolsets():
        tools = list(_resolve_toolset_names_cached(name))
        # source = provenance (core-built-in toolsets); trust = curation/safety.
        visibility = policy.tool_visibility({"name": name, "source": "builtin", "trust": "official"})
        if not policy.can_view(visibility["roles"]):
            continue
        is_enabled = name in enabled_toolsets
        result.append({
            "name": name,
            "label": label,
            "description": desc,
            "enabled": is_enabled,
            "available": is_enabled and not visibility["locked"],
            "configured": _toolset_has_keys(name, config),
            "tools": tools,
            "roles": visibility["roles"],
            "source": visibility["source"],
            "trust": visibility["trust"],
            "risk": visibility["risk"],
            "locked": visibility["locked"],
            "can_edit": visibility["can_edit"],
            "action_mode": visibility["action_mode"],
        })
    return result


def _desk_catalog_plugins(policy) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for plugin in _get_dashboard_plugins():
        clean = _strip_internal_plugin_fields(plugin)
        if not clean.get("source"):
            clean["source"] = "bundled"
        source_l = str(clean.get("source") or "").strip().lower()
        if source_l in {"bundled", "installed", "user", "project"} and not clean.get("trust"):
            clean["trust"] = "official"
        visibility = policy.plugin_visibility(clean)
        if not visibility["visible"]:
            continue
        clean["roles"] = visibility["roles"]
        clean["source"] = visibility["source"]
        clean["trust"] = visibility["trust"]
        clean["recommended"] = visibility["recommended"]
        clean["risk"] = visibility["risk"]
        clean["can_edit"] = visibility["can_edit"]
        clean["action_mode"] = visibility["action_mode"]
        out.append(clean)
    return sorted(out, key=lambda p: (p.get("label") or p.get("name") or ""))


_DESK_CATALOG_TTL_SEC = 20.0
_desk_catalog_cache_payload: Optional[Dict[str, Any]] = None
_desk_catalog_cache_role: Optional[str] = None
_desk_catalog_cache_expires: float = 0.0


def invalidate_desk_catalog_cache() -> None:
    """Drop HermesDesk capability catalog cache (skills/toolsets/plugins lists)."""
    global _desk_catalog_cache_payload, _desk_catalog_cache_role, _desk_catalog_cache_expires
    _desk_catalog_cache_payload = None
    _desk_catalog_cache_role = None
    _desk_catalog_cache_expires = 0.0
    _resolve_toolset_names_cached.cache_clear()


def _build_desk_catalog_payload_unlocked() -> Dict[str, Any]:
    policy = _capability_policy()
    return {
        "role": policy.role,
        "skills": _desk_catalog_skills(policy),
        "toolsets": _desk_catalog_toolsets(policy),
        "plugins": _desk_catalog_plugins(policy),
    }


def get_desk_catalog_payload_cached() -> Dict[str, Any]:
    """Build or return cached /api/hermesdesk/capabilities body (short TTL, keyed by role)."""
    global _desk_catalog_cache_payload, _desk_catalog_cache_role, _desk_catalog_cache_expires
    policy = _capability_policy()
    now = time.monotonic()
    if (
        _desk_catalog_cache_payload is not None
        and _desk_catalog_cache_role == policy.role
        and now < _desk_catalog_cache_expires
    ):
        return _desk_catalog_cache_payload
    payload = _build_desk_catalog_payload_unlocked()
    _desk_catalog_cache_payload = payload
    _desk_catalog_cache_role = policy.role
    _desk_catalog_cache_expires = now + _DESK_CATALOG_TTL_SEC
    return payload


def _desk_skill_detail_sync(skill_name: str) -> Dict[str, Any]:
    from tools.skills_tool import skill_view

    policy = _capability_policy()
    catalog = get_desk_catalog_payload_cached()
    skills = {s["name"]: s for s in catalog["skills"]}
    if skill_name not in skills:
        raise KeyError(skill_name)
    try:
        detail = json.loads(skill_view(skill_name, preprocess=False))
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    if not detail.get("success"):
        raise KeyError(skill_name)
    visibility = policy.skill_visibility({**skills[skill_name], **detail})
    if not visibility["visible"]:
        raise KeyError(skill_name)
    detail["roles"] = visibility["roles"]
    detail["source"] = visibility["source"]
    detail["trust"] = visibility["trust"]
    detail["recommended"] = visibility["recommended"]
    detail["risk"] = visibility["risk"]
    detail["can_edit"] = visibility["can_edit"]
    detail["action_mode"] = visibility["action_mode"]
    return detail


class SkillToggle(BaseModel):
    name: str
    enabled: bool


@app.get("/api/skills")
async def get_skills():
    from tools.skills_tool import _find_all_skills
    from hermes_cli.skills_config import get_disabled_skills
    config = load_config()
    disabled = get_disabled_skills(config)
    skills = _find_all_skills(skip_disabled=True)
    for s in skills:
        s["enabled"] = s["name"] not in disabled
    return skills


@app.put("/api/skills/toggle")
async def toggle_skill(body: SkillToggle):
    from hermes_cli.skills_config import get_disabled_skills, save_disabled_skills
    config = load_config()
    disabled = get_disabled_skills(config)
    if body.enabled:
        disabled.discard(body.name)
    else:
        disabled.add(body.name)
    save_disabled_skills(config, disabled)
    invalidate_desk_catalog_cache()
    return {"ok": True, "name": body.name, "enabled": body.enabled}


@app.get("/api/hermesdesk/capabilities")
async def get_hermesdesk_capabilities():
    return await asyncio.to_thread(get_desk_catalog_payload_cached)


@app.get("/api/hermesdesk/skills/{skill_name:path}")
async def get_hermesdesk_skill_detail(skill_name: str):
    try:
        return await asyncio.to_thread(_desk_skill_detail_sync, skill_name)
    except KeyError:
        raise HTTPException(status_code=404, detail="Skill not found") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"Could not load skill: {exc}") from exc


@app.get("/api/tools/toolsets")
async def get_toolsets():
    from hermes_cli.tools_config import (
        _get_effective_configurable_toolsets,
        _get_platform_tools,
        _toolset_has_keys,
    )
    from toolsets import resolve_toolset

    config = load_config()
    enabled_toolsets = _get_platform_tools(
        config,
        "cli",
        include_default_mcp_servers=False,
    )
    result = []
    for name, label, desc in _get_effective_configurable_toolsets():
        try:
            tools = sorted(set(resolve_toolset(name)))
        except Exception:
            tools = []
        is_enabled = name in enabled_toolsets
        result.append({
            "name": name, "label": label, "description": desc,
            "enabled": is_enabled,
            "available": is_enabled,
            "configured": _toolset_has_keys(name, config),
            "tools": tools,
        })
    return result


def _load_capability_policy():
    """Import HermesDesk's desktop catalog policy from dev or bundled layout."""
    try:
        from capability_policy import CapabilityPolicy  # type: ignore
        return CapabilityPolicy
    except ImportError:
        candidates = [
            Path(os.environ.get("HERMESDESK_BUNDLE_DIR", "")),
            Path(__file__).resolve().parents[2] / "python" / "src",
            Path(__file__).resolve().parents[2],
        ]
        for candidate in candidates:
            if not str(candidate) or not candidate.exists():
                continue
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            try:
                from capability_policy import CapabilityPolicy  # type: ignore
                return CapabilityPolicy
            except ImportError:
                continue
        raise


def _catalog_policy():
    return _load_capability_policy()()


def _catalog_skill_items() -> list:
    from tools.skills_tool import _find_all_skills
    from hermes_cli.skills_config import get_disabled_skills

    config = load_config()
    disabled = get_disabled_skills(config)
    policy = _catalog_policy()
    items = []
    for skill in _find_all_skills(skip_disabled=True):
        enriched = dict(skill)
        enriched["enabled"] = enriched["name"] not in disabled
        visibility = policy.skill_visibility(enriched)
        if not visibility["visible"]:
            continue
        enriched.update({
            "roles": visibility["roles"],
            "source": visibility["source"],
            "trust": visibility["trust"],
            "recommended": visibility["recommended"],
            "risk": visibility["risk"],
            "can_edit": visibility["can_edit"],
            "action_mode": visibility["action_mode"],
        })
        items.append(enriched)
    return sorted(items, key=lambda s: (s.get("category") or "", s.get("name") or ""))


def _catalog_toolset_items() -> list:
    from hermes_cli.tools_config import (
        _get_effective_configurable_toolsets,
        _get_platform_tools,
        _toolset_has_keys,
    )
    from toolsets import resolve_toolset

    config = load_config()
    enabled_toolsets = _get_platform_tools(
        config,
        "cli",
        include_default_mcp_servers=False,
    )
    policy = _catalog_policy()
    result = []
    for name, label, desc in _get_effective_configurable_toolsets():
        try:
            tools = sorted(set(resolve_toolset(name)))
        except Exception:
            tools = []
        item = {
            "name": name,
            "label": label,
            "description": desc,
            "enabled": name in enabled_toolsets,
            "available": name in enabled_toolsets,
            "configured": _toolset_has_keys(name, config),
            "tools": tools,
        }
        visibility = policy.tool_visibility({**item, "source": "builtin", "trust": "official"})
        if not policy.can_view(visibility["roles"]):
            continue
        item.update({
            "roles": visibility["roles"],
            "source": visibility["source"],
            "trust": visibility["trust"],
            "risk": visibility["risk"],
            "locked": visibility["locked"],
            "can_edit": visibility["can_edit"],
            "action_mode": visibility["action_mode"],
        })
        result.append(item)
    return result


def _catalog_plugin_items() -> list:
    policy = _catalog_policy()
    items = []
    for plugin in _get_dashboard_plugins():
        clean = {k: v for k, v in plugin.items() if not k.startswith("_")}
        if not clean.get("source"):
            clean["source"] = "bundled"
        source_l = str(clean.get("source") or "").strip().lower()
        if source_l in {"bundled", "installed", "user", "project"} and not clean.get("trust"):
            clean["trust"] = "official"
        visibility = policy.plugin_visibility(clean)
        if not visibility["visible"]:
            continue
        clean.update({
            "roles": visibility["roles"],
            "source": visibility["source"],
            "trust": visibility["trust"],
            "recommended": visibility["recommended"],
            "risk": visibility["risk"],
            "can_edit": visibility["can_edit"],
            "action_mode": visibility["action_mode"],
        })
        items.append(clean)
    return sorted(items, key=lambda p: p.get("name") or "")


@app.get("/api/hermesdesk/capabilities")
async def get_hermesdesk_capabilities():
    """Desktop-shell catalog for skills, tools, and plugins."""
    policy = _catalog_policy()
    return {
        "role": policy.role,
        "skills": _catalog_skill_items(),
        "toolsets": _catalog_toolset_items(),
        "plugins": _catalog_plugin_items(),
    }


@app.get("/api/hermesdesk/skills/{name:path}")
async def get_hermesdesk_skill_detail(name: str):
    """Return a filtered skill detail document for the desktop shell."""
    matching = [skill for skill in _catalog_skill_items() if skill.get("name") == name]
    if not matching:
        raise HTTPException(status_code=404, detail="Skill not visible or not found")

    from tools.skills_tool import skill_view

    try:
        detail = json.loads(skill_view(name, preprocess=False))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Could not parse skill detail: {exc}")
    if not detail.get("success"):
        raise HTTPException(status_code=404, detail=detail.get("error") or "Skill not found")

    item = matching[0]
    detail.update({
        "roles": item.get("roles", []),
        "source": item.get("source", "installed"),
        "trust": item.get("trust", "official"),
        "recommended": bool(item.get("recommended")),
        "risk": item.get("risk", "low"),
        "can_edit": bool(item.get("can_edit")),
        "action_mode": item.get("action_mode", "view_only"),
        "enabled": bool(item.get("enabled")),
    })
    return detail


# ---------------------------------------------------------------------------
# Raw YAML config endpoint
# ---------------------------------------------------------------------------


class RawConfigUpdate(BaseModel):
    yaml_text: str


@app.get("/api/config/raw")
async def get_config_raw():
    path = get_config_path()
    if not path.exists():
        return {"yaml": ""}
    return {"yaml": path.read_text(encoding="utf-8")}


@app.put("/api/config/raw")
async def update_config_raw(body: RawConfigUpdate):
    try:
        parsed = yaml.safe_load(body.yaml_text)
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="YAML must be a mapping")
        save_config(parsed)
        return {"ok": True}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")


# ---------------------------------------------------------------------------
# Token / cost analytics endpoint
# ---------------------------------------------------------------------------


@app.get("/api/analytics/usage")
async def get_usage_analytics(days: int = 30):
    from hermes_state import SessionDB
    from agent.insights import InsightsEngine

    db = SessionDB()
    try:
        cutoff = time.time() - (days * 86400)
        cur = db._conn.execute("""
            SELECT date(started_at, 'unixepoch') as day,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read_tokens,
                   SUM(reasoning_tokens) as reasoning_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls
            FROM sessions WHERE started_at > ?
            GROUP BY day ORDER BY day
        """, (cutoff,))
        daily = [dict(r) for r in cur.fetchall()]

        cur2 = db._conn.execute("""
            SELECT model,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls
            FROM sessions WHERE started_at > ? AND model IS NOT NULL
            GROUP BY model ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
        """, (cutoff,))
        by_model = [dict(r) for r in cur2.fetchall()]

        cur3 = db._conn.execute("""
            SELECT SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(reasoning_tokens) as total_reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                   COUNT(*) as total_sessions,
                   SUM(COALESCE(api_call_count, 0)) as total_api_calls
            FROM sessions WHERE started_at > ?
        """, (cutoff,))
        totals = dict(cur3.fetchone())
        insights_report = InsightsEngine(db).generate(days=days)
        skills = insights_report.get("skills", {
            "summary": {
                "total_skill_loads": 0,
                "total_skill_edits": 0,
                "total_skill_actions": 0,
                "distinct_skills_used": 0,
            },
            "top_skills": [],
        })

        return {
            "daily": daily,
            "by_model": by_model,
            "totals": totals,
            "period_days": days,
            "skills": skills,
        }
    finally:
        db.close()


@app.get("/api/analytics/models")
async def get_models_analytics(days: int = 30):
    """Rich per-model analytics for the Models dashboard page.

    Returns token/cost/session breakdown per model plus capability metadata
    from models.dev (context window, vision, tools, reasoning, etc.).
    """
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        cutoff = time.time() - (days * 86400)

        cur = db._conn.execute("""
            SELECT model,
                   billing_provider,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read_tokens,
                   SUM(reasoning_tokens) as reasoning_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls,
                   SUM(tool_call_count) as tool_calls,
                   MAX(started_at) as last_used_at,
                   AVG(input_tokens + output_tokens) as avg_tokens_per_session
            FROM sessions WHERE started_at > ? AND model IS NOT NULL AND model != ''
            GROUP BY model, billing_provider
            ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
        """, (cutoff,))
        rows = [dict(r) for r in cur.fetchall()]

        models = []
        for row in rows:
            provider = row.get("billing_provider") or ""
            model_name = row["model"]
            caps = {}
            try:
                from agent.models_dev import get_model_capabilities
                mc = get_model_capabilities(provider=provider, model=model_name)
                if mc is not None:
                    caps = {
                        "supports_tools": mc.supports_tools,
                        "supports_vision": mc.supports_vision,
                        "supports_reasoning": mc.supports_reasoning,
                        "context_window": mc.context_window,
                        "max_output_tokens": mc.max_output_tokens,
                        "model_family": mc.model_family,
                    }
            except Exception:
                pass

            models.append({
                "model": model_name,
                "provider": provider,
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "reasoning_tokens": row["reasoning_tokens"],
                "estimated_cost": row["estimated_cost"],
                "actual_cost": row["actual_cost"],
                "sessions": row["sessions"],
                "api_calls": row["api_calls"],
                "tool_calls": row["tool_calls"],
                "last_used_at": row["last_used_at"],
                "avg_tokens_per_session": row["avg_tokens_per_session"],
                "capabilities": caps,
            })

        totals_cur = db._conn.execute("""
            SELECT COUNT(DISTINCT model) as distinct_models,
                   SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(reasoning_tokens) as total_reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                   COUNT(*) as total_sessions,
                   SUM(COALESCE(api_call_count, 0)) as total_api_calls
            FROM sessions WHERE started_at > ? AND model IS NOT NULL AND model != ''
        """, (cutoff,))
        totals = dict(totals_cur.fetchone())

        return {
            "models": models,
            "totals": totals,
            "period_days": days,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# /api/pty — PTY-over-WebSocket bridge for the dashboard "Chat" tab.
#
# The endpoint spawns the same ``hermes --tui`` binary the CLI uses, behind
# a POSIX pseudo-terminal, and forwards bytes + resize escapes across a
# WebSocket.  The browser renders the ANSI through xterm.js (see
# web/src/pages/ChatPage.tsx).
#
# Auth: ``?token=<session_token>`` query param (browsers can't set
# Authorization on the WS upgrade).  Same ephemeral ``_SESSION_TOKEN`` as
# REST.  Localhost-only — we defensively reject non-loopback clients even
# though uvicorn binds to 127.0.0.1.
# ---------------------------------------------------------------------------

import re
import asyncio

from hermes_cli.pty_bridge import PtyBridge, PtyUnavailableError

_RESIZE_RE = re.compile(rb"\x1b\[RESIZE:(\d+);(\d+)\]")
_PTY_READ_CHUNK_TIMEOUT = 0.2
_VALID_CHANNEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# Starlette's TestClient reports the peer as "testclient"; treat it as
# loopback so tests don't need to rewrite request scope.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})

# Per-channel subscriber registry used by /api/pub (PTY-side gateway → dashboard)
# and /api/events (dashboard → browser sidebar).  Keyed by an opaque channel id
# the chat tab generates on mount; entries auto-evict when the last subscriber
# drops AND the publisher has disconnected.
_event_channels: dict[str, set] = {}
_event_lock = asyncio.Lock()


def _resolve_chat_argv(
    resume: Optional[str] = None,
    sidecar_url: Optional[str] = None,
) -> tuple[list[str], Optional[str], Optional[dict]]:
    """Resolve the argv + cwd + env for the chat PTY.

    Default: whatever ``hermes --tui`` would run.  Tests monkeypatch this
    function to inject a tiny fake command (``cat``, ``sh -c 'printf …'``)
    so nothing has to build Node or the TUI bundle.

    Session resume is propagated via the ``HERMES_TUI_RESUME`` env var —
    matching what ``hermes_cli.main._launch_tui`` does for the CLI path.
    Appending ``--resume <id>`` to argv doesn't work because ``ui-tui`` does
    not parse its argv.

    `sidecar_url` (when set) is forwarded as ``HERMES_TUI_SIDECAR_URL`` so
    the spawned ``tui_gateway.entry`` can mirror dispatcher emits to the
    dashboard's ``/api/pub`` endpoint (see :func:`pub_ws`).
    """
    from hermes_cli.main import PROJECT_ROOT, _make_tui_argv

    argv, cwd = _make_tui_argv(PROJECT_ROOT / "ui-tui", tui_dev=False)
    env = os.environ.copy()
    env.setdefault("NODE_ENV", "production")

    if resume:
        env["HERMES_TUI_RESUME"] = resume

    if sidecar_url:
        env["HERMES_TUI_SIDECAR_URL"] = sidecar_url

    return list(argv), str(cwd) if cwd else None, env


def _build_sidecar_url(channel: str) -> Optional[str]:
    """ws:// URL the PTY child should publish events to, or None when unbound."""
    host = getattr(app.state, "bound_host", None)
    port = getattr(app.state, "bound_port", None)

    if not host or not port:
        return None

    netloc = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
    qs = urllib.parse.urlencode({"token": _SESSION_TOKEN, "channel": channel})

    return f"ws://{netloc}/api/pub?{qs}"


async def _broadcast_event(channel: str, payload: str) -> None:
    """Fan out one publisher frame to every subscriber on `channel`."""
    async with _event_lock:
        subs = list(_event_channels.get(channel, ()))

    for sub in subs:
        try:
            await sub.send_text(payload)
        except Exception:
            # Subscriber went away mid-send; the /api/events finally clause
            # will remove it from the registry on its next iteration.
            pass


def _channel_or_close_code(ws: WebSocket) -> Optional[str]:
    """Return the channel id from the query string or None if invalid."""
    channel = ws.query_params.get("channel", "")

    return channel if _VALID_CHANNEL_RE.match(channel) else None


@app.websocket("/api/pty")
async def pty_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    # --- auth + loopback check (before accept so we can close cleanly) ---
    token = ws.query_params.get("token", "")
    expected = _SESSION_TOKEN
    if not hmac.compare_digest(token.encode(), expected.encode()):
        await ws.close(code=4401)
        return

    client_host = ws.client.host if ws.client else ""
    if client_host and client_host not in _LOOPBACK_HOSTS:
        await ws.close(code=4403)
        return

    await ws.accept()

    # --- spawn PTY ------------------------------------------------------
    resume = ws.query_params.get("resume") or None
    channel = _channel_or_close_code(ws)
    sidecar_url = _build_sidecar_url(channel) if channel else None

    try:
        argv, cwd, env = _resolve_chat_argv(resume=resume, sidecar_url=sidecar_url)
    except SystemExit as exc:
        # _make_tui_argv calls sys.exit(1) when node/npm is missing.
        await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return


    try:
        bridge = PtyBridge.spawn(argv, cwd=cwd, env=env)
    except PtyUnavailableError as exc:
        await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return
    except (FileNotFoundError, OSError) as exc:
        await ws.send_text(f"\r\n\x1b[31mChat failed to start: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return

    loop = asyncio.get_running_loop()

    # --- reader task: PTY master → WebSocket ----------------------------
    async def pump_pty_to_ws() -> None:
        while True:
            chunk = await loop.run_in_executor(
                None, bridge.read, _PTY_READ_CHUNK_TIMEOUT
            )
            if chunk is None:  # EOF
                return
            if not chunk:  # no data this tick; yield control and retry
                await asyncio.sleep(0)
                continue
            try:
                await ws.send_bytes(chunk)
            except Exception:
                return

    reader_task = asyncio.create_task(pump_pty_to_ws())

    # --- writer loop: WebSocket → PTY master ----------------------------
    try:
        while True:
            msg = await ws.receive()
            msg_type = msg.get("type")
            if msg_type == "websocket.disconnect":
                break
            raw = msg.get("bytes")
            if raw is None:
                text = msg.get("text")
                raw = text.encode("utf-8") if isinstance(text, str) else b""
            if not raw:
                continue

            # Resize escape is consumed locally, never written to the PTY.
            match = _RESIZE_RE.match(raw)
            if match and match.end() == len(raw):
                cols = int(match.group(1))
                rows = int(match.group(2))
                bridge.resize(cols=cols, rows=rows)
                continue

            bridge.write(raw)
    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass
        bridge.close()


# ---------------------------------------------------------------------------
# /api/ws — JSON-RPC WebSocket sidecar for the dashboard "Chat" tab.
#
# Drives the same `tui_gateway.dispatch` surface Ink uses over stdio, so the
# dashboard can render structured metadata (model badge, tool-call sidebar,
# slash launcher, session info) alongside the xterm.js terminal that PTY
# already paints. Both transports bind to the same session id when one is
# active, so a tool.start emitted by the agent fans out to both sinks.
# ---------------------------------------------------------------------------


@app.websocket("/api/ws")
async def gateway_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    token = ws.query_params.get("token", "")
    if not hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        await ws.close(code=4401)
        return

    client_host = ws.client.host if ws.client else ""
    if client_host and client_host not in _LOOPBACK_HOSTS:
        await ws.close(code=4403)
        return

    from tui_gateway.ws import handle_ws

    await handle_ws(ws)


# ---------------------------------------------------------------------------
# /api/pub + /api/events — chat-tab event broadcast.
#
# The PTY-side ``tui_gateway.entry`` opens /api/pub at startup (driven by
# HERMES_TUI_SIDECAR_URL set in /api/pty's PTY env) and writes every
# dispatcher emit through it.  The dashboard fans those frames out to any
# subscriber that opened /api/events on the same channel id.  This is what
# gives the React sidebar its tool-call feed without breaking the PTY
# child's stdio handshake with Ink.
# ---------------------------------------------------------------------------


@app.websocket("/api/pub")
async def pub_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    token = ws.query_params.get("token", "")
    if not hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        await ws.close(code=4401)
        return

    client_host = ws.client.host if ws.client else ""
    if client_host and client_host not in _LOOPBACK_HOSTS:
        await ws.close(code=4403)
        return

    channel = _channel_or_close_code(ws)
    if not channel:
        await ws.close(code=4400)
        return

    await ws.accept()

    try:
        while True:
            await _broadcast_event(channel, await ws.receive_text())
    except WebSocketDisconnect:
        pass


@app.websocket("/api/events")
async def events_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    token = ws.query_params.get("token", "")
    if not hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        await ws.close(code=4401)
        return

    client_host = ws.client.host if ws.client else ""
    if client_host and client_host not in _LOOPBACK_HOSTS:
        await ws.close(code=4403)
        return

    channel = _channel_or_close_code(ws)
    if not channel:
        await ws.close(code=4400)
        return

    await ws.accept()

    async with _event_lock:
        _event_channels.setdefault(channel, set()).add(ws)

    try:
        while True:
            # Subscribers don't speak — the receive() just blocks until
            # disconnect so the connection stays open as long as the
            # browser holds it.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _event_lock:
            subs = _event_channels.get(channel)

            if subs is not None:
                subs.discard(ws)

                if not subs:
                    _event_channels.pop(channel, None)


def mount_spa(application: FastAPI):
    """Mount the built SPA. Falls back to index.html for client-side routing.

    The session token is injected into index.html via a ``<script>`` tag so
    the SPA can authenticate against protected API endpoints without a
    separate (unauthenticated) token-dispensing endpoint.
    """
    if not WEB_DIST.exists():
        @application.get("/{full_path:path}")
        async def no_frontend(full_path: str):
            return JSONResponse(
                {"error": "Frontend not built. Run: cd web && npm run build"},
                status_code=404,
            )
        return

    _index_path = WEB_DIST / "index.html"

    def _serve_index():
        """Return index.html with the session token injected."""
        html = _index_path.read_text()
        chat_js = "true" if _DASHBOARD_EMBEDDED_CHAT_ENABLED else "false"
        token_script = (
            f'<script>window.__HERMES_SESSION_TOKEN__="{_SESSION_TOKEN}";'
            f"window.__HERMES_DASHBOARD_EMBEDDED_CHAT__={chat_js};</script>"
        )
        html = html.replace("</head>", f"{token_script}</head>", 1)
        return HTMLResponse(
            html,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    application.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @application.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = WEB_DIST / full_path
        # Prevent path traversal via url-encoded sequences (%2e%2e/)
        if (
            full_path
            and file_path.resolve().is_relative_to(WEB_DIST.resolve())
            and file_path.exists()
            and file_path.is_file()
        ):
            return FileResponse(file_path)
        return _serve_index()


# ---------------------------------------------------------------------------
# Dashboard theme endpoints
# ---------------------------------------------------------------------------

# Built-in dashboard themes — label + description only.  The actual color
# definitions live in the frontend (web/src/themes/presets.ts).
_BUILTIN_DASHBOARD_THEMES = [
    {"name": "default",   "label": "Hermes Teal",  "description": "Classic dark teal — the canonical Hermes look"},
    {"name": "midnight",  "label": "Midnight",      "description": "Deep blue-violet with cool accents"},
    {"name": "ember",     "label": "Ember",          "description": "Warm crimson and bronze — forge vibes"},
    {"name": "mono",      "label": "Mono",           "description": "Clean grayscale — minimal and focused"},
    {"name": "cyberpunk", "label": "Cyberpunk",      "description": "Neon green on black — matrix terminal"},
    {"name": "rose",      "label": "Rosé",           "description": "Soft pink and warm ivory — easy on the eyes"},
]


def _parse_theme_layer(value: Any, default_hex: str, default_alpha: float = 1.0) -> Optional[Dict[str, Any]]:
    """Normalise a theme layer spec from YAML into `{hex, alpha}` form.

    Accepts shorthand (a bare hex string) or full dict form.  Returns
    ``None`` on garbage input so the caller can fall back to a built-in
    default rather than blowing up.
    """
    if value is None:
        return {"hex": default_hex, "alpha": default_alpha}
    if isinstance(value, str):
        return {"hex": value, "alpha": default_alpha}
    if isinstance(value, dict):
        hex_val = value.get("hex", default_hex)
        alpha_val = value.get("alpha", default_alpha)
        if not isinstance(hex_val, str):
            return None
        try:
            alpha_f = float(alpha_val)
        except (TypeError, ValueError):
            alpha_f = default_alpha
        return {"hex": hex_val, "alpha": max(0.0, min(1.0, alpha_f))}
    return None


_THEME_DEFAULT_TYPOGRAPHY: Dict[str, str] = {
    "fontSans": 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    "fontMono": 'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace',
    "baseSize": "15px",
    "lineHeight": "1.55",
    "letterSpacing": "0",
}

_THEME_DEFAULT_LAYOUT: Dict[str, str] = {
    "radius": "0.5rem",
    "density": "comfortable",
}

_THEME_OVERRIDE_KEYS = {
    "card", "cardForeground", "popover", "popoverForeground",
    "primary", "primaryForeground", "secondary", "secondaryForeground",
    "muted", "mutedForeground", "accent", "accentForeground",
    "destructive", "destructiveForeground", "success", "warning",
    "border", "input", "ring",
}

# Well-known named asset slots themes can populate.  Any other keys under
# ``assets.custom`` are exposed as ``--theme-asset-custom-<key>`` CSS vars
# for plugin/shell use.
_THEME_NAMED_ASSET_KEYS = {"bg", "hero", "logo", "crest", "sidebar", "header"}

# Component-style buckets themes can override.  The value under each bucket
# is a mapping from camelCase property name to CSS string; each pair emits
# ``--component-<bucket>-<kebab-property>`` on :root.  The frontend's shell
# components (Card, App header, Backdrop, etc.) consume these vars so themes
# can restyle chrome (clip-path, border-image, segmented progress, etc.)
# without shipping their own CSS.
_THEME_COMPONENT_BUCKETS = {
    "card", "header", "footer", "sidebar", "tab",
    "progress", "badge", "backdrop", "page",
}

_THEME_LAYOUT_VARIANTS = {"standard", "cockpit", "tiled"}

# Cap on customCSS length so a malformed/oversized theme YAML can't blow up
# the response payload or the <style> tag.  32 KiB is plenty for every
# practical reskin (the Strike Freedom demo is ~2 KiB).
_THEME_CUSTOM_CSS_MAX = 32 * 1024


def _normalise_theme_definition(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise a user theme YAML into the wire format `ThemeProvider`
    expects.  Returns ``None`` if the theme is unusable.

    Accepts both the full schema (palette/typography/layout) and a loose
    form with bare hex strings, so hand-written YAMLs stay friendly.
    """
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    # Palette
    palette_src = data.get("palette", {}) if isinstance(data.get("palette"), dict) else {}
    # Allow top-level `colors.background` as a shorthand too.
    colors_src = data.get("colors", {}) if isinstance(data.get("colors"), dict) else {}

    def _layer(key: str, default_hex: str, default_alpha: float = 1.0) -> Dict[str, Any]:
        spec = palette_src.get(key, colors_src.get(key))
        parsed = _parse_theme_layer(spec, default_hex, default_alpha)
        return parsed if parsed is not None else {"hex": default_hex, "alpha": default_alpha}

    palette = {
        "background": _layer("background", "#041c1c", 1.0),
        "midground": _layer("midground", "#ffe6cb", 1.0),
        "foreground": _layer("foreground", "#ffffff", 0.0),
        "warmGlow": palette_src.get("warmGlow") or data.get("warmGlow") or "rgba(255, 189, 56, 0.35)",
        "noiseOpacity": 1.0,
    }
    raw_noise = palette_src.get("noiseOpacity", data.get("noiseOpacity"))
    try:
        palette["noiseOpacity"] = float(raw_noise) if raw_noise is not None else 1.0
    except (TypeError, ValueError):
        palette["noiseOpacity"] = 1.0

    # Typography
    typo_src = data.get("typography", {}) if isinstance(data.get("typography"), dict) else {}
    typography = dict(_THEME_DEFAULT_TYPOGRAPHY)
    for key in ("fontSans", "fontMono", "fontDisplay", "fontUrl", "baseSize", "lineHeight", "letterSpacing"):
        val = typo_src.get(key)
        if isinstance(val, str) and val.strip():
            typography[key] = val

    # Layout
    layout_src = data.get("layout", {}) if isinstance(data.get("layout"), dict) else {}
    layout = dict(_THEME_DEFAULT_LAYOUT)
    radius = layout_src.get("radius")
    if isinstance(radius, str) and radius.strip():
        layout["radius"] = radius
    density = layout_src.get("density")
    if isinstance(density, str) and density in ("compact", "comfortable", "spacious"):
        layout["density"] = density

    # Color overrides — keep only valid keys with string values.
    overrides_src = data.get("colorOverrides", {})
    color_overrides: Dict[str, str] = {}
    if isinstance(overrides_src, dict):
        for key, val in overrides_src.items():
            if key in _THEME_OVERRIDE_KEYS and isinstance(val, str) and val.strip():
                color_overrides[key] = val

    # Assets — named slots + arbitrary user-defined keys.  Values must be
    # strings (URLs or CSS ``url(...)``/``linear-gradient(...)`` expressions).
    # We don't fetch remote assets here; the frontend just injects them as
    # CSS vars.  Empty values are dropped so a theme can explicitly clear a
    # slot by setting ``hero: ""``.
    assets_out: Dict[str, Any] = {}
    assets_src = data.get("assets", {}) if isinstance(data.get("assets"), dict) else {}
    for key in _THEME_NAMED_ASSET_KEYS:
        val = assets_src.get(key)
        if isinstance(val, str) and val.strip():
            assets_out[key] = val
    custom_assets_src = assets_src.get("custom")
    if isinstance(custom_assets_src, dict):
        custom_assets: Dict[str, str] = {}
        for key, val in custom_assets_src.items():
            if (
                isinstance(key, str)
                and key.replace("-", "").replace("_", "").isalnum()
                and isinstance(val, str)
                and val.strip()
            ):
                custom_assets[key] = val
        if custom_assets:
            assets_out["custom"] = custom_assets

    # Custom CSS — raw CSS text the frontend injects as a scoped <style>
    # tag on theme apply.  Clipped to _THEME_CUSTOM_CSS_MAX to keep the
    # payload bounded.  We intentionally do NOT parse/sanitise the CSS
    # here — the dashboard is localhost-only and themes are user-authored
    # YAML in ~/.hermes/, same trust level as the config file itself.
    custom_css_val = data.get("customCSS")
    custom_css: Optional[str] = None
    if isinstance(custom_css_val, str) and custom_css_val.strip():
        custom_css = custom_css_val[:_THEME_CUSTOM_CSS_MAX]

    # Component style overrides — per-bucket dicts of camelCase CSS
    # property -> CSS string.  The frontend converts these into CSS vars
    # that shell components (Card, App header, Backdrop) consume.
    component_styles_src = data.get("componentStyles", {})
    component_styles: Dict[str, Dict[str, str]] = {}
    if isinstance(component_styles_src, dict):
        for bucket, props in component_styles_src.items():
            if bucket not in _THEME_COMPONENT_BUCKETS or not isinstance(props, dict):
                continue
            clean: Dict[str, str] = {}
            for prop, value in props.items():
                if (
                    isinstance(prop, str)
                    and prop.replace("-", "").replace("_", "").isalnum()
                    and isinstance(value, (str, int, float))
                    and str(value).strip()
                ):
                    clean[prop] = str(value)
            if clean:
                component_styles[bucket] = clean

    layout_variant_src = data.get("layoutVariant")
    layout_variant = (
        layout_variant_src
        if isinstance(layout_variant_src, str) and layout_variant_src in _THEME_LAYOUT_VARIANTS
        else "standard"
    )

    result: Dict[str, Any] = {
        "name": name,
        "label": data.get("label") or name,
        "description": data.get("description", ""),
        "palette": palette,
        "typography": typography,
        "layout": layout,
        "layoutVariant": layout_variant,
    }
    if color_overrides:
        result["colorOverrides"] = color_overrides
    if assets_out:
        result["assets"] = assets_out
    if custom_css is not None:
        result["customCSS"] = custom_css
    if component_styles:
        result["componentStyles"] = component_styles
    return result


def _discover_user_themes() -> list:
    """Scan ~/.hermes/dashboard-themes/*.yaml for user-created themes.

    Returns a list of fully-normalised theme definitions ready to ship
    to the frontend, so the client can apply them without a secondary
    round-trip or a built-in stub.
    """
    themes_dir = get_hermes_home() / "dashboard-themes"
    if not themes_dir.is_dir():
        return []
    result = []
    for f in sorted(themes_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        normalised = _normalise_theme_definition(data)
        if normalised is not None:
            result.append(normalised)
    return result


@app.get("/api/dashboard/themes")
async def get_dashboard_themes():
    """Return available themes and the currently active one.

    Built-in entries ship name/label/description only (the frontend owns
    their full definitions in `web/src/themes/presets.ts`).  User themes
    from `~/.hermes/dashboard-themes/*.yaml` ship with their full
    normalised definition under `definition`, so the client can apply
    them without a stub.
    """
    config = load_config()
    active = cfg_get(config, "dashboard", "theme", default="default")
    user_themes = _discover_user_themes()
    seen = set()
    themes = []
    for t in _BUILTIN_DASHBOARD_THEMES:
        seen.add(t["name"])
        themes.append(t)
    for t in user_themes:
        if t["name"] in seen:
            continue
        themes.append({
            "name": t["name"],
            "label": t["label"],
            "description": t["description"],
            "definition": t,
        })
        seen.add(t["name"])
    return {"themes": themes, "active": active}


class ThemeSetBody(BaseModel):
    name: str


@app.put("/api/dashboard/theme")
async def set_dashboard_theme(body: ThemeSetBody):
    """Set the active dashboard theme (persists to config.yaml)."""
    config = load_config()
    if "dashboard" not in config:
        config["dashboard"] = {}
    config["dashboard"]["theme"] = body.name
    save_config(config)
    return {"ok": True, "theme": body.name}


# ---------------------------------------------------------------------------
# Dashboard plugin system
# ---------------------------------------------------------------------------

def _discover_dashboard_plugins() -> list:
    """Scan plugins/*/dashboard/manifest.json for dashboard extensions.

    Checks three plugin sources (same as hermes_cli.plugins):
    1. User plugins:    ~/.hermes/plugins/<name>/dashboard/manifest.json
    2. Bundled plugins: <repo>/plugins/<name>/dashboard/manifest.json  (memory/, etc.)
    3. Project plugins: ./.hermes/plugins/  (only if HERMES_ENABLE_PROJECT_PLUGINS)
    """
    plugins = []
    seen_names: set = set()

    from hermes_cli.plugins import get_bundled_plugins_dir
    bundled_root = get_bundled_plugins_dir()
    search_dirs = [
        (get_hermes_home() / "plugins", "user"),
        (bundled_root / "memory", "bundled"),
        (bundled_root, "bundled"),
    ]
    if os.environ.get("HERMES_ENABLE_PROJECT_PLUGINS"):
        search_dirs.append((Path.cwd() / ".hermes" / "plugins", "project"))

    for plugins_root, source in search_dirs:
        if not plugins_root.is_dir():
            continue
        for child in sorted(plugins_root.iterdir()):
            if not child.is_dir():
                continue
            manifest_file = child / "dashboard" / "manifest.json"
            if not manifest_file.exists():
                continue
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                name = data.get("name", child.name)
                if name in seen_names:
                    continue
                seen_names.add(name)
                # Tab options: ``path`` + ``position`` for a new tab, optional
                # ``override`` to replace a built-in route, and ``hidden`` to
                # register the plugin component/slots without adding a tab
                # (useful for slot-only plugins like a header-crest injector).
                raw_tab = data.get("tab", {}) if isinstance(data.get("tab"), dict) else {}
                tab_info = {
                    "path": raw_tab.get("path", f"/{name}"),
                    "position": raw_tab.get("position", "end"),
                }
                override_path = raw_tab.get("override")
                if isinstance(override_path, str) and override_path.startswith("/"):
                    tab_info["override"] = override_path
                if bool(raw_tab.get("hidden")):
                    tab_info["hidden"] = True
                # Slots: list of named slot locations this plugin populates.
                # The frontend exposes ``registerSlot(pluginName, slotName, Component)``
                # on window; plugins with non-empty slots call it from their JS bundle.
                slots_src = data.get("slots")
                slots: List[str] = []
                if isinstance(slots_src, list):
                    slots = [s for s in slots_src if isinstance(s, str) and s]
                plugins.append({
                    "name": name,
                    "label": data.get("label", name),
                    "description": data.get("description", ""),
                    "icon": data.get("icon", "Puzzle"),
                    "version": data.get("version", "0.0.0"),
                    "tab": tab_info,
                    "slots": slots,
                    "entry": data.get("entry", "dist/index.js"),
                    "css": data.get("css"),
                    "has_api": bool(data.get("api")),
                    "source": source,
                    "_dir": str(child / "dashboard"),
                    "_api_file": data.get("api"),
                })
            except Exception as exc:
                _log.warning("Bad dashboard plugin manifest %s: %s", manifest_file, exc)
                continue
    return plugins


# Cache discovered plugins per-process (refresh on explicit re-scan).
_dashboard_plugins_cache: Optional[list] = None


def _get_dashboard_plugins(force_rescan: bool = False) -> list:
    global _dashboard_plugins_cache
    if _dashboard_plugins_cache is None or force_rescan:
        _dashboard_plugins_cache = _discover_dashboard_plugins()
    return _dashboard_plugins_cache


@app.get("/api/dashboard/plugins")
async def get_dashboard_plugins():
    """Return discovered dashboard plugins."""
    plugins = _get_dashboard_plugins()
    # Strip internal fields before sending to frontend.
    return [
        {k: v for k, v in p.items() if not k.startswith("_")}
        for p in plugins
    ]


@app.get("/api/dashboard/plugins/rescan")
async def rescan_dashboard_plugins():
    """Force re-scan of dashboard plugins."""
    plugins = _get_dashboard_plugins(force_rescan=True)
    invalidate_desk_catalog_cache()
    return {"ok": True, "count": len(plugins)}


@app.get("/dashboard-plugins/{plugin_name}/{file_path:path}")
async def serve_plugin_asset(plugin_name: str, file_path: str):
    """Serve static assets from a dashboard plugin directory.

    Only serves files from the plugin's ``dashboard/`` subdirectory.
    Path traversal is blocked by checking ``resolve().is_relative_to()``.
    """
    plugins = _get_dashboard_plugins()
    plugin = next((p for p in plugins if p["name"] == plugin_name), None)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    base = Path(plugin["_dir"])
    target = (base / file_path).resolve()

    if not target.is_relative_to(base.resolve()):
        raise HTTPException(status_code=403, detail="Path traversal blocked")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Guess content type
    suffix = target.suffix.lower()
    content_types = {
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".html": "text/html",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".woff2": "font/woff2",
        ".woff": "font/woff",
    }
    media_type = content_types.get(suffix, "application/octet-stream")
    return FileResponse(target, media_type=media_type)


def _mount_plugin_api_routes():
    """Import and mount backend API routes from plugins that declare them.

    Each plugin's ``api`` field points to a Python file that must expose
    a ``router`` (FastAPI APIRouter).  Routes are mounted under
    ``/api/plugins/<name>/``.
    """
    for plugin in _get_dashboard_plugins():
        api_file_name = plugin.get("_api_file")
        if not api_file_name:
            continue
        api_path = Path(plugin["_dir"]) / api_file_name
        if not api_path.exists():
            _log.warning("Plugin %s declares api=%s but file not found", plugin["name"], api_file_name)
            continue
        try:
            module_name = f"hermes_dashboard_plugin_{plugin['name']}"
            spec = importlib.util.spec_from_file_location(module_name, api_path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            # Register in sys.modules BEFORE exec_module so pydantic/FastAPI
            # can resolve forward references (e.g. models defined in a file
            # that uses `from __future__ import annotations`). Without this,
            # TypeAdapter lazy-build fails at first request with
            # "is not fully defined" because the module namespace isn't
            # reachable by name for string-annotation resolution.
            sys.modules[module_name] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception:
                sys.modules.pop(module_name, None)
                raise
            router = getattr(mod, "router", None)
            if router is None:
                _log.warning("Plugin %s api file has no 'router' attribute", plugin["name"])
                continue
            app.include_router(router, prefix=f"/api/plugins/{plugin['name']}")
            _log.info("Mounted plugin API routes: /api/plugins/%s/", plugin["name"])
        except Exception as exc:
            _log.warning("Failed to load plugin %s API routes: %s", plugin["name"], exc)


# Mount plugin API routes before the SPA catch-all.
_mount_plugin_api_routes()

mount_spa(app)


def start_server(
    host: str = "127.0.0.1",
    port: int = 9119,
    open_browser: bool = True,
    allow_public: bool = False,
    *,
    embedded_chat: bool = False,
):
    """Start the web UI server."""
    import uvicorn

    global _DASHBOARD_EMBEDDED_CHAT_ENABLED
    _DASHBOARD_EMBEDDED_CHAT_ENABLED = embedded_chat

    _LOCALHOST = ("127.0.0.1", "localhost", "::1")
    if host not in _LOCALHOST and not allow_public:
        raise SystemExit(
            f"Refusing to bind to {host} — the dashboard exposes API keys "
            f"and config without robust authentication.\n"
            f"Use --insecure to override (NOT recommended on untrusted networks)."
        )
    if host not in _LOCALHOST:
        _log.warning(
            "Binding to %s with --insecure — the dashboard has no robust "
            "authentication. Only use on trusted networks.", host,
        )

    # Record the bound host so host_header_middleware can validate incoming
    # Host headers against it. Defends against DNS rebinding (GHSA-ppp5-vxwm-4cf7).
    # bound_port is also stashed so /api/pty can build the back-WS URL the
    # PTY child uses to publish events to the dashboard sidebar.
    app.state.bound_host = host
    app.state.bound_port = port

    if open_browser:
        import webbrowser

        def _open():
            time.sleep(1.0)
            webbrowser.open(f"http://{host}:{port}")

        threading.Thread(target=_open, daemon=True).start()

    print(f"  Hermes Web UI → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
