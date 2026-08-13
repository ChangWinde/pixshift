# PixShift 概览

PixShift 是一个本地优先的命令行工具，覆盖日常的**图片、PDF、视频**处理：格式转换、压缩、裁剪缩放、水印、去重、合并拆分、转码剪辑。

它的特点不在于功能多，而在于**人和自动化程序共用同一套接口**：同一条命令，人看到的是表格和进度条，脚本或 agent 加上 `--json` 就得到字段稳定、退出码明确的机器输出。所有处理都在本地完成，媒体处理路径上不存在任何网络调用。

## 安装

```bash
pip install pixshift
```

需要 Python 3.10 或更高版本。PDF 能力开箱即用，视频能力需要额外安装 ffmpeg，详见[安装与环境](install.md)。

## 五分钟上手

```bash
# 查看环境是否就绪（缺什么、能做什么，一眼看清）
pixshift doctor

# 手机照片转 WebP，整个目录一起处理
pixshift convert ./photos -t webp -r

# 压到 500KB 以内，并在预算内保留最好的画质
pixshift compress poster.jpg --target-size 500KB

# 发朋友之前清掉 GPS 等隐私元数据
pixshift strip IMG_0421.jpg

# 扫描件合成一个 PDF
pixshift pdf merge ./scans -o 合同.pdf

# 视频压到 25MB 以内（需要 ffmpeg）
pixshift video compress talk.mp4 --target-size 25MB
```

## 能力速查

| 场景 | 图片 | PDF | 视频 |
| --- | --- | --- | --- |
| 查看信息 | `info` | `pdf info` | `video info` |
| 格式转换 | `convert` | `pdf extract` | `video convert` |
| 压缩瘦身 | `compress` | `pdf compress` | `video compress` |
| 控制体积上限 | `--target-size` | `--target-size` | `--target-size` |
| 合并 | `montage`、`pdf merge` | `pdf concat` | `video concat` |
| 拆分与截取 | `crop`、`resize` | `pdf split` | `video trim` |
| 其他 | `strip`、`rotate`、`watermark`、`dedup`、`compare` | — | `video thumbnail`、`video extract-audio`、`video gif` |

完整参数见[图片](images.md)、[PDF](pdf.md)、[视频](video.md)三章。

## 三条行为约定

无论调用哪条命令，下面三点都成立。理解它们，就不需要逐条记忆各命令的边界行为。

**写入是原子的。** 输出先写到同目录的临时文件，编码成功后才替换到目标路径。命令中断或编码失败时，你不会得到一个半截的文件。

**重复执行是安全的。** 已存在的输出会被跳过而不是覆盖，除非显式加 `--overwrite`；目录扫描也会自动排除本次操作自己产生的派生文件（如 `photo_compressed.jpg`）。同一条命令连续跑两次，第二次不会做无用功，也不会二次劣化画质。

**破坏性操作必须显式请求。** 只有 `dedup --delete` 会删除文件，且仅限于哈希逐字节复核过的完全相同文件；感知相似度只用于提示，永远不作为删除依据。

## 给脚本和 Agent 的接口

任何命令加 `--json` 即进入机器模式：输出单行 JSON，字段稳定，失败时 `ok` 为 `false` 且退出码非零（`1` 表示执行失败，`2` 表示参数被拒绝）。

```bash
# 发现能力 → 生成计划 → 执行 → 校验
pixshift tools --json
pixshift optimize ./media --json | pixshift apply --plan - --dry-run --json
pixshift hash ./media -r --json
```

详见[脚本与 Agent 集成](automation.md)与[JSON 输出契约](JSON_OUTPUT.md)。
