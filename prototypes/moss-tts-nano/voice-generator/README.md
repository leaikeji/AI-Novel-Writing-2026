# T0-D VoiceGenerator 安全基准骨架

状态：**T0–T6 真实硬件尖峰已通过当前用户／本机风险接受口径；三个固定 seed、取消、崩溃恢复和 Nano 二次验证均有证据。产品能力尚未接线，仍为 `hide`。**

本目录是 T0-D 的隔离原型，不是 PawApp 运行时。它不安装 VoiceGenerator 依赖，不下载模型，不调用 Torch/Transformers，不生成音频。

## 文件

- `metadata-baseline.json`：固定 VoiceGenerator revision/大小/期望 hash，记录官方 CUDA/CPU 代码路径、默认 full codec 开销、M4 16 GB 门禁与项目自有音色描述。full codec revision 只是 2026-08-26 官方元数据观测，还没进入 T0-A 锁，不可当作可重建依赖。
- `test_benchmark_voice_generator.py`：验证 T0-A/T0-I 输入、资源预算、失败关闭、源文本扫描、严格结果契约与不覆盖证据。
- `macos_memory_watchdog.py`：一次性原生子进程 watchdog。通过 macOS `vm_stat`、`sysctl` 和 `proc_pid_rusage` 采集 RSS、`phys_footprint`、可用内存估算、pressure、swap、page-in/page-out，并处理取消、硬超时、heartbeat 停滞、Nano 重载和安全终止。
- `staged_runtime.py`：分阶段加载证明。只有 VoiceGenerator 子进程退出、退出回收通过、受限中间文件完成 regular-file／大小／SHA-256 校验后，才允许启动单独 codec 子进程。
- `test_macos_memory_watchdog.py`：仅用轻量 Python 子进程与注入式伪指标覆盖安全门禁；不导入或运行模型。
- `requirements-macos-arm64.lock.txt`：T1 独立 macOS/arm64 运行环境的精确版本锁；不进入项目主依赖。
- `mps_probe.py`：T1 独立环境中的无权重 MPS/BF16 算子探针；固定依赖版本、禁止 CPU fallback，并覆盖 embedding、RMSNorm、RoPE/掩码、SDPA 与采样基本闭包。
- `t1_orchestrator.py`：不导入 Torch 的 T1 前置／结果裁决器；要求 15 个基线样本，严格验证六类 MPS 操作闭包，并以原子、不可覆盖方式写证据。
- `artifact_manifest.py`：不联网的模型制品清单与本地快照校验器；固定官方仓库/40位 revision、严格文件 allowlist、大小、SHA-256、符号链接和 42/24 GiB 磁盘门禁。
- `artifact_downloader.py`：只允许 HTTPS、单份 staging、逐文件大小/SHA-256、同文件系统原子发布和不可覆盖 release marker；不使用会复制第二份权重的共享 cache。
- `range_downloader.py`：针对官方 `Accept-Ranges` 的可恢复并行下载器；多个 HTTPS 区间直接 `pwrite` 到同一个稀疏目标文件，不生成第二份合并副本，最终仍以完整 SHA-256 裁决。
- `t2_load_probe.py`：T2 单组件一次性离线加载子进程；禁止 `AutoProcessor`，要求本地 fixed snapshot、MPS/BF16 参数落位并只输出有界原子证据。
- `t2_orchestrator.py`：T2 串行入口；先逐文件复验官方 manifest、采集 15 个宿主基线，再以用户本机风险接受策略交给 watchdog 启动一个组件，并汇总不可覆盖证据。
- `t3_generate_probe.py`：T3 一次性 VoiceGenerator 子进程；使用固定中性输入与官方采样参数，只生成有界 audio codes，并以 safetensors／SHA-256 原子发布，不加载 codec。
- `t3_orchestrator.py`：T3 串行入口；复用 T2 的 Nano 容器互斥和 15 个基线，监控生成进程、60 秒恢复及 token artifact 身份。
- `mps_generation_adapter.py`：批次 1 的窄 MPS 兼容适配器；保持官方 forward/audio 采样，只修复 chained mask 的 MPS placeholder 问题，并在官方 `audio_end` 后结束声音资产。
- `t4_decode_probe.py`／`t4_orchestrator.py`：独立 Audio Tokenizer 进程，将已验 token 解码为 48 kHz 双声道 PCM16，并执行严格机器波形检查与 60 秒回收。
- `mps_codec_adapter.py`：保持大 decoder 为 MPS/BF16，只让小 quantizer 边界使用其所需的 float32，再一次性转回 BF16。
- `t5_fault_orchestrator.py`／`t5_crash_probe.py`：真实加载期取消、完整加载后 `SIGKILL` 和无资产／无残留恢复验证。
- `scripts/tts/voice_generator/validate_with_nano*.py`：T6 数据库无关 Nano 二次验证客户端；只输出 hash、模型身份和 PCM 标量，不发布音频。
- `test_mps_probe.py`：不导入 Torch 的 fail-closed 契约测试。
- `test_t1_orchestrator.py`：覆盖低内存、Nano 驻留、指标缺失、内存中止、MPS 不支持与证据不可覆盖。
- `test_artifact_manifest.py`：覆盖浮动 revision、未冻结清单、未知/缺失/篡改文件、符号链接和磁盘门禁。
- `test_artifact_downloader.py`：覆盖截断/过长、hash 错、HTTPS 降级、已存在目标和原子发布。
- `test_t2_load_probe.py`：覆盖 fixed revision、本地快照、符号链接、不可覆盖结果和错误信息脱敏。
- `test_t2_orchestrator.py`：覆盖回环 Nano 驻留探针、15 个基线和低内存风险接受状态不可与默认严格模式混淆。
- `scripts/tts/benchmark_voice_generator.py`：稳定 CLI；默认只生成 `blocked` 元数据基准，明确记录下载/导入/加载/候选生成/Nano 二次克隆均为 0。

## 计划 40 watchdog 边界

原型默认保留原数值门禁：critical pressure 立即终止、估算余量低于 3.5 GiB 立即终止、单次 swap 增长超过 512 MiB 立即终止、单次运行判定安全要求余量始终不少于 4 GiB。默认退出回收观测点为 10／30／60 秒。

计划 40 在 2026-08-30 获得当前用户、本机专用的风险接受裁决后，T2–T7 调用方必须显式设置 `enforce_headroom_swap_pageout_limits=False`。该模式仍完整记录余量、swap 与 page-out，但它们不再单独启动、终止或判定 PASS；基线 critical 拒绝启动，运行中持续 critical 达 20 秒、指标不可测、Nano 重载、heartbeat 停滞、输出预算、取消和硬超时仍然 fail closed。结果 JSON 明确写出 `resource_limits_enforced=false`，避免被误读成默认安全门禁下的通过。

计划 40 的 QA 契约已冻结 page-out 与回收门禁：连续 60 秒平均 page-out 不低于 256 pages/s 对应累计 `15,360` pages，退出后 60 秒系统可用内存不得低于基线中位数减 512 MiB。`SafetyPolicy` 仍要求调用者显式传入 `pageout_budget_pages=15360` 与 `recovery_tolerance_bytes=512 MiB`，防止其他调用方遗漏或静默改写门禁。

macOS pressure 内核指标不可读取时按 `measurement_unavailable` fail closed，不能从一个空闲内存百分比猜测 PASS。`MacOSMetricsSampler` 强制调用者提供权威 Nano residency probe；默认严格策略在基线余量不足 4 GiB 时拒绝启动，计划 40 的显式本机风险接受策略只保留 Nano、unknown/critical pressure 前置拒绝。指标和事件可序列化为 JSON；默认不采集子进程 stdout/stderr，显式需要时也只保存有界字节数与 SHA-256，超过预算会终止进程。错误证据只记录异常类型，不复制命令内容、模型提示词或密钥。

该原型只能裁决每次运行及 T0–T6 的硬件拓扑，不能单独升级为产品完成。三次冷运行、真实模型、机器音频和 Nano 二次验证已经通过；人工听检、`0035`、人物卡一键状态机、CAS、Edition 与删除仍由后续产品波次验收。

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
