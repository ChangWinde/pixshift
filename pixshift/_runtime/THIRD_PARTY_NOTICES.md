# Bundled FFmpeg runtime

PixShift platform wheels contain unmodified `ffmpeg` and `ffprobe` executables
from **FFmpeg 8.1.2**, built and published by the Shaka Project's
`static-ffmpeg-binaries` release `n8.1.2-1`.

- Build source: <https://github.com/shaka-project/static-ffmpeg-binaries>
- Pinned build commit: `88caac417541f3bb678fa6670cb73f2d74c7aaf9`
- FFmpeg source: <https://github.com/FFmpeg/FFmpeg/tree/n8.1.2>
- Corresponding build inputs and per-platform SHA-256 values:
  `scripts/media_runtime_manifest.json` in the PixShift source distribution

The executables include GPL libraries and are distributed under **GPL-3.0-or-later**.
The full license text is installed beside this notice as `COPYING.GPLv3`.
PixShift's Python source remains available under the repository's MIT license;
the programs communicate through the documented command-line boundary.

The release pipeline downloads only the pinned artifacts above, verifies exact
length and SHA-256 before publication, executes the pair on its target platform,
and records machine-readable provenance as `provenance.json` in the wheel.
