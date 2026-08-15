# ADR-0005: Video as the Third Media Pillar

Status: Superseded in part by [ADR-0008](0008-default-local-media-runtime.md)

## Context

PixShift is an AI-native CLI for everyday media work. The image and PDF pillars are
stable (ADR-0001..0004): machine-readable JSON contracts, a discoverable tool catalog,
atomic writes, `--dry-run`, idempotent reruns, and a discover → plan → apply → verify
loop shared by humans and agents.

Everyday video operations — inspect, transcode, compress, trim, thumbnail, extract audio,
and make a GIF — are the same kind of deterministic one-shot job and are the most common
media request that PixShift could not serve. ffmpeg is powerful but its flag surface is a
notorious source of agent errors (silent `exit 0` on a truncated output, position-sensitive
flags, `-c copy` incompatibilities). Wrapping it behind the PixShift contract is the value.

## Decision

The original decision added an optional `video` command group backed by ffmpeg/ffprobe,
detected at runtime. ADR-0008 supersedes only the installation/availability policy;
the command scope and engine safety boundaries below remain authoritative.

Scope (MVP): `video info`, `video convert` (mp4/webm/mkv/mov), `video compress`
(CRF presets over h264/h265/vp9/av1), `video trim` (stream-copy by default), `video
thumbnail`, `video extract-audio`, and `video gif` (palettegen two-pass).

Engine design:

- **Stable absence behavior.** Every command returns a stable `ffmpeg_missing` error
  (JSON) or a clear install hint (human) when no complete runtime pair is available.
  ADR-0008 makes video readiness required in supported release-wheel installations.
- **Pure argv builders.** The per-operation ffmpeg argument lists are built by pure
  functions with no I/O, so their correctness is unit-tested even on hosts without ffmpeg;
  only `probe` and `run_ffmpeg` touch the binaries.
- **Safety invariants carry over.** Output is written to a same-directory temp path and
  atomically replaced on success (existing `atomic_output_path`); `--overwrite` and
  idempotent skips match the image commands; ffmpeg runs with an explicit argv list (never
  a shell string), user paths are absolutised so a `-`-leading name cannot become an
  option, filter graphs only interpolate validated numbers, and ffprobe/ffmpeg run with a
  timeout and `-nostdin` so a malformed container cannot hang the process.

## Consequences

- New modules `video_engine.py`, `ops/video.py`, `commands/video_commands.py`; catalog and
  `doctor` gain video entries; a minor (additive, non-breaking) release carries it.
- ADR-0008 adds authenticated platform wheels while preserving the system-runtime path
  for source installs, unsupported platforms, and administrator-managed environments.

## Non-goals

- Timeline/NLE editing, filter/effect chains, subtitle burn-in
- Generative AI in any pillar (synthesis, upscaling, interpolation, captioning)
- Cloud transcoding, render farms, live-streaming protocols (RTMP/HLS)
- Matching the full ffmpeg flag surface
