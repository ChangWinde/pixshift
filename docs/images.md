# 图片

所有命令都接受**文件、多个文件或目录**作为输入；给目录时加 `-r` 递归子目录。默认输出到输入文件同级目录，用 `-o` 指定输出目录。

## convert — 格式转换

```bash
pixshift convert INPUTS... -t webp [-o 输出目录] [-r] [--json]
```

| 参数 | 说明 |
| --- | --- |
| `-t, --to` | 目标格式（必填），可选项按运行环境探测 |
| `-q, --quality` | `max` / `high` / `medium` / `low` / `web`，默认 `high` |
| `-f, --from` | 只处理指定输入格式，如 `-f heic` |
| `--resize` | 同时缩放，`1920x1080` 或 `50%` |
| `--max-size` | 限制最长边像素，保持宽高比 |
| `--prefix` / `--suffix` | 给输出文件名加前后缀 |
| `--strip-alpha` | 去掉透明通道，用 `--bg-color`（默认白色）填充 |
| `--no-exif` / `--no-icc` / `--no-orient` | 分别关闭 EXIF、ICC 保留与方向自动校正 |
| `-j, --jobs` | 并行进程数，默认自动（最多 8） |
| `--flatten` | 输出不保留子目录结构 |

默认的 `high` 在画质、体积、编码速度之间取平衡；归档场景再显式指定 `-q max`。扫描目录时会自动跳过已经是目标格式的文件，但显式传入的文件参数一定会被处理。

**动图会保留动画。** GIF、APNG、动画 WebP 转换到同样支持动画的格式（`webp` / `gif` / `png`）时，帧、每帧时长、循环次数和透明度都会保留；转到无法承载动画的格式（如 `jpg`）则返回 `animated_input_not_supported` 错误而不是悄悄丢帧。缩放参数会逐帧生效。

## compress — 保持格式压缩

```bash
pixshift compress INPUTS... [-p medium] [-o 输出目录] [-r] [--json]
```

| 参数 | 说明 |
| --- | --- |
| `-p, --preset` | `lossless` / `high` / `medium` / `low` / `tiny`，默认 `medium` |
| `--quality` | 1–100，覆盖预设，仅对有损格式生效 |
| `--target-size` | 目标体积上限，如 `500KB`、`1MB` |
| `--max-size` | 同时限制最长边像素 |

输出为 `_compressed` 派生文件。PNG、TIFF 始终无损，此时 `--quality` 不生效，JSON 输出会给出 `quality_ignored_for_lossless` 警告。

**`--target-size` 回答的是最常见的诉求：不超过某个体积，同时保留尽可能好的画质。** 实现方式是在质量区间内二分搜索，取满足体积约束的最高质量。若连最低质量也超出预算，命令报错而不是交付一个不达标的文件。该参数与 `--quality` 互斥。

## resize — 保持格式缩放

```bash
pixshift resize INPUTS... (--size 1280x720 | --percent 50 | --max-size 2048) [-r] [--json]
```

三种尺寸模式**必须且只能选一种**。`--max-size` 限制最长边且从不放大。输出为 `_resized` 派生文件，`-q` 控制有损格式的重编码质量（默认 `high`）。动图逐帧缩放，时长与循环保持不变。

## rotate — 旋转与镜像

```bash
pixshift rotate INPUTS... [--degrees 90] [--flip horizontal] [-r] [--json]
```

`--degrees` 取 `90` / `180` / `270`（顺时针），`--flip` 取 `horizontal` / `vertical`，两者可组合但至少要给一个。

变换前会先按 EXIF Orientation 归一化方向且只归一化一次，因此结果与看图软件显示的方向一致。该命令逐像素重排，不支持动图。

## crop — 裁剪

```bash
pixshift crop INPUTS... (--crop 100,50,900,700 | --aspect 16:9 | --trim) [-r] [--json]
```

| 模式 | 说明 |
| --- | --- |
| `--crop L,T,R,B` | 按绝对像素区域裁剪 |
| `--aspect 16:9` | 按比例裁剪，`--gravity` 指定保留重心（默认 `center`） |
| `--trim` | 自动裁掉边缘纯色留白，`--trim-fuzz` 设置容差（0–255） |

## strip — 清理元数据

```bash
pixshift strip INPUTS... [--mode privacy] [-r] [--json]
```

| 模式 | 清理内容 |
| --- | --- |
| `privacy`（默认） | GPS、设备信息、个人字段，保留时间与色彩等无关信息 |
| `all` | 清空全部 EXIF |
| `gps` / `device` / `personal` / `time` | 只清理对应类别 |

清理会同时覆盖顶层 EXIF 与嵌套的 EXIF 目录，也会处理 XMP、注释等编码器可能回写的字段。加 `--strip-icc` 可一并移除 ICC 色彩配置（默认保留，避免颜色偏移）。输出为 `_clean` 派生文件。

## watermark — 水印

```bash
pixshift watermark text  INPUTS... --text "内部资料" [-r] [--json]
pixshift watermark image INPUTS... --watermark logo.png [-r] [--json]
```

共用参数：`--position`（九宫格位置，默认右下）、`--opacity`（0–255）、`--margin`、`--tile` 与 `--tile-spacing`（平铺）。文字水印另有 `--font`、`--font-size`（默认按图片短边自动计算）、`--color`、`--rotation`；图片水印用 `--scale`（0.01–1.0）控制相对大小。

## montage — 网格拼图

```bash
pixshift montage INPUTS... -o board.png [--cols 4] [-r] [--json]
```

输出格式限 `.png`、`.jpg`/`.jpeg`、`.webp`。可调 `--gap`（间距）、`--cell-width` / `--cell-height`（单元格尺寸）、`--background`、`--border` 与 `--border-color`、`--label`（显示文件名）。

## dedup — 查重与安全清理

```bash
pixshift dedup INPUTS... [-r] [--threshold 5] [--json]
pixshift dedup INPUTS... -r --delete --yes [--json]
```

默认只分析不删除：用感知哈希（`--hash-method` 可选 `phash` / `ahash` / `dhash`）按 `--threshold` 汉明距离聚类，列出相似组与可回收空间。

!!! warning "删除的安全边界"
    `--delete` **只删除逐字节完全相同的文件**，且在删除前立即用 SHA-256 重新校验一次；感知相似只作为提示，永远不构成删除依据。加 `--dry-run` 可预览删除清单，`--json` 模式下需要 `--yes` 跳过交互确认。动图不参与感知聚类（只比对首帧会产生误判），但仍可通过逐字节比对被识别为完全重复。

## compare — 画质对比

```bash
pixshift compare A.jpg B.jpg [--json]
```

输出 MSE、PSNR、SSIM 与综合评级。宽高比相同的图片会被归一化到同一尺寸后比较；宽高比差异明显时命令直接失败，而不是给出会误导人的相似度。评级为「完美」要求像素与透明度完全一致，仅靠亮度 SSIM 不足以判定相等。

## info — 查看信息

```bash
pixshift info FILES... [--exif] [--json]
```

显示格式、尺寸、体积、颜色模式、透明通道与帧数。`--exif` 额外输出完整 EXIF。做自动化前先用它确认 `frame_count`，可以提前区分静态图与动图。

## optimize — 格式建议与执行计划

```bash
pixshift optimize INPUTS... [-r] [--json]
```

分析内容特征（照片、截图、图形、动画）后推荐输出格式，并给出各候选格式的体积预估。大图会先采样再试编码，因此分析速度与原图尺寸基本无关。

它的价值主要在自动化：`--json` 输出里每条结果都带一个可直接执行的 `plan`，交给 `apply` 就能落地。详见[脚本与 Agent 集成](automation.md)。
