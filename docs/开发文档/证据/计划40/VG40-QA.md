# VG40-A-QA：MOSS-VoiceGenerator 16 GiB 可执行验收矩阵

状态：**2026-08-31 T0–T7 的机器、数据库、运行时、正式人物、Edition 和浏览器矩阵已执行；当前长期四章合计 `502/502` 句段可播，人物卡与播放器均显示沈砚 generated Voice Version。作者听检仍未执行，质量总 Gate 保持 `VG40_AUTHOR_LISTENING_PENDING`；其余产品 Gate 见 `VG40-FINAL.md`。**

- 对应计划：计划 40《MOSS-VoiceGenerator 16 GiB 安全运行、自查优化与正式人物音色闭环计划》
- 工作包：`VG40-A-QA`
- 性质：只读审计计划 35 证据与现有测试后形成的测试设计
- 当前已执行：T0–T7 的模型固定、依赖安装、真实加载、生成、解码、三次冷运行、取消、崩溃恢复、Nano 二次验证、`0035`、产品 API/runtime、长期部署、正式人物生成、四章 Edition 和四视口浏览器验收
- 当前未执行：作者对 generated 样音与官方对照音色的主观听检；正式 generated 音色按计划只验证删除投影，不物理删除
- 适用顺序：`T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7`
- 事实边界：较早阶段通过只授权进入下一阶段，不自动放行产品代码、`0035`、长期部署或人物卡按钮

## 1. 审计依据与沿用基线

本文沿用计划 35 已验证且仍适用于 generated 私人音色的四项基线，不另造第二套规则：

1. Nano 机器音频入口沿用 `narration-audio-pipeline/1`：48 kHz、双声道、16-bit PCM WAV；时长 80–180000 ms；RMS 必须高于 `-55 dBFS`；削波样本比例不得超过 `0.001`。
2. 异步结果只有在模型身份、revision、参数 digest、输入／输出 hash 和 `ModelRun` 完整一致后才可成为机器验证版本；失败不静默改参数重试。
3. CAS 漂移保留已生成结果但不得覆盖作者新选择，状态为 `ready_unapplied`；旧 Edition 继续冻结其原 Voice Version 身份。
4. generated Profile 进入计划 35 的 novel-scoped 私人音色生命周期；官方音色不可删除，物理删除使用精确资产计划并保留不可变审计证据。

计划 35 的候选证据只能证明上述基础设施在隔离 Nano 流程中成立，不能证明 VoiceGenerator、MPS、分阶段 codec 或 16 GiB 安全性成立。

## 2. 裁决词典

### 2.1 单项状态

| 状态 | 精确定义 |
| --- | --- |
| `NOT_RUN` | 尚未执行，不能用于通过或失败结论 |
| `RUNNING` | 已开始但证据包尚未闭合 |
| `PASS` | 本项所有必需断言通过，原始证据、命令、版本和 hash 完整 |
| `HOLD` | 尚不能作结论；原因只能是测量不可靠、作者听检未完成、外部前置未满足或性能超标但安全性仍成立 |
| `BLOCKED` | 已有可复核事实证明当前拓扑无法安全或正确继续；必须停止该拓扑 |

测试断言失败可以在运行记录中写 `FAIL`，但阶段汇总必须把它映射为有稳定原因码的 `BLOCKED` 或仍可补证的 `HOLD`，不能只留一个不可解释的失败词。

### 2.2 稳定原因码

| 原因码 | 裁决 |
| --- | --- |
| `VG40_EVIDENCE_INCOMPLETE`、`VG40_MEASUREMENT_UNRELIABLE` | `HOLD` |
| `VG40_AUTHOR_LISTENING_PENDING` | `HOLD` |
| `VG40_SAFE_BUT_SLOW` | `HOLD`，不得开放一键产品入口 |
| `VG40_PREREQUISITE_NOT_READY` | `HOLD` |
| `VG40_RUNTIME_UNSUPPORTED`、`VG40_MPS_UNSUPPORTED` | 当前拓扑 `BLOCKED_RUNTIME` |
| `VG40_MEMORY_ABORTED`、`VG40_MEMORY_LIMIT_EXCEEDED` | 当前拓扑 `BLOCKED_MEMORY` |
| `VG40_CODEC_STAGE_BOUNDARY_ABSENT` | 分阶段拓扑 `BLOCKED_RUNTIME` |
| `VG40_AUDIO_MACHINE_INVALID`、`VG40_AUDIO_LISTENING_REJECTED` | `BLOCKED_QUALITY` |
| `VG40_CAS_SAFETY_VIOLATION`、`VG40_EDITION_IDENTITY_MUTATED` | `BLOCKED_RUNTIME`，产品化停止 |
| `VG40_DELETE_SCOPE_VIOLATION`、`VG40_RECOVERY_DID_NOT_CONVERGE` | `BLOCKED_RUNTIME`，产品化停止 |

### 2.3 总 Gate 映射

| Gate | PASS 必需项 | 非 PASS 映射 |
| --- | --- | --- |
| `VG16-FEASIBILITY` | T0–T4 通过且完成一个真实短样音 | 运行／codec 阻断写 `BLOCKED_RUNTIME`；内存终止写 `BLOCKED_MEMORY` |
| `VG16-SAFE` | T2、T4、T5 的三次冷运行和回收全部通过 | 指标缺失为 `HOLD_MEASUREMENT`；越线为 `BLOCKED_MEMORY` |
| `VG16-QUALITY` | T3 机器质量、T4 解码、T6 Nano 验证和作者听检均通过 | 未听检为 `HOLD`；音频或听检失败为 `BLOCKED_QUALITY` |
| `VG16-PERF` | 首次短样音 `≤300 s`，后续各次 `≤180 s` | 安全但超时为 `SAFE_BUT_SLOW` |
| `VG16-PRODUCT` | T7 的一键、恢复、CAS、Edition 和删除全部通过 | 任一权威数据安全项失败为 `BLOCKED_RUNTIME` |
| `VG16-FINAL` | 上述五项全部 PASS | 仅允许计划 40 已冻结的 `HOLD_MEASUREMENT`、`SAFE_BUT_SLOW`、`BLOCKED_RUNTIME`、`BLOCKED_MEMORY`、`BLOCKED_QUALITY` |

## 3. 统一运行身份与证据目录

每次运行 ID 使用 `vg40-<t0..t7>-<UTC YYYYMMDDTHHMMSSZ>-<8位随机十六进制>`。禁止复用目录或覆盖旧运行。所有时间字段为 UTC RFC 3339，所有单调耗时使用 `monotonic_ns` 差值。

仓库内证据固定为：

```text
docs/开发文档/证据/计划40/
├── VG40-OFFICIAL.md
├── VG40-QA.md
├── runs/<run_id>/
│   ├── run.json
│   ├── command.json
│   ├── environment.json
│   ├── model-manifest.json
│   ├── timeline.ndjson
│   ├── memory-summary.json
│   ├── audio-inspection.json
│   ├── fault.json
│   ├── recovery.json
│   ├── assertions.json
│   ├── listening.md
│   ├── stderr-summary.txt
│   └── hashes.sha256
├── database/<run_id>-migration-and-state.json
├── browser/<run_id>-<viewport>-<screen>.png
└── VG40-FINAL.md
```

未产生的可选文件从清单省略，不能创建空文件冒充证据。完整模型日志、完整人物资料、正文、音频、数据库 dump 和密钥不得进入 Git。

仓库外受控产物固定为：

```text
/Users/liujia/Library/Application Support/AI小说世界2026/voice-generator-vg40/
├── runtime/
├── models/
├── runs/<run_id>/
│   ├── sample.wav
│   ├── intermediate.safetensors
│   └── raw-operator-logs/
└── staging/
```

仓库证据只引用受控产物的逻辑名、字节数和 SHA-256，不写绝对私人输入内容。正式 generated 音频进入 PawApp 媒体存储，不复制进证据目录。

## 4. 证据 schema 与内存断言

### 4.1 `run.json`

必填：`schema_version=vg40-run-evidence/1`、run ID、T0–T7 stage、status、verdict、reason code、40 位 Git commit、dirty paths digest、主机 machine／物理内存／macOS build、topology、seed、开始／结束／wall time、隐私布尔值、证据文件表和断言汇总。

若运行时工作区非 clean，`dirty_paths_sha256` 必须是按路径排序后对“相对路径、文件状态、内容 hash”形成的总 digest；不得把不相关 diff 内容复制进证据。

### 4.2 `timeline.ndjson`

每行使用 `vg40-memory-sample/1`，必含 run ID、单调 sequence、UTC 时间、`monotonic_ns`、phase、generator／codec／Nano PID、RSS、`phys_footprint`、系统可用内存、memory pressure、swap used、page-in／page-out total、`nano_model_loaded` 和 progress counter。

phase 只能是：`baseline`、`load_generator`、`generate`、`unload_generator`、`load_codec`、`decode`、`unload_codec`、`nano_validate`、`recovery`。

采样周期固定为 2 秒，进程启动前至少采 15 个基线样本，退出后分别保留 10、30、60 秒样本。缺少 `phys_footprint`、系统余量、swap 或 page-out 任一核心指标时，`VG16-SAFE` 必须为 `HOLD_MEASUREMENT`。

### 4.3 内存断言

- watchdog 在启动前发现 `memory_pressure=critical` 时立即拒绝创建子进程；运行中首次 critical 开始 20 秒固定观察窗，持续达到 20 秒才终止，窗口内恢复则记录开始／清除事件。系统／模型进程持续失去响应、冻结硬超时、Nano 意外重新加载或进程无进展仍立即终止。
- 系统余量、swap delta 和 page-out 必须继续逐样本记录，但依照用户 2026-08-30 的本机风险接受裁决，不再单独构成 T2–T7 的启动、终止或 PASS 数值门禁。
- PASS：无 OOM／jetsam／系统卡死／critical pressure／持续失去响应，Nano／VoiceGenerator 驻留重叠为 0，且所有规定阶段与回收证据完整。
- 回落 PASS：退出后 60 秒 generator／codec PID 均不存在，其 `phys_footprint=0`，重模型租约为空，系统可用内存已记录且没有仍在恶化的 critical pressure／持续失去响应；不再设置固定可用内存差值门禁。
- `VG16-SAFE` 通过时必须限定表述为“当前用户风险接受条件下，本机固定拓扑三次实测通过”，不得外推为所有 16 GiB Mac 的通用安全认证。

## 5. 音频证据与质量门禁

`audio-inspection.json` 使用 `vg40-audio-inspection/1`，至少包含逻辑资产名、SHA-256、字节数、容器、codec、sample rate、channels、sample width、frame count、duration、peak／RMS dBFS、DC offset、clipped count／fraction、non-finite sample count、leading／trailing silence和处理策略 fingerprint。

VoiceGenerator 原始样音和 Nano 验证输出分别检查：

| 项目 | PASS |
| --- | --- |
| 容器 | 可完整解析，无截断、额外帧或损坏 header |
| PCM | 48 kHz、双声道、16-bit signed PCM；不同原生输出必须经固定转码，原始与转码 hash 均保留 |
| 时长 | T3/T5 中性样音 3–5 秒；T7 冻结短句不得为 0 或超过 180 秒 |
| 有限值 | `non_finite_sample_count=0` |
| 静音 | `rms_dbfs > -55.0` |
| 严重削波 | `clipped_fraction ≤0.001` |
| DC 偏移 | 绝对均值 `<0.05` full scale；越线阻断，不静默滤除 |
| 内容 | ASR 只作诊断，不以第三方 ASR 相似度作为唯一质量门禁 |

若原始输出不是目标 PCM，允许一个审计过的确定性转换步骤，但不能篡改生成语义；转码失败、输入 hash 不符或固定工具链 identity 不符均为机器质量失败。

机器指标不能证明音色符合人物。T3/T4 至少由作者听一条中性样音；T7 必须听主角 generated 样音和同文本官方音色对照。`listening.md` 只记录 run ID、音频 digest／盲化顺序、可懂度／人物一致度／自然度／跨两句身份一致性各 `1..5`、六类阻断性伪影和 `accept|reject|not_completed`。

T7 听检 PASS 要求四项均至少 3，爆音、断裂、金属颤振、吞字、异常重复、明显噪声全部为否，作者结论为 `accept`。作者未完成时只能 `VG40_AUTHOR_LISTENING_PENDING`，不能由代理代替。

## 6. T0–T4 可执行矩阵

### `VG40-T0`：只读冻结

前置：无；禁止下载和安装。核验三个官方仓库 fixed revision、许可证、allowlist、LFS/Xet size、已知 hash、权重 dtype、设备选择、remote code、codec 加载时机、分阶段 token 边界、MPS 不支持算子和量化来源。磁盘下载前至少 42 GiB，预计完成后至少 24 GiB。

未来命令（对应脚本在进入 T0 前实现并纳入测试）：

```bash
.venv/bin/python scripts/tts/voice_generator/freeze_official.py \
  --output docs/开发文档/证据/计划40/VG40-OFFICIAL.md \
  --manifest-output docs/开发文档/证据/计划40/model-source-manifest.json \
  --no-download
git diff --check -- docs/开发文档/证据/计划40
```

PASS：来源／revision 完整，分阶段边界有源码证据且没有未审计执行面。无分阶段边界只阻断该拓扑，不授权危险 CPU/FP32 同驻留实测。

### `VG40-T1`：依赖与空载原型

前置：T0 PASS；独立 runtime 不修改项目 `.venv`。固定环境变量：

```text
VG40_RUNTIME_ROOT=/Users/liujia/Library/Application Support/AI小说世界2026/voice-generator-vg40/runtime
VG40_MODEL_ROOT=/Users/liujia/Library/Application Support/AI小说世界2026/voice-generator-vg40/models
VG40_RUN_ROOT=/Users/liujia/Library/Application Support/AI小说世界2026/voice-generator-vg40/runs
VG40_EVIDENCE_ROOT=/Users/liujia/Documents/AI小说世界2026-vg40/docs/开发文档/证据/计划40
VG40_OFFLINE=1
VG40_DEVICE=mps
VG40_DTYPE=bfloat16
```

未来命令：

```bash
"$VG40_RUNTIME_ROOT/bin/python" scripts/tts/voice_generator/run_spike.py \
  --stage t1 --device mps --dtype bfloat16 --offline \
  --evidence-root "$VG40_EVIDENCE_ROOT" --run-root "$VG40_RUN_ROOT"
```

注入 MPS unavailable、BF16 unsupported、attention operator unsupported 和明确 CPU fallback。任何静默 fallback 都失败；可能改变峰值的 fallback 必须回到静态评估。PASS 要求依赖锁、版本、设备 probe 和空载回收完整，且不读取权重。

用户于 2026-08-30 明确授权 T1 忽略 4 GiB 启动条件。窄例外只适用于不读取权重的固定小张量探针：15 个基线样本均至少 2.5 GiB，MPS allocator 上限 5%，2.0 GiB 硬停，swap 增量上限 256 MiB，120 秒硬超时。T1 已按该历史契约通过；用户随后另行授权 T2–T7 取消固定剩余内存／swap 数值门禁，原 T1 证据不得回写。

### `VG40-T2`：单模型只加载

前置：T1、模型下载 hash、磁盘门禁均 PASS。未来在两个不同进程执行：

```bash
"$VG40_RUNTIME_ROOT/bin/python" scripts/tts/voice_generator/run_spike.py \
  --stage t2 --component voice-generator --device mps --dtype bfloat16 \
  --model-root "$VG40_MODEL_ROOT" --offline \
  --evidence-root "$VG40_EVIDENCE_ROOT" --run-root "$VG40_RUN_ROOT"
"$VG40_RUNTIME_ROOT/bin/python" scripts/tts/voice_generator/run_spike.py \
  --stage t2 --component audio-tokenizer --device mps --dtype bfloat16 \
  --model-root "$VG40_MODEL_ROOT" --offline \
  --evidence-root "$VG40_EVIDENCE_ROOT" --run-root "$VG40_RUN_ROOT"
```

注入权重 hash 错、缺文件、错误 revision、加载超时、load 中 watchdog 终止和 `SIGKILL`。PASS 要求每个模型单独完成加载、退出 60 秒回落、无残留进程／租约。任一单模型发生 OOM、critical pressure、持续失去响应或回收失败，立即 `BLOCKED_MEMORY`，不进入 T3；仅低于旧 4 GiB 数值不再阻断。

### `VG40-T3`：最短真实生成

前置：T2 两组件 PASS；使用非正式中性描述和 3–5 秒短句，不连接小说数据库。输入只保存 digest，版本为 `vg40-neutral-voice-input/1`。

```bash
"$VG40_RUNTIME_ROOT/bin/python" scripts/tts/voice_generator/run_spike.py \
  --stage t3 --topology mps-bf16-staged-process-v1 --seed 104729 \
  --input-fixture vg40-neutral-voice-input/1 \
  --model-root "$VG40_MODEL_ROOT" --offline \
  --evidence-root "$VG40_EVIDENCE_ROOT" --run-root "$VG40_RUN_ROOT"
```

注入空 token、NaN、零字节、损坏 WAV、异常静音、削波和硬超时。PASS 要求真实输出 3–5 秒、机器质量通过、运行和输入 fingerprint 完整；作者听检未完成不阻断 FEASIBILITY，但 QUALITY 保持 HOLD。

### `VG40-T4`：分阶段解码

前置：T3 PASS。

```bash
"$VG40_RUNTIME_ROOT/bin/python" scripts/tts/voice_generator/run_spike.py \
  --stage t4 --topology mps-bf16-staged-process-v1 --seed 104729 \
  --input-fixture vg40-neutral-voice-input/1 --require-zero-residency-overlap \
  --model-root "$VG40_MODEL_ROOT" --offline \
  --evidence-root "$VG40_EVIDENCE_ROOT" --run-root "$VG40_RUN_ROOT"
```

必验 token schema／shape／dtype／长度／hash，临时写入、fsync、原子 rename，generator 退出和回落后才启动 codec，驻留交集为零，codec 输出通过机器质量。注入 token 截断／篡改、残留引用、codec 前／中崩溃和输出后响应丢失；只可复用 hash 完整中间结果。

## 7. T5–T7 可执行矩阵

### `VG40-T5`：三次冷运行、取消与恢复

前置：T4 PASS。三个成功 seed 固定为 `104729`、`130363`、`155921`；每次都从无重模型驻留开始。

```bash
for vg40_seed in 104729 130363 155921; do
  "$VG40_RUNTIME_ROOT/bin/python" scripts/tts/voice_generator/run_spike.py \
    --stage t5 --topology mps-bf16-staged-process-v1 --seed "$vg40_seed" \
    --input-fixture vg40-neutral-voice-input/1 --cold-start \
    --model-root "$VG40_MODEL_ROOT" --offline \
    --evidence-root "$VG40_EVIDENCE_ROOT" --run-root "$VG40_RUN_ROOT"
done
```

三次成功要求音频 hash 互不相同、各自满足 SAFE、无 OOM／critical pressure／系统失去响应，首次不超过 300 秒，后两次分别不超过 180 秒。安全但超时写 `VG40_SAFE_BUT_SLOW`。

取消只在 `queued`、`analyzing_character`、`waiting_for_heavy_runtime` 和 generator 输出发布围栏前的 `generating_voice` 可接受。围栏后 `cancellable=false`，重复取消返回当前资源，不删除已接受资产。围栏前取消必须无 Voice Version、无绑定变化、无残留进程／租约／临时文件。

### `VG40-T6`：Nano 二次验证

前置：T5 三次 SAFE；VoiceGenerator 和 codec 已完全退出；计划 35 CORE 在隔离环境 ready。

```bash
.venv/bin/python scripts/tts/voice_generator/validate_with_nano.py \
  --run-id "$VG40_SOURCE_RUN_ID" \
  --source-root "$VG40_RUN_ROOT" \
  --evidence-root "$VG40_EVIDENCE_ROOT" \
  --require-generator-unloaded --require-exclusive-heavy-lease
```

PASS：Nano requested/actual 模型和 revision 一致，source sample hash、参数 digest、输出 hash、`ModelRun`、版本验证 fingerprint 完整，Nano 与 generator 驻留无重叠。Nano 失败不得创建可用 Version 或改变绑定，不允许静默换官方音色或默认参数重试。

### `VG40-T7`：正式人物产品闭环

前置：`VG16-SAFE + VG16-QUALITY + VG16-PERF` PASS；计划 35 已在长期环境通过；`0035` 隔离迁移与全量回归通过；正式悬疑小说两卷四章、至少两主角四配角均已完成正式 revision，写作阶段从未进入 TTS。

T7 分两部分：

1. 隔离 PostgreSQL／隔离媒体先完成所有故障、CAS 和删除写测试。
2. 长期环境只对用户指定的一位正式主角执行一次成功生成；不注入故障，不删除作者要保留的正式音色。

PASS：一次点击形成 Brief、Draft、生成、Nano 验证、generated Version 和 CAS；旧官方 Edition 身份不变；新 Edition 使用 generated Version；浏览器和作者听检通过；隔离副本完成删除生命周期。

## 8. 故障注入与恢复矩阵

| 注入点 | 注入方式 | 预期终态／恢复 | 不变量 |
| --- | --- | --- | --- |
| command 持久化后、spawn 前 | runner 抛错 | `failed_runtime_unavailable`，可重试 | 原绑定不变，无资产 |
| Nano 未卸载 | readiness fixture | 保持 waiting 后有界失败 | 不启动 generator |
| 重模型租约冲突 | 持有另一 owner lease | waiting／有界失败 | 单租约，无并行重模型 |
| generator load 中 | watchdog／`SIGTERM` | `failed_memory_safety` 或 cancelled | 子进程退出、临时文件清理 |
| generator 无响应 | 冻结 progress counter | watchdog 终止 | 不产生 Version |
| token 写前 | 进程崩溃 | 可从命令重试 | 不接受部分 token |
| token fsync 后、ack 前 | 丢响应 | 查询 hash 后精确恢复 | 不重复发布两个 token 资产 |
| generator 退出前残留 codec 引用 | mock ref probe | 当前拓扑失败 | 不启动 codec |
| codec load／decode 中 | `SIGKILL` | 同一已验 token 可重试 | hash 不变、无半成品发布 |
| WAV 写后、DB 前 | 丢响应 | storage identity 对账后恢复 | 不重复创建媒体 |
| WAV hash 篡改 | 修改隔离 fixture | `failed_audio_validation` | 不进入 Nano |
| Nano 验证失败 | Sidecar 返回稳定错误 | `failed_nano_validation` | 原绑定、Version quality 不变 |
| Version 建立后、CAS 前 | 模拟响应丢失 | 幂等查询并继续 CAS | 只有一个 generated Version |
| CAS 漂移 | 作者改绑官方 B2 | `ready_unapplied` | B2 保持，结果可使用 |
| 应用成功后响应丢失 | HTTP 丢包 | GET 返回同一 `ready_applied` | 不增加第二 Version／binding version |
| PawApp 重启 | 每个非终态各一次 | 启动对账收敛 | 无永久 running、租约过期可回收 |
| 删除围栏前漂移 | 增加引用／Version | `superseded` | 不物理删除，释放活动槽 |
| unlink 后 finalize 前崩溃 | 计划 35 注入点 | 按精确计划完成 | 不重算资产范围 |

每个注入必须记录 `fault.json` 的 fault ID、精确 phase、注入方法、预期状态、实际状态、绑定 before/after、进程／租约 before/after；`recovery.json` 记录启动扫描次数、最终状态、残留列表和恢复耗时。

## 9. 幂等、fingerprint 与 CAS 矩阵

fingerprint 必含：

- `CharacterVoiceBrief/1` digest、VoiceDesignDraft digest；
- instruction digest，不保存完整私密 instruction；
- seed 和四个解码参数；
- requested／actual VoiceGenerator model、revision、dtype、device、topology；
- codec model、revision 和 decode parameters；
- 量化方法／校准／权重 digest，未量化明确写 `none`；
- 中间 token schema 和 digest；
- 音频处理策略 fingerprint；
- Nano requested／actual model、revision、参数和 source audio hash。

| 用例 | 预期 |
| --- | --- |
| 同 idempotency key、同 request digest | 返回同一 command |
| 同 key、不同 request digest | 409 稳定冲突 |
| 不同 key、相同完整 fingerprint 且版本已验证 | 允许复用同一 verified Version，仍执行目标 CAS |
| seed 不同 | fingerprint 和输出 hash 不同，不串缓存 |
| instruction／人物工作区版本不同 | 新 fingerprint，不复用旧结果 |
| actual revision／dtype／topology 不同 | 新 fingerprint；若与请求不符则验证失败 |
| binding 未变化 | `ready_applied`，binding version 单调 +1 |
| binding 已变化 | `ready_unapplied`，作者选择不变 |
| 重复“使用此音色” | 单调幂等，同一目标不重复增加版本 |
| 任意生成／验证／存储失败 | binding before 等于 after |

## 10. 私人音色删除与 Edition 身份

### 10.1 隔离删除

删除验收只使用隔离小说的 generated Profile，不操作正式书中作者要保留的主角音色：

1. 无引用 generated Profile：请求后进入 30 秒 grace，可取消；不取消则完成并 tombstone 精确媒体。
2. 当前绑定 generated Profile：服务端返回权威影响，一次确认；围栏前取消保持音色和绑定。
3. 有历史 Edition：摘要包含 Edition／Render／资产数；删除后历史 Edition 的 Voice Version ID 不得变成官方音色，媒体不可用则明确标记 unavailable。
4. Profile／资产／引用漂移或摘要过期：请求转 `superseded` 并释放活动唯一槽。
5. 围栏后三类崩溃：沿用同一 frozen plan 恢复，不重新计算资产范围。
6. 官方 preset：没有删除入口，服务端拒绝。
7. 跨 novel／workspace／storage identity：fail closed，不可重试安全失败。

### 10.2 正式 generated 音色

正式主角音色只验证生命周期投影、eligibility、引用数、资产数和影响摘要，不执行物理删除。若用户另行明确要求删除，再走正式删除流程；计划 40 验收不得把“测试删除”当作删除用户正式成果的授权。

### 10.3 Edition 冻结

- 生成前建立旧 Edition 的 edition ID、manifest revision、segment ordinal、speaker root、Voice Profile ID、Voice Version ID 和音频 hash 快照。
- 人物绑定 generated 版本后，旧 Edition 上述字段逐项相同。
- 新 Edition 的目标人物使用 generated Version；旁白和其他人物仍使用已绑定官方 Version。
- 删除隔离 generated 媒体后，旧 Edition 不得偷偷重映射到新音色；只能保持身份并显示不可用／需要重新生成。

## 11. 正式小说与 TTS 隔离清单

进入 T7 前保存脱敏 `book-freeze.json`：novel ID、两卷 ID／position、四章 document ID、正式 revision ID／number／content hash／visible character count、至少两主角四配角的 root ID 和 workspace version，不保存正文。

必须同时满足：

- 2 卷，每卷 2 章，共 4 章；
- 每章 1900–2300 中文可见字符；
- 不少于 2 位主角、4 位配角；
- 书名、卷章标题、人物卡和正文不含“测试、实验、验收、样书、TTS”及计划编号；
- 四章均已有正式不可变 revision；
- 写作日志中不存在 TTS 命令、音色绑定或 Edition 创建。

T7 开始与结束后再次读取同一快照。novel 标题／description 版本、卷标题／position／version、章标题／position、正式 revision ID／hash、人物 root/workspace version 必须完全一致。TTS 只允许新增或修改 narration 域记录和媒体；任何正文、章名、人物资料变化均以 `VG40_TTS_CHANGED_AUTHORITATIVE_CONTENT` 阻断产品 Gate。

声音不满意只能重新生成候选、保留未应用结果、恢复官方绑定或进入私人删除；不得回写小说台词来迎合音色。

## 12. 数据库、自动化与浏览器命令

### 12.1 隔离数据库环境

```text
VG40_TEST_DATABASE_URL=仅指向数据库名 ai_novel_world_2026_vg40_test 的 loopback PostgreSQL URL
TTS_TEST_DATABASE_URL=仅指向数据库名 ai_novel_world_2026_tts_test 的 loopback PostgreSQL URL
TTS_VOICE_DELETION_TEST_DATABASE_URL=仅指向数据库名 ai_novel_world_2026_voice_delete_test 的 loopback PostgreSQL URL
AI_NOVEL_DATABASE_URL=不得与上述任一 URL 相同；destructive gate 中由 fixture 临时切换后恢复
```

测试必须在代码中校验 database name、host／port／database 与生产不相等、初始表为空。缺变量应 skip/HOLD，不允许自动回退长期数据库。

未来 VoiceGenerator 专项命令：

```bash
.venv/bin/python -m pytest \
  tests/narration/test_voice_generator_runtime.py \
  tests/narration/test_voice_generator_watchdog.py \
  tests/narration/test_voice_generator_service.py \
  tests/narration/test_voice_generator_api.py \
  tests/narration/test_voice_generator_recovery.py

VG40_TEST_DATABASE_URL="$VG40_TEST_DATABASE_URL" \
TTS_VOICE_DELETION_TEST_DATABASE_URL="$TTS_VOICE_DELETION_TEST_DATABASE_URL" \
.venv/bin/python -m pytest \
  tests/narration/test_voice_generator_postgres.py \
  tests/narration/test_voice_deletion.py \
  tests/narration/test_voice_lifecycle.py

TTS_TEST_DATABASE_URL="$TTS_TEST_DATABASE_URL" \
.venv/bin/python -m pytest tests/narration/test_migrations.py
```

迁移专项必须证明 `0034 → 0035 → 0034 → 0035`、fresh → `0035`、`0035.down_revision=20260829_0034` 和唯一 Alembic head。只有 `VG-GO` 后这些 VoiceGenerator 测试和 `0035` 才应存在；当前命令中的未来文件不得被写成已通过。

全量发布命令：

```bash
.venv/bin/python -m pytest
pnpm test
pnpm typecheck
pnpm build
.venv/bin/python scripts/package_plugin.py
.venv/bin/python -m pytest \
  tests/test_manifest.py tests/test_skill_contract.py tests/test_qwenpaw_integration_contract.py
docker compose config --quiet
git diff --check
```

### 12.2 浏览器验收

覆盖 `2560×1440`、`1920×1080`、`1280×800`、`390×844`：

- 人物卡只有一次主操作“生成专属音色并使用”；
- waiting/generating/unloading/validating 状态可读，刷新后恢复；
- 可取消期显示取消，围栏后不显示虚假取消；
- 失败显示稳定原因和一次重试，不把官方音色回退显示为生成成功；
- CAS 漂移显示“已生成、未应用”和“使用此音色”；
- 私人音色生命周期展示生成来源、状态和删除影响；
- 新旧 Edition 身份和当前说话人可见；
- 窄屏不遮挡正文、播放器或原生助手；
- 键盘、焦点、IME、控制台和网络请求均检查。

截图不能证明音频可听或绑定正确；必须与 API／数据库投影、音频 hash 和作者听检交叉对应。

## 13. 波次退出清单

### T0–T2

- [ ] fixed revision／hash／许可证完整
- [ ] 没有未审计 remote code 或在线跟随 `main`
- [ ] 独立环境未污染 PawApp `.venv`
- [ ] 单模型加载未越内存阈值
- [ ] 60 秒回收证据完整

### T3–T6

- [ ] 中性输入不来自正式小说
- [ ] generator 与 codec 分阶段，generator 与 Nano 零重叠
- [ ] 三次冷运行全部满足内存阈值
- [ ] 三条成功音频 hash 不同
- [ ] 取消、崩溃、响应丢失均收敛
- [ ] 机器音频和 Nano 验证通过
- [ ] 作者听检完成，或明确保持 HOLD

### T7

- [ ] 正式四章在 TTS 前已冻结
- [ ] TTS 前后正文／卷章／人物权威 hash 未变化
- [ ] 原官方绑定在失败路径均未变化
- [ ] 成功路径 CAS applied，漂移路径 ready_unapplied
- [ ] 旧 Edition 身份不变，新 Edition 使用 generated Version
- [ ] 隔离 generated 音色完成删除／恢复矩阵
- [ ] 正式 generated 音色未因验收被物理删除
- [ ] 四视口和作者听检完成

## 14. 最终报告最低内容

`VG40-FINAL.md` 必须逐项写明：

1. Git commit、插件 hash、迁移 head、模型／codec revision 和 manifest digest；
2. 最终 topology、dtype、device、是否量化及完整 fingerprint；
3. 三次冷运行的峰值 `phys_footprint`、最小系统余量、swap delta、page-out、耗时和 60 秒回落；
4. T3/T4/T6/T7 机器音频指标、音频 digest 和作者听检；
5. 每个故障注入的预期／实际终态和恢复耗时；
6. CAS 成功／漂移、幂等复用和不同 seed 隔离；
7. 删除生命周期和 Edition 冻结证据；
8. 正式小说 TTS 前后权威 hash 对比；
9. `FEASIBILITY/SAFE/QUALITY/PERF/PRODUCT/FINAL` 六项独立裁决；
10. 未验证项、残余风险、回退方式和受控产物清理状态。

不得仅用“没有崩溃”“声音能响”“页面有按钮”或单次成功作为 `VG16-FINAL=PASS`。

## 15. 本工作包自查结论

- 本文把 T0–T7、证据 schema、机器与作者质量、内存阈值、故障恢复、CAS、删除、Edition 和正式小说隔离收敛为一套可复核矩阵。
- 计划 35 只作为已验证基础契约引用，没有把 Nano 的成功外推为 VoiceGenerator 成功。
- 对当前尚不存在的 runner、专项测试和 `0035` 均明确标注“未来命令”，没有把未执行项写成通过。
- 正式小说 generated 音色不会因 QA 自动删除；破坏性删除仅在隔离副本执行。
- 当前裁决更新为：T0–T7 的机器与产品路径已完成，`VG16-PRODUCT=PASS`；作者听检未完成，所以 `VG16-QUALITY=MACHINE_PASS_AUTHOR_LISTEN_HOLD`、`VG16-FINAL=HOLD_AUTHOR_LISTENING`。
