# PostgreSQL 运行角色隔离底座

状态：**计划 53 已接入显式 one-shot maintenance overlay，计划 54 已用同一 schema-owner 链完成长期 `0037 → 0038` 并补齐精确 `0038 → 0037` 恢复门禁；它不是普通 Compose 启动项，API／worker 正式连接切换仍为 HOLD。**

`bootstrap.sh` 是可由一次性 Compose service 调用的幂等入口。它只接受无密码连接元数据，管理员密码通过管理员自己的 `PGPASSFILE` 读取；三个运行密码分别只写入下列独立挂载，文件固定为 `0600`：

- `/run/ai-novel-db-auth/migrator/.pgpass`
- `/run/ai-novel-db-auth/api/.pgpass`
- `/run/ai-novel-db-auth/worker/.pgpass`

`compose.maintenance.yaml` 是计划 53 的显式维护 overlay，不会被普通 `docker compose up` 自动加载。它提供 bootstrap、validator、schema-owner migrator 三个 one-shot service，并把三条运行路径绑定到精确命名的 external volume；bootstrap 还会逐条验证父目录本身就是独立 mountpoint，不能用一个总卷下的三个普通子目录冒充隔离。

维护 overlay 独立运行并只连接显式 external 数据库网络，不加载或重建基础 Compose 的任何常驻 service。调用者必须提供已封存的 maintenance-root volume、不可变 QwenPaw image ID、外部 `0700` 管理员 pgpass 目录、精确 expected head、maintenance step 和 migration command／target；任何一项缺失都会在 Compose 解析阶段 fail closed。管理员 passfile 固定为该目录内的 `.pgpass`、模式 `0600`；目录只读挂入 one-shot service，不进入 `.env`、argv、日志或长期 QwenPaw 卷。外部管理员密码可以使用 libpq 的 `\:`／`\\` 转义且不要求采用运行角色的 64 位十六进制格式；三个新生成运行密码仍必须满足该固定格式。

三条路径分别位于 `ai-novel-2026-db-migrator-auth`、`ai-novel-2026-db-api-auth`、`ai-novel-2026-db-worker-auth`。当前 migrator service 只挂 migrator 卷；validator 只读挂三卷；bootstrap 是唯一同时可写挂载三卷的 service。API／worker 卷当前不挂入 QwenPaw，因为运行连接切换尚未批准，也没有受审窄写过程。不能把任一密码复制到 `.env`、数据库 URL、Compose command 或日志。

每次只能使用 `docker compose ... run --rm -T <one-service>` 显式运行一个 service，不得使用 profile-wide `up`。`AI_NOVEL_MAINTENANCE_STEP` 是代码级单步授权：bootstrap 只接受 `bootstrap-20260830_0035`／`bootstrap-20260902_0037`／`bootstrap-20260902_0038`；validator 使用与显式 head 相等的 `validate-<head>`；migrator 只接受 `upgrade-20260902_0038`、`downgrade-20260902_0037` 或历史完整回退 `downgrade-20260830_0035`。不匹配的 service 会在连接数据库前失败。

计划 54 已执行的 `0037 → 0038` 串行顺序：

1. PostgreSQL 健康且 QwenPaw 已停止后，以 `bootstrap-20260902_0037` 和管理员专属 pgpass 启动一次 `bootstrap.sh`；脚本在写凭据卷或改 ACL 前确认实际 head 恰为 `0037`。
2. 以 `validate-20260902_0037`／`--expected-head 20260902_0037` 运行 67 表 validator；未 PASS 不得迁移。
3. 迁移 service 仅挂 migrator pgpass，以 `upgrade-20260902_0038` 调用 `migrate-as-owner.sh upgrade 20260902_0038`。包装器以 `ai_novel_migrator` 登录，再固定 `SET ROLE ai_novel_schema_owner`；迁移专用 search path 是 owner 独占 CREATE 的 `public,pg_catalog`，URL 不含密码。禁止 `head`、相对 revision、零参数默认和其他 Alembic 参数。
4. 以 `bootstrap-20260902_0038` 再次运行 `bootstrap.sh`，把迁移后的对象纳入 owner/ACL/default-ACL 门禁。
5. 以 `validate-20260902_0038`／`--expected-head 20260902_0038` 运行 67 表 validator；只有角色、owner、ACL、实际登录及 raw-DML 负测都通过，才允许安装候选。API／worker 正式连接切换仍保持 HOLD。

若 0038 候选必须回退，先备份、停止 QwenPaw 并确认当前 head 恰为 0038，再使用 `downgrade-20260902_0037` + `migrate-as-owner.sh downgrade 20260902_0037`；随后以 0037 bootstrap／validator 复验并恢复精确旧候选。该动作只用于恢复，不允许形成 0037／0038 双运行轨道。

角色校验只接受以下四个已审计 head，不会从仓库、脚本默认值或数据库自身猜测期望版本：

| 显式 `--expected-head` | 保护表数量 | 用途 |
| --- | ---: | --- |
| `20260829_0034` | 62 | 历史隔离兼容验证 |
| `20260830_0035` | 65 | 计划 53 迁移前历史只读预检 |
| `20260901_0036` | 67 | 整书选角候选兼容验证 |
| `20260902_0037` | 67 | 计划 51 账本候选历史发布验证；只新增索引，不增加保护表 |
| `20260902_0038` | 67 | 当前单一故事账本契约；删除等值列，不增加保护表 |

`protected-tables.sql` 保存当前 `0038` 的 67 表全集；其中 66 张是 ORM 业务表，`alembic_version` 是唯一系统表。`0036`、`0037` 与 `0038` 的保护表集合相等：0037 只增加账本分页索引，0038 只收缩等值列和约束。0034／0035 旧版本集合是该全集的严格子集。SQL 通过 catalog join 只处理目标库中已存在的表；迁移至候选 head 后必须重新执行 bootstrap 并要求对应表集通过。验证器还会拒绝未进入保护清单、也没有非 TTS 理由 allowlist 的 `narration_*`、`voice_*`、`character_*`、媒体和后台任务权威表。

测试环境同样必须显式设置 `TTS_ROLE_TEST_EXPECTED_HEAD`；未设置时 PostgreSQL 集成用例保持跳过，不回退到隐含默认值。此矩阵只扩充读取验证覆盖，不向 API、worker、`PUBLIC` 或任何其他主体授予新权限。

一次性 bootstrap service 至少需要这些环境变量：

```text
PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSFILE
AI_NOVEL_EXPECTED_DATABASE
AI_NOVEL_EXPECTED_ADMIN_ROLE
AI_NOVEL_ROLE_BOOTSTRAP_CONFIRM=<database>:<admin-role>
AI_NOVEL_RUNTIME_PGHOST / AI_NOVEL_RUNTIME_PGPORT
AI_NOVEL_MIGRATOR_UID / AI_NOVEL_MIGRATOR_GID
AI_NOVEL_API_UID / AI_NOVEL_API_GID
AI_NOVEL_WORKER_UID / AI_NOVEL_WORKER_GID
```

`ai_novel_schema_owner` 固定 `NOLOGIN`；只有 `ai_novel_migrator` 具有该角色的 `SET ROLE` membership。管理员预装的 `vector` 扩展及其成员仍是外部对象，owner 只获得完成迁移所需的 type/routine 使用权。API 与 worker 当前都只有读权限、没有任何 raw table DML；`protected-tables.sql` 进一步冻结正文 source/CAS、设置、speaker/casting、音色池、发音、权利/同意、执行、GC、媒体和发布权威表，防止后续误授。所有 public routines 默认不向 `PUBLIC`、API 或 worker 开放执行。

当前没有受审的 enqueue/claim/heartbeat/complete/GC/publish `SECURITY DEFINER` procedures。bootstrap 不伪造这些过程，也不会授予尚不存在的能力。因此正式 API/worker 连接切换仍是 HOLD；后续需要新的、独立审计的过程或等价窄适配器，并为每个过程固定空 `search_path`、全限定对象名和 `REVOKE EXECUTE FROM PUBLIC`。
