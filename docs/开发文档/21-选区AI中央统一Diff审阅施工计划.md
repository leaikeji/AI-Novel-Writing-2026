# 选区 AI 中央统一 Diff 审阅施工计划

状态：**✅ 2026-08-25 已完成 W1–W3 施工并通过 `UD3-G`。一键选区任务、全部既有字段 Host、中央统一 Diff、一次应用/撤销、真实 MiniMax-M2.7 三题材七操作、双桌面分辨率、隔离数据库、完整卸载/重装和原生聊天非回归均已验证。用户已明确授权 `UD4-GIT`，由本次精确提交与推送完成发布。**

计划版本：V1.1（施工验收回写）

制定与复查日期：2026-08-25（Asia/Shanghai）

目标环境：QwenPaw 2.1.0 + AI小说世界2026 PawApp；桌面端 1920×1080、2560×1440，当前不验收手机版。

关联资料：

- [获选设计基线](./设计稿/21-选区AI中央统一Diff审阅-2026-08-25/README.md)
- [选区 AI 改写与审阅体验审计](../../audit/ai-assistant-selection-ux-2026-08-25/README.md)
- [ADR-0004：选区 AI 编辑任务与中央统一 Diff 审阅](./ADR/ADR-0004-选区AI编辑任务与中央统一Diff审阅.md)
- [历史 V2 计划](./20-QwenPaw原生助手与创作上下文联动施工计划.md)
- [ADR-0003：QwenPaw 原生助手上下文与受控编辑边界](./ADR/ADR-0003-QwenPaw原生助手上下文与受控编辑边界.md)
- [模型跟随计划](./19-跟随AI小说作家Agent模型切换开发计划.md)

## 0. 结论、授权与当前事实

### 0.1 施工结论

本计划不是重做 QwenPaw 原生助手 V2，而是在其上下文、字段 Adapter、哈希/CAS、撤销和模型跟随基线上替换一段体验：

> 旧默认路径：“点击选区动作 → 复制 slash 命令 → 切到右栏粘贴发送 → 在聊天内候选卡片审阅”。
>
> 新默认路径：“点击选区动作 → PawApp 直接启动 AI 编辑任务 → 在当前字段所属主工作区进行统一 Diff 审阅 → 一次受控应用”。

用户已选择并确认方案 1；设计方向不再开放重选。本计划完成后已经具备施工所需的产品、协议、文件所有权、回退和验收边界。后续收到明确“开始施工”指令后，从 W0 门禁复核进入 W1，不再重复做 UI 方向讨论。

### 0.2 施工入口事实（历史基线）

- QwenPaw 原生助手 V2 已随提交 `6790eb7` 发布；本计划进入施工时 HEAD 与 `AI-Novel-Writing-2026/main` 均为 `1c9448d`。
- 当前前端仍由 `assistant-selection-controller.ts` 复制 slash 命令，并由 `assistant-tool-card.ts` 把完整候选渲染在右侧聊天消息流中。
- 现有 `EditableFieldAdapter`、Selection Registry、`AIEditTransactionManager`、完整字段 SHA-256、UTF-16 选区、正文 CAS/恢复草稿/自动保存均可复用。
- 后端已经通过公开 PawApp `ctx.chat`、`get_novel_generation_ctx` 和 `get_novel_effective_model` 执行受控生成；`CreativeGenerationJob` 已记录 requested/actual Provider、模型、输入哈希、attempt、输出和失败证据。
- 现有 `creative_generation_jobs` 足以承载 `selection_edit`；首选方案不新增表、不改 Alembic。若真实尖峰证明无法满足幂等、恢复或数据边界，必须暂停并单独裁决迁移，不能临时塞入其他表。
- 规划前相关前端基线专项为 4 个测试文件、39 项通过；这只证明当前候选/事务基础未坏，不代表本计划已经实现。

以上只记录开工时的事实，不再代表当前源码状态；完成后的实现与真实验收结果以第 10 节门禁和[验收证据](./证据/选区AI中央统一Diff审阅-2026-08-25/UD3-E2E/README.md)为准。

### 0.3 当前工作区边界

截至制定时，以下相关共享文件已有未提交修改，均视为需要保留的现有工作，不得被子代理覆盖：

- `frontend/src/assistant-selection-controller.ts`
- `frontend/src/assistant-selection-controller.test.ts`
- `frontend/src/styles.ts`
- `frontend/src/workbench-v2.ts`
- `docs/开发文档/README.md`
- `docs/开发文档/证据/助手计划V2验证-2026-08-25/新会话与选区润色缺陷回归.md`

朗读设计、关系网备份、安装备份及其他未列入本计划的工作区内容全部只读。施工前由唯一集成责任人重新执行 `git status --short` 和目标文件 diff 复核；不得 reset、stash、暂存、提交或清理无关文件。

## 1. 目标与非目标

### 1.1 必须完成

1. 润色、改写、扩写、缩写、增强对白、检查问题由一次点击直接启动 AI 编辑任务；“自定义”在补充要求并提交后启动。
2. 不覆盖系统剪贴板，不要求作者切换到右侧、粘贴或再次发送。
3. 章节正文在中央编辑区显示统一 Diff；其他已注册字段在其所属页面或弹窗的字段主工作面显示同一审阅组件。
4. 支持上一处、下一处、逐处接受、逐处拒绝、拒绝全部、接受全部/应用已接受修改、退出审阅和整次撤销。
5. 逐处决定只修改 `reviewDraft`；最终只通过一次 Adapter 事务写入字段，避免每处决定触发自动保存。
6. 右侧 QwenPaw 助手继续是原生对话，不再承载完整候选正文或嵌套审阅器。
7. 模型始终跟随“AI 小说作家”Agent 的有效模型；记录 requested/actual 证据，不新增模型选择器、固定白名单或静默回退。
8. 网络、模型、校验、冲突、取消、过期、路由或渲染失败均不改变页面字段和权威正文。
9. 现有标题、章纲、总体大纲、正文、人物卡、关系、故事线、伏笔和设定字段的选区能力不得因新主路径回退。
10. 普通 `/chat`、其他 Agent、Provider、Skills、MCP、设置、插件管理和 QwenPaw 卸载恢复保持非回归。

### 1.2 明确非目标

- 不实现手机版审阅。
- 不实现方案 2 的左右同步滚动对照，也不建设对照模式开关。
- 不建设富文本编辑器、多人协作、云端剪贴板或第二套聊天前端。
- 不允许 AI 自动接受、自动保存显式表单或直接写数据库正文。
- 不解析普通聊天文字为修改，不通过私有 DOM/store 模拟发送，不修改 QwenPaw 上游核心。
- 第一版不提供候选内部自由编辑器；作者可审阅应用后继续在原字段手工修改。候选内手改另行评估，不阻断本计划。
- 不顺带修改整章生成、智能朗读、关系网或其他专项计划。

## 2. 产品流程与状态机

### 2.1 默认流程

1. 作者在任一已注册字段中形成有效选区。
2. 选区工具条出现；工具条显示选区字数和操作。
3. 作者点击固定动作，或点击“自定义”并提交要求。
4. 前端立即冻结 Selection Registry 记录、字段完整哈希、UTF-16 范围、原选区和前后文，然后创建 `selection_edit` 任务。
5. 当前字段进入生成态；仍显示原文，不写入候选占位文本。
6. 后端通过“AI 小说作家”Agent 受控生成并返回经过结构校验的纯文本候选、摘要、警告和可复核模型证据。
7. 前端再次校验字段、作品、文档、实体、上下文 revision、完整哈希和选区原文；通过后构造统一 Diff，进入审阅态。
8. 作者逐处决定，或使用全部操作。
9. 最终应用时将接受/拒绝决定合成为一个 replacement，并通过一次 `AIEditTransaction` 与字段 Adapter 写回。
10. 正文继续走恢复草稿、600ms 自动保存和 CAS；显式保存字段保持 dirty，仍由原保存按钮持久化。
11. 作者可撤销整次 AI 审阅事务；撤销仍走同一 Adapter 和原保存策略。

### 2.2 状态机

| 状态 | 可见内容 | 允许动作 | 数据影响 |
| --- | --- | --- | --- |
| `idle` | 普通字段与选区工具条 | 建立选区、选择操作 | 无 |
| `preparing` | 原文、准备状态 | 取消 | 无 |
| `generating` | 原文、进度、取消/收起 | 取消等待；不得应用 | 无 |
| `reviewing` | 统一 Diff、变更计数 | 上/下一处、逐处接受/拒绝、全部操作、退出 | 只改内存 `reviewDraft` |
| `applying` | 审阅面锁定、应用状态 | 不允许重复应用 | 完整校验通过后一次 Adapter 写入 |
| `conflict` | Diff 与冲突说明 | 复制候选、放弃、基于新稿重新生成 | 无 |
| `failed` | 原文与失败说明 | 重试、发送到助手、退出 | 无 |
| `applied` | 正常字段、成功状态 | 撤销 AI 修改、继续编辑 | 已按原保存策略更新草稿 |
| `discarded` | 正常字段 | 重新选择 | 无 |

状态转换不允许跳过 `applying` 校验。刷新、切书、切字段、关闭弹窗、切 Agent、字段 hash 变化或任务基线过期都不能自动应用候选。

### 2.3 操作与 Skill 映射

| 操作 | 默认 Skill | 结果要求 |
| --- | --- | --- |
| `polish` 润色 | `prose-writing` | 保持事实、视角和语气，改善表达 |
| `rewrite` 改写 | `prose-writing` | 保持核心事实，明显改变表达组织 |
| `expand` 扩写 | `prose-writing` | 只扩展选区，不续写未选中内容 |
| `shorten` 缩写 | `prose-writing` | 保留关键信息并显著压缩 |
| `dialogue` 增强对白 | `prose-writing` | 只使用选区和正式资料已有角色关系 |
| `review` 检查问题 | `style-review` | 有可修项时返回修订候选；无修项时返回原文并说明无差异 |
| `custom` 自定义 | `prose-writing` | 只执行作者本次明确要求，不扩展系统权限 |

Skill 只是公开 PawApp 生成调用的创作规则来源，不成为第二套 Agent 或模型配置。若运行态不允许按任务选择 Skill，降级为“AI 小说作家”Agent 默认 Skills，但不得改用其他 Agent。

## 3. 冻结的数据与接口契约

### 3.1 复用现有任务表

首选实现扩展现有 `/api/ai-novel-world-2026/creative-generations`：

- 新增 `kind="selection_edit"`。
- 正文、标题、章纲等文档字段使用 `scope_type="document"`、`scope_id=document_id`。
- 总体大纲、人物、关系、线索和设定等非文档字段使用 `scope_type="novel"`、`scope_id=novel_id`；目标实体和字段仍在受校验的 `input_snapshot.target` 中声明。
- `force_new=false` 为默认幂等路径；同一输入重复点击复用 running/ready job。明确“重新生成”才使用 `force_new=true` 并增加 attempt。
- 使用现有 `CreativeGenerationJob` 记录 input hash、attempt、requested/actual Provider/模型、Agent、失败和完成时间。
- 不新增 migration。若必须增加数据库字段或表，`UD1-BE` 立即停止，由主负责人另建迁移裁决；不得改写历史 revision。

### 3.2 请求快照 V1

```json
{
  "schema_version": 1,
  "selection_id": "uuid",
  "operation": "polish|rewrite|expand|shorten|dialogue|review|custom",
  "custom_instruction": "仅 custom 可用，最多2000字符",
  "target": {
    "novel_id": "uuid",
    "document_id": "uuid或null",
    "entity_type": "document|outline|character|relationship|storyline|foreshadow|setting",
    "entity_id": "uuid或null",
    "field_id": "稳定字段ID",
    "field_label": "显示名称",
    "persistence": "autosave|explicit-save",
    "context_revision": 12
  },
  "base": {
    "field_value_sha256": "64位十六进制",
    "persistence_version_kind": "draft|entity|none",
    "persistence_version": 3,
    "start_utf16": 120,
    "end_utf16": 286,
    "selection_text": "作者明确选中的纯文本",
    "selection_text_sha256": "64位十六进制",
    "before": "最多1500字符",
    "after": "最多1500字符"
  }
}
```

强制规则：

- 选区仍不得超过 12,000 字符；`before/after` 各不超过 1,500 字符。
- `persistence_version` 在没有可比较版本的临时表单中允许为 null；正文使用 draft version，已持久化实体表单使用实体 version。该字段不能替代最终完整哈希与 Adapter 复查。
- 后端从请求路径和当前数据库重新验证作品、文档和 scope 归属；模型传入或浏览器传入的 ID 不能替代服务端校验。
- `field_id/entity_type/operation/persistence` 只接受冻结枚举；禁止任意字段名和任意 Skill 名。
- `custom_instruction` 作为作者数据处理，不能改变系统、Agent、工具权限、保存或模型规则。
- 显式触发的选区文本、前后文、作者自定义要求和候选会存入项目自己的 `creative_generation_jobs`，用于幂等、恢复和审计；不写入 QwenPaw 可见聊天历史、Memory 或日志。不得把其他完整页面字段一并持久化。

### 3.3 结果契约 V2

```json
{
  "schema_version": 2,
  "selection_id": "uuid",
  "operation": "polish",
  "replacement_text": "纯文本候选",
  "short_summary": "不超过240字符",
  "replacement_character_count": 166,
  "warnings": [],
  "diff_segments": [
    {"segment_id": "稳定ID", "kind": "equal", "text": "未改变内容"},
    {"segment_id": "稳定ID", "kind": "delete", "original_text": "被删除内容"},
    {"segment_id": "稳定ID", "kind": "insert", "replacement_text": "新增内容"},
    {
      "segment_id": "稳定ID",
      "kind": "replace",
      "original_text": "原片段",
      "replacement_text": "候选片段"
    }
  ]
}
```

- 模型只负责 `replacement_text` 与简短摘要；字符数、哈希和 `diff_segments` 由项目代码计算，不能接受模型自报。
- `diff_segments.kind` 只允许 `equal|insert|delete|replace`；equal 只含 `text`，insert 只含 `replacement_text`，delete 只含 `original_text`，replace 同时含原文与候选。
- 输出只按纯文本渲染，不执行 HTML、Markdown、URL、脚本或模型给出的操作指令。
- replacement 为空、超限、结构错误、混入状态胶囊或请求/实际模型不一致时，任务失败并保留原文。
- 候选与原文完全一致时显示“未发现需要修改的差异”，不建立伪变更块。
- Skill 与 prompt 继续要求模型直接返回裸严格 JSON。为兼容当前 Provider 的真实传输行为，后端只允许从单个响应中提取**唯一一个**严格形状的 `{replacement_text, short_summary}` 对象并丢弃对象外 reasoning/围栏；多个候选对象、重复 key、非法常量、额外字段、候选内状态胶囊或工作语句仍 fail closed。被丢弃的外围壳不持久化、不显示、不进入 Diff 或作者字段；这是 Provider 传输规范化，不放宽 V1/V2 领域契约。

### 3.4 Selection Registry 新绑定

现有“发送时绑定 QwenPaw session”改为可区分的联合类型：

```text
unbound
  ├─ editor-task(job_id)      # 新默认主路径
  └─ chat-session(session_id) # 显式兼容/对话路径
```

- 同一 selection 一旦绑定一种 delivery，不得静默改绑另一种。
- 编辑任务不依赖当前可见聊天 session，但仍绑定 Agent、作品、文档、字段、context revision、完整字段哈希和 tab instance。
- 聊天兼容路径继续保留原 session 校验，不能借新任务绕过旧会话隔离。

## 4. Diff、决定与最终应用

### 4.1 结构化 Diff

- 后端使用 Python 标准库构建确定性 Diff，不新增前端运行时依赖。
- 第一层按段落和中文/英文句末标点切分并保留分隔符；极长无标点文本按有界块切分，避免二次复杂度失控。
- 改变块可在有界范围内做字符级细化；超过预算或算法无法稳定对齐时安全降级为一个整体 replacement hunk。
- Diff 必须能严格重建原选区与候选文本；若重建校验失败，任务结果无效。
- `segment_id` 由 job/顺序/内容哈希确定；不得使用数组位置以外不可复核的随机语义。
- 性能门槛：12,000 字符原文和候选各一次 Diff，开发机 p95 小于 100ms；前端切换决定不出现超过 50ms 的主线程长任务。

### 4.2 审阅决定

- `equal` 不可操作；`insert/delete/replace` 形成可操作变更块。
- 逐处“接受/拒绝”只更新 `reviewDraft.decisions[segment_id]` 并刷新预览，不调用字段 Adapter。
- 未决定项默认显示候选与原文两部分，不能在合成结果中被默认接受。
- “接受全部”把所有未决定项设为接受并执行一次最终应用。
- 已存在逐处决定时，主按钮显示“应用已接受修改（N处）”；点击后，已接受项使用候选、已拒绝项使用原文、未决定项阻止应用。
- “拒绝全部”放弃整份候选并退出；“退出审阅”在存在未应用接受项时显示确认。

### 4.3 一次性应用

最终合成值必须按以下顺序校验：

1. Agent、作品、文档/实体、字段和 tab instance 仍匹配。
2. Selection Registry 与 job 仍有效，job 为 ready，requested/actual 模型一致。
3. Adapter 当前完整值 SHA-256 等于任务基线。
4. 当前 UTF-16 范围仍对应原 selection_text。
5. Diff 能重建原文，决定能重建最终候选。
6. 异步校验完成后再次读取 Adapter getter，防止校验期间作者继续输入。
7. 仅调用一次 `AIEditTransactionManager.apply`；页面只通过 Adapter 的受控 callback 更新。

正文应用后复用恢复草稿、自动保存和 CAS；显式保存字段只更新 draft 并保持 dirty。应用失败、CAS 冲突或保存失败时不得把结果写成“已完成”；恢复方式沿用现有正文恢复和 AI 事务撤销链路。

## 5. 页面与 UI 接线

### 5.1 统一审阅 Surface

新增项目自有 `SelectionEditReviewSurface`，不复制 QwenPaw 聊天组件：

- 章节正文：替换中央 textarea 的可见审阅面，但保留同一编辑器容器、标题、章节树和工具轨。
- 标题、章纲、总体大纲、人物、关系、故事线、伏笔和设定：挂载到当前字段所属页面或弹窗的主内容区；不把用户带离当前草稿。
- 单行字段使用紧凑的删除/新增两行 diff；多行字段使用与章节正文相同的块级统一 Diff。
- 页面通过稳定 `ReviewSurfaceHost`/Adapter 注册目标容器；禁止 querySelector 后直接覆盖 DOM value。
- 同一标签页只允许一个活动审阅 session。切到另一字段前必须明确放弃、完成或保留为可恢复任务。

### 5.2 工具栏和滚动

- 审阅栏固定在中央/字段主工作面的顶部，不覆盖 QwenPaw 宿主头部。
- 中央区只有一个纵向主滚动容器；候选正文不再拥有独立 180–360px 内嵌滚动框。
- 上一处/下一处滚动到变更并移动程序焦点；不得抢占输入法组合状态。
- 1920 空间不足时按既有策略夹紧助手、折叠章节树；不能隐藏接受、拒绝、退出或当前冲突状态。

### 5.3 右侧原生助手

- 默认一键任务不向原生聊天输入框注入命令，也不创建伪造聊天消息。
- 既有 PawApp 助手状态条可以显示“正在生成 / 候选已在正文打开 / 冲突 / 已应用”，但只显示轻量状态，不包含完整原文或候选。
- `chat.toolRender` 仍需兼容历史消息和作者主动在聊天中发起的结构化提案；renderer 改为紧凑桥接结果，只提供“在编辑器中打开审阅 / 复制 / 放弃”，不再渲染完整候选正文。
- 如果当前字段已离开或候选失效，桥接结果只允许复制/放弃，不恢复过期 Selection Registry。
- 显式“发送到助手”作为失败态或更多菜单中的兼容路径；选择它时可以使用旧 slash suggestion，但不得自动覆盖剪贴板。旧 Clipboard 自动复制只保留为代码回退候选，默认 UI 不调用。

## 6. 无障碍、键盘与错误态

- 审阅工具栏使用 `role="toolbar"`，变更列表使用可读 region/list 语义；状态变化以 `aria-live="polite"` 播报一次。
- 差异不能只靠红绿：同时使用 `+ / −`、新增/删除文本、边框和按钮名称。
- 进入审阅后焦点落在审阅标题或首个变更；退出、失败、冲突、应用和撤销后焦点回到原字段。
- `Escape` 退出前遵守未应用决定确认；不得直接丢失已做决定。
- 键盘必须能完成上/下一处、接受、拒绝、接受全部、拒绝全部、退出和撤销；快捷键需避开中文 IME `compositionstart/ compositionend`。
- 加载、空差异、失败、冲突、过期、取消、离线和超长选区都有独立可见状态。
- 200% 等效缩放下所有核心操作可达；截图只能证明布局，仍需真实键盘和辅助技术检查。

## 7. 恢复、留存与降级

### 7.1 恢复

- `CreativeGenerationJob` 保存显式任务的有界输入和候选。刷新后若当前 Adapter 完整哈希、选区范围、作品和字段仍匹配，页面提示“恢复审阅”，不得自动打开或应用。
- 已接受到字段的结果依靠现有 working copy、不可变 revision、IndexedDB 恢复草稿和 `AIEditTransaction`；不另建平行正文副本。
- 切书、删文档、关闭弹窗或退出工作台时，内存 `reviewDraft` 销毁；ready job 仍是只读历史候选。

### 7.2 取消与超时

- 浏览器取消/Abort 表示停止等待和退出生成 UI；若上游公开接口不能真正取消后台模型调用，后端任务可以继续完成，但绝不自动打开或写回。
- 超时、模型错误和 requested/actual 不一致将 job 标为 failed；原文不变。
- 不为了“看起来已取消”伪造后端取消状态。

### 7.3 功能降级

- 新编辑任务能力不可用时，保留普通编辑器和右侧正常聊天；显示明确错误。
- 兼容路径必须由作者显式点击“发送到助手”，不能静默覆盖剪贴板或私下操作原生输入框。
- QwenPaw 公共契约变化时关闭 editor-task 入口和 bridge renderer，保留手工编辑与原生聊天；在项目适配层修复，不改上游核心。

## 8. 子代理并行施工设计

本节只组织本计划已批准范围，不授权朗读、关系网或其他开发文档。工作包 ID 只属于本文。

### 8.1 标记、角色与共享锁

| 标记 | 含义 |
| --- | --- |
| `PAR` | 只读审计、测试或证据可并行，不修改共享实现 |
| `PAR-C` | 契约冻结后可并行写入，文件所有权必须互斥 |
| `SER` | 只能由唯一责任人串行完成 |
| `MUTEX` | 独占浏览器、数据库、Agent、安装态或共享文件 |
| `GATE` | 前置验收门禁；未通过不得进入下一波 |
| `INT` | 唯一集成责任人接线、复核和汇合 |

唯一集成责任人：主 Codex。其独占 `frontend/src/index.ts`、`frontend/src/styles.ts`、`frontend/src/workbench-v2.ts`、Git index、QwenPaw 安装态和最终裁决。

共享锁：

- `LOCK-FE-SHARED`：`index.ts`、`styles.ts`、`workbench-v2.ts`、`api.ts`、`types.ts`。
- `LOCK-SELECTION`：selection controller/registry、事务和 tool renderer 接线。
- `LOCK-BE-CONTRACT`：creative schema/service/runtime/API 公共契约。
- `LOCK-QWENPAW`：本机唯一 QwenPaw 安装、Agent 配置、真实会话和插件卸载。
- `LOCK-DB`：共享 PostgreSQL 运行态；自动化只使用明确隔离测试库。
- `LOCK-BROWSER`：同一浏览器登录态与精确分辨率窗口。

所有子代理默认不得提交、推送、暂存、删除数据、修改迁移、切换 Agent 模型、安装/卸载插件或触碰未分配文件。若当前运行规则不允许子代理，主 Codex按相同文件所有权串行执行，不改变技术依赖。

### 8.2 波次与工作包

| 波次 | 工作包 | 标记 | 唯一目标 | 精确文件所有权 | 前置/退出条件 |
| --- | --- | --- | --- | --- | --- |
| W0 | `UD0-SER` | `DONE/SER` | 归档设计、冻结计划与 ADR | 本计划、ADR-0004、设计稿 README/PNG、索引 | 本轮已完成；不含代码 |
| W0 | `UD0-G` | `DONE/GATE` | 施工前复核工作区、契约和测试基线 | 只读；本节记录门禁事实 | ✅ 无未解释规划级 P0；相关 39 项测试绿 |
| W1 | `UD1-BE` | `DONE/PAR-C` | selection_edit job、模型规范化、Diff 和恢复查询 | `backend/creative_schemas.py`、`backend/creative_services.py`、`backend/model_runtime.py`、`backend/creative_api.py`、新建 `backend/selection_edit_diff.py`、对应新测试及既有相关测试 | ✅ 不新增迁移；API/结果契约测试通过 |
| W1 | `UD1-FE-CORE` | `DONE/PAR-C` | review session 状态机、决定合成与纯组件 | 新建 `frontend/src/selection-edit-review.ts`、`selection-edit-review.test.ts`、`selection-edit-review-surface.ts`、`selection-edit-review-surface.test.ts` | ✅ 状态机测试通过 |
| W1 | `UD1-SKILL` | `DONE/PAR-C` | 受控选择编辑的 Skill 输出规则 | `skills/prose-writing/SKILL.md`、`skills/style-review/SKILL.md`、`tests/test_skill_contract.py` | ✅ 契约测试通过 |
| W1 | `UD1-BRIDGE` | `DONE/PAR-C` | 将聊天候选 renderer 收缩为中央审阅桥 | `frontend/src/assistant-tool-card.ts`、`frontend/src/assistant-tool-card.test.ts` | ✅ 历史结果安全降级 |
| W1 | `UD1-G` | `DONE/GATE/INT` | 冻结实际 DTO、状态机和 mount 接口 | 主 Codex只读复核各工作包；必要修订由原 Owner 完成 | ✅ 无 DTO 漂移、无同文件冲突 |
| W2 | `UD2-SELECTION` | `DONE/SER/MUTEX` | editor-task delivery、取消选区和兼容路径 | `frontend/src/assistant-selection-controller.ts`、其测试、`assistant-selection-registry.ts`、其测试；独占 `LOCK-SELECTION` | ✅ 一键任务；不默认写剪贴板 |
| W2 | `UD2-INT` | `DONE/SER/INT/MUTEX` | API/types、页面 Host、中央 UI、样式和入口接线 | `frontend/src/api.ts`、`types.ts`、`assistant-fields.ts`、`assistant-body-field.ts`、`assistant-form-field.ts`、`assistant-context-runtime.ts`、新建 `selection-edit-runtime.ts` 与专项测试、`index.ts`、`styles.ts`、`workbench-v2.ts`、`chapter-workflow.ts`、`workbench-studio.ts`、`relationship-editor.ts` 及页面集成测试；独占 `LOCK-FE-SHARED/LOCK-SELECTION` | ✅ 全部注册字段接线；无新嵌套候选卡 |
| W2 | `UD2-CAPABILITY` | `DONE/SER/MUTEX` | 健康能力、打包与安装验证接线 | `backend/app.py`、`scripts/verify_qwenpaw_lab.py`、安装/契约测试；独占安装脚本相关文件 | ✅ 卸载无残留；不改上游 |
| W2 | `UD2-G` | `DONE/GATE/INT` | 功能集成门禁 | 主 Codex | ✅ 一键任务→中央审阅→应用/撤销闭环通过 |
| W3 | `UD3-FE-QA` | `DONE/PAR` | 前端全量、类型、构建、性能探针 | 只读实现；证据目录独占子目录 | ✅ 命令全部通过 |
| W3 | `UD3-BE-QA` | `DONE/PAR/MUTEX` | 后端单元、隔离 DB、幂等、权限、失败恢复 | 只读实现；明确测试数据库 | ✅ 251 passed、0 skipped |
| W3 | `UD3-A11Y-QA` | `DONE/PAR/MUTEX` | 键盘、ARIA、IME、200% | 独占浏览器时段；证据目录独占子目录 | ✅ 无 P0/P1；保留人工 IME 建议 |
| W3 | `UD3-E2E` | `DONE/SER/MUTEX` | 三题材真实模型、双分辨率和宿主非回归 | 独占 `LOCK-QWENPAW/DB/BROWSER` | ✅ 全矩阵完成、正文影响可复核 |
| W3 | `UD3-G` | `DONE/GATE/INT` | 最终产品与技术裁决 | 主 Codex | ✅ 无未解释 P0/P1；恢复路径可执行 |
| W4 | `UD4-GIT` | `DONE/SER` | 精确暂存、提交、推送 | Git index；仅在用户明确授权后 | ✅ 用户已明确授权；排除朗读专项与既有备份 |

#### W1 可并行写包的完整派发契约

`UD1-BE`：

- 唯一目标：在现有 creative generation 链路中实现 `selection_edit` 的严格输入、scope 校验、Skill 映射、模型结果规范化、结构化 Diff、幂等、恢复查询和失败记录。
- 非目标：不建新表、不修改迁移、不碰 QwenPaw 安装态、不改变其他 creative kind 的输出、不写前端。
- 前置输入：本计划第 3–4 节和 ADR-0004；请求/结果字段名不可自行改动。
- 允许修改：表格所列后端文件和 `tests/test_selection_edit_diff.py`、直接相关的既有后端测试；其他文件只读。
- 必跑测试：`.venv/bin/python -m pytest tests/test_selection_edit_diff.py tests/test_model_runtime.py tests/test_domain_unit.py tests/test_api_model_orchestration.py`。
- 返回证据：测试摘要、12k Diff 性能、一个成功/幂等/失败 payload 脱敏样本、实际修改文件和给 `UD2-INT` 的 DTO 说明，写入证据目录 `UD1-BE/`。
- 禁止触碰：任何 Alembic 文件、前端、Skills、Agent 配置、用户数据库、Git index 和无关工作区修改。

`UD1-FE-CORE`：

- 唯一目标：实现与 React 页面无关的 review session 状态机、决定合成、焦点目标模型和纯 `SelectionEditReviewSurface` 组件。
- 非目标：不接真实 API、不修改 selection controller/registry、不改共享样式或工作台、不写字段。
- 前置输入：结果契约 V2、`ReviewSurfaceHost` 事件草案和现有 `AIEditTransactionManager` 只读接口。
- 允许修改：表格列出的四个新文件；若必须增加新测试 fixture，也只能放在同名前缀的新文件。
- 必跑测试：`pnpm exec vitest run frontend/src/selection-edit-review.test.ts frontend/src/selection-edit-review-surface.test.ts`。
- 返回证据：状态转换矩阵、base/candidate 重建、逐处决定合成、无差异/冲突/失败组件快照或 DOM 断言、导出 API 和接线说明，写入 `UD1-FE-CORE/`。
- 禁止触碰：`index.ts`、`styles.ts`、`workbench-v2.ts`、现有 selection/transaction 实现、后端和 Git index。

`UD1-SKILL`：

- 唯一目标：让 `prose-writing` 与 `style-review` 明确区分原生聊天回复和 PawApp `selection_edit` 严格 JSON 候选，并保留事实/选区边界。
- 非目标：不新增 Skill、不修改其他四个 Skill、不切换 Agent/模型、不改工具注册或安装脚本。
- 前置输入：第 2.3 节操作映射和结果契约 V2；不得要求模型生成项目计算的 Diff 或哈希。
- 允许修改：表格所列两个 Skill 和 `tests/test_skill_contract.py`。
- 必跑测试：`.venv/bin/python -m pytest tests/test_skill_contract.py`。
- 返回证据：两种 Skill 的规则差异、契约测试摘要和给后端 prompt Owner 的注意事项，写入 `UD1-SKILL/`。
- 禁止触碰：Agent 文件、manifest、其他 Skills、模型配置、运行环境和 Git index。

`UD1-BRIDGE`：

- 唯一目标：把聊天中的完整候选 renderer 重构为不包含候选正文的紧凑桥，并把可用候选交给共享 review coordinator。
- 非目标：不实现中央 UI、不修改字段、不改变 tool schema、不接 `index.ts`、不操作 QwenPaw 私有 DOM/store。
- 前置输入：现有 tool result V1、结果契约 V2 和 `UD1-FE-CORE` 冻结的 coordinator 入口；若后者未冻结，只能先写测试设计，不能猜接口。
- 允许修改：表格所列 renderer 与专项测试。
- 必跑测试：`pnpm exec vitest run frontend/src/assistant-tool-card.test.ts frontend/src/assistant-page-apply.integration.test.ts`。
- 返回证据：历史结果、ready/expired/conflict/invalid 四类 DOM 断言，完整候选不在聊天 DOM 的断言，以及接线说明，写入 `UD1-BRIDGE/`。
- 禁止触碰：共享入口/样式、selection controller、工作台、后端、Skills、Git index。

#### W2 串行集成包的完整责任

- `UD2-SELECTION` 必须先保存并复核当前未提交的失焦/取消选区修复，再加入 `editor-task` binding；专项测试至少覆盖重复点击、取消、切字段、切 Agent、兼容路径和 Clipboard 未调用。
- `UD2-INT` 是唯一页面接线 Owner；它消费 W1 已冻结接口，把全部现有字段挂入 Review Host，并负责表格列明的 API、字段 Adapter/上下文、统一 runtime、章节页、章纲、工作室各实体弹窗、关系弹窗、入口与样式。实际 mount 审计证明只修改原先六个共享文件无法给章纲、总体大纲、人物、关系、故事线、伏笔和设定提供版本元数据及所属工作面，因此本行是施工前必须完成的所有权纠正，不扩大功能范围。不得把 W1 的独立模块重新复制进共享文件。
- `UD2-CAPABILITY` 只能在功能 DTO 稳定后增加健康/验证能力；若无需更改 manifest 或安装脚本，不得为了“对称”制造无意义改动。
- 三个包的证据分别进入 `UD2-SELECTION/`、`UD2-INT/`、`UD2-CAPABILITY/`；任何共享文件重叠都由主 Codex串行处理，不能交给两个代理事后合并。

#### W3 只读 QA 包的证据边界

- `UD3-FE-QA`、`UD3-BE-QA` 不修改实现；发现失败只报告精确复现，由原 Owner 修复后重跑。
- `UD3-A11Y-QA` 与 `UD3-E2E` 不得同时控制同一浏览器；真实模型、安装态、共享数据库和精确窗口由主 Codex排队。
- 每个 QA 包只写自己的证据子目录，不覆盖其他轨截图或报告；所有截图记录真实像素、URL、作品/章节、操作和数据影响。

### 8.3 可直接派发的任务模板

每个代码子任务必须包含：

- 工作包 ID 和唯一目标。
- 允许修改的精确文件；未列文件一律只读。
- 不得改变的请求/结果 DTO、状态枚举、模型政策、字段 Adapter 和保存语义。
- 当前工作区同文件是否已有修改；有重叠时取消并行，交回唯一 Owner。
- 必须运行的专项测试、输出证据和给主 Codex 的集成说明。
- 禁止 Git、迁移、生产数据、QwenPaw 安装态、Agent 模型和无关专项。

### 8.4 汇合顺序

1. `UD0-G` 冻结当前事实和 DTO。
2. W1 三到四个文件互斥工作包可以并行；主 Codex等待全部完成。
3. `UD1-G` 比对 DTO、事件、review state 和错误码，不在冲突状态下强行接线。
4. `UD2-SELECTION` 串行保留现有选区失焦修复，再由 `UD2-INT` 独占共享前端文件完成页面接线。
5. `UD2-CAPABILITY` 在 API 稳定后接线健康/安装验证。
6. `UD2-G` 通过后，W3 的纯测试轨可并行；真实 QwenPaw、数据库和浏览器轨必须排队。
7. 主 Codex统一复核 diff、运行集成门禁并形成 `UD3-G`。Git 只在新的明确授权后进行。

## 9. 验收矩阵与命令

### 9.1 自动化

前端至少执行：

```bash
pnpm exec vitest run frontend/src/selection-edit-review.test.ts frontend/src/selection-edit-review-surface.test.ts frontend/src/assistant-selection-controller.test.ts frontend/src/assistant-tool-card.test.ts frontend/src/assistant-transactions.test.ts frontend/src/assistant-page-apply.integration.test.ts
pnpm typecheck
pnpm test
pnpm build
```

后端至少执行：

```bash
.venv/bin/python -m pytest tests/test_selection_edit_diff.py tests/test_model_runtime.py tests/test_domain_unit.py tests/test_api_model_orchestration.py tests/test_skill_contract.py
.venv/bin/python -m pytest
.venv/bin/python scripts/package_plugin.py
```

数据库测试必须指向明确隔离测试库；条件测试的 skipped 不得写成通过。打包、健康、安装或公共契约发生变化时继续执行现有 `verify_qwenpaw_lab.py`、安装幂等、完整卸载和重装验证。

最终实际结果：前端 `38` 文件、`303 passed`，typecheck/build 通过；后端明确隔离 PostgreSQL 全量 `251 passed, 0 skipped, 1 warning`；12k 后端 Diff p95 约 `1.403ms`，前端重建 p95 `0.0806ms`；打包产物 0 个 `__pycache__/pyc/pyo`；完整卸载后 PawApp/Skills/novel tools 均为 0，原生聊天恢复，重装 verifier 通过。

### 9.2 功能矩阵

| 场景 | 必须验证 |
| --- | --- |
| 一键启动 | 不访问 Clipboard；不要求原生助手二次发送；只创建一次 job |
| 自定义 | 要求输入、取消无副作用、注入式文字不改变权限 |
| 生成中 | 原文可见、任务状态清楚、重复点击幂等、取消不写回 |
| 统一 Diff | 单滚动面、段落上下文、+/- 和标签、变更计数正确 |
| 逐处决定 | 前后跳转、接受/拒绝决定、未决定阻止应用 |
| 全部操作 | 接受全部一次写入；拒绝全部零写入；退出确认正确 |
| 应用 | 完整哈希、UTF-16、异步复查、Adapter、自动/显式保存正确 |
| 撤销 | 整次审阅一步撤销；正文再次自动保存；表单保持 dirty |
| 冲突 | 生成期间继续输入、切页、切书、切 Agent、删除实体均不覆盖 |
| 恢复 | 刷新后仅在基线仍匹配时提示恢复；不自动应用 |
| 右侧助手 | 正常聊天、附件、停止、历史、新对话不回归；无完整候选卡 |
| 普通聊天 | 不出现小说壳、页面上下文、编辑任务或工具 bridge 泄漏 |

### 9.3 真实模型与真实写作

使用“AI 小说作家”当时的有效模型，不在计划中固定 MiniMax-M3。至少使用三种真实题材作品覆盖全部七个操作：

- 悬疑作品：润色、检查问题、冲突恢复。
- 年代言情作品：改写、增强对白、接受部分并撤销。
- 现实生活作品：扩写、缩写、自定义、拒绝全部。

每种题材都要保存操作前字符数、完整哈希、任务 requested/actual 模型、候选字符数、决定数量、应用后/撤销后哈希和截图。测试作品使用正常书名，不使用“测试”“样例”等伪写作命名。除验收要求的显式应用外，不静默改变其他章节。

### 9.4 视觉与无障碍

- 精确 1920×1080、2560×1440。
- 章节树展开/折叠、助手 320/380/动态最大宽度、助手折叠。
- 200% 等效缩放、长章节、12,000 字符选区、无标点长段、中文 IME。
- 纯键盘完成一整次审阅；焦点进入和返回正确。
- 红绿色觉不可区分时仍可读；检查中文 aria-label 和一次性 live 播报。
- 截图放入 `docs/开发文档/证据/选区AI中央统一Diff审阅-2026-08-25/`，并记录真实像素与数据影响。

## 10. 阶段门禁

### `UD0-G`：允许开工

状态：**✅ 2026-08-25 已通过。**

- 设计、计划、ADR 和索引互链正确。
- 当前工作区目标文件 diff 已复核并分配唯一 Owner。
- 旧 V2 与 ADR-0003 历史事实保留，新 ADR 只替代指定决策。
- 未发现必须先迁移数据库或修改 QwenPaw 上游核心的 P0。
- 获选 PNG 已以 SHA-256 `0886ef8b05356e228d77aa5a7887b4b0a7c67c20c889fe693a9b668336cf52ab` 归档；8 份相关文档本地链接检查为 0 缺失。
- 规划前端基线 4 个相关测试文件、39 项通过；文本与当前 tracked diff 的 whitespace 检查通过。本轮没有运行全量代码验收，因为尚未施工任何功能代码。

### `UD1-G`：协议冻结

状态：**✅ 2026-08-25 已通过。**

- W1 源码协议与专项测试已冻结：后端 67 项、前端审阅内核 42 项、聊天桥 22 项通过；12k Diff p95 远低于 100ms。
- 当前真实安装态仍返回旧的 `kind` 枚举，证明运行中的 PawApp 尚未安装本轮候选，而不是源码 DTO 失败。真实 `/creative-generations` 的 `selection_edit` 受控尖峰并入 `UD2-CAPABILITY` 的打包/安装后第一项门禁；在该尖峰通过前 `UD2-G` 仍不得判定通过。
- requested/actual 模型、Agent、Skill、幂等、失败和 input snapshot 边界可复核。
- Diff 可严格重建 base/candidate，12k 性能达标。
- DTO 与前端 review state 无歧义。

### `UD2-G`：功能闭环

状态：**✅ 2026-08-25 已通过。**

- 七操作不再默认走 Clipboard。
- 章节正文和全部既有字段在本字段所属工作面审阅。
- 逐处决定、一次应用、保存、撤销和冲突通过。
- 右侧不存在完整候选审阅卡；聊天功能非回归。

补充事实：静态测试覆盖 47 个注册字段唯一 Host；真实标题、正文和章纲/弹窗 focus scope 已打开统一 Surface。默认项目任务不向原生聊天写命令或候选卡，工作台内“新建对话”保持同页。

### `UD3-G`：最终验收

状态：**✅ 2026-08-25 已通过。**

- 前后端全量、构建、打包、隔离 DB、安装/卸载、性能、无障碍和三题材真实模型通过。
- 没有未解释 P0/P1；任何跳过项、未运行项和环境限制单独列出。
- 证据、恢复方式和数据影响可复核。

实际裁决：三题材七操作均记录 MiniMax-M2.7 requested/actual 一致；1920×1080、2560×1440、200% 等效缩放和参考稿 1525×1031 同图已复核；正文拒绝/退出零写入，显式应用/撤销后原哈希恢复；隔离数据库、打包、完整卸载、原生聊天、重装和四章哈希保持均通过。人工中文 IME 候选窗和人工读屏顺序作为非阻断发布前复核建议透明保留，不表述为已人工执行。

### `UD4-GIT`：发布

- 2026-08-25 用户已明确要求提交并推送，发布门禁获准执行。
- 精确暂存本计划文件，排除朗读、关系网备份、旧验收备份和用户其他修改。

## 11. 施工前自查与已解除门槛

| 审核角度 | 结论 | 依据/处理 |
| --- | --- | --- |
| 产品方向 | ✅ 已冻结 | 用户选择方案 1；不再比较方案 2/3 |
| 当前/目标事实 | ✅ 已分离 | V2 保留为历史完成；本计划按阶段保存历史入口事实，并在 `UD3-G` 后才回写为最终验收完成 |
| QwenPaw 边界 | ✅ 可施工 | 使用公开 PawApp `ctx.chat` 与现有 route/renderer；不碰私有 DOM/store |
| 模型权威 | ✅ 可施工 | 继续 follow-agent-effective；requested/actual 强校验 |
| 数据与审计 | ✅ 可施工 | 复用 CreativeGenerationJob；显式有界选区留存已在 ADR 披露 |
| 数据库迁移 | ✅ 当前不需要 | 新 kind 复用现有表；若不足必须暂停裁决 |
| 正文安全 | ✅ 已冻结 | reviewDraft 不写字段；最终一次 Adapter/CAS 事务；失败零写回 |
| 多字段兼容 | ✅ 已纳入 | 文档字段中央/字段内审阅，其他实体走 novel scope |
| Diff 可实现性 | ✅ 有安全降级 | 标准库结构化 Diff；无法细分时整体 replacement hunk |
| 右侧聊天 | ✅ 已冻结 | 原生聊天保留；完整候选卡退出默认主路径 |
| 取消语义 | ✅ 已澄清 | 取消等待不伪造上游取消；迟到结果只作可恢复候选 |
| 无障碍 | ✅ 有门禁 | 非颜色语义、焦点、键盘、IME、200% 实测 |
| 并行施工 | ✅ 已分包 | W1 独立文件可并行；共享前端、安装、浏览器与 Git 串行 |
| 工作区保护 | ✅ 已标注 | 相关 dirty 文件由主 Codex独占，其他改动只读 |

自查结论：没有剩余 P0/P1；`UD0-G → UD3-G` 已全部完成，未修改 QwenPaw 核心、未引入第二套模型运行时、未新增迁移。用户已明确授权 `UD4-GIT`；本次只提交本计划范围，排除朗读专项、关系网备份、旧验收备份和其他用户修改。
