"""Stable tool catalog for agents and optional MCP adapters."""

from __future__ import annotations

from typing import Any, TypedDict


class ToolAnnotations(TypedDict):
    """MCP-aligned side-effect hints for a tool."""

    readOnlyHint: bool
    destructiveHint: bool
    idempotentHint: bool
    openWorldHint: bool


class ToolEntry(TypedDict):
    """One discoverable PixShift tool."""

    name: str
    description: str
    when_to_use: str
    input_summary: str
    annotations: ToolAnnotations


def _ann(
    *,
    read_only: bool,
    destructive: bool,
    idempotent: bool,
) -> ToolAnnotations:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": idempotent,
        "openWorldHint": False,
    }


TOOL_CATALOG: list[ToolEntry] = [
    {
        "name": "convert",
        "description": "Convert images to another format with optional resize.",
        "when_to_use": "Need a different format or bounded dimensions.",
        "input_summary": "paths; -t format; optional --resize/--max-size; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "compress",
        "description": "Compress images in the same format.",
        "when_to_use": "Reduce file size without changing container format.",
        "input_summary": "paths; -p preset or --quality; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "strip",
        "description": "Remove metadata for privacy cleanup.",
        "when_to_use": "Remove EXIF/GPS/device/personal fields before sharing.",
        "input_summary": "paths; --mode privacy|all|gps|device|personal|time; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "dedup",
        "description": "Find similar or byte-identical duplicates.",
        "when_to_use": "Inventory duplicates; delete only with --delete after dry-run.",
        "input_summary": "paths; -r; optional --delete --dry-run --yes; --json",
        "annotations": _ann(read_only=False, destructive=True, idempotent=False),
    },
    {
        "name": "compare",
        "description": "Compare two images with SSIM/PSNR/MSE.",
        "when_to_use": "Verify quality after a transform.",
        "input_summary": "image_a image_b; --json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "crop",
        "description": "Crop images by box, aspect, or auto-trim.",
        "when_to_use": "Need framed or trimmed still images.",
        "input_summary": "paths; --crop/--aspect/--trim; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "resize",
        "description": "Resize images keeping their format (WxH, percent, or bounded).",
        "when_to_use": "Change dimensions without changing container format.",
        "input_summary": "paths; --size WxH | --percent P | --max-size N; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "rotate",
        "description": "Rotate clockwise (90/180/270) or mirror still images.",
        "when_to_use": "Fix orientation or mirror images in batch.",
        "input_summary": "paths; --degrees 90|180|270; --flip horizontal|vertical; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "watermark",
        "description": "Add text or image watermarks.",
        "when_to_use": "Brand or mark ownership on still images.",
        "input_summary": "text|image subcommand; paths; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "montage",
        "description": "Build an image grid montage.",
        "when_to_use": "Compose a contact sheet from many images.",
        "input_summary": "paths; -o output; --cols; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "optimize",
        "description": "Recommend output format for images and videos and emit executable plans.",
        "when_to_use": "Decide convert/compress/keep next steps for agents.",
        "input_summary": "paths; -r; --json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "info",
        "description": "Inspect image metadata and properties.",
        "when_to_use": "Read format, size, alpha, frames before acting.",
        "input_summary": "files; optional --exif; --json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "formats",
        "description": "Show supported formats and quality presets.",
        "when_to_use": "Discover runtime-available codecs.",
        "input_summary": "--json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "doctor",
        "description": "Validate runtime dependencies.",
        "when_to_use": "Diagnose missing optional codecs before batch work.",
        "input_summary": "--json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "pdf.merge",
        "description": "Merge images into a PDF.",
        "when_to_use": "Build a PDF album from still images.",
        "input_summary": "paths; -o output.pdf; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "pdf.extract",
        "description": "Extract PDF pages as images.",
        "when_to_use": "Rasterize selected pages for review or editing.",
        "input_summary": "pdf; -o dir; optional page range; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "pdf.compress",
        "description": "Compress a PDF.",
        "when_to_use": "Shrink PDF size for delivery.",
        "input_summary": "pdf; -o output; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "pdf.concat",
        "description": "Concatenate multiple PDFs.",
        "when_to_use": "Join PDF documents in order.",
        "input_summary": "pdfs; -o output; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "pdf.split",
        "description": "Split a PDF into per-page documents or one sub-range document.",
        "when_to_use": "Extract pages as standalone PDFs.",
        "input_summary": "pdf; -o dir; optional --pages '1-5,8'; --single; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "pdf.info",
        "description": "Show PDF details.",
        "when_to_use": "Inspect page count and metadata.",
        "input_summary": "pdf; optional --pages; --json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "video.info",
        "description": "Inspect video container, codecs, duration, and frame properties (needs ffmpeg).",
        "when_to_use": "Read duration, resolution, codec, fps before trim or convert.",
        "input_summary": "files; --json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "video.convert",
        "description": "Transcode video to another container/codec (needs ffmpeg).",
        "when_to_use": "Change format for playback compatibility (mp4/webm/mkv/mov).",
        "input_summary": "paths; -t mp4|webm|mkv|mov; --codec; --hwaccel; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "video.compress",
        "description": "Reduce video size with CRF presets (needs ffmpeg).",
        "when_to_use": "Shrink a clip for upload or sharing.",
        "input_summary": "paths; -p web|archive|tiny; --codec h264|h265|vp9|av1; --hwaccel; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "video.trim",
        "description": "Cut a time range into a new file, stream-copy when possible (needs ffmpeg).",
        "when_to_use": "Extract a clip by start/end or start/duration; source is untouched.",
        "input_summary": "video; --start TS; --end TS | --duration SEC; -o out; --reencode; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "video.thumbnail",
        "description": "Extract a still frame as an image (needs ffmpeg).",
        "when_to_use": "Grab a poster frame at a timestamp or percentage.",
        "input_summary": "paths; --at TS|P%; -t jpg|png|webp; -o dir; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "video.extract-audio",
        "description": "Export the audio track (needs ffmpeg).",
        "when_to_use": "Pull audio to mp3/aac/opus/flac/wav for transcription or reuse.",
        "input_summary": "paths; -t mp3|aac|opus|flac|wav; -o dir; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "video.gif",
        "description": "Convert a video clip to an animated GIF (needs ffmpeg).",
        "when_to_use": "Make a shareable GIF from a short clip (palettegen two-pass).",
        "input_summary": "video; --start TS; --duration SEC; --fps N; --width N; -o out; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "tools",
        "description": "List the agent-facing tool catalog.",
        "when_to_use": "Discover available commands and side-effect annotations.",
        "input_summary": "--json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "apply",
        "description": "Execute machine plans (image and video.* steps) from optimize or files.",
        "when_to_use": "Run a previously emitted plan without re-parsing prose.",
        "input_summary": "--plan file|- ; optional --output; --dry-run; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "prep",
        "description": "Prepare delivery-ready assets (resize, convert, privacy strip).",
        "when_to_use": "One-shot package images for upload or agent handoff.",
        "input_summary": "paths; -o out; --max-size; -t format; -r; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
    },
    {
        "name": "manifest",
        "description": "Build a directory inventory with hashes and properties.",
        "when_to_use": "First pass before filter, dedup, or batch transforms.",
        "input_summary": "paths; -r; --json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "hash",
        "description": "Compute content hashes for files.",
        "when_to_use": "Audit what changed after a transform.",
        "input_summary": "paths; -r; --algorithm sha256; --json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
]


def catalog_payload() -> dict[str, Any]:
    """Return the machine catalog envelope without schema_version (presenter adds it)."""
    return {
        "command": "tools",
        "ok": True,
        "total": len(TOOL_CATALOG),
        "tools": list(TOOL_CATALOG),
    }
