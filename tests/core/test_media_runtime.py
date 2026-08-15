"""Runtime-provider contract for install-complete media dependencies."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from pixshift.cli import cli
from pixshift.core.media_runtime import (
    BundledFFmpegProvider,
    FFmpegRuntime,
    SystemFFmpegProvider,
    resolve_ffmpeg_runtime,
)


class _Provider:
    def __init__(self, runtime: FFmpegRuntime | None) -> None:
        self.runtime = runtime
        self.calls = 0

    def resolve(self) -> FFmpegRuntime | None:
        self.calls += 1
        return self.runtime


def _make_executable(path: Path) -> None:
    path.write_bytes(b"runtime")
    path.chmod(0o755)


def test_resolver_uses_the_first_complete_provider() -> None:
    system = FFmpegRuntime("system-ffmpeg", "system-ffprobe", "system")
    bundled = FFmpegRuntime("bundled-ffmpeg", "bundled-ffprobe", "bundled")
    first = _Provider(system)
    second = _Provider(bundled)

    assert resolve_ffmpeg_runtime((first, second)) == system
    assert first.calls == 1
    assert second.calls == 0


def test_system_provider_requires_ffmpeg_and_ffprobe(monkeypatch: pytest.MonkeyPatch) -> None:
    found = {"ffmpeg": "/tools/ffmpeg", "ffprobe": None}
    monkeypatch.setattr("pixshift.core.media_runtime.shutil.which", found.get)

    assert SystemFFmpegProvider().resolve() is None


def test_bundled_provider_resolves_a_complete_packaged_pair(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    _make_executable(bin_dir / f"ffmpeg{suffix}")
    _make_executable(bin_dir / f"ffprobe{suffix}")

    runtime = BundledFFmpegProvider(runtime_root=tmp_path).resolve()

    assert runtime is not None
    assert runtime.source == "bundled"
    assert Path(runtime.ffmpeg) == (bin_dir / f"ffmpeg{suffix}").resolve()
    assert Path(runtime.ffprobe) == (bin_dir / f"ffprobe{suffix}").resolve()


def test_bundled_provider_rejects_a_partial_pair(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    _make_executable(bin_dir / f"ffmpeg{suffix}")

    assert BundledFFmpegProvider(runtime_root=tmp_path).resolve() is None


@pytest.mark.skipif(os.name == "nt", reason="unprivileged Windows symlinks are not portable")
def test_bundled_provider_rejects_symlinked_executables(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    _make_executable(outside / "ffmpeg")
    _make_executable(outside / "ffprobe")
    bin_dir = tmp_path / "runtime" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "ffmpeg").symlink_to(outside / "ffmpeg")
    (bin_dir / "ffprobe").symlink_to(outside / "ffprobe")

    assert BundledFFmpegProvider(runtime_root=tmp_path / "runtime").resolve() is None


def test_doctor_uses_packaged_runtime_when_path_has_no_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = FFmpegRuntime("/bundle/ffmpeg", "/bundle/ffprobe", "bundled")
    monkeypatch.setattr("pixshift.commands.system_commands.resolve_ffmpeg_runtime", lambda: runtime)
    monkeypatch.setattr("pixshift.commands.system_commands._ffmpeg_version", lambda _path: "8.1.2")

    result = CliRunner().invoke(cli, ["doctor", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    check = next(item for item in payload["checks"] if item["name"].startswith("ffmpeg"))
    assert check["ok"] is True
    assert check["required"] is True
    assert "随包安装" in check["status"]
