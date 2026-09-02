# L51-W2 全书账本 API 与查询基准

状态：**PASS；API/DTO/查询实现通过，用户随后批准的 `L51-MIG-QUERY` 已完成并解除查询扫描硬门禁。**

日期：2026-09-02（Asia/Shanghai）

## 1. 已冻结实现

新增只读 API：

- `GET /novels/{novel_id}/story-ledger/summary`
- `GET /novels/{novel_id}/story-ledger/facts`
- `GET /novels/{novel_id}/story-ledger/facts/{fact_id}`
- `GET /novels/{novel_id}/story-ledger/facts/{fact_id}/source`
- `GET /novels/{novel_id}/story-ledger/facts/{fact_id}/impact-preview`
- `GET /novels/{novel_id}/story-ledger/batches/{batch_id}/impact-preview`

关键事实：

- 每个响应在新 Session 的首个数据库动作前进入只读 `REPEATABLE READ`；token、页选、分类和 enrichment 来自同一快照。
- opaque `ledger-snapshot/1` 绑定小说与 `story_ledger_version`；`story-ledger-cursor/1` 绑定 token、规范化筛选 SHA-256、`created_at DESC` 和 `id DESC`。版本或筛选变化返回 409 `stale_page`，不混页。
- 默认列表先在数据库选 `limit + 1` 个 ID，再只对本页分类和定批 enrichment；需要 effective/health/review 的组合筛选在数据库完成分类扫描后再 limit。summary 是独立聚合，不实例化 StoryFact ORM。
- 列表不读取完整 `object_text`、details、visibility 或正文；详情按需读取事实正文；来源 API 只读取最大 1,600 code points 的有界摘录，列表／详情不加载完整 revision。
- 8 种冻结 fact type、无实体合法形态、实体已删除／缺失、空账本、单／多时间线、冲突、supersedes、reverted batch、作品越权和并发插入均有契约测试。
- 事实／批次影响预览复用现有 correction／revert 服务，不复制第二套 mutation 规则。

旧公开 `GET /novels/{id}/story-facts` 未越权删除，已标记 deprecated 并返回：

- `Deprecation: true`
- `Sunset: Tue, 01 Dec 2026 00:00:00 GMT`
- 指向新 list 的 successor `Link`

它最早在 0.6.0 且不早于 2026-12-01 才可按 W4b 窗口删除。

## 2. API 与一致性复验

隔离数据库：一次性 PostgreSQL 18 + pgvector，数据库名带 `_test`；未导入长期小说。

```bash
AI_NOVEL_TEST_DATABASE_URL='postgresql+psycopg://***@127.0.0.1:59926/plan51_w1c_test' \
  .venv/bin/python -m pytest tests/story_ledger -q
```

结果：**18 tests collected，全部通过**。覆盖同一 repeatable-read 请求期间的并发写入：当前响应 token 与数据保持旧快照一致，下一事务才观察到新版本。

## 3. 500／2,000／10,000 修复前基准

命令：

```bash
PYTHONPATH=. AI_NOVEL_TEST_DATABASE_URL='postgresql+psycopg://***@127.0.0.1:59926/plan51_w1c_test' \
  .venv/bin/python tests/story_ledger/benchmark_postgres.py
```

这是批准迁移前保存的历史基准：脚本强制校验测试库后缀，创建三部隔离合成小说，当时的候选探针索引只在测试中创建并删除，最后删除合成小说。列表均返回 20 行。它用于证明迁移必要性，不是当前正式索引下的最终结果。

| 事实数 | list SQL | StoryFact ORM load | 峰值内存 | list p50 / p95 | summary p50 | detail p50 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 500 | 7 | 20 | 0.599 MiB | 16.945 / 17.308 ms | 25.043 ms | 14.753 ms |
| 2,000 | 7 | 20 | 0.516 MiB | 39.539 / 42.538 ms | 83.946 ms | 40.242 ms |
| 10,000 | 7 | 20 | 0.515 MiB | 143.517 / 145.685 ms | 369.497 ms | 141.694 ms |

10,000 条峰值低于 2,000 条的 2 倍，证明 Python 内存不再随全书事实线性增长；默认同质页为 7 条 SQL，混合全部实体类型仍不超过 10 条，StoryFact ORM load 精确等于本页 20 条。

## 4. EXPLAIN 与正式索引结果

最终默认页 ID SQL 的实际扫描：

| 事实数 | 现有索引扫描 / 返回 | 执行时间 | 隔离探针索引扫描 / 返回 | 执行时间 |
| ---: | ---: | ---: | ---: | ---: |
| 500 | 500 / 20 | 0.083 ms | 21 / 20 | 0.024 ms |
| 2,000 | 2,000 / 20 | 0.322 ms | 21 / 20 | 0.023 ms |
| 10,000 | 10,000 / 20 | 1.719 ms | 21 / 20 | 0.019 ms |

上述修复前证据证明 API 的 SQL 数、ORM 装载和内存门禁通过，但旧索引在 2,000 条下扫描 2,000 行，未通过“默认页扫描不超过 64 行”的发布门禁。用户随后批准了唯一经测试的窄 DDL：

```sql
CREATE INDEX ... ON story_facts
  (novel_id, created_at DESC, id DESC)
  WHERE schema_version = 'story-fact/2';
```

它已由新 revision `20260902_0037` 以正式索引 `ix_story_facts_novel_created_v2` 实现。正式 benchmark 不再创建探针索引；500／2,000／10,000 三档均命中该 Index Only Scan，扫描／返回均为 21／20，执行时间分别为 0.021／0.018／0.018 ms，扫描门禁 **PASS**。

隔离迁移验证完成 `0036 → 0037 → 0036 → 0037`，4,000 条合成事实全部保持；迁移不改列、不改数据，downgrade 只删除索引。完整证据见 [L51-MIG-QUERY 窄分页索引迁移验收](./L51-MIG-QUERY-窄分页索引迁移验收.md)。

## 5. 当前边界

- 新 API 已经过 W3/W5 前端集成、候选真宿主页面复核和隔离插件生命周期验证。
- 公开旧 GET 仍在兼容窗口，当前只能保留带期限 deprecation，不能以“冗余”为由提前删除。
- 长期 `18088` 的备份、安装、迁移和回退没有授权、没有执行；W2／迁移 PASS 不等于长期发布。
