# T1-C：持久任务、租约与资源围栏（0015 current-head 证据）

状态：**`READY_FOR_T1_GATE_REVIEW`（仅 T1-C 基础设施范围）**。T1-C 对 0012 建立的 immutable manual retry、executor epoch、resource policy/slot、attempt-recorded fence 与 publication context 的实现保持不变；主代理又在迁移 head `20260826_0015` 的隔离 PostgreSQL 18 环境完成 current-head 汇合，T1-C 的 10 个 live job 用例包含在 **56/56 passed** 中。当前证据不等于 T1-GATE 已通过，也不开放产品 capability。

工作包：`T1-C`（`PAR-C`）；日期：2026-08-26（Asia/Shanghai）。

## 1. 已实现契约

| 契约 | 当前实现与验证 |
| --- | --- |
| immutable manual retry | `manual_retry` 固定 actor/reason/idempotency key，只追加 command；claim 后才创建新 attempt，支持有审计地越过 automatic max。 |
| executor epoch | claim 固化 active epoch；heartbeat/fail/cancel/complete/publication/reconcile 重新锁定并核对 epoch，撤销后旧 worker fence 全部失效。 |
| resource registry / slots | 从数据库 registry 读取 kind→resource policy 与 slot，不接受请求方自由指定；无 slot 时不创建 attempt、不泄漏锁。 |
| attempt-recorded fence | resource key/token/generation 固化在 attempt；worker mutation 只能消费 attempt 记录的 fence。 |
| publication context | `lock_result_publish_fences` 返回绑定同一 `Session`/transaction 的 context；commit、rollback、close 或换事务后旧 context 失效。 |
| completion order | 成功状态先在 live resource fence 下 flush，再旋转 token/释放资源并第二次 flush；服务自身不 commit。 |
| unknown job kind | 未注册 `narration.*` fail-closed；新增 kind/policy/slot 只能通过新的迁移。 |

锁序保持为：

```text
claim          : job → pending manual command → active epoch → slot → resource
worker mutation: job → current attempt → executor epoch → attempt-recorded resource
publish        : PublicationFenceContext → authoritative rows → successful completion
                 → resource token rotation/release → caller commit
```

外部模型、网络或文件 I/O 不得进入上述数据库短事务。

## 2. 当前字节验证

当前源码 head 是线性的 `20260826_0015`。主代理使用与正式库不同的 loopback disposable PostgreSQL 18；正式数据库保持 `20260825_0009`，未迁移、未读写，测试实例不挂正式卷。

| 验证 | 结果 |
| --- | --- |
| 当前无数据库组合单测：`test_jobs.py test_media.py test_domain_services.py test_contracts.py test_adapters.py` | `175 passed`；其中 T1-C `test_jobs.py` 为 `34/34` |
| current-head live suite | `56/56 passed`，0 failed、0 skipped |
| T1-C current-head slice：`test_jobs_postgres.py` | `10/10 passed` |
| T1-F 并发锁序 slice：`test_domain_concurrency_postgres.py` | `10/10 passed`，真实两会话锁等待而非 mock |
| publication slice：`test_publication_postgres.py` | `1/1 passed`，完整用例重复两次均通过 |

T1-C 早期在 head 0012 的 `34 SQLite + 10 live PG = 44` 与 live job 连续两次通过仍是历史证据；本次 0015 汇合结果取代“只有 0012 已验证”的旧措辞，但没有改写 0012 的迁移历史。

## 3. capability、角色与阶段边界

- T1 允许 `AI_NOVEL_TTS_RUNTIME_ENABLED=false`、`product_visible=false`、`production_ready=false` 进入 GATE；保持 capability false 不是 T1-C 缺陷。
- PostgreSQL 角色包目前是 **secure HOLD**：API/worker raw DML 为零，但没有 enqueue/claim/heartbeat/complete/GC/publish 的受审窄写入过程，故不能切换生产连接。它是同一 PostgreSQL 的角色方案，不是第二个业务数据库，也未接入根 `compose.yaml`。
- 角色包可作为明确 no-go 随 T1-GATE 保持 HOLD；不得把它写成“业务可用”，也不得为通过 T1 强行增加第二数据库。
- T2 产品 API、T4 长期 scheduler/worker 和产品 UI 不属于 T1-C 退出条件。本包只交付以后由这些阶段消费的持久任务与 fence 基础设施。
- PawApp 最窄生命周期接线、包安装/禁用/卸载非回归和最终证据裁决仍由 T1-GATE 唯一 Owner 完成；本文件不声称已经完成。

精确输入与角色边界见 [follow-on-schema-requirements.md](./follow-on-schema-requirements.md)，机器可读结果见 `validation.json`，固定摘要见 `hashes.sha256`。

门禁结论：`T1-C_READY_FOR_T1_GATE_REVIEW`；`T1_GATE_NOT_DECIDED_BY_THIS_EVIDENCE`。
