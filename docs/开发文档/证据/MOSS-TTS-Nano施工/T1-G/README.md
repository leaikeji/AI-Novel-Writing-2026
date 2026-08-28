# T1-G：阶段 1 基础设施集成与恢复证据

## 结论

状态：**`READY_FOR_T1_GATE_REVIEW`（测试与证据范围）**。主代理已在隔离 PostgreSQL 18 完成当前迁移链与 head `20260826_0015` 的汇合：migration `6/6`、request sealing `8/8`、asset migration `2/2`、current-head live suite `56/56`；domain concurrency `10/10` 使用真实两会话锁等待，publication atomicity `1/1` 的完整用例重复两次均通过。正式数据库保持 `20260825_0009` 且未触碰。

本结论只把 T1-A–F 的基础设施交给 T1-GATE Owner 复核；**不表示 T1-GATE 已通过，也不表示产品 API、长期 Worker、播放器/UI 或 capability 已启用。**

## 1. 当前验证矩阵

| 验证 | 结果 | 关键覆盖 |
| --- | --- | --- |
| `test_migrations.py` | `6/6` | 线性 head、foundation 元数据、关键约束、0010 条件回退 |
| `test_request_source_sealing_postgres.py` | `8/8` | 0014 preflight、精确 seal、replay、seal 后 child immutable |
| `test_asset_scoped_migration.py` | `2/2` | 0013 asset path preflight、条件 downgrade/re-upgrade |
| current-head live suite | `56/56` | jobs、media、asset scope、snapshots、并发、publication、foundation、crash recovery |
| domain concurrency slice | `10/10` | script approval/children、settings/override/snapshot、voice use/revoke 的双向提交顺序与真实 lock wait |
| publication atomicity slice | `1/1`，重复两次 | DB 失败全回滚、文件保留、确定性 re-adopt、同事务权威提交 |
| 当前无数据库组合 | `175/175` | jobs 34、media 76、domain 12、contracts/adapters 53 |

current-head 56 项精确组成：

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

## 2. 已证明的集成与恢复能力

- fake adapter 与真实 SQLAlchemy store 可完成 request→snapshot→script→Edition→job/fence→model-run/media→ready render，并保持正式 revision/working copy 不变。
- 同 fingerprint cache 可复用，跨 novel scope cache 被拒绝，`analyze_only` 不创建 Edition/render/audio。
- claim 提交前崩溃可幂等重放；过期 lease 可 reconcile；新 executor epoch 永久拒绝旧 fence。
- active-job/media reference 可阻止 GC；media 发布失败或 DB 回滚不会留下可达半成品。
- publication writer 在同一事务写入 model-run、master/playback assets、render links、ready render 和 attempt completion；失败后数据库零部分提交，确定性文件可重试采用。
- current-head catalog、trigger、resource policy 与领域 concurrency guards 由真实 PostgreSQL 执行，不以 SQLite/mock 代替锁等待证据。

## 3. T1-GATE 边界

### 可以带着 no-go 通过的事项

- `AI_NOVEL_TTS_RUNTIME_ENABLED=false`、`product_visible=false`、`production_ready=false`：T1 是基础设施阶段，capability false 是安全预期。
- `production_role_switch=HOLD`：角色包是同一 PostgreSQL 的 secure fail-closed 候选，目前 business write path 不可用且未接根 Compose。只要 GATE 明确记录 no-go，不得将其表述为 production-ready，即可保持 HOLD；不需要第二个业务数据库。
- T2 产品 API、T4 长期 scheduler/worker、浏览器播放器/UI、真实用户工作流：均属于后续已规划阶段，不是 T1 硬阻断。

### T1 内仍需 GATE Owner 关闭或明确验收的事项

1. PawApp 最窄技术生命周期/健康接线：false 路径零 Sidecar 依赖；隔离 true 路径可认证、health/warmup，并在 poison 后观察新 generation；不得修改 QwenPaw 上游。
2. 当前 package 的隔离安装/升级/禁用/卸载非回归：卸载后无插件路由/Skills/tools/wrapper 残留，QwenPaw 原生能力正常；保留用户数据卷、模型和媒体恢复策略。
3. 汇总当前源码 hash、migration 0010–0015、package/Compose 与宿主证据并由唯一 Owner 形成 `T1-GATE.md`。

上述是 T1-GATE 工作，不由本 T1-G 证据提前宣称完成。

## 4. 数据隔离事实

- live suite 只连接精确 test identity 的 loopback disposable PostgreSQL 18。
- 正式 PostgreSQL 数据库保持 `20260825_0009`；未迁移、未降级、未读写。
- 测试库不挂正式数据库卷、QwenPaw 核心卷或用户媒体卷。
- role package 未接根 Compose；它描述同一数据库的未来最小权限角色，不是新增生产数据库。

机器可读结果见 `integration-validation.json`，角色边界见 `roles-README.md` / `roles-validation.json`，当前摘要见 `hashes.sha256`。本证据不裁决 T1-GATE。
