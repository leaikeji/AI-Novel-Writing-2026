# T1-C schema 消费与后续边界

状态：**0012 是 T1-C execution-safety 基线；0013–0015 均为线性 fix-forward，当前 head `20260826_0015` 已在隔离 PostgreSQL 18 current-head suite 中验证。历史迁移不得回写。**

## 1. 0012 基线契约

| 契约 | 数据库能力 | T1-C 消费方式 |
| --- | --- | --- |
| manual retry command | command lifecycle、全 scope idempotency、单 pending、immutable audit、command/attempt deferred closure | `manual_retry` 只排队；claim 原子认领并写 attempt 审计 |
| executor epoch | generation unique、单 active、active→revoked one-way、attempt epoch FK | claim/worker mutation/reconcile 固定核对 active epoch |
| resource registry / slots | 四类 policy、六个 slots、五项 narration kind mapping | claim 按 registry 与 `max_concurrency` 领取，不硬编码请求方资源 |
| execution fence | attempt 固化 command/epoch/resource key/token/generation | 所有 mutation 依固定锁序复核 attempt 记录的 fence |
| publication closure | successful completion 必须仍持有 claim-time fence | 同事务 context 下先完成，再旋转/释放 resource |
| direct mutation shape | no-delete、identity immutability、generation/token lifecycle、deferred closure | 服务检查与 DB guard 共同 fail-closed，但不冒充权限隔离 |

当前 registry 保持：

```text
moss-nano        max=1 exact=moss-nano:inference         publish_fence=true
voice-generator  max=1 exact=voice-generator:generation  publish_fence=true
cpu-transcode    max=2 slots=cpu-transcode:0..1           publish_fence=false
cpu-analysis     max=2 slots=cpu-analysis:0..1            publish_fence=false

narration.segment_render → moss-nano
narration.export         → cpu-transcode
narration.voice_generate → voice-generator
narration.voice_preview  → moss-nano
narration.analyze        → cpu-analysis
```

未知 `narration.*` 必须 fail-closed；新增 kind、resource class 或 slot 只能由新 Alembic revision 修改 registry。

## 2. 0013–0015 对 T1-C 的关系

- `0013` 将媒体路径改为 asset-scoped，未改写 T1-C fence 状态机。
- `0014` 封闭 request source，未改写 job/attempt/resource registry。
- `0015` 增加 script/settings/rights 聚合锁序 guard，与 T1-C 的 job→attempt→epoch→resource 锁序相容。
- 当前 0015 live suite `56/56` 中，T1-C job slice `10/10`、domain concurrency `10/10`、publication atomicity `1/1` 均通过。

## 3. 数据库角色边界

角色包已证明 fail-closed 基线，但 `production_role_switch=HOLD`：

- schema owner/migrator/API/worker 是同一 PostgreSQL 的角色分工，不是新业务数据库；
- API/worker 当前无 raw DML；
- 尚无受审写过程或等价窄 worker adapter，所以当前角色不能承载真实 enqueue/claim/heartbeat/complete/GC/publish；
- role fragment 未接根 Compose，正式数据库仍在 `20260825_0009` 且未触碰。

T1-GATE 可以在明确记录上述 no-go 后保持角色切换 HOLD；不得为了形式通过而接入不可用角色，也不得把 secure HOLD 写成 production-ready。

## 4. 后续阶段，而非 T1-C 硬阻断

- T2 API/tool 负责鉴权后调用领域服务，不直接 DML。
- T4 scheduler/worker 在事务外执行模型/文件 I/O，发布时用 T1-C context 回到短事务。
- 产品 capability 在后续门禁前继续 false。

T1 内仍需由 GATE Owner 做的是 PawApp 最窄生命周期/健康接线、安装与禁用/卸载非回归、当前 package 与证据汇合；本文件不裁决 T1-GATE。
