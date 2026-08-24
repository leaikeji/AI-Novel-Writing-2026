# 跟随“AI 小说作家”Agent 模型切换开发计划

状态：**计划已完成 2026-08-25 三次审核，是本项目模型切换的唯一批准方案。2026-08-25 已完成阶段 0–4 施工、数据库单向迁移、真实 QwenPaw 安装升级和当前 effective 模型验证；仍待第二个真实可用模型的付费/连接 E2E，不因此保留固定模型、双轨或回退路径。**

制定日期：2026-08-25（Asia/Shanghai）

最近审核：2026-08-25（Asia/Shanghai）

目标环境：QwenPaw 2.1.0 内的 `AI小说世界2026` PawApp；专用 Agent ID 固定为 `ai-novel-writer`。

关联文档：

- [架构边界与模型接入决策](./01-架构边界与模型接入决策.md)
- [总体架构与核心流程](./06-总体架构与核心流程.md)
- [新项目初始化与兼容性验证](./13-新项目初始化与兼容性验证.md)
- [ADR-0001：QwenPaw 原生聊天组合与小说 Agent 作用域](./ADR/ADR-0001-QwenPaw原生聊天组合与小说Agent作用域.md)
- [妙笔神书一比一创作闭环与三书实写总目标计划](./16-妙笔神书一比一创作闭环与三书实写总目标计划.md)
- [Codex 多子代理并行施工矩阵](./21-Codex多子代理并行施工矩阵.md)

## 0. Codex 并行施工索引

本计划按并行矩阵第 7 节的 M0–M5 工作包直接派发：

| 阶段 | 可并行工作包 | 串行/汇合点 |
| --- | --- | --- |
| 0 | M0-A…E：模型 scope、公开读取、路由、usage、竞态尖峰 | M0-G 冻结 effective、requested/actual 和 attempt |
| 1 | M1-A…D：Agent 依赖、解析器、路由接入、schema/测试 | M1-G 统一入口接线 |
| 2 | M2-C/D：幂等 attempt 与历史兼容测试 | M2-A/B 数据库备份和迁移，M2-G 数据门禁 |
| 3 | M3-A…E：审计、提示/解析、六 Skills、系统提示、测试 | M3-G 运行时汇合 |
| 4 | M4-B…E：各页面动态显示和隔离测试 | M4-A DTO/type 冻结，M4-G 前端接线 |
| 5 | M5-A…D：配置脚本、验证脚本、分层回归、两模型 E2E | 真实模型切换使用共享 Agent 状态，M5-G 最终门禁 |

模型跟随迁移必须先于后续 TTS 正式迁移；本计划与助手计划共享 Skills、配置脚本和领域服务时，严格采用并行矩阵第 10 节的单一文件所有权。

## 1. 决策摘要

本项目把当前“只接受 `minimax-cn / MiniMax-M3`”的创作生成链改为：

> 所有自动创作任务固定由 `ai-novel-writer` Agent 执行；每次任务开始前读取该 Agent 的有效模型，调用后核验实际模型，下一次任务自动跟随用户在 QwenPaw 中完成的模型切换。

有效模型遵守 QwenPaw 2.1.0 的原生优先级：

```text
ai-novel-writer 有专属 active_model
  -> 使用 Agent 专属模型

ai-novel-writer active_model = null
  -> 使用 QwenPaw 全局默认模型
```

这里的“继承全局”是 `ai-novel-writer` effective 模型的正常解析规则，不是生成失败后的备用模型回退。任务一旦按某个 effective 模型开始，失败时不得改用全局模型或其他模型续跑。

本项目不新增模型选择页，不复制 Provider 设置，不保存模型密钥，不接管 QwenPaw 的模型参数。

### 1.1 明确不建设模型档案

本计划明确排除以下设计：

- 不建立模型档案表、模型注册表或模型能力画像。
- 不建立本项目自己的模型白名单、推荐榜或兼容性等级。
- 不按模型名称分叉 Skills、业务提示词或领域流程。
- 不在 PawApp 中维护逐模型温度、思考预算、最大输出、重试或供应商参数。
- 不因某个模型一次失败就沉淀永久模型规则。
- 不要求新模型先登记、建档或发版后才能使用。

模型与参数升级速度快，以上数据容易过期，还会与 QwenPaw Provider 配置形成第二份真相。供应商、模型、参数与连接状态继续完全由 QwenPaw 管理。

### 1.2 必须保留的不是档案，而是任务证据

每次任务仍必须记录：

- 固定执行 Agent ID；
- 调用前解析到的 requested provider/model；
- 调用后用量元数据中的 actual provider/model；
- 输入哈希、提示词/Skill 契约版本、输出状态和失败原因；
- 已有业务要求的输入快照、目标字数、输出字数和结果内容。

这些字段只证明某一次任务实际发生了什么，不形成可复用的模型档案，也不限制下一次可以选择什么模型。

### 1.3 唯一运行策略与不可退回原则

正式运行时只允许这一条路径：

```text
ai-novel-writer effective 模型
  -> 任务级 requested 证据
  -> QwenPaw Agent 调用
  -> actual 证据与通用结果校验
  -> 成功保存或安全失败
```

以下替代路径永久排除：

- 不保留“固定 MiniMax-M3”运行模式、环境开关或隐藏兼容分支。
- 不在新模型失败时静默回退 MiniMax-M3、全局模型或其他备用模型。
- 不同时维护“旧固定模式”和“新跟随 Agent 模式”两套生产代码。
- 不通过偷读 QwenPaw 私有配置维持旧路径。
- 不让前端、安装脚本或历史任务反向决定下一次运行模型。

故障只能安全失败并向前修复。数据库备份和迁移中断恢复只保护用户数据，不构成产品策略退回；一旦新路径完成切换并接受新写入，后续问题通过修复新路径解决，不恢复固定模型业务逻辑。

### 1.4 可靠性的定义与已接受代价

本文所说的“可靠”不是承诺任意新模型都能生成合格小说，而是保证：模型来源唯一、调用 Agent 正确、每次实际模型可核验、历史不会被覆盖、失败不会污染业务数据、系统不会暗中换模型。模型能力不足时，正确结果是可见失败，而不是伪装成功。

选择唯一方案的收益和主动接受的代价如下：

| 收益 | 主动接受的代价与处理 |
| --- | --- |
| 用户在 QwenPaw 切换后，下一次任务自然生效，不等待 PawApp 发版 | 新模型可能不满足输出契约；由通用校验安全失败，用户自行决定是否换模型 |
| QwenPaw 是模型设置的唯一真相，没有易过期档案和白名单 | 不做逐模型提示词或参数优化，优先保持 Skills 和流程通用 |
| 单一运行路径减少长期维护、测试分叉和隐藏状态 | 公开 active-model API 或用量身份证据异常时会阻止生成，必须修复唯一路径 |
| requested/actual/attempt 让切换、竞态、费用和历史可审计 | 审计记录增加少量存储和迁移复杂度 |
| 不静默换模型，用户对质量、成本和隐私选择保持知情 | 用户误切模型会影响下一次任务，因此生成前必须只读展示 effective provider/model |
| 多步骤任务可逐次采用新模型，不锁死整本书 | 同一本书可能出现跨模型风格差异，由任务历史、作者审阅和统一 Skills 管理，不自动换回旧模型 |

这些代价不引入第二套策略。它们全部在 `follow-agent-effective` 内通过预检、审计、通用校验、可见失败和作者确认处理。

## 2. 范围与非目标

### 2.1 本次纳入

- 建书模板、取名和封面方案文本；
- 五步大纲的背景、角色、主要情节和亮点；
- 故事线推荐和章纲生成；
- 章节正文生成与重新生成；
- 章节情报同步；
- AI 审稿；
- 关系网自动同步；
- 上述任务的历史记录、模型显示、失败恢复和审计。

### 2.2 本次不纳入

- Embedding 模型；它继续按独立 `EmbeddingAdapter` 和向量空间规则管理。
- TTS、VoiceGenerator、图片和视频模型；它们有各自的输入输出契约和隐私边界。
- 在小说工作台增加第二套模型设置或模型参数表单。
- 每个按钮单独选模型、会话级临时模型覆盖或自动模型路由。
- 对模型质量做排行榜、打分、推荐或自动回退。
- 固定 MiniMax-M3 兼容模式、双轨运行和失败后备用模型。
- 修改 QwenPaw 上游源码、私有配置文件或 Provider 密钥存储。

### 2.3 与 MiniMax-M3 历史验收的关系

[妙笔神书一比一创作闭环与三书实写总目标计划](./16-妙笔神书一比一创作闭环与三书实写总目标计划.md)中的 MiniMax-M3 记录是当时的专项验收条件和历史证据，不得改写。

本文生效后：

- 已完成的 MiniMax-M3 任务继续显示原 requested/actual 模型；
- 历史验收报告继续保留 MiniMax-M3 名称；
- 新任务跟随 `ai-novel-writer` 的有效模型；
- 如果仍需完成一个“只允许 MiniMax-M3”的历史验收批次，应在验收前由用户把 Agent 切回 MiniMax-M3，而不是让业务代码永久锁死。

## 3. 已核实的当前事实

### 3.1 QwenPaw 模型作用域

**已核实事实**：QwenPaw 2.1.0 的模型 API 支持 `effective`、`global` 和 `agent` 三种读取作用域。`effective` 先读指定 Agent，Agent 未设置时回退全局模型。

**已核实事实**：`PawAppContext.chat()` 根据 `ctx.agent_id` 取得 workspace 并执行请求，但当前公开参数没有单次 `model_override`，`ctx.config` 的活动模型仍是占位值。

**项目决策**：本项目通过 QwenPaw 公开的 `GET /api/models/active?scope=effective&agent_id=ai-novel-writer` 读取有效模型；不再直接导入 `qwenpaw.config.config.load_agent_config` 作为正式方案。

### 3.2 当前 Agent 路由并不统一

**已核实事实**：正文和情报创建请求显式带有 `agent_id=ai-novel-writer`；建书、大纲、章纲、审稿、封面、故事线和关系网等通用创作请求没有该参数。按 QwenPaw 2.1.0 的 `get_ctx` 行为，未指定时会得到 `default` Agent。

**已核实事实**：当前本机的 `default` 与 `ai-novel-writer` 都恰好是 `minimax-cn / MiniMax-M3`，所以错误 Agent 没有通过模型结果暴露。

**项目决策**：所有 AI 路由在服务端强制使用 `ai-novel-writer`。前端查询参数不再承担安全或正确性责任。

### 3.3 当前幂等键不含模型身份

**已核实事实**：正文任务、通用创作任务和情报提案的 `input_hash` 都没有纳入 provider/model。输入不变时，切换模型可能复用旧任务。

**项目决策**：所有新生成任务使用统一的模型相关幂等材料：

```text
业务输入快照
+ agent_id
+ requested_provider_id
+ requested_model_id
+ generation_contract_version
-> input_hash
```

同一输入使用不同模型必须形成不同任务；同一模型、同一契约、同一输入仍可按原业务规则复用。

### 3.4 安装脚本会覆盖用户选择

**已核实事实**：`scripts/configure_qwenpaw_novel_agent.py` 每次执行都会把 Agent 更新为环境变量指定的模型，默认是 MiniMax-M3。

**项目决策**：脚本不再读取任何“初始模型”环境变量。首次创建 Agent 时保持专属模型为空并继承 QwenPaw 全局默认；已有专属模型或“继承全局”选择原样保留。若全局也没有可用模型，安装验证明确报告“未就绪”并阻止生成，提示用户先在 QwenPaw 配置，不替用户选择 MiniMax-M3 或其他模型。

### 3.5 Skills 不绑定模型，但阶段边界已过期

**已核实事实**：六个小说 Skills 没有 MiniMax-M3 条件，工作方法可以跨模型复用。

**已核实事实**：部分 Skill 和 `qwenpaw-agent/AI_NOVEL_WORLD.md` 仍声明“不创建候选版本”“只能在对话中给出草稿”，与当前已实现的候选、Diff、采用和情报闭环冲突。

**项目决策**：更新这些阶段边界，使 Skills 同时适用于原生对话和 PawApp 发起的受控生成任务；不新增任何按模型名称分支。

## 4. 目标调用链

```text
用户在 QwenPaw 中设置 ai-novel-writer 模型
  -> 若 Agent 有专属模型，使用专属模型
  -> 若 Agent 重置为全局，使用全局默认模型

用户在小说工作台发起生成
  -> 服务端强制选择 ai-novel-writer
  -> 通过 QwenPaw 公开 API 解析 effective provider/model
  -> 计算包含模型身份和契约版本的 input_hash
  -> 创建不可混淆的任务记录
  -> ctx.chat(..., skill=..., session_id=...)
  -> 从回复/用量元数据解析 actual provider/model
  -> requested 与 actual 完全一致：进入通用内容校验
  -> 不一致或缺少实际模型证据：任务失败，结果不进入候选/情报/关系网
  -> 校验通过：保存结果和实际模型
```

### 4.1 当前版本的冻结语义

QwenPaw 2.1.0 的 `ctx.chat()` 没有公开单次模型覆盖参数，因此本项目只能冻结“任务预期模型身份”，不能要求宿主在 Agent 被并发切换后仍强制使用旧模型。

如果模型在预检与实际调用之间发生变化：

- 不接受实际模型与 requested 模型不一致的结果；
- 任务进入可见失败状态；
- 不自动改用另一个模型重试；
- 用户再次点击生成时，重新读取新的有效模型并创建新任务。

只有未来 QwenPaw 公开每次 `ctx.chat()` 的模型覆盖契约，才能在不修改上游的前提下实现真正单次硬锁定。

### 4.2 任务级切换，不锁整条工作流

模型身份以一次外部生成调用为边界。建书、取名、大纲、章纲、正文、情报和审稿分别创建自己的任务证据；用户在多步骤向导中切换模型时，已经完成的步骤保持原模型，下一次尚未开始的任务使用新的 effective 模型。

本项目不把一本书、一个向导或一个章节永久绑定某个模型，也不修改历史任务模型名称。由不同模型完成不同步骤是允许且可审计的正常状态。

### 4.3 禁止静默模型回退

模型连接、输出、审计或内容校验失败时：

- 当前任务按原 requested 模型记为失败；
- QwenPaw 自身针对同一 provider/model 的传输重试可以继续使用；
- PawApp 不自动改用 MiniMax-M3、全局模型或其他模型；
- 用户可以保持当前模型再次发起，也可以先在 QwenPaw 切换模型再发起；每次外部调用都形成新 attempt。

## 5. 数据设计与迁移

### 5.1 字段语义

三类任务统一使用以下概念：

| 字段 | 含义 |
| --- | --- |
| `execution_agent_id` | 本次实际指定的 Agent，当前固定 `ai-novel-writer` |
| `requested_provider_id` | 调用前从 effective 模型解析得到的 provider |
| `requested_model_id` | 调用前从 effective 模型解析得到的 model |
| `actual_provider_id` | 回复用量证据中的 provider |
| `actual_model_id` | QwenPaw 回复用量元数据报告的 model |
| `generation_contract_version` | 业务提示词、Skill 使用方式和校验结构的版本 |
| `input_hash` | 包含业务输入、Agent、requested 模型和契约版本的幂等哈希 |
| `attempt` | 同一 input hash 下第几次真实外部调用；每次调用只增不改 |

provider/model ID 按不透明标识处理。不得删除标点后比较，也不得自行把别名猜成同一模型；调用前后使用 QwenPaw 返回的原值精确比较。

`actual_provider_id`/`actual_model_id` 只代表 QwenPaw 能观察并写入回复用量的身份。若 Provider、Portkey、OpenRouter 或其他网关在其内部把别名路由到另一底层模型，本项目不能穿透上游证明物理模型，不得把 QwenPaw 可见身份表述成供应商内部绝对真相。

同一 `input_hash` 的每次真实调用必须创建新的、不可覆盖的 attempt。失败重试不能把旧失败记录原地改成成功；唯一约束按“业务作用域 + input hash + attempt”表达，保留每次费用、输出、失败和实际模型证据。

### 5.2 移除“模型档案”命名

当前 `chapter_generation_jobs` 和 `intelligence_proposals` 中的 `model_profile_fingerprint` 不是实际档案表，但名称容易继续制造模型档案概念。

迁移方案：

1. 新增 `execution_agent_id`、`requested_provider_id`、`actual_provider_id` 和 `generation_contract_version`。
2. 将现有 `provider_profile` 数据回填到 `actual_provider_id`。
3. 现有 `model_profile_fingerprint` 改为可空并停止新写入；旧值只读保留一个兼容周期，确认后续没有读取方再单独删除该列，不新建替代 fingerprint 字段。
4. 现有 `provider_profile` 在回填后同样停止新写入；兼容期 API 可从 `actual_provider_id` 映射旧字段，后续再单独删除旧列。
5. 新代码不得把 provider/model 组合解释为可查询、可配置的模型档案。
6. 删除 `requested_model_id` 的 MiniMax-M3 ORM/数据库默认值；新任务必须显式传入服务端解析结果。

不直接重命名旧列，也不做长期双写。采用“新增明确字段 → 回填 → 新代码切读写 → 旧列只读兼容 → 后续单独删除”的单向、可中断恢复顺序；旧列兼容只服务历史读取，不构成旧运行策略。

### 5.3 历史数据

- 不改写任何历史 requested/actual provider/model。
- 旧记录缺少 requested provider 时，只有在 `provider_profile` 非空且实际模型已经通过当时的 requested/actual 审计时才能回填；其余保持 `null`，不得填写 `legacy-unknown` 冒充真实 provider，也不得猜测。
- 当前真实数据库中的 MiniMax-M3 历史继续可读取、可显示、可恢复。
- 迁移前必须备份数据库；迁移中断恢复和后续前滚修复都不得删除候选正文、情报项或生成输出。

## 6. 后端改造

### 6.1 专用 Agent 依赖

新增统一的创作上下文入口，例如 `get_novel_generation_ctx`：

- 固定 `agent_id=ai-novel-writer`；
- 不信任前端传入其他 Agent；
- 四个调用入口全部复用：正文、情报、通用创作、关系网同步；
- 非 AI 的普通 CRUD 不增加 Agent 依赖。

### 6.2 有效模型解析器

新增窄接口 `EffectiveModelResolver`，只返回：

```text
agent_id
provider_id
model_id
effective_max_input_length（QwenPaw 提供时）
```

它不是模型档案，也不缓存模型能力。实现使用 QwenPaw 公开 active-model API，并验证：

- 响应存在 `active_llm`；
- provider/model 均非空；
- 目标 Agent 是 `ai-novel-writer`；
- 连接错误转换为可见、可重试的任务失败，不开始模型调用。

`effective_max_input_length` 只在当前任务开始时临时用于通用输入长度预检：存在且输入明显超限时，在调用前给出可见错误；缺失时交由 QwenPaw 正常调用和报错。该值不进入数据库、不缓存、不形成模型能力档案。

### 6.3 通用模型审计

保留 `ModelAudit.ensure_matches()` 的职责，删除：

- `MINIMAX_M3_MODEL_ID`；
- `is_minimax_m3()`；
- `ensure_minimax_m3()`；
- 所有“实际模型不是 MiniMax-M3，结果已作废”的门禁。

新的审计只判断：

```text
requested_provider_id == actual_provider_id
且 requested_model_id == actual_model_id
```

缺少 provider/model 用量证据仍然失败，因为没有证据就不能把结果归属给某个模型。

这里的 actual 是“QwenPaw 可见 actual”，不承诺穿透 Provider 或网关内部路由。缺少用量证据的失败必须单独显示为“模型身份未核验”，不能伪装成 JSON、正文或普通网络错误。

### 6.4 通用提示、解析和校验

- 删除系统提示中的“本次固定使用 MiniMax M3”。
- 不替换成动态模型名；模型无需在业务提示词中被告知自己的名称。
- `parse_model_json`、正文清洗、字数、结构和污染文本检查改成供应商无关命名。
- 允许基于输出形状做通用、确定性的容错；禁止 `if model_id == ...` 类型的分支。
- 任何容错后的结果仍必须通过任务类型的完整结构校验。
- 模型理解和写作差异由 Skills、提示词、作者输入和结果校验处理，不建设模型档案补丁层。

### 6.5 API 请求责任

前端不再提交 `requested_model_id`。服务端按以下顺序执行：

1. 解析 effective 模型；
2. 创建带 requested provider/model 的任务；
3. 调用 Agent；
4. 审计 actual provider/model；
5. 执行业务输出校验；
6. 完成或失败任务。

关系网自动同步中写死的 MiniMax-M3 也必须走同一个入口，不能保留特殊路径。

同一模型重试和切换模型重试都创建新 attempt，不覆盖既有失败任务；任何任务类型都不得把失败历史原地改写为另一模型的成功结果。

## 7. Skills 与 Agent 提示更新

### 7.1 通用原则

- Skills 描述任务方法和内容边界，不描述模型品牌。
- Skills 不承诺模型一定合规；最终由程序校验和作者确认兜底。
- Skills 不读取 Provider、模型名称、密钥或参数。
- 原生对话与 PawApp 受控生成必须区分，但不能互相否定。

### 7.2 需要修订的旧边界

- `prose-writing`：允许 PawApp 把干净正文保存为“可审阅候选”，仍禁止模型声称已经采用或覆盖正式正文。
- `story-bible`：允许受控任务返回结构化草稿或情报候选，正式事实仍以业务采用/同步规则为准。
- `chapter-outline`：允许章纲生成任务写入章纲草稿，最终创建章节仍由业务事务完成。
- `style-review`、`continuity-check`：允许生成结构化审稿结果，但不得直接修改正文。
- `AI_NOVEL_WORLD.md`：删除“当前只能在对话中”的过期阶段说明，改成“模型只输出建议或候选，权威写入由 PawApp 事务完成”。

## 8. 前端改造

### 8.1 删除固定常量和请求字段

删除以下页面中的 `FIXED_MODEL_ID = "MiniMax-M3"` 和所有前端 MiniMax 身份门禁：

- `frontend/src/creative-center.ts`
- `frontend/src/workbench-studio.ts`
- `frontend/src/chapter-workflow.ts`

前端不自行判断某个模型是否允许，只展示后端任务状态和 requested/actual 审计结果。

### 8.2 模型名称显示规则

| 场景 | 显示来源 |
| --- | --- |
| 点击生成前的确认提示 | 后端返回的 `ai-novel-writer` effective provider/model |
| 生成进度 | 当前任务 requested provider/model |
| 成功结果 | 当前任务 actual provider/model |
| 失败结果 | requested 与 actual（若存在）及通用失败原因 |
| 历史列表 | 每条历史自己的 actual，缺少 actual 时显示 requested |
| 旧历史 | 旧记录中的 MiniMax-M3，不随当前设置改变 |

不得用“当前 Agent 模型”覆盖历史任务标签。

多步骤向导允许各生成步骤显示不同模型；每一步只显示自己的 requested/actual，不虚构“本书统一模型”。

### 8.3 文案规则

可以动态显示：

- `{model_id} 正在生成正文`
- `本次将使用 {provider_id} / {model_id}`
- `{model_id} 已完成审稿`

应改成通用文案：

- `模型回复与任务启动模型不一致`
- `当前 AI 小说作家没有可用模型`
- `模型没有返回可解析的结果`

历史证据、测试报告和专项验收计划中的 MiniMax-M3 文案不做动态替换。

### 8.4 Agent 专属模型与全局模型说明

工作台只读显示“当前有效模型”，并在模型入口附近固定说明：

```text
小说生成跟随“AI 小说作家”Agent：Agent 专属模型优先；未设置专属模型时继承 QwenPaw 全局默认模型。
```

用户修改全局模型但 Agent 仍有专属模型时，工作台继续显示专属模型，不误报切换成功。模型配置仍在 QwenPaw 完成，工作台不增加设置控件。

## 9. 安装、升级与健康检查

### 9.1 Agent 配置脚本

`configure_qwenpaw_novel_agent.py` 改为：

- 不读取或写入模型环境变量；
- 首次创建 Agent 时专属模型保持为空，按 QwenPaw 原生规则继承全局；
- 已存在 Agent 且已有专属模型时，不修改；
- 已存在 Agent 且设置为继承全局时，不写回专属模型；
- 全局也没有可用模型时报告未就绪并阻止生成，由用户在 QwenPaw 配置；
- 不再出现“lock novel agent to MiniMax M3”语义；
- 仍验证 Agent、Skills、工具和系统提示安装完整。

### 9.2 健康检查

删除：

```text
required_generation_model = MiniMax-M3
```

替换为稳定策略信息：

```text
generation_agent_id = ai-novel-writer
generation_model_policy = follow-agent-effective
model_verification_mode = preflight-effective+provider-usage
```

另设只读运行时模型状态接口；健康接口不把某一时刻的模型名称当成部署常量。

### 9.3 升级不覆盖

插件升级、重新打包、重新安装和验证脚本都必须证明：

- Agent 当前模型选择不变；
- Agent 的“继承全局”状态不变；
- Provider 密钥和模型参数不被读取或重写；
- Skills 和工具仍只在 `ai-novel-writer` 中启用。

## 10. 实施阶段

### 10.1 施工文件清单

以下是本次代码扫描确认的直接施工面；实施时必须再次运行全仓搜索，不能把本表当成永久允许列表：

| 层 | 文件 | 主要修改 |
| --- | --- | --- |
| 后端入口 | `backend/app.py` | 专用 Agent 依赖、正文/情报调用顺序、健康策略字段 |
| 创作 API | `backend/creative_api.py` | 通用创作和关系网统一解析 effective 模型，删除 M3 请求值 |
| 请求 Schema | `backend/schemas.py`、`backend/creative_schemas.py` | 删除前端可信 `requested_model_id` 和 MiniMax 默认值 |
| 领域服务 | `backend/services.py`、`backend/creative_services.py` | 删除模型门禁、写入任务模型证据、模型相关幂等、通用提示和错误 |
| 模型审计 | `backend/model_runtime.py` | 删除 M3 身份函数，保留通用 actual/requested 审计和通用输出校验 |
| ORM | `backend/models.py` | 新增明确执行字段、删除 MiniMax 默认、停止新写旧 profile 字段 |
| 数据迁移 | 新增 Alembic migration | 不修改历史 `backend/migrations/versions/20260824_0004_longform_workflow.py`；通过新迁移回填、删默认和调整旧列兼容性 |
| 前端 | `frontend/src/creative-center.ts`、`frontend/src/workbench-studio.ts`、`frontend/src/chapter-workflow.ts` | 删除固定模型常量、请求字段和 M3 门禁，按任务动态显示 |
| 前端类型/样式 | `frontend/src/types.ts`、`frontend/src/styles.ts` | 增加 requested/actual provider 字段，清理固定模型注释和旧字段兼容 |
| Agent 安装 | `scripts/configure_qwenpaw_novel_agent.py` | 初次默认、后续保留，不覆盖专属/继承选择 |
| 环境验证 | `scripts/verify_qwenpaw_lab.py` | 验证有效模型存在和模型策略，不再断言 MiniMax-M3 |
| Skills/系统提示 | `skills/*/SKILL.md`、`qwenpaw-agent/AI_NOVEL_WORLD.md` | 修正过期阶段边界，保持模型无关 |
| 后端测试 | `tests/test_model_runtime.py`、`tests/test_domain_integration.py` 及相关领域测试 | 从 M3 允许列表测试改为双模型、继承、竞态、幂等和历史兼容测试 |
| 前端测试 | 相关 `frontend/src/*.test.ts` | 动态模型名称、当前/历史隔离和旧记录兼容显示 |

### 阶段 0：QwenPaw 公共契约尖峰

1. 在固定 QwenPaw 2.1.0 容器中验证 effective、agent、global 三种读取。
2. 验证 PawApp 后端可通过公开 active-model API 获取 `ai-novel-writer` 的有效模型，不导入私有配置模块。
3. 验证所有 AI 路由确实进入 `ai-novel-writer` workspace。
4. 验证回复用量元数据稳定包含实际 provider/model；缺失时能安全失败。
5. 记录并发切换模型时的行为，确认当前版本只能预检加事后审计，不能硬锁单次模型。

退出条件：以上五项有自动化或可复核运行证据；失败则停止，不进入迁移。

### 阶段 1：统一 Agent 与有效模型解析

1. 增加专用 Agent 依赖。
2. 增加公开 API 驱动的 effective 模型解析器。
3. 删除业务请求对前端 `agent_id` 和 `requested_model_id` 的依赖。
4. 四类 AI 路由统一走新入口。

退出条件：把 default 与 ai-novel-writer 配成不同模型后，所有创作任务仍只使用 ai-novel-writer。

### 阶段 2：数据库和幂等迁移

1. 备份当前 PostgreSQL。
2. 新增 requested/actual provider、执行 Agent 和契约版本字段。
3. 回填可证明的历史数据，保留未知值。
4. 删除 MiniMax-M3 默认值。
5. 将模型身份加入三类任务的 input hash，并统一不可覆盖的 attempt 语义。
6. 验证单向 upgrade、中断恢复、历史任务读取和切换后新写入。

退出条件：同一输入用两个模型产生两个任务；历史 MiniMax-M3 记录不变。

### 阶段 3：通用运行时、提示词与 Skills

1. 删除 MiniMax-M3 允许条件和模型名归一化比较。
2. requested/actual 使用 provider/model 精确核验。
3. 提示词、解析、错误和清洗改为模型无关。
4. 审查六个 Skills，并修正其中与当前候选/采用流程冲突的 Skills 和 Agent 系统提示。
5. 保留正文、JSON、字数、关系、情报和审稿的业务校验。

退出条件：代码中不存在运行时 MiniMax-M3 门禁或按模型名称分支；历史文档除外。

### 阶段 4：前端动态显示

1. 删除固定模型常量和请求字段。
2. 增加当前 effective 模型只读显示。
3. 进度、结果、失败和历史按各自任务模型显示。
4. 中途切换模型时不篡改已创建任务名称。

退出条件：当前模型、当前任务和历史任务三种名称不会串用。

### 阶段 5：安装升级与回归

1. 修改配置和验证脚本，保留用户模型选择。
2. 修改健康检查策略字段。
3. 运行后端、数据库、前端、构建和真实 QwenPaw E2E。
4. 用至少两个真实可用模型完成建书辅助、章纲、正文、情报和审稿链路。

退出条件：全部验收用例通过，无正文、历史、Skills、工具和 Provider 设置回归。

## 11. 测试矩阵

### 11.1 Agent 和继承

- Agent 专属模型 A、全局模型 B：所有小说生成使用 A。
- Agent 重置为全局：所有小说生成使用 B。
- Agent 继承全局后，全局从 B 切到 C：下一次小说生成使用 C。
- 原生聊天当前选中其他 Agent：小说自动生成仍使用 `ai-novel-writer`。
- `ai-novel-writer` 不存在或无有效模型：任务不创建模型结果，不改变正文。

### 11.2 模型切换与竞态

- 任务完成后从 A 切到 B：历史 A 仍显示 A，新任务显示 B。
- 相同输入分别用 A、B：生成两个独立任务。
- 相同输入、相同模型连续失败再重试：生成连续 attempt，旧失败记录不变。
- 预检为 A、实际回复证据为 B：任务失败，结果不进入候选或故事账本。
- 回复缺少 provider/model 用量证据：任务失败且原因可见。
- 模型失败后用户切换再试：新任务读取新模型，不篡改失败历史。
- 模型失败后不得静默回退 MiniMax-M3、全局模型或其他模型。

### 11.3 通用输出

- 合法 JSON、代码围栏 JSON、可安全恢复的文本输出。
- 缺字段、错类型、截断、空正文、系统状态胶囊和 Skill 工作语句。
- 正文字数上下限、段落、重复和污染检查。
- 关系、情报、审稿结构校验不依赖模型名称。
- Skills 在两个真实模型下都不与当前候选/采用流程冲突。

### 11.4 数据和升级

- 迁移前后历史 MiniMax-M3 任务数量、内容和模型字段一致。
- 迁移中断可从备份或已提交检查点恢复后继续向前，正文、候选和情报不丢失。
- 插件更新不覆盖 Agent 专属模型。
- 插件更新不破坏 Agent 继承全局状态。
- 首次安装不从环境变量写模型；无全局模型时明确未就绪且不擅自选择模型。
- 前端旧记录缺少 requested provider 时正常兼容显示。

## 12. 验收标准

以下条件必须同时满足：

1. 项目不存在模型档案表、模型白名单、逐模型 Skills 或逐模型业务参数。
2. 所有自动创作任务只通过 `ai-novel-writer` 执行。
3. Agent 专属模型和全局继承语义与 QwenPaw 原生行为一致。
4. 前端不再提交可信模型名称，服务端是任务 requested 模型的唯一写入方。
5. requested/actual provider/model 可核验；不一致结果不能进入业务数据。
6. 模型身份进入幂等键，切换模型不会复用旧任务。
7. 所有运行时 MiniMax-M3 门禁和固定 UI 名称已删除。
8. 历史 MiniMax-M3 数据和历史验收文档保持原样。
9. Skills 和 Agent 系统提示不含过期的“只能在对话中”边界。
10. 插件安装和升级不读取模型环境变量、不替用户选择模型，也不覆盖 QwenPaw 中的用户模型选择。
11. 至少两个真实模型完成关键生成链路，失败模型也能安全失败且不修改权威正文。
12. 每次真实外部调用形成独立 attempt，失败记录不可覆盖。
13. 输入长度只使用 QwenPaw 当次返回值做临时预检，不保存模型能力档案。
14. actual 明确定义为 QwenPaw 可见身份，不虚构网关底层模型。
15. 多步骤流程允许逐任务切换，前端正确显示每步模型。
16. 不存在固定 MiniMax-M3 模式、双轨运行、兼容开关或静默模型回退。
17. 后端单元/集成、前端测试、类型检查、生产构建和真实 QwenPaw 验证全部通过。

## 13. 唯一运行路径、故障恢复与只前滚修复

- 数据迁移前创建数据库备份并记录 Alembic 当前版本。
- 新字段采用先新增、回填、切读、停止旧写入、最后清理的顺序，不在同一步删除旧证据。
- 任一调用缺少 effective 模型、实际模型证据或 requested/actual 一致性时，任务失败，不写候选、情报、关系或审稿结果。
- 已经创建的失败任务保留原因，用户切换模型后创建新任务，不原地伪装成另一个模型的成功任务。
- 若公开 active-model API 在固定 2.1.0 环境中不能可靠供 PawApp 后端调用，阻止模型生成并修复公开契约接入；不得退回偷读配置文件、固定 MiniMax-M3 或前端传模型。
- 迁移在切换新写入前失败时，可以从备份恢复数据后重新执行同一迁移；这属于数据事故恢复，不恢复旧产品策略。
- 一旦新路径开始接受写入，生产问题只通过修复 `follow-agent-effective` 路径和前滚迁移解决，不重新启用固定模型代码。
- 不设置固定/跟随模式开关，不保留旧路由作为应急入口，不用历史 MiniMax 记录影响当前模型选择。

## 14. 三次审核与自查结论

审核日期：2026-08-25（Asia/Shanghai）

### 14.1 已发现并纳入的原计划遗漏

- [x] 发现通用创作接口可能落到 `default` Agent，已改为服务端统一专用 Agent。
- [x] 发现 Agent 未设置专属模型时应按 QwenPaw 规则继承全局，已改为读取 effective 模型；这不是失败后的备用模型回退。
- [x] 发现 QwenPaw 2.1.0 无单次模型覆盖，已把“硬冻结”修正为预检加事后审计。
- [x] 发现三类幂等键都没有模型身份，已加入迁移和测试要求。
- [x] 发现安装脚本会把用户选择重新覆盖为 MiniMax-M3，已删除模型环境变量入口；首次创建继承全局，后续原样保留。
- [x] 发现模型 ID 不能通过删除标点做通用比较，已改为不透明原值精确核验。
- [x] 发现 Skills 和 Agent 提示保留旧 MVP 边界，已加入通用修订阶段。
- [x] 发现动态当前模型不能覆盖历史标签，已分开当前 effective、任务 requested 和历史 actual。
- [x] 发现“模型档案”没有必要，已从方案、数据、阶段和验收中明确排除。
- [x] 发现同模型失败重试也需要独立证据，已统一不可覆盖 attempt。
- [x] 发现上下文窗口可能随模型变化，已限定为 QwenPaw 当次返回值的临时预检，不持久化。
- [x] 发现 actual 无法穿透网关，已限定为 QwenPaw 可见身份。
- [x] 发现多步骤向导可能混用模型，已明确逐任务切换和逐步显示。
- [x] 发现全局切换可能被 Agent 专属模型覆盖，已增加固定继承说明。
- [x] 发现失败后回退会破坏唯一真相，已永久禁止静默模型回退和固定模式复活。

### 14.2 架构自查

- [x] 模型设置唯一真相仍在 QwenPaw。
- [x] PawApp 不读取密钥、不保存 Provider 参数、不建立第二套模型设置。
- [x] Agent、模型和调用结果的职责边界清楚。
- [x] 模型切换不扩大 AI 对权威正文的写权限。
- [x] Embedding、TTS、图片和视频没有被错误并入聊天模型切换。
- [x] 历史专项验收与新运行策略没有相互篡改。

### 14.3 数据自查

- [x] requested 与 actual provider/model 分开保存。
- [x] 模型身份进入幂等键。
- [x] 旧 MiniMax-M3 记录不改写。
- [x] 缺失历史 provider 不猜测。
- [x] 迁移包含备份、中断恢复、单向切换和前滚修复要求。
- [x] 没有模型档案表、档案版本或档案生命周期。
- [x] 每次外部调用都有独立 attempt，失败历史不可覆盖。

### 14.4 施工后证据与仍待验证项

- [x] PawApp 后端通过公开 active-model API 读取 effective 模型的同进程调用方式。
- [ ] `ai-novel-writer` 模型热切换与 workspace reload 的精确时间边界。
- [ ] 所有支持的 Provider 都在回复用量中提供可核验的 provider/model；缺失时的失败路径必须实测。
- [ ] 两个真实模型下的结构化输出、正文长度和 Skill 遵循结果。
- [x] 数据库单向迁移已在当前真实历史记录上 upgrade 到 `20260825_0009`，迁移前备份与只前滚边界已核对。
- [ ] 主动注入迁移中断后的备份恢复演练；本次不为演练破坏已升级的真实数据库。

### 14.5 本次审核证据

- [x] 已读取并核对 QwenPaw 2.1.0 容器中的 `PawAppContext`、`get_ctx`、active-model API、workspace 模型解析和回复用量记录实现。
- [x] 已通过真实 API 确认当前 global、default Agent 和 `ai-novel-writer` 的有效模型均为 `minimax-cn / MiniMax-M3`，证明错误 Agent 会被相同模型配置掩盖。
- [x] 已查询真实 PostgreSQL：当前成功记录包含 30 个正文任务、81 个通用创作任务和 26 个情报提案，均保留 `MiniMax-M3 / minimax-cn` 审计；另有未完成记录需要迁移兼容。
- [x] 已枚举运行时代码、前端、安装脚本和测试中的 MiniMax-M3 硬编码，覆盖后端门禁、ORM/Schema 默认、前端常量、健康检查、安装验证和测试断言。
- [x] 已运行针对性模型/生成/情报测试，结果为 19 项通过、4 项因当前选择条件跳过；这些结果证明现有固定模型基线正常，不代表切换功能已经实现。
- [x] 已验证本文全部本地 Markdown 链接存在。

### 14.6 审核结论

**“零模型档案、跟随专用 Agent 有效模型、只有一条生产运行路径”已实现并安装到当前 QwenPaw 验证环境。**

当前生产代码不存在固定 MiniMax-M3、模型档案、双轨开关或静默备用模型。剩余的双真实模型 E2E 是外部连接和成本验收项，不改变唯一运行路径；后续发现问题仍只允许修复 `follow-agent-effective`，不恢复旧策略。

## 15. 2026-08-25 施工与验收结果

- 后端四类生成入口已统一强制 `ai-novel-writer`，调用前从公开 API 解析 effective provider/model，调用后从可信 usage 信封审计 actual。
- 三类任务已写入 Agent、requested/actual provider/model、契约版本和不可覆盖 attempt；并发 attempt 使用 PostgreSQL 事务级 advisory lock 分配。
- 前端不再提交 Agent 或模型身份；当前 effective、任务 requested/actual 与历史模型分层展示。
- 安装脚本不读写模型环境变量或设置；真实升级前后 `ai-novel-writer` 专属模型选择保持不变。
- Python 完整测试 76 项通过；前端 20 项通过；TypeScript、Vite 生产构建、Compose 配置、插件打包和真实 QwenPaw 验证通过。
- 详细证据见 [模型切换施工验收记录](./证据/模型切换施工-2026-08-25/验收记录.md)。
