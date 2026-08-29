# 创作数据统一重构只读审计与合成回归样本

审计日期：2026-08-29（Asia/Shanghai）

审计性质：`CDV-AUDIT` 施工前只读证据。本目录只记录当前仓库事实、实现风险、门禁和合成样本说明，不代表 31 号计划中的数据库、服务、页面或向量能力已经实现。

## 1. 范围与安全声明

本轮只读取了当前仓库中的 SQLAlchemy 模型、Alembic 脚本、创作服务、上下文服务、既有测试、24／27／29／31 号计划和 ADR-0007。

- 未连接、查询或修改 PostgreSQL，包括长期库、测试库和容器内数据库。
- 未执行 Alembic upgrade／downgrade，未创建数据库备份或 reset manifest。
- 未调用阿里云百炼或任何其他云端／模型接口，未产生云费用。
- 未读取 `.env`、API Key、SecretStore 内容或其他真实密钥。
- 未读取或处理旧项目 `/Users/liujia/Documents/AI小说世界3/Data`。
- 未处理真实小说正文；`tests/fixtures/creative-data-v2/scenarios.json` 全部为合成数据。
- 未修改 QwenPaw 上游、未安装 PawApp、未暂存、提交或推送 Git。

因此，本审计可以证明代码与迁移的静态形状，不能证明长期数据库中的实际行数、数据质量、备份可恢复性、阿里云实时契约或真实页面行为。

## 2. 三路只读审计结论

### 2.1 Schema、迁移与任务运行时

已核实事实：

1. 当前 Alembic 只有一个线性 head：`20260828_0024`。新增迁移不得改写历史脚本，且必须在持有 `LOCK-MIGRATION-HEAD` 后重新发现真实 head。
2. 初始迁移已经安装 pgvector；`NovelChunk` 只有正文 revision、字符串 profile、块序号、文本、hash 和无固定 typmod 的 `VECTOR()`，不足以表达多 corpus、candidate／active generation、时间线、知识范围和私有素材绑定。
3. 正文已有 working copy、不可变 revision、候选采用、情报 proposal/item/commit batch 和来源有效性绑定，应当复用。
4. 关系已有稳定人物根 ID、关系根、不可变关系 revision 和 current pointer；故事内关系发展不应再覆盖关系定义。
5. 共享 `background_jobs`、attempt、租约、取消、重试、dead-letter 和 `model_run_records` 可作为向量批处理的公共底座；但现有 worker、executor 和资源策略仍与 narration 领域耦合，不能把向量任务伪装成朗读任务。
6. `BackgroundJob` 没有任务 payload；可靠的 10 条 embedding 批次需要独立、不可变的 batch 与 batch item 证据，否则重试时无法证明处理的是同一组 chunk。

首批 schema 的必要修正：

- 所有新小说范围实体使用 `(id, novel_id)` guard，子表通过复合外键阻止跨小说串联。
- StoryFact v2 的正文来源不能继续只存裸 `revision_id`；必须同时验证 document、revision 和 content hash。
- 正文 revision 的多段时间线映射不能只靠 head + segment 两层可靠版本化。最小正确结构为 mapping head、不可变 mapping revision、mapping segment 三层。
- 语义索引除配置、profile、generation、consent、source、chunk、embedding 外，还必须有逐小说 generation 状态和固定批次／逐项证据；否则无法安全激活 candidate 或精确重试。
- 个人小说规模首期不需要 HNSW／IVFFlat；结构化状态由确定性投影裁决，向量只保存可重建派生证据。

### 2.2 创作数据权威与调用链

已核实事实：

1. `OutlineDraft.characters_json`、`NovelCharacter`、`Novel` 大纲投影和页面输入目前可能表达同一人物或大纲信息；正式化后必须收敛为正式 head／revision 与稳定人物实体。
2. `StoryFact` 当前仍是通用文本事实，没有人物实例、时间线、故事时间、知识范围和实体范围外键。
3. `ChapterBrief.role_constraints` 仍是 JSON，既有流程中包含按姓名引用；新写入必须使用人物实例 ID，姓名只作显示与兼容读取。
4. `Storyline.progress` 和 `Foreshadow.latest_progress` 是可覆盖值；正式进展应从作者确认的 StoryFact 事件投影，GET/list 不得借读取机会修改它们。
5. 现有上下文路径没有统一读取正式规划、截止目标章节的 StoryFact 投影和语义证据；部分路径按固定条数选取旧事实，会遗漏较新事实，并可能把目标章节之后的信息带入较早章节。
6. 生产服务中存在样书专用词、自然语言关键词推断权威状态、非空正文强制产生情报和静默截断等硬编码风险。样书文字只能存在于 fixture，不能驱动生产分支。

统一权威边界：

```text
作者正式规划 revision
  -> 正文不可变 revision
  -> AI 候选
  -> 作者确认的 StoryFact v2
  -> 指定 timeline/cutoff/perspective 的只读投影
  -> 统一上下文 assembler
  -> 可重建语义证据
```

人物根表示跨时间线叙事身份，人物实例表示具体连续个体；改名不能改变任何稳定 ID。真实身份事实、读者何时获知、某人物何时获知是不同事件，不能在“揭晓”时重写人物从何时拥有该身份。

### 2.3 私有库、向量接入与泄漏边界

已核实事实：

1. `PrivateAsset` 当前内容原地覆盖；preset 只引用素材根。生成 job 虽有 `asset_snapshot`，仍不足以证明私有库版本、来源权利和小说固定绑定。
2. 私有素材必须先形成不可变 version，再由 preset 或小说 binding 固定具体 version；素材更新只能提示，不得静默改变后续小说上下文。
3. 未绑定的全局私有素材不能因为另一部小说已授权而进入该小说索引或云端请求。
4. 当前仓库有 pgvector schema 和词面检索，但静态代码证据不能证明真实语义服务、向量行数或检索质量已经存在。
5. 目标接入为 PawApp 自有的全局向量模型接入页和小说内授权／索引卡片，不占用 QwenPaw 全局模型页，也不跟随正文 Agent 模型切换。
6. 当前计划指定阿里云百炼 DashScope Native、`qwen3.7-text-embedding`、1024 维 Dense、cosine、document/query 双角色和批次 10；这些时效事实仍须在 `CDV-CLOUD-G` 用官方一手资料和非敏感哨兵重新核验。
7. API Key 必须 write-only，只保存 SecretStore 引用；不得进入 ORM 明文字段、日志、fixture、前端本地存储或普通上下文响应。

检索的安全顺序必须是：先校验 owner/workspace/novel、consent、current source、timeline 可达性、叙事截止点和观察者知识，再在允许 corpus 内做向量／词面召回。检索后的 metadata 过滤不能替代检索前隔离。

## 3. 合成 fixture

[`scenarios.json`](../../tests/fixtures/creative-data-v2/scenarios.json) 使用 `creative-data-v2-scenarios/1.0`，仅包含虚构人物、时间线、章节、事实和素材。它覆盖：

- 单时间线零配置基线；
- 分支只继承分叉点之前事实；
- 穿越者与目标线对应人物并存；
- 循环只建立新分支和显式 link，不改写原历史；
- 汇合只继承主线，其他输入必须显式转写事实；
- 真实身份与读者／人物知识时间分离；
- 改名后稳定人物根、实例、关系和 TTS 引用不变；
- 目标章节不得召回未来章节事实；
- 兄弟时间线事实不得泄漏；
- 未绑定私有素材不得进入 semantic source、chunk、embedding 或云端 batch。

fixture 面向后续 Pydantic、投影、上下文和检索隔离测试。`expected` 是规范性预期，不代表当前实现已经满足。测试不得把 fixture 中的虚构名称或文本复制进生产逻辑。

## 4. 数据、云端与发布门禁

### `CDV-SCHEMA-G`

- 先让出 `backend/models.py`、Alembic head 和共享迁移测试的唯一所有权。
- 重新执行 `alembic heads` 并冻结唯一线性迁移顺序。
- 迁移先在隔离 PostgreSQL 验证；不得改写已有迁移。

### `CDV-DATA-G`

- 若以后需要检查或重建当前实验数据库，必须先获得精确数据库范围授权。
- 先在仓库外生成 PostgreSQL 备份，再记录路径、大小、SHA-256、PostgreSQL 版本和可执行恢复命令。
- reset 必须使用显式 database URL、manifest hash 和确认参数；Alembic migration 不承担测试数据重建。
- 当前审计没有生成备份，不能据此执行 reset。

### `CDV-CLOUD-G`

- 重新核验官方模型、地域、Base URL、维度、批次、限流、价格和数据处理条款。
- 连接测试只发送非敏感哨兵。
- 真实小说或已绑定私有素材外发前，必须存在有效的小说级 consent、明确预算和目标小说范围。
- 未授权小说云端请求必须为 0；撤销授权后停止所有新请求。

### `CDV-RELEASE-G`

- 全量后端、前端、迁移、泄漏、恢复、浏览器和 QwenPaw 插件生命周期回归通过。
- candidate generation 未完整 ready 时不得激活；失败时旧 active generation 保持服务。
- 禁用向量后，正文写作、词面搜索和 QwenPaw 原生功能继续可用。

## 5. 恢复原则

- 所有新 schema 使用后继 Alembic revision；不改写已经存在或可能执行过的历史。
- 创作 revision、StoryFact、consent 和 generation 证据不通过普通删除清理。
- semantic source、chunk 和 embedding 是派生数据，可按 generation 精确清理并从权威 revision 重建。
- 清除 API Key 或撤销 consent 不删除正文、事实或本地向量；本地派生索引清理是独立显式动作。
- 若隔离升级失败，停止切换 PawApp；若长期测试库以后被授权重建且失败，按已验证恢复命令恢复备份，不删除 PostgreSQL／QwenPaw 数据卷。

## 6. 未验证项

- 长期数据库当前实际数据量、冲突行和向量行数；
- 新 schema 的 PostgreSQL upgrade／downgrade、锁时长和查询计划；
- 阿里云接口当前真实响应、1024 维、批次 10、价格和限流；
- 新页面、移动窄屏、键盘、焦点和错误恢复；
- 固定评测集的 Recall@5、MRR、泄漏率和端到端延迟。

这些项目必须由相应施工 Gate 和隔离测试补齐，不能从本只读审计推断为已经通过。
