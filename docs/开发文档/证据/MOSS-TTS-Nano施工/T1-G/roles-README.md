# T1-G PostgreSQL 角色隔离底座证据

状态：**`SECURE_HOLD`。历史 disposable PostgreSQL 18 角色验证在 head `20260826_0012` 通过；当前 validator 源码期望 head 已更新为 `20260826_0015`，但本轮没有新建角色测试容器，也没有在 0015 重跑 live role suite。`production_role_switch` 继续为 `HOLD`。**

## 1. 它是什么，不是什么

- 它是同一 PostgreSQL 内的最小权限角色候选：`ai_novel_schema_owner`、`ai_novel_migrator`、`ai_novel_api`、`ai_novel_worker`。
- 它不是第二个生产数据库，也不要求 TTS 使用独立业务库。
- `compose.example.yaml` 只是一次性验证 fragment，未接入根 `compose.yaml`。
- 正式数据库保持 `20260825_0009`，未因角色测试或证据刷新而迁移、降级或读写。

## 2. 已有安全证据

在历史 0012 disposable 环境中：

- database/public schema/application objects 归 NOLOGIN schema owner；migrator 仅可受控 `SET ROLE`。
- API/worker 对全部 public application tables 的 raw INSERT/UPDATE/DELETE 为零。
- PUBLIC/API/worker 对 public routines 的 EXECUTE 为零；SECURITY DEFINER routine 为零。
- pgpass 使用三个独立 mountpoint、0600 文件、0700 父目录，不把密码写入 argv/证据。
- live role tests `10/10 passed`；330 次 protected-table DML 负测全部拒绝。

这些历史结果证明 fail-closed 角色底座，不证明当前 0015 业务写路径可用。

## 3. 为什么必须 HOLD

当前没有 enqueue/claim/heartbeat/fail/cancel/complete/reconcile/GC/publish 的受审 `SECURITY DEFINER` procedures，也没有等价的窄 worker adapter。API/worker 都是只读角色，因此真实 narration 写路径不可用，不能切换生产连接。

T1-GATE 可以把这一点作为明确 no-go 保持 HOLD；capability 继续 false，后续若批准角色切换，再由独立工作包实现/审计窄过程并在 head 0015 或届时新 head 的全新 disposable 库重跑。不得为了通过 T1 把不可用角色接入根 Compose，也不得新增第二业务数据库。

## 4. 当前与历史验证的精确区分

| 项目 | 状态 |
| --- | --- |
| 历史 live role suite | head 0012，`10/10 passed` |
| 当前 validator/test 静态契约 | 期望 head 0015 |
| 当前 0015 live role suite | **未运行** |
| root Compose 接线 | **未接入** |
| business write path | **不可用** |
| production role switch | **HOLD** |
| 正式数据库 | 0009，未触碰 |

机器可读历史结果与当前裁决见 `roles-validation.json`；`roles-catalog.txt` 不得被解读为 0015 live catalog。
