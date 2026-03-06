"""Registration for advanced image workflow commands."""

import os
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..converter import PixShiftConverter, SUPPORTED_INPUT_FORMATS
from ..core.files import collect_supported_files, derivative_output_name, plan_output_path
from ..ops import compare as compare_ops
from ..ops import crop as crop_ops
from ..ops import montage as montage_ops
from ..ops import optimize as optimize_ops
from ..ops import watermark as watermark_ops
from ..ops import watch as watch_ops
from ..presenters.json_presenters import emit_json, emit_json_and_exit

_WATERMARK_POSITIONS = [
    "top-left",
    "top-center",
    "top-right",
    "center-left",
    "center",
    "center-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
]


def register_advanced_commands(
    cli_group: click.Group,
    console: Console,
    mini_logo: str,
    human_size: Callable[[int], str],
) -> None:
    """Register advanced workflow commands."""

    @cli_group.command("compare")
    @click.argument("image_a", type=click.Path(exists=True))
    @click.argument("image_b", type=click.Path(exists=True))
    @click.option("--no-blocks", is_flag=True, default=False, help="关闭分块 SSIM（更快）")
    @click.option("--block-size", default=64, type=click.IntRange(16, 256), help="分块大小")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def compare_cmd(image_a: str, image_b: str, no_blocks: bool, block_size: int, as_json: bool) -> None:
        """🧪 对比两张图片质量（SSIM/PSNR/MSE）"""
        result = compare_ops.compare(image_a, image_b, use_blocks=not no_blocks, block_size=block_size)
        payload = {
            "command": "compare",
            "ok": result.success,
            "image_a": image_a,
            "image_b": image_b,
            "size_a": result.size_a,
            "size_b": result.size_b,
            "filesize_a": result.filesize_a,
            "filesize_b": result.filesize_b,
            "mse": round(result.mse, 6),
            "psnr": None if result.psnr == float("inf") else round(result.psnr, 4),
            "ssim": round(result.ssim, 6),
            "quality_rating": result.quality_rating,
            "quality_detail": result.quality_detail,
            "duration_sec": round(result.duration, 4),
            "error": result.error or "",
        }
        if as_json:
            if not result.success:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return
        if not result.success:
            console.print(f"[red]❌ 对比失败: {result.error}[/red]")
            return
        console.print(f"\n{mini_logo} [bold]图片对比[/bold]\n")
        console.print(
            Panel(
                f"  SSIM: [bold cyan]{result.ssim:.4f}[/bold cyan]\n"
                f"  PSNR: [bold]{'inf' if result.psnr == float('inf') else f'{result.psnr:.2f} dB'}[/bold]\n"
                f"  MSE : [bold]{result.mse:.4f}[/bold]\n"
                f"  评级: [bold green]{result.quality_rating}[/bold green]\n"
                f"  说明: {result.quality_detail}",
                title="[bold]🧪 对比结果[/bold]",
                border_style="green",
                box=box.ROUNDED,
            )
        )
        console.print()

    @cli_group.command("crop")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(), help="输出目录")
    @click.option("--crop", "crop_box", default=None, type=str, help="裁剪区域 left,top,right,bottom")
    @click.option("--aspect", default=None, type=str, help="按比例裁剪，如 16:9")
    @click.option("--trim", is_flag=True, default=False, help="自动裁剪边缘空白")
    @click.option("--trim-fuzz", default=10, type=click.IntRange(0, 255), help="自动裁剪容差")
    @click.option(
        "--gravity",
        default="center",
        type=click.Choice(["center", "top-left", "top-right", "bottom-left", "bottom-right"], case_sensitive=False),
        help="比例裁剪时重心",
    )
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归处理目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖输出")
    @click.option("--flatten", is_flag=True, default=False, help="扁平输出目录")
    @click.option("--dry-run", is_flag=True, default=False, help="仅预览")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def crop_cmd(
        inputs: Tuple[str, ...],
        output_dir: Optional[str],
        crop_box: Optional[str],
        aspect: Optional[str],
        trim: bool,
        trim_fuzz: int,
        gravity: str,
        recursive: bool,
        overwrite: bool,
        flatten: bool,
        dry_run: bool,
        as_json: bool,
    ) -> None:
        """✂️ 批量裁剪图片（区域/比例/自动裁边）"""
        enabled_modes = int(bool(crop_box)) + int(bool(aspect)) + int(bool(trim))
        if enabled_modes != 1:
            message = "select_exactly_one_mode"
            if as_json:
                emit_json_and_exit({"command": "crop", "ok": False, "error": message}, 1)
            console.print("[red]❌ 请且仅选择一种模式: --crop / --aspect / --trim[/red]")
            return

        files = crop_ops.collect_files(list(inputs), recursive)
        if not files:
            emit_json({"command": "crop", "ok": True, "total": 0, "message": "no_files"}) if as_json else console.print(
                "[yellow]⚠️  未找到可裁剪文件[/yellow]"
            )
            return

        tasks: List[Tuple[str, str]] = []
        for f in files:
            out_name = derivative_output_name(f, "_crop")
            out_path = plan_output_path(f, out_name, output_dir, flatten, list(inputs))
            tasks.append((f, out_path))

        if dry_run:
            payload = {
                "command": "crop",
                "ok": True,
                "mode": "dry_run",
                "total": len(tasks),
                "preview": [{"input": i, "output": o} for i, o in tasks[:50]],
            }
            if as_json:
                emit_json(payload)
            else:
                console.print(Panel(f"  共 {len(tasks)} 个文件将被裁剪", title="[bold]✂️ 预览[/bold]", box=box.ROUNDED))
            return

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        start = time.time()
        success = 0
        failed = 0
        errors: List[str] = []
        input_bytes = 0
        output_bytes = 0
        for inp, out in tasks:
            result = crop_ops.crop_one(inp, out, crop_box, aspect, trim, trim_fuzz, gravity, overwrite)
            input_bytes += result.input_size
            output_bytes += result.output_size if result.success else 0
            if result.success:
                success += 1
            else:
                failed += 1
                errors.append(f"{os.path.basename(inp)}: {result.error}")
        payload = {
            "command": "crop",
            "ok": failed == 0,
            "total": len(tasks),
            "success": success,
            "failed": failed,
            "input_bytes": input_bytes,
            "output_bytes": output_bytes,
            "duration_sec": round(time.time() - start, 4),
            "errors": errors,
        }
        if as_json:
            if failed:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return
        console.print(
            Panel(
                f"  ✅ 成功: [bold green]{success}[/bold green]\n"
                f"  ❌ 失败: [bold red]{failed}[/bold red]\n"
                f"  📦 输入: {human_size(input_bytes)} → 输出: {human_size(output_bytes)}",
                title="[bold]✂️ 裁剪完成[/bold]",
                border_style="green" if failed == 0 else "yellow",
                box=box.ROUNDED,
            )
        )
        console.print()

    @cli_group.group("watermark")
    def watermark_group() -> None:
        """💧 添加文字或图片水印"""

    @watermark_group.command("text")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("--text", required=True, help="水印文字")
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(), help="输出目录")
    @click.option("--font", "font_path", default=None, type=click.Path(), help="字体文件路径")
    @click.option("--font-size", default=36, type=int, help="字体大小")
    @click.option("--color", default="255,255,255", help="颜色")
    @click.option("--opacity", default=128, type=click.IntRange(0, 255), help="透明度")
    @click.option("--position", default="bottom-right", type=click.Choice(_WATERMARK_POSITIONS, case_sensitive=False))
    @click.option("--rotation", default=0, type=int, help="旋转角度")
    @click.option("--tile", is_flag=True, default=False, help="平铺水印")
    @click.option("--tile-spacing", default=100, type=int, help="平铺间距")
    @click.option("--margin", default=20, type=int, help="边距")
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归处理目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖输出")
    @click.option("--flatten", is_flag=True, default=False, help="扁平输出目录")
    @click.option("--dry-run", is_flag=True, default=False, help="仅预览")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def watermark_text_cmd(
        inputs: Tuple[str, ...],
        text: str,
        output_dir: Optional[str],
        font_path: Optional[str],
        font_size: int,
        color: str,
        opacity: int,
        position: str,
        rotation: int,
        tile: bool,
        tile_spacing: int,
        margin: int,
        recursive: bool,
        overwrite: bool,
        flatten: bool,
        dry_run: bool,
        as_json: bool,
    ) -> None:
        _run_watermark(
            mode="text",
            inputs=inputs,
            recursive=recursive,
            output_dir=output_dir,
            flatten=flatten,
            overwrite=overwrite,
            dry_run=dry_run,
            as_json=as_json,
            apply_text_kwargs={
                "text": text,
                "font_path": font_path,
                "font_size": font_size,
                "color": color,
                "opacity": opacity,
                "position": position,
                "rotation": rotation,
                "tile": tile,
                "tile_spacing": tile_spacing,
                "margin": margin,
            },
            apply_image_kwargs=None,
            console=console,
            human_size=human_size,
        )

    @watermark_group.command("image")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("--watermark", "watermark_path", required=True, type=click.Path(exists=True), help="水印图片")
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(), help="输出目录")
    @click.option("--scale", default=0.2, type=click.FloatRange(min=0.01, max=1.0), help="水印缩放比例")
    @click.option("--opacity", default=128, type=click.IntRange(0, 255), help="透明度")
    @click.option("--position", default="bottom-right", type=click.Choice(_WATERMARK_POSITIONS, case_sensitive=False))
    @click.option("--margin", default=20, type=int, help="边距")
    @click.option("--tile", is_flag=True, default=False, help="平铺水印")
    @click.option("--tile-spacing", default=100, type=int, help="平铺间距")
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归处理目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖输出")
    @click.option("--flatten", is_flag=True, default=False, help="扁平输出目录")
    @click.option("--dry-run", is_flag=True, default=False, help="仅预览")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def watermark_image_cmd(
        inputs: Tuple[str, ...],
        watermark_path: str,
        output_dir: Optional[str],
        scale: float,
        opacity: int,
        position: str,
        margin: int,
        tile: bool,
        tile_spacing: int,
        recursive: bool,
        overwrite: bool,
        flatten: bool,
        dry_run: bool,
        as_json: bool,
    ) -> None:
        _run_watermark(
            mode="image",
            inputs=inputs,
            recursive=recursive,
            output_dir=output_dir,
            flatten=flatten,
            overwrite=overwrite,
            dry_run=dry_run,
            as_json=as_json,
            apply_text_kwargs=None,
            apply_image_kwargs={
                "watermark_path": watermark_path,
                "scale": scale,
                "opacity": opacity,
                "position": position,
                "margin": margin,
                "tile": tile,
                "tile_spacing": tile_spacing,
            },
            console=console,
            human_size=human_size,
        )

    @cli_group.command("montage")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-o", "--output", "output_path", required=True, type=click.Path(), help="输出拼图文件")
    @click.option("--cols", default=3, type=click.IntRange(1, 20), help="列数")
    @click.option("--gap", default=10, type=click.IntRange(0, 200), help="间距")
    @click.option("--cell-width", default=None, type=int, help="单元格宽")
    @click.option("--cell-height", default=None, type=int, help="单元格高")
    @click.option("--background", default="255,255,255", help="背景色")
    @click.option("--border", default=0, type=int, help="边框宽度")
    @click.option("--border-color", default="200,200,200", help="边框颜色")
    @click.option("--label", is_flag=True, default=False, help="显示文件名")
    @click.option("--label-size", default=14, type=int, help="标签字号")
    @click.option("--no-auto-size", is_flag=True, default=False, help="关闭自动单元格尺寸")
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖输出")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def montage_cmd(
        inputs: Tuple[str, ...],
        output_path: str,
        cols: int,
        gap: int,
        cell_width: Optional[int],
        cell_height: Optional[int],
        background: str,
        border: int,
        border_color: str,
        label: bool,
        label_size: int,
        no_auto_size: bool,
        recursive: bool,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        files = montage_ops.collect_files(list(inputs), recursive)
        if not files:
            if as_json:
                emit_json({"command": "montage", "ok": True, "total": 0, "message": "no_files"})
            else:
                console.print("[yellow]⚠️  未找到可拼图文件[/yellow]")
            return
        result = montage_ops.create(
            input_paths=files,
            output_path=output_path,
            cols=cols,
            gap=gap,
            cell_width=cell_width,
            cell_height=cell_height,
            background=background,
            border=border,
            border_color=border_color,
            label=label,
            label_size=label_size,
            auto_size=not no_auto_size,
            overwrite=overwrite,
        )
        payload = {
            "command": "montage",
            "ok": result.success,
            "total_images": result.total_images,
            "grid_size": result.grid_size,
            "canvas_size": result.canvas_size,
            "output": output_path,
            "output_bytes": result.output_size,
            "duration_sec": round(result.duration, 4),
            "error": result.error or "",
        }
        if as_json:
            if not result.success:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return
        if not result.success:
            console.print(f"[red]❌ 拼图失败: {result.error}[/red]")
            return
        console.print(f"\n{mini_logo} [bold]拼图完成[/bold]\n")
        console.print(Panel(f"  图片: {result.total_images}\n  输出: {output_path}", box=box.ROUNDED, border_style="green"))
        console.print()

    @cli_group.command("optimize")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归处理目录")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def optimize_cmd(inputs: Tuple[str, ...], recursive: bool, as_json: bool) -> None:
        """📈 分析图片并推荐最佳输出格式"""
        files = collect_supported_files(list(inputs), SUPPORTED_INPUT_FORMATS, recursive=recursive)
        if not files:
            if as_json:
                emit_json({"command": "optimize", "ok": True, "total": 0, "message": "no_files"})
            else:
                console.print("[yellow]⚠️  未找到可分析文件[/yellow]")
            return
        analyses = [optimize_ops.analyze(f) for f in files]
        if as_json:
            emit_json(
                {
                    "command": "optimize",
                    "ok": all(not r.error for r in analyses),
                    "total": len(analyses),
                    "results": [
                        {
                            "input": r.input_path,
                            "input_bytes": r.input_size,
                            "image_type": r.image_type,
                            "recommended_format": r.recommended_format,
                            "recommended_reason": r.recommended_reason,
                            "error": r.error or "",
                        }
                        for r in analyses
                    ],
                }
            )
            return
        table = Table(title="📈 优化建议", box=box.ROUNDED)
        table.add_column("文件", style="cyan")
        table.add_column("类型")
        table.add_column("推荐格式", style="green")
        table.add_column("原因")
        for r in analyses[:50]:
            table.add_row(Path(r.input_path).name, r.image_type or "-", r.recommended_format or "-", r.recommended_reason or r.error)
        console.print(table)
        if len(analyses) > 50:
            console.print(f"[dim]... 还有 {len(analyses) - 50} 个文件[/dim]")
        console.print()

    @cli_group.command("watch")
    @click.argument("watch_dir", type=click.Path(exists=True, file_okay=False))
    @click.option("-t", "--to", "output_format", default="webp", help="目标格式")
    @click.option("-o", "--output", "output_dir", default="", type=click.Path(), help="输出目录")
    @click.option("-f", "--from", "input_format", default=None, help="仅监控指定输入格式")
    @click.option("-q", "--quality", default="max", type=click.Choice(["max", "high", "medium", "low", "web"]))
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归监控子目录")
    @click.option("--interval", default=2.0, type=click.FloatRange(0.2, 60.0), help="轮询间隔（秒）")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖输出")
    @click.option("--once", is_flag=True, default=False, help="单次扫描并退出")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果（仅 --once）")
    def watch_cmd(
        watch_dir: str,
        output_format: str,
        output_dir: str,
        input_format: Optional[str],
        quality: str,
        recursive: bool,
        interval: float,
        overwrite: bool,
        once: bool,
        as_json: bool,
    ) -> None:
        """👀 监控目录并自动转换新图片"""
        if as_json and not once:
            emit_json_and_exit({"command": "watch", "ok": False, "error": "json_requires_once"}, 1)
        if once:
            files = collect_supported_files([watch_dir], SUPPORTED_INPUT_FORMATS, input_format, recursive)
            converter = PixShiftConverter(quality=quality, overwrite=overwrite)
            success = 0
            failed = 0
            out_dir = output_dir or str(Path(watch_dir) / "converted")
            os.makedirs(out_dir, exist_ok=True)
            errors: List[str] = []
            for f in files:
                out = plan_output_path(f, f"{Path(f).stem}.{output_format.lower().lstrip('.')}", out_dir, False, [watch_dir])
                result = converter.convert_single(f, out)
                if result.success:
                    success += 1
                else:
                    failed += 1
                    errors.append(result.error)
            payload = {"command": "watch", "ok": failed == 0, "mode": "once", "total": len(files), "success": success, "failed": failed, "errors": errors}
            if as_json:
                if failed:
                    emit_json_and_exit(payload, 1)
                emit_json(payload)
                return
            console.print(f"[green]✅ 处理完成: {success}[/green], [red]失败: {failed}[/red]")
            return

        config = watch_ops.make_config(
            watch_dir=watch_dir,
            output_dir=output_dir,
            output_format=output_format,
            quality=quality,
            input_format=input_format,
            recursive=recursive,
            interval=interval,
            keep_exif=True,
            overwrite=overwrite,
        )

        def on_status(kind, message):
            if kind == "start":
                console.print(f"\n{mini_logo} [bold]目录监控[/bold]\n")
            console.print(f"[cyan]{message}[/cyan]")

        def on_new_file(kind, filepath, result=None):
            if kind == "success":
                console.print(f"[green]✅[/green] {os.path.basename(filepath)}")
            elif kind in {"failed", "error"}:
                err = result.error if hasattr(result, "error") else str(result)
                console.print(f"[red]❌[/red] {os.path.basename(filepath)}: {err}")

        watcher = watch_ops.create_watcher(config, on_new_file=on_new_file, on_status=on_status)
        stats = watcher.start()
        elapsed = max(0.0, time.time() - stats.start_time)
        console.print(
            Panel(
                f"  ✅ 成功: [bold green]{stats.files_processed}[/bold green]\n"
                f"  ❌ 失败: [bold red]{stats.files_failed}[/bold red]\n"
                f"  ⏱️  运行: [bold]{elapsed:.1f}s[/bold]",
                title="[bold]👀 监控结束[/bold]",
                box=box.ROUNDED,
            )
        )


def _run_watermark(
    mode: str,
    inputs: Tuple[str, ...],
    recursive: bool,
    output_dir: Optional[str],
    flatten: bool,
    overwrite: bool,
    dry_run: bool,
    as_json: bool,
    apply_text_kwargs: Optional[dict],
    apply_image_kwargs: Optional[dict],
    console: Console,
    human_size: Callable[[int], str],
) -> None:
    files = watermark_ops.collect_files(list(inputs), recursive)
    if not files:
        if as_json:
            emit_json({"command": f"watermark.{mode}", "ok": True, "total": 0, "message": "no_files"})
        else:
            console.print("[yellow]⚠️  未找到可处理文件[/yellow]")
        return

    tasks: List[Tuple[str, str]] = []
    for f in files:
        out_name = derivative_output_name(f, "_wm")
        out_path = plan_output_path(f, out_name, output_dir, flatten, list(inputs))
        tasks.append((f, out_path))

    if dry_run:
        payload = {
            "command": f"watermark.{mode}",
            "ok": True,
            "mode": "dry_run",
            "total": len(tasks),
            "preview": [{"input": i, "output": o} for i, o in tasks[:50]],
        }
        if as_json:
            emit_json(payload)
        else:
            console.print(Panel(f"  共 {len(tasks)} 个文件将添加水印", title="[bold]💧 预览[/bold]", box=box.ROUNDED))
        return

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    success = 0
    failed = 0
    errors: List[str] = []
    input_bytes = 0
    output_bytes = 0
    start = time.time()
    for inp, out in tasks:
        if mode == "text":
            result = watermark_ops.text_one(inp, out, overwrite=overwrite, **apply_text_kwargs)
        else:
            result = watermark_ops.image_one(inp, out, overwrite=overwrite, **apply_image_kwargs)
        input_bytes += result.input_size
        output_bytes += result.output_size if result.success else 0
        if result.success:
            success += 1
        else:
            failed += 1
            errors.append(f"{os.path.basename(inp)}: {result.error}")
    payload = {
        "command": f"watermark.{mode}",
        "ok": failed == 0,
        "total": len(tasks),
        "success": success,
        "failed": failed,
        "input_bytes": input_bytes,
        "output_bytes": output_bytes,
        "duration_sec": round(time.time() - start, 4),
        "errors": errors,
    }
    if as_json:
        if failed:
            emit_json_and_exit(payload, 1)
        emit_json(payload)
        return
    console.print(
        Panel(
            f"  ✅ 成功: [bold green]{success}[/bold green]\n"
            f"  ❌ 失败: [bold red]{failed}[/bold red]\n"
            f"  📦 输入: {human_size(input_bytes)} → 输出: {human_size(output_bytes)}",
            title=f"[bold]💧 水印完成 ({mode})[/bold]",
            border_style="green" if failed == 0 else "yellow",
            box=box.ROUNDED,
        )
    )
    console.print()

