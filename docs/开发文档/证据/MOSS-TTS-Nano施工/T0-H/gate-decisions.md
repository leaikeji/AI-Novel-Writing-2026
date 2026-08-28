# T0-H 数据、API 与安全契约冻结候选

> **现行官方预设范围覆盖（2026-08-27）：** 本文对第三方示例、真人／名人声音和权利记录的约束继续适用于用户上传、外部素材、生成声音、主动仿声以及商业发布／再分发；不适用于按 fixed manifest exact ID 使用的个人本地 `official_preset`。全部 18 项官方预设（包括 `Trump`、`Xiaoyu`）均可本地展示、试听、绑定、合成和播放，不设公众人物排除名单。

状态：**由主集成代理依据 T0-H 只读审计作出的 T0-GATE 冻结输入；尚未实施数据库、API、任务或 GC。只有 T0-GATE 接受且物理部署门禁通过后，本文列出的 T1 工作包才能进入 ready set。**

决策日期：2026-08-26（Asia/Shanghai）。

关联证据：[契约审查](./contract-review.md)、[威胁模型](./threat-model.md)、[ADR-0005](../../../ADR/ADR-0005-MOSS-TTS本地运行拓扑与资源边界.md)、[ADR-0006](../../../ADR/ADR-0006-朗读编辑器与Manifest播放契约.md)。

## 1. 冻结原则

- 本文解决 `contract-review.md` 第 15 节的 10 个施工前裁决，不代表实现完成。
- 所有 ID、state、severity、fingerprint、rights 和引用关系以服务端/数据库为权威；请求体、模型输出和媒体 URL 不能提供 scope 或批准结论。
- T1-D 是 schema/Alembic 唯一 Owner；T1-A 先冻结代码常量/DTO，T1-C/E/F 只能消费已冻结契约，不能各自发明枚举或 JSON 权威字段。
- 所有 `approved`、locked voice、Edition 制作输入、ready render 和 Manifest revision 均不可变；变化通过新版本、新事件或新指针表达。

## 2. 裁决 1–2：固定本地主体与 novel scope

### 2.1 实际类型和值来源

首版 `owner_id`、`workspace_id` 均为 PostgreSQL/SQLAlchemy UUID。服务端常量固定为：

```text
scope_contract_version = narration-scope/1
owner_id                = 29cf94d9-a5c9-54ec-912c-5dfff8738c4c
workspace_id            = f0e2e632-bc99-52d2-9916-bb906aa4da6e
app_id                  = ai-novel-world-2026
is_local_only           = true
```

两个 UUID 分别由 UUIDv5(`NAMESPACE_URL`, `app://ai-novel-world-2026/local-owner/v1`) 与 UUIDv5(`NAMESPACE_URL`, `app://ai-novel-world-2026/local-workspace/v1`) 得出。它们只是当前个人版的服务端结构隔离标签，不是登录凭据，也不冒充已经实现多用户认证。前端、Agent、模型、session、header、query 和请求体都不能覆盖它们。

### 2.2 唯一 scope 权威

- 选择在 `novels` 直接增加非空 `owner_id/workspace_id`，不建立第二套 `novel_security_scopes` 映射。
- T1 migration 先用上述固定值回填全部既有 novel，再设非空、索引和 `(id, owner_id, workspace_id)` 唯一约束；ORM 与数据库默认只服务迁移/本地创建，服务层仍显式注入 scope。
- TTS 顶层表携带 `owner_id/workspace_id/novel_id`，通过复合 FK 或同等数据库约束保证三者与 novel 一致；子表通过不可为空的父 FK 继承 scope。跨作品私人 voice 可令 `novel_id` 为空，但永不跨 owner/workspace。
- 缓存、幂等和媒体查找至少包含 `(owner_id, workspace_id, fingerprint)`；首版禁止跨 scope 命中。
- 未来若 QwenPaw 提供经过验证的公开身份/工作区契约，必须以新迁移和新 ADR 替换固定 scope；不得读取其私有数据库或把 Agent ID 当用户 ID。

## 3. 裁决 3：approved script 与 stale 派生位置

- `narration_script_versions.state=approved` 是终态；approved 行的正文/范围、issue、casting、fingerprint、计数和审批审计禁止 UPDATE。
- `document_narration_state` 是每 `(owner_id, workspace_id, document_id)` 唯一的 CAS 指针表，只保存 `current_script_version_id`、`current_edition_id`、`version`、切换 actor/time；不保存可漂移的 `stale=true/false` 权威位。
- 查询时比较当前 working copy/revision 的 `content_hash`、当前 narration settings fingerprint 与被指向 script/Edition 的冻结输入，派生 `current | working_copy_diverged | superseded | unavailable`。
- 切换 current 指针不修改旧 script/Edition；旧版本继续按权限、权利和保留策略读取。

## 4. 裁决 4：`narration_requests`、状态与 Edition 反向约束

### 4.1 精确字段

`narration_requests` 至少包含：

```text
id, owner_id, workspace_id, novel_id, document_id?
intent, request_hash, idempotency_key
source_revision_id?, source_content_hash?, settings_fingerprint
force_review, effective_policy
state, version
explicit_generation_intent_at?, explicit_generation_actor?
cancel_requested_at?, cancel_actor?, cancel_reason_code?
failure_code?, created_at, updated_at, completed_at?
allows_edition, allows_render（由 intent 生成并受 CHECK 约束的数据库 guard）
```

- `intent = analyze_only | create | update | batch`；`force_review` 只能把策略收紧为 `always_review`。
- `create|update` 必须绑定同 document 的不可变 `source_revision_id/content_hash`；`batch` 使用 `narration_request_sources` 逐项冻结 document/revision/hash，不能只把 revision 列表塞进自由 JSON。
- `explicit_generation_intent_at/actor` 对 `create|update|batch` 必填，对 `analyze_only` 必须为空。
- 唯一 `(owner_id, workspace_id, idempotency_key)`；同 key/同 canonical request hash 返回同一记录，同 key/不同 hash 返回 `409 idempotency_conflict`。

### 4.2 状态机

请求状态冻结为：

```text
created -> analyzing | cancel_requested
analyzing -> analyzed | review_required | queued | cancel_requested | failed
review_required -> analyzing | queued | cancel_requested | failed
queued -> rendering | cancel_requested | failed
rendering -> partial_ready | ready | cancel_requested | failed
partial_ready -> ready | cancel_requested | failed
cancel_requested -> cancelled
```

- `analyze_only` 只能终止于 `analyzed|review_required|failed|cancelled`，不能进入 `queued|rendering|partial_ready|ready`。
- `queued` 只在同一短事务内完成 approved script 与合法 Edition 创建后进入；`approved` 是 script 状态，不额外作为 request 状态。
- `partial_ready/ready` 是与 request/Edition 关联的领域汇总，不替代 segment job 状态。

### 4.3 数据库防绕过

- `allows_edition` 与 `allows_render` 都由 intent 生成并受 CHECK 约束：只有 `create|update|batch` 为 true，`analyze_only` 两者必须为 false；父表分别提供唯一 `(id, allows_edition)`、`(id, allows_render)`，不能由请求 DTO 传入或更新。
- `narration_editions` 携带常量 `request_allows_edition=true`，以 `(request_id, request_allows_edition)` 复合 FK 指向 request；`narration_segment_renders` 同理以 `(request_id, request_allows_render=true)` 复合 FK 防止 analyze-only 创建 render。Edition 还以 approved guard 复合引用 `narration_script_versions`。
- `background_jobs` 的 narration job 保存可空 `request_id/request_allows_render`；`narration.segment_render|narration.export` 必须为 true 并通过 request 复合 FK，`narration.analyze` 可引用 false。CHECK 同时拒绝把 render/export job 伪装成 analyze job 后发布结果。
- segment master/playback 媒体只能由合法 `narration_segment_renders.master_asset_id/playback_asset_id`（或语义等价的结构化 FK link）可达；生成类媒体不接受自由 request ID/JSON 来源。删除 render FK 或直接插入媒体都不能让 analyze-only 结果进入 Manifest。source upload/voice reference 属于独立用户资产，不受 generation request guard 混淆。
- 服务层在同一短事务内重新计算 blocker、scope、source/settings/model fingerprint、显式 actor/time 和两项 guard；API/领域/job/DB 负向测试分别断言 analyze-only 新增 Edition、render、render/export job 和生成媒体数量都为 0。
- T1/T4 不开放“只凭客户端 payload 创建 Edition”的公共 HTTP 旁路；`POST narration-requests` 是唯一编排入口，approve/recovery API 也调用同一领域服务。
- T1-F 是 `requests.py` 基础不变量与持久状态唯一 Owner；T4-A 只在其后补产品编排、Edition/render cache 和 API，不能复制第二套 request 逻辑。

## 5. 裁决 5：`narration-review-taxonomy/1`

置信度首版只接受 `high | medium | low | unknown`。`low|unknown` 进入 blocker，`medium` 进入 warning，`high` 仍须通过 scope/唯一候选/voice/rights 等确定性规则；模型自报数值不能直接决定 severity。

Warnings：

```text
W_SPEAKER_MEDIUM_CONFIDENCE
W_NEW_ANONYMOUS_SPEAKER
W_GENERIC_VOICE_FALLBACK
W_MANUAL_OVERRIDE_INHERITED
W_PRONUNCIATION_SOFT_FALLBACK
W_CLOUD_ASSISTED_USED
W_SCENE_BOUNDARY_MEDIUM_CONFIDENCE
```

Blockers：

```text
B_SPEAKER_UNKNOWN
B_SPEAKER_LOW_CONFIDENCE
B_CHARACTER_ALIAS_CONFLICT
B_CHARACTER_REFERENCE_INVALID
B_ANONYMOUS_IDENTITY_CONFLICT
B_CASTING_TARGET_UNRESOLVED
B_VOICE_MISSING
B_VOICE_VERSION_UNAVAILABLE
B_VOICE_RIGHTS_UNAVAILABLE
B_PRONUNCIATION_HARD_CONFLICT
B_CLOUD_DECISION_UNAVAILABLE
```

Workflow failures（不能伪装成 issue 后自动批准）：

```text
F_ANALYZER_RUNTIME
F_MODEL_IDENTITY_MISMATCH
F_MODEL_OUTPUT_SCHEMA_INVALID
F_INPUT_FINGERPRINT_CHANGED
F_SCOPE_VIOLATION
F_CONSENT_REVOKED_BEFORE_CALL
F_ADAPTER_UNAVAILABLE
```

`B_VOICE_RIGHTS_UNAVAILABLE` 专门覆盖 rights record 缺失，以及当前事件为 revoked、expired 或 review_blocked；不得复用“版本不可用”掩盖权利原因。`narration_script_issues` 是 script version 的不可变子表，保存 taxonomy version、code、服务器计算的 severity、可空 segment、公开证据摘要/不可逆 digest；作者修正创建新 script version，不 PATCH 旧 issue。blocker/warning 计数由行重算并在批准事务中复核。

唯一 Owner：T1-A 在 `backend/narration/contracts.py` 和 fixture 冻结常量/DTO；T1-D 建表与约束；T1-F 只持久化/读取；T3-H 实现确定性分类器与复核；T3-I 对全部 code、非法 code、模型伪造 severity 和零 blocker 审批做负向测试。修改含义必须发布 taxonomy v2。

## 6. 裁决 6：job fencing、attempt 与 manual retry

共享 `background_jobs` 继续作为逻辑任务，不创建独立 narration job 表。最小字段：scope、`job_kind`、canonical input hash、幂等键、base/临时交互优先级与过期时间、resource class、状态、max attempts、attempt count、next retry、取消字段、进度、安全错误码和时间戳。唯一键至少为 `(owner_id, workspace_id, idempotency_key)`；canonical input 创建后不可改。

状态冻结为：

```text
queued -> running -> succeeded
queued -> cancelled
running -> retry_wait | failed | dead_letter | cancel_requested | succeeded
retry_wait -> queued
cancel_requested -> cancelled
failed | dead_letter -> queued（仅显式 manual retry，新 attempt）
```

`background_job_attempts` 为追加式 attempt 审计，至少保存 `job_id/attempt_number`、`retry_kind=initial|automatic|manual`、manual actor/reason、`lease_owner/lease_token/lease_generation/lease_until/heartbeat_at`、开始/完成时间、错误分类/码和 actual result digest；唯一 `(job_id, attempt_number)`。每次领取在 `FOR UPDATE SKIP LOCKED` 短事务内创建新 attempt 与随机 lease token；heartbeat、取消确认、媒体发布和完成都必须匹配 `job_id + attempt_id + lease_token + lease_generation`。

- 活动 request timeout、协议错序、worker identity 错或 adapter poison 后不得继续使用同一 generation；必须显式重启。
- lease 过期、旧 attempt、取消后或插件 epoch 失效的迟到结果不能发布，即使底层模型最终返回成功。
- manual retry 不改旧 attempt/input；保存 actor/reason，创建 `attempt_number+1`，超出自动 max attempts 也必须显式操作。
- `model_run_records` 追加引用精确 attempt，记录 requested/actual provider/model/revision、参数/input/output digest、耗时和结果分类。
- `background_resource_locks` 每 resource key 只有一个当前 lease，采用独立 token/generation；重模型任务必须同时持有 job attempt lease 与 resource lease。
- 执行器 single-flight；并发调用同一 adapter 必须 fail-closed，不能让 JSONL/媒体响应交错。

## 7. 裁决 7：Manifest 主键、保留与 GC

- `narration_manifests.id` 为 UUID 主键，唯一 `(edition_id, manifest_revision)`；revision 从 1 单调增加，整行和 segment 子行插入后不可变。
- 公共 Manifest 唯一 wire shape 消费 T0-G 冻结的 `narration-manifest/2.0` snake_case schema：segment ordinal 从 0 连续递增，range 为半开 `end_ordinal_exclusive`，服务端 `ready_ranges/ready_prefix_count/default_start_ready/last_playable_start_ordinal/status` 必须可由 `segments + buffer_policy` 精确复算。数据库可持久化不可变 Manifest JSON/派生索引，但不得形成与 segment 行冲突的第二套状态权威。
- `narration_edition_state` 每 Edition 一行，CAS 保存 `current_manifest_id/current_manifest_revision/version`；current pointer 与 Manifest 内容分离。相同 revision 不同 ETag 是 `revision_collision`，不得覆盖。
- `document_narration_state` 只选择当前 Edition；播放中不能因指针变化静默换 Edition。
- T1 对所有历史 Edition/Manifest revision 采用**无限期保留**的保守策略；任何历史 Manifest、Edition、export、locked voice、voice reference、源资产或未过期运行租约可达的资产都是 GC root。T1 不实现“为了配额删除历史朗读”。
- 普通 GC 只处理可重建派生物：无结构化 FK 引用且无活跃 job 的 staging/orphan 满 24 小时后可成为候选；ready 派生资产必须先写 generation mark，等待至少 7×24 小时，再在同一 scope 一致性快照中复核引用/generation，仍不可达才物理删除并写 tombstone。
- source upload、normalized reference、locked voice source 永不进入普通 GC；引用权威来自明确 FK 列和已知表，不扫描 JSON、文件名或目录。
- 文件删除失败保持 `deleting` 并重试；不能先把数据库写成 deleted。数据库提交失败后的 content-addressed orphan 也服从 24 小时 + mark/recheck，不直接提供媒体 API。
- T6 若要引入历史 Edition 配额/保留期限，必须以新的用户可见策略、迁移、影响预览和 ADR 重开；不能静默缩短本冻结值。

## 8. 裁决 8：声音权利权威表

采用独立、结构化、不可变权利记录，不允许 `rights_json` 成为唯一权威：

- `voice_rights_records` 保存 source kind、来源/许可标识、声明文本版本、用途、商用/再分发/克隆范围、确认 actor/time、可空 subject consent、到期时间和项目风险标记；记录插入后不可改。
- `voice_rights_events` 追加保存 `confirmed | revoked | expired | review_blocked`，当前是否允许新使用由事件序列和时间确定；撤权不改写旧记录。
- locked `voice_profile_version` 引用精确 rights record；历史 Edition 保留当时引用，但撤权后新 request 必须 blocker，除非权利记录明确允许历史继续播放。
- 用户勾选声明只是权利证据的一部分，不能把第三方示例、外部公众人物声音或 NOASSERTION 资产自动变成可分发／商用。该商业／外部来源规则不降低固定 ONNX manifest 官方预设的个人本地可用性。
- T0-E 当前 24/24 槽均没有通过权利与听感，正式通用音色能力继续关闭。

## 9. 裁决 9：私人短文本 HMAC/pepper

- 私人短台词、spoken text、候选描述等用于日志、诊断、去重或模型审计时，使用 versioned `HMAC-SHA256`；行内只存 `digest_key_id + digest`，不存裸 SHA-256 或原文。
- keyring 是 32 字节以上随机密钥文件，位于受控 `qwenpaw-secrets`/项目 secret 持久卷；仓库、`.env`、数据库、日志、证据、Sidecar 镜像和浏览器均不得包含密钥。环境变量最多提供受控 keyring 文件路径，不传原始密钥。
- 新写入只使用 active key；轮换保留旧 key 为只读校验直到相关缓存/审计保留期结束，不批量改写不可变历史。每条记录保存 key ID。
- 备份必须同时覆盖数据库与 secret volume。keyring 丢失时 TTS 新 fingerprint/去重 fail-closed；不得静默生成新 key 冒充旧 scope。恢复旧 key 或执行显式 rekey/cache-miss 迁移后再开放能力。
- DocumentRevision/媒体的权威内容 SHA-256 仍用于 CAS、字节校验和 ETag，但只在服务端受控字段使用，不回显在普通日志/列表；HMAC 不替代媒体完整性哈希。

## 10. 裁决 10：彻底删除私人音色、历史与备份

两个命令必须分离：

1. `delete_uploaded_original_only`：仅在规范化 reference/locked version 已独立校验且用户确认影响后删除上传原件；不删除仍被 voice version 引用的规范化源。
2. `true_delete_private_voice`：先停止新绑定/生成/播放租约，生成不可变影响快照并二次确认；随后删除 live upload、normalized reference、preview、使用该 voice 的 segment/播放副本/导出，撤销媒体读取并保留最小 tombstone。

彻底删除不级联删除小说正文、DocumentRevision、script/Edition/Manifest 审计行；受影响历史 Edition 变为 `unavailable_private_voice_deleted`，保留不可枚举 ID、删除请求 ID、actor/time、scope、HMAC digest 和原因码，不保留人声、自由描述、服务器路径或可复原元数据。浏览器已取得的本地 Blob 无法远程追回，UI 必须在确认前说明。

`voice_deletion_requests` 与 `asset_tombstones` 追加记录 live 删除、失败重试和备份状态。应用只能清理自己登记的 live 数据与专属 TTS 备份，不能静默修改 QwenPaw/数据库的未知备份：

```text
requested -> live_deleting -> live_deleted_backup_pending
          -> completed（已核实全部受管备份清除/到期）
          -> failed（保留可重试证据）
```

在受管备份清除/到期得到证据前，不得向用户声称“所有副本已永久删除”。普通“清缓存”和 GC 永不调用 true-delete。

## 11. T1 唯一 Owner、测试与阶段门禁

| P0 | 冻结 Owner 顺序 | T1 必须测试 | Gate |
| --- | --- | --- | --- |
| H-P0-01 scope | T1-A constants/DTO → T1-D schema → T1-G 集成 | 客户端伪造 scope、跨 novel/voice/media/job、统一 404、既有 novel 回填 | T1-GATE |
| H-P0-02 approved/stale | T1-D guard/指针 → T1-F service → T1-G | approved UPDATE 拒绝、working copy divergence 派生、切换不改历史 | T1-GATE |
| H-P0-03 request/analyze-only | T1-D DB guard → T1-F request 基础 → T4-A 编排 | 同/异 payload 重放、direct Edition、analyze-only 对 Edition/render/media 各表新增 0 | T1-GATE + T4-GATE |
| H-P0-04 taxonomy | T1-A 常量/fixture → T1-D issue 表 → T3-H/I 分类器 | 全 code、未知 code、模型伪 severity、计数重算、v1 不可漂移 | T1-GATE 契约 + T3-GATE 行为 |
| H-P0-05 job fencing | T1-D schema → T1-C runner → T1-G kill/lease → T4-B 真 worker | SKIP LOCKED、timeout poison、双 worker、迟到发布、cancel、manual retry、资源锁 | T1-GATE + T4-GATE |
| H-P0-06 Manifest/GC | T1-D FK/schema → T1-E storage/GC → T1-F append/pointer → T1-G 竞态 → T4-D 播放 → T6-F 配额 | revision collision、旧 revision、24h/7d 时钟、引用变化取消删除、source 删除数 0 | T1-GATE 起逐门禁 |

只有上述常量、表语义和文件 Owner 同步进入主计划，T0-H 才不再阻断 T1-C/D/E/F；任何后续机械字段调整必须保持这些约束并由主集成 Owner记录。
