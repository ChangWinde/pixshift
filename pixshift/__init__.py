"""
PixShift - 高效图片格式批量转换工具
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pixshift")
except PackageNotFoundError:
    __version__ = "0+unknown"

__author__ = "PixShift Team"
