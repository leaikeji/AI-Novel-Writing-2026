# 开发计划 49：TTS 复查收尾与部署前兼容性加固

状态：**V1.5 源码施工与隔离验收已完成：`TTS49-CODE-FINAL=PASS`、`TTS49-SCHEMA-COMPAT-FINAL=PASS`、`TTS49-RELEASE-READY=PASS`。候选位于 `codex/tts49-compat-hardening` 的未提交工作树；长期迁移、安装、重启、提交和推送仍未授权、未执行。**

日期：2026-09-01（Asia/Shanghai）

## 一、真实基线

### 1. Git 与候选实现

- G0 基线为 `main@84e4858e0a7f87e41dfe2578e6c7e20eeef4f348`，当时与 `origin/main` 一致；实际施工在独立分支 `codex/tts49-compat-hardening` 完成，当前仍以该提交为未提交候选的父提交。
- V1.2 复查开始前工作树干净；当时只有本轮产生的 6 个开发文档/索引改动，尚无 TTS 源码、迁移或运行环境改动。这是施工前的历史基线，不是完成后工作树现状。
- 计划 47 已在 `6748cb3` 提交，并已随当前 `main` 推送；计划 48 与 Docker 编排也已合并。旧版计划中“89 个已跟踪改动、75 个未跟踪文件、计划 48 不得混入”的工作树前提已失效，V1.2 删除该范围。
- 源码唯一 Alembic head 为 `20260901_0036`。
- 候选能力契约为 `narration-capabilities/3`，包含 `character_cast_planning`。
- G0 基线中 `frontend/dist/index.js` 的 SHA-256 为 `aca43711ea092c2f8e7e62d797a3ec9a72a418d53ce43affb84c5514842fa1f0`；最终候选 bundle 身份另记录于计划 49 验收证据，构建产物不作为手工修改源。

### 2. 已通过的候选基线

最近一次合并后验证结果：

- 后端全量：`3469 passed / 167 skipped / 3 warnings`。
- 前端全量：`126 files / 1088 tests passed`。
- TypeScript typecheck、生产构建、插件打包、宿主契约、controller-node、Compose 配置和 `git diff --check` 均通过。

这些结果证明当前候选基线可继续收尾，不代表计划 49 已实施，也不能替代长期部署和真人验收。

### 3. 长期运行态

2026-09-01 的只读核验结果：

- QwenPaw、PostgreSQL 和 MOSS-TTS Sidecar 均为 `healthy`，PawApp health 为 `ready`。
- 长期数据库迁移版本为 `20260830_0035`，不是候选源码的 `0036`。
- 长期 `narration_features` 只公开 `character_voice_matching`、`nano_advanced_tuning`、`private_voice_deletion` 和 `voice_generator`；没有 `character_cast_planning`。
- 因此计划 47 的整书智能配音仍只是已提交候选，尚未长期部署；不得把“容器健康”表述为“计划 47 已上线”。
- 长期库当前有 18 条 `explicit_generation_actor='local-owner'` 的历史生成请求。数量会随业务变化，施工 G0 必须重新只读冻结；不得批量回填或改写。
- 当前还存在其他任务的三个 `anw-ccl-*` 容器：运行中的 `anw-ccl-postgres-20260901`、占用宿主 `18190` 的 `anw-ccl-qwenpaw-20260901`，以及已退出但仍保留的 `anw-ccl-qwenpaw-20260901-stale-cc48`；QwenPaw 项使用与本项目相同的 Compose project label。它们都不是计划 49 的测试资源；G0 必须记录容器 ID、状态、镜像、端口和标签，所有隔离测试使用新的唯一名称，禁止通过 project label、`docker compose down` 或广义 prune 清理它们。

### 4. 仍未完成的计划 45／47 门禁

- `PITCH45-FINAL=HOLD_AUTHOR_LISTENING`：客观保音高探针已通过，作者真实章节听感尚未完成。
- `TTS47-UX-FINAL=HOLD_AUTHOR_LISTENING`。
- `TTS47-CAST-FINAL=HOLD_BROWSER_MODEL_PROVIDER`：缺少真实 `ai-novel-writer` Provider 下的一次成功整书选角浏览器全链。
- `TTS47-EXPR-SPIKE=NOT_RUN`。

计划 49 不得代替或自动通过这些门禁。

## 二、复查发现与优先级

### P1：发布与迁移语义已落后于真实 head

以下生产/发布校验仍锁死 `20260829_0034`：

- `scripts/tts/verify_qwenpaw_plugin_lifecycle.py`
- `scripts/tts/validate_database_roles.py`
- `scripts/tts/chapter_e2e_readiness.py`

`scripts/tts/candidate_migration_identity.py` 当前尚不存在，是本计划拟新增的无执行解析器，不能列作既有缺陷文件。

后果不同，不能用同一种比较方式修复：

- 插件生命周期验证安装的是一个不可变候选目录，因此应在宿主以无执行 AST 方式从候选自身的 `alembic.ini` 与迁移文件解析唯一 head，再在隔离容器内用 Alembic/数据库核对；不能导入候选模块，也不能用运行脚本所在仓库的 head 代替候选身份。
- 数据库角色验证针对调用者明确指定的数据库，`--expected-head` 应改为必填；删除会再次过期的全局默认常量。候选发布流程负责把已解析的候选 head 显式传入，长期部署前后则分别显式传入 `0035` 和 `0036`。
- 章节 E2E readiness 的 `0034` 是最低功能迁移，合法的 `0035`、`0036` 及后续线性后代都应通过；精确相等会把正常升级误判为过期。

当前 `backend/narration/schema_readiness.py` 已正确区分 `0034` 的 TTS 最低版本和 `0036` 的整书选角最低版本，不应把它改成“永远等于仓库 head”。

### P1：候选包校验缺少整树资源上限

当前生命周期校验会遍历并哈希候选目录中的全部普通文件，但只做链接/文件类型约束，没有候选整树条目数、文件数、单文件大小和总字节数上限。迁移 AST 解析器自身的窄上限不能代替整个候选包的资源边界；恶意或损坏候选仍可能在枚举或 hash 阶段耗尽时间、内存或磁盘读取预算。V1.5 将整树限制冻结为最多 8192 个文件系统条目、其中最多 4096 个普通文件、单文件 64 MiB、总计 512 MiB，任何一项超限均在复制、安装和容器启动前 fail closed。

### P1：当前 schema PostgreSQL 测试重复锁死版本

以下六个“在当前完整 schema 上运行”的模块各自复制了 head 常量：

- `test_script_review_backend_postgres.py`：`0034`
- `test_script_review_postgres.py`：`0034`
- `test_nano_experiments_postgres.py`：`0034`
- `test_failed_segment_retry_postgres.py`：`0034`
- `test_voice_generator_postgres.py`：`0036`
- `test_official_voice_selection_contract.py`：`0034`

它们应共用唯一测试帮助器解析仓库唯一 head。现有已经正确动态解析 head 的 publication/media 测试本轮不做机械搬迁，避免把一个发布阻断扩张为全测试基础设施重构。以下历史阶段测试不得动态化：

- `test_settings_postgres.py` 固定 `0015`。
- `test_script_postgres.py` 固定 `0016`。
- `test_domain_concurrency_postgres.py` 固定 `0015`。
- `test_migrations.py` 与 `test_voice_product_schema_postgres.py` 中验证具体迁移关系的历史断言继续明确写出 revision。

### P1：数据库角色权威表清单未覆盖后续 TTS 表

`validate_database_roles.py` 与 `docker/postgres-roles/protected-tables.sql` 目前相互一致，但只包含 55 张旧表。后续已经进入 ORM/迁移的以下 TTS 权威表未进入显式保护清单：

- `nano_voice_experiment_commands`
- `narration_script_review_actions`
- `voice_action_commands`
- `voice_action_receipts`
- `voice_deletion_asset_plans`
- `voice_design_drafts`
- `voice_generator_commands`
- `voice_generator_run_evidence`
- `voice_previews`
- `voice_reference_asset_links`
- `character_cast_plan_commands`
- `character_cast_plan_items`

现有全 public schema DML 扫描仍提供广义防线，但显式权威表的存在性、SELECT 与角色契约不完整，发布前必须同步脚本、SQL 和测试。

按迁移归属复核后，显式清单应当版本化为：`0034=62`（现有 55 加 7）、`0035=65`（再加 VoiceGenerator 3 表）、`0036=67`（再加整书选角 2 表）。当前 Python/SQL 发布清单只代表最新 `0036` 的 67 表；旧 head 兼容验证必须选择经审计的对应集合，不能拿 67 表存在性去校验尚未创建整书选角表的 `0035`。

### P2：作者界面仍显示协议枚举

`script-review-panel.ts` 仍直接渲染 `segment.confidence`，会显示 `high / medium / low / unknown`。这只是显示层问题，协议和数据库值无需改变。

### P2：Edition 聚合读取边界证据不完整

`chapter-narration-session.ts` 已实现最大次数、超时、`AbortController` 和只对可识别投影偏差重试。已有“短暂偏差后收敛”和 scope 错误用例，但缺少：

- 达到最大次数仍不收敛；
- 达到超时；
- backoff 期间 dispose；
- 新 load 取代旧 load；
- 失败路径不发布 Edition、不安装 bundle、不创建播放器。

本项必须测试优先。只有回归证明生产实现有缺陷时，才允许最小修改生产代码。

### P2：历史 actor 缺完整 HTTP 成功链

现有 HTTP 用例已覆盖 `PATCH → approve → request GET → Edition GET`，但使用新 actor `owner`。底层兼容和持久封印已有局部证据，仍缺一条 `explicit_generation_actor='local-owner'` 的完整历史请求回归。

`local-owner` 在官方音色选择等其他子系统仍是合法值；不得做全仓字符串替换，也不得把 actor 收窄为二值枚举。

### 已在本次复查修正：文档状态

复查时计划 45、计划 47 和计划 47 证据仍写“Git 提交和推送未执行”，与当前 `main` 不符。本次 V1.2 文档复查已经保留原验收事实并补记已提交/推送、长期未部署、真人/真模型门禁仍未通过；源码施工后只需再次核对是否有新状态变化。

## 三、迁移判断的四种语义与角色矩阵

本计划冻结四种不可混用的判断：

| 场景 | 正确语义 | 例子 |
| --- | --- | --- |
| 候选包完整性 | 宿主只用 AST 静态读取候选迁移字面量，候选图必须完整、唯一、线性；隔离安装库精确等于该 head | 插件生命周期 |
| 仓库当前 schema 测试 | 当前仓库必须只有一个线性 head；已升级的隔离测试库精确等于仓库 head | 六个当前 schema PG 测试 |
| 功能最低版本 | 最低 revision 必须位于数据库当前 revision 的线性祖先链 | 章节 E2E 对 `0034` 的要求 |
| 历史迁移证据 | 保持固定 revision，验证升级链和历史阶段行为 | `0015`、`0016`、`0034 → 0035 → 0036` |

禁止用字符串大小比较 revision。可信源码仓库和功能最低版本使用 Alembic `ScriptDirectory`；尚未安装的候选目录只能用无执行的 AST 静态解析器，禁止在宿主 dry-run 中导入候选迁移模块。候选图必须从固定规范 base `20260823_0001` 完整连到唯一 head；“只有一个 base”但 base 被截断或替换同样拒绝。候选目录与源码仓库不得互相冒充迁移身份；多 head、未知 revision、不完整或非线性分叉一律 fail closed。

数据库角色兼容采用显式矩阵，不跟随“最新 head”猜测：

| 精确数据库 head | 受支持状态 | Python 保护表集合 | 用途 |
| --- | --- | --- | --- |
| `20260829_0034` | 支持隔离兼容验证 | 62 张 | Nano 高级调音与私人音色生命周期完成后的历史兼容 |
| `20260830_0035` | 支持长期部署前只读预检 | 65 张 | 当前长期库与 VoiceGenerator schema |
| `20260901_0036` | 支持候选发布 | 67 张 | 当前候选与整书智能配音 |
| 其他、缺失、多 head、格式不合法 | 拒绝 | 无 | fail closed |

`validate_database_roles.py` 必须先以 `^[0-9]{8}_[0-9]{4}$` 校验调用者显式传入的 head，再从不可变映射选择集合；不接受任意 revision 或默认值。`CURRENT_PROTECTED_TABLES` 固定为 67 张，并与 `protected-tables.sql` 完全相等；62/65 张旧集合是它的经审计严格子集，只用于相应数据库版本的兼容验证，不是另两份生产 SQL 文件。SQL 通过 catalog join 只作用于目标库实际存在的表，因此隔离矩阵和回退 A 可在 0034/0035 使用同一超集；正常长期发布在迁移前仍只运行 65 表只读校验，迁移到 `0036` 后才首次写入当前 bootstrap 并要求 67 表校验通过。迁移前如 65 表角色校验失败，停止发布，不以“迁移后会修复”为理由继续。

## 四、目标与完成口径

### 1. `TTS49-CODE-FINAL`

- 四种置信度只显示稳定中文标签，协议值不变。
- Edition 聚合加载的次数、超时、取消、取代和不可重试错误均有 fail-closed 回归。
- 历史 `local-owner` 请求能完成当前 HTTP 复核、冻结和 Edition 成功链；幂等与审计封印不被绕开。
- 未经测试证明，不改现有已通过的声音配置器、选角、播放器或生产重试逻辑。

### 2. `TTS49-SCHEMA-COMPAT-FINAL`

- 四类迁移判断各用正确语义。
- 六个当前 schema PostgreSQL 模块共用唯一 head 帮助器，不再复制版本数字。
- 生命周期、角色和章节 readiness 对 `0034/0035/0036` 的接受与拒绝符合冻结矩阵。
- 角色验证对 `0034/0035/0036` 分别使用 62/65/67 张经审计集合；当前 67 张显式保护表（现有 55 张加本轮 12 张）在 Python 与 SQL 中完全一致，缺表、重复、漏权限或 raw DML 都 fail closed。
- 不新增迁移，不改写 ORM、已执行迁移或业务数据。

### 3. `TTS49-RELEASE-READY`

- 定向、隔离 PostgreSQL、全量、打包、宿主契约、生命周期、数据库角色、Compose、浏览器和 diff 门禁全部通过。
- 生成候选/长期差异报告，明确 `0036` 与长期 `0035` 的差异及部署顺序。
- 文档状态与 Git/长期事实一致。

`RELEASE-READY` 只表示候选具备另行授权部署的条件，不表示已经部署，也不通过计划 45／47 的真人门禁。

## 五、冻结修复方案

### 1. 置信度本地化

显示层使用唯一穷尽映射：

| 协议值 | 作者界面 |
| --- | --- |
| `high` | `高` |
| `medium` | `中` |
| `low` | `低` |
| `unknown` | `未知` |

统一显示为“置信度：高”等文案；不复制 DTO，不把中文写回 API 或数据库。

### 2. Edition 重试边界

使用可注入时钟和 delay，不做真实 sleep：

1. 可识别短暂偏差在限额内收敛，只构建一次播放运行时。
2. 达到 `maxPollAttempts` 时请求数等于上限并返回稳定错误。
3. 达到 `pollTimeoutMs` 时有界失败，不留后台请求。
4. dispose 或新 load 在 delay 期间发生时，旧 load 以取消语义退出。
5. scope、revision、manifest 或身份不匹配首次立即失败，重试与 delay 均为零。
6. 所有失败路径均不向 bridge 发布 Edition、不安装 bundle、不创建播放器。

### 3. 旧 actor 兼容

隔离回归覆盖：

1. 构造历史 `local-owner` 的 `review_required` 请求，通过当前 HTTP `PATCH → approve → request GET → Edition GET` 完成修正、冻结和 Edition 创建。
2. 相同幂等键重放不改 actor，不重复创建脚本子版本、动作或 Edition。
3. 新 `owner` 请求仅在源脚本已批准、段落哈希、前后锚点、说话人目标、workspace 和审计证据完全一致时继承人工修正。
4. SQL 修改已持久化 actor 被现有封印 trigger 拒绝。
5. action/provenance actor 不一致或任一 scope 漂移时拒绝继承并零 Edition 写入。

### 4. 可信仓库与候选包分离解析

对可信源码仓库，不在发布脚本和测试中复制 Alembic 遍历：

- 在 `backend/narration/schema_readiness.py` 暴露无路径参数的只读 `repository_unique_head() -> str | None`，内部只能使用本仓库既有规范化 `ALEMBIC_CONFIG_PATH`，复用现有 fail-closed 线性祖先链实现。调用者不得把候选目录或任意配置路径传给可信仓库解析器。
- 零 head、多 head、未知父 revision、循环、非字符串 `down_revision` 或解析异常均返回未就绪；不调用 `upgrade()` / `downgrade()`，也不连接数据库。
- 现有 `NARRATION_FEATURE_MINIMUM_DATABASE_REVISION`、`VOICE_GENERATOR_MINIMUM_DATABASE_REVISION`、`CHARACTER_CAST_MINIMUM_DATABASE_REVISION` 和三项 readiness 行为保持不变。
- 新增 `tests/narration/current_schema_gate.py`，只封装“仓库唯一 head＋隔离库精确相等”的测试断言。

对尚未安装的候选包，新建 `scripts/tts/candidate_migration_identity.py`：

- 只遍历候选根下 `backend/migrations/versions/*.py` 的普通非符号链接文件；最多 512 个文件、单文件最多 1 MiB、合计最多 16 MiB，超限即拒绝。
- 使用禁用插值的 `configparser.RawConfigParser` 证明候选 `alembic.ini` 的 `script_location` 精确为 `backend/migrations`，并要求 `version_locations` / `recursive_version_locations` / `sourceless` 不存在或保持默认关闭；不接受绝对路径、变量替换或 `..`。
- 使用 `ast.parse` 与 `ast.literal_eval` 从 `Assign` / `AnnAssign` 读取唯一的 `revision`、`down_revision`、`branch_labels` 和 `depends_on`；绝不 import、exec、调用候选代码或编译为可执行字节码。
- 当前项目只接受匹配 `^[0-9]{8}_[0-9]{4}$` 且与文件名前缀一致的 `revision: str`、`down_revision: str | None`、`branch_labels=None`、`depends_on=None`；图必须从固定规范 base `20260823_0001` 连续到唯一 head。tuple/list 分支、重复 revision、缺父节点、截断/替换 base、多 base、多 head、环、路径逃逸或解析异常均 fail closed。
- 生命周期在候选 tree hash 形成前后使用同一规范化目录；复制进隔离容器后，再由容器内 Alembic 与迁移后数据库 head 交叉验证 AST 结果。
- 生命周期在调用迁移解析器前，对宿主候选整树实施最多 8192 个文件系统条目、其中最多 4096 个普通文件、单文件 64 MiB、合计 512 MiB 的上限；目录遍历不跟随链接，文件以 no-follow descriptor 打开，SHA-256 使用固定大小分块流式读取，不再 `read_bytes()` 整文件，并在打开前/读取后比对普通文件类型、device、inode、link count、size 与 mtime。符号链接、硬链接、特殊文件、读取中身份/大小漂移或超限全部拒绝。复制后的容器内 tree hash 使用同一四项上限、分块算法和路径排序，并与宿主 hash 精确相等后才继续。迁移解析器继续使用更严格的 512 文件、1 MiB/文件、16 MiB 合计上限。
- 单元测试放置带顶层写文件/抛异常语句的迁移 fixture，断言宿主解析不产生副作用；连续解析两个不同候选时结果不得串用；另覆盖截断 base、替换 base、候选整树三个资源上限及校验期间文件漂移。

六个当前 schema 模块共用可信仓库帮助器；历史阶段测试和已经正确工作的其他 PG 模块保持原样。

### 5. 发布脚本

- 生命周期脚本在 `validate_candidate()` 阶段调用无执行 AST 解析器得到候选唯一 head，将其存入不可变 GateConfig；dry-run 计划、容器内 `alembic heads`、迁移后数据库精确校验和证据全部使用同一值。候选缺迁移、图不完整、复制后 tree hash 漂移或任一结果不一致时 fail closed。
- 数据库角色脚本删除 `EXPECTED_HEAD` 默认常量；CLI `--expected-head` 和测试环境 `TTS_ROLE_TEST_EXPECTED_HEAD` 均改为必填。输入先通过 revision 格式和 0034/0035/0036 支持矩阵校验，再选择 62/65/67 表集合。报告继续同时记录实际和预期身份，不根据仓库状态猜测目标数据库应该处于哪个版本。
- 章节 E2E readiness 将常量改名为最低 revision，并直接复用 `database_revision_satisfies(...)`；`0033`、未知 head、多 head 和分叉继续拒绝。

### 6. 数据库角色清单

- Python 定义 `PROTECTED_TABLES_BY_HEAD`：0034 为 62 张、0035 为 65 张、0036 为 67 张；三个集合均显式、排序、唯一，后者严格包含前者。
- `CURRENT_PROTECTED_TABLES` 指向 0036 的 67 张；SQL 临时表只维护该当前全集并与其完全相等。SQL 对缺失的未来表不发出语句，可用于隔离兼容 fixture 和回退 A；正常长期 0035 迁移前不改 ACL，只用 65 表集合只读验证，迁移至 0036 后才执行 bootstrap。
- 该集合是人工审计后的显式安全清单，禁止直接从 ORM 动态生成授权；新表必须经过独立审查后才能加入。
- ORM metadata 当前有 114 张表。测试必须证明 `CURRENT_PROTECTED_TABLES - {'alembic_version'}` 的 66 张业务表全部存在于 ORM，且 `alembic_version` 是唯一允许不在 ORM 中的系统表；隔离数据库还要证明每个版本对应的全部目标表真实存在。
- 对 `narration_`、`voice_`、`nano_`、`character_cast_` 当前权威表执行“未分类表”负向审计；Python 当前全集与 SQL 必须同步，旧集合不得误含后续迁移表。
- API/worker 对受保护表的 raw INSERT/UPDATE/DELETE 继续被拒绝；所需 SELECT 只按现有角色契约开放，不扩大 public 或匿名权限。

### 7. 文档同步

- 本次复查已为计划 45、计划 47及计划 47 证据补记提交/推送事实。
- 明确保留长期未部署、作者听检未完成、真实 Provider 成功链未完成。
- 两个文档索引已更新为计划 49 V1.5 和候选/长期迁移差异；施工完成后按实际裁决再次同步。

## 六、文件边界

### 允许修改

- `frontend/src/narration/script-review-panel.ts`
- `frontend/src/narration/script-review-panel.test.ts`
- `frontend/src/narration/styles/t4-chapter.ts`：真实浏览器暴露脚本复核窄容器两列挤压后追加的最小响应式修复；移动端不计入用户最终指定的浏览器矩阵。
- `frontend/src/narration/chapter-narration-session.test.ts`
- `frontend/src/narration/chapter-narration-session.ts`：仅测试证明缺陷时。
- `scripts/tts/candidate_migration_identity.py`：新增文件。
- `scripts/tts/verify_qwenpaw_plugin_lifecycle.py`
- `scripts/tts/validate_database_roles.py`
- `scripts/tts/chapter_e2e_readiness.py`
- `backend/narration/schema_readiness.py`：只允许增加/复用只读迁移图帮助器，不改变三项能力最低版本或 schema sentinel。
- `docker/postgres-roles/protected-tables.sql`
- `docker/postgres-roles/README.md`
- `tests/narration/current_schema_gate.py`
- `tests/narration/test_script_review_backend_postgres.py`
- `tests/narration/test_script_review_postgres.py`
- `tests/narration/test_nano_experiments_postgres.py`
- `tests/narration/test_failed_segment_retry_postgres.py`
- `tests/narration/test_voice_generator_postgres.py`
- `tests/narration/test_official_voice_selection_contract.py`
- `tests/narration/test_schema_readiness.py`
- `tests/narration/test_candidate_migration_identity.py`
- `tests/narration/test_qwenpaw_plugin_lifecycle_runner.py`
- `tests/narration/test_database_roles.py`
- `tests/narration/test_chapter_e2e_readiness.py`
- `tests/narration/test_script_review_http_continue.py`
- `tests/narration/test_script_review_actions.py`
- `tests/narration/test_script_backend.py`
- `tests/narration/test_migrations.py`：仅允许增加 actor 封印回归，不得动态化或改写历史 revision 断言。
- 计划 45、47、49、计划 47/49 证据及两个文档索引。

### 禁止触碰

- `backend/models.py`、`backend/migrations/**`、公共 API/DTO、capabilities 契约。
- `backend/narration/schema_readiness.py` 中既有最低 migration 常量、表/列/trigger/function sentinel 及 readiness 结果语义。
- VoiceGenerator、Nano Sidecar、选角求解、私人音色删除、媒体和真实小说。
- QwenPaw 上游核心、长期数据库写入、长期安装/重启和数据卷。

如回归要求越过禁止范围，应停止扩张并形成新裁决，不以计划 49 顺带修改。

## 七、施工波次与子代理并行设计

本轮只复查并修订计划，不启动子代理。若用户批准施工，以下互不重叠工作包可并行；共享契约、迁移语义、长期环境和最终集成保持串行。

| 波次 | 工作包 | 标记 | 唯一目标与文件所有权 |
| --- | --- | --- | --- |
| W0 | `TTS49-G0` | `GATE/SER/MUTEX` | 主代理重冻结 Git、仓库 head、候选包 head、长期 revision/health、bundle、Node/pnpm 路径、历史 actor 计数和全部既有 `anw-ccl-*` 容器身份；任何前提变化先修订计划。 |
| W0 | `TTS49-C0` | `GATE/SER` | 主代理冻结四种迁移语义、候选 GateConfig 字段、67 表显式集合、重试失败合同和 HTTP actor fixture。 |
| W1 | `TTS49-MIG-CORE` | `MUTEX/SER` | 主代理唯一修改 `schema_readiness.py`、`current_schema_gate.py` 与 schema readiness 测试，冻结无路径参数的可信仓库 `repository_unique_head()`；其他工作包只消费接口。 |
| W2 | `TTS49-FE-I18N` | `PAR-C/MUTEX` | 只改 `script-review-panel` 源码与测试。 |
| W2 | `TTS49-EDITION-QA` | `PAR-C/MUTEX` | 先改 chapter session 测试；只有红测证明时最小改对应生产文件。 |
| W2 | `TTS49-CURRENT-PG` | `PAR-C/MUTEX` | 只改 Nano 实验、失败段落重试、VoiceGenerator、官方音色契约四个当前 schema PG 模块；不得触碰两个脚本复核 PG 文件。 |
| W2 | `TTS49-LIFECYCLE` | `PAR-C/MUTEX` | 独占候选 AST 解析器、生命周期脚本及两者测试，使候选自身 head 成为唯一身份且宿主 dry-run 不执行候选代码。 |
| W2 | `TTS49-READINESS` | `PAR-C` | 只改章节 E2E readiness 与测试，复用最低版本祖先判断。 |
| W2 | `TTS49-ROLE-ACL` | `PAR-C/MUTEX` | 只改角色验证脚本、保护表 SQL、角色 README 与测试；`--expected-head` 必填。 |
| W2 | `TTS49-LEGACY-ACTOR` | `PAR-C/MUTEX` | 独占两个脚本复核 PG 模块，并修改旧 actor 的 HTTP/幂等/继承/封印测试；同时消费 current-schema 帮助器，默认不改生产服务。 |
| W3 | `TTS49-INT` | `INT/SER/MUTEX` | 主代理汇合 diff，检查候选/仓库 head 不串用、角色最小权限和重复常量，删除被替代的默认版本常量。 |
| W4 | `TTS49-QA-DOC` | `GATE/SER/MUTEX` | 串行执行隔离 PG/角色/生命周期、全量、浏览器并同步计划 45/47/49、证据和索引，防止并行覆盖状态。 |
| W5 | `TTS49-RELEASE-AUDIT` | `GATE/SER` | 生成候选与长期差异、部署前置和恢复证据，不操作长期环境。 |
| W6 | `TTS49-FINAL` | `INT/GATE/SER` | 分别裁决 CODE、SCHEMA-COMPAT、RELEASE-READY；不代替计划 45/47 门禁。 |

共享锁：`LOCK-MIGRATION-GRAPH`、`LOCK-SCRIPT-REVIEW-FE`、`LOCK-CHAPTER-SESSION`、`LOCK-NARRATION-REQUESTS`、`LOCK-POSTGRES-TEST`、`LOCK-POSTGRES-ROLES`、`LOCK-PLUGIN-LIFECYCLE`、`LOCK-DOC-INDEX`、`LOCK-GIT`、`LOCK-QWENPAW`。

### 可派发工作包合同

| 工作包 | 精确可写文件 | 必须运行/返回 | 独占锁与禁止事项 |
| --- | --- | --- | --- |
| `TTS49-MIG-CORE` | `backend/narration/schema_readiness.py`、`tests/narration/current_schema_gate.py`、`tests/narration/test_schema_readiness.py` | 三文件定向 pytest；返回唯一 head、固定 base、零/多 head 和祖先判断证据 | `LOCK-MIGRATION-GRAPH`；不得接受外部路径、不得改最低版本或 sentinel |
| `TTS49-FE-I18N` | `frontend/src/narration/script-review-panel.ts`、`frontend/src/narration/script-review-panel.test.ts` | 对应 Vitest；返回四枚举和窄屏 DOM 证据 | `LOCK-SCRIPT-REVIEW-FE`；不得改 DTO/API |
| `TTS49-EDITION-QA` | `frontend/src/narration/chapter-narration-session.test.ts`；红测证明后才可改 `frontend/src/narration/chapter-narration-session.ts` | 对应 Vitest；返回请求次数、虚拟时钟、取消和零副作用断言 | `LOCK-CHAPTER-SESSION`；不得顺带重写播放器 |
| `TTS49-CURRENT-PG` | `tests/narration/test_nano_experiments_postgres.py`、`tests/narration/test_failed_segment_retry_postgres.py`、`tests/narration/test_voice_generator_postgres.py`、`tests/narration/test_official_voice_selection_contract.py` | 四模块 pytest；无隔离 URL 时记录预期 skip，真实 PG 断言统一在 W4 运行 | `LOCK-MIGRATION-GRAPH`；不得改共享 helper 或两个 script-review PG 模块 |
| `TTS49-LIFECYCLE` | `scripts/tts/candidate_migration_identity.py`、`scripts/tts/verify_qwenpaw_plugin_lifecycle.py`、`tests/narration/test_candidate_migration_identity.py`、`tests/narration/test_qwenpaw_plugin_lifecycle_runner.py` | 两测试模块；返回无执行 fixture、固定 base、整树资源上限、tree hash 漂移和双候选不串包证据 | `LOCK-PLUGIN-LIFECYCLE`；不得调用真实安装/容器 |
| `TTS49-READINESS` | `scripts/tts/chapter_e2e_readiness.py`、`tests/narration/test_chapter_e2e_readiness.py` | 对应 pytest；返回 0033 拒绝、0034/35/36 接受和未知/分叉拒绝证据 | `LOCK-MIGRATION-GRAPH`；不得复制字符串大小比较 |
| `TTS49-ROLE-ACL` | `scripts/tts/validate_database_roles.py`、`docker/postgres-roles/protected-tables.sql`、`docker/postgres-roles/README.md`、`tests/narration/test_database_roles.py` | 对应 pytest；返回 62/65/67 集合、Python/SQL 当前全集一致、ORM 66+系统表 1 和非法 head 证据 | `LOCK-POSTGRES-ROLES`；不得操作长期角色或扩大 public 权限 |
| `TTS49-LEGACY-ACTOR` | `tests/narration/test_script_review_backend_postgres.py`、`tests/narration/test_script_review_postgres.py`、`tests/narration/test_script_review_http_continue.py`、`tests/narration/test_script_review_actions.py`、`tests/narration/test_script_backend.py`、`tests/narration/test_migrations.py` | 六模块 pytest；无隔离 URL 时记录预期 skip，W4 补真实 PG；返回 HTTP 成功链、幂等、继承与 trigger 封印证据 | `LOCK-NARRATION-REQUESTS`；`test_migrations.py` 不得更改历史 head/链断言，生产默认只读 |

W2 工作包可并行编辑，但任何真实 PostgreSQL 测试统一在 W4 由主代理持有 `LOCK-POSTGRES-TEST` 串行运行；子代理不得各自创建或清理 Compose 项目。每个返回必须附 `git diff --check`、实际命令、通过/跳过/失败数量和未验证项，不能用“看起来正确”代替证据。

汇合顺序：G0/C0 → MIG-CORE → W2 独立工作包 → INT → 隔离数据库/生命周期/全量/浏览器与文档 → 发布审计 → FINAL。

子代理不得暂存、提交、推送、操作长期数据库、安装或重启 PawApp、删除媒体或修改未分配文件；主代理是唯一集成责任人。

## 八、测试与证据

### 1. 定向测试

G0 必须通过工作区依赖定位解析并记录两个绝对可执行文件，分别放入任务专用变量 `TTS49_PNPM_BIN` 和 `TTS49_NODE_BIN`，并以 `test -x` 校验；同时校验工作树中的 `node_modules/vitest/vitest.mjs`、`node_modules/typescript/bin/tsc` 和 `node_modules/vite/bin/vite.js`。实测仅调用绝对 pnpm 仍会因其脚本子进程找不到裸 `node` 而失败，因此测试、类型检查和构建一律由绝对 Node 直接执行固定 CLI 入口；不得修改 `PATH`、假定裸 `node` 存在或依赖 `pnpm exec node`。变量只保存可执行文件路径，不写入仓库。

```text
"$TTS49_NODE_BIN" node_modules/vitest/vitest.mjs run \
  frontend/src/narration/script-review-panel.test.ts \
  frontend/src/narration/chapter-narration-session.test.ts

.venv/bin/python -m pytest \
  tests/narration/test_schema_readiness.py \
  tests/narration/test_candidate_migration_identity.py \
  tests/narration/test_qwenpaw_plugin_lifecycle_runner.py \
  tests/narration/test_database_roles.py \
  tests/narration/test_chapter_e2e_readiness.py \
  tests/narration/test_script_review_http_continue.py \
  tests/narration/test_script_review_actions.py \
  tests/narration/test_script_backend.py \
  tests/narration/test_migrations.py
```

### 2. 隔离 PostgreSQL

- 使用一次性 PostgreSQL 18 容器、独立网络和独立卷；不得指向长期 `15432` 数据库。
- 显式设置并预检 `TTS_TEST_DATABASE_URL`，升级到仓库唯一 head 后运行六个当前 schema 模块：两个脚本复核模块、Nano 实验、失败段落重试、VoiceGenerator 和官方音色契约。
- 覆盖 `0034 → 0035 → 0036` 的最低版本接受矩阵，以及 `0033`、未知 revision、多 head/非线性链拒绝。
- 使用隔离角色验证环境分别停在 0034、0035、0036，按 62、65、67 表集合执行存在性、SELECT 与 raw DML 拒绝矩阵；证明旧集合不要求未来表、当前 67 集合与 SQL 精确一致。
- 生命周期额外构造“仓库 head 与候选 head 不同”“连续解析两个不同候选”和“候选迁移含顶层副作用语句”的负向 fixture，证明脚本以候选为准、结果不串包且宿主无代码执行；再执行插件安装、原位升级、卸载和旧镜像/旧包回退的隔离生命周期。不得替换唯一长期容器。

### 3. 全量门禁

```text
env \
  -u AI_NOVEL_DATABASE_URL \
  -u AI_NOVEL_TEST_DATABASE_URL \
  -u TTS_ASSET_MIGRATION_DATABASE_URL \
  -u TTS_T1G_TEST_DATABASE_URL \
  -u TTS_TEST_DATABASE_URL \
  -u TTS_VOICE_DELETION_TEST_DATABASE_URL \
  -u TTS_ROLE_TEST_HOST \
  -u TTS_ROLE_TEST_PORT \
  -u TTS_ROLE_TEST_DATABASE \
  -u TTS_ROLE_TEST_ADMIN_ROLE \
  -u TTS_ROLE_TEST_ADMIN_PGPASS \
  -u TTS_ROLE_TEST_MIGRATOR_PGPASS \
  -u TTS_ROLE_TEST_API_PGPASS \
  -u TTS_ROLE_TEST_WORKER_PGPASS \
  -u TTS_ROLE_TEST_EXPECTED_HEAD \
  -u TTS_REAL_NANO_TOKEN_FILE \
  .venv/bin/python -m pytest
"$TTS49_NODE_BIN" node_modules/vitest/vitest.mjs run
"$TTS49_NODE_BIN" node_modules/typescript/bin/tsc --noEmit
"$TTS49_NODE_BIN" node_modules/vite/bin/vite.js build
.venv/bin/python scripts/package_plugin.py
.venv/bin/python -m pytest \
  tests/test_manifest.py \
  tests/test_skill_contract.py \
  tests/test_qwenpaw_integration_contract.py
"$TTS49_NODE_BIN" --test scripts/tts/controller-node/test/*.test.mjs
docker compose config --quiet
git diff --check
```

全量 pytest 必须在上述净化环境中运行；开始前以只显示变量名、不显示值的预检证明这些变量均未传入子进程，尤其不能因遗留 `TTS_REAL_NANO_TOKEN_FILE` 意外启动真实模型。隔离 PostgreSQL、角色和生命周期门禁另起命令，只注入该门禁需要的精确变量，并先证明目标不是长期 `15432` 数据库、正式容器或任何既有 `anw-ccl-*` 容器。

### 4. 浏览器与证据

用户在浏览器复验过程中补充裁决：本轮正式浏览器矩阵只保留 `1920×1080` 与 `2560×1440`，不再把移动端纳入本轮门禁。隔离环境需要证明：

- 两种桌面视口下四种协议值均不泄露英文枚举。
- 两档桌面视口下的焦点、滚动、操作区和布局不回归。
- 控制台无本轮新增 error/warning。

新增证据目录：

- `docs/开发文档/证据/计划49/README.md`
- `docs/开发文档/证据/计划49/TTS49-SCHEMA-COMPAT.md`
- `docs/开发文档/证据/计划49/TTS49-RELEASE-READINESS.md`

证据必须分开记录自动化、隔离数据库、生命周期、角色、浏览器、未执行项和计划 45/47 保留门禁。

## 九、部署前置与恢复

计划文本不授权长期部署。只有 `TTS49-RELEASE-READY=PASS` 且用户另行授权后，才能按以下串行顺序执行：

1. 从不可变候选包解析并记录唯一 head，冻结长期镜像 digest、插件包/bundle hash、数据库 `0035`、媒体清单、只读 health 和全部既有 `anw-ccl-*` 容器身份；备份数据库。
2. 在隔离环境证明候选包 `0035 → 0036`、67 表角色 bootstrap、安装、卸载，以及“0036 尚无选角记录时降回 0035”的回退分支；所有步骤使用同一个候选 hash/head。
3. 以显式 `--expected-head 20260830_0035` 对长期库执行 65 表只读角色预检。任何缺表、owner、SELECT 或 raw DML 异常都在维护窗前阻断发布，不提前写 ACL。
4. 取得 `LOCK-QWENPAW` 与 `LOCK-POSTGRES-ROLES`，进入短维护窗并先撤销所有 narration 新任务领取；不在作者请求运行时切换 schema/包。
5. 使用候选迁移以 schema owner 身份执行 `0035 → 0036`，随后重新应用 PostgreSQL 角色 bootstrap，并用显式 `--expected-head 20260901_0036` 验证 67 表 ACL。迁移或 ACL 未通过时继续保持任务领取关闭。
6. 安装同一候选包并重启；只读核验 health、`narration-capabilities/3`、`character_cast_planning` 和页面入口，不在真实小说创建选角命令。全部通过后才恢复任务领取。

回退分为两个真实可执行分支，不能笼统写成“关闭新能力并回退兼容包”：

- **A：0036 尚无 `character_cast_plan_commands/items` 正式记录。** 保持任务领取关闭，运行迁移自带 downgrade guard；只有 guard 与独立计数都证明零记录时才降到 0035，恢复冻结的旧包，重新执行经审计 bootstrap（67 表超集只命中实际存在的 65 表），再以显式 0035/65 集合验证 health/ACL 后恢复旧功能。该分支必须在隔离发布演练中通过。
- **B：0036 已存在任一正式选角记录。** 禁止降 schema，也不得假定当前代码已有单独关闭 `character_cast_planning` 的运行开关。立即撤销全部 narration readiness 与任务领取，保留 0036 数据和媒体，进入 `HOLD_0036_COMPAT_PATCH`；只有另行实现并验收能理解 0036 且隐藏/关闭整书选角的兼容补丁后才能恢复其他 TTS 功能。数据库损坏或权限异常才按已验证备份恢复，不以删除选角记录换取降级。

长期仍为 `0035` 时，不得安装依赖 `0036` 的候选前端/后端并声称降级可用；迁移、角色 ACL、候选包和任务领取必须作为一个维护窗内的原子发布单元。

## 十、最终验收清单

- [x] Git、唯一 head、长期 revision/health 与 bundle 身份已重新冻结。
- [x] 四种置信度显示中文，协议值不变。
- [x] Edition 收敛、次数耗尽、超时、dispose、取代和真实 scope 错误全部有精确断言。
- [x] 所有 Edition 失败路径零 bridge、零 bundle、零播放器副作用。
- [x] 历史 `local-owner` 完成当前 HTTP 成功链、幂等重放、精确继承和封印拒绝。
- [x] 四种迁移语义未混用；六个当前 schema 模块不再复制 head。
- [x] 可信仓库帮助器无外部路径参数；宿主使用 AST 静态解析候选 head，不导入或执行候选迁移代码。
- [x] 候选迁移图从固定 base `20260823_0001` 完整连到唯一 head，截断或替换 base 均拒绝。
- [x] 宿主与容器候选 hash 均使用 no-follow/分块读取、8192 条目/4096 文件/64 MiB 单文件/512 MiB 合计上限；链接、越界、身份漂移及迁移解析器窄上限均有回归。
- [x] 生命周期精确跟随候选目录自己的唯一 head，仓库 head 不会污染候选判断；容器内 Alembic 与数据库结果完成交叉验证。
- [x] 角色验证必须显式接收并校验受支持目标 head，不保留会过期的默认常量。
- [x] 章节 readiness 接受 `0034` 的合法后代并拒绝未知/分叉。
- [x] 0034/0035/0036 分别使用 62/65/67 表集合；当前 67 表 Python/SQL 一致，66 张业务表均在 ORM，`alembic_version` 是唯一系统表例外。
- [x] 无新迁移、无长期写入、无公共契约或模型行为漂移。
- [x] 定向、隔离 PostgreSQL、生命周期、角色、全量、打包、Compose、桌面浏览器和 diff 全部通过。
- [x] CURRENT-PG 与 LEGACY-ACTOR 没有共同可写文件；每个共享测试帮助器只有一个 Owner。
- [x] `TTS49_NODE_BIN`/`TTS49_PNPM_BIN` 已解析为可执行绝对路径，三个本地 CLI 入口已验证；门禁由绝对 Node 直接启动，不依赖裸 Node 或隐式 `PATH`。
- [x] 全量 pytest 子进程不携带任何数据库/角色可选门禁变量或 `TTS_REAL_NANO_TOKEN_FILE`，隔离门禁逐项显式注入。
- [x] 三个现存 `anw-ccl-*` 容器（含一个 exited 保留项）已列入保护清单，计划 49 未以 project label 或广义清理影响它们。
- [x] 回退 A 分支已隔离演练；存在 0036 记录时明确进入全 narration fail-closed 的 B 分支，不虚构未实现的单能力开关。
- [x] 计划 45/47、证据和索引准确反映“已提交推送、未长期部署、真人门禁仍 HOLD”。
- [x] `TTS49-CODE-FINAL`、`TTS49-SCHEMA-COMPAT-FINAL`、`TTS49-RELEASE-READY` 已分别裁决。

## 十一、自查结论

V1.5 在保留 V1.4 候选/仓库隔离、AST 无执行解析、并行互斥和净化测试环境的基础上，关闭了本轮复查发现的九项计划缺口：

1. 删除了把尚未存在的候选解析器误列为旧硬编码脚本的事实错误。
2. 可信仓库 helper 固定为无路径参数，候选不能借 Alembic 可信解析路径执行代码。
3. 候选图要求固定规范 base，不再接受从中途截断但仍“单 base”的伪完整链。
4. 生命周期的宿主/容器 tree hash 改为分块读取并增加候选整树文件数、单文件和总字节上限；迁移解析器继续使用更窄上限。
5. 数据库角色清单按 0034/0035/0036 冻结为 62/65/67，当前 SQL 只与最新 67 表全集相等，避免在长期 0035 上错误要求未来表。
6. ORM 对账明确区分 66 张业务表与唯一非 ORM 的 `alembic_version`，不再声称 67 张都来自 ORM metadata。
7. 所有工作包获得精确文件、测试、证据与锁；真实 PostgreSQL 统一由 W4 串行执行。
8. 测试命令使用绝对 Node 直接运行固定 CLI 入口，避免绝对 pnpm 的子进程仍找不到裸 Node；同时清除可能触发真实 Nano 的 token 文件变量。
9. 发布恢复拆成零 0036 记录可降级与已有记录全 narration fail-closed 两支，不再虚构尚未实现的单能力关闭开关；三个现存 `anw-ccl-*` 容器也已纳入保护边界。

V1.5 不新增迁移、不重写播放器/选角/VoiceGenerator、不回填 18 条历史 actor，也不以自动化替代作者听检或真实 Provider 成功链。

终审裁决：**V1.5 已完成源码施工与隔离验收，计划 49 的代码、schema 兼容和发布准备三项裁决均为 PASS。最终候选证据见[计划 49 验收目录](./证据/计划49/README.md)。当前仍不能开始长期部署，也不能宣称计划 45/47 的作者听感、真实 Provider 或表达风格验收已经完成。**
