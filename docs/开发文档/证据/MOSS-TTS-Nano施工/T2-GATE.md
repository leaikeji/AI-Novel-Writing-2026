# T2-GATE 声音与朗读设置集成门禁

状态：**`PASS_WITH_EXPLICIT_T3_PLUS_HOLDS_AND_OPERATIONAL_CLEANUP`。T2-B～T2-H 已完成真实 QwenPaw 安装、29 路由、PostgreSQL 18、1920×1080／2560×1440 浏览器、深链接刷新、卸载／重装和数据保留验收；T3-A 进入下一 ready set。T2 只放行朗读设置闭环，不放行正文分析、自动人物识别／选角、合成、播放器、编辑器同步、reference clone、生产通用音色、云端辅助、缓存删除或 VoiceGenerator。**

日期：2026-08-26（Asia/Shanghai）

基线：`2caab228af15d5e4a5e858264799a67aede62f3d`（`main` 与 `origin/main`）；当前施工仍在未提交工作树中，本阶段未获 Git 提交或推送授权，未暂存、提交或推送。

## 1. 最终门禁裁决

| 项目 | 实际结果 | 裁决 |
| --- | --- | --- |
| T2-B～T2-H 局部实现与共享接线 | 已汇合并经两轮红队、真实宿主和浏览器复核 | 接受 |
| T2-A wire/API/DTO | 21 URL、29 HTTP 操作、5 个 schema version、14 capability、27 error code 未漂移 | 接受；见第 2 节 source re-freeze |
| PostgreSQL 18 首写 CAS | 一次性隔离库真实锁等待、唯一赢家和输家 CAS 冲突通过 | 接受 |
| 正式项目数据库 | 同一 `ai_novel_world_2026` 库从 `0009` 升到 `20260826_0015 (head)`；未创建 TTS 专用第二数据库 | 接受 |
| 标准安装／热更新 | 两次修复后完整安装均一次通过；公开 health 有界等待消除启动竞态 | 接受 |
| 29 个真实 HTTP 操作 | 29/29 命中契约路由、29/29 `no-store`、0 个未注册／方法不匹配 | 接受 |
| 真实浏览器 | 1920×1080、2560×1440、助手收起／展开、深链接／刷新／前进后退、人物卡声音页签通过 | 接受 |
| uninstall→原生宿主→reinstall | 插件路由、Skills、tools 卸载清零；原生聊天／设置／模型／Agent 正常；重装完整恢复 | 接受 |
| 数据与卷保留 | 作品数 5→5，作品列表响应 SHA-256 完全一致，迁移仍为 `0015`，3 个 QwenPaw 命名卷保留 | 接受 |
| 低于 1920×1080 的布局 | 用户于 2026-08-26 明确改为非目标 | 不作为门禁；既有 390/720 修复保留 |
| 旧临时 installer 容器条目 | 一个 `Created` 条目因 Docker Desktop 删除调用持续挂起；不运行、不被标准安装使用、未删除卷 | 非阻断运维清理项 |

受支持范围内没有尚未解释的代码级 P0/P1。T2-GATE 因此通过，但只能释放 T3 的脚本、场景和选角施工，不能把后续能力提前翻转为可用。

## 2. T2-A 契约复核与实现源 re-freeze

### 2.1 保持字节一致的冻结源

| 文件 | 当前 SHA-256 | 结果 |
| --- | --- | --- |
| `backend/narration/schemas.py` | `1e189e812cf674b0d9457328d4e74e95fda57a67b62a83f99eb31d299633fdbd` | 与 T2-A 一致 |
| `frontend/src/narration/contracts.ts` | `9a62723164027da7607ee4df0dc39bd61e9c21e89519d6cfb13352dfb66fc5ec` | 与 T2-A 一致 |
| `frontend/src/narration/api.ts` | `2c675603fe7e19b0d2dcf362015a432a2fe1cf36920b4096bf52c8a479b9dce8` | 与 T2-A 一致 |

### 2.2 `settings_api.py` 的显式实现源 re-freeze

- T2-A 历史 SHA-256：`05b1a6be9ab58d30ccb12d143033a96aa8feb9fec7a6ed7ad1a6560894505378`；历史记录保留，不覆盖。
- T2-GATE 当前 SHA-256：`5f2236868892992d7c62cdcac4bdb1db20b34c05fb885adf225eeba77c240afb`。
- 裁决：`AUDITED_IMPLEMENTATION_HARDENING_REFREEZE`。
- 漂移原因：GATE 内加入领域异常适配、授权／no-go 加固，并把运行时 import 改成 PawApp namespace 可热加载的 package-relative import。
- 独立只读审计实际复验：Python 契约/API 两文件 `90 passed`；前端 contract/API `22 passed`。

审计确认当前实现仍为 21 个唯一 URL、29 个 method/operation；5 个 schema version、14 capability、27 error code 及 HTTP 映射、5 个必需 `Idempotency-Key`、consent DELETE body、archive query CAS、其余 JSON DTO、上传 raw multipart、response model/status 均与 T2-A wire invariant 一致；不存在 synthesis、player、VoiceGenerator 或 automatic-speaker 路由。因此本节只 re-freeze **implementation source**，`narration-settings-api/1` 版本不变。T2-A 没有保存旧源码快照，故这里只声明语义等价审计通过，不声明新旧文件 byte-identical。

## 3. 接受的产品边界

当前 factory 只让以下设置能力可见、可读，并在存在合法资源和授权时可配置：

- `narration_product`；
- `reading_settings`。

真实页面诚实显示“章节播放与校听将在 T4 完成后接入，目前不可用”。下列能力继续保持各自冻结的 HOLD／UNAVAILABLE：

- 正文分析、自动人物识别、匿名说话人和自动选角；
- 正式脚本冻结、Edition、合成、播放器和编辑器跟随；
- preset、reference clone、VoiceGenerator、试听和上传音色合成；
- 24 槽生产通用音色和自动通用选角；
- 云端辅助分析；
- 缓存清理和彻底删除。

当前没有合法锁定音色资产，页面不会伪造声音下拉、试听或 24 个生产音色。对应保存／试听／锁定按钮按服务端 capability 和资源状态真实禁用。

## 4. 真实 QwenPaw、HTTP 与运行态

### 4.1 运行拓扑

最终运行中的本项目容器：

| 容器 | 状态 | 用途 |
| --- | --- | --- |
| `ai-novel-2026-qwenpaw-lab` | healthy | QwenPaw 2.1.0 与 PawApp |
| `ai-novel-2026-postgres` | healthy；PostgreSQL 18.6 | 项目唯一业务数据库 |
| `ai-novel-2026-moss-tts-sidecar` | healthy | 固定 Linux/arm64 Nano Sidecar |

`tomato-novel-webui-docker` 属于其他项目，整个阶段未停止、删除或改写。TTS 没有新增 Redis、队列数据库或第二个 PostgreSQL。

安装后的公开验证：

- PawApp `ai-novel-world-2026@0.4.0`、health `ready`；
- narration `technical_enabled=true`、`lifecycle_status=ready`、Sidecar reachable、model ready；
- protocol `moss-tts-sidecar/1.1`，模型 fingerprint 与固定值一致；
- `product_visible=false` 保持完整朗读产品门禁关闭；
- AI 小说作家继续使用 `minimax-cn / MiniMax-M2.7`；9 个小说 Skills 和 5 个工具只在 `ai-novel-writer` 启用，其他 Agent 均为 0 enabled。

### 4.2 29 个真实 HTTP 操作

使用冻结 `_api_cases()` 和不存在的测试 UUID 调用 loopback `127.0.0.1:18088`，避免任何业务写入。结果：

| 项目 | 实际值 |
| --- | --- |
| HTTP 操作 | 29 |
| `Cache-Control: no-store` | 29 |
| 状态分布 | 404×18、409×8、503×3 |
| 契约错误分布 | `RESOURCE_NOT_FOUND`×14、`VOICE_PROFILE_NOT_FOUND`×4、`CAPABILITY_DISABLED`×8、`PREVIEW_UNAVAILABLE`×1、`STORAGE_UNAVAILABLE`×2 |
| 未注册或 method mismatch | 0 |

这里的 404 都带冻结结构化错误码和 `no-store`，是领域资源不存在，不是路由未注册。QwenPaw 关闭公开 OpenAPI，故没有把 `/openapi.json` 的宿主 404 当成业务路由证据。

## 5. 真实浏览器验收

本节记录 T2 当时已验证的 1920×1080 和 2560×1440 历史证据，页面、原生左侧宿主导航和右侧助手栏无横向溢出或相互遮挡。2026-08-27 的最终发布合同已取代“1920×1080 及以上”的模糊口径：后续 TTS UI 且仅验收 1920×1080、2560×1440 各自助手收起／展开的四个精确组合；低于 1920×1080、移动、窄屏和 200% 等效小视口不设计、不测试、不阻断发布。

已完成：

- 创作中心真实“朗读”入口和作品工作台“朗读”导航；
- 总览、旁白、人物配音、通用音色、选角规则、发音与停顿、音频与缓存七个页面逐项切换；每次恰有一个 `aria-current=page`；
- `section=reading&reading_panel=characters` 在宿主清理 query 后仍恢复；从裸 `/chat/<session>` 再次刷新仍保持人物配音；
- back/forward、显式 URL 覆盖旧 session、离开朗读后重新进入总览；
- `history.replaceState` 保留宿主 state 和 hash，不新增面板级历史项；
- 人物卡“人物资料／声音”是完整 `tablist/tab/tabpanel`，ArrowRight 可把焦点和选中态切到“声音”；
- 助手收起为 52px inline；展开在空间不足时 overlay，折叠按钮保持可见可操作；
- HOLD 页面只显示真实状态，未发出音色写入、合成或播放器请求；
- 控制台 0 error；仅有一个既有宿主 warning：`[moduleRegistry] Module not found: AppCenter`，不是 TTS 产生。

证据截图：

- [`reading-1920x1080-final.png`](./T2-GATE/reading-1920x1080-final.png)
- [`reading-2560x1440-final.png`](./T2-GATE/reading-2560x1440-final.png)

390×844、720×900 和 960×540 的历史／诊断截图仍保留用于问题追踪，但根据用户最新范围决定，它们不是本阶段或后续阶段的发布门槛。

## 6. uninstall／reinstall 与数据保留

### 6.1 卸载前基线

- PawApp 安装数：1；作品数：5；作品列表响应 SHA-256：`7f8cf2bc05343b318a1b9f461c56c9dc1b4edeeb5c90e17349d71d11caea4e03`；
- migration：`20260826_0015 (head)`；
- 3 个 QwenPaw 命名卷均存在：data、secrets、backups；
- 三个 Agent 均可发现 9 个 plugin Skills 和 5 个 novel tools，但只有 `ai-novel-writer` 启用它们。

### 6.2 官方公开卸载后的事实

- `/api/ai-novel-world-2026/health` 和插件业务路由返回 404；`/api/pawapps` 中该 PawApp 数量为 0；
- 三个 Agent 的 plugin Skill 数和 novel tool 数均为 0；
- QwenPaw `/`、`/chat`、`/settings` 均为 200；原生 Agent 和 effective model API 为 200；
- 真实浏览器不再存在 `.anw-workbench-frame` 或朗读页面，原生聊天输入与设置导航仍可用；
- PostgreSQL、Sidecar、QwenPaw 仍 healthy；数据库 migration 仍为 `0015`、作品表仍为 5 行；3 个命名卷均保留。

### 6.3 重装后的事实

- 标准脚本完整重跑并一次成功：测试→构建→打包→官方 hot install→Alembic→Agent 配置→公开 health ready→final verify；
- PawApp 数量恢复为 1；9 Skills／5 tools 恢复，仍只在 AI 小说作家启用；
- 作品数仍为 5，响应 SHA-256 仍是 `7f8cf2bc05343b318a1b9f461c56c9dc1b4edeeb5c90e17349d71d11caea4e03`；
- migration 仍为 `20260826_0015 (head)`；
- 浏览器人物配音深链接、宿主规范化后的刷新恢复和正式布局再次通过。

没有删除数据库、正文、revision、媒体或 QwenPaw 命名卷。

## 7. 自动化、构建与打包

| 命令／链路 | 实际结果 |
| --- | --- |
| `.venv/bin/python -m pytest` | `741 passed, 87 skipped, 1 warning` |
| `pnpm test` | `55 files / 448 tests passed` |
| `pnpm typecheck` | PASS |
| `pnpm build` | PASS；`frontend/dist/index.js` 2,208.21 kB，gzip 763.54 kB |
| `.venv/bin/python scripts/package_plugin.py` | PASS；生成 `build/ai-novel-world-2026` |
| `QWENPAW_EXPECT_TTS_RUNTIME=ready ... qwenpaw_lab_plugin.py install` | 两次修复后完整执行均 PASS |
| `qwenpaw_lab_plugin.py uninstall --confirm ai-novel-world-2026` | PASS |
| `verify_qwenpaw_lab.py` | runtime ready、Agent/Skill/tool/model 隔离 PASS |
| `docker compose config --quiet` | PASS |
| `git diff --check` | PASS |

Python 的 87 个 skip 是条件环境测试；一次性 PostgreSQL 18 的 11 项真实并发用例已另行执行并通过，不能与普通 pytest 的 skip 混为同一次输出。

第一次真实热安装暴露 final verify 早于 narration runtime ready 的竞态；该次安装本身成功，约 0.2 秒后独立 verify 通过。安装器随后改为轮询公开 PawApp health 的 30 秒有界等待，不使用固定 sleep；disabled／ready、瞬态→ready、超时、非法期望和错误透传均有测试。修复后的两次完整安装都一次通过。

## 8. 显式 HOLD、非目标和运维清理

1. 低于 1920×1080 的布局和 200% 等效小视口按用户 2026-08-26 最新决定不再施工或阻断发布；后续 T3–T6 的 UI 验收同步采用该下限。
2. `ai-novel-2026-plugin-installer-t2` 是早期 Docker Desktop bind-mount 故障留下的 `Created` 容器条目。两次精确 `docker rm -f` 均在有界 8 秒后超时；它没有运行，不是当前标准安装器资源，也没有删除任何卷。为避免中断另一个项目，未擅自重启 Docker Desktop。后续只有在用户明确允许维护窗口时才重启 Docker 并精确删除该容器；不得批量 prune 或处理番茄项目容器。
3. `reference_clone_visible`、`generic_voice_pool_enabled`、`automatic_casting_enabled`、`cloud_assisted_analysis_enabled`、`product_synthesis_enabled`、`product_player_enabled`、`voice_generator_visible` 和缓存清理继续为 false／HOLD。

上述项目不改变 T2 设置闭环的正确性，也不授权越过后续阶段门禁。

## 9. 恢复与回退

- PawApp 可用官方 DELETE 卸载；卸载后插件路由、Skills 和 tools 已证明可完全清除，原生 QwenPaw 恢复。
- T2 代码回退只移除 narration router/factory、前端 reading 接线和 T2 局部模块；不回写迁移历史、不删除声音权利／设置历史、不修改正文或 Edition。
- 数据库已经升级到线性 head `0015`；恢复使用现有备份和向前修复迁移，不改写已执行 migration。
- Sidecar 故障保持 fail-closed，不静默切换第二运行时，不修改 QwenPaw 上游核心。

## 10. 下一 ready set

T3-A（SER）现在可开始冻结 `narration script/segment`、范围和 ID 契约。T3-A 通过后可释放 T3-B、T3-C、T3-D、T3-E、T3-F、T3-G、T3-H 和测试先行的 T3-I，严格按本文档各自文件所有权并行；T3-GATE 前仍不得启用自动人物识别、自动选角或正式脚本冻结产品能力。
