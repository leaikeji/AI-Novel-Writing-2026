# T3-GATE 脚本、场景与本地选角集成门禁

状态：**`PASS_WITH_LOCAL_ONLY_SCRIPT_RUNTIME_AND_EXPLICIT_T4_PLUS_HOLDS`。T3-B～T3-I 已完成主代理集成、typed PostgreSQL 18 持久化、固定 QwenPaw 热安装、真实 HTTP、完整卸载／重装、数据保留和独立对抗终审；释放 T4 分阶段 ready set。当前只放行固定本地 scope 内的确定性正文切分、人物归因、旁白／已配置人物逻辑选角、脚本分析、自动无阻塞冻结和只读查询。用户可见章节朗读、音频合成、播放器、编辑器同步及本节列出的高级分析／复核能力仍为 HOLD。**

日期：2026-08-27（Asia/Shanghai）。

Git 基线：`9d1ad30e9fbbc70d4b1ccce1e2d9bdb7eaae1ce1`（`main`）；当前施工位于含其他已授权任务改动的未提交工作树。本阶段没有暂存、提交或推送。

布局范围：用户于 2026-08-27 最终明确不考虑 1080P 以下布局。本专项后续 UI 且仅验收 1920×1080、2560×1440 各自助手收起／展开的四个精确组合；移动、窄屏、低于 1920×1080 和 200% 等效小视口不设计、不测试，也不阻断门禁。

## 1. 最终裁决

| 门禁项 | 实际结果 | 裁决 |
| --- | --- | --- |
| T3-B～T3-I 局部工作包 | 切分、场景、别名、本地归因、云端窄契约、匿名身份、逻辑选角、表达／置信、复核 facade 与独立 QA 已汇合 | 接受；运行时只启用第 3 节列出的 local-only 子集 |
| T3-A typed contract | contract/schema invariant 未改变；T3-GATE 仅实现唯一持久投影和 reverse loader | 接受 |
| 服务端 authority | 固定 owner/workspace，重新加载正文 revision、设置 snapshot、人物／音色关系、请求和批准证据；客户端 ID 集合不成为权限 | 接受 |
| 脚本 ID／版本分配 | 文档行锁串行，实际 script root + 非空幂等键派生 UUIDv5 version ID；旧 UUIDv4 script root 可生成 typed successor | 接受 |
| typed 写入／重放 | 不可变 hash、子表、状态和批准审计往返一致；同键只产生同一版本 | 接受 |
| PostgreSQL 18 并发 | disposable loopback 测试库中两个会话被文档锁串行为 version 1/2 | 接受 |
| 旧数据兼容 | legacy 行只读返回 `requires_reanalysis`，读取不静默改写；未知／混合 marker 失败关闭 | 接受 |
| 已批准历史脚本 | 人物改绑、归档或正常 unset 后仍可读；未批准脚本继续要求当前 active authority | 接受 |
| QwenPaw 接线 | 使用 PawApp 现有 router 和唯一 lifecycle；逐请求 SQLAlchemy Session；没有修改上游核心 | 接受 |
| HTTP mutation | patch、manual approve、partial reanalyze 缺少持久动作幂等位，当前在查询前拒绝 | HOLD |
| 独立终审 | P0=0、P1=0；145 项窄回归通过 | 接受 |
| T4+ 产品能力 | Edition、render、Manifest endpoint、播放器、编辑器 bridge、句段高亮／跳播尚未施工 | HOLD；进入下一阶段 |

受支持的 local-only T3 范围没有尚未解释的 P0/P1。门禁通过不等于完整多角色有声书已经可用；它只证明下一阶段可以安全消费一份可恢复、可审计、不可变的朗读脚本。

## 2. 集成实现与信任边界

### 2.1 唯一编排链

当前后端按以下顺序组装，不复制各工作包的规则：

```text
固定本地 scope + 请求/正文/设置鉴权
  -> 文档锁与 script/version identity 预留
  -> Markdown/纯文本 + UTF-16 完整切分
  -> 场景映射
  -> 服务端人物/别名索引
  -> 本地说话人归因
  -> 表达/置信分类
  -> 旁白设置或人物绑定逻辑选角
  -> issue 合并与复核策略
  -> T3-A typed contract
  -> 唯一 immutable_hash 持久化
  -> 必要时 auto_no_blockers 冻结
```

`analyze_only` 只产生 analyzed／review_required 脚本，不得创建 Edition。`create|update|batch` 仍需已有持久 request、精确 revision/hash、设置 fingerprint 和显式 generation intent；零 blocker 的 `blockers_only` 可由可信 service 自动冻结，任一 blocker 都停止在 review_required。

### 2.2 持久化与 reverse loader

- `script_versions.py` 继续使用 T1 既有 `NarrationScriptVersion.immutable_hash`，没有新增第二个 hash、第二套状态机或 T3 migration。
- 首次写入重新锁定 Document，并从数据库复核 novel/document/revision/hash、当前最大 version、幂等键和 UUIDv5 version identity。调用者伪造 script/version ID、跳号、陈旧 allocation 或直接 approved 状态均被拒绝。
- T1 legacy script root 可能是 UUIDv4；系统保留这个不可变历史 root，并用“实际 root + 新幂等键”派生 typed successor version，不改写旧外键。
- typed reverse loader 要求每个 segment 都携带精确 current casting/evidence contract marker，同时要求非空 idempotency key 和 server-derived version UUID；仅有 marker、仅有 UUID 或未知版本都不能伪装成 typed 行。
- non-approved 行的六个 approval 字段必须全部为 NULL；`approval_request_allows_edition` 单独为 true 或 false 都属于部分审计并失败关闭。
- legacy 行只提供独立 `narration-script-legacy-read/1` read-only 形状和 `requires_reanalysis`，不会因 GET、parent classification 或 approve 尝试被原地升级。

### 2.3 历史 authority

已批准脚本是不可变历史，读取时允许忽略后来发生的可变状态：人物归档、同一 binding 的改绑，以及正常 unset 删除 `CharacterVoiceBinding`。这是 approved-only 分支；analyzed/review_required 脚本仍要求人物 active、绑定当前可用，防止撤销后继续批准。

历史放宽不覆盖固定关系：narrator profile/version、direct profile、anonymous speaker scope、generic pool/slot 仍须存在并匹配原 scope；当前仅忽略它们可变的 lifecycle/status/enabled。设置 snapshot、正文 revision/hash、脚本 hash、批准请求和 actor/time 始终严格重建。

脚本只冻结“逻辑 casting target”，没有冻结实际用于音频的 `voice_version_id`。T4 创建 Edition 时必须重新校验并冻结精确音色版本；本阶段不得把脚本表述为已经固定最终声音或已经生成音频。

## 3. 当前已放行与继续 HOLD

### 3.1 已放行的技术能力

- Markdown／纯文本的确定性块、句段、scene 与 UTF-16 source range；
- 已有人物卡姓名／别名与明确说话提示的本地人物归因；
- narrator setting 与当前可用 character voice binding 的逻辑选角；
- conservative emotion/delivery/confidence 建议及 warnings/blockers；
- `ANALYZE_SCRIPT`、`GET_SCRIPT`、`GET_SCRIPT_VERSION` 的 request-scoped SQLAlchemy backend；
- `blockers_only + create/update/batch + 0 blockers` 的可信 service 自动冻结；
- working copy divergence／settings superseded 的只读派生状态；
- approved 历史脚本稳定读取与 legacy reanalysis 提示。

这些能力目前是后端技术闭环。章节工作台尚未挂载脚本复核面板，也没有 Edition、音频或播放器，因此 `product_visible=false` 与设置 API 中 `automatic_speaker_detection=HOLD` 均保持正确；后者只能由 T4-GATE 在用户闭环验收后翻转。

### 3.2 显式 HOLD

以下能力没有被本门禁启用：

- 公共 HTTP 的 segment patch、人工 approve、局部 reanalyze；
- 云端正文外发与 cloud-assisted 归因／场景边界；
- manual override、跨版本 inherited override、casting-rule 精确重放；
- group speaker；
- 自动创建／合并／拆分匿名说话人及历史 scene 匿名生命周期；
- 章／卷旁白 override、第一人称和内心独白的完整产品规则；
- 24 槽生产通用音色包、generic automatic casting；
- reference clone、VoiceGenerator；
- Edition、Nano render、后处理、Manifest、播放器、编辑器高亮／跳播、边听边改；
- 缓存删除、批量生成、导出和最终人工听感。

HOLD 操作返回显式 `INVALID_STATE`／capability 状态，不访问数据库后伪造成功。云端 T3-D 与匿名 T3-E 的局部实现保留为后续可审计输入，不代表它们已接入正式 runtime。

## 4. API、事务和错误契约 re-freeze

T3-H 冻结的 wire version 继续为 `narration-script-review-api/1`。T3-GATE 的实现审计增加两个必要但兼容的安全适配：

1. backend factory 改为 `Callable[[Session], ...]`，每个请求创建并关闭自己的 SQLAlchemy Session；未安装 factory 时零数据库访问。
2. 增加 `STORAGE_UNAVAILABLE`，数据库未配置或 SQLAlchemy 连接失败稳定映射为 `503 + retryable=true`，不伪装成 backend 未安装，也不暴露 SQL 或正文。

三个 HOLD mutation 在任何 store 查询前拒绝。GET 只读；ANALYZE 的权威持久化在一个请求事务中完成，失败整体回滚，且不会创建 Edition、媒体或 workflow failure script 行。应用继续只有一组 PawApp startup/shutdown/uninstall hook，settings factory 先安装、script factory 后安装，清理时逆序且使用嵌套 finally。

## 5. 真实 PostgreSQL 18 证据

使用现有 `ai-novel-2026-postgres` 容器，在 loopback `127.0.0.1:15432` 创建精确 disposable 数据库 `ai_novel_world_2026_tts_test` 和角色 `tts_test`：

1. 先只读确认同名数据库／角色不存在；
2. 由管理员创建测试库，预装 `vector`；
3. 测试角色从空库执行 Alembic `-> 20260826_0016`；
4. 运行 `tests/narration/test_script_postgres.py`；
5. trap 终止测试连接，精确删除测试库和角色；
6. 最后确认数据库计数 0、角色计数 0。

实际通过两项：

- typed script write → 新 Session reload → API replay 完全一致，同一 idempotency key 只有一个 version，Edition 数为 0；
- 两个并发 Session 在同一 Document 上分配不同动作，第二个在第一个提交前不能越过行锁，最终 version number 精确为 `[1, 2]`。

没有新建 Docker 容器、第二个长期数据库、Redis 或队列服务；没有接触正式小说正文或删除持久卷。

## 6. 固定 QwenPaw、HTTP 与卸载非回归

### 6.1 最终运行态

本项目长期容器仍为三项且全部 healthy：

| 容器 | 作用 |
| --- | --- |
| `ai-novel-2026-qwenpaw-lab` | QwenPaw 2.1.0 + PawApp |
| `ai-novel-2026-postgres` | 唯一项目 PostgreSQL 18 数据库 |
| `ai-novel-2026-moss-tts-sidecar` | 固定 Linux/arm64 Nano Sidecar |

安装后公开 health：`status=ready`、`technical_enabled=true`、`lifecycle_status=ready`、`sidecar_reachable=true`、`model_ready=true`、`product_visible=false`。migration head 为 `20260826_0016`。

对不存在的 UUID 调用真实路由：

```text
GET /api/ai-novel-world-2026/narration-script-versions/<missing>
HTTP 404
Cache-Control: no-store
code=RESOURCE_NOT_FOUND
contract_version=narration-script-review-api/1
```

这是领域 404，不是未注册路由。没有向正式库写测试脚本。

### 6.2 uninstall → reinstall

- 官方 DELETE 卸载成功后，上述脚本路由返回宿主 `{"detail":"Not Found"}`，证明插件路由和 factory 已清理；QwenPaw 容器仍 healthy。
- 卸载前后数据库计数精确保持：novels `6→6`、document revisions `123→123`、script versions `0→0`、Editions `0→0`。
- 标准安装重新完整执行 TypeScript、Vitest、build、Python 全量、package、hot install、Alembic、Agent 配置和公开 health verify，一次通过。
- 重装后同一 URL 恢复结构化 T3 错误契约和 `no-store`；三个长期容器均 healthy。

卸载和重装未删除 PostgreSQL 数据卷、QwenPaw 命名卷、小说、正文 revision、媒体或用户 Agent 选择。

## 7. 自动化、构建、打包与终审

| 验证 | 实际结果 |
| --- | --- |
| T3-GATE 三个核心 Python 测试文件 | `29 passed`；live DB 文件在无 URL 时 `2 skipped` |
| disposable PostgreSQL 18 | `2/2 passed`，cleanup `db:0, role:0` |
| `.venv/bin/python -m pytest`（最终 install 两次） | 每次 `1211 passed, 97 skipped, 2 warnings` |
| 前端 `pnpm test` | `60 files / 499 tests passed` |
| `pnpm typecheck` | PASS |
| `pnpm build` | PASS；73 modules，`frontend/dist/index.js` 2,228.81 kB，gzip 768.45 kB |
| `.venv/bin/python scripts/package_plugin.py` | PASS |
| 标准 hot install | PASS；runtime ready |
| 官方 uninstall → reinstall | PASS；路由清理／恢复、数据计数不变 |
| 专项 `git diff --check` | PASS |
| 独立对抗终审 | `145 passed`；P0=0、P1=0 |

97 项 skip 是未注入的可选数据库／外部集成环境；本门禁要求的 PostgreSQL 真实用例已用精确 disposable URL 单独执行并全部通过。两条 warning 是既有 Starlette/httpx 与 FastAPI 422 常量弃用提示，不属于 T3 失败。

## 8. 最终实现源 hash

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/script_versions.py` | `fe1f9db0aec8930e308801d88d317fabb3401a4668dd12620f3f945de8b7503a` |
| `backend/narration/script_analysis.py` | `9ebd1d84769a863fa9853d6b2ffd1737f813be0830ea5d22bac65aa4deb72baa` |
| `backend/narration/script_api.py` | `2970956be073781cf8314935e0265ece0f4334373c012fbd54ff2a06386a42d3` |
| `backend/narration/script_backend.py` | `3567068e74da814867c77ae8a68f9c91c9c600e43e4456fe211a94330069e684` |
| `backend/app.py` | `8ad4cfdc79d1d2821cf78959cc6467ce8538416c8d35c384411928cd9bdd78e7` |
| `tests/narration/test_script_versions_t3_gate.py` | `8f6a11db77e255e27e888ac0fbc3cdd3c2a686c70ca3b94aafb0900f374fc53a` |
| `tests/narration/test_script_analysis.py` | `f69da316607a7f15df2c0fb7aa7bda15761b6309b124bcfa3f0222e08435350b` |
| `tests/narration/test_script_backend.py` | `1fa3ccf1f0903fab018951d11580621bb3b7890fc0e0f64d42001170fea71404` |
| `tests/narration/test_script_postgres.py` | `456281b668f4902a3b149630e5f555ca5a974ab6798126500631e2efc4d1b172` |
| `frontend/src/narration/script-contracts.ts` | `ee4e5bc86a3cc44e6fa3da114376fb69d3c515e7c30f4a59667ae11b189d67c1` |

本文不记录自身 hash，避免自引用循环。T3-H 的历史 source hash 继续保留；本节是 T3-GATE 对 request-scoped factory、`STORAGE_UNAVAILABLE` 和 typed persistence 接线后的显式 implementation re-freeze，不宣称历史文件 byte-identical。

## 9. 恢复与回退

- 脚本分析失败或 Sidecar 不可用不会修改正文、working copy、正式 revision 或故事账本；T3 分析本身不调用 Nano。
- 旧 typed/legacy 脚本不原地改写；重新分析创建 successor version。
- PawApp 可用官方 DELETE 完整卸载，已经证明插件路由与 backend factory 消失且 QwenPaw 原生服务保持健康。
- 回退 T3 代码时移除 script router/factory 和 T3 局部模块接线即可；不倒拨迁移、不删除数据库、脚本历史或声音权利记录。
- 如后续发现 authority 证据不足，保持对应 capability HOLD，并在本项目适配层向前修复；不得修改 QwenPaw 上游核心。

## 10. 下一 ready set

T3-GATE 通过后，T4 按依赖分批释放：

1. `T4-DEP`（SER）先接入唯一正式编辑器依赖并冻结根 lock、bundle 增量和保存链边界；Monaco 不进入 lock。
2. 不依赖 T4-DEP 的 `T4-A`（Edition/request）、`T4-B`（worker）、`T4-C`（后处理）、`T4-D`（Manifest/API）和 `T4-J` 测试骨架可按精确文件 Owner 并行，但公共 DTO、状态机、媒体路径和 migration Owner 必须先由主代理冻结。
3. `T4-E` 消费 T4-D mock；`T4-F` 等待 T4-DEP；`T4-G/H/I` 等待各自前置契约后再进入下一波。
4. `T4-K` 的真实 Nano、相邻句段听检、30 分钟耐久与 RTF 使用 `LOCK-NANO` 串行；最终 `T4-GATE` 仍由主代理唯一集成。

T4 的 UI 只验收 1920×1080 与 2560×1440。T4-GATE 通过前，章节智能朗读、句段播放、高亮、跳播和边听边改不得表述为用户可用。
