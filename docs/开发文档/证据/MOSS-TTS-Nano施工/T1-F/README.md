# T1-F：持久领域服务与并发边界证据

状态：**`READY_FOR_T1_GATE_REVIEW`（领域服务范围）**。当前无数据库领域/契约 slice 为 `65/65 passed`；在隔离 PostgreSQL 18、Alembic head `20260826_0015` 上，request source sealing `8/8`、current-head live suite `56/56`、domain concurrency `10/10`、publication atomicity `1/1`（重复两次）均通过。旧证据中“真实 PostgreSQL、0012 closeout 与组合发布均未验收”的措辞已由本次结果取代，但本文件仍不裁决 T1-GATE 或产品 GO。

日期：2026-08-26（Asia/Shanghai）；工作包：`T1-F`（`PAR-C`）。

## 1. 当前领域服务

| 模块 | 已实现边界 |
| --- | --- |
| `requests.py` | canonical request hash、幂等 replay、父作品锁、request CAS；单章 revision/hash 与全书结构化 sources；`analyze_only` 禁止生成 |
| `snapshots.py` / `settings.py` | snapshot 只从持久 settings/override 派生；隐藏 revision、父锁、CAS 与并发 reload |
| `script_versions.py` | scenes/segments/issues 纳入 immutable hash；审批前重算，审批后 child insert/update/delete fail-closed |
| `editions.py` | 完整覆盖 approved segments；音色、rights、scope 与 segment fingerprint 服务端复核 |
| `renders.py` | `narration-render-input/1`、source job 与 cache scope；ready 发布要求组合 job/resource fence |
| `publication.py` | model-run、master/playback MediaAsset、render links、ready render 与 attempt completion 的单事务写入 |
| `manifest.py` | 从 ready render/playback MediaAsset 派生 Manifest v2、ranges、duration、revision 与 ETag；pending 不持久化 |
| `progress.py` | concrete ready-range 校验、`updated_at` CAS、文档 Edition 指针从 Edition 派生 |
| `services.py` | SQLAlchemy Session 适配、固定本地 scope、权利复核；只 flush、不 commit，外部 I/O 不进事务 |

组合发布顺序冻结为：

```text
T1-C lock_result_publish_fences
  → T1-E deterministic file publication
  → T1-F publication writer 写 model-run/media/link/render ready/attempt complete
  → caller commit
```

任一步异常均回滚数据库；已耐久且身份正确的确定性文件保留，下一次相同证据重试可安全 re-adopt。

## 2. 旧 closeout 项的当前结果

| 原待关闭项 | 当前证据 |
| --- | --- |
| 全书 `analyze_only` structured source | 0014 request source sealing live `8/8`；精确 seal、顺序/数量、replay 与 seal 后 immutable 均通过 |
| settings snapshot phantom/drift | `test_snapshots_postgres.py` `6/6` + domain concurrency 中 settings/override 锁等待用例 |
| approved script child race | 0015 guard + domain concurrency 插入/更新/删除双向提交顺序用例 |
| voice use 与 revoke 竞态 | domain concurrency 两个真实锁等待提交顺序用例 |
| 组合 fence 与原子 publication | `test_publication_postgres.py` `1/1`，完整用例重复两次 |
| crash/restart 后旧 fence | `test_crash_recovery.py` `6/6` |
| fake/domain-to-ready render | `test_foundation_integration.py` `6/6`，其中 live SQLAlchemy pipeline 在 0015 head 执行 |

Manifest revision/progress CAS 的精确投影仍由 12 个 `test_domain_services.py` 用例和数据库 constraint/parent-lock 实现验证；本证据不额外声称做过独立的浏览器/播放器或 T4 Worker 多进程压力验收。

## 3. 当前验证结果

- 当前无数据库组合命令：`175 passed`；其中 T1-F `test_domain_services.py` 12 项 + T1-A contracts/adapters 53 项，共 `65/65`。
- request source sealing：`8/8 passed`。
- current-head live suite：`56/56 passed`，0 failed、0 skipped。
- domain concurrency：`10/10 passed`，使用真实 PostgreSQL 两会话 lock wait，不是 mock。
- publication atomicity：`1/1 passed`，完整用例重复两次均通过。
- 正式数据库仍为 `20260825_0009`，未连接、未迁移、未降级。

## 4. 当前 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `requests.py` | `72d3e88c15ec33dda6ec9902ce41018fe6aee6055c0035db063e6c871fe92493` |
| `snapshots.py` | `a3e5997c6b1f1e38a74ffe1f7213239df11596c626d693f6a7b9a22f3a21a78f` |
| `settings.py` | `77d8ad0d3f2a4375d9672c547c4ee33c4801b5e8385a88c94c2e3ce78805981a` |
| `script_versions.py` | `d745da76564998a8b093721b376c15a1bc38f091da87f235dc89af7d950c2fd0` |
| `editions.py` | `553546d1200482bf20fd2ba14d5c62c12297e1f72f55bfabbec846f769a1f6fd` |
| `renders.py` | `68a743dc8147320ea111ee864a58da26ab8a150dd1f3ce6b1055f7e9e6f0122b` |
| `manifest.py` | `e814bef268a7fbe6708797e16344c1499539f06b0e1d15337322f53df7c11584` |
| `progress.py` | `2b713746b7e002888869b3b34543554aa687a4612cf8b21364be857a863df3f9` |
| `services.py` | `2be849e80bca38a9de738ef11193bddd4e199483e423b8a3afde4393f3c31e11` |
| `publication.py` | `09ec2b404b73e61ab6e0ac6c223276e2e19092da66d06bb21050f10fbb4bb344` |
| `test_domain_services.py` | `ca2555dfb206e68a2148dbb6fc27ad8acd1a1473222dd65669b8ac4a9a90e8e8` |
| `test_snapshots_postgres.py` | `1c0e087c21781979ac051e4d064908ac13fba7591fe68d5e925ee3ce54aafccb` |
| `test_domain_concurrency_postgres.py` | `7b56b46a64852ff9e33bff3399800d634fe112c53da442193d89c3ab961aaa7d` |
| `test_publication_postgres.py` | `ef73b71535696f234c032331f6d33a15cb5dfbfa9268dc893bfb32f72742965d` |

## 5. 阶段与能力边界

- capability 保持 false 是 T1 的安全预期，不是本包未完成项。
- database role package 是同一 PostgreSQL 的 secure HOLD，当前 business write path 不可用且未接根 Compose；T1-GATE 可明确保留该 no-go，不需要新建第二数据库。
- T2 API、T4 scheduler/worker、播放器/UI 和真实用户朗读流程属于后续阶段，不应倒灌为 T1-F 阻断。
- T1-GATE 仍需独立完成 PawApp 最窄生命周期、安装/禁用/卸载非回归与最终 package/证据汇合；本文件不声称这些已经完成。

机器可读不变量与验证等级见 `invariants.json`。失败回退只停止公共接线并 forward-fix；不得删除 TTS schema、媒体、小说正文或历史证据。
