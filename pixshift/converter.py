"""
PixShift Core Converter Engine
支持多格式、最高质量的图片转换引擎
"""

import math
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core.defaults import DEFAULT_CONVERT_QUALITY
from .core.errors import AnimatedInputNotSupportedError
from .core.files import (
    SelectionFilters,
    atomic_output_path,
    collect_supported_files,
    conversion_output_name,
    plan_output_path,
)
from .core.metadata import (
    ensure_within_pixel_limit,
    flatten_transparency,
    image_frame_count,
    image_has_transparency,
    normalize_orientation,
    normalized_exif_bytes,
)

try:
    import pillow_heif
    from PIL import ExifTags, Image, ImageFile, ImageSequence

    pillow_heif.register_heif_opener()
    HEIF_SUPPORT = True
except ImportError:
    HEIF_SUPPORT = False
    try:
        from PIL import ExifTags, Image, ImageFile, ImageSequence
    except ImportError:
        print("请先安装 Pillow: pip install Pillow")
        sys.exit(1)


# ============================================================
#  支持的格式定义
# ============================================================


def _build_supported_input_formats() -> set[str]:
    """Build input extensions backed by a usable runtime decoder."""
    Image.init()
    extensions: set[str] = set()
    for extension, format_name in Image.registered_extensions().items():
        handler = Image.OPEN.get(format_name)
        if handler is None or format_name == "MPEG":
            continue
        factory = handler[0]
        if isinstance(factory, type) and issubclass(factory, ImageFile.StubImageFile):
            continue
        if format_name == "EPS" and shutil.which("gs") is None:
            continue
        extensions.add(extension.lower())
    return extensions


def _build_supported_output_formats() -> set[str]:
    """Report writable outputs from the registered saver table.

    An earlier version actually encoded a 16x16 probe for each candidate,
    which on every process start initialised the libheif/x265 encoder — ~43ms
    and ~61MB RSS just to compute a set. Checking ``Image.SAVE`` (populated by
    ``Image.init()`` and by the pillow-heif/avif plugins on registration) is
    equivalent and effectively free.
    """
    candidates = {
        "png": "PNG",
        "jpg": "JPEG",
        "jpeg": "JPEG",
        "webp": "WEBP",
        "tif": "TIFF",
        "tiff": "TIFF",
        "bmp": "BMP",
        "gif": "GIF",
        "heic": "HEIF",
        "heif": "HEIF",
        "avif": "AVIF",
        "pdf": "PDF",
        "ico": "ICO",
        "tga": "TGA",
    }
    Image.init()
    savers = set(Image.SAVE) | set(Image.SAVE_ALL)
    return {name for name, pillow_format in candidates.items() if pillow_format in savers}


SUPPORTED_INPUT_FORMATS = _build_supported_input_formats()
SUPPORTED_OUTPUT_FORMATS = _build_supported_output_formats()

# 格式别名映射
FORMAT_ALIASES = {
    "jpeg": "jpg",
    "tif": "tiff",
    "heif": "heic",
}

# 输出端支持动画的格式（png 即 APNG）。动图只允许转到这些目标；
# 其余格式保持稳定报错，绝不静默丢帧。
ANIMATED_OUTPUT_FORMATS = {"webp", "gif", "png"}

_DEFAULT_FRAME_DURATION_MS = 100

# 能够存储 CMYK 像素的输出格式（已按 FORMAT_ALIASES 归一化）。
_CMYK_CAPABLE = {"jpg", "jpeg", "tiff", "tif", "pdf"}


def _color_family(mode: str) -> str:
    """Group a Pillow mode into an ICC-compatible colour family.

    An embedded ICC profile describes one colour space; once the pixels move
    to another family (notably CMYK -> RGB) the profile is meaningless and
    must be dropped. RGB/RGBA/L/P all share device-RGB handling, so flatten or
    palette changes keep the profile valid.
    """
    if mode in ("CMYK", "YCCK"):
        return "cmyk"
    if mode == "LAB":
        return "lab"
    return "rgb"


# 每种输出格式的最佳质量参数
QUALITY_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
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
    results: list[ConvertResult] = field(default_factory=list)


# ============================================================
#  核心转换器
# ============================================================


class PixShiftConverter:
    """PixShift 核心转换引擎"""

    def __init__(
        self,
        quality: str = DEFAULT_CONVERT_QUALITY,
        resize: tuple[int, int] | None = None,
        resize_percent: float | None = None,
        max_size: int | None = None,
        keep_exif: bool = True,
        keep_icc: bool = True,
        overwrite: bool = False,
        strip_alpha: bool = False,
        background_color: tuple[int, int, int] = (255, 255, 255),
        auto_orient: bool = True,
    ):
        if quality not in QUALITY_PRESETS:
            raise ValueError(f"unsupported_quality_preset: {quality}")
        resize_modes = sum(option is not None for option in (resize, resize_percent, max_size))
        if resize_modes > 1:
            raise ValueError("resize_options_are_mutually_exclusive")
        if resize is not None and (resize[0] <= 0 or resize[1] <= 0):
            raise ValueError("resize_dimensions_must_be_positive")
        if resize_percent is not None and (
            not math.isfinite(resize_percent) or resize_percent <= 0
        ):
            raise ValueError("resize_percent_must_be_positive_and_finite")
        if max_size is not None and max_size <= 0:
            raise ValueError("max_size_must_be_positive")
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

    def get_save_params(self, fmt: str) -> dict[str, Any]:
        """获取指定格式和质量等级的保存参数"""
        fmt = fmt.lower().lstrip(".")
        preset = QUALITY_PRESETS[self.quality]
        params = preset.get(fmt, {}).copy()
        return params

    def _process_image(self, img: Image.Image, output_fmt: str) -> Image.Image:
        """处理图片：调整大小、方向、颜色模式等"""

        return self._process_image_with_orientation(img, output_fmt)[0]

    def _process_image_with_orientation(
        self,
        img: Image.Image,
        output_fmt: str,
    ) -> tuple[Image.Image, bool]:
        """Process pixels and report whether EXIF orientation was consumed."""
        orientation_normalized = False

        # 自动旋转（根据 EXIF 信息）
        if self.auto_orient:
            try:
                img = self._auto_orient(img)
                orientation_normalized = True
            except Exception:
                # Damaged EXIF must not block pixel conversion. Metadata
                # serialization below will omit fields it cannot parse.
                pass

        # 调整大小
        if self.resize:
            img = img.resize(self.resize, Image.Resampling.LANCZOS)
        elif self.resize_percent:
            w, h = img.size
            new_w = max(1, int(w * self.resize_percent / 100))
            new_h = max(1, int(h * self.resize_percent / 100))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        elif self.max_size:
            img.thumbnail((self.max_size, self.max_size), Image.Resampling.LANCZOS)

        # 处理 Alpha 通道
        output_fmt_lower = output_fmt.lower()
        no_alpha_formats = {"jpg", "jpeg", "bmp", "pdf", "pcx"}

        if output_fmt_lower in no_alpha_formats or self.strip_alpha:
            if image_has_transparency(img):
                img = flatten_transparency(img, self.background_color)
            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

        # 只有 JPEG/TIFF/PDF 能存 CMYK；其余格式（PNG/WEBP/HEIC…）直接保存
        # CMYK 会失败，需先转 RGB。
        if img.mode in ("CMYK", "YCCK") and output_fmt_lower not in _CMYK_CAPABLE:
            img = img.convert("RGB")

        return img, orientation_normalized

    def _auto_orient(self, img: Image.Image) -> Image.Image:
        """根据 EXIF 信息旋转图片，并移除已应用的方向标签。"""
        return normalize_orientation(img)

    def _process_animation_frame(self, frame: Image.Image) -> Image.Image:
        """Resize and normalise one animation frame.

        EXIF auto-orientation is deliberately skipped: orientation tags on
        animations are undefined in practice, and rotating frames against
        inconsistent per-frame EXIF would corrupt the stream.
        """
        if frame.mode not in ("RGB", "RGBA"):
            frame = frame.convert("RGBA" if image_has_transparency(frame) else "RGB")
        if self.resize:
            frame = frame.resize(self.resize, Image.Resampling.LANCZOS)
        elif self.resize_percent:
            width, height = frame.size
            new_width = max(1, int(width * self.resize_percent / 100))
            new_height = max(1, int(height * self.resize_percent / 100))
            frame = frame.resize((new_width, new_height), Image.Resampling.LANCZOS)
        elif self.max_size:
            frame.thumbnail((self.max_size, self.max_size), Image.Resampling.LANCZOS)
        if self.strip_alpha and image_has_transparency(frame):
            frame = flatten_transparency(frame, self.background_color)
        return frame

    def _save_animated(
        self,
        frames: list[Image.Image],
        durations: list[int],
        loop: int,
        output_fmt: str,
        output_path: str,
    ) -> None:
        """Encode a multi-frame image preserving frames, timing, and loop."""
        processed = [self._process_animation_frame(frame) for frame in frames]

        save_params = self.get_save_params(output_fmt)
        first = processed[0]
        exif_bytes = None
        if self.keep_exif:
            try:
                exif_bytes = normalized_exif_bytes(first, remove_orientation=False)
            except Exception:
                exif_bytes = None
        icc_profile = first.info.get("icc_profile") if self.keep_icc else None
        for frame in processed:
            # 同静态路径：编码器会从 info 回捞元数据，清洗必须显式删除。
            frame.info.pop("exif", None)
            frame.getexif().clear()
            if not self.keep_exif:
                frame.info.pop("xmp", None)
            frame.info.pop("icc_profile", None)
        if exif_bytes:
            save_params["exif"] = exif_bytes
        if icc_profile:
            save_params["icc_profile"] = icc_profile

        save_params.update(
            save_all=True,
            append_images=processed[1:],
            duration=durations,
            loop=loop,
        )
        if output_fmt == "gif":
            # Full-frame replacement disposal: frames were composited on
            # decode, so carrying over partial-frame disposal would smear.
            save_params["disposal"] = 2
        with atomic_output_path(output_path) as temporary:
            first.save(temporary, **save_params)

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

            # 打开图片并复制到内存，避免覆盖源文件时依赖惰性文件句柄。
            animation: tuple[list[Image.Image], list[int], int] | None = None
            with Image.open(input_path) as opened:
                # Checked before any pixel is decoded: convert is the one path
                # that also accepts animations, so it cannot rely on
                # ensure_static_image for the pixel budget.
                ensure_within_pixel_limit(opened)
                result.width, result.height = opened.size
                source_mode = opened.mode
                if image_frame_count(opened) > 1:
                    if output_fmt not in ANIMATED_OUTPUT_FORMATS:
                        raise AnimatedInputNotSupportedError()
                    animation = _extract_animation(opened)
                else:
                    img = opened.copy()
                    img.info.update(opened.info)

            if animation is not None:
                # Save only after the source handle is closed: Windows cannot
                # atomically replace a file that is still open, so an in-place
                # --overwrite re-encode would fail there.
                frames, durations, loop = animation
                self._save_animated(frames, durations, loop, output_fmt, output_path)
                result.output_size = os.path.getsize(output_path)
                result.success = True
                result.duration = time.time() - start_time
                return result

            # 处理图片
            img, orientation_normalized = self._process_image_with_orientation(img, output_fmt)

            # 获取保存参数
            save_params = self.get_save_params(output_fmt)

            # 计算 EXIF/ICC，必须在清理 img.info 之前完成（getexif 读的是 info）。
            exif_bytes = None
            if self.keep_exif:
                try:
                    exif_bytes = normalized_exif_bytes(
                        img,
                        remove_orientation=orientation_normalized,
                    )
                except Exception:
                    exif_bytes = None
            # CMYK→RGB 之类的色彩模型变换会让内嵌 ICC 失效，必须丢弃。
            color_space_changed = _color_family(source_mode) != _color_family(img.mode)
            icc_profile = None
            if self.keep_icc and not color_space_changed:
                icc_profile = img.info.get("icc_profile")

            # Pillow 各编码器（PNG/WEBP/TIFF/HEIF…）会从 img.info 回捞
            # exif/xmp/icc 即使未传对应 kwarg，因此清洗元数据必须显式删除这些键，
            # 而非只是"不传"——否则 --no-exif/--no-icc 对这些格式静默失效。
            img.info.pop("exif", None)
            img.getexif().clear()  # 清缓存的 EXIF，否则 HEIF/WebP 编码器会回写
            if not self.keep_exif:
                img.info.pop("xmp", None)
            img.info.pop("icc_profile", None)

            if exif_bytes:
                save_params["exif"] = exif_bytes
            if icc_profile:
                save_params["icc_profile"] = icc_profile

            # 保存到同目录临时文件，编码成功后原子替换。
            with atomic_output_path(output_path) as temporary:
                img.save(temporary, **save_params)

            result.output_size = os.path.getsize(output_path)
            result.success = True

        except Exception as e:
            result.error = str(e)

        result.duration = time.time() - start_time
        return result

    @staticmethod
    def get_image_info(filepath: str) -> dict[str, Any]:
        """获取图片详细信息"""
        info: dict[str, Any] = {
            "path": filepath,
            "exists": os.path.exists(filepath),
        }

        if not info["exists"]:
            return info

        info["size_bytes"] = os.path.getsize(filepath)
        info["size_human"] = _human_size(info["size_bytes"])
        info["format_ext"] = Path(filepath).suffix.lower()

        try:
            with Image.open(filepath) as img:
                info["width"] = img.size[0]
                info["height"] = img.size[1]
                info["mode"] = img.mode
                info["format"] = img.format
                info["has_alpha"] = image_has_transparency(img)
                info["frame_count"] = image_frame_count(img)

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


def _extract_animation(opened: Image.Image) -> tuple[list[Image.Image], list[int], int]:
    """Copy every frame with its duration (ms) and the stream's loop count.

    Pillow composites partial GIF frames on seek, so each copy is the full
    visible frame. Non-positive or missing durations fall back to a sane
    default rather than producing a zero-length frame.
    """
    default_duration = int(opened.info.get("duration") or _DEFAULT_FRAME_DURATION_MS)
    if default_duration <= 0:
        default_duration = _DEFAULT_FRAME_DURATION_MS
    frames: list[Image.Image] = []
    durations: list[int] = []
    for frame in ImageSequence.Iterator(opened):
        # copy() forces load(), and some decoders (WebP) only publish the
        # frame duration after load — so read timing from the copy.
        copied = frame.copy()
        duration = int(copied.info.get("duration") or default_duration)
        durations.append(duration if duration > 0 else default_duration)
        frames.append(copied)
    loop = int(opened.info.get("loop") or 0)
    return frames, durations, loop


def _human_size(size_bytes: int) -> str:
    """将字节数转换为人类可读的大小"""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def collect_files(
    input_paths: list[str],
    input_format: str | None = None,
    recursive: bool = False,
    selection: SelectionFilters | None = None,
) -> list[str]:
    """收集所有待转换的文件"""
    return collect_supported_files(
        input_paths=input_paths,
        supported_exts=SUPPORTED_INPUT_FORMATS,
        input_format=input_format,
        recursive=recursive,
        selection=selection,
    )


def generate_output_path(
    input_path: str,
    output_format: str,
    output_dir: str | None = None,
    prefix: str = "",
    suffix: str = "",
    flatten: bool = False,
    source_paths: list[str] | None = None,
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
