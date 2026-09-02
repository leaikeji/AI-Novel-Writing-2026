# DBR53-W3–W5 长期发布与双分辨率验收

状态：**PASS（2026-09-02，Asia/Shanghai）。本证据验收时计划 51 最终候选已安装，长期数据库和安装树均为 `20260902_0037`；后续[计划 54](../../54-故事账本单契约收缩与测试小说清理计划.md)已将两者升至 `20260902_0038`。**

## 1. 范围与边界

本证据覆盖计划 53 的长期首次建角色、schema-owner 迁移、精确候选安装、账本上下文阻塞修复、只读 API／原生非回归、真实 1080P／2K 前端以及数据／媒体一致性。

本轮没有调用真实小说写 API，没有保存人物卡、正文或 StoryFact，没有修正／撤销 revision，没有更新朗读进度或生成媒体；没有切换 QwenPaw 正式运行连接到 `ai_novel_api`／`ai_novel_worker`，没有启动计划 52 压力矩阵，也没有修改 QwenPaw 上游、暂存、提交或推送。

## 2. 冻结身份与恢复点

| 项目 | 最终事实 |
| --- | --- |
| PawApp | `ai-novel-world-2026@0.4.0` |
| QwenPaw | `2.1.0`；基础 image ID `sha256:ea2c0858b94a6522821cceb73593bbea5f02c85fee2f08a8d7386ea90d9f15b1` |
| 迁移 head | `20260902_0037` |
| 首次正式候选树 | `7233b58013118f893a044ae4edc7d44cc9e287e4f8625f18d274b6054d94df37`；账本助手上下文失败时点，只作历史证据 |
| 最终候选／已安装过滤树 | `1b09e823bf4fc0e880733dd6c70959399889f437dcde23ebf2527c3c5adc479d`；运行期 `__pycache__` 不计入摘要 |
| 前端 bundle | `dd5f913799efe35f2dc4512b894deee587b82d3f310f90751c4c68ea903246bf` |
| 权威恢复点 | `/Users/liujia/Documents/AI小说世界2026-backups/plan53-live-20260902-122554-paused-authoritative` |
| 另一份有效恢复点 | `/Users/liujia/Documents/AI小说世界2026-backups/plan53-live-20260902-122021` |
| 禁止使用的部分备份 | `/Users/liujia/Documents/AI小说世界2026-backups/plan53-live-20260902-121738-INVALID-qwen-restarted`；名称和本证据均明确标为无效 |

权威恢复点包含维护前数据库 dump、public 表逐表计数、安装树、QwenPaw 数据／配置、秘密和媒体归档。没有把密码、小说标题、正文、人物名、事实内容、来源摘录、媒体内容或真实业务 UUID 写入本证据。

## 3. 四角色、迁移与安装

1. 在 QwenPaw stopped、活动任务和数据库会话归零后，以维护 overlay 建立 `ai_novel_schema_owner`、`ai_novel_migrator`、`ai_novel_api`、`ai_novel_worker` 及三个独立 `0600` pgpass 文件。
2. 0035 validator PASS 后，仅由 migrator 登录并 `SET ROLE ai_novel_schema_owner`，线性执行 `20260830_0035 → 20260901_0036 → 20260902_0037`。
3. 第二次 bootstrap／validator PASS：67 张保护表、115 个 public relations、222 个 routines；数据库、schema 与应用对象 owner 均为 `ai_novel_schema_owner`；API／worker 任意 raw DML、保护表 raw DML和 public routine execute 均为 false；未来对象默认权限 fail closed。
4. `production_role_switch=HOLD`。三个运行角色能独立认证不等于正式进程已经切换；当前 QwenPaw 继续使用兼容的 `ai_novel` 连接。
5. 最终候选通过 QwenPaw 公开 CLI 在正式容器停止态安装。正式容器 ID、基础镜像、restart policy 和三个 QwenPaw 数据卷没有变化；启动后插件 installed/loaded、PawApp health ready、数据库 connected。
6. “AI小说作家”专用 Agent 保留 9 个项目 Skills 与 5 个项目工具；另外两个 Agent 没有被误启用项目 Skills／工具。

## 4. W5 阻塞与严格修复

首次候选安装后，真实账本页显示“页面上下文准备失败”。事实冲突是：前端已经冻结并发送 `page.section="ledger"`、`page.view="story-ledger"` 和有界 `ledger` 子对象，后端 context-ref registry 仍只允许旧页面白名单并拒绝顶层 `ledger`，因此返回 422。

修复只同步这一冻结契约，并继续强制：exact keys、页面 section／view／ledger 成对出现、外层与 ledger 小说范围一致、选中事实 ID 一致、严格类型、`ledger` 6,000 code-point 子预算、总上下文预算，以及额外字段／跨作品／正文摘录拒绝。没有增加迁移、宽泛 passthrough 或第二套上下文。

修复后的 registry／HTTP API 正负测试、相关前端上下文测试、前后端全量回归、重打包、生命周期 dry-run 和精确重装均通过。最终候选树更新为 `1b09…479d`；bundle 和迁移 head 保持冻结值；真实账本页助手显示“本轮上下文已就绪”。

## 5. Docker Desktop 运行故障与恢复

首次正式停止态安装的 container-start 请求两次超时。只读诊断确认 Docker Engine 的 start API 全局卡住：一个不挂卷、只运行 `/bin/true` 的独立探针也无法启动，故障并非候选、QwenPaw 或数据卷特有。用户明确授权重启 Docker Desktop 后执行恢复：

- 重启前精确登记的 10 个运行容器全部恢复：`ai-novel-2026-moss-tts-sidecar`、`ai-novel-2026-postgres`、`anw-ccl-postgres-20260901`、`anw-ccl-qwenpaw-20260901`、`showcase-admin`、`showcase-api`、`showcase-nginx`、`showcase-pgsql`、`showcase-web`、`tomato-novel-webui-docker`；
- 恢复后无卷探针立即通过，正式安装随后通过；
- 未执行 `prune`、未删除任何持久卷、未重建正式 QwenPaw 容器；诊断包和临时管理员 passfile 已精确删除；
- 为诊断曾临时把安装 start timeout 提高到 120 秒，事实证明无效，该源码／测试变动随后使用补丁完整撤销，最终候选不包含这一猜测性修改。

外部 `/Users/liujia/Documents/AI小说世界2026-docker-orchestration/compose.yaml` 曾在维护窗自动拉起 QwenPaw；本轮没有越权修改该文件。它是下一次停机维护前必须冻结的外部 reconciler 风险。

## 6. 自动化与只读 API 验收

| 门禁 | 结果 |
| --- | --- |
| 后端全量 `.venv/bin/python -m pytest` | 3625 passed、180 skipped、3 warnings，34.07s |
| 前端全量 `pnpm test` | 137 files、1169 tests passed |
| 前端 `pnpm typecheck`／`pnpm build` | PASS／PASS |
| 账本 context registry／HTTP API 定向正负测试 | PASS；额外字段、未配对页面、跨作品与超预算均拒绝 |
| 插件打包／生命周期 | package PASS；最终 head `0037`，dry-run lifecycle PASS |
| 长期 API／原生非回归 | 86 个只读请求 PASS；`/`、`/chat`、`/settings`、`/frontend_plugin` 正常 |

API 矩阵只记录数量和结构：3 个 Agent、10 个唯一作品、旧事实共 111 条；ledger summary/list/detail/source、story-state、人物 workspace V1/V2、人物 facts、时间线链接／事件链接／人物实例及 18 项 narration capabilities 均通过。

解释修正：第一次汇总把一个 422 记成“9 个已初始化、1 个未初始化”不准确。该作品实际有多条活跃时间线，未传 `timeline_id` 时按冻结契约返回范围歧义；显式传入服务端给出的合法 timeline scope 后，story-state 和 ledger 都是 10/10 ready。证据不保存实际 timeline UUID。

## 7. 真实 1080P／2K 前端矩阵

浏览器请求 viewport 为 1920×1080 和 2560×1440；受应用浏览器 chrome 影响，页面实际 `innerWidth × innerHeight` 分别为 1901×1069 和 2534×1426。每格均检查 document 横向溢出、横向越界可交互控件、可见错误面、助手遮挡和 console；全部为 0／false。展开态均出现精确 ready 文案，折叠态状态文案隐藏且失败文案不存在。

| 请求尺寸 | 实际页面尺寸 | 页面 | 助手 | 目标区宽度 | 结果 |
| --- | --- | --- | --- | ---: | --- |
| 1920×1080 | 1901×1069 | 全书账本 | 展开 | 807 | PASS；context ready |
| 1920×1080 | 1901×1069 | 全书账本 | 折叠 | 1145 | PASS |
| 1920×1080 | 1901×1069 | 人物 | 展开 | 807 | PASS；context ready |
| 1920×1080 | 1901×1069 | 人物 | 折叠 | 1145 | PASS |
| 1920×1080 | 1901×1069 | 时间线 | 展开 | 807 | PASS；context ready |
| 1920×1080 | 1901×1069 | 时间线 | 折叠 | 1145 | PASS |
| 1920×1080 | 1901×1069 | 朗读播放器 | 展开 | 891 | PASS；context ready |
| 1920×1080 | 1901×1069 | 朗读播放器 | 折叠 | 1265 | PASS |
| 2560×1440 | 2534×1426 | 全书账本 | 展开 | 1327 | PASS；context ready |
| 2560×1440 | 2534×1426 | 全书账本 | 折叠 | 1747 | PASS |
| 2560×1440 | 2534×1426 | 人物 | 展开 | 1327 | PASS；context ready |
| 2560×1440 | 2534×1426 | 人物 | 折叠 | 1747 | PASS |
| 2560×1440 | 2534×1426 | 时间线 | 展开 | 1327 | PASS；context ready |
| 2560×1440 | 2534×1426 | 时间线 | 折叠 | 1747 | PASS |
| 2560×1440 | 2534×1426 | 朗读播放器 | 展开 | 1440 | PASS；context ready |
| 2560×1440 | 2534×1426 | 朗读播放器 | 折叠 | 1440 | PASS |

最初固定等待 700ms 的自动化会早于 context-ref 创建完成，被更正为最多 10 秒的状态条件等待；这属于 QA 脚本时序修正，不是产品故障。由于页面包含真实小说信息，本轮没有把新截图持久化到仓库或可视化目录；证据只保存几何、状态和错误计数，不保存内容面。

## 8. 数据与媒体不变门禁

- 维护前 public 表基线为 113 张；升级后为 115 张。全部 113 张既有表的逐表 `count(*)` 与权威备份完全相同；唯一新增的 `character_cast_plan_commands`、`character_cast_plan_items` 均为 0。
- 活动 background jobs、未完成 attempts、未过期 resource locks、阻塞数据库会话均为 0。
- 权威备份媒体归档与长期 live volume 按“规范化相对路径 + 文件大小 + 每文件 SHA-256”比较：1876 个文件、402,374,226 bytes，规范清单 SHA-256 均为 `6c2364c7c24c15ee6af4c07bb1ec7e879ae4183d9c0b769b7f5319b6d3a52379`，结果 PASS。
- 正式启动日志自安装后无 ERROR／CRITICAL；PawApp health 为 ready，数据库 connected。

## 9. 剩余边界与恢复

- API／worker 运行连接切换继续 `HOLD`，直到受审窄写过程和运行拓扑另行获批；不得把当前兼容 superuser 连接描述成最小权限切换完成。
- 计划 52 的 100 万／500 万字压力矩阵尚未执行；计划 51 的 10,000 条 StoryFact soak 不能代替正文链容量验收。
- P1 手工事实／时间线写 UI 和公开兼容删除仍需各自门禁；2026-12-01 兼容窗口到期前不强删公开字段或旧 endpoint。
- 如最终候选出现回归，先停止真实写入，使用第 2 节权威恢复点、旧安装包／旧基础镜像和 W2 已演练的迁移分支恢复；若 0036 表出现非零正式记录，不得自动 downgrade 或删除记录。
