# TTS35-FINAL：MOSS-TTS-Nano 全功能闭环最终复查

状态：**2026-08-30 源码候选与隔离环境验收通过；`CORE-CANDIDATE=PASS`，`CORE-FINAL=HOLD_DEPLOY`，`VG-FINAL=BLOCKED_HARDWARE`。**

本报告只裁决计划 35 的独立 worktree 与隔离 QwenPaw。候选尚未提交、推送，也未安装到长期 `127.0.0.1:18088`；因此不得把本报告表述为“长期 TTS 全部功能已上线”。

## 1. 范围与发布身份

- 基线提交：`94f6b6644df363234969f0e6882e1b8c3fb1229e`（计划 36 稳定提交）。
- 分支／worktree：`codex/tts35-core`／`AI小说世界2026-tts35-core`。
- Alembic 单头：`20260829_0034`，`down_revision=20260829_0033`。
- PawApp 版本保持 `0.4.0`；本专项没有无关升级九个小说 Skills。
- 最终前端 bundle SHA-256：`166a106bf459d272dd2999d43db2cfb376558ba2e85bd9f9830ffbafbbb78d3e`。
- 最终插件目录有序文件清单 SHA-256：`f0139f0235caa245da5d6120f68ea1261215b40b306afd4a6cdc3450078690b2`；算法为按 UTF-8 相对路径排序后，依次写入 `path + NUL + file_sha256 + LF`，共 234 个文件。
- Sidecar image RepoDigest：`ai-novel-world/moss-tts-sidecar@sha256:e5ed30973cae61ddeba7c13db52edd2f94fe3f952954424d69cb64456fe9e7ff`。
- 适配器能力 fingerprint：`ca1621b8561a0af33ea45c4acb91c0a7b60647bcba763b4d8f31c5b80b2a6ee8`。

隔离环境使用 `127.0.0.1:18089`、独立 PostgreSQL、独立 Sidecar、独立网络和独立媒体卷；没有读取或修改真实用户音色、小说正文、长期数据库或长期媒体。

## 2. 已完成实现

### 2.1 门禁与统一能力

- `narration-capabilities/2` 新增 `character_voice_matching`、`nano_advanced_tuning`、`private_voice_deletion`。
- 唯一 `NarrationFeatureReadinessProvider` 同时驱动设置页、HTTP 路由和 health；schema、Sidecar、worker、存储或删除对账任一失联均 fail closed。
- TTS 生产最低迁移改为“`0032` 位于当前唯一线性祖先链”，不再错误要求全局 head 恰好等于 `0032`；完整新能力仍要求 `0034` schema sentinel。
- 删除 `PRIVATE_VOICE_DELETION_RELEASED`、旧全局删除路由、`stableOfficialVoiceAssignment`、旧六音色限制和重复前端目录常量。
- 最终自查又删除了路由文件内第二套 Nano／人物匹配／删除 DTO，统一由 `backend/narration/schemas.py` 提供一份公共契约。

### 2.2 作者操作闭环

- 18 个官方音色全部可搜索、按语言筛选、可选试听，并可零确认直接设为旁白或人物声音；跨语言只提示、不阻断。
- 人物卡入口一次点击完成“读取权威人物工作区 → AI 生成 `CharacterVoiceBrief/1` → 固定声学基线确定性评分 → 官方音色 CAS 绑定”；模型失败显示一键重试和手动音色库，不回退 UUID 哈希分配。
- 高级调音开放计划冻结的八个参数，异步真实合成与机器验证成功后再 CAS 绑定；失败、响应丢失、缓存串用或 CAS 漂移均不改原绑定。
- 私人音色使用 novel-scoped API；未引用项进入 30 秒可撤销期，已引用项只确认一次影响摘要；支持 `superseded`、精确资产计划、事件唤醒对账和三类崩溃恢复。
- 设置页收敛为“基础朗读、官方音色、人物配音、高级调音、私人音色”五区；章节播放器保留播放、前后段、跳播、倍速、音量、说话人、失败重试和冻结 Edition 身份。

## 3. 自动化与数据库验证

| 门禁 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest` | **PASS**：3383 collected，3239 passed，144 skipped，0 failed／0 errors，28.730 s |
| `pnpm test` | **PASS**：111 files／965 tests |
| `pnpm typecheck` | **PASS** |
| `pnpm build` | **PASS** |
| `scripts/package_plugin.py` | **PASS**，敏感文件与宿主专用文件审计通过 |
| manifest／Skill／QwenPaw 集成契约 | **PASS** |
| `docker compose config --quiet` | **PASS**，仅使用无秘密占位口令解析配置 |
| `python -m compileall -q backend scripts` | **PASS** |
| `git diff --check` | **PASS** |

PostgreSQL 专项在明确的 loopback 一次性数据库中通过：

- `0031 → 0032 → 0033 → 0034 → 0033 → 0034`；fresh → head 也通过。
- 历史 `0021` voice-product schema 契约在单独一次性 PostgreSQL 中 9/9 通过。
- 高级调音覆盖合成失败、进程失败、响应丢失、CAS 漂移、相同 fingerprint 复用和不同 seed／参数隔离。
- 删除覆盖影响变化、摘要过期、job drain 超时、围栏前／unlink 后／finalize 前后恢复和活动唯一槽释放。
- readiness 覆盖启动、关闭、Sidecar 失联、processor／reconciler 崩溃后的统一 fail closed。

复查时曾把同一 `0034` 数据库 URL 错误注入整套历史 PostgreSQL 测试；各历史 fixture 因预期 `0015`／`0021` 等固定 head 而正确拒绝，并删除了该一次性数据库。该错误没有接触长期环境；随后已从空库重建至 `0034`、重装最终候选并恢复 `health=ready`。它不计入通过结果，也形成一条明确规则：全量 pytest 使用默认隔离／跳过门禁，各 migration-head 专项只能使用各自一次性数据库。

## 4. 真实 Nano 与官方 18 音色

固定 requested／actual 模型完全一致：

```text
OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX+MOSS-Audio-Tokenizer-Nano-ONNX
f52645cb467506d8e18e746ddd59482685b74e58+ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae
model fingerprint = 3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d
```

隔离 Sidecar 对 18 个 preset 各完成一条真实试听：18 个 ModelRun 全部 success、18 个音频非空、18 个输出 hash 不同；MediaAsset、attempt 和 ModelRun output digest 全部闭合。逐项 preview／asset／bytes／duration／SHA-256 见 [TTS35-OFFICIAL-18-REAL.json](./TTS35-OFFICIAL-18-REAL.json)。

在随后重建的空 `0034` 数据库中，又对一个合成小说依次执行 18 次旁白直接绑定；18 次均 `selection_still_current=true`，settings version 从 0 单调增至 18。英语和日语音色正确返回 `language_mismatch=true` 但没有阻断，中文六音色返回 false。该 JSON 同时保存全部 profile/version 身份。

## 5. 高级调音、删除与章节朗读实证

### 高级调音

- Zhiming 自定义参数命令 `e3bb791f-765e-5c86-8435-c270ee76edbb`：`ready_applied`，seed `3579`。
- Zhiming 官方默认参数命令 `5bb03a04-f83b-5556-874e-494621655871`：`ready_applied`，seed `1234`。
- 相同 fingerprint 复用命令 `cbbe1d75-60b5-5e9e-9abe-fdbae5218e68`：`reused_version=true`。
- Xiaoyu 边界命令 `1863a838-aa06-5bb3-ba4f-5b1392f3ca4f`：最大 int64 seed，温度／top-p／top-k／repetition penalty 全部使用冻结边界，`ready_applied`；输出 SHA-256 `4db4dc78f1a4d29796d276a3defd929aa3cc203705c1436e4af74354f8bdb66f`。
- 所有成功命令均验证 Version `locked + experimental_machine_validated + machine_validated`、ModelRun requested/actual 身份、参数 digest、媒体 hash 和 cache fingerprint；恢复官方音色再次走官方 fixed 版本，不复制实验参数。

### 私人音色删除

- 未引用合成私人音色创建请求 `5ef0f69a-b855-4dde-8539-817ec9bc8c16` 后进入 30 秒 `grace_pending`，服务端倒计时可取消；对账器自动收敛到 `completed`。
- 精确计划资产已转为 `deleted` 并生成 tombstone `7bb9b059-7967-4b5d-a191-0dbcdb83924c`，物理文件不存在；不可变 Version 和审计证据保留。
- 另验证未引用取消、已引用一次影响确认后取消，以及刷新后的权威影响摘要；官方音色始终没有删除入口。

### 三人物章节

- 合成 Edition `33f00671-053a-4457-bcbf-ab39c23f43db`：14/14 segments，manifest revision 22，总时长 50.52 s。
- speaker 分布：旁白 8、林晚 2、沈川 2、顾砚舟 2；ordinal 为 0..13，零缺口、零重复。
- 8 个高级旁白片段的失败重试后请求收敛为 ready；Edition 中四个声音身份保持冻结。
- 真实浏览器完成播放／暂停、下一段、倍速 `1.5×`、进度与当前说话人检查。音量控件显示 100%，单元／集成测试覆盖更新处理器；当前浏览器自动化无法可靠向 React range 控件注入一次真实音量变化，因此“不遮挡且控件存在”已实测，但该次指针／键盘音量 mutation 不冒充浏览器 PASS。

## 6. 浏览器复验

隔离页面覆盖 `2560×1440`、`1920×1080`、`1280×800`、`390×844`；浏览器框架导致实际截图分别略小。控制台 warning/error 为 0；中文搜索 `明星` 可将 18 项目录筛为 1 项并恢复；键盘焦点环可见。移动端五区导航已改为两列换行，播放器和展开后的原生助手不再互相覆盖。

| 证据 | SHA-256 |
| --- | --- |
| [1920×1080 官方 18 音色](TTS35-UI-RECHECK/1920x1080-official-18-preview-ready.png) | `701da3894b7f06a1d98d9ce4ac9f97e97bf216091aad0956e44f60e103ec938e` |
| [1920×1080 高级调音已应用](TTS35-UI-RECHECK/1920x1080-advanced-tuning-applied.png) | `1094d05623059916435d1e90ed6737f3c37c56020d482c38be03d8db34519b7f` |
| [1920×1080 人物模型失败后的重试与手动音色库](TTS35-UI-RECHECK/1920x1080-character-match-retry-and-manual.png) | `967e60bd2768397d56aa6182f69cf075f4c25f841e162e319e980ce1d7bc581c` |
| [1920×1080 删除一次影响确认](TTS35-UI-RECHECK/1920x1080-private-delete-impact-once.png) | `23eab40f166acd5d3e01639854a7e7efe66d6ec2650516eaaff2e48a55507dbe` |
| [1920×1080 私人音色生命周期](TTS35-UI-RECHECK/1920x1080-private-voice-lifecycle.png) | `000a1cfae2430bddd54ae1404ca42cafebd349f986d7517a703fe537841a0c79` |
| [2560×1440 播放器](TTS35-UI-RECHECK/2560x1440-player-ready.png) | `a8bb79906eee3d8cc43811ff361b305b75776ff6db90220dc888542b51b8be1f` |
| [1920×1080 播放器](TTS35-UI-RECHECK/1920x1080-player-ready.png) | `748ecb6cfb257e98d21c7aa4d2e751c2cb15140fe729b6fddf697563d4d1ff69` |
| [1280×800 播放器](TTS35-UI-RECHECK/1280x800-player-ready.png) | `5d030235a2c482ed9c59f8fe2226d1649813847d349f848eba4d16d13e0e3b94` |
| [390×844 播放器与折叠助手](TTS35-UI-RECHECK/390x844-player-ready-assistant-collapsed.png) | `19f0d75eb8a92e610969f03091173d28e0a78d3979df991028729ad54bfb8cbf` |
| [390×844 展开助手无覆盖](TTS35-UI-RECHECK/390x844-assistant-expanded-no-player-overlap.png) | `713048b2a504caeffca02ab75a3f6ae3c372188195d873f2e6ff7d9ab43f99e7` |
| [390×844 五区导航换行](TTS35-UI-RECHECK/390x844-official-voice-settings-wrapped.png) | `4a99e8fd59ed8fc656b6419bc7cf2749220c0fd789ca5c9284c0818567357f4f` |

隔离 `ai-novel-writer` 没有 active model，因此浏览器真实走到了可重试失败和手动音色库，而没有伪造成功。人物 Brief、确定性匹配、同语言筛选、模型证据拒绝、CAS 成功／漂移和自动绑定成功路径已由后端自动化覆盖；长期部署后仍需用作者当前有效模型补一次真实成功点击，才能关闭 `CAST-REAL`。

## 7. 最终裁决

| Gate | 裁决 | 说明 |
| --- | --- | --- |
| `P0-OFFICIAL` | `PASS_ISOLATED` | 18 项真合成、18 项逐项直接绑定、搜索／筛选／试听可选均通过 |
| `P1-UI-PLAYER` | `PASS_ISOLATED_WITH_VOLUME_TOOL_LIMIT` | 四视口、三人物 Edition 与核心播放控制通过；仅自动化音量 mutation 未形成浏览器证据 |
| `ADV` | `PASS_ISOLATED` | 默认、自定义、边界、复用、失败安全和 CAS 闭环通过 |
| `DEL` | `PASS_ISOLATED` | grace、一次确认、取消、superseded、对账和物理删除恢复通过 |
| `CAST` | `PASS_AUTOMATED / HOLD_REAL_MODEL` | 真实失败恢复通过；真实成功点击待有 active `ai-novel-writer` 的部署环境 |
| `CORE-CANDIDATE` | `PASS` | 源码、迁移、包、隔离运行时和 UI 候选可发布 |
| `CORE-FINAL` | `HOLD_DEPLOY` | 尚未提交／推送／备份并部署长期 `18088`，且长期 CAST 成功点击未验收 |
| `VG-FINAL` | `BLOCKED_HARDWARE` | 当前 M4／16 GiB 不满足 VoiceGenerator ≥24 GiB、建议 32 GiB 门禁；未下载约 10.6 GiB 模型 |

要把 `CORE-FINAL` 改为 `PASS`，后续只允许串行执行：复核并提交本任务 diff → 推送用户指定远端 → 备份长期数据库与媒体清单 → 长期迁移到 `0034` → 安装相同包 hash → 重启 → 只读 health／18 目录检查 → 用当前有效 `ai-novel-writer` 在隔离小说完成一次人物匹配成功点击。任何一步失败都先撤销三项 readiness；已经产生 `0034` 记录后不降 schema，只回退兼容代码并保留数据库／媒体。

## 8. 隔离资源收尾

最终证据固化后已恢复浏览器视口，并精确删除本计划创建的 `tts35-ui-qwenpaw-20260830`、`tts35-nano-advanced-20260830`、`tts35-pgvector-20260830` 三个容器、`tts35-ui-private-20260830` 网络、四个 `tts35-ui-*` 合成验收卷及临时迁移库；`18089`／`8765` 监听端口已释放。这些资源只包含合成小说、合成私人音色和隔离运行数据，删除后不能从运行环境恢复，所需可复核结果已保存为本文、JSON 和截图。

长期 `ai-novel-2026-qwenpaw-lab`、`ai-novel-2026-moss-tts-sidecar`、`ai-novel-2026-postgres` 在清理后仍为 healthy；长期模型卷、密钥卷、数据库卷、用户媒体及不属于本计划的 `tts35-pg-20874-26782` 均未删除或修改。
