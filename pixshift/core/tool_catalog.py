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
        "input_summary": "paths; --mode privacy|custom; -r; --json",
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
        "description": "Recommend output format and emit executable plans.",
        "when_to_use": "Decide convert/compress next steps for agents.",
        "input_summary": "paths; -r; --json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
    },
    {
        "name": "watch",
        "description": "Watch a directory and auto-convert new images.",
        "when_to_use": "Continuous ingest folders; use --once for agents.",
        "input_summary": "dir; -t format; --once; --json",
        "annotations": _ann(read_only=False, destructive=False, idempotent=True),
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
        "name": "pdf.info",
        "description": "Show PDF details.",
        "when_to_use": "Inspect page count and metadata.",
        "input_summary": "pdf; --json",
        "annotations": _ann(read_only=True, destructive=False, idempotent=True),
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
        "description": "Execute machine plans from optimize or explicit plan files.",
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
