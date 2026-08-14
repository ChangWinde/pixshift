# 脚本与 Agent 集成

任何命令加 `--json` 就进入机器模式：输出**单行 JSON**，字段稳定，失败时 `ok` 为 `false` 且退出码非零。字段级定义见[JSON 输出契约](JSON_OUTPUT.md)，本页说明如何组织调用。

## 退出码

| 退出码 | 含义 | 典型场景 |
| --- | --- | --- |
| `0` | 成功 | 包含幂等跳过、`keep` 计划这类「什么都不用做」的情况 |
| `1` | 执行失败 | 已经开始干活，至少一个文件失败；细节在 `errors` / `results` / `steps` 里 |
| `2` | 参数被拒绝 | 尚未写入任何文件就被拒：参数解析错误、选项冲突、批次计划校验失败 |

区分 `1` 和 `2` 的意义在于重试策略：`2` 是调用方自己的问题，重试无益，必须改参数；`1` 可能只是部分文件损坏，值得逐条检查 `errors`。

## 失败条目的形状

批处理命令（`convert`、`compress`、`strip`、`resize`、`rotate`、`crop`、`watermark`）把失败项统一放在 `errors` 数组里，每项是一个对象：

```json
{"input": "/data/photos/broken.png", "output": "/out/broken_compressed.png", "error": "cannot identify image file"}
```

`input` 是完整路径，可直接用于重试或告警，不需要再去拼接目录。

## 发现 → 计划 → 执行 → 校验

这是推荐的自动化闭环，四步都有稳定的机器接口。

### 1. 发现能力

```bash
pixshift tools --json
```

返回工具目录，每个条目带用途说明、参数摘要和副作用标注（`readOnlyHint`、`destructiveHint`、`idempotentHint`）。Agent 可据此判断哪些命令可以自由调用、哪些需要用户确认。

### 2. 生成计划

```bash
pixshift optimize ./media -r --json
```

对每个文件给出分析结论和一个**可执行的 `plan`**。图片会试编码采样以预估体积；视频和动图只读元数据，不做任何试编码，因此速度快且结果确定。

计划的 `command` 取值：`convert`、`compress`、`strip`、`video.convert`、`video.compress`，以及 `keep`。`keep` 表示「重新编码得不偿失」，是明确的结论而不是失败。

### 3. 执行计划

```bash
# 先干跑，确认输出路径和步骤无误
pixshift optimize ./media -r --json | pixshift apply --plan - --dry-run --json

# 确认后再执行
pixshift optimize ./media -r --json | pixshift apply --plan - -o ./out --json
```

`apply` 接受四种输入：`optimize --json` 的完整输出、单个计划对象、`{"plans": [...]}` 包装，或计划对象数组。计划文件可用 `--plan plan.json`，也可以用 `--plan -` 从标准输入读。

不指定 `-o` 时，输出遵循与命令行一致的命名规则放在源文件旁边：`convert` 换扩展名，`compress` 加 `_compressed`，`strip` 加 `_clean`。

`--dry-run` 会完整校验计划词表、规划输出路径、检测输出冲突，但不写任何文件——**视频步骤即使在没有 ffmpeg 的机器上也能这样验证**。

### 4. 校验结果

```bash
pixshift hash ./out -r --json        # 内容哈希，用于前后审计
pixshift manifest ./out -r --json    # 清单：尺寸、格式、帧数、敏感 EXIF 概览
pixshift compare a.jpg b.jpg --json  # 两图画质对比
pixshift verify a.jpg out.webp --min-ssim 0.99 --json  # 跨媒体质量门
```

## 一步到位的交付流程

如果需求是「把素材整理成可交付资产」，不必自己拼装上面四步：

```bash
pixshift prep ./raw -r -o ./deliver --max-size 2048 -t webp --json
```

`prep` 一次完成限宽缩放、格式转换、隐私元数据清理，并为每个产物给出 SHA-256。默认清理隐私元数据并转换/嵌入 sRGB；需要保留时分别加 `--keep-metadata`、`--color-space preserve`。

## 幂等与重复执行

批处理命令跳过已存在的输出，除非加 `--overwrite`。目录扫描会自动排除本次操作自己产生的派生文件、聚合输出和水印素材，因此**同一条命令连续执行两次是安全的**：第二次不会重复编码，也不会把产物当成新的输入再处理一遍。JSON 输出中 `skipped` 与 `ignored_generated` 分别计数，便于确认这一点。

显式传入的文件参数永远优先于这些自动排除规则。

## 脚本示例

```bash
#!/usr/bin/env bash
set -euo pipefail

SRC=${1:?用法: prepare.sh <素材目录>}

# 参数或环境问题会以退出码 2 立即失败，不会产生半成品
pixshift doctor --json > doctor.json

# 生成可交付资产并留存清单
pixshift prep "$SRC" -r -o ./deliver --max-size 2048 -t webp --json > prep.json

# 交付前核对：所有产物的内容哈希
pixshift hash ./deliver -r --json > deliver-hashes.json

echo "完成：$(jq '.success' prep.json) 个文件"
```

## MCP 适配器

仓库内置一个轻量的 MCP（Model Context Protocol）stdio 适配器，把工具目录映射为 MCP 工具：

```bash
python -m pixshift.mcp
```

它只是把 MCP 调用转成 CLI 调用并回传 JSON，不重新实现任何引擎逻辑或安全策略——因此 CLI 的全部约定（退出码、原子写入、幂等、错误词表）在 MCP 侧同样成立。适配器严格校验 JSON-RPC 2.0 请求与工具参数，只接受 CLI 返回的 JSON 文档；每次调用都在隔离的子进程组中运行，超时会终止整个进程组，避免遗留 worker 或 ffmpeg。
