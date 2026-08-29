# MOSS-TTS-Nano 全预设直用、人物专属音色与播放体验优化计划

状态：**2026-08-29 源码候选已完成本轮施工与自审。P0 的 18 项官方 preset 直用、`0031` 与 18 项真模型短句已通过；P1 的设置、规则、人物覆盖和播放器已接线，前端 102 文件/920 项、typecheck 与 build 通过。Nano 高级参数的产品闭环未完成，保持隐藏；VoiceGenerator 在 M4/16 GiB 上为 `NO-GO`，人物页降级为一键/批量自动分配官方音色。P2-DEL 的 `0032`、精确资产计划与三崩溃恢复已通过隔离 PostgreSQL，但持久 grace/重启对账 worker 和权威 eligibility 尚缺，故 UI 未接入、HTTP 路由 fail-closed。W6 已删除三组零引用旧 UI/样式，后端全量 3093 项通过、138 项按环境门跳过，打包与契约检查通过。W6 隔离 QwenPaw 安装两次在 Docker Engine 启动新 PostgreSQL 容器前超时，因此 `P0/P1-RELEASE=HOLD_INSTALL`；长期数据库、18088 安装与唯一运行环境均未切换。**

施工授权边界：用户已用“按计划 33 开始实施”一次性批准 `P0 + P1 + P1.5 + P2-VG + P2-DEL` 的代码与隔离验证，不再在每个非破坏性阶段重复索要批准；该授权不包含迁移唯一长期数据库、切换唯一长期运行环境、提交/推送或删除任何真实私人媒体。真实私人媒体的彻底删除仍由产品内针对精确目标的一次确认授权。

本文对 [18-MOSS-TTS-Nano 多角色智能朗读产品与技术设计](./18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md) 的目标取代原则为“一次批准、分波实施、内部验收自动推进”：

- 批准本文施工后，固定 18 项官方 preset 直用、设置/播放器、实验参数和人物一键生成均进入同一授权范围；
- `VG0/VG1` 是工程内部可用性检查，不是作者使用前的确认框，也不再要求第二次产品化批准；通过则按本文继续实施，失败则保持 capability 隐藏并准确说明不可用；
- `MNX-DEL-AUDIT` 是工程内部删除正确性检查，不要求再次批准代码施工；真正删除某个私人音色时，只针对该精确目标显示一次影响确认；
- 工程 `GATE` 只判断构建能否安全发布，不得被实现成作者每次使用都要跨越的产品门禁。

本文未获批前，当前 6 个中文预设与 `VOICE_GENERATOR_NO_GO` 仍是运行事实。

关联输入：

- [MOSS-TTS-Nano 朗读设置只读审计](../../audit/MOSS-TTS-Nano朗读设置审计-2026-08-29/README.md)
- [18-MOSS-TTS-Nano 多角色智能朗读产品与技术设计](./18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md)
- [30-TTS 按需加载与 Docker CPU 优化计划](./30-TTS按需加载与DockerCPU优化计划.md)
- [32-创作账本缺口闭环与向量联合复验计划](./32-创作账本缺口闭环与向量联合复验计划.md)
- [MOSS-VoiceGenerator 官方模型卡](https://github.com/OpenMOSS/MOSS-TTS/blob/main/docs/moss_voice_generator_model_card.md)（2026-08-29 复核）
- [MOSS-TTS-Nano 官方 ONNX 应用](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/app_onnx.py)（2026-08-29 复核）

## 1. 目标结果与优先级

目标用户流程如下：

```text
官方音色：浏览 18 个预设 -> 点击“设为旁白/用于此人物” -> 立即完成绑定
人物专属音色：人物卡点击“根据人物生成并使用”
  -> 后台自动分析人物、生成 1 个音色、技术校验、创建版本并绑定
  -> 完成后直接可播放；不满意可点“换一个并使用”或“删除”
  -> 章节同页生成、播放、跳播、跟随和失败重试
```

| 优先级 | 交付目标 | 独立价值 | 不依赖项 |
| --- | --- | --- | --- |
| `P0` | 18 个固定官方 ONNX 预设全部可见，可选试听，并可不试听直接设为旁白或绑定人物 | 立即消除“官方音色存在但不能直接用”和五步建档阻力 | 不依赖 VoiceGenerator；激活证据由后台处理，按当前约束证据预计需要最小迁移 |
| `P1` | 朗读设置、音色库、人物配音和章节播放器重构；补齐播放器音量、时间/句段进度与紧凑态 | 改善日常朗读和校听效率 | 不依赖 VoiceGenerator |
| `P1.5` | Nano 官方参数的高级实验入口 | 满足可调教需求，同时保护官方默认版本和历史 Edition | 后台技术校验通过后直接使用，试听可选 |
| `P2-VG` | 人物卡权威 revision → AI 描述 → 单候选生成 → Nano 技术验证 → 自动建档/绑定；支持一键换一个 | 交付真正的一键人物专属音色 | 真实 M4 资源与依赖检查是内部发布条件，不进入作者操作流程 |
| `P2-DEL` | 未使用候选一键丢弃；已使用私人音色一次影响确认后彻底删除 | 形成简洁完整生命周期 | FK、备份和历史 Edition 由后台删除计划保证 |

实施仍按 `P0 → P1 → P1.5/P2` 分波降低风险，但作者只需一次批准整份非破坏性施工。模型不达标不得拖住官方预设和播放器优化，也不得静默把“匹配官方音色”冒充“生成专属音色”。

### 1.1 产品门禁减负原则

| 旧门禁/步骤 | 新规则 |
| --- | --- |
| 官方音色必须先试听、确认质量、锁定 | 全部取消；试听是可选播放按钮，“使用”直接建档并绑定 |
| 跨语言二次确认 | 取消弹窗；只显示非阻断语言标签/提示 |
| 版权、商业用途或来源勾选 | 个人本地写作模式不展示确认框；来源/provenance 仅在“模型详情”中只读保留 |
| 用户理解 profile/version/preview/lock | 主路径全部隐藏，由服务端完成 |
| 人物声音描述先确认 | 取消；点击“生成并使用”即授权本次分析与生成，描述保存在详情中可事后修改 |
| 默认生成 3 个候选并要求选择 | 改为默认生成 1 个并自动使用；“换一个”生成下一个 seed，“生成 3 个备选”仅放高级入口 |
| Nano 克隆后再人工确认/锁定/绑定 | 取消；机器技术校验通过后自动建立不可变版本并绑定 |
| 每个施工阶段重复请求批准 | 取消；一次批准本文后按内部工程验收自动推进 |
| 删除的请求、预览、二次确认三段 UI | 后端仍使用持久删除计划；UI 对未引用候选一键删除，对已使用音色只显示一次影响确认 |

默认操作预算冻结为：官方预设 `1 次点击 + 0 次确认`；人物专属音色 `1 次点击 + 0 次中间确认`；“换一个并使用” `1 次点击`；未引用私人音色删除 `1 次点击 + 0 次确认`；当前或历史已使用私人音色删除 `1 次点击 + 1 次影响确认`。只有异步期间绑定被其他操作改写时，才追加一次“使用此音色”，且不得把该低频冲突分支计入正常路径。

只保留不会打扰正常使用的后台防线：scope/CAS/幂等、音频可解码与非空检查、重模型资源互斥、异步任务恢复、历史 Edition 不被静默改写。如果异步生成期间作者已经手动换了音色，系统不得覆盖较新的选择；此时生成结果进入“已生成、未自动应用”，这是冲突保护而非常规门禁。

## 2. 当前实现事实与目标缺口

| 领域 | 已核实当前事实 | 本计划目标 |
| --- | --- | --- |
| 官方目录 | 固定 manifest、Sidecar、`0022` 数据库防线和 `VoiceProductService.create_preset_version()` 下层已支持 18 项；`PRODUCT_OFFICIAL_PRESET_IDS`、exact-six schema/handler/前端 DTO 只投影 6 个中文项 | 18 项全部进入个人本地产品目录；保留语言和验证等级提示，不做名称黑名单；目录 wire contract 升级到 `/2.0` |
| 官方音色使用 | 用户须建 profile、建 version、生成真实试听、确认质量、锁定后才能绑定 | “使用”是一个服务端原子业务动作；后台自动建立或复用可审计的不可变版本 |
| 官方参数 | 正式版本依赖运行时官方默认；跨进程协议/指纹目前只显式携带 `seed/sample_mode/max_new_frames/voice_key`，页面展示的停顿、播放倍速和音量不是模型参数 | 默认仍保持官方参数；decode contract v2 才显式开放完整参数，高级实验版本单独创建，绝不原地修改官方默认版本 |
| 设置页 | 总览、旁白、人物配音、选角规则、发音与停顿、音频与缓存均已实现，但首次流程重、语言是自由文本、毫秒与范围覆盖过于靠前；`playback` 偏好未找到被播放器完整消费的路径 | 基础偏好优先；音色库独立；高级参数和范围覆盖折叠；不可用云端能力不展示可操作假表单；倍速/音量必须真实接线或移除无效入口 |
| 播放器 | 已有播放/暂停、上一句/下一句、句段滑杆、倍速、Edition 切换、正文跟随、光标/段落跳播、更新朗读和失败句段重试；当前无 `setVolume`，固定 94 px 预留与可扩展失败列表存在遮挡风险 | 保留引擎与 Edition 语义；补音量、可播放/全章双进度、时间、音色身份、紧凑态、窄屏和完整状态反馈；先消除固定高度遮挡风险 |
| 人物专属音色 | `VoiceDesignAdapter` 契约和 test fake 已存在；生产使用 `DisabledVoiceDesignAdapter`，原因 `VOICE_GENERATOR_NO_GO` | 先做固定 revision 与真实 M4 尖峰，通过后才开放人物卡入口 |
| 人物权威 | 人物根、不可变 revision、别名权威及 `source_character_revision_id` 已由计划 32 完成并验收 | 只消费已正式保存的人物 revision，不从临时表单、姓名猜测或工作稿静默生成 |
| 私人音色删除 | 有 profile archive API、`voice_deletion_requests`、`asset_tombstones`；当前页面无入口，也没有完整真删除服务 | 按资产可达性分级删除；历史文字和审计行不级联删除；备份未到期时不宣称永久删除 |
| 资源 | Nano 已实现按需加载和 300 秒空闲卸载；冷态约 25 MiB；现有 `moss-nano:inference` 与 `voice-generator:generation` 是两个互不排斥的 exact key | VoiceGenerator 必须同样按需加载；新增经跨进程验证的共享硬件 residency claim 后才可保证 Nano 与 VoiceGenerator 不同时常驻，不能把计划级锁名称冒充现有数据库事实 |

### 2.1 历史施工冲突已解除，仍需开工重取基线

2026-08-29 初版规划时，[32 号计划](./32-创作账本缺口闭环与向量联合复验计划.md)曾处于“已批准、施工中”，并占用：

- 唯一 Alembic head 与 `backend/models.py`；
- `backend/narration/production_runtime.py`、迁移总测试和声音 schema 测试；
- `frontend/src/workbench-studio.ts`、`frontend/src/styles.ts` 及人物/账本公共 DTO；
- 长期 PostgreSQL、QwenPaw 安装态和联合复验环境。

第三轮复查时，计划 32 已标记“完成施工、长期安装、真实联合复验与三视口验收”，当前 `git status --short` 也未显示其遗留 dirty 文件；该跨计划阻断已解除。本文仍不得把旧基线当成当前事实：`MNX-G0` 在一次性施工授权后重新执行 `git status --short`、确认 migration head（当前文件序列已到 `0029`）、复核最终人物 revision/API，并冻结本文接口。若届时出现新的用户改动，只保护具体冲突文件，不把整个产品流程重新变成等待门禁。

另有一项 UI 基线风险：同日审计截图仍出现当前 `reading-overview.ts` 已移除的“通用音色”入口，说明本机运行 bundle 与当前源码候选可能不同。`MNX-G0` 必须记录源码 tree hash、PawApp 包 hash、已安装 bundle hash 和宿主版本；真实 UI 验收前从同一源码候选重建、安装到隔离环境。旧截图只能作为历史证据，不能冒充当前源码验收。

## 3. 范围与明确非目标

### 3.1 纳入

- 固定 revision 的 18 个官方 preset 全量产品投影、过滤、试听和直接选择；
- 旁白和正式人物的一键官方音色绑定；
- 官方默认模式与受控高级实验模式分离；
- 朗读设置页信息架构、音色库、人物批量配音、发音/停顿和缓存入口优化；
- 章节播放器的面板、音量、进度、状态、键盘、窄屏和无障碍；
- 从正式人物 revision 生成结构化声音描述；
- 本地 VoiceGenerator 单命令生成、Nano 技术验证、自动建立不可变版本和稳定绑定；高级入口可生成多个备选；
- 未使用生成结果一键丢弃、profile 归档、私人音色一次确认式真删除和墓碑；
- 迁移、任务、模型运行证据、安装/升级/卸载和失败恢复；
- 在同一施工范围内识别并删除已被新实现完全替代的旧 TTS 代码、组件、样式、DTO、测试夹具、配置和依赖，不保留双轨实现或无主兼容壳。

### 3.2 不纳入

- 修改、复制、替换或 monkey patch QwenPaw 上游核心；
- 团队、云端共享、远程 TTS、跨用户音色库或第二套业务 API/任务队列；
- 未授权真人仿声、上传第三方声音、从姓名推断现实人物身份或对外发布权利结论；
- 章节/全书音频导出，现行 `T6-D_CANCELLED` 保持不变；
- 每句台词调用 VoiceGenerator、播放中静默换音色或人物卡变化后自动重绑；
- 由模型直接修改人物卡、正文、正式大纲或故事账本；
- 另建聊天模型选择器、固定模型白名单或静默回退。人物声音描述提案只能由作者显式触发并复用 `ai-novel-writer` 当时有效模型；
- 把播放倍速、播放器音量、句间停顿误写成 Nano 音色生成参数；
- 把 12 个英文/日文 preset 表述为已经完成本项目中文长篇听感验收；
- 以“清理冗余”为名删除已执行迁移、历史验收/审计原始证据、仍有真实调用者的兼容路径、语义独立的负向/恢复测试或用户既有未提交改动。

### 3.3 冗余删除硬规则

本计划采用“替换即收口”，不允许在旧流程旁边长期叠加一套新流程。`MNX-PRUNE-AUDIT` 在代码施工前创建 `docs/开发文档/证据/MOSS-TTS-Nano优化/redundancy-ledger.md`，并在各波汇合时持续记录候选；每条记录至少包含精确文件/符号、现有调用者、替代实现、删除或保留裁决、独立契约/风险覆盖、负责人、验证证据和恢复方式。

删除前必须同时满足：

1. 用 `rg`、前端 import/路由/样式接线、后端注册/API/DTO、Compose/打包清单和依赖图证明没有剩余调用者；
2. 替代路径已接线并通过相应聚焦测试，旧代码不再承担兼容、回退、负向、并发、恢复或安全边界；
3. 目标不是已执行迁移、历史验收原始证据、外部公开契约的唯一兼容实现，也不包含未归属本计划的用户改动；
4. 删除文件、符号、测试或依赖的精确范围已冻结进 ledger，并由主代理在 `MNX-PRUNE` 串行执行与复核；新增候选必须先补证据，不能把该工作包当成开放式大扫除；
5. 依赖删除通过项目包管理器和锁文件正常更新完成，不手工删改锁文件；删除后运行受影响回归、全量门禁和 `git diff --check`。

例如现有 catalog v1 的 exact-six 响应、旧音色入口、旧播放器布局和旧删除交互都只是待核候选：有真实调用者或独立回退价值就保留并写明退出条件；已被 v2/新组件完全覆盖且无调用者则必须在本计划同一发布版本内由 W6 删除。任何保留的兼容壳都要写明理由、调用方和 sunset 条件，不能以“也许以后有用”为由常驻。

## 4. 冻结产品与领域规则

### 4.1 18 个官方预设直接使用

1. 目录权威仍是固定 revision `f52645cb467506d8e18e746ddd59482685b74e58` 和既有 manifest/hash；不得从网络实时目录静默增删。
2. 对外顺序固定跟随 manifest：6 中文、5 英文、7 日文，共 18 项。
3. 全部 18 项允许个人本地试听和选择。非中文项目专项未验收只影响标签，不形成阻断。
4. 主卡片只显示官方显示名、语言、性别/分组、非阻断验证徽标和本地可用状态；exact `preset_id`、模型 revision、manifest 来源等技术证据收进可展开“模型详情”，不挤占日常选择界面。
5. 验证等级必须忠实：
   - `canonical_chapter_verified`：仅现有真实章节证据实际覆盖的 `Zhiming`、`Junhao`、`Xiaoyu`；
   - `pinned_catalog_unreviewed`：其他固定项；
   - 英文/日文另显示“跨语言/本项目未专项听检”。
6. “试听”是完全可选的播放动作；不试听也能直接使用。试听可以按需建立隐藏的本书范围官方版本与临时 preview，但不得把浏览过程变成用户可见的建档向导；不得使用 `novel_id=NULL` 的全局 profile 承载临时媒体。
7. “设为旁白/用于此人物”必须是单个服务端数据库事务，不在长事务内同步运行 Nano：鉴权与 scope → 保留/读取幂等键 → 已完成则直接重放冻结结果 → 未完成才校验内部 CAS → 建立或复用官方版本 → 写激活证据 → 更新设置或人物绑定 → 完成命令与回执。任一数据库动作失败整体回滚；响应丢失后用原 key 和原请求重放不能被旧 CAS 阻断。
8. 用户点击“使用”本身就是本次绑定授权。数据库使用 `activation_basis=explicit_official_preset_selection` 表示官方 preset 可用性，不得伪造 preview、`quality_confirmed`、ModelRun 或人工听检 actor；“未专项听检”只作为详情信息，不能阻断使用。generated/实验的 `machine_validated` 枚举仅作后续契约预留；在 `VG-CONTRACT-GATE` 闭合 description、ModelRun、rights 与技术校验证据前，P0 不允许其 locked/绑定/渲染。上传参考音频仍遵守独立的权利与试听规则。
9. 服务端从作品设置读取 `target_language`，官方卡片显示来源语言。语言不匹配只给非阻断提示，不增加确认字段、弹窗或服务端拒绝；人物绑定仍由客户端透明携带 settings/binding CAS，避免并发覆盖，但作者无需理解这些版本号。
10. canonical 官方身份区分稳定容器与不可变版本：profile UUIDv5 保持 `moss-tts-official-preset-identity/1.0`，输入固定为 `(identity_contract_version, owner_id, workspace_id, novel_id, preset_id)`；直用 version 身份升为 `moss-tts-official-preset-direct-version-identity/2.0`，额外固结 activation/validation、fixed model revision、manifest SHA-256、preset provenance fingerprint、rights policy fingerprint、decode contract 与官方默认参数 digest。隐藏试听版本不得占用直用 version ID。只复用同小说、完整 provenance/rights/默认参数指纹完全匹配且仍可用的 canonical profile/version；模型、manifest、rights policy 或默认参数改变时在原 profile 下生成新版本。
11. 官方 preset 本身不可被删除；用户只能解除绑定、移出常用列表或归档本地派生档案。
12. 当前产品模式固定为个人、本地、写作辅助、无下载/导出/分享入口。官方来源与固定 revision 在详情中保留用于维护和复现，但不显示版权、商业用途、主体同意或来源确认框，不参与“使用”按钮的放行。

### 4.2 可选择性与可渲染性必须分离

回退开关或产品范围变化只能阻止“新选择”，不能让已经锁定、绑定且 provenance 合法的 18 项官方版本突然无法渲染。服务端必须分别判断：

- `selectable_now`：当前 UI 是否允许新建/新绑定；
- `renderable_existing`：既有不可变版本是否仍能合成历史/当前 Edition；
- `previewable_now`：当前模型运行态是否可试听。

同理，未来关闭 VoiceGenerator 或高级参数入口时，既有已锁定 generated/custom 版本仍可用于朗读；只停止新生成。该规则是安全回退与历史完整性的硬约束。

### 4.3 官方默认与高级实验参数分层

默认卡片固定使用官方参数：

```text
sample_mode=fixed
do_sample=true（由 fixed 推导，不单独冲突配置）
seed=1234
max_new_frames=375
text_temperature=1.0
text_top_p=1.0
text_top_k=50
audio_temperature=0.8
audio_top_p=0.95
audio_top_k=25
audio_repetition_penalty=1.2
```

高级实验入口不得修改系统官方版本，只能“复制为实验版本”。页面允许查看完整有效配置，但只把会实际影响声音风格或采样稳定性的项目做成作者可编辑控件：

- 生成稳定性：`sample_mode`、`seed`（派生新的 Nano 实验版本时确定性记录）；
- 文本/音频采样：text/audio temperature、top-p、top-k、audio repetition penalty；
- 文本处理：受运行时支持的规范化策略。

`do_sample` 由 `sample_mode` 统一推导。`max_new_frames=375`、`voice_clone_max_text_tokens`、CPU threads、execution provider、batch/流式后端、输出格式和 normalization 可在“技术详情”查看，默认由运行时与安全上限管理，不伪装成音色调教旋钮。音高、情绪、语速不得伪装成 Nano 原生精确旋钮，它们进入 VoiceGenerator 描述或播放器层。

现有 `onnx.Zhiming` 短归因 `fixed_seed_1` 只是历史诊断/回归分支，当前生产 `ACTIVE_SHORT_ATTRIBUTION_STRATEGY=disabled`，所有新官方渲染继续使用版本默认 seed。P1.5 必须保留该历史分支可读及旧 fingerprint 可重放，但不得因开放 base seed 而静默重新启用它；未来若有新真实听感证据要恢复，必须作为新的版本化 effective policy 进入 render/ModelRun/cache fingerprint。

当前 Sidecar 并未显式接收 text/audio temperature、top-p、top-k 和 repetition penalty，而是依赖固定运行时默认值。因此 `P1.5` 的前置条件不是“给页面加输入框”，而是冻结可双读的 decode contract v2，并将完整参数纳入 Voice Version fingerprint、Sidecar canonical request/HMAC、ModelRun `parameters_digest`、render/cache fingerprint 和 worker 安全校验。既有 v1 Voice Version/Edition 继续按旧隐式默认解释，不回填、不重写历史。

所有高级值由服务端定义枚举/上下界，写入新的不可变实验版本和 render fingerprint。作者保存后经后台机器校验即可直接设为当前版本，试听是可选动作；失败时保持原绑定并报告参数问题，不要求“试听确认—锁定—再绑定”三段操作。历史 Edition、旧音频和官方默认版本不变。P0/P1 不等待该能力。

### 4.4 人物专属音色

人物自动声音链固定为：

```text
作者点击“根据人物生成并使用”一次
  -> 冻结正式人物 revision 快照与当前 binding CAS
  -> CharacterVoiceBrief/1（确定性、可解释）
  -> AI 小说作家自动生成 VoiceDesignDraft
  -> VoiceGenerator 用下一个确定性 seed 生成 1 个私人样音
  -> Nano reference-clone 自动执行技术测试句
  -> 机器校验可解码、非空、时长、削波、指纹与 ModelRun
  -> 创建 machine_validated 的不可变 generated VoiceProfileVersion
  -> binding CAS 未变化时自动绑定并提示“已生成并使用”
```

声音描述只读取已明确保存的字段：年龄/年龄感、作者填写的性别或声音表达、身份、性格、说话习惯、口头禅、语速倾向、音高/质感偏好。不得根据姓名、头像、现实民族或其他未填写属性猜测；缺字段使用“中性/待作者补充”，不能制造人物事实。

生成链自动创建窄化的本地使用/provenance 证据：`source_kind=voice_generator`、精确模型 revision/hash 与 candidate 标识、`purpose=private_novel_narration`、`commercial_use=false`、`redistribution=false`、`voice_cloning=true`、`subject_consent_reference=NULL`；confirmed event 绑定本次作者点击和 command id。这是生成链所需的内部来源/用途证据，不是要求作者勾选的法律或商用声明。人物卡若含有“模仿可识别现实人士”等指令，描述生成只保留抽象声学特征，忽略具体身份/仿声要求，不增加弹窗。

VoiceGenerator 官方可调信号与 Nano 不同：最主要的音色控制是自由文本 `instruction`，可表达年龄感、音色质感、情绪、风格、口音、语速和音高；`text` 是试音内容，不是音色参数。官方推荐解码值为 `audio_temperature=1.5`、`audio_top_p=0.6`、`audio_top_k=50`、`audio_repetition_penalty=1.1`。默认一键路径由 AI 根据人物快照生成 instruction，固定使用官方推荐解码值；折叠详情允许作者事后编辑 instruction 并点“按此描述重新设计并使用”。仅高级人物音色入口可复制本次设计后调整上述四项解码参数与 seed，所有值经服务端 bounds 校验并进入不可变 candidate/ModelRun fingerprint；不在首次生成前摆出一排必填控件。

人物 AI 分析只在作者点击“根据人物生成并使用”或“按最新人物重新设计并使用”后运行，复用 `ai-novel-writer` 当时的有效模型，冻结 `NovelCharacterRevision.id + content_hash` 并记录 requested/actual 模型与无静默回退证据；普通“换一个并使用”只复用既有 draft 并推进 seed，不再次调用 AI。不新增第二套聊天模型选择器，也不因人物卡保存而自动调用。声音描述不写回正式人物卡，只作为本次音色生成输入与详情记录；正常路径不要求作者先审核。

一次点击即授权该异步命令在成功后自动绑定，但不得覆盖作者在任务运行期间做出的更新选择：若 binding CAS 已变化，结果保留为“已生成、未自动应用”，提供一个“使用这个音色”按钮。人物 revision 在运行中变化不让任务反复重启；结果明确记录所用快照。若人物卡后来改变，页面只显示非阻断“人物卡已更新”标签和一键“按最新人物重新设计并使用”，不在普通“换一个”中静默替换设计输入。

“换一个并使用”复用上一次不可变 VoiceDesignDraft/instruction 和解码参数，只推进 seed；成功后原子替换当前绑定，旧绑定仍由历史 Edition 冻结。作者编辑 instruction 或选择“按最新人物”时创建新 VoiceDesignDraft，不原地改写旧设计。高级入口才提供“生成 3 个备选”；它不影响默认一键路径。VoiceGenerator 样音交给 Nano 的二次克隆属于后台技术验证，不是作者确认步骤，也不等于开放用户上传参考录音；用户上传来源继续受原有独立规则。

任一模型、音频或数据库步骤失败都不得改变当前绑定；页面只显示失败原因和“一键重试”。如果 VoiceGenerator 在本机工程验收中不可用，按钮应明确显示“专属音色生成当前不可用”，可另提供“根据人物自动匹配官方音色”，但不得静默降级后仍声称生成了新音色。

### 4.5 私人音色生命周期

| 对象状态 | 用户动作 | 服务端语义 |
| --- | --- | --- |
| 失败、未使用或未晋升的生成结果 | 点“删除”即完成 | 取消 job；无租约/引用后进入短暂可撤销废纸篓，再物理删除并留最小墓碑；不弹确认框 |
| 已生成但从未绑定、未被 Edition 引用 | 点“删除”即完成 | 同上；不要求先归档、预览影响或二次确认 |
| 当前旁白或人物正在使用 | “删除并解除使用” | 一个弹窗列出当前绑定，作者确认一次后原子阻止新使用、解除绑定并启动后台删除 |
| 被历史 Edition 引用 | “删除且让旧朗读不可播放” | 同一个影响弹窗说明受影响 Edition 数量；确认一次后保留文字/审计，删除声音字节并标记旧朗读不可用 |
| 官方 preset | 解除绑定/归档本地档案 | 不删除官方模型目录和 preset 本身 |

候选与 profile 使用两条不混淆的内部生命周期：尚未晋升的 candidate 在自身状态机中使用 `ready|rejected|failed → trash_pending → <prior_state>|deleted`，并保存 `trashed_at/delete_after/trashed_actor/prior_state`；撤销只在 `delete_after` 前回到准确 prior state。物理删除后 candidate 行保留不可反推媒体的 HMAC digest、digest key id 和 delete voice-action-command id 作为最小审计证据，不伪造要求 profile FK 的 AssetTombstone。profile 仍由 `voice_deletion_requests` 管理：未引用 profile 使用 `grace_pending → cancelled|live_deleting → live_deleted_backup_pending|completed|failed`；已使用 profile 使用 `requested → cancelled|live_deleting → live_deleted_backup_pending|completed|failed`，`failed` 只能按原精确计划重试回 `live_deleting`。`grace_pending` 必须有 `execute_after`，撤销必须留下 `cancelled_at/cancelled_actor`（或等价不可变事件）；进入 candidate 物理删除或 profile `live_deleting` 后不再宣称可撤销。这些内部阶段不要求作者逐步确认。在线资产已删但受管备份尚未核实过期时，UI 显示“在线数据已删除，备份等待到期”，不得写“永久删除完成”。

“不保留声音字节”包括上传原件、规范化 reference、生成候选、Nano 克隆参考、试听、以该私人 voice version 合成的 segment master/playback、已有导出及无其他合法引用的派生缓存；只删除参考样音而保留仍可播放的历史 segment 音频不算完成真删除。删除开始前必须 fence 新绑定、生成任务和媒体租约；受影响 Edition 标记 `unavailable_private_voice_deleted`，但正文、revision、script、Edition/Manifest 审计行不级联删除。

锁定的 Voice Version 继续保持不可变，不增加 `locked → deleted` 的伪状态；Profile 进入不可用投影，由 deletion request 与不可反推音频的 HMAC tombstone 表达删除事实。普通 GC 不得承担真删除：只能由已确认 request 绑定的持久精确资产清单获得窄删除许可，禁止新增全局绕过媒体引用保护的开关。

`completed` 只表示项目管理范围内的在线主/副本已按证据核验删除；Time Machine、用户自建快照或其他外部备份统一显示 `external_backup_status=unknown|unmanaged`，不得承诺“全世界永久删除”。只有存在项目可审计 backup manifest 与 retention evidence 时，才使用 `live_deleted_backup_pending` 并最终宣称受管备份到期。

## 5. 朗读设置与音色配置重构

### 5.1 信息架构

保留 `section=reading`，避免破坏工作台与 QwenPaw 原生路由。目标页签收敛为 6 个作者心智入口：

```text
总览
旁白与朗读（兼容旧 reading_panel=narrator）
人物配音
音色库（新增）
识别、发音与停顿（兼容 casting-rules / pronunciation）
存储与隐私（兼容 audio-cache）
```

旧 query key 保持可解析：`narrator`、`characters` 保持语义，`casting-rules` 与 `pronunciation` 映射到新规则页各自子区，`audio-cache` 映射到存储页；不得静默落回总览。若标签改名，只改变可见文案，不让书签或返回导航失效。

### 5.2 当前选项逐项裁决

| 当前选项 | 裁决 | 目标交互 |
| --- | --- | --- |
| 默认旁白 | 保留并前置 | 下拉旁直接提供“浏览 18 个官方音色”，无需先建档 |
| 语言自由文本 | 修改 | 官方音色语言元数据自动带入音色版本；作品朗读语言使用受控 `zh-CN / en / ja-JP`，按作品预填并允许显式改选；不匹配只显示提示，不确认、不阻断 |
| 朗读章节标题/作者的话/分隔内容 | 保留 | 作为基础复选项，解释只影响新脚本/Edition |
| 第一人称与内心独白规则 | 保留 | 移至“文本与角色规则”折叠区，人物选择只显示本书有效角色 |
| 句/段/分隔停顿毫秒 | 保留能力、简化默认 | 提供“紧凑/自然/舒缓”预设；展开高级后才显示精确毫秒 |
| 播放倍速/音量 | 从旁白生成设置移到播放偏好，并完成真实接线 | 即时生效，不重合成；明确与模型语速/音色参数不同；若契约/引擎不能完成就移除无效入口，不保留“保存成功但播放器不消费”的假设置 |
| 分卷/章节覆盖 | 保留 | 默认折叠为“范围覆盖”；显示继承链和受影响范围 |
| 仅异常复核/每章复核 | 保留 | 更名“脚本复核策略”，与云端分析开关保持分离 |
| 本地/云端辅助分析 | 保留安全边界 | 云端不可用时只展示原因，不显示看似可勾选的授权表单 |
| 发音替换/跳过/作用域 | 保留 | 增加命中预览和短句试听 |
| 发音优先级数字 | 修改 | 默认拖拽排序或高/普通/低；高级区保留精确数值 |
| 音频格式 | 不开放作者调节 | 作为只读技术详情，避免把浏览器播放格式误当音色配置 |
| 缓存清理 | 保留 | 继续只清理未引用派生物，和音色删除入口明确分离 |

### 5.3 音色库

音色库分为“官方 18 音色”和“我的音色”。官方卡片支持语言/男女分组过滤、搜索、可选短试听、设为旁白、绑定人物和复制为实验版本；“使用”按钮不依赖试听。我的音色支持 generated 来源、当前绑定、历史使用、试听、换一个、重命名、归档和简化删除；uploaded 仅在未来独立能力开启后出现。

官方卡片不显示版权、商业、主体同意或来源审批按钮，也不在主卡片反复提示公开分发边界。固定官方来源、revision 和本地写作工具模式只放进可展开的“模型详情”，纯展示、零阻断。

人物配音页增加：未配置扫描、当前绑定与来源标签、就地试听、18 音色直接绑定，以及醒目的“根据人物生成并使用”。批量“为未配置人物自动匹配官方音色”可一次执行并返回逐人物结果；真正的 VoiceGenerator 专属音色默认逐人物一键生成，避免 M4 同时加载多任务。部分失败必须准确显示，但成功人物无需再逐项确认。

## 6. 章节播放面板

### 6.1 保留的权威边界

- 继续使用现有 Manifest v2、`NarrationPlayer`、`SegmentPlaybackQueue`、Edition、Range/ETag 和进度 CAS；扩展现有状态模型，不另建第二套播放引擎。
- 播放会话固定同一 Edition；更新 Manifest revision 只扩展同一 Edition 的可播窗口，不能静默切换正文或音色版本。
- 句段 slider 在部分就绪时只允许合法 ready window；不能越过 pending/failed 缺口。
- 普通编辑器单击仍放置光标；段落 gutter、上下文菜单和 `Mod+Alt+Enter` 才触发从当前位置朗读。
- 状态不得压成一个互斥枚举，至少正交保存：内容态（无版本/分析/复核/排队/部分可播/就绪/不可用）、播放态（idle/preparing/buffering/playing/paused/blocked/ended/error）、来源态（当前稿/旧稿/历史 Edition/新 Edition 可用）和布局态（紧凑/完整/详情抽屉）。

### 6.2 目标面板

主面板固定包含：

- 当前稿/旧稿/历史 Edition 状态；
- 当前说话人、Edition 冻结的音色名和来源；历史 Edition 不得用“现在的绑定”冒充旧版本声音；
- 上一句、播放/暂停、下一句；
- 当前时间/当前句、可播放时长/句数、全章生成进度；
- 句段进度条；完整 Edition 就绪后增加连续时间拖动；
- 倍速与音量；音量通过统一接口选择 Web Audio `GainNode` 或 `<audio>.volume` 的单一实际增益后端，禁止两层同时衰减；
- 正文跟随、返回当前朗读位置、从光标/段落朗读；
- 更新朗读、脚本复核、版本选择和失败句段重试；
- 生成中、模型冷加载、缓冲、部分就绪、等待缺口、失败、离线、正文已变化的非颜色提示。

默认使用桌面两行紧凑态；展开态或独立抽屉承载失败句段、版本和技术详情，不能把失败列表继续塞进当前固定 `--anw-chapter-player-height: 94px` 的预留区。布局必须让编辑器安全区随实际紧凑栏变化，抽屉不参与固定高度计算。`≤1024 px` 收纳次要操作，`≤720 px` 使用 64–72 px 主控制栏加底部详情面板；按钮触控尺寸至少 44 px，正文不得被 sticky 面板遮挡。

当前 Edition `resolution_json` 只冻结 profile/version ID 与 authority，没有冻结可变的 profile name/source/preset 展示身份。新 Edition 必须使用版本化 resolution contract 追加 `voice_identity={display_name, source_type, preset_id}` 并纳入 Edition fingerprint；旧 Edition 不回填当前名称，只显示稳定 ID 与“旧版未保存名称”。任何播放 API 都只能读取该冻结 JSON，不能 join 当前 profile 名称或当前绑定来补历史。

### 6.3 播放偏好

倍速和音量先本地即时生效，再通过窄 playback-preferences CAS 写回作品设置；冲突时重新读取并提示，不用过期的整份 settings 覆盖旁白或规则。权威规则冻结为：作品 settings 是倍速/音量偏好的唯一权威；当前会话只做即时未同步态；Edition progress 的 `playback_rate_millis` 仅为旧协议兼容/设置不可用时的故障回退，正常恢复不得覆盖 settings，音量不写入 progress。统一新范围为 0.5–3.0；旧 progress 的 0.25–4.0 值只在 fallback 时 clamp 并提示。播放位置仍按 Edition 保存，倍速/音量均不进入音频 render fingerprint。

### 6.4 可访问性与键盘

- 主控制、进度、音量、倍速、版本和更多操作均有可读 label；
- 状态变化使用节流的 `aria-live`，不能每个音频 tick 刷屏；
- 焦点不因轮询/Manifest 更新跳走；冲突/失败后回到触发动作或错误摘要；
- 播放状态不只依赖颜色，遵守 `prefers-reduced-motion`；
- 空格键只在播放器控制获得焦点时播放/暂停，不劫持编辑器输入；
- 覆盖中文输入法、emoji、撤销/重做、200% 等效缩放和 390 px 窄屏。

## 7. VoiceGenerator 内部工程可用性检查（非作者使用门禁）

### 7.1 `VG0` 固定模型与依赖

必须重新核验并冻结：官方仓库/模型 revision、license/模型卡、文件清单和 hash、Python/torch/transformers/音频依赖、推荐采样参数、模型权重体积及缓存路径。模型文件不得进入 Git、PawApp bundle 或 QwenPaw 核心目录。

既有 T0-D 只能作为风险基线：候选 revision `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`，模型约 4.228 GB，连同 full codec 快照约 10.566 GiB，16 GiB 主机 CPU FP32 静态权重下界约 14.487 GiB；官方示例的 MPS 路径尚未证明，真实下载、导入、生成、Nano 二次克隆和听检证据仍为 0。`VG0` 必须按实施日期重新核验这些时效性事实，不能把旧估算写成已可运行。

### 7.2 `VG1` M4 16 GB 真实尖峰

在仓库外模型缓存和隔离输出目录比较：

1. macOS MPS 受管 worker；
2. Linux/arm64 Compose CPU Sidecar；
3. 不评估浏览器 VoiceGenerator 为正式路径。

同一组项目自有中英文描述与试听句，测冷启动、默认单候选耗时、连续“换一个”三次的总耗时、峰值内存、取消、失败恢复、输出格式、卸载后的内存回收和 Nano 二次克隆。`VG0/VG1` 先用串行运维围栏；产品化迁移必须新增/重构真正跨进程共享的硬件 residency claim，让 Nano 与 VoiceGenerator 在保留各自执行锁的同时共同争用容量 1 的物理重模型资源，并验证加锁顺序和崩溃释放。进程内 mutex 或现有两个不同 key 均不构成互斥证据。

`VG1-GATE` 默认 `NO-GO`；只有同时满足以下条件才继续：

- 固定 revision 能重复安装、校验和卸载；
- 16 GB 机器无 OOM、容器/宿主重启或持续红色内存压力，并保留明确安全余量；
- 完成后模型能释放，Nano 的 300 秒按需卸载和再次加载不回归；
- 至少 3 类虚构人物分别执行默认生成与两次“换一个”，结果可解码、可懂且 seed 间有可感知差异；
- 样音经 Nano 克隆后达到内部技术听检的可懂度与基本辨识度，不要求产品用户逐次试听批准；
- 失败时 capability 保持隐藏，现有 18 官方音色路径完全可用。

真实耗时与内存阈值由 `VG1` 报告回填后由工程流程自动作出 `GO/NO-GO`，不在没有实测时伪造性能承诺，也不把该判断做成作者操作弹窗。一次性施工授权已覆盖 `GO` 后继续实现；只有范围扩大或需要破坏性外部操作时才重新询问。

若 `VG1=NO-GO`，唯一允许的降级是“根据人物卡的明确字段推荐/匹配 18 个官方 preset”，并清楚标成推荐结果；不得把匹配既有音色宣传成“生成了人物专属新音色”。

### 7.3 生产拓扑

若 `VG1` 通过，选中的执行后端只暴露既有 `VoiceDesignAdapter` 窄契约，不拥有小说、人物、音色档案、任务或媒体状态。VoiceGenerator 使用独立依赖环境/进程，不把依赖混入 Nano Sidecar；它完全退出并释放 `LOCK-MODEL-HEAVY` 后才允许 Nano 二次克隆。PawApp 领域服务继续拥有 scope、幂等、CAS、job、ModelRun、媒体发布和版本锁定。新增能力使用独立开关 `AI_NOVEL_TTS_VOICE_GENERATOR_ENABLED`，默认 false；关闭后停止新生成但不破坏既有 generated 版本。

## 8. 数据模型与 API 冻结方向

### 8.1 P0 激活证据预计最小迁移；P1 原则上零 schema 迁移

18 项目录投影本身无需迁移，设置重排、播放器和新 Edition 的版本化 JSON 投影原则上复用现有表。但当前数据库约束把 `locked` 等同于 `quality_state=accepted`，状态只允许 `draft → preview_ready → locked`，锁定服务又要求未过期真实 Nano preview 与匹配 ModelRun；这与“不试听也能直接使用、且不伪造质量事实”冲突。故 P0 不再承诺零迁移。

`P0-CONTRACT-GATE` 是内部数据库设计检查，不是作者操作步骤。它必须冻结最小激活证据方案并做 PostgreSQL 反例测试。推荐方向是：

- 为 Voice Version 增加受约束的 `activation_basis`（至少 `preview_confirmed / explicit_official_preset_selection / character_one_click_generation / experimental_machine_validated`）和与之正交的 validation evidence，或采用语义等价的窄字段；
- official preset 可不试听直接进入可用且不可变状态；generated/实验版本在机器验证与 ModelRun 闭包通过后直接可用，不要求 `human_accepted`；
- uploaded 来源不因本次减负而放宽，且不进入当前个人写作工具主路径；
- 更新 DB trigger、DTO、fingerprint 与 `require_usable_voice`，只允许与 source_type 匹配的 activation/validation 组合；
- 新增不可变 voice action command/result 记录，统一承载 official 直用和 character generate-and-use，供 `VoiceActionReceipt.resource_id` 指向并重放多资源结果；不能假设现有单一 `resource_id` 已保存响应快照；
- 不重写旧 Voice Version、Edition、preview 或绑定，既有三个正式绑定不得被迁移或替换。

若内部契约检查找到不新增字段且仍能满足上述事实分离、并发重放和数据库防线的完整证据，可以取消该迁移；否则按当前证据由唯一 migration Owner 在 `0029` 之后的实时新 head 上实施最小迁移。不得以伪造试听或放宽所有 source_type 的质量约束来守住“零迁移”目标。

### 8.2 官方目录与直接选择 API

目录响应升级为 `moss-tts-official-preset-catalog/2.0`，精确包含 18 项，并新增：

```text
validation_tier
language_scope
selectable_now
previewable_now
renderable_existing
usage_notice
```

新增原子动作：

```text
POST /novels/{novel_id}/official-voice-selections
Idempotency-Key: ...

target =
  { kind: "narrator", expected_settings_version }
  | { kind: "character", character_id, expected_binding_version, expected_settings_version }
preset_id
```

响应返回 replay、不可变 selection command/result、官方 profile/version 资源，以及精确一种当前 `settings` 或 `character_binding` 投影；冻结结果与当前投影必须分字段，不能在目标后来被用户改绑后伪装原命令从未成功。服务端从固定目录和作品设置派生 provenance、显示名、目标语言与模型参数，客户端不能提交 prompt codes、权重路径、provenance 或语言覆盖。语言不匹配只作为非阻断标签返回，不要求确认字段、弹窗或第二次提交；前端在一次“使用”动作中透明携带当前设置/绑定版本，不向作者暴露 CAS 概念。

原子动作必须复用/提取现有 `VoiceProductService` 的官方 provenance、rights 和 fingerprint 规则，不得在新服务中复制一套逐渐漂移的官方版本构造逻辑。请求 hash 包含 scope、target、原 CAS 和 preset；鉴权/scope 后先查幂等记录，completed 命令直接重放冻结结果，只有新命令才加锁校验 CAS。幂等回执的 `resource_id` 指向稳定 selection command；同一事务产生的 profile/version/settings 或 binding 通过不可变 result 和领域引用关联。

### 8.3 播放面板补充 API

```text
PATCH /novels/{novel_id}/narration-playback-preferences
GET   /narration-editions/{edition_id}/segment-voices
```

第一个接口只接受 `expected_settings_version + playback_rate + volume`，原子 patch 这两个字段，不能覆盖旁白、脚本规则、停顿或隐私模式。第二个接口只从版本化 `resolution_json.voice_identity` 返回当前 owner/workspace 可见的 Edition 冻结投影：`segment_id/profile_id/voice_version_id/frozen_display_name/source_type/preset_id/identity_contract_version`；旧 Edition 缺失身份时返回稳定 ID 与显式 `legacy_identity_missing=true`，不 join 当前 profile。接口不返回正文、prompt codes、文件路径或私人描述，公共 Manifest v2 保持不含人物/声音隐私字段。

### 8.4 高级参数 API

Nano 使用独立 `preset-experimental` version 创建接口，不扩张“官方默认直接选择”的请求体。Sidecar/adapter 协议版本、参数 DTO、服务端上下界、fingerprint 和兼容策略必须在 `ADV-CONTRACT-GATE` 先冻结；旧协议继续只能生成官方默认版本，不能忽略新字段后假装成功。

VoiceGenerator 高级参数不复用 `preset-experimental`；仅在 `VG1=GO` 后由第 8.5 节同一 voice-generation command 接收版本化 `design_parameters`（可编辑 instruction、seed 和官方四项 audio decode 值）以及可选 `candidate_count=3`。默认人物卡命令不传 `design_parameters`，服务端固定填充官方推荐值；高级请求必须指明 `voice_design_decode_contract_version`，未知字段/越界值直接拒绝，不得静默忽略。

### 8.5 VoiceGenerator 一键命令与数据

仅在 `VG1-GATE=GO` 后创建下一条线性迁移。当前 QwenPaw `ai-novel-writer` 调用是 HTTP 请求作用域内的 `ctx.chat`，现有 narration worker 不持有该 Agent context；因此不得在计划中虚构“已有全后台 Agent worker”，也不新建第二套 Agent Runtime。默认交互冻结为“一次用户点击，两段内部 HTTP/任务编排”：

```text
POST /novels/{novel_id}/characters/{character_id}/voice-generation-commands
Idempotency-Key: ...

mode = generate_and_use | regenerate_and_replace | redesign_and_replace
expected_binding_version

generate_and_use/redesign_and_replace:
  expected_character_revision_id
  expected_character_content_hash
  design_source = ai_character_revision | author_edited_instruction

regenerate_and_replace:
  base_voice_design_draft_id

POST /voice-generation-commands/{command_id}/analysis-runs
Idempotency-Key: <command-key>:analysis

GET  /voice-generation-commands/{command_id}
POST /voice-generation-commands/{command_id}/cancel
```

人物卡按钮透明携带所需 revision/draft 与 binding 版本；作者只点击一次。第一个接口只在短事务内创建/重放 command，立即返回 `202 queued`。`generate_and_use` 和 AI 来源的 `redesign_and_replace` 由前端在同一次交互中自动调用 `analysis-runs`，不显示第二个按钮；该路由复用既有 `ai-novel-writer` 依赖和 `CreativeGenerationJob(kind=character_voice_description)`，先事务性领取 command analysis lease，再在数据库事务外调用 `ctx.chat`，严格校验 requested/actual 模型和结构化输出，最后以短事务绑定新 VoiceDesignDraft 并入队 VoiceGenerator。

`regenerate_and_replace` 必须复用服务端验证的同一 `base_voice_design_draft_id`，只推进 seed，因此不调用 AI，创建 command 后可直接进入 `generating`。`design_source=author_edited_instruction` 的 `redesign_and_replace` 将作者编辑文本固化为新的不可变 VoiceDesignDraft，只做本地结构/边界校验后入队，也不调用 AI。三种 mode 使用 discriminated union DTO，不允许同时传“旧 draft”和“新人物/编辑描述”导致优先级不明。

页面刷新、网络断开或请求取消后，同一 command/idempotency key 必须先复用已 `ready` 的 CreativeGenerationJob；只有原 analysis lease 过期且没有可复用结果时才允许新 attempt，原无 owner 的 `running` 记录必须收敛到可诊断失败，不得永久占用。页面重新打开可自动续领 `queued/analyzing` command；这是恢复逻辑，不增加用户确认。

`cancel` 对 command 是单调且幂等的：若 `ctx.chat` 已在运行但宿主不支持物理中断，服务端记录 `cancel_requested`，等调用返回后只完成审计/计费证据而不绑定输出、不入队 VoiceGenerator；若运行时支持取消则使用该公开能力。已取消 command 不能被页面自动续领，重新生成需作者点“重试”并创建有关联的新 attempt，不得复活原终态。

VoiceDesignDraft 就绪后由现有后台任务系统按 `generating → nano_validating → binding → completed` 推进；AI 路径的完整状态为 `queued → analyzing → generating → nano_validating → binding → completed`，复用/编辑 draft 路径合法跳过 `analyzing`。失败或取消进入明确终态，任一步失败都不改变原绑定。默认一次只创建一个确定性 seed；“换一个并使用”以 `regenerate_and_replace` 推进 seed。高级入口可复用同一命令契约请求 `candidate_count=3`，但不得污染默认路径。

最小数据模型为：

- `voice_design_drafts`：owner/workspace/novel/character scope、不可变 `design_source=ai_character_revision|author_edited_instruction`、`source_character_revision_id + source_character_content_hash`、`CharacterVoiceBrief/1`、instruction、四项 decode 值、contract/model/parameter fingerprint、requested/actual 模型证据与可空 parent draft；作者编辑或按最新人物重新设计都新建 draft，不原地改写；
- `voice_design_commands`：owner/workspace/novel/character scope、mode/discriminator、点击时的 `expected_binding_version`、AI/编辑设计的人物快照或换音时的 `base_voice_design_draft_id`、最终 `voice_design_draft_id`、seed progression、可空 CreativeGenerationJob id/attempt、analysis lease/过期、幂等结果、状态和失败码；CreativeGenerationJob 仅允许在 `design_source=ai_character_revision` 时非空；
- `voice_design_candidates`：command/draft、ordinal、seed、分离的 `voice_generator_job_id/model_run_id` 与 `nano_preview_id/job_id/model_run_id`、私有媒体、model/parameter fingerprint、`queued/running/ready/selected/rejected/trash_pending/deleted/failed` 状态、失败码和提升关系；不得用一个含糊 `job` 字段伪装两次模型运行。默认命令只生成 ordinal 1，高级三备选才允许 `partial_ready`；
- `voice_generated_reference_links` 或等价专用不可变链接：只允许机器验证通过的 generated candidate 提升为 Nano reference；不得直接放宽既有 uploaded-only reference trigger；
- 默认单候选经 Nano 技术验证后，在一个事务中冻结 checksum、ModelRun、描述/参数指纹，创建 `VoiceProfileVersion(source_type=generated)`、建立 generated reference link，并在绑定 CAS 仍匹配时自动绑定；
- 每个 candidate 的 VoiceGenerator 阶段复用已冻结的 `narration.voice_generate` job kind/attempt，Nano 技术克隆验证单独复用 `narration.voice_preview` job/preview；两者都复用 `background_jobs`、`background_job_attempts`、`model_run_records` 和共享重模型 residency claim。不新造 `narration.voice_design`，不建第二套任务表，不声称一个 job 跨越两个资源类。

`VG-CONTRACT-GATE` 必须先冻结 mode discriminated union、draft 不可变与来源优先级、请求态 Agent 桥边界、本地后台状态机、迁移字段、CAS、唯一 `(command_id, ordinal)`、单一晋升结果、CreativeGenerationJob/VoiceGenerator job/Nano job/candidate 终态闭合、取消/重试和媒体晋升规则，迁移不得反向发明产品契约。迁移通过后，`VG-AI-BRIDGE-GATE` 再用真实请求路径验证 CreativeGenerationJob 新 kind、lease/断线重放、模型验证和“不在长事务内调模型”的反例。两个 gate 都不转化为作者步骤。人物 revision 以点击瞬间快照为本次新设计输入；生成期间人物卡后来变化不阻断本次任务，只有显式 `redesign_and_replace` 才读取新 revision。绑定 CAS 若已变化，结果保留为“已生成、未自动应用”并提供一次“使用此音色”，绝不覆盖作者较新的选择。

机器校验至少覆盖可解码、非空、时长边界、明显削波、fingerprint、ModelRun 与 Nano 二次克隆闭包。generated 版本必须新增专用数据库约束，达到与 preset/uploaded 等强但不混淆来源的证据标准；不得伪造人工试听/接受，也不得只修改 Python 分支绕过现有 `0021/0022` trigger。

人物描述正文保存在本地权威 command/draft 中，供作者在折叠详情里查看、编辑后点“按此描述重新设计并使用”；它不是首次生成前的必填确认。日志、幂等、模型运行证据和诊断只保存版本化 HMAC，不打印描述或试听文本。

### 8.6 删除 API 与单层交互

后端继续采用持久、可恢复的精确删除计划，但作者界面不展示“创建请求—查看预览—再次确认—执行”多段流程。接口在 FK 尖峰后冻结为：

```text
POST /voice-profiles/{profile_id}/discard-unreferenced
POST /voice-profiles/{profile_id}/deletion-requests
GET  /voice-deletion-requests/{request_id}
POST /voice-deletion-requests/{request_id}/confirm
POST /voice-deletion-requests/{request_id}/cancel
POST /voice-deletion-requests/{request_id}/retry
DELETE /voice-design-candidates/{candidate_id}
POST /voice-design-candidates/{candidate_id}/restore
```

所有变更接口都要求 `Idempotency-Key`；profile 操作透明携带 `expected_profile_version`，candidate 操作携带候选版本/指纹。未被绑定、未被 Edition 引用且未提升为 Voice Version 的候选，点击删除即调用 `DELETE`，不弹确认框；服务端在同一 voice action command/result 中验证无引用，将 candidate 转为 `trash_pending` 并返回 `undo_deadline`，窗口结束后才物理删除。候选撤销固定调用 `restore`，回放到服务端冻结的 prior state；它不使用强制 `voice_profile_id` 的现有 `voice_deletion_requests`。

已提升但从未使用、无任何引用的独立私人 profile 固定调用 `discard-unreferenced`，返回 `grace_pending` deletion request 及 `undo_deadline`；这条路径的撤销由 deletion request `cancel` 执行。不再使用“语义等价”留给实现临时发明第三套接口，也不为候选伪造 profile deletion request。

当前使用或被历史 Edition 引用的私人 profile，前端在一次弹窗中展示影响摘要并完成唯一一次确认；请求创建、影响指纹和确认调用可由同一界面状态机透明编排。后端创建请求时冻结有时效的影响快照：当前旁白、人物绑定、生成中 job/租约、历史 Edition、在线资产、派生缓存/导出、备份状态和不可逆后果。确认仍携带 request id、profile CAS 与 impact fingerprint，均为防竞态的内部字段；引用变化时返回冲突并刷新同一个弹窗，不把它变成常规多重门禁。未点击影响确认时可用 `cancel` 收口；`retry` 只接收可重试的 failed request，复用原 request/精确资产计划，不新建无关联删除任务。

首版 `true_delete_private_voice` 以整个私人 profile 为目标，新生成音色必须建立独立私人 profile。含 official preset 与 private version 的 legacy 混合 profile 一律阻断，并在 `MNX-DEL-AUDIT` 后决定“迁移绑定到 canonical 官方 profile”或另立 version-scope 删除，不得误删官方内容。当前 `voice_deletion_requests` 缺少 command `discard_unreferenced_private_voice`、状态 `grace_pending/cancelled`、`execute_after/cancelled_at`、影响快照/过期、profile CAS、精确资产计划和备份证据；候选表若因 `VG1=GO` 存在，DEL migration 另窄化增加 `trash_pending` 形状与时间/原状态字段，不改成多态 deletion request。按现有证据，真删除产品化必须由唯一 migration Owner 添加最小字段/表与 request-scoped trigger。不得先删字节再补数据库状态，也不得在本计划中预先假定具体 write set 已完整。

受影响 Edition 保留审计行并进入 unavailable；若仍是 `DocumentNarrationState.current_edition_id`，指针保留用于解释当前不可播放原因，播放 API 返回 `unavailable_private_voice_deleted`，不得静默切到另一 Edition。所有共享该 voice version render 的 Edition 同步进入影响快照；true-delete tombstone 必须携带非空 `deletion_request_id`。

## 9. 施工波次与内部工程验收点（非产品使用门禁）

| 波次 | 工作包 | 标记 | 目标与退出条件 |
| --- | --- | --- | --- |
| W0 | `MNX-G0` | `SER/GATE/MUTEX` | 计划 32 已释放共享所有权；开工时重取 migration/人物/API 基线，核对源码 tree/PawApp 包/已安装 bundle hash，冻结 catalog/直接选择/播放器 DTO 和功能开关；无代码施工 |
| W0 | `MNX-PRUNE-AUDIT` | `SER/GATE` | 只读枚举旧 TTS 入口、实现、样式、DTO、测试夹具、配置和依赖，建立 redundancy ledger；没有调用者与替代证据的条目不得标记删除 |
| W1 | `MNX-P0-CONTRACT` | `SER/GATE/MUTEX` | 用真实 PostgreSQL 约束冻结 activation basis、selection command/result、UUIDv5 scope、幂等顺序、透明设置/绑定 CAS 和 catalog v1/v2；形成 `P0-CONTRACT-GATE` |
| W1 | `MNX-P0-MIG` | `SER/MUTEX` | 仅按 contract gate 的已证最小 write set 创建当时下一线性 migration；迁移/回退/并发约束通过后才开放实现 |
| W1 | `MNX-P0-BE`、`MNX-P0-FE` | `PAR-C` | 18 目录、原子直用、音色库卡片和兼容路由；聚焦测试通过 |
| W1 | `MNX-P0-INT` | `SER/INT/GATE` | 公共 DTO/API 接线、18 项真实短句技术烟测、三档语言标签、现有绑定非回归；形成 `P0-GATE` |
| W2 | `MNX-P1-BE-CONTRACT` | `SER/GATE/MUTEX` | 冻结 playback-preferences、Edition resolution v2/历史 identity fallback 与读取 API；先接后端和契约测试 |
| W2 | `MNX-P1-PLAYER-CORE`、`MNX-P1-SETTINGS`、`MNX-P1-CHARACTERS` | `PAR-C` | 播放音量/进度核心、设置/规则、人物覆盖表分开施工；明确默认值恢复优先级，消灭无效播放偏好；不共享文件 |
| W2 | `MNX-P1-PLAYER-VIEW` | `SER` | 先修固定 94 px/失败列表遮挡，再做正交状态、紧凑/展开/抽屉、窄屏、键盘和无障碍；依赖 player core DTO |
| W2 | `MNX-P1-INT` | `SER/INT/GATE` | 工作台接线、三桌面+窄屏、IME、旧稿/失败/partial-ready；形成 `P1-GATE` |
| W3 | `MNX-ADV-SPIKE` | `SER/MUTEX/GATE` | 冻结 decode contract v2 双读、HMAC/ModelRun/render fingerprint 与质量/缓存回归并形成 `ADV-CONTRACT-GATE`；不达标则保持隐藏 |
| W3 | `MNX-VG0-A`、`MNX-VG0-B` | `PAR` | 分别只读冻结官方模型/许可证与本机依赖/拓扑候选；汇合后才能进入真实模型测试 |
| W3 | `MNX-VG1` | `SER/MUTEX/GATE` | 消费 VG0 冻结输入，独占模型/运行资源执行真实 M4 尖峰；形成 `VG1-GATE` |
| W4 | `MNX-VG-CONTRACT` | `SER/GATE/MUTEX` | `VG1=GO` 后先冻结公共 DTO、三种 mode、draft/candidate 状态机、迁移字段、三类 job/ModelRun、AI 桥边界、rights 与资源 claim；形成 `VG-CONTRACT-GATE`，不让 migration 反向定义产品行为 |
| W4 | `MNX-VG-MIG` | `SER/MUTEX` | `VG-CONTRACT-GATE` 后沿本文一次性施工授权分配当时下一 Alembic revision；升级/回退/约束测试通过 |
| W4 | `MNX-VG-AI-BRIDGE` | `SER/GATE/MUTEX` | 迁移通过后复用现有 CreativeGenerationJob/`ai-novel-writer` 建立请求态分析桥，验证两段内部编排、lease/重放和模型校验；形成 `VG-AI-BRIDGE-GATE` |
| W4 | `MNX-VG-RUNTIME`、`MNX-VG-DOMAIN`、`MNX-VG-FE` | `PAR-C` | 迁移与 AI bridge 契约冻结后，运行时、领域服务、人物卡 UI 按不重叠文件独立施工 |
| W4 | `MNX-VG-INT` | `SER/INT/GATE` | 一键生成并使用、换一个、取消/恢复、Nano 技术校验、CAS 冲突保护与资源卸载；形成 `VG-GATE` |
| W5 | `MNX-DEL-AUDIT` | `SER/GATE` | 枚举精确 FK、Profile 混源、Edition/Manifest/current pointer/render/media/备份影响，产出并冻结精确 write set 与迁移；审计结论在既定范围内可继续施工，无需再次请示 |
| W5 | `MNX-DEL-BE`、`MNX-DEL-FE` | `SER → PAR-C` | 审计冻结 schema/API/物理删除计划后，主代理先完成共享契约，再让不触碰共享文件的一键删除/单次影响确认 UI 并行施工 |
| W5 | `MNX-DEL-INT` | `SER/INT/GATE` | 竞态、失败恢复、历史不可用、墓碑和备份文案验收 |
| W6 | `MNX-PRUNE` | `SER/MUTEX/GATE` | 只删除 ledger 中已证明“完全替代且无独立价值”的精确条目，移除对应接线与无用依赖；所有保留项写明调用者/理由/sunset，不把已确认冗余延期为 TODO |
| W6 | `MNX-FINAL` | `SER/INT/GATE` | `MNX-PRUNE` 通过后执行全量测试、打包、隔离安装/升级/卸载、真实浏览器/听感、资源与文档一致性；不得自动提交/推送 |

`MNX-G0` 与 `MNX-PRUNE-AUDIT` 共同构成 W1–W6 的全局前置；任一未通过都不得开始代码施工。各波汇合时由主代理把新发现的候选及证据追加到 ledger，但实际删除统一留给 W6 的 `MNX-PRUNE`，避免并行包越权删文件或在替代路径尚未接稳时提前清理。

### 9.1 阶段估算

以下是 Codex 有效工程时间的粗估，不含模型下载带宽；内部听检由施工团队完成，不作为作者逐阶段等待项：

- P0（含契约与预计最小迁移）：22–36 小时；
- P1（含 Edition identity 与播放器后端契约）：28–44 小时；
- 高级参数尖峰：12–20 小时；
- VoiceGenerator 尖峰：12–24 小时，若 GO 则沿一次性施工授权继续实施 36–60 小时；
- 私人音色删除审计：8–16 小时；审计冻结 write set 后实现与恢复验证 28–48 小时；
- 冗余调用图审计、精确删除和回归：8–16 小时，随各波记录候选并在 W6 统一收口；
- 对已启用范围的最终真实验收：12–24 小时。

VoiceGenerator NO-GO 时，总工期不能把未实施的 `P2-VG` 写成失败；P0/P1 独立发布。

## 10. 子代理并行施工设计

唯一集成责任人：主代理。用户一次性批准本文施工后，子代理只在内部前置验收点通过且文件 Owner 已释放时派发，不再按非破坏性阶段重复请示。公共 schema、Alembic、长期运行态、最终 Git 始终串行。

### 10.1 工作包所有权

串行/集成包由主代理唯一持有：

| 工作包 | 前置 | 唯一目标与允许修改 | 禁止范围 | 必测与证据 |
| --- | --- | --- | --- | --- |
| `MNX-G0` | 本文一次性施工授权 | 冻结基线；仅本文及新 `docs/开发文档/证据/MOSS-TTS-Nano优化/W0-基线.md` | 不改代码/数据库/安装态 | status、migration head、tree/package/bundle/host hash |
| `MNX-PRUNE-AUDIT` | G0 | 只读扫描本计划全部 TTS 源码、测试、样式、配置、Compose/打包与依赖引用；唯一允许写入新 `docs/开发文档/证据/MOSS-TTS-Nano优化/redundancy-ledger.md` | 不修改/删除源码、测试、迁移、历史证据、依赖或用户 dirty 文件；不因名称相似判定冗余 | 每条候选的精确 path/symbol、调用图、替代物、独立风险覆盖、删留裁决、owner、验证与恢复证据 |
| `MNX-P0-CONTRACT` | G0、PRUNE-AUDIT、本文一次性施工授权 | 本文、同证据目录 `P0-contract.md`、新 `tests/narration/test_official_voice_selection_contract.py` | 不改历史迁移，不绕 trigger | PostgreSQL 约束反例、幂等重放、UUID scope、v1/v2 冻结 |
| `MNX-P0-MIG` | P0 contract 判定需迁移 | `backend/models.py`、当时下一条 migration、`backend/narration/production_runtime.py`、`scripts/tts/bootstrap_digest_keyring.py`、`tests/narration/test_migrations.py`、`tests/narration/test_voice_product_schema_postgres.py` | 不改包括 `0025–0029` 在内的旧 migration；不覆盖开工时用户 dirty diff | upgrade/约束/回退兼容、旧版本不改写 |
| `MNX-P0-INT` | P0 BE/FE、迁移（若需） | `backend/narration/schemas.py`、`backend/narration/settings_api.py`、`backend/narration/narration_api.py`；`frontend/src/narration/contracts.ts`、`contracts.test.ts`、`api.ts`、`api.test.ts`、`reading-overview.ts`、`reading-overview.test.ts`、`reading-page.ts`、`reading-page.test.ts`、`index.ts` | 不改 QwenPaw 核心/正式绑定 | 36 动作矩阵、真实 18 smoke、路由/深链、当前绑定非回归 |
| `MNX-P1-BE-CONTRACT` | P0 release 或独立冻结 | `backend/narration/contracts.py`、`schemas.py`、`settings_api.py`、`privacy.py`、`playback_api.py`、`narration_api.py`、`edition_service.py`、`editions.py`；`tests/narration/test_settings_api.py`、`test_settings_contract.py`、`test_reading_privacy.py`、`test_playback_progress_api.py`、`test_edition_service.py`、`test_narration_requests_api.py`、新 `test_edition_voice_identity.py`；前端读取契约 `frontend/src/narration/chapter-contracts.ts`及 test | 不改 Manifest v2 公共隐私边界，不 join 当前名称补历史 | playback CAS/范围、resolution v2 fingerprint、legacy identity |
| `MNX-P1-INT` | P1 子包完成 | `frontend/src/narration/chapter-narration-session.ts`及 test、`reading-overview.ts`及 test、`reading-page.ts`及 test、`chapter-narration-workbench.integration.test.ts`、`chapter-narration.integration.test.ts`、`reading-page.integration.test.ts`、`reading-accessibility.test.ts`、`index.ts`、`narration/api.ts`及 test、`narration/styles.ts`、`styles/t2-b.ts`、`frontend/src/workbench-v2.ts`、`frontend/src/workbench-studio.ts`、`frontend/src/workbench-route.ts`及 test、`frontend/src/styles.ts` | 不覆盖开工前 dirty diff | 深链、状态矩阵、焦点、IME、全视口真实浏览器 |
| `MNX-ADV-SPIKE` | P1 契约稳定、本文一次性施工授权 | `backend/narration/contracts.py`、`fingerprints.py`、`runtime.py`、`sidecar_server.py`、`worker.py`、`voice_product.py`；`tests/narration/test_contracts.py`、`test_runtime.py`、`test_sidecar_server.py`、`test_worker_model_run_postgres.py`、`test_voice_product.py` 及证据 | 不改官方默认历史版本，不吞未知字段 | v1/v2 双读、HMAC/ModelRun/cache、参数 bounds/质量 |
| `MNX-VG1` | VG0 汇合、本文一次性施工授权 | `scripts/tts/benchmark_voice_generator.py`、新 `validate_voice_generator_clone.py`、VG1 证据目录 | 不改生产 runtime/schema/长期安装 | M4 内存/swap/RTF/取消/卸载/Nano clone 听检 |
| `MNX-VG-CONTRACT` | VG1=GO | `backend/narration/contracts.py`、`backend/narration/schemas.py`、`frontend/src/narration/contracts.ts`、`frontend/src/narration/contracts.test.ts`、新 `tests/narration/test_voice_generation_contract.py`及 `docs/开发文档/证据/MOSS-TTS-Nano优化/VG-contract.md` | 不改 models/migration/routes/worker/UI，不在 DTO 中加入第二套模型选择器或用户确认门禁 | discriminated union、状态转移、字段/约束清单、rights/provenance、三类 job/ModelRun、AI bridge fixture |
| `MNX-VG-MIG` | VG-CONTRACT-GATE | `backend/models.py`、当时下一线性 migration、`backend/narration/production_runtime.py`、`tests/narration/test_migrations.py`、`tests/narration/test_voice_product_schema_postgres.py`及新 VG schema PostgreSQL tests | 不改 0010/0021/0022，不放宽 uploaded trigger，不偏离冻结 DTO/字段清单 | command/candidate 状态机、generated link、analysis lease、rights provenance、共享 residency claim、回退 |
| `MNX-VG-AI-BRIDGE` | VG migration、VG-CONTRACT-GATE | `backend/creative_services.py`、`backend/creative_schemas.py`、`backend/creative_api.py`、`backend/model_runtime.py`、新 `backend/narration/voice_design_analysis.py`、新 `tests/test_character_voice_description_api.py`、`tests/test_model_runtime.py`及桥接证据 | 不把 `ctx.chat` 移入 narration worker，不新建 Agent Runtime，不在长事务内调模型，不改变冻结 narration DTO | 新 kind、模型一致性、JSON 校验、lease 过期、断线/幂等重放、ready job 复用 |
| `MNX-VG-INT` | VG 子包完成 | `backend/narration/worker.py`、`production_runtime.py`、`narration_api.py`、`backend/background/jobs.py`、`plugin.py`、`compose.yaml`；`frontend/src/narration/api.ts`、`character-voice-panel.ts`及 test、`reading-page.ts`及 test、`index.ts`、`frontend/src/workbench-studio.ts`、`frontend/src/workbench-route.test.ts` | 不让子代理争用 shared worker/runtime，不修改冻结 DTO/状态机，不修改 QwenPaw 上游 | CreativeGenerationJob/VoiceGenerator/Nano job、共享资源/媒体全链、能力关闭、安装升级卸载 |
| `MNX-DEL-AUDIT` | 本文一次性施工授权、前序共享 owner 释放 | 仅新 `docs/开发文档/证据/MOSS-TTS-Nano优化/DEL-audit.md` | 不改 schema/media/数据 | FK/混源/profile scope/current pointer/render/备份 write set |
| `MNX-DEL-BE` | DEL-AUDIT 冻结 write set | 以下是不可扩张的最大允许集，审计只能缩减：`backend/models.py`、当时下一线性 migration、新 `backend/narration/voice_deletion.py`、`backend/narration/media.py`、`storage.py`、`privacy.py`、`edition_service.py`、`editions.py`、`playback_api.py`、`narration_api.py`、`schemas.py`、`worker.py`、`backend/background/jobs.py`；新 `tests/narration/test_voice_deletion.py`、`test_voice_deletion_api.py`及现有 `test_media.py`、`test_media_postgres.py`、`test_edition_service.py`、`test_playback_recovery.py`、`test_migrations.py`、`test_voice_product_schema_postgres.py` | 报告未冻结的文件不得修改；不用普通 GC/全局绕过；不让 candidate 伪装 profile request | candidate trash/restore、profile grace/cancel、三崩溃边界、fence、对账、tombstone、backup semantics |
| `MNX-DEL-INT` | DEL BE/FE 完成 | `frontend/src/narration/contracts.ts`、`api.ts`、`reading-overview.ts`及 test、`reading-page.ts`及 test、`reading-page.integration.test.ts`、`reading-accessibility.test.ts`、`index.ts`、`frontend/src/workbench-studio.ts`、`frontend/src/workbench-route.test.ts`；新 DEL 集成证据 | 不操作真实用户媒体，不改候选/profile 后端状态契约 | 影响快照变化、候选撤销、profile 撤销、不可用 Edition、重启收敛、文案 |
| `MNX-PRUNE` | P0/P1/ADV/VG/DEL 中实际启用范围已汇合、ledger 已冻结 | 仅可修改或删除 `redundancy-ledger.md` 中逐条列出的精确源码/测试/样式/配置/manifest 路径，并正常更新其中明确归因于被删依赖的项目清单及锁文件；该精确列表必须在开包前由主代理冻结，包内不得扩张 | 不删除已执行迁移、历史验收/审计原始证据、仍有调用者的兼容层、独立负向/恢复测试、QwenPaw 上游或用户 dirty 文件；不手改锁文件 | removed-symbol 零引用、替代路径聚焦回归、依赖/Compose/打包检查、保留项理由与 sunset、`git diff --check` |
| `MNX-FINAL` | 本文授权范围内各内部 gate、PRUNE-GATE | 打包/隔离安装/升级/卸载；仅在实际启用范围冻结后协调更新 `plugin.json`/`pyproject.toml` 版本、根 `README.md`、`docs/README.md`、`docs/开发文档/README.md`、18 号文档当前口径 supersession、ADR-0005、新证据索引及当前 capability matrix；不自动提交 | 不把 NO-GO 能力写成失败或已实现，不操作唯一长期环境，不重写历史证据原文/hash | 全量回归、版本/包一致、文档链接、digest 回退、原生 QwenPaw 非回归 |

以下为可下放工作包；只有标记 `PAR/PAR-C` 且位于同一 ready set 的包才同时施工，`MNX-P1-PLAYER-VIEW` 仍按 W2 依赖串行。公共契约未冻结不派发，任何同时施工的文件集合必须互不重叠：

| 工作包 | 前置 | 唯一目标与允许修改 | 禁止范围 | 必测与证据 |
| --- | --- | --- | --- | --- |
| `MNX-P0-BE` | P0 contract/migration | `backend/narration/official_presets.py`、`voice_product.py`、`voices.py`、新 `official_voice_selection.py`；`tests/narration/test_official_presets.py`、`test_voice_product.py`、`test_voices.py`、新 `test_official_voice_selection.py` | 不改 schemas/settings/models/migration/runtime | catalog、事务回滚、receipt replay、并发/CAS |
| `MNX-P0-FE` | catalog/API fixture 冻结 | 新 `frontend/src/narration/official-voice-library.ts`、`official-voice-library.test.ts`、`official-voice-use-state.ts`、`official-voice-use-state.test.ts`、`official-voice-selection-panel.ts`、`official-voice-selection-panel.test.ts`、`styles/voice-library.ts`；`voice-preview-playback.ts`、`voice-preview-playback.test.ts`、`voice-source-panel.ts`、`voice-source-panel.test.ts`、`voice-source-workspace.ts`、`voice-source-workspace.test.ts` | 不改 contracts/api/reading-page/host styles | 键盘、空态、18 名称、非阻断语言提示、一步使用状态 |
| `MNX-P1-PLAYER-CORE` | P1 BE contract | `frontend/src/narration/narration-player.ts`、`narration-player.test.ts`、`segment-playback-queue.ts`、`segment-playback-queue.test.ts`、`chapter-playback.ts`、`chapter-playback.test.ts` | 不改 panel/style/session | 单增益后端、latest-wins、时间/进度、rate authority |
| `MNX-P1-SETTINGS` | P1 DTO fixture | 新 `frontend/src/narration/reading-preferences-panel.ts`、`reading-preferences-panel.test.ts`、`scope-overrides-panel.ts`、`scope-overrides-panel.test.ts`、`reading-rules-workspace.ts`、`reading-rules-workspace.test.ts`；`reading-rules-panel.ts`、`reading-rules-panel.test.ts`、`pronunciation-panel.ts`、`pronunciation-panel.test.ts`、`styles/t2-f.ts`、`styles/t2-g.ts` | 不改 reading-page/公共 DTO | 继承、语言、自然停顿、规则合并、命中预览 |
| `MNX-P1-CHARACTERS` | character DTO 冻结 | `frontend/src/narration/character-voice-panel.ts`、`character-voice-panel.test.ts`、`styles/t2-c.ts`、新 `character-voice-roster.ts`、`character-voice-roster.test.ts` | 不改人物 authority/modal/workbench | 缺口、来源、批量逐项结果、窄屏 |
| `MNX-P1-PLAYER-VIEW` | player core | `frontend/src/narration/chapter-narration-panel.ts`、`chapter-narration-panel.test.ts`、`styles/t4-chapter.ts`、新 `chapter-player-view-state.ts`、`chapter-player-view-state.test.ts` | 不改 core/session/host styles | 正交状态、失败抽屉、44 px、1024/720/390/200% |
| `MNX-VG0-A` | 允许资料核验 | 仅 `docs/开发文档/证据/MOSS-TTS-Nano优化/VG0-official.md` | 不下载模型、不改代码 | 官方 revision/license/files/deps 可复核来源 |
| `MNX-VG0-B` | 允许本机只读核验 | 仅 `docs/开发文档/证据/MOSS-TTS-Nano优化/VG0-local-topology.md` | 不加载模型、不改长期环境 | M4/容器/依赖/磁盘/锁候选 |
| `MNX-VG-RUNTIME` | VG migration/contract | `backend/narration/adapters.py`、新 `voice_generator_runtime.py`、`voice_generator_sidecar.py`、`tests/narration/test_voice_generator_runtime.py`；新 `docker/voice-generator-sidecar/Dockerfile`、`requirements.lock`、`model-source.lock.json`、`NOTICE`、`THIRD_PARTY_NOTICES.md`、`entrypoint.py`、`verify_runtime.py` | 不改 worker/models/API/compose，不把模型权重或缓存提交进 Git，不混入 Nano Sidecar 依赖 | 依赖/许可锁定、健康、指纹、取消、加载/卸载/崩溃 |
| `MNX-VG-DOMAIN` | VG migration/contract | 新 `backend/narration/voice_design.py`、`voice_generated_references.py`、`tests/narration/test_voice_design.py`、`test_voice_generated_references.py` | 不改 worker/schema/API/person authority | scope/CAS、draft 不可变、换一个只换 seed、最新人物/编辑描述新建 draft、单候选自动晋升/绑定、冲突保留、高级 partial-ready、隐私 |
| `MNX-VG-FE` | VG API fixture | 新 `frontend/src/narration/character-voice-designer.ts`、`character-voice-designer.test.ts`、`voice-generator-api.ts`、`voice-generator-api.test.ts`、`styles/voice-generator.ts` | 不改公共 modal/workbench/contracts | 一键生成并使用、进度/失败、换一个、绑定冲突、高级三备选 |
| `MNX-DEL-FE` | DEL API 冻结 | 新 `frontend/src/narration/voice-lifecycle-panel.ts`、`voice-lifecycle-panel.test.ts`、`voice-lifecycle-state.ts`、`voice-lifecycle-state.test.ts`、`styles/voice-lifecycle.ts` | 不改 reading-page/api/contracts | 未引用一键删除、已引用单次影响确认、undo、backup 文案 |

### 10.2 主代理独占共享文件

以下文件只能由主代理在每波汇合时串行修改；多个子代理不得同时触碰：

```text
backend/models.py
backend/migrations/versions/<当时下一线性 revision>.py
backend/narration/schemas.py
backend/narration/contracts.py
backend/narration/settings_api.py
backend/narration/privacy.py
backend/narration/production_runtime.py
backend/narration/playback_api.py
backend/narration/narration_api.py
backend/narration/edition_service.py
backend/narration/editions.py
backend/narration/worker.py
backend/narration/media.py
backend/narration/storage.py
backend/background/jobs.py
backend/creative_services.py
backend/creative_schemas.py
backend/creative_api.py
backend/model_runtime.py
scripts/tts/bootstrap_digest_keyring.py
frontend/src/narration/contracts.ts
frontend/src/narration/api.ts
frontend/src/narration/playback-api.ts
frontend/src/narration/playback-contracts.ts
frontend/src/narration/playback-progress-contracts.ts
frontend/src/narration/reading-overview.ts
frontend/src/narration/reading-page.ts
frontend/src/narration/chapter-narration-session.ts
frontend/src/narration/index.ts
frontend/src/workbench-studio.ts
frontend/src/styles.ts
frontend/src/workbench-route.test.ts
plugin.py
plugin.json
compose.yaml
pyproject.toml / requirements.txt / 锁文件
README.md
docs/README.md
docs/开发文档/README.md
docs/开发文档/18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md
docs/开发文档/ADR/ADR-0005-MOSS-TTS本地运行拓扑与资源边界.md
本文、docs/开发文档/证据/MOSS-TTS-Nano优化/README.md 与 redundancy-ledger.md
docs/开发文档/证据/MOSS-TTS-Nano施工/README.md 与 capability-matrix.md
```

### 10.3 共享资源锁

- `LOCK-MIGRATION-HEAD`：计划 32 已完成；开工实时确认 `0029` 之后的唯一新 head，一次只有主代理持有；
- `LOCK-PUBLIC-CONTRACT`：DTO/API 冻结后子代理才并行，任何变更先停止并回主代理；
- `LOCK-MODEL-HEAVY`：规划/运维层先保证 Nano、VoiceGenerator、真实音频验收串行；它不是现有数据库锁，VG 产品化前还必须实现并验证跨进程共享 residency claim；
- `LOCK-TEST-DB`：只用显式隔离测试库，不触碰正式小说；
- `LOCK-LONG-RUNTIME`：长期 QwenPaw/Compose 安装、重启、迁移、卸载只由主代理操作；
- `LOCK-MEDIA`：真实候选、缓存清理与删除验证使用隔离媒体根；
- `LOCK-PRUNE-LEDGER`：redundancy ledger 及其中冻结的删除清单只由主代理串行更新；子代理可以报告候选但不得自行删除，未证明替代路径、零调用者和独立风险覆盖的条目一律保留；
- `LOCK-USER-DIRTY`：开工时所有目标 dirty 文件都必须逐文件确认来源已集成、owner 已释放或重新分配；所有既有未提交文件默认禁止覆盖；
- `LOCK-GIT`：子代理和主代理均不暂存、提交或推送，除非用户另行明确要求。

### 10.4 派发卡模板

每次子代理派发必须写明：稳定工作包 ID、唯一目标、非目标、允许修改的精确文件、冻结 DTO/fixture、前置门禁、共享锁、最小测试、证据路径、禁止触碰的用户改动、发现但不自行删除的冗余候选及给主代理的接线说明。缺一项不得派发。

## 11. 内部验证与发布验收（非产品使用门禁）

### 11.1 自动化

```bash
.venv/bin/python -m pytest tests/narration
.venv/bin/python -m pytest
pnpm test
pnpm typecheck
pnpm build
docker compose config
.venv/bin/python scripts/package_plugin.py
git diff --check
git status --short
```

聚焦阶段还必须覆盖：

- 18 项目录 exact 顺序、manifest/provenance/hash、防缺项/重复/客户端覆盖；
- 原子直用的 scope、CAS、Idempotency-Key 重放、并发、部分失败零残留；profile UUID 在版本更换时稳定，model revision/manifest/rights policy/default parameter 任一改变都产生新 version UUID；
- 关闭新能力后既有 12 个非中文/生成/实验版本仍可渲染；
- 参数进入 version/render fingerprint，旧协议不得吞字段；`onnx.Zhiming` 历史 `fixed_seed_1` 分支在 v1/v2 中仍可重放，但新生产渲染的 active strategy 保持 `disabled`；
- player Web Audio 与 HTMLAudio 双后端、Range/ETag、partial-ready/pending gap、旧稿、Edition 切换、进度恢复；
- 人物点击快照、描述字段白名单、现实人士仿声指令去身份化、VoiceGenerator 默认 `1.5/0.6/50/1.1` 与高级 bounds/未知字段拒绝、不可变 draft、“换一个”只换 seed、按最新人物/作者编辑新建 draft、自动 generated rights/provenance、请求态 Agent bridge、CreativeGenerationJob ready 复用、analysis lease 过期/断线重放、VoiceGenerator/Nano 两个独立 job/ModelRun、单候选自动晋升/绑定、绑定 CAS 冲突保留结果、取消/重试，以及高级三备选 partial-ready；
- candidate `trash_pending → prior_state|deleted` 与专用 restore、profile 删除影响变化 CAS/当前绑定阻断/历史 Edition 不级联、`grace_pending → cancelled|live_deleting` 时间边界、超时后撤销拒绝、墓碑/非空 request、备份 pending，以及 unlink 前、unlink 后/DB finalize 前、finalize 后重放三个崩溃边界；
- VoiceGenerator 独立依赖锁、NOTICE/许可、模型权重 Git 排除、Compose 健康与按需加载/卸载；`plugin.json`、`pyproject.toml`、打包产物与最终能力文档版本一致；
- redundancy ledger 中每个删除项都要有 removed-symbol/import/route/style/config 零引用复扫；替代路径聚焦测试、全量 Python/前端/打包回归与依赖清单检查通过；删除测试前证明其语义已由等价或更强覆盖承接，独立负向、兼容和恢复测试不得因代码路径合并被误删；
- PawApp 安装/升级/完整卸载后 QwenPaw 原生聊天、设置、Agent、Skills、MCP、工具和数据卷非回归。

### 11.2 真实模型与听感

- 使用项目自有短句，为 18 项各执行一次真实技术烟测：正确 preset、48 kHz/双声道、可解码、非空、无异常时长；
- 中文/英文/日文分别至少选择代表音色人工听检；未逐项听检的卡片保持 `unreviewed`；
- VoiceGenerator 使用至少 3 类虚构人物，每类执行一次默认生成和连续两次“换一个”，验证可区分度、可懂度、角色贴合和 Nano 二次克隆保持度；
- 所有真实音色生成使用隔离人物和隔离媒体，不修改用户小说、当前绑定或历史 Edition；
- 发布前听感结论以内部人工听检为准，自动音频指标只做技术故障拦截；发布后作者每次选择或生成不需要重复听检确认。

### 11.3 浏览器矩阵

至少覆盖：

- 1920×1080、2560×1440，原生助手展开/收起；
- 1280×800、1024×768；
- 720×900；
- 960×540（200% 等效缩放）；
- 390×844 窄屏；
- 键盘全流程、中文输入法、减少动效、高对比/非颜色状态、焦点恢复；
- 18 个长短名称、无音色、可选试听加载/失败、CAS/幂等冲突、一键人物生成进度/失败/成功/绑定冲突/换一个、高级 0/1/2/3 候选、播放器所有状态/失败抽屉、未引用一键删除与已引用单次影响弹窗；
- 无水平溢出、播放器不遮正文/助手、触控目标至少 44 px；验收候选的 tree/package/bundle hash 必须与 W0/W6 证据一致。

截图与报告写入 `audit/` 或 `docs/开发文档/证据/MOSS-TTS-Nano优化/`，不得保存真实小说正文、私人描述、音频字节路径、密钥或 token。

### 11.4 阶段通过定义

- `P0-GATE`：catalog v2 精确 18 项；18 个 preset × 旁白/人物两类动作共 36 个契约/数据库矩阵全部通过，18 项各至少完成一种真实隔离绑定与技术合成，两类路径均有全量 idempotency/CAS/回滚测试；现有三个正式绑定不变；
- `P1-GATE`：官方音色从目录到设为旁白/人物的主路径不出现 profile/version 等领域术语，点击“使用”即完成且无语言/版权/质量二次确认；任务式作者验收脚本、键盘/读屏和浏览器矩阵通过；播放器在桌面/窄屏均不遮正文，音量/进度真实生效；
- `VG-GATE`：人物卡一次点击可完成分析、生成、Nano 校验、建档和绑定，中间无描述/候选/质量/锁定确认；请求态 AI bridge 在刷新、断线、响应丢失和 lease 过期后均能幂等恢复，不留永久 running 记录；硬件、听感、资源回收、冲突保护和安装生命周期全通过；
- `DEL-GATE`：未引用私人音色一键删除且在 `undo_deadline` 前可一键撤销，candidate 过期/进入物理删除或 profile 进入 `live_deleting` 后准确拒绝撤销；已使用私人音色最多一次可见影响确认。任何终态不得虚报；文件 unlink 与 PostgreSQL finalize 之间的所有中间窗口都有持久精确计划、幂等恢复和对账 worker，三个崩溃边界均能收敛到一致终态；历史影响和受管/外部备份状态准确；
- `PRUNE-GATE`：ledger 中标记删除的条目已全部删除且零引用，标记保留的条目均有真实调用者/独立风险价值与 sunset；不存在“已确认冗余、以后再删”的待办，迁移历史、原始证据、独立测试和用户改动完整；
- `FINAL-GATE`：汇总本文一次性施工授权范围内实际达到 GO 并启用的独立 `P0-RELEASE / P1-RELEASE / ADV-RELEASE / VG-RELEASE / DEL-RELEASE`；NO-GO 能力保持隐藏且不要求通过其产品化测试。`PRUNE-GATE`、全量自动化、真实浏览器、对应真实模型、隔离安装/升级/卸载、文档与当前运行事实一致。

## 12. 回退与恢复

- P0 回退：catalog v2 仍固定返回 18 项，只把受影响项置 `selectable_now=false`，已经绑定的版本继续 `renderable_existing=true`；如保留旧 exact-six 响应，只能由独立兼容 v1 提供，不能让 v2 改长度；
- 高级参数回退：隐藏新建入口；既有锁定实验版本继续播放，旧 sidecar 协议只处理兼容版本；
- VoiceGenerator 回退：关闭独立 capability、停止领取新的 `narration.voice_generate` VoiceGenerator job、保留 draft/candidate 和已锁定版本；Nano/官方预设继续工作；
- 删除回退：candidate 在 `trash_pending` 且未过 `delete_after` 时用 restore 回到 prior state；未引用 profile 在 `grace_pending` 时用 cancel 撤销；已使用 profile 在唯一一次影响确认前可取消。candidate 已物理删除或 profile 进入 live delete 后不得假装恢复，按各自持久状态继续完成或报告失败；备份恢复只在实际仍存在且用户明确要求时执行；
- 代码清理回退：只在替代路径已验证且删除清单冻结后删除，并保留在 Git diff/提交历史中可逐条恢复；若回归失败，恢复对应精确文件/符号并回到 ledger 的“保留/待证”状态，不借此倒改迁移历史、验收原始证据或用户数据；
- 数据库：只追加新 migration，不修改历史。每次长期升级前做仓库外备份和 manifest；恢复时数据库与 media/digest keyring 成对处理；
- 部署：发布前记录并实际留存上一版 PawApp/Sidecar 的不可变 image digest、安装包 hash 和固定模型 revision。一旦 `0031` 写入官方直用证据，数据库最低兼容应用版本就是理解 `narration-voice/2` 与 activation evidence 的 P0 兼容版；产品回退只可在该兼容线内关闭 `selectable_now`并 fix-forward，不得声称可直接回到 `0031` 前旧 image。回退不删除 PostgreSQL、QwenPaw、媒体和模型卷；
- 用户内容：任何测试使用隔离小说/人物/媒体 scope；正式人物卡、正文和既有声音绑定不得作为可回滚测试夹具。

## 13. 风险与施工期证据裁决

| 风险 | 当前结论 | 控制措施 |
| --- | --- | --- |
| 官方直用与既有 locked=accepted 约束冲突 | 已证实，P0 不能再承诺零迁移 | activation basis/selection command 最小迁移；严禁伪造 preview/accepted |
| 响应丢失后旧 CAS 阻断重放 | 已证实 | 鉴权/scope 后先读 receipt/command；completed 重放冻结结果，新命令才校验 CAS |
| catalog v2 回退到 6 项破坏 exact-18 | 已证实 | v2 始终 18 项，只翻 `selectable_now`；v1 才保留六项兼容 |
| 非中文 preset 对中文正文质量不稳定 | 允许个人本地直接使用，但未专项验证 | 仅显示非阻断语言/验证标签并做发布前逐项技术烟测，不弹确认、不做硬禁用 |
| `Trump` 等名称可能被误解为仿声授权 | 官方 manifest 固定项不按名称屏蔽；本计划不提供主动仿真人生成功能 | 显示官方 ID/来源和个人本地提示；公开/商业分发不在本计划结论内 |
| Raw 参数造成长篇漂移、异常长度或缓存爆炸 | 不能混入默认路径 | 复制为实验版本、服务端 bounds、机器校验、fingerprint、配额和一键恢复默认 |
| VoiceGenerator 在 M4 16 GB 不可用 | 尚未验证 | runtime-first、UI-later；NO-GO 不影响 P0/P1 |
| 把人物描述误当成已有后台 Agent 任务 | 已证实当前 `ctx.chat` 为请求态 | 一次点击由 command + analysis-runs 透明编排；复用 CreativeGenerationJob、analysis lease 和幂等恢复，不新建 Agent Runtime |
| 页面刷新/断线使描述 job 永久 running 或重复扣费 | 必须在施工前冻结 | 先复用 ready result；lease 过期后才新建 attempt；无 owner running 明确收敛失败 |
| 人物卡信息不足或包含矛盾 | 不允许模型把推测写回人物事实 | 字段白名单、unknown、点击快照、描述可编辑后重新设计；普通换一个只推进 seed，不增加生成前确认 |
| generated 版本需要 rights 记录却不应增加勾选门禁 | 当前 schema 的真实约束 | 用 command 点击自动生成窄化的私人写作/provenance 证据，不声称商用、再分发或现实主体同意 |
| 作者不喜欢自动生成结果 | 属于正常创作迭代，不应卡住首次使用 | “换一个并使用”、恢复上一音色、未引用结果一键删除 |
| 真删除破坏历史播放 | 用户可选择，但必须理解后果 | 一次影响确认、原子解绑/阻止新使用、历史 Edition 标记不可用、最小墓碑 |
| “一键删除可撤销”没有服务端时间边界 | 当前候选与 profile 状态机都有缺口 | candidate 用 `trash_pending` + restore，profile request 用 `grace_pending/cancelled` + cancel；进入物理/live delete 后不再宣称可恢复 |
| 外部备份不受项目控制 | 无法证明已过期 | completed 只声明项目管理副本；external backup 显示 unknown/unmanaged |
| 历史 Edition 没有冻结音色名称 | 当前真实缺口 | 新 resolution v2 冻结 identity；旧 Edition 只显示稳定 ID，不回填当前名称 |
| Nano/VoiceGenerator 现有锁互不排斥 | 当前真实缺口 | VG 产品化迁移新增跨进程共享 residency claim；尖峰阶段运维串行 |
| VoiceGenerator 依赖混入 Nano 或缺失许可/版本锁 | 会放大安装与回退风险 | 独立 Sidecar 目录、依赖锁/model source lock/NOTICE、权重 Git 排除、打包与卸载验证 |
| 后续任务再次占用迁移/人物模型/工作台 | 计划 32 的历史冲突已解除，但开工时仍可能出现新改动 | W0 重取 status/head；只隔离具体冲突文件，迁移、公共 DTO 和长期运行态串行 |
| 只叠加新实现导致双权威，或清理过早误删兼容/恢复能力 | 两类风险都必须阻断 | W0 建 ledger、逐条调用图与替代证据、主代理独占 `MNX-PRUNE`；确认冗余必须同版删除，仍有调用者/独立风险覆盖则保留并写明 sunset；迁移/历史证据/用户改动列为保护项 |
| 页面一次塞入全部高级功能 | 会重现当前首次流程过重 | 基础操作优先、渐进展开、音色库独立、技术详情默认折叠 |

## 14. 规划自审记录

### 14.1 第一轮：范围、事实与架构复查

已逐项核对：

- 18 项来自项目固定 manifest，而不是临时网络目录；
- 当前限制来自产品 gate，不是运行时目录缺失；
- 现有 player 已具备大量核心能力，本计划是增量优化而非重写；
- VoiceGenerator 当前确实是生产 NO-GO，不能把设计描述成可用；
- generated source、archive、删除请求和墓碑只有底座，不能写成完整删除功能；
- 计划 32 已完成并释放人物 revision、migration 和工作台共享所有权；本文 W0 仍需以开工时状态重新确认；
- 所有能力位于 PawApp/适配器内，不改 QwenPaw 上游；
- 规划授权没有扩大为代码、模型下载、数据库或数据删除授权。

### 14.2 第一轮反例审查后已修正

1. **反例：**前端连续调用“建 profile → 建 version → 锁定 → 绑定”，中途失败会留半成品。
   **修正：**官方直用改为单个服务端原子动作和幂等回执。
2. **反例：**回退到 6 项时，已经绑定英文/日文音色会被 `require_product` 阻断。
   **修正：**拆分 selectable/previewable/renderable，回退只停止新选择。
3. **反例：**为了试听官方卡片仍要求完成旧五步流程。
   **修正：**系统内部按需建立隐藏官方版本，不向作者暴露建档负担，也不伪造试听确认。
4. **反例：**把倍速、音量、停顿和模型参数混在同一区域，用户无法判断是否重合成。
   **修正：**播放偏好、脚本停顿、Nano 实验参数三层分离。
5. **反例：**先做 VoiceGenerator UI，真实 M4 最后才发现不可运行。
   **修正：**固定模型和真实资源/听感尖峰先于 schema、API 和 UI。
6. **反例：**根据人物姓名/性别刻板印象自动补声音。
   **修正：**只读点击时正式 revision 的明确字段，缺失即 unknown；推测只进入可查看的音色描述，不写回人物事实，也不要求作者先确认才能生成。
7. **反例：**播放器显示当前人物绑定，但用户正在播放历史 Edition。
   **修正：**声音标签必须来自 Edition 冻结解析投影，不能用当前绑定替代。
8. **反例：**真删除直接级联 Edition/Manifest 或先删媒体后写状态。
   **修正：**历史审计保留、影响预览和状态机先行，在线字节删除与墓碑受事务/worker 围栏。
9. **反例：**为未来一次性建立系统 profile、VoiceGenerator、删除的巨型迁移。
   **第一轮修正：**尝试让 P0/P1 零迁移，VG 和删除仅在各自 GO 后追加 migration。
   **第二轮复核：**既有 `locked=accepted+真实 preview` 约束推翻了 P0 零迁移假设；现改为 P0 activation evidence 预计最小迁移、P1 原则上零 schema 迁移，VG/删除继续独立追加。
10. **反例：**并行代理覆盖计划 32 的未提交改动。
    **修正：**新增 `MNX-G0` 等待门禁、共享文件主代理独占和 `LOCK-USER-DIRTY`。

### 14.3 独立第二轮反例审查：已完成并采纳

独立只读审查从 API 原子性、迁移必要性、资源上限、删除可恢复性、页面复杂度、测试遗漏和文件所有权七个维度提出阻断项；主代理复核源码/迁移后采纳以下修正：

1. 第二轮当时采用阶段批准逐项生效；第三轮根据个人写作工具定位，已改为一次性施工授权覆盖所有非破坏性代码与隔离验证，但 `VOICE_GENERATOR_NO_GO` 仍必须由内部真实验收自动解除，真实媒体删除仍按精确目标确认一次；
2. P0 不再以伪造 accepted/preview 换取零迁移，改为 activation basis + selection command 的最小契约门禁；
3. 幂等顺序改为 completed receipt 先重放、新命令后验 CAS；语言标签读取带版本作品设置但不要求确认，canonical profile 固定本书 scope；
4. catalog v2 回退仍返回 exact-18，只改变 selectable；旧六项只能由兼容 v1 提供；
5. 明确现有 Nano/VG 资源 key 不互斥并复用已注册 `narration.voice_generate`，VG 产品化另建共享 residency claim；
6. 真删除改为持久计划和可恢复中间窗，不承诺文件系统/PostgreSQL 原子；冻结 profile scope、混源阻断、current Edition、全部 render 与外部备份语义；
7. settings 成为倍速/音量唯一偏好权威，progress rate 只做旧协议 fallback；WebAudio/HTMLAudio 单次只启用一个增益后端；
8. 新 Edition resolution v2 冻结 voice identity，旧 Edition 不用当前名称回填；
9. 补齐 VG 状态/CAS/partial-ready/晋升与 generated DB 闭包；
10. 新增 P0 contract/migration、P1 后端契约、人物页、DEL audit 等工作包，所有共享热点回归单一 Owner。

所有有源码或迁移证据支撑的阻断意见均已采纳。对具体最终表数量、字段名和 VoiceGenerator 后端拓扑只冻结约束与决策门，不在真实尖峰/DEL audit 前提前锁死实现。

### 14.4 规划期只读验证与最终复查

- 后端聚焦基线：`.venv/bin/python -m pytest -q tests/narration/test_official_presets.py tests/narration/test_adapters.py tests/narration/test_settings_api.py`，`78 passed`，另有 1 条 Starlette/httpx 弃用警告；该结果证明当前 exact-six + VG disabled 基线，不证明目标能力；
- 前端基线：固定 Node 24.19.0 下 `pnpm test` 为 `92 files / 836 tests passed`，`pnpm typecheck` 通过；未运行 build，避免只读规划阶段更新 `frontend/dist`；
- 前端审计确认运行截图与源码候选可能不是同一 bundle，已提升为 W0/W6 hash 门禁；现有 accessibility/string tests 和 desktop-only 断言不能冒充 WCAG/窄屏验收；
- 主代理第二轮复查已逐项消除“P0 必定零迁移、v2 回退过滤、两模型已有共享锁、真删除无中间态、历史名称可现查”等自相矛盾表述；第三轮又统一清理了跨语言确认、三候选必选、人工锁定和分阶段重复审批的残留；
- 本轮只修改计划与索引，不修改代码、数据库、运行态、模型、音色、媒体或小说数据。

### 14.5 第三轮：个人写作工具门禁减负复查

本轮按“本地个人写作辅助，不提供下载、导出或外传”的产品边界，逐路径复查后确认：

- 官方预设从卡片到旁白/人物绑定只有一次“使用”操作；试听、语言提示、来源详情都不阻断；
- 人物专属音色从人物卡到生效只有一次“根据人物生成并使用”；描述确认、候选选择、质量接受、锁定和再次绑定全部退出默认路径；
- 默认只生成一个候选以降低等待和资源占用，不喜欢时点“换一个并使用”；三备选只在高级入口出现；
- 未引用私人音色一键删除并支持短时撤销；当前或历史正在使用的私人音色只做一次影响确认；
- 官方来源、模型 revision、不可变版本、ModelRun、幂等、CAS、资源互斥、删除恢复仍保留在后台；它们是可信工程证据，不是作者要理解或逐项批准的门槛；
- 一次性批准本文施工后，内部 `GATE` 由测试结果自动推进。只有超出本文范围、操作唯一长期环境、提交/推送，或删除精确真实媒体时才需要新的明确授权。

全文反向搜索标准为：默认使用路径不得残留 `language_mismatch_confirmed`、强制 preview、人工 accepted/locked、三候选必选、二次删除确认或“每阶段另批”语义；高级/兼容测试中出现这些术语时必须明确标注非默认路径或内部状态。

### 14.6 第四轮：施工就绪终审

本轮以当前源码、`0029` 迁移 head、现有 CreativeGenerationJob 调用路径、VoiceGenerator/Nano job 注册、rights 约束、删除表和打包拓扑反向推演每个工作包。发现并修正的实际施工缺口为：

1. 人物描述不能直接放入既有 narration worker；现已冻结一次点击下的 command + request-scoped `analysis-runs`、CreativeGenerationJob 新 kind、lease/断线重放和独立 `MNX-VG-AI-BRIDGE`，不引入第二套 Agent Runtime。
2. VoiceGenerator 生成与 Nano 克隆验证是两个不同资源类；现已分离 job/preview/ModelRun 字段和终态闭合，不再用单一含糊 `job` 表述。
3. “换一个”原先同时隐含重跑人物分析和推进 seed，差异来源不可解释；现已冻结不可变 VoiceDesignDraft 及三个 discriminated mode：普通换音只换 seed，人物卡更新或作者编辑描述才一键创建新 draft。
4. “未使用音色一键删除可撤销”原先没有可实现的 API/状态，且尚未晋升的 candidate 不能塞入强制 profile FK 的删除表；现已分开 candidate `trash_pending` + `restore` 与 profile `discard-unreferenced` + `grace_pending/cancel`，两者均有过期后拒绝撤销的时间边界。
5. 官方 canonical UUID 原先混淆 profile 容器与 version 身份；现已分开两层 UUIDv5，并把 model revision、manifest、provenance、rights policy、decode contract 和默认参数指纹纳入版本身份。
6. generated Voice Version 必须满足现有 rights 闭包；现已冻结由 command 点击自动建立的窄化私人写作/provenance 证据，既不伪造现实主体同意，也不增加用户勾选门禁。
7. 高级页原先把运行时安全项与音色调教项混在一起；现已冻结“全部可查看、有效音色参数可编辑、运行安全参数只读”，并明确 `onnx.Zhiming` 历史 `fixed_seed_1` 分支只保留可重放性，新生产 active strategy 继续 `disabled`。
8. VoiceGenerator 产品化原先未分配容器依赖/许可文件所有权；现已为独立 Sidecar 的 Dockerfile、依赖锁、model-source lock、NOTICE、entrypoint 与验证脚本指定唯一工作包，权重不入 Git。
9. 最终发布原先未覆盖插件版本和现行文档口径；现已由 `MNX-FINAL` 唯一负责 `plugin.json`/`pyproject.toml`、根 README、18 号文档、ADR-0005、新证据索引和 capability matrix 的一致更新，历史证据只添加 supersession 指向而不重写。
10. W4 原先引用 `VG-CONTRACT-GATE` 却没有唯一工作包，且 migration 排在契约冻结前；现已增加串行 `MNX-VG-CONTRACT`，先冻结 DTO、状态机、字段清单、AI bridge 边界和三类 job/ModelRun，再允许迁移、桥接和不重叠实现。

终审结论：文档已具备按 W0–W6 开工的产品契约、数据边界、迁移唯一所有权、子代理不重叠文件包、测试证据和回退路径，没有未解决的方案级阻断。`VG1` 对 M4 16 GB 的 GO/NO-GO 和 `MNX-DEL-AUDIT` 的精确 write set 仍是施工中必须以真实证据得出的能力结论，它们已有完整分支/降级路径，不再是需要用户补充产品决策的规划缺口。

### 14.7 冗余清理补充复核

根据作者“发现老旧冗余设计必须删除、尽量减少冗余”的补充要求，本轮再次反查施工组织，避免把新设置页、音色库、播放器和删除流程仅作为旁路叠加。已补充：

1. `MNX-PRUNE-AUDIT` 在 W0 建立可恢复的 redundancy ledger，各波只报告有精确 path/symbol、调用图和替代证据的候选；
2. `MNX-PRUNE` 在 W6 由主代理串行删除所有已证实冗余，`PRUNE-GATE` 阻止把确认项延期成 TODO；
3. 旧 catalog v1、旧入口/布局/交互和相关测试只列为候选，不预判删除；仍有真实调用者或独立兼容/负向/恢复价值时必须保留并记录 sunset；
4. 已执行迁移、历史验收/审计原始证据、QwenPaw 上游、用户 dirty 文件和语义独立测试列为禁止清理范围；
5. 删除后必须完成零引用复扫、依赖与锁文件正规更新、受影响回归、全量门禁和 Git diff 复核，并能从 Git 精确恢复。

补充复核没有改变产品范围、数据状态或外部行为，只把“替换旧实现”升级为施工硬门禁。终审结论保持不变：本文档层面可以进入施工，尚未因此开始修改代码。

## 15. 一次性施工授权口径

本文已完成四轮主审、冗余清理补充复核、前后端独立只读审计和独立反例审查，可提交用户一次性评审。建议使用一句明确指令，例如“按计划 33 开始实施”，其授权边界为：

1. 一次覆盖 `P0 + P1 + P1.5 + P2-VG + P2-DEL` 的代码、文档、自动化测试、隔离数据库迁移验证、隔离模型下载/尖峰、隔离浏览器/音频验收，以及 redundancy ledger 中已证明冗余的项目源码/测试/配置/依赖删除；
2. 内部按 W0–W6 顺序推进，`VG1=GO` 才继续 VoiceGenerator 产品化，`NO-GO` 则诚实降级为人物自动匹配官方预设；无需作者在 W1/W3/W4/W5 之间反复批准；
3. `MNX-DEL-AUDIT` 冻结精确 write set 后可继续实现删除能力，但测试只用隔离媒体；不会借施工授权删除任何真实私人音色；
4. 产品上线后的日常使用遵循本计划的一键/单确认原则；每次真实私人音色彻底删除，仍由作者针对该精确音色在页面中确认一次；
5. 冗余删除只作用于 ledger 冻结的项目文件，不包含用户小说/媒体、已执行迁移、历史验收原始证据、QwenPaw 上游或任务外 dirty 改动；
6. 该授权不自动包含提交、推送、迁移唯一长期数据库、切换唯一长期运行环境或修改用户小说；这些外部/长期状态动作仍按其精确目标另行执行。
