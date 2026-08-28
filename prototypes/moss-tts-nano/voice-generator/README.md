# T0-D VoiceGenerator 安全基准骨架

状态：**元数据审计与 dry-run 可用；真实模型运行为 0，当前产品能力建议 `hide`**。

本目录是 T0-D 的隔离原型，不是 PawApp 运行时。它不安装 VoiceGenerator 依赖，不下载模型，不调用 Torch/Transformers，不生成音频。

## 文件

- `metadata-baseline.json`：固定 VoiceGenerator revision/大小/期望 hash，记录官方 CUDA/CPU 代码路径、默认 full codec 开销、M4 16 GB 门禁与项目自有音色描述。full codec revision 只是 2026-08-26 官方元数据观测，还没进入 T0-A 锁，不可当作可重建依赖。
- `test_benchmark_voice_generator.py`：验证 T0-A/T0-I 输入、资源预算、失败关闭、源文本扫描、严格结果契约与不覆盖证据。
- `scripts/tts/benchmark_voice_generator.py`：稳定 CLI；默认只生成 `blocked` 元数据基准，明确记录下载/导入/加载/候选生成/Nano 二次克隆均为 0。

## 安全命令

```bash
prototypes/moss-tts-nano/.venv/bin/python scripts/tts/benchmark_voice_generator.py \
  --fixture-manifest tests/fixtures/narration/benchmark_manifest.json \
  --output-dir docs/开发文档/证据/MOSS-TTS-Nano施工/T0-D
```

该命令可在未持有 `LOCK-VOICEGEN`/`LOCK-MODEL-ASSETS` 时执行，因为它不会触发真实模型操作。`--dry-run` 是同一安全路径的显式别名。`--replace-existing` 只能原子替换已能证明属于 T0-D、不含音频的同版契约文件。

## 可选代码路径扫描

`--source-audit-dir` 只读扫描一个已获授权、已固定的小型源码快照，要求：

```text
<dir>/docs/moss_voice_generator_model_card.md
<dir>/processing_moss_tts.py
<dir>/config.json
<dir>/pyproject.toml
```

扫描只解析文本/JSON，每文件上限 2 MiB，不会执行或导入远程代码。本工作包没有受权下载源码快照，因此正式 `metrics.json` 记录的是固定 URL 人工审计，而不是本地扫描或运行结果。

## 真实探测边界

真实探测不是加一个参数就应该偷偷执行的动作。必须先：

1. 由主代理串行授予 `LOCK-MODEL-ASSETS` 和 `LOCK-VOICEGEN`；
2. 将 full `MOSS-Audio-Tokenizer` 的 revision/所有权重 hash 加入隔离锁；
3. 在独立 Python 3.11 环境处理 VoiceGenerator 与 Nano 的 Torch/Transformers 冲突；
4. 模型和音频只能写入已验证的仓库外目录；
5. VoiceGenerator 进程完全退出后，主代理才能将候选 WAV hash 交给 Nano 克隆阶段。

详细时序与验收记录见 `T0-D/clone-retention.md`。
