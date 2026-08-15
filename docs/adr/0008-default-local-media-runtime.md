# ADR-0008: Default local media runtime

## Status

Accepted

## Context

The image and PDF pillars are complete after a normal installation, but the video
pillar historically required a separate system installation of ffmpeg and ffprobe.
That made the advertised three-pillar product dependent on a second installation
workflow and left otherwise valid installations reporting `ffmpeg_missing`.

The runtime must remain local-first: installation may download declared package
artifacts, but invoking a media command must never contact a network, elevate
privileges, or mutate the host `PATH`. A system-managed runtime should remain usable
because administrators may patch it faster or compile additional hardware encoders.

## Driving Factors

- A standard release-wheel installation should enable image, PDF, AVIF, and video.
- Runtime discovery must be deterministic, side-effect free, and offline.
- ffmpeg and ffprobe must come from one source and be selected as a pair.
- Linux, macOS, and Windows release platforms need the same public behavior.
- Binary provenance, codec coverage, installation size, and licensing must be explicit.
- A vulnerable or abandoned binary package is worse than a clear installation failure.

## Candidates

### Option A: Invoke system package managers during Python installation

- Pros: uses administrator-managed security updates and native integration.
- Cons: pip/uv cannot portably invoke apt, Homebrew, winget, or Chocolatey;
  installation may need elevation and becomes non-reproducible or interactive.

### Option B: Download ffmpeg on the first video command

- Pros: small Python wheel and broad platform selection at runtime.
- Cons: violates the offline media boundary, moves failure from installation to
  production work, and makes command latency and reproducibility network-dependent.

### Option C: Depend on a third-party Python binary wheel

- Pros: ordinary package resolution installs the executables with little PixShift
  release machinery.
- Cons: delegates patch cadence, codec selection, provenance, and platform coverage.
  The evaluated package contained FFmpeg 6.0 and was rejected during security review.

### Option D: Publish authenticated PixShift platform wheels

- Pros: a standard installation is complete; exact artifacts, hashes, supported
  platforms, codec floor, and smoke tests are under the PixShift release gate.
- Cons: larger downloads and ongoing binary provenance, GPL, and security-response
  obligations; source/editable installs still need a system runtime.

## Trade-off Matrix

| Criterion | System managers | First-use download | Third-party wheel | PixShift platform wheels |
| --- | --- | --- | --- | --- |
| One standard install | Poor | Partial | Strong | Strong |
| Offline media commands | Strong | Poor | Strong | Strong |
| Reproducible artifacts | Mixed | Poor | Mixed | Strong |
| Provenance control | System-specific | Weak | Delegated | Explicit manifest + hashes |
| Operational burden | Low | Medium | Medium | High |
| Install size | Small | Small initially | Large | Large |

## Decision

Choose **Option D** for published wheels. The Python dependencies include AVIF support.
The tag-driven release pipeline additionally stages an unchanged FFmpeg 8.1.2 pair from
Shaka Project's reproducible `static-ffmpeg-binaries` release `n8.1.2-1` into each
platform wheel. The committed manifest pins the upstream build commit, versioned URLs,
exact byte lengths, and SHA-256 values for:

- manylinux_2_28-compatible Linux x86-64 and ARM64;
- macOS 15+ x86-64 and Apple Silicon (matching the binaries' Mach-O deployment target);
- Windows x86-64.

The build publishes nothing until both executables authenticate, execute on their target
runner, expose the required codecs/filters, and complete a real encode/probe journey.
Each wheel carries `COPYING.GPLv3`, a third-party notice, and machine-readable provenance.
The source distribution never downloads or embeds native artifacts; source and editable
installs use a complete system pair.

The runtime boundary has deterministic precedence:

```text
resolve_ffmpeg_runtime()
  -> complete system ffmpeg + ffprobe pair
  -> complete wheel-packaged ffmpeg + ffprobe pair
  -> unavailable
```

The provider accepts only regular, executable files from one directory. PixShift passes
the selected paths directly to subprocesses and never mutates global `PATH`. The bundled
codec floor matches the public command surface: H.264 (`libx264`), H.265 (`libx265`),
VP9 (`libvpx-vp9`), AV1 (`libsvtav1`), AAC, MP3, Opus, FLAC, and PCM, plus the filters
used by verification.

## Impact

- `pip install pixshift` and `uv tool install pixshift` enable all three pillars when a
  supported platform wheel exists. Unsupported platforms and source installs use system
  ffmpeg/ffprobe and fail readiness clearly when that pair is absent.
- A complete system pair remains preferred; `doctor` executes both commands, requires
  matching version tokens, and reports `系统` or `随包安装`.
- AVIF and video runtime failures are required doctor checks. `--no-deps`, an unsupported
  platform, a source build without a system pair, or damaged files make readiness fail.
- PixShift's Python source remains MIT. Wheel-packaged FFmpeg is GPL-3.0-or-later and
  carries its license and provenance; redistributors retain the corresponding-source
  and license obligations described by GPLv3.
- Updating FFmpeg requires a reviewed manifest change and the full cross-platform release
  gate. Dependency freshness is a release blocker, not an implicit downloader behavior.
- No network call is added to import, startup, probing, encoding, or verification.
