"""
PixShift Strip Engine — 隐私清洗 / 元数据批量清除

功能:
  - 一键批量清除 EXIF（GPS 位置、设备信息等）
  - 可选保留 ICC 色彩配置
  - 可选保留方向信息
  - 社交媒体发图前的隐私保护
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

from .core.files import SelectionFilters, atomic_output_path, collect_supported_files
from .core.metadata import ensure_static_image, normalize_orientation

# ============================================================
#  数据结构
# ============================================================


@dataclass
class StripResult:
    """单个文件的元数据清除结果"""

    input_path: str = ""
    output_path: str = ""
    success: bool = False
    input_size: int = 0
    output_size: int = 0
    duration: float = 0.0
    error: str = ""
    exif_removed: bool = False
    gps_removed: bool = False
    icc_removed: bool = False
    fields_removed: int = 0


@dataclass
class StripBatchResult:
    """批量清除汇总"""

    total: int = 0
    success: int = 0
    failed: int = 0
    total_input_size: int = 0
    total_output_size: int = 0
    total_duration: float = 0.0
    total_fields_removed: int = 0
    results: list[StripResult] = field(default_factory=list)


# ============================================================
#  敏感 EXIF 标签
# ============================================================

# GPS 相关标签
GPS_TAGS = {
    "GPSInfo",
    "GPSVersionID",
    "GPSLatitudeRef",
    "GPSLatitude",
    "GPSLongitudeRef",
    "GPSLongitude",
    "GPSAltitudeRef",
    "GPSAltitude",
    "GPSTimeStamp",
    "GPSSatellites",
    "GPSStatus",
    "GPSMeasureMode",
    "GPSDOP",
    "GPSSpeedRef",
    "GPSSpeed",
    "GPSTrackRef",
    "GPSTrack",
    "GPSImgDirectionRef",
    "GPSImgDirection",
    "GPSMapDatum",
    "GPSDestLatitudeRef",
    "GPSDestLatitude",
    "GPSDestLongitudeRef",
    "GPSDestLongitude",
    "GPSDestBearingRef",
    "GPSDestBearing",
    "GPSDestDistanceRef",
    "GPSDestDistance",
    "GPSProcessingMethod",
    "GPSAreaInformation",
    "GPSDateStamp",
    "GPSDifferential",
}

# 设备信息标签
DEVICE_TAGS = {
    "Make",
    "Model",
    "Software",
    "HostComputer",
    "CameraOwnerName",
    "BodySerialNumber",
    "LensSerialNumber",
    "LensMake",
    "LensModel",
    "LensSpecification",
    # MakerNote 常含厂商序列号/固件，部分机型还嵌 GPS；ImageUniqueID 可追踪单张照片。
    "MakerNote",
    "ImageUniqueID",
}

# 个人信息标签
PERSONAL_TAGS = {
    "Artist",
    "Copyright",
    "ImageDescription",
    "UserComment",
    "XPAuthor",
    "XPComment",
    "XPKeywords",
    "XPSubject",
    "XPTitle",
}

# 时间信息标签
TIME_TAGS = {
    "DateTime",
    "DateTimeOriginal",
    "DateTimeDigitized",
    "SubSecTime",
    "SubSecTimeOriginal",
    "SubSecTimeDigitized",
    "OffsetTime",
    "OffsetTimeOriginal",
    "OffsetTimeDigitized",
}

# 所有敏感标签
ALL_SENSITIVE_TAGS = GPS_TAGS | DEVICE_TAGS | PERSONAL_TAGS | TIME_TAGS
EXIF_IFD_TAG = 34665


# ============================================================
#  核心函数
# ============================================================


def strip_metadata(
    input_path: str,
    output_path: str,
    strip_exif: bool = True,
    strip_gps: bool = True,
    strip_icc: bool = False,
    strip_device: bool = True,
    strip_personal: bool = True,
    strip_time: bool = False,
    keep_orientation: bool = True,
    overwrite: bool = False,
) -> StripResult:
    """
    清除图片元数据

    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        strip_exif: 清除所有 EXIF（最彻底）
        strip_gps: 清除 GPS 位置信息
        strip_icc: 清除 ICC 色彩配置
        strip_device: 清除设备信息
        strip_personal: 清除个人信息
        strip_time: 清除时间信息
        keep_orientation: 保留方向信息（先应用旋转）
        overwrite: 是否覆盖
    """
    result = StripResult(input_path=input_path, output_path=output_path)
    start_time = time.time()

    try:
        if not os.path.exists(input_path):
            result.error = f"文件不存在: {input_path}"
            return result

        result.input_size = os.path.getsize(input_path)

        if os.path.exists(output_path) and not overwrite:
            result.error = "输出文件已存在（使用 --overwrite 覆盖）"
            return result

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with Image.open(input_path) as opened:
            ensure_static_image(opened)
            img = opened.copy()
            img.info.update(opened.info)

        # 统计原始 EXIF 字段数
        original_fields = 0
        try:
            exif = img.getexif()
            original_fields = len(_iter_exif_entries(exif))
        except Exception:
            pass

        # 如果需要保留方向，先应用旋转
        if keep_orientation:
            img = _apply_orientation(img)

        if strip_exif:
            # 完全清除所有 EXIF
            _save_clean(img, output_path, input_path, strip_icc=strip_icc)
            result.exif_removed = True
            result.fields_removed = original_fields
        else:
            # 选择性清除
            fields_removed = _selective_strip(
                img,
                output_path,
                input_path,
                strip_gps=strip_gps,
                strip_device=strip_device,
                strip_personal=strip_personal,
                strip_time=strip_time,
                strip_icc=strip_icc,
            )
            result.fields_removed = fields_removed
            result.gps_removed = strip_gps

        result.output_size = os.path.getsize(output_path)
        result.success = True

    except Exception as e:
        result.error = str(e)

    result.duration = time.time() - start_time
    return result


def _apply_orientation(img: Image.Image) -> Image.Image:
    """应用 EXIF 方向信息，并移除已消费的方向标签。"""
    return normalize_orientation(img)


# 编码器会从 img.info 回捞的元数据通道；隐私清洗必须显式删除它们，
# 只是"不传对应 kwarg"并不能阻止 Pillow 把它们写回（HEIC 的 EXIF/XMP、
# PNG 的 ICC、JPEG 的注释此前都因此泄漏）。
_AUTO_METADATA_KEYS = ("exif", "xmp", "comment", "photoshop", "iptc")

# 各扩展名的干净编码参数（不含任何元数据）。
_STRIP_SAVE_KWARGS: dict[str, dict[str, Any]] = {
    ".jpg": {"format": "JPEG", "quality": 95, "optimize": True},
    ".jpeg": {"format": "JPEG", "quality": 95, "optimize": True},
    ".png": {"format": "PNG", "optimize": True},
    ".webp": {"format": "WEBP", "quality": 95},
    ".tiff": {"format": "TIFF", "compression": "tiff_lzw"},
    ".tif": {"format": "TIFF", "compression": "tiff_lzw"},
    ".heic": {"format": "HEIF"},
    ".heif": {"format": "HEIF"},
    ".avif": {"format": "AVIF"},
}


def _save_clean(
    img: Image.Image,
    output_path: str,
    input_path: str,
    *,
    strip_icc: bool,
    exif_bytes: bytes | None = None,
) -> None:
    """清除所有会被编码器回捞的元数据通道后原子保存。

    ``exif_bytes`` 为 None 表示完全清除 EXIF；非 None 表示选择性清除后重建的
    EXIF（经 kwarg 显式写回）。XMP/IPTC/Photoshop 这些非 EXIF 通道同样可能携带
    GPS/作者信息，且无法逐字段编辑，隐私清洗一律整体删除。
    """
    ext = Path(input_path).suffix.lower()
    save = img
    if ext in (".jpg", ".jpeg") and save.mode in ("RGBA", "LA", "PA", "P"):
        save = save.convert("RGB")

    icc = None if strip_icc else save.info.get("icc_profile")
    for key in _AUTO_METADATA_KEYS:
        save.info.pop(key, None)
    save.info.pop("icc_profile", None)
    # exif_transpose()/getexif() cache the EXIF block on the image object, and
    # encoders such as HEIF read that cache rather than info["exif"]. Clearing
    # info alone let HEIC keep its GPS/device tags; empty the cache too. When a
    # rebuilt EXIF is supplied it is written explicitly via the kwarg below.
    save.getexif().clear()

    kwargs = _STRIP_SAVE_KWARGS.get(ext)
    if kwargs is None:
        fmt = img.format
        kwargs = {"format": fmt} if fmt else {}
    else:
        kwargs = dict(kwargs)
    if exif_bytes:
        kwargs["exif"] = exif_bytes
    if icc:
        kwargs["icc_profile"] = icc

    with atomic_output_path(output_path) as temporary:
        save.save(temporary, **kwargs)


def _selective_strip(
    img: Image.Image,
    output_path: str,
    input_path: str,
    strip_gps: bool,
    strip_device: bool,
    strip_personal: bool,
    strip_time: bool,
    strip_icc: bool,
) -> int:
    """选择性清除指定类别的 EXIF 标签"""
    fields_removed = 0

    try:
        exif = img.getexif()
        if not exif:
            _save_clean(img, output_path, input_path, strip_icc=strip_icc)
            return 0

        # 构建要删除的标签集合
        tags_to_remove: set[str] = set()
        if strip_gps:
            tags_to_remove |= GPS_TAGS
        if strip_device:
            tags_to_remove |= DEVICE_TAGS
        if strip_personal:
            tags_to_remove |= PERSONAL_TAGS
        if strip_time:
            tags_to_remove |= TIME_TAGS

        fields_removed += _remove_named_tags(exif, tags_to_remove)

        nested_exif = _get_nested_exif(exif)
        fields_removed += _remove_named_tags(nested_exif, tags_to_remove)
        if EXIF_IFD_TAG in exif and not nested_exif:
            del exif[EXIF_IFD_TAG]

        # 特殊处理 GPS IFD
        if strip_gps:
            gps_ifd_key = next(
                (key for key, name in ExifTags.TAGS.items() if name == "GPSInfo"),
                None,
            )
            if gps_ifd_key is not None and gps_ifd_key in exif:
                del exif[gps_ifd_key]
                fields_removed += 1

        # 保存（重建后的 EXIF 经 kwarg 显式写回）
        exif_bytes = exif.tobytes() if exif else None
        _save_clean(img, output_path, input_path, strip_icc=strip_icc, exif_bytes=exif_bytes)

    except Exception:
        # 如果选择性清除失败，回退到完全清除
        _save_clean(img, output_path, input_path, strip_icc=strip_icc)
        fields_removed = -1  # 标记为完全清除

    return fields_removed


def _get_nested_exif(exif: Any) -> dict[int, Any]:
    """Return the mutable Exif IFD mapping when it is present."""
    if EXIF_IFD_TAG not in exif:
        return {}
    try:
        return exif.get_ifd(EXIF_IFD_TAG)
    except (KeyError, TypeError, ValueError):
        return {}


def _iter_exif_entries(exif: Any) -> list[tuple[int, Any]]:
    """Return logical EXIF fields, including fields stored in the nested Exif IFD."""
    entries = [(key, value) for key, value in exif.items() if key != EXIF_IFD_TAG]
    entries.extend(_get_nested_exif(exif).items())
    return entries


def _remove_named_tags(exif_fields: Any, tags_to_remove: set[str]) -> int:
    """Remove matching EXIF fields from one mutable IFD mapping."""
    keys = [key for key in exif_fields if ExifTags.TAGS.get(key, "") in tags_to_remove]
    for key in keys:
        del exif_fields[key]
    return len(keys)


def analyze_metadata(filepath: str) -> dict[str, Any]:
    """
    分析图片的元数据内容（用于预览）

    返回各类别的元数据统计
    """
    info: dict[str, Any] = {
        "path": filepath,
        "has_exif": False,
        "has_gps": False,
        "has_device": False,
        "has_personal": False,
        "has_time": False,
        "has_icc": False,
        "gps_fields": [],
        "device_fields": [],
        "personal_fields": [],
        "time_fields": [],
        "other_fields": [],
        "total_fields": 0,
    }

    try:
        with Image.open(filepath) as img:
            if img.info.get("icc_profile"):
                info["has_icc"] = True

            exif = img.getexif()
            if not exif:
                return info

            info["has_exif"] = True
            entries = _iter_exif_entries(exif)
            info["total_fields"] = len(entries)

            for key, val in entries:
                tag_name = ExifTags.TAGS.get(key, f"Tag_{key}")
                val_str = str(val)
                if len(val_str) > 100:
                    val_str = val_str[:100] + "..."
                if isinstance(val, bytes):
                    val_str = f"<bytes: {len(val)}>"

                entry = {"tag": tag_name, "value": val_str}

                if tag_name in GPS_TAGS or tag_name == "GPSInfo":
                    info["gps_fields"].append(entry)
                    info["has_gps"] = True
                elif tag_name in DEVICE_TAGS:
                    info["device_fields"].append(entry)
                    info["has_device"] = True
                elif tag_name in PERSONAL_TAGS:
                    info["personal_fields"].append(entry)
                    info["has_personal"] = True
                elif tag_name in TIME_TAGS:
                    info["time_fields"].append(entry)
                    info["has_time"] = True
                else:
                    info["other_fields"].append(entry)

    except Exception as e:
        info["error"] = str(e)

    return info


# Formats that can carry EXIF/XMP metadata worth stripping.
EXIF_CAPABLE_FORMATS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tiff",
    ".tif",
    ".heic",
    ".heif",
    ".avif",
}


def collect_strippable_files(
    input_paths: list[str],
    recursive: bool = False,
    selection: SelectionFilters | None = None,
) -> list[str]:
    """收集所有可清除元数据的图片文件（仅限能承载 EXIF 的格式）"""
    return collect_supported_files(
        input_paths, EXIF_CAPABLE_FORMATS, recursive=recursive, selection=selection
    )
