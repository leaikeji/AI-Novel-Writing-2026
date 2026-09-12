# 计划 73：章节生成与朗读连续播放局部刷新验收证据

日期：2026-09-12（Asia/Shanghai）

结论：`PASS / FORMAL_18088_DEPLOYED / DESKTOP_EXISTING_AUDIO_PASS / NO_NEW_MODEL_CALL`

## 范围

本次只验收章节页的 Manifest 原地刷新、播放器连续性、pending 缺口续播意图、正文生成时编辑器稳定挂载和动态只读。不修改数据库、Alembic、TTS Provider、模型配置、媒体格式或 QwenPaw 上游；不执行移动端验收。

## 自动化与构建

- 主工作区 TypeScript 类型检查通过。
- 主工作区前端全量：153 个测试文件、1319 项测试全部通过。
- 主工作区 Vite 生产构建通过；`frontend/dist/index.js` 为 3,539.25 kB，gzip 1,093.18 kB。
- `git diff --check` 通过。
- 从 Plan 72 正式发布源复制出的隔离候选中，本次 session／编辑器／workbench 定向测试为 5 个文件、93 项通过，类型检查和 Vite 构建通过。
- 隔离源目录保留的是 Plan 72 生产代码，但其中三份 Plan 72 测试夹具仍是更早基线；因此隔离目录全量测试出现 11 项已知夹具不匹配，不将其误报为本次回归。当前主工作区的最新测试夹具全量 1319/1319 通过，正式桌面行为另行实测。

## 候选纯度与正式部署

- Plan 72 正式 ZIP 内前端 SHA-256：`31049f08b8ea85b4473c0b204344dfe337c02264be41227099dc90f8b78af2d7`。
- Plan 73 候选 ZIP SHA-256：`5ec8efb6a66a91415bcc89659984a1edb75aa6d99d68811fd180417ffbe97f54`。
- Plan 73 前端 SHA-256：`a8c5550d0f8535837b40b20887e79eec7021c8c8408711b9757fbe54295822a8`。
- Plan 73 包与 Plan 72 正式包逐文件比较，只有 `frontend/dist/index.js` 不同；计划 70 的未发布界面文案不存在。
- 第一次公开热安装阻塞在 `docker cp`，安装没有开始。强制重启 Docker Desktop 后，同一冻结候选通过 QwenPaw 公开 `plugin install --force` 路径安装并热加载成功；未删除容器、卷或业务数据。
- Docker Desktop 重启后，原本运行的 Plan 70 隔离 PostgreSQL 容器没有自动启动；已只启动该原容器恢复现场，正式与隔离 PostgreSQL 容器最终都保持运行，未重建或删除任何卷。
- 正式容器内 `frontend/dist/index.js` SHA-256 与候选完全一致。
- 部署前 Skills 快照恢复成功：11 项小说 Skills 保持启用；AI 小说作家的 5 项小说工具保持，默认与 QA Agent 未被启用状态污染。

## 正式运行与桌面验证

- `http://127.0.0.1:18088/api/ai-novel-world-2026/health` 返回 `ready`。
- PostgreSQL 18.6、向量运行时、朗读 worker、播放能力和 Qwen-TTS 生产链均返回 `ready`；模型仍为 `bigmodel / glm-5.3-flash`。
- Codex 应用内桌面浏览器进入《缺氧：末日地下世界》第 1 章；4380 字正文编辑器、11 个段落播放入口和章节播放器均可见。
- 播放器报告 206/209 句可播放、3 句失败；点击已有音频后状态为“正在播放”，随后点击暂停，状态为“已暂停”，进度从 1:00 到 1:01。
- 浏览器控制台错误为 0。QwenPaw 自身既有 `Module not found: Chat` 仅为 warning，未阻断 PawApp。
- 本轮没有点击“重新生成”，没有采用候选，没有触发新的正文或 TTS 模型调用；正式正文、既有 Edition 和音频没有被改写。

## 恢复

仓库外恢复点：`/Users/liujia/Documents/AI小说世界2026-backups/plan73-recovery-20260912-041800`。

- `ai-novel-world-2026-plan73.zip`：本次正式候选。
- `ai-novel-world-2026-plan72-rollback.zip`：上一正式包，SHA-256 `c7207b6a269d8e795c984adc24812ef2696feafc873889a95a846e3507fd91a9`。
- `skill-state-before.json`：部署前小说 Skills 状态。

回退使用公开插件更新路径恢复 Plan 72 包，再按快照恢复 Skills。本次没有 schema 或数据变更，不需要数据库回退。
