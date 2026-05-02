"""PathPolicy — confine file operations to allowed directories.

Extracted from ``overlays/workspace_jail.py`` and ``overlays/path_guard.py``.
This is the target replacement: a single policy object that knows which
paths are readable/writable, without monkey-patching ``builtins.open``.
"""

from __future__ import annotations

import os
import os.path
from pathlib import Path
from typing import Iterable


class PathPolicyError(PermissionError):
    """Raised when a path escapes the permitted allowlist."""


class PathPolicy:
    """Resolve and validate a path against the configured root + extra dirs."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        extra_read: Iterable[Path] = (),
        extra_write: Iterable[Path] = (),
    ) -> None:
        self._root = self._norm(workspace_root)
        self._extra_read = [self._norm(p) for p in extra_read]
        self._extra_write = [self._norm(p) for p in extra_write]

    @staticmethod
    def _norm(path: str | os.PathLike) -> Path:
        return Path(os.path.realpath(os.path.abspath(os.fspath(path))))

    def enforce(self, path: str | os.PathLike, *, write: bool = False) -> Path:
        p = self._norm(path)
        roots = [self._root] + self._extra_write
        if not write:
            roots = roots + self._extra_read
        for r in roots:
            try:
                p.relative_to(r)
                return p
            except ValueError:
                pass
        action = "write" if write else "read"
        raise PathPolicyError(
            f"HermesDesk path policy blocked {action} "
            f"to {p!s} (allowed root: {self._root!s})"
        )

    @property
    def workspace_root(self) -> Path:
        return self._root
