"""Registration for info/formats/doctor commands."""

import multiprocessing
import os
import sys
from io import BytesIO
from typing import List, Tuple

import click
from rich import box
from rich.console import Console
from rich.table import Table

from ..converter import PixShiftConverter, SUPPORTED_INPUT_FORMATS, SUPPORTED_OUTPUT_FORMATS
from ..presenters.json_presenters import emit_json


def register_system_commands(cli_group: click.Group, console: Console, mini_logo: str) -> None:
    """Register system and information commands."""

    @cli_group.command("info")
    @click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("--exif", is_flag=True, default=False,
                  help="显示完整 EXIF 元数据(拍摄参数/设备等). 默认: 不显示")
    @click.option("--json", "as_json", is_flag=True, default=False,
                  help="以 JSON 输出结果（适合脚本调用）")
    def info(files, exif, as_json):
        """📋 查看图片详细信息 (格式/尺寸/大小/颜色模式/EXIF)"""
        if as_json:
            items = []
            for filepath in files:
                img_info = PixShiftConverter.get_image_info(filepath)
                if not exif and "exif" in img_info:
                    img_info = dict(img_info)
                    img_info.pop("exif", None)
                items.append(img_info)
            emit_json({
                "command": "info",
                "ok": True,
                "total": len(items),
                "files": items,
            })
            return

        console.print(f"\n{mini_logo} [bold]图片信息[/bold]\n")

        for filepath in files:
            img_info = PixShiftConverter.get_image_info(filepath)

            table = Table(
                title=f"📄 {os.path.basename(filepath)}",
                box=box.ROUNDED,
                show_header=False,
                title_style="bold cyan",
            )
            table.add_column("属性", style="bold", width=16)
            table.add_column("值", style="")

            table.add_row("路径", str(filepath))
            table.add_row("格式", img_info.get("format", "N/A"))
            table.add_row("扩展名", img_info.get("format_ext", "N/A"))
            table.add_row("文件大小", img_info.get("size_human", "N/A"))

            if "width" in img_info:
                table.add_row("尺寸", f"{img_info['width']} × {img_info['height']} px")
                megapixels = (img_info["width"] * img_info["height"]) / 1_000_000
                table.add_row("像素", f"{megapixels:.1f} MP")

            table.add_row("颜色模式", img_info.get("mode", "N/A"))
            table.add_row("透明通道", "✅ 是" if img_info.get("has_alpha") else "❌ 否")

            console.print(table)

            if exif and "exif" in img_info:
                exif_table = Table(
                    title="📷 EXIF 信息",
                    box=box.SIMPLE,
                    show_header=True,
                )
                exif_table.add_column("标签", style="cyan", width=24)
                exif_table.add_column("值", style="")
                for tag, val in sorted(img_info["exif"].items()):
                    exif_table.add_row(tag, str(val)[:80])
                console.print(exif_table)

            console.print()

    @cli_group.command("formats")
    @click.option("--json", "as_json", is_flag=True, default=False,
                  help="以 JSON 输出结果（适合脚本调用）")
    def formats(as_json):
        """📑 列出所有支持的图片格式"""
        in_exts = sorted(SUPPORTED_INPUT_FORMATS)
        out_formats = sorted(SUPPORTED_OUTPUT_FORMATS)
        heif_ok = _check_heif()
        avif_ok = _check_avif()

        if as_json:
            emit_json({
                "command": "formats",
                "ok": True,
                "input_extensions": in_exts,
                "output_formats": out_formats,
                "features": {
                    "heif": heif_ok,
                    "avif_encode": avif_ok,
                },
            })
            return

        console.print(f"\n{mini_logo} [bold]支持的格式[/bold]\n")

        table_rt = Table(title="🔎 运行时能力探测", box=box.ROUNDED)
        table_rt.add_column("项目", style="bold cyan", width=22)
        table_rt.add_column("状态", style="")
        table_rt.add_row("输入扩展名数量", str(len(in_exts)))
        table_rt.add_row("输出格式数量", str(len(out_formats)))
        table_rt.add_row("HEIF/HEIC 支持", "✅ 可用" if heif_ok else "⚠️ 未启用 (pip install pillow-heif)")
        table_rt.add_row("AVIF 编码支持", "✅ 可用" if avif_ok else "⚠️ 未启用 (pip install pillow-avif-plugin)")
        table_rt.add_row("输入扩展预览", _preview_items(in_exts))
        table_rt.add_row("输出格式预览", _preview_items(out_formats))
        console.print(table_rt)
        console.print()

        table_q = Table(title="💎 质量预设", box=box.ROUNDED)
        table_q.add_column("等级", style="bold", width=10)
        table_q.add_column("说明", style="")
        table_q.add_column("适用场景", style="dim")
        table_q.add_row("[green]max[/green]", "最高质量 (默认)", "专业用途、存档")
        table_q.add_row("[blue]high[/blue]", "高质量", "日常使用")
        table_q.add_row("[yellow]medium[/yellow]", "中等质量", "一般用途")
        table_q.add_row("[red]low[/red]", "低质量", "缩略图、预览")
        table_q.add_row("[magenta]web[/magenta]", "网页优化", "网站、博客")
        console.print(table_q)
        console.print()

    @cli_group.command("doctor")
    @click.option("--json", "as_json", is_flag=True, default=False,
                  help="以 JSON 输出结果（适合脚本调用）")
    def doctor(as_json):
        """🩺 检查运行环境和依赖"""
        checks = _collect_doctor_checks()
        all_ready = all(ok for _, _, ok in checks)
        if as_json:
            emit_json({
                "command": "doctor",
                "ok": True,
                "all_ready": all_ready,
                "checks": [
                    {"name": name, "status": status, "ok": ok}
                    for name, status, ok in checks
                ],
            })
            return

        console.print(f"\n{mini_logo} [bold]环境检查[/bold]\n")

        table = Table(box=box.ROUNDED, show_header=True)
        table.add_column("组件", style="bold", width=28)
        table.add_column("状态", style="")
        table.add_column("", width=3)
        for name, status, ok in checks:
            icon = "[green]✅[/green]" if ok else "[red]❌[/red]"
            table.add_row(name, status if ok else f"[red]{status}[/red]", icon)
        console.print(table)

        if all_ready:
            console.print("\n  [bold green]🎉 所有依赖已就绪！[/bold green]\n")
        else:
            console.print("\n  [bold yellow]⚠️  部分依赖缺失，某些格式可能不支持[/bold yellow]")
            console.print("  运行以下命令安装所有依赖:")
            console.print("  [bold]pip install pillow pillow-heif click rich PyMuPDF[/bold]\n")


def _check_heif() -> bool:
    """Check if pillow-heif is available."""
    try:
        import pillow_heif  # noqa: F401
        return True
    except ImportError:
        return False


def _check_avif() -> bool:
    """Check whether AVIF encoding is available in current runtime."""
    try:
        from PIL import Image

        img = Image.new("RGB", (1, 1))
        buf = BytesIO()
        img.save(buf, format="AVIF")
        return True
    except Exception:
        return False


def _collect_doctor_checks() -> List[Tuple[str, str, bool]]:
    """Collect runtime doctor checks used by both rich and JSON output."""
    checks: List[Tuple[str, str, bool]] = []
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("Python", py_ver, sys.version_info >= (3, 8)))

    try:
        from PIL import Image
        checks.append(("Pillow", Image.__version__, True))
    except ImportError:
        checks.append(("Pillow", "未安装", False))

    try:
        import pillow_heif
        checks.append(("pillow-heif (HEIC支持)", pillow_heif.__version__, True))
    except ImportError:
        checks.append(("pillow-heif (HEIC支持)", "未安装 (pip install pillow-heif)", False))

    try:
        import pillow_avif  # noqa: F401
        checks.append(("pillow-avif (AVIF支持)", "✅", True))
    except ImportError:
        avif_builtin = _check_avif()
        checks.append(("AVIF 支持", "内置 (Pillow)" if avif_builtin else "未安装 (pip install pillow-avif-plugin)", avif_builtin))

    try:
        import fitz
        fitz_ver = fitz.version[0] if hasattr(fitz, "version") else fitz.VersionBind
        checks.append(("PyMuPDF (PDF处理)", str(fitz_ver), True))
    except ImportError:
        checks.append(("PyMuPDF (PDF处理)", "未安装 (pip install PyMuPDF)", False))

    try:
        from importlib.metadata import version as pkg_version
        checks.append(("Rich (终端美化)", pkg_version("rich"), True))
    except Exception:
        checks.append(("Rich", "未安装", False))

    try:
        from importlib.metadata import version as pkg_version
        checks.append(("Click (CLI框架)", pkg_version("click"), True))
    except Exception:
        checks.append(("Click", "未安装", False))

    checks.append(("CPU 核心数", str(multiprocessing.cpu_count()), True))
    return checks


def _preview_items(items: List[str], limit: int = 18) -> str:
    """Render compact preview string for long capability lists."""
    if len(items) <= limit:
        return ", ".join(items)
    head = ", ".join(items[:limit])
    return f"{head}, ... (+{len(items) - limit})"

