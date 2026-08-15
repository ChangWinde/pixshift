"""Stage a pinned FFmpeg pair for one PixShift platform wheel.

This script is release tooling, never a runtime fallback. It accepts only the
immutable URLs and digests declared in ``media_runtime_manifest.json`` and
publishes no file until its exact byte length and SHA-256 have both matched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

EXPECTED_RUNTIME_VERSION = "8.1.2"
MAX_ARTIFACT_BYTES = 100_000_000
TRUSTED_RELEASE_PREFIX = (
    "https://github.com/shaka-project/static-ffmpeg-binaries/releases/download/n8.1.2-1/"
)
TRUSTED_LICENSE_URL = "https://raw.githubusercontent.com/FFmpeg/FFmpeg/n8.1.2/COPYING.GPLv3"
CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Artifact:
    """One immutable release artifact."""

    command: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class RuntimeTarget:
    """Artifacts and wheel tag for one OS/CPU pair."""

    wheel_tag: str
    artifacts: tuple[Artifact, ...]


@dataclass(frozen=True)
class RuntimeManifest:
    """Validated release inputs for all supported platform wheels."""

    version: str
    repository: str
    release_tag: str
    commit: str
    license: Artifact
    targets: dict[str, RuntimeTarget]


def _parse_artifact(raw: object, *, allowed_commands: set[str]) -> Artifact:
    if not isinstance(raw, dict):
        raise ValueError("invalid_artifact")
    try:
        artifact = Artifact(
            command=str(raw["command"]),
            url=str(raw["url"]),
            size=int(raw["size"]),
            sha256=str(raw["sha256"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid_artifact") from exc
    if artifact.command not in allowed_commands:
        raise ValueError(f"invalid_artifact_command:{artifact.command}")
    if not 0 < artifact.size <= MAX_ARTIFACT_BYTES:
        raise ValueError(f"invalid_artifact_size:{artifact.command}")
    if len(artifact.sha256) != 64:
        raise ValueError(f"invalid_artifact_sha256:{artifact.command}")
    try:
        int(artifact.sha256, 16)
    except ValueError as exc:
        raise ValueError(f"invalid_artifact_sha256:{artifact.command}") from exc
    return artifact


def load_manifest(path: Path) -> RuntimeManifest:
    """Read and strictly validate the committed runtime manifest."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_runtime_manifest") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("unsupported_runtime_manifest")
    if raw.get("version") != EXPECTED_RUNTIME_VERSION:
        raise ValueError("unexpected_runtime_version")

    source = raw.get("source")
    targets_raw = raw.get("targets")
    if not isinstance(source, dict) or not isinstance(targets_raw, dict) or not targets_raw:
        raise ValueError("invalid_runtime_manifest")
    repository = str(source.get("repository", ""))
    release_tag = str(source.get("release_tag", ""))
    commit = str(source.get("commit", ""))
    if repository != "https://github.com/shaka-project/static-ffmpeg-binaries":
        raise ValueError("untrusted_runtime_repository")
    if release_tag != f"n{EXPECTED_RUNTIME_VERSION}-1" or len(commit) != 40:
        raise ValueError("untrusted_runtime_source")
    try:
        int(commit, 16)
    except ValueError as exc:
        raise ValueError("untrusted_runtime_source") from exc

    license_artifact = _parse_artifact(raw.get("license"), allowed_commands={"license"})
    if license_artifact.url != TRUSTED_LICENSE_URL:
        raise ValueError("untrusted_runtime_license")

    targets: dict[str, RuntimeTarget] = {}
    wheel_tags: set[str] = set()
    for platform_key, target_raw in targets_raw.items():
        if not isinstance(platform_key, str) or not isinstance(target_raw, dict):
            raise ValueError("invalid_runtime_target")
        wheel_tag = str(target_raw.get("wheel_tag", ""))
        artifacts_raw = target_raw.get("artifacts")
        if not wheel_tag or wheel_tag in wheel_tags or not isinstance(artifacts_raw, list):
            raise ValueError(f"invalid_runtime_target:{platform_key}")
        artifacts = tuple(
            _parse_artifact(item, allowed_commands={"ffmpeg", "ffprobe"}) for item in artifacts_raw
        )
        if len(artifacts) != 2 or {item.command for item in artifacts} != {
            "ffmpeg",
            "ffprobe",
        }:
            raise ValueError(f"incomplete_runtime_target:{platform_key}")
        if any(not item.url.startswith(TRUSTED_RELEASE_PREFIX) for item in artifacts):
            raise ValueError(f"untrusted_runtime_url:{platform_key}")
        wheel_tags.add(wheel_tag)
        targets[platform_key] = RuntimeTarget(wheel_tag=wheel_tag, artifacts=artifacts)

    return RuntimeManifest(
        version=EXPECTED_RUNTIME_VERSION,
        repository=repository,
        release_tag=release_tag,
        commit=commit,
        license=license_artifact,
        targets=targets,
    )


def _open_url(url: str) -> BinaryIO:
    request = urllib.request.Request(url, headers={"User-Agent": "PixShift-release-builder"})
    # Manifest validation constrains every URL to an immutable HTTPS allowlist.
    return urllib.request.urlopen(request, timeout=30)


def download_verified_artifact(
    artifact: Artifact,
    target: RuntimeTarget,
    destination: Path,
) -> None:
    """Download, authenticate, and atomically publish one build artifact."""
    if artifact not in target.artifacts and artifact.command != "license":
        raise ValueError(f"artifact_not_in_target:{artifact.command}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    with tempfile.TemporaryDirectory(prefix=".pixshift-runtime-", dir=destination.parent) as raw:
        temporary = Path(raw) / destination.name
        with _open_url(artifact.url) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > artifact.size or total > MAX_ARTIFACT_BYTES:
                    raise ValueError(f"size_mismatch:{artifact.command}")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if total != artifact.size:
            raise ValueError(f"size_mismatch:{artifact.command}")
        if digest.hexdigest() != artifact.sha256:
            raise ValueError(f"sha256_mismatch:{artifact.command}")
        if artifact.command != "license":
            temporary.chmod(0o755)
        os.replace(temporary, destination)


def stage_runtime(manifest: RuntimeManifest, platform_key: str, destination: Path) -> None:
    """Stage the complete pair, license, and machine-readable provenance."""
    try:
        target = manifest.targets[platform_key]
    except KeyError as exc:
        raise ValueError(f"unsupported_runtime_target:{platform_key}") from exc

    suffix = ".exe" if target.wheel_tag.startswith("win_") else ""
    for artifact in target.artifacts:
        download_verified_artifact(
            artifact,
            target,
            destination / "bin" / f"{artifact.command}{suffix}",
        )
    download_verified_artifact(manifest.license, target, destination / "COPYING.GPLv3")

    provenance = {
        "schema_version": 1,
        "version": manifest.version,
        "platform": platform_key,
        "wheel_tag": target.wheel_tag,
        "source": {
            "repository": manifest.repository,
            "release_tag": manifest.release_tag,
            "commit": manifest.commit,
        },
        "artifacts": [
            {
                "command": item.command,
                "url": item.url,
                "size": item.size,
                "sha256": item.sha256,
            }
            for item in target.artifacts
        ],
    }
    destination.mkdir(parents=True, exist_ok=True)
    provenance_path = destination / "provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, dest="platform_key")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("media_runtime_manifest.json"),
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "pixshift" / "_runtime",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest = load_manifest(args.manifest)
    stage_runtime(manifest, args.platform_key, args.destination)
    print(manifest.targets[args.platform_key].wheel_tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
