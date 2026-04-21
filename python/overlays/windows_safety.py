"""(Reserved) Defensive Windows compatibility shims.

Originally this overlay no-op'd POSIX-only `os.*` attributes on Windows
(`os.fork`, `os.setsid`, `os.killpg`, etc.) so that any unguarded
upstream call sites would be harmless. **That approach was wrong**:
much of the Python standard library uses `hasattr(os, "fork")` as a
feature flag (see `Lib/random.py`, `Lib/multiprocessing/`, etc.). When
we synthesise a fake `os.fork`, those `hasattr` checks return True
and the stdlib then calls *other* POSIX-only functions (e.g.
`os.register_at_fork`) that still don't exist, crashing module load.

The audit (docs/windows-port-audit.md) confirms that every posix-only
call in our default-on keep-list is already platform-guarded upstream.
Stripped subsystems (gateway, RL, tui_gateway) never load. So we
deliberately do nothing here.

If a future upstream change re-introduces an unguarded posix call into
the keep-list, prefer fixing it via:

  1. Add the file to `$drop` in `python/build_bundle.ps1` (if it's
     dispensable), or
  2. Add a targeted *symbol* monkey-patch (e.g. patch the specific
     function on the specific module) in a new overlay. **Never** patch
     attributes on the global `os` module.
"""

from __future__ import annotations


def install() -> None:  # noqa: D401
    """Intentionally a no-op. See module docstring for rationale."""
    return None
