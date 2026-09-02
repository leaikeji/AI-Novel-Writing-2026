# TTS49 schema 与兼容性证据

状态：**PASS**

日期：2026-09-01（Asia/Shanghai）

## 四种迁移语义

| 场景 | 实现与裁决 |
| --- | --- |
| 可信源码仓库当前 schema | `repository_unique_head()` 只读取仓库固定 Alembic 配置，要求从规范 base `20260823_0001` 到唯一 head 的完整线性链；当前结果为 `20260901_0036`。 |
| 未安装候选包身份 | `candidate_migration_identity.py` 以无执行 AST 读取字面量，不 import/exec 候选迁移；固定 base、唯一 head、单链、文件名一致和资源上限全部 fail closed。 |
| 功能最低版本 | `chapter_e2e_readiness.py` 通过祖先关系判断 `20260829_0034` 是否已应用；`0034/0035/0036` 接受，`0033`、未知、多 head 或分叉拒绝。 |
| 历史迁移证据 | 具体阶段测试继续锁定明确 revision；没有把 `0015/0016/0034→0035→0036` 动态化。 |

候选整树在宿主与容器内都按目录名和路径排序参与 SHA-256，并使用 no-follow、分块读取、身份复核及 `8192` 条目、`4096` 文件、`64 MiB` 单文件、`512 MiB` 总量上限。迁移解析器另有 `512` 文件、`1 MiB` 单文件、`16 MiB` 总量的更窄上限。链接、硬链接、特殊文件、截断或替换 base、文件漂移、资源越界均有负向回归。

## 当前 schema 测试

六个依赖完整当前 schema 的 PostgreSQL 模块统一使用 `tests/narration/current_schema_gate.py`；不再各自复制 `0034` 或 `0036`：

- 脚本复核 backend PostgreSQL
- 脚本复核 PostgreSQL
- Nano 高级调音 PostgreSQL
- 失败段落重试 PostgreSQL
- VoiceGenerator PostgreSQL
- 官方音色选择契约 PostgreSQL

隔离 PostgreSQL 18 最终结果为 `30 passed / 1 skipped`。跳过项只因没有为本轮提供真实 Nano token 文件，不影响本计划的 schema/兼容性裁决。

## 数据库角色矩阵

| 精确 head | 显式保护表 | 隔离结果 |
| --- | ---: | --- |
| `20260829_0034` | 62 | `18 passed` |
| `20260830_0035` | 65 | `18 passed` |
| `20260901_0036` | 67 | `18 passed` |

- `--expected-head` 与测试变量均为必填，不再存在会随版本过期的默认 head。
- 当前 67 表 Python 集合与 `protected-tables.sql` 精确一致。
- 66 张业务表全部存在于 ORM metadata；`alembic_version` 是唯一允许不在 ORM 中的系统表。
- `narration_`、`voice_`、`nano_`、`character_cast_` 权威表执行未分类负向审计。
- API/worker 对保护表的 raw INSERT/UPDATE/DELETE 保持拒绝；没有扩大 public/anonymous 权限。

迁移矩阵完成 `0034 → 0035 → 0036 → 0035 → 0036`；整书选角迁移往返专项 `1 passed`。迁移历史、ORM 与公共契约均未修改。

## 历史 actor

隔离回归证明：

- `explicit_generation_actor='local-owner'` 的历史请求可沿当前 HTTP `PATCH → approve → request GET → Edition GET` 完成。
- 同一幂等键重放不改变 actor，不重复创建脚本版本、动作或 Edition。
- 新 `owner` 请求只有在脚本、哈希、锚点、说话人、workspace 与审计证据完全一致时才继承人工修正。
- actor/provenance 不一致或任一 scope 漂移时拒绝继承，零 Edition 写入。
- 已持久化 actor 仍由数据库 trigger 封印，直接改写会被拒绝。

长期库中的 18 条 `local-owner` 历史请求未被回填或修改。

## 长期差异

2026-09-01 最终只读复核：

- 长期数据库：`20260830_0035`
- 候选数据库：`20260901_0036`
- 长期运行态：PawApp、PostgreSQL、Nano Sidecar 均健康，TTS runtime/production ready。
- 长期能力没有 `character_cast_planning`；候选 `/3` 契约包含该能力。

因此候选不得在长期库仍为 `0035` 时单独热装；`0035→0036`、67 表 ACL、候选包与任务领取必须在另行授权的同一维护窗中完成。
