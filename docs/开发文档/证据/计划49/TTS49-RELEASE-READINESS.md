# TTS49 部署前发布审计

状态：**候选级 `TTS49-RELEASE-READY=PASS`。2026-09-02 首次长期预检曾得到 `TTS49-LONGTERM-DEPLOY=BLOCKED_ROLE_BASELINE`；该阻断已由计划 53 独立解除，计划 53 验收时长期 schema 为 `20260902_0037`、四角色已建立、完整候选已安装。后续计划 54 已将长期 schema 与安装树升至 `20260902_0038`。**

日期：2026-09-01（Asia/Shanghai）

## 2026-09-02 当前运行态补记

计划 53 已在本计划首次预检之后独立完成备份、四角色基线建立、`0035 → 0036 → 0037` 线性迁移、完整候选安装与健康复核。四角色均存在（schema owner 禁止登录，migrator/API/worker 允许登录）；PawApp 与 Narration lifecycle ready，Sidecar reachable，production worker running，`character_cast_planning` enabled。计划 53 验收时 `character_cast_plan_commands/items` 计数为 `0/0`。

因此 `TTS49-LONGTERM-DEPLOY=BLOCKED_ROLE_BASELINE` 只描述下方首次尝试的历史结果，不再是当前阻断。计划 53 的发布证据负责其 `0037` 历史身份；[计划 54](../../54-故事账本单契约收缩与测试小说清理计划.md)负责现在的 `0038` 身份。本文件仍保留计划 49 的 `0036` 候选和恢复演练，不回写历史 hash。

## 2026-09-02 首次长期预检增量（历史）

用户另行授权长期部署后，已完成数据库、媒体、已安装插件和候选包备份，并实际执行维护窗前只读检查。长期数据库虽然处于预期的 `20260830_0035`，但角色目录只有 `ai_novel` 登录超级用户；以下四个冻结生产角色均不存在：

- `ai_novel_schema_owner`
- `ai_novel_migrator`
- `ai_novel_api`
- `ai_novel_worker`

因此本文件第 2 步的 0035／65 表角色预检不具备通过条件。发布在迁移、ACL 写入和候选后端安装前停止；数据库保持 `0035`，角色和媒体保持原样。计划 50 后续使用“旧已安装插件＋新前端 bundle”的单文件兼容包，只改变 `frontend/dist/index.js`，不提供 `character_cast_planning`，不构成计划 49 的完整发布。

恢复与证据见[计划 50 部署记录](../计划50/README.md)。重新尝试完整发布前，必须先单独设计并验收长期四角色基线的建立或迁移；不得把当前单超级用户连接直接解释为 65 表角色门禁已通过。

## 发布候选

| 项目 | 值 |
| --- | --- |
| 插件 | `ai-novel-world-2026@0.4.0` |
| 基线提交 | `84e4858e0a7f87e41dfe2578e6c7e20eeef4f348` |
| 施工分支 | `codex/tts49-compat-hardening` |
| 候选 head | `20260901_0036` |
| 候选整树 SHA-256 | `396500e75c4250492816fb1248bca2a1ddb97f471f3762ed59a358f7dc61f5b3` |
| bundle SHA-256 | `f394db08ccffe07afd6ba2968751d843515f66b66e25dbec32db21449759f147` |
| bundle 大小 | `3,438,034` 字节 |
| 最终生命周期 | `tts49real0904 = passed` |

候选仍是未提交工作树，不得以本文件替代 Git 提交身份。用户本轮只授权施工与隔离 QA，没有授权提交、推送或长期部署。

## 长期运行态差异

| 项目 | 长期环境 | 候选 |
| --- | --- | --- |
| 数据库 revision | `20260830_0035` | `20260901_0036` |
| 角色保护集合 | 65 表 | 67 表 |
| 能力 | 无 `character_cast_planning` | `narration-capabilities/3` 含整书选角 |
| Plan49 代码 | 未安装 | 本候选已通过 |

长期 health 在最终只读复核时为 `ready`：数据库连接、TTS runtime、production backend 和 worker 正常；模型当前按闲置策略未驻留，但 `model_ready=true`。长期数据库和长期媒体没有被本计划写入。

## 发布门禁结果

- 自动化、隔离 PostgreSQL、迁移矩阵、角色矩阵、全量测试、前端构建、插件打包、宿主契约、Controller、Compose 和 diff：PASS。
- 最终候选安装／强制重装／卸载／重新安装：PASS。
- 卸载后插件路由、PawApp、Skills 和工具零残留；重新安装后数据/卷哨兵保持：PASS。
- 桌面浏览器 `1920×1080`、`2560×1440`：PASS；中文置信度、焦点恢复、滚动/操作区和控制台均符合本轮要求。
- 长期数据库迁移、ACL 写入、候选安装和重启：NOT RUN（未授权）。

## 另行授权后的唯一发布顺序

1. 再次冻结不可变候选 hash/head、长期镜像、插件/bundle、数据库 `0035`、媒体清单、health 与所有外来容器身份，并完成数据库备份。
2. 显式以 `--expected-head 20260830_0035` 对长期库做 65 表只读预检。
3. 进入维护窗，先停止 narration 新任务领取。
4. 以 schema owner 执行 `0035 → 0036`。
5. 应用角色 bootstrap，并显式以 `--expected-head 20260901_0036` 验证 67 表。
6. 安装本文件记录的同一候选并重启；只读核验 health、`narration-capabilities/3`、`character_cast_planning` 与页面入口。
7. 全部通过后才恢复任务领取。

任何步骤失败都保持任务领取关闭，不允许把 `0036` 候选装到仍为 `0035` 的长期库上继续运行。

## 恢复边界

- **A：0036 两张选角表均无正式记录。** 双重计数与 downgrade guard 均确认零记录后，允许降回 `0035`、恢复冻结旧包、重放兼容 ACL 并复核 65 表；该迁移往返已在隔离 PostgreSQL 中通过。
- **B：0036 已有任一正式选角记录。** 禁止降 schema 或删除记录；保持全部 narration fail closed，保留数据库与媒体，进入 `HOLD_0036_COMPAT_PATCH`，等待另行实现并验收兼容补丁。

计划 45／47 的作者听感、真实模型 Provider 成功链和表达风格尖峰仍保持 HOLD/NOT_RUN；它们不是计划 49 发布兼容性门禁的一部分，也没有被本轮自动化代判。
