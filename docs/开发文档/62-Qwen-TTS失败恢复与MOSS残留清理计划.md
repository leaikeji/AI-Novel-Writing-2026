# 开发计划 62：Qwen TTS 失败恢复与 MOSS 残留清理计划

状态：**V1.0 已完成并 PASS。生产已安装同一校验候选并迁移至 `20260909_0050`；103/107 个失败句段已恢复，剩余 4 个为有明确提示且不可自动重试的音频质量失败；MOSS/Nano/VoiceGenerator/24 槽通用池活跃代码、旧数据、14 张专用表、4 个旧列和共享 scope trigger 旧分支均已移除。1677 个旧 TTS 音频经清单、大小和 SHA-256 复核后按作者明确授权销毁，释放 293,194,837 bytes；当前 Qwen 音频、正文、revision、故事账本和非 TTS 媒体未删除。完整插件生命周期、数据库四角色、全量自动化、长期健康、真实浏览器播放和媒体 Range 均通过。阿里云真实凭据 smoke 仍是计划 59/61 的独立待验收项，不阻断本计划结项。**

日期：2026-09-09（Asia/Shanghai）

## 1. 目标与边界

在不改变小说正文、不建设第二套 TTS 架构的前提下完成两件事：

1. 恢复当前章节朗读中观察到的 107 个失败句段，让已有 Edition 尽可能恢复为连续播放；
2. 删除现行系统中只服务于 MOSS/Nano/VoiceGenerator/24 槽通用音色池的残留数据、结构、代码、接口和 UI 分支。

本计划承接计划 59 的“历史失败恢复与旧 TTS 物理清理”。Qwen 本地／云端 Provider、Provider 中立的 `design_voice`／`clone_voice`、声音档案、Qwen 试听、章节脚本、Edition、媒体、缓存、重试和播放器继续保留。历史迁移、历史计划、ADR 和原始验收证据保留当时事实，不追求全仓库零 `MOSS` 字符串。

## 2. 已核实现状

### 2.1 107 个失败分为两类

- 103 个句段是迁移期间数据库发布闭包仍要求 `moss-nano` 导致的历史失败；迁移 `20260909_0047` 已把现行闭包改为 `qwen-tts`，但历史失败状态不会自动消失。
- 4 个句段因本地 Qwen 音频质量校验 `SHORT_CHINESE_DURATION_IMPLAUSIBLE` 失败，位于第 4、13、24、71 句；不能与前 103 个假定为同类问题。
- 当前数据库已经到 `20260909_0048`，QwenPaw、PostgreSQL、本地 Qwen3-TTS 和 worker 健康；同章前三段已经通过现行重试链恢复并在真实浏览器播放。
- 现有重试 API 一次接受 1–100 个唯一 `segment_ids`，并具备 CAS、幂等键、fanout 和权限校验；无需新增批处理服务。

“103／4／107”都是当前观察值，施工时只用于复核，不作为硬编码参数。真正提交对象必须来自最新失败投影。

### 2.2 数据库仍有真实旧引用

复核时的旧链数据计数如下，施工前必须重算并输出 ID 清单和哈希：

| 对象 | 当前计数 |
| --- | ---: |
| `nano_voice_experiment_commands` | 0 |
| `voice_generator_commands` | 34 |
| `voice_generator_run_evidence` | 23 |
| `generic_voice_design_drafts` | 24 |
| `generic_voice_generation_commands` | 29 |
| `generic_voice_pack_versions` / slots | 6 / 144 |
| `generic_voice_pools` / slots | 2 / 48 |
| `voice_preparation_commands` / items | 5 / 30 |
| `voice_design_drafts` | W0 重新计数 |

旧声音版本还被人物绑定、匿名说话人和历史 Edition 句段引用。现有代码也仍在 `script_versions.py`、`editions.py`、`authority_locks.py`、`review_actions.py`、`voice_deletion.py` 和 `casting.py` 读取通用池／槽位，因此不能先删表。

### 2.3 表与能力裁决

| 分类 | 对象 | 裁决 |
| --- | --- | --- |
| 删除 | `nano_voice_experiment_commands` | Nano 专用，即使空表也删除 |
| 删除 | `voice_design_drafts`、`voice_generator_commands`、`voice_generator_run_evidence` | 含 MOSS VoiceGenerator runtime／状态约束，不迁移为 Qwen 表 |
| 删除 | `voice_preparation_commands`、`voice_preparation_items` | 旧章节自动准备命令链已无运行调用者；不同于 Provider 中立的准备 DTO |
| 删除 | `generic_voice_design_drafts`、`generic_voice_generation_commands`、`generic_voice_pack_versions`、`generic_voice_pack_version_slots`、`generic_voice_pools`、`generic_voice_slots` | 24 槽生成与分配链整体退出 |
| 删除 | `character_cast_plan_commands`、`character_cast_plan_items` | W0 施工清单发现的漏项；运行模块已在前序迁移中退出，表仍固定 `onnx.*` 预设并保存旧自动选角结果，不属于现行 Qwen 人物绑定 |
| 收缩 | `voice_casting_rules`、`anonymous_speakers`、`narration_edition_segments` 里的 pool／slot 外键和字段；相关 check、trigger、function、索引 | 先处理引用，再删除旧列／分支 |
| 收缩 | `voice_rights_records.source_kind` 和声音版本 activation／validation 约束 | 删除 `voice_generator`、`preset_catalog` 旧来源和三种旧 activation basis；本计划不顺带发明新的持久化音色设计模式 |
| 保留 | `voice_previews` | 现行 Qwen 官方试听仍使用；只清理旧数据、Nano 注释和不兼容证据 |
| 保留 | `voice_reference_asset_links`、`voice_action_commands`／receipts、声音档案／版本／权利、媒体、任务、Qwen Provider | 仍属于现行 Qwen 能力或通用基础设施 |
| 保留 | `TTSVoicePreparationRequest/Result`、`design_voice`、`clone_voice` | Provider 中立能力；不得因名称含 preparation 而误删 |

Qwen 音色设计／克隆适配能力继续保留，但本计划不重建已删除的 MOSS 人物一键生成工作流。以后若要把 Qwen 设计结果长期写入声音档案，应另做一个小型、Provider 中立的应用闭环，不复活旧表。

## 3. 迁移后的声音规则

为避免删掉通用池后产生隐性换声，冻结以下最小规则：

- 当前和新建朗读不再产生 `GENERIC_SLOT` casting target，也不再发布 `W_GENERIC_VOICE_FALLBACK`；现行 `generic_pool=None` 成为唯一新写路径。
- 人物绑定若已指向可用 Qwen 声音版本则原样保留；若指向 MOSS/Nano/旧生成版本，则解绑为 `unset`，不根据性别或名称自动猜测新音色。
- 匿名说话人若已直接指向可用 Qwen 声音版本，则保留该版本并清空旧 `slot_id`；若只依赖旧槽位或旧声音，则清空声音引用并显示“需要选择声音”，不静默套用旁白。
- 仅引用旧 Provider／旧槽位的 TTS 派生脚本和 Edition，在 W0 证明属于允许删除的测试数据后删除；正文、working copy、revision 和故事账本不在范围内。
- 若任何正在使用的正式 Edition、人物音色或作者资产依赖旧链，停止物理删除并请求作者裁决，不扩大级联删除。

## 4. 轻量施工方案

### W0：冻结清单、契约与恢复点

1. 重新读取生产健康、唯一迁移 head、当前 Edition／request／manifest 版本和失败原因。
2. 生成只读 dry-run 清单：失败 fanout 组、旧 Provider／模型、旧表、声音绑定、匿名说话人、TTS 派生脚本／Edition、model-run 和媒体；保存精确 ID、计数与哈希到 `audit/qwen-tts/plan62/`。
3. 冻结第三节声音规则和本节表级裁决；检查当前 Qwen Edition 不包含旧 provider、旧 activation basis、pool／slot 引用。
4. 在任何删除前创建数据库 dump 和旧 TTS 媒体清单，并用 `pg_restore --list` 验证 dump 可读。恢复方式是“恢复数据库 dump＋恢复隔离媒体＋退回旧 PawApp 安装树”，不能只退镜像。

门禁：清单不得包含正文、revision、故事账本、Qwen 声音版本或非 TTS 媒体；发现未分类表、函数或正式资产立即停止。

### W1：先恢复当前失败句段

1. 从最新失败投影中只选择 `retryable=true` 的条目，并按 `job_id`／相同 `fanout_segment_ids` 去重，每组只提交一个代表 `segment_id`。
2. 每批最多 100 个代表 ID，使用独立幂等键和最新 CAS；一批完成后等待 worker、刷新失败投影和 CAS，再决定下一批，不按历史“103”盲目提交。
3. 已 ready 的句段不重复生成；出现新错误码即停止该组，不无限重试。
4. 对 4 个质量失败组各允许一次独立本地 Qwen 重试。若仍是同一质量错误，在同一说话人、同一段落边界内优先与相邻短句合并为派生朗读段，再统一新建一个 Edition；不修改正文、不降低质量阈值、不静默切云端。
5. 真实浏览器从首段播放并跨越原失败位置，记录最终 ready／failed、实际 Provider／模型和未调用云端证据。

门禁：当前 Edition 连续可播放，或只剩有明确证据且必须由作者选择声音／分段的失败，才进入代码解耦。

### W2：先断开运行代码对旧结构的依赖

1. 从新写链移除 `GENERIC_SLOT` target/action、通用池快照、自动池规则和旧 warning；把匿名说话人改为第三节的直接声音版本规则。
2. 调整脚本冻结、Edition 创建、权限锁、复核动作和声音删除服务，使其在旧表仍存在时已经不再读取或写入旧表。
3. 删除旧 API／DTO／导出和前端 `voice_generator`、旧 activation basis 兼容；保留 Qwen 试听、Provider 设计／克隆契约。
4. 先在“旧表仍存在”的测试数据库运行新代码回归，证明删表前现行 Qwen 链已经完全脱离旧结构。

门禁：活跃调用图中对待删 ORM 类和待删列的引用为零，Qwen 章节生成、人物／旁白绑定、试听、重试和播放通过。

### W3：精确删除数据、媒体和数据库结构

1. 按 W0 allowlist 从叶子依赖开始删除旧 TTS 测试 Edition／segment／manifest／render／job／model-run／media 关系，再处理旧绑定、匿名槽位、声音版本／档案和旧命令数据；具体顺序由外键图生成，不手写宽泛级联。
2. 旧媒体先移动到计划专用隔离目录；数据库事务和复核通过后才删除隔离副本。任何异常均按 W0 恢复点恢复。
3. 使用一个基于施工时唯一 head 的新 Alembic revision，删除第二节列出的旧表、列、外键、约束、枚举取值、trigger、function 和索引；绝不改写 `0001`–`0048` 历史 revision。
   - 实施说明：`0049` 在生产执行后，隔离生命周期发现共享 `narration_validate_scope()` 仍有静态旧表分支；按照“不改写已执行迁移”的硬约束新增 `0050` 精确前向修复，而未修改 `0049` 历史。
4. 迁移前置断言必须拒绝未列入清单的新引用或非测试数据；迁移本身不执行不可审计的无条件 `CASCADE`。
5. 同步删除 `backend/models.py` 中的旧 ORM，复核 W2 已移除的旧 DTO，并更新 `docker/postgres-roles/protected-tables.sql`、`scripts/tts/validate_database_roles.py` 及其测试。

### W4：只做必要的失败页面优化与集成验收

1. 失败页面按“可恢复／音频质量／暂不可重试”三个汇总组展示，增加“恢复全部可重试句段”按钮，保留单句重试和详细列表。
2. 汇总完全由现有失败投影在前端计算，不新增后端聚合 DTO；批量按钮串行执行最多 100 条／批，并在每批后刷新 CAS。
3. 不借本计划重做播放器、模型设置页或云端路由。

验证：

- 后端定向测试后运行 `.venv/bin/python -m pytest`；
- 前端运行相关 Vitest、`pnpm typecheck`、`pnpm test`、`pnpm build`；`typecheck` 必须执行且本计划不得新增错误，计划 58 保护区既有错误若仍存在则按基线差异报告，不冒充全局 PASS；
- 运行 `.venv/bin/python scripts/package_plugin.py`、数据库角色校验、`docker compose config`、迁移 upgrade／恢复演练和 `git diff --check`；
- 长期环境验证插件安装／升级／完整卸载、QwenPaw 原生页面非回归、本地 Qwen 新建章节、试听、失败恢复、连续播放，以及桌面和窄屏失败详情；
- `rg` 活跃源码扫描排除 `backend/migrations/**`、历史计划、ADR 和原始证据，并保存白名单报告。

## 5. 子代理并行施工设计

本轮只优化计划，不启动子代理。计划获准施工后，仅后端解耦和前端失败页可在契约冻结后并行；数据库、媒体、迁移、长期环境和最终集成保持主代理单一所有。

| 波次 | 工作包 | 类型 | 唯一目标与精确文件所有权 | 前置／禁止触碰 | 验收证据 |
| --- | --- | --- | --- | --- | --- |
| W0 | Q62-A | SER/GATE/MUTEX | 主代理冻结清单、声音规则、API 和恢复点；`docs/开发文档/62-*`、`audit/qwen-tts/plan62/**` | 不写业务数据，不改历史迁移 | 清单哈希、外键图、计数、备份可读 |
| W1 | Q62-R | SER/MUTEX | 主代理经现有 API 恢复失败组并做浏览器播放验收 | 不直改 DB、不切云端、不改正文 | 幂等结果、最终投影、播放证据 |
| W2 | Q62-C | PAR | 后端旧 casting 解耦；仅 `backend/narration/casting.py`、`script_analysis.py`、`script_versions.py`、`editions.py`、`authority_locks.py`、`review_actions.py`、`voice_deletion.py`、`schemas.py` 及对应测试 | A/R 通过；不可改 `models.py`、迁移、Provider 契约 | 调用图为零、定向 pytest、旧表存在兼容验证 |
| W2 | Q62-F | PAR | 失败分组和批量恢复 UI；仅 `frontend/src/narration/chapter-narration-panel*`、`failed-segment-retry-state*`、`contracts*`、`api*` | 复用冻结 API；不可改共享入口和 Provider 选择 | Vitest、类型基线、桌面／窄屏证据 |
| W3 | Q62-D | SER/MUTEX/GATE | 主代理拥有 `backend/models.py`、新 Alembic revision、清理脚本、`docker/postgres-roles/protected-tables.sql`、`scripts/tts/validate_database_roles.py`、迁移／角色测试、正式 DB 和媒体隔离 | C 完成；子代理不得操作 DB／媒体；不改历史 revision | 前置断言、upgrade、恢复演练、残留计数 |
| W4 | Q62-I | GATE/INT/MUTEX | 主代理唯一负责 `frontend/src/workbench-v2.ts` 等共享入口、冲突处理、全量回归、长期安装和最终证据 | C/F/D 完成；不得顺带修计划 58 | 全量命令、浏览器、安装／卸载、最终残留报告 |

共享资源锁：`backend/models.py`、迁移链、数据库、媒体根、`frontend/src/workbench-v2.ts`、`frontend/src/index.ts`、Compose、锁文件和正式运行时均为 MUTEX。子代理不得暂存、提交、推送、删除数据或操作长期环境。汇合顺序为 A → R → C/F → D → I，主代理是唯一集成责任人。

冻结接口：失败句段 GET／POST 路径、最多 100 个 `segment_ids`、CAS、幂等键、Provider 手动选择和 Qwen 声音版本格式不变。前端批量能力只是现有 API 的客户端编排，不增加新服务。

## 6. 与计划 59、计划 61 的门禁关系

- 用户已经明确不会回退 MOSS，本地 Qwen 也已通过真机生成和真实播放。因此，计划 62 的 MOSS 数据／结构清理不再等待阿里云真实 smoke；本条替代计划 59 中“必须先完成云端最小章才物理清理”的旧顺序。
- 阿里云真实凭据、作品级授权、Plus／Flash 实际模型回执和音频响应 smoke 仍是“云端正式可用”的独立发布门，未通过前不得宣称双 Provider 全部验收。
- 计划 61 继续负责多渠道域名、模型映射和密钥配置页；计划 62 不修改其 Provider URL 规则，也不以清理 MOSS 证明云端配置正确。
- 清理完成可以证明“本地 Qwen 主链不再依赖 MOSS”，不能证明“阿里云渠道已可用”。

## 7. 非目标与停止条件

- 不新增队列、数据库、自动云端回退、价格路由或新的音色市场；
- 不借清理重做朗读页面，不重新设计 Qwen Provider；
- 不删除历史迁移、历史 ADR、历史计划和原始验收证据；
- 不删除 `voice_previews` 或 Provider 中立的 voice preparation／design／clone 契约；
- 不自动把旧男声／女声映射到某个 Qwen 音色，不静默让旁白替代人物或匿名说话人；
- 发现正式资产、未分类依赖、删除范围漂移或备份不可恢复时立即停止。

## 8. 批准与退出标准

用户明确回复“开始施工计划 62”后才进入 W0。完成必须同时满足：

1. 当前章节连续可播放，或剩余质量失败已有作者可理解的明确处置；
2. 正式数据库中旧 MOSS/Nano/VoiceGenerator/24 槽数据及专用结构为零，保留对象未被误删；
3. 活跃源码、配置、API 和 UI 不再暴露旧模式，历史命中均在白名单内；
4. 本地 Qwen 新建章节、试听、人物／旁白绑定、重试、播放器和插件生命周期回归通过；
5. 数据库 dump、媒体隔离清单和恢复演练可复核，正文、revision、故事账本和非 TTS 媒体未改变；
6. 阿里云未真实 smoke 时，最终状态明确写为“本地 Qwen 清理完成，云端仍待验收”，不把局部完成冒充双 Provider 全部完成。
