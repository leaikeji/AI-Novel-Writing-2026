# E2E37-AUDIT：AI 写作全链只读审计

> 工作包：`E2E37-AUDIT`（`PAR`）
>
> 审计日期：2026-08-29
>
> 范围：计划 37 的 AI 写作链；不验收 TTS/narration
>
> 方法：只读源码、契约与现有测试审计；未读取真实小说、数据库内容、密钥，未调用正文或向量模型
>
> 结论属性：本文件是施工前审计证据，不等同于真实浏览器或真实模型验收

## 一、执行结论

当前代码已具备一条可验收的单时间线权威主链：建书/大纲草案形成正式人物与正式大纲，章纲和正文生成先保存不可变输入快照，模型结果先进入候选，作者采用后才创建正文 revision；情报提取也先形成 proposal，逐项确认后才写入 `StoryFact v2`。正文采用、手工 checkpoint/restore、正式大纲/设定和私有素材绑定都会请求 active generation 增量刷新；外部模型调用没有占用这些权威写入事务。

但计划 37 不应直接进入“全链 PASS”，至少有两个发布门禁：

1. **多时间线 Context V4 存在兄弟线资料泄漏风险（HOLD）**：数据库装载层把全小说所有活动人物实例都做成无 `timeline_id` 的块，并把所有正式章节都标成当前目标线；纯 assembler 的隔离规则因此无法识别并排除兄弟线人物实例/章节。
2. **未建立 semantic source/chunk 时，本地词面回退实际返回空结果（HOLD/需明确产品降级）**：语义搜索在 active build 不存在时直接返回 `local_index_unavailable`，并没有从正式 revision 或绑定素材做词面召回。“Dense 故障不阻断写作”成立，但“本地词面始终可用”并未完整实现。

单时间线三章合成样书可以继续做 stub 链路验收；多时间线隔离、无索引词面降级和旧 Context V3 调用者必须在发布裁决前单独处理或明确降级边界。

## 二、已核实事实

### 2.1 入口、权威写入与事务/CAS

| 环节 | 已核实入口与行为 | 权威写入、事务/CAS |
| --- | --- | --- |
| 建书 | 简单入口调用 `create_novel()`；完整建书向导使用 creation draft，并在 complete 时落库（`backend/app.py:564-571`；`backend/creative_api.py:286-342`） | 向导 draft 用行锁和 version；完成时锁 draft、创建 `Novel` 和默认故事状态后一次提交（`backend/creative_services.py:235-335`）。简单入口会同时创建卷、章节和默认主线（`backend/services.py:528-552`） |
| 大纲草案 | outline draft GET/PATCH/complete（`backend/creative_api.py:470-519`） | PATCH 对 draft 行锁并校验 `expected_version`（`backend/creative_services.py:689-755`）；formalize 同时锁 Novel 与 draft，校验版本、角色关联并一次提交（`backend/creative_services.py:778-1078`） |
| 人物草案正式化 | 新草案创建稳定人物根；已有同名正式人物必须先给出显式关联决策（`backend/creative_services.py:803-913`） | 正式化创建/关联人物根、人物 revision、主线实例和实例 profile revision，并把人物 revision 引用写入正式 outline revision（`backend/creative_services.py:837-1052`）；未按姓名静默合并 |
| 正式大纲/设定 | `GET/PATCH/restore/history`（`backend/creative_data_api.py:139-252`） | `save/restore` 使用 head version、幂等 hash、不可变 revision 和兼容 projection；API 在成功后提交、失败回滚（`backend/creative_authority/service.py:173-336`、`backend/creative_authority/service.py:414-565`；`backend/creative_data_api.py:150-252`） |
| 人物编辑 | 正式人物 create/PUT（`backend/creative_api.py:522-570`） | 创建人物根、root revision、默认人物实例；更新使用 character version CAS 并保留稳定 ID（`backend/creative_services.py:1097-1213`） |
| 章纲/章前要求 | chapter draft create/PATCH/complete 与通用 creative generation `chapter_outline`（`backend/creative_api.py:1223-1463`）；直接 brief PUT（`backend/app.py:722-753`） | chapter draft complete 创建初始 Document revision/working copy 与 ChapterBrief（`backend/creative_services.py:3780-3835`）；brief 更新锁行并校验 expected version（`backend/services.py:818-872`） |
| 正文生成 | `POST /documents/{document_id}/generate`（`backend/app.py:767-895`） | 写作位置、语义证据和 Context V4 在调用模型前冻结；job 先提交再执行外部 `ctx.chat`（`backend/app.py:782-844`）；`start_chapter_generation` 校验 brief/working 基线并使用输入 hash 幂等（`backend/services.py:967-1093`） |
| 正文候选/采用 | 模型结果先保存 `CandidateRevision`；作者再采用（`backend/services.py:1318-1420`、`backend/services.py:1504-1581`） | complete 只写候选，不改正文；adopt 锁 candidate/working，校验 draft version、base hash，创建不可变 `DocumentRevision`，切换 working copy、协调事实来源并请求向量刷新后一次提交（`backend/services.py:1504-1576`） |
| 正文手工保存/恢复 | checkpoint、revision restore | 锁 working copy、校验 CAS、创建新不可变 revision，不倒拨历史；同时协调 StoryFact 来源并请求向量刷新（`backend/services.py:2686-2820`）。autosave 只更新 working copy，不建正式 revision（`backend/services.py:2652-2683`） |
| 情报/StoryFact | `/intelligence/generate`、item review、commit（`backend/app.py:939-1071`） | proposal 冻结当前正式 revision、人物目录和时间线映射（`backend/services.py:1945-2027`）；候选要求逐字证据且按稳定 entity key 解析（`backend/services.py:2093-2253`）；commit 锁 working/proposal/novel，校验 revision hash，用 commit key 幂等，创建 `StoryFact v2` 与 `DerivedSourceBinding`，递增 ledger CAS 后一次提交（`backend/services.py:2442-2599`） |
| 审稿 | creative generation `review`（`backend/creative_api.py:1282-1463`） | 只形成 creative job/candidate；不直接改正式内容。存在 document 时接入 Context V4 与检索（`backend/creative_api.py:1295-1379`） |
| 选区修改 | creative generation `selection_edit` + 前端 review/apply（`backend/creative_api.py:1282-1463`） | 后端只保存严格校验的 replacement candidate（`backend/creative_services.py:4656-4725`）；前端冻结字段 hash、持久化版本、UTF-16 区间和前后文，应用前再次验证，并通过受控 adapter 写回（`frontend/src/selection-edit-runtime.ts:439-597`），不绕过原保存语义（`frontend/src/assistant-transactions.ts:130-215`） |

### 2.2 模型证据和失败隔离

- 正文生成、情报、大纲/章纲/审稿/选区任务均在外部调用前保存 running job，失败路径将 job 标记失败；正式内容不随模型失败变化（正文入口：`backend/app.py:817-895`；通用生成：`backend/creative_services.py:4252-4407`）。
- `ModelExecutionEvidenceV2` 只在公开 usage 给出完整实际身份且与 pre/post 一致时标记 verified；usage 未公开而 pre/post 一致时允许候选但 actual 字段为空；畸形、错配或执行中切换均拒绝（`backend/model_execution/evidence.py:25-44`、`backend/model_execution/evidence.py:227-299`；`backend/model_execution/policy.py:8-63`）。
- `complete_creative_generation` 在证据策略拒绝时将任务置为 failed；只有可采用证据才进入 ready（`backend/creative_services.py:4656-4724`）。
- 当前生产代码中的非 TTS `ctx.chat()` 入口集中在 `backend/app.py:825`、`backend/app.py:980`、`backend/creative_api.py:644`、`backend/creative_api.py:843`、`backend/creative_api.py:1372`；本工作包不评价 TTS 调用。

### 2.3 Context V4

- Context V4 loader 从正式 outline/settings head、人物 revision/instance profile、正式章节 revision、绑定私有素材、StoryFact 和检索证据构建块；最终冻结 `WritingContextSnapshotV2`，组装期间没有 commit（`backend/context_v4_loader.py:112-299`、`backend/context_v4_loader.py:302-435`）。
- 纯 assembler 对正文/章纲只允许 `source_sequence < target_sequence`，审稿/选区允许当前章但不允许后续章（`backend/context_v4/assembler.py:255-318`）。
- prohibited 素材被剔除；required/explicit 不能装入硬上限时抛 `context_overflow`，可选块按完整逻辑块省略并记录诊断，而不是静默截断（`backend/context_v4/assembler.py:265-318`、`backend/context_v4/assembler.py:340-398`）。
- 新正文生成传入 `writing_context` 时只生成 V4 snapshot；旧 V3 路径仅在调用者未传 V4 时回退（`backend/services.py:875-940`）。

### 2.4 向量增量与检索降级

- `resolve_writing_position` 对单时间线使用版本化 identity mapping；多时间线必须存在唯一 revision mapping，否则结构化失败（`backend/embedding/writing.py:51-121`）。
- V1 索引只覆盖 manuscript/planning/private_asset；多线正文索引使用 revision mapping，未映射正文不会进入多线语料；prohibited 素材不索引（`backend/embedding/indexing.py:53-54`、`backend/embedding/indexing.py:250-342`、`backend/embedding/indexing.py:422-443`）。
- 正式大纲/设定、正文采用/checkpoint/restore、素材绑定及 v2 授权会请求 active generation 刷新；helper 只在当前事务中排队，不做云调用（`backend/creative_authority/service.py:334-335`、`backend/creative_authority/service.py:563-564`、`backend/services.py:1574-1575`、`backend/services.py:2722-2723`、`backend/services.py:2808-2809`、`backend/private_library/service.py:665-666`、`backend/embedding/indexing.py:656-696`）。
- 授权会把小说附着到 active/candidate generation，必要时创建 `EmbeddingGenerationNovel`；随后请求 active refresh（`backend/embedding/persistence.py:269-421`、`backend/embedding/api.py:908-949`）。
- semantic search 先按小说、current source、corpus、时间线继承、叙事/故事截止点确定 SQL 范围；Dense 查询后再次校验 generation/index/authority/consent，再在合格集合上做 exact cosine（`backend/embedding/api.py:1432-1605`）。
- Dense 需要 v2 授权、已发布索引和 credential；失败时降级词面，检索异常不会阻止写作（`backend/embedding/api.py:1514-1616`、`backend/embedding/writing.py:185-235`）。

### 2.5 合法的候选/采用边界

- 正文、通用创作和情报模型输出都不是权威正文/账本；作者采用或逐项提交才写权威数据。
- `no_changes` 可形成没有 items 的 ready proposal；它不应调用要求非空 `accepted_item_ids` 的 commit（completion：`backend/services.py:2093-2253`；commit 非空门禁：`backend/services.py:2491-2493`）。
- 选区 AI 结果对于 explicit-save 字段只写回草稿；UI 明确要求作者使用原保存按钮持久化（`frontend/src/selection-edit-runtime.ts:588-596`）。

## 三、风险与缺口

### R1（P0 / 发布 HOLD）：Context V4 多时间线兄弟线泄漏

**已核实事实**

- `_character_blocks()` 查询小说全部 active `CharacterInstance`，构造块时未写 `timeline_id`（`backend/context_v4_loader.py:149-193`）。
- `_manuscript_blocks()` 查询小说全部章节，却把每个块的 `timeline_id` 统一设置为本次目标 timeline（`backend/context_v4_loader.py:196-226`）。
- assembler 只有当块本身带有非空且不在继承路径中的 timeline 时才排除它（`backend/context_v4/assembler.py:277-307`）。

**风险**

多时间线写作时，兄弟线人物实例资料可作为“无时间线块”进入上下文；兄弟线正式章节可被错误标成目标线，并在叙事截止点之前进入 prompt。semantic retrieval 自身的 scope-first 过滤无法弥补 Context V4 确定性块的泄漏。

**建议**

- loader 必须按当前线继承可达范围选择人物实例，并给人物块写明确 `timeline_id`/instance scope；穿越者通过明确 presence/fact 进入目标线，不得全量并入。
- manuscript block 必须依据当前 revision 的 timeline mapping 写真实 timeline、narrative/story 坐标；多线未映射应 fail closed 或记录 omission，不能改标为目标线。
- 在数据库集成层增加兄弟线人物秘密、兄弟线章节诱饵、父线分叉前/后事实四组负向用例。纯 assembler 单测不能替代 loader 集成测试。

### R2（P0 或明确降级）：无本地分块时词面回退为空

**已核实事实**

active generation 或小说 build 不存在时，semantic search 直接返回 `lexical_only`、空 hits 和 `local_index_unavailable`（`backend/embedding/api.py:1439-1456`）。

**风险**

未授权、刚授权尚未构建、索引被清理或配置尚未激活的小说，所谓“本地词面始终可用”并不存在。正文仍可依靠 Context V4 继续生成，因此不是保存阻断，但 `preferred/context_only` 私有素材和远距离前文的降级召回会缺失。

**建议**

二选一并冻结：

1. 从正式 revision、规划 head 和固定素材版本建立独立、纯本地且无需云授权的 lexical source/chunk；或
2. 明确产品契约为“存在已发布本地分块时词面可用”，并保证 Context V4 对 required/preferred/context_only 的无索引降级完整、可见且可测试。

### R3（P1）：助手/工具仍生产调用 Context V3 和旧词面搜索

**已核实事实**

- `get_novel_context()` 仍调用 `context_v3_loader` 并返回 `context_v3`（`backend/services.py:18`、`backend/services.py:2863-2977`）。
- 公共 `/context` 与 Agent 工具 `novel_get_context` 仍使用该服务（`backend/app.py:1099-1112`；`backend/tools.py:227-247`）。
- 公共 `/search` 与 `novel_search` 仍使用 working-copy 子串搜索（`backend/services.py:2830-2860`；`backend/app.py:1081-1095`；`backend/tools.py:262-272`）。

**风险**

章节正文/章纲/审稿/选区已走 V4，但助手上下文仍是另一条权威组装路径，可能出现时间线、知识和私有素材语义漂移。旧搜索不是 semantic-search v2，也不返回 revision/时间线/可见性证据。

**建议**

先枚举外部/前端调用者并冻结兼容 DTO，再让 `/context` 与 Agent tool 使用同一只读 V4 service；旧 `/search` 可保留为明确命名的 working-copy lexical search，不能与语义检索混称。确认无调用者后再删除 V3 生产依赖，历史快照仍只读保留。

### R4（P1）：AI 人物草案输出没有完整利用 V2 类型字段

**已核实事实**

- 草案归一化支持 `identity_summary`、`personality_summary`、`core_goal`、`age_at_story_start_note`（`backend/creative_services.py:634-686`）。
- 正式化会把这些字段写入人物实例 profile（`backend/creative_services.py:947-1018`）。
- 但 `outline_characters` 当前模型 prompt/normalizer 只强制 name、role_type、description、details.gender/personality；未要求模型单独返回 identity/core_goal/age note（`backend/creative_services.py:4542-4555`；`backend/model_runtime.py:704-742`）。

**风险**

AI 生成人物草案时，V2 的身份、核心目标和开篇年龄备注通常为空，或混在 bio 描述里，导致正式人物实例资料完整度低于手工草案路径。

**建议**

升级模型输出契约为与 `OutlineCharacterDraftV2` 同形的短键 DTO；保留 legacy normalizer 只读兼容，候选应用仍通过同一草案 CAS。不要从 bio 关键词猜填身份/年龄。

### R5（P1）：人物草案按姓名禁止重复，与稳定 ID 能力不一致

**已核实事实**

PATCH outline draft 在写入前用 name 去重，重复姓名直接拒绝（`backend/creative_services.py:716-746`）；正式化对现有同名正式人物则要求显式 link/create 决策（`backend/creative_services.py:803-828`）。

**风险**

系统具备稳定人物 ID 和显式关联能力，却无法在一个新大纲草案中规划两个同名但不同的人物。若计划 37 样书或未来作品需要同名人物，该限制会成为产品硬阻断。

**建议**

草案唯一性改为 `draft_key`/`character_id`；同名仅触发 UI 消歧，不作为拒绝条件。正式化预览必须显示 create/link 决策。

### R6（P2）：建书存在两套初始结构语义

**已核实事实**

简单 `create_novel()` 会自动创建卷、章节和默认时间线（`backend/services.py:528-552`）；完整 creation draft complete 明确创建“空小说”，只初始化默认故事状态（`backend/creative_services.py:267-335`）。

**风险**

不同入口创建出的初始书籍结构不同，会增加 E2E 脚本分支、UI 空态差异和后续维护成本。

**建议**

冻结一个领域级建书服务，并把“是否创建第一卷/第一章”定义为显式产品策略；两种入口只负责编排，不重复决定初始结构。

### R7（P2）：错误文案仍硬编码旧字数范围

**已核实事实**

正文候选采用门禁使用任务动态目标计数，但失败文案仍写死“1000—1500字”（`backend/services.py:1513-1519`）。

**风险**

当章节目标约 2000 字或其他范围时，作者会得到错误诊断，影响测试定位但不改变权威数据安全。

**建议**

文案从 job 的目标/容差策略生成，显示实际计数与目标范围；不要再引入第二个字数常量。

### R8（清理候选）：生产包内仍含合成故事评测文本及内容启发式

**已核实事实**

- `backend/writing_eval_contract.py:61-195` 保存合成故事 `_CASES`，路由在生产 app 中挂载（`backend/app.py:57`、`backend/app.py:190`），虽有 feature gate 且不写小说库。
- 建书模板 prompt 含“久别重逢和治愈→现实生活”的内容启发式（`backend/creative_services.py:4515-4527`）。

**风险**

合成故事文本属于验收 fixture，却随生产 backend 模块交付；内容启发式把具体题材判断硬编码在生产 prompt，后续题材扩展可能出现不透明偏置。

**建议**

评测样本移到 tests/audit fixture，由显式验收脚本装载；feature-gated 端点如需保留，只读取非生产数据包。题材映射改为版本化产品策略或模板元数据，保留协议枚举和 schema 常量。

### R9（集成注意）：检索异常被统一降级，部分结构化错误可能被吞没

**已核实事实**

`retrieve_for_writing()` 捕获所有异常并返回 degraded snapshot（`backend/embedding/writing.py:185-226`）。章节正文入口会先独立调用 `resolve_writing_position()`，所以多线 mapping 缺失不会在正文链被吞掉（`backend/app.py:782-797`）。

**风险**

没有 document 的 novel-scoped review/selection 可能把 `timeline_required`/scope 错误降级为普通检索不可用；这符合“检索尽力而为”，但不符合“多线不得猜测/必须明确实例”的结构化错误期待。

**建议**

只降级 provider/network/timeout/index-not-ready；owner、scope、timeline mapping、knowledge perspective 等确定性校验错误应保留结构化失败。验收中分别覆盖 document-scoped 与 novel-scoped 操作。

## 四、旧调用者与冗余清理候选

| 候选 | 当前调用者/事实 | 集成要求 |
| --- | --- | --- |
| Context V3 loader | `backend/services.py:18`、`backend/services.py:2863-2977`；公共 API 与 Agent tool 仍调用 | 不能直接删除；先迁移 `/context` 和 `novel_get_context`，保留历史 V3 snapshot 展示 |
| chapter generation V3 fallback | `_generation_snapshot()` 在未传 `writing_context` 时仍组装 V3（`backend/services.py:913-940`） | 先证明全部新生产入口总是传 V4；测试兼容读取与旧 job 展示后删除新任务 fallback |
| working-copy `/search` | `backend/services.py:2830-2860`、`backend/app.py:1081-1095`、`backend/tools.py:262-272` | 若保留，改为明确的本地草稿词面搜索；不要作为 semantic v2 的重复实现 |
| writing eval 合成文本 | `backend/writing_eval_contract.py:61-195` | 移入测试/审计 fixture 后再确认 endpoint 和打包路径；不得删除历史验收证据 |
| outline legacy compatibility fields | `description/details` 由 V2 草案生成兼容投影（`backend/creative_services.py:672-685`） | 先升级安装包前端并确认无调用者；旧草稿读取仍需兼容，不能直接清历史字段 |

## 五、建议验收矩阵

| ID | 场景 | 必须证明的结果 | 证据层级 |
| --- | --- | --- | --- |
| A01 | 完整建书向导 → 大纲背景/人物草案/情节/亮点 → 正式化 | Novel、默认主线、稳定人物根/实例、正式 outline revision 一致；刷新后无重复人物 | DB 隔离集成 + API |
| A02 | AI 人物生成 usage 不公开但 pre/post 一致 | job=`ready`、evidence=`not_exposed`、actual null，可应用草案；正式数据未提前改变 | stub 模型 + DB |
| A03 | usage 畸形/错配/模型切换 | job failed/rejected；draft、正式人物、大纲均无写入 | stub 负向 |
| A04 | 同名现有人物 | formalize 返回 `character_link_required`；显式 link/create 后稳定 ID 正确 | API + DB |
| A05 | 两个新同名人物 | 应能以不同 draft_key/人物 ID 创建，或在修复前明确标记 HOLD | API 负向 |
| A06 | 三章单线链 | 每章：章纲候选→采用/保存→正文候选约 2000 字→采用→情报 proposal→逐项确认；下一章可读取前章，不读取后章 | stub 全链 + DB |
| A07 | 正文候选冲突 | 生成后人工改 working copy，再采用候选返回冲突；人工内容保留 | DB/CAS |
| A08 | `no_changes` | proposal 正常 ready/完成，无 StoryFact、无需伪造 item、ledger 不增加 | API + DB |
| A09 | 情报证据与稳定 ID | 非逐字/多处重复证据、未知 entity key 被拒绝或忽略；确认后才写 StoryFact/binding | DB 集成 |
| A10 | 改名 | 人物根 ID 不变；章纲角色引用、关系、StoryFact、实例仍指向原 ID | DB 集成 |
| A11 | checkpoint/restore | 每次创建新 revision；旧 revision 不改写；事实 binding 有效性切换；向量 refresh 排队 | DB 集成 |
| A12 | 多线兄弟章节/人物秘密 | 目标线 Context V4 和 semantic hits 均不含兄弟线分叉后内容；父线分叉前内容按继承可见 | loader + assembler + retrieval 集成，发布门禁 |
| A13 | 多线缺 revision mapping | 正文/章纲结构化返回 `timeline_mapping_required`，不得降级吞掉 | API 负向 |
| A14 | 未授权、v1 授权、v2 授权 | 未授权云请求 0；v1 可维护正式索引但写作 query 请求 0；v2 才允许 Dense query | spy adapter + DB |
| A15 | 无 active build/索引被清理 | 本地 fallback 行为符合冻结契约；required/preferred/context_only 不静默消失 | API + Context snapshot |
| A16 | Dense timeout/限流/Key 错误 | 正文、章纲、审稿、选区仍可完成候选；snapshot 记录 degraded reason，无密钥/原文日志 | stub adapter |
| A17 | 正式 revision 快速连续更新 | 旧 refresh 不可发布；仅最新 head/hash 成为 current，index_version 单调增加 | worker + DB |
| A18 | 审稿 | 当前章可进入 Context，后续章不可进入；只生成候选，不改正文 | API + snapshot |
| A19 | 选区 rewrite/expand/dialogue/review | 按操作触发检索；hash/版本/选区变化时拒绝 apply；应用后原保存/重载一致 | Vitest + 真实浏览器 |
| A20 | 选区 polish/shorten/custom | polish/shorten 云向量请求 0；custom 仅显式“参考全书资料”时查询 | spy adapter + 浏览器 |
| A21 | GET/list/context/search | 除已知 get-or-create outline draft 外读接口零写；Context V4/semantic search 零写 | SQL write spy |
| A22 | get-or-create outline draft | 第一次 GET 的写入是显式兼容决定且 UI 可容错重试，或改为 POST 初始化 | API/DB |
| A23 | 三视口主链 | 1920×1080、2560×1440、390×844 完成建书、大纲人物、章纲、正文、情报、审稿、选区；失败态可恢复 | 真实浏览器截图/日志 |

## 六、集成顺序与注意事项

1. **先冻结门禁**：把 R1 多线 Context 泄漏和 R2 无索引词面行为写进计划 37 的发布裁决，避免三章单线样书通过后误报全链通过。
2. **先修 loader，再测 assembler**：R1 的缺口不在纯 Context V4 包，而在 ORM loader；不得只补纯 DTO 单测。
3. **保持事务边界**：模型、Dense 和 worker 网络调用继续放在权威事务之外；refresh 请求仅排队，与 revision/head/binding 同事务提交。
4. **统一 V4 调用者时保留历史可读性**：迁移 `/context` 和 Agent tool，不改写历史 V3 job/snapshot；删除 fallback 前用 `rg` 和契约测试证明无新生产调用者。
5. **样书使用独立合成库**：不接触真实小说。stub 全矩阵先行；真实正文/向量调用仍需独立授权。计划 37 当前可以完成不产生费用的验收。
6. **TTS 明确排除**：人物声音字段、朗读页、narration API、音色模型和音频产物均不作为本工作包 PASS/HOLD 依据；只要求本轮改动不触碰、不破坏其共享文件。
7. **脏文件隔离**：计划 37 与 TTS 任务共享工作区时，集成、暂存和提交必须按精确路径复核；不得把 narration/TTS、`pyproject.toml` 或其他计划文档混入。

## 七、审计裁决

- **单时间线、stub、无费用的 AI 写作主链验收：可以开始。**
- **多时间线全链与“本地词面始终可用”发布声明：当前 HOLD。**
- **真实正文模型、真实向量模型、长期安装与发布：本文件未执行、未裁决。**
- **TTS：明确不在本工作包验收范围。**
