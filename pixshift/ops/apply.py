"""Execute machine-readable plans against existing engines."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..compress_engine import COMPRESS_PRESETS
from ..converter import SUPPORTED_OUTPUT_FORMATS
from ..core.defaults import DEFAULT_COMPRESS_PRESET, DEFAULT_CONVERT_QUALITY
from ..core.errors import OperationPolicyError, OutputCollisionError
from ..core.files import (
    conversion_output_name,
    derivative_output_name,
    plan_output_path,
    validate_unique_output_paths,
)
from ..strip_engine import resolve_strip_mode
from ..video_engine import (
    CONTAINER_DEFAULT_CODEC,
    VIDEO_CODECS,
    VIDEO_COMPRESS_PRESETS,
    VideoResult,
    validate_container_codec,
)
from . import compress as compress_ops
from . import convert as convert_ops
from . import strip as strip_ops
from . import video as video_ops

_VIDEO_CONVERT_CONTAINERS = {"mp4", "webm", "mkv", "mov"}


@dataclass
class AppliedStep:
    """One applied plan step."""

    input_path: str
    command: str
    arguments: dict[str, Any]
    output_path: str = ""
    success: bool = False
    skipped: bool = False
    dry_run: bool = False
    error: str = ""
    detail: str = ""


@dataclass
class ApplyResult:
    """Batch apply summary."""

    steps: list[AppliedStep] = field(default_factory=list)
    error: str = ""
    rejected: bool = False

    @property
    def ok(self) -> bool:
        if self.error:
            return False
        return all(step.success or step.skipped for step in self.steps)


@dataclass(frozen=True)
class _VideoPlan:
    audio_policy: str
    codec: str
    preset: str
    crf: int | None
    container: str
    output_name: str


def load_plan_document(raw: str) -> list[dict[str, Any]]:
    """Normalize optimize payloads or explicit plan lists into executable steps."""
    document = json.loads(raw)
    if isinstance(document, list):
        return [_normalize_step(item) for item in document]
    if not isinstance(document, dict):
        raise ValueError("plan_must_be_object_or_array")

    if "results" in document:
        results = document["results"]
        if not isinstance(results, list):
            raise ValueError("invalid_optimize_result")
        steps: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            plan = item.get("plan")
            if not isinstance(plan, dict) or not plan.get("command"):
                # A failed optimize entry carries no plan — since schema 1.1
                # that is an *empty* plan object, not a missing key — so skip
                # it and let the healthy items in a mixed batch still apply,
                # rather than rejecting the whole document.
                continue
            steps.append(
                {
                    "input": item.get("input") or item.get("input_path"),
                    "command": plan.get("command"),
                    "arguments": plan.get("arguments", {}),
                }
            )
        return [_normalize_step(step) for step in steps]

    if "plans" in document:
        plans = document["plans"]
        if not isinstance(plans, list):
            raise ValueError("invalid_plans_list")
        return [_normalize_step(item) for item in plans]

    if "command" in document:
        return [_normalize_step(document)]

    raise ValueError("unrecognized_plan_document")


def _normalize_step(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        # Guard bare-list payloads like ``[1]`` so a bad step becomes a stable
        # ValueError (JSON error document) instead of an uncaught TypeError.
        raise ValueError("invalid_plan_step")
    input_path = item.get("input") or item.get("input_path")
    command = item.get("command")
    arguments = item.get("arguments", {})
    if not input_path or not isinstance(input_path, str):
        raise ValueError("missing_input")
    if not command or not isinstance(command, str):
        raise ValueError("missing_command")
    if not isinstance(arguments, dict):
        raise ValueError("invalid_arguments")
    return {"input": input_path, "command": command, "arguments": dict(arguments)}


def apply_plans(
    steps: list[dict[str, Any]],
    *,
    output_dir: str | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> ApplyResult:
    """Validate a complete batch before executing any step.

    The preflight uses the exact command validators and output planner used by
    dry-run. Destination collisions (including an output that aliases another
    step's input) are checked for the whole batch before the first write.
    """
    result = ApplyResult()
    claimed: set[str] = set()
    for step in steps:
        applied = _apply_one(
            input_path=step["input"],
            command=step["command"],
            arguments=step["arguments"],
            output_dir=output_dir,
            overwrite=overwrite,
            dry_run=True,
            claimed=claimed,
        )
        result.steps.append(applied)

    if any(not (step.success or step.skipped) for step in result.steps):
        result.error = "plan_validation_failed"
        result.rejected = True
        return result

    planned_tasks = [
        (step.input_path, step.output_path)
        for step in result.steps
        if step.output_path and not step.skipped
    ]
    try:
        validate_unique_output_paths(planned_tasks)
    except OutputCollisionError as error:
        result.error = error.code
        result.rejected = True
        if result.steps:
            result.steps[-1].success = False
            result.steps[-1].error = error.code
            result.steps[-1].detail = str(error)
        return result

    if dry_run:
        return result

    executed = ApplyResult()
    claimed = set()
    for step in steps:
        applied = _apply_one(
            input_path=step["input"],
            command=step["command"],
            arguments=step["arguments"],
            output_dir=output_dir,
            overwrite=overwrite,
            dry_run=False,
            claimed=claimed,
        )
        executed.steps.append(applied)
    return executed


def _apply_one(
    *,
    input_path: str,
    command: str,
    arguments: dict[str, Any],
    output_dir: str | None,
    overwrite: bool,
    dry_run: bool,
    claimed: set[str],
) -> AppliedStep:
    applied = AppliedStep(
        input_path=input_path,
        command=command,
        arguments=dict(arguments),
        dry_run=dry_run,
    )
    source = Path(input_path)
    if not source.is_file():
        applied.error = "input_not_found"
        return applied

    try:
        if command == "convert":
            return _apply_convert(
                applied,
                output_dir=output_dir,
                overwrite=overwrite,
                dry_run=dry_run,
                claimed=claimed,
            )
        if command == "compress":
            return _apply_compress(
                applied,
                output_dir=output_dir,
                overwrite=overwrite,
                dry_run=dry_run,
                claimed=claimed,
            )
        if command == "strip":
            return _apply_strip(
                applied,
                output_dir=output_dir,
                overwrite=overwrite,
                dry_run=dry_run,
                claimed=claimed,
            )
        if command == "keep":
            # An optimize verdict of "already efficient": succeed explicitly
            # without touching the file so batch counts stay meaningful.
            applied.skipped = True
            applied.success = True
            applied.detail = "plan_keep"
            return applied
        if command in ("video.convert", "video.compress"):
            return _apply_video(
                applied,
                output_dir=output_dir,
                overwrite=overwrite,
                dry_run=dry_run,
                claimed=claimed,
            )
        applied.error = "unsupported_plan_command"
        return applied
    except OperationPolicyError as error:
        applied.error = error.code
        applied.detail = str(error)
        return applied
    except Exception as error:
        applied.error = "apply_failed"
        applied.detail = str(error)
        return applied


def _output_for(
    input_path: str,
    *,
    output_dir: str | None,
    output_name: str,
    overwrite: bool,
    claimed: set[str],
) -> tuple[str, bool]:
    target = plan_output_path(
        input_path,
        output_name,
        output_dir=output_dir,
        flatten=False,
        source_paths=[input_path],
    )
    # A key already in ``claimed`` means an earlier step this run targeted the
    # same destination. Check that before the existing-output skip, otherwise
    # the first step's fresh write makes the second look like an idempotent
    # skip and the collision is masked.
    # ``claimed`` only catches duplicate destinations within this planning
    # pass; the shared full-batch validator below also checks input aliases and
    # filesystem-specific canonical identity.
    key = str(Path(target).resolve(strict=False))
    if key in claimed:
        raise OutputCollisionError(f"multiple plan steps map to the same output: {target}")
    if Path(target).exists() and not overwrite:
        return target, True
    claimed.add(key)
    return target, False


def _apply_convert(
    applied: AppliedStep,
    *,
    output_dir: str | None,
    overwrite: bool,
    dry_run: bool,
    claimed: set[str],
) -> AppliedStep:
    target_format = str(
        applied.arguments.get("to") or applied.arguments.get("format") or ""
    ).lower()
    if not target_format:
        applied.error = "missing_target_format"
        return applied
    if target_format == "jpeg":
        target_format = "jpg"
    if target_format not in SUPPORTED_OUTPUT_FORMATS:
        applied.error = "unsupported_target_format"
        return applied
    quality = str(applied.arguments.get("quality") or DEFAULT_CONVERT_QUALITY)
    if quality not in {"max", "high", "medium", "low", "web"}:
        applied.error = "unsupported_quality"
        return applied
    color_space = str(applied.arguments.get("color_space") or "preserve").lower()
    if color_space not in {"preserve", "srgb"}:
        applied.error = "unsupported_color_space"
        return applied
    output_path, skipped = _output_for(
        applied.input_path,
        output_dir=output_dir,
        output_name=conversion_output_name(applied.input_path, target_format),
        overwrite=overwrite,
        claimed=claimed,
    )
    applied.output_path = output_path
    if skipped:
        applied.skipped = True
        applied.success = True
        applied.detail = "existing_output_skipped"
        return applied
    if dry_run:
        applied.success = True
        return applied
    result = convert_ops.convert_one(
        applied.input_path,
        output_path,
        {"quality": quality, "overwrite": overwrite, "color_space": color_space},
    )
    applied.success = bool(result.success)
    applied.error = result.error or ""
    return applied


def _apply_compress(
    applied: AppliedStep,
    *,
    output_dir: str | None,
    overwrite: bool,
    dry_run: bool,
    claimed: set[str],
) -> AppliedStep:
    preset = str(applied.arguments.get("preset") or DEFAULT_COMPRESS_PRESET)
    if preset not in COMPRESS_PRESETS:
        applied.error = "unsupported_compress_preset"
        return applied
    quality_raw = applied.arguments.get("quality")
    quality: int | None
    try:
        quality = None if quality_raw is None else int(quality_raw)
    except (TypeError, ValueError):
        applied.error = "invalid_quality"
        return applied
    if quality is not None and not 1 <= quality <= 100:
        applied.error = "invalid_quality"
        return applied
    output_path, skipped = _output_for(
        applied.input_path,
        output_dir=output_dir,
        output_name=derivative_output_name(applied.input_path, "_compressed"),
        overwrite=overwrite,
        claimed=claimed,
    )
    applied.output_path = output_path
    if skipped:
        applied.skipped = True
        applied.success = True
        applied.detail = "existing_output_skipped"
        return applied
    if dry_run:
        applied.success = True
        return applied
    result = compress_ops.compress_one(
        applied.input_path,
        output_path,
        quality=quality,
        preset=preset,
        target_size=None,
        max_size=None,
        overwrite=overwrite,
    )
    applied.success = bool(result.success)
    applied.error = result.error or ""
    return applied


def _apply_video(
    applied: AppliedStep,
    *,
    output_dir: str | None,
    overwrite: bool,
    dry_run: bool,
    claimed: set[str],
) -> AppliedStep:
    """Execute one video.convert / video.compress plan step.

    Argument validation and output planning stay pure so ``--dry-run``
    verifies a plan (names, collisions, vocabulary) on hosts without ffmpeg;
    only real execution requires the optional dependency.
    """
    try:
        plan = _validated_video_plan(applied)
    except ValueError as error:
        applied.error = str(error)
        return applied

    output_path, skipped = _output_for(
        applied.input_path,
        output_dir=output_dir,
        output_name=plan.output_name,
        overwrite=overwrite,
        claimed=claimed,
    )
    applied.output_path = output_path
    if skipped:
        applied.skipped = True
        applied.success = True
        applied.detail = "existing_output_skipped"
        return applied
    if dry_run:
        applied.success = True
        return applied
    if not video_ops.available():
        applied.error = "ffmpeg_missing"
        return applied
    result = _execute_video_plan(applied, plan, output_path, overwrite=overwrite)
    applied.success = bool(result.success)
    applied.error = result.error or ""
    applied.detail = applied.detail or result.detail
    return applied


def _validated_video_plan(applied: AppliedStep) -> _VideoPlan:
    arguments = applied.arguments
    audio_policy = str(arguments.get("audio_policy") or "compatible").lower()
    if audio_policy not in {"preserve", "compatible", "compact"}:
        raise ValueError(f"unsupported_audio_policy:{audio_policy}")
    codec = str(arguments.get("codec") or "")
    preset = str(arguments.get("preset") or "web")
    crf_raw = arguments.get("crf")
    try:
        crf = int(crf_raw) if crf_raw is not None else None
    except (TypeError, ValueError) as error:
        raise ValueError("invalid_crf") from error
    if crf is not None and not 0 <= crf <= 63:
        raise ValueError("invalid_crf")

    if applied.command == "video.convert":
        container = str(arguments.get("to") or "").lower().lstrip(".")
        if container not in _VIDEO_CONVERT_CONTAINERS:
            raise ValueError(f"unsupported_target_container:{container or '?'}")
        validate_container_codec(
            codec=codec or CONTAINER_DEFAULT_CODEC[container], container=container
        )
        output_name = conversion_output_name(applied.input_path, container)
    else:
        codec = codec or "h264"
        if preset not in VIDEO_COMPRESS_PRESETS:
            raise ValueError(f"unsupported_video_preset:{preset}")
        if codec not in VIDEO_CODECS:
            raise ValueError(f"unsupported_video_codec:{codec}")
        container = VIDEO_CODECS[codec][1]
        output_name = f"{Path(applied.input_path).stem}_compressed.{container}"
    return _VideoPlan(audio_policy, codec, preset, crf, container, output_name)


def _execute_video_plan(
    applied: AppliedStep, plan: _VideoPlan, output_path: str, *, overwrite: bool
) -> VideoResult:
    if applied.command == "video.convert":
        return video_ops.convert_one(
            applied.input_path,
            output_path,
            container=plan.container,
            codec=plan.codec or None,
            overwrite=overwrite,
            audio_policy=plan.audio_policy,
        )
    return video_ops.compress_one(
        applied.input_path,
        output_path,
        preset=plan.preset,
        codec=plan.codec,
        crf=plan.crf,
        overwrite=overwrite,
        audio_policy=plan.audio_policy,
    )


def _apply_strip(
    applied: AppliedStep,
    *,
    output_dir: str | None,
    overwrite: bool,
    dry_run: bool,
    claimed: set[str],
) -> AppliedStep:
    mode = str(applied.arguments.get("mode") or "privacy")
    try:
        strip_exif, strip_gps, strip_device, strip_personal, strip_time = resolve_strip_mode(mode)
    except ValueError:
        applied.error = "invalid_strip_mode"
        return applied
    output_path, skipped = _output_for(
        applied.input_path,
        output_dir=output_dir,
        output_name=derivative_output_name(applied.input_path, "_clean"),
        overwrite=overwrite,
        claimed=claimed,
    )
    applied.output_path = output_path
    if skipped:
        applied.skipped = True
        applied.success = True
        applied.detail = "existing_output_skipped"
        return applied
    if dry_run:
        applied.success = True
        return applied
    result = strip_ops.strip_one(
        applied.input_path,
        output_path,
        strip_exif=strip_exif or bool(applied.arguments.get("strip_exif", False)),
        strip_gps=strip_gps or bool(applied.arguments.get("strip_gps", False)),
        strip_icc=bool(applied.arguments.get("strip_icc", False)),
        strip_device=strip_device or bool(applied.arguments.get("strip_device", False)),
        strip_personal=strip_personal or bool(applied.arguments.get("strip_personal", False)),
        strip_time=strip_time or bool(applied.arguments.get("strip_time", False)),
        keep_orientation=bool(applied.arguments.get("keep_orientation", True)),
        overwrite=overwrite,
    )
    applied.success = bool(result.success)
    applied.error = result.error or ""
    return applied
