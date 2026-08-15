# 常见问题

## 网站文档和 `pip install pixshift` 是同一个版本吗

不一定。本站由仓库 `main` 分支自动发布，用于记录当前已经合并并通过文档构建的
命令面；PyPI 只在版本标签通过完整发布门禁后更新，因此发布准备期间可能落后。

先检查本机实际版本：

```bash
pixshift --version
```

需要本站描述的完整开发命令面时，按[安装与环境](install.md)从当前源码安装；需要
稳定发布版时继续使用 `pip install pixshift`，并以对应版本的 `--help` 为准。

## 视频命令报 `ffmpeg_missing`

支持平台的发布 wheel 会带上 ffmpeg 与 ffprobe。出现这个错误通常意味着正在
使用源码/可编辑安装、当前架构没有平台 wheel，或运行时文件损坏。先重新安装并自检：

```bash
pip install --upgrade --force-reinstall pixshift
pixshift doctor
```

仍不可用时按[安装与环境](install.md)安装系统 ffmpeg/ffprobe；完整的系统二进制对
会自动优先于随包版本。图片与 PDF 命令不会因为视频运行时缺失而崩溃，但
`doctor` 会把整个安装标记为未就绪。

## `--target-size` 达不到目标怎么办

命令会明确失败而不是交付一个超标的文件，错误码区分两种情况：

- 图片与 PDF：`target_size_unreachable`，表示即使降到最低质量仍超出预算；
- 视频：`target_size_missed`，表示两次码率尝试后仍未落进预算。

对应的处理方式是放宽预算，或先降低分辨率再压缩（图片用 `--max-size`，视频先 `video convert` 降分辨率）。预算过小以致算出的视频码率低于可用下限时，会提前返回 `target_size_too_small`，不会白白编码一遍。

## 为什么第二次运行「什么都没做」

这是幂等设计：已存在的输出会被跳过，避免重复编码和二次画质损失。需要重新生成时加 `--overwrite`。JSON 输出里的 `skipped` 字段会显示具体跳过了多少个。

## 输出目录里的文件会被当成新输入吗

不会。目录扫描会自动排除本次操作产生的派生文件（如 `photo_compressed.jpg`）、聚合输出和水印素材。但**显式传入的文件参数总是被处理**——这个优先级是刻意的，方便你精确指定要处理的文件。

## 动图（GIF/APNG/动画 WebP）支持到什么程度

`convert` 与 `resize` 会保留动画：帧、每帧时长、循环次数、透明度都不丢。目标格式必须能承载动画（`webp` / `gif` / `png`），否则返回 `animated_input_not_supported`。

逐像素合成类操作（`rotate`、`crop`、`watermark`、`compare`、`pdf merge`、`montage`）不支持动图，会以同样的错误码明确拒绝，而不是悄悄只处理第一帧。用 `pixshift info` 查看 `frame_count` 可以提前区分。

## GIF 太大，怎么变小

优先转成动画 WebP，通常能减小 30%–60% 且保留动画：

```bash
pixshift convert banner.gif -t webp
```

`optimize` 对动图给出的也正是这条建议。

## 处理大批量文件慢吗

图片转换及同格式图片批处理会自动并行：最多 8 个进程，并根据输入尺寸与 `PIXSHIFT_BATCH_MEMORY_MB` 内存预算进一步降低并发；任务少于 4 个时保持串行。`convert` 可用 `-j` 请求更低的并行上限。PDF 与视频命令默认顺序处理，以控制外部编码器和大文档的资源峰值。

## 元数据到底清掉了什么

`strip --mode privacy`（默认）清除 GPS、设备型号、作者等个人与设备字段，保留时间与色彩信息；`--mode all` 清空全部 EXIF。清理覆盖顶层与嵌套 EXIF 目录，同时处理 XMP 与注释段——这些字段部分编码器会自动回写，只是「不传参数」并不足以清除。

ICC 色彩配置默认保留（删掉可能导致颜色偏移），需要时用 `--strip-icc`。

另外，`pdf merge` 直接嵌入原始 JPEG 字节的快路径也会剥离元数据段，拍摄信息不会随图片进入 PDF。

## `dedup --delete` 会误删吗

不会基于「看起来像」删除文件。感知相似度只用于分组提示；`--delete` 只处理逐字节完全相同的文件。候选先被原子隔离到同目录私有暂存区，再对隔离后的对象身份和 SHA-256 复验；路径在检查/删除边界被替换时，无关文件不会被删除。建议先用 `--dry-run` 预览。

## 命令中途失败会留下半成品吗

不会。所有输出先写到同目录临时文件，编码成功后才原子替换到目标路径。编码器异常退出、磁盘写入失败或进程被中断，都不会产生半截文件。

## 退出码 1 和 2 有什么区别

`2` 表示参数被拒绝，尚未写入任何文件，重试无意义，必须修改调用方式；`1` 表示已经开始处理但至少一项失败，值得逐条检查 `errors` 数组。详见[JSON 输出契约](JSON_OUTPUT.md)。

## 支持哪些操作系统

Linux、macOS、Windows 均有持续集成覆盖。测试在推送到 `main`/`master` 和每个 Pull Request 时运行；Linux 覆盖 Python 3.10/3.12/3.13，macOS 与 Windows 覆盖 Python 3.13，三个平台都安装真实 ffmpeg 执行视频集成路径。

## 报错 `image_too_large` 是怎么回事

为防范「解压炸弹」——一个几百 KB 的文件声明了几十亿像素的画布，解码时会耗尽内存——PixShift 默认限制单张图片为 1.2 亿像素。超限的文件在**解码之前**就被拒绝，不会先把内存吃满。

确实需要处理超大画布时，用环境变量放宽或关闭：

```bash
PIXSHIFT_MAX_PIXELS=1000000000 pixshift convert huge.png -t webp   # 提高 PixShift 限制
PIXSHIFT_MAX_PIXELS=0 pixshift convert huge.png -t webp            # 仅关闭 PixShift 附加限制
```

Pillow 自身的解压炸弹策略独立生效，因此提高或关闭 PixShift 限制不会降低
宿主进程配置的 Pillow 安全阈值。

## 会不会上传我的文件

不会。媒体处理路径上没有任何网络调用，全部处理在本地完成。
