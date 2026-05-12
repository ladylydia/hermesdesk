"""Workspace-folder jail (m4).

# DEPRECATED: path_policy.remove_when=Phase4
# Target replacement: ``python/src/policies/path_policy.py``

All file operations Hermes performs must stay inside a single workspace
folder, by default %USERPROFILE%\\Documents\\KabuqinaWork. We enforce
this by wrapping the small set of "open file" entry points that every
Hermes file tool funnels through:

    builtins.open
    pathlib.Path.open / .read_text / .write_text / .read_bytes / .write_bytes
    os.open
    shutil.copy / .copy2 / .move / .rmtree
    os.remove / os.unlink / os.rename / os.replace / os.makedirs

For each, we resolve the target path, then reject anything that
canonicalises outside the workspace root. Reads from a curated allowlist
of "system" paths (the bundle's own data dir, temp, and read-only OS
locations needed for imports) are permitted.

Configuration is read from environment variables set by the Tauri shell:

    HERMESDESK_WORKSPACE   absolute path of the workspace folder
    HERMESDESK_BUNDLE_DIR  absolute path of the installed app dir
    HERMESDESK_DATA_DIR    absolute path of the per-user data dir

The actual path-checking logic is delegated to
``python/src/policies/path_policy.py`` (Phase 3A).  This overlay only
installs the monkey-patches that wire ``builtins.open`` / ``os.*`` /
``shutil.*`` to the policy.
"""

from __future__ import annotations

import builtins
import logging
import os
import os.path
import shutil
from pathlib import Path
from typing import Iterable

log = logging.getLogger("hermesdesk.jail")

try:
    from path_policy import PathPolicy, PathPolicyError  # type: ignore[import-untyped]
except ImportError:
    # Dev layout: python/src/ not yet on sys.path.
    _src = str(Path(__file__).resolve().parent.parent / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)
    from path_policy import PathPolicy, PathPolicyError  # type: ignore[import-untyped]

JailError = PathPolicyError  # backward-compat

_policy: PathPolicy | None = None
_installed = False


def _norm(p: str | os.PathLike) -> Path:
    return PathPolicy._norm(p)  # type: ignore[attr-defined]


def _check(path: str | os.PathLike, *, write: bool) -> Path:
    if _policy is None:
        return _norm(path)
    return _policy.enforce(path, write=write)


# --- builtins.open wrapper -------------------------------------------------

_orig_open = builtins.open


def _safe_open(file, mode="r", *args, **kwargs):
    write_modes = {"w", "x", "a", "+"}
    is_write = any(c in mode for c in write_modes)
    # Only check string/Path arguments; ints (file descriptors) bypass.
    if isinstance(file, (str, bytes, os.PathLike)):
        _check(file, write=is_write)
    return _orig_open(file, mode, *args, **kwargs)


# --- os.* wrappers ---------------------------------------------------------

def _wrap_unary_write(name):
    orig = getattr(os, name)

    def wrapper(path, *args, **kwargs):
        _check(path, write=True)
        return orig(path, *args, **kwargs)

    wrapper.__name__ = name
    wrapper.__wrapped_by_hermesdesk__ = True  # type: ignore[attr-defined]
    return orig, wrapper


def _wrap_binary_write(name):
    orig = getattr(os, name)

    def wrapper(src, dst, *args, **kwargs):
        _check(src, write=True)
        _check(dst, write=True)
        return orig(src, dst, *args, **kwargs)

    wrapper.__name__ = name
    wrapper.__wrapped_by_hermesdesk__ = True  # type: ignore[attr-defined]
    return orig, wrapper


_replaced: list[tuple[object, str, object]] = []


def _replace(obj, name, new):
    old = getattr(obj, name)
    _replaced.append((obj, name, old))
    setattr(obj, name, new)


# --- public install -------------------------------------------------------

def configure(workspace: Path,
              extra_read: Iterable[Path] = (),
              extra_write: Iterable[Path] = ()) -> None:
    global _policy
    _policy = PathPolicy(
        workspace,
        extra_read=list(extra_read),
        extra_write=list(extra_write),
    )
    workspace.mkdir(parents=True, exist_ok=True)
    log.info("workspace jail root = %s", workspace)


def install() -> None:
    global _installed
    if _installed:
        return

    workspace_env = os.environ.get("HERMESDESK_WORKSPACE")
    bundle_env = os.environ.get("HERMESDESK_BUNDLE_DIR")
    data_env = os.environ.get("HERMESDESK_DATA_DIR")

    if not workspace_env:
        log.warning("HERMESDESK_WORKSPACE not set; jail running in permissive mode")
        _installed = True
        return

    extra_read: list[Path] = []
    extra_write: list[Path] = []

    if bundle_env:
        extra_read.append(Path(bundle_env))

    # Gateway children (bots) must NOT get the full data_dir in extra_write —
    # that would allow cross-profile reads/writes via the file tool.  They only
    # get their own HERMES_HOME (a per-platform profile), set by the Rust
    # supervisor at spawn time.  The host (desktop agent) gets the full
    # data_dir as before.
    is_gateway_child = bool(os.environ.get("HERMESDESK_GATEWAY_PLATFORM"))
    if data_env and not is_gateway_child:
        extra_write.append(Path(data_env))

    # Hermes' own config/cache root (set by desktop_entrypoint to a path
    # inside HERMESDESK_DATA_DIR). Without this Hermes can't persist its
    # config.yaml, sessions, or permanent allowlist.
    # For gateway children HERMES_HOME is set to <data_dir>/hermes-home/profiles/<platform>/.
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        extra_write.append(Path(hermes_home))

    # Allow reading/writing in temp; many libs (httpx caches, fal-client) need it
    extra_write.append(Path(os.environ.get("TEMP", os.environ.get("TMP", "C:/Windows/Temp"))))

    # Read-only OS paths (Python stdlib, site-packages bundled with the app)
    extra_read.extend(Path(p) for p in [
        os.path.dirname(os.__file__),  # stdlib
        os.path.dirname(os.path.dirname(os.__file__)),  # python install root
    ])

    configure(Path(workspace_env), extra_read=extra_read, extra_write=extra_write)

    builtins.open = _safe_open  # type: ignore[assignment]

    for n in ("remove", "unlink", "mkdir", "makedirs", "rmdir"):
        if hasattr(os, n):
            _, w = _wrap_unary_write(n)
            _replace(os, n, w)
    for n in ("rename", "replace", "link", "symlink"):
        if hasattr(os, n):
            _, w = _wrap_binary_write(n)
            _replace(os, n, w)

    # shutil
    for n in ("copy", "copy2", "copyfile", "move"):
        if hasattr(shutil, n):
            orig = getattr(shutil, n)

            def make(orig=orig, n=n):
                def wrapper(src, dst, *a, **kw):
                    _check(src, write=False)
                    _check(dst, write=True)
                    return orig(src, dst, *a, **kw)

                wrapper.__name__ = n
                return wrapper

            _replace(shutil, n, make())

    if hasattr(shutil, "rmtree"):
        orig = shutil.rmtree

        def _rmtree(path, *a, **kw):
            _check(path, write=True)
            return orig(path, *a, **kw)

        _replace(shutil, "rmtree", _rmtree)

    _installed = True


def uninstall_for_tests() -> None:
    """Restore originals; used by tests only."""
    global _installed
    builtins.open = _orig_open  # type: ignore[assignment]
    while _replaced:
        obj, name, old = _replaced.pop()
        setattr(obj, name, old)
    _installed = False
