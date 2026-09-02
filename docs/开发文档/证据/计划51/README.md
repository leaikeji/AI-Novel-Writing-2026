# 计划 51 证据索引

状态：**`L51-G0`、W1–W4、`L51-QA` 与 `L51-RELEASE` 均已通过。计划 53 已完成长期四角色／pgpass、schema-owner `0035 → 0037`、账本上下文修复候选安装以及 API、1080P／2K、数据和媒体一致性验收。真实小说写入、API／worker 运行角色切换、兼容窗口删除、P1 与计划 52 不在本次完成范围。**

日期：2026-09-02（Asia/Shanghai）

## 1. G0 裁决

- G0 启动时，用户已批准计划 51 V0.5，并按计划先执行串行 `L51-G0`；后续波次、V0.7 候选结果和发布预检见第 5、6 节及独立证据。
- 当前语义可以继续由 `StoryFact + DerivedSourceBinding + StoryEventLink + IntelligenceCommitBatch` 表达，不需要 Adoption 表、通用 Operation 表或新的快照表。
- 完整读快照采用**扩张后的单一 `Novel.story_ledger_version`**。所有能改变账本行、实体显示名、来源显示或投影纳入结果的权威业务动作，必须在同一事务锁定小说聚合根，并在实际变化时精确推进一次；no-op、精确幂等回放和失败回滚推进零次。
- `ledger_snapshot_token` 是客户端不解析的 `ledger-snapshot/1` 令牌，服务端内容包含小说范围与 `story_ledger_version`。list、summary、detail、source、impact preview 的令牌与正文必须来自同一只读 `REPEATABLE READ` 数据库快照。
- 当前人物事实读取被实测证明为“全量投影 + 全量人物事实 + Python 切页”，不得作为全书账本分页实现。
- 现有 schema 足以开始 W1/W2；不需要语义迁移。用于全局 `created_at DESC, id DESC` 页选的窄索引已有必要性证据，但必须等 W2 最终 SQL 冻结并获得单独批准后，才进入 `L51-MIG-QUERY`。
- 长期真实数据只做只读聚合和公开 GET；没有修正、撤销、删除或写入任何小说。

## 2. 证据文件

- [G0 权威契约与命令矩阵](./G0-权威契约与命令矩阵.md)
- [G0 数据、查询与迁移基线](./G0-数据查询与迁移基线.md)
- [G0 公共契约、前端系统与交叉锁](./G0-公共契约前端与交叉锁.md)
- [W1 权威一致性与写命令验收](./W1-权威一致性与写命令验收.md)
- [W2 全书账本 API 与查询基准](./W2-全书账本API与查询基准.md)
- [L51-MIG-QUERY 窄分页索引迁移验收](./L51-MIG-QUERY-窄分页索引迁移验收.md)
- [W3 前端共享工作台与交叉集成验收](./W3-前端共享工作台与交叉集成验收.md)
- [W4 冗余清理与兼容边界](./W4-冗余清理与兼容边界.md)
- [W5 候选整体验收与发布门禁](./W5-候选整体验收与发布阻塞.md)
- [W5 隔离插件生命周期首次报告](./W5-隔离插件生命周期.json)
- [W5 隔离插件生命周期重试报告](./W5-隔离插件生命周期-重试.json)
- [W5 隔离插件生命周期最终通过报告](./W5-隔离插件生命周期-0037.json)
- [L51-RELEASE 长期发布预检与恢复点](./L51-RELEASE-长期发布预检与恢复点.md)
- [计划 53 W3–W5 长期发布与双分辨率验收](../计划53/DBR53-W3-W5-长期发布与双分辨率验收.md)

## 3. G0 精确环境身份

| 项目 | 只读证据 |
| --- | --- |
| 源码基准提交 | `ee0992dc8e8cd1ded40b99ead662e629ca8b2bbb`；工作树为 dirty，计划 50 的未提交前端施工被保留 |
| 项目 Python | `3.12.13`，满足 `>=3.11,<3.14` |
| 源码 Alembic head | `20260901_0036 (head)` |
| 长期数据库已应用 head | `20260830_0035`；通过只读 `alembic_version` 查询取得，不能由源码 head 推断 |
| 长期 QwenPaw | 页面／容器为 `2.1.0`；基础镜像 ID 与 RepoDigest 均为 `sha256:ea2c0858b94a6522821cceb73593bbea5f02c85fee2f08a8d7386ea90d9f15b1` |
| 长期 PawApp | 公开插件状态为 `installed`，版本 `0.4.0`；`/health` 为 `ready` |
| 长期安装树摘要 | 排除 `__pycache__` 后的内容清单 SHA-256：`9388fab44dc658124185aecbc58093777f9e101bfce7232f2c7c65ad86175f3d`；安装树共 443 个普通文件（含缓存计数，仅用于规模说明） |
| 长期 plugin.json | SHA-256 `e1b3fd6ec4c7fb5170587e9a1f050bc95feb7070d1716092b24baf34a654b0cc` |
| 长期前端 bundle | SHA-256 `2b01f8c282321e4954e0865135bcc5c97cc894ce12513052dfabef86996ca845` |
| G0 时已有 build bundle | SHA-256 `819ead4ff4d5b55bc82248371b4a7f36847c5a1fb75ee6c0b4e363048becfc07`；这是 G0 取证时点，不是最终候选或长期安装事实 |

G0 时长期安装树没有 `20260901_0036_character_cast_plans.py`，长期库也停在 `0035`；当时源码和 build 已包含 `0036`，最终候选又追加了 `0037`。`backend/services.py`、人物 workspace service 和 story-state persistence 的抽样哈希在长期安装树与 G0 源码相同，而 `backend/models.py` 与前端 bundle 不同。这证明长期人物卡能力来自较新的已安装包，但不证明当前 dirty 候选、`0036` 或 `0037` 已部署。

## 4. 长期公开读取矩阵

| 路径 | 结果 |
| --- | --- |
| `GET /api/ai-novel-world-2026/health` | HTTP 200，`status=ready`，PawApp `0.4.0`，PostgreSQL 18.6 可达 |
| `GET /api/pawapps/ai-novel-world-2026` | HTTP 200，`status=installed`，PawApp `0.4.0` |
| `GET /api/ai-novel-world-2026/novels` | HTTP 200，共 10 个作品；证据只记录数量和字段形状，不保存标题／正文 |
| 旧 `GET /novels/{id}/story-facts` | 10/10 个作品 HTTP 200；返回 111 条，任一作品均未触达 500 条截断上限 |
| `workspace?view_version=1` | HTTP 200，`character-workspace/1` |
| `workspace?view_version=2` | HTTP 200，`character-workspace/2`，同一读时点的 ledger version 与 V1 相同 |
| `GET .../characters/{id}/facts?limit=2` | HTTP 200，`character-fact-history/1`，返回 2 行、稳定 cursor 和 summary；实现仍先全量加载，不能把响应页大小误当数据库有界 |

## 5. 最终候选与发布裁决

| 项目 | 结果 |
| --- | --- |
| 候选迁移 head | `20260902_0037`；G0 时点的 `0036` 身份仍保留在第 3 节历史取证中 |
| 首次正式候选树 SHA-256 | `7233b58013118f893a044ae4edc7d44cc9e287e4f8625f18d274b6054d94df37`；真实 W5 暴露 assistant context 白名单冲突，仅保留为失败时点身份 |
| 最终候选／已安装树 SHA-256 | `1b09e823bf4fc0e880733dd6c70959399889f437dcde23ebf2527c3c5adc479d` |
| 候选 bundle SHA-256 | `dd5f913799efe35f2dc4512b894deee587b82d3f310f90751c4c68ea903246bf` |
| 后端全量 | 最终候选 3625 passed、180 skipped、3 warnings；初始 W5 时点 3605 passed 作为历史结果保留 |
| 前端全量 | 137 files、1169 tests passed；typecheck／build PASS |
| Skill／打包 | 12 passed；package PASS |
| 查询硬门禁 | PASS：正式索引在 500／2,000／10,000 三档均为 Index Only Scan，扫描 21、返回 20 |
| 隔离生命周期 | PASS：`l51w5c0902` 完成 install → force reinstall → uninstall → reinstall；零残留、哨兵保持、精确清理 |
| 真实前端 | PASS：1080P／2K 目标 viewport 均覆盖助手展开／折叠，详情／来源／焦点关键路径通过 |
| 长期发布 | PASS：四角色／独立 pgpass、owner／ACL、`0035 → 0037`、最终候选安装、86 项只读矩阵和 16 格真实 UI 均通过；运行角色切换仍为 `HOLD` |

结论：候选实现和长期发布均已收口，`L51-QA`、`L51-RELEASE` 整体 PASS。预检阶段的角色阻塞由计划 53 按独立获批方案解除；旧公开 GET 与兼容字段仍在截止 2026-12-01 的窗口内，不因实现冗余而提前删除。

验收解释修正：早期 API 汇总把一个 422 写成“9 个已初始化、1 个未初始化”不准确。事实是该作品存在多条活跃时间线，请求未显式传 `timeline_id` 时按契约返回范围歧义；传入响应中合法时间线范围后，story-state 与 ledger 均为 10/10 ready。此修正不改写历史原始证据，只更正当前结论。

## 6. 未完成项

- 已安装最终长期 PawApp 并完成数据库升级；没有运行长期写 API，也没有修改真实事实、正文、revision 或媒体。
- 已创建并验证唯一获批的查询索引 revision `20260902_0037`；没有创建 `L51-MIG-COMPAT`，兼容收缩仍被窗口与旧包回退约束。
- 真实 1080P／2K 证据覆盖目标页面、助手展开／折叠、几何、错误面和 console；它不是完整 WCAG 审计，也不包含作者真实写入或主观内容质量验收。
- 四角色和三个独立 pgpass 已建立，但 API／worker 运行连接切换继续 `HOLD`；计划 52 压力矩阵和 P1 写 UI 仍需独立批准。
