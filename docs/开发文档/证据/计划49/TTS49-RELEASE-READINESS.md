# TTS49 部署前发布审计

状态：**`TTS49-RELEASE-READY=PASS`；长期发布未授权、未执行。**

日期：2026-09-01（Asia/Shanghai）

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
