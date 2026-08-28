# T1-D 回退与数据保护

当前迁移链为 `20260825_0009 → 0010 → 0011 → 0012 → 0013 → 0014 → 0015`。历史 revision 不得修改；任何修复继续新增线性 fix-forward。

## 已实测条件回退

- 0010 foundation：仅 narration 空数据时允许 `0010 → 0009 → 0010`；存在 foundation/TTS 数据即抛出 `T1-D downgrade refused`。
- 0013 asset-scoped paths：`test_asset_scoped_migration.py` 的 preflight、条件 downgrade 与重升 `2/2 passed`。
- 0014 request source sealing：空数据 cycle 可逆；已有或损坏 request source 时 preflight/closure fail-closed，`8/8 passed`。
- 0015 当前作为 head 承载 current-head live suite `56/56 passed`；本证据没有在正式库执行全链 downgrade，也不声称带真实业务数据的 0015→0009 已获批准。

## 正式数据保护规则

1. 正式升级前必须完整备份数据库、配置和相关卷，并记录旧镜像/digest。
2. downgrade 前逐 revision 满足其精确空数据或可逆条件；任一条件不满足即停止。
3. 不得为回退级联删除小说正文、revision、voice rights、Edition、Manifest、render、job attempt、媒体或 tombstone。
4. 优先让旧镜像在保留新 schema 的情况下回退，随后 fix-forward；需要恢复时使用升级前完整备份。
5. `20260825_0009` 自身是 one-way migration，不能自动继续降到 0008。

本轮所有迁移验证均位于 disposable PostgreSQL 18，正式数据库保持 `20260825_0009` 且未触碰。
