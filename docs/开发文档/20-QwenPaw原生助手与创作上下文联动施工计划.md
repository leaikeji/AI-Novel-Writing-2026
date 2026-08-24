# QwenPaw 原生助手与创作上下文联动施工计划

状态：**计划已完成 2026-08-25 首次编制与两轮自查；尚未实施。必须先完成阶段 0 的 Git 基线和公开契约尖峰，才能进入正式功能施工。**

制定日期：2026-08-25（Asia/Shanghai）

目标环境：QwenPaw 2.1.0 内的 `AI小说世界2026` PawApp；桌面端验收分辨率为 1920×1080 与 2K，当前不验收手机版。

关联文档：

- [项目开工计划](./00-项目开工计划.md)
- [总体架构与核心流程](./06-总体架构与核心流程.md)
- [QwenPaw 原生 UI 盘点与小说工作台 UI 基线](./12-QwenPaw原生UI盘点与小说工作台UI基线.md)
- [新项目初始化与兼容性验证](./13-新项目初始化与兼容性验证.md)
- [阶段 3–6 实现与验收记录](./14-阶段3至6实现与验收.md)
- [ADR-0001：QwenPaw 原生聊天组合与小说 Agent 作用域](./ADR/ADR-0001-QwenPaw原生聊天组合与小说Agent作用域.md)
- [跟随“AI 小说作家”Agent 模型切换开发计划](./19-跟随AI小说作家Agent模型切换开发计划.md)

## 1. 目标与批准范围

本计划建设一个由 QwenPaw 原生聊天承载、能够理解当前小说工作台页面和局部选区的写作助手闭环。完成后应满足：

1. 小说工作台右侧保留 QwenPaw 原生对话助手，不复制第二套聊天界面。
2. 助手知道当前作品、模块、卷、章节、文档、人物或线索对象。
3. 助手既能按需读取已保存的小说资料，也能感知当前页面尚未保存的输入。
4. 作者框选标题、大纲、章纲、正文、人物卡等字段的文字后，可以要求助手只处理选区。
5. AI 返回结构化修改提案，作者点击后只替换或插入指定选区，并继续走工作台原有草稿、自动保存和版本流程。
6. 右侧助手、章节树和中央编辑器在 1920×1080 与 2K 下可以同时工作，支持折叠和宽度调整。

### 1.1 本计划对旧阶段边界的更新

早期 MVP 文档与 ADR-0001 的“不在本阶段加入 AI 正文写回 UI”是当时阶段边界。用户现已明确批准选区修改与优化能力，因此本计划允许：

- AI 生成结构化修改提案；
- 作者在 QwenPaw 原生工具卡片中显式点击“替换选中文字”或“插入到后面”；
- 前端将提案应用到当前工作草稿；
- 修改继续由原有自动保存、checkpoint 和 revision 机制处理。

本计划仍然不允许 Agent 工具绕过页面状态直接覆盖数据库权威正文。正式施工前应补充一份新的 ADR，明确“结构化提案 + 作者点击应用”已经取代旧阶段的完全不写回边界；不得静默改写 ADR-0001 的历史决策。

### 1.2 非目标

- 不复制、替换或 fork QwenPaw 原生聊天组件。
- 不读取 QwenPaw 私有 React Router、私有聊天 store 或私有输入框实现。
- 不建立第二套 Agent Runtime、会话系统、模型选择页或 Provider 配置。
- 不让 AI 无操作确认地自动覆盖整章或数据库正式 revision。
- 不在本阶段建设多人协作、手机版交互、语音输入、TTS 或富文本编辑器。
- 不把整本小说全部正文无差别注入每一轮聊天。

## 2. 已核实事实与当前缺口

### 2.1 QwenPaw 公开能力

依据当前容器 `/app/src/qwenpaw/docs/plugins.zh.md` 与本机实测，QwenPaw 2.1.0 公开前端扩展包括：

- `route.wrap(pluginId, "core.chat", wrapper)`：包装并保留原生聊天页面；
- `host.useSelectedAgent()` / `getSelectedAgentId()`：读取当前 Agent；
- `host.useCurrentSession()` / `getCurrentSessionId()`：读取当前会话；
- `chat.sender.set()` / `chat.sender.addSuggestion()`：配置输入区和建议；
- `chat.requestPayload.add()`：在发送前追加或转换请求体；
- `chat.actions.add()`：为普通 AI 回复增加操作；
- `chat.toolRender()`：为指定工具结果提供原生聊天内的自定义卡片；
- `chat.response.append()`：在回复区域追加轻量状态内容。

QwenPaw 后端插件公开支持 `register_tool`、`register_middleware` 与 `register_http_router`。

### 2.2 当前实现回退

当前 `frontend/src/index.ts` 在小说工作台模式下只渲染 `NovelWorkbench`，没有继续渲染 `route.wrap` 提供的 `Inner`。这与 ADR-0001 中“AI 助手区域始终渲染原生 Inner”的已接受决策不一致，是需要优先修复的实现回退。

### 2.3 当前前端类型声明不完整

当前 `frontend/src/qwenpaw-host.d.ts` 只声明了基础 `host` 与 `route`，没有声明已公开的 Agent、Session 与 `chat.*` 扩展点。施工前必须从当前 QwenPaw 2.1.0 公共类型和文档补齐窄类型，不能用大量 `any` 掩盖接口误用。

### 2.4 当前小说工具的覆盖范围不足

当前只注册：

- `novel_get_context`
- `novel_get_document`
- `novel_search`

其中 `novel_get_context` 主要返回已保存的当前/前置文档与正式故事事实；它不会自动知道浏览器当前页面，也没有完整返回大纲草稿、人物卡、关系、故事线、伏笔和当前未保存表单内容。

### 2.5 当前没有公开的命令式聊天发送接口证据

当前公开文档能证明输入建议和请求转换，但不能证明插件可以不经用户操作直接调用原生聊天的 `sendMessage`。本计划不得依赖查询原生输入框 DOM、写入私有 store 或模拟点击发送。

第一版选区操作允许保留一次用户“发送”动作；如果阶段 0 尖峰发现新的正式公开接口，再通过 ADR/文档更新决定是否减少该动作。

## 3. 目标体验与桌面布局

### 3.1 章节正文页面

```text
QwenPaw 宿主侧栏
  └─ 小说工作台
       ├─ 左：章节树（256px，可折叠为 54px）
       ├─ 中：正文编辑区（自适应，最小 760px）
       └─ 右：QwenPaw 原生助手（默认 380px，可调 320–520px）
```

### 3.2 大纲、角色、线索和设定页面

```text
小说资料卡/模块导航
  + 中央模块内容
  + 右侧原生助手
```

### 3.3 助手面板规则

- 桌面首次进入默认展开，默认宽度 380px。
- 支持拖动左边缘调整宽度，最小 320px、最大 520px。
- 支持折叠；折叠后保留 48–54px 恢复入口。
- 宽度和折叠状态按浏览器本地偏好保存，不绑定具体小说。
- 折叠不结束会话、不清空消息、不改变当前 Agent。
- 页面导航、章节跳转和弹窗打开不得重建原生聊天组件。
- 1920×1080 下同时展开章节树与助手时，中央正文区不得小于 760px。
- 当实际可用宽度不足时，优先缩小中央空白边距，其次把章节树折叠为窄栏；不隐藏正文输入区。
- 当前不建设手机版布局；小于桌面验收宽度时可以降级为助手覆盖抽屉，但不作为本阶段验收条件。

### 3.4 助手感知状态条

在原生助手附近增加轻量状态，而不复制其模型、Agent、历史和输入控件：

```text
已感知：第二卷 · 第4章 · 正文
```

状态至少覆盖：

- 已感知当前页面；
- 当前存在未保存修改；
- 已框选 N 字；
- 当前 Agent 不是“AI小说作家”；
- 上下文暂不可用或已过期。

## 4. 统一创作上下文协议

### 4.1 前端协议

新增版本化的 `NovelAssistantContext`，建议结构：

```ts
interface NovelAssistantContext {
  schemaVersion: 1;
  contextRevision: number;
  capturedAt: string;
  novel: { id: string; title: string };
  page: {
    section: "chapters" | "outline" | "roles" | "clues" | "settings";
    view: string;
    modal?: string;
  };
  entity?: {
    type: "document" | "character" | "relationship" | "storyline" | "foreshadow";
    id?: string;
    title?: string;
  };
  document?: {
    id: string;
    volumeId?: string;
    kind: string;
    chapterNumber?: number;
    title: string;
    draftVersion: number;
    savedContentHash: string;
    dirty: boolean;
  };
  editing?: {
    field: string;
    unsavedValue?: string;
    valueTruncated: boolean;
  };
  selection?: {
    id: string;
    field: string;
    text: string;
    start: number;
    end: number;
    before: string;
    after: string;
    sourceContentHash: string;
    requestSessionId?: string;
  };
}
```

### 4.2 上下文分层

上下文分成三层，避免重复发送和混淆正式事实：

1. **定位层**：作品、模块、实体、文档、卷章、当前字段；每轮可以发送。
2. **即时草稿层**：当前聚焦字段的未保存值；只在存在修改且与本轮任务有关时发送。
3. **正式资料层**：由 Agent 调用只读工具从数据库读取，不在每轮请求中复制全书。

### 4.3 内容上限

- 定位层必须保持小且固定。
- 选区正文完整发送，单次上限建议 12,000 字符；超过时要求缩小选区。
- 选区前后文各取最多 1,500 字符。
- 当前未保存字段建议最多 20,000 字符，并显式标记是否截断。
- 完整已保存正文、大纲、人物与设定通过工具按需读取。
- 不把上下文写入浏览器持久存储；只持久保存助手面板宽度和折叠偏好。

### 4.4 生命周期

- 工作台加载完成后发布当前上下文。
- 页面切换、章节跳转、实体选择、字段聚焦、输入变化和选区变化时递增 `contextRevision`。
- 弹窗打开后，弹窗上下文覆盖背景页面；关闭后恢复背景页面。
- 切换作品时先清空旧上下文，再发布新作品上下文。
- 离开小说工作台时立即清空上下文，普通 `/chat` 不得继续携带小说页面信息。
- AI 请求发送时捕获不可变快照，后续页面变化不能修改已发送请求对应的 selection ID。
- 输入过程只更新轻量内存状态；大字段裁剪和 JSON 序列化延迟到真正发送请求时执行，避免每次按键复制整章文本。
- 高频输入更新不得引起原生聊天组件重渲染；助手状态条只订阅标题、dirty、选区字数等轻量派生状态。

## 5. 各模块上下文映射

| 模块/状态 | `page.view` | 当前实体 | 必须提供的即时字段 | 正式资料读取 |
| --- | --- | --- | --- | --- |
| 章节列表 | `chapter-list` | novel/volume | 当前展开卷、章节总数 | 卷章树、字数、状态 |
| 章节正文 | `chapter-editor` | document | 当前正文草稿、字数、dirty、选区 | 当前章节、前文、章纲、事实 |
| 标题弹窗 | `title-editor` | document | 标题输入值、长度、原始标题 | 文档位置、卷章信息 |
| 章纲弹窗 | `chapter-outline-editor` | document | 章纲、目标字数 | 当前正文、前文、人物/设定 |
| 总体大纲 | `novel-outline` | outline document/draft | 当前大纲草稿或聚焦字段 | 大纲正式稿、人物、设定 |
| 人物列表 | `character-list` | character（选中时） | 当前筛选与选中人物 | 全部人物摘要、关系 |
| 人物编辑弹窗 | `character-editor` | character | 类型、姓名、性别、年龄、身份、性格、小传 | 人物正式卡、相关关系/事实 |
| 关系网 | `relationship-graph` | relationship/character | 当前选中节点或边 | 人物、关系及来源证据 |
| 线索页 | `clue-list` | storyline/foreshadow | 当前选中线索和编辑字段 | 故事线、伏笔、章节来源 |
| 设定页 | `novel-settings` | setting document | 当前设定草稿或聚焦字段 | 正式设定、冲突事实 |

## 6. QwenPaw 请求注入与 Agent 链路

### 6.1 前端发送链路

```text
工作台状态/选区
  -> NovelAssistantContextStore
  -> chat.requestPayload.add()
  -> request_context.ai_novel_context（JSON 字符串）
  -> QwenPaw 原生请求
```

采用 JSON 字符串而不是任意深层对象，降低 QwenPaw `request_context` 类型和中间件链对嵌套结构处理差异的风险。

### 6.2 注入条件

只有同时满足以下条件才注入：

- 当前路由是小说工作台；
- 当前存在有效 `novel_id`；
- 上下文 schema 可识别；
- 当前选中 Agent 为 `ai-novel-writer`。

切换到其他 Agent 时保持普通聊天，不自动注入小说上下文；界面提示用户当前 Agent 未启用小说工具。

### 6.3 后端 Middleware

新增窄 Middleware：

1. 读取请求级 `request_context.ai_novel_context`；
2. 校验 JSON、schema、字段长度和 Agent ID；
3. 把定位层和即时草稿层注入本轮临时 system-info；
4. 明确区分“数据库正式资料”和“当前页面未保存草稿”；
5. 提示 Agent 需要正式资料时调用小说只读工具；
6. 请求结束后丢弃页面快照，不写入 Agent 人设文件或长期 Memory。

### 6.4 会话与路由

- 工作台继续依赖 QwenPaw 原生 session。
- QwenPaw 把 `/chat` 规范化为 `/chat/{session_id}` 后，小说工作台与当前上下文必须继续存在。
- 切换章节不创建新会话；同一个会话可以跨章节讨论。
- 新建对话只清空聊天历史，不清空当前页面定位；下一条消息仍注入当前页面。

## 7. 小说上下文工具扩展

### 7.1 新增统一读取工具

新增只读工具：

```text
novel_get_workspace_context
```

建议参数：`novel_id`、`section`、可选的 `document_id`、`entity_type`、`entity_id` 与 `max_chars`。

### 7.2 返回策略

- `chapters`：卷章树、当前章节、章纲、前文范围与故事事实；
- `outline`：大纲草稿/正式文档、目标章数与角色摘要；
- `roles`：当前人物完整卡、其他人物摘要和直接关系；
- `clues`：故事线、伏笔、状态、来源章节和进展；
- `settings`：设定文档与相关正式事实；
- `relationship`：节点、边、关系描述、版本和来源证据。

### 7.3 兼容原则

- 保留现有三个只读工具，不破坏已有 Skill 和历史会话。
- 新工具调用同一领域服务，不复制第二套数据库查询逻辑。
- 所有 `document_id`、`entity_id` 和关系端点必须验证确实属于传入的 `novel_id`。
- 返回内容按当前页面和实体裁剪，不一次返回整本书全部数据。
- 工具只读；页面未保存草稿由请求上下文提供，不伪装成数据库正式事实。

## 8. 选区改写闭环

### 8.1 选区捕获

- `textarea`/`input` 使用 `selectionStart`、`selectionEnd`。
- 支持正文、大纲、章纲、标题、人物身份、性格、小传及其他可编辑多行字段。
- 鼠标选择和键盘选择都要更新上下文。
- 只在选区非空且处于可编辑字段时显示工具条。

### 8.2 浮动工具条

第一版动作：

```text
润色  改写  扩写  缩写  增强对白  检查问题  自定义
```

工具条不得遮住当前选区、右侧滚动条和底部写作操作栏。点击动作后展开右侧助手，并把对应输入建议置于原生输入区附近；用户完成一次发送动作。

### 8.3 结构化修改提案工具

普通聊天回复可能包含解释、Markdown、统计或多个版本，不适合直接解析后覆盖正文。新增一个**不写数据库**的工具：

```text
novel_prepare_selection_edit(
  selection_id,
  operation,
  replacement_text,
  short_summary = ""
)
```

职责：

- 校验 selection ID 的格式、操作类型和返回长度；后端不能声称浏览器中的选区仍然存在；
- 返回结构化提案；
- 不读取或修改浏览器输入框；
- 不直接写 working copy、checkpoint 或 revision；
- 不声称已经修改正文。

选区相关 Skill/Agent 规则要求模型最终调用该工具，而不是只返回一段无法关联选区的普通文字。

### 8.4 原生工具卡片

使用 `chat.toolRender()` 为上述工具结果渲染原生聊天卡片：

- 修改摘要；
- 原选区字数与新文本字数；
- 新文本预览；
- “替换选中文字”；
- “插入到选区后”；
- “复制”；
- “放弃”。

工具卡片仍位于 QwenPaw 原生消息流中，不建设第二套聊天消息列表。

### 8.5 应用规则

- selection ID 对应发送时的不可变选区快照。
- 前端同时校验工具卡片 `sessionId`、字段、原选区文字、起止位置、源内容哈希和当前小说/文档 ID。
- 如果等待 AI 期间正文、章节或人物字段已经变化，旧卡片的替换按钮进入“选区已变化，请重新框选”状态。
- 点击“替换”只改变目标区间；点击“插入”只在目标区间末尾插入。
- 应用后进入现有未保存状态，触发现有自动保存逻辑。
- 保留一次可撤销记录；不得直接调用数据库写接口绕过编辑器状态。
- 关闭页面、切换作品或销毁编辑字段时，使相关 selection ID 失效。

### 8.6 键盘与可访问性

- 助手宽度拖拽柄使用 `role="separator"`，支持左右方向键微调宽度，并有清晰可见的焦点态。
- 助手折叠、展开和选区操作按钮必须具有中文 `aria-label`。
- 选区工具条支持 Tab 导航与 Escape 关闭；关闭工具条不得清空正文选区。
- 工具卡片的“替换”“插入”“复制”“放弃”必须可以只用键盘完成。
- 打开助手或工具条时不得抢走正文输入焦点；只有作者主动进入助手输入区时才切换焦点。

## 9. 分阶段施工顺序

### 阶段 0：Git 基线与公开契约尖峰

工作内容：

1. 提交当前章节树、关系网和 UI 修复的既有工作，建立独立基线。
2. 保存 1920×1080 与 2K 的章节、人物和大纲截图。
3. 补充新的 ADR，明确作者点击应用结构化选区提案的边界。
4. 在最小实验代码中验证：
   - `Inner` 可以在固定宽度右栏持续渲染；
   - `chat.requestPayload.add()` 的字段能到达后端 Middleware；
   - Middleware 注入信息能被 `ai-novel-writer` 本轮读取；
   - `chat.toolRender()` 能读取结构化工具结果并调用插件前端动作；
   - `chat.sender.addSuggestion()` 是否支持运行时更新和清理；
   - `/chat/{session_id}` 路由规范化后 wrapper 与上下文仍在；
   - Agent 和 Session 的公开 hook/命令式 getter 与文档一致。

退出条件：全部公开契约有真实浏览器证据；任一关键接口不成立时先更新本计划，不进入正式施工。

### 阶段 1：恢复原生助手与三栏布局

- 补全 QwenPaw 前端窄类型；
- `route.wrap` 同时渲染工作台和原生 `Inner`；
- 实现右侧助手折叠、恢复、拖动宽度和本地偏好；
- 完成章节正文、大纲、人物、线索和设定页面的桌面布局；
- 普通 `/chat` 非回归。

退出条件：1920×1080 与 2K 下原生助手完整可用，工作台无横向溢出和不可达操作。

### 阶段 2：统一上下文 Store 与模块适配器

- 建立 `NovelAssistantContextStore`；
- 实现上下文 schema、裁剪、生命周期和单元测试；
- 依次接入章节正文、标题、章纲、大纲、人物、关系、线索与设定；
- 实现助手感知状态条。

退出条件：每次页面、实体、弹窗和字段切换都得到正确上下文，不残留旧作品内容。

### 阶段 3：请求注入与 Middleware

- 注册 `chat.requestPayload` 转换；
- 注册 QwenPaw 请求 Middleware；
- 仅对小说工作台和 `ai-novel-writer` 注入；
- 实现长度、schema 和过期检查；
- 增加前后端集成测试。

退出条件：用户不复制 ID，询问“我当前在编辑什么”即可获得准确回答；普通聊天和其他 Agent 不受影响。

### 阶段 4：统一小说资料读取工具

- 新增 `novel_get_workspace_context`；
- 复用现有领域服务；
- 补齐大纲、人物、关系、故事线、伏笔和设定读取；
- 更新安装/升级配置脚本，在 `ai-novel-writer` 中显式启用新工具，并保证 Default、QA 等其他 Agent 保持关闭；
- 更新 `AI_NOVEL_WORLD.md` 和相关 Skills 的工具选择规则；
- 保持现有工具兼容。

退出条件：助手能按当前模块读取真实正式资料，并明确区分未保存草稿与数据库事实。

### 阶段 5：选区捕获与发送体验

- 建立 selection registry；
- 接入正文及全部允许编辑的文本字段；
- 实现浮动操作条；
- 实现输入建议、助手展开和过期状态；
- 覆盖鼠标与键盘选区。

退出条件：任一支持字段框选后都能创建准确、可追踪的 selection ID 并发起请求。

### 阶段 6：结构化提案与局部应用

- 注册 `novel_prepare_selection_edit` 工具；
- 在 `ai-novel-writer` 中显式启用该工具，并验证插件重装/升级后配置幂等；
- 注册原生 tool renderer；
- 实现替换、插入、复制和放弃；
- 接入现有草稿状态、自动保存、冲突提示与撤销；
- 更新选区相关 Skill 规则。

退出条件：AI 只能通过结构化卡片影响选区，点击后只改变目标范围，自动保存和撤销正常。

### 阶段 7：全面回归、证据与提交

- 使用当前 `ai-novel-writer` 有效模型进行真实对话验收；历史专项若要求 MiniMax-M3，则验收前由用户在 QwenPaw 中选择 MiniMax-M3；
- 在不同题材的真实作品中验证正文、章纲、人物、设定和线索；
- 保存参考状态与实现截图；
- 完成 TypeScript、单元、后端、构建、Docker 健康和浏览器控制台检查；
- 按阶段提交 Git，不把无关用户改动混入提交。

退出条件：本文第 11 节全部验收项通过，无未解释的 P0/P1 问题。

## 10. 预计代码落点

### 10.1 前端

| 文件 | 预计修改 |
| --- | --- |
| `frontend/src/index.ts` | 原生 Inner 布局、聊天扩展注册和生命周期 |
| `frontend/src/qwenpaw-host.d.ts` | Agent、Session、requestPayload、sender、actions、toolRender 窄类型 |
| `frontend/src/styles.ts` | 三栏、助手折叠/拖动、状态条、选区工具条和工具卡片 |
| `frontend/src/workbench-v2.ts` | 页面/实体/文档上下文发布、选区接入 |
| `frontend/src/chapter-workflow.ts` | 章纲上下文与选区接入 |
| `frontend/src/workbench-studio.ts` | 人物、线索、设定相关适配 |
| `frontend/src/relationship-editor.ts` | 人物关系上下文 |
| `frontend/src/assistant-pane.ts` | 右侧助手外壳和宽度状态（新增） |
| `frontend/src/assistant-context.ts` | 上下文协议、store、裁剪和序列化（新增） |
| `frontend/src/assistant-selection.ts` | selection registry 与局部应用（新增） |
| `frontend/src/assistant-tool-card.ts` | 结构化选区提案渲染（新增） |

### 10.2 后端与 Agent

| 文件 | 预计修改 |
| --- | --- |
| `plugin.py` | 注册 Middleware、统一上下文工具和选区提案工具 |
| `backend/assistant_context.py` | 请求上下文校验与 Middleware（新增） |
| `backend/tools.py` | `novel_get_workspace_context` 与 `novel_prepare_selection_edit` |
| `backend/services.py` / `backend/creative_services.py` | 统一读取正式资料的领域服务 |
| `qwenpaw-agent/AI_NOVEL_WORLD.md` | 当前页面语义、未保存草稿边界和选区工具路由 |
| `skills/*` | 各创作 Skill 的上下文和选区提案规则 |
| `scripts/configure_qwenpaw_novel_agent.py` | 新工具只在 `ai-novel-writer` 中启用，升级时保持幂等 |
| `scripts/verify_qwenpaw_lab.py` | 新 Middleware、工具作用域和卸载残留验证 |

### 10.3 测试

- `frontend/src/assistant-context.test.ts`
- `frontend/src/assistant-selection.test.ts`
- QwenPaw 请求转换契约测试
- Middleware 单元/集成测试
- 统一工作区上下文领域测试
- 选区提案工具测试
- 真实浏览器桌面验收证据

## 11. 验收矩阵

### 11.1 UI 与原生聊天

- [ ] 1920×1080 下章节树、正文、助手同时展开可用。
- [ ] 2K 下三栏比例正确，无巨大浪费空间。
- [ ] 助手可折叠、恢复、拖动，刷新后保留偏好。
- [ ] 原生 Agent、模型、历史、输入、附件、工具调用和停止功能完整。
- [ ] 普通 `/chat` 页面未出现小说外壳。
- [ ] `/chat/{session_id}` 导航后工作台与助手不消失。
- [ ] 拖拽柄、折叠按钮、选区工具条和工具卡片可以只用键盘操作。
- [ ] 打开助手、出现选区工具条时正文焦点不会被意外抢走。

### 11.2 页面感知

- [ ] 章节正文：准确回答作品、卷、章节、标题和 dirty 状态。
- [ ] 标题弹窗：感知尚未保存的新标题。
- [ ] 章纲弹窗：感知章纲和目标字数。
- [ ] 总体大纲：感知当前大纲字段和正式资料。
- [ ] 人物卡：感知姓名、性别、年龄、身份、性格和小传。
- [ ] 关系网：感知选中人物或关系边。
- [ ] 线索/伏笔：感知选中对象、状态和来源章节。
- [ ] 设定：感知当前设定草稿与正式规则。
- [ ] 切换页面、章节和作品后没有旧上下文残留。

### 11.3 选区改写

- [ ] 鼠标和键盘选区都可触发工具条。
- [ ] 单句、多段、含换行和长选区均可处理。
- [ ] AI 返回结构化工具卡片，不依赖解析普通回复。
- [ ] “替换”只改变选区；“插入”只在选区后增加内容。
- [ ] 应用后自动保存继续工作。
- [ ] 应用后可以撤销。
- [ ] 等待 AI 时正文变化会使旧卡片失效。
- [ ] 切换章节、字段、人物或作品后旧卡片不能错误应用。
- [ ] 切换 QwenPaw 会话后，旧会话的工具卡片不能应用到新会话选区。

### 11.4 上下文质量

- [ ] 助手能区分“正式已保存事实”与“当前未保存草稿”。
- [ ] 助手能按需调用统一上下文工具，而不是要求用户复制 ID。
- [ ] 助手不会把当前人物卡误认为上一人物。
- [ ] 助手不会把当前章节选区应用到另一章节。
- [ ] 长会话跨章节时仍以最新页面上下文为“当前”。

### 11.5 工程质量

- [ ] TypeScript 检查通过。
- [ ] 前端单元测试通过。
- [ ] 后端单元和集成测试通过。
- [ ] Vite 生产构建通过。
- [ ] Docker 容器健康。
- [ ] 浏览器控制台无新增 error/warn。
- [ ] 连续输入长章节时无明显按键延迟，原生聊天不随每次按键重渲染。
- [ ] `git diff --check` 通过。
- [ ] 每个阶段有独立提交和可恢复证据。

## 12. 风险、回退与降级

| 风险 | 预防/验证 | 回退 |
| --- | --- | --- |
| 原生 `Inner` 在窄栏布局异常 | 阶段 0 真实浏览器尖峰 | 助手改为覆盖抽屉或普通 `/chat` 跳转 |
| requestPayload 字段未到达 Middleware | 阶段 0 最小回显工具验证 | 暂时把定位信息转成用户可见的输入建议，不使用私有接口 |
| Middleware 注入方式不稳定 | 单次会话新旧消息对照 | 退回显式上下文工具调用和可见上下文提示 |
| sender suggestion 不能动态更新 | 阶段 0 验证注册/清理 | 右侧状态条展示可复制指令，保留用户发送 |
| toolRender 无法关联浏览器 selection | selection ID + session + contextRevision 尖峰 | 工具卡片只提供复制，不启用替换 |
| 等待 AI 期间内容变化 | 哈希、字段、文档和 selection ID 校验 | 旧卡片失效，要求重新框选 |
| 页面上下文过大 | 分层、上限和工具按需读取 | 只保留定位与选区，完整资料全部走工具 |
| 切换 Agent 后错误注入 | selectedAgent 条件与状态条 | 其他 Agent 完全不注入 |
| QwenPaw 升级破坏扩展点 | 升级前重跑阶段 0 契约测试 | 禁用聊天扩展注册，工作台与数据层继续可用 |

## 13. Git 提交建议

1. `docs: plan qwenpaw assistant context integration`
2. `test: verify qwenpaw chat extension contracts`
3. `feat: restore native qwenpaw assistant pane`
4. `feat: add novel workbench context protocol`
5. `feat: inject page context into novel agent`
6. `feat: add unified novel workspace context tool`
7. `feat: add selected text proposal workflow`
8. `test: verify assistant-aware novel workbench`

## 14. 自查审核记录

### 14.1 第一轮：事实与公开接口核查

结论：**通过，但阶段 0 契约尖峰不可省略。**

已核对：

- 当前代码确实没有在工作台模式渲染原生 `Inner`；
- ADR-0001 已批准 `route.wrap` + 原生聊天同屏；
- QwenPaw 2.1.0 当前文档包含 requestPayload、sender suggestion、actions 和 toolRender；
- 当前项目的前端类型声明缺少上述接口；
- 当前小说工具只读且不能自动感知浏览器页面；
- 当前 `novel_get_context` 没有覆盖所有结构化创作资料；
- 当前没有公开命令式自动发送证据，因此计划保留一次用户发送；
- 普通 AI 回复不适合直接解析为选区替换，已改为结构化工具提案与 toolRender 卡片。

### 14.2 第二轮：阶段依赖与查漏补缺

结论：**通过。正式施工依赖顺序明确，无功能阶段倒置。**

本轮补充的遗漏：

1. 增加新的 ADR 任务，解决旧“不写回”边界与当前授权之间的冲突。
2. 把 QwenPaw 公开扩展点验证提前到阶段 0，避免完成 UI 后才发现接口不可用。
3. 增加 Session 路由从 `/chat` 规范化到 `/chat/{session_id}` 的回归。
4. 增加当前 Agent 不是 `ai-novel-writer` 时的可见状态和不注入规则。
5. 增加弹窗上下文覆盖与关闭后恢复，避免标题/人物弹窗仍使用背景页面。
6. 增加选区等待期间正文变化、章节切换和作品切换的失效处理。
7. 增加选区工具结构化提案，避免解析带解释的普通模型回复。
8. 增加未保存内容截断标记，防止助手误以为拿到了完整草稿。
9. 增加关系网、故事线、伏笔和设定的上下文映射，不只覆盖正文和人物卡。
10. 增加助手宽度/折叠偏好与小说内容分离的持久化边界。
11. 增加真实模型跟随 `ai-novel-writer` 有效模型的要求，避免与模型切换计划冲突；MiniMax-M3 只在指定专项验收中手动选择。
12. 增加插件升级和公开扩展点失效时的降级路径。
13. 增加新工具在 `ai-novel-writer` 中的显式启用和其他 Agent 关闭验证。
14. 明确后端只校验 selection ID 格式，选区存在性、会话和内容一致性由浏览器端负责。
15. 增加助手拖拽、选区工具条和工具卡片的键盘可访问性验收。
16. 增加高频输入时不序列化整章、不重渲染原生聊天的性能约束。

### 14.3 最终审核结论

本文已具备施工使用所需的目标、边界、依赖、数据协议、UI规则、代码落点、分阶段退出条件、验收矩阵和回退方案。

开始功能编码前只剩两个前置动作：

1. 提交当前 Git 基线；
2. 完成阶段 0 的公开契约尖峰并记录真实浏览器证据。

在这两个动作完成前，不应直接进入大范围 UI 与上下文编码。
