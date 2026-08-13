# 视频

视频命令需要系统中安装 ffmpeg 与 ffprobe（见[安装与环境](install.md)）。未安装时命令返回稳定的 `ffmpeg_missing` 错误，其余图片与 PDF 功能不受影响。

输出同样是原子写入，已存在的输出默认跳过，加 `--overwrite` 才覆盖。

## info — 查看视频信息

```bash
pixshift video info FILES... [--json]
```

输出容器、视频与音频编码、时长、分辨率、帧率、码率。做自动化处理前先用它确认素材参数。

## convert — 转码

```bash
pixshift video convert INPUTS... [-t mp4] [--codec h264] [-o 输出目录] [-r] [--json]
```

| 参数 | 说明 |
| --- | --- |
| `-t, --to` | 目标容器：`mp4`（默认）/ `webm` / `mkv` / `mov` |
| `--codec` | `h264` / `h265` / `vp9` / `av1`，默认按容器选择 |
| `--hwaccel` | 硬件编码后端，见下文 |

不指定 `--codec` 时按容器取默认编码：mp4 与 mov 用 h264，mkv 用 h265，webm 用 vp9。mp4/mov 输出会自动写入 `+faststart`，便于边下边播。

## compress — 压缩

```bash
pixshift video compress INPUTS... [-p web] [-o 输出目录] [-r] [--json]
pixshift video compress talk.mp4 --target-size 25MB [--json]
```

| 参数 | 说明 |
| --- | --- |
| `-p, --preset` | `web`（默认，均衡）/ `archive`（接近视觉无损）/ `tiny`（最小体积，长边限 1280） |
| `--codec` | `h264`（默认）/ `h265` / `vp9` / `av1` |
| `--crf` | 覆盖预设的 CRF 值（0–63），数值越小画质越好 |
| `--target-size` | 目标体积上限，如 `25MB` |
| `--hwaccel` | 硬件编码后端，见下文 |

输出为 `_compressed` 派生文件，容器取所选编码的原生容器。

**`--target-size` 用两遍编码达成体积约束下的最优画质。** 先把字节预算换算成视频码率（预留音轨与容器封装开销），再执行两遍编码——这是给定体积下画质最优的做法。av1 与硬件编码器没有可移植的两遍实现，会退化为单遍 ABR。原文件已在预算内时原样复制；码率控制超出预算时按实测比例回调再试一次，仍不达标则返回 `target_size_missed` 且不产出文件。该参数与 `-p`、`--crf` 互斥。

## concat — 拼接

```bash
pixshift video concat a.mp4 b.mp4 -o joined.mp4 [--json]
```

默认使用**流拷贝**：不重新编码，无画质损失且几乎瞬时完成，但要求各段的编码与分辨率一致。参数不一致时返回 `concat_requires_matching_streams`，此时加 `--reencode` 会把所有片段统一重编码为 h264 后再拼接。

## trim — 截取片段

```bash
pixshift video trim source.mp4 --start 00:01:30 --duration 45 -o clip.mp4 [--json]
```

`--start` 与 `--end` 接受 `HH:MM:SS`、`MM:SS` 或纯秒数；`--end` 与 `--duration` 二选一。

默认在关键帧处流拷贝，速度快但起止点会对齐到最近的关键帧；需要精确到帧时加 `--reencode`，代价是一次重编码。

## thumbnail — 导出封面帧

```bash
pixshift video thumbnail INPUTS... [--at 25%] [-t jpg] [-o 输出目录] [-r] [--json]
```

`--at` 接受时间点（`HH:MM:SS` 或秒）或时长百分比（默认 `25%`）。输出格式支持 `jpg`（默认）、`png`、`webp`。

## extract-audio — 导出音轨

```bash
pixshift video extract-audio INPUTS... [-t mp3] [-o 输出目录] [-r] [--json]
```

支持 `mp3`（默认）、`aac`、`m4a`、`opus`、`flac`、`wav`。有损格式默认 192 kbps，无损格式按编码原生设置。

## gif — 片段转动图

```bash
pixshift video gif source.mp4 --start 5 --duration 3 --fps 12 --width 480 -o out.gif [--json]
```

采用调色板两段式滤镜生成，画质明显优于直接转换。`--fps`（1–60）与 `--width`（1–4096）直接决定体积，默认 12 帧、480 像素宽。

## 硬件加速

`--hwaccel` 在 `convert` 与 `compress` 上可用，需显式开启：

| 后端 | 适用平台 |
| --- | --- |
| `videotoolbox` | macOS |
| `nvenc` | NVIDIA 显卡 |
| `qsv` | Intel 核显 |

仅支持 h264 与 h265，其他编码组合返回 `unsupported_hwaccel:<后端>:<编码>`。CRF 风格的质量目标会被换算到各后端自己的参数上。硬件编码器以单位码率下的画质换取大幅提速，追求极致压缩率时仍应使用软件编码。可用性取决于本机 ffmpeg 的编译选项，用 `ffmpeg -encoders` 确认。

`optimize` 生成的计划永远不包含 `hwaccel`，以保证计划可以在任意机器上执行。

## 分析与自动化

`optimize` 同样能分析视频，且**只读取 ffprobe 元数据，不做任何试编码**：

- 陈旧编码（如 mpeg4、wmv）→ 建议转码到现代编码；
- 码率明显偏高 → 建议同族重压，并给出体积预估；
- 已经足够高效 → 给出显式的 `keep`（不动它），因为重编码只会损失画质。

结果可直接交给 `apply` 执行，详见[脚本与 Agent 集成](automation.md)。
