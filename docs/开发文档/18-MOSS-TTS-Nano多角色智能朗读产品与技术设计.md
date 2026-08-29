# MOSS-TTS-Nano 多角色智能朗读产品与技术设计

> **2026-08-29 计划 33 候选状态：**[全预设直用、人物专属音色与播放体验优化计划](./33-MOSS-TTS-Nano全预设直用人物专属音色与播放体验优化计划.md) 已完成 18 项官方 preset 一步直用、新设置/播放器和人物自动分配官方音色的源码候选；VoiceGenerator 在 M4/16 GiB 上为 `NO-GO`，高级参数与私人音色删除均因各自未闭合门而保持隐藏/fail-closed。长期环境仍是下文 2026-08-28 的 6 中文音色版本；在隔离安装、浏览器矩阵和长期升级未完成前，不得把候选误写为已发布。

> **2026-08-28 v3 真实章节最新状态（当前权威）：**canonical run `bb03ccaf-4681-490a-b987-84bec9199b3b` 已使用旁白 `onnx.Zhiming`、沈川 `onnx.Junhao`、林晚 `onnx.Xiaoyu` 完成真实 Nano 技术链。三者均直接消费固定官方 ONNX manifest 的原始 prompt codes，并统一使用官方默认 `seed=1234`、`sample_mode=fixed`、`do_sample=true`、`max_new_frames=375` 及下文列明的官方采样参数；没有项目自制音色、换 seed、greedy、音高、语速、情绪、克隆或其他调教。自动链 0 blocker，人工链预期 3 blocker 已修正，自动／人工链各包含 1 个未命中缓存的真实 Nano job；播放器、CodeMirror 跟随、段落／光标跳播、latest-wins、倍速／进度、编辑恢复、pending-gap、Range/ETag、1920×1080／2560×1440 × 助手收起／展开四组合以及固定 31 点／30 分钟稳定性均取得技术 `PASS`。作者随后明确确认“完整章节通过”，同 run listening finalize、resume 与 teardown 已完成；最终 result 为 `PASS_CANDIDATE`、human state 为 `PASS`，baseline 保持恢复，历史运行不改写。listening record SHA-256 为 `70f005a209be1b75cde351e0352bb89654a29256b7c5004decc5fd7bfa2a3ec0`，receipt SHA-256 为 `1d8c69a23de5cdd41fed50f6c715836887b7992bbcfa938cea34cce6119a66e1`，result SHA-256 为 `afc70316e08a7ea8cc053a622c5733c27c48e18a0a605ce8eef557b65bdd49f5`。详见 [v3 官方默认参数真实章节技术验收](证据/MOSS-TTS-Nano施工/T4-K/v3官方默认参数真实章节技术验收-2026-08-28.md)。

> **2026-08-28 最终产品候选与补充浏览器状态：**最终候选 tree `7a57471ebe9ea6cffc6d76529e3fdcab6c1683ad236499fbc2d1fdfb720bde13` 已删除当前范围外仍可见的“通用音色 24 分类位”页面、入口、专用样式及仅服务该页面的前端 API／DTO／测试；已执行迁移和历史证据保留。88 个前端文件／813 项测试、2821 项 Python 全量、固定 Node／Python 回归、typecheck、production build、包与安装契约均通过；长期 QwenPaw 已安装同哈希候选并保持 `20260828_0024`、`runtime=true / product=true / validation=false / reference=false`，6 个中文产品 preset 精确可见，三个长期容器 healthy/restart=0，隐藏验证 token 已销毁。作者本人已用 macOS 系统中文输入法亲自输入至少两个汉字并确认正常；自动 supplement envelope 未生成，因此只保留为“核心浏览器 PASS + 作者 IME PASS + supplement 非阻断未生成”，不伪造自动报告。最终裁决见 [T4-GATE](证据/MOSS-TTS-Nano施工/T4-GATE.md)。

> **2026-08-28 v3 fresh run 前置复验历史：**新的 append-only 官方默认 Voice Version 已真实创建、锁定、接受并绑定：旁白 `onnx.Zhiming`、沈川 `onnx.Junhao`、林晚 `onnx.Xiaoyu`，三者均为 `seed=1234 + sample_mode=fixed + max_new_frames=375`，没有换 seed、greedy、音高、语速、情绪或克隆参数；新 baseline Edition `2f9d6e0a-961b-4355-b626-8e3be03138c4` 已 56/56 ready 并通过 CAS 切为当前 Edition。随后 fresh T4-K 人工链出现一个独立 `onnx.Junhao` 句段失败；隔离 Sidecar 以完全相同官方参数复现，24 字输入得到 20240 ms WAV，超过冻结的短中文保守上限 10800 ms，格式、48 kHz／双声道、静音和削波均不是主因。该结果证明“参数传递正确，但固定官方采样对这一特定文本产生异常长输出”；不得用自定义参数绕过。为保持产品参数和用户正文都不变，已把原 v2 失败 fixture 冻结为历史证据，新增 append-only `chapter-e2e-v3.json` 项目自有稳定验收样本：替换句在相同官方 `onnx.Junhao` 参数下两次均为 4160 ms 且 actual WAV hash 完全一致；v3 仍保持 57 句段、自动链 0 blocker、人工链精确 3 blocker。质量门继续 fail-closed；该段计划中的 v3 fresh 技术运行现已由 canonical run `bb03ccaf-4681-490a-b987-84bec9199b3b` 完成，历史失败 run 及恢复尝试只作追加历史，不得重标 PASS，作者可见正文与 current Edition 已恢复到上述 baseline。

> **2026-08-28 官方默认参数最终裁决（取代下方 fixed／seed 0 与 fixed／seed 1 的产品候选描述）：**作者已试听同一篇 146 字中文文本的三个官方原始效果样本，并明确确认“官方预设是完全没问题的，官方的预设音色就用官方预设的参数”。现行产品只允许使用固定官方 ONNX manifest 的原始 prompt codes 与默认生成配置：`sample_mode=fixed`、`do_sample=true`、`max_new_frames=375`、`audio_temperature=0.8`、`audio_top_k=25`、`audio_top_p=0.95`、`audio_repetition_penalty=1.2`、`text_temperature=1`、`text_top_k=50`、`text_top_p=1`，以及固定官方运行时的初始 RNG seed `1234`。不得再对 `Zhiming` 短提示语启用 `fixed_seed_1`，不得加入音高、语速、情绪、克隆或其他音色调教。此前 seed 0 异常、greedy runaway、fixed／seed 1 回归和作者听检仍作为历史诊断证据保留，但统一标记为 `SUPERSEDED_DIAGNOSTIC_NON_PRODUCT`，不能进入新 Voice Version／Edition 或阻断官方默认参数主路径。当前代码已把专项策略默认值恢复为 `disabled`，三个新官方 preset Voice Version 的默认 seed 冻结为 `1234` 并已 locked／accepted／bound；既有 seed 0／seed 1 版本保持不可变，只读保留。append-only v3 的真实 Nano、播放器、CodeMirror、30 分钟、四桌面、作者完整章节听检、同 run resume／teardown 均已完成。

> **阅读顺序：**下方两段是裁决前的历史过程记录，其 fixed seed 1 的“待选／待确认”描述不再表示当前产品状态。作者最终听检、同 run resume／teardown、长期 `0024` 升级、product mode、补充证据文档收口与最终一致性复查均已完成；不得再把旧 `HUMAN_LISTENING_PENDING` 当作现状。

> **2026-08-28 历史诊断（`SUPERSEDED_DIAGNOSTIC_NON_PRODUCT`，run `270ea179-e3cf-4095-a928-56b414070719`）：**作者当时实际听检并明确判定样本 01、04 不是可理解的正常中文；其余样本正常。该历史 run 结论为 `HUMAN_LISTENING_FAILED`，不得重标 PASS。精确诊断确认 01=`林晚说道：`（3760 ms）、04=`沈川说道：`（22080 ms），两者都是 `onnx.Zhiming` 的 5 字独立旁白提示语；正常 21～22 字旁白只有约 4.2 秒。隔离真实 Nano 矩阵排除了转码、音色串错、“只改冒号”和 greedy：greedy 在 `欧阳澈说道：` 上产生 30000 ms runaway，已淘汰；fixed／seed 1 曾作为窄诊断候选扩展为 182 字、10 句段、40.74 秒长试听，但随后被作者的官方默认参数裁决取代，不得进入产品。官方模型、`onnx.Zhiming` preset 和 prompt codes 未改。Unicode fail-closed、短中文异常时长门禁、8-case／10-occurrence 回归 fixture、听检 schema 1.1、精确失败状态传播与 recovery 3.2 证据继续作为历史防线保留；它们不覆盖本文首段的 v3 当前状态。详见[人工听检失败与短提示语诊断](证据/MOSS-TTS-Nano施工/T4-K/人工听检失败与短提示语诊断-2026-08-28.md)。

> **2026-08-28 短提示语历史候选与证据接线（`SUPERSEDED_DIAGNOSTIC_NON_PRODUCT`）：**`nano-zh-attribution-sampling/2` 纯策略解析器与 `narration-render-input/4` 缓存身份接线作为历史诊断候选保留，但正式策略固定为 `disabled`，产品不得选择 fixed seed 1。真实诊断曾证明 `沈川说道。` 的句号变体可能 runaway，并完成 8-case／10-occurrence 伴随集；这些证据只说明历史候选可复核，不授权改变官方参数。历史坏段可读可核验，旧 result/probe 2.2 中实为 `SHA-256(edition_id)` 的字段也保留原语义且不重标；result 2.3／probe 2.3／request 1.3／collector 2.1／listening receipt+claim 1.2／recovery 3.2 继续绑定 Edition UUID hash 与数据库真实 Edition fingerprint。现行 v3 产品运行统一使用官方默认参数。

> **下方粗体长状态段的范围裁决仍有效，但其中 run `270ea179-e3cf-4095-a928-56b414070719` 及“当前只剩”措辞仅为历史 v2 快照；当前运行事实和 ready set 只能以本文首段、上方新 ready set 与 v3 专项证据为准。**

状态：**当前完工范围为“个人、单用户、本机、6 个中文官方预设的多角色网页朗读”。权威绑定是旁白 `onnx.Zhiming`、沈川 `onnx.Junhao`、林晚 `onnx.Xiaoyu`，全部使用固定官方 ONNX manifest prompt codes 与官方默认参数。canonical run `bb03ccaf-4681-490a-b987-84bec9199b3b` 已完成真实 Nano、网页播放器、CodeMirror 句段同步、段落／光标跳播、倍速／进度、更新朗读、失败恢复、Range/ETag、固定 31 点／30 分钟稳定性和四桌面组合；作者确认“完整章节通过”，同 run listening finalize、resume、teardown 已完成。长期环境已升级到 `20260828_0024` 并验证 `runtime=true / product=true / validation=false / reference=false`。作者本人另确认系统中文输入法至少输入两个汉字正常；自动 supplement envelope 未生成，作为非阻断证据缺口如实保留。商业／再分发、英文／日文专项、云端／共享／复杂继承、OS signing／SSHSIG 与音频导出为当前非目标；云端辅助说话人识别与高级匿名人物选角继续 `HOLD`。低于 1920×1080、移动、窄屏和 200% 等效小视口不进入本专项门禁。**

> 2026-08-27 本地信任模型覆写：此前把 `CONTROLLER_TRUST_ROOT_HOLD`、`CONTROLLER_LIFECYCLE_SIGNING_PORT_HOLD`、空 public trust root、正式 key 登记或独立 OS service 写成当前放行前置的段落，均由本裁决取代。现有代码中若仍保留这些 fail-closed 实验路径，只能视为待从个人本地主路径旁路或清理的历史候选，不能据此暂停 T4-K。AUTH-3 现指固定本地 Node/Playwright 执行器、不可由调用方注入的页面／选择器／视口／浏览器路径、实际观测和脱敏摘要；AUTH-6 现指把这些本地证据与真实产品链、恢复和 teardown 汇合，不包含签名服务或密钥仪式。

> 2026-08-27 实施历史：T4-PRESET、`0022/0023`、重复句段安全 fanout、真实基线和 v2 技术运行都保留为追加证据；run `270ea179-e3cf-4095-a928-56b414070719` 后续人工听检失败，不得重标 PASS。其“当前停在 `HUMAN_LISTENING_PENDING`／product false”的旧快照已由 canonical v3、作者完整章节通过、同 run resume／teardown、`0024` 与长期 product mode 验证取代。

> 历史审计保留：同 uid HMAC、同进程私有 signer、SSHSIG/public-root、Agent/Daemon signing service，以及商业发布／再分发和声音权利审查曾被评估。这些记录只回答已经被现行范围排除的第三方证明或商业分发问题，统一标记为 `SUPERSEDED_NON_TARGET`；不得继续扩建、进入 PawApp 产品包／正常 launcher、触发审批流程或阻断 6 个中文官方预设与 T4 产品主路径。

> 范围缩减的工期影响：T5 VoiceGenerator、除最小磁盘保护外的 T6 高级生产、24 槽、英文／日文专项、商业审批、云端／共享／继承音色、OS 签名权威和 T6-D 导出均已移出当前 ready set。真实 Nano、30 分钟、四桌面、作者听检、resume／teardown、`0024`、product mode、最终源码／包内容／文档一致性复核及回归均已完成；本轮 T4-GATE 已收口，不再估算或等待新的作者试听时间。

制定日期：2026-08-24（Asia/Shanghai）

最近修订：2026-08-28（Asia/Shanghai）

修订结论：采用“本地优先、规则优先、可审计的自动人物识别与自动选角、默认仅异常复核、脚本与朗读版本分离、独立显示句段合成、Manifest 分段播放、章节同页校听、统一持久任务底座”。阶段 0 已将正式执行拓扑冻结为 Linux/arm64 Compose 私网 Sidecar，macOS managed worker 只作诊断；编辑器冻结为 CodeMirror 6 条件候选与现有 textarea 安全降级，不能用视觉叠层冒充可编辑句段映射。T0–T6 已补充可直接派发的文件 Owner、共享资源锁、验收命令、证据目录与串行汇合规则；这些施工卡仍受阶段批准状态约束。

目标环境：QwenPaw 2.1.0 内的 `AI小说世界2026` PawApp；Apple Silicon M4、16 GB 内存；个人、本地优先使用。

关联文档：

- [架构边界与模型接入决策](./01-架构边界与模型接入决策.md)
- [总体架构与核心流程](./06-总体架构与核心流程.md)
- [创作工作台内容模型与关系图产品规格](./09-创作工作台内容模型与关系图产品规格.md)
- [阶段实施矩阵](./08-阶段实施矩阵.md)
- [当前布局页面设计评审稿 V2](./设计稿/18-MOSS-TTS-Nano智能朗读-页面设计评审-V2-2026-08-25/README.md)：基于 2026-08-25 运行界面重新截图和重画，已完成用户初审与施工前专项终审；不代表已实施或已批准进入后续阶段。

## 0. Codex 多子代理并行施工授权

用户明确授权本专题在已批准阶段采用多个 Codex 子代理并行施工，并且**授权层不设累计子代理数量、并行批次、任务总数或合理嵌套委派的上限**。主 Codex 可以根据依赖关系持续创建、补充、复用和滚动调度子代理，无需为每次派发再次请求用户确认。

实际瞬时并发仍受 Codex 平台槽位、模型/工具限流、本机 M4 资源和共享工作区安全约束；达到容量时采用连续批次，而不是绕过系统限制。2026-08-26 的完整实施授权只改变后续阶段是否需要重复请示，不改变技术门禁：阶段 0 未退出前不得让空闲子代理提前实施阶段 1–6；任一阶段只有在前一阶段 GATE 明确通过并形成下一 ready set 后才可施工。

本专题优先按以下工作流并行：

```text
主 Codex（计划、契约、集成、最终验收）
├─ Nano 安装、基准和运行拓扑
├─ 6 个中文官方预设的目录、试听与直接绑定
├─ Manifest v2、播放队列和音频接缝原型
├─ CodeMirror/textarea 编辑器同步与跳播
├─ 数据模型、迁移、任务与媒体治理审查
└─ 固定测试集、真实章节、性能、恢复与宿主非回归证据
```

并行施工必须维持单一集成责任：每个子代理获得明确的领域/文件所有权和验收条件；数据库迁移顺序、共享 API/schema、依赖锁、状态机和最终 Git 提交由主 Codex 统一协调。子代理完成只表示候选结果就绪，只有主 Codex 完成复核、集成测试和阶段退出检查后才算交付。

正式开发直接使用本文第 18.0 节定义的 T0–T6 本地工作包编号。它们只用于完成本 MOSS-TTS-Nano 专项，不授权当前聊天任务顺带开发模型切换、助手或其他专项。

### 0.1 2026-08-27 当前范围覆写

本节是当前施工、能力翻转和完工判断的最高优先级输入。下文保留的 T0–T6 原计划、商业／权利审计、18 项目录研究、VoiceGenerator、24 槽、云端、继承、共享、签名服务和导出内容只用于历史追溯或未来重新立项；与本节冲突时一律按本节执行。

| 类别 | 当前裁决 | 对 T4 的影响 |
| --- | --- | --- |
| 产品与用户 | 个人、单用户、本机自用 | 不新增跨用户、workspace、团队或远程权限模型 |
| 正式产品音色 | 仅 6 个中文 `official_preset` | 选择器、试听、绑定、合成、听检和门禁只覆盖中文六项 |
| 底层固定目录 | 18 项 manifest/catalog 可保留 | 只用于固定 revision/hash/fingerprint、升级兼容和排错；其余 12 项不进入当前专项 UI／语言质量／放行矩阵 |
| 当前正式演员 | 旁白 `onnx.Zhiming`；沈川 `onnx.Junhao`；林晚 `onnx.Xiaoyu` | 已试听、确认、locked/accepted/bound；不得再次要求作者选择，也不得回退旧 Lingyu/Yuewen/Junhao 映射 |
| 音色复用 | 同一用户在同一本地作品内直接复用／绑定中文官方 preset | 不做云端音色、远程 provider、共享音色或复杂继承层级 |
| 商业／权利流程 | `SUPERSEDED_NON_TARGET` | 只保留最小官方 repo/revision/preset ID/manifest/model fingerprint/hash 技术溯源；不建设审批或授权工作流，不阻断本地使用 |
| 英文／日文 | `OUT_OF_CURRENT_SCOPE` | 不做专项 UI、文本处理、试听或发布门禁；中文正文中的少量英文姓名、字母、数字只做基础兼容 |
| OS 签名与证明 | `REJECTED_NON_BLOCKING` | 不创建 daemon/launchd/专用身份/IPC signer/正式 key/trust root/key ceremony；历史候选不进入产品包与正常 launcher |
| 音频导出 | `T6-D_CANCELLED` | 不做章节/全书导出、拼接、导出 manifest/UI/API/测试；不得与网页分段 Manifest 播放混淆 |
| 云端辅助说话人识别 | `HOLD_PENDING_DECISION` | 没有被取消，也没有被放行；不阻断 local-rules-only T4 |
| 高级匿名人物选角 | `HOLD_PENDING_DECISION` | 没有被取消，也没有被放行；不阻断旁白＋两名正式人物 T4 |
| 当前完工门禁 | T4 中文本地闭环 | 真实章节、网页播放器、CodeMirror 句段同步、段落/光标跳播、倍速/进度、更新朗读、失败恢复、最小缓存/磁盘保护、30 分钟、四桌面、安装升级卸载非回归 |

当前 T4 ready set 已清空并由 `T4-GATE` 裁决为 `PASS_LOCAL_CHINESE_CORE`。v3 完整章节人工听检、同 run resume／teardown、长期环境部署 tree `7a57471b…`／迁移 `0024`、正式 product mode、作者系统中文输入法亲验、最小 `cache_cleanup`、失败句段人工重试契约、候选安装生命周期、文档／证据一致性收口和最终回归均已完成各自记录的产品或技术验收，不再列为等待项。补充 observer 自动 envelope 未形成，按最终门禁记录为非阻断证据边界，不构成新的施工工作包。`T5-*`、除最小磁盘保护外的 `T6-*`、全部 `AUTH-3*` 历史候选和 `T6-D` 都不在当前 ready set。

### 0.1 T4 失败句段人工重试补充冻结（2026-08-28）

当前只读审计证明既有 `project_failed_segment_retry_eligibility()` 固定返回 `execution_supported=false`，而 `jobs.manual_retry()` 只把 BackgroundJob 重新排队，不会复位 Render／EditionSegment／Edition／Request；直接接按钮会在 Worker load 阶段失败。因此 T4 的“失败句段可单独重试”按以下最小完整合同施工，不得降级成只有 UI 的假功能：

- `GET /narration-editions/{edition_id}/failed-segments` 返回 `narration-failed-segment-retry/1`，按公开 `NarrationSegment.id` 列出 ordinal、稳定 failure code、真实 retryable、job ID 及同 request／同 render fingerprint 的 fanout segment IDs；即使整章 `unavailable`，重载后仍可找回。
- `POST /narration-editions/{edition_id}/retry-failed-segments` 使用 `Idempotency-Key`，body 固定为去重的 `segment_ids[1..100] + expected_request_version + expected_manifest_revision|null`；服务端按 render/job 去重并自动扩展 fanout，返回 accepted／affected IDs、每组 command/job、request／Edition 新状态和 replay 标记。
- 新命令只接受“一次 Request 精确对应一个 Edition”的当前生产拓扑、job=`failed|dead_letter`、Render=`failed`、同 fingerprint fanout 全部 failed、voice 仍可用，且 Request／Edition 处于“部分失败仍在生产”或“全失败”两种精确组合。部分失败允许尚无 ready 段的 `failed + pending|queued|rendering` 在产组合并保持 aggregate 状态；`cancelled/quarantined` 不可混入。全失败只允许 Request `failed→queued`、Edition `unavailable→rendering`。Render 只允许 `failed→pending`，fanout EditionSegment 只允许 `failed→queued` 并清 failure code；ready／cancelled／quarantined 永不倒退。若未来允许同一 Request 产生多个 Edition，必须先补 request-wide 完成聚合再单独放行，当前不得猜测处理。
- 同一 root 幂等键与 canonical selection/op hash 只授权一次；同 payload replay 不再次复位或排队，改 payload 冲突。再次失败后作者再次点击必须使用新 root key。
- 写锁顺序冻结为 request 内全部 render job UUID 升序 → attempt/manual command → Request CAS → 目标 Edition → 目标 EditionState/Manifest revision CAS → render UUID 升序 → EditionSegment `(edition_id, ordinal)`；Edition 必须先于 EditionState，与 `publish_manifest` 的锁序一致，既阻止陈旧 revision 又避免反向死锁。HTTP 事务不发布 Manifest。Worker 成功或终态失败再追加新 Manifest revision，旧 Edition canonical input 和旧 Manifest 均不可变。
- 需要当前 migration head 后的新线性 fix-forward migration，只替换四个既有状态 guard，不新增表／列；每条反向边都必须由同 scope/source job 的 pending manual retry command 与 queued job 证明。还必须补 `narration.segment_render` expired-attempt terminalizer，避免崩溃后留下 render/segment=`rendering`。
- 前端在章节播放器下方显示失败句段及“重试本句”；共享 fingerprint 明示会同步重试 N 个相同音频句段。提交后禁用同组按钮并轮询现有 workflow／Edition／Manifest；成功恢复播放，失败重新允许作者用新幂等键重试，正文和 Edition 选择不变。

并行施工波次与文件锁：

| 波次 | 工作包 | 标记 | 唯一 Owner／精确文件 | 门禁与证据 |
| --- | --- | --- | --- | --- |
| R0 | `T4-RETRY-MIG` | `SER/MUTEX` | 单一代理：新 `backend/migrations/versions/20260828_0024_failed_segment_manual_retry.py`、`backend/narration/requests.py`、`backend/narration/editions.py`、迁移测试 | schema head、upgrade/downgrade、非法反向边、合法 command 证明；未完成前不得真实 DB 写 |
| R1 | `T4-RETRY-DOMAIN` | `PAR-C` | 单一代理：新 `backend/narration/failed_segment_retry.py`、`backend/narration/regeneration.py`、对应新测试；暂不触碰 API／前端 | fanout、CAS、幂等 replay、部分／全失败、voice rights、锁序测试 |
| R2 | `T4-RETRY-WORKER` | `PAR-C` | 主代理或单一代理：`backend/narration/manifest.py`、`worker.py`、`production_runtime.py` 与各自测试 | 再成功／再失败、失败 Manifest、expired attempt terminalizer、迟到 fence |
| R3 | `T4-RETRY-API` | `PAR-C` | 单一代理：`backend/narration/narration_api.py` 与 API 测试 | 固定 DTO、404 scope、409 CAS/idempotency/state、202 replay |
| R3 | `T4-RETRY-FE-CONTRACT` | `PAR-C` | 单一代理：`frontend/src/narration/chapter-contracts.ts`、`api.ts` 与对应测试 | 严格字段、unknown-field fail-closed、latest-wins |
| R4 | `T4-RETRY-FE-UI` | `SER` | 单一代理：`chapter-narration-panel.ts`、必要工作台接线／样式及对应测试 | 可见／禁用／fanout 提示、键盘／焦点／错误恢复；不得与其他代理同时改共享页面 |
| R5 | `T4-RETRY-INT` | `INT/GATE/MUTEX` | 主代理唯一 Owner | PostgreSQL 真实失败注入→单句 retry→fanout→成功／二次失败／崩溃恢复、四桌面浏览器、全量测试、打包与 QwenPaw 非回归 |

公共 DTO、上述状态边、迁移 Owner、锁序和 API 路径由本节先行冻结。所有子代理不得修改未分配文件，不得操作唯一正式数据库／容器、暂存、提交或推送；主代理负责逐波汇合与最终门禁。

## 1. 结论与产品定位

本项目当前交付一套本地中文多角色小说朗读与校听系统：

> 人物卡保存正式人物与中文官方预设的直接绑定；书本管理的“朗读”模块管理作品旁白与基础朗读设置；系统把不可变正文版本解析成可复核朗读脚本，按旁白／正式人物调用 MOSS-TTS-Nano 生成分段音频，并用句段时间轴驱动编辑器高亮和滚动。

系统中的职责必须分开：

```text
MOSS-TTS-Nano             = 单说话人发声引擎
人物卡                     = 正式演员档案
6 个中文 official preset  = 当前本地演员目录
本地人物归因规则            = 当前配音导演
朗读脚本                   = 可复核有声书画本
朗读版本 NarrationEdition  = 一次可复现的配音制作版本
持久任务与句段缓存          = 制作流水线
播放器与句段时间轴          = 阅读体验
```

**项目决策**：目标是实现与番茄小说公开能力同类的中文多角色网页朗读架构，不复制其私有算法、声音资产、品牌、界面文案或未公开接口，也不承诺达到其多年生产数据积累形成的主观音质。作品级旁白配置留在书本“朗读”页面，正式人物音色在人物卡中直接绑定；章节播放、段落／光标跳播和校听修改进入同一个章节工作台。章节／全书音频导出不属于本产品。

### 1.1 自动识别人物并自动配音的明确结论

**当前实现事实（2026-08-27）**：T2 朗读设置闭环已公开；T3 已实现固定本地 scope 的规则人物归因、旁白／已配置人物选角和脚本分析技术闭环；T4 的 Edition、合成、Manifest、播放器、CodeMirror／textarea 编辑器同步与播放进度已形成代码和自动化候选。但真实 T4-K／T4-GATE 尚未通过，相关公开 capability 仍为 `false/HOLD`，所以不能把这些候选表述为当前普通用户已可用。

**目标能力**：可以实现“系统自动识别旁白、正式人物、匿名人物和群体声音，并自动选择已配置音色完成多角色配音”。这不是 MOSS-TTS-Nano 单模型原生提供的能力，而是本项目把正文分析、人物卡、别名与场景、自动选角、脚本复核、Nano 合成和 Edition 播放组合后的产品能力。

```text
不可变正文 revision
  -> 句段与场景切分
  -> 自动判断 narrator / character / anonymous / group / unknown
  -> 正式人物映射到人物卡，匿名人物建立稳定身份
  -> 当前解析旁白或正式人物的 direct 中文 official preset；其他来源保持 HOLD
  -> 计算 warnings 与 blockers
  -> 默认策略且 0 blockers：系统自动冻结脚本并创建 Edition
  -> 存在 blockers 或启用逐章复核：进入脚本复核底部面板
  -> 作者集中处理后一次确认继续生成
  -> MOSS-TTS-Nano 按句段和锁定音色版本自动合成
  -> 形成可播放、可恢复、可回溯的 NarrationEdition
```

首版采用“可审计自动化”，而不是无条件猜测：

| 识别结果 | 系统自动行为 | 是否需要逐句人工处理 |
|---|---|---|
| 旁白 | 自动使用当前章节/分卷/作品旁白 | 否 |
| 高置信度正式人物 | 自动使用人物卡直接绑定的中文 official preset | 否 |
| 中置信度正式人物 | 自动给出人物和音色，明显标记证据 | 默认不阻塞，可集中检查 |
| 已知匿名人物 | 在其合法作用域内复用稳定匿名身份和音色 | 否；发生冲突时才处理 |
| 新匿名人物 | 自动建立候选稳定身份并从通用音色池确定性选角 | 低置信度或跨章疑似复现时处理 |
| 低置信度、`unknown`、别名/匿名冲突或缺失音色 | 不进入正式 Edition，不静默猜人物或套用错误音色 | 是，必须处理 |

用户不需要为每一句手动指定人物和声音。点击“智能朗读”“批量生成”或“更新朗读”后，系统完成识别、选角和所需生成；默认只有低置信度、`unknown`、别名冲突、匿名人物冲突和缺失音色成为待办。没有阻塞项时不再要求作者额外点击“审批”，但按键和普通自动保存仍不得触发说话人分析或 TTS。“扫描全书”只分析并报告覆盖率/阻塞项，不创建 Edition 或音频。

当前音色解析只有两条正式路径：作品旁白 direct 中文 official preset、人物卡 direct 中文 official preset；未直接绑定时进入待人工配置，不沿复杂继承、共享或云端音色链猜测。匿名人物和通用选角的既有候选继续 HOLD。任一已生成 Edition 都冻结实际使用的 `character_id`、音色版本、规则版本和正文 revision；以后修改人物卡音色或正文不会静默改写旧音频。

V2 界面中的对应入口为：朗读总览显示自动识别覆盖率、提醒和阻塞项；人物配音页显示正式人物声音映射；选角规则页控制本地规则、复核策略、匿名人物和可选智能增强；章节脚本复核底部面板只在阻塞或逐章复核时出现；满足冻结条件后由音频与缓存页及后台任务自动生产音频。

### 1.2 脚本复核策略：默认自动，异常暂停

作品设置增加独立于正文隐私模式的 `script_review_policy`：

| 策略 | 行为 | 适用场景 |
|---|---|---|
| `blockers_only`（默认） | 零阻塞时由确定性领域规则自动冻结脚本并继续创建 Edition；有阻塞时才暂停 | 日常写作与番茄式低摩擦朗读 |
| `always_review` | 即使零阻塞也打开整章复核面板，作者确认后才创建 Edition | 重要章节、出版前校听或作者主动精细控制 |

`blockers_only` 不是让聊天模型自行“批准”内容。只有用户已显式发起朗读/更新/批量生成、分析成功、`blocker_count = 0`、全部人物/匿名身份/音色/scope 可解析且模型身份校验通过时，领域服务才能执行自动冻结。中置信度结果作为 `warning` 可见但不阻塞；低置信度、`unknown`、别名冲突、匿名身份冲突、缺失音色、非法人物/scope 和硬性发音冲突属于 `blocker`。`analyze_only` 扫描结果不得触发自动冻结或生成；后续生成前必须重新校验正文与设置 fingerprint。

每次冻结都记录 `approval_kind = auto_no_blockers | manual_after_review`、策略和阻断分类版本、warnings/blockers 计数、actor、时间、规则/模型 fingerprint 与输入哈希。自动或人工冻结后的脚本同样不可变；任何修改都创建新脚本版本。逐次请求只允许把默认策略临时收紧为 `always_review`，不能把作品已设为逐章复核的策略静默放宽。

## 2. 研究结论和能力边界

### 2.1 MOSS-TTS-Nano

**已核实事实**：根据 [MOSS-TTS-Nano 官方仓库](https://github.com/OpenMOSS/MOSS-TTS-Nano)、[官方 ONNX 权重](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX)及其运行时代码，Nano 具备：

- 约 1 亿参数的轻量自回归语音生成架构；
- ONNX CPU 推理和浏览器 ONNX 路径；浏览器 JavaScript 路径可以不依赖 PyTorch，但当前固定的官方 Python ONNX 入口仍在顶层导入 `torch/torchaudio`，T1-DEP 不得把它误配成 torch-free；
- 48 kHz 双声道音频生成；
- 内置参考音色和自定义参考音频克隆；
- 长文本按句段切分；
- 流式与非流式生成；
- CLI、Web Demo、FastAPI 演示接口、浏览器 ONNX 示例和 MLX 社区接入路径；
- 文本规范化、采样参数和随机种子配置；
- 代码仓与模型卡发布元数据声明 Apache 2.0；该声明不自动覆盖训练数据、示例参考录音、声音/人格权、生成输出的所有商用场景，也不覆盖无根许可证的 Reader 项目。

官方仓库明确说明 ONNX CPU 版本保留参考音频克隆与实时流式解码，并报告其在 MacBook Air M4 单核可运行；官方 [Nano Reader](https://github.com/OpenMOSS/MOSS-TTS-Nano-Reader)还提供本地网页朗读和浏览器 ONNX 路径。这证明本地句段朗读具备工程基础，但不等于官方模型直接返回适合本项目的可靠逐字或跨句时间轴。

固定 ONNX manifest 显示 18 个官方预设，其中 6 个为中文标识。用户此前允许个人本地使用全部 18 项，这一历史裁决证明不存在基于名称或公众人物标签的本地禁用规则；2026-08-27 最新产品范围又进一步收敛为**只向当前产品提供 6 个中文预设**。因此底层 18 项 manifest/catalog 和精确 hash/fingerprint 仍可保留用于兼容、升级和排错，但产品选择器、试听、绑定、合成、语言专项和发布门禁只覆盖 `onnx.Junhao`、`onnx.Zhiming`、`onnx.Weiguo`、`onnx.Xiaoyu`、`onnx.Yuewen`、`onnx.Lingyu`。其余 12 项是“当前非目标”，不是因商业权利或人物标签被禁止。

#### 2.1.1 个人本地 official preset re-freeze（2026-08-27）

本节取代本文、ADR-0005、T0-E/T2/T4-K 当前口径中任何“18 项全部进入当前产品”或“因商业授权、明星／公众人物标签而排除官方预设”的规则。历史审计原文和 hash 继续保留并标记为商业发布／再分发或旧产品范围记录。当前个人本地中文产品契约冻结如下：

1. 唯一目录权威为 `OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX` revision `f52645cb467506d8e18e746ddd59482685b74e58` 的 `browser_poc_manifest.json`，内容 SHA-256 为 `097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee`；当前精确包含 18 个 preset，任何增删都要求新 revision、新 manifest hash 和显式 re-freeze。
2. 对外 `preset_id` 采用 `onnx.<manifest voice>`，例如 `onnx.Lingyu`；Sidecar 只能在已验证固定 manifest 中按 exact `preset_id → manifest voice` 一一映射并使用该行 `prompt_audio_codes`。不得去掉前缀后跨 Python Runtime 猜同名替代；缺行、缺 prompt codes、重复映射、manifest/hash/model fingerprint 不匹配或真实推理失败才是合法技术阻断原因。
3. 数据库既有 `VoiceProfileVersion.source_type='preset'` 继续作为兼容性的领域类别，不伪装成上传或生成来源；每条新官方预设记录的 `VoiceRightsRecord.source_kind` 必须为 `official_preset`，并在 `parameters_json.official_preset` 不可变保存 repository、revision、manifest path、manifest SHA-256、exact preset ID、manifest voice、prompt-codes SHA-256、prompt frame/quantizer 数、模型 fingerprint SHA-256 与 provenance fingerprint。API 同时投影强类型 `OfficialPresetProvenance`。因此“官方预设记录为 `official_preset`”有可查询、可审计的实体字段；旧 `preset_catalog` 只作为历史只读兼容值，不得用于新建官方预设。
4. 不再建设商业使用、再分发或声音权利审批流程，也不以这些状态参与个人本地 usability、capability、试听、锁定、绑定、合成和播放判定。既有 rights 字段只作为历史 schema 兼容和最小技术来源记录，不得形成审批按钮、审批状态机、前置确认或发布门禁；官方预设不要求用户参考录音、subject consent reference、`VoiceReferenceAssetLink` 或上传媒体。
5. 服务端可继续读取固定 18 项 metadata-only catalog，但当前产品投影和所有可操作入口只返回／接受六个中文 preset ID；不得返回 prompt codes、模型权重、官方参考音频路径或音频字节。`POST /voice-profiles/{profile_id}/versions/preset` 只接收 exact 中文 `preset_id` 与 profile CAS，语言、显示名和全部 provenance 由服务端目录填充，客户端不能覆盖。未来若扩大产品语言范围，必须另行 re-freeze，而不能只靠前端取消过滤。
6. 中文 official preset capability 独立于 reference clone；只有固定目录校验通过、生产 Sidecar 模型 fingerprint 匹配且当前产品／隐藏验证运行链允许 TTS 时才 actionable。模型未安装或 runtime 未 ready 时六项仍可展示为技术不可用，试听/合成返回稳定技术 HOLD，不得改写为授权失败。
7. official preset 试听使用真实 Nano 且不上传参考音频；试听媒体仍是临时、私有、可到期资产并保留 ModelRun/fingerprint 证据。版本只有在真实试听成功并由作者确认听感后才能成为 `locked/accepted`；T4-K 的三个预设必须满足同样锁定条件。
8. T4-K 的唯一权威映射已经由作者确认并实际写入：旁白 `onnx.Zhiming`、沈川 `onnx.Junhao`、林晚 `onnx.Xiaoyu`。readiness/runtime audit 必须核验这三个 exact 角色语义绑定、三个互异中文 preset ID、同一 manifest/model fingerprint、锁定／接受状态和 official provenance；不得回退旧 Lingyu/Yuewen/Junhao 候选，不得再次要求作者选择，也不得要求三份用户上传录音、克隆权利链、reference link 或六份媒体。
9. Git、插件包和镜像层不提交官方预设音频、prompt codes、模型权重或生成音频；只允许 metadata、revision、hash、fingerprint、代码、测试和脱敏证据。运行时继续从固定官方来源安装模型树并使用 manifest 内嵌 prompt codes。

当前 fixed manifest 的 18 个 external preset ID 精确为：`onnx.Junhao`、`onnx.Zhiming`、`onnx.Weiguo`、`onnx.Xiaoyu`、`onnx.Yuewen`、`onnx.Lingyu`、`onnx.Trump`、`onnx.Ava`、`onnx.Bella`、`onnx.Adam`、`onnx.Nathan`、`onnx.Soyo`、`onnx.Saki`、`onnx.Mortis`、`onnx.Umiri`、`onnx.Mei`、`onnx.Anon`、`onnx.Arisa`。目录不得设置公众人物排除名单。

Nano 原生不负责：

- 从小说正文识别说话人；
- 将人物姓名映射到项目人物卡；
- 在单个请求中原生编排多角色对话；
- 根据自由文字描述创造全新音色；
- 返回可靠的逐字时间戳；
- 提供可直接依赖的高级情绪控制 API；
- 完成有声书人工校对、缓存和版本治理。

因此 Nano 只能是最终 TTS 引擎，不能被误写成完整多角色系统。

### 2.2 MOSS-VoiceGenerator

**已核实事实**：[MOSS-VoiceGenerator 官方模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator)说明它可以根据自由文字描述生成音色、情绪和说话风格，不要求参考录音；当前公开模型约 1.7B，权重约 4.2 GB，重点支持中英文。

**项目决策**：VoiceGenerator 只在创建或调整音色时按需运行。作者从多个候选中选择一个样音，经 Nano 克隆验证后将该样音锁定为不可变音色版本；正式章节朗读全部交给 Nano。禁止为每一句台词重新调用 VoiceGenerator，否则同一人物可能出现音色漂移。

VoiceGenerator 的公开模型卡证明了文字描述生成音色，不证明其在 M4 16 GB、MPS 或与 Nano 二次克隆组合中的速度和稳定性。T0-D 当前只有元数据和静态权重下界估算，真实加载/生成/峰值 RSS/听检均为 0，因此 `voice_generator_visible=false`；只有独立依赖锁、真实 M4 资源、人工听检和 Nano 二次克隆全部通过并修订门禁后，才可重新申请“实验性”入口。

### 2.3 番茄式公开方案

**已核实事实**：番茄小说的[官方 App Store 说明](https://apps.apple.com/cn/app/id1468454200)公开了多角色对话音、角色设定匹配音色和情绪表达；[字节 Leto](https://leto.bytedance.com/experience)与[火山引擎有声内容创作平台](https://www.volcengine.com/product/accp)公开展示了旁白/对白分离、人物识别、情绪预测、音色选择、发音/停顿校对和批量生成。

**技术推断**：可复核的同类生产链为：

```text
正文版本
  -> Markdown/文本切分
  -> 旁白与对白识别
  -> 正式人物/匿名人物归因
  -> 情绪、表达方式和停顿建议
  -> 人物/路人/旁白音色选角
  -> 作者复核朗读脚本
  -> 分段 TTS
  -> 音频后处理、缓存和拼接
  -> 文本位置与音频时间映射
  -> 播放、高亮和进度恢复
```

番茄未公开完整实现源码和客户端同步协议。本项目只采用由官方公开产品能力支持的架构模式。

[公开可复核的番茄操作记录](https://jingyan.baidu.com/article/bea41d43dfc919f5c41be60b.html)还显示，至少部分版本在“边听边读”中提供“长按段落 -> 从本段听”。具体手势可能随客户端版本变化，本项目只学习“正文位置可成为播放起点”的产品原则：只读朗读视图可直接点击句段，写作编辑器必须保留普通单击放置光标，改用段落边栏播放按钮、上下文菜单和键盘命令触发跳播。

## 3. 范围

### 3.1 纳入

- 书本管理新增独立“朗读”入口；
- 旁白声音与作品级朗读规则；
- 人物卡专属音色；
- 青年、中年、老人、儿童、中性等通用/路人音色池；
- 匿名说话人稳定绑定；
- 预设、上传参考录音和文字描述生成三种音色来源；
- 旁白/对白切分和正式人物识别；
- 情绪与表达方式建议；
- 低置信度人工复核；
- 本地规则分析和经用户授权的云端辅助分析两种隐私模式；
- 按章合成、增量重生成、缓存和失败恢复；
- 同一朗读脚本的多朗读版本与历史回溯；
- 句段级正文高亮和自动滚动；
- 章节工作台内的段落跳播、固定播放器和边听边改；
- 音频未全部完成时，对用户明确选择位置建立连续就绪播放窗口；
- 工作稿与当前朗读快照不一致时的旧稿提示、显式更新与版本切换；
- 播放进度保存；
- `SUPERSEDED_NON_TARGET`：后续全书批量生成的历史设想不在当前 T4 完工范围；章节／全书音频导出已明确取消，禁止继续施工。

### 3.2 明确排除

- 逐字卡拉 OK 高亮；
- 实时多人语音聊天；
- 首版使用 8B MOSS-TTSD 作为本机默认模型；
- 未经授权的真人、名人或第三方声音克隆；
- 直接复制番茄或其他平台的私有音色和内部算法；
- 模型自动新增正式人物或直接修改小说正文；
- 默认把整章正文发送给云端模型；
- 首版跨句 rolling prompt、跨显示句段合成和逐字强制对齐；
- 第一版自动生成复杂情绪变体并静默替换已锁定音色；
- 每次按键、每次自动保存都触发说话人分析或 TTS；
- 播放过程中无提示地把旧 Edition 切换成新正文 Edition；
- 在可编辑正文中劫持普通单击作为播放手势。

本节“未经授权的真人、名人或第三方声音克隆”只约束用户上传、文字描述生成、外部素材和主动仿声功能，不得解释为基于名称或公众人物标签过滤固定官方 ONNX manifest。现行产品只展示并开放 2.1.1 冻结的 6 个中文 `official_preset`；其余 12 项仅保留 metadata-only 技术目录用于固定版本兼容、升级和排错，不进入当前 UI、绑定、合成或门禁。`Xiaoyu` 属于正式六项并正常可用；`Trump` 未进入当前产品只是语言范围收敛，不是公众人物排除。

## 4. 当前项目基础与必须保持的边界

**已核实事实**：

- [`NovelCharacter`](../../backend/models.py) 已有稳定 UUID、`novel_id`、角色类型、姓名、描述、`details`、生命周期和版本字段。
- [`DocumentRevision`](../../backend/models.py) 已保存不可变 Markdown、纯文本、内容哈希和来源。
- [`DocumentWorkingCopy`](../../backend/models.py) 已提供草稿版本和内容哈希。
- [`MediaAsset`](../../backend/models.py) 已预留小说媒体元数据、来源 revision、存储路径和内容哈希，但尚缺 MIME、字节数、资产类别、生命周期、保留策略和存储后端字段，实施时必须扩展，不能把现状误写为已满足朗读资产治理。
- 当前作品工作台导航为章节、大纲、角色、线索、设定，见 [`workbench-studio.ts`](../../frontend/src/workbench-studio.ts)。
- 当前桌面工作台同时保留 QwenPaw 全局左侧导航、PawApp 作品/章节导航、中央业务区和右侧原生 AI 助手。TTS 页面、播放器和复核工具只能使用 PawApp 自有区域，不能占用、替换或覆盖原生助手列。
- 当前正文控件实际仍是原生 `textarea`，见 [`workbench-v2.ts`](../../frontend/src/workbench-v2.ts)；它只能提供整块文本选择和光标偏移，不能原生渲染句段 decoration、段落 gutter 或被编辑事务安全映射的播放范围。
- 现有架构已经预留 `TTSAdapter`、`LocalMountedMediaStorage` 和 TTS 失败不影响正文的边界。

**项目决策**：

- 音色不能写入 `NovelCharacter.details`。当前人物保存逻辑会用性别、年龄、身份和性格重建 `details`，音色数据存在被覆盖风险；音色版本、参考录音、授权、缓存失效和历史引用也需要独立关系表。
- TTS 是 revision 绑定的可重建派生数据。失败、取消或清理不得修改 working copy、正式 revision、角色和故事账本。
- 浏览器只访问 PawApp API；浏览器不能直接访问模型 Runtime、模型目录或文件系统路径。
- 逻辑上保留 `TTSAdapter` 和 `VoiceDesignAdapter`；Nano 的物理运行方式由阶段 0 决定。即使采用本机 Sidecar，它也只是受控模型依赖，不是第二套业务 API、Agent Runtime 或权威任务系统。
- 现有 `ChapterGenerationJob`、`CreativeGenerationJob` 不作为 TTS 新建第三套调度器的理由。朗读使用共享持久任务领取、租约、重试和审计协议，领域表只保存朗读状态。
- 章节播放和写作必须同页，但播放权威始终是不可变 `NarrationEdition`，编辑权威始终是 `DocumentWorkingCopy`。两者可以同时存在，不能共享一个会随按键变化的内容哈希。
- T0-F/T0-GATE 的编辑器兼容性尖峰已经选择 CodeMirror 6，并冻结业务层只依赖 `NarrationEditorBridge`；Monaco 不进入根依赖。T4-K/T4-GATE 仍须在固定 QwenPaw Blob bundle、系统中文输入法、现有自动保存和真实长章节中复验该选择，但不得把“再次比较 Monaco”列为发布前未决项。
- 原生 `textarea` 只允许作为安全降级：音频可继续播放，编辑仍可进行，但正文变更后当前句只显示在播放器字幕或不可变旧稿抽屉中，不承诺可编辑正文内的精确高亮和段落边栏跳播。

## 5. 产品信息架构

### 5.1 作品工作台导航

```text
章节
大纲
角色
线索
设定
朗读  <- 新增，位于“设定”下方
```

路由 section 新增稳定值 `reading`。新版工作台、兼容工作台、创作中心跳转、路由恢复、类型定义和测试必须同步扩展，不能只在一个导航数组里增加按钮。

创作中心作品卡的四个主快捷入口调整为大纲、角色、线索和朗读；破坏性的删除进入作品卡更多菜单，不与高频创作入口并列。该调整属于 V2 设计候选，只有用户批准并进入对应实施阶段后才能修改代码。

### 5.2 “朗读”页面

```text
朗读
├── 总览
├── 旁白
├── 人物配音
├── 通用音色
├── 选角规则
├── 发音与停顿
└── 音频与缓存
```

#### 总览

显示：

- Nano Runtime 安装、健康和预热状态；
- VoiceGenerator 可用状态；
- 当前正文分析隐私模式及云端授权状态；
- 当前脚本复核策略；
- 当前旁白；
- 正式人物音色覆盖率；
- 通用音色池覆盖率；
- 自动识别覆盖率、提醒/阻塞数量、待复核脚本、已生成章节和失败任务；
- 模型、媒体和缓存磁盘占用；
- 测试朗读、初始化基础音色包、扫描缺失配置、批量生成和清理缓存入口；
- 不可删除源资产、可回收派生缓存和预计可释放空间分别统计。

#### 旁白

支持：

- 默认旁白音色和不可变版本；
- 内置、上传、文字生成三种来源；
- 语言、叙述风格及合成参数；
- 播放倍速和播放器音量；二者属于播放设置，不触发重新合成；
- 是否朗读章节标题、作者的话和分隔内容；
- 第一人称叙述使用旁白还是指定人物；
- 内心独白使用人物声还是旁白声；
- 可选分卷和章节旁白覆盖；覆盖必须落入 `narration_scope_overrides`，不能只存在于 UI；
- 试听、确认和版本历史。

#### 人物配音

集中显示每个正式人物：

- 专属音色、继承音色或未配置；
- 当前音色版本；
- 试听；
- 跳转人物卡声音设置；
- 受音色变更影响的章节和句段数量；
- 批量初始化或重生成入口。

#### 通用音色

管理路人、临时角色和缺少专属音色人物的音色池，详见第 6 节。

#### 选角规则

管理人物归因、匿名角色复用、同场景去重、备用声音、低置信度阈值、第一人称、内心独白、信件、电话、广播和群体声音规则，同时显示：

- `仅异常复核`（默认）与 `每章都复核` 两种脚本复核策略；策略与正文是否允许云端分析分开设置；
- `隐私优先`：本地规则无法确定时直接进入人工复核；
- `智能增强`：仅把不确定句段和最小上下文发送给当前受控聊天模型；必须单独确认作品级授权；
- 最近一次分析实际使用的供应商、模型和规则版本；
- 云端关闭后不会把已有云端判断冒充新的本地判断。

#### 发音与停顿

管理人名、地名、多音字、外语名、数字、年代、特殊称谓、朗读替换、句间停顿和不朗读规则。朗读替换只改变 `spoken_text`，不得修改正文。

#### 音频与缓存

按章节显示正文版本、脚本状态、生成状态、音色版本、时长、大小、失败句段、过期状态、重新生成和删除缓存。章节／全书音频导出已取消，不提供导出按钮。

### 5.3 人物卡“声音”页签

人物卡增加：

- 是否使用专属声音；
- 音色来源；
- 可编辑音色描述；
- 试听文本；
- 多候选生成和试听；
- 上传参考录音；
- Nano 克隆测试；
- 确认锁定；
- 当前版本和历史版本；
- 默认语言与基础朗读参数；
- 继承的通用音色及转为专属音色入口。

### 5.4 章节编辑器

章节写作与校听使用同一个章节工作台；书本“朗读”页面继续负责旁白、人物、通用声音、选角和作品级规则，不把这些制作设置复制进章节正文。

```text
┌──QwenPaw──┬────章节树────┬────────────章节正文────────────┬──原生 AI 助手──┐
│ 全局导航  │ 第一章       │  ▶ 第一段正文……               │ 会话与创作上下文│
│           │ 第二章       │    “第一句对白……”             │ 不承载 TTS 表单 │
│           │ 第三章       │  ▶ 第二段正文……               │                │
└───────────┴──────────────┴────────────────────────────────┴────────────────┘
                            ┌────脚本复核底部面板（按需）────┐
                            │ 句段列表｜说话人/音色/证据/修正 │
                            └────────────────────────────────┘
                            ┌────────固定播放器──────────────┐
                            │ 当前稿/旧稿｜播放｜进度｜更新朗读│
                            └────────────────────────────────┘
```

章节工作台增加：

- `智能朗读` 和当前朗读 Edition 状态；
- 朗读脚本复核底部面板，不强制离开章节，也不与右侧原生 AI 助手争夺同一列；
- 只位于 PawApp 编辑区内、在原生 AI 助手左侧结束的固定底部播放器；正文必须预留真实底部空间，不能被播放器覆盖；
- 播放、暂停、倍速、上一句、下一句和完整 Edition 的全章进度拖动；
- 当前说话人、音色、源正文版本和“当前稿/旧稿”状态；
- 当前句段高亮、自动滚动和“返回当前朗读位置”；
- 段落边栏 `▶`、上下文菜单“从本段朗读”和键盘命令；
- 单句试听、重新生成和“更新朗读”；
- 正文修改后的待更新范围与旧版本提示。

#### 自动生成与复核状态

- 点击“智能朗读”或“更新朗读”后，按钮进入“正在分析人物与选角”，并通过可读状态区报告进度；普通输入和自动保存不出现该状态；
- 默认 `blockers_only` 且零阻塞时，页面显示“识别完成，已自动创建 Edition；0 个阻塞、N 个提醒”，直接进入渐进生成，不打开复核面板；
- 发现阻塞时，页面显示阻塞总数并打开/提示打开复核底部面板；面板默认只列阻塞项，可切换查看全部 warnings；
- 阻塞未清零时“处理完成并继续生成”禁用；清零后作者一次确认，脚本以 `manual_after_review` 冻结并继续；
- `always_review` 即使零阻塞也打开面板，主要按钮文案为“确认脚本并生成”；
- 分析器失败、模型身份不匹配或输出结构非法属于分析失败，不伪装成待复核，也不能自动冻结；云端授权撤销后不再外发，无法由本地规则确定的句段转为阻塞；Nano Runtime 不可用则脚本可保留，但 Edition 生成进入可恢复失败/待就绪状态；
- 生成进度、成功、部分就绪和失败均与当前 `edition_id` 绑定；重新分析不会原地覆盖已冻结脚本或历史 Edition。

复核面板打开后，键盘焦点进入面板标题或首个阻塞项；关闭后回到原触发控件。阻塞、提醒和已确认状态必须同时有文字/图标，不只依赖红黄绿；状态变化使用非打断式 live region。TTS UI 且仅在 `1920×1080 × 助手收起`、`1920×1080 × 助手展开`、`2560×1440 × 助手收起`、`2560×1440 × 助手展开` 四个组合下验收句段列表、编辑表单、右侧原生 AI 助手和固定播放器不互相覆盖；低于 1920×1080、移动、窄屏和 200% 等效小视口不设计替代堆叠布局，也不作为本专项验收范围。已经存在的防御性窄屏 CSS 可以保留以避免宿主回归，但不形成 TTS 专项的设计、截图、人工验收、发布阻断或后续维护承诺。

复核面板与播放器不得成为两个互相覆盖的 fixed layer：没有活跃播放时使用完整复核面板；旧 Edition 正在播放时音频默认继续，完整播放器收为面板内/上方的紧凑播放条，至少保留“旧稿”标记、说话人、播放/暂停、进度和关闭面板后的焦点恢复。关闭复核面板后恢复完整播放器。若分析期间 working copy 已继续修改，面板必须显示其绑定的来源 revision，并提供“继续生成该快照”与“使用最新正文重新分析”，不能把旧脚本修正套到新正文偏移。

#### 写作手势与跳播

- 普通单击、拖选、双击和中文输入法行为完全归编辑器所有，不能触发播放；
- 可编辑模式以段落边栏 `▶` 为主入口；上下文菜单和可配置键盘命令为辅助入口；
- 只读朗读快照允许直接点击句段；若点击的是段落空白，解析为该段第一个可朗读 `segment_id`；
- 段落含多个句段时，边栏按钮从第一句开始，句段点击或上下文菜单可从具体句开始；
- 标题、分隔符或不朗读内容没有可播放 segment 时禁用入口并说明原因；
- 工作稿段落已经修改、新增或无法唯一映射到当前 Edition 时，不得把该段强行指向相似旧句；入口改为“更新后朗读”，只有进入不可变旧稿视图后才能明确跳播旧内容；
- 目标起点已有满足缓冲策略的连续 ready window 时立即 `seekToSegment`；目标句虽 ready 但后续缓冲不足时，仍创建或提升从该句开始的播放窗口并显示准备状态，不静默回退到章首；
- 连续点击不同段落只保留最后一次用户意图为最高交互优先级，已完成 render 和正在安全执行的模型调用不被破坏。

播放器和所有跳播入口必须支持键盘操作、焦点可见、ARIA 标签和高对比度高亮。段落边栏按钮使用“从第 N 段朗读”等可读标签，不能只依赖 hover 或颜色。

#### 自动跟随与编辑优先

- 未发生人工操作时，当前 `segment_id` 驱动句段级高亮和滚动；
- 用户手动滚动、移动光标、选择文字或开始输入后，立即暂停自动跟随，播放器继续播放；
- 暂停跟随后显示“返回当前朗读位置”，只有用户明确点击才恢复；
- 自动滚动不能改变 selection、输入法 composition、撤销栈或编辑器焦点；
- 当前播放句段被修改时，旧音频可以继续，但该句在工作稿中的高亮失效，播放器字幕显示 Edition 中的旧文本并明确标记“旧稿朗读”。

### 5.5 同页边听边改的版本契约

“边听边改”表示播放与编辑可以同时进行，不表示每次按键都实时重新合成：

```text
不可变正文快照 A ──► Script A ──► Edition A ──► 正在播放
                                           │
作者继续编辑 ─────────► WorkingCopy B       │ 音频仍锁定 A
                                           ▼
                                  显示“旧稿朗读/待更新”
                                           │ 用户点击更新朗读
                                           ▼
不可变正文快照 B ──► Script B ──► Edition B ──► 用户明确切换
```

必须满足：

1. 播放会话固定 `edition_id`，不因 working copy 自动保存而切换 Edition；
2. 同一 Edition 可在句段边界刷新到更新的 Manifest revision，以接收新完成的 render，但不得改变来源 `revision_id/content_hash`；
3. 作者输入只更新 working copy；不得在每次按键或每次自动保存后创建分析/TTS 任务；
4. 活跃编辑会话可通过编辑器 transaction 映射未被触碰且局部文本哈希/锚点仍一致的句段范围；任何与变更相交的句段立即标为本地失效，段落拆分/合并或边界标点变化还要保守失效相邻块；
5. 页面重载、编辑器映射链丢失或无法唯一验证锚点时，禁止把旧偏移映射到当前正文，只在播放器字幕或不可变旧稿视图高亮；
6. “更新朗读”先完成保存屏障，再幂等创建/复用新快照和脚本；说话人分析至少覆盖变化句段及其必要场景上下文；
7. 新脚本按 `script_review_policy` 自动冻结或经人工复核后冻结，再创建新 Edition；相同 `spoken_text`、音色和模型输入继续复用 render；
8. 新 Edition 准备好后由用户选择“立即从对应位置切换”或“下次播放使用新版本”；前者必须带可播放起点，后者必须已有章首或已保存的合法起点，不能无提示热切换；
9. 旧 Edition、旧进度和旧快照保持可回放，删除和回收继续服从媒体保留策略。

## 6. 声音体系

### 6.1 声音类型

```text
旁白
正式人物专属声音
正式人物继承声音
匿名/路人声音
群体声音
未知备用声音
```

### 6.2 通用音色池最低分类

| 年龄感 | 男性 | 女性 | 首版建议槽位 |
| --- | --- | --- | ---: |
| 儿童 | 男童 | 女童 | 各 1–2 |
| 少年/少女 | 少年 | 少女 | 各 2 |
| 青年 | 青年男性 | 青年女性 | 各 3 |
| 中年 | 中年男性 | 中年女性 | 各 3 |
| 老年 | 老年男性 | 老年女性 | 各 2 |
| 中性/未知 | 中性声音 | — | 1–2 |
| 群体 | 众人/人群 | — | 1–2 |

按每类下限计算，完整基础池至少需要 24 个可区分槽位。该 24 槽是已退出当前完工范围的历史规划，不能阻断中文有限核心。现行产品只使用固定官方 ONNX manifest 中的 6 个中文预设作为手动选声与真实章节验收来源；底层 18 项目录不等于 18 项产品能力，也不能凭数量宣称已填满自动通用选角矩阵。商业发布／再分发未评估只作独立历史信息，不参与本地中文六项的可用性判断。

**基础音色包闸门**：阶段 0 必须完成以下二选一，否则“自动通用选角”不得进入默认可见范围：

1. 使用 VoiceGenerator 为每个槽位生成至少 2 个候选，经人工试听、Nano 二次克隆和授权记录后锁定 24 个项目基础音色；
2. 准备不少于 24 个具有明确授权来源的内置参考音色，并通过同一套质量验收。

个人本地中文产品现已批准固定 6 项中文 official preset 作为独立系统预设来源；其目录、真实试听和手动绑定可以开放，不受历史 24 槽规划是否完成影响。固定 manifest 的 18 项 metadata-only 技术目录继续保留，但不得把其中 12 项非中文行投影为当前产品能力。界面也不能用这 6 项冒充按年龄／性别／场景覆盖的完整自动通用选角矩阵。用户上传 reference clone 是另一条独立来源：T0 已冻结 reference-audio 为 multipart 元数据加内联 WAV/FLAC bytes 的窄协议，并在 Linux 真容器完成 3/5/8/12 秒 isolated-test-only 技术 smoke，但产品 fixture、来源声明和人工听感尚未完成，所以 `reference_clone_visible=false`；这项 HOLD 不影响中文 official preset。

每个槽位是具体音色版本，例如“青年女性 A：清亮活泼”“青年女性 B：温柔内敛”。音色元数据至少包括：

- 性别；
- 年龄段；
- 语言；
- 音高和音色质感；
- 性格气质；
- 可选职业/场景标签；
- 适用与不适用标签；
- 是否启用；
- 优先级和版本。

标签只用于选角，不足以证明两个音色在听感上真正不同。首版由人工试听负责最终去重；可选声纹嵌入只作为相似度预警，不能代替作者确认，也不得在没有相应模型和基准时写成已实现能力。

### 6.3 匿名说话人

“店小二、老妇人、侍卫、陌生女子”等不强制建立正式人物卡，但系统必须创建可追踪的匿名说话人并稳定绑定声音。

默认规则：

- 自动复用范围默认为“场景或章节”，不因“老妇人、侍卫”等泛称相同就跨全书认定为同一人；
- 同一稳定匿名人物在其作用域内再次出现时复用原音色；
- 同一场景不同匿名人物尽量不用同一音色；
- 通用音色尽量避开同场景正式人物的音色；
- 重跑分析和合成不得随机换声音；
- 匿名人物跨多章反复出现时提示作者升级为正式人物卡；
- 升级必须由作者确认，并允许继承既有声音和历史别名。

系统必须提供匿名人物合并、拆分、重命名、调整作用域和转为正式人物的复核操作。跨章节复用必须来自明确别名/上下文证据或作者确认。

### 6.4 群体声音

第一版用一个群体代表音色并明确标记 `group`。高级版可将 2–3 个不同音色分别合成，加入轻微时间偏移后混合。群体混合是后处理能力，不把 Nano 描述为原生多人同时发声模型。

### 6.5 音色来源

#### 系统预设

个人本地中文产品的系统预设来自 2.1.1 固定 manifest 中的六项中文行，只展示这六项并用于试听、旁白初始化、人物绑定、合成和播放。底层其余 12 项 metadata 仅为固定版本兼容和技术溯源保留；它们不是因名称或标签被禁用，但不进入当前产品投影。六项均以 `official_preset` provenance 保存 repo、revision、exact preset ID、manifest/model fingerprint 与必要 hash；不建设商业审批。24 槽通用音色包是已退出当前范围的历史规划。

#### 上传参考录音

流程：

1. 用户选择文件并确认拥有授权；
2. 校验 MIME、扩展名、大小、时长和可解码性；
3. 检测过长静音、削波和明显噪声；
4. 保存原始私有资产；
5. 生成统一格式的参考音频；
6. 使用 Nano 生成固定测试句；
7. 作者试听；
8. 保存来源、授权和文件哈希；
9. 锁定音色版本。

#### 文字描述生成

流程：

```text
人物年龄/性别/身份/性格/小传
  -> 本地模板生成可编辑音色描述
  -> 作者确认描述
  -> VoiceGenerator 生成多个候选
  -> 作者试听选择
  -> 保存候选来源、描述、模型和种子
  -> Nano 克隆测试
  -> 作者锁定为不可变音色版本
```

默认由本地模板把年龄感、性别、音高、质感、语速倾向和性格标签组合成描述，不需要把人物小传发送给聊天模型。若以后提供 AI 润色，必须使用同一显式授权机制但单独说明“音色描述润色”用途，只发送作者勾选的最小字段；说话人分析授权不能自动扩张为该用途。最终描述必须由作者确认后才能交给本地 VoiceGenerator。

## 7. 自动选角

### 7.1 优先级

```text
1. 章节范围人工覆盖
2. 分卷范围人工覆盖
3. 作品级旁白与人工选角规则
4. 正式人物专属音色
5. 正式人物明确绑定的继承音色
6. 已存在匿名说话人绑定
7. 根据人物描述匹配通用音色池
8. 根据性别/年龄匹配备用池
9. 中性备用音色
10. 无法安全判断：待人工确认
```

### 7.2 选角流程

```text
当前句段
   │
   ├─ 旁白 -> 旁白音色
   │
   ├─ 正式人物
   │    ├─ 有专属音色 -> 专属音色
   │    └─ 无专属音色 -> 年龄/性别通用池
   │
   ├─ 已知匿名人物 -> 复用匿名绑定
   │
   ├─ 带描述的匿名人物
   │    ├─ 年轻女子 -> 青年女性池
   │    ├─ 老妇人 -> 老年女性池
   │    ├─ 中年男人 -> 中年男性池
   │    ├─ 小男孩 -> 男童池
   │    └─ 侍卫/医生/掌柜 -> 属性和职业标签匹配
   │
   ├─ 众人齐声 -> 群体规则
   │
   └─ 未知 -> 待确认并阻止正式 Edition
                └─ 仅作者显式选择临时试听时，才可使用中性备用音色；试听资产不得进入正式版本
```

### 7.3 稳定分配

通用音色选择使用确定性分配，输入至少包含：

```text
novel_id
+ anonymous_speaker_stable_key
+ generic_pool_version
+ scene_scope（仅用于同场景排除）
```

同一稳定键在同一通用池版本下得到相同 slot。音色池升级不能改变任何历史 Edition；从同一已冻结脚本创建新 Edition 时，默认沿用原 settings snapshot/pool version，只有作者显式选择“使用新音色池重新选角”才解析新 pool，并在创建前展示受影响人物和句段。

`scene_scope` 不是自由字符串。分析器先根据章节结构、显式分隔符和段落边界生成 `narration_scenes`；无法确定场景时退回章节范围。匿名稳定键由标准化描述、作用域、首次出现局部锚点和显式别名共同生成，并保留生成算法版本。哈希碰撞、泛称冲突或跨章疑似复现必须进入人工合并/拆分流程，不能静默合并。

### 7.4 可配置规则

- 同场景是否禁止重复音色；
- 未配置正式人物是否自动继承；
- 匿名人物复用范围：句段、场景、章节、全书；
- 第一人称叙述和内心独白规则；
- 信件、短信、电话、广播和回忆的表达方式；
- 众人齐声采用代表声还是群体混合；
- 低置信度阈值；
- 是否允许自动推断年龄、性别和职业；
- 是否在匿名人物多次出现时提示建卡。

### 7.5 前置数据依赖

自动选角开工前必须先实现或明确降级：

- `character_aliases`：人物别名、规范化值、冲突状态和来源；
- `narration_scenes`：脚本内场景边界和结构来源；
- 匿名人物合并、拆分和作用域调整；
- 声音解析器的章节 > 分卷 > 作品优先级测试。

缺少别名或场景数据时允许降低自动识别率并要求人工复核，但不能伪造“当前场景人物”或跨章稳定身份。

## 8. 正文分析与朗读脚本

### 8.1 保存屏障

用户点击智能朗读时必须：

1. 等待当前自动保存完成；
2. 校验 `draft_version`；
3. 读取并确认 `content_hash`；
4. 查找该文档内容哈希完全相同的既有 revision，存在则直接复用；
5. 不存在时幂等创建隐藏的 `tts_snapshot` revision；
6. `tts_snapshot` 不移动 working copy 的 `base_revision_id`，不增加 `draft_version`，默认不出现在用户手工检查点历史中；
7. 对 `(document_id, content_hash, snapshot_purpose)` 建立唯一约束或等价幂等保证；
8. 将朗读脚本绑定精确 `revision_id` 和 `content_hash`；
9. 任何后续编辑都不能改变该脚本的来源文本。

不得直接复用当前 `create_checkpoint()` 的行为：它会无条件创建 `manual_checkpoint`、推进 revision number 并更新 working copy 基线，连续点击朗读会污染版本历史。

### 8.2 Markdown 与句段切分

解析器需要识别：

- 标题和正文；
- 段落与标点；
- `“”`、`「」`、`『』` 和英文引号；
- 冒号、破折号和嵌套引号；
- 对话提示语；
- 内心独白；
- 短信、信件、广播和电话；
- 场景分隔符与作者注释；
- 不朗读标记。

每个句段同时保存：

- Markdown 源位置；
- 前端使用的 UTF-16 起止偏移；
- 脚本版本内的段落序号、`source_block_key` 和段内句段序号；
- 原文；
- 实际朗读文本 `spoken_text`；
- 局部内容哈希；
- 前后必要上下文。

`source_block_key` 只标识同一不可变脚本版本中的来源块，由版本化解析器基于块类型、段落序号、局部哈希和锚点生成；它不能被当作跨 revision 永久 ID。前端从段落边栏触发跳播时，先定位当前可验证的来源块，再选择该块第一个可朗读 segment；从句段视图触发时直接使用命中的 `segment_id`。

章节标题、自动插入停顿等没有直接正文字符范围的合成项必须使用独立 `segment_kind`，其源偏移允许为空；不得伪造正文范围。

前后端必须冻结 UTF-16 偏移契约并覆盖 emoji、组合字符和特殊标点测试，避免浏览器选择范围与 Python code point 计数不一致。

### 8.3 规则优先

确定性规则先处理明确情形：

```text
林晚说道：“你终于来了。”       -> 林晚
“你终于来了。”林晚轻声说道。   -> 林晚
沈川皱眉。“我没有骗你。”       -> 沈川
“别动！”一个年轻女人喊道。     -> 匿名青年女性
```

规则至少使用：

- 人物姓名和别名；
- 说、问、喊、答、低语、暗道等提示动词；
- 前后提示语；
- 同段连续说话；
- 当前场景人物；
- 上一说话人和轮次；
- 第一人称与内心独白设置。

### 8.4 模型补充判断

作品级正文分析模式只能为：

```text
local_rules_only
  -> 规则无法确定时标记 unknown/低置信度并进入人工复核

cloud_assisted
  -> 用户明确授权后，仅把不确定句段、最小前后文和有限候选人物发送给受控聊天模型
```

`cloud_assisted` 输入包含当前句、必要前后文、候选人物与别名、有限角色属性、当前场景和前一说话人。禁止默认发送整章、完整人物库、参考录音或未参与判断的设定。授权记录必须包含作品、用途、模式版本、时间和撤销状态。

模型输出必须通过严格 JSON Schema，并且 `speaker_kind` 只能为：

```text
narrator
character
anonymous
group
unknown
```

当 `speaker_kind=character` 时，`character_id` 必须属于本次输入的允许集合。模型不能新增或修改正式人物。非法 ID、缺失证据或结构不合格的输出必须转为 `unknown`，不能猜测后写入权威数据。

长章节按场景/窗口处理，只对不确定句段调用模型，并在窗口边界保留重叠上下文。相邻窗口结果冲突时转入复核。每次调用保存 requested/actual provider、model、提示模板版本、输入哈希和结果哈希；当前项目实际模型校验规则继续生效，模型身份不匹配时结果作废。

### 8.5 情绪与表达方式

情绪和表达方式分开保存：

```text
emotion: neutral | happy | sad | angry | fearful | tense
delivery: normal | whisper | shout | inner_monologue
```

第一版只把它们用于脚本标记、人工复核、基础停顿和有限生成参数。不同情绪参考音频必须由作者试听确认；不自动为每个情绪重新创造人物音色。

### 8.6 置信度和人工优先

每个句段保存说话人置信度、情绪置信度、判断证据、规则/模型来源和人工覆盖状态。

模型自报的数值不是经过校准的真实概率。最终置信等级由可解释规则信号、候选冲突、模型一致性和固定标注集校准共同决定；在校准完成前只使用 `high | medium | low | unknown` 等级，不向用户展示伪精确百分比。

- 高置信度：默认通过；
- 中置信度：可见但不强制阻塞；
- 低置信度：必须复核；
- `unknown`：不得静默生成正式成品；
- 作者修改后设为 durable override；同一脚本版本内后续自动分析不得覆盖，除非作者显式重置；
- 新正文版本只在“原文局部哈希、唯一前后锚点和说话人目标”全部匹配时继承人工覆盖；歧义、改写或多处重复文本必须重新复核。

## 9. 朗读脚本复核

```text
[旁白][平静] 夜色笼罩着长安城。
[林晚][冷淡] “你终于来了。”
[沈川][压抑] “我一直都在。”
[未知角色][低置信度] “你们两个都被骗了。”
```

作者可以：

- 修改正式人物；
- 设为旁白、匿名、群体或未知；
- 新建匿名说话人；
- 把匿名说话人升级为正式人物候选；
- 修改情绪和表达方式；
- 调整场景边界和匿名人物作用域；
- 修改 `spoken_text` 而不修改正文；
- 调整前后停顿；
- 合并或拆分句段；
- 单句试听；
- 只重分析当前句；
- 批量修改同一匿名说话人；
- 在逐章复核或阻塞处理路径中确认整章脚本。

脚本只有进入 `approved`（已冻结）状态后才能进入正式朗读版本合成。允许快速试听单句，但试听资产必须标为临时派生数据。

冻结存在两条合法路径：

1. 默认 `blockers_only` 且 `blocker_count = 0` 时，领域服务记录 `auto_no_blockers` 并自动冻结；
2. 存在阻塞或启用 `always_review` 时，作者处理/检查后记录 `manual_after_review` 并冻结。

阻断代码只能来自 `narration-review-taxonomy/1`：说话人低置信/未知、别名冲突、匿名身份冲突、casting target 未解析、音色缺失/版本不可用和硬发音冲突分别使用冻结的 `B_*` 代码。历史 `B_VOICE_RIGHTS_UNAVAILABLE` 只适用于未来重新立项的用户上传、生成、reference clone 或商业／对外声音来源；当前 6 个 `official_preset` 只做固定来源、revision、preset ID、manifest、fingerprint 和 hash 的技术溯源校验，商业状态不得进入本地可用性或 T4 门禁。中置信使用 `W_SPEAKER_MEDIUM_CONFIDENCE`，只作为 warning。分析器失败、实际模型不匹配、输出 schema 非法、scope/fingerprint 变化使用 `F_*` workflow failure，不能降级成 warning。完整代码、severity 和版本升级规则以 [T0-H gate decisions 第 5 节](证据/MOSS-TTS-Nano施工/T0-H/gate-decisions.md#5-裁决-5narration-review-taxonomy1) 为冻结输入，但与现行缩减范围冲突的权利审批语义不再执行。

冻结后的 `narration_script_version` 不可变。任何修改都必须创建新的脚本版本；旧朗读版本继续引用旧脚本版本。这样才能复现历史配音并准确计算失效范围。

## 10. 音频生成、时间轴和播放

### 10.1 合成单元

- 首版一个显示句段对应一个独立最终 `segment_render`；
- 对话通常以一个完整引号段为显示句段，旁白按句子或短段落切分；
- 不跨显示句段合并模型请求，不依赖模型返回内部时间戳；
- 超过 Nano 长度预算的单个显示句段可在 Runtime 内拆成多个 `render_part`，合成后拼为一个句段资产，前端仍只做句段级高亮；
- 首版禁用跨句 rolling prompt。每个句段只依赖自身文本、锁定音色和冻结参数；
- 只有独立基准证明质量收益大于缓存连锁失效和重试复杂度后，后续版本才能增加上下文模式。

这一约束是句段同步、局部重生成和崩溃恢复的共同基础，不能为了少量吞吐优化提前取消。

### 10.2 缓存键

句段缓存键至少包含：

```text
canonical_spoken_text_digest_key_id
+ canonical_spoken_text_hmac_sha256
+ pronunciation_profile_fingerprint
+ voice_profile_version_fingerprint
+ reference_audio_hash
+ tts_model_revision
+ tokenizer_revision
+ normalizer_version
+ language
+ synthesis_style_and_parameters
+ deterministic_seed
+ postprocess_version_and_master_format
```

指纹由版本化 canonical JSON 计算，禁止依赖对象键顺序或浮点字符串偶然格式。`spoken_text` 必须是完成发音词典、数字和停顿前文本规范化后的最终模型输入；发音表变化即使最终文本偶然相同，也由 `pronunciation_profile_fingerprint` 明确记录来源。

播放倍速和播放器音量不进入 render 缓存键，因为它们由播放层实时处理。会改变发声结果的风格、情绪变体或速度参数只有在 Nano/VoiceGenerator 阶段 0 明确支持并通过验收后，才进入合成参数。

朗读版本 Manifest 指纹由有序句段 render 哈希、句间停顿、播放格式和 Manifest schema 版本共同决定。现行产品只做网页分段 Manifest 播放，不生成整章或全书连续文件，也不存在“整章播放文件缓存键”。

T4 主集成已把上述语义收口为隐私安全的 `narration-render-input/3`：私人 `spoken_text` 不再以裸 SHA-256 进入新 render canonical input，而是使用服务端版本化 keyring 产生带用途域分离的 `canonical_spoken_text_digest_key_id + canonical_spoken_text_hmac_sha256`。`segment_id`、来源定位用 `local_hash`、`pause_before_ms` 和 `pause_after_ms` 不进入音频 render fingerprint；它们仍在脚本／Edition／Manifest 层校验、保存并参与时间线或来源审计。这样新 ScriptVersion 产生新句段 ID、或作者只调整句间停顿时，仍可在同一本地 owner/workspace/novel 且同一摘要密钥版本内复用完全相同的声音资产。

施工前候选 `narration-render-input/1` 与 `narration-render-input/2` 仅为历史只读兼容：v1 曾把来源和时间线字段混入音频缓存键，v2 虽修正缓存语义却仍保存私人短文本的裸摘要；两者均不得由新 Edition 生成、不得改写成 v3，也不得跨 schema 伪装命中。所有新 Edition 只生成 v3，并在行内冻结 `render_digest_key_id`；密钥轮换后，既有 Edition 继续依赖其历史 key 验证，新缓存 miss 必须由使用当前 active key 的新 Edition 产生。该实现已通过隔离的跨请求缓存复用、HMAC/keyring、轮换、缺失历史 key fail-closed 和“全部 ready cache、零新 job、唯一 Manifest 即时收口”自动化；应用入口与 live PostgreSQL 仍由 T4-GATE 验证，不能据此提前宣布产品可用。

### 10.3 生成顺序

1. 校验脚本已经按复核策略自动或人工冻结；
2. 冻结朗读设置快照、发音表版本、模型 fingerprint 和所有音色版本；
3. 创建幂等 `narration_edition`；
4. 为每个句段解析最终音色版本并保存解析证据；
5. 计算句段 render fingerprint；
6. 复用命中缓存，并立即把已命中句段写入 Edition Manifest；
7. 缺失句段进入共享持久任务队列；
8. 按“用户明确选择的播放窗口 > 交互试听 > 当前章节开头 > 当前章节剩余”排序；同一资源类别仍应用公平老化，避免连续跳播永久饿死后台任务；批量与导出不在当前调度范围；
9. M4 初始默认单并发运行 Nano；
10. 校验输出可解码、非空、非异常长度；
11. 检查严重静音、削波、峰值、响度和时长异常；
12. 保存无损/可重建 master 和浏览器播放资产；
13. 写入真实句段时长、停顿和 render 状态；
14. 每完成一个可连续播放的章首前缀或用户请求窗口就更新 Manifest revision；
15. 任一合法播放起点的连续窗口达到最小播放门槛时将 Edition 标记 `partial_ready`；默认从章首播放仍要求章首前缀达到门槛；
16. 所有必需句段完成并校验后标记 Edition `ready`；
17. `T6-D_CANCELLED`：不生成章节或全书连续文件；网页分段 Manifest 即为现行交付形态。

最小播放门槛的初始候选为“从本次合法播放起点起连续至少 3 个句段且累计至少 8 秒，或到章末的剩余内容已经全部完成”；最终值由阶段 0 接缝和生成速度基准冻结，并作为 `initial_buffer_policy_version` 写入 Edition/Manifest，不能由前端临时猜测。用户没有明确选择中间起点时，合法起点只能是章首或已保存进度；系统不得为了更快出声自动跳过前面的 pending/failed 句段。

### 10.4 长篇一致性

采用固定参考音频、不可变音色版本、固定模型 revision、稳定种子和稳定采样参数。核心首版明确使用 `independent_segment` 上下文模式。

以后若增加 rolling prompt，必须创建新的上下文模式和缓存 schema，把前序音频/文本尾部哈希加入指纹，并定义从修改点向后的连锁失效；不得在同一缓存命名空间内静默开启。

### 10.5 播放清单

```json
{
  "schema_version": "narration-manifest/2.0",
  "edition_id": "edition-123",
  "chapter_id": "chapter-123",
  "source_revision_id": "revision-123",
  "source_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
  "buffer_policy": {
    "version": "initial-buffer/v1-3-segments-8000ms",
    "minimum_segments": 3,
    "minimum_duration_ms": 8000,
    "target_segments": 5,
    "chapter_end_exception": true
  },
  "manifest_revision": 1,
  "etag": "\"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd\"",
  "generated_at": "2026-08-26T04:00:00+08:00",
  "status": "partial_ready",
  "ready_prefix_count": 3,
  "default_start_ready": true,
  "last_playable_start_ordinal": 0,
  "ready_ranges": [
    {
      "start_ordinal": 0,
      "end_ordinal_exclusive": 3,
      "segment_count": 3,
      "duration_ms": 8980,
      "last_playable_start_ordinal": 0
    }
  ],
  "segments": [
    {
      "segment_id": "segment-1",
      "ordinal": 0,
      "paragraph_ordinal": 0,
      "source_block_key": "block-1",
      "source_start_utf16": 0,
      "source_end_utf16": 9,
      "gap_after_ms": 260,
      "render_status": "ready",
      "audio": {
        "url": "/api/ai-novel-world-2026/media-assets/asset-1/content",
        "actual_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "duration_ms": 2800,
        "sample_rate": 48000,
        "channels": 2,
        "etag": "\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\""
      },
      "failure": null
    },
    {
      "segment_id": "segment-2",
      "ordinal": 1,
      "paragraph_ordinal": 1,
      "source_block_key": "block-2",
      "source_start_utf16": 0,
      "source_end_utf16": 11,
      "gap_after_ms": 220,
      "render_status": "ready",
      "audio": {
        "url": "/api/ai-novel-world-2026/media-assets/asset-2/content",
        "actual_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "duration_ms": 3100,
        "sample_rate": 48000,
        "channels": 2,
        "etag": "\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\""
      },
      "failure": null
    },
    {
      "segment_id": "segment-3",
      "ordinal": 2,
      "paragraph_ordinal": 1,
      "source_block_key": "block-2",
      "source_start_utf16": 11,
      "source_end_utf16": 22,
      "gap_after_ms": 0,
      "render_status": "ready",
      "audio": {
        "url": "/api/ai-novel-world-2026/media-assets/asset-3/content",
        "actual_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "duration_ms": 2600,
        "sample_rate": 48000,
        "channels": 2,
        "etag": "\"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\""
      },
      "failure": null
    },
    {
      "segment_id": "segment-4",
      "ordinal": 3,
      "paragraph_ordinal": 2,
      "source_block_key": "block-3",
      "source_start_utf16": 0,
      "source_end_utf16": 14,
      "gap_after_ms": 180,
      "render_status": "pending",
      "audio": null,
      "failure": null
    }
  ]
}
```

Manifest 是分段播放清单，不要求先存在整章音频。它列出全部 Edition segment 的有序状态，并分别保存：

- 从章首形成的 `ready_prefix_count` 和服务端判定的 `default_start_ready`，用于默认开始播放；
- 从 segment 状态推导、且至少一个起点达到门槛的最大连续 `ready_ranges`（统一使用 0-based ordinal 与半开 `end_ordinal_exclusive`），以及按服务端缓冲策略计算的 `last_playable_start_ordinal`；
- pending/failed 句段和空缺位置，前端不能把它们隐藏成连续时间轴。

`ready_ranges.duration_ms` 包含窗口内音频时长和内部句间 gap，不包含 range 末段之后的 gap。服务端回传这些字段，前端仍必须按冻结 schema 对 `segments + buffer_policy` 做一致性校验；它不是第二套可漂移状态。某个起点只有在不晚于该 range 的 `last_playable_start_ordinal` 时才可立即开始；更靠后的起点仍需 `prepare-range` 补足后续缓冲。尚未达到门槛的零散 ready segment 只通过 segment 状态暴露，前端不能自行拼出绕过策略的窗口。Edition 完整 `ready` 后，任一可朗读 segment 都是合法起点。

公共 Manifest 不暴露句段原文、短文本 SHA/HMAC、人物绑定或内部路径；人物/旁白解析证据属于受权限保护的脚本/Edition 领域接口。媒体只通过 PawApp 同源受控 URL 暴露，URL 不含 token/query/fragment，`audio.etag` 必须由实际播放字节 SHA-256 形成强 ETag。唯一 wire shape 以 [T0-G JSON Schema](证据/MOSS-TTS-Nano施工/T0-G/manifest-v2.schema.json) 和正反 fixture 为准。

用户显式从第 N 段开始时，N 之前的缺失不构成跳过；播放器只能消费从 N 开始的连续 ready window，并在遇到下一个 pending/failed 句段时停下或等待。系统绝不能在同一次播放中静默越过窗口内部缺口。目标窗口未 ready 时，`prepare-range` 幂等提升 N 及其后续缓冲句段的任务优先级，不新建重复 render。

前端播放器通过统一 `SegmentPlaybackQueue` 预取后续 3–5 个句段。优先验证 Web Audio 调度以减少分段间隙；若宿主环境不兼容，则回退双 `<audio>` 预加载，但必须记录可听间隙并进入阶段 0/4 验收。播放会话固定同一 `edition_id`；它可在句段边界通过 ETag/CAS 获取同一 Edition 的较新 Manifest revision，以延长 ready window，但不能在播放中途无提示切换到另一 Edition、另一正文哈希或另一整章文件。已经排入本地播放队列的旧 Manifest revision 资产在消费完成前保持可读。

### 10.6 编辑器跟随

播放器以当前 `segment_id` 为句段级同步权威；完整 Edition 准备后可根据累计时长支持全章拖动。播放倍速由播放层应用，不能修改原始句段时间数据。

前端通过稳定的 `NarrationEditorBridge` 对接实际编辑器，最少提供：

- 按 `segment_id/source_block_key/source range` 安装和移除 decoration；
- 从段落或 UTF-16 光标位置解析合法播放起点；
- 通过 gutter、上下文菜单和键盘命令触发 `seekToSegment`；
- 接收编辑 transaction，映射未相交范围并使相交句段失效；
- 高亮当前句段、滚动到句段和暂停/恢复自动跟随；
- 正确处理中文输入法 composition、emoji、组合字符、撤销/重做和大文本虚拟化。

默认候选 CodeMirror 6 与备用 Monaco 都只能使用公开 transaction/decoration/range API，不访问内部节点。原生 `textarea` 降级模式不做透明可编辑叠层：正文 hash 一致时可切换只读句段层完成高亮和点击跳播；用户返回编辑时音频不暂停，但高亮退到播放器字幕/旧稿抽屉，使用“从光标所在段朗读”代替段落 gutter，直到恢复内容一致或启用合格编辑器。

活跃的可装饰编辑器允许把未相交的 decoration 随 transaction 移动，但移动后还必须复核局部文本哈希和锚点；这一映射只是当前前端会话的临时派生状态。任一变化与句段范围相交时，该句段立即失效；段落拆分/合并、引号或边界标点变化还要保守失效相邻来源块，不能仅因最终偏移仍落在相似文字上就继续高亮。

### 10.7 正文变化

正文 `content_hash` 与 manifest 不一致时：

- 计算派生兼容状态 `working_copy_diverged`，不得因每次按键改写 Edition 或创建持久任务；
- 活跃编辑会话中，只允许继续显示经 transaction 映射且未与变更相交的句段；相交句段改在播放器字幕中显示 Edition 旧文本；
- 页面重载、映射链丢失或锚点无法唯一验证后，立即停止把旧时间轴映射到当前正文，只在不可变旧版本朗读视图中高亮；
- 旧 approved 脚本和 Edition 都保持不可变历史状态并可继续播放；新 revision/脚本/Edition 被选为当前版本时，只更新 `document_narration_state` 的 CAS 指针，查询时派生 `superseded` 或 `working_copy_diverged`，不得回写旧脚本为 `stale`；
- “更新朗读”必须完成第 8.1 节保存屏障，并对变化句段及必要上下文重新分析；不能在工作稿尚未稳定时按键级触发；
- 新脚本按复核策略自动或人工冻结后创建新 Edition；相同文本、音色和模型输入的句段仍可命中缓存；
- 新 Edition 切换必须由用户明确确认，并从可唯一对应的句段或章首开始；不能把旧 Edition 的句内毫秒偏移直接迁移到新 Edition。

## 11. 数据模型

### 11.1 关系总览

```text
DocumentRevision
  ├─ NarrationRequest / NarrationRequestSource
  └─ NarrationScript
       └─ NarrationScriptVersion
            ├─ NarrationScriptIssue
            ├─ NarrationScene
            └─ NarrationSegment
                 └─ NarrationEditionSegment ──► SegmentRender ──► MediaAsset

NarrationRequest + approved NarrationScriptVersion
  └─ NarrationEdition ──► NarrationManifest / NarrationEditionState

NarrationScriptVersion
  + NarrationSettingsSnapshot
  + VoiceProfileVersions
  + TTS/Normalizer fingerprints

VoiceProfileVersion ──► VoiceRightsRecord ──► VoiceRightsEvent
BackgroundJob ──► BackgroundJobAttempt ──► ModelRunRecord
VoiceDeletionRequest ──► AssetTombstone
```

权威层级：正文 revision 是文本权威；已冻结的 `approved` 脚本版本是说话人/朗读文本权威；Edition 是一次配音制作配置权威；render 和媒体均为可校验派生物。

### 11.2 `media_assets` 扩展

在现有字段上增加：

- 非空本地 `owner_id/workspace_id` scope，并把 `novel_id` 调整为可空；个人复用音色资产使用 owner/workspace scope，作品音频同时校验 owner/workspace/novel scope；播放 profile 只是进度维度，不能替代安全 scope；
- `asset_class`: `source | voice_reference | preview | segment_master | segment_playback`；迁移历史若已存在 `export` 枚举，只作为 `legacy/reserved compatibility only` 保留，不得创建新的 export 资产；
- `mime_type`、`byte_size`、`duration_ms`、`sample_rate`、`channels`；
- `storage_backend`、`state`、`retention_policy`；
- `verified_at`、`checksum_algorithm`、`last_accessed_at`；
- 可选 `expires_at`、`deleted_at` 和结构化校验结果。

迁移必须为现有资产回填固定本地 owner/workspace，并用非空列、复合 FK/CHECK 和服务层 resolver 保证 scope；任何带 `novel_id` 的访问还要验证小说属于同一 owner/workspace。不能为了实现跨书声音库继续强迫私人参考音频伪装成某本小说的资产。

保留策略：上传原件、标准化参考音频和锁定音色不可被普通“清缓存”删除；试听、segment master 和播放副本属于可重建派生物，按引用可达性和配额清理。历史已有 export 行仅按兼容数据处理，不得产生新 export。物理删除前必须检查人物绑定、脚本版本、Edition 和历史 render 引用。

### 11.3 `voice_profiles` 与 `voice_profile_versions`

`voice_profiles` 是稳定音色身份，保存 owner/workspace 与可空 novel scope、名称、当前版本、状态、CAS 版本和归档时间；跨作品私人音色只能在同一 owner/workspace 内复用。

`voice_profile_versions` 是不可变版本，至少保存：

- `source_type`: `preset | uploaded | generated`；
- provider/model/revision、预设键、参考和试听资产；
- 文字描述、试听文本、语言、标签和规范化参数；
- 随机种子、fingerprint、来源和授权确认；
- 创建时间、质量审核状态和锁定人/时间。

被脚本、Edition 或 render 引用的版本不可原地修改。

### 11.4 `character_aliases` 与 `character_voice_bindings`

`character_aliases` 保存 `novel_id`、`character_id`、原别名、规范化别名、来源、冲突状态和生命周期。相同规范化别名指向多个活跃人物时必须标记冲突，不能由规则静默选择。

`character_voice_bindings` 保存：

- `character_id` 唯一；
- profile 和可选锁定 version；
- 专属/继承策略、默认语言及已验证的有限合成参数；
- CAS 版本和时间戳。

角色归档不级联删除历史音色或朗读。

### 11.5 `novel_narration_settings`、版本与范围覆盖

`novel_narration_settings` 指向当前可编辑配置；每次用于正式合成时冻结 `narration_settings_snapshot`，保存：

- 默认旁白 profile/version；
- 标题、作者注、第一人称和内心独白规则；
- 正文分析模式与云端授权引用；
- 默认语言、停顿、播放格式、低置信度策略和 `script_review_policy`；
- 默认通用池、选角规则和发音表 fingerprint；
- 阻断分类/策略版本与 schema/version/fingerprint。

`narration_scope_overrides` 使用 `scope_kind = volume | chapter` 与 `scope_id`，保存旁白和有限规则覆盖。解析顺序固定为章节 > 分卷 > 作品，并用数据库约束保证 scope 属于同一小说。

`narration_cloud_consents` 保存 `novel_id`、用途、告知文本版本、允许的数据范围、可选 provider/model scope、确认时间和撤销时间。授权记录不可被普通设置覆盖；撤销后所有新 job 必须在执行前再次校验，排队时已授权不代表真正调用时仍获授权。

播放倍速和播放器音量属于个人播放偏好，不写入合成设置快照。

### 11.6 `generic_voice_pools` 与 `generic_voice_slots`

Pool 保存作品、版本、年龄/性别/用途分类和状态；slot 保存排序、不可变音色版本、标签、启用状态和优先级。历史脚本/Edition 引用具体 slot 与 voice version，不能只保存“青年女性”字符串。

### 11.7 `voice_casting_rules` 与 `narration_scenes`

`voice_casting_rules` 保存作品范围、优先级、条件 schema、目标 pool/slot/动作、同场景去重、匿名复用、回退策略、来源、版本和归档状态。

`narration_scenes` 属于脚本版本，保存场景序号、源范围、边界来源、场景局部哈希和可选人工标题。它是同场景去重和匿名作用域的明确数据来源。

### 11.8 `anonymous_speakers` 与绑定

- 作品、稳定键、稳定键算法版本、显示名称和描述；
- 默认作用域 `scene | chapter | novel` 及 scope ID；
- 首次/最近来源 revision、脚本版本和句段；
- 推断年龄、性别、职业、证据和置信等级；
- slot、voice version、人工覆盖和生命周期；
- 可选 `promoted_character_id`、合并来源和拆分记录。

### 11.9 `pronunciation_profiles` 与 `pronunciation_entries`

正式合成引用不可变 `pronunciation_profile` fingerprint。Entry 保存原文本、最终朗读替换或经验证的音素表示、语言、作用域、优先级、大小写策略、来源和版本。

匹配顺序固定为章节 > 分卷 > 作品、人工条目 > 系统规范化、长匹配 > 短匹配；同优先级冲突必须提示，首版不开放任意正则替换。转换只生成 `spoken_text`，正文和原始 segment 文本保持不变。

Nano 不支持的标记语法不得直接送入模型；阶段 0 先验证中文多音字、数字和中英混读的可用控制方式。

### 11.10 `narration_scripts` 与 `narration_script_versions`

`narration_scripts` 是 document/revision 下的稳定分析身份，绑定精确 `revision_id` 和 `content_hash`。

`narration_script_versions` 保存分析器、规则、分析/选角设置 fingerprint、提示模板、requested/actual model fingerprint、状态、warnings/blockers 分类统计、父版本和唯一幂等键。冻结审计至少保存 `approval_kind`、生效的 `script_review_policy`、阻断分类版本、actor type/ID 和时间。草稿通过 CAS 修改；一旦进入 `approved` 即不可变且保持终态。working copy 按键级变化只产生派生的 `working_copy_diverged`，新正文快照/脚本/Edition 被设为当前时由指针比较派生 `superseded`；两者都不持续写脚本状态，更不得把旧 approved 行更新成 `stale`。

数据库/服务层约束必须保证 `auto_no_blockers` 只能在分析成功、`blocker_count = 0`、所有 casting target 与音色都可解析、生效策略为 `blockers_only` 且存在用户显式生成意图时写入；`manual_after_review` 必须有 owner actor 和复核时间。聊天模型输出本身不能写审批字段。

### 11.11 `narration_segments`

- 脚本版本、场景、稳定序号和 `segment_kind`；
- 脚本版本内的 `paragraph_ordinal`、`source_block_key`、段内序号；
- 可空 Markdown/UTF-16 起止位置；
- 原文、最终 `spoken_text`、局部哈希和前后锚点；
- `speaker_kind`、character/anonymous ID；
- 情绪、表达方式、前后停顿；
- 规则/模型来源、证据和置信等级；
- 候选及最终 casting target（character binding、anonymous binding、slot 或 profile 身份）；脚本不冻结最终 voice version；
- `manual_override`、继承来源和版本。

### 11.12 `narration_editions` 与 `narration_edition_segments`

`narration_editions` 是一次可复现制作版本，绑定：

- 已冻结的 `approved` script version；
- settings snapshot、pronunciation profile；
- TTS/Tokenizer/Normalizer/postprocess fingerprints；
- 上下文模式，首版固定 `independent_segment`；
- 初始缓冲策略版本；
- 状态、当前 Manifest revision、创建人和时间；
- 由上述输入计算的唯一 edition fingerprint。

`narration_edition_segments` 保存 Edition 内句段顺序、按当次设置解析出的最终 slot/profile/voice version、解析证据、render fingerprint、render 状态、gap 和失败信息。同一脚本版本可拥有多个 Edition。

### 11.13 `narration_segment_renders`

- 唯一 render fingerprint；
- canonical 输入、voice/reference、模型和后处理 fingerprints；
- master/playback `media_asset_id`、时长和音频校验信息；
- 状态、来源 job 和时间戳。

Render 不属于某一个脚本；满足相同隐私 scope 和完整 fingerprint 时可复用。首版缓存限定在同一本地 owner/workspace，避免跨用户复用私人正文和私人音色。

### 11.14 `narration_manifests` 与播放进度

Manifest 绑定 Edition，保存 schema version、Manifest revision、连续 ready 前缀、连续 ready ranges、有序 segment/render 哈希、每段 render 状态、总时长、状态和结构化 JSON。更新使用 CAS；Manifest 与 Edition 历史只追加，不因当前指针或播放会话结束而删除。`ready_ranges` 是 render 状态的可校验派生索引，不另建会与 segment 真相漂移的第二套状态表。

T1 采用保守保留基线：全部历史 Edition/Manifest revision 无限期保留，任一历史 Manifest、Edition、locked voice、voice reference、源资产或未过期运行租约可达的资产都是 GC root；迁移历史中既有 export 记录仅作为 legacy GC root 兼容，不得继续创建。T1 不因配额删除历史朗读。普通 GC 只处理无结构化 FK 引用且无活跃 job 的可重建派生物：staging/orphan 满 24 小时后方可成为候选，ready 派生资产必须先写 generation mark，至少等待 7×24 小时，再在同一 scope 一致性快照中复核引用与 generation，仍不可达才物理删除并写 tombstone。source upload、normalized reference 与 locked voice source 永不进入普通 GC。T6 若要引入历史 Edition 配额或期限，必须以新的用户可见策略、影响预览、迁移和 ADR 重开，不能静默缩短本基线。

`narration_edition_state` 每个 Edition 唯一一行，只用 CAS 保存 `current_manifest_id/current_manifest_revision/version`；Manifest 内容与 revision 追加不可变，首个 revision 为 1。同 revision/不同强 ETag 必须拒绝为 `revision_collision`，不能覆盖旧行。

`document_narration_state` 按 `(owner_id, workspace_id, document_id)` 唯一保存当前 script/Edition 指针、CAS 版本和切换 actor/time。working copy 是否匹配由查询时比较内容哈希得出，不把每次编辑写进该表；只有用户明确选择新 Edition 时才更新指针。Edition 的生成状态与“是否当前”正交，切换指针不改写旧 Edition 状态；个人播放进度仍可按 profile 分开保存。

`narration_playback_progress` 保存本地 owner/workspace/profile、Edition、Manifest revision、最后 segment、句内偏移、最近一次合法起点、倍速和更新时间。刷新同一 Edition 的 Manifest revision 可以继续使用 segment 进度；正文或 Edition 更新后保留历史进度，但不自动迁移到不同内容哈希。

### 11.15 `narration_requests` 与 `narration_request_sources`

`narration_requests` 是分析、章节生成、更新朗读和批量生成的持久编排权威，至少保存 owner/workspace/novel/document scope、`intent = analyze_only | create | update | batch`、canonical request hash、scope 内幂等键、source/settings fingerprint、复核策略、状态/CAS、显式生成 actor/time、取消/失败和结果引用。`create|update|batch` 必须有显式生成意图；`analyze_only` 禁止进入 render 状态。

章节 `create|update` 直接绑定不可变 revision/content hash；`batch` 是退出当前 ready set 的历史兼容 intent，若未来重开必须通过 `narration_request_sources` 逐项冻结同 scope 的 document/revision/hash。`allows_edition/allows_render` 由 intent 生成并受 CHECK 约束，Edition 与 segment render job 通过复合 FK 反向引用 true guard；历史 export FK／表只作 legacy compatibility，不得创建新 export job/asset/API/UI。生成媒体只能由合法 render 的结构化资产 FK 可达。公共 HTTP 不提供 direct Edition 创建端点，恢复命令也调用同一领域服务。精确字段、状态机和四层负向约束以 [T0-H gate decisions 第 4 节](证据/MOSS-TTS-Nano施工/T0-H/gate-decisions.md#4-裁决-4narration_requests状态与-edition-反向约束) 为准。

### 11.16 `background_jobs` 与 `model_run_records`

不再新增独立 `narration_jobs` 调度体系。共享 `background_jobs` 至少保存：

- `job_kind`: 现行只消费 `narration.analyze | narration.voice_preview | narration.segment_render`；迁移历史若保留 `narration.export`，其状态为 `legacy/reserved compatibility only`，调度器不得创建或领取新的 export job；
- 非空本地 `owner_id/workspace_id`、可选 `novel_id`、`scope_kind`、`scope_id`、可选 `source_revision_id`；
- 输入哈希、唯一幂等键、基础优先级、可过期交互优先级提升和资源类别；
- `queued | running | retry_wait | succeeded | failed | dead_letter | cancel_requested | cancelled`；
- `max_attempts`、`attempt_count`、`next_retry_at`、取消字段、进度、安全错误码和时间戳；逻辑 job 本身不承载一个可被覆盖的当前 attempt 日志。

`background_job_attempts` 是追加式审计：每个 attempt 保存 `retry_kind=initial|automatic|manual`、manual actor/reason、`lease_owner/lease_token/lease_generation/lease_until/heartbeat_at`、开始/完成时间、错误分类/码和 actual result digest，唯一 `(job_id, attempt_number)`。领取在 `FOR UPDATE SKIP LOCKED` 短事务中创建 attempt；heartbeat、取消确认、媒体发布和完成都必须同时匹配 job、attempt、lease token 和 generation，旧租约的迟到结果不得发布。

`background_resource_locks` 对每个资源 key 只保存一个当前 token/generation/lease；重模型任务必须同时持有 job attempt lease 与 resource lease。它不是第二套 job 状态机，过期或 token/generation 不匹配时一律不能发布结果。

`model_run_records` 逐次引用精确 attempt，记录 requested/actual provider、model/revision、参数 fingerprint、输入/输出摘要、耗时、供应商请求 ID 和失败信息。朗读 Edition 的 `partial_ready/ready` 是领域状态，不是 job 状态。完整字段与转移以 [T0-H gate decisions 第 6 节](证据/MOSS-TTS-Nano施工/T0-H/gate-decisions.md#6-裁决-6job-fencingattempt-与-manual-retry) 为冻结输入。

领取必须使用 PostgreSQL 原子锁/租约；前端 PawTask/SSE 只展示进度，不是持久权威。共享执行器可被后续 Embedding、情报派生和媒体任务复用；现有专用生成 job 的迁移另行评审，不在朗读阶段偷偷重写。

优先级调度必须带等待时间老化和资源类别配额，避免持续单句试听永久饿死全书任务。Nano、VoiceGenerator、CPU 转码分别声明资源类别；同一模型重任务默认单并发，轻量校验/转码可在阶段 0 基准后独立限流。

`prepare-range` 不创建第二份 render job；它按 render fingerprint 幂等复用现有任务，只更新尚未运行任务的短期交互优先级。用户连续选择多个位置时，最后一次请求获得最高优先级，旧请求自然降级；若底层 Nano 不支持安全抢占，当前正在合成的单句完成后再调度新窗口，不能粗暴终止并留下半写资产。

取消是协作式请求：执行器在调用前、分段间和写入前检查 `cancel_requested_at`。若底层模型不能立即中断，允许本次计算结束，但取消后的结果不得发布到 Edition；只有通过完整 fingerprint 校验且仍有其他有效引用时才可作为缓存保留。

### 11.17 `voice_rights_records` 与 `voice_rights_events`（历史兼容／非当前审批流程）

这两张表保留为已有 schema／历史数据兼容，当前不建设商业授权、再分发、subject consent 或 `review_blocked` 审批工作流。对 6 个官方预设，仅保存必要的官方来源、revision、preset ID、manifest、模型 fingerprint 和 hash；商业／再分发状态可记为未评估，但不得阻断个人本地展示、试听、绑定、合成或播放。若未来重新立项用户上传、生成或 reference clone 来源，再单独裁决相应删除、撤销和使用策略，不从本历史表自动放行。

### 11.18 私密 digest 与 versioned HMAC keyring

私人短台词、`spoken_text` 和候选描述用于日志、诊断、去重或模型审计时只保存 `digest_key_id + HMAC-SHA256 digest`，不保存可字典猜测的裸 SHA-256。32 字节以上随机 keyring 位于受控 secret volume，仓库、`.env`、数据库、日志、Sidecar 镜像和浏览器都不得含密钥；环境变量只可指向 keyring 文件。轮换时新写入使用 active key，旧 key 只读保留到相关保留期结束；keyring 丢失必须 fail-closed，数据库与 secret volume 必须成对备份/恢复。DocumentRevision CAS 与媒体字节完整性仍使用服务端 SHA-256，不与私人短文本 digest 混淆。

### 11.19 `voice_deletion_requests` 与 `asset_tombstones`

普通缓存清理、仅删除上传原件和彻底删除私人音色是三个不同动作。`true_delete_private_voice` 必须先冻结影响快照、停止新绑定/生成/播放租约并二次确认，再删除 live 音频与派生资产；正文、revision、脚本/Edition/Manifest 审计行不级联删除，受影响历史 Edition 进入 `unavailable_private_voice_deleted`。`voice_deletion_requests` 使用 `requested -> live_deleting -> live_deleted_backup_pending -> completed|failed`，`asset_tombstones` 只留不可复原的最小审计。受管备份尚未核实清除/到期时不得声称“所有副本已永久删除”。

## 12. 状态机

### 12.1 音色

```text
draft
  -> generating
  -> preview_ready
  -> locked
  -> retired

generating -> failed -> generating
```

### 12.2 朗读脚本

```text
analyzing
  ├─ analyze_only -> analyzed（只报告，不冻结/不生成）
  ├─ blockers_only + 0 blockers -> approved（auto_no_blockers）
  ├─ blockers > 0 -> review_required
  └─ always_review -> review_required

analyzed + 显式生成意图 + 正文/设置 fingerprint 仍一致
  -> 按当前策略进入 approved 或 review_required

review_required + blockers 已清零 + 作者确认
  -> approved（manual_after_review）

新正文快照/脚本被设为当前 -> approved 行不变；查询派生 superseded
分析失败 -> failed
approved 后修改 -> 新建 script version -> review_required
```

脚本状态只表达分析、复核与冻结，不表达音频合成。`analyzed` 只是扫描候选，不能创建正式 Edition；`approved` 表示脚本满足进入正式合成的不可变门槛，不等同于每次都由作者逐句人工背书。任何自动转移都由确定性领域校验执行，不能由模型自由判断。

working copy 与当前 Edition 的关系是查询时派生的兼容状态，不进入脚本状态机：

```text
content_match
  -> working_copy_diverged
  -> update_requested
  -> new_edition_available

new_edition_available -> user_switched
```

`working_copy_diverged` 不写入不可变 Edition，也不按键创建后台任务；它由 working copy `content_hash` 与 Edition 来源哈希比较得出。

### 12.3 朗读版本 Edition

```text
queued
  -> rendering
  -> partial_ready
  -> ready

rendering/partial_ready -> failed -> rendering（重试）
```

旧 Edition 不因正文、音色或当前指针更新被改写；working copy 修改也不会改变其 `partial_ready/ready` 状态。当前 Edition 由 `document_narration_state` 表达，历史 Edition 始终可以按权限和保留策略回放。

### 12.4 后台任务

```text
queued
  -> running
  -> succeeded

queued -> cancelled
running -> retry_wait | failed | dead_letter | cancel_requested | succeeded
retry_wait -> queued（自动重试，新 attempt）
cancel_requested -> cancelled
failed | dead_letter -> queued（仅显式人工重试，新 attempt）
进程失联 -> lease 过期 -> 旧 attempt fencing -> 新 attempt 重新领取
```

每一次自动/人工重试都追加新的 `background_job_attempts`，不得覆盖旧 attempt 或修改 canonical input；达到自动上限后只有带 actor/reason 的 manual retry 能重新排队。资源任务还必须持有独立的 `background_resource_locks` token/generation，不能只凭 job state 发布媒体。

## 13. API 草案

所有修改接口使用 `expected_version` 或幂等键；任务创建支持 `Idempotency-Key`；进度优先使用 SSE，断线后可用 GET 恢复。

T2-A 已将 13.1–13.3 中标出的设置／音色子集冻结为 `narration-settings-api/1`：21 个唯一 URL、29 个 HTTP 操作、27 个错误码。精确 DTO、capability 和 SHA-256 见 [T2-A 契约冻结记录](证据/MOSS-TTS-Nano施工/T2-A/README.md)。T3 与部分 T4 路由现已实现为仍受 capability 门禁的候选；下文明确标为 HOLD 的路由仍只是计划，隐藏 validation-only 路由也不得被视为公开产品 API。

### 13.1 设置和总览

```text
GET  /novels/{novel_id}/narration-overview
GET  /novels/{novel_id}/narration-settings
PUT  /novels/{novel_id}/narration-settings
GET  /novels/{novel_id}/narration-scope-overrides
PUT  /novels/{novel_id}/narration-scope-overrides/{scope_kind}/{scope_id}
POST /novels/{novel_id}/narration-cloud-consents
DELETE /novels/{novel_id}/narration-cloud-consents/current
```

cloud consent POST 必须携带 `Idempotency-Key`；DELETE body 必须精确携带 `consent_id + expected_version`，只撤销作者看到并确认的那条授权，不能让延迟请求撤销刚重新创建的新 consent。

### 13.2 音色

```text
GET    /voice-profiles
POST   /voice-profiles
GET    /voice-profiles/{profile_id}
PUT    /voice-profiles/{profile_id}
DELETE /voice-profiles/{profile_id}
POST   /voice-profiles/{profile_id}/versions/preset
POST   /voice-profiles/{profile_id}/versions/uploaded
POST   /voice-profiles/{profile_id}/previews
GET    /voice-previews/{preview_id}
POST   /voice-profiles/{profile_id}/lock
GET    /novels/{novel_id}/character-voice-bindings
GET    /novels/{novel_id}/characters/{character_id}/voice-binding
PUT    /novels/{novel_id}/characters/{character_id}/voice-binding
```

创建 profile、音色版本和试听必须使用幂等键；profile 更新/归档、锁定和人物绑定必须带精确 CAS。上传只允许 `metadata + reference_audio` 的窄 multipart，WAV/FLAC、16 MiB；浏览器只能收到与 `asset_id` 精确绑定的 `/media-assets/{asset_id}/content`，公开 rights 只返回来源 SHA-256，不返回文件或供应商 locator。

### 13.3 通用音色和选角

```text
GET /novels/{novel_id}/generic-voice-pools
PUT /novels/{novel_id}/generic-voice-pools
GET /novels/{novel_id}/casting-rules
PUT /novels/{novel_id}/casting-rules
GET /novels/{novel_id}/pronunciation-profile
PUT /novels/{novel_id}/pronunciation-profile
GET  /novels/{novel_id}/narration-cache
POST /novels/{novel_id}/narration-cache/cleanup-preview
POST /novels/{novel_id}/narration-cache/cleanup
```

通用音色池只有 24 个槽全部具备锁定音色、权利、质量和 production-ready 证据时才可返回 ready；当前没有已批准 pack，必须返回 missing/disabled 且自动通用选角不可操作。缓存清理采用 snapshot → expiring token → explicit confirmation 两步协议，source、locked voice 和被 Edition 引用的资产删除数在 wire contract 中固定为 0。

下列匿名说话人接口属于 T3 契约，不属于 T2-A 冻结面：

```text
GET /novels/{novel_id}/anonymous-speakers
PUT /novels/{novel_id}/anonymous-speakers/{speaker_id}
POST /novels/{novel_id}/anonymous-speakers/merge
POST /novels/{novel_id}/anonymous-speakers/{speaker_id}/split
POST /novels/{novel_id}/anonymous-speakers/{speaker_id}/promote
```

### 13.4 脚本

```text
POST  /documents/{document_id}/narration-requests
POST  /documents/{document_id}/narration-scripts/analyze
GET   /narration-scripts/{script_id}
GET   /narration-script-versions/{version_id}
PATCH /narration-script-versions/{version_id}/segments/{segment_id}
POST  /narration-script-versions/{version_id}/approve
POST  /narration-script-versions/{version_id}/reanalyze-segments
```

`narration-requests` 是“扫描全书”、章节“智能朗读”“更新朗读”和后续批量生成的单入口编排接口，不新建第二套任务账本。请求绑定已保存的 `source_revision_id/content_hash`、`intent = analyze_only | create | update | batch`、幂等键和可选 `force_review = true`；`force_review` 只能收紧为 `always_review`。服务复用既有脚本/Edition 或创建共享后台任务，并返回 `workflow_state = created | analyzing | analyzed | review_required | queued | rendering | partial_ready | ready | cancel_requested | cancelled | failed`、warnings/blockers 计数、script version、可选 Edition 和 job ID。这里的 `workflow_state` 是对冻结 `narration_requests.state` 的同名只读投影，不是前端自建状态机；不能省略取消/渲染状态，也不能把 `background_jobs.state` 直接冒充 request 状态。`analyze_only` 永不创建 Edition/音频；以后转为生成时必须重新校验 source、settings、规则和音色 fingerprint。

`analyze` 与 `approve` 只保留为调用同一 request 领域服务的受控动作；Edition 创建仅是该领域服务内部步骤和后台恢复命令，不暴露可由前端直接调用的 HTTP endpoint。默认零阻塞路径由 `narration-requests` 编排自动冻结并创建 Edition；人工路径只能在阻塞已清零或作品启用 `always_review` 时调用 `approve`。前端不得自行伪造 `auto_no_blockers`，恢复命令也必须复核同一 scope、request generation guard、approved script 和显式生成意图。

### 13.5 生成和播放

```text
GET  /documents/{document_id}/narration-playback-context
PUT  /documents/{document_id}/current-narration-edition
GET  /narration-editions/{edition_id}
GET  /narration-editions/{edition_id}/manifest
POST /narration-editions/{edition_id}/prepare-range
POST /narration-editions/{edition_id}/retry-failed-segments  # 规划／HOLD，当前未实现
# T6-D_CANCELLED：不存在章节／全书 export API
GET  /background-jobs/{job_id}
GET  /background-jobs/{job_id}/events
POST /background-jobs/{job_id}/retry
POST /background-jobs/{job_id}/cancel
GET  /media-assets/{asset_id}/content
GET  /narration-editions/{edition_id}/playback-progress?profile_id={profile_id}
PUT  /narration-editions/{edition_id}/playback-progress?profile_id={profile_id}
```

`narration-playback-context` 返回 working copy 哈希、当前 Edition/来源哈希、派生兼容状态、可用新 Edition 和最后进度。`current-narration-edition` 使用 `expected_version`，请求体包含目标 Edition、`switch_mode = immediate | next_playback` 和可选 `start_segment_id`：立即切换必须验证该起点已有合法 ready window，并原子写入新 Edition 进度；下次使用必须已有章首或历史合法起点。接口只接受同一 document 的可播放 Edition，并代表用户明确切换。

`prepare-range` 请求体至少包含 `start_segment_id` 和 `reason = user_seek | resume`；服务端验证 segment 属于该 Edition，按服务端缓冲策略幂等提升该句及后续句段任务，并返回当前 Manifest revision、窗口状态和可选 job ID。前端不能指定任意高优先级或绕过资源配额。

播放进度 GET/PUT 都要求 exact `profile_id` query；PUT body 内的 `profile_id` 必须同值，并通过 Edition、Manifest revision、segment 归属和 CAS version 围栏防止跨版本污染。

隐藏预发布验证另有一个非公开、仅读投影：

```text
GET /novels/{novel_id}/documents/{document_id}/narration-validation-observation
```

它仅在 `validation=true` 且 `product=false` 时对同一 token 信封的 exact novel/document 生效，只接受一个 validation header；缺失、错误、重复、过期或跨 scope 均返回 `404 + no-store`，运行时不可用返回 `503 + no-store`。响应严格只有 `model_ready`、`worker_ready`、`active_syntheses`、`queued_jobs`、`observed_at` 五个字段，不回显 token、scope、正文、路径、容器或数据库详情。

云端授权接口不得与普通设置 PUT 混在一起静默开启。媒体读取支持 Range、ETag 和内容类型校验；API 返回受控媒体 URL，不返回服务器文件路径或供应商临时 URL。Manifest 使用 `ETag`/revision 支持增量轮询；SSE 只用于加快状态更新，不能成为恢复权威。

## 14. 运行拓扑与资源

### 14.1 服务边界

```text
浏览器
  -> PawApp API
       ├─ NarrationService / ScriptAnalyzer / VoiceCastingService
       ├─ BackgroundJobRunner
       ├─ MediaStorage / PostgreSQL
       ├─ TTSAdapter ──► NanoExecutionBackend
       └─ VoiceDesignAdapter ──► VoiceGeneratorExecutionBackend（按需）
```

浏览器永远只访问 PawApp API。`NanoExecutionBackend` 是逻辑执行边界，不预先等同于第二个 HTTP 服务。

**项目决策**：不创建第二套业务 Web API、Agent Runtime 或任务账本；允许经阶段 0 选择受后台管理的本地模型进程。若使用 Sidecar，它只暴露窄模型契约，不拥有小说、人物、脚本、任务或媒体业务状态。

### 14.2 Nano 部署闸门

官方已提供 ONNX CPU、浏览器 ONNX 和本地服务示例；其中浏览器 JavaScript 路径可不依赖 PyTorch，但当前固定 Python ONNX 源码仍导入 `torch/torchaudio`。阶段 0 对同一基准集测试：

1. PawApp 后端进程内 ONNX CPU：最少拓扑，验证依赖冲突、事件循环阻塞和崩溃影响；
2. 后端受管 macOS 原生子进程：验证 IPC/loopback、自动拉起、日志和资源释放；
3. Linux ARM64 Compose Sidecar ONNX：验证部署一致性、挂载和容器开销；
4. 浏览器 ONNX：只作为未来低延迟试听候选，验证模型下载、缓存、内存、页面关闭和宿主 CSP；
5. 各路径统一测冷启动、预热首包、RTF、峰值内存、连续 30 分钟稳定性、取消和重启恢复。

当前固定宿主是 Linux/arm64 QwenPaw Compose。T0-GATE 已在固定依赖、故障/恢复、资源、reference、1804 秒耐久、零残留与 QwenPaw 健康真证据通过后，选定同一 Compose 私网中的 Linux/arm64 Sidecar；T1-DEP 必须保持该拓扑和窄协议。QwenPaw Linux 容器内隔离 venv 子进程未获批准，不能在 Sidecar 故障时静默切换；若未来需要评估，必须重开 ADR 并重新验证镜像体积、依赖冲突、卸载清理和故障边界。macOS 原生受管 worker 只作为开发/协议/算法诊断证据，容器内 PawApp 无法直接启动它，不是生产回退。浏览器 ONNX 也不作为正式批量生成路径，因为页面生命周期不能承担持久任务、媒体落盘和崩溃恢复。

上层 `TTSAdapter` 契约保持不变，至少提供 capabilities/health/warmup/synthesize/cancel/model-fingerprint。物理部署切换不得改变 Edition fingerprint 的语义。

若使用 loopback HTTP：只监听 `127.0.0.1` 或容器私网，使用随机启动令牌、请求大小限制、版本握手和超时；浏览器不可访问。若使用 IPC，应同样校验协议版本和路径白名单。

### 14.2.1 隐藏验证运行态与公开产品放行

T4-K 真实章节验收需要调用与生产相同的后端、worker 和 Sidecar，但在 T4-GATE 通过前不得对普通用户暴露尚未放行的入口。因此冻结四个彼此独立、默认关闭的开关：

- `AI_NOVEL_TTS_RUNTIME_ENABLED=true`：只表示技术 Sidecar 与基础运行时可被检查，不表示产品可见；
- `AI_NOVEL_TTS_VALIDATION_ENABLED=true`：仅供 T4-K/T4-GATE 的隐藏预发布验证。它复用现有进程内生产 backend/worker，不新增数据库、容器或队列，且必须与 `AI_NOVEL_TTS_PRODUCT_ENABLED=true` 互斥；
- `AI_NOVEL_TTS_PRODUCT_ENABLED=true`：只能由 T4-GATE 在真实闭环通过后提议公开放行。T4-K 运行时必须保持它为 `false`，且服务端健康投影中 `product_visible` 必须为 `false`；
- `AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=true`：只表示另行验收过的参考音频产品链可被请求；它不能由 runtime、validation 或 product 开关推导。有限核心 T4-K 固定为 `false`，并要求健康投影 `reference_clone_ready=false`；本轮只消费运行前已经通过真实试听、作者确认、锁定和角色绑定的三个互异 `official_preset`，不上传参考录音。在独立 reference-clone validation 工作包获批前，服务端、安装器和固定 launcher 均须硬拒绝 `validation=true + reference=true`。

隐藏 validation 不是“知道一个开关即可访问”的后门。每次验证必须同时配置 canonical novel UUID、属于该小说的 canonical chapter document UUID，以及未来不超过 24 小时、UTC 秒级的 expiry；宿主与 QwenPaw secret volume 各保存一个身份一致的私有 token 文件副本，token 不进入 `.env`、进程环境、命令行、URL、日志或证据。请求只能携带一条 `X-AI-Novel-TTS-Validation` 物理 header；无、错或重复 header 在 narration/script/playback 三类 T4 路由均返回门禁专属 `404` 与 `Cache-Control: no-store`，且普通 overview 仍精确投影 T2。即使 token 正确，服务端也必须以 SELECT-only scope 检查 direct novel/document、request/Edition/script/version 间接资源和 novel 级声音资源；未知路径 fail-closed。

validation worker 继续使用同一持久任务账本，但 claim、retry promotion 与 expired-attempt reconciliation 必须同时过滤 exact novel、exact document、允许的资源类别、`moss-nano` 资源和允许的 job kind；request-linked job 不得借 novel 级匹配越过 document 约束。expiry 到达后 scheduler 不再开启新的领取或维护事务。固定真实 launcher 在任何 baseline 读取或写请求之前，还必须完成无／错／重复 token 跨三类路由、负向 overview 和正确 token 临时 tier 在内的 13 个只读探针；随后校验固定 Node/Playwright 本地执行器、canonical run_id、scope/fixture、四个 actual viewport、一次性私有目录、文件权限和同一运行绑定。调用方不得注入 URL、browser、selector、viewport 或任意执行模块；validation token 只能经冻结的私有输入通道使用，不能进入 argv、env、URL、日志或证据。上述本地前置任一失败立即停止，不得进入真实章节写入；但不再执行或等待 controller-authority 签名 preflight、OS signing port、public trust root、active root 或 key ceremony。既有 run 的 resume 恢复通道继续只走冻结恢复合同。

公开 capability 不得只因产品环境变量为 `true` 就被返回。放行时必须改为 `product=true`、`validation=false`，并同时满足：技术 runtime 已启用、生命周期就绪、Sidecar 可达且模型 ready；生产 pipeline 已被明确请求、生命周期就绪、播放链已安装、render digest keyring 可用、backend 已安装、worker 正在运行，且两层健康结果都没有失败 reason。若同时拟放行 reference clone，还必须 `AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED=true` 且可取得真实 voice product port；否则 reference capability 继续独立 HOLD，不影响已经另行通过的有限核心。任一核心条件缺失都应 fail-closed 回到已放行的 T2 设置能力。上述是 T4-GATE 的放行合同，不是已经完成真实运行验收的声明。

### 14.3 VoiceGenerator

优先验证 macOS MPS，其次验证可接受的 CPU/其他本地路径。它只在创建音色或阶段 0 制作基础音色包时加载，完成后释放；Nano 和 VoiceGenerator 默认不同时常驻，并由共享 `gpu_heavy` 资源锁串行化。

VoiceGenerator UI 与完整通用音色池已退出当前范围。当前有限核心只使用作者已确认、锁定和接受的三个官方预设：旁白 `onnx.Zhiming`、沈川 `onnx.Junhao`、林晚 `onnx.Xiaoyu`。VoiceGenerator 或 24 槽未实施不得阻断这三项中文官方预设的个人本地 T4 主路径。

### 14.4 持久存储

Compose/本机增加：

```text
moss-models    模型权重、锁定 revision 和经过校验的 manifest
novel-media    当前试听、句段 master 和网页播放副本；历史参考录音只作兼容，不新建导出资产
```

模型文件不写入 Git。模型版本、revision、文件清单和哈希保存在部署配置/数据库中。下载必须支持临时文件、断点/重试、哈希校验和原子改名，不能把半下载文件标记为可用。

### 14.5 音频格式和容量

- Nano 原生输出按官方能力为 48 kHz 双声道；阶段 0 验证是否保留双声道或在后处理规范化为单声道；
- 参考音频：保留原始私有资产和标准化无损版本；
- 句段 master：优先 FLAC 或经验证的无损格式，只用于重建网页播放副本；
- 句段播放副本：经浏览器兼容验证后选择 Opus/AAC；
- 章节／全书连续导出文件：`CANCELLED`，不生成、不拼接、不缓存；网页分段播放资产不视为导出文件；
- 临时 WAV 在 master 和播放副本均校验成功后删除；
- 官方 Nano ONNX 单个 TTS shared-data 文件约 441 MB，完整 Nano、Audio Tokenizer 和运行依赖以锁定 revision 实测为准；VoiceGenerator 当前权重约 4.23 GB；
- 一本 200 章小说的压缩音频预计为数 GB，必须有配额、过期缓存清理和磁盘不足提示。

阶段 0 必须固定 ffmpeg 或等价转码器版本并验证可用性；缺少转码器时不得生成只有数据库记录、没有可播放文件的半成品。

参考录音、锁定音色和无法重新取得的用户资产必须备份；可重建章节音频可按策略排除普通备份。

## 15. 安全、隐私和授权

- 上传录音前要求用户确认拥有授权；
- 保存来源类型、授权确认时间和可选说明；
- 自定义音色、参考录音和 TTS 合成始终默认只在本地处理；
- 正文分析默认 `local_rules_only`；只有作品级 `cloud_assisted` 明确授权后，才发送不确定句段和最小上下文；
- 撤销云端授权只阻止未来调用，不伪造删除供应商侧已经处理的数据；界面必须说明供应商数据政策由其条款决定；
- 云端分析请求不包含参考录音、音频资产、完整人物库或整章正文；
- 不在日志、错误跟踪或遥测中记录完整正文、参考录音或音频内容；
- `model_run_records` 保存哈希和审计元数据，不保存可还原正文的提示全文；
- 校验 MIME、大小、时长、解码、路径和文件名；
- 禁止目录穿越和任意文件读取；
- 浏览器不接触模型目录、服务端路径和第三方密钥；
- 本机模型进程只接受后台签发的请求，限制文件根目录、请求大小、并发和超时；
- 被人物、脚本或历史 render 引用的音色只能归档；
- 物理删除前生成引用影响预览；
- 提供彻底删除私人音色和源录音的显式操作；
- “仅删除上传原件”和“彻底删除该私人音色”是历史上传／reference-clone 兼容语义，不在当前官方预设主路径新建入口；对旧数据执行彻底删除时，仍必须展示受影响人物、脚本、Edition 和历史网页播放资产，并留下不可还原的 tombstone 审计；
- 官方 preset 名称和官方标签必须如实展示，不建立名人／公众人物排除名单；界面不额外作官方未声明的背书或商业宣传，且这类展示说明不得降低个人本地可用性；
- Apache 2.0 模型许可证不自动授权未来的商业发布、再分发或外部声音使用；该风险记录不得转化为当前个人本地 6 个官方预设的审批流程或功能阻断。

## 16. 完整主流程

### 16.1 首次配置

1. 用户进入书本“朗读”；
2. 检查模型安装、哈希、执行后端和磁盘；
3. 下载缺失模型并显示可恢复进度；
4. 预热 Nano；
5. 选择 `local_rules_only` 或明确授权 `cloud_assisted`；
6. 配置默认旁白；
7. 若存在门禁批准的基础音色包则校验并初始化；否则保持 `generic_voice_pool_enabled=false`，只显示缺失/未授权状态，不创建、默认绑定或伪装 24 个可用声音；
8. 配置第一人称、内心独白、标题和备用规则；
9. 扫描正式人物音色覆盖率和别名冲突；
10. 给主要人物设置专属音色；
11. 建立发音词典；
12. 用固定测试文本试听并锁定声音；
13. 冻结首个 narration settings snapshot。

### 16.2 生成章节朗读

1. 作者点击章节“智能朗读”；
2. 前端完成保存屏障；
3. 后端复用相同哈希 revision 或幂等创建隐藏 `tts_snapshot`；
4. 创建幂等分析任务；
5. 解析 Markdown 并保留偏移；
6. 生成场景边界并加载人物别名；
7. 按规则识别旁白和明确说话人；
8. 仅在授权的智能增强模式下，对不确定句段调用受控模型；
9. 建立/匹配匿名说话人，冲突项进入复核；
10. 预测有限情绪和表达方式；
11. 应用章节、分卷、作品、人物和通用音色优先级；
12. 校验所有 character ID 和 scope 归属；
13. 生成带证据和置信等级的脚本草稿；
14. 计算 warnings、blockers 和生效的 `script_review_policy`；
15. 若为默认 `blockers_only` 且零阻塞，领域服务记录 `auto_no_blockers` 并自动冻结脚本；
16. 若存在阻塞或启用 `always_review`，打开复核面板；作者集中处理低置信度、unknown、别名/匿名冲突、缺失音色等项目；
17. 阻塞清零并经作者确认后记录 `manual_after_review` 并冻结脚本；
18. 冻结设置/发音/模型/音色并创建 Edition；
19. 计算所有句段 render fingerprint；
20. 复用命中 render 并发布包含全部句段状态、ready prefix 和 ready ranges 的初始 Manifest；
21. 对缺失句段建立共享持久任务；
22. 优先合成章节连续开头；
23. 校验、标准化并保存 master/播放资产；
24. 每个句段完成后重新计算连续窗口并 CAS 更新 Manifest；
25. 章首连续前缀达到门槛后标记 `partial_ready` 并允许默认播放；
26. 前端按 Segment Manifest 预加载和播放；
27. 校验当前正文 hash 后通过 `NarrationEditorBridge` 按 segment ID 高亮；
28. 保存播放进度；
29. 失败句段可单独重试；
30. 所有句段完成后 Edition 标记 `ready`。

第 15 步只发生在作者已显式发起本次生成之后；它不是后台按键级预生成，也不会自动替换正在播放的旧 Edition。首次生成且不存在当前 Edition 时，只有 working copy 仍与来源 hash 一致，才可在达到播放门槛后把它设为初始当前版本；分析期间正文已经继续修改时，新 Edition 标为“旧快照已就绪”并等待作者更新或明确选择。已有旧 Edition 时仍执行第 16.4 节的显式切换契约。

### 16.3 从任意段落开始朗读

1. 用户点击段落边栏 `▶`、句段上下文命令，或在只读快照点击句段；
2. 前端把当前来源块/位置解析成 Edition 内的 `segment_id`，普通正文单击仍只放置光标；
3. 读取播放上下文并确认目标 segment 属于当前 Edition，且工作稿来源块仍有可验证映射；若该段已修改、新增或映射不唯一，则提示先更新朗读或进入旧稿视图，不猜测跳转；
4. 若 Manifest 已有覆盖目标起点且该起点满足 `last_playable_start_ordinal` 的连续 ready range，立即停止当前队列并从目标 segment 预取播放；
5. 若目标未 ready 或后续缓冲不足，调用幂等 `prepare-range`，显示“正在准备本段”，不回退章首、不跳到其他已完成段；
6. 后端提升目标句及后续缓冲句的短期优先级，保留 render fingerprint 幂等和公平老化；
7. 目标窗口达到服务端门槛后发布新的 Manifest revision；
8. 前端只在句段边界刷新同一 Edition 的 Manifest，随后从目标 segment 播放；
9. 跳播更新最后合法起点和播放进度；
10. 正文一致时恢复高亮，正文已修改时使用安全映射或旧稿字幕，不错误套用偏移。

### 16.4 同页修改、更新和失效

1. Edition A 播放期间，作者可以继续修改 working copy B；输入、选择和撤销优先于自动跟随，音频默认不暂停；
2. 页面派生 `working_copy_diverged`，显示“旧稿朗读”和待更新范围，不创建按键级任务；
3. 合格编辑器只继续映射未与 transaction 相交的句段；相交句段的高亮失效并在播放器显示 Edition A 旧文本；
4. 作者点击“更新朗读”后，前端等待自动保存并执行保存屏障；
5. 后端幂等复用或创建正文快照 B，对变化范围及必要场景上下文重新分析；
6. 可唯一匹配且证据仍成立的人工覆盖允许迁移，其他变化进入复核；
7. 新脚本按复核策略自动或人工冻结后创建 Edition B，相同 render fingerprint 直接复用，只合成必要句段；
8. Edition B 达到目标起点的播放门槛后提示“新朗读已就绪”；
9. 用户明确选择立即切换或下次使用；立即切换只在当前句段边界进行，并从可唯一匹配且已 ready 的 segment 或章首开始；下次使用必须保存新 Edition 的合法起点；
10. 更新 `document_narration_state` 后 Edition A 不再是当前版本，但其生成状态、音频、进度和快照不被改写，继续按保留策略可回放。

其他失效规则：

- 修改正文：新 revision 的脚本重新分析；满足唯一锚点条件的人工覆盖可迁移，相同句段仍可复用 render；旧 approved 脚本/Edition 保持不可变，由当前指针和 fingerprint 查询派生 `superseded`/`working_copy_diverged`。
- 修改某一句说话人或 `spoken_text`：创建新脚本版本，按复核策略重新冻结后创建新 Edition；只缺失必要 render。
- 修改人物音色：创建新 voice version/binding；历史 Edition 不变，新 Edition 只生成受影响句段。
- 修改停顿：创建新 settings snapshot/Edition，复用语音 render，只重建 Manifest 时间线；不生成或重建章节／全书导出文件。
- 升级模型、Tokenizer、Normalizer 或后处理：按 fingerprint 精确失效。
- 归档人物：保留历史绑定，当前脚本重新分析时提示处理。

### 16.5 全书扫描与批量生成

“扫描全书”和“批量生成”必须是两个动作：

1. “扫描全书”只创建/复用 `analyze_only` 请求，按章节显示覆盖率、warnings、blockers 和失效状态，不创建 Edition、render 或音频任务；
2. “批量生成”在阶段 6 开放；开始前展示章节范围、预计时长/磁盘、当前复核策略和并发策略，并由作者显式确认；
3. 每章使用独立幂等请求和脚本/Edition；某章有 blocker 或失败时只暂停该章，不阻塞其他零阻塞章节；
4. `blockers_only` 下零阻塞章节自动进入生成，问题章节进入总览待办队列；不连续弹出多个复核面板；
5. `always_review` 下每章停在待复核队列，由作者逐章确认；
6. 总览显示“已完成/生成中/待复核/失败/取消”数量，可取消未开始任务并保留已完成的合法 render；
7. 批量生成完成的新 Edition 不自动替换各章当前 Edition；作者在章节内或批量结果页显式选择更新范围。

## 17. 失败恢复

| 故障 | 用户看到 | 权威数据 | 恢复 |
| --- | --- | --- | --- |
| Nano 未安装/损坏 | 模型未就绪 | 正文、脚本不变 | 校验并恢复下载 |
| Nano 执行后端不健康 | 朗读服务不可用 | 正文不变，任务留队 | 重启/切换后端、预热、重试 |
| 参考音频无效 | 音色测试失败 | 不锁定新版本 | 更换/修复文件 |
| VoiceGenerator 失败 | 候选生成失败 | 现有音色不变 | 重试或改用预设/上传 |
| 人物识别失败 | unknown 待复核 | 正文、人物不变 | 作者绑定后继续 |
| 云端未授权/已撤销 | 不调用云端，显示需复核 | 正文、人物不变 | 本地复核或重新明确授权 |
| 实际聊天模型不匹配 | 本次分析结果作废 | 旧脚本不变 | 修复 Provider 后重试 |
| 单句合成失败 | 章节部分完成 | 已成功句段保留 | 单句重试 |
| 任务进程崩溃 | 进度暂时停止 | 持久 job/render 保留 | 租约过期后恢复 |
| 正文已修改 | 播放器显示“旧稿朗读”，修改段待更新 | 旧音频、Edition 和 revision 保留 | 继续旧版校听或点击“更新朗读” |
| 跳播目标未生成或后续缓冲不足 | 显示“正在准备本段” | Edition、已有 render 和任务保留 | 幂等提升目标连续窗口优先级，满足门槛后从目标播放 |
| 编辑器映射链丢失 | 当前工作稿不显示旧高亮 | Edition 与不可变旧稿保留 | 播放器字幕/旧稿视图继续高亮，禁止猜测映射 |
| 磁盘不足 | 暂停生成并提示 | 不删除重要资产 | 清缓存/扩容后重试 |
| 音频转码失败 | 目标句段未 ready | 已校验 master 可恢复 | 重试播放副本转码，不重合成 |
| 当前播放窗口中间句缺失 | 播放到缺口后等待或停止 | 已完成 render 和 ready ranges 保留 | 优先重试缺失句，不静默越过缺口 |
| 浏览器断线 | 进度暂停显示 | 后台任务继续 | 按 job ID 恢复 |

## 18. 实施阶段

### 18.0 本文内部的子代理并行派发总表

| 阶段 | 可并行工作包 | 主要串行/互斥点 | 汇合门禁 |
| --- | --- | --- | --- |
| 0 | T0-A…I：历史依赖、拓扑、语音质量、VoiceGenerator、24 音色、编辑器、Manifest、数据审查、测试工具 | 已完成历史阶段；VoiceGenerator、24 槽和商业审计不进入当前 ready set | T0-GATE（历史） |
| 1 | T1-A…C、E…G：适配器、模型生命周期、任务、媒体、领域服务和测试 | T1-DEP 运行依赖、T1-D schema/Alembic 与共享任务契约 | T1-GATE |
| 2 | T2-B…H：历史朗读页、人物声音、上传标准化、音色池、发音缓存、错误/授权状态和测试 | 当前产品只消费旁白／正式人物与六个中文预设的直接绑定 | T2-GATE（已通过历史范围） |
| 3 | T3-B…I：历史切分映射、说话人、云端补充、匿名人物、选角、情绪、复核和测试 | 当前只放行 local-rules-only 的旁白／正式人物；云端辅助与高级匿名继续 HOLD | T3-GATE（已通过有限技术范围） |
| 4 | T4-A…K：Edition、Worker、后处理、Manifest、网页播放器、编辑器桥、高亮、旧稿、局部重生成、最小缓存／磁盘保护和真实验收 | 真正 Nano 单并发、重复句段 fanout、公共接口与最终章节 E2E | T4-GATE（当前唯一完工门禁） |
| 5 | T5-A…E：VoiceGenerator 历史规划 | `DEFERRED_OUT_OF_CURRENT_COMPLETION`；不得从 T4-GATE 自动开放 | 无当前门禁 |
| 6 | T6-A…C/E…H：高级生产历史规划；T6-D 导出已取消 | 仅最小缓存／磁盘保护并入 T4；其余 `DEFERRED`，T6-D `CANCELLED` | 无当前门禁 |

标注不等于提前开工：T0-A…I、T1-DEP/T1-A…G、T2-B…H 和 T3-B…I 是历史已执行工作，不因范围缩减伪造删除；但商业／再分发审批、英文／日文专项、云端／共享／复杂继承音色、VoiceGenerator、24 槽、独立 OS 签名和导出不再属于当前完成定义。当前 ready set 只推进 T4：先复核 `T4K-RF` 重复规范句段 fanout 修复，再以唯一确认的 Zhiming／Junhao／Xiaoyu 绑定建立可恢复 baseline Edition，随后完成真实 Nano 章节、播放器／CodeMirror、30 分钟、四桌面、恢复、最小缓存／磁盘保护、打包及安装／升级／卸载非回归，最后由 `T4-GATE` 汇合。云端辅助说话人识别和高级匿名人物选角继续 false/HOLD，但不阻断这一有限核心。T4-GATE 通过前不得把 Edition、合成、播放器、人工复核或编辑器同步表述为已可用。

工作包标记：`PAR` 表示前置满足后可独立并行，`PAR-C` 表示先冻结契约再并行，`SER` 表示串行或单一所有者，`MUTEX` 表示共享 M4/模型资源互斥，`GATE` 表示阶段闸门，`INT` 表示主代理集成。以下编号全部是本 TTS 文档的本地编号。

#### 18.0.1 阶段 T0：ADR、模型、音色包和质量尖峰

| ID | 标记 | 本文工作包 | 独立产物 |
| --- | --- | --- | --- |
| T0-A | PAR | Nano、Tokenizer、ONNX、VoiceGenerator、转码器 revision/hash、许可证和下载清单 | 可复现依赖清单 |
| T0-B | PAR/MUTEX | 进程内 ONNX、受管本机进程、Sidecar、浏览器试听同基准 | 拓扑性能/故障矩阵 |
| T0-C | PAR/MUTEX | 数字、标点、多音字、中英混读、长句、3/5/8/12 秒参考和独立句段听感 | 音质与参考音频报告 |
| T0-D | PAR/MUTEX | VoiceGenerator MPS/CPU、峰值内存、候选生成和 Nano 二次克隆 | 可见/隐藏结论 |
| T0-E | PAR | 24 槽位音色来源、授权台账、去重、样本和人工锁定 | 音色包或替代来源 |
| T0-F | PAR | CodeMirror 6、Monaco、textarea 降级的 IME、自动保存、undo、decoration、gutter、UTF-16 和 Blob bundle | 编辑器 ADR 输入 |
| T0-G | PAR | Manifest v2、章首前缀、中段 ready window、pending gap、快速跳播和播放接缝原型 | Manifest/队列原型 |
| T0-H | PAR | 任务、媒体、脚本、Edition、render、复核策略、阻断分类、授权与隐私 schema 审查 | 数据/API/状态机草案复核 |
| T0-I | PAR | 固定语料、假适配器、自动化、性能、崩溃恢复和人工听感记录模板 | 可复用验收工具 |
| T0-GATE | GATE | 冻结 Nano 拓扑、24 音色、播放器、VoiceGenerator、编辑器、ready-window、复核策略/阻断分类七项 go/no-go | ADR、能力矩阵、阶段 0 报告 |

T0-A 和 T0-I 必须先冻结隔离依赖与基准 CLI/fixture，随后才能正式运行 T0-B、T0-C、T0-D、T0-F、T0-G；这些工作包的资料分析和脚本骨架可以提前并行。Nano 与 VoiceGenerator 的 MPS/大内存运行不得同时压测；每次测试必须记录环境、进程、模型 hash、参数、峰值内存和结果。T0-E 可以先并行核验槽位与授权来源，但只能在 T0-C/T0-D 听感结果回收后锁定最终音色包。

2026-08-26 的 T0 汇合审计发现：当前 QwenPaw 固定实验环境实际位于 Linux/arm64 容器，而最先通过故障恢复的 T0-B worker 位于宿主 macOS arm64。后续 T0-B 已在原工作包与受控 `LOCK-NANO` 窗口内补齐 Linux/arm64 Compose Sidecar 真证据：固定 wheels/FFmpeg/镜像与模型校验、无主机端口、非 root/只读边界、普通与 reference 请求、取消、活动请求故障恢复、容器重启、1804 秒耐久、最终零残留和 QwenPaw 健康均通过。T0-GATE 因此冻结 `deployment_topology=linux_arm64_private_sidecar` 并只开放 `T1-DEP`；这仍不等于生产 Sidecar、API 或 UI 已实现。

同日的 T0-H 只读审查发现，scope、脚本终态、请求隔离、阻断分类、job fencing、Manifest/GC、授权、私密指纹和彻底删除仍存在可导致并行实现分叉的 schema 歧义。主代理已在 [`T0-H/gate-decisions.md`](证据/MOSS-TTS-Nano施工/T0-H/gate-decisions.md) 冻结 10 项精确决策，T0-GATE 对其固定 SHA-256 作 `ACCEPT_UNCHANGED`；这只冻结后续施工输入，不代表 ORM、迁移或领域服务已实现。当前先由 `T1-DEP` 完成并通过依赖/运行层验收；随后才由 T1-A 落公共常量、DTO 与 taxonomy fixture，T1-D 再据此成为唯一 schema/Alembic Owner。T1-C、T1-E、T1-F 在 T1-D schema 通过前不得并行写各自的临时字段。

#### 18.0.2 阶段 T1：共享基础设施与数据

| ID | 标记 | 本文工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T1-DEP | SER | 将 T0-GATE 选定的正式 Python/转码/拓扑依赖接入项目锁与可重建运行层 | T0-GATE；依赖/Compose 锁 |
| T1-A | PAR-C | `MossNanoTTSAdapter`、`VoiceDesignAdapter`、能力/健康/指纹 | T1-DEP |
| T1-B | PAR-C | 模型下载、校验、预热和受管生命周期 | T0-GATE 拓扑、T1-A 接口 |
| T1-C | PAR-C | background job、租约、幂等、重试、死信和资源锁 | T1-D 共享任务 schema |
| T1-D | SER | TTS schema、Alembic 迁移编号、升级/回退 | T0-H gate decisions、T1-A contracts/fixture、迁移锁 |
| T1-E | PAR-C | media assets、moss-models、novel-media、Range/ETag、引用/GC | T0-GATE、T1-D schema |
| T1-F | PAR-C | tts_snapshot、voice/settings/script/source key/Edition/render/Manifest/进度领域服务 | T1-A 接口、T1-D schema |
| T1-G | PAR-C | fake adapter、崩溃恢复、GC、迁移和缓存集成测试 | T1-A–T1-F 契约 |
| T1-GATE | INT/GATE | 本阶段共享基础设施集成 | T1-DEP、T1-A–T1-G |

#### 18.0.3 阶段 T2：声音和朗读设置

| ID | 标记 | 本文工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T2-A | SER | 设置、音色、绑定和试听 API/DTO 冻结 | T1-GATE |
| T2-B | PAR-C | 书本 reading 路由、总览、导航和旁白/范围覆盖 UI | T2-A |
| T2-C | PAR-C | 历史人物卡“声音”页签；当前产品只使用 direct official-preset 绑定 | T2-A；继承 UI 不进入当前产品 |
| T2-D | PAR-C | 历史预设、上传、标准化、授权、试听和不可变锁定版本 | 当前 T4 只消费六个中文官方预设的试听／锁定；审批工作流非目标 |
| T2-E | PAR-C | 历史通用音色池候选 | `SUPERSEDED_NON_TARGET`；24 槽不进入当前 ready set 或 T4 门禁 |
| T2-F | PAR-C | 发音、停顿、音频和缓存设置 | T2-A |
| T2-G | PAR-C | 本地规则/云端授权、脚本复核策略、撤销、磁盘和模型缺失状态 | T2-A |
| T2-H | PAR-C | API、UI、键盘、授权、历史引用及 1920×1080／2560×1440 桌面布局测试 | T2-A 后可测试先行；最终运行依赖 T2-B–T2-G |
| T2-GATE | INT/GATE | 本阶段声音设置闭环集成 | T2-B–T2-H |

#### 18.0.4 阶段 T3：脚本、场景和选角

| ID | 标记 | 本文工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T3-A | SER | narration script/segment、范围和 ID 契约冻结 | T1-GATE |
| T3-B | PAR-C | Markdown、纯文本、UTF-16、source_block_key 和 segment_kind | T3-A |
| T3-C | PAR-C | 别名冲突、场景切分和本地说话人规则 | T3-A |
| T3-D | PAR-C | 最小云端不确定窗口、requested/actual 和严格 schema 校验 | 历史候选保留；当前 `HOLD_PENDING_DECISION` |
| T3-E | PAR-C | 匿名人物稳定键、合并、拆分和升级 | 历史候选保留；高级匿名选角 `HOLD_PENDING_DECISION` |
| T3-F | PAR-C | 通用选角、scope 优先级和稳定分配 | 历史候选；不进入当前 T4 产品范围 |
| T3-G | PAR-C | 情绪/表达、置信等级和人工覆盖继承 | 历史候选；复杂继承不进入当前产品范围 |
| T3-H | PAR-C | 默认零阻塞自动冻结、逐章复核、阻塞复核 UI、版本和 unknown 处理 | T3-A、T0-H、T2-GATE |
| T3-I | PAR-C | 归因准确率、非法 ID、两种复核策略、阻断拦截、隐私和重复分析测试 | T3-A 后可测试先行；最终运行依赖 T3-B–T3-H |
| T3-GATE | INT/GATE | 本阶段可自动/人工冻结朗读脚本集成 | T3-B–T3-I |

#### 18.0.5 阶段 T4：独立句段合成和同步播放

| ID | 标记 | 本文工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T4-DEP | SER | 按 T0-F ADR 接入唯一正式编辑器依赖和根 lock | T3-GATE；依赖锁 |
| T4-A | PAR-C | narration-request 编排、Edition、不变设置快照、render fingerprint 和缓存作用域 | T1-F/T1-GATE、T3-GATE |
| T4-B | PAR-C/MUTEX | 持久句段 Worker、优先级、公平老化、取消和单并发资源锁 | T1-C/T1-GATE |
| T4-C | PAR-C | master/播放副本校验、转码、响度和接缝处理 | T0-GATE、T1-E/T1-GATE |
| T4-D | PAR-C | Manifest v2、连续前缀/range、ETag/CAS 和 prepare-range API | T0-G、T1-F/T1-GATE |
| T4-E | PAR-C | Web Audio 队列、3–5 段预取和双 audio 回退 | T4-D mock |
| T4-F | PAR-C | `NarrationEditorBridge` 与正式编辑器适配器 | T0-F ADR、T4-DEP |
| T4-G | PAR-C | gutter、上下文命令、键盘跳播、高亮和滚动暂停/恢复 | T4-D、T4-E、T4-F 契约 |
| T4-H | PAR-C | working_copy_diverged、来源快照提示、复核面板/播放器共存、旧稿字幕、显式更新和 Edition 切换 | T3-H、T4-A、T4-F |
| T4-I | PAR-C | 局部失效/重生成、旧版本视图、进度保存和快速连续跳播 | T1-F、T4-A、T4-D |
| T4-J | PAR-C | 零阻塞自动生成、阻塞暂停、Manifest、编辑映射、缓存、隐私、恢复和不触发按键级 TTS 自动化 | T4 契约 |
| T4-RC | SER/MUTEX | 补齐持久幂等的人工脚本修正／批准、request 当前复核版本 CAS，以及 `review_required → queued → 唯一 Edition` 同事务继续生产；只使用现有 PostgreSQL 与既有任务队列 | T3-H、T4-A；主代理冻结 schema/API 后独占脚本 mutation 文件 |
| T4-K | PAR/MUTEX | 一章真实多角色、接缝、30 分钟、RTF、跳播和人工听感 | T4-A–T4-I 集成 |
| T4-GATE | INT/GATE | 核心多角色朗读闭环集成 | T4-DEP、T4-A–T4-K、T4-RC |

T0-F/T0-G 固定宿主只读审计进一步冻结 T4 启用边界：T0-GATE 即使条件接受 CodeMirror、Manifest、Range/ETag 和播放调度契约，`editor_production_enabled` 与 `product_player_enabled` 也必须保持 `false`。T4-DEP 只接入 CodeMirror 一套根依赖并先冻结相对当前正式 bundle 的 raw/gzip 增量预算；Monaco 不得进入根 lock。T4-F 只能在 `docChanged` 时把纯 `nextValue` 交给现有唯一保存链，decoration、跟随或 seek 不能写 recovery、触发自动保存或触发 TTS，并必须为旧章节 timer/response 增加 document id/generation fencing。T4-D 新建专用媒体读取适配器，不能复用强制 JSON 的 `apiRequest()`；Range/If-Range/AbortSignal 经 `window.QwenPaw.host.fetch` 传递，token 不得进入 URL。T4-RC 不新增第二套数据库、容器、队列或状态机：仅在现有 PostgreSQL 中保存人工动作幂等证据和 request 当前候选指针；修正生成不可变子 ScriptVersion，批准、request CAS、Edition/segment/render/job 规划必须同事务提交，Nano 只在事务提交后由既有 worker 调用。只有 T4-GATE 在固定 QwenPaw 中通过完整 Blob/CSP、正式保存/CAS/recovery、系统中文 IME、键盘/焦点/ARIA、精确四组合（`1920×1080 × 助手收起/展开`、`2560×1440 × 助手收起/展开`）、流式 Range 鉴权、独立相邻句段听检、章节切换/刷新/卸载清理和原生聊天非回归后，主集成 Owner 才可把对应 capability 改为默认可见；四组合缺任一项都不得通过，而低于 1920×1080、移动、窄屏和 200% 等效小视口不进入本专项设计、测试或阻断门禁。

`T4-K` 在真实写入前继续拆成本文档内的稳定 ready set，避免把 HTTP 编排、浏览器探针、授权资产和唯一固定宿主写入混成一个不可审计任务：

| 子包 ID | 标记 | 唯一目标 | 前置与文件 Owner | 退出条件 |
| --- | --- | --- | --- | --- |
| T4-K-C | SER | 冻结项目自有真实章节 fixture 2.1、稳定句段定位、正式人物名单、恢复与脱敏结果契约 | 主代理独占 `tests/fixtures/narration/chapter-e2e-v2.json`、`scripts/tts/validate_chapter_e2e.py`、`tests/narration/test_validate_chapter_e2e.py` 和本文 | 原创自动／人工双链均超过 500 字符；`expected_formal_speakers` 精确为林晚／沈川；双人物域分析精确得到 0 blocker 与预期 3 blocker；校验器默认无网络；视口只接受 1920×1080／2560×1440 与助手收起／展开的精确四组合，其他组合拒绝；恢复不宣称数据库清零 |
| T4-K-X | PAR-C | 实现固定 loopback/API 前缀的真实 HTTP executor | 消费 T4-K-C；独占 `scripts/tts/chapter_e2e_executor.py`、`tests/narration/test_chapter_e2e_executor.py` | 自动／人工链、Manifest/Range 与恢复均由 fake HTTP 完整证明，未注入探针时 fail-closed |
| T4-K-P | PAR-C | 冻结浏览器与 Sidecar 指标报告的严格导入/绑定契约 | 消费 T4-K-C；独占 `scripts/tts/chapter_e2e_probes.py`、`tests/narration/test_chapter_e2e_probes.py` | 只接受同 scope/run/Edition 输出 hash 且同一 run 内齐全的精确四组合报告；伪造、过期、缺任一组合或缺探针均拒绝 |
| T4-K-A | PAR-C | 以显式 PostgreSQL 只读事务核验专用 scope、旁白／林晚／沈川的 exact semantic voice mapping、Edition、job、render 与 ModelRun 权威链 | 消费 T4-K-C/X；独占 `scripts/tts/chapter_e2e_runtime_audit.py`、`tests/narration/test_chapter_e2e_runtime_audit.py` | 非 PostgreSQL、非只读事务、exact-name 人物／dedicated binding／逐 Segment 冻结音色、scope／权利／版本／模型 fingerprint 任一不一致均 fail-closed；仅出现三个互异 version 但人物对错音也必须失败；不读取正文或音频字节 |
| T4-K-L | SER/MUTEX | 固定真实启动入口，在任何数据库／执行器装配前持有三把私有锁，并向外部探针发布无正文／无原始 ID 的运行绑定握手 | 消费 T4-K-C/X/P/A；主代理独占 `scripts/tts/chapter_e2e_probe_request.py`、`scripts/tts/run_chapter_e2e_real.py`、`tests/narration/test_chapter_e2e_probe_request.py`、`tests/narration/test_run_chapter_e2e_real.py` | CLI 不接受任意 import、shell 或数据库 URL；token、三锁、探针报告和私有工作目录均须位于仓库／已安装 PawApp 根之外；三锁必须绝对路径、`0600`、当前 uid、单硬链接、非符号链接且全程非阻塞独占；报告等待前只在仓库外 `0700` 目录创建一次 `0600` 脱敏握手，busy／旧握手均 fail-closed |
| T4-K-V | SER/MUTEX | 冻结隐藏 validation 安全信封：同值私有 token、单 novel/document、24 小时 expiry、HTTP 二次 scope、worker 精确领取和负向 tier 探测 | 消费 T4-K-C/X/L；主代理独占 `backend/narration/release_gate.py`、`validation_access.py`、`production_runtime.py`、`jobs.py`、`scheduler.py`、`backend/app.py`、provisioner、QwenPaw 安装／验证脚本及对应测试；共享入口／scheduler 串行汇合 | product/validation、validation/reference 均互斥；host token 位于宿主仓库外私有路径，container token 只位于既有 secret volume，token 不进 env/URL/log/evidence；无／错／重复 token 的三类 T4 路由均 `404 + no-store` 且 overview 精确 T2；正确 token 仅同 novel scope 的 overview 与 exact novel/document 资源临时 T4；worker 仅处理 exact novel/document 的允许 job，到期后不再开新领取／维护事务 |
| T4-K-D | SER/MUTEX | 在永久隔离专用测试小说中使用已确认三项：旁白 Zhiming、沈川 Junhao、林晚 Xiaoyu，建立可恢复基线 | 消费 T4-PRESET-INT/T4K-RF；持有 `LOCK-T4-K-DATA`；不得使用既有用户小说；不得再次请求选声或回退旧映射 | 三个 exact 中文 preset ID、official provenance、locked/accepted、语义绑定、设置、章节归属和 baseline Edition 均可复核；不向 Git 写音频/正文／prompt codes／模型 |
| T4-K-Q | SER | 对 T4-K-D 做只读、脱敏、fail-closed 就绪审计 | 消费 T4-K-C/A/V/D；独占 `scripts/tts/chapter_e2e_readiness.py`、`tests/narration/test_chapter_e2e_readiness.py`；读取私有 attestation、现有 PostgreSQL 与三把锁 | 输出只能是 `HOLD + NOT_READY/READY_FOR_OPERATOR_REVIEW`；精确 Zhiming/Junhao/Xiaoyu 三角色语义绑定、同 manifest/model fingerprint、fixture、基线、四桌面组合和三锁任一缺失均给稳定缺失码；不要求 reference 媒体或商业／克隆审批，不写 DB／文件、不启动模型、不翻 capability |
| T4-K-O | SER | 发行一次性、限时、run/scope/fixture/四视口/三锁绑定且经作者显式复核的 `moss-tts-t4k-operator-envelope/1.0`，并由正式 launcher 在任何真实写请求前强制重跑 Q、核对并原子认领 | 消费 T4-K-Q；主代理独占 `scripts/tts/chapter_e2e_operator_envelope.py`、`scripts/tts/run_chapter_e2e_real.py`、对应测试；只读复用 readiness；不得把 raw scope、nonce、路径或 attestation 写入 stdout／证据 | 无 envelope、旧／未来／过期 envelope、run/scope/fixture/case/duration/视口/锁不一致、未写作者确认、Q 不再 ready、同 envelope 二次非恢复运行均在数据库写入／executor 装配前失败；`--resume` 只接受同一已认领 run |
| T4-K-S | PAR-C | 补齐三锁、probe report、listening record 等全部私有运行文件的统一身份与路径门禁 | 消费 T4-K-C/P/L；独占 `scripts/tts/chapter_e2e_probes.py`、`scripts/tts/validate_chapter_e2e.py` 及各自测试；launcher 中锁路径最终由 T4-K-O 主 Owner 汇合 | 文件须位于仓库及已安装 PawApp 根之外的当前 uid `0700` 目录，且为当前 uid `0600`、单硬链接、普通文件、无符号链接；读取前后身份一致，错误只返回稳定码且不泄漏路径或内容 |
| T4-K-RCV | SER/MUTEX | 把 operator claim、baseline fence、技术结果、人工听检与 finalization 串成 crash-safe 单调恢复链 | 消费 T4-K-O/S；唯一集成 Owner 独占 `scripts/tts/validate_chapter_e2e.py`、`chapter_e2e_executor.py`、`chapter_e2e_operator_envelope.py`、`run_chapter_e2e_real.py` 及四组对应测试；不得与其他代理并改这些共享文件 | recovery 使用 generation／previous digest；所有权威写前持久化 old/next fence；一代差只在完整 run/scope/fixture/binding 验证后对齐；旧代、跨 run、错误 binding、输出目录替换、finalization 崩溃均不能错误删除恢复证据或宣布完成 |
| T4-K-BR | PAR-C | 实现固定、不可自由注入的本地 Node/Playwright 浏览器／Sidecar collector 与可复核证据摘要绑定 | 消费 T4-K-P/O/S；独占 `scripts/tts/chapter_e2e_collector.py` 与固定 controller-node observer 及对应测试；浏览器依赖只走冻结本地执行器／固定公开页面，不接触数据库、模型目录或正文文件 | 只消费同一次私有 probe request；精确采集四组合、console/network/截图摘要、Range/ETag、latest-wins、pending gap、零编辑 TTS 写入和 Sidecar 指标；synthetic/fake 只能验证协议，不能产生 PASS；报告保存布尔／计数／耗时／SHA-256 等脱敏证据，不以签名、public root 或 OS service 作为本地 PASS 前置 |
| T4-K-HL | PAR-C | 为同一 run 发行脱敏听检请求并提供独立 finalize 导入，使作者能在结果落盘后完成三角色与相邻句段听检 | 消费 T4-K-C/O/S；独占 `scripts/tts/chapter_e2e_listening.py`、对应测试；不代替作者作主观裁决 | 请求绑定输出 hash、旁白／林晚／沈川和相邻接缝；finalize 只接受当前 uid 私有文件与同 run 决定，缺人类结论保持 `HUMAN_LISTENING_PENDING`，脚本不得根据时长或解码成功伪造 PASS |
| T4-K-TD | SER | 固定验证隐藏 validation teardown、token 销毁、公开 T2 回落与未来 product 放行 fail-closed 矩阵 | 消费 T4-K-O/BR/HL；主代理独占 `scripts/tts/verify_chapter_e2e_teardown.py`、对应测试及 T4-GATE 证据；真实容器操作仍持有 `LOCK-QWENPAW` | 无／错／旧 token 均为 `404 + no-store`、overview 精确 T2、worker 不再领取目标任务、token 双副本销毁身份一致；未有 T4-K-I PASS 时 verifier 必须拒绝 product=true，不能自行翻 capability |
| T4-K-R | MUTEX | 在唯一固定宿主运行真实 Nano、浏览器、30 分钟与人工听检 | T4-K-C/X/P/A/L/V/D/Q/O/S/BR/HL 全部通过且作者复核；持有 `LOCK-NANO`、`LOCK-BROWSER`、`LOCK-T4-K-DATA` | 真实技术结果与听感记录齐全；运行后必须执行 T4-K-TD，产品开关仍由 T4-GATE 单独裁决 |
| T4-K-I | INT | 汇合脱敏证据并作 PASS／HOLD 裁决 | T4-K-R | 无未解释 P0/P1，恢复复核完成，形成 T4-GATE 输入 |

2026-08-27 用户裁决触发以下 official-preset re-freeze 波次。它们属于本 T4 文档内部的稳定工作包；共享 DTO、migration、入口和本文仍由主代理唯一集成，冻结完成后才允许独立 Owner 并行：

| 工作包 ID | 标记 | 唯一目标 | 精确 Owner／禁止范围 | 验收与汇合 |
| --- | --- | --- | --- | --- |
| T4-PRESET-RF | SER | 历史冻结 18 项底层 metadata catalog；当前产品 re-freeze 为六项中文投影、`OfficialPresetProvenance`、API、capability、Sidecar exact mapping 和 T4-K 证明模式 | 主代理独占本文、公共 DTO、migration 决策和入口；禁止下载/写入模型、prompt codes、音频或操作数据库 | 底层 18 项仅兼容；产品只接受六项中文；新记录 `source_kind=official_preset`；不新增审批状态机 |
| T4-PRESET-BE | PAR-C | 实现后端 catalog、中文产品投影、preset version/preview/lock/worker provenance 与 capability | `backend/narration/official_presets.py`、`schemas.py`、`settings_api.py`、`voices.py`、`privacy.py`、`voice_product.py`、`worker.py`、必要的单一新 migration 及对应后端测试；与 SC/FE/K 不并写文件 | 底层 18 exact ID 可校验；产品 API/actionable 精确六项中文；商业字段不阻断；缺 manifest/prompt hash/model fingerprint fail-closed |
| T4-PRESET-SC | PAR-C | 让生产 Sidecar 只接受 external exact preset ID，并对已验证 manifest 逐行映射 prompt codes | `backend/narration/sidecar_server.py`、`docker/tts-sidecar/verify_runtime.py` 及对应 Sidecar/runtime 测试；只读消费 model lock；禁止修改模型资产、lock revision 或保存 prompt codes | `onnx.<voice>` 仅在固定 manifest 行存在、prompt codes 非空且 inventory 完整时转换；未知、缺失、重复、hash/fingerprint 错误给稳定技术错误；18 项短句 fake/semantic 测试覆盖 |
| T4-PRESET-FE | PAR-C | 实现六项中文官方预设的展示、选择、真实试听、锁定和人物直接绑定 UI | `frontend/src/narration/contracts.ts`、`api.ts`、`voice-source-panel.ts`、`voice-source-workspace.ts`、`character-voice-panel.ts`、`reading-overview.ts` 及对应测试；禁止修改根入口/样式聚合 | 精确六项中文可见且可操作；其余 12 项不出现在当前产品 UI；runtime 技术 HOLD 与产品范围分离；四桌面组合进入真实浏览器验收 |
| T4-PRESET-K | PAR-C | 把 T4-K readiness/runtime audit/operator envelope 从 uploaded-only 改为 official-preset 证明模式；上传音色仅保留为独立产品来源，不再是 T4-K 验收输入 | `scripts/tts/chapter_e2e_readiness.py`、`chapter_e2e_runtime_audit.py`、`chapter_e2e_operator_envelope.py`、fixture 与对应测试；不改真实数据库 | 三个互异 official preset 可 READY，无 reference link/六媒体也可通过；不得退回三份上传录音前置，不得用历史 controller authority 实验阻断，也不得伪造真实 PASS |
| T4-PRESET-DOC | PAR | 更新当前索引、能力矩阵和 T4-K 说明；历史 T0-E 与 18 项本地授权审计只加 supersession/非目标标识 | `README.md`、`docs/README.md`、`docs/开发文档/README.md`、施工 README/capability matrix/T4-K README；禁止删除或重写历史 hash 证据 | 当前产品精确六项中文；商业／多语言／导出／authority 非目标可追溯；文档链接、状态和日期通过检查 |
| T4-PRESET-INT | INT/GATE | 主代理审查越界、迁移顺序、共享入口和包清单，运行后端/前端/T4-K/打包回归并决定下一 ready set | 消费 BE/SC/FE/K/DOC；主代理唯一 Owner；Git 暂存/提交/推送仍须用户明确要求 | 自动化与 `git diff --check` 通过；无模型/音频/prompt codes 入 Git；只解除 official-preset 数据来源 HOLD，不自动解除真实 Nano 章节、30 分钟、四组合或听感 HOLD |

当前 ready-set 状态（2026-08-28）：历史 `T4-PRESET-RF/BE/SC/FE/K/DOC/INT`、`0022/0023`、真实 baseline 与重复句段安全 fanout 均已形成证据；正式数据库随后升级至 `20260828_0024`。权威绑定为旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao`。旧 v2 run `270ea179-e3cf-4095-a928-56b414070719` 保持 `SUPERSEDED_V2_RUN_HISTORY`；canonical v3 run `bb03ccaf-4681-490a-b987-84bec9199b3b` 已完成真实技术链、作者完整章节听检、同 run resume／teardown，长期产品模式也已验证。最终文档、包内容、回归和 T4-GATE 一致性收口已经完成，当前 T4 ready set 为空；不等待重新选声、上传录音、商业审批、OS signing service 或 public trust root。

AUTH-3/AUTH-6 采用本 T4-K 内部的本地固定执行器 ready set，不建立跨开发文档总矩阵。作者／操作员本人是本机信任根；Node/Playwright observer 只能由冻结 launcher 启动，调用方不能选择 URL、browser、selector、viewport、报告内容或 PASS。共享 observer contract、报告事务和 launcher 参数只能由对应唯一 Owner 修改；token、正文、原始 ID、截图／媒体内容和私有运行文件均禁止进入 Git、插件包或普通日志。历史签名实验所涉及的私钥、`SSH_AUTH_SOCK` 与签名文件同样不得进入 Git，但它们不是当前施工输入。

| 工作包 ID | 标记 | 唯一目标 | 精确 Owner／禁止范围 | 验收与汇合 |
| --- | --- | --- | --- | --- |
| T4-K-AUTH-1 | SER/GATE | 冻结个人单用户本地信任模型、威胁边界和不得宣称的证明能力 | 主代理独占本文和 T4-K 证据说明；只读消费历史签名审计；禁止生成正式私钥、安装服务或扩大 QwenPaw 权限 | 明确作者／操作员是本机信任根；本地报告只支持可复核验收，不宣称远程、第三方或密码学 provenance；六个中文官方预设不受历史商业或 authority 结论阻断 |
| T4-K-AUTH-2 | PAR-C | 固定 Node/Playwright observer contract 与脱敏报告 schema | 独占 controller-node contract/observer/CLI 及对应测试；不得修改 Python、前端、后端或调用方输入面 | validation token 只从固定继承 FD 读取且不输出；loopback 请求只注入一条 validation header；调用方不能注入 URL/browser/selector/viewport；报告只含布尔、计数、耗时和 SHA-256 |
| T4-K-AUTH-3 | SER | 把固定 Node/Playwright 定义为作者／操作员本地执行器，并完成真实交互、布局与媒体观测 | 消费 AUTH-2；固定 Edge、Node、Playwright、公开页面和精确四 actual viewport；禁止调用方提交 observation/evidence/PASS | 实际观测播放器、CodeMirror/textarea、段落／光标跳播、latest-wins、播放暂停倍速 seek、编辑零 TTS 写、Range/ETag/304/206/416 与安全布局；不具备条件的项必须 `not_observed`，不得伪造 true |
| T4-K-AUTH-4 | SER | 将本地 observer 摘要、Sidecar 指标、request/run/scope/Edition 和输出 hash 绑定到原子 collector 报告 | 独占 collector 及测试；消费 AUTH-2/3；不得接受自由报告、路径、正文、媒体或 token | canonical run_id、scope/fixture、模型／Edition／Manifest／输出 SHA-256、四 actual viewport 与 30 分钟链一致；跨 run、缺项、漂移、篡改或 synthetic 当真均 fail-closed；不要求 SSHSIG/public root |
| T4-K-AUTH-5 | SER | launcher 在任何真实写入前完成固定本地执行器、operator envelope、私有文件和同次 run 绑定检查 | 独占 launcher 及测试；消费 AUTH-2/4；不得改 collector schema | 一次性目录 `0700`、文件 `0600`、canonical run_id、scope/fixture、三锁、四视口、token 秘密保护和恢复合同全部通过；不再调用或等待 signing preflight、active root、OS service 或 key ceremony |
| T4-K-AUTH-6 | INT/GATE/MUTEX | 主代理汇合固定本地执行器、真实四组合、30 分钟、人工听检、恢复与 teardown | 主代理唯一 Owner；`LOCK-BROWSER`、`LOCK-NANO`、`LOCK-T4-K-DATA`、`LOCK-QWENPAW`；暂存/提交/推送仍需用户明确要求 | 消费已确认并绑定的 Zhiming/Junhao/Xiaoyu，完成基线与真实章节；四组合、播放器／编辑器、媒体链、30 分钟、模型／Edition／Manifest／输出 hash、人工听检、恢复、teardown 和宿主非回归全部可复核；无私密 token、音频、模型或正文入 Git |

当前 AUTH 状态：个人单用户本地信任模型已经裁决；三个 official preset 已 confirmed／locked／accepted／bound，baseline Edition、真实四桌面浏览器、播放器、CodeMirror、跳播、播放控制、latest-wins、媒体 HTTP、编辑零 TTS 写、固定 31 点／30 分钟、作者完整章节听检、同 run resume／teardown 均已完成。作者另已确认系统中文输入法至少输入两个汉字正常；自动 supplemental envelope 未生成并保持非阻断。代码中遗留的 signing／authority 实验只作被否决历史候选，必须旁路且不得进入 PawApp 产品包。

> **2026-08-28 历史 v2 ready-set 快照：**run `270ea179-e3cf-4095-a928-56b414070719` 当时完成浏览器观察、固定 31 点／30 分钟技术门禁、报告导入与基线恢复，随后因人工听检失败而保持历史 HOLD；不得把它称为当前 canonical run。当前 v3 权威状态与剩余项以本文首段及 [v3 官方默认参数真实章节技术验收](证据/MOSS-TTS-Nano施工/T4-K/v3官方默认参数真实章节技术验收-2026-08-28.md) 为准。

### AUTH-3 历史签名／OS service 审计（`REJECTED_FOR_LOCAL_PRODUCT / NON_BLOCKING / NOT_IMPLEMENTED`）

本附录只保留 2026-08-27 第二轮红队和官方资料审计的历史原文、链接与反事实设计，用于说明：如果未来产品改成多人、远程或需要向不信任本机作者的第三方提供来源证明，独立身份和签名边界会涉及哪些问题。用户已经否决把该威胁模型用于当前个人单用户本地产品；以下拓扑、协议、状态机、工作包、安装路径和 key ceremony 全部是**已否决、未批准、未实现、非阻断实验候选**，不进入 current ready set，不是 T4-K、AUTH-3、AUTH-6 或 T4-GATE 的前置，也不得用其中的 `HOLD` 码阻止本地选择、试听、绑定、合成、播放或验收。它不代表已经安装服务、创建系统账户、生成 key 或激活 public root。2026-08-27 当时的只读基线为 macOS 26.5.2 arm64、Swift 6.3.3、仅 Command Line Tools，有效 code-signing identity 数量为 0；这只说明反事实方案本身尚不具备实施条件。

Apple 的现行边界支持以下判断：LaunchAgent 运行在登录用户上下文，适合访问 GUI；LaunchDaemon 运行在 system context，不能访问 WindowServer，不能独自承担当前 `headless:false` 的真实 Edge 验收（[Designing Daemons and Services](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/DesigningDaemons.html)）。XPC listener/connection 可以按 peer code-signing requirement 丢弃不符合身份的请求（[xpc listener peer requirement](https://developer.apple.com/documentation/xpc/xpc_listener_set_peer_requirement)、[xpc connection peer requirement](https://developer.apple.com/documentation/xpc/xpc_connection_set_peer_requirement)）；稳定 requirement 必须同时考虑 identifier、Team／本地签名根与升级身份，而不能只看进程名或脚本路径（[TN3127](https://developer.apple.com/documentation/Technotes/tn3127-inside-code-signing-requirements)）。macOS 13+ 的 `SMAppService` 可以注册 app bundle 内的 LaunchAgent／LaunchDaemon，Daemon 仍需管理员批准（[SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice)、[register](https://developer.apple.com/documentation/servicemanagement/smappservice/register%28%29)）。OpenSSH 的 `ssh-add -c`／`-t` 只是每次确认与短时约束，不能替代 OS 身份隔离（[ssh-add](https://man.openbsd.org/ssh-add.1)、[ssh-agent](https://man.openbsd.org/ssh-agent.1)）。

基于上述事实，当时审计给出的反事实候选拓扑不是单一 Python daemon，而是同一个宿主控制面的两个 OS 组件；当前产品不采用该拓扑：

```text
固定宿主操作员／signed client shim
              │ 只提交四项冻结输入；不能提交 artifact/evidence/PASS
              ▼
┌──────────────────────────────────────────────────────────────┐
│ signed Controller Agent（登录用户域 / LaunchAgent）          │
│ 固定 Edge + sealed Python/Node closure；browser/runtime 观察  │
│ request/preflight 三次身份核验；evidence/host binding；无私钥 │
└───────────────────────┬──────────────────────────────────────┘
                        │ 双向 XPC
                        │ exact peer code requirement + challenge
                        ▼
┌──────────────────────────────────────────────────────────────┐
│ Signer Daemon（system domain / 独立非登录 service UID）       │
│ service-owned encrypted Ed25519；fresh ssh-agent -c -t 120   │
│ 仅签 frozen preflight/report namespace；socket/key 不外泄     │
└───────────────────────┬──────────────────────────────────────┘
                        │ public SSHSIG only
                        ▼
Controller Agent 立即 public verify → fixed collector finalize
                        │
                        ▼
QwenPaw/PawApp：只保留 public verifier/trust metadata/消费者
```

选择两个组件是因为单独 LaunchAgent 与 PawApp 同 UID，`0600` 文件、随机 socket、普通 UDS peer UID、独立进程名或 Python private factory都不能区分同 UID 代码；单独 LaunchDaemon 又没有 GUI 会话，无法运行当前真实 Edge。Controller Agent 必须是原生签名 broker，不能把 Python／Node 解释器的签名误当成脚本身份；现有 Python/Node host closure 只能作为管理员所有、普通用户不可写、code receipt 固定的 immutable release，由 broker 通过私有 pipe 调用。Signer Daemon 必须以独立非 root、非登录、非 admin 的 service UID 运行；root 只用于受控安装／注册，不能成为长期 controller 身份。

外部业务输入严格只有四项，协议固定 canonical JSON、最大 4 KiB、拒绝重复键／未知键／尾随字节／非 canonical UTF-8；`schema_version` 是固定元数据，不算调用方业务参数：

```json
{
  "schema_version": "moss-tts-t4k-controller-ipc-request/1.0",
  "probe_request_path": "/absolute/private/path/probe-request.json",
  "novel_id": "canonical-lowercase-uuid",
  "document_id": "canonical-lowercase-uuid",
  "validation_token": "43-128-char-base64url"
}
```

`probe_request_path` 只允许受保护 spool 下固定 leaf，优先由已认证 client 传已经安全打开的 directory FD／opaque handle，不能退化为自由路径。服务不得接收或允许覆盖 artifact、observation、evidence、hash、verdict、PASS、browser URL/path、selector、signer、policy/key path、timeout、clock、command、shell 或数据库 URL。validation token 只存在于 IPC body 与进程内存，DTO `repr=False`；不得进入 URL、argv、环境、Unified Log、journal、进度、响应、证据或异常。

同一连接内由 Agent 完成 preflight 与 report 两阶段全生命周期：验证固定 operator envelope／scope／fixture → 内部构造并请求 Daemon 签 preflight → `O_EXCL` 发布 preflight → 等待 launcher 产生固定 request → 安全加载 request → 启动 Edge 四组合 → 采集 30 分钟 runtime → 从 raw observation 组装 evidence → 构造 canonical report binding → 签名前复核 request/source/Edge/Node/policy/key/time → Daemon 通过已认证 XPC 与作者确认后签名 → Agent 立即用 public verifier 验签 → 取得新的 `commit_now` 并第三次复核 request/preflight/source/Edge/policy/key → fixed collector 原子 finalize → `SignedCollectorReportGuard` read-back → journal `fsync(COMMITTED)` 后才返回两个 public report SHA。外部永远拿不到“签任意 bytes/artifact”的端口。

服务自有状态机固定为：

```text
ACCEPTED → PREFLIGHT_SIGNED → OBSERVING → READY_TO_SIGN
         → SIGNING → SIGNED_PENDING_COMMIT → COMMITTED
                                      └──→ HOLD
```

operation key 必须绑定 preflight nonce/payload SHA、probe request SHA、request/run/scope fingerprint；同 operation 只允许一个活动实例。活动重复请求返回 `CONTROLLER_IPC_BUSY`；完全相同且已 `COMMITTED` 的请求只幂等返回旧 digest；`SIGNED_PENDING_COMMIT` 重启后只能用原签名继续 finalize，禁止二次签名；同 nonce/run 跨目录或不同内容重放返回 `CONTROLLER_REPLAY_HOLD`。IPC handshake 5 秒、私有加载 10 秒、签名命令 30 秒、agent lifetime 120 秒、整体 45 分钟硬上限；30 分钟观测只用 monotonic deadline，UTC 只用于证据时间。

公开响应只允许 `committed + 两个 SHA-256` 或 `hold + 稳定码 + retryable`，不返回路径、ID、token、报告、截图、指标、签名、stderr 或 traceback。稳定码冻结为：`CONTROLLER_IPC_PROTOCOL_INVALID`、`CONTROLLER_IPC_PEER_UNAUTHORIZED`、`CONTROLLER_IPC_BUSY`、`CONTROLLER_IPC_TIMEOUT`、`CONTROLLER_IPC_DISCONNECTED`、`CONTROLLER_AUTHORITY_HOLD`、`CONTROLLER_REQUEST_INVALID`、`CONTROLLER_REQUEST_DRIFT`、`CONTROLLER_REPLAY_HOLD`、`CONTROLLER_BROWSER_HOLD`、`CONTROLLER_RUNTIME_HOLD`、`CONTROLLER_LAYOUT_HOLD`、`CONTROLLER_PENDING_GAP_HOLD`、`CONTROLLER_BINDING_HOLD`、`CONTROLLER_SIGNING_DECLINED`、`CONTROLLER_SIGNING_HOLD`、`CONTROLLER_FINALIZE_HOLD`、`CONTROLLER_COMMIT_CONFLICT`、`CONTROLLER_INTERNAL_HOLD`。

以下是被用户否决为当前产品前置的历史提案波次，仅为审计可追溯而保留；这些工作包不进入 ready set，也不需要用户批准后再推进当前 T4：

| 工作包 ID | 标记 | 唯一目标与精确 Owner | 前置／禁止范围 | 退出证据 |
| --- | --- | --- | --- | --- |
| AUTH-3A | SER/GATE | 主代理冻结本地签名身份、signed broker、dedicated service UID、双向 XPC 与 askpass callback 尖峰；拟新增 `host/macos-controller/README.md` 和只在 `/tmp`／`build` 的可丢弃尖峰 | 必须用户批准；禁止安装长期服务、创建正式 key／active root、改 QwenPaw；当前 0 个 signing identity 不能跳过 | macOS 26.5.2 上 Agent/Daemon 双向 peer requirement、取消/允许确认、锁屏/退出登录、崩溃与卸载尖峰通过；明确本地证书或其他稳定 identity 的升级合同 |
| AUTH-3B | PAR-C | Agent Owner 独占 `host/macos-controller/Sources/ControllerAgent/**`、sealed host closure receipt 与 Agent 测试 | 消费 3A 冻结 DTO；不改 Daemon/PawApp/collector/key | only-four-input；固定 Edge/Node/Playwright；pre/post identity；无私钥/agent socket；任意第五字段与 caller artifact 拒绝 |
| AUTH-3C | PAR-C/MUTEX | Daemon Owner 独占 `host/macos-controller/Sources/SignerDaemon/**`、service UID state 与 signer 测试 | 消费 3A；`LOCK-CONTROLLER-KEY`；不得长期 root、不得读正文/音频/token、不得生成正式 key | 只接受 exact signed Agent peer；两个 namespace；fresh `ssh-agent -c -t 120`；断线/cleanup/超时 fail-closed；普通用户读 key 失败 |
| AUTH-3D | PAR-C | IPC Owner 独占 `host/macos-controller/Sources/ControllerIPC/**` 与协议/模糊测试 | 只实现冻结 schema/error/state；不改业务 lifecycle | canonical framing、4 KiB、unknown/duplicate/trailing/slowloris、peer/challenge/replay/concurrency 全负测 |
| AUTH-3E | SER | Python integration Owner 把现有 lifecycle/host/evidence/browser/runtime/collector writer 拆为 service-only closure，并新增 public-only client/contract | `scripts/tts/chapter_e2e_controller_{client,ipc_contract}.py` 与对应测试；host-only 文件仍受 package denylist；不得把 signer/service 放 PawApp | PawApp 不 import lifecycle/host/signer/writer；服务内部 preflight→观察→签名→finalize；签名前后 source/Edge/request/policy/time 与 read-back 全闭环 |
| AUTH-3F | SER/MUTEX | 安装 Owner 构建独立 host app bundle，以 `SMAppService` 注册 Agent/Daemon，采用 immutable release 与 disabled-first 安装 | `LOCK-CONTROLLER-SERVICE`；管理员批准；不新增容器/数据库/mount；不改 QwenPaw 上游 | root-owned plist/release、service-owned state/key、无 symlink/world-writable、唯一进程/socket；注册失败保持旧 release/HOLD |
| AUTH-3G | SER/MUTEX | 作者另行批准后执行正式 key ceremony 与 public root 两阶段登记 | `LOCK-CONTROLLER-KEY + LOCK-QWENPAW`；3A–3F 与 P0 红队通过前禁止 | 先 public policy allow old/new build，再启用 service；public-only receipt；private key/passphrase/socket/token 零入日志/包/Git |
| AUTH-3H | INT/GATE/MUTEX | 主代理真实 30 分钟、四组合、崩溃恢复、升级回退、完整卸载与 QwenPaw 非回归 | `LOCK-CONTROLLER-SERVICE + LOCK-BROWSER + LOCK-NANO + LOCK-T4-K-DATA + LOCK-QWENPAW`；唯一集成/暂存/提交 Owner | P0/P1=0；旧 release 可回退；卸载先 authority HOLD 后停服务；PostgreSQL/卷/正文不变；形成 AUTH-6/T4-K-I 输入 |

历史候选安装设计曾要求使用新 release 目录、不原位覆盖且不使用可变 `current` symlink；候选布局为 `/Library/Application Support/AI小说世界2026/controller-service/releases/<build-sha256>/`、service state/key `/var/db/ai-novel-world-2026-controller/`、boot-ephemeral socket `/private/var/run/ai-novel-world-2026-controller/`。它还提出 `N/N+1/N+2` policy 升级与 authority→HOLD 后再卸载的顺序。这些路径和流程当前均不得创建或执行；保留文字仅用于未来若产品边界改变时重新立项，且任何未来方案仍绝不能删除 PostgreSQL、媒体、QwenPaw 数据卷或小说 revision。

历史 AUTH-3A 的 P0 清单包括：第五字段／caller artifact／伪 evidence/PASS、未授权 peer、同 UID PawApp 直读 key/直连 signer、有效 preflight 下替换 request seed、观察中替换 source 或另一 allowlisted Edge、byte-identical inode replacement、确认期间 policy/key 到期或撤销、签名后断线、`SIGNED_PENDING_COMMIT` 崩溃恢复不二签、token 零泄漏、签名成功但 read-back 失败不得 committed。P1 还列出 canonical framing、跨目录重放、并发 run、Browser/Sidecar 资源竞争、sleep/lock/logout、clock jump、stale/future `signed_at`、每个 journal state 的 kill -9、旧 release 回退与完整卸载。它们只属于被否决的第三方 provenance 威胁模型；当前本地产品复用其中仍有价值的秘密保护、路径身份、并发互斥和崩溃恢复测试，但不要求签名或 OS 服务。

现有候选代码已经实现部分独立且仍适用于本地验收的加固：`VerifiedBrowserObservation` 投影实际执行的 Edge/Node SHA；controller source build SHA 在观察前后重新计算；request/preflight 私有文件需安全读取；collector finalize 后再 read-back。这些能力在当前方案中用于本地漂移检测、可恢复性和证据一致性，不再围绕签名时点或 active authority 作产品门禁。browser/evidence/lifecycle 相关专项通过只证明相应自动化候选，不代替真实章节、四组合交互、30 分钟、人工听检或 teardown。

`T4-K-O` 冻结的操作员信封不是“输入一个确认字符串就放行”的替代门禁。固定发行器必须在现有 PostgreSQL 的 repeatable-read/read-only 事务中重新执行 Q；只有返回 `READY_FOR_OPERATOR_REVIEW` 且作者随后显式输入 `AUTHOR-REVIEWED-T4-K-READINESS`，才可在同一当前 uid、仓库外 `0700` 目录独占写入一个 `0600` 信封。`moss-tts-t4k-operator-envelope/1.0` 精确绑定 canonical run UUID、novel/document、fixture manifest SHA-256、automatic/manual case、30 分钟时长、精确四桌面组合、三把锁的 grant 与物理身份摘要、attestation 语义摘要、Q 脱敏报告摘要、至少 32 字节随机 nonce、UTC 秒级 issued/reviewed/expires 及自身 canonical fingerprint；有效期不超过 15 分钟。信封不含 token、正文、录音、媒体路径或数据库 URL，stdout／正式证据只允许稳定状态码和非秘密 schema，不回显 raw scope、nonce、路径或摘要。

正式 launcher 必须接受固定 `--operator-envelope-file` 和同一个显式 `--run-id`。fresh run 在 executor／token／任何真实写请求前重新读取 attestation、校验 scope/fixture/case/duration/四视口/锁与信封、重新执行 Q 并比对脱敏报告摘要；完成 token 与 13 个只读门禁后，直接执行固定本地 Node/Playwright readiness，并在固定中央 registry `/app/working.secret/ai-novel-world-2026/t4k-operator-claims/` 中按 run fingerprint 以 `O_EXCL` 创建 `0600` claim，通过同一中央 lease 串行维护。正常个人本地路径不得再调用 controller-authority 签名 preflight，也不得因空 public trust root、缺 key 或缺 OS service 返回 HOLD。claim 不位于 envelope 同目录，也不由调用者提供路径；普通 real 运行只接受“尚未 claim”。`--resume` 是失败后的基线恢复通道：它可在信封过期后跳过新的 Q 裁决，但只接受同一信封、同一 run、同一静态 scope/fixture/四视口/三锁绑定和既有 claim，且不得继续创建新的 Edition、job、ModelRun 或媒体；这样资产漂移或信封过期不会阻断恢复，反向组合一律失败。该 claim 保留到 T4-K-TD 完成，不能在失败后删除以绕过重放保护。它只防止误用、陈旧输入和同一作者账号下的非预期重放，不伪装成对本机作者、远程第三方或已攻陷账号的密码学证明。

T4-K 的测试对象必须是**永久隔离、可留下追加审计历史**的专用小说／章节；禁止在用户正在创作的小说上执行后再删除记录伪装回滚。`narration_requests`、ScriptVersion、Edition、job、ModelRun、Manifest、媒体引用和声音权利事件继续遵守不可变／no-delete 规则。恢复的冻结含义是：用 CAS 和单调递增版本恢复作者可见 working copy 内容与运行前 current Edition／script 指针，并验证正文 hash；本次测试新增的追加历史保留并在脱敏资源账本中登记。若运行前没有可恢复的 baseline Edition，真实 executor 必须在首个写入前拒绝，而不能生成后把 current pointer 留在新 Edition。私有恢复文件只允许位于受信本机、仓库外、权限 `0700/0600`、不受云同步或日志采集的目录；成功恢复后立即删除，失败时保留到人工恢复完成并复核 hash 后删除。

真实章节 fixture 不得复用 `benchmark_manifest.json`，也不得静态保存包含随机 ScriptVersion ID 的 `source_block_key`。v2 使用 `segment_ordinal + expected_source_local_hash` 稳定定位，executor 必须再核对来源 UTF-16 范围与服务器返回的 runtime `source_block_key`，不允许只凭序号修改。正式样例必须证明旁白加至少两名 active 人物、三个互异且 `source_kind=official_preset`、manifest/model fingerprint 一致的 locked/accepted voice version，以及至少一次未命中缓存的真实 Nano ModelRun；公共 API 无法证明的 ModelRun/voice-input 证据只能由窄只读审计投影或已批准测试库探针补齐，不能从“Edition ready”推断。

#### 18.0.6 阶段 T5：文字描述生成音色

> **当前状态：`DEFERRED_OUT_OF_CURRENT_COMPLETION`。** 本节仅保留历史设计，不进入当前 ready set、剩余工期、T4-GATE 或产品 capability；不得因它未实施而阻断六个中文官方预设的本地朗读。

| ID | 标记 | 本文工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T5-A | PAR-C/MUTEX | VoiceGenerator 受管后端、生命周期和资源锁 | T0-D go、T1-B/T1-GATE |
| T5-B | PAR-C | 人物卡资料到可编辑音色描述 | T2-GATE |
| T5-C | PAR-C | 多候选、试听、来源、不可变版本和私人音色库 UI | T2-A、T5-A API 契约 |
| T5-D | PAR/MUTEX | VoiceGenerator 样音到 Nano 克隆保持度与质量测试 | T5-A |
| T5-E | PAR-C | M4 不达标时隐藏入口和既有路径非回归 | T5-A–T5-D |
| T5-GATE | INT/GATE | 本阶段文字生音色产品化裁决 | T5-A–T5-E |

#### 18.0.7 阶段 T6：高级生产

> **当前状态：`DEFERRED_WITH_T6_D_CANCELLED`。** T6-D 章节／全书音频导出已被正式取消，不再施工、测试或设门禁。T6-F 中“防止误删权威媒体、显示磁盘不足、仅清理可达性明确的派生缓存”的最小子集并入当前 T4-GATE；其他高级生产工作包不进入当前完成范围。

| ID | 标记 | 本文工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T6-A | PAR-C | 人工确认的情绪音色变体 | T4-GATE |
| T6-B | PAR-C/MUTEX | 群体声音混合与听感 | T4-GATE |
| T6-C | PAR-C | 全书仅扫描/批量生成分离、逐章阻塞隔离、恢复、优先级和公平性 | T4-GATE |
| T6-D | CANCELLED | 章节／全书导出、拼接、导出 manifest/UI/API/测试均取消 | `SUPERSEDED_NON_TARGET`；不得恢复到 ready set |
| T6-E | PAR-C | 发音批量校对和可选 ASR 告警 | T4-GATE |
| T6-F | PAR-C | 音质报告、可达性 GC、配额和磁盘治理 | T4-GATE |
| T6-G | PAR-C | 明确开启的空闲预生成和显式 Edition 切换 | T4-GATE |
| T6-H | DEFERRED | 高级批量、恢复、音质、配额和隐私回归；不含导出 | 未来重新立项后方可执行 |
| T6-GATE | DEFERRED | 本阶段高级生产最终集成 | 不属于当前完成定义 |

### 18.0.8 子代理直接派发协议

本文的阶段表不是口头分工建议，而是正式施工的派发入口。主代理只能派发当前前置满足且已由上一阶段门禁列入 ready set 的工作包。当前已按 `T0-GATE → T1-DEP/T1-A…G → T1-GATE → T2-A → T2-B…H → T2-GATE → T3-A → T3-B…I → T3-GATE` 推进；T3-GATE 的 local-only 脚本 runtime 已通过，当前转入 T4 分批波次。`T4-DEP`、公共 DTO／状态机／媒体路径、migration 顺序、入口和本文继续由主代理持锁；其余工作包只能在对应前置和文件 Owner 冻结后派发。

每次派发必须完整填写以下施工卡；任一字段为空、允许写范围与其他活跃工作包重叠、或冻结输入尚未形成时，不得启动该子代理：

```text
工作包 ID：
唯一目标：
明确非目标：
允许修改的精确文件/目录：
只读文件/目录：
禁止触碰的共享文件与当前用户改动：
已冻结输入契约、fixture 与版本：
需要取得的共享资源锁：
必须运行的最小测试命令：
必须写入的证据文件：
交付给主代理的接线位置、风险、未完成项与回退说明：
```

派发和交付规则：

1. 一个活跃工作包只有一个写 Owner；Owner 表示文件和接口责任域，不绑定固定代理。后续代理只有在前一 Owner 已交付、主代理确认工作树边界并重新派发后，才能按表中顺序继续修改同一文件。
2. 子代理只改施工卡列出的路径。发现必须触碰共享入口、公共 DTO、迁移、依赖锁或另一工作包文件时立即停止写入，只向主代理返回所需变更和原因；不得自行扩大范围。
3. 子代理不得执行 `git add`、`git commit`、`git push`，不得分配 Alembic revision，不得操作正式数据库、真实用户小说、唯一 QwenPaw 安装状态、媒体清理或模型全局安装。主代理负责串行接线、迁移、真实运行状态、最终测试和 Git。
4. 每个实现 Owner 同时拥有本表指定的窄单元测试；专职 QA 工作包只写独立集成/回归测试文件，不与实现 Owner 并写同一测试。
5. 子代理返回“完成”只表示候选 diff 和证据就绪。主代理必须核对越界文件、测试原始结果、风险和未完成项，再决定接收、返工或丢弃候选。
6. 若开始施工时目标路径已有用户或其他专项未提交改动，主代理必须先登记冲突并暂停相应工作包；不得让代理靠事后大规模合并解决同文件竞争。
7. `PAR-C` 的代理只能消费已冻结契约，不得修改契约语义。需要变更时退回对应 `SER/GATE`，更新文档和 fixture 后重新形成 ready set。

每个工作包的唯一目标就是 18.0.1–18.0.7 对应行；同时继承第 3.2 节排除项和以下阶段非目标。派发卡可以继续收窄非目标，但不得放宽：

| 阶段 | 统一非目标 |
| --- | --- |
| T0 | 不建正式迁移、生产 API、产品 UI 或正式媒体；不把模型实验依赖装进 PawApp 运行环境 |
| T1 | 不做页面、说话人推断、真实章节合成或用户可见自动化；只建立共享底座 |
| T2 | 不分析正文、不自动冻结脚本、不生成正式 Edition 或接入章节播放 |
| T3 | 不合成音频、不修改权威正文、不让模型创建正式人物、不绕过 blocker |
| T4 | 不产品化 VoiceGenerator；取消全书批量与章节／全书导出；不做 ASR／群体混音 |
| T5 | 不逐句调用 VoiceGenerator、不静默替换锁定音色、不因该能力不可用而破坏上传/预设路径 |
| T6 | ASR 不写正文；GC 不删源资产/被引用资产；空闲准备默认关闭且不自动切换 Edition |

### 18.0.9 专属目录、共享文件和禁止范围

为避免把所有实现继续堆进现有大文件，T0-GATE 通过后采用以下专属目录。括号中的目录当前可不存在；只有其 Owner 工作包获批后才可创建。

| 路径 | 用途与所有权规则 |
| --- | --- |
| `backend/narration/`（新） | TTS 领域、模型适配、任务、脚本、音频和 API 的唯一后端包；按 18.0.11 的精确文件分配 Owner，不允许把相同逻辑复制回 `backend/services.py` |
| `frontend/src/narration/`（新） | 朗读设置、播放器、编辑器桥和专属样式；对外只通过 `index.ts` 导出冻结接口 |
| `tests/narration/`（新） | 后端单元、集成、迁移、恢复和安全测试；测试数据库必须与正式数据库隔离 |
| `tests/fixtures/narration/`（新） | 只保存有授权的短文本、schema fixture、参数和哈希清单；不提交用户小说、私人参考音频或模型权重 |
| `scripts/tts/`（新） | 可复现下载校验、基准、音频检查和 E2E 工具；不得拥有业务权威状态 |
| `prototypes/moss-tts-nano/`（新） | 仅阶段 0 原型；T0-GATE 必须列出保留、迁移或删除决定，生产代码不得运行时依赖该目录 |
| `docs/开发文档/证据/MOSS-TTS-Nano施工/`（新） | 每个工作包和阶段门禁的可复核证据根目录；二进制模型与正式音频不进入 Git |
| `moss-models/`、`novel-media/` | 受控挂载/运行数据，不是源码目录；模型、当前试听、句段 master 和网页播放缓存只记录 hash、来源和恢复信息，不由子代理提交；不新建导出文件 |

以下是共享热点文件的唯一写入顺序。除表中 Owner 外，所有子代理只读：

| 精确文件 | 唯一 Owner / 顺序 | 允许内容 |
| --- | --- | --- |
| `backend/models.py` | T1-D → T4-RC，均由主集成 Owner 串行 | T1-D 建立已冻结朗读 ORM；T4-RC 只允许增加 request 当前复核指针与不可变人工动作账本 ORM，不得追加临时 JSON 字段、第二套业务状态机或复写已有表语义 |
| `backend/migrations/versions/20260826_0010_narration_foundation.py` | 仅 T1-D；实施前先确认仍为下一合法 revision | 单一 TTS 基础迁移、升级和回退；若其他已批准迁移先落地，主代理先修订本文文件名和 `down_revision`，禁止产生第二个 head |
| `backend/migrations/versions/20260827_0020_narration_script_review_actions.py` | 仅 T4-RC 主集成 Owner；实施前确认 `0019` 仍是唯一 head，并持有 `LOCK-DB-MIGRATION` | 在现有 PostgreSQL 内增加 nullable request 复核指针、CAS 约束与不可变人工动作账本；不得新建数据库、容器、队列，不得改写 0010–0019 历史；upgrade／downgrade、旧行 fail-closed 和唯一 head 均须验证 |
| `backend/narration/__init__.py` | T1-A → T1-GATE → 后续相关 GATE，串行 | 初始包契约和已通过门禁的公开导出；实现代理不得越过门禁提前暴露模块 |
| `backend/narration/manifest.py` | T1-F → T4-D | T1 只实现持久领域骨架，T4 按冻结 Manifest v2/ETag 契约补齐；两个 Owner 不得重叠 |
| `backend/narration/requests.py` | T1-F → T4-A | T1 冻结持久 intent/idempotency/analyze-only 不变量；T4 只补产品编排/API，不得复制第二套 request 状态机 |
| `backend/narration/progress.py` | T1-F → T4-I | T1 建立持久进度，T4 增加播放器/局部重生成语义；保持同一数据契约顺序演进 |
| `backend/narration/script_versions.py` | T1-F → T3-GATE，主集成 Owner 串行 | T1 不可变基础保持权威；T3-GATE 只允许一次集中适配：按幂等键先分配并重放同一服务端 `script_version_id` 与 `version_number`，再派生 scene/segment ID；同一幂等动作必须重放原 `action_id`/`recorded_at`、approval 审计、requested/actual 模型指纹及 consent/model-run/HMAC 云端证据，不得二次生成。把 T3-A typed contract 无损投影到现有列及版本化 `casting_json`/`evidence_json`，持久化已有列 `evidence_summary`；reload 后要求不可变持久投影和现有 `immutable_hash` 完全相同，匿名人物的可变 `display_name`/显示置信度是实时元数据，不承诺历史 wire 字节级相同。反向 loader 必须拒绝未知 `casting`/`evidence` contract version；旧行只做兼容读取，不因读取静默重写。允许合法 `synthetic_pause` 使用空 `spoken_text`；blocker 清零的已验证修正子版本只能经 owner 走 `manual_after_review`，不得自动批准；loader 必须把每个授权父版本显式且互斥地分类为 `manual-review` 或 `verified non-review`，缺失、重叠或仅因“有 parent”而推断都必须 fail-closed。服务端须校验完整 revision 文本分区、ID scope 及精确关系对（character—binding、anonymous—binding、pool—slot），而 casting rule 必须精确绑定 `rule_id`—`version`—完整 decision—`segment_id`—源文局部哈希—speaker/casting digest，不得只校验彼此独立的 ID 集合。同时校验同作品 consent/model run/允许模型/HMAC 摘要与其精确 `segment_id`/源文局部哈希/speaker-casting digest，防止同一云端证据改绑另一决定；每个云端辅助句段还必须有 `W_CLOUD_ASSISTED_USED`。并校验历史匿名身份唯一性和 inherited override 的同作品、approved 人工来源、局部哈希、唯一锚点与 speaker/casting digest。v1 不开放缺少持久证据位的 `cloud_assisted` 场景边界来源。不得新增 migration、第二个哈希、第二套状态机或把 workflow failure 写入 script 行。 |
| `backend/narration/script_analysis.py`、`backend/narration/script_backend.py` | 仅 T3-GATE，主集成 Owner 串行 | 前者只编排已冻结的 T3-B/C/F/G 纯领域组件并调用唯一 typed persistence，不复制切分、判角、选角或复核规则；后者只做 SQLAlchemy session、固定本地 scope、API command/resource 适配。缺少持久动作键的 approve/patch/reanalyze、云端判角、casting-rule 精确重放及匿名人物高级生命周期必须显式 HOLD，不得返回伪成功。 |
| `backend/narration/script_versions.py`、`backend/narration/script_analysis.py`（T4-RC 补充 Owner，覆盖上两行的旧阶段终点） | T3-GATE → T4-RC，主集成 Owner 串行 | T4-RC 只能新增从 request 当前 `review_required` 父版本派生不可变修正子版本，以及分析首次物化／幂等重放时维护 request 复核指针的窄逻辑；必须重新分配并校验全部 scene/segment ID、完整 revision 分区、speaker/casting/evidence 关系及 immutable hash，旧父版本零写入，旧 request 缺指针 fail-closed，不得按“最新版本”猜测归属，不得降低任何 T3 校验。 |
| `backend/narration/script_backend.py`、`backend/narration/script_api.py`（T4-RC 补充 Owner，覆盖上行的旧阶段终点） | T3-GATE → T4-RC，主集成 Owner 串行 | 只在持久账本、request 指针、生产 policy 和同事务继续生产都可用时开放 patch/reanalyze/approve；GET 必须投影 request 当前候选；生产 runtime 不可用时动作继续 HOLD。任何成功响应都必须来自真实提交，不得返回伪成功。 |
| `backend/narration/authority_locks.py`（T4-RC 新增）、`backend/narration/voices.py`（T2-D → T4-RC 窄修正） | T4-RC 源 Owner → PostgreSQL 并发 Owner → 主代理复核，串行汇合 | `authority_locks.py` 是 request／document／Novel 与声音权威的唯一确定性锁计划；`voices.py` 只允许把公开 lock route 的反序 `Profile → Version` 校准为全局 `Version → Profile`，不得借此提前开放预设／上传／生成音色 capability。施工后必须以真实双事务跨路由交错证明无 `40P01` 且 HOLD 终态不变。 |
| `backend/narration/edition_service.py`、`backend/narration/narration_api.py`、`backend/narration/production_runtime.py` | T4-A → T4-RC → T4-GATE，主集成 Owner 串行 | 抽取自动路径与人工批准路径共用的 approved-request 生产步骤；批准、`review_required→queued`、唯一 Edition、segment/render/job 规划在同一 DB 事务内完成，Nano/Sidecar 只在提交后由既有 worker 调用；runtime policy 不可用时人工生产 fail-closed。`production_runtime.py` 同时是隐藏 validation 与公开 product 互斥、共用既有 backend/worker 且不新增基础设施的唯一运行态 Owner。 |
| `backend/app.py` | T1-GATE → T2-GATE → T3-GATE → T4-GATE → T5-GATE → T6-GATE，均由主集成 Owner 串行 | 路由、健康和生命周期的最窄接线；公开 T4 capability 必须同时通过 14.2.1 的 product/runtime/worker 就绪链，验证模式或任一健康条件不满足时 fail-closed；领域逻辑不得写入该文件 |
| `plugin.py`、`plugin.json` | 仅需要宿主生命周期/权限变化的 GATE 主 Owner | 只使用公开 PawApp/PluginApi 契约；不得改 QwenPaw 上游实现 |
| `frontend/src/index.ts` | T2-GATE → T4-GATE → T5-GATE → T6-GATE，主集成 Owner 串行 | 注册专属模块和清理函数；子代理不得直接接线 |
| `frontend/src/narration/index.ts`、`frontend/src/narration/styles.ts` | T2-GATE → T4-GATE → T5-GATE → T6-GATE，主集成 Owner 串行 | 汇出已通过门禁的模块并维护 TTS 局部样式；实现代理只返回新增导出和样式需求 |
| `frontend/src/narration/script-review-panel.ts` | T3-H → T4-H | T3 完成脚本复核，T4 增加与播放器共存和旧稿状态；保持单一 Owner 顺序 |
| `frontend/src/creative-center.ts` | 仅 T2-GATE | 创作中心“朗读”入口；必须保留现有作品卡和用户改动 |
| `frontend/src/workbench.ts`、`frontend/src/workbench-v2.ts`、`frontend/src/workbench-studio.ts` | T2-GATE → T4-GATE，按页面由主集成 Owner 串行 | `reading` 路由、人物声音页签、章节播放器/复核面板接线；同一时刻禁止其他专项并写 |
| `frontend/src/styles.ts` | 默认只读；确有宿主级共享样式时仅对应 GATE 主 Owner | TTS 局部样式优先写 `frontend/src/narration/styles.ts`，避免共享样式冲突 |
| `frontend/src/types.ts`、`frontend/src/api.ts`、`backend/schemas.py`、`backend/contracts.py` | 默认只读；公共边界确需变化时仅 GATE 主 Owner | TTS DTO 优先留在专属模块，禁止复制出第二份漂移契约 |
| `pyproject.toml`、`requirements.txt`、`requirements-dev.lock` | 仅 T1-DEP 的运行时依赖 Owner 串行 | 阶段 0 使用 `prototypes/moss-tts-nano/python-requirements.lock` 和隔离 `.venv`；只有 T0-GATE 选定且核实许可证/离线影响的依赖才能进入项目运行时 |
| `package.json`、`pnpm-lock.yaml` | 仅 T4-DEP 的正式编辑器依赖 Owner 串行 | 阶段 0 使用 prototype 自己的 `package.json`/lock；只有编辑器 ADR 选中的依赖才进入根项目，继续使用 `pnpm` |
| `compose.yaml`、`.dockerignore`、`docker/qwenpaw/Dockerfile`、`docker/tts-sidecar/**`（新）、`.env.example` | T1-DEP → T1-B 收口/T1-GATE 主集成 Owner，严格串行 | T1-DEP 只建立依赖 target、私网、受控挂载和未来 production target；T1-B 自有运行时通过红队后，主集成 Owner 才可覆盖 production 标签、冻结 source/protocol hash、补 token 双端文件挂载与无 Docker socket 的 supervisor，并重建固定镜像。`.dockerignore` 只最小放行 Sidecar 固定输入和窄 runtime 文件；不得复制整个 `backend/`、覆盖 QwenPaw 核心目录或删除持久卷。任何共享拓扑改动都须重跑 T1-DEP 非回归与真实 T1-B 门禁。 |
| `scripts/package_plugin.py`、`scripts/qwenpaw_lab_plugin.py`、`scripts/verify_qwenpaw_lab.py` | 各相关 GATE 的主验证 Owner；T4-K-V 期间仍由主代理串行 | 打包、安装、升级、卸载和公开契约验证；T4-K 只把固定 runner/readiness/授权 fixture 加入包并接入四开关、scope、expiry 与私有 token 文件编排，严禁打包或回显 token、attestation、锁、录音和私有报告；子代理只返回所需验证点 |
| 本文、TTS ADR 与所有 `T*-GATE.md` | 仅主代理 | 决策、状态、门禁、下一 ready set 和最终验收结论 |

本文为 T0 预留 ADR-0005 和 ADR-0006。真正创建前主代理必须重新执行 `rg --files docs/开发文档/ADR`；若编号已被另一项已批准工作占用，先串行更新本文的两个精确路径和所有引用，再派发 T0-GATE，禁止覆盖既有 ADR 或产生同号文件。

默认禁止触碰：`/Users/liujia/Documents/AI小说世界3/Data`；QwenPaw 上游核心、已安装包、私有路由/store/数据库；不属于本文的开发计划、ADR、Skills 和 Agent 配置；`frontend/dist/`、`build/`、`node_modules/`、`__pycache__/` 等生成目录；真实用户正文、revision、媒体、数据库 dump 和当前工作树中未分配的用户改动。

### 18.0.10 共享资源锁与冻结接口

| 锁 | 使用者 | 规则 |
| --- | --- | --- |
| `LOCK-NANO` | T0-B、T0-C、T4-B、T4-K、T5-D、T6-B | 同一时间只运行一个真实 Nano 重任务；代码和假适配器测试可并行 |
| `LOCK-VOICEGEN` | T0-D、T5-A、T5-D | VoiceGenerator 加载、MPS/CPU 基准和候选生成串行；默认不与 Nano 同时常驻 |
| `LOCK-MODEL-ASSETS` | T0-A、T0-E、T1-B、T5-A | 模型/音色下载、校验、版本切换和清单更新由单一 Owner 排队，禁止并发覆盖文件 |
| `LOCK-DEPENDENCIES` | T1-DEP、T4-DEP | 根 Python/Node 依赖、lock 和本地依赖安装状态由主代理串行；子代理不得自行安装未冻结依赖 |
| `LOCK-DB-MIGRATION` | T1-D、T4-RC、各迁移门禁 | 只允许专用测试库；备份、升级、回退和 schema 比对由主代理串行；T4-RC 0020 只能接在唯一 0019 head 后，不得并发分配 revision |
| `LOCK-QWENPAW` | 各安装/升级/卸载与真实宿主验证 | 唯一实验环境串行；测试结束必须恢复已登记状态 |
| `LOCK-BROWSER` | T0-F、T0-G、T2-H、T4-K、T5/T6 UI 验收 | 同一浏览器会话和同一小说状态串行，截图任务可在不同隔离会话并行 |
| `LOCK-MEDIA-GC` | T1-E、T6-F | GC/配额测试只能针对可重建测试媒体；删除前验证引用，禁止触碰用户媒体 |
| `LOCK-SHARED-FILE` | 所有共享热点文件 | 主代理登记文件、函数/页面区域、Owner 和起止时间；锁释放后下一 Owner 才能接手 |
| `LOCK-GIT` | 最终集成、提交、推送 | 仅主代理持有；阶段门禁不会自动授权提交或推送 |

并行编码前必须依次冻结以下接口；冻结产物既是后续 `PAR-C` 的输入，也是发生变更时必须退回的串行门禁：

| 冻结点 | 必须冻结的内容 | 权威产物 |
| --- | --- | --- |
| T0-GATE | `TTSAdapter`/`VoiceDesignAdapter` 能力契约、模型拓扑、音频规范、Manifest v2、ready-window、`NarrationEditorBridge`、复核策略和 blocker taxonomy | T0 报告、能力矩阵、`docs/开发文档/ADR/ADR-0005-MOSS-TTS本地运行拓扑与资源边界.md`、`docs/开发文档/ADR/ADR-0006-朗读编辑器与Manifest播放契约.md` |
| T1-D | ORM 表、枚举、唯一约束、外键、保留语义、迁移 revision 和回退路径 | `backend/models.py`、唯一 Alembic revision、schema fixture |
| T2-A | 设置/音色/绑定/试听 API、前后端 DTO、错误码、授权与能力状态 | `backend/narration/schemas.py`、`frontend/src/narration/contracts.ts`、契约测试 |
| T3-A | script/segment/scene/speaker/anonymous ID、UTF-16 范围、正文与 source block 无缺口/无重叠/不交错的完整分区、typed casting 精确关系及规则决定记录、情绪置信度、人工覆盖来源、云端 consent/model-run/模型指纹与 `segment_id`/源文局部哈希/speaker-casting digest 精确证据、父版本人工复核/非复核全量互斥分类、历史匿名身份唯一性、warnings/blockers（云端辅助句段强制 `W_CLOUD_ASSISTED_USED`）、唯一持久哈希投影和冻结状态机；wire 解析必须同时校验服务端权威根字段、精确关系、approval 审计与权威 revision 正文；v1 不开放缺少持久证据位的云端场景边界 | `backend/narration/script_contracts.py`、版本化 JSON fixture |
| T4-A/T4-D | Edition/render fingerprint、任务幂等、Manifest revision、Range/ETag、播放和局部重生成契约 | 领域契约测试、Manifest fixture 和播放 mock |
| 现行 T4-GATE | 六个中文官方预设、真实章节、网页播放器、CodeMirror 同步／跳播、恢复、最小缓存磁盘保护与非回归 capability | T4 阶段门禁记录和前后端 capability 测试；T5/T6 不在当前 ready set，T6-D 导出永久标记 `CANCELLED` |

### 18.0.11 T0–T6 精确工作包绑定

下表中的路径是对应工作包可写范围；未列出的路径一律只读。`（新）` 只表示获批施工时允许创建，不表示当前已经实现。每个工作包还只能写自己的证据目录 `docs/开发文档/证据/MOSS-TTS-Nano施工/<ID>/`。

为压缩表格，同一分号分组中不含 `/` 的后续文件名继承该分组第一项的目录。例如 `` `backend/narration/adapters.py`、`fingerprints.py` `` 精确表示两个文件 `backend/narration/adapters.py` 与 `backend/narration/fingerprints.py`，不授权整个目录。

“必须证据”列中 `<ID>/...` 和紧随其后的裸文件名都位于上述证据根目录的同一 `<ID>/` 下。七个阶段门禁文件固定为证据根目录下的 `T0-GATE.md` 至 `T6-GATE.md`；只有主代理可以创建或改写这些门禁文件。

任何包含前端产品实现的工作包还可独占一个同名局部样式片段 `frontend/src/narration/styles/<小写工作包ID>.ts`，例如 T2-B 只能写 `frontend/src/narration/styles/t2-b.ts`。这是唯一允许从 ID 推导的附加路径；不得修改其他片段。各 GATE 仅在 `frontend/src/narration/styles.ts` 中按已通过工作包顺序组合片段。

#### T0 文件、验证和证据

| ID | 允许修改的精确文件/目录 | 最小验收 | 必须证据 |
| --- | --- | --- | --- |
| T0-A | `scripts/tts/collect_dependency_inventory.py`；`prototypes/moss-tts-nano/python-requirements.lock`、`model-sources.lock.json`、`package.json`、`pnpm-lock.yaml`、`dependencies/`；本地生成但不提交的 `prototypes/moss-tts-nano/.venv/`、`node_modules/` | `DOC`；`.venv/bin/python -m venv prototypes/moss-tts-nano/.venv`；隔离环境按 hash lock 安装；`pnpm --dir prototypes/moss-tts-nano install --frozen-lockfile --ignore-workspace`；依赖 hash/许可证复核 | `T0-A/README.md`、`dependency-lock.json`、`licenses.md` |
| T0-B | `scripts/tts/benchmark_nano_topologies.py`；`prototypes/moss-tts-nano/topology/` | `BENCH-NANO`；真实运行持有 `LOCK-NANO` | `T0-B/README.md`、`metrics.json`、`failures.md` |
| T0-C | `scripts/tts/benchmark_nano_quality.py`；`prototypes/moss-tts-nano/quality/` | `BENCH-QUALITY`；固定样本人工听检 | `T0-C/README.md`、`metrics.json`、`listening.md` |
| T0-D | `scripts/tts/benchmark_voice_generator.py`；`prototypes/moss-tts-nano/voice-generator/` | `BENCH-VOICEGEN`；持有 `LOCK-VOICEGEN` | `T0-D/README.md`、`metrics.json`、`clone-retention.md` |
| T0-E | `tests/fixtures/narration/voice_pool_slots_v1.json`；本工作包证据目录 | `.venv/bin/python -m json.tool tests/fixtures/narration/voice_pool_slots_v1.json`、来源与授权逐槽复核、人工去重 | `T0-E/README.md`、`voice-pack-manifest.json`、`licenses.md`、`listening.md` |
| T0-F | `prototypes/moss-tts-nano/editor/editor-spike.ts`、`editor-spike.test.ts`、`vitest.config.ts` | `pnpm --dir prototypes/moss-tts-nano exec vitest run --config editor/vitest.config.ts`、IME/undo/decoration/gutter/Blob 实测 | `T0-F/README.md`、`matrix.json`、目标分辨率截图 |
| T0-G | `prototypes/moss-tts-nano/manifest-player/manifest-player.ts`、`manifest-player.test.ts`、`vitest.config.ts` | `pnpm --dir prototypes/moss-tts-nano exec vitest run --config manifest-player/vitest.config.ts`、pending gap/跳播/接缝浏览器实测 | `T0-G/README.md`、`manifest-v2.schema.json`、`queue-metrics.json`、截图 |
| T0-H | 本工作包证据目录，源码只读 | schema/API/状态机/权限威胁审查清单 | `T0-H/README.md`、`contract-review.md`、`threat-model.md` |
| T0-I | `scripts/tts/inspect_audio.py`；`scripts/tts/render_benchmark_report.py`；`tests/fixtures/narration/benchmark_manifest.json`、`authorized-texts.json` | 两个脚本 `--help`、fixture schema、假数据自测 | `T0-I/README.md`、`tooling-contract.md` |
| T0-GATE | 本文；`docs/开发文档/ADR/ADR-0005-MOSS-TTS本地运行拓扑与资源边界.md`、`docs/开发文档/ADR/ADR-0006-朗读编辑器与Manifest播放契约.md`；证据根目录的 `T0-GATE.md` | 汇总 T0-A…I，执行 `DOC`，逐项作七个 go/no-go | `T0-GATE.md`、`capability-matrix.md`、下一 ready set |

#### T1 文件、验证和证据

| ID | 允许修改的精确文件/目录 | 最小验收 | 必须证据 |
| --- | --- | --- | --- |
| T1-DEP | `pyproject.toml`、`requirements.txt`、`requirements-dev.lock`、`compose.yaml`、`.dockerignore`、`docker/qwenpaw/Dockerfile`、`docker/tts-sidecar/**`、`.env.example` | `.venv/bin/python -m pip check`、`docker compose config --quiet`、Sidecar 固定依赖 target 的 `docker build`/hash/import probe、确认 T1-B 源码缺失时生产 target fail-closed、`PKG`；持有 `LOCK-DEPENDENCIES`，不在 T1-B 前宣称服务健康 | `T1-DEP/README.md`、依赖/许可证/镜像与卸载回退清单 |
| T1-A | `backend/narration/__init__.py`、`contracts.py`、`adapters.py`、`fingerprints.py`；`tests/narration/test_contracts.py`、`test_adapters.py`；`tests/fixtures/narration/review-taxonomy-v1.json` | `PY:test_contracts.py test_adapters.py`；固定 scope、taxonomy 全 code/未知 code、fingerprint canonicalization | `T1-A/README.md`、契约 fixture、fake/real capability 对照 |
| T1-B | `backend/narration/runtime.py`、`model_assets.py`、`sidecar_server.py`；`scripts/tts/install_models.py`、`validate_sidecar_lifecycle.py`；`tests/narration/test_runtime.py`、`test_sidecar_server.py` | `PY:test_runtime.py test_sidecar_server.py`、下载校验 dry-run、固定 runner 重建 T1-DEP image 后真实 health/auth/bytes-stream/cancel/restart；持有 `LOCK-NANO` 的调用与其他真实模型测试串行 | `T1-B/README.md`、生命周期、Sidecar 窄协议与恢复记录、固定 runner SHA/结构化 transcript |
| T1-C | `backend/narration/jobs.py`、`resource_locks.py`；`tests/narration/test_jobs.py` | `PY:test_jobs.py` | `T1-C/README.md`、租约/重试/死信/公平性结果 |
| T1-D | `backend/models.py`；唯一 TTS migration；`tests/narration/test_migrations.py` | `MIG`、`PY:test_migrations.py` | `T1-D/README.md`、升级/回退/schema diff |
| T1-E | `backend/narration/media.py`、`storage.py`；`tests/narration/test_media.py` | `PY:test_media.py`；GC 用测试资产 | `T1-E/README.md`、Range/ETag/引用/GC 结果 |
| T1-F | `backend/narration/requests.py`、`snapshots.py`、`settings.py`、`script_versions.py`、`editions.py`、`renders.py`、`manifest.py`、`progress.py`、`services.py`；`tests/narration/test_domain_services.py` | `PY:test_domain_services.py`；request/analyze-only DB guard、approved 终态、stale 派生、Manifest 追加/CAS | `T1-F/README.md`、幂等与不可变性矩阵 |
| T1-G | `tests/narration/test_foundation_integration.py`、`tests/narration/test_crash_recovery.py` | `PY:test_foundation_integration.py`、`PY:test_crash_recovery.py` | `T1-G/README.md`、崩溃恢复和缓存复用结果 |
| T1-GATE | `backend/narration/__init__.py`；18.0.9 分配给 T1-GATE 的共享热点；`T1-GATE.md` | `PY-ALL`、`MIG`、`PKG`、相关宿主健康验证 | `T1-GATE.md`、已接收 diff、回退点、下一 ready set |

#### T2 文件、验证和证据

| ID | 允许修改的精确文件/目录 | 最小验收 | 必须证据 |
| --- | --- | --- | --- |
| T2-A | `backend/narration/schemas.py`、`settings_api.py`；`frontend/src/narration/contracts.ts`、`api.ts`；`tests/narration/test_settings_contract.py`；`frontend/src/narration/contracts.test.ts`、`api.test.ts` | `PY:test_settings_contract.py`、`FE:contracts.test.ts api.test.ts` | `T2-A/README.md`、字段/错误码/API 对照 |
| T2-B | `frontend/src/narration/reading-page.ts`、`reading-overview.ts`、`reading-page.test.ts`、`reading-overview.test.ts` | `FE:reading-page.test.ts reading-overview.test.ts`、`FE-CHECK` | `T2-B/README.md`、空/加载/成功/失败截图 |
| T2-C | `frontend/src/narration/character-voice-panel.ts`、`character-voice-panel.test.ts` | `FE:character-voice-panel.test.ts`、键盘测试 | `T2-C/README.md`、人物绑定与历史影响截图 |
| T2-D | `backend/narration/voices.py`；`tests/narration/test_voices.py`；`frontend/src/narration/voice-source-panel.ts`、`voice-source-panel.test.ts` | `PY:test_voices.py`、`FE:voice-source-panel.test.ts`，上传格式/授权/试听测试 | `T2-D/README.md`、上传与锁定版本证据 |
| T2-E | `backend/narration/voice_pool.py`、`backend/narration/resources/voice_pool_v1.json`；`tests/narration/test_voice_pool.py`；`frontend/src/narration/voice-pool-panel.ts`、`voice-pool-panel.test.ts` | `PY:test_voice_pool.py`、`FE:voice-pool-panel.test.ts`，24 槽位完整性校验 | `T2-E/README.md`、覆盖率和缺失降级截图 |
| T2-F | `backend/narration/pronunciations.py`；`tests/narration/test_pronunciations.py`；`frontend/src/narration/pronunciation-panel.ts`、`pronunciation-panel.test.ts`、`cache-panel.ts`、`cache-panel.test.ts` | `PY:test_pronunciations.py`、`FE:pronunciation-panel.test.ts cache-panel.test.ts` | `T2-F/README.md`、发音/停顿/缓存状态证据 |
| T2-G | `backend/narration/privacy.py`；`tests/narration/test_reading_privacy.py`；`frontend/src/narration/reading-rules-panel.ts`、`reading-rules-panel.test.ts`、`reading-status.ts`、`reading-status.test.ts` | `PY:test_reading_privacy.py`、`FE:reading-rules-panel.test.ts reading-status.test.ts`，授权撤销和磁盘不足测试 | `T2-G/README.md`、两种复核策略和失败态证据 |
| T2-H | `tests/narration/test_settings_api.py`；`frontend/src/narration/reading-page.integration.test.ts`、`reading-accessibility.test.ts` | `PY:test_settings_api.py`、两个 `FE`、`UI` | `T2-H/README.md`、1920×1080／2560×1440、键盘和状态矩阵 |
| T2-GATE | `frontend/src/narration/index.ts`、`styles.ts`；18.0.9 分配给 T2-GATE 的共享热点；`T2-GATE.md` | `PY-ALL`、`FE-ALL`、`PKG`、`UI` | `T2-GATE.md`、入口/卸载非回归、下一 ready set |

#### T3 文件、验证和证据

| ID | 允许修改的精确文件/目录 | 最小验收 | 必须证据 |
| --- | --- | --- | --- |
| T3-A | `backend/narration/script_contracts.py`；`tests/fixtures/narration/script-contract-v1.json`；`tests/narration/test_script_contracts.py` | `PY:test_script_contracts.py` | `T3-A/README.md`、版本化 schema 和状态机 |
| T3-B | `backend/narration/segmentation.py`、`source_mapping.py`；`tests/narration/test_segmentation.py` | `PY:test_segmentation.py` | `T3-B/README.md`、Markdown/UTF-16/边界用例 |
| T3-C | `backend/narration/scenes.py`、`speaker_rules.py`、`aliases.py`；`tests/narration/test_speaker_rules.py` | `PY:test_speaker_rules.py` | `T3-C/README.md`、场景和别名冲突矩阵 |
| T3-D | `backend/narration/cloud_analysis.py`、`speaker_model.py`；`tests/narration/test_cloud_analysis.py` | `PY:test_cloud_analysis.py`，假模型覆盖全部失败态 | `T3-D/README.md`、最小外发/模型身份/schema 证据 |
| T3-E | `backend/narration/anonymous_speakers.py`；`tests/narration/test_anonymous_speakers.py` | `PY:test_anonymous_speakers.py` | `T3-E/README.md`、稳定键/合并/拆分/升级用例 |
| T3-F | `backend/narration/casting.py`；`tests/narration/test_casting.py` | `PY:test_casting.py` | `T3-F/README.md`、scope 优先级和确定性结果 |
| T3-G | `backend/narration/expression.py`、`confidence.py`；`tests/narration/test_confidence.py` | `PY:test_confidence.py` | `T3-G/README.md`、校准样本和阈值说明 |
| T3-H | `backend/narration/script_review.py`、`script_api.py`；`tests/narration/test_script_review.py`、`test_script_api.py`；`frontend/src/narration/script-contracts.ts`、`script-api.ts`、`script-api.test.ts`、`script-review-panel.ts`、`script-review-panel.test.ts` | `PY:test_script_review.py test_script_api.py`、`FE:script-api.test.ts script-review-panel.test.ts`，两种冻结路径和 unknown 阻断 | `T3-H/README.md`、阻塞处理和焦点恢复证据 |
| T3-I | `tests/narration/test_speaker_attribution.py`、`tests/narration/test_script_review_integration.py`；`frontend/src/narration/script-review.integration.test.ts` | `PY:test_speaker_attribution.py test_script_review_integration.py`、`FE:script-review.integration.test.ts` | `T3-I/README.md`、准确率、授权/非法 ID/重复分析和失败分类报告 |
| T3-GATE | 18.0.9 分配给 T3-GATE 的共享热点；`backend/narration/script_analysis.py`、`script_backend.py`；`tests/narration/test_script_versions_t3_gate.py`、`test_script_analysis.py`、`test_script_backend.py`；证据根目录的 `T3-GATE.md` | `PY-ALL`、`FE-ALL`、隐私回归；typed DB write→reload、API 安装/卸载、零 Edition、固定脚本样本 | `T3-GATE.md`、固定脚本样本、下一 ready set |

#### T4 文件、验证和证据

| ID | 允许修改的精确文件/目录 | 最小验收 | 必须证据 |
| --- | --- | --- | --- |
| T4-DEP | `package.json`、`pnpm-lock.yaml` | `pnpm install --frozen-lockfile`、`pnpm typecheck`、`pnpm build`；持有 `LOCK-DEPENDENCIES`；仅 CodeMirror，一条 import-free 单 ESM，固定宿主 Blob/CSP、raw/gzip 增量预算、解析/启动/内存和 textarea 回退通过 | `T4-DEP/README.md`、依赖/许可证/bundle 增量、预算裁决和回退清单 |
| T4-A | `backend/narration/requests.py`、`edition_service.py`、`render_cache.py`、`narration_api.py`；`tests/narration/test_edition_service.py`、`test_narration_requests_api.py` | `PY:test_edition_service.py test_narration_requests_api.py`，幂等/快照/缓存作用域 | `T4-A/README.md`、fingerprint 和重放结果 |
| T4-B | `backend/narration/worker.py`、`scheduler.py`；`tests/narration/test_narration_worker.py` | `PY:test_narration_worker.py`；真实运行持有 `LOCK-NANO` | `T4-B/README.md`、取消/公平/崩溃恢复指标 |
| T4-C | `backend/narration/audio_pipeline.py`、`transcoding.py`；`tests/narration/test_audio_pipeline.py` | `PY:test_audio_pipeline.py`、音频校验和接缝听检 | `T4-C/README.md`、格式/响度/接缝报告 |
| T4-D | `backend/narration/manifest.py`、`playback_api.py`；`tests/narration/test_manifest_v2.py`；`tests/fixtures/narration/manifest-v2.json`；`frontend/src/narration/playback-contracts.ts`、`playback-api.ts`、`playback-api.test.ts` | `PY:test_manifest_v2.py`、`FE:playback-api.test.ts`；owner/workspace/novel/Edition/Manifest 可达性、GET/HEAD、单 Range、If-Range/If-None-Match、206/416、持久 CAS、AbortSignal、流式读取和 pending gap；专用 media fetch 不复用 JSON API、不把 token 放入 URL | `T4-D/README.md`、Manifest v2 样本、媒体鉴权/流式 Range/取消证据 |
| T4-E | `frontend/src/narration/segment-playback-queue.ts`、`segment-playback-queue.test.ts`、`narration-player.ts`、`narration-player.test.ts` | `FE:segment-playback-queue.test.ts narration-player.test.ts`，Web Audio 与双 audio 回退 | `T4-E/README.md`、预取/间隙/失败指标 |
| T4-F | `frontend/src/narration/editor-bridge.ts`、`editor-bridge.test.ts`、`editor-codemirror.ts`、`editor-codemirror.test.ts`、`editor-textarea-fallback.ts`、`editor-textarea-fallback.test.ts` | `FE:editor-bridge.test.ts editor-codemirror.test.ts editor-textarea-fallback.test.ts`；只有 `docChanged` 驱动纯 `nextValue` 保存；覆盖 600 ms debounce、保存中 100 ms 追保存、CAS 409、断网/reload recovery、AI apply/undo、document generation fencing、章节切换、selection、系统 IME、卸载和 textarea 降级；decoration/跟随/seek 写入数为 0 | `T4-F/README.md`、编辑器兼容矩阵、正式保存链非回归证据 |
| T4-G | `frontend/src/narration/paragraph-gutter.ts`、`paragraph-gutter.test.ts`、`segment-follow.ts`、`segment-follow.test.ts`、`chapter-playback.ts`、`chapter-playback.test.ts` | `FE:paragraph-gutter.test.ts segment-follow.test.ts chapter-playback.test.ts`，键盘跳播/高亮/暂停跟随 | `T4-G/README.md`、精确四组合证据 |
| T4-H | `backend/narration/document_state.py`；`tests/narration/test_document_narration_state.py`；`frontend/src/narration/chapter-narration-state.ts`、`chapter-narration-state.test.ts`、`script-review-panel.ts`、`script-review-player.integration.test.ts` | `PY:test_document_narration_state.py`、`FE:chapter-narration-state.test.ts script-review-player.integration.test.ts` | `T4-H/README.md`、旧稿/新稿/面板播放器共存、版本分歧和焦点证据 |
| T4-I | `backend/narration/regeneration.py`、`progress.py`；`tests/narration/test_regeneration.py`；`frontend/src/narration/edition-history.ts`、`edition-history.test.ts` | `PY:test_regeneration.py`、`FE:edition-history.test.ts`，局部失效/恢复/快速跳播 | `T4-I/README.md`、复用率和进度恢复结果 |
| T4-J | `tests/narration/test_narration_e2e.py`、`tests/narration/test_playback_recovery.py`；`frontend/src/narration/chapter-narration.integration.test.ts` | `PY:test_narration_e2e.py test_playback_recovery.py`、`FE:chapter-narration.integration.test.ts`，正文不被按键级 TTS 触发 | `T4-J/README.md`、自动化矩阵 |
| T4-K | `scripts/tts/validate_chapter_e2e.py`、`chapter_e2e_executor.py`、`chapter_e2e_probes.py`、`chapter_e2e_probe_request.py`、`chapter_e2e_runtime_audit.py`、`chapter_e2e_readiness.py`、`run_chapter_e2e_real.py`、`provision_validation_token.py`；对应 `tests/narration/test_*.py`；`tests/fixtures/narration/chapter-e2e-v2.json`；`backend/narration/release_gate.py`、`validation_access.py`、`production_runtime.py`、`jobs.py`、`scheduler.py`；`backend/app.py`、`scripts/qwenpaw_lab_plugin.py`、`scripts/verify_qwenpaw_lab.py`、`scripts/package_plugin.py`；本工作包证据目录 | `BENCH-CHAPTER`、`UI`；fixture 2.1 与旁白／林晚／沈川 exact voice mapping；13 个只读隐藏门禁探针；同值 token、exact novel/document、24 小时 expiry、worker 过滤、只读 readiness；真实 Nano/浏览器按三锁排队。T4-K runner/readiness/fixture 只保留为仓库侧作者／操作员本地验收工具，不进入 PawApp 产品包；生产包也不得包含 controller trust/signing/authority 候选、token、attestation、锁、录音或私有报告 | `T4-K/README.md`、准备加固测试、生产包排除清单、30 分钟/RTF/接缝/跳播/听感报告 |
| T4-RC | `backend/models.py`、`backend/migrations/versions/20260827_0020_narration_script_review_actions.py`、`backend/narration/script_versions.py`、`script_analysis.py`、`script_backend.py`、`script_api.py`、`authority_locks.py`、`edition_service.py`、`narration_api.py`、`production_runtime.py`；P1 窄修正 `voices.py`；`tests/narration/test_script_review_actions.py`、`test_script_review_postgres.py`、`test_script_review_backend_postgres.py`、`test_script_review_http_continue.py`；`frontend/src/narration/script-api.ts`、`script-review-panel.ts`、`script-review-continue.integration.test.ts`、`frontend/src/workbench-v2.ts` | `MIG`；四个 `PY`；相关 `FE`；always_review 零 blocker 批准后同 request 产生唯一 `manual_after_review` Edition；blocker 修正为不可变子版本；同键重放、异输入冲突、并发修正/批准/cancel、跨 route 反序锁、注入失败全事务回滚、新 Session 恢复当前候选、真实 HTTP 继续生产；生产 runtime 缺失时动作不可见且 fail-closed | `T4-RC/README.md`、schema/API 状态机、重放/竞争/回滚原始结果、无新数据库/容器/队列证明、前端从批准到 Edition 的真实轮询证据 |
| T4-GATE | 18.0.9 分配给 T4-GATE 的共享热点；证据根目录的 `T4-GATE.md` | `PY-ALL`、`FE-ALL`、`PKG`、真实一章 E2E、固定宿主完整 bundle/Blob/CSP、系统中文 IME、键盘/焦点/ARIA、精确四组合、正式保存链、流式 Range 鉴权、独立相邻句段听检、章节切换/刷新/卸载和原生页面/聊天非回归；另须证明 validation 隐藏运行时公开 capability 为 false，并对拟放行产品运行就绪链作 fail-closed 检查 | `T4-GATE.md`、核心可用 go/no-go、capability 默认启用/继续关闭裁决、下一 ready set |

`T4-RC` 冻结的最小状态模型如下：每个 generation request 持有 nullable `review_script_id`／`current_review_version_id` 二元指针，二者同时为空或同时存在；分析首次物化或幂等重放时写入该指针，人工修正只能在锁定 request 后以当前指针、版本号、immutable hash、句段 local hash 和 request 状态做 CAS。每个动作写入不可变 `narration_script_review_actions` 行，唯一键作用域为 owner/workspace/idempotency key，并保存 action kind、规范化 request hash、request、父/结果版本、前后 request version、actor 及批准结果 Edition；同键同输入返回原结果，同键异输入返回 409。旧 request 若缺少可证明归属的指针，不做“取最新版本”迁移猜测，明确要求重新发起朗读请求。

修正操作不得更新父 ScriptVersion 或其任何 scene/segment/issue 子行；它先为同一 script 预留新的版本身份，重新派生全部 scene/segment ID，并在完整 typed contract 校验后保存子版本和移动 request 指针。批准只接受 request 当前候选、owner actor、零 blocker、同 revision/hash/settings/policy 且 immutable children 复核一致的版本；随后在同一事务内冻结为 `manual_after_review`、CAS 推进 request、创建唯一 Edition 与 render/job 计划并落动作账本。任一写入、计划或 flush 失败都整体回滚；事务中严禁调用 Nano、ffmpeg、网络或 Sidecar。`continue_snapshot` 只承认旧快照，`reanalyze_latest` 必须走“稳定保存 → 新 revision → 新 request”，不得把新正文改绑旧 request。

#### T5 文件、验证和证据

以下 Owner 表仅作历史计划索引，全部 `T5-*` 当前为 `DEFERRED_OUT_OF_CURRENT_COMPLETION`，不得派发。

| ID | 允许修改的精确文件/目录 | 最小验收 | 必须证据 |
| --- | --- | --- | --- |
| T5-A | `backend/narration/voice_generator.py`、`voice_generator_runtime.py`、`voice_generator_api.py`；`tests/narration/test_voice_generator_runtime.py`、`test_voice_generator_api.py` | `PY:test_voice_generator_runtime.py test_voice_generator_api.py`；真实运行持有 `LOCK-VOICEGEN` | `T5-A/README.md`、生命周期/峰值内存/失败恢复 |
| T5-B | `backend/narration/voice_descriptions.py`；`tests/narration/test_voice_descriptions.py` | `PY:test_voice_descriptions.py`，最小人物字段和可编辑描述 | `T5-B/README.md`、隐私字段矩阵 |
| T5-C | `frontend/src/narration/voice-generator-contracts.ts`、`voice-generator-api.ts`、`voice-generator-api.test.ts`、`voice-generator-panel.ts`、`voice-generator-panel.test.ts`、`private-voice-library.ts`、`private-voice-library.test.ts` | `FE:voice-generator-api.test.ts voice-generator-panel.test.ts private-voice-library.test.ts`，候选/试听/锁定/来源状态 | `T5-C/README.md`、完整交互截图 |
| T5-D | `scripts/tts/validate_voice_generator_clone.py`；`tests/narration/test_voice_generator_quality.py` | `PY:test_voice_generator_quality.py`、真实 VoiceGenerator→Nano 听检，持有两个模型锁 | `T5-D/README.md`、保持度与漂移报告 |
| T5-E | `backend/narration/capabilities.py`；`tests/narration/test_narration_capabilities.py`；`frontend/src/narration/voice-generator-capability.ts`、`voice-generator-capability.test.ts` | `PY:test_narration_capabilities.py`、`FE:voice-generator-capability.test.ts`，不可用时隐藏且既有路径非回归 | `T5-E/README.md`、go/hide 两套证据 |
| T5-GATE | 18.0.9 分配给 T5-GATE 的共享热点；证据根目录的 `T5-GATE.md` | `PY-ALL`、`FE-ALL`、`PKG`、M4 真实裁决 | `T5-GATE.md`、可见/隐藏结论 |

#### T6 文件、验证和证据

以下 Owner 表仅作历史计划索引。除 T6-F 的最小磁盘保护语义已经并入 T4-GATE 外，全部工作包不得由当前 ready set 派发；T6-D 永久标记为本轮取消。

| ID | 允许修改的精确文件/目录 | 最小验收 | 必须证据 |
| --- | --- | --- | --- |
| T6-A | `backend/narration/voice_variants.py`、`voice_variants_api.py`；`tests/narration/test_voice_variants.py`、`test_voice_variants_api.py`；`frontend/src/narration/voice-variants-api.ts`、`voice-variants-api.test.ts`、`voice-variants-panel.ts`、`voice-variants-panel.test.ts` | `PY:test_voice_variants.py test_voice_variants_api.py`、`FE:voice-variants-api.test.ts voice-variants-panel.test.ts`，仅人工确认后生效 | `T6-A/README.md`、版本影响和听感记录 |
| T6-B | `backend/narration/group_mix.py`、`group_mix_api.py`；`tests/narration/test_group_mix.py`、`test_group_mix_api.py`；`frontend/src/narration/group-mix-api.ts`、`group-mix-api.test.ts`、`group-mix-setting.ts`、`group-mix-setting.test.ts` | `PY:test_group_mix.py test_group_mix_api.py`、`FE:group-mix-api.test.ts group-mix-setting.test.ts`、真实混音持有 `LOCK-NANO` | `T6-B/README.md`、响度/相位/听感报告 |
| T6-C | `backend/narration/batch.py`、`batch_api.py`；`tests/narration/test_batch_narration.py`、`test_batch_api.py`；`frontend/src/narration/batch-api.ts`、`batch-api.test.ts`、`batch-generation-panel.ts`、`batch-generation-panel.test.ts` | `PY:test_batch_narration.py test_batch_api.py`、`FE:batch-api.test.ts batch-generation-panel.test.ts`，扫描/生成分离和逐章恢复 | `T6-C/README.md`、公平性与恢复记录 |
| T6-D | `CANCELLED`：不得新增或接入 `export.py`、`export_api.py`、导出 UI／测试／manifest | 不执行；若发现未接入候选只标记非目标，不为清理延误 T4 | 历史计划保留为 `SUPERSEDED_NON_TARGET`，不新建 T6-D 证据 |
| T6-E | `backend/narration/pronunciation_audit.py`、`pronunciation_audit_api.py`；`tests/narration/test_pronunciation_audit.py`、`test_pronunciation_audit_api.py`；`frontend/src/narration/pronunciation-audit-api.ts`、`pronunciation-audit-api.test.ts`、`pronunciation-audit-panel.ts`、`pronunciation-audit-panel.test.ts` | `PY:test_pronunciation_audit.py test_pronunciation_audit_api.py`、`FE:pronunciation-audit-api.test.ts pronunciation-audit-panel.test.ts`，ASR 仅告警不改正文 | `T6-E/README.md`、误报/漏报样本 |
| T6-F | `backend/narration/quality.py`、`gc.py`、`storage_governance_api.py`；`tests/narration/test_narration_gc.py`、`test_storage_governance_api.py`；`frontend/src/narration/storage-governance-api.ts`、`storage-governance-api.test.ts`、`storage-governance-panel.ts`、`storage-governance-panel.test.ts` | `PY:test_narration_gc.py test_storage_governance_api.py`、`FE:storage-governance-api.test.ts storage-governance-panel.test.ts`，持有 `LOCK-MEDIA-GC` | `T6-F/README.md`、引用可达性/配额/恢复报告 |
| T6-G | `backend/narration/idle_prepare.py`、`idle_prepare_api.py`；`tests/narration/test_idle_prepare.py`、`test_idle_prepare_api.py`；`frontend/src/narration/idle-prepare-api.ts`、`idle-prepare-api.test.ts`、`idle-prepare-setting.ts`、`idle-prepare-setting.test.ts` | `PY:test_idle_prepare.py test_idle_prepare_api.py`、`FE:idle-prepare-api.test.ts idle-prepare-setting.test.ts`，默认关闭且不按键触发 | `T6-G/README.md`、启停与 Edition 显式切换证据 |
| T6-H | 历史高级生产测试范围；删除 `test_export_recovery.py` 目标 | 未来重新立项后再冻结 | 当前不生成证据 |
| T6-GATE | 历史高级生产汇合点 | 当前不执行，也不阻断 T4-GATE | 当前无发布裁决 |

### 18.0.12 推荐施工波次与唯一汇合顺序

| 波次 | 主代理串行工作 | 子代理 ready set | 汇合条件 |
| --- | --- | --- | --- |
| W0-1 | 登记基线、锁和 fixture 契约 | T0-A、T0-E、T0-H、T0-I | 依赖、音色槽位、数据边界和工具输入可复用 |
| W0-2 | 安排真实模型/浏览器资源锁 | T0-B/T0-C 代码可并行但真实 Nano 排队；T0-F、T0-G 可并行 | 拓扑、音质、编辑器和播放器原型均有原始证据 |
| W0-3 | 串行安排 T0-D VoiceGenerator；汇总未通过项 | T0-E 可根据听感结果完成候选锁定 | T0-GATE 七项 go/no-go |
| W1-1 | 先串行完成 T1-DEP，再由 T1-A 冻结 scope、taxonomy、DTO、adapter 和 fingerprint 公共契约 | T1-A 完成后可开放 T1-B；T1-D 只读准备可以并行，但不得在 T1-A fixture 冻结前写 ORM/迁移 | 正式依赖和公共契约可重建，T1-D 获得唯一 schema 输入 |
| W1-2 | 主代理/唯一 Owner 串行完成 T1-D ORM、测试库迁移和回退并冻结 schema | T1-B 可继续；T1-D 通过后开放 T1-C、T1-E、T1-F，T1-G 只在各依赖落地后补集成测试 | T1-GATE 共享底座通过 |
| W2/3-1 | 依次冻结 T2-A、T3-A 两套不重叠契约 | T2-B…G 与 T3-B…E、T3-G 可滚动并行 | T2-H 后执行 T2-GATE |
| W3-2 | 释放 T2 声音设置契约 | T3-F、T3-H、T3-I | T3-GATE 可冻结完整朗读脚本 |
| W4-1 | 先串行完成 T4-DEP，再冻结 Edition/render 与 Manifest 接口 | T4-A、T4-B、T4-C、T4-D、T4-F | 正式编辑器依赖和 lock 可重建；后端生产和编辑器桥 mock 通过 |
| W4-2 | 保持共享页面文件锁；主代理冻结并独占 T4-RC schema、0020 migration、script mutation 与 approved-request 生产接口 | T4-E、T4-G、T4-H、T4-I、T4-J 可按原不重叠文件滚动并行；T4-RC 只允许测试／只读复核代理并行，禁止其他代理写其共享文件 | T4-RC migration、领域、HTTP、前端继续生产和事务回滚证据通过后，主代理方可接真实人工按钮 |
| W4-3 | T4K-RF 与 Zhiming/Junhao/Xiaoyu 真实 baseline 已完成；继续独占 Nano、浏览器和同 scope 章节数据完成剩余产品验证 | 只允许不重叠的播放器、浏览器证据和文档范围更新并行 | 网页播放、CodeMirror、30 分钟、四桌面、恢复与最小磁盘保护通过 |
| W4-4 | 固定 PawApp 打包与 QwenPaw 安装／升级／卸载；排除签名实验和导出非目标 | 子代理只读复核 capability、包内容和证据绑定 | T4-GATE 核心中文本地多角色朗读 go/no-go |
| W5/6 | 无当前施工 | T5 全部 deferred；T6 高级生产 deferred；T6-D cancelled | 不属于当前完成定义，不阻断 T4 |
| W-FINAL | 主代理接线、全量相关测试、打包、真实浏览器和恢复验证 | 子代理只读复核不同证据维度，不再并写代码 | T4 发布门槛全部通过；Git 仍需用户明确授权 |

任何阶段的唯一汇合顺序固定为：`契约/fixture → 独立实现与窄测试 → 主代理越界审查 → 共享入口接线 → 集成测试 → 真实资源验证 → GATE 记录 → 下一 ready set`。不得先把多个未冻结实现合并，再倒推公共接口。

### 18.0.13 验收命令束与证据格式

工作包表中的命令束含义如下；派发卡必须把 `test_files` 替换成表中一个或多个精确测试文件，不得只写“运行相关测试”。表中同时列出多个 basename 时，每个 basename 都分别补全为 `tests/narration/<name>` 或 `frontend/src/narration/<name>` 后作为独立命令参数，不能只给第一个参数补目录。

`DOC`：

```bash
git status --short
git diff --check
```

`PY:test_files`：

```bash
.venv/bin/python -m pytest -q -ra tests/narration/<test_files>
```

`PY-ALL`：

```bash
.venv/bin/python -m pytest -q -ra
```

`FE:test_files`：

```bash
pnpm exec vitest run frontend/src/narration/<test_files>
pnpm typecheck
```

`FE-CHECK`：

```bash
pnpm typecheck
pnpm build
```

`FE-ALL`：

```bash
pnpm test
pnpm typecheck
pnpm build
```

`MIG` 只能在主代理已确认的专用测试数据库执行；数据库名固定为 `ai_novel_world_2026_tts_test`，`TTS_TEST_DATABASE_URL` 必须与正式数据库不同，并在证据中隐藏口令。执行 downgrade 前还必须完成该测试库的可恢复备份或确认它可由 fixture 全量重建：

```bash
test -n "${TTS_TEST_DATABASE_URL:-}"
case "$TTS_TEST_DATABASE_URL" in */ai_novel_world_2026_tts_test) ;; *) exit 64 ;; esac
AI_NOVEL_DATABASE_URL="$TTS_TEST_DATABASE_URL" .venv/bin/python scripts/migrate.py upgrade head
AI_NOVEL_DATABASE_URL="$TTS_TEST_DATABASE_URL" .venv/bin/python scripts/migrate.py downgrade <T1-D记录的精确前一revision>
AI_NOVEL_DATABASE_URL="$TTS_TEST_DATABASE_URL" .venv/bin/python scripts/migrate.py upgrade head
```

`PKG`：

```bash
docker compose config --quiet
.venv/bin/python scripts/package_plugin.py
.venv/bin/python -m pytest -q -ra tests/test_manifest.py tests/test_qwenpaw_integration_contract.py
```

`BENCH-NANO`、`BENCH-QUALITY`、`BENCH-VOICEGEN`、`BENCH-CHAPTER` 必须使用 T0-I 冻结的 fixture manifest 和统一 JSON 输出契约。阶段 0 的模型实验统一使用由 `prototypes/moss-tts-nano/python-requirements.lock` 重建的 `prototypes/moss-tts-nano/.venv/bin/python`，不得把尚未裁决的模型依赖装入项目 `.venv` 或正式 PawApp；T1-DEP 冻结正式运行依赖后才切换到项目解释器。T0-I 必须让四个脚本支持下列稳定 CLI，工作包将实际命令和退出码原样写入证据：

```bash
prototypes/moss-tts-nano/.venv/bin/python scripts/tts/benchmark_nano_topologies.py \
  --fixture-manifest tests/fixtures/narration/benchmark_manifest.json \
  --output-dir docs/开发文档/证据/MOSS-TTS-Nano施工/T0-B

prototypes/moss-tts-nano/.venv/bin/python scripts/tts/benchmark_nano_quality.py \
  --fixture-manifest tests/fixtures/narration/benchmark_manifest.json \
  --output-dir docs/开发文档/证据/MOSS-TTS-Nano施工/T0-C

prototypes/moss-tts-nano/.venv/bin/python scripts/tts/benchmark_voice_generator.py \
  --fixture-manifest tests/fixtures/narration/benchmark_manifest.json \
  --output-dir docs/开发文档/证据/MOSS-TTS-Nano施工/T0-D

# validate-only 也必须显式绑定专用测试 scope；以下 fixture 只有在授权完成后才允许创建。
.venv/bin/python scripts/tts/validate_chapter_e2e.py \
  --mode validate-only \
  --fixture-manifest tests/fixtures/narration/chapter-e2e-v3.json \
  --api-base http://127.0.0.1:18088/api/ai-novel-world-2026 \
  --novel-id '<DEDICATED_TEST_NOVEL_UUID>' \
  --document-id '<DEDICATED_TEST_CHAPTER_UUID>' \
  --automatic-case-id chapter-auto-zero-blockers \
  --manual-case-id chapter-real-blocker \
  --private-work-dir '<TRUSTED_LOCAL_NON_SYNCED_0700_DIRECTORY>' \
  --confirm-dedicated-test-novel '<DEDICATED_TEST_NOVEL_UUID>' \
  --confirm-dedicated-test-document '<DEDICATED_TEST_CHAPTER_UUID>' \
  --duration-minutes 30 \
  --output-dir '<REPOSITORY_EXTERNAL_REDACTED_RESULT_0700_DIRECTORY>'

# readiness 结果经作者复核后，先在同一容器、同一 run 的 recovery 私有目录发行 15 分钟有效且不可覆盖的操作员信封。
# <T4K_RUN_UUID> 由操作员为本次 run 预先生成，并在发行与 real 命令中保持完全相同；stdout 不回显该值。
docker exec \
  --workdir /app/working/plugins/ai-novel-world-2026 \
  ai-novel-2026-qwenpaw-lab \
  /app/venv/bin/python scripts/tts/chapter_e2e_operator_envelope.py \
  --mode issue \
  --attestation-file '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/recovery/readiness-attestation.json' \
  --run-id '<T4K_RUN_UUID>' \
  --output-file '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/recovery/operator-envelope.json' \
  --confirm-author-review AUTHOR-REVIEWED-T4-K-READINESS

# 正式 real 模式只在现有 QwenPaw 容器的已安装 PawApp 根中执行；所有可变文件均位于既有 secret volume。
# 下列尖括号内容必须来自上一步同一 envelope/run，不能把 token 值放入命令行。
docker exec \
  --workdir /app/working/plugins/ai-novel-world-2026 \
  ai-novel-2026-qwenpaw-lab \
  /app/venv/bin/python scripts/tts/run_chapter_e2e_real.py \
  --mode real \
  --operator-envelope-file '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/recovery/operator-envelope.json' \
  --readiness-attestation-file '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/recovery/readiness-attestation.json' \
  --probe-report '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/recovery/probe-report.json' \
  --validation-token-file /app/working.secret/ai-novel-world-2026/t4k-validation/token \
  --lock-nano-file '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/recovery/lock-nano' \
  --lock-browser-file '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/recovery/lock-browser' \
  --lock-data-file '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/recovery/lock-data' \
  --lock-nano-grant 'LOCK-NANO/<RUN_NONSECRET_ID>' \
  --lock-browser-grant 'LOCK-BROWSER/<RUN_NONSECRET_ID>' \
  --lock-data-grant 'LOCK-T4-K-DATA/<RUN_NONSECRET_ID>' \
  --confirm-fixed-launcher RUN-T4-K-FIXED-LAUNCHER \
  --run-id '<T4K_RUN_UUID>' \
  --fixture-manifest /app/working/plugins/ai-novel-world-2026/tests/fixtures/narration/chapter-e2e-v3.json \
  --api-base http://127.0.0.1:8088/api/ai-novel-world-2026 \
  --novel-id '<DEDICATED_TEST_NOVEL_UUID>' \
  --document-id '<DEDICATED_TEST_CHAPTER_UUID>' \
  --automatic-case-id chapter-auto-zero-blockers \
  --manual-case-id chapter-real-blocker \
  --private-work-dir '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/recovery' \
  --confirm-dedicated-test-novel '<DEDICATED_TEST_NOVEL_UUID>' \
  --confirm-dedicated-test-document '<DEDICATED_TEST_CHAPTER_UUID>' \
  --duration-minutes 30 \
  --output-dir '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/result' \
  --confirm-real-run RUN-T4-K-REAL-CHAPTER \
  --confirm-baseline-restore RESTORE-T4-K-BASELINE \
  --confirm-private-work-dir-local-non-synced PRIVATE-WORK-DIR-LOCAL-NON-SYNCED
```

首次 fresh run **不得**传 `--listening-record`：技术链和 baseline 恢复完成后应进入 `HUMAN_LISTENING_PENDING`，而不是预先指向一个尚不存在的文件。外部 collector 提交同一 run 的技术报告后，作者实际听完并用 `chapter_e2e_listening.py --mode finalize` 在 `<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/listening/` 同时生成固定 `listening.json` 与 `listening-finalization-receipt.json`；随后重放上面完全相同的 launcher 命令，只增加 `--resume --listening-record '<CONTAINER_PRIVATE_RUN_0700_DIRECTORY>/listening/listening.json'`。恢复过程仍使用同一 envelope、run UUID、recovery 目录和三锁，不重跑普通生成链。15 分钟 envelope 与 probe-request 的新鲜度只约束 fresh claim／初次提交；一旦同 run 已持久化合法 recovery head，等待作者实际听检可以跨越该窗口，resume 必须通过既有 claim、recovery generation/hash 与精确绑定恢复，不能重新签发 envelope、改 run 或重跑浏览器／Nano 链。

尖括号不是可直接执行的默认值。launcher 强制 envelope、attestation、probe report 和三锁的直接父目录精确等于 `--private-work-dir`；result 与 listening 则必须是不重叠的 sibling 私有目录。operator claim/lease 由固定中央 registry 自动管理，不接受调用者路径；正常个人本地运行不需要 controller-authority 材料、签名文件、trust port/root 或 OS service。固定 launcher 会再次拒绝仓库内路径、符号链接、宽权限、缺少三锁、旧／错 run 报告或不匹配 scope；完整安装环境、host/container token 区分、恢复与销毁顺序见 [T4-K 固定操作报告](证据/MOSS-TTS-Nano施工/T4-K/README.md)。

模型与试听音频仍写入已验证的外部模型/媒体目录，`--output-dir` 只允许保存脱敏 JSON、Markdown、日志摘要和截图；脚本不得把权重、私人参考录音或完整生成音频复制进证据目录。所有运行至少记录：硬件/系统、Python、模型 revision/hash、执行后端、参数、输入 hash、首包、RTF、峰值内存、取消/失败状态和输出 hash。人工听检另外记录漏字、重复、音色漂移、停顿、接缝和主观结论，不能用时长/解码成功替代听感。

`UI` 只覆盖当前宿主真实布局下的精确四组合：`1920×1080 × 助手收起`、`1920×1080 × 助手展开`、`2560×1440 × 助手收起`、`2560×1440 × 助手展开`；每个组合都须检查键盘、中文 IME、焦点恢复、控制台和错误态。用户于 2026-08-27 明确将低于 1920×1080、移动、窄屏、受限小视口和 200% 等效小视口改为非目标：不设计、不测试，也不阻断本专项发布；已有的防御性响应式样式可为避免宿主回归而保留，但不得据此扩张正式验收矩阵。截图必须记录实际像素和助手状态，不以文件名代替核验。

`FULL`：

```bash
git diff --check
.venv/bin/python -m pytest -q -ra
pnpm test
pnpm typecheck
pnpm build
docker compose config --quiet
.venv/bin/python scripts/package_plugin.py
```

若阶段影响真实 QwenPaw 安装/升级/卸载，主代理还必须在隔离环境执行项目当时有效的生命周期验证器，并验证禁用/卸载后原生聊天、设置、Agent、Skills、工具和数据卷非回归。`scripts/verify_qwenpaw_lab.py` 是长期项目实验室的历史验证器；当前 TTS 阶段以不会触碰长期项目资源、使用一次性精确命名资源的 `scripts/tts/verify_qwenpaw_plugin_lifecycle.py` 为现行权威验证器。2026-08-28 已完成真实 install → force reinstall → public API uninstall → reinstall，原生能力、数据／卷哨兵与零残留检查均 PASS，临时容器、卷和网络 cleanup failures=0；因此不得再把旧实验室脚本当作本阶段重复前置，也不得用旧结果冒充当前 TTS 通过。

每个 `docs/开发文档/证据/MOSS-TTS-Nano施工/<ID>/README.md` 必须包含：基线 commit 与工作树状态、Owner、开始/结束时间、冻结输入、实际修改文件、命令及原始通过/失败/跳过数量、运行环境、产物 hash、人工验收、未验证项、风险、回退和主代理接线说明。每个 `T*-GATE.md` 还必须列出接收/拒绝的工作包、尚未解释的 P0/P1、降级决定、下一 ready set 和是否需要用户重新批准。没有证据文件、测试被无说明跳过或只收到口头总结时，门禁不得通过。

### 阶段 0：ADR、模型、音色包和质量尖峰

- 固定 Nano、Audio Tokenizer、ONNX、VoiceGenerator 和转码器 revision/hash；
- 补充 ADR：Nano 执行后端、模型进程安全边界、共享任务表、正文云端授权；
- 对进程内 ONNX、受管本机进程、Compose Sidecar 和浏览器试听候选运行同一基准；
- 测试中文数字、标点、多音字、中英混读、长句和内部切分；
- 测试 3/5/8/12 秒参考音频与清洁度；
- 测试 independent segments 的音色、语速、停顿、漏字、重复和接缝；
- 测试首包、RTF、取消、崩溃恢复和连续 30 分钟稳定性；
- 测试 VoiceGenerator MPS/可用本地路径以及 Nano 二次克隆保持度；
- 生成并人工锁定 24 槽位基础音色包，或确定具有授权的替代包；
- 补充编辑器 ADR，使用真实长章节对 CodeMirror 6、Monaco 和 `textarea` 安全降级验证中文输入法、自动保存、undo/redo、decoration、gutter、UTF-16 映射和 Blob bundle；
- 用 pending gap、章首前缀和中段用户请求窗口验证 Manifest schema v2、任务优先级、公平老化和同 Edition revision 刷新；
- 冻结 `script_review_policy`、warnings/blockers taxonomy、自动冻结约束、API/状态机契约、基准语料、参数、能力矩阵和 go/no-go 报告。

退出条件：七项均明确——Nano 物理部署、24 音色来源、浏览器分段播放方案、VoiceGenerator 可见/隐藏结论、正式编辑器与安全降级方案、随机跳播 ready-window 协议、复核策略与阻断分类契约。未退出阶段 0 时只允许原型代码，不建正式迁移和产品 UI。

### 阶段 1：共享基础设施与数据

- `MossNanoTTSAdapter`、`VoiceDesignAdapter`、能力/健康/指纹契约；
- 模型下载、校验、预热、受管进程或 Sidecar 生命周期；
- 扩展 `media_assets` 与引用/保留/清理策略；
- `background_jobs`、租约、幂等、重试、死信和 `model_run_records`；
- 幂等隐藏 `tts_snapshot`，不推进 working copy 基线；
- 音色、设置快照、脚本版本、`source_block_key`、Edition、`document_narration_state`、render、Manifest v2 和播放进度迁移；
- `moss-models`、`novel-media`、Range/ETag；
- fake adapter、崩溃恢复、迁移升级/回退和 GC 集成测试。

### 阶段 2：声音和朗读设置

当前实施事实（2026-08-26）：以下模块、隔离 PostgreSQL 18 CAS、正式项目数据库升级、真实 QwenPaw 安装、29 路由、1920×1080／2560×1440 浏览器、键盘焦点及卸载／重装非回归均已完成，详见 [T2-GATE 最终报告](证据/MOSS-TTS-Nano施工/T2-GATE.md)。本清单只代表 T2 朗读设置闭环；T3 的后端技术闭环状态见下一节，T4 合成播放或 T5/T6 高级能力仍未可用。

- `reading` 路由、总览和导航；
- 旁白、章节/分卷范围覆盖；
- 正文分析隐私模式和独立云端授权；
- 默认“仅异常复核”与可选“每章都复核”；
- 人物卡声音页签；
- 预设、上传、标准化、授权、试听和锁定版本；
- 24 槽位基础音色池导入、覆盖率和缺失提示；
- 人物专属/继承绑定与历史影响预览；
- 发音、停顿、音频和缓存管理；
- 空、加载、分析中、零阻塞自动继续、阻塞待处理、失败、模型缺失、授权和磁盘不足状态；
- 当前宿主 1920×1080、2560×1440 和助手展开／收起验证。

### 阶段 3：脚本、场景和选角

当前实施事实（2026-08-27）：[T3-GATE 最终报告](证据/MOSS-TTS-Nano施工/T3-GATE.md)已经通过 fixed-local、local-rules-only 的 typed 脚本技术闭环，包括确定性切分、明确人物归因、旁白／人物绑定逻辑选角、脚本持久化、零阻塞自动冻结、历史读取和 API GET/ANALYZE。下列清单同时保留阶段 3 的完整目标；云端归因、自动匿名生命周期、通用选角、人工／继承修正和公共 mutation 仍是显式 HOLD，`automatic_speaker_detection` 产品 capability 也要等待 T4 用户闭环后才能启用。

- Markdown/UTF-16 映射、段落 `source_block_key` 和 `segment_kind`；
- `character_aliases`、别名冲突和场景切分；
- 本地规则解析；
- 授权后的最小化云端补充归因；
- requested/actual model 与严格 schema/ID 校验；
- 匿名人物稳定键、合并、拆分和升级；
- 确定性通用选角与 scope 优先级；
- 情绪/表达标签和校准置信等级；
- 脚本版本、warnings/blockers、默认自动冻结、逐章人工复核和人工覆盖安全继承。

### 阶段 4：独立句段合成和同步播放

历史 v2 实施事实（2026-08-28）：T4-A～T4-J 的代码与自动化候选已经汇合，人工阻塞脚本的修正、批准、同 request 唯一 Edition 与任务图也已通过 [T4-RC 门禁](证据/MOSS-TTS-Nano施工/T4-RC/README.md)。run `270ea179-e3cf-4095-a928-56b414070719` 曾完成真实 Nano、partial-ready、pending-gap、四桌面浏览器和 30 分钟技术链，但其后人工听检失败，整体结论保持历史 HOLD。当前 canonical run 是 `bb03ccaf-4681-490a-b987-84bec9199b3b`；不得用该 v2 快照覆盖本文首段或 v3 专项证据。

- `narration-requests` 一键编排、Edition 创建和不可变设置快照；
- 版本化 render fingerprint 与 owner/workspace 缓存；
- 持久句段任务、优先级和单并发资源锁；
- master/播放副本校验和后处理；
- 渐进 Segment Manifest v2、连续 ready 前缀和用户请求 ready ranges；
- Web Audio 队列及双 audio 回退验证；
- `NarrationEditorBridge` 与阶段 0 选定的可装饰编辑器；
- 段落 gutter、上下文命令、只读句段点击和 `prepare-range`；
- 句段高亮、编辑优先、滚动暂停/恢复、跳转、倍速和进度；
- 同页边听边改、播放器旧稿字幕和 `textarea` 安全降级；
- 分析/复核期间正文继续修改的来源快照提示，以及复核面板与紧凑播放器共存；
- `working_copy_diverged`、显式“更新朗读”、Edition 切换和正文 hash 屏障；
- 局部重生成、旧版本视图、快速连续跳播和后台公平性。

完成阶段 4 才达到核心“番茄式多角色朗读”可用范围。本次有限核心的真实声音范围精确为旁白 + 至少两名正式人物 + 三个互异、已真实试听并锁定的 official preset；匿名人物与通用音色 capability 可继续 false/HOLD，不因它们未放行而阻断有限核心。

### 阶段 5：文字生成音色产品化

`DEFERRED_OUT_OF_CURRENT_COMPLETION`。以下历史目标不再施工、不计入剩余工期，也不阻断 T4：VoiceGenerator 受管后端、人物描述、多候选、二次克隆和私人音色库。若未来恢复，必须重新立项、重新做 M4 资源与产品门禁。

### 阶段 6：高级生产

`DEFERRED_WITH_T6_D_CANCELLED`。情绪变体、群体混音、全书批量、ASR、完整质量治理和空闲预生成均不属于当前完成范围；T6-D 章节／全书音频导出已取消，不得出现导出 API、UI、拼接文件或发布门禁。当前只把磁盘不足提示、权威媒体保护和安全清理派生缓存的最小能力并入 T4。

## 19. 测试与验收

### 19.1 固定测试集

建立不含未授权文本的项目测试集，覆盖：

- 旁白；
- 前置/后置人物提示语；
- 双人和多人轮流对白；
- 省略主语；
- 内心独白；
- 匿名青年/中年/老人/儿童；
- 群体声音；
- 同一匿名人物跨章、相同泛称但实际不同人物；
- Markdown、emoji、嵌套引号和特殊标点；
- 多音字、人名、年代和中英混合；
- 正文中途修改和音色换版；
- 分析/复核期间继续修改正文、旧来源快照提示、继续旧快照与重新分析两条路径；
- 段前、段内和段后编辑，段落拆分/合并、引号/边界标点变化，以及编辑当前/下一播放句段；
- 章首 pending、中段 ready、窗口内部 failed 和快速连续选择不同段落；
- 用户手动滚动、移动光标、中文输入法、键盘播放和正文 hash 不一致；
- 页面重载导致临时编辑映射链丢失；
- 云端辅助保持 HOLD 时不外发正文；历史授权／撤销契约可作负向回归，但不作为当前真实产品放行路径。
- 默认零阻塞自动冻结、warning 不阻塞、每章都复核、每一种 blocker 和阻塞清零后继续；
- 1920×1080／2560×1440 与助手收起／展开的精确四组合下，复核面板、播放器和右侧原生助手共存。

匿名人物、群体和通用音色样例可作为未来 capability 的固定负向／回归输入；在对应产品 capability 继续 false/HOLD 时，它们不是 T4 有限核心发布的真实资产或听感阻断项。

### 19.2 自动化门槛

- 明确姓名+说话动词样本的说话人识别目标不低于 98%；
- 每个自动识别结果都保存规则/模型来源、人物候选、证据和置信等级，缺少证据的结果不能标记为高置信度；
- 同一 Edition 内，同一 `character_id` 或同一合法作用域的 `anonymous_speaker_id` 必须稳定解析到同一锁定音色版本，错误漂移数量为 0；
- 已配置人物的高置信度对白必须自动解析人物卡音色，不要求作者逐句重复选角；
- 非允许 character ID 数量为 0；
- 所有 unknown 和低置信度句段均可见、可编辑；
- 未处理的 unknown、别名冲突、匿名人物冲突和缺失音色进入正式 Edition 的数量为 0；
- `blockers_only` 在分析成功且零阻塞时无需额外人工点击，脚本以 `auto_no_blockers` 冻结并幂等创建 Edition；
- 中置信度 warning 不阻塞默认生成，但在总览和脚本详情中可追溯；
- 任一 blocker 存在时自动冻结和正式 Edition 创建数量为 0；清零并确认后只能生成 `manual_after_review` 记录；
- `always_review` 在零阻塞时仍停留 `review_required`，未经作者确认不得创建正式 Edition；
- 分析失败、实际模型不匹配或非法 schema 不得被降级为 warning 或 `auto_no_blockers`；
- 自动/人工冻结均记录策略、阻断分类版本、计数、actor、时间和输入/模型 fingerprint，已冻结脚本不可原地修改；
- 未修改 revision 的句段高亮偏移错误为 0；
- emoji/组合字符测试的前后端范围完全一致；
- 同幂等键不重复创建 job、render 或媒体；
- 相同正文重复点击朗读不重复创建可见 checkpoint，也不推进 working copy 基线；
- `analyze_only` 扫描创建 Edition、render 或音频任务的数量为 0；扫描后正文/设置 fingerprint 改变时，生成请求必须重新分析或明确失效旧候选；
- 单句修改只失效必要 render；
- 已冻结脚本不可原地修改，同一脚本可创建多个独立 Edition；
- 普通正文单击只移动光标，只有 gutter/命令/只读句段点击触发跳播；
- 目标起点已有合法 ready window 时从正确 `segment_id` 开始；目标未 ready 或缓冲不足时幂等准备窗口且不回退章首；
- 已修改、新增或映射不唯一的工作稿段落不能误跳旧 Edition 的相似句，只能更新朗读或在旧稿视图明确跳播；
- 未显式选择中段时，默认播放仍只使用章首连续 ready 前缀；显式选择中段时允许使用该起点的连续 ready range；
- 播放窗口内部 pending/failed 句段绝不被静默跳过；
- 同一 Edition 可在句段边界刷新 Manifest revision，但不会无提示切换 Edition；
- 活跃编辑 transaction 只映射未相交且哈希/锚点仍一致的句段；相交、段落拆并和边界标点变化按规则失效相邻块；页面重载后旧 manifest 不猜测映射新正文；
- 编辑时播放器不被强制暂停，光标、selection、composition 和 undo/redo 不被自动跟随破坏；
- 按键和自动保存不创建 narration job；明确“更新朗读”才进入保存、分析和新 Edition 流程；
- 复核面板支持键盘遍历、可见焦点、关闭后焦点恢复、非颜色状态提示和分析/生成 live region；在精确四组合下主要操作不被固定播放器或原生助手覆盖；
- 旧 Edition 播放时打开复核面板不会中断音频或产生双层遮挡，紧凑播放条可操作；来源 revision 已落后时不能把旧句段修正映射到新正文；
- 新 Edition 不自动替换旧 Edition，CAS 显式切换只更新当前指针，不改写旧 Edition 的生成状态；
- `local_rules_only` 网络捕获中正文外发数量为 0；
- `cloud_assisted` 未授权调用数量为 0，授权后 payload 只包含不确定窗口和允许候选；
- 实际聊天模型与请求配置不匹配时分析结果作废；
- `partial_ready` 的默认起点和显式 ready ranges 均服从服务端缓冲策略；
- 任务崩溃恢复不重复合成已 ready 句段；
- 音色归档、角色归档和缓存清理不破坏历史引用；
- 普通清缓存不删除上传原件、标准化参考音频或锁定音色；
- 私人正文/音色 render 不跨 owner/workspace 复用；
- TTS 失败不改变 working copy 和 revision。
- 当前不验收全书批量或音频导出；相关历史候选不得翻转 capability，也不得影响网页分段播放。

### 19.3 本机性能门槛

阶段 0 先记录真实基线；初始项目目标为：

- Nano 预热后标准中文黑盒实时因子必须 `RTF <= 1.0`；`RTF > 1.0` 直接失败，渐进播放只能作为独立体验证据，不能覆盖或豁免该硬门槛；
- 单任务峰值内存不导致 16 GB M4 明显换页或拖垮 QwenPaw；
- 已缓存句段可立即播放；
- 章首前缀或用户明确请求的连续 ready window 达到阶段 0 冻结门槛后可从对应合法起点播放；
- 局部重生成不触发整章 TTS；
- 不安装或常驻 VoiceGenerator；当前只运行 Nano Sidecar。

性能未达标时先优化部署、量化、加载和队列；不能通过删除版本校验、缓存正确性或复核流程换取速度。

### 19.4 人工听感验收

- 正式人物跨章可辨识且稳定；
- 旁白与主要人物明显可区分；
- 同场景路人不过度撞声；
- 无严重漏字、重复、爆音、噪声和异常停顿；
- 人物间响度基本一致；
- 独立句段接缝没有不可接受的爆音、吞字或长空白；
- 当前真实章节只允许三个已确认的中文官方预设，不接受 VoiceGenerator 候选。

时长、解码和响度检查不能发现所有漏字、重复和错读。阶段 0/4 必须对固定样本人工听检；阶段 6 可增加 ASR 回查作为质量告警，但 ASR 结果不能自动改写正文或朗读脚本。

## 20. 发布门槛

核心功能进入默认可见前必须满足：

1. 阶段 0 真实 M4 报告完成；
2. 产品目录只展示六个中文 official preset；有限核心的旁白与两名正式人物分别绑定 `onnx.Zhiming`、`onnx.Junhao`、`onnx.Xiaoyu` 并完成真实章节验收；不得把其余 12 项语言预设、24 槽、上传音色、商业审批或通用选角加入本次阻断项；
3. 数据迁移具有升级和回退测试；
4. Nano 执行后端不影响 QwenPaw 原生聊天、模型、Skills、MCP 和插件管理；
5. `local_rules_only` 的零正文外发与契约边界通过；`cloud_assisted` 可继续 false/HOLD，只有拟同时放行云端判角 capability 时才必须完成授权、实际模型、最小外发与撤销边界测试；
6. 一章真实多角色正文同时完成“零阻塞自动生成”和“阻塞暂停—处理—继续”两条链路，并通过多 Edition、局部重生成和句段跟随；
7. `partial_ready` 章首前缀和用户请求 ready window 都可从各自合法起点播放，窗口内部失败不会被跳过；
8. 关闭重开后任务、音色、Edition、Manifest 和进度可恢复；
9. 修改正文后音频可继续，播放器明确显示旧稿，旧高亮只在安全映射或不可变快照中出现；
10. 清缓存不会删除锁定音色、当前/历史 Edition 引用媒体或其他权威资产；磁盘不足会暂停新生成并给出可恢复提示；
11. T4 有限核心至少完成旁白加两名正式人物的真实验收，exact 映射固定为旁白 Zhiming、沈川 Junhao、林晚 Xiaoyu；云端辅助说话人识别和高级匿名人物选角继续 false/HOLD，不阻断有限核心，也不得借 T4-GATE 顺带放行；
12. 所有当前范围内的 P0/P1 数据安全、秘密泄漏、scope、恢复和版本一致性问题清零；商业发布／再分发／声音审批不属于本地产品门禁；
13. 普通编辑点击不触发播放，段落 gutter、上下文命令和键盘跳播通过可达性验收；
14. 工作稿自动保存不产生 TTS 任务，“更新朗读”和 Edition 切换均为显式操作；
15. 可装饰编辑器和原生 `textarea` 安全降级都通过中文输入法、撤销、长章节和页面重载测试；
16. `blockers_only`、`always_review`、阻断分类和冻结审计均通过契约与权限测试；
17. 当前宿主的 `1920×1080 × 助手收起`、`1920×1080 × 助手展开`、`2560×1440 × 助手收起`、`2560×1440 × 助手展开` 四个组合均完成真实浏览器检查；复核面板、紧凑/完整播放器和原生 AI 助手互不遮挡，旧 Edition 播放时仍有可操作控件；低于 1920×1080、移动、窄屏和 200% 等效小视口不需要验收且不阻断发布；
18. T4-K 隐藏验证期间必须是 runtime=true、validation=true、product=false、reference=false，`product_visible=false`；token 只存在于身份一致的 host/container 两个私有文件副本，请求仅一条 header，并绑定 exact novel/document 与不超过 24 小时 expiry；无／错／重复 token 的 narration/script/playback 路由必须 `404 + no-store` 且 overview 精确 T2，worker 的 claim／retry promotion／expired reconciliation 只处理该 novel/document 的允许 Nano job；有限核心拟公开放行时必须是 runtime=true、validation=false、product=true、reference=false，并通过 14.2.1 的完整 runtime/worker/readiness fail-closed 链；reference 只有独立门禁通过后才能另改为 true，不得用单一环境变量或前端隐藏代替就绪验收；
19. PawApp 包不包含 OS signing/SSHSIG/正式 key 实验、模型权重、prompt codes、生成音频或章节／全书导出实现；安装、原位升级、完整卸载后 QwenPaw 原生聊天／设置／插件管理和核心数据卷均通过非回归；
20. 关联 ADR、总体架构、迁移、API、测试和回退说明同步更新。

## 21. 仍待验证

- 已成功的 baseline Edition 作为后续播放器、CodeMirror、30 分钟稳定性、恢复与 teardown 的同 scope 可恢复基线；
- 已证明 Linux/arm64 私网 Sidecar 在正式中文章节负载下的真实 Nano 首次未缓存生成、失败恢复，以及 result/probe 2.2 的 fresh 固定精确 31 点／30 分钟技术门禁：Sidecar 首 5 点与末 5 点中位数趋势、`peak<=4 GiB`、restart=0、health failure=0、QwenPaw slowdown=false、宿主 paging telemetry 一致性、硬 RTF、pending-gap、浏览器交互和恢复均已形成同 run 证据；tree `e40d6314…` 的真实隔离安装生命周期、作者最终听检、同 run resume／teardown、长期 `0024` 升级和 product mode 均已完成；
- Web Audio 分段队列与双 `<audio>` 回退的历史真实主交互已经通过；2026-08-28 fresh canonical run 已形成合法缓存前缀加两个 miss 的 `partial_ready`，并在同一 run 完成 `browser_observed`、pending-gap 不跳过、seek latest-wins、Range/ETag 与四桌面组合证据；
- CodeMirror 6 的编辑撤销、TTS write=0 与作者系统中文输入法亲验已通过。第一次自动补证在作者合规输入后因执行器三次撤销上限返回恢复失败；正文已恢复，执行器现以 128 次有界撤销逐次核对精确 baseline digest，Node 54/54、Python 11/11 通过。四个 CodeMirror 与一个 textarea fallback 的完整自动 envelope 尚未生成，只作为非阻断证据完善项，不得反写为作者输入失败；
- 段落 gutter、上下文命令与键盘跳播，进度刷新恢复、旧稿字幕和显式“更新朗读”；本次段落／光标跳播、倍速与 seek 已通过；
- 四个 actual viewport 的焦点与 ARIA、A→B→A 章节切换和 progress reload／close-reopen 补充检查；本次精确视口、console/page error、遮挡和溢出已通过；切章重复加载的 generation／lease 修复已通过自动化，仍待新候选真实浏览器复验；
- 最小磁盘不足保护、可达性明确的派生缓存清理和权威媒体不误删代码已完成；安装生命周期非回归已经通过，当前只需在作者听检后随同一 run resume/teardown 完成最终门禁复核；
- 固定包排除签名／authority 实验和导出非目标；tree `e40d6314…` 已在隔离 run `t4rel0828` 通过安装、原位升级、完整卸载及 QwenPaw 原生功能／核心数据卷非回归，长期环境也已在 canonical teardown 后升级到 `0024` 并验证 product mode；
- 旁白 Zhiming、沈川 Junhao、林晚 Xiaoyu 的完整章节最终人工听检已经由作者明确确认通过。

云端辅助说话人识别和高级匿名人物选角仍是 `HOLD_PENDING_DECISION`，不是“待本次验证后自动放行”；T5 VoiceGenerator、完整 24 槽、英语／日语专项、云端／共享／继承音色、商业审批、OS 签名和所有音频导出均是当前非目标，不得出现在剩余工期或 T4-GATE 缺口中。

## 22. 最终验收流程

```text
进入书本“朗读”
  -> 使用 local-rules-only；云端辅助继续 HOLD
  -> 从六个中文官方预设配置旁白
  -> 在人物卡给主要人物直接绑定中文官方预设
  -> 打开章节并保存正文
  -> 复用 revision 或创建隐藏幂等 TTS 快照
  -> 生成 revision 绑定的朗读脚本版本
  -> 自动识别旁白和正式人物；高级匿名人物仅在未来独立裁决后纳入
  -> 本次 exact 映射为旁白 Zhiming、沈川 Junhao、林晚 Xiaoyu
  -> 计算 warnings 与 blockers
  -> 零阻塞时自动冻结脚本；否则作者集中处理后一次确认
  -> 冻结设置/发音/音色并创建 Edition
  -> Nano 独立句段合成并复用缓存
  -> 章首前缀和用户请求窗口形成渐进 Segment Manifest
  -> 在章节工作台点击段落 gutter，从对应句段开始朗读
  -> 播放到哪一段，正文一致时编辑器高亮到哪一段
  -> 作者边听边改，自动跟随让位于光标和输入
  -> 播放器明确显示旧稿，按键和自动保存不触发 TTS
  -> 作者点击“更新朗读”，只分析/生成必要内容
  -> 用户明确切换新 Edition，旧 Edition 仍可回放
  -> 关闭重开后恢复任务、Manifest 和播放进度
  -> 磁盘不足时暂停新生成，只清理安全可回收的派生缓存
```

只有上述链路在真实 M4、真实数据库、真实浏览器和真实中文小说章节中完整通过，才可将本方案状态改为“已实现”。
