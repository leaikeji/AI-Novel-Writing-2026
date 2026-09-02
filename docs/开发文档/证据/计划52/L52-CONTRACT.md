# L52-CONTRACT：长篇写作链前后端冻结契约

日期：2026-09-02（Asia/Shanghai）
状态：V1.2 已冻结并实现；新小说直接尝试启用当前有效向量配置，无偏好表；字数 migration `20260902_0039` 已通过隔离往返，尚未应用到长期库

## 1. 冻结原则

- StoryFact 账本是唯一权威事实链；向量 source/chunk/vector 只是可重建派生索引，不形成第二套账本。
- 页面和 AI 都按需取得有界上下文，不再把整部小说作为导航 DTO、检索候选或 Prompt 的隐式输入。
- UI API、Agent 工具和后台处理复用同一领域服务、范围校验、Context selector、Prompt budget ledger 和 retrieval summary 投影。
- 不保留永久 full-tree 兼容层。第一方调用者全部迁移、回归通过后，在同一计划内删除旧 helper、旧 DTO 和只覆盖旧实现的测试壳。

## 2. Navigation 契约：`novel-workspace-manifest/1`

### 2.1 路由与兼容窗口

- `GET /novels/{novel_id}` 最终只返回小说元数据和 `story_ledger_version`，不含 `tree`、正文、revision 正文。
- 新增 `GET /novels/{novel_id}/workspace-manifest?cursor=&limit=`；默认／最大 `limit=200`。
- 返回扁平、有序的 volume/document 元数据页；正文继续复用 `GET /documents/{document_id}` 按需读取。
- `GET /novels/{novel_id}/tree` 和旧 `get_novel_tree` 分类为第一方内部兼容。迁移期间只允许一个 release 候选窗口；所有前端、creative response、assistant validation 和工具调用者归零后立即删除，不跨 Plan 52 长期保留。

### 2.2 DTO

```json
{
  "schema_version": "novel-workspace-manifest/1",
  "novel": {
    "id": "uuid",
    "title": "string",
    "description": "string|null",
    "story_ledger_version": 1,
    "visible_character_count": 0,
    "updated_at": "timestamp"
  },
  "items": [
    {
      "kind": "volume|document",
      "id": "uuid",
      "parent_volume_id": "uuid|null",
      "document_type": "chapter|outline|setting|...|null",
      "title": "string",
      "position": 0,
      "status": "string|null",
      "draft_version": 1,
      "base_revision_id": "uuid|null",
      "content_hash": "sha256|null",
      "visible_character_count": 0,
      "updated_at": "timestamp"
    }
  ],
  "next_cursor": "opaque|null",
  "manifest_etag": "opaque"
}
```

- 排序固定为 volume position/id，再按 document position/id；游标包含最后排序键和 `manifest_etag`，不使用 offset。
- `manifest_etag` 只由会改变游标顺序或成员集合的小说/账本版本与 volume、document 的 count/max-updated 聚合材料生成，不加载正文。working copy 的 autosave 不改变目录顺序，因此不会让 2,500 章后台分页在作者连续输入时反复失效；当前章正文仍以单文档 CAS 为准。
- 后续页 ETag 不一致返回 `409 manifest_changed`，前端丢弃旧页并从第一页重载；迟到响应还必须匹配当前 novel ID、请求 generation 和 cursor chain。
- manifest 禁止字段：`content_markdown`、revision `content_markdown`、候选正文、Prompt、retrieval snippet。

### 2.3 单文档和前端缓存

- 单文档响应保留当前 working body，只返回最近 50 条 revision summary；更早历史走独立 cursor endpoint，每页最大 50，正文仍按 revision ID 单独读取。
- 前端常驻：当前文档、未安全保存的 dirty 文档、最多 8 个 clean 最近文档；dirty／IndexedDB 恢复稿永不被 LRU 静默淘汰。
- 切作品、切章、分页和搜索都使用 AbortController + generation token；旧响应不得覆盖新状态。
- 卷章列表使用虚拟滚动；DOM 数量由 viewport/overscan 决定，不由 2,500 章决定。

## 3. Context V4：`context-source-policy/1`

### 3.1 选择上限与顺序

- 当前目标章：1。
- 相邻正文：最多 8 章，按当前章前 4／后 4 取候选；写作生成默认不读取未来正式正文，若 purpose 禁止未来证据则 8 个名额只从前文补足。
- StoryFact 初筛：数据库最多返回 512 个候选 ID；最终进入 Context 的事实最多 160 条。
- character instance/profile：最多 64 个；private asset：最多 32 个；semantic hits：最多 10 个。
- 最终正文 evidence block：最多 20 个；同一 source/revision/range 去重后再水合正文。
- 所有初筛使用 `limit + 1` 检测截断；排序必须包含稳定 UUID tie-breaker。

选择顺序：scope/timeline 安全边界 → 当前章定位 → formal planning/当前人物状态 → 相关事实 → 相邻正文 → semantic evidence → private asset。先只查询 ID、位置、哈希和评分；去重、裁剪完成后才读取被选正文。

### 3.2 失败与 omission

- 必需 scope/timeline 无法唯一确定：`409 context_scope_unresolved`，停止模型调用。
- 必需集合因 cap 截断且无法证明选择完整：`409 context_selection_incomplete`，停止模型调用，不静默改用旧 V3。
- 某个可选组件被预算省略：记录 `omitted`、reason、candidate_count、selected_count 和 token estimate；不伪报“无数据”。
- 所有 job 已创建后若触发上述错误，必须写 terminal failed/cancelled 状态，不能悬挂。

## 4. Prompt：`prompt-budget-ledger/1`

每次模型调用只允许一个组件账本，顺序和预算项固定为：system/skill instructions、operation instructions、current draft、formal planning、character state、StoryFact、manuscript evidence、private assets、semantic evidence、user request、diagnostics。每项记录 source IDs/hash、estimated tokens、included tokens、omission reason。

- `brief`／chapter requirements 只能属于一个组件，禁止在 Context 和 operation prompt 重复拼接。
- 同一 source/revision/range 不能同时作为完整 manuscript block 和 semantic snippet 重复计费。
- 所有组件相加不得超过当前实际模型上下文窗口和项目保留输出预算；超限在 Provider 调用前返回 `prompt_budget_exceeded`。
- V4 不可用时禁止回退到无统一预算的旧生产 Prompt。可以返回结构化错误，或在契约允许时只用已经纳入同一 ledger 的有界基础上下文。
- 完整 ledger/snapshot 仅存服务端审计边界；公开响应只返回脱敏诊断计数。

## 5. Retrieval：`writing-retrieval/3`

### 5.1 SQL 和候选

- Dense candidate cap：80；lexical candidate cap：80；都必须在 SQL 层 `LIMIT`。
- scope、novel、active generation、source current/head 和 corpus 授权过滤必须在候选查询内完成；候选后的 `_source_is_current` N+1 为 0。
- 两路 ID 并集后再批量水合；每个最终 hit 最多相邻 2 个 chunk，全部邻块最多 20，最终 hit 最多 10。
- Dense 继续 exact cosine；暂不增加 HNSW／IVFFlat。lexical 继续使用现有 trigram；暂不新增索引。
- 固定稳定排序：融合分数降序、单路最佳 rank、source ID、chunk ordinal、chunk ID。

### 5.2 质量门禁

同合成 oracle 比较：Recall@5 ≥ 0.85、MRR ≥ 0.70、hybrid 不低于 lexical-only、无答案正确拒答率 ≥ 0.90、跨小说／owner／workspace／timeline 泄漏为 0。若 cap 相对未截断 oracle 的 Recall@5 下降超过 0.03，不能发布，必须调整查询策略或重新裁决索引。

### 5.3 真实模式

- `hybrid`：Dense 与 indexed lexical 均实际执行并参与融合。
- `lexical_only`：本地或 indexed lexical 实际执行成功；不能因配置存在就宣称成功。
- `context_only`：检索未执行、失败且本地也未成功，或无额外证据；基础有界 Context 仍可用。
- `no_hit` 是 outcome，不是伪装的失败；Provider 失败、not authorized、index building/outdated/partial_failed 分别保留 reason code。

## 6. 授权：新小说直接默认启用

用户已明确裁决不建立“未来默认偏好表”。产品规则直接冻结为：当前 active embedding 配置有效时，新建小说默认创建自己的 `NovelEmbeddingConsent`，然后在创建事务提交后排队增量索引。现有 `novel_embedding_consents` 已保存 novel、scope、notice、Provider、model、actor、授权时间和撤销信息，不需要第二张偏好表，也不形成第二套账本。

- 两个建书入口必须调用同一领域服务，不能分别复制默认开启规则。
- 新书创建不能被索引等待、Provider 超时或无 Key 阻断；无法建立有效云端配置时小说仍创建成功，状态显示本地路径／向量配置不可用，云端请求为 0。
- 默认范围固定为当前告知版本允许的 `manuscript`、`planning`、`private_asset` 和写作 query；服务端不能接受调用者临时扩大范围。
- 每本小说仍有独立记录、状态和撤销入口。撤销只影响该书，不关闭其他小说，也不删除正文、revision 或 StoryFact。
- 已有未授权小说保持原状态；本次产品规则改变不自动批量上传历史作品。作者可逐本启用；若未来需要“全部启用”，必须另做精确预览与明确动作。
- Provider/model/notice/scopes 变化时，既有逐书记录不得静默授权新的外发目标；该书显示 `requires_reconsent`，但新小说按创建时当前有效配置建立自己的记录。
- 同 notice 撤销后重新启用使用现有 consent 历史行数/最新记录形成 CAS version，并生成新的 operation hash/idempotency key；不再使用会命中已撤销旧行的固定 key，无需新增 version 列。

逐书状态冻结为 `not_authorized | granted | revoked | requires_reconsent`；索引状态沿用 `not_authorized | building | ready | outdated | partial_failed`，两者不得混为一项。冻结错误码：`consent_version_conflict`、`consent_scope_mismatch`、`consent_target_changed`、`index_enqueue_failed`。索引排队失败不回滚已经提交的新书或合法 consent，但必须显示可重试状态。

## 7. 公开任务投影：`retrieval-summary/1`

所有正文、章纲、审稿及适用选区任务的创建、轮询、完成、失败、历史列表和详情统一返回可选顶层字段：

```json
{
  "schema_version": "retrieval-summary/1",
  "outcome": "used|degraded|no_hit|not_run|failed",
  "mode": "hybrid|lexical_only|context_only",
  "reason_code": "ready|not_authorized|index_building|index_outdated|partial_failed|provider_unavailable|no_hit|not_applicable",
  "hit_count": 0,
  "index_state": "not_authorized|building|ready|outdated|partial_failed|null"
}
```

公开 projection 禁止：query、snippet、完整 Prompt、向量、密钥、private asset 内容、writing/context snapshot。内部持久化 snapshot 不因公开 DTO 清理而删除。

前端使用作者语言显示本次事实；“管理索引”深链固定为 `/chat?novel_workbench=1&novel_id={N}&section=settings&settings_tab=semantic-index`，刷新、前进后退及助手展开/折叠不得丢失 tab。

## 8. Index lifecycle：`semantic-index-lifecycle/2`

- working copy 保存只计算受影响 source 的 authority digest，执行 source 级 refresh；禁止为了一个章节读取其他章节正文。
- 全量 rebuild 是显式动作；7,500 chunk 不再按 `EMBEDDING_BATCH_MAX_ITEMS=1` 形成 7,500 个外部请求。目标 batch 上限先冻结为每请求最多 32 chunk，同时遵守 Provider token/size 上限；job 可包含一个有界 batch 的稳定 idempotency hash。
- source/chunk/vector 计数使用 SQL aggregate，不把所有 ID 返回 Python。
- superseded pending 自动终止且不覆盖新 head；retry 只重试失败/缺失 batch；cancel 不删除已经可验证完成的 current 数据。
- active generation 内 retired/invalid 派生 source 采用每批最多 500 source 的可恢复 GC，先检查无 pending/running 引用，再级联清理其 chunk/vector。整书索引清理必须显式确认且不触碰正文、revision、StoryFact、binding 或 consent 审计。

## 9. 性能门槛与真实 UI

采用 `L52-G0.md` 第 7 节门槛：作品列表 P95≤250 ms/SQL≤5；manifest 200 项 P95≤250 ms/SQL≤8/≤512 KiB；单文档 P95≤100 ms；Context V4 P95≤1,500 ms/SQL≤60/峰值≤64 MiB/snapshot≤2 MiB；本地 fallback P95≤750 ms；hybrid 应用链 P95≤500 ms/SQL≤20；Dense/lexical DB P95≤250 ms。

真实 UI 只以 QwenPaw 宿主中的 1920×1080 和 2560×1440 为正式验收，覆盖左栏与助手展开/折叠、2,500 章虚拟滚动、随机/连续切章、搜索、dirty/恢复、授权确认、索引状态和检索摘要。记录实际内容 viewport、network、console、长任务、DOM、可得 heap 和横向溢出。窄屏与 200% 只作补充。

## 10. Migration、文件所有权与开始门禁

只需要一个窄 migration，由 `L52-MIGRATION` 所有者基于唯一 head 创建：

1. `L52-MIG-COUNT`：`DocumentWorkingCopy.visible_character_count`、回填及所有写路径等值维护。

明确不创建：授权偏好表、逐书 consent version 列、搜索索引 migration、lexical 索引 migration、ANN、vector typmod 变更、tree-version 列。逐书 CAS 由现有历史记录派生；若实现证据推翻本裁决，必须停回本门禁，不得顺手加 DDL。

共享 DTO、错误码、策略版本和文件锁沿用计划正文第 7 节。默认向量授权实现不再依赖 migration；字数聚合仍须在用户批准 `L52-MIG-COUNT` 后进入实现，不能用临时 JSON 或永久兼容层绕过字数契约。

## 11. 删除清单与测试矩阵

替代和调用者迁移通过后，计划内必须删除：旧 full-tree helper/DTO、前端整树转换与重复 selected-document 缓存、Context 全量 manuscript 构造、Dense/lexical `.all()` 后裁剪、逐候选 `_source_is_current`、authority local 整书切分路径、只验证这些旧实现的测试壳。删除前必须以 `rg` 证明调用者为 0；恢复、负向、兼容窗口和历史证据测试保留。

最低矩阵：

- 后端：manifest 游标/ETag/字段禁入、单文档历史分页、Context cap+1/稳定排序/失败、Prompt ledger 去重/超限、retrieval cap/oracle/隔离、本地降级、source refresh/GC、新书默认逐书记录/撤销/重授权、公开 projection 脱敏。
- 前端：2,500 章虚拟列表、迟到响应、dirty LRU/IndexedDB、逐书开关与状态文案、settings deep-link、全部生成入口 summary。
- 数据库：每个获批 migration 在隔离 PostgreSQL upgrade→downgrade→upgrade，回填等值、空/大正文、唯一 head、锁时长与回退。
- 集成：全量 pytest、Vitest、typecheck、build、package/Skill contract、第一方旧调用为 0、100 万/500 万复测、1080P/2K 真宿主。

## 12. 闸门裁决

`L52-G0` 与修订后的 `L52-CONTRACT` 输入已经闭合；未获批准的数据库改动只剩 `L52-MIG-COUNT`。长期环境发布、真实云模型调用、Git 提交和推送仍未获授权，不得扩大解释。
