"""Registration for PDF command group."""

import os
from collections.abc import Callable
from pathlib import Path

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..compress_engine import parse_target_size
from ..core.defaults import DEFAULT_PDF_EXTRACT_DPI, DEFAULT_PDF_MERGE_MARGIN
from ..ops import pdf as pdf_ops
from ..pdf_engine import (
    PAGE_SIZES,
    PDF_COMPRESS_PRESETS,
)
from ..presenters.json_presenters import emit_json, emit_json_and_exit
from .common import (
    usage_error_or_exit,
    validate_affixes_or_exit,
    validate_aggregate_output_or_exit,
)


def _require_pdf(command: str, as_json: bool) -> None:
    """Fail consistently when the optional PDF runtime is unavailable."""
    if pdf_ops.is_available():
        return
    if as_json:
        emit_json_and_exit({"command": command, "ok": False, "error": "pymupdf_missing"}, 1)
    raise click.ClickException("PDF 功能需要 PyMuPDF。请安装: pip install PyMuPDF")


def register_pdf_commands(
    cli_group: click.Group,
    console: Console,
    mini_logo: str,
    human_size: Callable[[int], str],
) -> None:
    """Register PDF command group and subcommands."""

    @cli_group.group("pdf")
    def pdf() -> None:
        """PDF 合并、拆分、压缩、拼接和信息查看工具。"""

    @pdf.command("merge")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option(
        "-o",
        "--output",
        "output_path",
        required=True,
        type=click.Path(),
        help="[必填] 输出 PDF 文件路径",
    )
    @click.option(
        "--page",
        "page_size",
        default="a4",
        type=click.Choice(list(PAGE_SIZES.keys()), case_sensitive=False),
        help="页面大小. 可选: a4|a3|a5|letter|legal|b5|fit. 默认: a4",
    )
    @click.option(
        "-q",
        "--quality",
        default=95,
        type=click.IntRange(1, 100),
        help="图片嵌入质量 (1-100). 默认: 95",
    )
    @click.option(
        "--margin",
        default=DEFAULT_PDF_MERGE_MARGIN,
        type=click.IntRange(0),
        help="页边距，单位为点（1 点约为 0.35 mm）。默认: 20",
    )
    @click.option("--landscape", is_flag=True, default=False, help="横向页面. 默认: 纵向")
    @click.option(
        "-r",
        "--recursive",
        is_flag=True,
        default=False,
        help="递归扫描子目录中的图片. 默认: 仅当前目录",
    )
    @click.option(
        "--overwrite", is_flag=True, default=False, help="覆盖已存在的输出文件. 默认: 不覆盖"
    )
    @click.option(
        "--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果（适合脚本调用）"
    )
    def pdf_merge_cmd(
        inputs: tuple[str, ...],
        output_path: str,
        page_size: str,
        quality: int,
        margin: int,
        landscape: bool,
        recursive: bool,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """将多张图片合并为 PDF。"""
        _require_pdf("pdf.merge", as_json)

        image_files = pdf_ops.collect_images(list(inputs), recursive)
        validate_aggregate_output_or_exit(
            command="pdf.merge", as_json=as_json, inputs=image_files, output=output_path
        )
        if not image_files:
            if as_json:
                emit_json({"command": "pdf.merge", "ok": True, "total": 0, "message": "no_images"})
            else:
                console.print("[yellow]未找到可用的图片文件。[/yellow]")
            return

        if not as_json:
            console.print(f"\n{mini_logo} [bold]PDF 合并：图片转 PDF[/bold]\n")
            console.print(f"  图片数: [bold green]{len(image_files)}[/bold green]")
            console.print(
                f"  页面大小: [bold cyan]{page_size.upper()}[/bold cyan]"
                + (" [横向]" if landscape else " [纵向]")
            )
            console.print(f"  图片质量: [bold]{quality}[/bold]")
            console.print(f"  页边距: [bold]{margin}[/bold] 点")
            console.print(f"  输出文件: [bold]{output_path}[/bold]\n")

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
            console.print(
                Panel(
                    f"  页数: [bold green]{result.page_count}[/bold green]\n"
                    f"  输入: {human_size(result.input_size)}；"
                    f"输出: [bold]{human_size(result.output_size)}[/bold]\n"
                    f"  输出文件: {output_path}\n"
                    f"  耗时: [bold]{result.duration:.2f} 秒[/bold]",
                    title="[bold]PDF 合并完成[/bold]",
                    border_style="green",
                    box=box.ROUNDED,
                )
            )
        else:
            console.print(f"[red]PDF 合并失败: {result.error}[/red]")
            raise click.exceptions.Exit(1)
        console.print()

    @pdf.command("split")
    @click.argument(
        "pdf_file", type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True)
    )
    @click.option(
        "-o", "--output", "output_dir", required=True, type=click.Path(), help="[必填] 输出目录路径"
    )
    @click.option("--pages", default=None, type=str, help="指定页码, 如 '1-5,8'；默认全部")
    @click.option(
        "--single", is_flag=True, default=False, help="所选页合并输出为一个 PDF（默认每页一个）"
    )
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出文件")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def pdf_split_cmd(
        pdf_file: str,
        output_dir: str,
        pages: str | None,
        single: bool,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """将 PDF 拆分为独立的 PDF 文件。"""
        _require_pdf("pdf.split", as_json)

        result = pdf_ops.split(
            pdf_path=pdf_file,
            output_dir=output_dir,
            pages=pages,
            single=single,
            overwrite=overwrite,
        )
        if not result.success and result.details.get("error_kind") == "usage":
            usage_error_or_exit(
                command="pdf.split",
                as_json=as_json,
                error=result.error,
                detail="--pages must select existing pages, for example '1-5,8'",
                human_message="--pages 页码范围无效或超出 PDF 总页数",
            )

        if as_json:
            payload = {
                "command": "pdf.split",
                "ok": result.success,
                "input": pdf_file,
                "output_dir": output_dir,
                "mode": "single" if single else "each",
                "total_pages": result.details.get("total_pages"),
                "requested_pages": result.details.get("requested_pages"),
                "written_files": result.details.get("written_files", 0),
                "skipped_existing": result.details.get("skipped_existing", 0),
                "input_bytes": result.input_size,
                "output_bytes": result.output_size,
                "duration_sec": round(result.duration, 4),
                "error": result.error or "",
            }
            if not result.success:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return

        console.print(f"\n{mini_logo} [bold]PDF 拆分[/bold]\n")
        if result.success:
            console.print(
                Panel(
                    f"  PDF 总页数: [bold]{result.details.get('total_pages', '?')}[/bold]\n"
                    f"  选中页数: [bold green]{result.details.get('requested_pages', 0)}[/bold green]\n"
                    f"  写出文件: [bold green]{result.details.get('written_files', 0)}[/bold green]\n"
                    f"  跳过已存在: [bold yellow]{result.details.get('skipped_existing', 0)}[/bold yellow]\n"
                    f"  输出目录: {output_dir}\n"
                    f"  耗时: [bold]{result.duration:.2f} 秒[/bold]",
                    title="[bold]PDF 拆分完成[/bold]",
                    border_style="green",
                    box=box.ROUNDED,
                )
            )
        else:
            console.print(f"[red]PDF 拆分失败: {result.error}[/red]")
            raise click.exceptions.Exit(1)
        console.print()

    @pdf.command("extract")
    @click.argument(
        "pdf_file", type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True)
    )
    @click.option(
        "-o", "--output", "output_dir", required=True, type=click.Path(), help="[必填] 输出目录路径"
    )
    @click.option(
        "-t",
        "--format",
        "output_format",
        default="png",
        type=click.Choice(["png", "jpg", "webp", "tiff"], case_sensitive=False),
        help="输出图片格式",
    )
    @click.option(
        "--dpi",
        default=DEFAULT_PDF_EXTRACT_DPI,
        type=click.IntRange(72, 1200),
        help="渲染 DPI；默认 150（屏幕查看与速度平衡）",
    )
    @click.option("--pages", default=None, type=str, help="指定页码, 如 '1-5,8,10-12'")
    @click.option("--prefix", default="", type=str, help="输出文件名前缀")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出文件")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def pdf_extract_cmd(
        pdf_file: str,
        output_dir: str,
        output_format: str,
        dpi: int,
        pages: str | None,
        prefix: str,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """将 PDF 页面导出为图片。"""
        validate_affixes_or_exit(
            command="pdf.extract",
            as_json=as_json,
            values=(("prefix", prefix),),
        )
        _require_pdf("pdf.extract", as_json)

        result = pdf_ops.extract_pages(
            pdf_path=pdf_file,
            output_dir=output_dir,
            output_format=output_format,
            dpi=dpi,
            pages=pages,
            prefix=prefix,
            overwrite=overwrite,
        )
        if not result.success and result.details.get("error_kind") == "usage":
            usage_error_or_exit(
                command="pdf.extract",
                as_json=as_json,
                error=result.error,
                detail="--pages must select existing pages, for example '1-5,8'",
                human_message="--pages 页码范围无效或超出 PDF 总页数",
            )

        if as_json:
            payload = {
                "command": "pdf.extract",
                "ok": result.success,
                "input": pdf_file,
                "output_dir": output_dir,
                "output_format": output_format.lower(),
                "dpi": dpi,
                "exported_pages": result.page_count,
                "requested_pages": result.details.get("requested_pages"),
                "skipped_existing": result.details.get("skipped_existing", 0),
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

        console.print(f"\n{mini_logo} [bold]PDF 拆分：PDF 转图片[/bold]\n")
        if result.success:
            console.print(
                Panel(
                    f"  PDF 总页数: [bold]{result.details.get('total_pages', '?')}[/bold]\n"
                    f"  导出页数: [bold green]{result.page_count}[/bold green]\n"
                    f"  跳过已存在页面: [bold yellow]"
                    f"{result.details.get('skipped_existing', 0)}[/bold yellow]\n"
                    f"  输入: {human_size(result.input_size)}；"
                    f"输出: [bold]{human_size(result.output_size)}[/bold]\n"
                    f"  输出目录: {output_dir}\n"
                    f"  耗时: [bold]{result.duration:.2f} 秒[/bold]",
                    title="[bold]PDF 拆分完成[/bold]",
                    border_style="green",
                    box=box.ROUNDED,
                )
            )
        else:
            console.print(f"[red]PDF 拆分失败: {result.error}[/red]")
            raise click.exceptions.Exit(1)
        console.print()

    @pdf.command("compress")
    @click.argument(
        "pdf_file", type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True)
    )
    @click.option(
        "-o", "--output", "output_path", default=None, type=click.Path(), help="输出 PDF 路径"
    )
    @click.option(
        "-p",
        "--preset",
        default="medium",
        type=click.Choice(list(PDF_COMPRESS_PRESETS.keys()), case_sensitive=False),
        help="压缩预设",
    )
    @click.option(
        "--image-quality", default=None, type=click.IntRange(1, 100), help="自定义图片质量"
    )
    @click.option(
        "--max-dpi", default=None, type=click.IntRange(72, 1200), help="自定义最大图片 DPI"
    )
    @click.option(
        "--target-size",
        "target_size",
        default=None,
        type=str,
        help="目标大小上限（如 2MB）：预算内保留最高质量（质量阶梯搜索）",
    )
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出文件")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    @click.pass_context
    def pdf_compress_cmd(
        ctx: click.Context,
        pdf_file: str,
        output_path: str | None,
        preset: str,
        image_quality: int | None,
        max_dpi: int | None,
        target_size: str | None,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """压缩并优化 PDF，或压到目标大小内保最高质量。"""
        _require_pdf("pdf.compress", as_json)

        target_bytes: int | None = None
        if target_size is not None:
            preset_explicit = (
                ctx.get_parameter_source("preset") is click.core.ParameterSource.COMMANDLINE
            )
            if image_quality is not None or preset_explicit:
                usage_error_or_exit(
                    command="pdf.compress",
                    as_json=as_json,
                    error="conflicting_options",
                    detail="--target-size cannot be combined with --preset or --image-quality",
                    human_message="--target-size 与 --preset / --image-quality 不能同时使用",
                )
            try:
                target_bytes = parse_target_size(target_size)
            except ValueError:
                usage_error_or_exit(
                    command="pdf.compress",
                    as_json=as_json,
                    error="invalid_target_size",
                    detail="--target-size expects a size like 500KB or 2MB",
                    human_message="--target-size 需要 500KB / 2MB 这样的大小格式",
                )

        if output_path is None:
            p = Path(pdf_file)
            output_path = str(p.parent / f"{p.stem}_compressed.pdf")

        if target_bytes is not None:
            result = pdf_ops.compress_to_target(
                input_path=pdf_file,
                output_path=output_path,
                target_size=target_bytes,
                max_image_dpi=max_dpi,
                overwrite=overwrite,
            )
        else:
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
                    ratio_text = f"  压缩率: [bold green]{ratio:.1f}%[/bold green]（节省 {human_size(saved)}）"
                else:
                    ratio_text = f"  体积变化: [bold yellow]{ratio:.1f}%[/bold yellow]（增加 {human_size(-saved)}）"
            console.print(
                Panel(
                    f"  页数: [bold]{result.page_count}[/bold]\n"
                    f"  输入: {human_size(result.input_size)}；"
                    f"输出: [bold]{human_size(result.output_size)}[/bold]\n"
                    f"{ratio_text}\n"
                    f"  输出文件: {output_path}\n"
                    f"  耗时: [bold]{result.duration:.2f} 秒[/bold]",
                    title="[bold]PDF 压缩完成[/bold]",
                    border_style="green",
                    box=box.ROUNDED,
                )
            )
        else:
            console.print(f"[red]PDF 压缩失败: {result.error}[/red]")
            raise click.exceptions.Exit(1)
        console.print()

    @pdf.command("concat")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option(
        "-o",
        "--output",
        "output_path",
        required=True,
        type=click.Path(),
        help="[必填] 输出 PDF 文件路径",
    )
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归扫描子目录中的 PDF")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出文件")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def pdf_concat_cmd(
        inputs: tuple[str, ...],
        output_path: str,
        recursive: bool,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """将多个 PDF 拼接为一个文件。"""
        _require_pdf("pdf.concat", as_json)

        validate_aggregate_output_or_exit(
            command="pdf.concat", as_json=as_json, inputs=list(inputs), output=output_path
        )
        pdf_files = pdf_ops.collect_pdfs(list(inputs), recursive)
        validate_aggregate_output_or_exit(
            command="pdf.concat", as_json=as_json, inputs=pdf_files, output=output_path
        )
        ignored_generated = 0
        if not pdf_files:
            if as_json:
                emit_json(
                    {
                        "command": "pdf.concat",
                        "ok": True,
                        "total": 0,
                        "message": "no_pdfs",
                        "ignored_generated": ignored_generated,
                    }
                )
            else:
                console.print("[yellow]未找到 PDF 文件。[/yellow]")
            return
        if ignored_generated and not as_json:
            console.print(f"[dim]已忽略 {ignored_generated} 个既有拼接输出[/dim]")
        if len(pdf_files) < 2:
            if as_json:
                emit_json_and_exit(
                    {"command": "pdf.concat", "ok": False, "error": "need_at_least_two"}, 2
                )
            else:
                console.print("[yellow]至少需要 2 个 PDF 文件。[/yellow]")
                raise click.exceptions.Exit(2)
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
                "ignored_generated": ignored_generated,
                "warnings": result.details.get("warnings", []),
            }
            if not result.success:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return

        console.print(f"\n{mini_logo} [bold]PDF 拼接：合并多个 PDF[/bold]\n")
        if result.success:
            console.print(
                Panel(
                    f"  总页数: [bold green]{result.page_count}[/bold green]\n"
                    f"  文件数: [bold]{result.details.get('file_count', '?')}[/bold]\n"
                    f"  输入: {human_size(result.input_size)}；"
                    f"输出: [bold]{human_size(result.output_size)}[/bold]\n"
                    f"  输出文件: {output_path}\n"
                    f"  耗时: [bold]{result.duration:.2f} 秒[/bold]",
                    title="[bold]PDF 拼接完成[/bold]",
                    border_style="green",
                    box=box.ROUNDED,
                )
            )
            for warning in result.details.get("warnings", []):
                console.print(f"[yellow]警告: {warning}[/yellow]")
        else:
            console.print(f"[red]PDF 拼接失败: {result.error}[/red]")
            raise click.exceptions.Exit(1)
        console.print()

    @pdf.command("info")
    @click.argument(
        "pdf_file", type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True)
    )
    @click.option("--pages", is_flag=True, default=False, help="显示每页详细信息")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def pdf_info_cmd(pdf_file: str, pages: bool, as_json: bool) -> None:
        """查看 PDF 详细信息。"""
        _require_pdf("pdf.info", as_json)

        info = pdf_ops.info(pdf_file)
        if as_json:
            payload = {
                "command": "pdf.info",
                "ok": not bool(info.error),
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
                "error": info.error,
            }
            if info.error:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return

        if info.error:
            raise click.ClickException(f"PDF 信息读取失败: {info.error}")

        console.print(f"\n{mini_logo} [bold]PDF 信息[/bold]\n")
        table = Table(
            title=os.path.basename(pdf_file),
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
        table.add_row("加密", "是" if info.encrypted else "否")
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
            page_table = Table(title="页面详情", box=box.SIMPLE, show_header=True)
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
