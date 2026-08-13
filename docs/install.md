# 安装与环境

## 安装

=== "pip"

    ```bash
    pip install pixshift
    ```

=== "uv"

    ```bash
    uv tool install pixshift
    ```

=== "AVIF 支持"

    ```bash
    pip install "pixshift[avif]"
    ```

要求 Python 3.10 及以上，在 Linux、macOS、Windows 上均有持续集成覆盖。

## 依赖说明

| 能力 | 依赖 | 是否随包安装 |
| --- | --- | --- |
| 图片核心（转换、压缩、裁剪、水印等） | Pillow | 是 |
| HEIC/HEIF 读写 | pillow-heif | 是 |
| PDF 全部功能 | PyMuPDF | 是 |
| AVIF 编码 | pillow-avif-plugin | 否，需装 `pixshift[avif]` |
| 视频全部功能 | ffmpeg / ffprobe | 否，需自行安装 |

视频功能采用**可选依赖**设计：没有 ffmpeg 时其余命令完全不受影响，视频命令会返回稳定的 `ffmpeg_missing` 错误而不是崩溃。

安装 ffmpeg：

```bash
# macOS
brew install ffmpeg
# Debian / Ubuntu
sudo apt install ffmpeg
# Windows
winget install Gyan.FFmpeg
```

## 自检

```bash
pixshift doctor
```

该命令列出各项依赖的可用状态。可选依赖缺失只做提示，不会让命令失败——因此 `doctor` 返回成功不代表视频功能可用，需要看具体检查项。

查看当前环境实际支持的输入扩展名与输出格式：

```bash
pixshift formats
```

输出取决于运行环境的探测结果。例如未安装 AVIF 插件时，`avif` 不会出现在可选输出格式中。

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
