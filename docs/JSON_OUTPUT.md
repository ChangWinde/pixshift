# JSON 输出契约

所有命令加 `--json` 后输出**单行 JSON**。字段定义稳定，可直接用于脚本与 agent；调用方式与推荐流程见[脚本与 Agent 集成](automation.md)。

正式的共享 envelope，以及 `tools` / `optimize` / `apply` / `prep` / `manifest` / `hash` / `verify` 的专用 JSON Schema 位于仓库 `docs/schemas/v1/`，CI 会用它校验真实命令输出。其他命令由共享 envelope 与本页字段契约覆盖；不声称每个命令都有独立 schema。

## 版本

当前 `schema_version` 为 `"1.1"`。同一版本内只做**新增字段**；删除字段或改变字段类型必须提升版本号。

1.1 相对 1.0 的变化：

- 批处理命令的 `errors` 从 `"文件名: 错误码"` 字符串改为 `{"input", "output", "error"}` 对象，且 `input` 是完整路径；
- `manifest` / `hash` 的每文件条目用 `size_bytes`（原 `bytes`），与 `info`、`video info` 对齐；
- `optimize` 的 `estimates` 拆成机器可用的 `format`（与 `convert -t` 同词表，或视频编码键）和用于展示的 `label`；
- dry-run 的 `preview` 列出全部任务（此前静默截断到 50 条），`strip` 的预览条目用 `input`（原 `file`）。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功，包含幂等跳过与 `keep` 计划 |
| `1` | 执行失败：已开始处理，至少一项失败，细节在 `errors` / `results` / `steps` |
| `2` | 参数被拒绝：写入任何文件之前就被拒（解析错误、选项冲突如 `conflicting_options`、各类 `invalid_*`、`nothing_to_do`、批次计划校验失败） |

退出码为 `2` 时，JSON 仍然正常输出，形如 `{"command", "ok": false, "error", "detail"}`。

## 公共字段

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 契约版本，当前 `"1.1"` |
| `command` | 命令标识，如 `compress`、`pdf.info`、`video.compress` |
| `ok` | 布尔值，是否成功 |
| `error` | `ok` 为 `false` 时的稳定错误码 |

批处理命令另有整型的 `skipped`（跳过的已存在输出）与 `ignored_generated`（自动排除的派生文件）计数。`dedup` 的 `skipped` 是安全原因数组，属于该命令特有的语义。

仅支持静态图的操作遇到多帧输入时，统一返回 `animated_input_not_supported`，且在替换任何输出文件之前就完成判断。

## 失败数组

`convert`、`compress`、`strip`、`resize`、`rotate`、`crop`、`watermark *` 的失败项统一为对象：

```json
{"input": "完整输入路径", "output": "计划输出路径或空串", "error": "稳定错误码"}
```

## 图片命令

### `convert`

`total`、`success`、`failed`、`skipped`、`ignored_generated`、`output_format`、`quality`、`input_bytes`、`output_bytes`、`duration_sec`、`errors`。

### `compress`

在 `convert` 字段基础上增加 `warnings` 数组，例如对 PNG/TIFF 使用 `--quality` 时给出 `quality_ignored_for_lossless`。

### `strip`

`total`、`success`、`failed`、`fields_removed`（清除的字段总数）、`input_bytes`、`output_bytes`、`duration_sec`、`errors`。

### `resize` / `rotate`

`total`、`success`、`failed`、`skipped`、`ignored_generated`、`duration_sec`、`errors`；`resize` 另有 `quality`、`input_bytes`、`output_bytes`，`rotate` 另有 `degrees`、`flip`。dry-run 返回 `mode: "dry_run"`、`pending` 与完整的 `preview`。

### `crop` / `watermark text|image`

`total`、`success`、`failed`、`input_bytes`、`output_bytes`、`errors`；dry-run 返回 `mode: "dry_run"` 与 `preview`。

### `montage`

`total_images`、`grid_size`、`canvas_size`、`output`、`output_bytes`。

### `compare`

`image_a`、`image_b`、`mse`、`psnr`、`ssim`、`quality_rating`、`quality_detail`、`comparison_size`、`resized_for_comparison`、`sampled_for_comparison`、`sample_scale`。

### `dedup`

分析模式（未加 `--delete`）：

`mode: "analyze"`、`total_files`、`duplicate_groups`、`duplicate_files`、`deletable_files`、`recoverable_bytes`、`skipped_invalid`、`preview`。

其中 `deletable_files` 与 `recoverable_bytes` **只统计经 SHA-256 确认逐字节相同的文件**；感知相似度仅供参考。

删除模式（`--delete`）：`mode: "delete"`、`deleted`、`kept`、`skipped`、`errors`。分析后发生变化的候选文件会进入 `skipped` 而不会被删除。干跑（`--delete --dry-run`）返回 `mode: "delete_dry_run"`、`would_delete`、`keep`。

### `optimize`

| 字段 | 说明 |
| --- | --- |
| `total` | 分析的文件总数 |
| `results[*].input` | 输入路径 |
| `results[*].media_type` | `image` 或 `video` |
| `results[*].recommended_format` | 推荐结果（展示用） |
| `results[*].recommended_reason` | 推荐理由 |
| `results[*].analysis` | 图片：尺寸、采样基准、透明通道、分类依据；视频：编码、时长、尺寸、每像素比特 |
| `results[*].estimates` | 候选格式的 `format`（机器词表）、`label`（展示名）、预估字节、压缩比与质量属性 |
| `results[*].plan.command` | `convert` / `compress` / `strip` / `video.convert` / `video.compress` / `keep`；该条目出错时为空对象 |
| `results[*].plan.arguments` | 结构化的命令参数 |

视频与动图的分析完全基于探测元数据，不做任何试编码，因此结果确定且可重复。`keep` 表示重新编码得不偿失，`apply` 会将其记为显式跳过。

## 系统命令

### `info`

`total` 与 `files` 数组；每个条目含 `frame_count`、`has_alpha`（索引色透明也算作透明通道）等属性。仅在指定 `--exif` 时包含 EXIF。

### `formats`

`input_extensions`、`output_formats`、`features.heif`、`features.avif_encode`、`defaults`（供客户端读取的通用默认值）。

### `doctor`

`all_ready` 与 `checks` 数组（每项含 `name`、`status`、`ok`、`required`）。可选依赖缺失会出现在 `checks` 中，但不会让命令失败。

## PDF 命令

`pdf merge`、`pdf extract`、`pdf compress`、`pdf concat`、`pdf info` 均遵循公共字段，并给出 `page_count`、`input_bytes`、`output_bytes`、`duration_sec` 等。`pdf concat` 的 `warnings` 会列出无法由拼接模型保留的文档级语义。

`pdf split` 另有：`mode`（`each` 或 `single`）、`total_pages`、`requested_pages`、`written_files`、`skipped_existing`、`input_bytes`、`output_bytes`、`duration_sec`。

## 视频命令

批处理类（`video convert` / `compress` / `thumbnail` / `extract-audio`）：`total`、`succeeded`、`failed`、`skipped_existing`，以及 `results` 数组（每项含 `input`、`output`、`ok`、`input_bytes`、`output_bytes`、`error`；转码/压缩另含 `audio_policy` 与 `audio_action`）。

单文件类（`video trim` / `gif` / `concat`）直接在顶层给出 `input`、`output`、`ok`、`input_bytes`、`output_bytes`、`error`；`concat` 另有 `clips`。

`video info` 返回 `files` 数组，每项含 `duration_sec`、`width`、`height`、`video_codec`、`audio_codec`、`fps`、`bit_rate`、`container`、`stream_count`、`size_bytes`、`error`。

未安装 ffmpeg 时，所有视频命令返回 `error: "ffmpeg_missing"`。

## Agent 命令

### `verify`

跨图片、PDF、视频使用同一质量门。返回 `passed`、`media_type`、源/候选体积、`thresholds`、`metrics`（SSIM、PSNR、是否采样）、布尔结构 `checks` 与数值 `observations`。PDF checks 包括文本层、链接、注释、表单、附件与 outline；带音轨的视频会检查声道/采样率并在 `observations.audio_snr_db` 披露流式差分信噪比（至少 20 dB）。门槛未通过是退出码 `1`；不支持的媒体组合或非法阈值是退出码 `2`。

### `tools`

`total` 与 `tools` 数组，每项含 `name`、`description`、`when_to_use`、`input_summary`，以及 `annotations`（`readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`，本地工具的 `openWorldHint` 恒为 `false`）。

### `apply`

`total`、`applied`、`skipped`、`failed`、`dry_run`，以及 `steps` 数组（每项含 `input`、`plan_command`、`arguments`、`output`、`ok`、`skipped`、`error`、`detail`）。

接受的计划文档：`optimize --json` 的输出、单个计划对象、`{"plans": [...]}` 包装、计划对象数组。视频步骤在缺少 ffmpeg 时返回 `ffmpeg_missing`；`keep` 步骤计入 `skipped`，`detail` 为 `plan_keep`。

### `prep`

`total`、`success`、`skipped`、`failed`、`ignored_generated`、`output_dir`、`dry_run`，以及 `items` 数组（每项含 `input`、`output`、`ok`、`skipped`、`input_bytes`、`output_bytes`、`sha256`、`width`、`height`、`error`）。

### `manifest`

`total` 与 `files` 数组（每项含 `path`、`sha256`、`size_bytes`、`format`、`width`、`height`、`mode`、`has_alpha`、`frame_count`、`sensitive_exif_keys`、`error`）。

### `hash`

`total`、`algorithm`，以及 `files` 数组（每项含 `path`、`algorithm`、`digest`、`size_bytes`、`error`）。
