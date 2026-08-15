"""Execute the staged FFmpeg pair and verify PixShift's codec floor."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

EXPECTED_VERSION = "n8.1.2"
REQUIRED_ENCODERS = (
    "libx264",
    "libx265",
    "libvpx-vp9",
    "libsvtav1",
    "aac",
    "libmp3lame",
    "libopus",
    "flac",
    "pcm_s16le",
)
REQUIRED_FILTERS = ("amix", "psnr", "ssim")


def _run(command: list[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-2000:]
        raise RuntimeError(f"runtime_command_failed:{Path(command[0]).name}:{detail}")
    return completed


def verify_runtime(runtime_root: Path) -> None:
    suffix = ".exe" if os.name == "nt" else ""
    ffmpeg = runtime_root / "bin" / f"ffmpeg{suffix}"
    ffprobe = runtime_root / "bin" / f"ffprobe{suffix}"
    if not ffmpeg.is_file() or not ffprobe.is_file():
        raise RuntimeError("runtime_pair_missing")

    ffmpeg_version = _run([str(ffmpeg), "-version"]).stdout.splitlines()[0]
    ffprobe_version = _run([str(ffprobe), "-version"]).stdout.splitlines()[0]
    if f"version {EXPECTED_VERSION}" not in ffmpeg_version:
        raise RuntimeError(f"unexpected_ffmpeg_version:{ffmpeg_version}")
    if f"version {EXPECTED_VERSION}" not in ffprobe_version:
        raise RuntimeError(f"unexpected_ffprobe_version:{ffprobe_version}")

    encoders = _run([str(ffmpeg), "-hide_banner", "-encoders"]).stdout
    for encoder in REQUIRED_ENCODERS:
        if encoder not in encoders:
            raise RuntimeError(f"required_encoder_missing:{encoder}")
    filters = _run([str(ffmpeg), "-hide_banner", "-filters"]).stdout
    for media_filter in REQUIRED_FILTERS:
        if media_filter not in filters:
            raise RuntimeError(f"required_filter_missing:{media_filter}")

    with tempfile.TemporaryDirectory(prefix="pixshift-runtime-smoke-") as raw:
        sample = Path(raw) / "sample.mp4"
        _run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=32x32:rate=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=8000",
                "-t",
                "0.2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-y",
                str(sample),
            ]
        )
        probe = _run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-show_streams",
                "-print_format",
                "json",
                str(sample),
            ]
        )
        streams = json.loads(probe.stdout).get("streams", [])
        if {item.get("codec_type") for item in streams} != {"audio", "video"}:
            raise RuntimeError("runtime_smoke_probe_failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "pixshift" / "_runtime",
    )
    args = parser.parse_args()
    verify_runtime(args.runtime_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
