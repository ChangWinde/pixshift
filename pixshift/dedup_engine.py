"""
PixShift Dedup Engine — 图片哈希去重

功能:
  - 感知哈希 (pHash) 检测相似图片
  - 平均哈希 (aHash) 快速粗筛
  - 差异哈希 (dHash) 辅助判断
  - 支持 --dry-run 预览 + --delete 删除重复
  - 相似度阈值可调
"""

import hashlib
import os
import shutil
import stat
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .converter import SUPPORTED_INPUT_FORMATS, _human_size
from .core.metadata import ensure_static_image

# ============================================================
#  数据结构
# ============================================================


@dataclass
class DuplicateGroup:
    """一组重复/相似图片"""

    hash_value: str = ""
    files: list[str] = field(default_factory=list)
    sizes: list[int] = field(default_factory=list)
    similarity: float = 1.0
    keep: str = ""  # 建议保留的文件
    duplicates: list[str] = field(default_factory=list)  # 建议删除的文件


@dataclass(frozen=True)
class DeleteCandidate:
    """A byte-identical duplicate that may be deleted after revalidation."""

    keep: str
    duplicate: str
    sha256: str
    size: int


@dataclass
class DedupResult:
    """去重分析结果"""

    total_files: int = 0
    total_size: int = 0
    duplicate_groups: int = 0
    duplicate_files: int = 0
    deletable_files: int = 0
    recoverable_size: int = 0
    recoverable_size_human: str = ""
    skipped_invalid: int = 0
    groups: list[DuplicateGroup] = field(default_factory=list)
    delete_candidates: list[DeleteCandidate] = field(default_factory=list)
    duration: float = 0.0
    error: str = ""


# ============================================================
#  感知哈希算法
# ============================================================


def _average_hash(img: Image.Image, hash_size: int = 8) -> int:
    """
    平均哈希 (aHash)

    将图片缩小到 hash_size x hash_size，转灰度，
    每个像素与均值比较，大于均值为 1，否则为 0。
    """
    img = img.convert("L").resize((hash_size, hash_size), Image.Resampling.LANCZOS)
    # Use tobytes() to avoid Pillow getdata() deprecation warnings.
    pixels = img.tobytes()
    avg = sum(pixels) / len(pixels)
    bits = 0
    for pixel in pixels:
        bits = (bits << 1) | (1 if pixel >= avg else 0)
    return bits


def _difference_hash(img: Image.Image, hash_size: int = 8) -> int:
    """
    差异哈希 (dHash)

    将图片缩小到 (hash_size+1) x hash_size，转灰度，
    比较相邻像素的亮度差异。
    """
    img = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = img.tobytes()
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            idx = row * (hash_size + 1) + col
            bits = (bits << 1) | (1 if pixels[idx] < pixels[idx + 1] else 0)
    return bits


def _perceptual_hash(img: Image.Image, hash_size: int = 8) -> int:
    """
    感知哈希 (pHash) — 简化版

    使用 DCT（离散余弦变换）的近似实现。
    将图片缩小到 32x32，转灰度，计算均值哈希的增强版。
    """
    # 缩小到较大尺寸以获取更多信息
    img = img.convert("L").resize((32, 32), Image.Resampling.LANCZOS)
    pixels = img.tobytes()

    # 计算 hash_size x hash_size 区域的均值
    block_size = 32 // hash_size
    blocks = []
    for by in range(hash_size):
        for bx in range(hash_size):
            total = 0
            count = 0
            for dy in range(block_size):
                for dx in range(block_size):
                    y = by * block_size + dy
                    x = bx * block_size + dx
                    total += pixels[y * 32 + x]
                    count += 1
            blocks.append(total / count)

    avg = sum(blocks) / len(blocks)
    bits = 0
    for val in blocks:
        bits = (bits << 1) | (1 if val >= avg else 0)
    return bits


def _hash_one_file(
    filepath: str, hash_func: Callable[[Image.Image, int], int], hash_size: int
) -> tuple[str, int | None, int | None]:
    """Return ``(path, size, perceptual_hash)`` for one file, worker-safe.

    ``size`` is None when the file cannot be stat-ed; ``hash`` is None when the
    bytes stat but cannot be decoded/hashed (animated or corrupt). JPEG decode
    is accelerated with ``draft`` (decode at ~1/8 scale), which the audit
    measured at ~9x faster with a max hash drift of 2 (well under threshold 5).
    """
    try:
        size = os.path.getsize(filepath)
    except OSError:
        return filepath, None, None
    try:
        with Image.open(filepath) as img:
            ensure_static_image(img)
            img.draft("L", (64, 64))
            h = hash_func(img, hash_size)
        return filepath, size, h
    except Exception:
        return filepath, size, None


def _hamming_distance(hash1: int, hash2: int) -> int:
    """计算两个哈希值的汉明距离"""
    return (hash1 ^ hash2).bit_count()


def _hash_to_hex(hash_val: int, hash_size: int = 8) -> str:
    """将哈希值转为十六进制字符串"""
    hex_len = (hash_size * hash_size) // 4
    return f"{hash_val:0{hex_len}x}"


# ============================================================
#  核心去重函数
# ============================================================


def find_duplicates(
    input_paths: list[str],
    recursive: bool = False,
    hash_method: str = "phash",
    threshold: int = 5,
    hash_size: int = 8,
) -> DedupResult:
    """
    扫描目录找出重复/相似图片

    Args:
        input_paths: 输入路径列表
        recursive: 是否递归子目录
        hash_method: 哈希方法 (phash/ahash/dhash)
        threshold: 相似度阈值（汉明距离，0=完全相同，越大越宽松）
        hash_size: 哈希大小
    """
    result = DedupResult()
    start_time = time.time()

    try:
        # 收集文件
        files = _collect_image_files(input_paths, recursive)
        result.total_files = len(files)

        if not files:
            result.duration = time.time() - start_time
            return result

        # 选择哈希函数
        hash_func = {
            "phash": _perceptual_hash,
            "ahash": _average_hash,
            "dhash": _difference_hash,
        }.get(hash_method, _perceptual_hash)

        # 计算静态图片的感知哈希。字节级重复检测仍覆盖所有可读取文件。
        # 解码+哈希占总耗时 ~96% 且逐文件独立，Pillow 解码/缩放在 C 层释放 GIL，
        # 故用线程池并行；ex.map 保序，聚合结果的确定性不变。
        file_hashes: list[tuple[str, int, int]] = []  # (path, hash, size)
        file_records: list[tuple[str, int]] = []

        workers = min(16, (os.cpu_count() or 4))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            computed = list(pool.map(lambda f: _hash_one_file(f, hash_func, hash_size), files))

        for filepath, size, h in computed:
            if size is None:
                result.skipped_invalid += 1
                continue
            file_records.append((filepath, size))
            result.total_size += size
            if h is None:
                result.skipped_invalid += 1
                continue
            file_hashes.append((filepath, h, size))

        # 聚类：找出相似的图片组
        groups = _cluster_by_hash(file_hashes, threshold)

        # 删除候选必须是字节级完全一致的文件，与感知相似分组解耦。
        result.delete_candidates = _find_exact_duplicates(file_records)
        result.deletable_files = len(result.delete_candidates)
        result.recoverable_size = sum(candidate.size for candidate in result.delete_candidates)

        # 过滤：只保留有重复的组
        for group_files in groups:
            if len(group_files) < 2:
                continue

            group = DuplicateGroup()
            group.files = [f[0] for f in group_files]
            group.sizes = [f[2] for f in group_files]
            group.hash_value = _hash_to_hex(group_files[0][1], hash_size)

            # 建议保留最大的文件（通常质量最好）
            max_idx = group.sizes.index(max(group.sizes))
            group.keep = group.files[max_idx]
            group.duplicates = [f for i, f in enumerate(group.files) if i != max_idx]

            result.groups.append(group)
            result.duplicate_files += len(group.duplicates)

        result.duplicate_groups = len(result.groups)
        result.recoverable_size_human = _human_size(result.recoverable_size)

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _cluster_by_hash(
    file_hashes: list[tuple[str, int, int]],
    threshold: int,
) -> list[list[tuple[str, int, int]]]:
    """将相似哈希的文件聚类"""
    if not file_hashes:
        return []

    if threshold < 0:
        raise ValueError("threshold must be non-negative")

    if threshold == 0:
        exact_hash_groups: dict[int, list[tuple[str, int, int]]] = defaultdict(list)
        for item in file_hashes:
            exact_hash_groups[item[1]].append(item)
        return list(exact_hash_groups.values())

    parents = list(range(len(file_hashes)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    bit_count = max(64, max(item[1].bit_length() for item in file_hashes))
    if threshold >= bit_count:
        return [file_hashes]

    # Split the hash into threshold + 1 disjoint segments. If two hashes differ
    # by at most threshold bits, at least one segment must match exactly. This
    # gives a complete candidate set without scanning every prior hash.
    segment_count = threshold + 1
    base_width, wider_segments = divmod(bit_count, segment_count)
    segments: list[tuple[int, int]] = []
    shift = 0
    for segment_index in range(segment_count):
        width = base_width + (1 if segment_index < wider_segments else 0)
        segments.append((shift, (1 << width) - 1))
        shift += width

    indexes: list[dict[int, list[int]]] = [defaultdict(list) for _ in segments]
    for index, (_, image_hash, _) in enumerate(file_hashes):
        candidates: set[int] = set()
        values: list[int] = []
        for segment_index, (segment_shift, mask) in enumerate(segments):
            value = (image_hash >> segment_shift) & mask
            values.append(value)
            candidates.update(indexes[segment_index].get(value, []))
        for match in candidates:
            if _hamming_distance(image_hash, file_hashes[match][1]) <= threshold:
                union(index, match)
        for segment_index, value in enumerate(values):
            indexes[segment_index][value].append(index)

    components: dict[int, list[tuple[str, int, int]]] = defaultdict(list)
    for index, item in enumerate(file_hashes):
        components[find(index)].append(item)
    return list(components.values())


def _find_exact_duplicates(
    file_records: list[tuple[str, int]],
) -> list[DeleteCandidate]:
    """Build safe delete candidates by hashing only equal-size files."""
    by_size: dict[int, list[str]] = defaultdict(list)
    for path, size in file_records:
        by_size[size].append(path)

    candidates: list[DeleteCandidate] = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_digest: dict[str, list[str]] = defaultdict(list)
        for path in paths:
            by_digest[_sha256_file(path)].append(path)
        for digest, identical_paths in by_digest.items():
            if len(identical_paths) < 2:
                continue
            ordered = sorted(identical_paths)
            keep = ordered[0]
            # Hardlinks to one inode are the same bytes on disk, not two
            # copies: unlinking a second name frees nothing, so counting it
            # as recoverable space would be a false promise.
            seen_inodes = {_file_identity(keep)}
            for duplicate in ordered[1:]:
                identity = _file_identity(duplicate)
                if identity is not None and identity in seen_inodes:
                    continue
                seen_inodes.add(identity)
                candidates.append(
                    DeleteCandidate(
                        keep=keep,
                        duplicate=duplicate,
                        sha256=digest,
                        size=size,
                    )
                )
    return candidates


def _file_identity(path: str) -> tuple[int, int] | None:
    """The (device, inode) pair that identifies one file on disk."""
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    return (info.st_dev, info.st_ino)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_destination(source: str, backup_dir: str) -> Path:
    """A collision-free path for ``source`` inside ``backup_dir``.

    Duplicates come from different directories and often share a basename, so
    the first collision gets a numeric suffix rather than overwriting the file
    that was just moved to safety.
    """
    origin = Path(source)
    target = Path(backup_dir) / origin.name
    index = 1
    while target.exists():
        target = Path(backup_dir) / f"{origin.stem}_{index}{origin.suffix}"
        index += 1
    return target


def delete_duplicates(
    candidates: list[DeleteCandidate],
    dry_run: bool = True,
    backup_dir: str | None = None,
) -> dict[str, list[str]]:
    """
    删除重复文件

    Args:
        candidates: 分析阶段生成的字节级相同候选
        dry_run: 仅预览不删除
        backup_dir: 给定时把重复文件移入该目录，而不是永久删除

    Returns:
        {"deleted": [...], "kept": [...], "skipped": [...], "errors": [...]}
    """
    result: dict[str, list[str]] = {
        "deleted": [],
        "kept": [],
        "skipped": [],
        "errors": [],
    }
    kept = set()

    if backup_dir and not dry_run:
        Path(backup_dir).mkdir(parents=True, exist_ok=True)

    for candidate in candidates:
        kept.add(candidate.keep)
        if dry_run:
            result["deleted"].append(f"[DRY-RUN] {candidate.duplicate}")
            continue
        try:
            identity = _candidate_is_still_safe(candidate)
            if identity is None:
                result["skipped"].append(
                    f"{candidate.duplicate}: file changed or is no longer byte-identical"
                )
                continue
            if not _still_the_same_object(candidate.duplicate, identity):
                result["skipped"].append(
                    f"{candidate.duplicate}: file was replaced after verification"
                )
                continue
            if backup_dir:
                destination = _backup_destination(candidate.duplicate, backup_dir)
                # move, not copy+unlink: the duplicate must never exist twice
                # nor vanish if the write fails halfway.
                shutil.move(candidate.duplicate, str(destination))
                result["deleted"].append(f"{candidate.duplicate} -> {destination}")
            else:
                os.remove(candidate.duplicate)
                result["deleted"].append(candidate.duplicate)
        except Exception as e:
            result["errors"].append(f"{candidate.duplicate}: {e}")

    result["kept"] = sorted(kept)

    return result


def _verified_identity(path: str, candidate: DeleteCandidate) -> tuple[int, int] | None:
    """Hash ``path`` through one open descriptor; return its (dev, inode).

    Hashing by name and then deleting by name leaves a window in which the
    name can be repointed at different bytes. Reading through a descriptor
    opened with ``O_NOFOLLOW`` pins the object being verified, and the
    returned identity lets the caller confirm the name still resolves to that
    same object at the moment of deletion.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size != candidate.size:
            return None
        digest = hashlib.sha256()
        with os.fdopen(os.dup(descriptor), "rb", closefd=True) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != candidate.sha256:
            return None
        return (file_stat.st_dev, file_stat.st_ino)
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _candidate_is_still_safe(candidate: DeleteCandidate) -> tuple[int, int] | None:
    """Revalidate both files; return the duplicate's identity when safe.

    Returns ``None`` when either file changed, so the caller skips it.
    """
    if _verified_identity(candidate.keep, candidate) is None:
        return None
    return _verified_identity(candidate.duplicate, candidate)


def _still_the_same_object(path: str, identity: tuple[int, int]) -> bool:
    """Whether ``path`` still names the object that was verified."""
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (current.st_dev, current.st_ino) == identity


def _collect_image_files(
    input_paths: list[str],
    recursive: bool,
) -> list[str]:
    """收集所有图片文件。

    符号链接一律跳过：``resolve()`` 会把链接换成它在扫描目录之外的目标，
    随后删除阶段就会删掉用户根本没有授权的文件。链接本身也不是重复文件，
    删它并不回收任何空间。
    """
    files = []
    for path_str in input_paths:
        path = Path(path_str)
        if path.is_symlink():
            continue
        if path.is_file():
            if path.suffix.lower() in SUPPORTED_INPUT_FORMATS:
                files.append(str(path.resolve()))
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for item in sorted(path.glob(pattern)):
                if item.is_symlink() or not item.is_file():
                    continue
                if item.suffix.lower() in SUPPORTED_INPUT_FORMATS:
                    files.append(str(item.resolve()))
    return sorted(set(files))
