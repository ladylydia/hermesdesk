"""
Path guard for the messaging gateway.

# DEPRECATED: path_policy.remove_when=Phase4
# Target replacement: ``python/src/path_policy.py``

Installs a lightweight file-system jail that restricts agent-initiated
file operations to a configurable workspace root.  The gateway process
itself is unaffected — only file_tools calls funnel through the guarded
entry points.

Activates when ``GATEWAY_WORKSPACE_ROOT`` is set (HermesDesk sets this
from ``HERMESDESK_WORKSPACE``).  When unset, the guard is a no-op.

The actual path-checking logic is delegated to ``path_policy.PathPolicy``
(Phase 3A).  This overlay only installs the monkey-patches.
"""

from __future__ import annotations

import builtins
import logging
import os
import shutil
import sys
from pathlib import Path

log = logging.getLogger("gateway.path_guard")

try:
    from path_policy import PathPolicy
except ImportError:
    _src = str(Path(__file__).resolve().parent.parent / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from path_policy import PathPolicy

_policy = None  # type: PathPolicy | None
_installed = False

_orig_open = builtins.open
_patched = []


def _norm(p):
    return PathPolicy._norm(p)


def _check(path, write=None):
    if _policy is None:
        return _norm(path)
    return _policy.enforce(path, write=bool(write))


def _safe_open(file, mode="r", *args, **kwargs):
    write_modes = {"w", "x", "a", "+"}
    is_write = any(c in mode for c in write_modes)
    if isinstance(file, (str, bytes, os.PathLike)):
        _check(file, write=is_write)
    return _orig_open(file, mode, *args, **kwargs)


def _wrap_unary_write(name):
    orig = getattr(os, name)

    def wrapper(path, *args, **kwargs):
        _check(path, write=True)
        return orig(path, *args, **kwargs)

    wrapper.__name__ = name
    return orig, wrapper


def _wrap_binary_write(name):
    orig = getattr(os, name)

    def wrapper(src, dst, *args, **kwargs):
        _check(src, write=True)
        _check(dst, write=True)
        return orig(src, dst, *args, **kwargs)

    wrapper.__name__ = name
    return orig, wrapper


def _replace(obj, name, new):
    old = getattr(obj, name)
    _patched.append((obj, name, old))
    setattr(obj, name, new)


def _make_shutil_shim(orig, name):
    def wrapper(src, dst, *a, **kw):
        _check(src, write=False)
        _check(dst, write=True)
        return orig(src, dst, *a, **kw)

    wrapper.__name__ = name
    return wrapper


def install(workspace=None):
    global _policy, _installed
    if _installed:
        return

    _root_str = (
        workspace
        or os.environ.get("GATEWAY_WORKSPACE_ROOT")
        or os.environ.get("HERMESDESK_WORKSPACE")
        or os.environ.get("MESSAGING_CWD")
    )
    if not _root_str:
        log.info("No workspace root configured — path guard inactive")
        _installed = True
        return

    _root = _norm(_root_str)
    try:
        _root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    _extra_write: list[Path] = []
    _extra_read: list[Path] = []

    _hermes_home = os.environ.get("HERMES_HOME")
    if _hermes_home:
        _extra_write.append(Path(_hermes_home))

    _data_dir = os.environ.get("HERMESDESK_DATA_DIR")
    if _data_dir:
        _extra_write.append(Path(_data_dir))

    for _tmp_key in ("TEMP", "TMP"):
        _tmp = os.environ.get(_tmp_key)
        if _tmp:
            _extra_write.append(Path(_tmp))
            break

    _extra_read.extend(
        Path(p)
        for p in [
            os.path.dirname(os.__file__),
            os.path.dirname(os.path.dirname(os.__file__)),
        ]
    )

    _policy = PathPolicy(
        _root,
        extra_read=_extra_read,
        extra_write=_extra_write,
    )

    builtins.open = _safe_open

    for n in ("remove", "unlink", "mkdir", "makedirs", "rmdir"):
        if hasattr(os, n):
            _, w = _wrap_unary_write(n)
            _replace(os, n, w)
    for n in ("rename", "replace"):
        if hasattr(os, n):
            _, w = _wrap_binary_write(n)
            _replace(os, n, w)

    for n in ("copy", "copy2", "copyfile", "move"):
        if hasattr(shutil, n):
            orig = getattr(shutil, n)
            _replace(shutil, n, _make_shutil_shim(orig, n))

    if hasattr(shutil, "rmtree"):
        _origtree = shutil.rmtree

        def _rmtree(path, *a, **kw):
            _check(path, write=True)
            return _origtree(path, *a, **kw)

        _replace(shutil, "rmtree", _rmtree)

    _installed = True
    log.info(
        "Gateway path guard active — workspace=%s, extra_write=%d, extra_read=%d",
        _workspace_root,
        len(_extra_write_roots),
        len(_extra_read_roots),
    )
