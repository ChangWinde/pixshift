"""
PixShift Core Converter Engine
支持多格式、最高质量的图片转换引擎
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass, field
from enum import Enum
from .core.files import (
    collect_supported_files,
    plan_output_path,
    conversion_output_name,
)

try:
    from PIL import Image, ImageFilter, ExifTags
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_SUPPORT = True
except ImportError:
    HEIF_SUPPORT = False
    try:
        from PIL import Image, ImageFilter, ExifTags
    except ImportError:
        print("❌ 请先安装 Pillow: pip install Pillow")
        sys.exit(1)


# ============================================================
#  支持的格式定义
# ============================================================

def _build_supported_input_formats() -> set:
    """Build supported input extensions from current Pillow runtime."""
    exts = {ext.lower() for ext in Image.registered_extensions().keys()}
    exts.update({".jpg", ".jpeg", ".tif", ".tiff"})
    return exts


def _build_supported_output_formats() -> set:
    """Build supported output formats from current Pillow runtime."""
    formats = {fmt.lower() for fmt in Image.SAVE.keys()}
    normalized = set()
    for fmt in formats:
        if fmt == "jpeg":
            normalized.update({"jpg", "jpeg"})
        elif fmt == "tiff":
            normalized.update({"tif", "tiff"})
        else:
            normalized.add(fmt)
    return normalized


SUPPORTED_INPUT_FORMATS = _build_supported_input_formats()
SUPPORTED_OUTPUT_FORMATS = _build_supported_output_formats()

# 格式别名映射
FORMAT_ALIASES = {
    "jpeg": "jpg",
    "tif": "tiff",
    "heif": "heic",
}

# 每种输出格式的最佳质量参数
QUALITY_PRESETS = {
    "max": {
        "jpg": {"quality": 100, "subsampling": 0},
        "jpeg": {"quality": 100, "subsampling": 0},
        "png": {"compress_level": 0},  # 无损，最快
        "webp": {"quality": 100, "method": 6},
        "tiff": {"compression": "tiff_lzw"},
        "heic": {"quality": 100},
        "heif": {"quality": 100},
        "avif": {"quality": 100},
        "bmp": {},
        "gif": {},
        "ico": {},
        "pdf": {},
        "ppm": {},
        "tga": {},
        "pcx": {},
    },
    "high": {
        "jpg": {"quality": 95, "subsampling": 0},
        "jpeg": {"quality": 95, "subsampling": 0},
        "png": {"compress_level": 3},
        "webp": {"quality": 90, "method": 4},
        "tiff": {"compression": "tiff_lzw"},
        "heic": {"quality": 90},
        "avif": {"quality": 90},
    },
    "medium": {
        "jpg": {"quality": 85},
        "jpeg": {"quality": 85},
        "png": {"compress_level": 6},
        "webp": {"quality": 80, "method": 4},
        "tiff": {"compression": "tiff_lzw"},
    },
    "low": {
        "jpg": {"quality": 60},
        "jpeg": {"quality": 60},
        "png": {"compress_level": 9},
        "webp": {"quality": 50, "method": 6},
    },
    "web": {
        "jpg": {"quality": 80, "optimize": True},
        "jpeg": {"quality": 80, "optimize": True},
        "png": {"compress_level": 9, "optimize": True},
        "webp": {"quality": 75, "method": 6},
    },
}


# ============================================================
#  转换结果
# ============================================================

@dataclass
class ConvertResult:
    """单个文件的转换结果"""
    input_path: str
    output_path: str
    success: bool
    input_size: int = 0
    output_size: int = 0
    duration: float = 0.0
    error: str = ""
    width: int = 0
    height: int = 0


@dataclass
class BatchResult:
    """批量转换的汇总结果"""
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    total_input_size: int = 0
    total_output_size: int = 0
    total_duration: float = 0.0
    results: List[ConvertResult] = field(default_factory=list)


# ============================================================
#  核心转换器
# ============================================================

class PixShiftConverter:
    """PixShift 核心转换引擎"""

    def __init__(
        self,
        quality: str = "max",
        resize: Optional[Tuple[int, int]] = None,
        resize_percent: Optional[float] = None,
        max_size: Optional[int] = None,
        keep_exif: bool = True,
        keep_icc: bool = True,
        overwrite: bool = False,
        strip_alpha: bool = False,
        background_color: Tuple[int, int, int] = (255, 255, 255),
        auto_orient: bool = True,
    ):
        self.quality = quality
        self.resize = resize
        self.resize_percent = resize_percent
        self.max_size = max_size
        self.keep_exif = keep_exif
        self.keep_icc = keep_icc
        self.overwrite = overwrite
        self.strip_alpha = strip_alpha
        self.background_color = background_color
        self.auto_orient = auto_orient

    def get_save_params(self, fmt: str) -> dict:
        """获取指定格式和质量等级的保存参数"""
        fmt = fmt.lower().lstrip(".")
        preset = QUALITY_PRESETS.get(self.quality, QUALITY_PRESETS["max"])
        params = preset.get(fmt, {}).copy()
        return params

    def _process_image(self, img: Image.Image, output_fmt: str) -> Image.Image:
        """处理图片：调整大小、方向、颜色模式等"""

        # 自动旋转（根据 EXIF 信息）
        if self.auto_orient:
            try:
                img = self._auto_orient(img)
            except Exception:
                pass

        # 调整大小
        if self.resize:
            img = img.resize(self.resize, Image.LANCZOS)
        elif self.resize_percent:
            w, h = img.size
            new_w = int(w * self.resize_percent / 100)
            new_h = int(h * self.resize_percent / 100)
            img = img.resize((new_w, new_h), Image.LANCZOS)
        elif self.max_size:
            img.thumbnail((self.max_size, self.max_size), Image.LANCZOS)

        # 处理 Alpha 通道
        output_fmt_lower = output_fmt.lower()
        no_alpha_formats = {"jpg", "jpeg", "bmp", "pdf", "ico", "pcx"}

        if output_fmt_lower in no_alpha_formats or self.strip_alpha:
            if img.mode in ("RGBA", "LA", "PA"):
                background = Image.new("RGB", img.size, self.background_color)
                if img.mode == "RGBA":
                    background.paste(img, mask=img.split()[3])
                else:
                    img_rgba = img.convert("RGBA")
                    background.paste(img_rgba, mask=img_rgba.split()[3])
                img = background
            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

        return img

    def _auto_orient(self, img: Image.Image) -> Image.Image:
        """根据 EXIF 信息自动旋转图片"""
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

    def convert_single(self, input_path: str, output_path: str) -> ConvertResult:
        """转换单个文件"""
        result = ConvertResult(
            input_path=input_path,
            output_path=output_path,
            success=False,
        )

        start_time = time.time()

        try:
            # 检查输入文件
            if not os.path.exists(input_path):
                result.error = f"文件不存在: {input_path}"
                return result

            result.input_size = os.path.getsize(input_path)

            # 检查是否覆盖
            if os.path.exists(output_path) and not self.overwrite:
                result.error = "输出文件已存在（使用 --overwrite 覆盖）"
                return result

            # 确保输出目录存在
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

            # 获取输出格式
            output_fmt = Path(output_path).suffix.lstrip(".").lower()
            output_fmt = FORMAT_ALIASES.get(output_fmt, output_fmt)

            # 打开图片
            img = Image.open(input_path)
            result.width, result.height = img.size

            # 处理图片
            img = self._process_image(img, output_fmt)

            # 获取保存参数
            save_params = self.get_save_params(output_fmt)

            # 保留 EXIF
            if self.keep_exif:
                try:
                    exif_data = img.info.get("exif")
                    if exif_data:
                        save_params["exif"] = exif_data
                except Exception:
                    pass

            # 保留 ICC Profile
            if self.keep_icc:
                try:
                    icc_profile = img.info.get("icc_profile")
                    if icc_profile:
                        save_params["icc_profile"] = icc_profile
                except Exception:
                    pass

            # 保存
            img.save(output_path, **save_params)

            result.output_size = os.path.getsize(output_path)
            result.success = True

        except Exception as e:
            result.error = str(e)

        result.duration = time.time() - start_time
        return result

    @staticmethod
    def get_image_info(filepath: str) -> dict:
        """获取图片详细信息"""
        info = {
            "path": filepath,
            "exists": os.path.exists(filepath),
        }

        if not info["exists"]:
            return info

        info["size_bytes"] = os.path.getsize(filepath)
        info["size_human"] = _human_size(info["size_bytes"])
        info["format_ext"] = Path(filepath).suffix.lower()

        try:
            img = Image.open(filepath)
            info["width"] = img.size[0]
            info["height"] = img.size[1]
            info["mode"] = img.mode
            info["format"] = img.format
            info["has_alpha"] = img.mode in ("RGBA", "LA", "PA")

            # EXIF 信息
            try:
                exif = img.getexif()
                if exif:
                    exif_info = {}
                    for key, val in exif.items():
                        tag = ExifTags.TAGS.get(key, key)
                        if isinstance(val, bytes):
                            val = f"<bytes: {len(val)}>"
                        exif_info[str(tag)] = str(val)
                    info["exif"] = exif_info
            except Exception:
                pass

        except Exception as e:
            info["error"] = str(e)

        return info


# ============================================================
#  工具函数
# ============================================================

def _human_size(size_bytes: int) -> str:
    """将字节数转换为人类可读的大小"""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def collect_files(
    input_paths: List[str],
    input_format: Optional[str] = None,
    recursive: bool = False,
) -> List[str]:
    """收集所有待转换的文件"""
    return collect_supported_files(
        input_paths=input_paths,
        supported_exts=SUPPORTED_INPUT_FORMATS,
        input_format=input_format,
        recursive=recursive,
    )


def generate_output_path(
    input_path: str,
    output_format: str,
    output_dir: Optional[str] = None,
    prefix: str = "",
    suffix: str = "",
    flatten: bool = False,
    source_paths: Optional[List[str]] = None,
) -> str:
    """生成输出文件路径"""
    out_name = conversion_output_name(
        input_path=input_path,
        output_format=output_format,
        prefix=prefix,
        suffix=suffix,
    )
    return plan_output_path(
        input_path=input_path,
        output_name=out_name,
        output_dir=output_dir,
        flatten=flatten,
        source_paths=source_paths,
    )
