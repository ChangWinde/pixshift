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
from pathlib import Path
from typing import Optional, List, Dict, Set
from dataclasses import dataclass, field

from PIL import Image, ExifTags

from .converter import SUPPORTED_INPUT_FORMATS, _human_size


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
    results: List[StripResult] = field(default_factory=list)


# ============================================================
#  敏感 EXIF 标签
# ============================================================

# GPS 相关标签
GPS_TAGS = {
    "GPSInfo", "GPSVersionID", "GPSLatitudeRef", "GPSLatitude",
    "GPSLongitudeRef", "GPSLongitude", "GPSAltitudeRef", "GPSAltitude",
    "GPSTimeStamp", "GPSSatellites", "GPSStatus", "GPSMeasureMode",
    "GPSDOP", "GPSSpeedRef", "GPSSpeed", "GPSTrackRef", "GPSTrack",
    "GPSImgDirectionRef", "GPSImgDirection", "GPSMapDatum",
    "GPSDestLatitudeRef", "GPSDestLatitude", "GPSDestLongitudeRef",
    "GPSDestLongitude", "GPSDestBearingRef", "GPSDestBearing",
    "GPSDestDistanceRef", "GPSDestDistance", "GPSProcessingMethod",
    "GPSAreaInformation", "GPSDateStamp", "GPSDifferential",
}

# 设备信息标签
DEVICE_TAGS = {
    "Make", "Model", "Software", "HostComputer",
    "CameraOwnerName", "BodySerialNumber", "LensSerialNumber",
    "LensMake", "LensModel", "LensSpecification",
}

# 个人信息标签
PERSONAL_TAGS = {
    "Artist", "Copyright", "ImageDescription", "UserComment",
    "XPAuthor", "XPComment", "XPKeywords", "XPSubject", "XPTitle",
}

# 时间信息标签
TIME_TAGS = {
    "DateTime", "DateTimeOriginal", "DateTimeDigitized",
    "SubSecTime", "SubSecTimeOriginal", "SubSecTimeDigitized",
    "OffsetTime", "OffsetTimeOriginal", "OffsetTimeDigitized",
}

# 所有敏感标签
ALL_SENSITIVE_TAGS = GPS_TAGS | DEVICE_TAGS | PERSONAL_TAGS | TIME_TAGS


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

        img = Image.open(input_path)

        # 统计原始 EXIF 字段数
        original_fields = 0
        try:
            exif = img.getexif()
            original_fields = len(exif)
        except Exception:
            pass

        # 如果需要保留方向，先应用旋转
        if keep_orientation:
            img = _apply_orientation(img)

        if strip_exif:
            # 完全清除所有 EXIF
            save_kwargs = _get_clean_save_kwargs(img, input_path, strip_icc)
            img.save(output_path, **save_kwargs)
            result.exif_removed = True
            result.fields_removed = original_fields
        else:
            # 选择性清除
            fields_removed = _selective_strip(
                img, output_path, input_path,
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
    """应用 EXIF 方向信息后旋转图片"""
    try:
        exif = img.getexif()
        orientation_key = None
        for key, val in ExifTags.TAGS.items():
            if val == "Orientation":
                orientation_key = key
                break

        if orientation_key and orientation_key in exif:
            orientation = exif[orientation_key]
            if orientation == 2:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 3:
                img = img.transpose(Image.ROTATE_180)
            elif orientation == 4:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
            elif orientation == 5:
                img = img.transpose(Image.ROTATE_270).transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 6:
                img = img.transpose(Image.ROTATE_270)
            elif orientation == 7:
                img = img.transpose(Image.ROTATE_90).transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 8:
                img = img.transpose(Image.ROTATE_90)
    except Exception:
        pass
    return img


def _get_clean_save_kwargs(
    img: Image.Image,
    input_path: str,
    strip_icc: bool,
) -> dict:
    """获取干净的保存参数（不含 EXIF）"""
    ext = Path(input_path).suffix.lower()
    kwargs: dict = {}

    if ext in (".jpg", ".jpeg"):
        if img.mode in ("RGBA", "LA", "PA"):
            img = img.convert("RGB")
        kwargs = {"format": "JPEG", "quality": 95, "optimize": True}
    elif ext == ".png":
        kwargs = {"format": "PNG", "optimize": True}
    elif ext == ".webp":
        kwargs = {"format": "WEBP", "quality": 95}
    elif ext in (".tiff", ".tif"):
        kwargs = {"format": "TIFF", "compression": "tiff_lzw"}
    else:
        orig_format = img.format
        if orig_format:
            kwargs = {"format": orig_format}

    # 保留 ICC（如果不需要清除）
    if not strip_icc:
        try:
            icc = img.info.get("icc_profile")
            if icc:
                kwargs["icc_profile"] = icc
        except Exception:
            pass

    return kwargs


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
            save_kwargs = _get_clean_save_kwargs(img, input_path, strip_icc)
            img.save(output_path, **save_kwargs)
            return 0

        # 构建要删除的标签集合
        tags_to_remove: Set[str] = set()
        if strip_gps:
            tags_to_remove |= GPS_TAGS
        if strip_device:
            tags_to_remove |= DEVICE_TAGS
        if strip_personal:
            tags_to_remove |= PERSONAL_TAGS
        if strip_time:
            tags_to_remove |= TIME_TAGS

        # 反向映射：标签名 → 标签ID
        tag_name_to_id = {v: k for k, v in ExifTags.TAGS.items()}

        # 删除匹配的标签
        keys_to_delete = []
        for key in exif:
            tag_name = ExifTags.TAGS.get(key, "")
            if tag_name in tags_to_remove:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del exif[key]
            fields_removed += 1

        # 特殊处理 GPS IFD
        if strip_gps:
            gps_ifd_key = tag_name_to_id.get("GPSInfo")
            if gps_ifd_key and gps_ifd_key in exif:
                del exif[gps_ifd_key]
                fields_removed += 1

        # 保存
        save_kwargs = _get_clean_save_kwargs(img, input_path, strip_icc)
        if exif:
            save_kwargs["exif"] = exif.tobytes()
        img.save(output_path, **save_kwargs)

    except Exception:
        # 如果选择性清除失败，回退到完全清除
        save_kwargs = _get_clean_save_kwargs(img, input_path, strip_icc)
        img.save(output_path, **save_kwargs)
        fields_removed = -1  # 标记为完全清除

    return fields_removed


def analyze_metadata(filepath: str) -> Dict:
    """
    分析图片的元数据内容（用于预览）

    返回各类别的元数据统计
    """
    info = {
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
        img = Image.open(filepath)

        # ICC
        if img.info.get("icc_profile"):
            info["has_icc"] = True

        # EXIF
        exif = img.getexif()
        if not exif:
            return info

        info["has_exif"] = True
        info["total_fields"] = len(exif)

        for key, val in exif.items():
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


def collect_strippable_files(
    input_paths: List[str],
    recursive: bool = False,
) -> List[str]:
    """收集所有可清除元数据的图片文件"""
    files = []
    # 支持 EXIF 的格式
    exif_formats = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".heic", ".heif", ".avif"}

    for path_str in input_paths:
        path = Path(path_str)
        if path.is_file():
            if path.suffix.lower() in exif_formats:
                files.append(str(path.resolve()))
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for item in sorted(path.glob(pattern)):
                if item.is_file() and item.suffix.lower() in exif_formats:
                    files.append(str(item.resolve()))
    return sorted(set(files))
