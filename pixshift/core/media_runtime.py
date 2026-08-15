"""Resolve external media executables without network access or PATH mutation.

PixShift prefers an administrator-managed ffmpeg/ffprobe pair on ``PATH`` and
falls back to the platform wheel installed with PixShift. Providers return a
complete pair or no result: mixing binaries from different distributions can
produce subtly incompatible probe/encode behavior and is therefore forbidden.

The bundled provider reads package data staged into PixShift's platform wheel.
Resolution is side-effect free and media commands can never trigger a downloader.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

FFMPEG_INSTALL_HINT = (
    "视频运行时不可用。请重装支持平台的 PixShift wheel，或安装 ffmpeg 与 ffprobe。"
)
BUNDLED_RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "_runtime"


@dataclass(frozen=True)
class FFmpegRuntime:
    """One compatible ffmpeg/ffprobe pair and its provenance."""

    ffmpeg: str
    ffprobe: str
    source: Literal["system", "bundled"]


class FFmpegProvider(Protocol):
    """Environment boundary for locating a complete local video runtime."""

    def resolve(self) -> FFmpegRuntime | None:
        """Return a complete executable pair, or ``None`` when unavailable."""


class SystemFFmpegProvider:
    """Resolve a pair managed by the host and exposed through ``PATH``."""

    def resolve(self) -> FFmpegRuntime | None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            return None
        return FFmpegRuntime(ffmpeg=ffmpeg, ffprobe=ffprobe, source="system")


class BundledFFmpegProvider:
    """Resolve executables already installed by the platform dependency wheel."""

    def __init__(self, runtime_root: Path | None = None) -> None:
        self.runtime_root = runtime_root or BUNDLED_RUNTIME_ROOT

    def resolve(self) -> FFmpegRuntime | None:
        suffix = ".exe" if os.name == "nt" else ""
        bin_dir = self.runtime_root / "bin"
        ffmpeg = bin_dir / f"ffmpeg{suffix}"
        ffprobe = bin_dir / f"ffprobe{suffix}"
        if not _is_usable_executable(ffmpeg) or not _is_usable_executable(ffprobe):
            return None
        return FFmpegRuntime(str(ffmpeg.resolve()), str(ffprobe.resolve()), "bundled")


def _is_usable_executable(path: Path) -> bool:
    """Reject links/non-files and enforce Unix execute bits."""
    return (
        not path.is_symlink() and path.is_file() and (os.name == "nt" or os.access(path, os.X_OK))
    )


_PROVIDER_FACTORIES: tuple[type[FFmpegProvider], ...] = (
    SystemFFmpegProvider,
    BundledFFmpegProvider,
)


def default_ffmpeg_providers() -> tuple[FFmpegProvider, ...]:
    """Build providers in deterministic precedence order."""
    return tuple(factory() for factory in _PROVIDER_FACTORIES)


def resolve_ffmpeg_runtime(
    providers: Iterable[FFmpegProvider] | None = None,
) -> FFmpegRuntime | None:
    """Return the first complete local runtime without downloading anything."""
    candidates = providers if providers is not None else default_ffmpeg_providers()
    for provider in candidates:
        runtime = provider.resolve()
        if runtime is not None:
            return runtime
    return None
