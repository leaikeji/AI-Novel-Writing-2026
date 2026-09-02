# 计划 54：故事账本单契约与测试小说清理验收证据

状态：**PASS**

日期：2026-09-02（Asia/Shanghai）

本目录只保存不含正文的结论与脱敏 UI 截图。来源摘录、人物状态和事实详情已在真实浏览器中核对，但不把正文或摘录持久化到证据目录。

## 1. 最终结论

- 长期数据库与安装树 head：`20260902_0038`。
- 权威账本：`novels.story_ledger_version` + `story_facts`；来源、事件、批次分别由 `derived_source_bindings`、`story_event_links`、`intelligence_commit_batches` 承载。
- 候选层：`intelligence_proposals`／`intelligence_proposal_items`，只有作者接受后才进入上述正式账本，不是第二账本。
- 人物卡、Context、Embedding 和全书账本均消费同一权威服务；人物工作台只保留 `character-workspace/2`。
- 旧 GET、旧纠错／撤销路径、`item_overrides`、`relation_type`、`derived_entity_type` 及对应前端 fallback 已删除。

## 2. 数据清理与恢复点

精确删除 7 本已证明为测试用途的小说；当前仅保留：

| UUID | 标题 | version | story_ledger_version |
| --- | --- | ---: | ---: |
| `b68c6731-99e5-47e8-92cb-dac99a77503f` | 刑侦1988:消失的档案 | 2 | 12 |
| `b9983b07-f3aa-44e5-9433-d367563f48e4` | 潮汐盲区 | 4 | 29 |
| `1e405084-319f-472d-b95d-d003ed1e305d` | 超能梦境 | 2 | 11 |

当前长期库只读计数：

| 项目 | 结果 |
| --- | ---: |
| novels | 3 |
| story_facts | 89 |
| derived_source_bindings | 89 |
| character_relationships | 25 |
| intelligence_commit_batches | 12 |
| 已移除兼容列残留 | 0 |
| 新来源唯一约束 | 1 |

仓库外恢复点：

1. 删除前：`/Users/liujia/Documents/AI小说世界2026-backups/plan54-ledger-cleanup-20260902-143645-before.wzRPnJ`
   - custom-format dump：25,946,831 bytes；
   - restore list 可读；
   - 主 checksum 与删除后 manifest checksum 均为 OK；
   - 目录 `0700`、文件 `0600`。
2. 删除后、0038 前：`/Users/liujia/Documents/AI小说世界2026-backups/plan54-single-contract-20260902-AH2Zph`
   - custom-format dump：24,461,941 bytes；
   - restore list 与全部 checksum 为 OK；
   - 目录 `0700`、文件 `0600`。

没有删除 PostgreSQL、QwenPaw、媒体或凭据持久卷。测试小说恢复必须使用第一份完整 dump；schema／候选回退优先使用精确 `0038 → 0037` schema-owner 动作和第二份 dump。

## 3. 迁移与正式发布

- 隔离库：`0037 → 0038 → 0037 → 0038` 全链 PASS；升级后两列消失、新唯一约束存在、批次 canonical hash 等值，降级后旧结构可恢复。
- 正式库：先备份并停止 QwenPaw，经 migrator + `SET ROLE ai_novel_schema_owner` 精确升级；0038 bootstrap 与 validator 对 67 张保护表 PASS，API／worker raw DML 保持拒绝，`production_role_switch=HOLD`。
- 精确 `0038 → 0037` 恢复动作已同时写入源码和维护发布卷 `ai-novel-2026-dbr54-release-root-20260902`；包装器 SHA-256 均为 `8b290a87f0a0f97dde24b13eb93979a87b67126b3a5b74f3ec01e36d10613a58`。这是灾难恢复工件，不是运行时兼容分支。
- 最终候选树 SHA-256：`d2baf2b249afb4f51d0ce239d694b9d619f4a65479fbabe1a5645b97dcc7c7ff`。
- 最终前端 bundle SHA-256：`3a6f365ab500c2cdc34b61cb616305cc3a9633f89768195b852a0c6c50efac2f`；候选与安装树相同。
- QwenPaw 容器 ID：`bacd5c35e858ccb0df660314aff28b6d57523133eb40cf489fb2975d49dce8f5`；基础镜像 ID：`sha256:ea2c0858b94a6522821cceb73593bbea5f02c85fee2f08a8d7386ea90d9f15b1`；restart count 0，health `healthy`。

## 4. 自动化结果

| 层 | 实际结果 |
| --- | --- |
| Python 全量 | 3,629 passed；180 skipped；3 warnings |
| 前端全量 | 136 files；1,163 tests passed |
| TypeScript | `pnpm typecheck` PASS |
| 前端生产构建 | 173 modules，`pnpm build` PASS |
| 插件打包 | `scripts/package_plugin.py` PASS，head 0038 |
| 数据库角色定向回归 | `tests/narration/test_database_roles.py` PASS（含精确 0038→0037 恢复门禁） |
| Compose | `docker compose config --quiet` PASS |
| 差异卫生 | `git diff --check` PASS |

运行态 HTTP 复核：

| 请求 | 结果 | 判定 |
| --- | ---: | --- |
| 新故事账本 summary | 200 | 唯一读取路由可用 |
| 旧 `story-facts` GET | 404 | 不再提供 |
| 新纠错路径 + 空 body | 422 | 路由存在且严格校验 |
| 旧纠错路径 + POST | 405 | 插件未注册该命令路径 |
| 旧批次 revert + POST | 405 | 插件未注册该命令路径 |

## 5. 1920×1080／2560×1440 真实 UI

浏览器明确设置 1920×1080 和 2560×1440；宿主内容视口实际分别为 1901×1069 与 2534×1426。两档均验证：

- 创作中心只显示 3 本保留小说；
- 统一账本总览、85 条事实分页、详情与三项操作均可用；
- 来源只返回服务端有界摘录，不加载整章 revision；
- 修正与撤销只打开影响预览，没有提交真实写入；
- 人物卡“状态与经历”明确来自故事账本，人物来源同样走有界摘录；
- 无页面横向溢出、旧字段、旧版／兼容文案或账本 console error。

首轮 1080P 发现详情操作区被宿主滚动边界裁切。修复桌面详情高度为 `calc(100dvh - 240px)` 后，重新完成前端全量、构建、重装和双分辨率复验。浏览器仅观察到一条 QwenPaw 宿主 `AppCenter` 模块 warning，未出现账本 error，且不影响 PawApp 页面。

脱敏截图：

- [1080P 创作中心：仅三本保留小说](./01-1080p-创作中心-仅三本正式小说.jpg)
- [1080P 统一故事账本总览](./02-1080p-统一故事账本.jpg)
- [2K 统一故事账本总览（事实列表前裁切）](./05-2k-统一故事账本-脱敏.jpg)

最终证据复核发现早期同名 2K 图片实际停留在章节页，不能证明账本页面；该错误图片已由真实 2560×1440 账本页重新取图并覆盖。现文件为 2509×475 JPEG，SHA-256 `92c9dbeab41dd75b7cc21432fedeeb1bf5acd1cd14ea0d820f5d2e15400336be`，裁切止于筛选区，不保存事实正文。

## 6. 剩余边界

- API／worker 正式运行角色切换仍为 `HOLD`；本轮没有扩大授权。
- 没有执行真实纠错、批次撤销、正文保存或模型写作。
- 计划 52 的百万／五百万字压力矩阵未启动，仍需独立批准与恢复点。
- 工作树未暂存、未提交、未推送。
