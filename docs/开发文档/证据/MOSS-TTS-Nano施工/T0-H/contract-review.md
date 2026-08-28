# T0-H 契约审查：数据、API、状态机与治理

状态：**T0-H 只读审查已完成；T0-GATE 暂不得把本报告中的建议视为已实现。下列 P0 必须先由主代理冻结到 ADR/契约，再进入 T1 schema 施工。**

> 本文保留审查形成过程，但公共 wire 的最终裁决以 [gate-decisions.md](./gate-decisions.md) 和 T0-G 证据为准。后续修订已将下方 Manifest 版本、ordinal/range 与 ETag 示例对齐该唯一裁决；不得从历史建议恢复第二套协议。

> **官方预设范围更正（2026-08-27）：** 本文关于“未经授权真人／名人克隆”的限制只适用于用户上传、文字描述生成、外部素材和主动仿声，不得用于过滤固定 ONNX manifest 的个人本地 `official_preset`。全部 18 项官方预设均可本地使用，包括 `Trump`、`Xiaoyu`；商业发布／再分发风险记录仍独立保留且不参与本地 usability。

审查日期：2026-08-26（Asia/Shanghai）

审查范围：MOSS-TTS-Nano 专项的数据模型、API、状态机、权限与范围、后台任务、媒体、朗读脚本、Edition、render、复核策略、问题分类、声音权利和隐私。

权威输入：

- [MOSS-TTS-Nano 专项设计](../../../18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md)
- [架构边界与模型接入决策](../../../01-架构边界与模型接入决策.md)
- [总体架构与核心流程](../../../06-总体架构与核心流程.md)
- [创作工作台内容模型与关系图产品规格](../../../09-创作工作台内容模型与关系图产品规格.md)
- [当前 ORM](../../../../../backend/models.py)、[领域服务](../../../../../backend/services.py)、[PawApp API](../../../../../backend/app.py)
- [ADR-0001](../../../ADR/ADR-0001-QwenPaw原生聊天组合与小说Agent作用域.md)、[ADR-0002](../../../ADR/ADR-0002-MVP0正文版本与崩溃恢复.md)、[ADR-0003](../../../ADR/ADR-0003-QwenPaw原生助手上下文与受控编辑边界.md)、[ADR-0004](../../../ADR/ADR-0004-选区AI编辑任务与中央统一Diff审阅.md)

## 1. 审查结论

专项设计已经覆盖大多数产品边界，但还不能直接转成 T1 migration/API。当前结论是：

- 工作包 T0-H 的只读审查本身完成；
- 数据/API 契约门禁为 `HOLD`；
- 发现 6 项 P0、10 项 P1 和 5 项 P2；
- P0 都有局部可实现的收敛方案，不要求修改 QwenPaw 上游，也不要求建设 RBAC 或第二套业务服务；
- T1 只能在主代理冻结第 4–12 节的契约并由 T0-GATE 接纳后开始。

### 1.1 P0 清单

| ID | 问题 | 风险 | 必须冻结的处理 |
| --- | --- | --- | --- |
| H-P0-01 | `owner_id/workspace_id` 被目标 schema 和缓存规则引用，但当前 HTTP 业务 API 没有可信用户身份，现有小说表也没有 owner/workspace 归属 | UUID IDOR、跨作品/未来跨 owner 数据混用；错误宣称多用户安全 | 采用“固定本地安全主体 + 服务端解析”的个人版契约；主体绝不来自请求体、模型或任意 header，并明确它不是多用户认证 |
| H-P0-02 | `narration_script_versions` 同时被要求“approved 后不可变”和“新脚本成为当前后把旧版标为 stale” | 修改冻结行会破坏哈希、审批和 Edition 审计 | `approved` 成为终态；`stale/superseded` 改为当前指针比较所得的派生状态，不更新已冻结 script version |
| H-P0-03 | API 定义了 `narration-requests` 单入口，但数据模型没有持久的领域请求；同时保留直接 `editions` 接口 | `analyze_only`、显式生成意图和幂等重放无法可靠证明；直接接口可能绕过审批 | 增加持久 `narration_requests` 领域记录；任何 Edition 必须绑定合法 create/update/batch request，`analyze_only` 由数据库关系和服务层双重阻断 |
| H-P0-04 | warnings/blockers 只有自然语言示例，没有冻结代码表、分类版本和确定性计算规则 | 不同模块可把同一问题降级，`auto_no_blockers` 可能错误放行 | 冻结 `narration-review-taxonomy/1`；严重度只由服务端分类器决定，模型/客户端不能提交 severity、计数或 approval kind |
| H-P0-05 | job 有租约字段目标，但没有 fencing token、完成发布顺序和取消后发布规则 | 过期 worker、重试 worker或取消任务可能重复写 render/Manifest | 原子领取 + lease generation/token；外部调用不占长事务；最终发布必须比较 job/attempt/token、scope、consent、cancel 和 fingerprint |
| H-P0-06 | 媒体目标包含 Range/ETag/GC 和旧 Manifest revision 可读，但未冻结 Manifest 追加方式、资产可达性真相和物理删除协议 | GC 可删历史 Edition/参考音频，或覆盖旧 Manifest 使播放无法恢复 | Manifest revision 采用追加式不可变行；媒体只从显式 FK 可达图回收，先标记/宽限/复核再物理删除；普通清缓存永不触及源资产 |

### 1.2 P1/P2 摘要

| 等级 | ID | 缺口 |
| --- | --- | --- |
| P1 | H-P1-01 | 批量 PUT、PATCH 与领域命令的 CAS/替换语义尚未逐接口冻结 |
| P1 | H-P1-02 | direct `editions`、retry、cancel、prepare-range 的授权输入与错误码不完整 |
| P1 | H-P1-03 | requested/actual 模型身份需扩展到 provider/model/revision/权重/tokenizer/adapter，而不只是显示名 |
| P1 | H-P1-04 | consent 在排队、真正外发前、外发后提交三个时间点的撤权处理未冻结 |
| P1 | H-P1-05 | 声音权利记录、授权到期/撤销、真人/名人滥用和彻底删除后的历史 tombstone 尚无结构契约 |
| P1 | H-P1-06 | 私人短文本使用普通 SHA-256 作为审计/缓存键可能被字典推测；日志脱敏没有字段级规则 |
| P1 | H-P1-07 | 跨表同 scope 约束只写成服务规则，尚未确定哪些由复合 FK/唯一约束保证 |
| P1 | H-P1-08 | job 的 retryable/final failure、manual retry、attempt 历史和 dead-letter 重新入队语义不明确 |
| P1 | H-P1-09 | Edition/Render 哪些字段可变、ready 后哪些字段永久冻结尚未逐字段列出 |
| P1 | H-P1-10 | 插件卸载/升级尚未包含 TTS worker、模型子进程、租约释放和媒体路由非回归断言 |
| P2 | H-P2-01 | SSE 断线续传 cursor、事件保留时长和慢消费者策略待 T4 冻结 |
| P2 | H-P2-02 | GC 影响预览、预计释放空间和删除审计的 UX/API 分页待后续阶段冻结 |
| P2 | H-P2-03 | taxonomy/schema 向前兼容和旧客户端只读降级策略未定义 |
| P2 | H-P2-04 | 并发试听/prepare-range 的公平老化参数与资源配额需由真实基准决定 |
| P2 | H-P2-05 | 隐私事件和异常缓存命中的指标只定义最小聚合口径，具体观测方案待实现阶段决定 |

## 2. 当前事实、设计目标和施工缺口

下表严格区分“现在已有”与“目标设计”。

| 领域 | 当前实现事实 | 专项目标 | 施工缺口 | 等级 |
| --- | --- | --- | --- | --- |
| 身份/权限 | 项目是本机个人 PawApp；普通业务 API 依赖 UUID 查找，未建立真实用户认证；助手 workspace 工具另有服务端 scope，但不能直接当作 TTS HTTP 身份 | owner/workspace/novel 全链路隔离 | 冻结固定本地主体、scope dependency 和统一非枚举失败；不得声称 RBAC/多用户安全 | P0 |
| 正文版本 | working copy 有 `draft_version/content_hash` CAS；revision 保存不可变 Markdown/text/hash | 创建不污染 working copy 基线的幂等 `tts_snapshot` | 新增唯一键、并发 revision number 分配和隐藏历史策略；不能复用当前 manual checkpoint | P0 |
| 任务 | 当前是章节/创作专用 job；没有共享 background job 租约执行器 | 共享 `background_jobs`、原子领取、重试、死信、取消和资源分类 | 新 schema、runner、fencing、attempt 审计和发布协议全部尚未实现 | P0 |
| 模型证据 | 现有创作任务已比较 requested/actual provider/model，不匹配即失败 | 聊天分析、Nano、VoiceGenerator 都保存精确实际 fingerprint | 增加 revision/hash/tokenizer/adapter/parameters 和不发布输出的统一规则 | P1 |
| 媒体 | `media_assets` 只有 novel、revision、kind、path、hash、JSON；novel 必填；无内容 API、Range、ETag、生命周期或 GC | owner scope、跨书音色、来源/派生分类、受控读取和可达 GC | 迁移、状态机、路径根、引用图、ETag/Range、删除与恢复都待实现 | P0 |
| 声音 | 当前没有 voice profile、version、绑定或授权表 | 人物/通用/上传/生成音色，锁定版本和历史引用 | 权利记录、锁定不变性、scope 约束和删除语义待冻结 | P1 |
| 脚本 | 当前没有 narration script/segment | revision 绑定、CAS 草稿、approved 冻结、证据与问题分类 | `approved -> stale` 自相矛盾；issue schema/taxonomy 未冻结 | P0 |
| Edition/render | 当前没有 Edition/render/Manifest | Edition 冻结全部制作输入，render 可同 scope 复用，Manifest 分段发布 | fingerprint canonicalization、发布事务和 current pointer 约束待冻结 | P0 |
| 隐私 | 文档已规定本地默认、云端最小化、日志不含正文/音频 | consent 可审计、可撤回、运行前复核 | consent 版本、用途、撤权竞态、日志字段和 HMAC 尚未冻结 | P1 |
| QwenPaw | 插件走公开 PawApp/Middleware/Skill/工具注册；已有安装/卸载验证 | TTS 禁用/卸载后不留路由、worker、进程和拦截；数据按策略保留 | 验证脚本尚无 TTS 断言，Sidecar/子进程生命周期未接线 | P1 |

## 3. T0-GATE 必须冻结的总契约

建议把以下常量作为阶段 0 输出，而不是散落在代码中：

```text
scope_contract_version              = narration-scope/1
request_contract_version            = narration-request/1
script_schema_version               = narration-script/1
review_taxonomy_version             = narration-review-taxonomy/1
edition_fingerprint_schema_version  = narration-edition-fingerprint/1
render_fingerprint_schema_version   = narration-render-fingerprint/1
manifest_schema_version             = narration-manifest/2.0
job_protocol_version                = background-job/1
media_contract_version              = narration-media/1
consent_notice_version              = narration-cloud-consent/1
```

所有 fingerprint 使用稳定字段顺序的 canonical JSON；版本号是 canonical 输入的一部分。任何未知版本都拒绝写入，允许只读兼容时必须显式声明。

## 4. 服务端范围与权限契约

### 4.1 当前个人版主体

T1 推荐冻结为：

```text
NarrationRequestScope
  owner_id       = 服务端固定的本地 owner/profile 标识
  workspace_id   = 本插件安装域的稳定标识，不读取 QwenPaw 私有 workspace
  app_id         = ai-novel-world-2026
  is_local_only  = true
```

约束：

1. `owner_id/workspace_id` 由后端 dependency 解析；请求体、query、模型输出、`X-Agent-Id`、session ID 和媒体 URL 都不能覆盖。
2. 现阶段这只是单用户结构隔离，不是已验证的多用户认证。HTTP 仍必须保持宿主同源并只暴露于已批准的本机拓扑。
3. T1 migration 为已有数据回填固定值；未来接入真实身份前另做迁移和威胁复核，不能把 Agent ID 当人类用户 ID。
4. 顶层 TTS 表持有 `owner_id/workspace_id`；子表通过父 FK 继承。跨作品复用 voice 时 `novel_id` 可空，跨 owner/workspace 永远禁止。
5. 任何 cache unique key 最少包含 `(owner_id, workspace_id, fingerprint)`；首版不做跨 scope 命中。

### 4.2 每类 ID 的服务端校验

所有不存在、已删除、越权或父子链不一致的资源统一返回不可枚举的 `404 resource_not_found`；详细原因只进入脱敏安全审计。

| 目标 | 必须由服务端验证的链 |
| --- | --- |
| novel | `novel.owner/workspace == request scope`；个人版可通过回填字段或唯一 scope 映射表实现 |
| document/revision | document 属于已授权 novel；revision 属于 document；`content_hash` 与请求冻结值一致 |
| volume/chapter override | scope ID 属于同一 novel；`scope_kind` 与实际实体类型匹配 |
| character/alias | character 属于 path 中 novel；alias、binding 的 novel 与 character 一致；归档角色只可读历史 |
| voice profile/version | profile 的 owner/workspace 匹配；profile.novel 为空或等于目标 novel；version 属于 profile 且用于正式 Edition 时已 locked |
| anonymous speaker | speaker 属于同一 novel；scene/chapter scope 属于脚本来源 document；合并/拆分目标同 scope |
| script/version/segment | script 的 document/revision 链合法；version 属于 script；segment 属于 version；PATCH path 的两级 ID 同时过滤 |
| Edition/edition segment | Edition 属于同 scope document；绑定 approved script version；segment 来自该 script version |
| render | 只通过合法 Edition segment 或同 scope cache lookup 获取；不能凭 render UUID 枚举 |
| Manifest | edition_id 与 manifest edition 一致；revision 不超过 edition 当前指针；旧 revision 仍按保留策略读取 |
| job/model run | job owner/workspace 匹配；scope_kind/scope_id 指向同 scope 资源；事件流也重复校验 |
| media | media owner/workspace 匹配；若有 novel 必须同 scope；文件路径必须位于登记 storage root，API 永不返回 path |

### 4.3 Agent、UI 与执行器权限

- UI API、后台执行器和任何未来 Agent 媒体工具必须调用同一 `NarrationService`。
- 首版不注册能够批准脚本、创建 Edition、删除音色或清理媒体的 Agent 工具。
- 模型只返回受 allowlist 限制的候选 speaker/evidence；模型提供的 `character_id` 不是授权依据。
- `auto_no_blockers` 由领域服务在已有显式用户意图上执行，不是 Agent 自主写入。
- 执行器领取 job 后仍重新加载 server scope；queue 中保存的 ID 不是永久授权。

## 5. T1 最小 schema 与约束

以下是施工前应冻结的最小集合。字段名称可在 T1-D 做机械调整，但语义和约束不能静默改变。

### 5.1 领域入口和固定主体

| 表/记录 | 最小约束 |
| --- | --- |
| novel scope | 已有 novel 对固定 `owner_id/workspace_id` 可验证；新建 novel 同事务建立归属；不建设角色权限表 |
| `narration_requests` | `owner_id/workspace_id/document_id/source_revision_id/source_content_hash/intent/request_hash/idempotency_key/force_review/effective_policy/state`；唯一 `(owner_id, workspace_id, idempotency_key)`；同 key 不同 request hash 返回 409 |
| `document_revisions` 扩展 | 对 `source=tts_snapshot` 提供 `(document_id, content_hash, source)` 幂等唯一性；创建不更新 working copy 的 base revision 或 draft version |

`narration_requests.intent` 只能为 `analyze_only | create | update | batch`。`explicit_generation_intent_at/actor` 对后三者非空，对 `analyze_only` 必须为空。它是领域请求，不是第二套调度账本。

### 5.2 设置、声音和授权

| 表 | 最小不变量 |
| --- | --- |
| `novel_narration_settings` | 每 novel 唯一、CAS version；policy 只能 `blockers_only|always_review`；分析 mode 只能 `local_rules_only|cloud_assisted` |
| `narration_settings_snapshots` | 追加式；包含 schema/taxonomy/rules/pronunciation/pool/consent fingerprint；被 Edition 引用后不可变 |
| `narration_scope_overrides` | 唯一 `(novel_id, scope_kind, scope_id)`；数据库/服务验证 scope 同 novel |
| `narration_cloud_consents` | 追加式授权记录；`revoked_at` 只追加撤销时间，DELETE API 不能物理删；purpose/data_scope/notice_version 必填 |
| `voice_profiles` | 稳定身份、owner/workspace、可空 novel、CAS current_version；归档不级联删 |
| `voice_profile_versions` | source/provider/model/revision/reference/preview/description/seed/rights/fingerprint；locked 后内容不可变 |
| `voice_rights_records`（或等价不可变记录） | 来源、声明文本版本、权利范围、确认 actor/time、可选 subject consent、到期/撤销、风险标记；不能只塞进自由 JSON |
| `character_voice_bindings` | character 唯一；character/profile/version scope 一致；CAS；历史引用不受新绑定影响 |

`voice_profile_version` 被锁定前的试听候选可以失败/淘汰；进入 locked 后不得替换 reference asset、描述、seed、模型或授权记录。授权撤销不改写版本内容，而是使新使用受阻并保留历史审计。

### 5.3 脚本与问题分类

| 表 | 最小不变量 |
| --- | --- |
| `narration_scripts` | 唯一 `(document_id, revision_id)` 或等价稳定身份；保存当前 draft/approved pointer 的 CAS，不把旧 frozen version 改成 stale |
| `narration_script_versions` | 父版本、输入/规则/模型/taxonomy fingerprint、状态、计数、approval audit、immutable hash；approved 终态 |
| `narration_script_issues` | version、segment 可空、taxonomy version、code、severity、公开证据摘要/哈希；severity/code 由服务端产生 |
| `narration_segments` | version 内稳定 ordinal；UTF-16 range、source block key、原文/spoken text hash、speaker/casting/evidence；parent scope 一致 |
| `narration_scenes` | version 内 ordinal/range/hash；segment.scene 必须属于同 version |

`warning_count/blocker_count` 由 issue 行计算并在冻结时再次核对；客户端提交的数字只能被忽略或拒绝。手工修正创建新 script version；不能 PATCH approved 行。

### 5.4 Edition、render 与 Manifest

| 表 | 最小不变量 |
| --- | --- |
| `narration_editions` | 必须绑定非 analyze-only request、approved script、settings/pronunciation/model fingerprints；制作配置冻结；同 scope edition fingerprint 唯一 |
| `narration_edition_segments` | 保存实际 voice version 与 render fingerprint；segment 必须来自 Edition script version；配置字段创建后不可改 |
| `narration_segment_renders` | 唯一 `(owner_id, workspace_id, render_fingerprint)`；canonical input 创建后不可改；ready 后媒体引用/hash 冻结 |
| `narration_manifests` | 主键/唯一 `(edition_id, manifest_revision)`；每个 revision 追加式不可变；结构 hash 与 ETag 一致 |
| `document_narration_state` | `(owner_id, workspace_id, document_id)` 唯一；current edition pointer 用 CAS；切换不修改 Edition |
| `narration_playback_progress` | owner/profile + Edition 唯一；segment 必须属于 Edition；跨 Edition 不自动迁移 |

建议 canonical fingerprint 至少覆盖：

```text
Edition = schema + owner/workspace scope + script immutable hash
        + settings/pronunciation snapshots + per-segment final voice versions
        + TTS/tokenizer/normalizer/postprocess exact fingerprints
        + context mode + seed/validated synthesis parameters

Render  = schema + privacy scope + spoken_text canonical hash
        + language/pronunciation result + voice version/reference hash
        + TTS/tokenizer/model weights + seed/parameters + postprocess
```

播放倍速、音量、UI 选择和当前指针不进入 Edition/render fingerprint。

### 5.5 job 与模型运行

| 表 | 最小不变量 |
| --- | --- |
| `background_jobs` | scope、kind、input hash、idempotency、priority/resource class、state、attempts/max、lease owner/until/generation、retry、cancel、错误分类 |
| `model_run_records` | job + attempt + requested/actual provider/model/revision/fingerprint、参数 hash、输入/输出不可逆审计 hash、耗时、供应商 request ID、结果分类；追加式 |

共享 job 不等于把现有生成任务在 T1 偷偷迁移。TTS 首先使用新协议；其他专用 job 的迁移另行裁决。

## 6. 保存屏障、幂等、CAS 与不可变性

### 6.1 保存屏障

一次“智能朗读/更新朗读”必须按以下顺序：

1. 前端等待自动保存并拿到服务端 `draft_version/content_hash`；
2. 服务端以 `expected_draft_version/content_hash` 锁定 working copy；
3. 幂等复用或创建 `tts_snapshot`；并发时唯一约束决定胜者，失败方回读同一 revision；
4. 同一短事务创建/复用 `narration_request` 和首个 analysis job；
5. 提交后才允许执行规则/模型分析；
6. 任一后续正文变化不修改 request/source revision，只使查询结果显示 diverged。

### 6.2 幂等键

- API `Idempotency-Key` 必须连同 canonical request hash 持久化；同 key/同 payload 返回同一 request，same key/different payload 返回 `409 idempotency_conflict`。
- 后台 job 的幂等键由领域服务计算，至少包含 kind、scope、source/settings/model fingerprint 和目标 segment/render fingerprint。
- `prepare-range` 只能提升同 render fingerprint 的未运行 job；不得生成第二个 render。
- retry 不改变 canonical input；需要改变输入时创建新 request/job。
- `force_review=true` 只收紧策略；缺失或 false 不能把作品 `always_review` 放宽。

### 6.3 CAS

以下动作必须携带 `expected_version` 或 HTTP `If-Match`：设置、scope override、voice profile 元数据、人物绑定、script draft 修正、current Edition 指针、Manifest 发布和播放进度。CAS 冲突返回当前最小安全摘要，不回显私人正文/路径。

### 6.4 不可变行

| 对象 | 可变阶段 | 冻结点 | 冻结后允许动作 |
| --- | --- | --- | --- |
| DocumentRevision | 无 | 创建提交 | 新建 revision；不更新旧正文/hash |
| VoiceProfileVersion | draft/generating/preview | locked | retirement/rights 状态在外部记录；不换资产和模型 |
| ScriptVersion | analyzing/review draft + CAS | approved | 新建子版本；`stale` 只派生，不改旧行 |
| Edition config | queued 前构建 | Edition 创建提交 | 只推进生成状态和 Manifest pointer，不改制作输入 |
| Render canonical input | queued/running 的执行状态 | render 创建 | 只推进状态；ready 后资产/hash 不换 |
| Manifest revision | 无 | 插入提交 | 新增 revision；不 UPDATE 旧 JSON |

## 7. script review policy 与 taxonomy v1

### 7.1 策略与审批

`auto_no_blockers` 必须同时满足：

1. request intent 为 `create|update|batch` 且有显式用户发起证据；
2. effective policy 为 `blockers_only`；
3. analysis state 为成功，输入/source/settings/rules/taxonomy/model fingerprint 仍一致；
4. 若使用云端，consent 在调用前有效且 requested/actual 模型身份完全匹配；
5. 服务器重新计算 `blocker_count == 0`；
6. 每个 segment 的 speaker、casting target、locked voice version 和 scope 均可解析；
7. request 不是 cancelled，且仍处于当前 lease/fencing token；
8. 同事务写 approval audit、approved immutable hash 和 Edition（或 Edition 创建幂等记录）。

`manual_after_review` 必须有 owner actor、reviewed_at、source/version/taxonomy fingerprint 和服务器重算的零 blocker。`approve` 请求体不能接受客户端指定的 approval kind。

### 7.2 `narration-review-taxonomy/1`

建议 T0-GATE 冻结以下最小代码。代码一旦进入已批准脚本，含义和严重度不可原地改变；后续调整发布 taxonomy v2。

Warnings（不阻塞默认生成）：

| Code | 含义 |
| --- | --- |
| `W_SPEAKER_MEDIUM_CONFIDENCE` | 人物候选唯一且 scope 合法，但证据只达中置信度 |
| `W_NEW_ANONYMOUS_SPEAKER` | 新建稳定匿名说话人候选且未发现冲突 |
| `W_GENERIC_VOICE_FALLBACK` | 合法使用通用池而非专属音色 |
| `W_MANUAL_OVERRIDE_INHERITED` | 从可唯一验证的旧句段继承人工覆盖 |
| `W_PRONUNCIATION_SOFT_FALLBACK` | 发音未命中专用条目，使用已验证规范化规则 |
| `W_CLOUD_ASSISTED_USED` | 本次至少一个不确定窗口使用了已授权云端辅助 |
| `W_SCENE_BOUNDARY_MEDIUM_CONFIDENCE` | 场景边界不影响 speaker/voice 完整解析，但建议复核 |

Blockers（存在任一项不得 approved/Edition）：

| Code | 含义 |
| --- | --- |
| `B_SPEAKER_UNKNOWN` | 无法确定 speaker kind/identity |
| `B_SPEAKER_LOW_CONFIDENCE` | 置信度低于冻结阈值 |
| `B_CHARACTER_ALIAS_CONFLICT` | 同一规范化别名指向多个活跃人物 |
| `B_CHARACTER_REFERENCE_INVALID` | 候选 character 不在允许集合或不属于目标 novel；UI 不回显越权对象细节 |
| `B_ANONYMOUS_IDENTITY_CONFLICT` | 匿名人物稳定键/合并/作用域冲突 |
| `B_CASTING_TARGET_UNRESOLVED` | speaker 已知但 casting target 不唯一 |
| `B_VOICE_MISSING` | 最终没有可用 voice profile/version/slot |
| `B_VOICE_VERSION_UNAVAILABLE` | voice version 未 locked、已撤权禁止新使用或 scope 不匹配 |
| `B_PRONUNCIATION_HARD_CONFLICT` | 同优先级人工发音条目冲突或会产生非法 spoken text |
| `B_CLOUD_DECISION_UNAVAILABLE` | 设置要求云端补充但未获有效授权/已撤销，且本地结果不足；可转人工解决 |

以下是 workflow failure，不得伪装成 warning/blocker 后自动批准：

```text
F_ANALYZER_RUNTIME
F_MODEL_IDENTITY_MISMATCH
F_MODEL_OUTPUT_SCHEMA_INVALID
F_INPUT_FINGERPRINT_CHANGED
F_SCOPE_VIOLATION
F_CONSENT_REVOKED_BEFORE_CALL
F_ADAPTER_UNAVAILABLE
```

模型只提供候选、证据和置信信息。最终 code/severity、计数和是否可审批由版本化确定性分类器产生。

### 7.3 `analyze_only` 硬约束

- `analyze_only` 可创建/复用 snapshot、request、analysis job、script draft/`analyzed` 结果和 issues；
- 不得写 approval audit、Edition、edition segment、render、媒体或 export job；
- 不能把请求改写成 create；后续生成必须新建 create/update/batch request 并重新验证所有 fingerprint；
- 数据库关系上 Edition 必须引用 intent 非 analyze-only 的 request；服务层再验证显式 actor/time；
- 测试按每类表断言新增行数为 0，而不只检查 UI 状态。

## 8. 事务、外部调用与发布协议

外部聊天模型、Nano、VoiceGenerator、ffmpeg 和文件 I/O 都不得占用包含业务行锁的长事务。

```text
短事务 A
  校验 scope/CAS/intent
  创建或复用 request、job、render placeholder
  commit

短事务 B
  FOR UPDATE SKIP LOCKED 领取 job
  写 locked_by + lease_until + lease_generation/token + attempt
  commit

无业务事务
  再校验 consent/adapter fingerprint
  调外部模型或本机模型
  写 job 私有 staging 文件
  解码、时长、格式、hash、响度等校验

短事务 C
  以 job_id + attempt + lease token 做 fencing
  重新校验 scope、cancel、consent、requested/actual、canonical fingerprint
  将已原子改名的 content-addressed 文件登记为 ready MediaAsset
  更新 render/edition segment
  插入新 Manifest revision 并 CAS 更新 Edition pointer
  标记 job succeeded
  commit
```

若数据库提交失败，已原子改名但无数据库引用的文件只能由 staging/orphan sweep 在宽限期后清理，绝不能直接被媒体 API 服务。若文件发布前发现 cancel、租约失效或模型身份不匹配，输出进入隔离区/删除；只有另一个有效同 scope render 引用且 fingerprint 完整一致时才可成为缓存。

## 9. 后台任务冻结协议

### 9.1 领取与续租

- 查询条件：`state=queued`、`next_retry_at <= now`、资源配额允许；使用 `FOR UPDATE SKIP LOCKED`；
- 领取时原子写 `running/locked_by/lease_until/lease_generation/attempt`；
- heartbeat 必须匹配 `job_id + attempt + lease_generation + locked_by`；
- 过期 worker 的任何完成回写因 fencing 不匹配而成为 no-op/冲突，不得发布媒体；
- 同一重模型资源默认单并发，参数由阶段 0 基准冻结。

### 9.2 失败、重试和死信

- 错误分类分为 `retryable | non_retryable | cancelled | security_failure`；
- retryable 失败保存 attempt 记录和退避时间，再显式转回 queued；
- non-retryable 直接 failed；达到 max attempts 进入 dead_letter；
- manual retry 记录 actor/reason，增加 retry generation，保留旧 model run，不覆盖失败历史；
- model identity mismatch、scope violation、非法 schema 和授权缺失不得无限自动重试。

### 9.3 取消

- queued job 可原子转 cancelled；
- running job 只写 `cancel_requested_at/actor/reason`，执行器在调用前、句段间、转码前、文件发布前检查；
- 底层模型不可抢占时允许计算结束，但取消请求自身不因成功返回而清除；
- 已完成且被其他合法同 scope Edition 引用的 render 保留；否则结果不发布或进入短期孤儿回收；
- 取消 Edition/request 不删除已合法完成的共享 render，也不改变正文/revision。

## 10. 媒体、Range、ETag 与 GC

### 10.1 资产状态与路径

建议状态：`staging -> ready -> quarantined | deleting -> deleted`，校验失败进入 `quarantined`。只有 `ready` 可读。

- storage backend 把逻辑 key 映射到登记 root；数据库不接受客户端 path；
- 解析后路径必须仍在 root，拒绝 `..`、symlink 逃逸、NUL 和未允许扩展；
- MIME 由解码/探测结果和 allowlist 决定，不信任文件名或上传 header；
- 参考音频限制大小、时长、采样率、通道和解码资源；ffmpeg 使用固定参数、超时和隔离 staging；
- 内容地址文件只在 hash/格式校验后原子改名。

### 10.2 HTTP 读取契约

`GET/HEAD /media-assets/{asset_id}/content` 必须先完成 scope 和 ready 校验：

- 媒体 strong ETag 精确为实际响应音频字节 SHA-256 的引号形式 `"<64 lowercase hex>"`，不加 `sha256:` 前缀；
- `If-None-Match` 命中返回 304；
- 首版只支持单一 byte range；合法 Range 返回 206、`Content-Range`、`Accept-Ranges: bytes` 和精确 `Content-Length`；
- 越界/多范围返回 416 与 `Content-Range: bytes */<size>`；
- 返回已校验 `Content-Type`、`X-Content-Type-Options: nosniff`；文件名使用安全 Content-Disposition；
- 源录音/参考音频使用私有、禁止共享缓存策略；不可变派生音频可以 private cache，但不得暴露 server path 或供应商 URL；
- Range/HEAD/304 和 SSE 均执行与普通 GET 相同的 scope 校验。

Manifest ETag 与媒体 ETag 分开：Manifest ETag 精确为 canonical Manifest JSON 字节 SHA-256 的引号形式 `"<64 lowercase hex>"`；`edition_id` 与 `manifest_revision >= 1` 是被哈希 JSON 的字段，不另拼自定义前缀。GET 用 `If-None-Match`；发布端用 Edition current revision CAS。公共 Manifest 固定 `narration-manifest/2.0`、segment ordinal 从 0 连续递增、range 使用半开 `end_ordinal_exclusive`。SSE 仅提示刷新，不是 Manifest 权威。

### 10.3 可达性与 GC

权威引用必须来自结构化 FK/受约束引用，不扫描 JSON 字符串或文件名：

```text
voice version -> source/reference/preview assets
render -> master/playback assets
export -> export asset
manifest/edition segment -> render
character binding/script/Edition -> voice version
```

GC 流程：

1. 在一致性快照中计算引用图；
2. 排除 source、voice_reference、locked voice、未过保留期、staging 活跃 job 和历史 Edition 可达资产；
3. 生成影响预览与候选 generation；
4. 标记 deleting 并进入宽限期；
5. 删除前再次比较 generation/引用；有新引用则取消；
6. 物理删除后写不可还原 tombstone，不复用原 asset ID；
7. 文件删除失败保留 deleting 并重试，不能先把 DB 伪装为已删除。

普通“清缓存”只处理可重建 preview/segment master/playback/export。上传原件、标准化参考、locked voice 永不进入该路径。

“仅删除上传原件”与“彻底删除私人音色”是独立命令。后者必须显示受影响历史并接受历史 Edition 将不可播放的事实；它不能通过级联悄悄删除审计行，而应留下 tombstone 和不可播放原因。

## 11. 云端授权、声音权利和日志脱敏

### 11.1 local/cloud 模式与撤权

- 默认 effective mode 为 `local_rules_only`；网络捕获中正文外发为 0；
- 选择 `cloud_assisted` 不等于已有 consent，必须引用 purpose/data scope/notice version 匹配且未撤销的记录；
- 设置切回 local 立即阻止后续外发，但不伪造删除历史 consent；显式撤权写 `revoked_at`，以后重新启用需新 consent；
- worker 在真正外发前重新读取 consent，不信任排队快照；
- 外发完成后、结果入库前再次检查：若期间撤权，记录 `revoked_during_run`，结果不得进入 script/approval；界面说明供应商可能已接收数据；
- 未获授权的模糊句段转为本地 unknown/blocker，不偷偷调用其他模型或发送更大上下文；
- payload 只能含不确定句、必要前后文、允许人物 ID/最小属性、场景和上一说话人；禁止整章、完整人物库、参考音频、voice description 和非参与设定。

### 11.2 requested/actual 模型

每次调用先保存 requested identity，完成时由可信 adapter/供应商 usage 解析 actual identity。至少比较：

```text
provider
model
model revision / weight manifest hash
tokenizer/audio tokenizer revision
adapter protocol version
关键采样/量化/后处理 fingerprint
```

聊天分析发现不匹配时，输出作废，script 保持旧状态，记录 `F_MODEL_IDENTITY_MISMATCH`。Nano/VoiceGenerator 不匹配时不得把文件发布为 ready render/locked voice。客户端不能提交 actual 字段。

### 11.3 声音权利

- 上传前保存用户权利声明和来源；如涉及他人声音，必须记录可证明的同意/许可范围；
- 对用户上传、文字描述生成、外部素材和主动仿声，默认禁止名人／公众人物仿声定位和未获授权真人克隆；文字描述也不能作为规避路径。该规则不用于建立固定 ONNX manifest 官方预设的名称／人物排除名单；
- 模型许可证、参考音频权利、输出使用权是三项独立证据；Apache 2.0 不替代人格权/声音权；
- rights 到期/撤销阻止新 preview/Edition，但历史行为和已有版本不被篡改；彻底删除遵循第 10.3 节；
- T0-E 的基础音色包每个 slot 必须链接到不可变来源/授权记录，不能只写“自制/官方”。

### 11.4 日志与哈希

禁止记录：完整正文、spoken text、提示全文、人物小传、voice description 原文、参考音频字节/base64、服务器路径、下载 token、第三方密钥和供应商返回原文。

允许记录：长度、不可逆/带密钥审计 hash、scope 的内部非公开标识、模型 fingerprint、状态、错误 code、耗时、字节数和已清洗供应商 request ID。私人短文本的审计/缓存键优先使用服务端 HMAC 或在 owner/workspace 隔离后加秘密 pepper，避免常见短句的裸 SHA-256 字典推测。API 错误只返回稳定 code 和安全描述。

## 12. API 冻结建议

### 12.1 通用规则

- 所有修改接口要求 `expected_version`/`If-Match` 或 `Idempotency-Key`；
- request scope 只由服务端注入；
- `404` 用于不可枚举的不存在/越权；`409` 用于 CAS/idempotency/fingerprint 冲突；`422` 用于合法 scope 内的业务校验；`503` 用于 adapter 不可用；
- 所有响应返回 `schema_version` 和稳定状态/code；不返回路径、内部 traceback、完整正文或模型原始输出；
- collection PUT 必须声明“全量替换”或改成逐项 command，不能让省略项被静默删除；
- SSE 带 job scope 验证、事件 ID 和恢复 GET；浏览器断线不改变 job。

### 12.2 关键端点附加不变量

| 端点 | 必须补充的冻结条件 |
| --- | --- |
| `PUT narration-settings` | CAS；不能创建/撤销 cloud consent；policy 只允许收紧/显式保存 |
| `POST narration-cloud-consents` | 独立告知文本/用途/数据范围；创建新不可变 consent |
| `DELETE .../consents/current` | 语义为 revoke，不物理删除；幂等返回同一 revoked record |
| `PUT character voice-binding` | character/path novel/profile/version 全链验证；locked version；CAS |
| `PATCH script segment` | 只允许 draft/review version；CAS；创建新 version 或受控草稿修订；approved 返回 409 |
| `POST approve` | 仅产生 `manual_after_review`；服务端重算 blocker；客户端不能传 approval kind |
| `POST narration-requests` | 持久 intent/request hash/idempotency；`force_review` 只能 true；analyze-only 硬隔离 |
| `POST .../editions` | 必须引用同 scope、非 analyze-only、显式生成 request；approved script/fingerprint 校验；不得成为绕过入口 |
| `PUT current-narration-edition` | 同 document、ready window、expected version；原子写 pointer + 合法起点；不改 Edition |
| `prepare-range` | segment 属于 Edition；priority 由服务端限制；复用 render/job；连续点击以最后意图提升 |
| retry/cancel | job scope、状态机和 actor 审计；retry 不改输入；cancel 协作式 |
| media content | scope + ready + root + Range/ETag；统一 404；不返回 path |

## 13. QwenPaw 安装、升级、禁用和卸载

TTS 施工必须延续当前公开 PawApp 边界：

- 不修改 QwenPaw 核心、私有数据库、私有配置或上游路由；
- worker/模型子进程由插件适配层持有生命周期，不向浏览器暴露；Sidecar 无业务数据库权限；
- 禁用/卸载前停止接收新 TTS job，向 worker 发协作停止，释放/缩短租约并撤销 loopback token；
- 运行中外部调用返回后因 lease fencing/插件 epoch 失效而不得发布；
- 卸载后 PawApp 路由、route wrapper、Middleware、Skills、工具、SSE、worker 和模型进程均为 0；原生聊天/设置/Agent/Provider/Skills/MCP/工具恢复；
- 默认保留 PostgreSQL、`novel-media`、参考录音、锁定音色和模型卷；删除这些资产必须是另一个显式、可恢复/有影响预览的动作；
- 升级先记录 QwenPaw old/new version+digest、插件 schema、job protocol 和 Manifest 兼容；先隔离安装/升级/卸载/回退验证，再替换唯一环境；
- TTS migration 失败时回退插件/基础镜像并保留卷，不临时修改 QwenPaw 上游源码。

现有验证脚本只验证当前 PawApp/Agent/Skills/工具/model contract，不能被引用为 TTS worker/媒体/卸载已经通过。T1/T4 gate 必须新增相应断言。

## 14. T1 施工与验收映射

| Owner | 必须消费本报告的部分 | 最小验证证据 |
| --- | --- | --- |
| T1-A | scope、错误码、schema version、fingerprint canonicalization | DTO/JSON fixture、同 key 重放/冲突、非法 scope |
| T1-B | adapter identity/cancel/capability | fake adapter 的 requested/actual mismatch、超时和 cancel |
| T1-C | 第 8–9 节 job protocol | SKIP LOCKED、租约过期、stale worker fencing、retry/dead-letter/cancel |
| T1-D | 第 4–7 节 schema/constraint | upgrade/downgrade、唯一约束、复合 scope、approved 不可变、analyze-only 反向约束 |
| T1-E | 第 10–11 节 media/privacy | Range/ETag/root、引用图、GC、源资产保护、日志捕获 |
| T1-F | snapshot/script/Edition/render/Manifest/current pointer | 幂等、CAS、追加式 Manifest、旧版本不变 |
| T1-G | 崩溃恢复和全链路 | kill/restart、租约恢复、数据库提交失败孤儿文件、正文 hash 不变 |
| T1-GATE | QwenPaw 非回归与 gate 裁决 | 打包、安装/升级/卸载、原生页面、数据卷、P0/P1 清零清单 |

## 15. 仍需 T0-GATE 主代理裁决

1. 固定本地 `owner_id/workspace_id` 的实际类型、值来源和 migration 回填方式；
2. 是否在 `novels` 增加 scope 字段，或建立唯一 `novel_security_scopes` 映射；两者只能选一套权威；
3. `approved` script 的 stale 派生指针落在哪个稳定表；
4. `narration_requests` 的精确字段、状态和 Edition FK；
5. taxonomy v1 代码表、阈值版本和 issue 存储方式；
6. job fencing token/generation、attempt 审计和 manual retry 语义；
7. Manifest 追加式主键、保留时长和 GC 对旧 revision 的引用方式；
8. voice rights 采用独立表还是受约束不可变对象；自由 JSON 不可作为唯一权威；
9. 私人短文本 hash 使用 HMAC/pepper 的密钥轮换和恢复策略；
10. “彻底删除私人音色”对历史 Edition 的不可播放状态、tombstone 和备份清除范围。

以上裁决不需要用户新增产品范围，但必须由 T0-GATE/ADR 明确后才能让不同 T1 子代理并行写 schema、任务和媒体代码。

> 2026-08-26 主代理后续记录：上述 10 项已在 [`gate-decisions.md`](gate-decisions.md) 形成精确门禁候选。该文件解决“施工应采用哪套契约”的歧义，但在 T0-GATE 正式接受前仍不代表 schema、迁移、服务或测试已经实现；本节作为审查时点的历史缺口保留，不回写成虚假的既成事实。
