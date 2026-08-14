# PDF

PDF 能力由内置的 PyMuPDF 提供，无需额外安装。所有子命令都在 `pixshift pdf` 下。

## merge — 图片合成 PDF

```bash
pixshift pdf merge INPUTS... -o out.pdf [--json]
```

| 参数 | 说明 |
| --- | --- |
| `-o, --output` | 输出 PDF 路径（必填） |
| `--page` | 页面大小：`a4`（默认）/ `a3` / `a5` / `letter` / `legal` / `b5` / `fit` |
| `-q, --quality` | 图片嵌入质量 1–100，默认 95 |
| `--margin` | 页边距，单位为点，默认 20 |
| `--landscape` | 横向页面 |
| `-r, --recursive` | 递归扫描子目录中的图片 |

`--page fit` 让页面尺寸跟随图片尺寸，适合拼接漫画、长图；固定纸张则适合打印。

未经变换的 JPEG 会**直接嵌入原始字节**，不解码也不重新编码：速度更快、体积更小，且没有二次压缩损失。这条快路径会剥掉 EXIF、XMP、注释等元数据段，因此拍摄信息不会随图片泄漏进 PDF。需要旋转校正、CMYK 转换、含透明通道，或显式要求 `-q` 低于 95 时，会自动回落到常规的重编码路径。

## extract — 页面导出为图片

```bash
pixshift pdf extract input.pdf -o 输出目录 [--json]
```

| 参数 | 说明 |
| --- | --- |
| `-t, --format` | `png`（默认）/ `jpg` / `webp` / `tiff` |
| `--dpi` | 渲染精度，默认 150；打印级用 `--dpi 300` |
| `--pages` | 指定页码，如 `'1-5,8,10-12'` |
| `--prefix` | 输出文件名前缀 |

DPI 直接决定渲染耗时与产物体积。150 适合屏幕查看，300 以上仅在需要印刷质量时使用。

## split — 拆分文档

```bash
pixshift pdf split report.pdf -o ./pages/ [--pages '1-5,8'] [--single] [--json]
```

默认每个选中页输出一个独立 PDF（命名为 `{文件名}_page_0001.pdf`）；加 `--single` 则把选中的页合并成一个文档。`--pages` 省略时处理全部页面。

## compress — 压缩

```bash
pixshift pdf compress input.pdf [-o out.pdf] [--json]
```

| 参数 | 说明 |
| --- | --- |
| `-p, --preset` | `lossless` / `light` / `medium`（默认）/ `heavy` / `extreme` |
| `--image-quality` | 1–100，覆盖预设的图片质量 |
| `--max-dpi` | 限制内嵌图片的最大 DPI |
| `--target-size` | 目标体积上限，如 `2MB` |

`lossless` 只做结构优化（去重、清理、压缩流），不触碰图片；其余预设会按对应质量重新编码内嵌图片。带软掩膜（透明度）的图片一律跳过重编码，避免破坏透明效果。

**`--target-size` 在预算内取最高画质。** 搜索顺序是：先尝试纯无损结构优化，不够小再从最高到最低检查完整的有限质量区间。编码后体积并不严格单调，因此不会用二分搜索猜测最高可行档位。原文件本身已在预算内时会原样复制；预算无论如何达不到时返回 `target_size_unreachable` 并且不产出文件。该参数与 `-p`、`--image-quality` 互斥。

ICC profile 是解释像素颜色所必需的功能性数据，不按隐私元数据删除。图片合并或 PDF 图片重编码会保留可安全直拼的 ICC，其他情况经 LittleCMS 转为带 profile 的 sRGB；无法解释的 profile 会跳过重编码或报告失败，而不是静默改色。

## concat — 拼接多个 PDF

```bash
pixshift pdf concat a.pdf b.pdf -o joined.pdf [--json]
```

按命令行给定的顺序首尾拼接。`-r` 可递归扫描目录中的 PDF。
输出文件不能同时是任一输入；目录扫描时也一样。若需重复生成，请把输出放在
扫描目录外，避免把真实源文档误当成旧产物覆盖。

!!! note "merge 与 concat 的区别"
    `merge` 的输入是**图片**，产出一个新 PDF；`concat` 的输入是**已有 PDF**，把它们连成一个文档。

## info — 查看文档信息

```bash
pixshift pdf info input.pdf [--pages] [--json]
```

输出页数、PDF 版本、是否加密、体积等。`--pages` 额外列出每页的尺寸与图片数量。

加密文档会在处理前给出稳定的错误提示，而不是中途失败留下半成品。

!!! warning "压缩与拼接不是安全净化"
    `pdf compress` 和 `pdf concat` 以保留文档语义为目标，可能继续保留链接、
    附件、JavaScript 或启动动作。它们不会执行这些动作，但下游阅读器可能会；
    不要把产物当作已 sanitize 的安全分享副本，只在可信阅读器中打开未知 PDF。
