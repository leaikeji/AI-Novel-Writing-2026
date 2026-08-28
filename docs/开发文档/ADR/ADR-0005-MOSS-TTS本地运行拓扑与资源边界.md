# ADR-0005：MOSS-TTS 本地运行拓扑与资源边界

状态：**🟢 已由 T0-GATE 条件接纳。正式运行拓扑冻结为 Linux/arm64 Compose 私网 Sidecar，且只作为 `T1-DEP` 的技术输入；固定镜像、真实 Nano、故障/恢复/容器重启、reference 4-case、1804 秒耐久、最终清理与 QwenPaw 健康证据已通过。macOS arm64 managed worker 只保留诊断用途。本文不表示生产 Sidecar、迁移、API 或 UI 已经接入；全部产品开关仍为 false。**

决策日期：2026-08-26（Asia/Shanghai）。

关联资料：

- [MOSS-TTS-Nano 多角色智能朗读产品与技术设计](../18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md)
- [阶段 0 施工证据](../证据/MOSS-TTS-Nano施工/README.md)
- [T0-B 拓扑证据](../证据/MOSS-TTS-Nano施工/T0-B/README.md)
- [T0-C 质量证据](../证据/MOSS-TTS-Nano施工/T0-C/README.md)
- [T0-D VoiceGenerator 证据](../证据/MOSS-TTS-Nano施工/T0-D/README.md)
- [T0-H 契约审查](../证据/MOSS-TTS-Nano施工/T0-H/contract-review.md)
- [T0-H 数据/API/安全冻结候选](../证据/MOSS-TTS-Nano施工/T0-H/gate-decisions.md)
- [T0-E 个人本地版官方预设现行裁决](../证据/MOSS-TTS-Nano施工/T0-E/local-personal-official-presets.md)

2026-08-27 修订：本软件按个人、本机、自用、非商用边界实施。T0-E 历史商业发布／再分发风险审计继续保留，但不再限制个人本地版使用固定 ONNX manifest 的官方预设；本文第 7、10、11 节以下述修订口径为当前权威。

## 1. 决策范围

本 ADR 冻结阶段 1 可以消费的本地模型执行边界、模型/媒体目录、转码规范、任务隔离、幂等与恢复原则，以及 VoiceGenerator 的可见性。它不批准迁移、正式 API、产品 UI 或完整 24 音色包；这些只能由对应阶段门禁放行。

## 2. 已接受决策 1：Linux/arm64 私网 Sidecar

- `linux_arm64_private_sidecar` 是 T0-GATE 选定的正式部署拓扑。选择理由是 Python/ONNX 依赖、模型、崩溃和进程级内存隔离，以及与真实 Linux/arm64 QwenPaw 部署边界一致，不是单样本快了约几十毫秒。
- macOS arm64 / CPython 3.11 managed worker 已通过故障恢复与耐久，但只证明 worker 协议/算法；PawApp 容器不能把宿主 macOS 进程作为自己的受管子进程，因此该路径仅用于开发/诊断，禁止作为生产默认或 Linux Sidecar 的静默回退。
- PawApp 领域服务只依赖 `TTSAdapter`，不得直接 import 官方脚本、模型目录或 ONNX session。
- worker 使用版本握手、PID、generation、request ID 和有界 JSONL/IPC 协议；每个请求显式传 voice、seed、上下文模式和已验证合成参数，不能把人物音色固定成进程全局状态。
- M4 初始单 worker、单推理并发。排队、公平老化、取消和恢复由项目任务层负责；不能通过同时常驻多个 Nano/VoiceGenerator 进程绕过 16 GiB 资源边界。
- 取消能力的首版语义是“当前句段边界确认取消”。若官方推理不能安全中断句内计算，UI 不得写“即时中止”。
- worker 异常退出必须由 manager 发现并以新 PID、新 generation 拉起；旧 generation 的迟到结果不能发布。

阶段 0 已证明的范围以 T0-B 为准。进程内 ONNX 只保留诊断/开发候选；浏览器 ONNX 默认关闭，不能承担持久生成、媒体落盘或恢复。T1-DEP 必须原样消费已冻结的 Linux/arm64 Sidecar 协议和资源边界，不能在接入时改回进程内或宿主 macOS 拓扑。

当前部署与回退顺序冻结为：

1. **已选定：Linux/arm64 Compose TTS Sidecar。** 它只实现窄 worker 契约，不拥有小说、job、Edition、Manifest 或媒体业务真相；不发布主机端口，只走 Compose 私网与短期启动令牌。模型卷只读，音频通过受限响应流回 PawApp，由 PawApp 校验并原子发布。
2. **未批准回退：QwenPaw 容器内独立 TTS venv 子进程。** 只有未来重开 ADR 后才可评估；不得污染 `/app/venv`，也不得在 Sidecar 故障时自动切换。
3. **开发/诊断：宿主 macOS worker。** 性能与故障协议证据可复用，但 PawApp 容器无法把它作为自己的子进程管理；不作为默认产品路径。

T0 已真实验证固定 aarch64 wheel/hash 与 Linux FFmpeg、模型校验、warmup/steady RTF/RSS、取消/kill/recovery、容器重启、无错误 final/`.part`、无主机端口、模型只读、媒体隔离和 QwenPaw 健康。1804.466 秒耐久完成 750 个请求、0 失败、单一 PID/generation、0 restart；最终清理为 0 Sidecar 容器、0 TTS 进程、0 orphan/`.part`。因此 `deployment_topology=GO_TECHNICAL_FOR_T1_DEP`；T1-DEP 仍须证明项目接入后的同等边界，不能把 T0 原型结果写成生产实现。

## 3. 已接受决策 2：结果幂等与非确定性

- render fingerprint 识别一次业务输入和缓存占位，但不把 seed 推导成预期音频哈希。
- 同 seed/参数跨 worker invocation 已出现输出哈希变化；因此成功发布时必须记录 `actual_output_sha256`、actual model/revision/参数和 worker generation。
- 崩溃恢复优先重新校验并复用已经 `ready` 的不可变资产；不得为了“可复现”覆盖旧文件或重新生成后冒充同一资产。
- 临时文件、验证、对象发布和数据库状态写入遵守 `temporary → verified → immutable publish → ready`。任何失败、取消或旧 lease/generation 只能留下可清理临时物，不能留下可寻址 final。
- `requested/actual` 模型证据、内容哈希和幂等键不能由前端或模型输出提供最终权威值。

## 4. 已接受决策 3：任务 fencing 与事务边界

- 持久 job 使用 lease owner、lease generation/token、到期时间、attempt 和幂等键；领取、续租、完成和发布都校验当前 token。
- 外部模型、转码和媒体 I/O 不占用长数据库事务。每次权威状态迁移在短事务内完成，并在发布前后重新校验 owner scope、job token、Edition 和 source hash。
- worker `started/ready/published` 事件按 request/segment/generation 记录；`ready` 文件哈希复核和数据库发布是两件不同的动作。
- 浏览器停止等待不等于后端取消；迟到结果只能作为同一基线下可恢复候选，不能自动进入当前 Edition。

## 5. 已接受决策 4：本地目录、权重与媒体

- 模型和工具固定在受控 `moss-models` 持久卷/本机目录，用户媒体固定在受控 `novel-media` 持久卷/本机目录；仓库、插件包、日志和证据目录不得包含权重、私人参考录音或完整生成音频。T0 原型已证明 Sidecar 模型/源码只读和 PawApp 原子发布边界；T1-DEP 必须在项目 Compose 中声明精确卷、只读/读写责任、权限与卸载保留策略。
- 所有模型、源码和转码器使用固定 revision/version、逐文件 SHA-256、许可证和完整树 hash；下载到临时目录，校验后原子发布。
- 请求不得传文件系统路径。API 和 worker 只接受服务端解析的 asset/model ID；解析后再次校验允许根、owner/workspace/novel scope 与不可变哈希。
- 上传原件、规范化参考音频和锁定音色是受保护来源资产；segment master/播放副本/试听/导出是可重建派生物。

媒体清理使用显式引用图：音色版本、人物绑定、脚本版本、Edition、Manifest revision、segment render、导出和活跃播放会话都属于可达根。物理删除采用 mark、宽限期、重新检查后执行；不能以“数据库当前没有引用”直接删除。

## 6. 已接受决策 5：音频规范与转码

- Nano 原始输出先保存并检查无损 PCM WAV master；当前固定样本为 48 kHz、双声道、16-bit PCM。正式 adapter 仍必须拒绝空音频、不可解码、异常时长、严重静音、削波、声道或采样率漂移。
- 浏览器播放候选为 AAC-LC/M4A，48 kHz、双声道、约 128 kbps。T0-A 已从固定 FFmpeg 9.0.1 源码构建 macOS arm64 LGPL 窄运行时，关闭 GPL、version3、nonfree、网络和自动外部依赖，只启用所需 WAV/FLAC/AAC-LC/MOV 能力；二进制、许可证和构建参数都有固定 hash，并且只能从受控 runtime layout 的绝对路径调用。该 Mach-O 产物不能在 Linux 容器运行；T0-B 已为 Linux/aarch64 Sidecar 独立固定同版本窄 LGPL 运行时与镜像 hash，两个平台产物不得以同一文件名互相冒充。
- 已验证真实 Nano WAV → 逐样本一致的 FLAC master → AAC-LC/M4A 播放副本；损坏输入不发布 final，从已验证 master 恢复转码得到 bit-exact 播放副本。Chromium 151 的 `loadedmetadata`、`canplaythrough`、`playing`、`ended` 均通过且控制台 0 error/0 warning。
- 首版必须保留 WAV 可回退路径。播放格式是 Edition/Manifest fingerprint 的一部分；不能原地把历史资产从 WAV 换成 M4A。
- 转码失败不改变 master 和 Edition 正式状态；只有 master 与播放副本都通过实际字节哈希/解码校验后，播放资产才能发布。

## 7. 已接受决策 6：VoiceGenerator 与音色来源

- `VoiceDesignAdapter` 是可选能力边界；当前 `voice_generator_visible=false`，产品不得显示“文字描述生成音色”入口，也不得创建 T5 正式依赖。
- 决定依据是：固定 VoiceGenerator 与默认 full codec 快照约 10.566 GiB；官方路径只明确 CUDA/CPU，CPU FP32 静态权重下界估算约 14.487 GiB，在 16 GiB 机器上缺少项目要求的安全余量，MPS 未被官方承诺且没有真机通过证据。该值是元数据/静态下界估算，不是峰值 RSS 实测，也不证明模型在 M4 上永久技术不可能；当前裁决只是安全隐藏。
- 完整 24 槽通用音色池仍是独立 `NO-GO`：48 个规划候选尚未形成真实资产、质量听检或去重锁定。该结论不再阻断固定 ONNX manifest 的 18 个官方预设作为个人本地音色来源，也不要求先取得 24 个上传录音。
- 固定 ONNX 仓库 `OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX`、revision `f52645cb467506d8e18e746ddd59482685b74e58` 的 `browser_poc_manifest.json`（SHA-256 `097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee`）所列 18 个预设全部允许用于个人本地展示、试听、绑定、合成和播放，包括 `Trump`、`Xiaoyu` 及带明星／公众人物标签的预设；不得设置名称或人物排除名单。
- 每个官方预设版本写入 `source_kind=official_preset`，并记录官方仓库、revision、精确 preset ID、manifest hash、正式模型 fingerprint `3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d` 与必要 prompt-code hash。既有 `source_type=preset` 只是数据库兼容枚举；旧 `preset_catalog` 只作历史兼容，不能把新官方预设伪装成用户上传或用户原创。
- Python Runtime 与 ONNX manifest 存在同名映射差异时，以当前正式使用的固定 ONNX manifest、模型 fingerprint 和精确 preset ID 为权威，不按名称跨 runtime 猜测替换。官方音频、权重、完整 prompt codes 和生成音频不得进入 Git；运行时从固定官方来源取得或使用模型内嵌 prompt codes。
- 商业发布／再分发仍未评估，T0-E 历史风险台账继续保留，但该信息不得阻断个人本地使用。只有 preset 不存在、prompt codes 缺失、fingerprint／manifest 不匹配、映射冲突、文件损坏或真实推理失败等技术原因可以阻止具体预设。
- “用户上传并确认权利的私人参考音色”仍是独立可选来源，不是官方预设或 T4-K 的前置：multipart 元数据加内联 WAV/FLAC bytes 的窄协议已经冻结，Linux 真容器 3/5/8/12 秒 isolated-test-only 技术 smoke 已通过；但正式 fixture 与人工听感未完成，因此当前 `reference_clone_visible=false`。用户上传录音、`NOASSERTION` Reader 资产和其他外部素材仍不得未经相应门禁打包或再分发。

## 8. 固定主体与隐私

- 当前部署主体由服务端固定本地 owner/workspace scope 提供；模型或浏览器传来的 owner、novel、asset、Edition ID 都必须重新查库校验范围。
- 默认本地分析、本地 Nano、本地媒体。任何正文或参考音频出机都需要用途明确、范围明确、可撤销的作品级授权，并在真正调用时再次检查。
- 私人参考录音不进入日志、模型缓存键明文、证据目录或 QwenPaw 聊天/Memory；诊断只保存脱敏 hash、规格、状态和错误分类。

## 9. 不采用

- 把官方 Python/ONNX 实现直接 import 进 PawApp 主进程作为正式默认。
- 让浏览器直接读取模型目录、文件路径、第三方密钥或承担后台生成。
- 用同 seed 预测输出文件哈希，或在恢复时无条件重生成已 ready 句段。
- 因性能 smoke 看起来更快就忽略故障/依赖隔离。
- 在 16 GiB M4 上同时常驻 Nano 和 VoiceGenerator，或在没有真机余量证据时展示 VoiceGenerator。
- 把代码/模型许可证自动解释为示例人声音频的商用和再分发授权。该条只保留商业发布／再分发风险边界，不否定固定 ONNX manifest 全部官方预设的个人本地可用性。

## 10. 回退与重新开门

- T1-DEP 接入、重建或后续升级若无法维持已冻结 Linux Sidecar 门禁，则关闭 TTS capability，退回固定镜像/模型输入和纯文本写作功能；不得把进程内或宿主 macOS 路径静默升为生产默认。
- M4A/转码失败时优先从已验证 FLAC master 重试；达到重试上限后回退经浏览器验证的 WAV 播放，不删除 master 或历史 Manifest。
- VoiceGenerator、Sidecar、浏览器 ONNX、官方预设来源和完整通用音色池使用相互独立的 capability；官方预设来源不得因 24 槽、VoiceGenerator、reference clone 或商业发布／再分发未评估而连带隐藏。catalog、固定 hash/fingerprint、Sidecar 或真实推理未就绪时仍须因技术原因 fail-closed。
- 禁用 PawApp 后立即停止续租和签发 worker token；Sidecar 必须在短租约到期后的有界时间内拒绝旧 token、卸载模型并进入 inert/idle，即使通用 QwenPaw 插件 UI 没有专属容器停止钩子也不能继续处理。完整项目卸载再由仓库内脚本串行停止 Sidecar、注销适配器和公开路由，并按声明保留模型/用户源资产/作品数据；不得修改或遗留 QwenPaw 核心拦截。
- 升级必须同时校验 runner protocol、镜像 digest 与 model fingerprint。握手失败时保持 TTS capability off，不影响原生聊天；旧 Sidecar image、模型 revision 和配置作为显式回退点。

## 11. T0-GATE 结果与后续产品门禁

1. Linux/arm64 Compose Sidecar 的真实 smoke、reference 4-case、1804 秒耐久、最终退出/清理和 QwenPaw 健康已经通过，T0 只据此放行 `T1-DEP`；
2. Nano 中文 20-case 技术矩阵已通过，人工听感仍为 `NOT_REVIEWED`；在 T4 用户可见门禁前不得以自动指标替代；
3. reference-audio 窄协议与 3/5/8/12 秒 Linux 技术 recheck 已通过，但正式授权产品资产和人工听感仍缺失，因此保持 `reference_clone_visible=false`；
4. 固定 FFmpeg 的源码 PGP 链与再分发义务仍是商业发布／再分发门禁；Safari/Firefox/移动端矩阵属于历史扩展验证设想，不是当前个人本地 T4 发布阻断。当前 TTS UI 只验收 1920×1080、2560×1440 与助手收起／展开四个精确组合；
5. T0-E 逐项权利矩阵作为商业发布／再分发历史审计保留；个人本地版改为纳入固定 ONNX manifest 的全部 18 个 `official_preset`，不因明星／公众人物标签排除。当前 capability 是否开启只等待 catalog、溯源、模型 fingerprint、实际推理与对应产品门禁，不再等待商业授权裁决。

T0-H 的 10 项精确数据/API 裁决已由 [T0-GATE](../证据/MOSS-TTS-Nano施工/T0-GATE.md) 对固定 hash 作 `ACCEPT_UNCHANGED`：固定 UUID scope、novel 直接归属、request/analyze-only guard、taxonomy v1、job attempt fencing、Manifest 无限期历史保留与 24h/7d GC、独立权利表、versioned HMAC 以及 true-delete/backup 状态均已有唯一 Owner 与测试映射。它们仍尚未实施。

T0-GATE 已按以上明确降级接纳本文，下一且唯一 ready set 是 `T1-DEP`。其余产品能力仍须等待对应阶段门禁，不得因 ADR 已接受而提前启用。
