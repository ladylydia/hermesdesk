"""ApprovalBackend — POST shell-command approval requests to Tauri bridge.

Extracted from ``overlays/approval_bridge.py``.
Target replacement: injected policy instead of monkey-patching
``tools/approval.prompt_dangerous_approval``.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shlex
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("hermesdesk.approval")

_READ_COMMANDS = {"cat", "type", "more", "gc", "get-content"}
_SHELL_METACHARS = ("|", ";", "&", ">", "<", "`", "$(")
_PYTHON_RE = re.compile(
    r"^\s*(?:python|python3|py)(?:\.exe)?\s+(?:-[^\s]+\s+)*-c\s+([\"'])(?P<code>.*)\1\s*$",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN_PY_IMPORTS = {
    "builtins",
    "os",
    "shutil",
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "httpx",
    "pathlib2",
}
_FORBIDDEN_PY_CALLS = {
    "write_text",
    "write_bytes",
    "unlink",
    "remove",
    "rmdir",
    "mkdir",
    "rename",
    "replace",
    "chmod",
    "chown",
    "open",
    "system",
    "popen",
    "run",
    "Popen",
}
_SAFE_LITERAL_PATH_CALLS = {
    "Path",
    "open",
    "Presentation",
    "ZipFile",
}


def _workspace_root() -> Path | None:
    raw = (
        os.environ.get("HERMESDESK_WORKSPACE")
        or os.environ.get("HERMES_WORKSPACE")
        or os.environ.get("TERMINAL_CWD")
        or ""
    ).strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except OSError:
        return None


def _resolve_workspace_path(raw: str, workspace: Path) -> Path | None:
    s = raw.strip().strip("\"'")
    if not s or s.startswith("-"):
        return None
    try:
        p = Path(s).expanduser()
        if not p.is_absolute():
            p = workspace / p
        return p.resolve(strict=False)
    except OSError:
        return None


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _split_command(command: str) -> list[str]:
    try:
        return [t.strip("\"'") for t in shlex.split(command, posix=False)]
    except ValueError:
        return []


def _unwrap_powershell_command(command: str) -> str:
    tokens = _split_command(command)
    if not tokens:
        return command
    exe = Path(tokens[0]).name.lower()
    if exe not in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return command
    lowered = [t.lower() for t in tokens]
    for flag in ("-command", "-c"):
        if flag in lowered:
            idx = lowered.index(flag)
            return " ".join(tokens[idx + 1:]).strip().strip("\"'")
    return command


def _is_simple_workspace_read_command(command: str, workspace: Path) -> bool:
    inner = _unwrap_powershell_command(command).strip()
    lowered = inner.lower()
    if any(ch in lowered for ch in _SHELL_METACHARS):
        return False

    tokens = _split_command(inner)
    if len(tokens) < 2:
        return False
    cmd = Path(tokens[0]).name.lower()
    if cmd not in _READ_COMMANDS:
        return False

    paths: list[Path] = []
    for token in tokens[1:]:
        if not token or token.startswith("-"):
            continue
        p = _resolve_workspace_path(token, workspace)
        if p is None:
            return False
        paths.append(p)
    return bool(paths) and all(_is_under(p, workspace) for p in paths)


def _python_code_from_command(command: str) -> str | None:
    m = _PYTHON_RE.match(command)
    if m:
        return m.group("code")

    tokens = _split_command(_unwrap_powershell_command(command).strip())
    if not tokens:
        return None
    exe = Path(tokens[0]).name.lower()
    if exe not in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}:
        return None
    for idx, token in enumerate(tokens[1:], start=1):
        if token.lower() == "-c" and idx + 1 < len(tokens):
            return tokens[idx + 1]
    return None


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _literal_str(node: ast.AST, literal_vars: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return literal_vars.get(node.id)
    return None


def _literal_path_from_call(
    node: ast.Call,
    literal_vars: dict[str, str],
    safe_call_names: set[str],
) -> str | None:
    if not node.args:
        return None
    if _call_name(node) not in safe_call_names:
        return None
    return _literal_str(node.args[0], literal_vars)


def _literal_string_assignments(tree: ast.AST) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = _literal_str(node.value, {})
            if value is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = _literal_str(node.value, {}) if node.value is not None else None
            if value is not None:
                out[node.target.id] = value
    return out


def _safe_path_call_names(tree: ast.AST) -> set[str]:
    names = set(_SAFE_LITERAL_PATH_CALLS)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        module = node.module.split(".", 1)[0]
        if module not in {"pathlib", "pptx", "zipfile"}:
            continue
        for alias in node.names:
            if alias.name in _SAFE_LITERAL_PATH_CALLS:
                names.add(alias.asname or alias.name)
    return names


def _is_python_workspace_read_command(command: str, workspace: Path) -> bool:
    code = _python_code_from_command(command)
    if not code:
        return False
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    read_path_seen = False
    literal_vars = _literal_string_assignments(tree)
    safe_call_names = _safe_path_call_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name.split(".", 1)[0] for a in getattr(node, "names", [])]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".", 1)[0])
            if any(n in _FORBIDDEN_PY_IMPORTS for n in names):
                return False

        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in _FORBIDDEN_PY_CALLS:
                # open() is allowed only for literal read modes.
                if name == "open":
                    if not node.args or _literal_str(node.args[0], literal_vars) is None:
                        return False
                    mode = "r"
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                        mode = str(node.args[1].value)
                    for kw in node.keywords:
                        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                            mode = str(kw.value.value)
                    if not mode.startswith("r") or "+" in mode:
                        return False
                else:
                    return False

            literal = _literal_path_from_call(node, literal_vars, safe_call_names)
            if literal:
                p = _resolve_workspace_path(literal, workspace)
                if p is None or not _is_under(p, workspace):
                    return False
                read_path_seen = True

    return read_path_seen


def _auto_approve_workspace_read(command: str) -> bool:
    workspace = _workspace_root()
    if workspace is None:
        return False
    return (
        _is_simple_workspace_read_command(command, workspace)
        or _is_python_workspace_read_command(command, workspace)
    )


class ApprovalBackend:
    """Route dangerous-command approvals to a Tauri native dialog."""

    def ask(self, command: str, description: str = "") -> str:
        """Return 'once' if allowed, 'deny' otherwise."""
        if _auto_approve_workspace_read(command):
            log.info("auto-approved workspace read command: %s", command[:200])
            return "once"

        return self._post({
            "type": "shell",
            "command": command,
            "description": description,
        })

    def ask_messaging(self, target: str, content_preview: str = "",
                      attachments: list[str] | None = None) -> str:
        """Ask approval for a send_message to a remote target.

        Returns 'once' if allowed, 'deny' otherwise.
        """
        return self._post({
            "type": "messaging",
            "target": target,
            "content_preview": content_preview[:500],
            "attachments": attachments or [],
        })

    def ask_cron(self, action: str, schedule: str = "",
                 description: str = "", delivery_target: str = "") -> str:
        """Ask approval for a cronjob create/update.

        Returns 'once' if allowed, 'deny' otherwise.
        """
        return self._post({
            "type": "cron",
            "action": action,
            "schedule": schedule,
            "description": description[:500],
            "delivery_target": delivery_target,
        })

    def _post(self, payload: dict) -> str:
        url = os.environ.get("HERMESDESK_APPROVAL_URL")
        if not url:
            log.warning("no HERMESDESK_APPROVAL_URL; denying request")
            return "deny"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:  # nosec - loopback
                body = json.loads(resp.read())
                return "once" if bool(body.get("allowed")) else "deny"
        except urllib.error.URLError:
            log.exception("approval bridge unreachable; denying")
            return "deny"
        except Exception:
            log.exception("approval bridge error; denying")
            return "deny"
