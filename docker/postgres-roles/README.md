# PostgreSQL 运行角色隔离底座

状态：**T1-G 候选部署底座；不是生产 Compose 已接线，也不是 worker 业务路径已可用。**

`bootstrap.sh` 是可由一次性 Compose service 调用的幂等入口。它只接受无密码连接元数据，管理员密码通过管理员自己的 `PGPASSFILE` 读取；三个运行密码分别只写入下列独立挂载，文件固定为 `0600`：

- `/run/ai-novel-db-auth/migrator/.pgpass`
- `/run/ai-novel-db-auth/api/.pgpass`
- `/run/ai-novel-db-auth/worker/.pgpass`

`compose.example.yaml` 是供主集成 Owner 串行吸收的 fragment，不会被当前 `compose.yaml` 自动加载。它把三条运行路径声明成三个 named volume；bootstrap 还会逐条验证父目录本身就是独立 mountpoint，不能用一个总卷下的三个普通子目录冒充隔离。

正式接线必须将三条路径分别挂载为三个独立 named volume，且 API 容器只挂 `api`、worker 只挂 `worker`、迁移 service 只挂 `migrator`。bootstrap service 是唯一同时短暂挂载三卷的服务，成功后退出；不能把任一密码复制到 `.env`、数据库 URL、Compose command 或日志。

推荐串行顺序：

1. PostgreSQL 健康后，以管理员专属 pgpass 启动一次 `bootstrap.sh`；显式传入预期数据库、预期管理员及二者组成的确认哨兵。
2. 迁移 service 仅挂 migrator pgpass，调用 `migrate-as-owner.sh upgrade head`。包装器以 `ai_novel_migrator` 登录，再固定 `SET ROLE ai_novel_schema_owner`；迁移专用 search path 是 owner 独占 CREATE 的 `public,pg_catalog`，URL 不含密码。
3. 迁移完成后再次运行 `bootstrap.sh`，把新对象纳入 owner/ACL/default-ACL 门禁。
4. 运行 `scripts/tts/validate_database_roles.py`，并用必填的 `--expected-head` 明确指定目标库版本；只有角色、owner、ACL、实际登录及 raw-DML 负测都通过，才允许考虑切换运行连接。

角色校验只接受以下三个已审计 head，不会从仓库、脚本默认值或数据库自身猜测期望版本：

| 显式 `--expected-head` | 保护表数量 | 用途 |
| --- | ---: | --- |
| `20260829_0034` | 62 | 历史隔离兼容验证 |
| `20260830_0035` | 65 | 当前长期库迁移前只读预检 |
| `20260901_0036` | 67 | 当前候选发布验证 |

`protected-tables.sql` 保存当前 `0036` 的 67 表全集；其中 66 张是 ORM 业务表，`alembic_version` 是唯一系统表。旧版本集合是该全集的严格子集。SQL 通过 catalog join 只处理目标库中已存在的表，但长期 `0035` 在迁移前只运行 65 表只读校验，不提前改 ACL；迁移至 `0036` 后才重新执行 bootstrap 并要求 67 表通过。验证器还会拒绝未进入保护清单、也没有非 TTS 理由 allowlist 的 `narration_*`、`voice_*`、`character_*`、媒体和后台任务权威表。

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
