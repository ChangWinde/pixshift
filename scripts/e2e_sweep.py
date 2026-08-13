"""Large-scale end-to-end sweep across the whole CLI surface.

Generates a seeded synthetic media corpus (formats, color modes, animations,
CMYK, unicode/space names, corrupt files), drives the real CLI through every
pillar in both output channels, and enforces the machine contract on every
JSON payload: schema validation, the exit-code contract (0/1/2), failure-array
shapes, idempotent reruns, and filesystem-neutral usage rejections.

Usage:
    uv run python scripts/e2e_sweep.py --images 200 --seed 7
    uv run python scripts/e2e_sweep.py --keep   # keep the corpus for autopsy

Exit code 0 means the sweep found no contract violation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import jsonschema
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO / "docs" / "schemas" / "v1"
SCHEMA_VERSION = "1.1"

COMMAND_SCHEMAS = {
    "tools": "tools.json",
    "optimize": "optimize.json",
    "apply": "apply.json",
    "prep": "prep.json",
    "manifest": "manifest.json",
    "hash": "hash.json",
}


class Sweep:
    """Collects invocation stats and contract violations."""

    def __init__(self) -> None:
        self.invocations = 0
        self.payloads = 0
        self.violations: list[str] = []
        self._schemas: dict[str, dict[str, Any]] = {}

    def violation(self, phase: str, message: str) -> None:
        self.violations.append(f"[{phase}] {message}")

    def schema(self, name: str) -> dict[str, Any]:
        if name not in self._schemas:
            self._schemas[name] = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        return self._schemas[name]

    def run(self, *args: str) -> tuple[int, str]:
        """Run one CLI invocation; returns (exit_code, stdout)."""
        self.invocations += 1
        completed = subprocess.run(
            [sys.executable, "-m", "pixshift", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode not in (0, 1, 2):
            self.violation("global", f"exit code {completed.returncode} outside contract: {args}")
        return completed.returncode, completed.stdout

    def run_json(
        self,
        phase: str,
        *args: str,
        expect_exit: int | None = None,
        stdin: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Run with --json and enforce the payload contract."""
        self.invocations += 1
        completed = subprocess.run(
            [sys.executable, "-m", "pixshift", *args, "--json"],
            capture_output=True,
            text=True,
            input=stdin,
            check=False,
        )
        code = completed.returncode
        if code not in (0, 1, 2):
            self.violation(phase, f"exit code {code} outside contract: {args}")
        try:
            payload: dict[str, Any] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            self.violation(phase, f"stdout is not JSON for {args}: {completed.stdout[:120]!r}")
            return code, {}
        self.payloads += 1
        if payload.get("schema_version") != SCHEMA_VERSION:
            self.violation(phase, f"schema_version {payload.get('schema_version')!r} != 1.1")
        try:
            jsonschema.validate(payload, self.schema("envelope.json"))
        except jsonschema.ValidationError as error:
            self.violation(phase, f"envelope violation for {args}: {error.message}")
        command = str(payload.get("command", ""))
        schema_name = COMMAND_SCHEMAS.get(command)
        if schema_name and "error" not in payload:
            try:
                jsonschema.validate(payload, self.schema(schema_name))
            except jsonschema.ValidationError as error:
                self.violation(phase, f"{schema_name} violation: {error.message}")
        ok = payload.get("ok")
        if ok is True and code != 0:
            self.violation(phase, f"ok=true but exit {code}: {args}")
        if ok is False and code == 0:
            self.violation(phase, f"ok=false but exit 0: {args}")
        if expect_exit is not None and code != expect_exit:
            self.violation(phase, f"expected exit {expect_exit}, got {code}: {args}")
        return code, payload


def _noise_image(rng: random.Random, size: tuple[int, int], mode: str = "RGB") -> Image.Image:
    img = Image.new(mode, size)
    band_count = len(img.getbands())
    pixels = [
        tuple(rng.randrange(256) for _ in range(band_count))
        if band_count > 1
        else rng.randrange(256)
        for _ in range(size[0] * size[1])
    ]
    img.putdata(pixels)
    return img


def build_corpus(root: Path, rng: random.Random, image_budget: int) -> dict[str, list[Path]]:
    """Create the seeded corpus; returns paths grouped by intent."""
    groups: dict[str, list[Path]] = {
        "photos": [],
        "graphics": [],
        "anims": [],
        "cmyk": [],
        "broken": [],
    }

    photos = root / "photos" / "相册 2026"
    photos.mkdir(parents=True)
    photo_formats = [
        ("jpg", "JPEG"),
        ("png", "PNG"),
        ("webp", "WEBP"),
        ("bmp", "BMP"),
        ("tiff", "TIFF"),
    ]
    photo_count = max(30, image_budget - 60)
    for index in range(photo_count):
        ext, fmt = photo_formats[index % len(photo_formats)]
        name = f"照 片_{index:03d}.{ext}" if index % 7 == 0 else f"shot_{index:03d}.{ext}"
        path = photos / name
        size = (rng.randrange(16, 320), rng.randrange(16, 320))
        img = _noise_image(rng, size)
        params: dict[str, Any] = {"format": fmt}
        if fmt == "JPEG":
            params["quality"] = rng.randrange(40, 96)
            if index % 3 == 0:
                tags = Image.Exif()
                tags[271] = "SweepCam"
                tags[272] = f"Model {index}"
                params["exif"] = tags.tobytes()
        img.save(str(path), **params)
        groups["photos"].append(path)

    graphics = root / "graphics"
    graphics.mkdir()
    for index in range(24):
        path = graphics / f"icon_{index:02d}.png"
        mode = ("RGBA", "P", "LA", "L")[index % 4]
        img = _noise_image(rng, (rng.randrange(8, 64), rng.randrange(8, 64)), "RGBA")
        if mode != "RGBA":
            img = img.convert(mode)
        img.save(str(path))
        groups["graphics"].append(path)

    # Extreme shapes and depths: 1x1, ultra-wide, 16-bit, oriented EXIF,
    # transparent palette GIF. These live with the photos so every batch
    # phase sweeps them too.
    extremes = root / "photos" / "extremes"
    extremes.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1, 1), "red").save(str(extremes / "single_pixel.png"))
    _noise_image(rng, (1600, 2)).save(str(extremes / "ultra_wide.jpg"), format="JPEG")
    _noise_image(rng, (2, 1600)).save(str(extremes / "ultra_tall.png"))
    Image.new("I;16", (40, 40), 40000).save(str(extremes / "deep_16bit.png"))
    for orientation in (3, 6, 8):
        oriented = _noise_image(rng, (60, 40))
        tags = Image.Exif()
        tags[274] = orientation
        oriented.save(
            str(extremes / f"oriented_{orientation}.jpg"), format="JPEG", exif=tags.tobytes()
        )
    palette = Image.new("P", (32, 32))
    palette.putpalette([value % 256 for value in range(768)])
    palette.info["transparency"] = 0
    palette.save(str(extremes / "palette_alpha.gif"), transparency=0)
    for path in sorted(extremes.iterdir()):
        groups["photos"].append(path)

    anims = root / "anims"
    anims.mkdir()
    for index in range(12):
        frames = [_noise_image(rng, (24, 24)) for _ in range(rng.randrange(2, 6))]
        durations = [rng.randrange(40, 400) for _ in frames]
        if index % 3 == 0:
            path = anims / f"anim_{index:02d}.gif"
            frames[0].save(
                str(path),
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=rng.randrange(0, 4),
                disposal=2,
            )
        elif index % 3 == 1:
            path = anims / f"anim_{index:02d}.png"
            rgba = [frame.convert("RGBA") for frame in frames]
            rgba[0].save(
                str(path), save_all=True, append_images=rgba[1:], duration=durations, loop=1
            )
        else:
            path = anims / f"anim_{index:02d}.webp"
            frames[0].save(
                str(path), save_all=True, append_images=frames[1:], duration=durations, loop=0
            )
        groups["anims"].append(path)

    cmyk = root / "cmyk"
    cmyk.mkdir()
    for index in range(6):
        path = cmyk / f"press_{index}.jpg"
        _noise_image(rng, (60, 40)).convert("CMYK").save(str(path), format="JPEG")
        groups["cmyk"].append(path)

    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        for index in range(3):
            path = root / "photos" / f"phone_{index}.heic"
            _noise_image(rng, (80, 60)).save(str(path), format="HEIF", quality=70)
            groups["photos"].append(path)
    except Exception:
        pass  # HEIF encoder unavailable in this environment; skip the format

    broken = root / "broken"
    broken.mkdir()
    text_png = broken / "not_an_image.png"
    text_png.write_bytes(b"this is not a png at all")
    truncated = broken / "truncated.jpg"
    buffer = groups["photos"][0].read_bytes() if groups["photos"][0].suffix == ".jpg" else b""
    if not buffer:
        sample = Image.new("RGB", (64, 64), "red")
        import io as _io

        stream = _io.BytesIO()
        sample.save(stream, format="JPEG")
        buffer = stream.getvalue()
    truncated.write_bytes(buffer[: max(24, len(buffer) // 3)])
    empty = broken / "empty.png"
    empty.write_bytes(b"")
    groups["broken"] = [text_png, truncated, empty]

    return groups


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def snapshot(root: Path) -> set[str]:
    return {str(p) for p in root.rglob("*") if p.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=int, default=200, help="approximate corpus size")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--keep", action="store_true", help="keep the corpus directory")
    parser.add_argument("--root", default=None, help="corpus root (default: temp dir)")
    options = parser.parse_args()

    rng = random.Random(options.seed)
    root = Path(options.root) if options.root else Path(tempfile.mkdtemp(prefix="pixshift-sweep-"))
    root.mkdir(parents=True, exist_ok=True)
    sweep = Sweep()
    started = time.time()

    print(f"corpus root: {root} (seed={options.seed}, budget={options.images})")
    groups = build_corpus(root, rng, options.images)
    total_files = sum(len(paths) for paths in groups.values())
    print(f"corpus built: {total_files} files")

    # -------- phase 1: read-only discovery --------
    sweep.run_json("doctor", "doctor")
    sweep.run_json("formats", "formats", expect_exit=0)
    code, tools = sweep.run_json("tools", "tools", expect_exit=0)
    catalog_names = {entry["name"] for entry in tools.get("tools", [])}
    for required in ("convert", "optimize", "apply", "video.compress", "pdf.merge"):
        if required not in catalog_names:
            sweep.violation("tools", f"catalog is missing {required}")

    code, manifest = sweep.run_json("manifest", "manifest", str(root), "-r", expect_exit=1)
    entries = {item["path"]: item for item in manifest.get("files", [])}
    if len(entries) < total_files - len(groups["broken"]):
        sweep.violation("manifest", f"only {len(entries)} entries for {total_files} files")
    # hash digests bytes without decoding, so corrupt media still hash fine.
    code, hashes = sweep.run_json("hash", "hash", str(root), "-r", expect_exit=0)
    digest_by_path = {
        item["path"]: item["digest"] for item in hashes.get("files", []) if not item.get("error")
    }
    for sample_path in rng.sample(sorted(digest_by_path), k=min(6, len(digest_by_path))):
        if digest_by_path[sample_path] != sha256(Path(sample_path)):
            sweep.violation("hash", f"digest mismatch for {sample_path}")

    # -------- phase 2: plan loop at scale --------
    code, optimized = sweep.run_json("optimize", "optimize", str(root), "-r", expect_exit=1)
    results = optimized.get("results", [])
    if len(results) < total_files - len(groups["broken"]) - 1:
        sweep.violation("optimize", f"only {len(results)} analyses for {total_files} files")
    animation_plans = [r for r in results if r.get("image_type") == "animation"]
    if len(animation_plans) < len(groups["anims"]) // 2:
        sweep.violation("optimize", "animated inputs were not classified as animations")

    apply_out = root / "_out" / "apply"
    code, preview = sweep.run_json(
        "apply",
        "apply",
        "--plan",
        "-",
        "--dry-run",
        "-o",
        str(apply_out),
        stdin=json.dumps(optimized),
        expect_exit=0,
    )
    if preview.get("total", 0) == 0:
        sweep.violation("apply", "dry-run saw an empty plan")
    if any(step["ok"] is False for step in preview.get("steps", [])):
        sweep.violation("apply", "dry-run rejected steps from optimize output")

    code, applied = sweep.run_json(
        "apply",
        "apply",
        "--plan",
        "-",
        "-o",
        str(apply_out),
        stdin=json.dumps(optimized),
        expect_exit=0,
    )
    for step in applied.get("steps", []):
        declared = step["ok"] and not step["skipped"] and step["output"]
        if declared and not Path(step["output"]).is_file():
            sweep.violation("apply", f"declared output missing: {step['output']}")
    code, reapplied = sweep.run_json(
        "apply",
        "apply",
        "--plan",
        "-",
        "-o",
        str(apply_out),
        stdin=json.dumps(optimized),
        expect_exit=0,
    )
    if reapplied.get("applied", -1) != 0:
        sweep.violation("apply", f"rerun applied {reapplied.get('applied')} steps; expected 0")

    # -------- phase 3: convert at scale + idempotency --------
    convert_out = root / "_out" / "webp"
    code, converted = sweep.run_json(
        "convert",
        "convert",
        str(root / "photos"),
        str(root / "anims"),
        str(root / "broken"),
        "-t",
        "webp",
        "-o",
        str(convert_out),
        "-r",
        expect_exit=1,
    )
    if converted.get("total") != converted.get("success", 0) + converted.get(
        "failed", 0
    ) + converted.get("skipped", 0):
        sweep.violation("convert", "total != success+failed+skipped")
    for entry in converted.get("errors", []):
        if set(entry) != {"input", "output", "error"}:
            sweep.violation("convert", f"error entry shape: {entry}")
        if "broken" not in entry["input"]:
            sweep.violation("convert", f"unexpected failure outside broken/: {entry}")
    code, reconverted = sweep.run_json(
        "convert",
        "convert",
        str(root / "photos"),
        str(root / "anims"),
        str(root / "broken"),
        "-t",
        "webp",
        "-o",
        str(convert_out),
        "-r",
        expect_exit=1,
    )
    if reconverted.get("success", -1) != 0:
        sweep.violation("convert", f"rerun re-encoded {reconverted.get('success')} files")
    sample_anim = groups["anims"][0]
    anim_out = next(convert_out.rglob(f"{sample_anim.stem}.webp"), None)
    if anim_out is None:
        sweep.violation("convert", f"no converted output found for {sample_anim.name}")
    else:
        with Image.open(anim_out) as check:
            if getattr(check, "n_frames", 1) < 2:
                sweep.violation("convert", f"animation flattened: {anim_out}")

    # -------- phase 4: same-format batch surfaces --------
    photos_dir = root / "photos"
    for phase, args in (
        (
            "resize",
            [
                "resize",
                str(photos_dir),
                "--percent",
                "50",
                "-r",
                "-o",
                str(root / "_out" / "resized"),
            ],
        ),
        (
            "rotate",
            [
                "rotate",
                str(photos_dir),
                "--degrees",
                "90",
                "-r",
                "-o",
                str(root / "_out" / "rotated"),
            ],
        ),
        ("compress", ["compress", str(photos_dir), "-r", "-o", str(root / "_out" / "compressed")]),
        ("strip", ["strip", str(photos_dir), "-r", "-o", str(root / "_out" / "stripped")]),
        (
            "crop",
            [
                "crop",
                str(photos_dir),
                "--aspect",
                "1:1",
                "-r",
                "-o",
                str(root / "_out" / "cropped"),
            ],
        ),
    ):
        code, payload = sweep.run_json(phase, *args)
        if code != 0:
            sweep.violation(phase, f"batch over healthy photos failed: {payload.get('errors')}")

    wm_out = root / "_out" / "watermarked"
    sweep.run_json(
        "watermark",
        "watermark",
        "text",
        str(photos_dir),
        "--text",
        "sweep",
        "-r",
        "-o",
        str(wm_out),
        expect_exit=0,
    )
    montage_target = root / "_out" / "board.png"
    sweep.run_json(
        "montage",
        "montage",
        str(root / "graphics"),
        "-o",
        str(montage_target),
        "--cols",
        "4",
        expect_exit=0,
    )
    # compare requires equal dimensions; build a deliberate comparable pair.
    compare_dir = root / "_out" / "compare"
    compare_dir.mkdir(parents=True)
    base = _noise_image(rng, (96, 96))
    base.save(str(compare_dir / "a.png"))
    base.convert("RGB").save(str(compare_dir / "b.jpg"), quality=70)
    sweep.run_json(
        "compare",
        "compare",
        str(compare_dir / "a.png"),
        str(compare_dir / "b.jpg"),
        expect_exit=0,
    )

    # -------- phase 4.5: the size-budget idiom on images --------
    budget = 12 * 1024
    budget_out = root / "_out" / "budget"
    code, _fitted = sweep.run_json(
        "target-size",
        "compress",
        str(photos_dir),
        "-r",
        "--target-size",
        str(budget),
        "-o",
        str(budget_out),
    )
    if code not in (0, 1):
        sweep.violation("target-size", f"unexpected exit {code} for the image budget batch")
    for produced in budget_out.rglob("*"):
        if produced.is_file() and produced.stat().st_size > budget:
            sweep.violation("target-size", f"{produced.name} exceeds the {budget}B budget")

    # -------- phase 5: privacy check on strip output --------
    stripped_root = root / "_out" / "stripped"
    stripped_jpg = next(stripped_root.rglob("*.jpg"), None)
    if stripped_jpg is None:
        sweep.violation("strip", "no jpg outputs found to verify")
    else:
        with Image.open(stripped_jpg) as img:
            if img.getexif():
                sweep.violation("strip", f"EXIF survived strip: {stripped_jpg}")

    # -------- phase 6: dedup with revalidated deletion --------
    dupes = root / "dupes"
    dupes.mkdir()
    for index, source in enumerate(groups["photos"][:6]):
        blob = source.read_bytes()
        (dupes / f"a_{index}{source.suffix}").write_bytes(blob)
        (dupes / f"b_{index}{source.suffix}").write_bytes(blob)
    code, deduped = sweep.run_json("dedup", "dedup", str(dupes), "--threshold", "0", expect_exit=0)
    if deduped.get("duplicate_files", 0) < 6:
        sweep.violation("dedup", f"expected >=6 duplicates, saw {deduped.get('duplicate_files')}")
    sweep.run_json("dedup", "dedup", str(dupes), "--threshold", "0", "--delete", "--yes")
    remaining = list(dupes.iterdir())
    if len(remaining) != 6:
        sweep.violation("dedup", f"expected 6 survivors, saw {len(remaining)}")

    # -------- phase 7: the pdf pillar --------
    pdf_dir = root / "_out" / "pdf"
    pdf_dir.mkdir(parents=True)
    first_pdf = pdf_dir / "album-α.pdf"
    subset = [str(path) for path in groups["photos"][:8]]
    sweep.run_json("pdf", "pdf", "merge", *subset, "-o", str(first_pdf), expect_exit=0)
    code, info = sweep.run_json("pdf", "pdf", "info", str(first_pdf), expect_exit=0)
    if info.get("page_count") != len(subset):
        sweep.violation("pdf", f"merge page count {info.get('page_count')} != {len(subset)}")
    sweep.run_json(
        "pdf", "pdf", "extract", str(first_pdf), "-o", str(pdf_dir / "pages"), expect_exit=0
    )
    sweep.run_json(
        "pdf", "pdf", "split", str(first_pdf), "-o", str(pdf_dir / "parts"), expect_exit=0
    )
    compressed_pdf = pdf_dir / "album_small.pdf"
    sweep.run_json(
        "pdf", "pdf", "compress", str(first_pdf), "-o", str(compressed_pdf), expect_exit=0
    )
    second_pdf = pdf_dir / "album2.pdf"
    sweep.run_json(
        "pdf",
        "pdf",
        "merge",
        *[str(p) for p in groups["graphics"][:3]],
        "-o",
        str(second_pdf),
        expect_exit=0,
    )
    concat_pdf = pdf_dir / "joined.pdf"
    sweep.run_json(
        "pdf",
        "pdf",
        "concat",
        str(first_pdf),
        str(second_pdf),
        "-o",
        str(concat_pdf),
        expect_exit=0,
    )
    code, joined = sweep.run_json("pdf", "pdf", "info", str(concat_pdf), expect_exit=0)
    if joined.get("page_count") != len(subset) + 3:
        sweep.violation("pdf", f"concat page count {joined.get('page_count')}")

    fitted_pdf = pdf_dir / "fitted.pdf"
    pdf_goal = int(first_pdf.stat().st_size * 0.6)
    code, _pdf_fit = sweep.run_json(
        "target-size",
        "pdf",
        "compress",
        str(first_pdf),
        "--target-size",
        str(pdf_goal),
        "-o",
        str(fitted_pdf),
        expect_exit=0,
    )
    if fitted_pdf.is_file() and fitted_pdf.stat().st_size > pdf_goal:
        sweep.violation("target-size", "fitted pdf exceeds its byte budget")

    # -------- phase 8: prep + hash cross-check --------
    prep_out = root / "_out" / "prep"
    code, prepped = sweep.run_json(
        "prep",
        "prep",
        str(root / "graphics"),
        "-o",
        str(prep_out),
        "--max-size",
        "128",
        expect_exit=0,
    )
    for item in prepped.get("items", [])[:8]:
        if item.get("ok") and not item.get("skipped") and item.get("sha256"):
            actual = sha256(Path(item["output"]))
            if actual != item["sha256"]:
                sweep.violation("prep", f"manifest sha mismatch for {item['output']}")

    # -------- phase 9: usage rejections must be filesystem-neutral --------
    probe = str(groups["photos"][0])
    before = snapshot(root)
    for phase, args in (
        ("usage", ["convert", probe, "-t", "jpg", "--resize", "bogus"]),
        ("usage", ["convert", probe, "-t", "jpg", "--resize", "50%", "--max-size", "9"]),
        ("usage", ["compress", probe, "--quality", "80", "--target-size", "1MB"]),
        ("usage", ["resize", probe, "--percent", "50", "--max-size", "9"]),
        ("usage", ["rotate", probe]),
        ("usage", ["video", "thumbnail", probe, "--at", "150%"]),
    ):
        code, payload = sweep.run_json(phase, *args)
        if code != 2:
            # video commands legitimately gate on ffmpeg first.
            if payload.get("error") == "ffmpeg_missing":
                continue
            sweep.violation(phase, f"expected exit 2 for {args}, got {code}")
    if snapshot(root) != before:
        sweep.violation("usage", "usage rejections changed the filesystem")

    # -------- phase 10: the video pillar (real ffmpeg when present) --------
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        fake_clip = root / "clip.mp4"
        fake_clip.write_bytes(b"not a real container")
        code, payload = sweep.run_json("video", "video", "info", str(fake_clip), expect_exit=1)
        if payload.get("error") != "ffmpeg_missing":
            sweep.violation("video", f"expected ffmpeg_missing, got {payload.get('error')}")
    else:
        vids = root / "vids"
        vids.mkdir()

        def _clip(name: str, *, size: str, duration: float, crf: int, audio: bool) -> Path:
            path = vids / name
            args = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size={size}:rate=24:duration={duration}",
            ]
            if audio:
                args += [
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency=330:duration={duration}",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "96k",
                    "-shortest",
                ]
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), str(path)]
            subprocess.run(args, check=True, capture_output=True)
            return path

        first = _clip("part1.mp4", size="320x240", duration=2.0, crf=23, audio=True)
        second = _clip("part2.mp4", size="320x240", duration=2.0, crf=23, audio=True)
        odd = _clip("odd.mp4", size="160x120", duration=1.0, crf=23, audio=False)
        rich = _clip("rich.mp4", size="640x480", duration=4.0, crf=10, audio=True)

        sweep.run_json("video", "video", "info", str(first), str(odd), expect_exit=0)

        video_budget = int(rich.stat().st_size * 0.5)
        code, _fitted = sweep.run_json(
            "video",
            "video",
            "compress",
            str(rich),
            "--target-size",
            str(video_budget),
            "-o",
            str(vids / "fit"),
            expect_exit=0,
        )
        produced = next((vids / "fit").glob("*.mp4"), None)
        if produced is None or produced.stat().st_size > video_budget:
            sweep.violation("video", "target-size output missing or over budget")

        joined = vids / "joined.mp4"
        sweep.run_json(
            "video",
            "video",
            "concat",
            str(first),
            str(second),
            "-o",
            str(joined),
            expect_exit=0,
        )
        code, info = sweep.run_json("video", "video", "info", str(joined), expect_exit=0)
        joined_duration = info.get("files", [{}])[0].get("duration_sec", 0)
        if not 3.4 <= joined_duration <= 4.6:
            sweep.violation("video", f"concat duration {joined_duration} not ~4s")

        code, mismatch = sweep.run_json(
            "video",
            "video",
            "concat",
            str(first),
            str(odd),
            "-o",
            str(vids / "no.mp4"),
            expect_exit=1,
        )
        if mismatch.get("error") != "concat_requires_matching_streams":
            sweep.violation("video", f"mismatched concat gave {mismatch.get('error')}")

        code, planned = sweep.run_json("video", "optimize", str(vids / "rich.mp4"), expect_exit=0)
        plan_cmd = planned.get("results", [{}])[0].get("plan", {}).get("command")
        if plan_cmd in ("video.compress", "video.convert"):
            code, applied_video = sweep.run_json(
                "video",
                "apply",
                "--plan",
                "-",
                "-o",
                str(vids / "applied"),
                stdin=json.dumps(planned),
                expect_exit=0,
            )
            for step in applied_video.get("steps", []):
                produced_step = step["ok"] and not step["skipped"] and step["output"]
                if produced_step and not Path(step["output"]).is_file():
                    sweep.violation("video", f"applied output missing: {step['output']}")

    elapsed = time.time() - started
    print(
        f"\nsweep finished in {elapsed:.1f}s: {sweep.invocations} CLI invocations, "
        f"{sweep.payloads} JSON payloads validated"
    )
    if sweep.violations:
        print(f"VIOLATIONS ({len(sweep.violations)}):")
        for item in sweep.violations:
            print(f"  - {item}")
    else:
        print("no contract violations")

    if not options.keep and options.root is None:
        shutil.rmtree(root, ignore_errors=True)
    elif options.keep:
        print(f"corpus kept at {root}")
    return 1 if sweep.violations else 0


if __name__ == "__main__":
    sys.exit(main())
