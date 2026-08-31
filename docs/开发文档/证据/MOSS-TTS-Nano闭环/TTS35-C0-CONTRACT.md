# TTS35-C0：公共契约、状态机与迁移冻结

状态：**2026-08-29 已冻结，允许 `TTS35-W2` 按本文并行施工。**

基线：`94f6b6644df363234969f0e6882e1b8c3fb1229e`（计划 36 稳定提交）

本文只冻结计划 35 的共享边界。实现若发现本文与数据库硬约束冲突，必须暂停相应工作包并由主代理修订本文；子代理不得自行发明第二套 DTO、状态或迁移字段。

## 1. 通用规则

- HTTP 命名空间继续位于 `/api/ai-novel-world-2026`；下文路径均省略该前缀。
- 作用域固定为服务端权威的本地 owner/workspace，所有资源还必须校验 URL 中的 `novel_id`。客户端传入的 UUID 不是授权证据。
- 所有响应使用 `snake_case`；前端只在视图状态内部使用 `camelCase`，不得复制第二份协议常量。
- 新建命令的 `Idempotency-Key` 必须满足现有 `^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$`。查询、confirm、cancel、retry 与显式 apply 不接收幂等请求头。
- 外部模型或 Nano 合成不得占用数据库事务。CAS 只在模型/合成完成后的短事务中执行。
- 时间均为带时区 ISO 8601；倒计时只使用响应中的 `server_now` 与 `execute_after`，浏览器本机时间只用于计算经过量。
- 失败不得改动既有 narrator/character binding，不得静默换模型、换 preset、换 seed 或退回官方默认参数。
- `VoiceGenerator` 不属于本轮可执行能力；保持隐藏且 `VG-FINAL=BLOCKED_HARDWARE`。

## 2. 数据库最低迁移语义

- `20260829_0032` 是现有 TTS 生产运行和 digest keyring 的**最低所需迁移**，不是必须精确相等的全局 head。
- 运行态只在数据库 `alembic_version` 恰有一个、仓库可识别的线性 revision，且 `0032` 位于该 revision 的祖先链中时通过旧 TTS 最低门禁；未知 revision、多个 head、缺少 `0032` 均 fail closed。
- 计划 35 完整能力的最低所需迁移是 `20260829_0034`。`0034.down_revision` 必须精确为 `20260829_0033`，仓库仍只能有一个 head。
- 共用实现放入 `backend/narration/schema_readiness.py`，供 production runtime、digest keyring bootstrap 与 feature readiness provider 使用，禁止保留多个“精确 head”判断。
- `0034` 不执行模型、网络、媒体 unlink、数据清理或长期任务；只增加/修改 schema、约束、trigger、索引和 sentinel 所需字段。

## 3. `narration-capabilities/2`

### 3.1 新增能力键

- `character_voice_matching`
- `nano_advanced_tuning`
- `private_voice_deletion`

既有键和语义不删改；`voice_generator` 继续为 `unavailable`、隐藏、不可操作。完整矩阵仍必须恰好包含所有冻结键，不允许客户端从按钮或路由存在性推断能力。

### 3.2 唯一 readiness provider

`NarrationFeatureReadinessProvider` 是可变运行态的唯一来源，同一实例驱动 overview 能力矩阵、HTTP 服务端门禁及 runtime/health 投影。快照必须一次原子替换，字段为：

- `schema_version = narration-feature-readiness/1`
- `lifecycle_status = disabled | starting | ready | degraded | stopping`
- `generation`：单调递增整数
- `capabilities`：三项新增能力各自的 `FeatureCapability`
- `reason_code`：整体稳定原因码或 `null`
- `updated_at`

依赖矩阵：

| 能力 | 必须同时就绪 |
| --- | --- |
| `character_voice_matching` | schema `0034`、权威 character workspace、`ai-novel-writer` 公开 effective-model 边界、18 项官方目录、官方原子绑定服务 |
| `nano_advanced_tuning` | schema `0034`、存储、digest keyring、Sidecar 协议/模型指纹、Nano experiment processor、background scheduler |
| `private_voice_deletion` | schema `0034`、存储、digest keyring、精确资产计划服务、deletion reconciler |

稳定 reason code：`TTS_FEATURE_DISABLED`、`TTS_FEATURE_STARTING`、`TTS_DATABASE_SCHEMA_OUTDATED`、`TTS_STORAGE_UNAVAILABLE`、`TTS_DIGEST_KEYRING_UNAVAILABLE`、`TTS_SIDECAR_UNAVAILABLE`、`TTS_PROCESSOR_UNAVAILABLE`、`TTS_DELETION_RECONCILER_UNAVAILABLE`、`TTS_CHARACTER_WORKSPACE_UNAVAILABLE`、`TTS_NOVEL_AGENT_UNAVAILABLE`、`TTS_FEATURE_STOPPING`、`TTS_FEATURE_CRASHED`。

启动时先发布 fail-closed 快照，再逐项开启；关闭或 processor/reconciler 崩溃时先撤销对应能力，再停止任务/卸载路由后端。删除 `PRIVATE_VOICE_DELETION_RELEASED` 及同类常量门禁。

## 4. `CharacterVoiceBrief/1` 与人物卡一键匹配

### 4.1 API

`POST /novels/{novel_id}/characters/{character_id}/official-voice-match`

请求体 `character-voice-match-request/1`：

- `timeline_id: UUID | null`
- `character_instance_id: UUID | null`
- `expected_binding_version: int >= 0`

请求必须携带 `Idempotency-Key`。多时间线人物仍遵守计划 36 的 workspace 解析规则；缺少必选 timeline/instance 时返回现有 character workspace 错误，不猜测最近项。

响应 `character-voice-match/1`：

- `character_id`
- `brief: CharacterVoiceBrief/1`
- `selected_preset_id`
- `score_milli: 0..1000`
- `state: ready_applied | ready_unapplied`
- `selection_still_current: bool`
- `current_character_binding`
- `model_evidence: model-execution-evidence/2`

`ready_unapplied` 是成功结果，不是模型失败；表示模型和确定性匹配已完成，但 CAS 漂移阻止覆盖作者的新选择。页面保留匹配结果，并复用现有官方音色选择 API 作为显式“使用此音色”动作，不新增第二套绑定端点。

### 4.2 Brief

`CharacterVoiceBrief/1` 字段：

- `language: zh-CN | en | ja-JP | null`
- `presentation: masculine | feminine | androgynous | null`
- `pitch: -2 | -1 | 0 | 1 | 2 | null`
- `pace: -2 | -1 | 0 | 1 | 2 | null`
- `energy: -2 | -1 | 0 | 1 | 2 | null`
- `texture: clear | warm | airy | husky | firm | soft | bright | dark | null`
- `evidence_fields: tuple[str, ...]`

模型只能读取计划 36 workspace 快照中已保存的 character/root、selected instance profile、aliases、relationships 和 projected state；不得使用姓名刻板印象补空值。每个非空维度至少对应一个 `evidence_fields` 路径。AI 只输出 Brief，不得输出 preset ID。

### 4.3 确定性匹配

- 固定基线文件：`backend/narration/resources/official_voice_casting_v1.json`，恰好覆盖官方 manifest 的 18 个 preset，并带源音频/提取器版本/hash。
- Brief 有语言时只在同语言集合评分；语言未知时覆盖全部 18 项且语言维度不计分，不阻断。
- 仅对非空维度评分并重新归一化；权重固定为 presentation 4、pitch 3、pace 2、energy 2、texture 1。
- 同分按官方 manifest 顺序裁决。脚本只从固定、可核验的官方预览/短句音频生成基线，禁止手填听感冒充测量值。
- 模型证据为 `verified_from_provider_usage` 或 `not_exposed` 时可继续；`rejected` 时不绑定并返回可重试失败。
- 绑定复用 `OfficialVoiceSelectionService`，以模型调用前读取的 settings/binding version 做 CAS。删除 `stableOfficialVoiceAssignment`；不得静默退回 UUID 哈希分配。

稳定失败码：`CHARACTER_VOICE_WORKSPACE_INVALID`、`CHARACTER_VOICE_MODEL_UNAVAILABLE`、`CHARACTER_VOICE_MODEL_REJECTED`、`CHARACTER_VOICE_BRIEF_INVALID`、`CHARACTER_VOICE_BASELINE_INVALID`、`CHARACTER_VOICE_NO_CANDIDATE`。

## 5. Nano 高级调音

### 5.1 参数契约

协议对象 `nano-decode-parameters/3` 使用整数千分位：

- `seed: "0".."9223372036854775807"`（HTTP 使用规范十进制字符串，避免浏览器 JSON 数字丢失 int64 精度；领域与 Sidecar 仍使用整数）
- `text_temperature_milli: 100..2000`，默认 `1000`
- `text_top_p_milli: 1..1000`，默认 `1000`
- `text_top_k: 1..100`，默认 `50`
- `audio_temperature_milli: 100..2000`，默认 `800`
- `audio_top_p_milli: 1..1000`，默认 `950`
- `audio_top_k: 1..100`，默认 `25`
- `audio_repetition_penalty_milli: 1000..2000`，默认 `1200`
- `sample_mode = full`
- `max_new_frames = 375`

前端显示小数并在提交前精确转换为整数；不提供未经听检的模板。重置只恢复上述默认值；“恢复官方音色”复用官方音色选择 API。

### 5.2 API

- `GET /novels/{novel_id}/nano-voice-experiments`
- `POST /novels/{novel_id}/nano-voice-experiments`
- `GET /novels/{novel_id}/nano-voice-experiments/{command_id}`
- `PUT /novels/{novel_id}/nano-voice-experiments/{command_id}/binding`

POST 请求 `nano-voice-experiment-request/1`：

- `base_preset_id`
- `target_kind: narrator | character`
- `character_id: UUID | null`
- `expected_settings_version: int >= 0`
- `expected_binding_version: int >= 0 | null`
- `parameters: nano-decode-parameters/3`

narrator 目标禁止 character 字段；character 目标必须提供 character 与 binding version。POST 携带 `Idempotency-Key`；PUT body 提供最新 `expected_settings_version` 和目标所需的 `expected_binding_version`，不带幂等头。

列表/单项资源 `nano-voice-experiment/1`：

- `command_id`、`novel_id`、`profile_id`、`version_id`、`background_job_id`
- `base_preset_id`、目标/CAS 字段、完整参数、`parameters_digest`、`fingerprint`
- `state: pending | running | ready_applied | ready_unapplied | failed`
- `reused_version: bool`
- `preview`（可空，成功时为现有 `VoicePreview` 资源）
- `current_settings` / `current_character_binding`（按目标二选一）
- `failure_code`、`retryable`、`created_at`、`started_at`、`completed_at`

状态只允许：`pending -> running -> ready_applied | ready_unapplied | failed`，以及 `ready_unapplied -> ready_applied`。终态内容不可改；同键同请求重放同 command，同键异请求冲突。

### 5.3 持久化与验证

- 实验 Profile ID 使用 `UUIDv5(NAMESPACE_URL, "nano-experiment-profile/1:{novel_id}:{base_preset_id}")`，从而保证小说＋基础 preset 唯一；Profile 为 novel-scoped 私人 Profile。
- 实验 Version 的 `source_type=generated`、`preset_key=base_preset_id`。pending 时保持 draft；只有真实验证完成后才能成为 `state=locked`、`activation_basis=experimental_machine_validated`、`validation_basis=machine_validated`、`quality_state=accepted`。
- `voice_profile_versions.model_run_id` 在成功机器验证时必须非空并指向该 BackgroundJobAttempt 的成功 `ModelRunRecord`；官方 fixed preset 不要求 model_run。
- fingerprint 必须覆盖 preset、固定模型 identity/revision、全部参数、seed、固定验证短句的 input digest、Sidecar protocol 与 postprocess identity。相同 fingerprint 可复用已验证 Version；任一输入不同不得复用。
- 校验音频格式/时长/非空、requested/actual 模型与 revision、ModelRun success、parameters digest、输入 HMAC、输出 SHA-256。任何一项失败均不绑定。

稳定失败码：`NANO_EXPERIMENT_MODEL_UNAVAILABLE`、`NANO_EXPERIMENT_SYNTHESIS_FAILED`、`NANO_EXPERIMENT_AUDIO_INVALID`、`NANO_EXPERIMENT_MODEL_IDENTITY_MISMATCH`、`NANO_EXPERIMENT_PARAMETERS_MISMATCH`、`NANO_EXPERIMENT_OUTPUT_HASH_MISMATCH`、`NANO_EXPERIMENT_DATABASE_FAILED`。

## 6. 私人音色生命周期

### 6.1 API

- `GET /novels/{novel_id}/private-voice-lifecycle`
- `POST /novels/{novel_id}/voice-profiles/{profile_id}/deletion-requests`
- `GET /novels/{novel_id}/voice-deletion-requests/{request_id}`
- `POST /novels/{novel_id}/voice-deletion-requests/{request_id}/confirm`
- `POST /novels/{novel_id}/voice-deletion-requests/{request_id}/cancel`
- `POST /novels/{novel_id}/voice-deletion-requests/{request_id}/retry`

创建 body 只含 `expected_profile_version`，并保留 `Idempotency-Key`。服务端根据权威 impact 自动选择：无任何当前/历史引用为 `discard_unreferenced_private_voice`，否则为 `true_delete_private_voice`；客户端不提交命令类型。confirm body 只含 `expected_profile_version` 与 `impact_digest`；cancel/retry 无 body。

生命周期列表 `private-voice-lifecycle/1` 返回每个 novel-scoped uploaded/generated Profile 的：

- Profile/当前 Version 身份、显示名、source type、profile version
- `eligibility: unreferenced | referenced | blocked`
- `blocked_reason`
- 权威引用数量、资产数量、总字节与影响摘要
- 当前活动 deletion request 或 `null`

官方 preset 不出现在列表中，所有删除入口必须隐藏。

### 6.2 请求资源和状态

资源升级为 `private-voice-deletion/2`，状态：

- pre-fence：`grace_pending | requested | failed(VOICE_DELETE_WAITING_FOR_JOBS)`
- fenced：`live_deleting | live_deleted_backup_pending | failed`
- 终态：`completed | cancelled | superseded`

每个响应除现有字段外必须包含：`server_now`、`cancellable`、`retryable`、`terminal`、`superseded_at`、`job_drain_started_at`、`job_drain_deadline`。稳定派生规则：

- `cancellable=true`：仍在 30 秒内的 grace、未确认 requested、或尚未物理围栏的 `VOICE_DELETE_WAITING_FOR_JOBS`。
- `retryable=true`：`VOICE_DELETE_WAITING_FOR_JOBS` 或围栏后临时 unlink/storage/finalize 失败。
- `terminal=true`：completed/cancelled/superseded，或不可重试安全失败。
- `superseded` 必须释放活动唯一槽；completed/cancelled 同样不占槽。围栏后 failed 保留槽和原精确资产计划。

状态转换：

- `grace_pending -> cancelled | live_deleting | failed(waiting) | superseded`
- `requested -> cancelled | live_deleting | failed(waiting) | superseded`
- `failed(waiting) -> cancelled | live_deleting | superseded`
- `live_deleting -> completed | live_deleted_backup_pending | failed`
- `live_deleted_backup_pending -> completed | failed`
- `failed(fenced) -> live_deleting | live_deleted_backup_pending | completed | failed`
- 三个终态不可变。

`0034` 增加 `superseded_at`、`job_drain_started_at`、`job_drain_deadline`，更新 check/trigger/活动唯一索引。Profile 版本漂移、impact/digest/资产集合变化、impact 过期或 job drain 超时在围栏前均在同一事务转为 `superseded`，failure code 分别为：

- `VOICE_DELETE_PROFILE_CHANGED`
- `VOICE_DELETE_IMPACT_CHANGED`
- `VOICE_DELETE_IMPACT_EXPIRED`
- `VOICE_DELETE_JOB_DRAIN_TIMEOUT`

围栏后可重试：`VOICE_DELETE_UNLINK_FAILED`、`VOICE_DELETE_STORAGE_TEMPORARY`、`VOICE_DELETE_FINALIZE_FAILED`。不可重试安全失败：`VOICE_DELETE_SCOPE_INVALID`、`VOICE_DELETE_FILE_IDENTITY_INVALID`、`VOICE_DELETE_ASSET_PLAN_INVALID`。

### 6.3 Reconciler

- 启动扫描一次；创建/确认/cancel/retry/worker 状态变化通过 `asyncio.Event` 唤醒。
- 每次最多领取 25 个请求；下次唤醒取最近 `execute_after` / `job_drain_deadline`，无 deadline 最长休眠 60 秒。禁止持续 5 秒轮询。
- grace 到期自动推进；waiting jobs 在 deadline 前自动重试，deadline 到期 supersede；已围栏的精确计划自动收敛。
- 停机先让 readiness provider 撤销 `private_voice_deletion`，再停止领取新请求；已持久化计划由当前或下次启动收敛。

## 7. `0034` 唯一 owner 字段

唯一迁移文件：`backend/migrations/versions/20260829_0034_narration_voice_lifecycle_and_experiments.py`。

ORM/迁移最小集合：

1. `voice_profile_versions.model_run_id` 可空 FK；更新 locked/machine-validated check。
2. 新表 `nano_voice_experiment_commands`，包含第 5 节 command 资源所需 scope、目标、CAS、状态、幂等、digest/fingerprint、资源 FK 和时间字段。
3. `voice_deletion_requests` 增加第 6 节三个时间字段；状态/check/trigger/index 支持 superseded。
4. schema sentinel 必须检查新表、列、约束/trigger 和单一 Alembic 祖先链，不得只比较字符串 head。

降级仅移除 `0034` 新增 schema；不得删除媒体或执行模型。存在 `0034` 业务记录的长期环境不做 schema downgrade，代码回退采用关闭能力并保留数据库/媒体卷。

## 8. 旧路径清理清单

仅在新流程接线并通过对应回归后删除：

- 前端 6 音色 `PRODUCT_OFFICIAL_PRESET_*` 限制与重复目录常量；公共 18 项证据保留。
- `stableOfficialVoiceAssignment` UUID 哈希自动分配及调用者。
- 计划 36 已替代的旧人物弹窗源码 token 断言。
- production runtime、digest bootstrap 与测试中把 `0032` 当精确全局 head 的判断。
- 已确认零调用者的旧播放器/重复样式。

不得删除已执行迁移、负向/恢复/兼容测试或历史验收原始证据。

## 9. C0 自查裁决

- 契约没有新增版权、语言、试听、名称或人工质量确认门禁。
- 官方 preset 继续零确认直用；人物匹配和高级调音均一次点击后自动尝试 CAS 绑定。
- AI 不决定 preset，未知人物声音字段不会被模型臆测；确定性评分可复现。
- 高级参数先真实异步验证，失败不动原绑定；相同输入可复用，不同输入不串缓存。
- 删除倒计时、资格、影响和可操作性均由服务端权威返回；漂移有 `superseded` 终态。
- 能力、HTTP 和 health 共用一个 provider，启动/崩溃/关闭均 fail closed。
- `0032` 兼容缺陷被纳入本计划，`0034` 仍线性接续 `0033`。
- VoiceGenerator 没有下载、按钮或空表/API；本轮只交付官方音色匹配。

裁决：`TTS35-C0=PASS`，可以派发 `TTS35-B1/B2/B3/B4/B5`，但共享 DTO、ORM、迁移、API、runtime 和入口接线继续由主代理唯一持有。
