"""Make stripped Hermes subpackages importable as harmless no-ops.

HermesDesk's Python bundle does not include `gateway`, `tui_gateway`,
`acp_adapter`, `acp_registry`, or the RL helpers. Some upstream code
imports these unconditionally from `hermes_cli/main.py` and other
dispatchers. Rather than carry a fragile source patch, we register
placeholder modules in `sys.modules`.

Two flavours of placeholder exist:

* `_Stripped` -- attribute access raises ImportError with a clear message.
  Used for fully removed subsystems (e.g. RL training).
* `_StubModule` -- exposes a small set of pre-populated attributes
  (typically callables that return None). Used when upstream `web_server`
  / `main` code imports specific symbols at module load that we cannot
  let raise.
"""

from __future__ import annotations

import sys
import types
from typing import Any, Dict


_STRIPPED = (
    "tui_gateway",
    "tui_gateway.entry",
    "acp_adapter",
    "acp_adapter.entry",
    "acp_registry",
    "rl_cli",
    "batch_runner",
    "mini_swe_runner",
    "tinker_atropos",
    "atroposlib",
    "tinker",
    "wandb",
)


def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def _empty_dict(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
    return {}


_STUBBED: Dict[str, Dict[str, Any]] = {
    # web_server.py imports these at module load; they query a running
    # messaging-gateway process. HermesDesk never runs that gateway, so
    # both return "no gateway present".
    "gateway": {},
    "gateway.status": {
        "get_running_pid": _noop,
        "read_runtime_status": _noop,
        "write_pid_file": _noop,
        "write_runtime_status": _noop,
        "terminate_pid": _noop,
    },
    "gateway.run": {
        "main": _noop,
    },
    "gateway.config": {
        "load_config": _empty_dict,
    },
    "gateway.platforms": {},
}


class _Stripped(types.ModuleType):
    """Module-shaped object whose attribute access raises a friendly error."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.__hermesdesk_stripped__ = True

    def __getattr__(self, attr: str):  # noqa: D401
        raise ImportError(
            f"'{self.__name__}.{attr}' is not available in HermesDesk. "
            f"This feature was removed for the desktop build. "
            f"Use the upstream Hermes Agent CLI for full functionality."
        )


class _StubModule(types.ModuleType):
    """Module-shaped object with a fixed set of attributes pre-populated."""

    def __init__(self, name: str, attrs: Dict[str, Any]) -> None:
        super().__init__(name)
        self.__hermesdesk_stubbed__ = True
        for k, v in attrs.items():
            setattr(self, k, v)

    def __getattr__(self, attr: str):  # noqa: D401
        # Unknown attribute: return a no-op callable so .foo() doesn't crash.
        return _noop


def install() -> None:
    for name, attrs in _STUBBED.items():
        if name not in sys.modules:
            sys.modules[name] = _StubModule(name, attrs)

    for name in _STRIPPED:
        if name not in sys.modules:
            sys.modules[name] = _Stripped(name)
