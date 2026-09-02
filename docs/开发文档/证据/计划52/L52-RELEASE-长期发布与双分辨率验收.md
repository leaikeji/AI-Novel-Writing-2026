# L52-RELEASE：长期发布与双分辨率验收

日期：2026-09-02 至 2026-09-03（Asia/Shanghai）
状态：**PASS（长期 `18088` 已迁移并安装最终候选）**

## 1. 发布结论与边界

- 用户已单独授权长期备份、数据库迁移、PawApp 安装、QwenPaw 重启和验收；Git 暂存、提交和推送不包含在该发布授权中，已由 2026-09-03 的独立用户指令另行授权。
- 长期数据库已从 `20260902_0038` 升级到唯一 head `20260902_0039`；新 revision 只为 `document_working_copies` 增加可回填的 `visible_character_count BIGINT NOT NULL`，不增加第二套账本。
- 最终候选已通过 QwenPaw 公开 PawApp 安装接口进入长期环境；未修改 QwenPaw 上游源码、镜像或数据卷。
- 长期真实小说只做只读 API 与 UI 验收，没有保存正文、创建 revision、写故事事实、发起模型生成、重建索引或删除小说。
- 计划 53 的 API／worker 运行角色切换继续 `HOLD`；这不影响本次 schema-owner 维护链和当前长期运行。

## 2. 候选身份

隔离 `L52-QA` 原始候选树 SHA-256 为 `cf7d5a93600d174275162c1b51bca5b94002be5484bad2e3644875be97af74d9`。长期真实数据只读 UI 复验发现两处宿主助手布局缺陷后，增加作用域限定在 `.anw-assistant-pane` 内的布局修复和对应前端测试。

提交前范围复查发现，第一次长期安装树 `58e3beb258bebc2e9e06e36de27e61903015f375623ab4ab06efe0af2d4326b7` 还混入了未获准的计划 55“新书默认旁白”源码和计划 52 开工前已有的抽屉／遮罩 UI 候选。该问题不是账本或迁移错误，但不满足精确候选范围：在此安装存续期间没有创建小说、保存正文或调用 Provider。复查后从候选中隔离上述代码，重新执行全量自动化、100 万／500 万字、打包和完整隔离生命周期，并以公开离线安装流程替换长期 PawApp；数据库保持 `0039`，无需再次迁移。

| 项目 | 最终值 |
| --- | --- |
| 最终候选树 SHA-256 | `90f1a601546ccbc458e557a65a9c9b421d6e3b1413bd50dda9d4f3b68dd5fc03` |
| 最终前端 bundle 字节数 | `3,574,122` |
| 最终前端 bundle SHA-256 | `4266dd7ab435c9b949226e45d9e2b2923e643d5792505150045436ee04228c3a` |
| 最终候选归档字节数 | `2,241,229` |
| 最终候选归档 SHA-256 | `a0cec77eb21dbcc411490f0b0a01cb9bf96ab9b8df381ec54e877ab60260502e` |
| 最终候选归档 | `/Users/liujia/Documents/AI小说世界2026-backups/plan52-live-20260903-0017-scope-corrected` |

最终候选另在一次性隔离 QwenPaw 中以 `l52clean0903` 通过公开安装、强制重装、卸载零残留、再次安装、`0039` head 和精确资源清理，原始记录见 [`L52-isolated-plugin-lifecycle-scope-corrected.json`](./L52-isolated-plugin-lifecycle-scope-corrected.json)。候选文件与长期安装目录在排除运行时 `__pycache__` 后均为 261 个文件，最终长期安装树 SHA-256 与候选同为 `90f1a601546ccbc458e557a65a9c9b421d6e3b1413bd50dda9d4f3b68dd5fc03`。

## 3. 发布前备份

权威备份目录为 `/Users/liujia/Documents/AI小说世界2026-backups/plan52-live-20260902-233719-before`，目录权限 `0700`、备份文件权限 `0600`。`pg_restore --list` 可读取 1,480 行目录。

| 备份对象 | 字节数 | SHA-256 |
| --- | ---: | --- |
| PostgreSQL `0038` 自定义格式 dump | 24,918,056 | `60acbfea111f61cc6fdc464ccd339297d12280a28602c9a34d4d85e5a702b650` |
| 发布前 QA 候选包 | 2,257,433 | `b1ea6ea64ae4b4ad763f6e4a3c2e32e030cbb4e9a2a37116b128dc7e70f4922b` |
| 旧长期 `0038` 已安装插件 | 4,644,260 | `60ff5520e84b22bf094b7b82b7d70ebf7b6ff9d98d0edf54f081dec9d6d09227` |
| QwenPaw data 卷 | 157,114,831 | `24f7fdff3887e6e85c1a3e152e99eec53e0a7ee108ec0e02ec0bef83eb1be143` |
| QwenPaw secrets 卷 | 7,420,275 | `541bcb3e57267c81afd65c1fb6530d44210556da1d148f468c9cdb88ddda4507` |
| 小说媒体卷 | 365,322,645 | `6d0d3c362269bb805b7c867ebbadc04382d2dfbdf3b270e3e0739cc1255f0a3d` |

一次失败的 `pg_restore` 预检只在 `/tmp` 产生不完整副本，随后由保护逻辑恢复服务；正式备份完成后，该无效副本、临时管理员 pgpass、临时 JSON 和被最终候选取代的中间归档均已精确删除。正式备份、最终候选归档和回滚卷保留。

## 4. 迁移、权限与运行态

长期发布按以下串行门禁执行：停止 QwenPaw → `0038` 权限 bootstrap／validate → migrator 以 schema owner 执行 `0038 -> 0039` → `0039` bootstrap／validate → 离线公开安装 → 启动与验证。

- `0038` 和 `0039` 的角色验证均通过：67 张受保护表、115 个 public relation、222 个 routine；运行角色 raw DML 被拒绝，未来未声明对象 fail closed。
- `visible_character_count` 为 `BIGINT NOT NULL`，空值和负值均为 0。
- QwenPaw 容器 ID 保持 `85d0cb14e3996e4d9a2e30ed2eb74326d64b78dacdb408be83f823c1a0ae7f82`，镜像 ID 保持 `sha256:ea2c0858b94a6522821cceb73593bbea5f02c85fee2f08a8d7386ea90d9f15b1`；最终状态 running／healthy。
- PawApp health 为 ready，数据库 connected；TTS runtime／product 均 ready。
- 三个 Agent 均存在；“AI小说作家”为 9 个小说 Skills／5 个小说工具，其他 Agent 没有小说 Skills／工具泄漏。
- `/`、`/chat`、`/settings`、`/frontend_plugin` 均返回 200，QwenPaw 原生容器与镜像身份未变化。

维护期间曾有外部机制意外启动 QwenPaw；发现后立即停止。当时离线安装门禁已在复制前拒绝继续，没有产生半安装目录。后续按完整串行流程重新执行并通过。

## 5. 长期数据与向量状态

发布前后下列计数保持一致：novels 3、documents 13、document revisions 41、working copies 13、story facts 89、逐书 embedding consent 1、semantic sources 3、chunks 31、embeddings 31、embedding generations 12；后台 active job／attempt／lock 均为 0。

长期向量状态为：全局检索开启，embedding runtime ready；3 本小说中 1 本 `granted`、2 本 `not_granted`，索引对应 1 本 `ready`、2 本 `not_authorized`。这证明默认开启规则没有静默改写既有小说授权，也没有制造第二套向量账本。此次验收没有调用真实 embedding 或正文 Provider。

## 6. 真实 1080P／2K 验收

Browser 目标 viewport 为 1920×1080 和 2560×1440；受浏览器内容边框影响，实际页面分别为 1901×1069 和 2534×1426。验收使用长期真实小说的只读页面，不保存真实标题、正文、Prompt、query、snippet 或截图证据。

真实页面首先暴露两项缺陷：长 QwenPaw 会话标题会把助手右侧 header 操作挤出面板；2K 下 sender action list 比其 424px 父容器宽 24px，发送按钮部分裁切。修复限定在 PawApp 的 `.anw-assistant-pane`，让原生 header 和 sender 子组可收缩，并增加 `assistant-native-header-layout.test.ts` 契约测试；未改 QwenPaw 上游样式。

| 页面／检查 | 1920×1080 | 2560×1440 |
| --- | --- | --- |
| 创作中心 | 1 个作品卡片区、4 个切换按钮、无横向溢出、0 越界、0 错误 | 同左；总 DOM 约 889 |
| 章节工作台 | 当前章有效、Context V4 ready、2 行当前小书目录、总 DOM 约 976、发送按钮在 sender 内 | Context V4 ready、总 DOM 约 1,041、发送按钮在 sender 内 |
| 全局向量接入页 | 1 个 embedding 页面、3 张卡片、无溢出／越界／错误 | 同左 |
| 小说语义索引卡片 | 卡片和指标各 1、无溢出／越界／加载失败 | 同左 |

两档分辨率最终均无页面横向溢出、关键控件越界或 Context V4 failure。范围隔离并替换长期 PawApp 后，再次以长期只读数据复验创作中心、章节工作台、全局向量接入页和小说语义索引页；1920×1080 与 2560×1440 均为 0 横向溢出、0 稳定可见越界、0 错误态。范围隔离后重新执行的自动化结果为：全量 Python PASS、长篇专项 8 项 PASS、`pnpm typecheck` PASS、`pnpm test` 140 个文件／1,182 项 PASS、`pnpm build` PASS。

## 7. 回退与剩余边界

精确 schema 回退命令已通过 `docker compose config --quiet`，但没有为了演示而破坏当前可用的长期 `0039`。如需回退：停止 QwenPaw → 使用保留的 `ai-novel-2026-plan52-release-root-20260902` 和三套角色认证卷以 schema owner 执行 `0039 -> 0038` → bootstrap／validate `0038` → 通过公开 QwenPaw CLI 安装备份中的旧 `0038` 插件 → 启动并复验。若 schema 或数据状态不确定，则在服务停止时恢复 PostgreSQL、QwenPaw data／secrets 和媒体完整备份。

保留卷：`ai-novel-2026-plan52-release-root-20260902`、`ai-novel-2026-db-migrator-auth`、`ai-novel-2026-db-api-auth`、`ai-novel-2026-db-worker-auth`。它们仅用于维护／恢复，不是第二套数据库或第二套账本。

计划 52 的长期发布门禁现已完成；最终安装树不含计划 55 默认旁白候选或开工前未归属 UI 候选。仍未执行且不应冒充通过的只有：真实正文／embedding Provider 调用、作者对模型输出的质量验收，以及 API／worker 生产运行角色切换；这些需要各自范围内的新指令或既有独立计划裁决。Git 提交／推送由当前独立指令授权，只能包含本次复核确认的计划 52 范围。
