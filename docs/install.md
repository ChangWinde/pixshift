# 安装与环境

## 安装

本手册跟随仓库 `main` 分支；PyPI 命令安装的是最近一次已发布版本，可能暂时
落后于本手册。正式发布的支持平台 wheel 是默认且完整的安装方式。

=== "当前源码"

    ```bash
    git clone https://github.com/ChangWinde/pixshift.git
    cd pixshift
    pip install .
    ```

    源码/可编辑安装不会在构建时联网抓取原生程序；视频功能使用系统中已有的
    ffmpeg 与 ffprobe。这一例外让源码构建可复现、可离线。

=== "pip"

    ```bash
    pip install pixshift
    ```

=== "uv"

    ```bash
    uv tool install pixshift
    ```

要求 Python 3.10 及以上。Linux、macOS、Windows 在主分支推送和 Pull Request 上均有持续集成覆盖。

支持平台上的 PyPI/uv 标准安装会提供所有媒体依赖，不需要额外的
`pixshift[all]` 或安装后下载步骤。不要使用 `--no-deps`；它会有意绕过
Python 依赖。源码安装与未提供 wheel 的平台需要系统 ffmpeg/ffprobe。

## 依赖说明

| 能力 | 依赖 | 是否随包安装 |
| --- | --- | --- |
| 图片核心（转换、压缩、裁剪、水印等） | Pillow | 是 |
| HEIC/HEIF 读写 | pillow-heif | 是 |
| PDF 全部功能 | PyMuPDF | 是 |
| AVIF 编码 | Pillow AVIF / pillow-avif-plugin | 是 |
| 视频全部功能 | ffmpeg / ffprobe | 是（支持的平台 wheel） |

视频运行时按下面的固定顺序解析：

1. `PATH` 中同时存在的系统 ffmpeg 与 ffprobe；
2. PixShift 平台 wheel 中同时存在的 ffmpeg 与 ffprobe；
3. 都不完整时返回稳定的 `ffmpeg_missing`，不会混用两个来源。

解析过程不修改 `PATH`，不会在 import、探测或编码时联网。当前平台 wheel
覆盖 manylinux_2_28 兼容的 Linux x86-64/ARM64、macOS 15+ Intel/Apple Silicon
和 Windows x86-64。musl/Alpine、其他架构、较早的 macOS 以及源码安装仍可使用
PixShift，但需要提供系统 ffmpeg/ffprobe；`doctor` 会把缺失视为安装未就绪。

系统版本会优先于随包版本，适合需要发行版安全更新、额外编码器或硬件集成的环境：

安装 ffmpeg：

```bash
# macOS
brew install ffmpeg
# Debian / Ubuntu
sudo apt install ffmpeg
# Windows
winget install Gyan.FFmpeg
```

平台 wheel 内的 FFmpeg 8.1.2 是 GPL-3.0-or-later 程序，wheel 同时包含完整
许可证、构建来源、固定提交与逐文件 SHA-256。PixShift Python 源码继续采用 MIT
License；重新分发含运行时的 wheel 时仍须遵守 FFmpeg 的许可证与对应源码义务。

## 自检

```bash
pixshift doctor
```

该命令列出各项依赖、是否必需，以及视频运行时来自 `系统` 还是 `随包安装`。
标准媒体依赖缺失会令 `ok` 与 `all_ready` 为 `false`，因此成功结果代表三类媒体
运行时均已就绪。视频检查会实际执行 ffmpeg 与 ffprobe，并要求两者版本一致；
损坏、不可执行或错架构的文件不会被“存在性检查”误报为成功。

查看当前环境实际支持的输入扩展名与输出格式：

```bash
pixshift formats
```

输出取决于运行环境的实际探测结果；系统 Pillow 或编解码器能力发生变化时，列表
会反映当前可用格式，而不是静态宣传值。

## Shell 补全

```bash
# bash（~/.bashrc）
eval "$(_PIXSHIFT_COMPLETE=bash_source pixshift)"
# zsh（~/.zshrc）
eval "$(_PIXSHIFT_COMPLETE=zsh_source pixshift)"
# fish（~/.config/fish/completions/pixshift.fish）
_PIXSHIFT_COMPLETE=fish_source pixshift | source
```

## 升级与卸载

```bash
pip install --upgrade pixshift
pip uninstall pixshift
```
