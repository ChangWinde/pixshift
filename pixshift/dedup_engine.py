"""
PixShift Dedup Engine — 图片哈希去重

功能:
  - 感知哈希 (pHash) 检测相似图片
  - 平均哈希 (aHash) 快速粗筛
  - 差异哈希 (dHash) 辅助判断
  - 支持 --dry-run 预览 + --delete 删除重复
  - 相似度阈值可调
"""

import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict

from PIL import Image

from .converter import SUPPORTED_INPUT_FORMATS, _human_size


# ============================================================
#  数据结构
# ============================================================

@dataclass
class DuplicateGroup:
    """一组重复/相似图片"""
    hash_value: str = ""
    files: List[str] = field(default_factory=list)
    sizes: List[int] = field(default_factory=list)
    similarity: float = 1.0
    keep: str = ""  # 建议保留的文件
    duplicates: List[str] = field(default_factory=list)  # 建议删除的文件


@dataclass
class DedupResult:
    """去重分析结果"""
    total_files: int = 0
    total_size: int = 0
    duplicate_groups: int = 0
    duplicate_files: int = 0
    recoverable_size: int = 0
    recoverable_size_human: str = ""
    groups: List[DuplicateGroup] = field(default_factory=list)
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
    img = img.convert("L").resize((hash_size, hash_size), Image.LANCZOS)
    # Use tobytes() to avoid Pillow getdata() deprecation warnings.
    pixels = list(img.tobytes())
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
    img = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(img.tobytes())
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
    img = img.convert("L").resize((32, 32), Image.LANCZOS)
    pixels = list(img.tobytes())

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


def _hamming_distance(hash1: int, hash2: int) -> int:
    """计算两个哈希值的汉明距离"""
    xor = hash1 ^ hash2
    distance = 0
    while xor:
        distance += xor & 1
        xor >>= 1
    return distance


def _hash_to_hex(hash_val: int, hash_size: int = 8) -> str:
    """将哈希值转为十六进制字符串"""
    hex_len = (hash_size * hash_size) // 4
    return f"{hash_val:0{hex_len}x}"


# ============================================================
#  核心去重函数
# ============================================================

def find_duplicates(
    input_paths: List[str],
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
            result.error = "未找到图片文件"
            return result

        # 选择哈希函数
        hash_func = {
            "phash": _perceptual_hash,
            "ahash": _average_hash,
            "dhash": _difference_hash,
        }.get(hash_method, _perceptual_hash)

        # 计算所有图片的哈希
        file_hashes: List[Tuple[str, int, int]] = []  # (path, hash, size)

        for filepath in files:
            try:
                img = Image.open(filepath)
                h = hash_func(img, hash_size)
                size = os.path.getsize(filepath)
                file_hashes.append((filepath, h, size))
                result.total_size += size
            except Exception:
                continue

        # 聚类：找出相似的图片组
        groups = _cluster_by_hash(file_hashes, threshold)

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

            # 可回收空间
            recoverable = sum(s for i, s in enumerate(group.sizes) if i != max_idx)
            result.recoverable_size += recoverable

            result.groups.append(group)
            result.duplicate_files += len(group.duplicates)

        result.duplicate_groups = len(result.groups)
        result.recoverable_size_human = _human_size(result.recoverable_size)

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _cluster_by_hash(
    file_hashes: List[Tuple[str, int, int]],
    threshold: int,
) -> List[List[Tuple[str, int, int]]]:
    """将相似哈希的文件聚类"""
    if not file_hashes:
        return []

    used = set()
    groups = []

    for i, (path_i, hash_i, size_i) in enumerate(file_hashes):
        if i in used:
            continue

        group = [(path_i, hash_i, size_i)]
        used.add(i)

        for j, (path_j, hash_j, size_j) in enumerate(file_hashes):
            if j in used:
                continue
            if _hamming_distance(hash_i, hash_j) <= threshold:
                group.append((path_j, hash_j, size_j))
                used.add(j)

        groups.append(group)

    return groups


def delete_duplicates(
    groups: List[DuplicateGroup],
    dry_run: bool = True,
) -> Dict[str, List[str]]:
    """
    删除重复文件

    Args:
        groups: 重复组列表
        dry_run: 仅预览不删除

    Returns:
        {"deleted": [...], "kept": [...], "errors": [...]}
    """
    result = {"deleted": [], "kept": [], "errors": []}

    for group in groups:
        result["kept"].append(group.keep)

        for dup_path in group.duplicates:
            if dry_run:
                result["deleted"].append(f"[DRY-RUN] {dup_path}")
            else:
                try:
                    os.remove(dup_path)
                    result["deleted"].append(dup_path)
                except Exception as e:
                    result["errors"].append(f"{dup_path}: {e}")

    return result


def _collect_image_files(
    input_paths: List[str],
    recursive: bool,
) -> List[str]:
    """收集所有图片文件"""
    files = []
    for path_str in input_paths:
        path = Path(path_str)
        if path.is_file():
            if path.suffix.lower() in SUPPORTED_INPUT_FORMATS:
                files.append(str(path.resolve()))
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for item in sorted(path.glob(pattern)):
                if item.is_file() and item.suffix.lower() in SUPPORTED_INPUT_FORMATS:
                    files.append(str(item.resolve()))
    return sorted(set(files))
