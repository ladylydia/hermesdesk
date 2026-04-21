"""L1 built-in helpers: whitelist ``run_builtin_helper`` (no generic code_execution).

HermesDesk ships a fixed set of Python modules under ``helpers/``. The LLM
can only invoke them by name through this tool; arbitrary code, imports,
and runtime downloads are not part of this path.

See: ``docs/skills-design-decision.md`` (ADR) and ``docs/skills-security.md``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict

log = logging.getLogger("hermesdesk.builtin_helpers")

_ALLOWED: frozenset[str] = frozenset(
    {"folder_organize", "excel_to_word", "pdf_digest", "image_batch"}
)
_HELPERS: Dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _load_helpers() -> None:
    global _HELPERS
    if _HELPERS:
        return
    from helpers import excel_to_word, folder_organize, image_batch, pdf_digest

    _HELPERS.update(
        {
            "folder_organize": folder_organize.run,
            "excel_to_word": excel_to_word.run,
            "pdf_digest": pdf_digest.run,
            "image_batch": image_batch.run,
        }
    )


RUN_BUILTIN_HELPER_SCHEMA: dict[str, Any] = {
    "name": "run_builtin_helper",
    "description": (
        "HermesDesk L1: run a signed, bundled helper script (strict whitelist). "
        "This is not general code execution — only predefined helpers run, with "
        "no runtime download. Helpers: folder_organize (sort by type, optional "
        "dry_run), excel_to_word (xlsx/xlsm → docx), pdf_digest (folder PDF excerpts), "
        "image_batch (image counts / thumbnails when Pillow is available)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Helper id: folder_organize | excel_to_word | pdf_digest | image_batch"
                ),
            },
            "args": {
                "type": "object",
                "description": (
                    "Arguments for the helper. Examples: folder_organize: "
                    "{folder: '.', dry_run: false}; image_batch: {folder: '.', "
                    "action: 'info'|'thumbnail', max_size: 256, dry_run: false}."
                ),
            },
        },
        "required": ["name", "args"],
    },
}


def _handle_run_builtin_helper(args: dict[str, Any], **kw: Any) -> str:
    _ = kw
    from tools.registry import tool_error

    name = str(args.get("name") or "").strip().lower()
    inner = args.get("args")
    if not isinstance(inner, dict):
        inner = {}
    if name not in _ALLOWED:
        return tool_error(f"helper {name!r} is not in the HermesDesk whitelist")
    fn = _HELPERS.get(name)
    if fn is None:
        return tool_error(f"helper {name!r} is not loaded")
    try:
        out = fn(inner)
        if not isinstance(out, dict):
            out = {"result": out}
        payload = {"ok": True, "helper": name, **out}
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — surface to model as tool error
        log.exception("builtin helper %s failed", name)
        return tool_error(str(exc))


def _patch_file_toolset() -> None:
    import toolsets as toolsets_mod

    file_entry = toolsets_mod.TOOLSETS.get("file")
    if not file_entry:
        return
    tools_list = file_entry.setdefault("tools", [])
    if "run_builtin_helper" not in tools_list:
        tools_list.append("run_builtin_helper")


def install() -> None:
    from tools.registry import registry

    _load_helpers()
    if "run_builtin_helper" in registry.get_all_tool_names():
        log.debug("run_builtin_helper already registered")
        return

    _patch_file_toolset()
    registry.register(
        name="run_builtin_helper",
        toolset="file",
        schema=RUN_BUILTIN_HELPER_SCHEMA,
        handler=_handle_run_builtin_helper,
        check_fn=lambda: True,
        emoji="🧰",
    )
    log.info("registered run_builtin_helper (%d helpers)", len(_HELPERS))
