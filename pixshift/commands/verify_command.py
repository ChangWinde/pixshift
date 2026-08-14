"""Registration for the cross-media quality gate."""

from __future__ import annotations

import math
from collections.abc import Callable

import click
from rich.console import Console

from ..compress_engine import parse_target_size
from ..ops import verify as verify_ops
from ..presenters.json_presenters import emit_json, emit_json_and_exit
from .common import usage_error_or_exit


def register_verify_command(
    cli_group: click.Group,
    console: Console,
    mini_logo: str,
    human_size: Callable[[int], str],
) -> None:
    """Register the media-aware verification command."""

    @cli_group.command("verify")
    @click.argument("source", type=click.Path(exists=True, dir_okay=False, readable=True))
    @click.argument("candidate", type=click.Path(exists=True, dir_okay=False, readable=True))
    @click.option("--min-ssim", default=0.99, show_default=True, type=click.FloatRange(0.0, 1.0))
    @click.option("--min-psnr", default=None, type=click.FloatRange(0.0))
    @click.option("--max-size", default=None, help="候选文件体积上限，如 2MB")
    @click.option("--allow-resize", is_flag=True, help="允许等比例尺寸变化后比较")
    @click.option("--json", "as_json", is_flag=True, help="以 JSON 输出结果")
    def verify_cmd(
        source: str,
        candidate: str,
        min_ssim: float,
        min_psnr: float | None,
        max_size: str | None,
        allow_resize: bool,
        as_json: bool,
    ) -> None:
        """验证图片、PDF 或视频候选是否满足结构与质量门槛。"""
        max_bytes = None
        if max_size is not None:
            try:
                max_bytes = parse_target_size(max_size)
            except ValueError:
                usage_error_or_exit(
                    command="verify",
                    as_json=as_json,
                    error="invalid_max_size",
                    detail="--max-size expects a positive size such as 2MB",
                    human_message="--max-size 需要 2MB 这样的正数体积。",
                )
        result = verify_ops.verify(
            source,
            candidate,
            min_ssim=min_ssim,
            min_psnr=min_psnr,
            max_bytes=max_bytes,
            allow_resize=allow_resize,
        )
        payload = {
            "command": "verify",
            "ok": result.success and result.passed,
            "passed": result.passed,
            "media_type": result.media_type,
            "source": source,
            "candidate": candidate,
            "source_bytes": result.source_bytes,
            "candidate_bytes": result.candidate_bytes,
            "thresholds": {
                "min_ssim": result.min_ssim,
                "min_psnr": result.min_psnr,
                "max_bytes": max_bytes,
            },
            "metrics": {
                "ssim": None if result.ssim is None else round(result.ssim, 6),
                "psnr": None
                if result.psnr is None or math.isinf(result.psnr)
                else round(result.psnr, 4),
                "sampled": result.sampled,
            },
            "checks": result.checks,
            "observations": result.observations,
            "error": result.error,
            "detail": result.detail,
        }
        if as_json:
            if not payload["ok"]:
                emit_json_and_exit(payload, 2 if result.rejected else 1)
            emit_json(payload)
            return
        console.print(f"\n{mini_logo} [bold]媒体质量验证[/bold]\n")
        console.print(
            f"[{'green' if result.passed else 'red'}]"
            f"{'通过' if result.passed else '未通过'}[/] · {result.media_type or '未知媒体'}"
        )
        if result.ssim is not None:
            console.print(f"SSIM {result.ssim:.6f}")
        if not result.passed:
            raise click.exceptions.Exit(2 if result.rejected else 1)
