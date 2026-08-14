"""Content hashing helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..converter import SUPPORTED_INPUT_FORMATS
from ..core.files import SelectionFilters, collect_supported_files


@dataclass
class HashItem:
    """One hashed file."""

    path: str
    algorithm: str
    digest: str = ""
    bytes: int = 0
    error: str = ""


@dataclass
class HashResult:
    """Batch hash summary."""

    items: list[HashItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(not item.error for item in self.items)


def hash_paths(
    input_paths: list[str],
    *,
    recursive: bool = False,
    algorithm: str = "sha256",
    media_only: bool = True,
    selection: SelectionFilters | None = None,
) -> HashResult:
    """Hash files under the given inputs."""
    algorithm_name = algorithm.lower()
    if algorithm_name not in hashlib.algorithms_available:
        raise ValueError("unsupported_hash_algorithm")

    if media_only:
        files = collect_supported_files(
            input_paths, SUPPORTED_INPUT_FORMATS, recursive=recursive, selection=selection
        )
    else:
        files = _collect_all_files(input_paths, recursive=recursive)
        if selection is not None and selection.active:
            files = [path for path in files if selection.accepts(Path(path))]

    result = HashResult()
    for path in files:
        item = HashItem(path=path, algorithm=algorithm_name)
        try:
            data_path = Path(path)
            item.bytes = data_path.stat().st_size
            item.digest = _hash_file(path, algorithm_name)
        except Exception as error:
            item.error = str(error)
        result.items.append(item)
    return result


def hash_payload(result: HashResult) -> list[dict[str, Any]]:
    """Serialize hash items."""
    return [
        {
            "path": item.path,
            "algorithm": item.algorithm,
            "digest": item.digest,
            "size_bytes": item.bytes,
            "error": item.error,
        }
        for item in result.items
    ]


def _hash_file(path: str, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_all_files(input_paths: list[str], *, recursive: bool) -> list[str]:
    files: list[str] = []
    for raw in input_paths:
        path = Path(raw)
        if path.is_file():
            files.append(str(path))
            continue
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            for child in sorted(iterator):
                if child.is_file():
                    files.append(str(child))
    return files
