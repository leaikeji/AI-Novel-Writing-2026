# TTS55-G0／C0：开工准备基线

日期：2026-09-03（Asia/Shanghai）
状态：**PASS；允许进入计划 55 W1 源码施工，不授权迁移、长期部署、Git 提交或推送。**

## 1. 范围与授权

- 用户已批准计划 55，并要求完成所有开工前准备。
- 本阶段只做只读运行核验、契约冻结、计划修订和基线测试。
- 没有创建 `0040`、运行 VoiceGenerator／Nano 合成、修改长期数据库、安装 PawApp、提交或推送。

## 2. Git、迁移与工作树

| 项目 | 冻结值 | 结论 |
| --- | --- | --- |
| 分支 | `main` | PASS |
| HEAD／origin | `c241b90d8096acca6542bf551b2e2cc188cf2f8e` | 精确一致 |
| 计划 52 | `c241b90 perf: 优化长篇写作与向量检索链路` | 已稳定交接并推送 |
| 源码 Alembic head | `20260902_0039` | 唯一 head |
| 长期数据库 head | `20260902_0039` | 与源码一致 |
| `0040` | 不存在 | 无迁移号冲突；计划 55 固定使用 `20260903_0040` |
| `git diff --check` | PASS | 无空白错误 |

开工前剩余 11 个源码／测试候选清单 digest 为 `4ec46416cdb42cd0c9e0c6979c37ced61578b6cc78c500cb31ac5ec27ce2b789`。它们已逐项归类：默认 Junhao 初始化候选属于计划 55；人物声音抽屉滚动与遮罩层级属于此前已确认的 TTS UI 修复。施工必须保留这些用户改动，不得覆盖或拆走。

## 3. 长期安装与模型身份

| 项目 | 冻结值／状态 |
| --- | --- |
| 长期候选树 SHA-256 | `90f1a601546ccbc458e557a65a9c9b421d6e3b1413bd50dda9d4f3b68dd5fc03` |
| 长期前端 bundle SHA-256 | `4266dd7ab435c9b949226e45d9e2b2923e643d5792505150045436ee04228c3a` |
| QwenPaw image | `sha256:ea2c0858b94a6522821cceb73593bbea5f02c85fee2f08a8d7386ea90d9f15b1`；healthy |
| Nano Sidecar image | `sha256:9af6a3224be51267f7e59687387a8d4585cf79c4fed6aed5e0986217fdbce632`；healthy |
| PostgreSQL image | `sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a`；healthy |
| PawApp | health `ready`，数据库 connected，Narration runtime／worker ready |
| Nano | `moss-tts-sidecar/1.1`；fingerprint `3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d`；模型未驻留 |
| VoiceGenerator host | `READY`；runtime fingerprint `f39979f7a522a4db308968d3e00b3ba217b9e154a04967c329d5adfabc2b79b7` |
| VoiceGenerator revision | `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4` |
| Audio Tokenizer revision | `3cd226ba2947efa357ef453bcad111b6eafba782` |
| 模型来源清单 SHA-256 | `5ce7e9270c136bb41dd0ac46020520e2bedab19c52c56722f630a2f351085a1d` |
| 24 槽目录 SHA-256 | `be117304b7e636d004772d08ed0b8c1a25e29981d7869f0cf6164502184e8a98` |

模型核验只调用无密钥输出的 host verify 和 PawApp health；没有加载模型或读取、输出 token。

## 4. C0 契约裁决

- 能力契约升级到 `narration-capabilities/4`，新增 `automatic_character_voice_generation`；通用包 building 只造成 feature-level degraded。
- API、状态机、说话人摘要、continuation fence、24/24 原子激活、reject／regenerate 和逐小说投影语义以计划正文第 4–6 节为准。
- W1 实施时发现 `generic-voice-generation-command/1` 命令态未单独列出；在不改变既有产品语义的前提下补冻结为 `queued → building → ready | failed | cancelled | superseded`，槽状态仍为 `pending | generating | validated | reused | rejected | failed`。
- job kind、scope、固定 mode 和稳定失败码已经写入计划正文第 6.5 节。
- 新迁移固定为 `20260903_0040_automatic_voice_preparation_and_generic_pack.py`；只有主代理可修改 ORM、迁移和共享 DTO。
- 首版通用包只允许 `zh-CN`；英文／日文不得使用中文通用槽。

## 5. 基线验证

| 命令／检查 | 结果 |
| --- | --- |
| `.venv/bin/python -m alembic heads` | `20260902_0039 (head)` |
| 长期只读 `alembic_version` | `20260902_0039` |
| `docker compose config --quiet` | PASS |
| 三容器 health＋PawApp health | PASS |
| VoiceGenerator host `--mode verify` | `READY`，无秘密输出 |
| 根目录 `pnpm test` | 140 个文件／1,184 项 PASS |
| 根目录 `pnpm typecheck` | PASS |
| 根目录 `pnpm build` | PASS；只更新被忽略的 `frontend/dist` |
| 默认旁白 PostgreSQL 专项收集 | 49 项 SKIP；两个明确隔离数据库变量均未配置 |
| `git diff --check` | PASS |

准备阶段发现计划原先的 `pnpm --dir frontend` 已过期：当前 `package.json`、Vitest 和 TypeScript 配置位于仓库根目录。计划已改为根目录命令；第一次错误调用没有执行测试、没有产生源码改动。

数据库专项 SKIP 不冒充通过。W1 实施后必须创建或使用名称、用户和 loopback 均满足测试保护规则的隔离 PostgreSQL，再执行默认旁白、`0040` 和并发恢复测试；长期数据库只允许发布阶段的只读检查。

## 6. 开工裁决

`TTS55-G0=PASS`，`TTS55-C0=PASS`。计划 52、迁移序列、长期运行身份、模型身份、目录、共享锁、DTO／状态机和错误码均已冻结；可以从 `TTS55-A-DEFAULT`、`TTS55-B-PREP`、`TTS55-C-POOL`、`TTS55-D-UI` 进入 W1。最终集成、数据库迁移、真实模型、长期发布和 Git 操作仍保留各自门禁。
