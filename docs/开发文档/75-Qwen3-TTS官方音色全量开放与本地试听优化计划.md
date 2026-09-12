# 开发计划 75：Qwen3-TTS 官方音色全量开放与本地试听优化计划

状态：**V1.0 已部署到正式 `18088` 并通过 9 音色真实本地试听、桌面页面、数据库与保态验收；隔离生命周期中的 Docker Desktop 启动异常按原始失败证据保留，不倒写为通过。**

日期：2026-09-12（Asia/Shanghai）

## 1. 目标与完成边界

在不改变现有本地／云端双 Provider 主架构、不引入新模型和新基础设施的前提下，修正当前“模型有 9 个官方音色、产品只显示 2 个且不能试听”的缺口：

1. 本地 `Qwen3-TTS-12Hz-1.7B-CustomVoice` 的 9 个官方固定音色全部进入产品目录；
2. 9 个音色都可以在页面点击并通过本机 Qwen 生成一段短试听；
3. 本地与云端可用性分别展示，不为缺少证据的音色虚构云端对应关系；
4. 保留现有旁白／人物直接选用、章节生成、局部重生、缓存和播放器链；
5. 修正前端硬编码“18 项／正在加载 18 个”的错误数量；
6. 不新增队列、数据库表、容器、模型常驻调度器或 QwenPaw 上游改动。

本计划的“全量”只指当前冻结的 Qwen3-TTS 12Hz 1.7B CustomVoice 官方 9 个固定 speaker，不包含 VoiceDesign 动态设计音色、Base 克隆音色或阿里云渠道的全部声音市场。

## 2. 已核实的当前事实

- 本机实际模型为 `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit`，固定 revision 为 `41d3337e8b7f2843a75841595fc14e4b9a7a4b96`。
- 本机模型 `config.json` 已包含 9 个 speaker：`Vivian`、`Serena`、`Uncle_Fu`、`Dylan`、`Eric`、`Ryan`、`Aiden`、`Ono_Anna`、`Sohee`。
- 2026-09-12 正式 `18088` 健康接口显示 QwenPaw、数据库、朗读 production backend 和 worker 均为 `ready`；正式 `/voice-presets` 实际只返回 `qwen.WarmFemale/Serena` 与 `qwen.ClearMale/Aiden`。
- `backend/narration/official_presets.py`、前端常量、测试以及迁移 `20260909_0045` 都把目录和数据库闭包固定为两个音色；`0046` 又前向修正了闭包中的 `local_model_revision` 键，新迁移不能倒退为旧错误键。
- 后端目录把 `previewable_now` 固定为 `False`；`backend/app.py` 又明确传入 `voice_product=None`，因此现有官方试听请求只能返回 `PREVIEW_UNAVAILABLE`。前端虽然保留轮询与播放代码，但生产端没有可调用实现。
- 计划 59 当时为了先完成 MOSS 迁移，主动采用两个跨 Provider 逻辑映射并删除旧 voice-preparation 前置流程。这是迁移期收缩，不是 Qwen3-TTS 或 MLX 的模型能力限制。
- 现有两个阿里云 voice ID 是冻结的配置映射，尚未完成计划 61 的真实云端凭据 smoke；“存在映射”不能写成“已验证可用”，也不代表本地与云端声学等价。
- 当前前端仍有“18 项／正在加载 18 个官方音色”的静态文案，与实际两项目录矛盾。

权威资料：

- Qwen3-TTS 官方仓库与 CustomVoice 调用：<https://github.com/QwenLM/Qwen3-TTS>
- Qwen 官方模型卡中的 9 个 speaker 与母语说明：<https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base/blob/main/README.md>
- 本项目现行 Provider 决策：[ADR-0010](./ADR/ADR-0010-Qwen-TTS双Provider与可替换本地运行时.md)
- 本项目迁移事实：[计划 59](./59-Qwen-TTS本地云端双Provider迁移施工计划.md)、[计划 62](./62-Qwen-TTS失败恢复与MOSS残留清理计划.md)

## 3. 产品方案

### 3.1 本地官方目录固定为 9 项

| 稳定产品 ID | 本地 speaker | 官方母语／特点 | 当前 Provider 可用性 |
| --- | --- | --- | --- |
| `qwen.WarmFemale` | `Serena` | 中文，温柔年轻女声 | 本地；保留现有 Plus／Flash 配置映射 |
| `qwen.Vivian` | `Vivian` | 中文，明亮年轻女声 | 本地 |
| `qwen.UncleFu` | `Uncle_Fu` | 中文，成熟低沉男声 | 本地 |
| `qwen.Dylan` | `Dylan` | 中文，北京口音年轻男声 | 本地 |
| `qwen.Eric` | `Eric` | 中文，四川口音男声 | 本地 |
| `qwen.ClearMale` | `Aiden` | 英语母语，清晰明亮男声；可读中文 | 本地；保留现有 Plus／Flash 配置映射 |
| `qwen.Ryan` | `Ryan` | 英语，节奏感男声 | 本地 |
| `qwen.OnoAnna` | `Ono_Anna` | 日语，轻快女声 | 本地 |
| `qwen.Sohee` | `Sohee` | 韩语，温暖女声 | 本地 |

兼容规则：

- 已存在的 `qwen.WarmFemale` 和 `qwen.ClearMale` 产品 ID、声音版本、指纹、人物绑定及历史 Edition 原样保留，不重命名、不批量重写。
- 既有两项为保持历史身份，原有 `language="zh-CN"`、`language_scope="zh-CN"` 和 `qwen-tts-preset-provenance/1` 内容不变；新加的 `native_language`／`dialect` 只是 catalog v2 展示元数据，不参与既有 provenance v1 指纹。特别是 `Aiden` 用新增母语字段纠正说明，不回写旧版本身份。
- 新增 7 个产品 ID；显示名同时写出官方 speaker，避免“产品昵称”掩盖真实模型身份。
- `Aiden` 明确标注官方母语为英语，不再只显示成容易误解的“中文男声”。它仍可按 Qwen 能力朗读中文，但不宣传为中文母语音色。
- 目录顺序固定为“中文母语 → 英语母语 → 日语 → 韩语”，搜索与语言筛选使用接口返回数据，不再维护另一份数量常量。

### 3.2 Provider 可用性不再强求一一映射

- `provider_voice_ids` 允许只包含已核实的 Provider key；9 个音色都有 `local_qwen3_tts`，现有两个逻辑音色继续保留当前阿里云 Plus／Flash 配置映射，但在真实 smoke 前只标记“有映射／未实测”。
- 不给其余 7 个本地 speaker 随意匹配阿里云声音。模型或渠道没有对应项时，卡片显示“仅本地可用”。
- 当前作品选择本地 Provider 时，9 项均可选用；选择云端时，只允许选择当前模型槽位存在映射的项。
- 已绑定本地专用音色后若作者切到云端，创建朗读任务前即使用现有业务错误 `VOICE_SOURCE_UNAVAILABLE` 阻断并提示切回本地或重新选音色；若 Provider 适配层单独遇到缺失 voice ID，则沿用既有 `TTS_VOICE_UNAVAILABLE`。不新造近义错误码，不得等到整章 fanout 后形成大量失败句段，也不得静默换声。
- 切换 Provider 不改写已有绑定和历史 Edition；缓存继续按 Provider／模型／声音版本严格隔离。

### 3.3 官方音色试听采用本地、临时、无写入路径

试听只回答“这个本地官方 speaker 听起来怎样”，不承担声音版本发布流程：

1. 作者点击“试听”，前端提交 `preset_id` 与当前作品目标语言；试听文本由服务端按允许的目标语言选择固定、无版权短句，不接受作者输入和小说正文。这样 `Aiden/Ryan` 也能直接试听中文朗读效果，而母语信息继续单独展示。
2. 后端先用短事务核验作品范围和 preset，再关闭事务；随后复用当前 `TTSExecutionService`，强制选择 `local_qwen3_tts` 调用 CustomVoice。
3. 新增窄路由 `POST /api/ai-novel-world-2026/novels/{novel_id}/official-voice-preview-audio`，请求体固定为 `preset_id + language`，成功后直接返回有上限的 `audio/wav`；响应带实际 Provider、模型和 speaker 身份，`Cache-Control: no-store`。
4. 前端以 `Blob` 播放，换音色时停止上一段并释放旧 Object URL；试听失败只影响当前按钮，不改变旁白／人物绑定。
5. 试听不创建 Edition、章节 job、声音版本、媒体资产或云端授权，不触发云端调用、不产生 Token／云端费用。

试听是无状态、无云端计费且不写入权威数据的动作，因此不新增幂等表、试听缓存或媒体清理任务；并发由页面单请求和本地 Provider 串行锁控制。

为避免复活已经退出的旧链，官方固定音色试听不重新启用通用 `VoiceProductPort`、`voice_preparation` 或 MOSS 时代的预览工作流。现有私人音色相关 `voice_previews` 表和通用接口保持不变；官方试听使用一个窄的 Qwen 本地服务与路由。

最小运行约束：

- 同一页面一次只允许一个试听请求；重复点击不并发生成。
- 首次点击允许出现模型冷加载提示，默认超时 45 秒；后端必须在请求协程取消或检测到客户端断开时调用既有 Provider `cancel(request_id)`，不能只在前端丢弃结果。
- 继续使用本地运行时既有串行模型锁，不让 CustomVoice、Base、VoiceDesign 同时常驻。
- WAV 响应继续执行现有格式、大小和模型身份校验；错误只返回稳定码，不记录试听正文或令牌。

### 3.4 页面保持轻量

音色卡只显示：显示名、官方 speaker、母语／方言、当前 Provider 可用性、试听、使用。详情中再显示模型与 revision，不增加复杂音色编辑器。

- 标题数量使用 `catalog.items.length` 动态显示；删除“18 项”静态文字。
- 试听在 T4 产品／权限门与本地试听服务已接线时允许发起；不根据容易过时的启动快照预判单槽模型当前角色，而在点击时通过真实本地合成、精确 CustomVoice 身份校验和局部稳定错误确认可用性。章节当前选择云端也可以试听本地官方声音，但按钮明确写“本地试听”。
- “使用”按钮由当前作品 Provider 与该音色映射共同控制。
- 试听中只局部更新当前卡片，不刷新整个工作台、不重建章节播放器。
- 保留键盘焦点、错误态和加载态；仅验收桌面 Web、桌面缩放和宿主侧栏挤压。

## 4. 数据、契约与迁移

### 4.1 需要一个小型前向迁移

虽然不新增表，现有数据库仍有两个音色的硬约束，因此不能只改前端：

- 新建一个基于施工时唯一 Alembic head 的 revision；不预占 revision 编号，不修改 `20260909_0045/0046` 历史迁移。
- 扩展 `ck_voice_action_command_preset_key` 到 9 个稳定产品 ID。
- 前向替换 `narration_check_official_voice_action_closure_v1()`，逐项核对本地 speaker、可选云端映射、语言和 provenance。
- 迁移不修改现有两个音色的 `voice_profiles`、`voice_profile_versions`、绑定、Edition、render 或媒体；升级前后对这些行做数量与哈希对比。
- downgrade 若无法在已创建新音色记录时安全收缩，应明确拒绝破坏性回退；恢复使用发布前数据库 dump 加旧插件树，不能偷偷删除新绑定。

### 4.2 契约变化

- 官方目录响应从 `qwen-tts-preset-catalog/1` 升级为 `/2`，因为新增元数据和稀疏 Provider map 属于 wire 语义变化；前后端同版本切换，不伪装成 v1。声音版本内部的 `qwen-tts-preset-provenance/1` 对既有两项保持不变，避免历史声音版本失效。
- 为页面正确说明音色，目录项增加 `official_speaker`、`native_language` 和可选 `dialect`；前后端同时冻结字段。
- 前端 `language_scope` 联合类型、运行时校验和筛选顺序必须与后端现有 `zh-CN | en | ja-JP | ko-KR` 对齐，补上当前遗漏的 `ko-KR`；`language_scope` 继续承担既有目录分类语义，不拿它冒充“模型只能合成这一种语言”。
- catalog v2 可新增展示字段，但不得把 `native_language`、`dialect` 或动态可用状态塞进既有两项的 provenance v1 计算；施工门禁要直接比较发布前后两项完整 provenance JSON 与指纹。
- 官方试听改为独立的本地 WAV 响应契约；删除当前永远不可用的官方试听轮询接线，不影响私人音色预览资源。
- 创建 Edition／生成任务时先检查当前 Provider 映射，使用现有 `VOICE_SOURCE_UNAVAILABLE` 失败关闭；worker 仍作第二道防线并把 Provider 级缺映射归为既有 `TTS_VOICE_UNAVAILABLE`，不再落入通用 `RENDER_INPUT_INVALID`。
- 当前未被运行代码消费的 `OFFICIAL_PRESET_MANIFEST_SHA256` 必须二选一：改为由 9 项规范目录计算并在启动／测试中真正校验，或安全删除该死常量；不得只换一个看似正确但无人验证的哈希。

## 5. 精确改动范围

预计涉及：

- 后端目录与约束：`backend/narration/official_presets.py`、`official_voice_records.py`、`schemas.py`、Edition／任务创建前置校验、`worker.py`；
- 本地试听：新建窄服务／路由文件，最小接线 `backend/narration/production_runtime.py`、`backend/app.py`；复用 `backend/narration/tts_execution.py` 和现有本地 Provider，不修改 QwenPaw 上游；
- 数据库：一个新 Alembic revision及迁移测试；
- 前端：`frontend/src/narration/contracts.ts`、`api.ts`、`official-voice-library.ts`、`official-voice-selection-panel.ts` 及相关样式／测试；
- 文档与证据：本计划、索引及 `audit/qwen-tts/plan75/**`。

禁止触碰：QwenPaw 核心、模型权重、真实密钥、小说正文、历史 Edition、计划 66／70 施工文件、云端渠道协议、章节生成状态机和无关工作区改动。

## 6. 施工波次与子代理并行设计

规划阶段不启动子代理；作者批准施工后，Q75-B、Q75-P、Q75-F 已按冻结契约并行完成，迁移与共享接线由主代理串行集成。工作包 ID 只属于计划 75。

| 波次 | 工作包 | 类型 | 唯一目标与精确所有权 | 前置／冻结接口 | 验收证据 |
| --- | --- | --- | --- | --- | --- |
| W0 | Q75-C | SER/GATE | 主代理冻结 9 项目录、稀疏 Provider map、试听 WAV 契约和错误码；本计划与 DTO 草案 | 作者批准；先复核工作区与唯一迁移 head | 契约评审、9 项清单与本机 config 对照 |
| W1 | Q75-B | PAR | 后端目录、catalog v2、provenance、任务前置阻断与 worker 防线；`official_presets.py`、`official_voice_records.py`、`schemas.py`、Edition／任务服务、`worker.py` 及定向测试 | Q75-C；不得改迁移、app、前端 | 9 项目录、既有两项指纹不变、Provider 负向测试 |
| W1 | Q75-P | PAR | 本地官方试听窄服务与路由；仅新文件及其测试，路由请求 DTO 留在新模块以免争用 `schemas.py` | Q75-C；不得改共享接线、数据库表或云端 Provider | fake 本地调用、WAV、断连／超时取消、无写入测试 |
| W1 | Q75-F | PAR | 9 项音色库、动态计数、Provider 徽标和 Blob 试听；仅官方音色前端模块及定向测试 | Q75-C wire fixture；不得改共享工作台 | Vitest、焦点／加载／错误／URL 释放验证 |
| W2 | Q75-D | SER/MUTEX/GATE | 主代理新建唯一 Alembic revision并更新迁移测试 | B 契约稳定；不得修改历史 revision | 当前数据快照、upgrade、闭包正负测试、恢复说明 |
| W2 | Q75-I | SER/MUTEX/INT | 主代理完成 `production_runtime.py`、`app.py`、前后端导出和共享入口接线 | B/P/F/D 完成 | 定向集成、无长事务、无云端调用证据 |
| W3 | Q75-V | GATE/MUTEX | 主代理全量回归、隔离插件升级、9 音色本地真实试听、桌面浏览器验收；正式部署另等作者授权 | I 完成 | pytest、pnpm、打包、迁移、9 WAV 身份／播放、页面截图 |

并行规则：Q75-B、Q75-P、Q75-F 只在 Q75-C 冻结后并行，文件不得重叠。迁移链、`backend/app.py`、`production_runtime.py`、前端共享入口、锁文件、正式数据库、唯一 Qwen 运行时、部署、Git 暂存／提交／推送全部为 MUTEX，由主代理单一所有。子代理不得操作正式环境、真实密钥、数据库、模型文件或用户未提交改动。汇合顺序为 C → B/P/F → D → I → V，主代理是唯一集成责任人。

## 7. 验收门禁

### 7.1 自动化

- 后端定向：官方目录、provenance、直接选用、worker Provider 映射、试听服务、试听 API、迁移正负闭包。
- 前端定向：9 项完整性、动态数量、语言筛选、当前 Provider 可用性、单卡局部试听、重复点击、取消、失败和 Blob 释放。
- 全量：`.venv/bin/python -m pytest`；`pnpm typecheck`、`pnpm test`、`pnpm build`；`.venv/bin/python scripts/package_plugin.py`；`git diff --check`。
- 若涉及 Compose 文字或部署入口才运行 `docker compose config`；本计划默认不改 Compose。

### 7.2 隔离与真实本地模型

1. 在隔离插件环境完成 upgrade，并确认现有两个声音版本、绑定和历史 Edition 哈希不变。
2. 9 个 speaker 各生成一次当前作品语言的固定短试听，核对实际 Provider=`local_qwen3_tts`、模型、revision、speaker、WAV 格式和非静音；样音不进入 Git。
3. 浏览器逐项点击试听，验证首个冷加载、后续热路径、切换停止上一段、失败只影响当前卡片，控制台无新错误。
4. 用一个测试作品建立 9 个短句／说话人，每个官方 speaker 各走一次真实 worker 合成与播放；参数化自动化同时覆盖旁白和人物两类选择目标。无需为每个音色建立一章或一本书。
5. 当前 Provider 为云端时，本地专用音色在创建任务前被明确阻断；不发起真实云端请求。现有两个云端配置映射只做 mock／契约回归并显示“未实测”，真实云端 smoke 仍归计划 61。

### 7.3 发布门

- 自动化、隔离迁移和 9 项真实本地试听全部通过；
- 发布前备份数据库与现有插件安装树并验证可读；
- 作者另行授权正式部署后才安装到长期 `18088`；作者已于 2026-09-12 在本轮明确要求“让改动生效”，正式发布授权已满足；
- 正式页面复核动态显示 9 项且每项本地试听可播放，已有正文和历史朗读不变；
- 未逐项生成／播放的音色不得写成“全部可用”。

## 8. 回退与风险

- 代码回退：恢复发布前 PawApp 安装树；本地 Qwen 模型和音频不删除。
- 数据回退：若数据库尚未出现新增 preset 记录，可前向收缩约束；若已出现，则使用经验证的发布前 dump 恢复，不级联删除声音绑定。
- 最大兼容风险是数据库 closure、后端目录和前端常量不同步；以同一 9 项 fixture、迁移测试和运行 API 清单三重校验。
- 最大体验风险是首次试听冷加载较慢；页面明确显示“正在加载本地模型”，不通过预生成 9 份仓库音频或常驻多个模型掩盖。
- `Aiden` 中文听感可能不如中文母语男声；通过真实说明和试听让作者选择，不修改模型输出或假造定位。

## 9. 非目标

- 不扩展阿里云全部音色，不抓取第三方渠道音色市场；
- 不自动为本地音色猜测云端替代项，不静默换声；
- 不实现实时流式试听、波形编辑、情绪时间线或音色评分系统；
- 不恢复 24 槽池、VoiceGenerator、Nano 或 MOSS 逻辑；
- 不修改 VoiceDesign／Base 的产品工作流；
- 不执行真实云端计费调用；
- 不顺带清理计划 66／70 临时文件或提交其改动。

## 10. 批准与退出标准

作者已于 2026-09-12 明确授权开始施工，并在完成候选后另行明确要求“复查改动、让改动生效、提交并 push”；后者构成本计划正式 `18088` 发布授权。若发布门出现新的代码或数据阻断，仍须先修复，不以授权替代验证。

完成需同时满足：正式目录为 9 项、9 项均能本地试听和直接使用、Provider 不兼容在生成前明确阻断、既有两项和历史朗读不变、页面数量准确、全量回归及隔离／正式门禁通过。任何一项未验证都按部分完成报告，不把模型支持等同于产品已可用。

## 11. 2026-09-12 施工记录

- Q75-B／P／F／D／I 已完成源码集成：目录为 9 项、catalog v2、稀疏 Provider 映射、生成前阻断、worker 防线、无状态本地 WAV 试听、动态数量和前端单卡局部状态均已实现。
- 既有 `qwen.WarmFemale`／`qwen.ClearMale` 的产品 ID、语言、Provider 映射及 provenance v1 指纹由回归测试固定；新增迁移 `20260912_0054` 只扩展约束和闭包，不修改历史行。
- 后端全量 `2835 passed, 265 skipped`；前端全量 `153 files / 1326 tests passed`；`pnpm typecheck`、190 模块 production build、插件打包和 `git diff --check` 通过。跳过项不计为通过。
- 独立 PostgreSQL 18 临时库从空库全链升级至 `20260912_0054`，9 个 preset 逐项通过 closure 正向与篡改拒绝测试；临时库已删除，正式数据库未写入。
- 本机 `127.0.0.1:8766` 的 9 个官方 speaker 均经真实 MLX 生成并通过 Provider／模型／revision、RIFF/WAVE、非静音校验；没有云端调用，样音未落库、未进入 Git。
- 隔离 QwenPaw 生命周期的标准入口连续两次停在临时 PostgreSQL 的 Docker `created` 状态；一次性 create→start 复核证明容器能够进入 `running`，但 Docker CLI 子进程仍不返回并最终超时，未进入插件安装阶段。各轮均由脚本精确清理全部本轮资源。原始记录见 [`audit/qwen-tts/plan75`](../../audit/qwen-tts/plan75/README.md)。因此不能宣称隔离安装、浏览器或正式发布已通过，也不会用仍运行旧包的 18088 页面冒充新候选验收。
- 发布前独立复查发现并修复两项阻断：前端不再按旧目录下标推导日语／韩语音色语言；官方试听除本地 Provider 外，又精确钉死 CustomVoice repository、revision 与 artifact tree SHA。日语、韩语成功响应以及错误 Provider、Base、revision、制品指纹均有负向／正向回归。
- 修复后后端全量为 `2838 passed, 273 skipped`；前端全量为 `153 files / 1328 tests passed`，typecheck 与 190 模块 production build 通过。
- 作者授权正式发布后，先完成数据库 custom-format dump、旧安装树、Skill 状态与候选包双位置备份及恢复演练，再以 schema-owner 把正式库从 `20260911_0053` 精确升级到 `20260912_0054`，0053／0054 角色 bootstrap 与 61 表 validator 均通过。
- 候选 tree SHA `8e22b70d4ea050b42afdcaaa1d799099da7f09696b074a260423b008d776ee55` 已通过 QwenPaw 公开 `plugin install --force` 安装到原长期容器；启动后健康、数据库、朗读 production backend、worker、Agent 模型、11 个 Skill 与 5 个小说工具均通过运行态复核。
- 正式 HTTP 接口返回 catalog v2／9 项；9 个 speaker 均逐项返回有效 WAV，响应中的 Provider、CustomVoice repository、revision 与 speaker 精确匹配。桌面页面显示 9 项及 6／1／1／1 语言分组，Sohee 页面试听实际进入“本地试听已开始”，没有新增浏览器错误。
- 发布前备份与发布后复比中，Edition、Edition segment、render、render asset、media asset、旁白设置与旧声音版本数量／摘要完全一致；`character_voice_bindings` 仅多一条 14:28:42 的 `qwen.WarmFemale` 业务绑定，它发生在停服／迁移／安装前的在线窗口，保留为用户数据，不回删。正式验收未改正文、历史 Edition 或媒体。
- 正式发布证据见 [`audit/qwen-tts/plan75/formal-release-20260912.md`](../../audit/qwen-tts/plan75/formal-release-20260912.md)。

## 12. 正式 18088 最小发布与恢复步骤（2026-09-12 冻结）

本节是 Q75-V 的正式 MUTEX／INT 操作单，由主代理单一执行，不与其他计划并行写数据库、安装插件或操作 Git。

1. 只读确认长期容器、镜像、卷、数据库 head 和 TTS 开关身份；确认活动后台任务为 0。
2. 保存发布前 Skill 开关快照；生成 PostgreSQL custom-format dump，并以 `pg_restore --list` 验证；复制当前已安装 PawApp 树；冻结新候选。数据库、旧安装树和候选同时保存在宿主 `0700` 恢复目录与 QwenPaw 专用备份卷，记录大小／SHA 或 tree SHA。
3. 保存旧两官方音色关联数据的脱敏数量与聚合哈希：`voice_profile_versions`、人物绑定、旁白设置、Edition segments、Editions、renders、render assets、media assets；不得读取或输出小说正文。
4. 停止长期 QwenPaw；在 PostgreSQL 保持健康时依次执行 0053 bootstrap／validate、schema-owner 精确 `upgrade 20260912_0054`、0054 bootstrap／validate。不得运行 `upgrade head`，不得尝试 downgrade。
5. 在宿主仍停止时，使用 `scripts/qwenpaw_lab_plugin.py offline-install-stopped`，绑定候选 tree SHA、head、正式 container ID、image ID 和发布前 Skill 快照；底层必须是 QwenPaw 公开 `plugin install --force`。
6. 启动原长期容器，恢复 Skill 开关并验证：健康接口 app／database／narration／worker 全部 ready；数据库精确为 0054；目录契约为 v2 且精确 9 项；同一测试作品逐项请求 9 个本地试听，只接受 RIFF/WAVE、`audio/wav`、`no-store`、精确 Provider／model／revision／speaker；真实桌面页面可见 9 项并可局部试听，控制台无新增错误。
7. 复比步骤 3 的全部数量／哈希；现有正文、旧朗读和媒体不得变化。成功后记录正式证据，再暂存本计划范围、提交和 push。

失败恢复：立即保持或重新进入停写，使用同批发布前数据库 dump、旧 PawApp 安装树和 Skill 快照整体恢复；恢复后重新验证 0053、健康和基线。不得删除 PostgreSQL、QwenPaw、密钥、模型或媒体卷，也不得用 0054 的拒绝型 downgrade 代替恢复。
