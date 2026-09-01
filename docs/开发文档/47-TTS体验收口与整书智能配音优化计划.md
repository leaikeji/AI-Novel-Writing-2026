# 开发计划 47：TTS 体验收口与整书智能配音

状态：**源码、自动化、隔离 PostgreSQL、四视口 UI 与客观保音高探针已完成；`TTS47-UX-FINAL=HOLD_AUTHOR_LISTENING`，`TTS47-CAST-FINAL=HOLD_BROWSER_MODEL_PROVIDER`。** 长期部署、Git 提交和推送未授权、未执行。

## 1. 目标与完成口径

本计划分为两个独立裁决：

- `TTS47-UX-FINAL`：人物卡声音页、全局人物配音页、朗读设置和播放器完成减重、共享逻辑、可访问性与真实浏览器复验。
- `TTS47-CAST-FINAL`：旁白、主角和配角可一次点击完成整书联合选角；支持刷新续跑、单目标重试、并发漂移零写入和最终原子绑定。

只有两项均通过，才允许表述为“本轮 TTS 优化完成”。本计划不授权长期部署、Git 提交或推送。

## 2. 冻结产品决策

- 全局人物配音采用“名单＋抽屉”，主页面只保留一个主动作“智能配音全书”。
- 人物卡和全局抽屉复用唯一 `CharacterVoiceConfigurator`。
- 人物卡声音页顺序固定为：当前声音、智能匹配官方音色、生成专属音色、浏览全部官方音色、折叠的私人音色与高级调音。
- 官方音色使用紧凑单选列表；radio＋文字标签是唯一绑定动作，试听和详情不触发绑定。
- 日常界面只显示目录名称，revision、digest 和模型内部名称进入技术详情。
- 私人、上传和 VoiceGenerator 专属音色始终保留；无冲突官方音色保留；撞声时只重配低优先级目标。
- 优先级固定为：旁白、main 主角、supporting 配角、稳定人物 ID。
- 自动分配不新增跨语言结果；没有可评分证据时标记手动处理，不恢复 UUID 哈希算法。

## 3. 播放器冻结方案

- 双 `HTMLAudioElement` 是唯一产品播放后端，并显式启用 `preservesPitch`。
- 删除 Web Audio 倍速播放与重复增益链。
- 保留预加载、跳播、前后段、暂停恢复、进度、音量和 Edition 身份。
- 当前 QwenPaw Chromium 无法证明保音高时 fail closed，不回退到变调播放。

## 4. 智能选角契约

- 能力协议升级为 `narration-capabilities/3`，唯一新增能力键为 `character_cast_planning`。
- DTO：`character-cast-plan-request/1`、`character-cast-plan/1`、`character-cast-plan-list/1`、`narrator-voice-brief/1`。
- 创建请求只含 `timeline_id` 与固定模式 `fill_and_deduplicate`；人物名单、设置版本、目录版本、工作区摘要和 CAS 均由服务端冻结。
- API：
  - `GET /novels/{novel_id}/character-cast-plans`
  - `POST /novels/{novel_id}/character-cast-plans`
  - `GET /novels/{novel_id}/character-cast-plans/{command_id}`
  - `POST /novels/{novel_id}/character-cast-plans/{command_id}/advance`
  - `POST /novels/{novel_id}/character-cast-plans/{command_id}/retry`
- 命令状态：`reserved → analyzing → ready_applied | ready_applied_with_warnings | ready_unapplied | failed | superseded`。
- 目标状态：`pending | analyzing | preserved | scored | assigned | blocked`。
- 每次 `advance` 只分析一个目标；15 分钟租约、随机 fence token、attempt 和 workspace digest 共同保护模型回写。
- 模型调用不占数据库事务；所有可执行绑定在一个短事务中提交。
- 任一人物目录、工作区、旁白设置或相关绑定漂移时整批 `ready_unapplied`，零绑定写入；不提供强制应用旧方案。

人物使用 `CharacterVoiceBrief/1`。旁白使用独立 `NarratorVoiceBrief/1`，证据只允许小说语言、title、genre、subgenre、description、idea、highlight、background、main_plot。模型不得输出 preset ID。

## 5. 求解与事务

按语言分组执行纯 Python 确定性求解：先固定保留声音；在剩余官方音色中最大化主角加权总分；音色未耗尽前不重复；耗尽后优先扩大与旁白、主角和相邻高优先级人物的声学距离；完全同分按官方 manifest 顺序和稳定人物 ID 裁决。

`official_voice_selection.py` 增加 `select_official_voices_atomically(...)`。现有单目标服务委托该批量入口执行一个目标。每个目标仍生成 `VoiceActionReceipt` 和 `VoiceActionCommand`；幂等键由 cast command ID 与 target key 确定性派生；任一 CAS、scope、版本或写入失败回滚整批。

## 6. 数据库

当前线性 head 为 `20260830_0035`。新增：

`backend/migrations/versions/20260901_0036_character_cast_plans.py`

迁移仅新增 `character_cast_plan_commands`、`character_cast_plan_items`、活动命令唯一索引、状态与租约约束、审计关联和 schema sentinel。迁移不得调用模型、绑定声音或处理媒体。

## 7. 场景演绎边界

本计划只执行隔离 `TTS47-EXPR-SPIKE`。不创建 `0037`、生产表、能力键、开关或页面控件；作者听感不可由自动化代判。失败不阻塞智能选角。

## 8. 子代理并行施工设计

| 波次 | 工作包 | 标记 | 所有权 |
|---|---|---|---|
| W0 | `TTS47-G0` | `GATE/SER/MUTEX` | 主代理冻结 Git、计划 44/46、迁移 head、长期 bundle 和锁 |
| W0 | `TTS47-C0` | `GATE/SER` | 主代理冻结能力、DTO、状态机、错误码、事务锁序和 0036 |
| W1 | `TTS47-FE` | `PAR-C/MUTEX` | narration 共享配置器、名单/抽屉、官方音色、样式与测试 |
| W1 | `TTS47-PLAYER` | `PAR-C/MUTEX` | 播放队列、播放器测试与频率探针 |
| W1 | `TTS47-CAST` | `PAR-C` | 纯领域简报、评分、求解器与独立测试 |
| W1 | `TTS47-EXPR-SPIKE` | `PAR/GATE` | 仅隔离脚本与证据 |
| W2 | `TTS47-MIG` | `MUTEX/SER` | 主代理唯一修改 ORM、0036、schema readiness 和迁移测试 |
| W3 | `TTS47-INT` | `INT/SER/MUTEX` | 主代理接入批量绑定、API、provider 和前端公共入口 |
| W4 | `TTS47-QA` | `GATE/SER` | 全量、隔离 PostgreSQL、真实 Nano、浏览器和听感验收 |
| W5 | `TTS47-DEPLOY` | `GATE/SER/MUTEX` | 仅在另行授权后部署 |
| W6 | `TTS47-FINAL` | `INT/GATE/SER` | 主代理复核 diff、冗余和证据；仅按用户要求提交/推送 |

共享锁为 `LOCK-NARRATION-FE`、`LOCK-PLAYBACK`、`LOCK-MODELS-MIGRATION`、`LOCK-DOC-INDEX`、`LOCK-BROWSER`、`LOCK-QWENPAW`。子代理不得提交、推送、操作长期数据库、安装 PawApp、删除媒体或修改未分配文件。汇合顺序：契约 → PLAYER/CAST/FE → 0036 → API/runtime → 前端入口 → 定向测试 → 全量 → 浏览器/听感 → 冗余清理 → 最终裁决。

## 9. 验收与恢复

- 自动化覆盖完整能力矩阵、严格证据路径、优先级/撞声/耗尽/确定性、lease/fence/恢复/重试、模型调用无长事务、批量审计链与整批回滚、所有漂移零写入，以及原单人物接口非回归。
- PostgreSQL 覆盖 `0035 → 0036 → 0035 → 0036`。
- 前端覆盖抽屉、焦点、Escape、IME、错误恢复和活动命令续跑。
- 浏览器覆盖 `2560×1440`、`1920×1080`、`1280×800`、`390×844`。
- 播放器最终 PASS 同时需要频率探针和作者真实听检。
- 0036 已有正式记录后不强制降 schema；回退时关闭 `character_cast_planning` 并保留记录。活动命令由租约恢复，无法恢复则 `superseded`，不得修改绑定。

## 10. 实施与复查结果（2026-09-01）

### 10.1 已完成

- 能力 v3、DTO、命令状态机、单目标 lease/fence、旁白简报、全局求解、原子批量官方绑定、API、`0036` 与前端恢复链已经接入。
- 人物卡和全局抽屉复用唯一声音配置器；全局人物配音收敛为名单＋抽屉；官方音色、设置页、高级调音、容量、历史失败和恢复进度完成减重。
- 双媒体元素播放器与 `preservesPitch` 已接入，Web Audio 变速后端和重复增益链已删除。
- 复查额外关闭四项真实缺陷：VoiceGenerator 不可用时的空标题、折叠高级区仍可聚焦、移动抽屉被宿主侧栏压住、模型全部失败却误报“已安全应用”。
- 隔离 PostgreSQL 迁移往返、相关服务、全量前端、类型检查、构建、插件打包、宿主契约与 Compose 均通过；完整结果以[计划 47 证据](./证据/计划47/README.md)为准。
- 浏览器覆盖四个冻结视口；设置页可访问全部 18 个官方音色；抽屉 Escape、焦点恢复、移动全屏、刷新找回失败命令和零绑定漂移均有隔离证据。
- Edge/Chromium `152.0.4191.53` 的 220/440 Hz、11 档正向保音高探针与负对照均通过。

### 10.2 未越界与未完成

- 隔离环境没有配置真实 `ai-novel-writer` 模型 Provider，故只验证了模型失败、重试、刷新恢复和零写入，没有伪造成功整书选角浏览器证据。
- 作者尚未使用真实章节完成旁白、男声、女声主观听检，客观频率探针不能替代该门禁。
- `TTS47-EXPR-SPIKE` 未执行；没有创建 `0037`、生产表、能力键、开关或页面控件。
- 没有迁移或安装长期环境，没有修改真实小说、真实绑定、真实音频或长期媒体。

### 10.3 当前裁决

- `TTS47-UX-FINAL=HOLD_AUTHOR_LISTENING`
- `TTS47-CAST-FINAL=HOLD_BROWSER_MODEL_PROVIDER`
- `TTS47-EXPR-SPIKE=NOT_RUN`

只有前两项分别完成真人听检和真实模型 Provider 成功全链后，才能表述为“本轮 TTS 优化完成”。
