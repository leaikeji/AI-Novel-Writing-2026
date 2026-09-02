# L51-RELEASE 长期发布预检与恢复点

状态：**`L51-RELEASE-CANDIDATE=PASS`、`L51-RELEASE-BACKUP=PASS`、`L51-RELEASE=PREFLIGHT_BLOCKED_ROLE_BASELINE`。长期数据库迁移、ACL 写入、候选安装和真实写链均未执行。**

日期：2026-09-02（Asia/Shanghai）

## 1. 本次授权与执行边界

用户已授权优先完成计划 51 的既有发布任务，并明确把百万／五百万字压力矩阵留到计划 51 收口之后。本次因此只串行持有 `LOCK-L51-QWENPAW` 与 `LOCK-L51-PG`，没有启动计划 52，没有使用子代理操作长期环境，也没有暂存、提交或推送。

实际执行到以下安全边界：

1. 只读核验长期 QwenPaw、PawApp、数据库、迁移、运行开关、卷和 Compose 接线；
2. 重新打包并确认候选身份与 W5 已验收候选逐字节一致；
3. 创建并验证数据库、候选、当前安装包、QwenPaw 数据／配置、秘密和小说媒体恢复点；
4. 发现计划 49 已冻结的四角色基线仍不存在后，在任何数据库所有权／ACL 写入、迁移、插件安装或服务重启之前停止。

这不是把“未发布”冒充“已完成”，也不是用当前超级用户连接绕过既有发布门禁。

## 2. 精确候选身份

| 项目 | 事实 |
| --- | --- |
| 插件 | `ai-novel-world-2026@0.4.0` |
| 候选目录 | `build/ai-novel-world-2026` |
| 候选迁移 head | `20260902_0037` |
| 候选树 SHA-256 | `7233b58013118f893a044ae4edc7d44cc9e287e4f8625f18d274b6054d94df37` |
| 候选 bundle SHA-256 | `dd5f913799efe35f2dc4512b894deee587b82d3f310f90751c4c68ea903246bf` |
| 重新打包／dry-run | PASS；候选树、迁移 head 与 W5 证据完全一致 |
| `git diff --check` | PASS |

本次重新打包没有产生另一个候选；Plan 52 只新增文档，不进入 PawApp 包。

## 3. 长期环境事实

| 项目 | 只读事实 |
| --- | --- |
| QwenPaw 容器 | `ai-novel-2026-qwenpaw-lab`，healthy |
| QwenPaw 镜像 ID | `sha256:ea2c0858b94a6522821cceb73593bbea5f02c85fee2f08a8d7386ea90d9f15b1` |
| PostgreSQL 容器 | `ai-novel-2026-postgres`，healthy |
| PostgreSQL 镜像 ID | `sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a` |
| PawApp | `0.4.0`，公开 health=`ready` |
| 长期数据库 head | `20260830_0035` |
| 当前数据库身份 | `ai_novel`；LOGIN + SUPERUSER；同时是数据库所有者 |
| public 表所有权 | 113 张表全部由 `ai_novel` 持有 |
| public schema | owner=`pg_database_owner`，在本库解析为 `ai_novel` |
| 四个冻结角色 | `ai_novel_schema_owner`、`ai_novel_migrator`、`ai_novel_api`、`ai_novel_worker` 均不存在 |
| TTS | runtime=true、product=true；health 显示 sidecar、model、production backend 与 worker ready |
| 当前长期 bundle | `43b329ec9830166d598f50eb75a19cec7ef7cc52b86dbf648a903c3cc480bbcd`，与计划 50 已部署兼容包一致 |
| 当前 plugin.json | `e1b3fd6ec4c7fb5170587e9a1f050bc95feb7070d1716092b24baf34a654b0cc` |
| 当前安装内容清单 | 排除 `__pycache__` 后逐文件 SHA-256 清单再哈希为 `7156701553bf3aef5101847bbd8985b5e7bd1035c2eb9a45ce3ecad5f49d4da3`；共 444 个普通文件 |

当前仓库 `compose.yaml` 没有数据库角色 bootstrap service、schema-owner migrator service或 migrator／API／worker 三个独立 pgpass 卷。`docker/postgres-roles/README.md` 也明确把现有 fragment 标记为“候选部署底座，不是生产 Compose 已接线”。此外，长期 QwenPaw 容器的 Compose label 仍指向一个当前不存在的历史临时编排文件；正式重建必须使用当前已复核的仓库 Compose，不能依赖该失效路径。

## 4. 恢复点

恢复目录：`/Users/liujia/Documents/AI小说世界2026-backups/plan51-release-20260902-110900`

目录权限为 `0700`，全部恢复文件为 `0600`。数据库 dump 已通过 `pg_restore --list`，共 1,110 行目录项；五个 tar 归档均实际完成全量列表读取，不只检查文件存在。

| 文件 | 字节数 | SHA-256 | 可读性证据 |
| --- | ---: | --- | --- |
| `postgresql-0035-before.dump` | 25,801,699 | `cc469547264c48a72f7419730975bdbf00adba2ab85ab7060f86c44876f32fed` | `pg_restore --list` PASS，1,110 行 |
| `candidate-plugin-0037.tar.gz` | 2,183,853 | `4bd0928b34713d0a26dd3c538bd0f728df089909fd85a4bb965bf4c10ada55a7` | tar list PASS，302 项 |
| `installed-plugin-before.tar.gz` | 4,425,518 | `d49b4a4fd7b1ef3ed0102c8948edd77358bf1e662be1900fccaf5efe2657af6d` | tar list PASS，502 项 |
| `qwenpaw-data-before.tar.gz` | 143,526,091 | `aeeadc8061e59173ef4ab9432b391a2217b9fc6c2203a3f567a352d0cbac4fe3` | tar list PASS，3,614 项 |
| `qwenpaw-secrets-before.tar.gz` | 7,492,261 | `4e541fed85efe4ba08fe9473affa97c59fa06fcdea7838eec8ef3919585fbd5a` | tar list PASS，1,687 项 |
| `novel-media-before.tar.gz` | 363,448,864 | `7511ce23aa19074191fd8066ab0604b4ad303ed92cf56ba3c73ca7ef5bcf61a2` | tar list PASS，4,011 项 |

备份全程只读挂载源卷，QwenPaw、PostgreSQL 和 Sidecar 未停止；备份完成后的公开 health 仍为 `ready`。没有删除或改写任何长期卷、小说、revision、媒体或秘密。

恢复动作本身尚未执行，因为当前运行态没有被改变。若后续发布失败：优先通过 QwenPaw 公开安装命令恢复 `installed-plugin-before.tar.gz`；只有 schema／数据也发生变化时，才在服务完全停止、再次确认目标和备份后使用 PostgreSQL dump。全卷归档只用于精确卷级灾难恢复，不得在服务运行时直接覆盖。

## 5. 阻塞判定

计划 49 的长期发布顺序要求：

1. 在 `0035` 上以显式 `--expected-head 20260830_0035` 通过 65 表角色门禁；
2. 在维护窗内以 `ai_novel_migrator SET ROLE ai_novel_schema_owner` 执行迁移；
3. 重新 bootstrap，再以目标 head 验证 67 表所有权、ACL、登录和 raw-DML 负测；
4. 最后才允许安装后端候选并恢复任务领取。

长期环境缺少角色、独立 pgpass、bootstrap service 和 migrator service，因此第 1 步不具备可执行前提。直接使用现有 `ai_novel` 超级用户迁移虽然技术上可能成功，但会绕过已经验收的 owner／ACL 契约，不能视为等价方案。

同时，现有角色底座明确把 API／worker 运行连接切换标记为 `HOLD`：当前没有受审的窄写入过程，API／worker 角色只能只读。建立四角色基线与把正式运行连接切成这些角色是两个不同决策，不能在一次发布中静默合并。

因此当前准确结论是：

- 候选与恢复点可用；
- 长期数据和服务未受影响；
- `L51-RELEASE` 不是代码缺陷阻塞，而是生产数据库身份／凭据／所有权拓扑尚未立项接线；
- 在新增并批准“四角色首次建立与迁移”施工设计前，不执行长期 `0035 → 0037`、ACL 写入或候选安装。

## 6. 下一次获批后的最小施工范围

后续方案至少必须冻结：

1. 三个独立 pgpass named volume、管理员专用临时 passfile、实际 UID/GID 和秘密备份／轮换方式；
2. 首次在 `0035` 建立角色与转移 owner／ACL的顺序、停机窗口和失败恢复点；
3. 只挂 migrator pgpass 的一次性迁移 service，候选必须以不可变摘要进入容器，不能靠主机工作树漂移；
4. `0035` 角色验证 → 停止 QwenPaw／确认无运行中任务 → `0035 → 0037` → 再 bootstrap → `0037` 角色验证 → 安装候选 → 只读验收的唯一顺序；
5. 角色建立后仍由旧超级用户运行的临时风险，及 API／worker 正式切换继续 HOLD 的明确边界；
6. 失败时按“尚无 0036 正式选角记录／已有正式记录”分叉，禁止误删数据或盲目 downgrade；
7. 1080P／2K、原生聊天／设置、账本只读、Plan 50 播放器和旧包回退的发布门禁。

该范围涉及新凭据卷、数据库 owner／ACL 和维护停机，是对当前生产拓扑的实质变更；本次预检不替用户默许。
