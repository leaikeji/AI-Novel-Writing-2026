# Codex 多子代理并行施工矩阵

状态：**项目级并行调度基线。正式开发时可以直接按本文工作包编号派发；本文只规定施工组织，不自动批准尚未立项的阶段。**

制定日期：2026-08-25（Asia/Shanghai）

适用范围：项目核心阶段、长篇一比一创作闭环、建书与大纲扩展、工作台扩展、短篇与文本拆解、Agent 模型跟随、QwenPaw 原生助手联动、MOSS-TTS-Nano 多角色朗读、测试与发布。

关联文档：

- [项目开工计划](./00-项目开工计划.md)
- [阶段实施矩阵](./08-阶段实施矩阵.md)
- [妙笔神书一比一创作闭环与三书实写总目标计划](./16-妙笔神书一比一创作闭环与三书实写总目标计划.md)
- [MOSS-TTS-Nano 多角色智能朗读产品与技术设计](./18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md)
- [跟随“AI 小说作家”Agent 模型切换开发计划](./19-跟随AI小说作家Agent模型切换开发计划.md)
- [QwenPaw 原生助手与创作上下文联动施工计划](./20-QwenPaw原生助手与创作上下文联动施工计划.md)

官方 OpenAI 文档说明，多代理适合能够清晰拆分成独立工作流的复杂任务，可以减少墙钟时间；本项目据此并行，但始终保留单一集成责任人和阶段门禁。[官方模型指导](https://developers.openai.com/api/docs/guides/latest-model)

## 1. 调度结论

项目中可以大量并行的部分包括：

- 官方契约、竞品证据、许可证、依赖和风险研究；
- 相互独立的技术尖峰与原型；
- 已冻结契约后的前端、后端、Worker、模型适配器和测试；
- 不同页面、不同领域模块和不同测试层；
- 三本验收小说之间的创作与验收；
- TTS 的模型基准、音色包、播放器、编辑器和任务恢复尖峰。

以下内容必须串行或由单一所有者负责：

- 范围批准、ADR 决策、公共契约和 schema 冻结；
- Alembic 迁移编号、数据库备份/恢复和破坏性数据操作；
- 同一个共享文件、依赖锁、公共 API、状态机和 Git index；
- QwenPaw 插件安装、升级、卸载和共享宿主配置；
- 同一台 M4 上争用 GPU/大内存的 Nano 与 VoiceGenerator 重负载基准；
- 最终集成、全量回归、暂存、提交、推送和阶段退出裁决。

“授权层不设上限”表示可以持续滚动派发任意数量的合格工作包，不表示任意时刻拥有无限并发槽位或无限本机资源。

## 2. 统一标记与派发规则

| 标记 | 含义 | 是否可以立刻并行 |
| --- | --- | --- |
| PAR | 独立工作包；文件、输入和验收均可隔离 | 满足前置后可以 |
| PAR-C | 契约冻结后可并行 | 必须先通过对应 GATE |
| SER | 串行工作；只能由主 Codex 或指定唯一所有者执行 | 不可以 |
| MUTEX | 代码可并行准备，但运行时争用同一资源 | 运行验证必须排队 |
| GATE | 汇合门禁；主 Codex 复核全部输入后冻结结论 | 不可以 |
| INT | 集成、冲突解决和全量验证 | 不可以 |
| DONE | 已完成历史阶段；保留编号用于追溯，不重复施工 | 不派发 |

同一波次不等于所有任务必须同时启动。只要工作包前置依赖满足、文件所有权不重叠并且有独立验收产物，就可以加入当前 ready set；槽位不足时滚动到下一批。

每个子代理任务必须写明：

1. 稳定工作包 ID；
2. 唯一目标与非目标；
3. 允许修改的精确文件或目录；
4. 前置契约、输入样本和不可改变的接口；
5. 必须运行的测试与需要保存的证据；
6. 禁止触碰的共享文件、迁移、锁文件和用户改动；
7. 完成时的变更清单、测试结果、遗留风险和集成说明。

## 3. 项目级依赖图

    SER-BASE：确认批准范围、干净基线、工作区改动归属、文件锁
      |
      +-- M0-*：Agent 模型跟随公共契约尖峰
      +-- A0A–A0D：QwenPaw 助手 V2 基线、留存/Hook 和前端可行性尖峰
      +-- T0-*：MOSS-TTS 模型、音色、播放器、编辑器尖峰
      +-- L-F-*：长篇闭环剩余独立功能与证据（仅在总目标继续执行时）
      |
      +-- 各专项 GATE-0 冻结契约
             |
             +-- 专项内部 PAR-C 工作包
             |
             +-- 共享 schema / 迁移 / API 由唯一所有者串行接入
                    |
                    +-- 分层测试与真实 E2E 可再并行
                           |
                           +-- INT-RELEASE：主 Codex 全量回归、提交与阶段退出

跨专项可以同时进行研究和新文件原型，但正式代码存在以下关键依赖：

- 模型跟随计划先冻结 effective model、requested/actual 和 attempt 语义，助手与 TTS 的云端辅助分析再接入这套唯一语义；
- 助手三栏布局与 TTS 章节播放器都会修改工作台布局，必须先冻结页面区域和公共桥接接口，再分别开发；
- TTS、模型跟随、助手工具和工作台扩展都会碰到领域服务、任务、模型审计与迁移，必须由公共契约所有者协调；
- 所有专项都可以先在新模块和独立测试文件中施工，入口注册、公共类型、共享样式和迁移由主 Codex 集中接线。

### 3.1 开工前串行裁决单

只读交叉审计发现，部分历史规格仍保留早期方案。以下项目必须在大规模并行编码前由主 Codex 按“后文覆盖前文、已实现事实优先、数据安全优先”的原则串行冻结；下表给出默认最优裁决，除非后续 ADR 明确改变：

| ID | 标记 | 冲突面 | 默认最优裁决 |
| --- | --- | --- | --- |
| D0-01 | SER/GATE | 工作台内部路由与 QwenPaw chat 路由 | 以现有 route.wrap 原生聊天组合和规范化后的 /chat/{session_id} 为宿主真相；PawApp 页面状态作为受控内部路由，不再建立第二套全局小说路由 |
| D0-02 | SER/GATE | Monaco、textarea、自然高度编辑器与未来 TTS 装饰能力 | 当前自然高度编辑器是生产基线；TTS 只通过 NarrationEditorBridge 接入，是否换 CodeMirror/Monaco 由 T0-F ADR 单独裁决 |
| D0-03 | SER/GATE | 情报逐项复核与参考流程“一次同步” | 保留一个“同步进展确认”可见步骤；无冲突项可批量确认，冲突/未知人物项必须展开复核，任何模型结果都不能静默入账 |
| D0-04 | SER/GATE | 普通保存是否再次选择分卷 | 普通保存与正式检查点不弹分卷；只有“我已有正文”产生的未分卷章节第一次正式保存时才条件性询问 |
| D0-05 | SER/GATE | 候选 Diff 安全层与参考站可见步骤 | 保留候选、CAS、Diff、采用/拒绝数据层，把入口嵌入已有生成结果/历史界面，不新增独立“保护流程”页面 |
| D0-06 | SER/GATE | 既有 intelligence_proposals/candidate_revisions 与新类型化表 | 扩展既有记录、保留稳定 ID、逐步增加类型化投影；禁止并行代理创建语义重复的第二套候选/情报表 |
| D0-07 | SER/GATE | target_word_count、target_chars 与实际可见字符门槛 | 统一语义为 target_visible_character_count；旧字段只做兼容读取，UI、任务记录和验收使用同一可见字符算法 |
| D0-08 | SER/GATE | 关系图/导出在通用 P2 与三书总目标中的优先级 | 通用产品仍可标后续，但只要继续三书总目标，它们就是该目标的阻断项 |
| D0-09 | PAR/GATE | 早期 DPR 截图与阶段 A 完成声明 | 增加证据修复轨，不阻塞独立后端代码，但在真实 DPR=1 双视口证据补齐前不能通过最终视觉门禁 |
| D0-10 | SER/GATE | MiniMax M3 与 AI 封面模型语义 | 当前验收使用授权系统/上传封面；M3 只可生成封面文案或提示词，未单独批准图片适配器时不声称由 M3 生成图片 |
| D0-11 | SER/GATE | 单人本地 owner、显式 ID 与服务端会话绑定 | 当前按固定本地 owner 隔离；工具仍需服务端验证小说/文档范围，公开会话绑定未证明前不得只信任模型传入 ID |
| D0-12 | SER/GATE | 各扩展自行建设任务表 | AI、向量、事实、TTS、文本拆解统一复用一套 background_jobs/model_run_records 契约，不各建状态机 |
| D0-13 | SER/GATE | CosyVoice 与 MOSS-TTS 候选基线 | MOSS-TTS-Nano 是当前首选；CosyVoice 只保留为未启用备用适配器，不参与 T0 默认实现 |
| D0-14 | SER/GATE | 历史阶段状态和仍写着“当前/暂缓”的旧标题 | 以文件顶部最新状态和真实验收记录为准；历史章节只作过程记录，不重新派发已完成工作 |

权威顺序固定为：

1. 新 ADR 与当前冻结契约；
2. 专项计划顶部最新状态和本并行矩阵；
3. 16、17 的当前长篇目标与可见参考真相；
4. 05、07、09、10 的完整产品规格；
5. 11、13、14、15 的历史实施与验收记录；
6. 更早且已被实现事实覆盖的 MVP 假设。

任何代理发现裁决表与当前代码事实不一致时，应停止该工作包并提交证据给主 Codex，不得自行选择一套历史方案继续实现。

## 4. 核心项目阶段 C1–C8

阶段 C1–C6 已有完成记录，下表保留为后续重建、升级或回归时的直接调度模板；不得因为标为 DONE 而重复改写已验收功能。

| ID | 标记 | 工作包 | 前置 | 独立产物与验收 |
| --- | --- | --- | --- | --- |
| C1-A | DONE/PAR | 产品范围、页面、路由与非目标 | 无 | 范围表、路由表、排除项 |
| C1-B | DONE/PAR | 架构、数据权威、状态机与失败恢复 | 无 | 架构图、状态机、恢复矩阵 |
| C1-C | DONE/PAR | 依赖、版本、许可证与资源基线 | 无 | 版本锁定建议、许可证清单 |
| C1-D | DONE/PAR | QwenPaw 与竞品只读证据 | 无 | 截图、公共接口证据、差异记录 |
| C1-G | DONE/GATE | 架构和范围冻结 | C1-A…D | 无矛盾文档和用户批准 |
| C2-A | DONE/SER | 最小工程骨架、manifest 与依赖锁 | C1-G | 可安装空插件、固定依赖 |
| C2-B | DONE/PAR-C | 后端路由和健康接口尖峰 | C2-A | 最小 HTTP 往返 |
| C2-C | DONE/PAR-C | 前端宿主 React、路由与样式尖峰 | C2-A | 最小 PawApp 页面 |
| C2-D | DONE/PAR-C | 工具、Skill provider 与 Agent 作用域 | C2-A | 注册/卸载验证 |
| C2-E | DONE/PAR-C | QwenPaw 原生页面非回归 | C2-A | 设置、聊天、模型、Skills、MCP 证据 |
| C2-F | DONE/PAR-C | 打包、升级、卸载与恢复 | C2-B…E | 安装和完整卸载记录 |
| C2-G | DONE/GATE | 固定 QwenPaw 版本兼容性裁决 | C2-B…F | go/no-go |
| C3-A | DONE/SER | 权威 schema 和领域契约冻结 | C2-G | 表关系、CAS、幂等规则 |
| C3-B | DONE/PAR-C | PostgreSQL、pgvector 与 Compose | C3-A | 健康、持久卷、端口验证 |
| C3-C | DONE/PAR-C | 领域服务、事务、CAS 与 revision | C3-A | 单元测试和服务契约 |
| C3-D | DONE/SER | Alembic 迁移与往返 | C3-A、C3-B | upgrade/downgrade/upgrade |
| C3-E | DONE/PAR-C | API、schema 与错误映射 | C3-A | API 契约测试 |
| C3-F | DONE/PAR-C | fake、集成测试和崩溃恢复夹具 | C3-B…E | 数据库集成证据 |
| C3-G | DONE/GATE | 数据并发与恢复门禁 | C3-B…F | 不静默覆盖、不丢正文 |
| C4-A | DONE/PAR-C | 作品库、卷章树和路由 | C3-G | 创建、刷新和隔离 |
| C4-B | DONE/PAR-C | 编辑、自动保存和保存状态 | C3-G | CAS、失败和恢复测试 |
| C4-C | DONE/PAR-C | IndexedDB 未同步稿恢复 | C3-G | 断库/重开恢复 |
| C4-D | DONE/PAR-C | 检查点、revision 与历史恢复 | C3-G | 不可变历史验证 |
| C4-E | DONE/PAR-C | 工作台视觉、键盘与状态反馈 | C4-A…D 的接口 | 双分辨率证据 |
| C4-F | DONE/PAR-C | 前端、后端和真实浏览器 E2E | C4-A…E | 类型、单元、构建、E2E |
| C4-G | DONE/INT | 工作台集成 | C4-A…F | 一条真实写作闭环 |
| C5-A | DONE/PAR-C | 原生聊天同屏与会话路由 | C4-G | 不复制聊天、导航非回归 |
| C5-B1…B6 | DONE/PAR-C | 六个 Skills 分目录独立审查和测试 | Skill 契约冻结 | 每个 Skill 独立用例 |
| C5-C | DONE/PAR-C | 三个只读小说工具 | C3-G | 工具作用域与权限测试 |
| C5-D | DONE/PAR-C | 小说、文档、会话绑定与降级 | C5-A、C5-C | 不串小说、不信任模型 ID |
| C5-E | DONE/PAR-C | Agent/Skill/工具真实模型验收 | C5-A…D | 真实对话与零正文写入 |
| C5-G | DONE/INT | 助手闭环集成 | C5-A…E | 原生助手可用 |
| C6-A | DONE/PAR | 创建、编辑、刷新、历史 E2E | C5-G | 功能证据 |
| C6-B | DONE/PAR | CAS、双标签与幂等 | C5-G | 并发证据 |
| C6-C | DONE/PAR | 断库、重启、模型/工具失败恢复 | C5-G | 故障注入证据 |
| C6-D | DONE/PAR | Skills 与模型创作质量观察 | C5-G | 回归样例和限制 |
| C6-E | DONE/PAR | UI、可访问性与宿主非回归 | C5-G | 截图和控制台记录 |
| C6-G | DONE/GATE | 增强范围裁决 | C6-A…E | 用户批准的后续范围 |
| C7-A | PAR-C | AI 候选、Diff、采用与事实提案 | C6-G 明确批准 | 独立候选/采用闭环 |
| C7-B | PAR-C | Embedding、分块、检索和重建 | C6-G 明确批准 | 向量 profile 和召回测试 |
| C7-C | PAR-C | TTS 与媒体 | C6-G 明确批准、T0-GATE | 见 T0–T6 |
| C7-D | SER | 共享任务、模型审计和媒体契约冻结 | 对应专项批准 | 单一 background job 语义 |
| C8-A | PAR-C | 备份与恢复 | 已批准功能集成 | 备份恢复演练 |
| C8-B | PAR-C | 日志脱敏、隐私和声音授权 | 已批准功能集成 | 安全审计 |
| C8-C | PAR-C | 性能、长章节和资源压力 | 已批准功能集成 | 性能报告 |
| C8-D | PAR-C | 键盘、ARIA 和双分辨率 QA | 已批准功能集成 | 可访问性证据 |
| C8-E | PAR-C | QwenPaw/依赖升级兼容性 | 已批准功能集成 | 升级/回退演练 |
| C8-F | PAR-C | 操作文档和发布说明 | 契约冻结 | 可执行手册 |
| C8-G | INT/GATE | 最终发布集成 | C8-A…F | 全量测试、提交和发布裁决 |

## 5. 建书、大纲和扩展包

### 5.1 创作中心、私有库与建书 B

| ID | 标记 | 工作包 | 前置 | 可并行关系 |
| --- | --- | --- | --- | --- |
| B0 | SER/GATE | 冻结草稿、资产版本、模板 schema 和最终创建契约 | 核心 document/revision 可用 | 所有 B1…B6 之前 |
| B1 | PAR-C | 私有资产版本、预设、快照领域服务 | B0 | 可与 B2、B3、B5 并行 |
| B2 | PAR-C | 私有库四分类表、编辑、归档和引用提示 UI | B0、B1 API mock | 可与 B3、B4 并行 |
| B3 | PAR-C | 建书草稿、刷新恢复和幂等创建 API | B0 | 可与 B1、B2 并行 |
| B4 | PAR-C | 六步建书路由、表单、前进后退和复核 UI | B0、B3 契约 | 可按步骤页面拆给不同代理，公共 store 单一所有者 |
| B5 | PAR-C | 模板生成、取名、系统封面及后续上传/AI 候选 | B0、有效模型契约 | 文本生成、媒体和 UI 可分开 |
| B6 | PAR-C | 草稿过期、重试、断线、历史快照和隔离测试 | B1…B5 契约 | 测试可提前写，最终 E2E 等集成 |
| B-G | INT/GATE | 建书与私有库汇合 | B1…B6 | 主 Codex 集成 |

### 5.2 分阶段大纲 O

| ID | 标记 | 工作包 | 前置 | 可并行关系 |
| --- | --- | --- | --- | --- |
| O0 | SER/GATE | 冻结 outline draft、section、任务和最终采用事务 | B-G 或既有小说可用 | 所有 O1…O6 之前 |
| O1 | PAR-C | 大纲草稿、分步任务和恢复 API | O0 | 可与 O2/O3 原型并行 |
| O2-A…E | PAR-C | 目标容量、背景、角色、主情节、定位五步生成器 | O0、模型契约 | 五步可独立开发，公共输入快照单一所有者 |
| O3-A…E | PAR-C | 五步 UI、手填/生成、状态和重试 | O0、前端 store 契约 | 五个步骤页面可分派 |
| O4 | PAR-C | 最终复核、幂等采用和正式 revision | O0、O1 | 与 O2/O3 并行准备，集成在后 |
| O5 | PAR-C | 角色冲突、关系候选和模块同步边界 | O0、稳定角色 ID | 与 O2/O3 并行 |
| O6 | PAR-C | 刷新、取消、过期、重复提交和零正式写入测试 | O1…O5 契约 | 测试优先 |
| O-G | INT/GATE | 大纲闭环汇合 | O1…O6 | 主 Codex 集成 |

### 5.3 工作台和研究扩展 W1–W6

| ID | 标记 | 可拆分的并行子包 | 前置与串行点 |
| --- | --- | --- | --- |
| W1 | PAR-C | W1-A 卷章排序/移动服务；W1-B 章节壳与章纲；W1-C 统一字数；W1-D 树与搜索/导出 UI；W1-E CAS/原子移动测试 | 先由唯一所有者冻结 position_key、target_word_count 和计数契约 |
| W2 | PAR-C | W2-A section 候选；W2-B Diff；W2-C 角色匹配合并；W2-D 一致性报告；W2-E 采用/冲突测试 | 依赖 AI 写回协议；正式采用事务为 SER |
| W3 | PAR-C | W3-A 情报 schema；W3-B 提取器；W3-C 复核 UI；W3-D 线路/事件编辑；W3-E 伏笔进展；W3-F 幂等与来源测试 | 依赖 W1 和采用协议；迁移为 SER |
| W4 | PAR-C | W4-A 图领域投影；W4-B 自动布局；W4-C Canvas/SVG；W4-D 键盘镜像列表；W4-E 视图保存；W4-F 200 节点性能 | 依赖 W3 稳定角色/关系 ID；布局与语义契约先冻结 |
| W5 | PAR-C | W5-A 短篇草稿；W5-B 九步 UI；W5-C 整篇候选；W5-D 统一版本/审稿；W5-E 恢复与字数测试 | 依赖 document/revision 和采用协议；可与 W1、W3、W6 并行 |
| W6 | PAR-C | W6-A 权利确认/导入；W6-B 切分与维度子任务；W6-C 证据报告；W6-D 历史；W6-E 私有资产沉淀；W6-F 去重/失败恢复测试 | 依赖资产 CRUD 与模型上下文；可与 W1、W5 并行 |

推荐扩展并行关系：

    第一组：W1 || W5 || W6
    第二组：W2（AI 写回协议冻结后）
    第三组：W3（W1 + W2 所需采用语义稳定后）
    第四组：W4（W3 稳定实体 ID 后）

## 6. 长篇一比一闭环 L-A–L-J

| 阶段 | 标记 | 可以并行派发的工作包 | 必须串行或汇合 |
| --- | --- | --- | --- |
| L-A | DONE/PAR | 按页面/状态分组采集 1920×1080、2K、DOM、文案、交互和异常状态 | 状态编号、参考真相索引与范围裁定单一所有者 |
| L-B | DONE/PAR | 工作树审计、前端测试、后端测试、数据库测试、演示数据盘点、跨书隔离审计 | 数据清理和 Git 检查点 SER |
| L-C | DONE/PAR-C | 建书、资产、大纲、角色关系、卷章、章节任务、生成、情报、导出各领域可分包 | schema、迁移序列和公共 API GATE |
| L-D | DONE/PAR-C | 创作中心、私有库、六步建书、逐状态视觉 QA | 共享向导 store、styles 和最终建书 E2E INT |
| L-E | DONE/PAR-C | 五步大纲、章节模块、角色、关系、故事线、伏笔、卷章各自施工 | 工作台导航、共享类型和关闭重开 E2E INT |
| L-F | PAR-C | L-F1 六步建章/手写旁路；L-F2 私有库选择/生成；L-F3 编辑/修改章纲/重生成；L-F4 情报/审稿/历史；L-F5 上下章/连续新建；L-F6 搜索/导出；L-F7 双分辨率视觉 QA | 章节 workflow、自动保存、统一版本和最终一章闭环由主 Codex 集成 |
| L-G | PAR-C/MUTEX | L-G1 模型身份审计；L-G2 字数硬门槛；L-G3 正文清洗；L-G4 重复/连续性/伏笔检查；L-G5 多章稳定性 | 共享 active model 切换与真实模型调用按宿主状态排队 |
| L-H | PAR | 后端测试、数据库集成、前端单元、类型、构建、浏览器 E2E、1920/2K 视觉对比、跨书隔离可分别派发 | 数据库破坏性场景和最终 design-qa 结论 SER/INT |
| L-I | PAR | 三本书各由一个独立工作流负责，三本之间并行 | 同一本书的 10 章按上下文和故事账本顺序串行；每章完成后才能进入下一章 |
| L-J | PAR | 跨书隔离、刷新/重启、历史恢复、导出、模型记录、视觉 QA、统计报告并行复核 | 30 章总门槛、全量回归和最终完成裁决 INT/GATE |

阶段 L-I 的推荐结构：

    书 1：第 1 章 -> 情报入账 -> 第 2 章 -> ... -> 第 10 章
      ||
    书 2：第 1 章 -> 情报入账 -> 第 2 章 -> ... -> 第 10 章
      ||
    书 3：第 1 章 -> 情报入账 -> 第 2 章 -> ... -> 第 10 章

三本书可以并行；一本书内部不能在上一章尚未形成正式 revision 和故事账本时并行生成后续章节，否则跨章连续性验收失真。

## 7. Agent 模型跟随计划 M0–M5

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| M0-A | PAR | effective、agent、global 公开 API 实测 | 固定 QwenPaw 2.1.0 |
| M0-B | PAR | PawApp 后端公开 active-model 读取尖峰 | 固定 QwenPaw 2.1.0 |
| M0-C | PAR | 全部 AI 路由和 Agent workspace 审计 | 只读代码扫描 |
| M0-D | PAR | 回复用量 provider/model 证据实测 | 真实模型可用 |
| M0-E | PAR/MUTEX | 并发切换模型竞态实测 | 共享 Agent 模型状态，运行时排队 |
| M0-G | GATE | 冻结 effective、requested/actual、attempt 和安全失败语义 | M0-A…E |
| M1-A | PAR-C | 专用 Agent 依赖与解析器 | M0-G |
| M1-B | PAR-C | 四类 AI 路由统一入口 | M0-G、M1-A 契约 |
| M1-C | PAR-C | 请求 schema 删除前端可信模型字段 | M0-G |
| M1-D | PAR-C | 路由/继承/安全失败测试 | M0-G |
| M1-G | INT | 统一模型入口接线 | M1-A…D |
| M2-A | SER | PostgreSQL 备份与迁移基线记录 | M1-G |
| M2-B | SER | requested/actual/Agent/契约字段迁移与回填 | M2-A |
| M2-C | PAR-C | 模型身份 input hash 与 attempt 服务语义 | M0-G、M2-B schema |
| M2-D | PAR-C | 历史兼容、中断恢复和双模型幂等测试 | M2-B 契约 |
| M2-G | GATE | 数据迁移和历史不变门禁 | M2-B…D |
| M3-A | PAR-C | 通用模型审计与输出校验 | M1-G、M2-G |
| M3-B | PAR-C | 建书/大纲/正文/情报/审稿提示与解析 | M1-G、M2-G |
| M3-C1…C6 | PAR-C | 六个 Skills 按目录独立修订和契约测试 | M0-G，Skill 总原则冻结 |
| M3-D | PAR-C | Agent 系统提示与候选/采用边界 | M0-G |
| M3-E | PAR-C | 两模型通用输出、污染和失败用例 | M3 契约 |
| M3-G | INT | 运行时、Skills 和提示汇合 | M3-A…E |
| M4-A | SER | 前端模型显示 DTO 和公共类型冻结 | M2-G |
| M4-B | PAR-C | 创作中心动态模型显示 | M4-A |
| M4-C | PAR-C | 章节 workflow 动态模型显示 | M4-A |
| M4-D | PAR-C | 工作台/关系/历史动态模型显示 | M4-A |
| M4-E | PAR-C | 当前、任务、历史隔离测试 | M4-A |
| M4-G | INT | 前端接线和共享样式 | M4-B…E |
| M5-A | PAR-C | Agent 配置脚本保留用户选择 | M3-G |
| M5-B | PAR-C | 健康与环境验证脚本 | M3-G |
| M5-C | PAR | 后端、数据库、前端和构建回归 | M2-G、M3-G、M4-G |
| M5-D | PAR/MUTEX | 两个真实模型的关键链路 E2E | M5-A…C；共享模型状态排队 |
| M5-G | INT/GATE | 唯一运行路径最终裁决 | M5-A…D |

## 8. QwenPaw 原生助手联动 V2：A0A–A7

当前只批准 A0A–A0D 验证施工；A1–A7 的并行标注只是门禁通过后的直接 backlog，不是提前开工许可。

### 8.1 阶段 A0A：基线与依赖封口

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| A0A-1 | DONE | 核验 UI Git 基线 | 已有 HEAD/origin 证据 |
| A0A-2 | SER/GATE | 完成或彻底隔离模型跟随计划 | M5-G 或独立可恢复边界 |
| A0A-3 | SER | 建立助手专项工作区、提交和文件所有权边界 | A0A-2 |
| A0A-4A…D | PAR | 章节、人物、大纲、线索/设定按双分辨率补现状证据 | 只读浏览器取证；同一会话运行时 MUTEX |
| A0A-G | GATE | 可恢复基线和依赖封口 | A0A-1…4 |

### 8.2 阶段 A0B：QwenPaw 契约与数据留存尖峰

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| A0B-1 | SER | 最窄公开前端类型 | A0A-G |
| A0B-2 | PAR-C | Inner 在 320/380/520px 的真实窄容器可用性 | A0B-1 |
| A0B-3 | PAR-C | requestPayload 到 runtime hook 的唯一标记链路 | A0B-1 |
| A0B-4 | PAR-C | runtime hook 与 middleware 比较 | A0B-3 fixture |
| A0B-5 | PAR-C | toolRender result/session/message 与前端动作 | A0B-1 |
| A0B-6 | PAR-C | suggestion 动态注册、注销和无残留 | A0B-1 |
| A0B-7 | PAR-C/GATE | request_context 在历史、state、导出、日志、trace 的留存取证 | A0B-3 |
| A0B-8 | PAR-C | 插件卸载/重装清理 Hook、renderer、suggestion 和 registry | A0B-3…6 |
| A0B-G | INT/GATE | 冻结公开扩展点、注入候选和 direct JSON/context_ref 决策 | A0B-1…8 |

A0B 各原型应写在隔离模块和测试中；真正插件注册、同一浏览器会话和 QwenPaw 安装状态由唯一 owner 排队验证。

### 8.3 阶段 A0C：前端可行性尖峰

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| A0C-1 | PAR-C | RouteSessionStateMachine：新会话、普通聊天、刷新、前进后退 | A0B-G |
| A0C-2 | PAR-C | 正文 EditableFieldAdapter：应用、自动保存、冲突、撤销 | A0B-G |
| A0C-3 | PAR-C | 显式保存表单 Adapter：应用后 dirty、不越过保存按钮 | A0B-G |
| A0C-4 | PAR-C | textarea 选区几何与字段锚定降级 | A0B-G |
| A0C-5 | PAR-C | selection registry：TTL、容量、hash、跨会话失效 | A0B-G |
| A0C-6 | PAR-C | 右侧工具轨迁移和助手不重叠实验 | A0B-2 |
| A0C-G | INT/GATE | 正文和一个显式表单受控回写、路由、选择、保存、撤销闭环 | A0C-1…6 |

A0C-1、A0C-2/3 和 A0C-6 会触碰现有工作台根文件时必须分时或由前端壳 owner 接线；各自的独立状态机、adapter、registry 和测试可并行。

### 8.4 阶段 A0D：ADR 与协议冻结

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| A0D-1 | SER | ADR：原生 Inner、注入机制、role=user 数据边界和留存 | A0B-G、A0C-G |
| A0D-2 | SER | 冻结 NovelAssistantContextV2 与预算/去重 | A0B-G |
| A0D-3 | SER | 冻结 EditableFieldAdapter 与 AIEditTransaction | A0C-G |
| A0D-4 | SER | 冻结 selection/proposal schema | A0C-G |
| A0D-5 | SER | 复核阶段 1–7 工期、代码落点和降级路径 | A0D-1…4 |
| A0D-G | GATE | 七个 P0 全部有实测或明确降级 | A0D-1…5 |

### 8.5 阶段 A1–A7（A0D-G 后才可派发）

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| A1-A | SER | 公开前端类型、助手壳和弹性网格契约 | A0D-G |
| A1-B | PAR-C | route.wrap、Inner 与工作台组合 | A1-A |
| A1-C | PAR-C | 折叠、拖动和本地偏好 | A1-A |
| A1-D1…D5 | PAR-C | 章节、大纲、人物、线索、设定弹性网格 | A1-A；模块独立文件 |
| A1-E | PAR-C | 固定工具轨迁移、separator、状态条与无障碍 | A1-A |
| A1-F | PAR-C | 普通聊天、缩放、路由和双分辨率非回归 | A1-A |
| A1-G | INT/GATE | 三栏与共享 styles/index 接线 | A1-B…F |
| A2-A | SER | V2 schema、预算、裁剪、字段与 persistence 接口 | A0D-G |
| A2-B | PAR-C | Context Store、字段 registry 和生命周期 | A2-A |
| A2-C1…C8 | PAR-C | 正文、标题、章纲、大纲、人物、关系、线索、设定 adapter | A2-A、A2-B 接口 |
| A2-D | PAR-C | AIEditTransaction、逐字段保存与状态文案 | A2-A |
| A2-E | PAR-C | 切页/切书/弹窗、预算、去重、过期和撤销测试 | A2-A |
| A2-G | INT/GATE | 上下文和字段行为汇合 | A2-B…E |
| A3-A | PAR-C | 前端 requestPayload 转换 | A0D-G、A2-G |
| A3-B | PAR-C | ADR 选定的 runtime hook 或替代注入 | A0D-G |
| A3-C | PAR-C | direct JSON/context_ref、Agent/页面/schema/过期检查 | A0D-G |
| A3-D | PAR-C | 内容隔离、预算、留存和路由/会话测试 | A3 契约 |
| A3-G | INT/GATE | 正式事实与草稿页面感知真实对话 | A3-A…D |
| A4-A | PAR-C | 统一正式资料聚合服务与查询预算 | A3-G |
| A4-B | PAR-C | novel_get_workspace_context、归属、provenance、as_of、truncated | A4-A 契约 |
| A4-C | PAR-C | Agent 配置/升级脚本和工具作用域 | A4-B |
| A4-D1…D6 | PAR-C | Agent 文档与六个 Skills 的工具规则 | A4-B 契约 |
| A4-E | PAR-C | N+1、越权、截断、跨书和旧工具兼容测试 | A4-A…D 契约 |
| A4-G | INT/GATE | 统一工具汇合 | A4-A…E |
| A5-A | SER | selection ID、Agent/session、字段、版本、hash 和失效契约 | A0D-G、A2-G |
| A5-B | PAR-C | selection registry | A5-A |
| A5-C1…Cn | PAR-C | 各允许编辑字段的选区 adapter | A5-A、A5-B 接口 |
| A5-D | PAR-C | 阶段 0 选定的位置、suggestion、助手展开和发送步数 | A5-A |
| A5-E | PAR-C | 鼠标、键盘、滚动、缩放、IME 和过期测试 | A5-A |
| A5-G | INT/GATE | 全字段选区发送体验 | A5-B…E |
| A6-A | PAR-C | 结构化提案后端工具与严格 schema | A4-G、A5-G |
| A6-B | PAR-C | 原生 renderer、卡片和降级 | A0D-G、A5-A |
| A6-C | PAR-C | 替换、插入、复制、撤销和放弃 | A5-A、A2-D |
| A6-D | PAR-C | 正文自动保存、表单 dirty、冲突和卡片失效 | A2-G |
| A6-E | PAR-C | 工具作用域、Skill 规则和安装幂等 | A6-A 契约 |
| A6-F | PAR-C | 无工具调用、坏 JSON、超时、切 Agent 与安全测试 | A6 契约 |
| A6-G | INT/GATE | 受控字段应用和撤销闭环 | A6-A…F |
| A7-A…H | PAR | 三题材 AI 质量、1920/2K/200%/错误态、前端、后端/DB、容器、性能、无障碍、控制台分别验收 | A6-G |
| A7-G | INT/GATE | 助手 V2 最终验收、证据和提交 | A7-A…H |

## 9. MOSS-TTS-Nano 并行施工 T0–T6

### 9.1 阶段 T0：ADR、模型、音色包和质量尖峰

当前 TTS 只批准本阶段、ADR 和原型。T0 所有研究包可以并行准备；真实重负载测试受 M4 资源互斥约束。

| ID | 标记 | 工作包 | 独立产物 |
| --- | --- | --- | --- |
| T0-A | PAR | Nano、Tokenizer、ONNX、VoiceGenerator、转码器 revision/hash、许可证和下载清单 | 可复现依赖清单 |
| T0-B | PAR/MUTEX | 进程内 ONNX、受管本机进程、Sidecar、浏览器试听同基准 | 拓扑性能/故障矩阵 |
| T0-C | PAR/MUTEX | 数字、标点、多音字、中英混读、长句、3/5/8/12 秒参考和独立句段听感 | 音质与参考音频报告 |
| T0-D | PAR/MUTEX | VoiceGenerator MPS/CPU、峰值内存、候选生成和 Nano 二次克隆 | 可见/隐藏结论 |
| T0-E | PAR | 24 槽位音色来源、授权台账、去重、样本和人工锁定 | 音色包或替代来源 |
| T0-F | PAR | CodeMirror 6、Monaco、textarea 降级：IME、自动保存、undo、decoration、gutter、UTF-16、Blob bundle | 编辑器 ADR 输入 |
| T0-G | PAR | Manifest v2、章首前缀、中段 ready window、pending gap、快速跳播和播放接缝原型 | Manifest/队列原型 |
| T0-H | PAR | 任务、媒体、脚本、Edition、render、授权与隐私 schema 审查 | 数据/API 草案复核 |
| T0-I | PAR | 固定语料、假适配器、自动化、性能、崩溃恢复和人工听感记录模板 | 可复用验收工具 |
| T0-GATE | GATE | 冻结六项 go/no-go：Nano 拓扑、24 音色、播放器、VoiceGenerator、编辑器、ready-window | ADR、能力矩阵、阶段 0 报告 |

资源规则：T0-B、T0-C、T0-D 的文档分析和脚本开发可以同时进行，但 Nano 与 VoiceGenerator 的 MPS/大内存运行不得同时压测；每次测试必须记录环境、进程、模型 hash、参数、峰值内存和结果。

### 9.2 阶段 T1：共享基础设施与数据

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T1-A | PAR-C | MossNanoTTSAdapter、VoiceDesignAdapter、能力/健康/指纹 | T0-GATE |
| T1-B | PAR-C | 模型下载、校验、预热和受管生命周期 | T0-GATE 拓扑 |
| T1-C | PAR-C | background job、租约、幂等、重试、死信和资源锁 | 共享任务契约冻结 |
| T1-D | SER | TTS schema、Alembic 迁移编号、升级/回退 | T0-H、迁移锁 |
| T1-E | PAR-C | media assets、moss-models、novel-media、Range/ETag、引用/GC | T0-GATE |
| T1-F | PAR-C | tts_snapshot、voice/settings/script/source key/Edition/render/Manifest/进度领域服务 | T1-D schema |
| T1-G | PAR-C | fake adapter、崩溃恢复、GC、迁移和缓存集成测试 | T1-A…F 契约 |
| T1-GATE | INT/GATE | 共享基础设施汇合 | T1-A…G |

### 9.3 阶段 T2：声音和朗读设置

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T2-A | SER | 设置、音色、绑定和试听 API/DTO 冻结 | T1-GATE |
| T2-B | PAR-C | 书本 reading 路由、总览、导航和旁白/范围覆盖 UI | T2-A |
| T2-C | PAR-C | 人物卡“声音”页签、专属/继承与历史影响预览 | T2-A |
| T2-D | PAR-C | 预设、上传、标准化、授权、试听和不可变锁定版本 | T2-A |
| T2-E | PAR-C | 24 槽位导入、通用音色池、覆盖率和缺失提示 | T2-A |
| T2-F | PAR-C | 发音、停顿、音频和缓存设置 | T2-A |
| T2-G | PAR-C | 本地规则/云端授权、撤销、磁盘和模型缺失状态 | T2-A |
| T2-H | PAR-C | API、UI、键盘、授权和历史引用测试 | T2-A |
| T2-GATE | INT/GATE | 设置闭环汇合 | T2-B…H |

### 9.4 阶段 T3：脚本、场景和选角

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T3-A | SER | narration script/segment、范围和 ID 契约冻结 | T1-GATE |
| T3-B | PAR-C | Markdown、纯文本、UTF-16、source_block_key 和 segment_kind | T3-A |
| T3-C | PAR-C | 别名冲突、场景切分、本地说话人规则 | T3-A |
| T3-D | PAR-C | 最小云端不确定窗口、requested/actual 和严格 schema 校验 | T3-A、M0-G/M3-G |
| T3-E | PAR-C | 匿名人物稳定键、合并、拆分和升级 | T3-A |
| T3-F | PAR-C | 通用选角、scope 优先级和稳定分配 | T2-GATE、T3-A |
| T3-G | PAR-C | 情绪/表达、置信等级和人工覆盖继承 | T3-A |
| T3-H | PAR-C | 脚本复核 UI、审批、版本和 unknown 处理 | T3-A |
| T3-I | PAR-C | 归因准确率、非法 ID、隐私和重复分析测试 | T3-A |
| T3-GATE | INT/GATE | 可审批朗读脚本汇合 | T3-B…I |

### 9.5 阶段 T4：独立句段合成和同步播放

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T4-A | PAR-C | Edition、不变设置快照、render fingerprint 和缓存作用域 | T1-GATE、T3-GATE |
| T4-B | PAR-C/MUTEX | 持久句段 Worker、优先级、公平老化、取消和单并发资源锁 | T1-GATE |
| T4-C | PAR-C | master/播放副本校验、转码、响度和接缝处理 | T0-GATE |
| T4-D | PAR-C | Manifest v2、连续前缀/range、ETag/CAS 和 prepare-range API | T0-G、T1-GATE |
| T4-E | PAR-C | Web Audio 队列、3–5 段预取和双 audio 回退 | T4-D mock |
| T4-F | PAR-C | NarrationEditorBridge 与正式编辑器适配器 | T0-F ADR |
| T4-G | PAR-C | gutter、上下文命令、键盘跳播、高亮和滚动暂停/恢复 | T4-D、T4-E、T4-F 契约 |
| T4-H | PAR-C | working_copy_diverged、旧稿字幕、显式更新和 Edition 切换 | T4-A、T4-F |
| T4-I | PAR-C | 局部失效/重生成、旧版本视图、进度保存和快速连续跳播 | T4-A、T4-D |
| T4-J | PAR-C | Manifest、编辑映射、缓存、隐私、恢复和不触发按键级 TTS 自动化 | T4 契约 |
| T4-K | PAR/MUTEX | 一章真实多角色、接缝、30 分钟、RTF、跳播和人工听感 | T4-A…I 集成 |
| T4-GATE | INT/GATE | 核心“番茄式多角色朗读”验收 | T4-A…K |

### 9.6 阶段 T5：文字描述生成音色

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T5-A | PAR-C/MUTEX | VoiceGenerator 受管后端、生命周期和资源锁 | T0-D go |
| T5-B | PAR-C | 人物卡资料到可编辑音色描述 | T2-GATE |
| T5-C | PAR-C | 多候选、试听、来源、不可变版本和私人音色库 UI | T2-A、T5 契约 |
| T5-D | PAR/MUTEX | VoiceGenerator 样音到 Nano 克隆保持度与质量测试 | T5-A |
| T5-E | PAR-C | M4 不达标时隐藏入口和既有路径非回归 | T5-A…D |
| T5-GATE | INT/GATE | 文字生音色产品化裁决 | T5-A…E |

### 9.7 阶段 T6：高级生产

| ID | 标记 | 工作包 | 前置/汇合 |
| --- | --- | --- | --- |
| T6-A | PAR-C | 人工确认的情绪音色变体 | T4-GATE |
| T6-B | PAR-C/MUTEX | 群体声音混合与听感 | T4-GATE |
| T6-C | PAR-C | 全书批量生成、恢复、优先级和公平性 | T4-GATE |
| T6-D | PAR-C | 章节/全书导出与 manifest | T4-GATE |
| T6-E | PAR-C | 发音批量校对和可选 ASR 告警 | T4-GATE |
| T6-F | PAR-C | 音质报告、可达性 GC、配额和磁盘治理 | T4-GATE |
| T6-G | PAR-C | 明确开启的空闲预生成和显式 Edition 切换 | T4-GATE |
| T6-H | PAR | 批量、恢复、导出、音质、配额和隐私回归 | T6 契约 |
| T6-GATE | INT/GATE | 高级生产最终验收 | T6-A…H |

## 10. 跨专项冲突与文件所有权

以下位置禁止两个代理同时修改。正式派发时必须给出唯一 owner；其他代理只能在新文件、测试文件或 mock 上工作。

| 共享位置/资源 | 可能冲突的计划 | 执行规则 |
| --- | --- | --- |
| backend/models.py | M、A、T、B/O/W | schema owner 唯一；其他代理提交字段建议，不直接并写 |
| backend/migrations/versions | M、T、B/O/W | migration owner 串行分配 revision、备份、升级和回退 |
| backend/app.py、plugin.py | M、A、T | 各专项先写独立模块；入口注册由主 Codex 集中接线 |
| backend/services.py、creative_services.py | M、A、T、W | 先冻结服务接口；按函数/模块明确 owner，禁止重叠 |
| backend/model_runtime.py | M、T 云端分析、长篇生成 | M 计划先冻结模型证据语义；其他专项只依赖公共接口 |
| frontend/src/types.ts、api.ts | M、A、T、W | DTO/type owner 唯一；页面代理使用冻结类型 |
| frontend/src/index.ts、styles.ts | A、T、所有 UI | 页面/样式集成 owner 唯一；模块尽量使用独立样式入口 |
| workbench-v2.ts、workbench-studio.ts、chapter-workflow.ts | A、T、L-F、W | 按页面区域或函数划定所有权；最终接线串行 |
| qwenpaw-agent 与 skills/* | M、A、创作质量 | 每个 Skill 可单独 owner；系统提示和统一版本由一个 owner 汇合 |
| configure/verify 脚本 | M、A、T | 先冻结工具与模型策略，再由脚本 owner 一次性更新 |
| pyproject、requirements、前端依赖锁 | 所有计划 | 依赖 owner 统一修改、锁定、许可证和构建验证 |
| PostgreSQL 实例 | 迁移、集成测试、三书验收 | 破坏性测试和迁移 MUTEX；只读检查可并行 |
| QwenPaw active model/Agent 配置 | M、A、L-G、真实 E2E | 每次验收固定状态并记录；切换模型的用例串行 |
| M4 CPU/GPU/内存 | T0/T4/T5/T6 | 重负载模型 MUTEX；Nano 与 VoiceGenerator 默认不同时常驻 |
| Git index、commit、push | 所有代理 | 仅主 Codex 操作；子代理不得提交或推送 |

推荐通过新增领域模块降低冲突，但新增文件名和包结构也必须先由主 Codex登记，避免两个代理创建功能重复的模块。公共 barrel、入口和导出文件留到每一波 INT 阶段统一修改。

## 11. 测试也要并行，但验收不能分裂

每个开发工作包应同时配一个独立测试工作包，测试可以在契约冻结后提前编写：

- 单元测试：按领域模块分文件并行；
- API 契约测试：按路由族分组并行；
- PostgreSQL 集成测试：测试代码可并行写，使用同一实例的破坏性执行串行；
- 前端组件测试：按页面或 store 分文件并行；
- 类型检查、生产构建和 diff-check：每波集成后由主 Codex统一运行；
- 浏览器 E2E：不同只读页面可并行；会修改同一本书、同一会话或同一模型配置的流程必须隔离或串行；
- 视觉 QA：1920×1080、2K、弹窗、空态和错误态可分包，最终 design-qa 只由一个人汇总；
- TTS 听感：样本可分组盲听，统一音量、设备、参数和评分口径后才能合并结论。

任何子代理“自己的测试通过”都不等于阶段完成。主 Codex必须在集成树上复跑受影响的单元、集成、构建、E2E、迁移和恢复测试。

## 12. 正式开发时的直接派发模板

    工作包：T4-F
    目标：实现 NarrationEditorBridge 和已冻结编辑器适配器
    前置：T0-F ADR 已通过；T3-A segment range 契约已冻结
    允许文件：明确列出的新模块和独立测试文件
    禁止文件：models.py、迁移、types.ts、styles.ts、index.ts、依赖锁
    输入：EditorBridge 接口、UTF-16 样本、长章节 fixture
    验收：IME、undo/redo、decoration、gutter、范围映射测试
    交付：变更清单、测试输出、风险、需要主 Codex接线的位置

每一波的执行顺序固定为：

1. 主 Codex检查范围批准、Git 状态和上波门禁；
2. 冻结公共契约并登记文件 owner；
3. 向 ready set 派发所有 PAR/PAR-C 工作包；
4. 子代理独立实现、测试并报告，不自行提交；
5. 主 Codex逐包审查和接线，解决共享文件冲突；
6. 运行该波完整测试、真实恢复和必要 QA；
7. 通过 GATE 后再开启下一依赖波；
8. 主 Codex精确暂存、检查提交内容、提交并按用户要求推送。

## 13. 开工前检查清单

- [ ] 当前阶段已被用户批准，不用并行授权越过范围门禁。
- [ ] 工作树中已有改动的归属已确认；不会覆盖用户或其他任务的修改。
- [ ] 每个工作包有稳定 ID、owner、允许文件、禁止文件和验收产物。
- [ ] 公共 schema、API、状态机、DTO 和错误语义已经冻结。
- [ ] 迁移、数据库、宿主配置、模型配置、M4 资源和 Git 均有互斥 owner。
- [ ] 子代理任务之间没有隐藏的同文件写入或同一外部状态写入。
- [ ] 单元、集成、浏览器、视觉、性能、恢复和听感测试均有归属。
- [ ] 主 Codex预留了集成、全量回归、文档同步和回退时间。
- [ ] 阶段完成以 GATE 验收为准，不以代理数量或候选分支数量为准。

## 14. 当前状态解释

本文列出“可并行”只表示任务形状适合并行，不表示所有工作包现在都已经获得实施授权。正式开工时必须同时读取各专项文件顶部状态：

- 核心 MVP 和阶段 7 首个纵向闭环已有完成记录，不重复施工；
- 长篇一比一总目标按其最新检查点继续，只派发尚未完成的 L-F 至 L-J 工作；
- Agent 模型跟随从 M0 公共契约门禁开始；
- QwenPaw 助手联动 V2 当前只从 A0A–A0D 开始，七个 P0 未闭环前不得派发 A1–A7；
- MOSS-TTS 当前只允许 T0、ADR 和原型，T0-GATE 前不得派发 T1–T6 正式产品代码；
- B/O/W 扩展只有在对应范围已明确批准且现有实现盘点完成后才派发。

如果专项状态与当前代码或 Git 工作树不一致，先执行只读审计并更新状态，不根据本文编号猜测已经完成或尚未完成。
