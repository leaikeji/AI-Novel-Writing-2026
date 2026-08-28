# T1-D：Narration schema 与 0010–0015 线性迁移证据

状态：**`READY_FOR_T1_GATE_REVIEW`（schema/migration 范围）**。`20260826_0010` 仍是冻结的 foundation revision；所有后续安全修复均以 `0011`–`0015` 线性 fix-forward 实施，当前唯一 Alembic head 为 `20260826_0015`。主代理已在隔离 PostgreSQL 18 完成 migration `6/6`、request sealing `8/8`、asset migration `2/2` 及 current-head live suite `56/56`。这不等于 T1-GATE 或产品 GO。

日期：2026-08-26（Asia/Shanghai）。

## 1. 当前线性迁移链

```text
20260825_0009
  → 20260826_0010 narration foundation
  → 20260826_0011 media safety
  → 20260826_0012 execution safety
  → 20260826_0013 asset-scoped media paths
  → 20260826_0014 request source sealing
  → 20260826_0015 domain concurrency guards (head)
```

`alembic heads` 只返回 `20260826_0015 (head)`，不存在第二 head。0010 的 39 张 foundation 表、既有表扩展、169 个具名约束与 frozen taxonomy 仍由 `schema-matrix.json` 描述；0011–0015 不回写 0010，而是依次收紧媒体、执行 fence、路径作用域、request source seal 以及 script/settings/rights 聚合锁序。

## 2. 当前隔离 PostgreSQL 18 验证

所有 live 验证只使用与正式库不同的 loopback disposable PostgreSQL 18，不挂正式数据卷。正式数据库仍为 `20260825_0009`，本轮未迁移、未降级、未读写。

| 验证 | 当前字节结果 |
| --- | --- |
| `tests/narration/test_migrations.py` | `6/6 passed` |
| `tests/narration/test_request_source_sealing_postgres.py` | `8/8 passed` |
| `tests/narration/test_asset_scoped_migration.py` | `2/2 passed` |
| current-head 0015 live suite | `56/56 passed`，0 failed、0 skipped |
| `tests/narration/test_domain_concurrency_postgres.py` | `10/10 passed`，包含真实两会话锁等待 |
| `tests/narration/test_publication_postgres.py` | `1/1 passed`，完整用例重复两次均通过 |

current-head live suite 的 56 项由以下文件组成：

```text
test_jobs_postgres.py                    10
test_media_postgres.py                   11
test_media_asset_scope_postgres.py        6
test_snapshots_postgres.py                6
test_domain_concurrency_postgres.py      10
test_publication_postgres.py              1
test_foundation_integration.py             6
test_crash_recovery.py                     6
total                                     56
```

## 3. 迁移与回退结论

- `test_migrations.py` 保留 0010 foundation 的空数据 `0010 → 0009 → 0010` 与有 narration 数据时 downgrade fail-closed 证据。
- `test_asset_scoped_migration.py` 验证 0013 的 preflight、未搬迁行拒绝、条件 downgrade 与重升，`2/2`。
- `test_request_source_sealing_postgres.py` 验证 0014 preflight 原子性、空数据可逆、seal 完整性及已 seal 子项不可变，`8/8`。
- 0015 是当前线性 head，并已承载 56 项 current-head live suite；现有证据不宣称在带真实 narration 数据的正式库执行过 0015→0009 全链降级。
- 正式策略仍是升级前完整备份、失败时固定旧镜像兼容保留 schema、优先 fix-forward；不得为回退删除小说、音色、媒体、job audit 或 revision。

完整保护策略见 [rollback.md](./rollback.md)。

## 4. 当前源码 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `backend/models.py` | `516b87909d683688e61e0ee8a51c3c26e157ae1c3841e592be20eb6e7f7ef8ac` |
| `0010_narration_foundation.py` | `8b4608449c056e5283e5d84c69d63d59c11beb49d8f28f60f88bf83ea3a465bd` |
| `0011_narration_media_safety.py` | `08a7d9a3c7c3d0f4b03081ac4d6b5acef24ce9d80642320219874cd3c4d99174` |
| `0012_narration_execution_safety.py` | `ab4384841a5471ef2638c2f5118f5e23028e32a333545c427445550f5e82c805` |
| `0013_narration_asset_scoped_paths.py` | `574762bfc63761cde77731118335549079758f221c9889e4ad0fdca8f95ec18e` |
| `0014_narration_request_source_sealing.py` | `aff61715c233ed4161c6ccdedc2a810e02bee0be3c486867ff2a8565121ca590` |
| `0015_narration_domain_concurrency_guards.py` | `553874380655e9762bba9de59e9230a69ff5364b76cf8a2d36d60196f7583a58` |
| `tests/narration/test_migrations.py` | `e6243e597c20ea4222661b2155f69e7c3cb4d02a1ab6aaa480a4c4d43297f0b6` |
| `tests/narration/test_request_source_sealing_postgres.py` | `4ed996e58d81f32f5047ecfc771df1b025a8f51ae51b7287f2528d558f1bd6b1` |
| `tests/narration/test_asset_scoped_migration.py` | `52b754f336ce2efc4ca7a030ae3a0c5d714d130e7997971738283e594996bbfb` |

机器可读命令与结果见 `validation.json`、`migration-plan.json`。T1-D 只证明 schema/migration 基础设施，不声明 T2 API、T4 Worker、产品 capability 或 T1-GATE 已通过。
