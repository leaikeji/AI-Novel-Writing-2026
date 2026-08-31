# MOSS-VoiceGenerator 16 GiB 安全运行、自查优化与正式人物音色闭环计划

状态：**2026-08-31 `VG40-T0 → T7` 的机器与产品闭环已经完成：`0035` 已部署到长期 PostgreSQL，VoiceGenerator、Nano、同槽 worker、人物卡一键生成、CAS 自动绑定、私人删除投影和四章新 Edition 均已真实运行。正式小说《潮汐盲区》保持两卷四章、两位主角和五位配角，当前四章合计 `502/502` 句段可播；桌面与窄屏浏览器验收、全量后端／前端回归、插件打包和运行健康均通过。`VG16-FEASIBILITY`、本机风险接受口径下的 `VG16-SAFE`、机器 `QUALITY`、`PERF` 与 `PRODUCT` 已通过；作者尚未对专属音色作主观听检，因此 `VG16-FINAL=HOLD_AUTHOR_LISTENING`，不能把机器质量接受表述为作者已满意。**

本文件是当前项目在 Apple M4／16 GiB 主机上评估、优化和产品化 MOSS-VoiceGenerator 的唯一施工权威。计划 35 继续负责 MOSS-TTS-Nano 核心闭环和 `0034`；本计划只在计划 35 成功集成部署后，重新验证真正的“人物描述生成全新音色”。施工中不得以聊天摘要、临时笔记或旧计划中的静态资源估算替代本文门禁。任何改变优化顺序、安全阈值、模型 revision、迁移序列或最终完成口径的决定，都必须先更新本文并重新复查，不能在代码中静默偏离。

## 一、立项原因与裁决边界

### 1.1 当前事实

- 当前主机为 Apple M4，物理内存 `17,179,869,184` bytes，即 16 GiB。
- 当前数据卷可用空间约 45 GiB；真正下载前必须重新测量。
- Docker Desktop VM 内存约 7.75 GiB，不足以承载 VoiceGenerator 完整运行时。
- 固定 VoiceGenerator 运行制品约 4.24 GB；完整 MOSS-Audio-Tokenizer 制品约 7.1 GB；两个仓库完整快照合计约 10.6 GiB。
- 官方示例在 CUDA 上使用 BF16，在非 CUDA 路径使用 CPU/FP32；固定官方示例没有已验证的 MPS 分支。
- 计划 35 的 `VG-FINAL=BLOCKED_HARDWARE` 是针对“官方组合路径、重模型可能同时驻留、当前没有 Apple 原生运行实现”的保守裁决。它证明该原始路径不能直接上线，但没有证明分阶段加载、MPS/BF16、内存映射或受控量化后的所有拓扑都不可能在 16 GiB 上运行。
- 当前仓库只有 VoiceGenerator 元数据与 dry-run 原型，没有产品运行 Sidecar、生成 API、`0035`、人物卡生成按钮或真实 generated Voice Version 闭环。

### 1.2 本计划重新开放的工程假设

本计划把以下判断作为待真实测量的工程假设，而不是既成事实：

> 若 VoiceGenerator 与完整 Audio Tokenizer 能分阶段加载，VoiceGenerator 使用 Apple MPS/BF16 或等效低内存路径，Nano 与 VoiceGenerator 从不同时常驻，并由系统级 watchdog 在内存压力恶化前终止子进程，则当前 M4／16 GiB 可能安全完成单人物、短样音、一次一个任务的声音设计。

只有真实三次连续运行、内存回收、Nano 二次验证和正式人物绑定全部通过，才能把“可能”改为“可用”。用户认为本机可以安全运行，构成本计划必须认真验证和优化的产品目标，但不替代测量证据。

### 1.3 独立终点

| Gate | 完成口径 |
| --- | --- |
| `VG16-FEASIBILITY` | 至少一种拓扑在 16 GiB 上完成真实短样音，未触发安全终止 |
| `VG16-SAFE` | 三次连续冷运行无 OOM、无 critical memory pressure、无持续 swap 抖动，退出后内存回落 |
| `VG16-QUALITY` | 生成音频有效、非空、无 NaN／严重削波／异常静音，且能进入 Nano 技术验证 |
| `VG16-PERF` | 单次一键任务达到本文冻结的可接受耗时，取消与超时可收敛 |
| `VG16-PRODUCT` | 人物卡一次点击完成 Brief、Draft、生成、验证、CAS 绑定和可删除生命周期 |
| `VG16-FINAL` | 上述五项全部通过，并在正式悬疑小说的一位主角上形成新 Edition |

任何一项未通过，都不得用官方音色匹配、Nano 高级调音、用户上传参考录音或声音名称变更冒充“生成了全新人物音色”。

## 二、目标与非目标

### 2.1 目标

1. 在不修改 QwenPaw 上游的前提下建立独立 Apple 原生 VoiceGenerator 运行时。
2. 找到当前 16 GiB 主机上最安全、最小峰值的真实生成拓扑。
3. 建立可复核的 system memory、process RSS、`phys_footprint`、swap、page-out、耗时和退出回收证据。
4. 冻结以下正式链路：

```text
正式人物工作区快照
→ CharacterVoiceBrief/1
→ VoiceDesignDraft
→ VoiceGenerator 生成样音
→ 完全释放 VoiceGenerator
→ Nano 技术验证
→ generated Voice Version
→ 目标人物 CAS 自动绑定
→ 新 Narration Edition
```

5. 生成结果进入计划 35 已实现的统一私人音色删除生命周期。
6. 与正式小说创作解耦：小说四章全部写完并形成正式 revision 后，才使用正文和人物卡执行人物音色验收。

### 2.2 非目标

- 不在写小说过程中测试 TTS，不为覆盖声音测试修改标题、卷章、人物或正文。
- 不在书名、卷名、章名、人物卡或正文中写入“测试”“实验”“验收”“样书”“TTS”或任务编号。
- 不一次生成多个重模型任务，不提供批量三候选作为首版默认路径。
- 不让 VoiceGenerator 与 Nano 同时常驻。
- 不把 VoiceGenerator 依赖加入 PawApp 主进程或现有 Nano Sidecar。
- 不跟随 Hugging Face `main`，不执行未固定 revision 的远程代码。
- 不自动使用第三方社区量化模型、第三方人物声纹或用户未授权参考录音。
- 不修改 QwenPaw 核心代码、私有配置、私有数据库或未公开内部模块。
- 不在 `VG16-SAFE` 通过前创建 `0035`、正式 API、长期 worker 或可见产品按钮。

## 三、不可偏离的安全设计

### 3.1 独立原生进程

VoiceGenerator 使用一次性 macOS 原生子进程，而不是 Docker：

- 独立 Python 环境和依赖锁；
- 独立、只读模型目录；
- 独立临时工作目录；
- 不修改项目 `.venv`；
- 不继承或打印密钥；
- 一次只处理一个命令；
- 成功、失败、取消或 watchdog 终止后都必须退出进程；
- 运行结果通过窄协议返回，不能把 Python 对象或模型实例留在 PawApp 进程中。

若官方依赖锁只有 CUDA wheel，Apple 运行时必须形成单独的 macOS/arm64 锁文件和兼容证据；不得修改全项目 Python 版本边界或让 CUDA 依赖进入主包。

### 3.2 重模型互斥

硬件尖峰阶段由主代理串行保证没有 Nano 推理任务；产品阶段必须实现跨进程、崩溃可恢复的唯一重模型租约：

```text
moss-nano:inference
voice-generator:generation
```

进入 VoiceGenerator 前固定执行：

1. 撤销新的 Nano 合成领取资格；
2. 等待正在运行的 Nano 任务有界收敛；
3. 请求 Nano 卸载并验证 `model_loaded=false`；
4. 获取 `voice-generator:generation` 独占租约；
5. 启动一次性 VoiceGenerator 子进程；
6. 子进程退出并验证内存回落；
7. 释放租约；
8. 恢复 Nano 任务领取资格。

租约超时、持有者失联、Nano 未卸载或内存基线异常时 fail closed。已经生成的音频播放不依赖 Nano 常驻，不应被阻断。

### 3.3 分阶段加载

第一优先级是验证能否把声音设计和完整 codec 解码分开：

```text
阶段 A：只加载 VoiceGenerator → 生成有界音频 token／中间结果
阶段 B：保存带 hash 的中间结果 → 完全销毁 VoiceGenerator
阶段 C：确认内存回落 → 单独加载 MOSS-Audio-Tokenizer
阶段 D：解码音频 → 完全销毁 Audio Tokenizer
```

如果模型结构或官方处理器契约要求两个模型同时驻留，则必须保存可复核证据并停止该拓扑；不得为了通过而保留未审计 monkey patch、跨模型悬挂引用或无法证明释放的缓存。

### 3.4 优化尝试顺序

只能按以下顺序推进；当前项失败并完成原因记录后才能进入下一项：

1. `MPS/BF16 + 分阶段加载 + 一次性进程`；
2. `MPS/BF16 + low_cpu_mem_usage／safetensors mmap + 分阶段加载`；
3. `CPU/FP32 + 分阶段加载`，仅在静态峰值仍满足安全余量时运行；
4. 从固定官方权重本地产生、可回溯的受控量化版本；
5. 其他拓扑必须先修订本文并说明新增依赖、精度影响和退出条件。

禁止直接运行已知危险的“VoiceGenerator 与完整 codec 同时 CPU/FP32 常驻”作为实测基线。它只保留静态估算，不值得用唯一主机承担 OOM 风险。

### 3.5 供应链与磁盘门禁

下载前必须重新满足：

- 数据卷可用空间 `≥42 GiB`；
- 下载、临时 staging 和最终模型目录位于同一受控文件系统；
- 完成后仍保留 `≥24 GiB` 可用空间；
- VoiceGenerator、Audio Tokenizer、官方源码分别固定 revision；
- 保存文件 allowlist、LFS/Xet 大小、官方 hash 和下载后逐文件 SHA-256；
- 审核固定快照内的 remote code、processor、modeling、configuration 和 inference utility；
- 首次下载以外的运行使用 `local_files_only`；
- 模型、缓存、临时音频和虚拟环境不进入 Git 或插件包。

磁盘不足时停止，不删除用户小说、媒体、PostgreSQL/QwenPaw 卷或不属于本计划的缓存。只允许精确清理本计划创建且已经证明可重建的 staging 目录。

## 四、内存 watchdog 与通过阈值

### 4.1 观测指标

每次真实运行必须同时记录：

- 子进程 RSS；
- macOS `phys_footprint`；
- 系统物理内存估算与 memory pressure 状态；
- swap 使用量及本次 delta；
- page-in／page-out 速率；
- QwenPaw、PostgreSQL、Nano Sidecar 的内存；
- 模型加载、token 生成、codec 解码、写音频和退出各阶段耗时；
- 子进程退出后 10／30／60 秒的内存回落；
- OOM、signal、MPS allocator、算子 fallback 和异常日志的结构化摘要。

证据不得保存模型输入中的完整人物私密资料、密钥、完整正文或完整音频；正式音频继续进入受控媒体目录，技术报告只保存 digest、时长和标量。

### 4.2 安全终止

以下任一条件出现，watchdog 必须先停止继续生成，再终止子进程并记为失败：

- memory pressure 进入 critical；
- 子进程超过冻结的硬超时；
- Nano 被观察到重新加载；
- MPS allocator、codec 或进程进入无进展状态；
- QwenPaw 原生页面或系统交互出现持续失去响应。

2026-08-30 的用户风险接受裁决明确取消“剩余内存 4 GiB／3.5 GiB”和固定 swap delta 作为 T2–T7 的硬停条件。watchdog 仍记录每个样本的可用内存、swap 与 page-out，供判断实际拓扑成本和退出回落；它们单独越过旧数值不终止任务，也不自动判失败。T2 首次真实映射在约 1.53 GiB 可用内存时出现一次瞬时 critical 并被旧立即终止策略拦截；鉴于用户已接受本机风险，T2–T7 改为持续 critical 达 20 秒才终止，开始、清除和最长持续时间必须入证据。该窗口不适用于基线：启动前已处于 critical 仍拒绝创建子进程。

安全终止不能写入 Voice Version、改变人物绑定或留下“处理中”的永久命令。

### 4.3 `VG16-SAFE` 通过条件

必须连续三次冷启动真实生成全部满足：

- 无 OOM、jetsam、系统卡死或手工强制重启；
- memory pressure 不进入 critical；
- 全程保留可复核的最小系统余量、swap delta 与 page-out 观测值；这些值不设固定 PASS 下限／上限；
- 未出现导致系统或模型进程持续失去响应的内存抖动；
- Nano 与 VoiceGenerator 驻留时间重叠为 0；
- 子进程退出后 60 秒内，系统和相关进程内存回落到运行前基线的合理范围；
- 三次均生成有效音频并关闭全部文件句柄与临时租约。

若 macOS 核心指标缺失，结论只能是 `HOLD_MEASUREMENT`，不得按“看起来没崩”记为通过。通过后的完整表述必须是“当前用户风险接受条件下，本机固定拓扑三次实测通过”，不得简写为通用 16 GiB 安全认证。

## 五、技术尖峰测试矩阵

### `VG40-T0`：只读冻结

- 重新读取官方 fixed revision、模型卡、源码、权重 dtype、文件体积和许可证；
- 检查 MPS 算子支持、PyTorch/macOS 兼容和官方处理器对 codec 的加载时机；
- 建立模型对象引用图和可能的分阶段边界；
- 不下载权重、不安装依赖、不运行模型。

退出证据：`VG40-OFFICIAL.md`、revision/hash 清单、静态峰值假设和阻断项。

### `VG40-T1`：依赖与空载原型

- 创建独立 macOS/arm64 环境；
- 只导入依赖、解析配置和执行空载设备探针；
- 验证 MPS/BF16 基础算子、attention fallback 和退出回收；
- 不读取完整模型权重。

退出证据：依赖 lock、Python/PyTorch/Transformers 版本、MPS 能力和空载内存基线。

2026-08-30 经用户明确授权增加窄例外：本阶段探针不读取模型权重，只执行固定小张量算子，因此允许在 15 个基线样本均不低于 2.5 GiB 时启动；设置 `torch.mps.set_per_process_memory_fraction(0.05)`，系统余量低于 2.0 GiB、memory pressure=critical、swap 增量超过 256 MiB或 120 秒超时立即终止。T1 已按该历史契约完成。用户随后对 T2–T7 作出更宽的本机风险接受裁决；不得用后续裁决改写 T1 已保存的原始证据。

### `VG40-T2`：只加载验证

- 下载完成且 hash 通过后，只加载 VoiceGenerator；
- 不生成音频；
- 记录权重加载峰值和稳定驻留；
- 退出并验证 60 秒内存回落；
- 再用单独进程只加载 Audio Tokenizer，执行同样验证。

任一单模型加载已经突破安全阈值时停止，不进入组合或真实生成。

### `VG40-T3`：最短真实生成

- 使用不属于正式小说的中性声音描述和 3–5 秒短句；
- 生成一个样音；
- 验证容器、采样率、声道、时长、非空、NaN、异常静音、DC 偏移和严重削波；
- 只保存在本计划隔离媒体目录，不创建正式 Voice Version。

### `VG40-T4`：分阶段解码

- 生成有界中间 token；
- 保存 token schema、shape、dtype、长度和 digest；
- 完全释放 VoiceGenerator 并验证内存回落；
- 新进程只加载 codec 解码；
- 核验两个重模型驻留区间没有重叠；
- 比较音频结构、参数证据和可听质量。

### `VG40-T5`：稳定性与取消恢复

使用三个不同 seed 连续执行三次冷运行，并覆盖：

- 正常完成；
- 作者取消；
- watchdog 安全终止或注入子进程崩溃；
- 响应丢失后的命令查询；
- 临时目录、租约和进程恢复；
- 三条成功音频 hash 不同；
- 退出后内存回落。

性能门禁：首个短样音目标 `≤300 s`，后续短样音目标 `≤180 s`。超过目标但内存安全时只能记录 `SAFE_BUT_SLOW`，不得直接开放一键产品按钮。

### `VG40-T6`：Nano 二次验证

- VoiceGenerator 和 codec 已完全退出；
- Nano 重新取得重模型租约；
- 使用生成样音完成一次真实技术验证；
- 验证 requested/actual 模型、revision、参数 digest、输入样音 hash、输出音频 hash 和 ModelRun；
- Nano 失败不得反向把 VoiceGenerator 样音标记为可用版本。

### `VG40-T7`：正式人物卡

只在正式悬疑小说两卷四章全部写完并形成正式 revision 后执行：

1. 读取一位主角的权威人物工作区快照；
2. 生成 `CharacterVoiceBrief/1`，缺失属性保持 unknown；
3. 创建不可变 `VoiceDesignDraft`；
4. 使用官方推荐解码参数生成一个新声音；
5. 完成 Nano 技术验证；
6. 创建 generated Voice Version；
7. 原子 CAS 绑定该主角；
8. 使用已完成的正式章节生成新 Edition；
9. 验证旧官方音色 Edition 身份不变，新 Edition 使用 generated 身份。

小说正文不得因声音结果而重写；声音不满意时通过重新设计或删除私人音色处理。

## 六、产品契约与状态机

只有 `VG16-SAFE + VG16-QUALITY + VG16-PERF` 通过，才允许冻结正式契约和创建 `0035`。

### 6.1 一键作者路径

作者只执行一次操作：

```text
人物卡 → 生成专属音色并使用
```

后台固定为：

```text
queued
→ analyzing_character
→ waiting_for_heavy_runtime
→ generating_voice
→ unloading_voice_generator
→ validating_with_nano
→ ready_applied | ready_unapplied
```

失败终态至少区分：

- `failed_character_analysis`
- `failed_runtime_unavailable`
- `failed_memory_safety`
- `failed_generation`
- `failed_audio_validation`
- `failed_nano_validation`
- `failed_storage`
- `cancelled`
- `superseded`

### 6.2 绑定规则

- 创建命令时冻结目标人物、人物工作区版本和当前 binding version；
- 任何生成或验证失败都不改变原官方音色；
- CAS 未变化时进入 `ready_applied`；
- 作者并发修改过声音时进入 `ready_unapplied`，保留结果并提供一次“使用此音色”；
- 不允许静默回退为官方音色后仍显示生成成功；
- 旧 Edition 继续冻结旧 Voice Version；
- generated 版本进入计划 35 的私人音色删除生命周期。

### 6.3 模型参数

默认一键路径使用官方推荐值：

- `audio_temperature=1.5`
- `audio_top_p=0.6`
- `audio_top_k=50`
- `audio_repetition_penalty=1.1`

文本通道只负责本路径的协议／控制 token，固定使用 greedy 解码；声音多样性仅由上述官方 audio 参数和 seed 驱动。这样不会让随机文本 token 把已经完成或本应开始的音频路径带离协议状态。

人物声音的年龄感、质感、情绪、口音、语速和音高倾向来自 `instruction`，不是伪装成 Nano 精确旋钮。seed、instruction、解码参数、requested/actual 模型、revision、运行拓扑和量化身份全部进入不可变 fingerprint。

### 6.4 `VG40-CONTRACT` 冻结结果

2026-08-30 在 T0–T6 通过后冻结以下产品契约。后续实现若需要改变字段、终态、模型身份或信任边界，必须先回到本文变更控制，不得在后端、宿主服务或前端分别演化。

#### 公共 HTTP API

```text
GET  /novels/{novel_id}/characters/{character_id}/voice-generator-commands
POST /novels/{novel_id}/characters/{character_id}/voice-generator-commands
GET  /novels/{novel_id}/voice-generator-commands/{command_id}
POST /novels/{novel_id}/voice-generator-commands/{command_id}/cancel
POST /novels/{novel_id}/voice-generator-commands/{command_id}/retry
PUT  /novels/{novel_id}/voice-generator-commands/{command_id}/binding
```

- 创建请求只接受人物工作区选择、`expected_binding_version` 和可选 seed；声音 instruction、模型 ID、revision、路径、Nano 参数和输出位置均由服务端决定。
- `POST` 创建必须带 `Idempotency-Key`；同 key／同 request digest 返回同一命令，同 key／不同 digest 返回稳定 `409`。
- cancel、retry、binding 由 command ID 和单调状态机保证重复调用安全，不接收无效的假幂等头。
- 所有响应使用 `character-voice-generation/1`，至少包含 command/draft/character ID、状态、进度、`cancellable`、`retryable`、`terminal`、稳定 `failure_code`、生成版本、当前人物绑定、CAS 是否仍有效及时间戳；不返回人物工作区、完整 instruction、宿主路径或 token。
- `binding` 只接受当前权威 `expected_binding_version`；重复应用同一版本不重复增加 binding version。

稳定非成功终态固定为：`failed_character_analysis`、`failed_runtime_unavailable`、`failed_memory_safety`、`failed_generation`、`failed_audio_validation`、`failed_nano_validation`、`failed_storage`、`cancelled`、`superseded`。不得把任一失败映射为官方音色成功。

#### 数据库权威记录

`0035` 新增且只新增三类权威表，并向现有后台任务注册表增加一个冻结 job kind：

1. `voice_design_drafts`：不可变保存人物 ID、character/catalog 版本、工作区 digest、`CharacterVoiceBrief/1`、模型证据 digest、服务端生成的有界 instruction、seed、官方 audio 参数、双模型 identity 与完整 fingerprint。完整人物工作区不复制到该表。
2. `voice_generator_commands`：持久化 novel／character／draft／job、创建幂等、预期 binding version、单调状态、宿主 request ID、生成参考资产、Nano 验证资产、两个 ModelRun、最终 Profile/Version、应用结果与稳定失败证据。
3. `voice_generator_run_evidence`：每个宿主尝试一行不可变回执，记录 requested/actual runtime identity、输入／token／WAV digest、音频标量、退出原因和脱敏内存摘要；不保存路径、token、完整 instruction 或音频字节。
4. 复用 `0012` 已注册但尚无产品调用者的 `narration.voice_generate` job kind；`0035` 只把它从历史独立 `voice-generator` resource class 重新绑定到现有单槽 `moss-nano` resource class，不再增加第二个同义 job kind。取得该槽即阻止新的 Nano 推理；处理器必须在调用宿主前进一步证明 Sidecar 已卸载，在生成进程和 codec 完全退出后才能在同一槽内重新 warmup Nano。历史 `voice-generator` registry row 为已执行迁移的兼容证据，不作为产品调度入口，也不在本迁移中破坏性删除。
5. 同一 `narration.voice_generate` attempt 需要分别封存 VoiceGenerator 与 Nano 两条 ModelRun。`0035` 因此把 `uq_model_run_attempt` 收窄调整为 `attempt_id + requested_model_id` 唯一，并增加数据库 trigger：只有该 job kind 可以写入第二条且最多两条；其他后台任务仍保持一 attempt 一 ModelRun。

`voice_profile_versions` 的 locked/model-run 约束扩展为允许：

```text
source_type='generated'
activation_basis='character_one_click_generation'
validation_basis='machine_validated'
quality_state='accepted'
model_run_id IS NOT NULL
rights.source_kind='voice_generator'
```

该 `model_run_id` 指向最终 Nano 技术验证；VoiceGenerator 原始运行另由 command 的 `generator_model_run_id` 和 run evidence 保存。最终 Version 必须有 `reference_asset_id`，并以生成样音 hash、Nano 输出 hash、两个 ModelRun、Draft fingerprint 和固定双模型 identity 闭包验证。高级调音继续只使用 `experimental_machine_validated`，两条来源不得互换。

#### macOS 原生宿主协议

宿主服务使用 `moss-voice-generator-host/1`，默认只监听 `127.0.0.1`，由 Docker 内 PawApp 通过固定 `host.docker.internal` 和五位端口访问。认证 token 只存在于宿主 `0600` 文件和 QwenPaw 私有 secret volume；不得进入环境变量值、URL、日志、数据库、证据或 Git。

```text
GET  /v1/health
POST /v1/generations
GET  /v1/generations/{request_id}
GET  /v1/generations/{request_id}/audio
POST /v1/generations/{request_id}/cancel
```

- 创建只接受 UUID request ID、`instruction`、instruction digest、`zh-CN|en|ja-JP`、seed 和四个冻结官方 audio 参数；服务端自行选择固定短句、模型目录、临时目录和输出路径。
- 请求必须同时声明固定 VoiceGenerator/codec revision、runtime topology 和协议版本；任一不一致 fail closed。
- 一个服务进程最多一个活动 request；每个 request 启动一次性 generator 子进程和一次性 codec 子进程，二者不得重叠。
- 相同 request ID／相同 request digest 可查询或复用已验收回执；相同 ID／不同 digest 返回冲突。
- 成功 manifest 先 fsync 再原子 rename；音频下载必须带 SHA-256、字节数、格式和 runtime fingerprint headers。PawApp 读取后重新执行 hash 与机器音频校验，不能信任 HTTP 成功状态。
- cancel 只在生成资产发布围栏前有效；围栏后返回当前终态。宿主重启后可从 manifest 恢复终态，但数据库 command 始终是产品状态权威。
- 服务拒绝调用方给出的文件路径、模型名、revision、任意 shell 参数、任意 Python 模块和远程 URL；运行固定 `local_files_only`，不继承 PawApp 密钥。

#### 运行时 readiness

`NarrationFeatureReadinessProvider` 的管理集合从三项扩展为四项，增加 `voice_generator`。该能力只有在 `0035` schema、存储、digest keyring、后台 scheduler、`moss-nano` 单槽、Nano processor、宿主协议／模型／codec／拓扑 identity、命令对账器和删除生命周期同时就绪时才 `enabled + visible + actionable`。启动、关闭、宿主失联、模型 identity 漂移、对账器崩溃或 Sidecar 失联时必须由同一个 provider 原子撤销；页面、API 和 health 不得各自判断。

#### 指令生成边界

复用现有 `CharacterVoiceBrief/1` 和 `ai-novel-writer` 证据链，不新增第二模型权威。Brief 仍只允许 language、presentation、pitch、pace、energy、texture 六维及已保存人物工作区 evidence path；服务端把非空维度确定性转换为本地语言的声音 instruction，unknown 不补全。姓名、别名、职业、身份、年龄或性别刻板印象不能单独形成声音特征。完整 instruction 只在本地权威数据库与一次宿主请求中存在，公开响应和证据只发布 digest。

## 七、迁移与文件所有权

### 7.1 迁移序列

- 计划 35 必须先稳定部署 `20260829_0034`；
- 只有 `VG-GO` 后才新增 `backend/migrations/versions/20260830_0035_voice_generator_design.py`；
- `0035.down_revision = 20260829_0034`；
- `0035` 只创建权威命令、VoiceDesignDraft、生成证据、重模型租约和必要约束；
- 迁移不得下载模型、运行推理、移动媒体或删除文件；
- 若尖峰失败，不创建占位表、预留 API 或空迁移。

### 7.2 候选模块边界

通过契约冻结后，代码只允许进入边界清晰的新模块或现有 narration 适配层：

```text
backend/narration/voice_design.py
backend/narration/voice_generator_runtime.py
backend/narration/voice_generator_service.py
frontend/src/narration/character-voice-generator.ts
scripts/tts/voice_generator/**
tests/narration/test_voice_generator_*.py
```

共享 `backend/models.py`、`backend/app.py`、公共 schema/API、`production_runtime.py`、前端 contracts/api/index、迁移和工作台入口只由主代理修改。若实现证明需要不同文件名，必须先在本文变更记录中更新所有权，不能由子代理自行扩展范围。

## 八、与正式悬疑小说计划的顺序

本计划不能把正式小说变成 TTS fixture。完整执行顺序固定为：

1. 集成并部署计划 35，长期数据库升级到 `0034`；
2. 完成 `VG40-T0 → T6` 的独立硬件尖峰，不接触正式小说；
3. 创建一部正式悬疑破案小说；
4. 创建两卷，每卷两章，共四章；
5. 创建不少于两位主角、四位配角的正式人物卡；
6. 完成并审阅四章正文，每章约 1900–2300 个中文可见字符；
7. 四章全部形成正式 revision 后，才进入朗读设置；
8. 旁白、两位主角和四位配角先绑定官方音色；
9. 第一、二章先形成使用官方音色的 Edition；
10. 对一位主角执行 `VG40-T7`，成功后生成第三、四章新 Edition；
11. 验证旧 Edition、generated 新 Edition、播放器和删除生命周期。

书名、卷章、人物、案件线索和对白只服务于悬疑故事，不得包含技术测试术语，也不得为了让角色发声而添加不符合情节的对白。

## 九、施工波次与子代理并行设计

主代理是唯一公共契约、共享入口、迁移、模型下载、真实重模型、长期环境、正式小说、浏览器、Git 与最终裁决 Owner。

| 工作包 | 标记 | 唯一目标 | 允许修改 | 必须返回 |
| --- | --- | --- | --- | --- |
| `VG40-G0` | `GATE/SER` | 冻结 Git、硬件、磁盘、计划 35 部署和模型事实 | 本文状态、G0 证据 | 当前提交、0034、资源快照 |
| `VG40-A-OFFICIAL` | `PAR` | 复核官方 revision、dtype、MPS/codec 边界和量化来源 | `docs/开发文档/证据/计划40/VG40-OFFICIAL.md` | 官方链接、hash、风险表 |
| `VG40-A-MEMORY` | `PAR-C` | 建立无模型的 watchdog 与分阶段加载原型 | `prototypes/moss-tts-nano/voice-generator/**`、对应原型测试 | 指标、终止、回收证据 |
| `VG40-A-QA` | `PAR-C` | 冻结音频、取消、崩溃、恢复和产品验收矩阵 | `docs/开发文档/证据/计划40/VG40-QA.md` | 完整测试矩阵 |
| `VG40-SPIKE` | `MUTEX/GATE/SER` | 主代理下载固定模型并执行 T1–T6 | 独立模型/环境/证据目录 | 三次运行和最终 GO/NO-GO |
| `VG40-CONTRACT` | `MUTEX/SER` | 冻结 DTO、状态机、资源租约和 `0035` | 本文、公共契约、迁移 | 单头、错误码、CAS 规则 |
| `VG40-B-RUNTIME` | `PAR-C` | 实现独立运行适配器与服务 | 新 VoiceGenerator 后端模块和专项测试 | 失败安全、取消和回收 |
| `VG40-B-FE` | `PAR-C` | 实现人物卡一键生成界面 | 新前端组件、样式和专项测试 | 一键、重试、CAS 状态 |
| `VG40-INT` | `INT/SER` | 主代理接入 API、runtime、人物卡和私人删除 | 共享入口 | 集成测试与冗余清理 |
| `VG40-BOOK` | `MUTEX/SER` | 完成正式四章小说，不进入 TTS | 长期小说权威数据 | 两卷四章与六名人物 |
| `VG40-LIVE` | `MUTEX/GATE/SER` | 正式人物新音色与章节 Edition | 长期声音和媒体权威数据 | 官方→generated 冻结证据 |
| `VG40-FINAL` | `INT/GATE/SER` | 全量回归、自查和最终裁决 | 最终报告 | SAFE/QUALITY/PERF/PRODUCT |

共享锁：

```text
LOCK-MIGRATION-HEAD
LOCK-PUBLIC-CONTRACT
LOCK-HEAVY-MODEL
LOCK-NANO-RESIDENCY
LOCK-MODEL-DOWNLOAD
LOCK-TEST-DATABASE
LOCK-LONG-RUNNING-PAWAPP
LOCK-BROWSER
LOCK-PRODUCTION-NOVEL
LOCK-GIT
```

子代理不得提交、推送、下载模型、安装依赖、运行重模型、操作长期数据库、创建正式小说、绑定声音、修改共享入口或删除媒体。无法隔离写入范围时回收为主代理串行施工。汇合顺序固定为：

```text
G0
→ A-OFFICIAL / A-MEMORY / A-QA
→ SPIKE
→ CONTRACT
→ B-RUNTIME / B-FE
→ INT
→ 隔离回归
→ BOOK
→ LIVE
→ FINAL
```

## 十、自动化、真实验收与证据

### 10.1 自动化

至少执行：

```text
.venv/bin/python -m pytest
pnpm test
pnpm typecheck
pnpm build
.venv/bin/python scripts/package_plugin.py
.venv/bin/python -m pytest tests/test_manifest.py tests/test_skill_contract.py tests/test_qwenpaw_integration_contract.py
docker compose config --quiet
git diff --check
```

VoiceGenerator 专项必须覆盖：

- MPS 不可用、算子不支持、dtype 不支持；
- 单模型加载超阈值；
- codec 分阶段边界不存在；
- watchdog 提前终止；
- 用户取消、子进程崩溃、响应丢失；
- Nano 未卸载和租约冲突；
- 相同 fingerprint 幂等复用、不同 seed 不串缓存；
- CAS 漂移不覆盖作者新绑定；
- 生成成功但 Nano 验证失败；
- 重启后命令、租约、临时文件和精确媒体计划收敛；
- generated 音色删除和历史 Edition 身份保持。

PostgreSQL 写测试必须使用明确隔离库，覆盖 `0034 → 0035 → 0034 → 0035`。模型尖峰不依赖数据库迁移；`0035` 只能在 GO 后出现。

### 10.2 真实验收

1. 三次中性短样音冷启动；
2. 三次内存、swap、page-out 和退出回收；
3. 一次主动取消与一次注入崩溃恢复；
4. 一个正式主角的真实 CharacterVoiceBrief；
5. 一个 generated Voice Version；
6. 一次 CAS 自动绑定和一次 CAS 漂移；
7. 一章旧官方 Edition 与一章新 generated Edition；
8. 桌面与 `390×844` 人物卡、朗读设置和播放器；
9. generated 私人音色删除影响、取消和完成状态。

必要证据统一写入：

```text
docs/开发文档/证据/计划40/
```

正式小说正文和完整音频不复制到该目录；只保存脱敏状态、ID、hash、标量、截图和恢复说明。

## 十一、部署、回退与清理

- 计划 35 的 `0034` 部署必须先独立通过，不能用 VoiceGenerator 尖峰掩盖 CORE 失败。
- 长期新增 `0035` 前备份 PostgreSQL、媒体清单、旧插件、镜像 digest、模型清单和迁移 head。
- 尖峰失败时删除入口保持不存在；可保留已校验的固定模型缓存供后续复核，不自动删除。
- `0035` 已产生记录后不降 schema；只撤销 VoiceGenerator capability、停止新任务并回退兼容代码。
- watchdog 或租约异常时停止新生成；已经生成但未绑定的版本保持可审计、可删除。
- 冗余原型只有在正式运行模块覆盖同一风险、调用者为 0、测试迁移完成后才能删除。
- 不清理用户小说、正文、正式人物、历史 Edition、PostgreSQL/QwenPaw 卷或不属于本计划的模型缓存。
- 卸载 PawApp 后不得残留 QwenPaw 路由包装、工具、Skills 或 VoiceGenerator 常驻进程。

## 十二、自查清单与最终裁决

每个波次退出前必须逐项回答：

1. 是否仍在使用固定官方 revision 和下载后 hash？
2. 是否把 Docker 7.75 GiB 错当成可运行 VoiceGenerator 的环境？
3. 是否有 Nano 与 VoiceGenerator 同时驻留的时间段？
4. 是否真实记录 `phys_footprint`、系统余量、swap 和退出回落？
5. 是否因一次未崩溃就跳过三次冷运行？
6. 是否用调音、匹配或克隆冒充全新声音设计？
7. 是否在 `VG-GO` 前增加了 `0035`、API 或页面按钮？
8. 是否让失败命令改变了原人物绑定？
9. 是否在写小说过程中进入了 TTS 测试或修改正文迎合声音？
10. 是否把完整正文、音频、密钥或人物私密资料写入证据？
11. 是否删除了不属于本计划的文件、缓存、媒体或用户数据？
12. 是否在没有用户明确授权时提交或推送 Git？

最终裁决只能使用：

```text
VG16-FINAL=PASS
VG16-FINAL=HOLD_AUTHOR_LISTENING
VG16-FINAL=HOLD_MEASUREMENT
VG16-FINAL=SAFE_BUT_SLOW
VG16-FINAL=BLOCKED_RUNTIME
VG16-FINAL=BLOCKED_MEMORY
VG16-FINAL=BLOCKED_QUALITY
```

只有 `PASS` 才允许对用户表述为“当前 16 GiB 主机可以正常生成并使用人物专属新音色”。其他状态都必须说明真实阻断，且不影响计划 35 的官方音色、Nano 高级调音、私人音色删除和章节播放器。

## 十三、变更控制

本文建立后，施工偏离只能通过以下流程发生：

1. 保存触发变更的事实或失败证据；
2. 在本文增加变更记录，说明原方案、拟变更、风险和回退；
3. 重新检查文件所有权、迁移序列、测试和安全阈值；
4. 涉及模型来源、安全阈值、数据处理、硬件资源或产品行为的实质变化，先交由用户裁决；
5. 获得允许后再修改源码。

不得在施工结束后才补写本文来合理化已经发生的偏离。

### 变更记录

| 日期 | 变更 | 状态 |
| --- | --- | --- |
| 2026-08-30 | 用户要求重新验证 16 GiB 安全运行可能性，并把自查优化测试方案固化为单独文档 | 已记录并获准施工 |
| 2026-08-30 | 计划 35 集成、`0034` 与长期 CORE 部署通过；T0 证明官方 CPU/FP32 组合路径不可运行，允许继续 MPS/BF16 分阶段路径 | 已实施，T1 受 4 GiB 启动前余量门禁约束 |
| 2026-08-30 | 用户明确授权 T1 忽略 4 GiB 启动条件；仅对无权重固定小张量探针采用 2.5 GiB 启动、2.0 GiB 硬停、5% MPS allocator、256 MiB swap 和 120 秒超时 | 已批准并完成，原始证据保持不变 |
| 2026-08-30 | 用户进一步明确授权 T2–T7 不再要求剩余内存达到 4 GiB，并接受本机可能卡顿、OOM 或死机的风险 | 已批准执行；剩余内存／swap／page-out 改为只测量，critical pressure、持续失去响应、重模型重叠与硬超时仍终止；结论限定为本机风险接受实测 |
| 2026-08-30 | T2 首次完整权重映射遇到单样本 critical；按用户风险接受改为 20 秒持续 critical 门禁，并在关闭全部项目容器后重跑 | 已实施；基线 critical 仍拒绝启动，持续 critical、Nano 重入、失去响应和硬超时仍终止；VoiceGenerator 与 Audio Tokenizer T2 均通过 |
| 2026-08-30 | Hugging Face 公共 Xet 传输过慢，改用 OpenMOSS 官方项目列出的 ModelScope 镜像传输 Audio Tokenizer 大分片 | 已实施；模型身份仍锁定 Hugging Face 固定 revision，镜像只负责字节传输，7 个文件仍逐项按冻结大小和 SHA-256 验收 |
| 2026-08-30 | T3–T6 完成；随机文本控制 token 会让固定 seed 漂移出协议，适配器升级为 v2，在官方 `audio_end` 后停止并固定文本通道 greedy，官方 audio 参数保持不变 | 已实施；三个固定 seed 在同一最终契约下重新冷运行并通过，旧失败证据未覆盖 |
| 2026-08-30 | T6 使用正式 Sidecar 协议对 generated 样音执行 Nano 参考验证，不写数据库、不发布输出音频 | 已实施；requested/actual fingerprint 一致，长期 PawApp 已恢复 ready，批准进入 PRODUCT 施工 |
| 2026-08-30 | PRODUCT 源码与隔离数据库闭环完成；自查补齐失败证据权威时钟、旧媒体删除触发器、真实模型目录、公共响应 scope 和宿主失联恢复路径 | 隔离验收通过；见 `VG40-PRODUCT-IMPLEMENTATION.md`，长期部署与 T7 仍待执行 |
| 2026-08-31 | 长期 `0035`、固定宿主和 PawApp 已部署；正式小说 T7 形成沈砚 generated Version 与四章当前 Edition，四视口播放器和人物卡状态通过真实浏览器复核 | 机器与产品闭环通过；作者听检仍为唯一最终 HOLD，见 `VG40-FINAL.md` |
