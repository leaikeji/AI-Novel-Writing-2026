# T4-K 真实章节门禁准备报告

> **2026-08-28 v3 当前权威状态：**canonical run `bb03ccaf-4681-490a-b987-84bec9199b3b` 已在固定官方 ONNX manifest 的原始 prompt codes 与官方默认参数上完成真实章节技术链：旁白 `onnx.Zhiming`、沈川 `onnx.Junhao`、林晚 `onnx.Xiaoyu`，统一 `seed=1234 + sample_mode=fixed + do_sample=true + max_new_frames=375`，未使用项目调音或替代映射。自动／人工 Nano、网页播放器、CodeMirror、段落／光标跳播、latest-wins、Range/ETag、四桌面组合、30 分钟稳定性和基线恢复均为技术 `PASS`。作者已明确确认“完整章节通过”，六项 listening finalize 已提交，同 run resume 返回 `PASS_CANDIDATE`，teardown 返回 `TOOLS_CLEANED`；human state 为 `PASS`。完整指标及失败历史见 [v3 官方默认参数真实章节技术验收](./v3官方默认参数真实章节技术验收-2026-08-28.md)。

> **2026-08-28 最终产品候选：**最终 tree `7a57471ebe9ea6cffc6d76529e3fdcab6c1683ad236499fbc2d1fdfb720bde13` 已在长期 QwenPaw 安装并与安装源码树精确一致；迁移 head `20260828_0024`，正式 product mode、6 个中文 preset、三容器 healthy/restart=0 和 validation token 缺失均已复核。复核中安全删除了旧“通用音色 24 分类位”前端页面、入口、样式、仅供其使用的 API／DTO 和 7 项非目标测试；迁移与历史证据保留。系统中文输入法由作者本人亲自输入至少两个汉字并确认正常；自动 supplemental envelope 未生成，按非阻断边界保留。最终裁决见 [T4-GATE](../T4-GATE.md)。

> **2026-08-28 v3 fresh run 前置复验历史：**三项正式绑定已切换到新的 append-only 官方默认版本，统一使用 `seed=1234 + fixed + 375`，新 baseline Edition `2f9d6e0a-961b-4355-b626-8e3be03138c4` 已 56/56 ready 且成为 current Edition。原 `chapter-e2e-v2.json` 的一个 `onnx.Junhao` 句段曾以 `NANO_AUDIO_INVALID` fail-closed；隔离复现确认是特定文本在官方固定采样下产生异常长输出，不是项目换参或调音。v2 与失败 run 已冻结为历史；新增 v3 只替换项目自有测试句，仍保持 57 句段、自动链 0 blocker、人工链精确 3 blocker。该段计划中的 fresh 技术运行已由 canonical v3 run `bb03ccaf-4681-490a-b987-84bec9199b3b` 完成，历史失败不得重标 PASS。

> **2026-08-28 官方默认参数最终裁决：**作者已确认三个官方 preset 的 146 字官方 manifest 默认参数试听完全正常。产品现统一使用固定官方 prompt codes 与默认生成参数，固定运行时初始 RNG seed 为 `1234`；`fixed_seed_1` 专项短句策略和 seed 0 项目基线均降为 `SUPERSEDED_DIAGNOSTIC_NON_PRODUCT`，不得进入新的产品 Voice Version／Edition。历史失败和回归证据不删除、不重标。当前代码已默认停用短句专项策略并冻结新官方 preset Voice Version 的默认 seed `1234`；v3 真实技术门禁、完整章节人工听检、同 run resume／teardown 均已完成。

> **阅读顺序：**下方 fixed seed 1 的“必须继续等待作者选择”属于历史失败处置记录，已被上方最终裁决取代；不得再把它作为当前等待项或门禁。

> **2026-08-28 历史质量诊断（`SUPERSEDED_DIAGNOSTIC_NON_PRODUCT`）：**旧 run `270ea179-e3cf-4095-a928-56b414070719` 的样本 01、04 曾被作者明确判为不可理解中文，最终保持 `HUMAN_LISTENING_FAILED / REAL_PRODUCT_VALIDATION_HOLD`。fixed seed 1 与 greedy 只作为隔离诊断候选，已被官方默认参数最终裁决取代，不得进入产品或覆盖本页首段的 v3 当前状态。详见[人工听检失败与短提示语诊断](./人工听检失败与短提示语诊断-2026-08-28.md)。

状态：`THREE_OFFICIAL_PRESETS_CONFIRMED / OFFICIAL_MANIFEST_DEFAULTS_AUTHOR_CONFIRMED / V3_REAL_PRODUCT_TECHNICAL_PASS / HUMAN_LISTENING_PASS / SAME_RUN_RESUME_PASS / TEARDOWN_PASS / PRODUCT_MODE_VERIFIED`

日期：2026-08-28（Asia/Shanghai）

## 结论

T4-K 的真实章节验收工具链已经完成隐藏验证、一次性操作员信封、单调恢复链、人工听检两阶段提交和 teardown verifier 的代码加固。现行架构把 Node／Playwright 浏览器报告、Sidecar／宿主指标和人工听检定位为作者／操作员在本人 Mac 上生成的本地验收证据：仍必须绑定同一 run、novel/document scope、fixture、权限、Edition／输出 hash、精确 viewport、30 分钟指标、恢复和 teardown，但不宣称密码学远程证明，也不要求独立 controller authority、正式私钥、active trust root 或 OS signing service。仓库中已有 OpenSSH Ed25519 SSHSIG／preflight／report-binding 候选只保留为非阻断安全实验与历史审计，不进入 PawApp 生产包，也不得再阻止真实运行或 T4-GATE。

专用小说、章节、林晚／沈川人物卡已经在永久隔离 scope 中建立。作者已实际确认并完成三个互异 `official_preset` 的 `locked + accepted + bound`：旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao`。首次 baseline 曾因重复规范句段的 render fanout 缺陷 fail-closed；完成“一次合成、同请求安全 fanout”修复后，2026-08-27 真实 Nano baseline Edition 已建立成功。旧 run `270ea179-e3cf-4095-a928-56b414070719` 的技术通过与后续人工听检失败均保持历史原貌，不再作为当前状态。现行 canonical run `bb03ccaf-4681-490a-b987-84bec9199b3b` 已以 result/probe 2.2 同 run 完成自动／人工未缓存 Nano、真实 `partial_ready`、pending-gap、四桌面组合、播放器／CodeMirror 主交互、报告自动导入、固定精确 31 点／30 分钟技术门禁与基线恢复。作者完整章节听检、同 run resume 和 teardown 也已通过，长期产品模式已经验证；补充浏览器自动 envelope 未生成的事实另行保留，不覆盖作者本人已确认的系统中文输入法产品验收。

上述稳定性失败以及 2026-08-28 后续同类失败都是当时 result/probe 2.1 “任意全机 pageout 大于 0 即失败”门禁的真实结果，必须原样保留，不得重标 PASS。result/probe 2.2 以固定 31 点 Sidecar 容器内存趋势、`peak<=4 GiB`、restart=0、health failure=0 与 QwenPaw slowdown=false 作硬门禁；原始 pageout/swapout 保留为 telemetry，其类型、非负性和派生布尔一致性仍 fail-closed，但非零不再单独阻断。run `bb03ccaf-4681-490a-b987-84bec9199b3b` 已对 2.2 完成 fresh real run 并取得技术 PASS，tree `e40d6314…` 的真实隔离安装生命周期也已 PASS；作者听检、同 run resume/teardown 和长期产品升级随后均已完成。自动 supplemental envelope 未形成，按“核心浏览器 PASS + 作者系统 IME PASS + supplement 非阻断未生成”分层记录，不再阻断 T4-K。

本报告的现行正式范围是个人、本地、单用户。产品可展示／试听／绑定／合成／播放的目录仅为六个中文预设：`onnx.Junhao`、`onnx.Zhiming`、`onnx.Weiguo`、`onnx.Xiaoyu`、`onnx.Yuewen`、`onnx.Lingyu`。固定 ONNX manifest/catalog 的 18 项全集只作底层兼容和技术溯源，不进入当前 UI、中文专项质量或 T4 发布门禁。商业／再分发审批、英语／日语专项、云端／远程／共享／复杂继承、OS／SSHSIG／正式 key 和章节／全书音频导出均已 superseded 或为非目标、非阻断；历史审计原文保留。云端辅助说话人识别和高级匿名人物选角仍为 HOLD／待用户裁决。

本阶段没有新增数据库、任务队列或测试容器。权威数据仍使用项目现有 PostgreSQL，合成仍使用既有 `ai-novel-2026-moss-tts-sidecar`，固定启动器只组合既有 PawApp HTTP、窄只读数据库审计与外部浏览器／运行指标报告。

2026-08-27 的真实 `partial_ready` 代码候选和本地固定编排器已经在 2026-08-28 进入真实运行，不再只是“尚未执行”的源码候选。现行 run `bb03ccaf-4681-490a-b987-84bec9199b3b` 已形成同一 run 的 `partial_ready`、`browser_observed`、合格 30 分钟窗口、基线恢复、最终听检、resume 和 teardown；长期产品升级也已完成。历史代码候选见 [真实 partial-ready 与本地编排器代码候选](./partial-ready-orchestrator-candidate-2026-08-27.md)，当前 v3 指标见 [v3 官方默认参数真实章节技术验收](./v3官方默认参数真实章节技术验收-2026-08-28.md)。

### 2026-08-28 当前 head 回归与真实安装生命周期

- 后端全量：`2591 passed, 116 skipped, 2 warnings`；TTS/narration 专项：`2116 passed, 83 skipped, 1 warning`。warning 均为既有 Starlette/FastAPI 弃用提示，无失败。
- 前端：`pnpm typecheck` 通过，87 个测试文件／805 项测试通过，生产 build 通过；打包、安装／teardown 契约 167 项通过，`docker compose config --quiet` 通过。
- PawApp 候选 tree SHA-256 为 `729900887c2c2022a3d5fd2bec2afe846414249b8fe37fec285826f49f81ec53`。真实隔离 run `t4klife0828` 完成安装、强制原位重装、公开 API 卸载和再安装；卸载后插件路由、静态文件、Skills 和工具零残留，QwenPaw 原生 Agent／Skills／Tools／前端 shell 仍可用，数据库与卷哨兵跨重装保留。
- 验收仅临时创建 2 个隔离容器、5 个隔离卷和 1 个内部网络，全部按 run label 精确删除，`cleanup failures=[]`、`broad_cleanup_used=false`；现有 QwenPaw／PostgreSQL／Sidecar 三容器仍 healthy、restart=0。
- 脱敏 transcript 见 [`qwenpaw-lifecycle-2026-08-28.json`](./qwenpaw-lifecycle-2026-08-28.json)，文件 SHA-256 为 `9837f1b5f29a1c9524c5d968581eea4675b7cc2880c1eeca2c1ba8a3bb32e1bb`。

### 2026-08-28 K／L 运行增量

- K：run `03e4ee99-22f1-409e-9ac8-bbbf0185c45b` 使用了超出正式 UI `0.75x～2x` 范围的 `4x`，因此 browser `HOLD`；运行已恢复，后续已改回正式范围内的 `2x`。K 不构成正式倍速验收证据。
- L：run `fd1a6337-c6f1-43cb-91f9-03346c955c27` 的自动链与人工链均 PASS，聚合结果为 57 cache hit、2 miss、58 ready、426800 ms；但运行中断并返回 `PARTIAL_READY_VALIDATION_FAILED`，没有浏览器观察证据或运行观察证据。working copy 与作者可见 Edition 均已恢复，L 明确为非通过。
- K／L 均是历史未通过运行，没有补齐当时同一 run 的 30 分钟稳定性、最终听检或 teardown；它们不覆盖后续 canonical v3 与产品模式通过事实。

## 已完成的准备

- `T4-K-C`：新增项目原创、授权用于 TTS 且不含参考音频的 `tests/fixtures/narration/chapter-e2e-v2.json`。当前 schema 为 `moss-tts-chapter-e2e-fixture/2.1`，自动链 1110 字符、人工链 1172 字符，均含林晚／沈川两名明确人物；真实领域分析已锁定自动链 0 blocker／2 人物、人工链精确 3 blocker／2 人物，首段修正定位同时锁定 UTF-16 范围与本地 hash。fixture 文件 SHA-256 为 `e970e4f837d2f96b2675e8922e43bb5dfcffc352e86f0f96b84e34db1065380b`。2.1 进一步冻结 `expected_formal_speakers=["林晚","沈川"]`、`voice_scope=local_personal_use`、`production_eligible=true` 与 `commercial_distribution_status=not_evaluated`；个人本地 PASS 候选不再被商业状态降为 technical-only。校验器另冻结仓库外私有恢复记录、追加式恢复和脱敏结果契约；直接 CLI 默认不具备真实 executor。
- `T4-K-C3`：v2 保持不可变并专门承载已发生的官方参数失败与恢复历史；fresh 路径新增 append-only `tests/fixtures/narration/chapter-e2e-v3.json`，文件 SHA-256 为 `3cfb094c3a3374eb233ccff5c08963adaba5cac55e5ec056ff5257d32e421913`。v3 自动链仍为 1110 字符／0 blocker，人工链为 1170 字符／精确 3 blocker，57 个句段及首段人工修正契约不变；唯一替换的项目自有 `onnx.Junhao` 测试句以官方 `seed=1234 + fixed + 375` 两次真实生成均为 4160 ms，actual WAV SHA-256 均为 `d0bbe9792100a10c9993968391624f154b3d0d7c86074436f82c8b8d214dde43`。这不是修改用户正文或音色参数，也不抹除 v2 失败。
- `T4-K-X`：仅允许 loopback、固定 PawApp API 前缀的真实 HTTP executor；覆盖零阻塞自动链、人工修正／批准链、Manifest、Range/ETag、输出 hash、ModelRun fingerprint 绑定和基线恢复。
- `T4-K-P`：只导入仓库外、当前 uid、`0600`、单硬链接、无符号链接、限长且未过期的严格 JSON；报告必须绑定 run、novel/document scope、自动／人工 Edition 和听感输出 hash。
- `T4-K-A`：现有 PostgreSQL 上显式 `SET TRANSACTION READ ONLY` 的窄审计；现行目标是核验专用章节、旁白加林晚／沈川两名 exact-name active 人物及其 dedicated binding，以及三个互异、已锁定／接受的官方预设版本。每个版本必须证明 `source_kind=official_preset`、固定官方仓库／revision／manifest SHA-256、精确 preset ID、正式模型 fingerprint 与必要 prompt-code hash；三者的 preset ID 互异且与 Sidecar 实际模型 fingerprint 一致。旧 `source_type=preset` 仅作数据库兼容，不得伪装为上传音色。Edition、job、render、生成媒体和成功 ModelRun 仍须绑定同一模型 fingerprint；每条 ScriptSegment 还必须证明旁白、林晚、沈川分别使用自己的冻结版本且三者实际出现。审计不再要求用户上传 reference/source 媒体，也不返回正文、音频字节、路径或秘密。
- `T4-K-L`：唯一固定真实启动器；在装配数据库和 executor 前持有 `LOCK-NANO`、`LOCK-BROWSER`、`LOCK-T4-K-DATA` 三把仓库外私有锁，CLI 不接受任意 import、shell 命令、数据库 URL 或自由探针 JSON。两条链完成后，启动器先在仓库外 `0700` private work dir 独占创建 `0600 probe-request.json`，只交付 run/scope/Edition 哈希、输出哈希和固定视口矩阵，再等待外部报告；文件不含正文、音频、原始 ID、路径或凭据，已有旧握手时拒绝覆盖。
- `T4-K-V`：新增隐藏验证安全信封。validation token 只允许仓库外当前 uid 的 `0700` 目录／`0600` 单硬链接普通文件，宿主与 QwenPaw secret volume 保存同值副本，命令行、环境变量、URL、日志和证据均不得出现 token 或摘要；validation scope 必须是 canonical novel/document UUID 与未来不超过 24 小时的 UTC 秒级 expiry。HTTP 除 token 外还要经 SELECT-only scope 核验；worker 的领取、重试晋升和过期租约恢复同时限定 novel、document、`moss-nano` 与允许的 job kind，到期后不再开启事务或领取新任务。
- `T4-K-Q`：只读就绪审计 `scripts/tts/chapter_e2e_readiness.py` 的现行目标只接受仓库外 `0600` 操作员 attestation，核验 fixture 绑定、专用范围声明、三把私有锁、精确四桌面组合、现有 PostgreSQL schema／基线指针，以及三套 profile/version 的 `official_preset` provenance、互异 preset ID、固定 manifest／模型 fingerprint／prompt-code hash。三份用户上传录音与六份 source/reference 媒体不再是输入。输出只含稳定缺失码及聚合计数；即使所有条件齐全也只返回 `status=HOLD`、`decision=READY_FOR_OPERATOR_REVIEW`，绝不自动给出 `PASS`、写数据、启动模型或翻转 capability。三个预设已确认／锁定／接受／绑定，baseline Edition 已 `ready`；真实私有 attestation／envelope 已用于 canonical v3，Q 只负责运行前准备判定，最终 PASS 来自后续同 run 技术、听检、恢复和 teardown 汇合。
- `T4-K-O`：新增 `scripts/tts/chapter_e2e_operator_envelope.py`。发行器必须重跑 Q 并取得 `READY_FOR_OPERATOR_REVIEW`，随后要求作者显式输入 `AUTHOR-REVIEWED-T4-K-READINESS`，才会独占写入 15 分钟有效的 `moss-tts-t4k-operator-envelope/1.0`。信封绑定显式 run UUID、scope、fixture/case、30 分钟、精确四桌面组合、三锁 grant/物理身份、attestation/Q 摘要、随机 nonce 和作者复核时间；不含 token、正文、录音、路径或数据库 URL。正式 launcher 现在强制接受同一 envelope、attestation 与 `--run-id`，在数据库/executor/真实写入前持有三锁、重新执行 Q、核对全部绑定并以 `O_EXCL` 创建一次性 claim；普通二次运行拒绝，恢复只接受同信封、同 run 的既有 claim，且不会因为 15 分钟已过而阻止安全恢复。
- `T4-K-S`：补齐 probe report、三把锁和 listening record 的仓库／已安装 PawApp 根外私有路径门禁。其父目录必须是当前 uid 的 `0700` 普通目录，文件必须是当前 uid 的 `0600`、普通文件、单硬链接且无任意符号链接组件；读取通过目录 FD、`O_NOFOLLOW` 和前后身份复核，错误只返回稳定码，不渲染路径或内容。正式 TTS UI 捕获仍且仅接受 1920×1080／2560×1440 与助手收起／展开四组合。
- `T4-K-RCV`：恢复文件升级为单调 generation／previous digest 链，操作员 claim 同步保存 state、generation 和 latest digest。所有会改变作者权威状态的请求在写前先持久化 old/next fence intent，resume 只允许观测值精确等于 old 或运行预计 next fence。claim 与 recovery 差一代时，必须先完整验证 schema、run/scope、fixture 和 claim binding，再由同一 lease 原子对齐；旧代重放、跨 run 或错 binding 均不能推进 claim。证据先持久化后才进入 `FINALIZATION_PENDING → FINALIZED`，在 claim 已 final 但 recovery 尚未删除的狭窄崩溃窗可幂等继续。
- `T4-K-HL`：作者听感结论使用中央 `PREPARED` claim 与独立 `COMMITTED` marker，精确绑定 run/scope、两个 Edition fingerprint、输出 hash、record／receipt hash 以及输出目录 canonical path／物理身份。claim、receipt、record 或 commit 窗中断后，只有完全相同的作者决定才能续写；冲突内容永不覆盖。输出或 registry 目录在事务中被 rename／replacement 时按本次 inode 回滚且不提交。validator 只导入 `reviewed_at >= collector.collected_at` 且 claim、commit、record、receipt 四者一致的结论。这是作者本人的明示听感记录，不伪装成第三方审计签名。
- `T4-K-TD`：新增固定 teardown verifier，默认只读检查 runtime=true、validation/product/reference=false、普通 overview 精确 T2、隐藏路由 `404 + no-store`、安装器与三个长期容器拓扑、token 双副本身份以及现有 PostgreSQL 的目标 worker claim 只读审计。只有 verify fingerprint 与两个精确销毁确认同时满足才调用既有 token provisioner 的可恢复销毁路径；不删数据库、媒体、音色或卷。
- `T4-K-BR` 历史实验：collector schema 曾升级为 `moss-tts-chapter-e2e-collector/2.0`，并试验 report／probe／commit 三文件私有原子事务、SSHSIG 与 canonical report binding。该实验对跨 run/scope/request、错误 actual viewport、少于 30 分钟和错误指标链保持 fail-closed；但它只证明签名与校验代码候选行为，不是个人本机产品的必需信任边界。空 production trust root 返回的 `COLLECTOR_CONTROLLER_AUTHORITY_HOLD` 仅属于这条实验路径，不再是 T4-K 真实运行或 T4-GATE 的阻断理由。
- `T4-K-PERF-GATE`：当前技术结果 schema 为 `moss-tts-chapter-e2e-result/2.2`，Probe 为 `moss-tts-chapter-e2e-probes/2.2`，正式 Collector 继续使用 `moss-tts-chapter-e2e-collector/2.0`，本地作者／操作员执行使用 `moss-tts-chapter-e2e-local-operator/1.1`；旧 result/probe 2.1 只作历史证据，不得按 2.2 语义重解释。预热后的黑盒 `RTF <= 1.0` 仍是不可覆盖的硬门槛。内存趋势对 31 点容器样本的首 5 点和末 5 点分别排序取中值，`growth=max(0, tail-baseline)`、`limit=max(128 MiB, ceil(baseline×5%))`，仅 `growth>limit` 失败，等号通过；另硬性要求 `peak<=4 GiB`、restart=0、health failure=0、`qwenpaw_slowdown_observed=false`。`pageout_delta`、`swapout_delta` 与 `host_paging_observed` 仍是无默认值的必填 telemetry，缺失、非精确类型、负数或布尔与差值不一致均 fail-closed，但 paging 非零不再单独导致失败。run `270ea179-e3cf-4095-a928-56b414070719` 已真实通过该 2.2 技术门禁，但不代表人工听检或 T4-GATE 已通过。
- `T4-K-AUTH-2/4/5` 历史实验：public-only verifier、launcher preflight、collector report-binding 和同进程 signer 的红队记录继续保留。第二轮红队正确证明“同进程 Python 私有零参数 signer factory”不能形成独立权限边界；同时，用户已裁决个人本机版本不需要密码学远程证明，因此不再建设或等待 PawApp 包外 OS controller/signing service、daemon/launchd、专用身份、正式 key 或 active trust root。相关 TOCTOU、重放和身份隔离问题只在未来重新立项远程证明／高对抗证明时才成为该实验的 P0，不得套用为本地产品 no-go。

- PawApp 包边界已加固为 frozen public allowlist：打包器拒绝 signer/lifecycle/host/build/evidence/browser/runtime observer、askpass、整个 `controller-node/`、宿主 key、agent socket 和签名文件进入产品包，并核验精确 TTS 文件集合。现行本地验收继续把 Node／Playwright 与指标采集保留在作者／操作员宿主侧；上述签名候选、key、socket 和 authority 工具均不进入 PawApp 生产包。若未来另行立项远程证明，再独立评估其信任根和发布流程。

2026-08-27 的发布复核发现旧 launcher 可以绕过 Q、旧 attestation/recovery 可重放，probe/listening/lock 路径门禁未达本文口径，且同 uid HMAC 不能证明浏览器 controller 真实执行。O/S、RCV、HL、TD 已关闭前三类产品安全缺口；“同 uid HMAC 不能形成远程证明”的结论继续作为历史审计事实保留，但个人本地验收不需要该证明。作者音色确认、baseline render fanout 修复、真实 Nano 基线重跑、同 run pending-gap/browser 提交和合格 30 分钟技术窗口已经完成；当前不得越过最终听检、同 run resume/teardown，以及因当前候选源已变化而必须重跑的安装生命周期非回归门禁，但不再因 BR/AUTH 实验未形成独立签名权威而禁止真实执行。

外部探针把握手中的 `binding_seed` 原样复制到最终报告，并以报告自己的 UTC `collected_at` 计算 `sha256(canonical_json({schema_version: report_schema_version, collected_at, ...binding_seed}))`；严格导入器会重新计算并核对。这样外部采集器无需读取包含基线正文的 `recovery.json`，也不能把旧报告复用到新 run。

## UI 验收范围

用户已冻结 TTS UI 发布验收且仅接受以下四种精确组合：

| 视口 | 原生 AI 助手 |
| --- | --- |
| 1920×1080 | 收起 |
| 1920×1080 | 展开 |
| 2560×1440 | 收起 |
| 2560×1440 | 展开 |

低于 1920×1080、移动端、窄屏和 200% 等效小视口均不设计、不测试，也不阻断 T4-K/T4-GATE。此前历史阶段留下的窄屏截图只保留为历史记录，不代表继续承担产品承诺；已有防御性窄屏 CSS 可为避免宿主回归而保留，但不会新增低分辨率设计、截图或人工验收。

此前固定宿主曾对上述四种组合做过只读布局预检。该次 2026-08-27 实机预检使用 Codex in-app Browser，先读取实际 `window.innerWidth/innerHeight` 再判定组合：Browser viewport override 的请求值并不等于页面实际 CSS viewport，1920×1080 需要在本机当前窗口校准到请求 1939×1091，2560×1440 需要校准到请求 2586×1455；校准后助手收起／展开四组的实际 inner size 均精确命中目标，`documentElement.scrollWidth == window.innerWidth`，未见水平溢出。校准值只属于该次宿主窗口，不能固化成跨环境常量。当时公开页面仍保持 T2，没有执行真实章节媒体交互，因此只是历史预检，不得与本报告后文的最新真实固定 Edge 产品交互报告混淆。

最新固定 Edge 报告已在真实 baseline Edition 上完成四组合、播放器、CodeMirror、跳播、播放控制和媒体 HTTP 验证，详见“2026-08-27 真实固定 Edge 产品交互报告”节。该报告仍是作者／操作员的本机证据，不是密码学远程证明，也不单独构成 T4-K/T4-GATE `PASS`。

## 隐藏验证运行态与公开放行边界

T4-K 需要启动与生产相同的现有 backend/worker 路径，但这不能导致未验收能力对普通用户可见。为此，真实运行冻结为：

- `AI_NOVEL_TTS_RUNTIME_ENABLED=true`，复用既有 Sidecar 与技术 runtime；
- `AI_NOVEL_TTS_VALIDATION_ENABLED=true`，启动隐藏预发布生产 pipeline；
- `AI_NOVEL_TTS_PRODUCT_ENABLED=false`，且服务端投影 `product_visible=false`；
- `AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=false` 是本次有限核心固定值；旁白、林晚、沈川使用运行前已从同一固定 ONNX manifest 建立、锁定并绑定的三个互异 `official_preset` 版本，本次不要求也不开放上传／克隆 UI；在独立 reference-clone validation 工作包获批前，服务端、安装器和固定 launcher 均硬拒绝 `validation=true + reference=true`；
- validation 与 product、validation 与 reference 均严格互斥，共用当前进程内 backend/worker，不新增数据库、容器、队列或第二套业务服务；
- `AI_NOVEL_TTS_VALIDATION_NOVEL_ID`、`AI_NOVEL_TTS_VALIDATION_DOCUMENT_ID` 必须精确指向专用小说与 chapter，`AI_NOVEL_TTS_VALIDATION_EXPIRES_AT` 必须是未来不超过 24 小时的 `YYYY-MM-DDTHH:MM:SSZ`；scope 过期后 token 立即失效，worker 不再领取、晋升或恢复该验证任务；
- host 副本位于宿主仓库外、当前 uid 的 `0700` 目录／`0600` 文件，路径通过 `QWENPAW_TTS_VALIDATION_TOKEN_HOST_FILE` 只交给安装编排器；container 副本固定为既有 `qwenpaw-secrets` 卷内 `/app/working.secret/ai-novel-world-2026/t4k-validation/token`，并由 `AI_NOVEL_TTS_VALIDATION_TOKEN_FILE` 指向。容器内 launcher 只读取 container 副本，不新增 bind mount。provision／verify／destroy 均不回显 token 或摘要，destroy 只有在两份副本身份一致时才删除，单边缺失或不一致会保留并报错；
- 隐藏 HTTP 请求必须且只能出现一条 `X-AI-Novel-TTS-Validation` header。无 token、错误 token、重复物理 header 均对 narration、script、playback 三类 T4 路由返回门禁专属 `404 + Cache-Control: no-store`，不得产生领域写入；同三种负向请求的 novel overview 精确保持 T2，正确 token 且同 novel scope 的 overview 才临时投影 T4 核心能力。document 约束由启动时 chapter 归属校验及后续 document/request/Edition/script 路由共同证明；
- 面向用户的 reference-clone 创建／上传产品 capability 在 T4 有限核心中继续 HOLD。若未来另行验证 reference clone，必须新建并批准独立工作包，证明 reference flag、真实 voice product port、novel 级 preview 任务、权利与清理链后再修改当前硬拒绝，不得借本次有限核心顺带放行。

上述是真实 T4-K 运行的前置合同。canonical v3 已形成真实技术与人工听检证据，并完成同 run resume／teardown；历史 launcher 在构造 executor、读取 baseline 或执行写请求之前完成了 13 个只读负向／tier 探测。有限核心的三态矩阵冻结如下；当前产品处于第三行，reference 只有独立门禁通过后才能另行改变：

| 状态 | runtime | validation | product | reference | 对普通用户 |
| --- | --- | --- | --- | --- | --- |
| 历史 T2／T4-K 前后 | `true` | `false` | `false` | `false` | 精确 T2 |
| 隐藏 T4-K | `true` | `true` | `false` | `false` | 仍精确 T2，仅正确 token + scope 临时 T4 |
| 当前有限核心公开 T4 | `true` | `false` | `true` | `false` | 长期产品模式已验证 |

T4-GATE 只能在有限核心公开矩阵下，且技术 runtime 的生命周期／Sidecar／模型就绪、生产 pipeline 的生命周期／播放链／digest keyring／backend／worker 就绪和无失败 reason 全部成立时，才可提议公开 capability；任一项缺失都必须 fail-closed。

## 历史固定操作顺序（canonical v3 已执行完成）

2026-08-27 最新范围已取代“把 T4-K runner/fixture 放入 PawApp 包”的旧路径：PawApp 生产包只包含产品运行所需代码和 digest-keyring 管理脚本，不包含 T4-K runner/readiness/fixture，也不包含 controller trust/signing/authority 候选。T4-K 工具继续保留在项目仓库，定位为作者／操作员运行的本地固定验收执行器；真实运行如需访问容器内 PostgreSQL／named media volume，只能通过固定、可复核、运行后清理的本地编排进入现有 QwenPaw 容器，不能把验收工具永久安装进产品、创建额外长期容器、第二数据库、bind mount 或仓库内秘密文件。container token、私有 attestation、三把锁、recovery、listening 和 probe report仍位于现有 `qwenpaw-secrets` 中的 T4-K 专用 `0700` 子目录；host token 单独位于宿主仓库外私有目录。外部浏览器采集器只通过不回显内容的受控 stdin／文件交换写入同一 container 私有目录。

严格顺序如下，任何一步失败都停止，不能越过：

1. 只读确认长期运行拓扑恰好为现有 PostgreSQL、QwenPaw、MOSS-TTS Sidecar 三个 healthy 容器；runtime=true、product=false、validation=false、reference=false，普通 overview 为 T2。
2. 在 `qwenpaw-secrets` 内建立本次专用 `0700` 目录与三个互异 `0600` 空锁文件；禁止复用上一 run 的 attestation、token、probe request、probe report、recovery 或 listening 文件。
3. 持有 `LOCK-T4-K-DATA`，在永久隔离小说中复核已完成的三项不可变绑定：旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao`；修复重复规范句段 render fanout 后重试并成功建立可恢复 baseline Edition。每个版本继续绑定固定仓库、revision、manifest SHA-256、精确 preset ID、模型 fingerprint 和必要 prompt-code hash；不得按名称跨 runtime 猜测替换。
4. 生成仓库外私有 attestation：绑定 fixture SHA-256、canonical novel/document UUID、个人本地自用声明、三个精确官方 preset ID 及其不可变 provenance 摘要、精确人物顺序、精确四桌面组合，以及三把锁的名称／路径／grant。attestation 不进入 Git、日志或证据目录。
5. 在既有 QwenPaw 容器中运行 `chapter_e2e_readiness.py --mode readonly --attestation-file <private-file>`。只有 canonical 输出仍为 `status=HOLD` 且 `decision=READY_FOR_OPERATOR_REVIEW`、`missing_codes=[]` 时，才交给作者复核；退出码 0 也不等于 PASS。
6. 复核三个精确 `official_preset` 绑定未漂移且 baseline 已成功后，为本次运行预先生成一个 canonical UUID，并使用 `chapter_e2e_operator_envelope.py --mode issue`、同一 attestation 与固定确认词发行不可覆盖的短时信封。发行器会再次只读执行 Q；manifest、fingerprint、preset ID 或其他条件漂移都会停止。该 UUID 和信封只能用于紧接着的一次 fresh run；失败恢复必须使用其既有 claim。
7. 使用固定 provisioner 在宿主私有 `0600` 文件和既有 secret volume 中原子创建同值 token；verify 必须通过。token 不写 `.env`，只把 host file 路径交给安装编排器。
8. 设定本次 canonical novel/document scope 与不超过 24 小时的 expiry；安装编排器同时设置 `QWENPAW_EXPECT_TTS_RUNTIME=ready`、`QWENPAW_EXPECT_TTS_VALIDATION=ready`、`QWENPAW_EXPECT_TTS_PRODUCT=disabled`、`QWENPAW_EXPECT_TTS_REFERENCE_CLONE=disabled`、`QWENPAW_TTS_VALIDATION_TOKEN_HOST_FILE=<host 私有路径>`，并设置对应实际四值 runtime=true、validation=true、product=false、reference=false。先把现有 QwenPaw 以四个实际开关全 false 安全重建为安装基线，再使用公开安装／升级流程进入隐藏矩阵；不得重建或删除 PostgreSQL／媒体／QwenPaw 数据卷。
9. 先核验完整 health：技术 runtime ready、`product_visible=false`、生产 backend／worker ready、`reference_clone_ready=false`、无 reason；再由固定 launcher 执行 13 个只读隐藏门禁探测。任一 run/scope/fixture/权限/token/产品可见性门禁不符都立即恢复 disabled flags。历史 controller-authority preflight 属于非阻断实验，现行本地验收不得因 `PROBE_CONTROLLER_AUTHORITY_HOLD` 停止；resume 仍只用于同一既有 run 的安全恢复。
10. 固定 launcher 在同一进程持有三把锁，重新执行 Q、核验并 claim 操作员信封，先保存 baseline，再执行自动零阻塞链和人工 blocker 修正／批准链；运行中只允许目标 novel/document 的 segment-render job 被该 worker 领取。
11. 作者／操作员在宿主运行固定本地 Node／Playwright 观察器，只按脱敏 probe request 完成四张精确桌面组合、Range/ETag、跳播 latest-wins、pending gap、编辑零 TTS 写入、控制台／遮挡和 30 分钟稳定性；作者通过后续 finalize 完成相邻句段与三角色听感记录。报告必须绑定同一 run，不能复用旧报告；它是本机操作证据，不宣称第三方或远程密码学证明。canonical v3 的真实章节技术报告、完整章节作者听检、listening record／receipt 均已形成并完成同 run 导入。
12. launcher 无论成功、异常或中断都按 CAS／单调版本执行作者可见 working copy 与 current Edition/script 指针恢复；新增不可变审计历史保留。恢复 hash 未核实前不得删除 recovery 文件。
13. 结束后由固定 TD verifier 恢复 runtime=true、validation=false、product=false、reference=false，核验普通 overview、隐藏路由与三个长期容器，再以 distinct destroy confirmation 删除身份一致的两份 token；canonical v3 已返回 `TOOLS_CLEANED`。数据库、音色、媒体、卷和追加审计历史未清理。
14. `T4-K-I` 汇合脱敏技术、浏览器、听感、恢复、隐私、打包和 QwenPaw 非回归证据；长期环境随后已切换并验证 product=true／validation=false。最终 T4-GATE 只做当前源码、包内容、产品模式和文档一致性收口。

### 固定安装、恢复与销毁模板

以下模板只展示变量名和稳定确认词，不含 token 值、真实 UUID、真实路径或秘密。尖括号必须由同一次 `READY_FOR_OPERATOR_REVIEW` 的私有 attestation 替换；未替换会安全失败。正式执行前先保存当前四开关与三容器只读快照。

```bash
# 先把现有 QwenPaw 置于公开安装器要求的四开关全关闭基线；只重建 qwenpaw，不动 PostgreSQL、Sidecar 或任何卷。
AI_NOVEL_TTS_RUNTIME_ENABLED=false \
AI_NOVEL_TTS_VALIDATION_ENABLED=false \
AI_NOVEL_TTS_PRODUCT_ENABLED=false \
AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=false \
docker compose up -d --no-deps --force-recreate qwenpaw

# host token 是仓库外私有文件；container token 固定写入既有 qwenpaw-secrets 卷，不新增挂载。
.venv/bin/python scripts/tts/provision_validation_token.py \
  --mode provision \
  --host-token-file '<HOST_REPOSITORY_EXTERNAL_0700_DIRECTORY>/token' \
  --confirm PROVISION-T4K-VALIDATION-TOKEN

export QWENPAW_EXPECT_TTS_RUNTIME=ready
export QWENPAW_EXPECT_TTS_VALIDATION=ready
export QWENPAW_EXPECT_TTS_PRODUCT=disabled
export QWENPAW_EXPECT_TTS_REFERENCE_CLONE=disabled
export QWENPAW_TTS_VALIDATION_TOKEN_HOST_FILE='<HOST_REPOSITORY_EXTERNAL_0700_DIRECTORY>/token'
export AI_NOVEL_TTS_RUNTIME_ENABLED=true
export AI_NOVEL_TTS_VALIDATION_ENABLED=true
export AI_NOVEL_TTS_PRODUCT_ENABLED=false
export AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=false
export AI_NOVEL_TTS_VALIDATION_NOVEL_ID='<DEDICATED_TEST_NOVEL_UUID>'
export AI_NOVEL_TTS_VALIDATION_DOCUMENT_ID='<DEDICATED_TEST_CHAPTER_UUID>'
export AI_NOVEL_TTS_VALIDATION_EXPIRES_AT='<UTC_SECOND_PRECISION_WITHIN_24_HOURS>'

.venv/bin/python scripts/qwenpaw_lab_plugin.py install
.venv/bin/python scripts/qwenpaw_lab_plugin.py verify
```

随后先使用主文档“统一基准脚本”中的固定 `chapter_e2e_operator_envelope.py` 模板发行信封，再立即使用同一 run UUID、attestation 和 envelope 调用固定 `docker exec ... run_chapter_e2e_real.py`；容器 token 路径只能是 `/app/working.secret/ai-novel-world-2026/t4k-validation/token`。目录布局必须精确冻结为：envelope、attestation、probe report、三把锁和 recovery 直接位于 `<RUN>/recovery/`；result 位于同级 `<RUN>/result/`；人工听检 claim/commit/record/receipt 位于同级 `<RUN>/listening/`。operator claim 不是调用者提供的 run 文件：它由 launcher 在固定中央 registry `/app/working.secret/ai-novel-world-2026/t4k-operator-claims/` 中按 run fingerprint 自动定位、加 lease 并维护，调用者不得自行创建、移动或复用。三个 run 子目录共同位于同一个 container 私有 `0700` run 根，但 result/listening 不能嵌入 launcher 的 private work dir，也不能与 recovery 输出重叠；所有输出均不得位于已安装 PawApp 根。运行结束并完成 baseline hash／指针恢复后，按以下顺序回到当前 T2 矩阵：

```bash
export QWENPAW_EXPECT_TTS_RUNTIME=ready
export QWENPAW_EXPECT_TTS_VALIDATION=disabled
export QWENPAW_EXPECT_TTS_PRODUCT=disabled
export QWENPAW_EXPECT_TTS_REFERENCE_CLONE=disabled
export AI_NOVEL_TTS_RUNTIME_ENABLED=true
export AI_NOVEL_TTS_VALIDATION_ENABLED=false
export AI_NOVEL_TTS_PRODUCT_ENABLED=false
export AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=false
export AI_NOVEL_TTS_VALIDATION_NOVEL_ID=''
export AI_NOVEL_TTS_VALIDATION_DOCUMENT_ID=''
export AI_NOVEL_TTS_VALIDATION_EXPIRES_AT=''

docker compose up -d --no-deps --force-recreate qwenpaw
.venv/bin/python scripts/qwenpaw_lab_plugin.py verify

# 只有恢复、普通 T2、隐藏路由 404/no-store 和三容器 healthy 均已核实，才销毁身份一致的两份 token。
.venv/bin/python scripts/tts/provision_validation_token.py \
  --mode destroy \
  --host-token-file '<HOST_REPOSITORY_EXTERNAL_0700_DIRECTORY>/token' \
  --confirm DESTROY-T4K-VALIDATION-TOKEN
```

标准安装流程可能短暂创建一个精确命名、带 ownership label 的一次性 installer；命令结束后它必须不存在。任何一步失败都保留 token、recovery 和追加式数据库历史供恢复，不得通过删除卷或测试记录“清理失败”。

## 实现源 re-freeze

T4-K-V 为隐藏 validation 增加 request-aware backend、运行态与 worker 隔离，因而 `settings_api.py` 当前实现源已经不同于 T2-GATE 的历史实现源。历史 SHA-256 `5f2236868892992d7c62cdcac4bdb1db20b34c05fb885adf225eeba77c240afb` 继续保留；当前实现源以 `acce0af8964266f66cfecae0f6709bbf3346a899a642b951cc5299dde7294ab8` 记为 `AUDITED_REQUEST_SCOPED_VALIDATION_REFREEZE`。本次没有改变 `narration-settings-api/1`：21 个唯一 URL、29 个 HTTP 操作、DTO、错误码和普通 T2 capability 仍由契约／API 回归验证；变化只允许服务端在一条已鉴权且同 scope 的隐藏请求内注入临时 T4 backend，不能改变普通请求或公开产品 tier。

| 冻结输入 | SHA-256 |
| --- | --- |
| `tests/fixtures/narration/chapter-e2e-v2.json`（历史 sealed） | `e970e4f837d2f96b2675e8922e43bb5dfcffc352e86f0f96b84e34db1065380b` |
| `tests/fixtures/narration/chapter-e2e-v3.json`（fresh active） | `3cfb094c3a3374eb233ccff5c08963adaba5cac55e5ec056ff5257d32e421913` |
| `backend/narration/release_gate.py` | `21bc3623299f78ec5dee3309028457b39a627b2ef256794ef5847f168c5f034c` |
| `backend/narration/validation_access.py` | `103a1ef17d64d02e595354d3764a51869d34ae92ed4e967f14e3bec649fb066b` |
| `backend/narration/production_runtime.py` | `526583f1cdbbabe48e2adfa88b8553aa01f0423ce6f69a8f097bdab4a9ed8323` |
| `backend/narration/jobs.py` | `39b1e65987604b4e1822a0375e393e8a53b1417deb1ce9e44f251a0cc46f99bf` |
| `backend/narration/scheduler.py` | `03456ecdea592b8933f30210e92ffbca76ac5a1b1c871482dfec883cd7c3f89b` |
| `scripts/tts/provision_validation_token.py` | `a92fc2d6e0b51ac89b35c7e9c893c65213635288361f0896b8a9980094a6d04e` |
| `scripts/tts/chapter_e2e_readiness.py` | `c41c8b4088888eda7e57fa23de5c29c898b11334cbd9d87336f4b6abab08821a` |
| `scripts/tts/chapter_e2e_collector.py` | `25bcd7280bbf7b3283ff59169ddd826b47804c34660b9487ebfe527591729736` |
| `scripts/tts/chapter_e2e_probes.py` | `ab19bb612ebafd4052b1bde7d085ce05bc0445e206915f5f91299c017316c32f` |
| `scripts/tts/chapter_e2e_probe_request.py` | `0131615decd87cefd7795bc0f29150af4db9d2215823746ae5960fe124bc1869` |
| `scripts/tts/chapter_e2e_listening.py` | `cffe66aad822c676c430d65b26ba2f038b53f9ebab27143f1a7f7c82ae6f3f0e` |
| `scripts/tts/verify_chapter_e2e_teardown.py` | `474c016311613129c0a59b5b28789877ba3bcfe3fc9a9426477bc3ca18b7c2f1` |
| `scripts/tts/validate_chapter_e2e.py` | `b8f1476b6afaad773cae47eaffddda9bd58fcde3439abf59de619ca52514170e` |
| `scripts/tts/chapter_e2e_executor.py` | `0eeb6fe9670524670457ec0432035f98a8526a75bd0d29bee0e0ba399853a2d5` |
| `scripts/tts/chapter_e2e_operator_envelope.py` | `01b5697ce27fe74a5a881d315229ca20124ab73b68e500f54607e67aca5d0726` |
| `scripts/tts/run_chapter_e2e_real.py` | `3d48f82b9773cd500b5f193890101aa2bf8f0220222239b2b19b44404e2c187e` |
| `scripts/tts/chapter_e2e_runtime_audit.py` | `c679f111a823f284841bbbdee0a8aa8e6ee760ec7a9f4408c7a0362fefa2fc72` |
| `scripts/tts/chapter_e2e_controller_trust.py` | `257a0b4658c6a39b7a1bb91bf8a3cc1777ae87d3e5ff6ce5b3ca06a94dd7c63f` |
| `scripts/tts/chapter_e2e_controller_host.py` | `af66d34ecc12867b513462177430e4c2c9390240e6b6edc544380eb72e42d414` |
| `scripts/tts/chapter_e2e_controller_signer.py` | `c6843c2439b392d35a67cdc331808a499c14805371068275b23c5474b16d0498` |
| `scripts/tts/controller_ssh_askpass.sh` | `159705ef16504d3ea072571ae5a9f73abc7a03d11e0fd66e93cc3348b12dd143` |
| `scripts/tts/trust/controller_trust_policy.json` | `1b0475015cd7b2c0d27459cec4517d6aac8a3b780482a909e3b4ab376f10996c` |
| `scripts/tts/trust/controller_allowed_signers` | `6b5b1548e3010ca95a065983362a87414529f78a0dbf6fe39654af3d2b05d01f` |
| `scripts/qwenpaw_lab_plugin.py` | `48c7ecf598fee0de792f97c0bebfa414549a80e997a06ef24672823383464c12` |
| `scripts/verify_qwenpaw_lab.py` | `d855cb2a205443bfcf33027321b3b7df7dda43eae2288a8ed31a037ac982c4fd` |
| `scripts/package_plugin.py` | `50dceb6a4f651622aebd1721a0e34094a62f7a636ef66be194cd1b4aa954a6a5` |

本文不记录自身 hash，避免自引用。任一上述实现源后续改变，都必须重新运行本节测试和产物审计，并在新 GATE 中解释语义变化；不得静默覆盖历史快照。

## 实际验证

验证基线为分支 `main` 的 `0858b0eb3774` 加当前保留用户其他施工内容的 dirty worktree；本报告记录的是尚未提交的集成候选，不把它表述为已进入 Git 历史。上节实现源 hash 用于绑定本次候选；本轮没有执行暂存、提交或推送。

本轮恢复／collector／听检／teardown 加固完成后，以下 12 组 T4-K 专项已由主代理在最终源码上整组复跑：

```text
.venv/bin/python -m pytest -q -o addopts='' \
  tests/narration/test_validate_chapter_e2e.py \
  tests/narration/test_chapter_e2e_executor.py \
  tests/narration/test_chapter_e2e_probes.py \
  tests/narration/test_chapter_e2e_probe_request.py \
  tests/narration/test_chapter_e2e_runtime_audit.py \
  tests/narration/test_chapter_e2e_readiness.py \
  tests/narration/test_chapter_e2e_operator_envelope.py \
  tests/narration/test_chapter_e2e_collector.py \
  tests/narration/test_chapter_e2e_listening.py \
  tests/narration/test_run_chapter_e2e_real.py \
  tests/narration/test_verify_chapter_e2e_teardown.py \
  tests/narration/test_provision_validation_token.py
```

结果：**349 项通过，0 失败**。其中恢复／executor／operator／launcher 四组为 121 项，collector／probe 两组为 132 项。该历史测试集覆盖当时的 fresh authority HOLD、resume、旧恢复重放、claim/recovery 一代差、baseline fence、finalization 输出目录替换、collector 三文件事务、30 分钟样本链、人工听检四文件提交和 teardown fail-closed；其中 authority HOLD 断言只说明实验代码按当时策略工作，已不再是现行本地验收要求。

同一最终源码还实际通过：

- `.venv/bin/python -m py_compile scripts/tts/*.py scripts/package_plugin.py`；
- `.venv/bin/python -m pytest -q -o addopts='' tests/test_qwenpaw_integration_contract.py tests/test_assistant_install_contract.py`：61 项通过；其中 clean-package entrypoint 会从包外临时工作目录执行 listening／launcher／teardown 的 `--help`；
- `.venv/bin/python scripts/package_plugin.py`：插件打包成功；产物 145 个普通文件、0 符号链接、0 source map、0 音频；collector、listening、teardown 和固定 launcher 均进入清单；
- 固定 launcher 写前的 13 个只读探针：无／错／重复物理 token header 跨 narration/script/playback 路由、普通资源 404 与门禁 404 不混淆、三类负向 overview 精确 T2、正确 token 同 novel scope 临时 T4、reference capability 继续缺失，以及 token/hash/body/path 零泄漏；
- 假 HTTP、伪造／过期／缺失探针、错误模型 fingerprint、非 PostgreSQL、锁冲突、锁释放、仓库内 token 路径拒绝、无任意 import 入口，以及当时 fresh authority HOLD 零落盘的 fail-closed 回归；
- 先前“独立红队 P0=0、P1=0”结论已被 2026-08-27 后续复核撤回。首轮发现的指标链不兼容、PNG 未解析和 request/preflight 绑定缺口仍是本地证据链应防止的真实问题；浏览器／OS 独立观测权威、不可注入签名边界和 active-root 全链则仅属于远程证明实验。空 production trust root 只使该实验路径 HOLD，不阻断现行 T4-K/T4-GATE；最新真实固定 Edge 浏览器结果已在后文记录，30 分钟、听检与剩余产品验证仍须实际完成。

集成后的全量非回归结果：

- `.venv/bin/python -m pytest -q -o addopts='' -ra`：**1906 项通过、116 项跳过、2 条既有弃用 warning**；跳过项均因未配置显式一次性 PostgreSQL／集成 URL，本报告不把它们计为真实数据库通过；
- 使用 Codex 工作区固定 Node 运行时执行 `pnpm typecheck`：通过；
- `pnpm test`：83 个测试文件、743 项测试全部通过；
- `pnpm build`：生产构建通过；
- `docker compose config --quiet`：通过；
- 跟踪文件的 `git diff --check` 以及各子代理授权的未跟踪 T4-K 文件 scoped diff-check 均通过。

以上一段是 controller／recovery 加固完成时的历史验证快照；其“没有启动容器／连接正式 PostgreSQL／运行 Nano”不再代表当前状态。后续真实预设试听增量证据如下。

### 2026-08-27 official preset 真实试听增量

- 正式 PostgreSQL 已在事前 `pg_dump` 备份后线性应用 `20260827_0022`，随后为合法 `running preview + queued retry job` 状态增加只前向迁移 `20260827_0023`；没有改写旧迁移，也没有新建第二数据库。
- 首次真实试听暴露 Worker／Sidecar 契约漂移：Worker 曾发送 `max_new_frames=4096` 与 `sample_mode=narration-segment`，而固定 Nano Sidecar 只接受 `1..2000` 且正式 runtime 使用 `375`、`fixed`。公共常量现冻结为 `max_new_frames=375`，采样模式只允许 `greedy | fixed | full`；Sidecar 镜像按新源 hash 重建并仅原位替换既有服务。
- 隐藏安装矩阵为 runtime=true、validation=true、product=false、reference=false；真实健康投影为 Sidecar/model/backend/worker ready、`product_visible=false`、`reference_clone_ready=false`。长期拓扑仍只有现有 PostgreSQL、QwenPaw、TTS Sidecar 三个容器。
- 公开安装流程在最终源码上实际通过：前端 84 个测试文件／748 项测试，后端 1961 项通过／116 项因显式集成环境未配置而跳过／2 条既有弃用 warning，生产构建和 QwenPaw 热安装／重建验证均成功。
- `prepare_chapter_e2e_data.py` 通过隐藏 PawApp HTTP、生产 Worker 与固定 Sidecar 生成中文官方预设试听；作者最终选定并已完成旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao` 的 `locked + accepted + bound`。真实请求后 Sidecar 仍 healthy、restart count 0。
- 三份生成音频只存在于仓库外当前用户私有 `0700` 目录，文件权限 `0600`；Git、插件包、镜像层和文档证据目录均不包含音频、prompt codes 或模型权重。
- 试听准备器当时以退出码 2 和 `QUALITY_CONFIRMATION_REQUIRED` 正常停止，这是已完成的历史中间态。作者确认、随后的 fanout 修复与真实 baseline 重跑现均已完成；不得再写为“等待作者试听”或“基线修复中”。

### 2026-08-27 真实 Nano baseline 成功证据

- request `3ac0e9ce-38f9-4f7d-92f8-ad61fc581f6d`：`ready`。
- Edition `5b3832f3-2f6b-4f7f-8ec3-5d1150a6d21d`：`ready`。
- Manifest：revision 42、`status=ready`、56/56 句段 `ready`、`total_duration_ms=418880`、ETag `b44467ec4dce6ab95358c69918dc8a04fb679a7ade0883c32046a12652242df7`。
- 该 Edition 共有 56 个句段、42 个 distinct render fingerprint；重复规范句段在同一 request 内共享一次合成并安全扇出到各目标句段，没有沿用首次失败的 segment-specific 冲突路径。
- 正式绑定保持为旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao`，未回退或替换为旧候选映射。
- 本组基线证据只关闭“真实 Nano baseline 与同请求 fanout”缺口；后续浏览器、30 分钟、听检与 teardown 在各自追加证据中独立记录，不能反向改写本节形成时的状态。

### 2026-08-27 真实固定 Edge 产品交互报告

- 脱敏报告 SHA-256：`ce5cf23bee896cd5e02c469aeaf39eba85dda6545adf7ec67702cc4b56c053e2`。
- `1920×1080 × 助手收起`、`1920×1080 × 助手展开`、`2560×1440 × 助手收起`、`2560×1440 × 助手展开` 四个精确组合均为 overlap=0、overflow=0；console error=0、page error=0。
- 真实页面中播放器可见；CodeMirror、段落／光标跳播、latest-wins、play/pause/rate/seek 均已通过。
- 媒体五请求的实际结果为 `200/304/206/206/416`，覆盖完整请求、条件请求、Range 与非法 Range 边界。
- 编辑后撤销成功，观察期间 TTS write=0，证明普通编辑和撤销没有误发语音生成写入。
- `pending_gap` 未被观测：本次正式 Edition 的 56/56 句段已全部 `ready`，不存在可观测 gap，因此必须保持 `not_observed`，不得用推断或伪造 fixture 补成 `true`。
- 首个完整 31 点／30 分钟窗口的脱敏指标与失败裁决见 [稳定性首次完整观测](./stability-attempt-2026-08-27.md)；它保留真实 `host_paging_observed=true`，不得重标为通过。
- 该报告关闭当时真实固定 Edge 的布局、播放、编辑和媒体交互缺口，但首个 result/probe 2.1 窗口因 `host_paging_observed=true` 如实失败；后续 canonical v3 的 result/probe 2.2、作者听检、恢复／teardown 与 product mode 通过另行追加，不重标本次历史报告。

### 2026-08-27 controller authority 历史实验与现行本地性能门禁

- 以下 signer／authority 内容是为更高对抗、可远程证明场景进行的非阻断历史实验，不是个人本机 PawApp 的生产架构，也不进入产品包。第二轮红队证明 SSHSIG 原语、临时 key 和 fail-closed 验证器可工作，但同进程 Python signer 不能形成独立权限边界；该结论保留，不再推导出“必须建设 OS service 才能继续本地验收”。
- 历史只读审计曾提出 signed native Controller Agent + 独立 Signer LaunchDaemon + XPC 的远程证明拓扑，并记录登录用户会话、WindowServer、同 UID、code-signing identity 和安装／回退约束。该方案维持 `PROPOSED / NOT_APPROVED / NOT_IMPLEMENTED`，且根据最新裁决不进入当前施工范围；没有注册 Agent/Daemon、创建服务账户、key、socket 或 active root。
- 历史候选还测试了 Edge/Node SHA、controller source build SHA、签名前后身份复核和 `commit_now` 漂移检查，browser/evidence/lifecycle **61 项通过**。这些结果可继续帮助本地证据发现环境漂移，但签名端口、empty root、AUTH-3/AUTH-6 状态均不再是 T4-K 或 T4-GATE 的前置。

- AUTH-3 历史实验曾把 Node 24.19.0、receipt-bound `playwright-core@1.62.1`、系统 Edge 固定路径和 controller build identity 纳入签名闭包；trust policy/allowed-signers 不纳入 build hash，以避免 policy 内含 build allowlist 的哈希循环。现行本地报告仍固定实际 Node／Playwright／Edge 版本并记录 hash 以便复核，但不把它提升为独立签名权威。
- Edge 的 executable SHA-256、Team ID、Identifier、CDHash、deep codesign、`spctl` 与 notarization 检查曾作为远程证明实验的硬门禁；现行本地验收把它们作为环境记录和漂移诊断。实际 viewport、页面行为、错误、媒体、性能与恢复结果仍须满足产品门禁，Gatekeeper 或签名身份不单独阻断作者本机使用。
- canonical observer report 的 SHA-256 已写入 probe／collector 候选，可用于本地核对 browser identity projection、四截图摘要和交互摘要，且不持久化原始截图、正文、音频或诊断文本；这里不把该 hash 或历史签名表述为远程证明。
- baseline 成功前，固定 Edge 对专用隐藏章节完成过一次历史 raw observation：四个精确组合 `1920×1080/2560×1440 × 助手收起/展开` 均为 actionable overlap=0、horizontal overflow=0，console error=0、page error=0；CodeMirror 改动后 undo 恢复原 digest，TTS write=0。sticky 播放器与编辑器只在精确兄弟关系、sticky、可滚动 shell 和双层安全 bottom padding 足够时豁免，任何条件缺失仍计为重叠。
- 该次历史 raw observation 不是正式 PASS：当时页面只有播放器壳层，且 baseline Edition 仍因 render fanout 缺陷未成功，所以段落/光标跳播、latest-wins、播放/暂停/倍速/seek、五种媒体 HTTP 结果和 pending-gap 均保持 `not_observed`。后续 baseline 与最新真实产品交互报告已分别完成，但不能追溯篡改这次历史记录；active-root 签名链不再属于本地产品门禁。
- 当前专项自动化增量：固定 Node **23/23**；browser observer、evidence assembler、collector 与 probe 联合测试全绿；controller build/host/lifecycle 相关测试全绿。此前把 `strict_verified=false` 同时视为可接受和篡改的矛盾测试已纠正，deep/team/id/notarized/accepted/SHA 及布尔类型仍有 fail-closed 负例。

- AUTH-2～AUTH-5 与 host askpass 的历史实验，以及当时 result/probe 2.1 的硬 RTF／内存安全字段和 runtime-audit→executor→TechnicalOutcome 传递，曾在最终候选上整组复跑：**454 项通过**。该复跑发现并修复了 `host_paging_observed`／`qwenpaw_slowdown_observed` 曾在 executor 边界被丢弃的集成缺口；此处计数与历史断言不代表 result/probe 2.2 已完成 fresh real run。当前 2.2 仍保留原始 paging telemetry 的完整传递与一致性 fail-closed，但只以 Sidecar 趋势、peak、restart、health failure 和 QwenPaw slowdown 作内存安全裁决。
- controller trust／collector／launcher／host／signer 历史实验子集由主代理复跑 **145 项通过**；临时 key 能完成 `ssh-add -c -t 120`、SSHSIG 与 public verify，empty root 会使该实验返回 `CONTROLLER_TRUST_ROOT_HOLD`。该结果不改变现行本地验收状态。
- 最终后端全量为 **2066 项通过、116 项按未配置显式集成库规则跳过、2 条既有弃用 warning**；前端为 **84 个测试文件、749 项通过**，`pnpm typecheck` 与生产 build 通过。
- package 实际审计并安装成功：QwenPaw 包明确不包含 host controller、signer、askpass、私钥、签名、实际 agent socket 或 agent 环境注入、音频、prompt codes 或模型权重；现存 public verifier／empty policy 属于无生产权限的历史兼容候选，不能被产品路径依赖。安装后矩阵仍为 runtime=true、validation=true、product=false、reference=false，三个项目容器 restart count 均为 0 且 healthy。

## 当前收口状态与历史验证条件

重复规范句段的 render fanout 修复、作者音色确认、可恢复 baseline Edition、最小缓存／磁盘保护、真实固定 Edge 四组合与主交互、本地编排器真实自动／人工 Nano 链、`partial_ready`、pending-gap 和 result/probe 2.2 的 fresh canonical 技术门禁均已完成。两次 result/probe 2.1 全机 paging 硬门禁下的历史失败仍不重标。作者已完成完整章节听检，同 run resume／teardown 已通过；长期产品已升级到 `0024` 并验证 product mode。系统中文输入法由作者亲验通过；完整 supplemental envelope 未生成的事实保留为非阻断后续完善项。独立 controller authority、OS signing service、正式私钥和 active trust root 不在当前条件中。下列条目保留既有验证合同与历史执行顺序，已完成项不得重新降级为等待项。

1. 保持已完成的旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao` 三项 `locked + accepted + bound` 与 `ready` baseline Edition 不变；每项继续保留官方仓库、revision、manifest hash、精确 preset ID、模型 fingerprint 与必要 prompt-code hash。该项已完成，作为后续同 scope 验证的基线，不得再降级为等待项。
2. 以私有 attestation、三把互异锁、同值 host/container token、canonical novel/document scope 和不超过 24 小时的 expiry 运行现有隐藏验证；运行前后分别证明普通 overview 精确 T2、正确 token 临时 T4，三种负向 token 仍精确 T2／隐藏 404。
3. 旧 run `270ea179-e3cf-4095-a928-56b414070719` 的技术与听检结果保持历史原貌；当前权威 run `bb03ccaf-4681-490a-b987-84bec9199b3b` 已在同一 fresh run 完成真实 Nano、更新朗读、恢复、最小缓存／磁盘保护、RTF、pending-gap、播放器、CodeMirror、段落／光标跳播、倍速／seek、latest-wins、Range/ETag、编辑零 TTS 写和固定 31 点／30 分钟门禁。
4. 作者／操作员本地浏览器核心报告覆盖且仅覆盖 `1920×1080`／`2560×1440` × 助手收起／展开四组合；作者已完成旁白／林晚／沈川与相邻句段的完整章节听检，并亲验系统中文输入法至少输入两个汉字正常。自动 supplemental envelope 未生成，按非阻断证据缺口保留；报告是本机证据，不是远程证明，低于 1920×1080 不采集、不验收。
5. canonical v3 已按追加式恢复策略复核正文 hash、working copy、current Edition／script 指针，完成同 run resume／teardown 并返回 `TOOLS_CLEANED`；身份一致的验证 token 已销毁。长期 PostgreSQL、QwenPaw、Sidecar 三容器保持健康，产品环境已升级到 `0024` 并验证 runtime=true／product=true／validation=false／reference=false。

以上有限核心条件已完成并进入最终 T4-GATE 一致性收口；云端辅助说话人识别和高级匿名人物选角继续 HOLD／待用户裁决，不能随有限核心顺带放行。商业／再分发、英语／日语专项、云端／远程／共享／复杂继承、OS／SSHSIG／正式 key 与章节／全书导出不得重新成为个人本地版阻断项。
