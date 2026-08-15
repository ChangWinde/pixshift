"""Supply-chain and release-contract tests for bundled FFmpeg artifacts."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts" / "media_runtime_manifest.json"
_SPEC = importlib.util.spec_from_file_location(
    "pixshift_stage_media_runtime",
    ROOT / "scripts" / "stage_media_runtime.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_STAGING = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _STAGING
_SPEC.loader.exec_module(_STAGING)
EXPECTED_RUNTIME_VERSION = _STAGING.EXPECTED_RUNTIME_VERSION
Artifact = _STAGING.Artifact
RuntimeTarget = _STAGING.RuntimeTarget
download_verified_artifact = _STAGING.download_verified_artifact
load_manifest = _STAGING.load_manifest


def test_runtime_manifest_covers_every_release_wheel() -> None:
    manifest = load_manifest(MANIFEST)

    assert manifest.version == EXPECTED_RUNTIME_VERSION == "8.1.2"
    assert set(manifest.targets) == {
        "linux-aarch64",
        "linux-x86_64",
        "macos-arm64",
        "macos-x86_64",
        "windows-x86_64",
    }
    assert {target.wheel_tag for target in manifest.targets.values()} == {
        "manylinux_2_28_aarch64",
        "manylinux_2_28_x86_64",
        "macosx_15_0_arm64",
        "macosx_15_0_x86_64",
        "win_amd64",
    }

    for target in manifest.targets.values():
        assert {artifact.command for artifact in target.artifacts} == {"ffmpeg", "ffprobe"}
        for artifact in target.artifacts:
            assert artifact.url.startswith(
                "https://github.com/shaka-project/static-ffmpeg-binaries/releases/download/"
                "n8.1.2-1/"
            )
            assert len(artifact.sha256) == 64
            int(artifact.sha256, 16)
            assert 1_000_000 < artifact.size < 100_000_000


def test_verified_download_rejects_hash_mismatch_without_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"not-the-declared-runtime"
    artifact = Artifact(
        command="ffmpeg",
        url="https://github.com/shaka-project/static-ffmpeg-binaries/releases/download/"
        "n8.1.2-1/fake",
        size=len(payload),
        sha256="0" * 64,
    )
    target = RuntimeTarget(wheel_tag="manylinux_2_28_x86_64", artifacts=(artifact,))

    monkeypatch.setattr(
        _STAGING,
        "_open_url",
        lambda _url: _Response(payload),
    )

    destination = tmp_path / "ffmpeg"
    with pytest.raises(ValueError, match="sha256_mismatch"):
        download_verified_artifact(artifact, target, destination)
    assert not destination.exists()


def test_verified_download_rejects_truncation_without_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"short"
    artifact = Artifact(
        command="ffprobe",
        url="https://github.com/shaka-project/static-ffmpeg-binaries/releases/download/"
        "n8.1.2-1/fake",
        size=len(payload) + 1,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    target = RuntimeTarget(wheel_tag="manylinux_2_28_x86_64", artifacts=(artifact,))
    monkeypatch.setattr(
        _STAGING,
        "_open_url",
        lambda _url: _Response(payload),
    )

    destination = tmp_path / "ffprobe"
    with pytest.raises(ValueError, match="size_mismatch"):
        download_verified_artifact(artifact, target, destination)
    assert not destination.exists()


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_release_workflow_stages_and_smoke_tests_platform_wheels() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "scripts/stage_media_runtime.py" in workflow
    assert "scripts/verify_media_runtime.py" in workflow
    assert "wheel tags" in workflow
    for platform_key in load_manifest(MANIFEST).targets:
        assert platform_key in workflow


def test_runtime_notice_records_provenance_and_license() -> None:
    notice = (ROOT / "pixshift" / "_runtime" / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "FFmpeg 8.1.2" in notice
    assert "n8.1.2-1" in notice
    assert "88caac417541f3bb678fa6670cb73f2d74c7aaf9" in notice
    assert "GPL-3.0" in notice
    assert "media_runtime_manifest.json" in notice

    source_manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "scripts/media_runtime_manifest.json" in source_manifest
    assert "scripts/stage_media_runtime.py" in source_manifest
    assert "scripts/verify_media_runtime.py" in source_manifest
