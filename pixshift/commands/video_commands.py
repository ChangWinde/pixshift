"""Registration for the ffmpeg-backed video pillar."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click
from rich.console import Console

from ..compress_engine import parse_target_size
from ..core.files import filter_generated_inputs, plan_output_path
from ..core.media_runtime import FFMPEG_INSTALL_HINT
from ..ops import video as video_ops
from ..presenters.json_presenters import emit_json, emit_json_and_exit
from ..video_engine import (
    AUDIO_CODECS,
    AUDIO_POLICIES,
    CONTAINER_DEFAULT_CODEC,
    DEFAULT_AUDIO_FORMAT,
    DEFAULT_AUDIO_POLICY,
    DEFAULT_GIF_FPS,
    DEFAULT_GIF_WIDTH,
    DEFAULT_THUMBNAIL_AT,
    DEFAULT_VIDEO_CODEC,
    DEFAULT_VIDEO_CONTAINER,
    DEFAULT_VIDEO_PRESET,
    HWACCEL_BACKENDS,
    VIDEO_CODECS,
    VIDEO_COMPRESS_PRESETS,
    VideoResult,
    collect_video_files,
    parse_timecode,
    resolve_thumbnail_time,
    validate_container_codec,
)
from .common import validate_aggregate_output_or_exit, validate_tasks_or_exit


def _ffmpeg_missing(command: str, as_json: bool, console: Console) -> None:
    """Report a stable ffmpeg_missing error in the requested channel."""
    if as_json:
        emit_json_and_exit({"command": command, "ok": False, "error": "ffmpeg_missing"}, 1)
    raise click.ClickException(FFMPEG_INSTALL_HINT)


def _result_payload(result: VideoResult) -> dict:
    return {
        "input": result.input_path,
        "output": result.output_path,
        "ok": result.success,
        "input_bytes": result.input_bytes,
        "output_bytes": result.output_bytes,
        "error": result.error,
        "audio_policy": result.audio_policy,
        "audio_action": result.audio_action,
    }


def _emit_batch(command: str, results: list[VideoResult], as_json: bool, console: Console) -> None:
    succeeded = sum(1 for item in results if item.success)
    failed = sum(1 for item in results if not item.success and item.error != "output_exists")
    skipped = sum(1 for item in results if item.error == "output_exists")
    if as_json:
        payload = {
            "command": command,
            "ok": failed == 0,
            "total": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "skipped_existing": skipped,
            "results": [_result_payload(item) for item in results],
        }
        emit_json_and_exit(payload, 0 if failed == 0 else 1)
    for item in results:
        if item.success:
            console.print(f"[green]完成[/green] {Path(item.output_path).name}")
        elif item.error == "output_exists":
            console.print(f"[yellow]跳过[/yellow] {Path(item.output_path).name}（已存在）")
        else:
            detail = f"：{item.detail}" if item.detail else ""
            console.print(f"[red]失败[/red] {Path(item.input_path).name}（{item.error}{detail}）")
    console.print(f"\n成功 {succeeded} · 跳过 {skipped} · 失败 {failed}")
    if failed:
        raise click.exceptions.Exit(1)


def _video_output(path: str, name: str, output_dir: str | None, source_paths: list[str]) -> str:
    return plan_output_path(
        path, name, output_dir=output_dir, flatten=False, source_paths=source_paths
    )


def register_video_commands(
    cli_group: click.Group,
    console: Console,
    mini_logo: str,
    human_size: Callable[[int], str],
) -> None:
    """Register the ``video`` command group on the root CLI group."""

    @cli_group.group("video")
    def video() -> None:
        """视频操作（转码/压缩/截取/缩略图/提取音频/GIF）。"""

    @video.command("info")
    @click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def video_info(files: tuple, as_json: bool) -> None:
        """查看视频容器、编码、时长、分辨率等信息。"""
        if not video_ops.available():
            _ffmpeg_missing("video.info", as_json, console)
        infos = [video_ops.info(str(path)) for path in files]
        ok = all(item.error == "" for item in infos)
        if as_json:
            payload = {
                "command": "video.info",
                "ok": ok,
                "files": [
                    {
                        "path": item.path,
                        "duration_sec": round(item.duration_sec, 3),
                        "width": item.width,
                        "height": item.height,
                        "video_codec": item.video_codec,
                        "audio_codec": item.audio_codec,
                        "fps": round(item.fps, 3),
                        "bit_rate": item.bit_rate,
                        "container": item.container,
                        "stream_count": item.stream_count,
                        "size_bytes": item.size_bytes,
                        "error": item.error,
                    }
                    for item in infos
                ],
            }
            if not ok:
                emit_json_and_exit(payload, 1)
            emit_json(payload)
            return
        for item in infos:
            console.print(f"\n[bold]{Path(item.path).name}[/bold]")
            if item.error:
                console.print(f"  [red]{item.error}[/red]")
                continue
            console.print(
                f"  {item.width}x{item.height} · {item.video_codec or '?'} · "
                f"{item.duration_sec:.1f}s · {item.fps:.2f}fps · {human_size(item.size_bytes)}"
            )
        if not ok:
            raise click.exceptions.Exit(1)

    @video.command("convert")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option(
        "-t",
        "--to",
        "container",
        default=DEFAULT_VIDEO_CONTAINER,
        type=click.Choice(["mp4", "webm", "mkv", "mov"]),
        help="目标容器",
    )
    @click.option("--codec", default=None, type=click.Choice(list(VIDEO_CODECS)), help="视频编码器")
    @click.option(
        "--audio-policy",
        default=DEFAULT_AUDIO_POLICY,
        type=click.Choice(list(AUDIO_POLICIES)),
        help="音频策略: preserve 原样复制；compatible 兼容转码；compact 小体积",
    )
    @click.option(
        "--hwaccel",
        default=None,
        type=click.Choice(list(HWACCEL_BACKENDS)),
        help="硬件编码后端（显式启用，仅 h264/h265；需 ffmpeg 带对应编码器）",
    )
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(), help="输出目录")
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归子目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def video_convert(
        inputs: tuple,
        container: str,
        codec: str | None,
        audio_policy: str,
        hwaccel: str | None,
        output_dir: str | None,
        recursive: bool,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """转码视频到另一容器/编码。"""
        if not video_ops.available():
            _ffmpeg_missing("video.convert", as_json, console)
        try:
            validate_container_codec(container, codec or CONTAINER_DEFAULT_CODEC[container])
        except ValueError as error:
            _fail("video.convert", str(error), as_json, console)
            return
        files = collect_video_files(list(inputs), recursive)
        files, _ = filter_generated_inputs(
            files,
            list(inputs),
            output_root=output_dir,
        )

        def convert_name(path: str) -> str:
            source = Path(path)
            target_suffix = f".{container}"
            if source.suffix.lower() == target_suffix:
                return f"{source.stem}_converted.{container}"
            # A directory can contain both ``clip.mp4`` and ``clip.webm``.
            # Keep both as inputs without planning an output over either one.
            if any(
                Path(other) != source
                and Path(other).parent == source.parent
                and Path(other).stem == source.stem
                and Path(other).suffix.lower() == target_suffix
                for other in files
            ):
                return f"{source.stem}_from_{source.suffix.lstrip('.').lower()}.{container}"
            return f"{source.stem}.{container}"

        tasks = [
            (
                path,
                _video_output(
                    path,
                    convert_name(path),
                    output_dir,
                    list(inputs),
                ),
            )
            for path in files
        ]
        validate_tasks_or_exit(command="video.convert", as_json=as_json, tasks=tasks)
        results = [
            video_ops.convert_one(
                path,
                dst,
                container=container,
                codec=codec,
                hwaccel=hwaccel,
                audio_policy=audio_policy,
                overwrite=overwrite,
            )
            for path, dst in tasks
        ]
        _emit_batch("video.convert", results, as_json, console)

    @video.command("compress")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option(
        "-p",
        "--preset",
        default=DEFAULT_VIDEO_PRESET,
        type=click.Choice(list(VIDEO_COMPRESS_PRESETS)),
        help="压缩预设",
    )
    @click.option(
        "--codec",
        default=DEFAULT_VIDEO_CODEC,
        type=click.Choice(list(VIDEO_CODECS)),
        help="视频编码器",
    )
    @click.option("--crf", default=None, type=click.IntRange(0, 63), help="覆盖预设 CRF")
    @click.option(
        "--audio-policy",
        default=DEFAULT_AUDIO_POLICY,
        type=click.Choice(list(AUDIO_POLICIES)),
        help="音频策略: preserve 原样复制；compatible 兼容转码；compact 小体积",
    )
    @click.option(
        "--target-size",
        "target_size",
        default=None,
        type=str,
        help="目标大小上限（如 25MB）：预算内保留最高质量（两遍编码）",
    )
    @click.option(
        "--hwaccel",
        default=None,
        type=click.Choice(list(HWACCEL_BACKENDS)),
        help="硬件编码后端（显式启用，仅 h264/h265；需 ffmpeg 带对应编码器）",
    )
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(), help="输出目录")
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归子目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    @click.pass_context
    def video_compress(
        ctx: click.Context,
        inputs: tuple,
        preset: str,
        codec: str,
        crf: int | None,
        audio_policy: str,
        target_size: str | None,
        hwaccel: str | None,
        output_dir: str | None,
        recursive: bool,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """按预设压缩视频体积，或压到目标大小内保最高质量。"""
        if not video_ops.available():
            _ffmpeg_missing("video.compress", as_json, console)
        target_bytes: int | None = None
        if target_size is not None:
            if crf is not None:
                _fail("video.compress", "conflicting_options", as_json, console)
            preset_source = ctx.get_parameter_source("preset")
            if preset_source is click.core.ParameterSource.COMMANDLINE:
                _fail("video.compress", "conflicting_options", as_json, console)
            try:
                target_bytes = parse_target_size(target_size)
            except ValueError:
                _fail("video.compress", "invalid_target_size", as_json, console)
        container = VIDEO_CODECS[codec][1]
        files = collect_video_files(list(inputs), recursive)
        files, _ = filter_generated_inputs(
            files,
            list(inputs),
            output_root=output_dir,
            generated_suffix="_compressed",
        )
        tasks = [
            (
                path,
                _video_output(
                    path,
                    f"{Path(path).stem}_compressed.{container}",
                    output_dir,
                    list(inputs),
                ),
            )
            for path in files
        ]
        validate_tasks_or_exit(command="video.compress", as_json=as_json, tasks=tasks)
        results = []
        for path, dst in tasks:
            if target_bytes is not None:
                results.append(
                    video_ops.compress_to_target_one(
                        path,
                        dst,
                        target_bytes=target_bytes,
                        codec=codec,
                        hwaccel=hwaccel,
                        overwrite=overwrite,
                        audio_policy=audio_policy,
                    )
                )
            else:
                results.append(
                    video_ops.compress_one(
                        path,
                        dst,
                        preset=preset,
                        codec=codec,
                        crf=crf,
                        hwaccel=hwaccel,
                        overwrite=overwrite,
                        audio_policy=audio_policy,
                    )
                )
        _emit_batch("video.compress", results, as_json, console)

    @video.command("concat")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option(
        "-o", "--output", "output_path", required=True, type=click.Path(), help="输出文件"
    )
    @click.option(
        "--reencode",
        is_flag=True,
        default=False,
        help="重编码为 h264 统一各段（默认流拷贝，要求编码/分辨率一致）",
    )
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def video_concat(
        inputs: tuple,
        output_path: str,
        reencode: bool,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """把多段视频首尾拼接为一个文件。"""
        if not video_ops.available():
            _ffmpeg_missing("video.concat", as_json, console)
        if len(inputs) < 2:
            _fail("video.concat", "concat_requires_two_inputs", as_json, console)
        if reencode:
            try:
                validate_container_codec(Path(output_path).suffix, "h264")
            except ValueError as error:
                _fail("video.concat", str(error), as_json, console)
                return
        validate_aggregate_output_or_exit(
            command="video.concat",
            as_json=as_json,
            inputs=[str(path) for path in inputs],
            output=output_path,
        )
        result = video_ops.concat_videos(
            [str(path) for path in inputs],
            output_path,
            reencode=reencode,
            overwrite=overwrite,
        )
        if as_json:
            payload = {
                "command": "video.concat",
                "clips": len(inputs),
                **_result_payload(result),
            }
            emit_json_and_exit(payload, 0 if result.success else 1)
        if result.success:
            console.print(f"[green]完成[/green] {result.output_path}（{len(inputs)} 段）")
        else:
            detail = f"：{result.detail}" if result.detail else ""
            console.print(f"[red]失败[/red]（{result.error}{detail}）")
            raise click.exceptions.Exit(1)

    @video.command("trim")
    @click.argument("source", type=click.Path(exists=True, dir_okay=False))
    @click.option("--start", default="0", type=str, help="起点 HH:MM:SS 或秒")
    @click.option("--end", default=None, type=str, help="终点 HH:MM:SS 或秒")
    @click.option("--duration", default=None, type=str, help="时长（秒），与 --end 二选一")
    @click.option("--reencode", is_flag=True, default=False, help="精确重编码（默认关键帧流拷贝）")
    @click.option("-o", "--output", "output_path", default=None, type=click.Path(), help="输出文件")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def video_trim(
        source: str,
        start: str,
        end: str | None,
        duration: str | None,
        reencode: bool,
        output_path: str | None,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """截取时间片段到新文件（默认流拷贝，秒级完成）。"""
        if not video_ops.available():
            _ffmpeg_missing("video.trim", as_json, console)
        if end is not None and duration is not None:
            _fail("video.trim", "conflicting_options", as_json, console)
        try:
            start_s = parse_timecode(start)
            end_s = parse_timecode(end) if end is not None else None
            dur_s = parse_timecode(duration) if duration is not None else None
        except ValueError as error:
            _fail("video.trim", str(error), as_json, console)
            return
        dst = output_path or str(
            Path(source).with_name(f"{Path(source).stem}_clip{Path(source).suffix}")
        )
        result = video_ops.trim_one(
            source,
            dst,
            start=start_s,
            end=end_s,
            duration=dur_s,
            reencode=reencode,
            overwrite=overwrite,
        )
        _emit_single("video.trim", result, as_json, console)

    @video.command("thumbnail")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option(
        "--at", "at_spec", default=DEFAULT_THUMBNAIL_AT, type=str, help="时间点 HH:MM:SS 或 25%"
    )
    @click.option(
        "-t",
        "--to",
        "image_format",
        default="jpg",
        type=click.Choice(["jpg", "png", "webp"]),
        help="缩略图格式",
    )
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(), help="输出目录")
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归子目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def video_thumbnail(
        inputs: tuple,
        at_spec: str,
        image_format: str,
        output_dir: str | None,
        recursive: bool,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """在指定时间点导出一帧静态图。"""
        if not video_ops.available():
            _ffmpeg_missing("video.thumbnail", as_json, console)
        try:
            # The spec's validity is file-independent; reject it up front.
            resolve_thumbnail_time(at_spec, 100.0)
        except ValueError as error:
            _fail("video.thumbnail", str(error), as_json, console)
        files = collect_video_files(list(inputs), recursive)
        tasks = [
            (
                path,
                _video_output(
                    path,
                    f"{Path(path).stem}_thumb.{image_format}",
                    output_dir,
                    list(inputs),
                ),
            )
            for path in files
        ]
        validate_tasks_or_exit(command="video.thumbnail", as_json=as_json, tasks=tasks)
        results = []
        for path, dst in tasks:
            probed = video_ops.info(path)
            at_seconds = resolve_thumbnail_time(at_spec, probed.duration_sec)
            results.append(
                video_ops.thumbnail_one(path, dst, at_seconds=at_seconds, overwrite=overwrite)
            )
        _emit_batch("video.thumbnail", results, as_json, console)

    @video.command("extract-audio")
    @click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
    @click.option(
        "-t",
        "--to",
        "audio_format",
        default=DEFAULT_AUDIO_FORMAT,
        type=click.Choice(list(AUDIO_CODECS)),
        help="音频格式",
    )
    @click.option("-o", "--output", "output_dir", default=None, type=click.Path(), help="输出目录")
    @click.option("-r", "--recursive", is_flag=True, default=False, help="递归子目录")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def video_extract_audio(
        inputs: tuple,
        audio_format: str,
        output_dir: str | None,
        recursive: bool,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """导出音频轨道。"""
        if not video_ops.available():
            _ffmpeg_missing("video.extract-audio", as_json, console)
        files = collect_video_files(list(inputs), recursive)
        tasks = [
            (
                path,
                _video_output(path, f"{Path(path).stem}.{audio_format}", output_dir, list(inputs)),
            )
            for path in files
        ]
        validate_tasks_or_exit(command="video.extract-audio", as_json=as_json, tasks=tasks)
        results = [
            video_ops.extract_audio_one(path, dst, audio_ext=audio_format, overwrite=overwrite)
            for path, dst in tasks
        ]
        _emit_batch("video.extract-audio", results, as_json, console)

    @video.command("gif")
    @click.argument("source", type=click.Path(exists=True, dir_okay=False))
    @click.option("--start", default="0", type=str, help="起点 HH:MM:SS 或秒")
    @click.option("--duration", default=None, type=str, help="时长（秒）")
    @click.option("--fps", default=DEFAULT_GIF_FPS, type=click.IntRange(1, 60), help="帧率")
    @click.option(
        "--width", default=DEFAULT_GIF_WIDTH, type=click.IntRange(1, 4096), help="宽度像素"
    )
    @click.option("-o", "--output", "output_path", default=None, type=click.Path(), help="输出文件")
    @click.option("--overwrite", is_flag=True, default=False, help="覆盖已存在输出")
    @click.option("--json", "as_json", is_flag=True, default=False, help="以 JSON 输出结果")
    def video_gif(
        source: str,
        start: str,
        duration: str | None,
        fps: int,
        width: int,
        output_path: str | None,
        overwrite: bool,
        as_json: bool,
    ) -> None:
        """把视频片段转成动画 GIF。"""
        if not video_ops.available():
            _ffmpeg_missing("video.gif", as_json, console)
        try:
            start_s = parse_timecode(start)
            dur_s = parse_timecode(duration) if duration is not None else None
        except ValueError as error:
            _fail("video.gif", str(error), as_json, console)
            return
        dst = output_path or str(Path(source).with_suffix(".gif"))
        result = video_ops.gif_one(
            source, dst, start=start_s, duration=dur_s, fps=fps, width=width, overwrite=overwrite
        )
        _emit_single("video.gif", result, as_json, console)


def _fail(command: str, code: str, as_json: bool, console: Console) -> None:
    """Reject invalid arguments before any encode starts (usage error, exit 2)."""
    if as_json:
        emit_json_and_exit({"command": command, "ok": False, "error": code}, 2)
    raise click.UsageError(code)


def _emit_single(command: str, result: VideoResult, as_json: bool, console: Console) -> None:
    if as_json:
        payload = {"command": command, **_result_payload(result)}
        emit_json_and_exit(payload, 0 if result.success else 1)
    if result.success:
        console.print(f"[green]完成[/green] {result.output_path}")
    else:
        detail = f"：{result.detail}" if result.detail else ""
        console.print(f"[red]失败[/red]（{result.error}{detail}）")
        raise click.exceptions.Exit(1)
