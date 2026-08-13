"""
PixShift - 高效图片格式批量转换工具
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pixshift")
except PackageNotFoundError:
    __version__ = "0+unknown"

__author__ = "PixShift Team"

# Register optional Pillow format plugins at package import so that EVERY
# process which imports any pixshift module can decode them. Worker-pool
# children under spawn/forkserver start methods (the Linux default since
# Python 3.14) import only the worker's own module graph — before this hook
# a compress/strip pool child could not identify HEIC files even though the
# parent CLI process could.
try:
    import pillow_heif as _pillow_heif

    _pillow_heif.register_heif_opener()
    HEIF_SUPPORT = True
except ImportError:  # pragma: no cover - environment without the codec
    HEIF_SUPPORT = False

import contextlib

with contextlib.suppress(ImportError):
    # pillow-avif-plugin registers itself on import when installed.
    import pillow_avif as _pillow_avif  # noqa: F401
