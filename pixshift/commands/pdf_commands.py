"""Registration for PDF command group."""

import os
from pathlib import Path
from typing import Callable, Optional

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from ..pdf_engine import (
    PAGE_SIZES,
    PDF_COMPRESS_PRESETS,
)
from ..ops import pdf as pdf_ops
from ..presenters.json_presenters import emit_json, emit_json_and_exit


def register_pdf_commands(
    cli_group: click.Group,
    console: Console,
    mini_logo: str,
    human_size: Callable[[int], str],
) -> None:
    """Register PDF command group and subcommands."""

    @cli_group.group("pdf")
    def pdf() -> None:
        """📑 PDF 处理工具集 (合并/拆分/压缩/拼接/信息)"""

    @pdf.command("merge")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-o", "--output", "output_path", required=True, type=click.Path(),
                  help="[必填] 输出 PDF 文件路径")
    @click.option("--page", "page_size", default="a4",
                  type=click.Choice(list(PAGE_SIZES.keys()), case_sensitive=False),
                  help="页面大小. 可选: a4|a3|a5|letter|legal|b5|fit. 默认: a4")
    @click.option("-q", "--quality", default=95, type=click.IntRange(1, 100),
                  help="图片嵌入质量 (1-100). 默认: 95")
    @click.option("--margin", default=20, type=int,
                  help="页边距 (点, 1点≈0.35mm). 默认: 20")
    @click.option("--landscape", is_flag=True, default=False,
                  help="横向页面. 默认: 纵向")
    @click.option("-r", "--recursive", is_flag=True, default=False,
                  help="递归扫描子目录中的图片. 默认: 仅当前目录")
    @click.option("--overwrite", is_flag=True, default=False,
                  help="覆盖已存在的输出文件. 默认: 不覆盖")
    @click.option("--json", "as_json", is_flag=True, default=False,
                  help="以 JSON 输出结果（适合脚本调用）")
    def pdf_merge_cmd(inputs, output_path, page_size, quality, margin, landscape, recursive, overwrite, as_json):
        """📑 多图合并成 PDF"""
        if not pdf_ops.is_available():
            if as_json:
                emit_json_and_exit({"command": "pdf.merge", "ok": False, "error": "pymupdf_missing"}, 1)
            else:
                console.print("[red]❌ PDF 功能需要 PyMuPDF。请安装: pip install PyMuPDF[/red]")
            return

        image_files = pdf_ops.collect_images(list(inputs), recursive)
        if not image_files:
            if as_json:
                emit_json({"command": "pdf.merge", "ok": True, "total": 0, "message": "no_images"})
            else:
                console.print("[yellow]⚠️  未找到可用的图片文件[/yellow]")
            return

        if not as_json:
            console.print(f"\n{mini_logo} [bold]PDF 合并 — 多图 → PDF[/bold]\n")
            console.print(f"  📁 找到 [bold green]{len(image_files)}[/bold green] 张图片")
            console.print(f"  📄 页面大小: [bold cyan]{page_size.upper()}[/bold cyan]" + (" [横向]" if landscape else " [纵向]"))
            console.print(f"  💎 图片质量: [bold]{quality}[/bold]")
            console.print(f"  📐 页边距: [bold]{margin}[/bold] pt")
            console.print(f"  📤 输出: [bold]{output_path}[/bold]\n")

        result = pdf_ops.merge_images(
            image_paths=image_files,
            output_path=output_path,
            page_size=page_size,
            quality=quality,
            margin=margin,
            landscape=landscape,
            overwrite=overwrite,
        )

        if as_json:
            payload = {
                "command": "pdf.merge",
                "ok": result.success,
                "input_count": len(image_files),
                "output": output_path,
                "page_count": result.page_count,
                "input_bytes": result.input_size,
                "output_bytes": result.output_size,
                "duration_sec": round(result.duration, 4),
                "error": result.error or "",
            }
            if not result.success:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return

        if result.success:
            console.print(Panel(
                f"  ✅ 合并成功！\n"
                f"  📄 页数: [bold green]{result.page_count}[/bold green] 页\n"
                f"  📦 输入: {human_size(result.input_size)}"
                f"  →  输出: [bold]{human_size(result.output_size)}[/bold]\n"
                f"  📁 文件: {output_path}\n"
                f"  ⏱️  耗时: [bold]{result.duration:.2f}s[/bold]",
                title="[bold]📑 PDF 合并完成[/bold]",
                border_style="green",
                box=box.ROUNDED,
            ))
        else:
            console.print(f"[red]❌ 合并失败: {result.error}[/red]")
        console.print()

    @pdf.command("extract")
    @click.argument("pdf_file", type=click.Path(exists=True))
    @click.option("-o", "--output", "output_dir", required=True, type=click.Path(),
                  help="[必填] 输出目录路径")
    @click.option("-t", "--format", "output_format", default="png",
                  type=click.Choice(["png", "jpg", "webp", "tiff"], case_sensitive=False),
                  help="输出图片格式")
    @click.option("--dpi", default=300, type=click.IntRange(72, 1200), help="渲染 DPI")
    @click.option("--pages", default=None, type=str, help="指定页码, 如 '1-5,8,10-12'")
    @click.option("--prefix", default="", type=str, help="输出文件名前缀")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出文件")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def pdf_extract_cmd(pdf_file, output_dir, output_format, dpi, pages, prefix, overwrite, as_json):
        """📤 PDF 拆分为图片"""
        if not pdf_ops.is_available():
            if as_json:
                emit_json_and_exit({"command": "pdf.extract", "ok": False, "error": "pymupdf_missing"}, 1)
            else:
                console.print("[red]❌ PDF 功能需要 PyMuPDF。请安装: pip install PyMuPDF[/red]")
            return

        result = pdf_ops.extract_pages(
            pdf_path=pdf_file,
            output_dir=output_dir,
            output_format=output_format,
            dpi=dpi,
            pages=pages,
            prefix=prefix,
            overwrite=overwrite,
        )

        if as_json:
            payload = {
                "command": "pdf.extract",
                "ok": result.success,
                "input": pdf_file,
                "output_dir": output_dir,
                "exported_pages": result.page_count,
                "total_pages": result.details.get("total_pages"),
                "input_bytes": result.input_size,
                "output_bytes": result.output_size,
                "duration_sec": round(result.duration, 4),
                "error": result.error or "",
            }
            if not result.success:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return

        console.print(f"\n{mini_logo} [bold]PDF 拆分 — PDF → 图片[/bold]\n")
        if result.success:
            console.print(Panel(
                f"  ✅ 拆分成功！\n"
                f"  📄 PDF 总页数: [bold]{result.details.get('total_pages', '?')}[/bold]\n"
                f"  📤 导出页数: [bold green]{result.page_count}[/bold green] 页\n"
                f"  📦 输入: {human_size(result.input_size)}"
                f"  →  输出: [bold]{human_size(result.output_size)}[/bold]\n"
                f"  📂 目录: {output_dir}\n"
                f"  ⏱️  耗时: [bold]{result.duration:.2f}s[/bold]",
                title="[bold]📤 PDF 拆分完成[/bold]",
                border_style="green",
                box=box.ROUNDED,
            ))
        else:
            console.print(f"[red]❌ 拆分失败: {result.error}[/red]")
        console.print()

    @pdf.command("compress")
    @click.argument("pdf_file", type=click.Path(exists=True))
    @click.option("-o", "--output", "output_path", default=None, type=click.Path(), help="输出 PDF 路径")
    @click.option("-p", "--preset", default="medium",
                  type=click.Choice(list(PDF_COMPRESS_PRESETS.keys()), case_sensitive=False),
                  help="压缩预设")
    @click.option("--image-quality", default=None, type=click.IntRange(1, 100), help="自定义图片质量")
    @click.option("--max-dpi", default=None, type=click.IntRange(72, 1200), help="自定义最大图片 DPI")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出文件")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def pdf_compress_cmd(pdf_file, output_path, preset, image_quality, max_dpi, overwrite, as_json):
        """🗜️  PDF 压缩优化"""
        if not pdf_ops.is_available():
            if as_json:
                emit_json_and_exit({"command": "pdf.compress", "ok": False, "error": "pymupdf_missing"}, 1)
            else:
                console.print("[red]❌ PDF 功能需要 PyMuPDF。请安装: pip install PyMuPDF[/red]")
            return

        if output_path is None:
            p = Path(pdf_file)
            output_path = str(p.parent / f"{p.stem}_compressed.pdf")

        result = pdf_ops.compress(
            input_path=pdf_file,
            output_path=output_path,
            preset=preset,
            image_quality=image_quality,
            max_image_dpi=max_dpi,
            overwrite=overwrite,
        )

        if as_json:
            payload = {
                "command": "pdf.compress",
                "ok": result.success,
                "input": pdf_file,
                "output": output_path,
                "page_count": result.page_count,
                "input_bytes": result.input_size,
                "output_bytes": result.output_size,
                "duration_sec": round(result.duration, 4),
                "error": result.error or "",
            }
            if not result.success:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return

        console.print(f"\n{mini_logo} [bold]PDF 压缩优化[/bold]\n")
        if result.success:
            ratio_text = ""
            if result.input_size > 0:
                ratio = (result.output_size / result.input_size) * 100
                saved = result.input_size - result.output_size
                if saved > 0:
                    ratio_text = f"  📉 压缩率: [bold green]{ratio:.1f}%[/bold green] (节省 {human_size(saved)})"
                else:
                    ratio_text = f"  📈 体积变化: [bold yellow]{ratio:.1f}%[/bold yellow] (增加 {human_size(-saved)})"
            console.print(Panel(
                f"  ✅ 压缩成功！\n"
                f"  📄 页数: [bold]{result.page_count}[/bold] 页\n"
                f"  📦 输入: {human_size(result.input_size)}"
                f"  →  输出: [bold]{human_size(result.output_size)}[/bold]\n"
                f"{ratio_text}\n"
                f"  📁 文件: {output_path}\n"
                f"  ⏱️  耗时: [bold]{result.duration:.2f}s[/bold]",
                title="[bold]🗜️  PDF 压缩完成[/bold]",
                border_style="green",
                box=box.ROUNDED,
            ))
        else:
            console.print(f"[red]❌ 压缩失败: {result.error}[/red]")
        console.print()

    @pdf.command("concat")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-o", "--output", "output_path", required=True, type=click.Path(), help="[必填] 输出 PDF 文件路径")
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归扫描子目录中的 PDF")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出文件")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def pdf_concat_cmd(inputs, output_path, recursive, overwrite, as_json):
        """📎 多个 PDF 合并成一个"""
        if not pdf_ops.is_available():
            if as_json:
                emit_json_and_exit({"command": "pdf.concat", "ok": False, "error": "pymupdf_missing"}, 1)
            else:
                console.print("[red]❌ PDF 功能需要 PyMuPDF。请安装: pip install PyMuPDF[/red]")
            return

        pdf_files = pdf_ops.collect_pdfs(list(inputs), recursive)
        if not pdf_files:
            if as_json:
                emit_json({"command": "pdf.concat", "ok": True, "total": 0, "message": "no_pdfs"})
            else:
                console.print("[yellow]⚠️  未找到 PDF 文件[/yellow]")
            return
        if len(pdf_files) < 2:
            if as_json:
                emit_json_and_exit({"command": "pdf.concat", "ok": False, "error": "need_at_least_two"}, 1)
            else:
                console.print("[yellow]⚠️  至少需要 2 个 PDF 文件才能合并[/yellow]")
            return

        result = pdf_ops.concat(pdf_paths=pdf_files, output_path=output_path, overwrite=overwrite)
        if as_json:
            payload = {
                "command": "pdf.concat",
                "ok": result.success,
                "input_count": len(pdf_files),
                "output": output_path,
                "page_count": result.page_count,
                "input_bytes": result.input_size,
                "output_bytes": result.output_size,
                "duration_sec": round(result.duration, 4),
                "error": result.error or "",
            }
            if not result.success:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return

        console.print(f"\n{mini_logo} [bold]PDF 拼接 — 多PDF → 一个PDF[/bold]\n")
        if result.success:
            console.print(Panel(
                f"  ✅ 合并成功！\n"
                f"  📄 总页数: [bold green]{result.page_count}[/bold green] 页\n"
                f"  📁 文件数: [bold]{result.details.get('file_count', '?')}[/bold] 个\n"
                f"  📦 输入: {human_size(result.input_size)}"
                f"  →  输出: [bold]{human_size(result.output_size)}[/bold]\n"
                f"  📁 文件: {output_path}\n"
                f"  ⏱️  耗时: [bold]{result.duration:.2f}s[/bold]",
                title="[bold]📎 PDF 合并完成[/bold]",
                border_style="green",
                box=box.ROUNDED,
            ))
        else:
            console.print(f"[red]❌ 合并失败: {result.error}[/red]")
        console.print()

    @pdf.command("info")
    @click.argument("pdf_file", type=click.Path(exists=True))
    @click.option("--pages", is_flag=True, default=False, help="显示每页详细信息")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def pdf_info_cmd(pdf_file, pages, as_json):
        """📊 查看 PDF 详细信息"""
        if not pdf_ops.is_available():
            if as_json:
                emit_json_and_exit({"command": "pdf.info", "ok": False, "error": "pymupdf_missing"}, 1)
            else:
                console.print("[red]❌ PDF 功能需要 PyMuPDF。请安装: pip install PyMuPDF[/red]")
            return

        info = pdf_ops.info(pdf_file)
        if as_json:
            emit_json({
                "command": "pdf.info",
                "ok": True,
                "path": pdf_file,
                "size_bytes": info.size_bytes,
                "page_count": info.page_count,
                "encrypted": info.encrypted,
                "pdf_version": info.pdf_version,
                "image_count": info.image_count,
                "metadata": {
                    "title": info.title,
                    "author": info.author,
                    "subject": info.subject,
                    "creator": info.creator,
                    "producer": info.producer,
                    "creation_date": info.creation_date,
                    "mod_date": info.mod_date,
                },
                "pages": info.pages if pages else None,
            })
            return

        console.print(f"\n{mini_logo} [bold]PDF 信息[/bold]\n")
        table = Table(
            title=f"📄 {os.path.basename(pdf_file)}",
            box=box.ROUNDED,
            show_header=False,
            title_style="bold cyan",
        )
        table.add_column("属性", style="bold", width=16)
        table.add_column("值", style="")
        table.add_row("文件路径", pdf_file)
        table.add_row("文件大小", human_size(info.size_bytes))
        table.add_row("PDF 版本", info.pdf_version or "N/A")
        table.add_row("页数", f"[bold green]{info.page_count}[/bold green]")
        table.add_row("加密", "🔒 是" if info.encrypted else "🔓 否")
        table.add_row("图片总数", str(info.image_count))
        if info.title:
            table.add_row("标题", info.title)
        if info.author:
            table.add_row("作者", info.author)
        if info.subject:
            table.add_row("主题", info.subject)
        if info.creator:
            table.add_row("创建工具", info.creator)
        if info.producer:
            table.add_row("PDF 生成器", info.producer)
        if info.creation_date:
            table.add_row("创建日期", info.creation_date)
        if info.mod_date:
            table.add_row("修改日期", info.mod_date)
        console.print(table)

        if pages and info.pages:
            console.print()
            page_table = Table(title="📑 页面详情", box=box.SIMPLE, show_header=True)
            page_table.add_column("#", style="dim", width=5)
            page_table.add_column("宽度(pt)", style="", width=10)
            page_table.add_column("高度(pt)", style="", width=10)
            page_table.add_column("尺寸(mm)", style="cyan", width=16)
            page_table.add_column("旋转", style="", width=6)
            page_table.add_column("图片数", style="green", width=8)
            for pg in info.pages[:100]:
                page_table.add_row(
                    str(pg["number"]),
                    str(pg["width"]),
                    str(pg["height"]),
                    f"{pg['width_mm']}×{pg['height_mm']}",
                    f"{pg['rotation']}°" if pg["rotation"] else "-",
                    str(pg["image_count"]),
                )
            if len(info.pages) > 100:
                page_table.add_row("...", "", "", "", f"(还有 {len(info.pages) - 100} 页)", "")
            console.print(page_table)
        console.print()

