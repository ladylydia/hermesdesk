"""HermesDesk local STT wrapper: bridges Hermes' ``local_command`` template to whisper.cpp.

Hermes' ``transcribe_audio`` invokes ``HERMES_LOCAL_STT_COMMAND`` after
formatting four placeholders into it:

    {input_path} {output_dir} {language} {model}

It then reads the first ``*.txt`` file produced under ``{output_dir}`` and
returns its contents as the transcript (see
``hermes_core/tools/transcription_tools.py::_transcribe_local_command``).

This script is what we plug in. It:
  1. Validates the bundled ``whisper-cli.exe`` + ``ffmpeg.exe`` exist.
  2. Verifies the GGML model exists at the desk canonical path (preferred:
     ``<HERMESDESK_WORKSPACE>/.hermesdesk/stt-models/``, with legacy locations
     still accepted) or exits 2 with ``STT_MODEL_MISSING``.
  3. Resamples the input to 16 kHz mono PCM WAV via ffmpeg (whisper.cpp does
     not decode webm and is picky about sample rate).
  4. Runs whisper.cpp with ``-otxt -of <prefix>`` so it writes
     ``<output_dir>/transcript.txt`` exactly where Hermes will read it.

Exit codes:
    0  success (transcript written)
    2  STT_MODEL_MISSING — model file not found; UI should offer to download
    3  binary missing / corrupted bundle
    4  ffmpeg failed (input audio not decodable)
    5  whisper.cpp run failed
    6  bad arguments
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

MODEL_FILENAME = "ggml-base-q5_1.bin"

try:
    import desk_voice_paths as _dvp  # type: ignore[import-untyped]
except ImportError:
    _dvp = None

# ---- Bootstrap site-packages so zhconv is importable ----
# When stt_wrapper.py runs as a Hermes-local_command subprocess the bundled
# Python's site-packages/ is NOT on sys.path automatically. Add it so the
# lazy zhconv import below succeeds.
# Two layouts: bundled (runtime/stt_wrapper.py -> runtime/site-packages)
# and dev (src/stt_wrapper.py -> dist/runtime/site-packages).
_runtime_site = Path(__file__).resolve().parent / "site-packages"
if not _runtime_site.is_dir():
    # Dev layout fallback
    _runtime_site = Path(__file__).resolve().parent.parent / "dist" / "runtime" / "site-packages"
if _runtime_site.is_dir() and str(_runtime_site) not in sys.path:
    sys.path.insert(0, str(_runtime_site))

# Lazy import zhconv for Traditional->Simplified Chinese conversion.
# zhconv has comprehensive coverage (~4000 character pairs). If missing
# (dev layout without rebuild), fall back gracefully.
_zhconv_convert = None
try:
    from zhconv import convert as _zhconv_convert  # type: ignore[import-untyped]
except ImportError:
    pass


def _runtime_dir() -> Path:
    """Folder that holds ``stt-bin/`` next to this script."""
    return Path(__file__).resolve().parent


def _resolve_stt_model_file() -> tuple[Path | None, Path]:
    """Return ``(existing_or_none, canonical_for_error)``."""

    rt = _runtime_dir()
    if _dvp is not None:
        found = _dvp.resolve_existing_stt_model(
            MODEL_FILENAME, no_env_fallback_dir=rt
        )
        canon = _dvp.canonical_stt_model_path(
            MODEL_FILENAME, no_env_fallback_dir=rt
        )
        return found, canon

    leg = _model_dir() / MODEL_FILENAME
    return (leg if leg.is_file() else None), leg


def _model_dir() -> Path:
    """Legacy resolver when ``desk_voice_paths`` is unavailable (dev smoke)."""

    data_dir = os.environ.get("HERMESDESK_DATA_DIR") or os.environ.get("LOCALAPPDATA")
    if not data_dir:
        return _runtime_dir() / "stt-models"
    base = Path(data_dir)
    if "LOCALAPPDATA" in os.environ and base == Path(os.environ["LOCALAPPDATA"]):
        base = base / "HermesDesk"
    return base / "stt-models"


def _quoted(s: str) -> str:
    """Helper for log output (Windows shell style)."""
    return f'"{s}"' if " " in s else s


def _maybe_convert_zh_tw_to_cn(out_prefix: Path) -> None:
    """Convert transcript.txt from Traditional to Simplified Chinese using zhconv."""
    if _zhconv_convert is None:
        return
    txt_path = Path(str(out_prefix) + ".txt")
    if not txt_path.is_file():
        return
    try:
        text = txt_path.read_text(encoding="utf-8")
        converted = _zhconv_convert(text, "zh-hans")
        if converted != text:
            txt_path.write_text(converted, encoding="utf-8")
    except Exception:
        pass  # Best-effort; don't fail transcription for post-processing.


def main() -> int:
    if len(sys.argv) < 5:
        print(
            "stt_wrapper: expected 4 args (input_path output_dir language model)",
            file=sys.stderr,
        )
        return 6

    input_path = sys.argv[1]
    output_dir = sys.argv[2]
    language = sys.argv[3] or "auto"
    # Hermes passes "{model}" which it normalises to a faster-whisper size like
    # "base"; we hard-pin the bundled GGML file (currently base-q5_1) and
    # ignore the requested size — the user can swap the .bin under stt-models/
    # to upgrade.
    _ = sys.argv[4]

    # Hermes shlex.quote()s every placeholder before substituting; on Windows
    # that produces 'C:\Foo\bar.wav' (single-quoted) which CMD doesn't strip.
    # Trim matching surrounding quotes here so the OS sees a real path.
    def _unquote(s: str) -> str:
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            return s[1:-1]
        return s

    input_path = _unquote(input_path)
    output_dir = _unquote(output_dir)
    language = _unquote(language)

    runtime = _runtime_dir()
    bin_dir = runtime / "stt-bin"
    ffmpeg = bin_dir / "ffmpeg.exe"
    whisper = bin_dir / "whisper-cli.exe"

    if not whisper.exists() or not ffmpeg.exists():
        print(
            f"stt_wrapper: bundled binaries missing under {bin_dir}",
            file=sys.stderr,
        )
        return 3

    model_path, canon = _resolve_stt_model_file()
    if model_path is None:
        print(f"STT_MODEL_MISSING: {canon}", file=sys.stderr)
        return 2

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: ffmpeg → 16 kHz mono PCM WAV. whisper.cpp's audio loader requires
    # 16 kHz; webm/ogg also require external decode.
    wav_path = out_dir / "input.wav"
    ffmpeg_cmd = [
        str(ffmpeg),
        "-y", "-loglevel", "error",
        "-i", input_path,
        "-ar", "16000", "-ac", "1",
        str(wav_path),
    ]
    try:
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or "").strip() or str(exc)
        print(f"stt_wrapper: ffmpeg failed: {msg}", file=sys.stderr)
        return 4

    # Step 2: whisper.cpp.
    # ``-of <prefix>`` writes <prefix>.txt; Hermes globs <output_dir>/*.txt
    # and reads the first match.
    # Use all available CPU threads (no cap — modern CPUs have 12-32 cores).
    # Add -bs 1 (greedy / beam-size 1) for ~2x faster decoding at minimal
    # accuracy cost for short voice messages.
    out_prefix = out_dir / "transcript"
    threads = os.cpu_count() or 4
    whisper_cmd = [
        str(whisper),
        "-m", str(model_path),
        "-f", str(wav_path),
        "-l", language if language else "auto",
        "-t", str(threads),
        "-bs", "1",
        "-fa",  # Flash Attention: ~30% faster on v1.8+ (CPU & GPU)
        "-otxt",
        "-of", str(out_prefix),
        "-nt",
    ]
    try:
        subprocess.run(whisper_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or "").strip() or str(exc)
        print(f"stt_wrapper: whisper-cli failed: {msg}", file=sys.stderr)
        return 5

    # Post-process: whisper.cpp "-l zh" tends to emit Traditional Chinese
    # characters. When the language is Chinese, convert the transcript to
    # Simplified Chinese so mainland users see 简体 instead of 繁體.
    # We also check when lang=auto because auto-detect may identify Chinese
    # but still output traditional characters.
    if language in ("zh", "zh-cn", "zh-sg", "zh-hans", "auto"):
        _maybe_convert_zh_tw_to_cn(out_prefix)

    # Best-effort cleanup of the resampled WAV; Hermes' temp dir is
    # cleaned anyway but we'd rather not double the disk peak.
    try:
        wav_path.unlink(missing_ok=True)
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    # Mirror the command on stderr so it shows up in agent.log when debugging.
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover - last-resort guard
        import traceback

        print(
            "stt_wrapper: unexpected exception:\n"
            + "".join(traceback.format_exception(exc)),
            file=sys.stderr,
        )
        sys.exit(7)
