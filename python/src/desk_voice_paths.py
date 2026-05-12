"""HermesDesk: shared paths for local STT model + desk voice scratch files.

Keeps GGML downloads and ephemeral audio under ``HERMESDESK_WORKSPACE`` so they
live next to the agent's default workspace. Legacy locations (``HERMESDESK_DATA_DIR``
etc.) remain in the search list so existing installs keep working until the user
re-downloads into the workspace tree.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional


_VOICE_SUBDIR = ".hermesdesk"
_STT_SUBDIR = "stt-models"
_VOICE_TMP_SUBDIR = "voice-tmp"
_VOICE_WORK_SUBDIR = "voice-work"


def workspace_root_resolved() -> Optional[Path]:
    raw = (os.environ.get("HERMESDESK_WORKSPACE") or "").strip()
    return Path(raw) if raw else None


def workspace_stt_models_dir() -> Optional[Path]:
    """``<workspace>/.hermesdesk/stt-models`` when workspace is configured."""
    root = workspace_root_resolved()
    if root is None:
        return None
    return root / _VOICE_SUBDIR / _STT_SUBDIR


def workspace_voice_tmp_dir() -> Optional[Path]:
    """Scratch dir for inbound desk audio before transcription."""
    root = workspace_root_resolved()
    if root is None:
        return None
    return root / _VOICE_SUBDIR / _VOICE_TMP_SUBDIR


def workspace_voice_work_dir() -> Optional[Path]:
    """Work dir for ffmpeg + local STT command outputs (HermesDesk)."""
    root = workspace_root_resolved()
    if root is None:
        return None
    return root / _VOICE_SUBDIR / _VOICE_WORK_SUBDIR


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def legacy_data_stt_model_path(filename: str) -> Optional[Path]:
    """Pre-workspace layout: under data dir or ``LOCALAPPDATA\\HermesDesk``."""
    data_dir = os.environ.get("HERMESDESK_DATA_DIR") or os.environ.get("LOCALAPPDATA")
    if not data_dir:
        return None
    base = Path(data_dir)
    if "LOCALAPPDATA" in os.environ and base == Path(os.environ["LOCALAPPDATA"]):
        base = base / "HermesDesk"
    return base / _STT_SUBDIR / filename


def canonical_stt_model_path(filename: str, *, no_env_fallback_dir: Path) -> Path:
    """Single write target for lazy-download + status ``path`` when missing."""
    wdir = workspace_stt_models_dir()
    if wdir is not None:
        return wdir / filename
    leg = legacy_data_stt_model_path(filename)
    if leg is not None:
        return leg
    return no_env_fallback_dir / _STT_SUBDIR / filename


def stt_model_search_paths(
    filename: str, *, no_env_fallback_dir: Path
) -> list[Path]:
    """Try in order: workspace, legacy data-dir tree, then ``no_env_fallback_dir``."""
    paths: list[Path] = []
    wdir = workspace_stt_models_dir()
    if wdir is not None:
        paths.append(wdir / filename)
    leg = legacy_data_stt_model_path(filename)
    if leg is not None:
        paths.append(leg)
    paths.append(no_env_fallback_dir / _STT_SUBDIR / filename)
    return _dedupe_paths(paths)


def resolve_existing_stt_model(
    filename: str, *, no_env_fallback_dir: Path
) -> Optional[Path]:
    """First path on disk, or ``None`` if none exist."""
    for p in stt_model_search_paths(filename, no_env_fallback_dir=no_env_fallback_dir):
        if p.is_file():
            return p
    return None
