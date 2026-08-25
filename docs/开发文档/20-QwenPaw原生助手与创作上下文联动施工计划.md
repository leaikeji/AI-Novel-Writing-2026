# QwenPaw 原生助手与创作上下文联动施工计划 V2

状态：**✅ A0A–A7 已于 2026-08-25 全部完成，A7-G 技术与产品门禁通过。当前候选已经真实通过 MiniMax-M3、桌面双分辨率、完整数据库、安装/卸载、性能、无障碍和隔离验收；本轮 Git 暂存、提交与推送尚未获得新的独立授权，因此不写成已完成。**

制定日期：2026-08-25（Asia/Shanghai）

V2 最近复查：2026-08-25（Asia/Shanghai）

目标环境：QwenPaw 2.1.0 内的 AI小说世界2026 PawApp；桌面端验收分辨率为 1920×1080 与 2560×1440，当前不验收手机版。

关联文档：

- [项目开工计划](./00-项目开工计划.md)
- [总体架构与核心流程](./06-总体架构与核心流程.md)
- [QwenPaw 原生 UI 盘点与小说工作台 UI 基线](./12-QwenPaw原生UI盘点与小说工作台UI基线.md)
- [ADR-0001：QwenPaw 原生聊天组合与小说 Agent 作用域](./ADR/ADR-0001-QwenPaw原生聊天组合与小说Agent作用域.md)
- [跟随“AI 小说作家”Agent 模型切换开发计划](./19-跟随AI小说作家Agent模型切换开发计划.md)
- [V1 审核报告](./证据/助手计划审核-2026-08-25/审核报告.md)
- [V2 验证证据](./证据/助手计划V2验证-2026-08-25/)
- [A7-G 最终验收记录](./证据/助手计划V2验证-2026-08-25/A7-GATE.md)

## 0. V2 验证结论

### 0.0 Codex 并行施工索引

本计划使用下表中的 A0A–A7 本地工作包组织施工。A0A–A7 已全部完成并由主 Codex 串行汇合；这些编号只属于本文：

| 阶段 | 可并行工作包 | 串行/汇合点 |
| --- | --- | --- |
| 0A | A0A-4A…E：各模块与原生聊天双分辨率证据 | A0A-2 已完成；A0A-3 Git/文件边界、A0A-G |
| 0B | A0B-2…8：窄 Inner、Hook/Middleware、renderer、suggestion、留存和清理尖峰 | A0B-1 窄类型、同一宿主状态互斥、A0B-G |
| 0C | A0C-1…6：路由状态、两个 Adapter、选区、registry 和工具轨实验 | 共享工作台根文件接线与 A0C-G |
| 0D | 实验结果、协议草案和降级证据可并行汇总 | ADR、四项协议和七个 P0 由 A0D-G 串行冻结 |
| 1–7 | A1–A7：布局、上下文、注入、工具、选区、提案和各测试层 | ✅ A1-G…A7-G 均已通过；见最终验收记录 |

任何助手子代理必须遵守本文各阶段声明的共享文件 owner。模型跟随计划已经闭环，助手任务只能消费其公开 effective-model 契约，不得重新引入固定模型、第二套模型选择或擅自修改该计划语义；若确需触碰其共享文件，必须暂停冲突工作包并由主 Codex 串行协调。

### 0.1 总结

产品目标和总体架构继续保留：使用 QwenPaw 原生聊天、按需读取正式小说资料、感知当前页面草稿、对选区返回结构化提案，并由作者点击后应用。

V1 不能直接施工的 7 个 P0 已由 A0A–A0D 的真实运行实验、保守降级和 ADR-0003 全部解除；A1–A7 随后完成正式实现与逐门验收。原生助手、页面上下文、正式资料工具、全字段选区、结构化提案、显式应用/撤销和三题材真实模型闭环均已有可复核证据。

施工批准状态：

- 阶段 0A–0D：✅ 已完成并通过门禁。
- 阶段 1–6：✅ 已完成并分别通过 A1-G…A6-G。
- 阶段 7：✅ 八轨验收完成，A7-G 技术与产品门禁通过。
- Git 发布：⏳ 当前证据与恢复点齐全，但未获本轮独立暂存/提交/推送授权。

### 0.2 当前工程基线

- Git HEAD 与 origin/main 均为 a4007ab；模型跟随施工提交为 0245bd1，专项文档内并行治理提交为 a4007ab。A1–A7 当前实现仍是未提交工作区候选，不冒充已发布提交。
- 模型跟随计划已经完成提交、数据库单向迁移、PawApp 重新安装和真实运行验证；本计划不得再把它写成未提交阻塞项。
- 当前本地源码验证：前端 33 个测试文件、231 项测试通过；TypeScript 检查与 Vite 构建通过。
- 当前构建产物 `frontend/dist/index.js` 为 1,912.99kB，gzip 700.09kB；相对冻结基线 660.67kB 增加 39.42kB，低于 40kB 门槛。
- 明确隔离 PostgreSQL 测试库的后端全量门禁为 216 passed、0 skipped；正式安装脚本的默认条件门禁为 195 passed、21 skipped，跳过项未计作通过。
- QwenPaw 与 PostgreSQL 容器均处于 healthy。
- 已安装 PawApp 健康接口返回 generation_model_policy=follow-agent-effective、model_verification_mode=preflight-effective+provider-usage；verify_qwenpaw_lab.py 通过。
- 本轮 verify 读取到 ai-novel-writer 当前 effective 模型为 minimax-cn / MiniMax-M3。该值是运行态证据，不是本计划新增的模型固定要求。
- 当前目标 Agent 启用 6 个小说 Skills 和 5 个小说工具：保留 3 个既有只读工具，并新增统一工作台资料读取与结构化选区提案工具；Default、QA Agent 均未启用。
- 结论：A1–A7 候选已经完成技术、产品与真实运行验收；当前只剩必须由用户另行授权的 Git 发布动作。

### 0.3 已核实的 QwenPaw 契约

QwenPaw 2.1.0 当前公开或源代码可核实的能力包括：

- route.wrap 可以保留并包装 core.chat 的原生 Inner。
- useSelectedAgent、getSelectedAgentId、useCurrentSession、getCurrentSessionId 可读取 Agent 与 Session。
- chat.sender.addSuggestion 可增加输入建议。
- chat.requestPayload.add 可在发送前修改 request_context。
- chat.toolRender 可读取 result、sessionId、messageId 并渲染工具卡片。
- `PluginApi.register_runtime_hook` 可注册 Hook，但真实 `/api/console/chat` 链路执行次数为 0，因此不接生产。
- `PluginApi.register_middleware(factory, priority=80)` 在真实链路执行，并能给目标 MiniMax-M3 当轮注入唯一标记；生产注入冻结为该公开 Middleware。

重要限制：

- QwenPaw Runtime 虽把动态注入描述为 system hint，但当前实现实际创建 Msg(name="system", role="user")。
- 因此小说正文和页面草稿必须被视为“待分析的数据”，不能被描述为不可覆盖的系统指令。
- A0B 双标记已经证明：注入后的 role=user 页面数据消息进入公开会话历史并在重启后保留；原始 marker 未出现在该公开历史，普通会话和普通日志均无两标记命中。结果冻结为工作台会话披露 + 短期内存 `context_ref`，不声称零留存。
- 当前没有公开的命令式 sendMessage/prefill 证据；固定选区动作点击时复制完整命令并展开原生助手，用户粘贴后点击原生发送按钮。不得用私有 DOM/store 模拟发送。

### 0.4 阶段 0 UI 基线证据

以下截图保留的是施工前基线与当时发现的问题，不代表 A7 最终页面；最终双分辨率、模块三栏、IDE 审阅器和缩放证据见 [A7-G](./证据/助手计划V2验证-2026-08-25/A7-GATE.md)。

#### 章节页 1920×1080

![章节页 1920×1080](./证据/助手计划V2验证-2026-08-25/02-editor-1920x1080.png)

基线结论：右侧可以容纳助手，但当时固定在视口右侧的审稿、情报和章节导航按钮会与助手冲突；A1 已将其迁入编辑器工具轨并由 A7 复验。

#### 章节页 2560×1440

![章节页 2560×1440](./证据/助手计划V2验证-2026-08-25/03-editor-2560x1440.png)

基线结论：2K 下右侧存在明显可用空间，常驻助手具有明确价值；最终空间利用已通过 A7-T2。

#### 角色页 1920×1080

![角色页 1920×1080](./证据/助手计划V2验证-2026-08-25/04-roles-1920x1080.png)

基线结论：当时 320px 书籍栏 + 880px 主区是固定网格；A1 已把章节、大纲、角色、线索和设定统一改为弹性布局。

#### QwenPaw 原生聊天补充证据（实际输出 1280×720）

![QwenPaw 原生聊天](./证据/助手计划V2验证-2026-08-25/05-native-chat-1920x1080.png)

基线结论：该文件名沿用了 1920×1080 采集任务名称，但实际图像是 1280×720，不能计入正式桌面分辨率验收。后续已补拍精确 1920×1080、2560×1440，并完成 320–520px 面板可用性验证。

证据边界：截图只能证明布局、空白和可见冲突，不能证明键盘、屏幕阅读器、请求留存、真实模型调用和长期性能。

## 1. 目标与批准范围

完成后必须满足：

1. 小说工作台右侧使用 QwenPaw 原生 Inner，不复制第二套聊天界面。
2. 助手知道当前作品、模块、卷、章节、文档、人物、关系、线索或设定对象。
3. 助手可以按需读取数据库正式资料，也可以在当前请求中感知相关的未保存表单草稿。
4. 作者框选标题、大纲、章纲、正文、人物卡、线索或设定字段后，可以要求助手只处理该选区。
5. AI 返回版本化结构提案；只有工具卡片中的作者操作可以直接应用到页面草稿。
6. 应用行为尊重各字段原有保存策略：正文继续自动保存，显式保存表单仍由作者点击原保存按钮。
7. 每次 AI 应用形成独立、可见、可撤销的一步事务，不依赖未经验证的浏览器原生 undo。
8. 章节树、中央工作区和右侧助手在 1920×1080 与 2560×1440 下同时可用。
9. 普通聊天和其他 Agent 不携带小说页面上下文，也不能调用本计划新增的小说工具。

### 1.1 对旧边界的更新

ADR-0001 的历史决策保留。新 ADR 将在阶段 0 实验结束后记录以下新边界：

- 模型可以生成结构化局部修改提案。
- 模型或后端工具不能直接覆盖浏览器字段或数据库权威正文。
- 作者点击工具卡片后，前端通过已注册字段适配器修改页面草稿。
- “直接应用”必须经结构化工具卡片；普通聊天文本仍可以提供建议和可复制内容，但不能被自动解析后写回。
- 标题、章纲、人物卡、线索和设定应用后仍保持 dirty，必须走各自既有保存按钮。
- 正文应用后复用正文恢复草稿、版本冲突和延迟自动保存链路。

### 1.2 非目标

- 不复制、替换或 fork QwenPaw 原生聊天组件。
- 不读取 QwenPaw 私有 Router、私有聊天 store 或私有输入框。
- 不建立第二套 Agent Runtime、会话、模型或 Provider 设置。
- 不让 AI 无确认地覆盖整章、正式 revision 或结构化权威数据。
- 不在本阶段建设多人协作、手机版、语音、TTS 或富文本编辑器。
- 不把整本小说正文无差别注入每轮请求。
- 不承诺第一版选区动作可以绕过用户发送。
- 不承诺 textarea 工具条一定精确贴近选中文字；其位置由阶段 0 几何实验决定。

## 2. 七个 P0 的强制解决方案

| P0 | 当前状态 | V2 决策 | 解除门槛 |
| --- | --- | --- | --- |
| P0-1 上下文协议不完整 | ✅ A0D-2 已解除 | 稳定枚举、完整实体类型、多字段 `editing.fields`、24,000 字符全局预算与三层来源已冻结 | A2 落实代码类型并覆盖章节、角色、线索、设定和弹窗 |
| P0-2 注入机制未定 | ✅ A0B/A0D-1 已解除 | 真实 Hook 不执行；生产使用公开 Middleware(priority=80) | A3 实现 context_ref 后复跑目标/非目标 Agent 隔离 |
| P0-3 缺受控字段适配器 | ✅ A0C/A0D-3 已解除 | 所有读取、选区和写回都走 `EditableFieldAdapter` | A2 完成八类页面接线 |
| P0-4 保存/撤销语义错误 | ✅ A0C/A0D-3 已解除 | autosave/explicit-save 分离，完整哈希冲突与独立 `AIEditTransaction` | A2/A6 完成页面级自动保存、dirty 和显式撤销 |
| P0-5 路由生命周期矛盾 | ✅ A0C/A0D-1 已解除；2026-08-25 缺陷回归修订 | 唯一四态状态机；同一运行期有效 owner 内允许原生新会话转换，fresh/direct `/chat` 仍清理旧 owner | A1/A3 保持真实路由非回归 |
| P0-6 页面草稿留存不明 | ✅ A0B/A0D-1 已解除 | 结果 C：历史披露 + 工作台会话绑定 + 短期内存 `context_ref` 减少原始载荷暴露 | A3 实现 5 分钟 ref、绑定、限流与清理 |
| P0-7 模型计划依赖未闭环 | ✅ 已解除 | 0245bd1 已完成提交、迁移、安装；当前运行策略和 verify 一致 | 已满足，不再阻断 A0A；后续只消费 effective-model 契约 |

七个 P0 均已解除；阶段 1–7 可以施工，但仍必须通过各自功能门禁。

## 3. 桌面体验与布局规则

### 3.1 章节正文

目标网格：

    QwenPaw 宿主侧栏
      └─ 小说工作台
           ├─ 章节树：270px，折叠为 54px
           ├─ 中央编辑器：minmax(760px, 1fr)
           └─ 原生助手：默认 380px，可调 320–520px

规则：

- 助手宽度必须按实际可用空间动态夹紧，不能机械保证 520px。
- 1920×1080 下空间不足时，依次减少页面空白、压缩非正文模块主区、折叠章节树或书籍栏。
- 不允许为了助手隐藏正文输入区或核心保存按钮。
- 当前 anw-editor-side-tools 不再固定到视口 right:40px；迁入中央编辑器自身工具轨。
- 右侧助手折叠后保留 48–54px 恢复入口。
- 折叠不销毁 Inner、不清空会话、不改变 Agent。
- 页面、章节和弹窗切换不得重建 Inner。
- 宽度偏好只保存数值和折叠状态，不保存小说内容。

### 3.2 大纲、角色、线索和设定

当前 mb-workbench 的固定 320px + 880px 改为弹性三列：

    书籍栏：clamp(260px, 19vw, 320px)
    模块主区：minmax(640px, 1fr)
    原生助手：clamp(320px, 用户偏好, 动态最大值)

在 1920×1080 下若 520px 助手导致主区低于 640px，必须自动夹紧助手宽度或折叠书籍栏，不能产生横向溢出。

### 3.3 助手状态条

状态条只显示轻量派生信息：

- 当前作品、模块、实体或章节。
- 正在感知的字段数量。
- 是否存在未保存草稿。
- 是否存在选区及选区字数。
- 内容是否被截断。
- 当前 Agent 是否受支持。
- 上下文是否过期、失效或等待重新捕获。

状态条不得复制原生 Agent、模型、历史、输入、附件和停止控件。

## 4. 页面上下文协议 V2

本节已由 A0D-2 与 ADR-0003 冻结；实现阶段只能逐字段落实，不能另建第二份 schema 或重新解释数据角色。

### 4.1 稳定类型

    type NovelPageSection =
      | "chapters"
      | "outline"
      | "roles"
      | "clues"
      | "settings";

    type NovelPageView =
      | "chapter-list"
      | "chapter-editor"
      | "title-editor"
      | "chapter-outline-editor"
      | "novel-outline"
      | "character-list"
      | "character-editor"
      | "relationship-graph"
      | "relationship-editor"
      | "clue-list"
      | "storyline-editor"
      | "foreshadow-editor"
      | "novel-settings";

    type NovelEntityType =
      | "novel"
      | "volume"
      | "document"
      | "outline"
      | "character"
      | "relationship"
      | "storyline"
      | "foreshadow"
      | "setting";

### 4.2 协议结构

    interface EditableFieldSnapshot {
      id: string;
      label: string;
      value: string;
      dirty: boolean;
      truncated: boolean;
      characterCount: number;
      persistence: "autosave" | "explicit-save";
    }

    interface NovelAssistantContextV2 {
      schemaVersion: 2;
      contextRevision: number;
      capturedAt: string;
      expiresAt: string;
      agentId: string;
      sessionId?: string;
      novel: { id: string; title: string };
      page: {
        section: NovelPageSection;
        view: NovelPageView;
        modal?: NovelPageView;
      };
      entity?: {
        type: NovelEntityType;
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
        focusedFieldId?: string;
        fields: EditableFieldSnapshot[];
      };
      selection?: {
        id: string;
        fieldId: string;
        text: string;
        startUtf16: number;
        endUtf16: number;
        direction: "forward" | "backward" | "none";
        before: string;
        after: string;
        sourceValueSha256: string;
        contextRevision: number;
        createdAt: string;
        expiresAt: string;
      };
      budget: {
        maxCharacters: number;
        usedCharacters: number;
        truncated: boolean;
        omittedFieldIds: string[];
      };
    }

page.view、field id 和 entity type 必须来自代码常量；显示文案与稳定 id 分离。

### 4.3 三层上下文

1. 定位层：作品、页面、实体、文档、字段 id。
2. 即时草稿层：相关 dirty 字段和选区；明确标注为未保存草稿。
3. 正式资料层：通过只读工具按需从数据库读取，并标记来源与时间。

### 4.4 总预算、优先级与去重

- 单轮页面上下文总上限冻结为 24,000 字符。
- schema、作品、页面、实体、文档和字段 id 属于强制定位信封，先预留并且不得被正文挤掉。
- 剩余预算优先级：选区 > 选区前后文 > 当前聚焦 dirty 字段 > 其他 dirty 字段。
- 选区最多 12,000 字符；超过时阻止发送并要求缩小范围。
- 前后文各最多 1,500 字符。
- 未保存字段使用剩余预算，不再拥有独立 20,000 字符额度。
- selection.text 已包含在字段 value 中时不得重复发送同一片段。
- 每个截断字段和整体预算都必须显式标记。
- 字段变化后 400ms 静默期，或作者明确触发选区动作/刷新上下文时，构造不可变快照并创建短期 ref；输入过程中不复制整章、不在每次按键序列化完整 JSON。

### 4.5 模块映射

| 页面 | 实体 | 即时字段 | 保存策略 |
| --- | --- | --- | --- |
| 章节列表 | novel/volume | 展开卷、选中章节 | 无写回 |
| 章节正文 | document | 正文、标题状态、选区 | 正文 autosave |
| 标题弹窗 | document | title | explicit-save |
| 章纲弹窗 | document | outlineText、targetCharacters | explicit-save |
| 总体大纲 | outline/document | 当前步骤全部字段、聚焦字段 | explicit-save |
| 人物弹窗 | character | 类型、姓名、性别、年龄、身份、性格、小传 | explicit-save |
| 关系网 | relationship/character | 当前节点或边 | explicit-save |
| 故事线/伏笔 | storyline/foreshadow | 当前表单全部字段 | explicit-save |
| 设定 | setting | 模板、分类、思路和动态设定字段 | explicit-save |

### 4.6 Store 生命周期

- 进入工作台后先发布定位信封，再注册当前页面字段。
- 页面、作品、实体、文档、弹窗、聚焦字段、dirty 状态或选区变化时递增 contextRevision。
- 输入时只保存字段 getter、dirty 和轻量计数，不在 store 中复制整章快照。
- 弹窗上下文覆盖背景页；关闭时销毁弹窗 Adapter 并恢复背景页。
- 切换作品前先销毁旧 Adapter、selection、proposal 和事务，再发布新作品。
- 真正发送时从 Adapter getter 构造不可变快照；之后的页面变化不能修改已发送快照。
- Inner 只订阅助手开关和会话自身状态；正文输入不得触发 Inner 重渲染。

## 5. 字段适配、保存与撤销

本节已由 A0D-3 与 ADR-0003 冻结。A0C 证明接口可行；A2/A6 仍须完成真实页面接线和事务 UI。

### 5.1 EditableFieldAdapter

    interface EditableFieldAdapter {
      id: string;
      label: string;
      getValue(): string;
      applyValue(nextValue: string, meta: AIApplyMeta): void | Promise<void>;
      getSelection(): SelectionSnapshot | null;
      restoreSelection?(range: SelectionRange): void;
      focus(): void;
      getDirty(): boolean;
      persistence: "autosave" | "explicit-save";
      undoPolicy: "ai-transaction";
      dispose(): void;
    }

禁止通过 querySelector 后直接设置 DOM value 完成写回。

### 5.2 逐字段应用规则

| 字段 | 应用提案后 | 保存 | 状态文案 |
| --- | --- | --- | --- |
| 正文 | 调用统一 applyEditorContent，更新 React state、ref 与恢复草稿 | 复用 600ms 自动保存 | 已应用，正在自动保存 |
| 标题 | 更新 titleDraft | 作者点击“保存” | 已应用到标题草稿，尚未保存 |
| 章纲 | 更新 briefForm | 作者点击“保存章纲” | 已应用到章纲草稿，尚未保存 |
| 人物/线索/设定 | 更新对应 form state 并标记 dirty | 作者点击原保存按钮 | 已应用到表单，尚未保存 |

### 5.3 AIEditTransaction

每次直接应用建立一条前端内存事务：

- transactionId。
- agentId、sessionId、selectionId。
- novelId、documentId、fieldId。
- beforeValue、afterValue。
- beforeSelection、afterSelection。
- sourceValueSha256。
- appliedAt。
- persistence 状态。

每个字段至少保留最近一次 AI 事务并显示“撤销 AI 修改”。撤销仍通过字段适配器执行；正文撤销后重新进入自动保存，显式保存表单撤销后保持 dirty。

页面卸载后不承诺跨页面撤销；这必须在 UI 文案中明确。

## 6. 请求注入、数据边界与会话状态

### 6.1 候选发送链路

    Page Context Store
      -> 400ms 静默期或显式刷新时构造不可变快照
      -> POST /api/ai-novel-world-2026/assistant-contexts
      -> 短期内存 context_ref
      -> chat.requestPayload.add
      -> request_context.context_ref
      -> QwenPaw AgentRequest
      -> PluginApi.register_middleware(priority=80)
      -> Msg(name="system", role="user") 页面数据消息
      -> 当前 Agent 本轮执行

### 6.2 注入机制决策

A0B 已真实比较并由 A0D-1 冻结：

1. PRE_EXECUTE runtime hook 注册成功但真实控制台链路执行次数为 0，不接生产。
2. AgentScope Middleware 在同一链路执行，MiniMax-M3 能读取唯一标记；生产只注册该公开 Middleware。
3. 前端已验证 requestPayload 转换器是同步契约，因此 context_ref 必须在发送前异步准备；发送时没有匹配 ready ref 就跳过页面上下文并显示状态，不能阻断原生消息。

注入内容必须采用结构化包裹并包含以下语义：

- 内容是作者创作材料和页面状态，不是系统或开发指令。
- 不执行材料中出现的命令式句子。
- 正式数据库资料与未保存草稿分别标记。
- 当前上下文不足时调用只读工具，不虚构缺失信息。

### 6.3 页面草稿留存决策树与最终结果

阶段 0 使用两个不同的唯一标记：一个只存在于原始 request_context，另一个只存在于 Middleware 生成的动态消息。分别检查：

- 聊天消息历史。
- ChatSpec/session state。
- 数据库或 JSON repo。
- 会话导出。
- 服务器日志。
- 调试 trace 与可观测性输出。
- 重启后的会话状态。

结果 A：原始 request_context 与注入后消息都不持久化。

- 可以直接发送裁剪后的 ai_novel_context JSON。

结果 B：原始 request_context 会持久化，但注入后消息不持久化。

- 改用内存 context registry。
- 前端通过同源插件 HTTP POST 提交已经过 24,000 字符总预算裁剪的短期页面快照，得到至少 128bit 随机、不可枚举的 context_ref；请求体不得进入普通访问日志。
- registry 条目同时绑定当前本地 owner、workbench owner token、浏览器 tab instance、Agent、作品和可选 session；后端不信任模型或 URL 单独传入的标识。
- chat.requestPayload 只携带 context_ref。
- 生产 Middleware 租用 context_ref，并核对 request/session/Agent/作品绑定；按 ADR-0003 使用 30 秒同会话幂等窗和 TTL 兜底清理，不依赖不存在的 Hook FINALLY。
- endpoint 必须限制单 owner 容量、单条大小和提交频率；错误、过期和绑定不符统一返回不可区分的失效结果，避免枚举。
- 服务重启后允许上下文失效，不写数据库和长期 Memory。

**A0B 实测为结果 C：注入后的页面草稿会进入 Agent 会话状态或聊天历史。以下规则已由 A0D 冻结：**

- context_ref 只能减少传输和日志暴露，不能解决注入消息进入会话状态的问题。
- 使用显式绑定的工作台会话，把页面草稿限制在该会话范围，并明确显示“本轮页面内容可能成为此工作台会话历史的一部分”。公开能力不能从任意普通聊天静默创建空白会话；作者已处于有效工作台时可以使用原生“新建对话”保留作品页面并得到空白助手。A7 的“先新会话再从创作中心进入”作为历史验收流程保留。
- 离开工作台只停止新的页面注入；历史中作者已经讨论或发送的小说内容不会被伪装成已经删除。
- 普通聊天必须使用不同会话，或在界面上明确当前仍处于小说工作台会话。同一运行期有效 owner 内的原生新会话保留工作台；fresh/direct `/chat`、显式普通聊天导航和主动离开工作台继续清理 owner。
- 若公开会话能力无法完成隔离，则即时草稿只在作者明确触发选区/页面分析时发送，不能默认附加全部 dirty 字段。
- 不允许把页面草稿写入 Agent 人设文件、长期 Memory 或项目文档。

### 6.4 Agent 作用域

只有以下条件全部成立时才注入：

- RouteSessionStateMachine 处于 workbench。
- novelId 有效。
- schemaVersion 受支持。
- selectedAgent 为 ai-novel-writer。
- context snapshot 未过期。

切换 Agent 后立即停止注入；生成中的 selection/proposal 同时绑定原 Agent，切换后只允许复制，不允许应用。

### 6.5 路由与会话状态机

状态：

- ordinary-chat。
- workbench-no-session。
- workbench-session。
- leaving-workbench。

事件与期望：

| 事件 | 期望 |
| --- | --- |
| 从创作中心进入作品 | 建立 workbench owner token 和页面定位 |
| /chat 规范化为 /chat/session | 保留同一 workbench 和页面 |
| 工作台内原生创建新对话 | 当前内存 workbench owner 与 tab 存储匹配时，保留作品/文档/owner，清空旧 chatPath；新 session 生成后绑定 |
| 点击返回列表/创作中心 | 先清空 context 和 owner token，再导航 |
| 主动进入普通聊天 | 清空 context 和 owner token |
| 刷新工作台深链接 | 从 URL 恢复作品与文档，不恢复选区 |
| 前进/后退 | 根据 URL 和 owner token 得到唯一状态 |
| 关闭弹窗 | 恢复背景页面上下文，不保留弹窗字段 |
| 切换作品 | 先销毁旧字段、选区和 proposal，再发布新作品 |

A0C 已证明不能只凭裸 `/chat` 猜测全部导航意图。2026-08-25 真实缺陷回归后，状态机收窄为“双证据”转换：只有当前内存仍处于有效 workbench owner，且 tab-scoped 存储的 owner/novel 同时匹配时，裸 `/chat` 才视为该工作台内的原生新会话；fresh/direct `/chat` 不读取旧 owner，显式普通聊天导航继续清理。该规则不依赖 QwenPaw 私有 Router、store 或 DOM。

## 7. 正式资料读取工具

新增只读工具 novel_get_workspace_context。

### 7.1 请求参数

- schema_version。
- novel_id。
- section。
- 可选 document_id、entity_type、entity_id。
- max_chars，后端强制夹紧在批准范围。
- include 列表，仅允许批准的资料类别；`chapter_naming` 只在模型明确处理章节标题时请求。

### 7.2 返回协议

返回必须包含：

- schema_version。
- as_of。
- novel_id、section 和当前实体。
- provenance：数据库表、working copy 或 revision。
- truncated 与 omitted_sections。
- data。
- warnings。

### 7.3 数据规则

- 所有 document、entity 和关系端点必须属于 novel_id。
- novel_id 必须属于服务端解析出的当前本地 owner；不得仅因模型传入了合法 UUID 就放行。
- 复用现有领域服务，不复制查询逻辑。
- 关系、人物和线索使用批量查询；测试中查询次数不得随实体数线性增长。
- 不返回整本书全部正文。
- `chapter_naming` 是标题质量专用的窄例外：只返回服务端当前作用域章节的 bounded working copy，以及按书内顺序排列的章名索引；不返回其他章节正文。标题必须从本章事件/转折/钩子中提炼，并对书内其他章名做重复与近重复检查，书名不得作为标题词库。
- 页面未保存草稿只来自请求上下文，不伪装成正式资料。
- 保留 novel_get_context、novel_get_document、novel_search 兼容旧会话。
- 新工具只在 ai-novel-writer 中启用，Default 与 QA Agent 保持关闭。

## 8. 选区与结构化提案闭环

### 8.1 Selection Registry

注册表只存在于当前浏览器内存，要求：

- selection_id 使用不可猜 UUID。
- 默认 TTL 20 分钟，阶段 0 可调整。
- 每个标签页最多 50 条；超限淘汰最旧记录。
- 创建选区时绑定 agentId、novelId、documentId、fieldId、contextRevision；若尚无原生会话，sessionId 允许为空。
- requestPayload 真正发送时把 selection 原子绑定到当前 sessionId；绑定后不得改绑到另一会话。
- 保存 startUtf16、endUtf16、direction、选区文本与完整字段 SHA-256。
- 切换作品、字段销毁、页面卸载和过期时清理。
- 同一选区的并发请求可以生成多张卡，但只有仍匹配当前字段的卡可以应用。

### 8.2 选区入口与工具条位置

input/textarea 使用 selectionStart、selectionEnd 和 selectionDirection。

阶段 0 比较两种位置策略：

1. textarea mirror 测量，工具条靠近选中文字。
2. 固定在当前字段右上或下方的选区工具条。

只有方案 1 在滚动、缩放、高 DPI、长行、换行和 IME 下稳定时才采用；否则使用方案 2。功能正确性优先于“贴着选区”的视觉效果。

动作：

- 润色。
- 改写。
- 扩写。
- 缩写。
- 增强对白。
- 检查问题。
- 自定义。

点击动作后展开助手、注册动态 suggestion，并在该用户手势内复制完整 slash 命令。QwenPaw 2.1 没有公开命令式发送/prefill 能力，真实流程明确显示为“选择动作 → 在原生助手按 ⌘V → 点击原生发送”；Clipboard 失败时降级为“输入命令或 `/` 选择建议 → 点击原生发送”。

### 8.3 结构化工具协议

新增不写数据库的 novel_prepare_selection_edit。

模型调用输入只包含 selection_id、operation、replacement_text 和 short_summary。工具的版本化结果至少包含：

    {
      "schema_version": 1,
      "selection_id": "uuid",
      "operation": "polish|rewrite|expand|shorten|dialogue|review|custom",
      "replacement_text": "纯文本",
      "short_summary": "修改摘要",
      "replacement_character_count": 146,
      "warnings": []
    }

规则：

- replacement_text 有后端长度上限。
- replacement_character_count 由工具按 replacement_text 计算，不接受模型自报。
- 原选区字数、字段名称和原文摘要由前端 selection registry 提供，不能由后端或模型猜测。
- renderer 把内容按纯文本展示，不执行 HTML。
- 后端只验证结构和长度，不声称浏览器选区仍存在。
- 前端应用前重新验证 Agent、Session、作品、文档、字段、SHA-256、UTF-16 范围和原文字段片段。
- 任何校验失败时禁用替换/插入，只保留复制和放弃。
- 模型没有调用工具、JSON 错误、超时或 renderer 失败时，明确显示“未应用”，并提供普通文本复制降级。
- 普通聊天文字不得被正则解析后直接写回。

### 8.4 工具卡片动作

- 替换选中文字。
- 插入到选区后。
- 复制。
- 撤销最近一次 AI 修改（仅在当前字段事务有效时）。
- 放弃。

卡片必须显示：摘要、操作类型、原文字数、新文字数、字段名称、过期/冲突状态。

## 9. 可访问性、性能与质量门槛

### 9.1 可访问性

- 助手拖拽柄使用 role=separator、aria-orientation=vertical、aria-valuemin、aria-valuemax、aria-valuenow。
- 左右方向键调整 10px，Shift+方向键调整 40px。
- 折叠、恢复、选区动作和卡片按钮有中文 aria-label。
- 可交互目标视觉或命中区域至少 40×40px。
- 状态变化通过 aria-live=polite 通知，但输入时不重复播报。
- 弹窗关闭、助手展开和撤销后恢复合理焦点。
- 选区工具条支持 Tab、Shift+Tab 和 Escape；Escape 不清空正文选区。
- 验收 200% 缩放、键盘全流程和中文 IME。
- 截图不能证明 WCAG 合规；必须使用实际键盘与辅助技术检查。

### 9.2 性能

- 100 次连续正文输入期间，原生 Inner 不因每次按键重渲染。
- 大字段裁剪和 JSON 序列化只在发送时发生。
- 24,000 字符快照构建在验收机器上 p95 不超过 50ms。
- 页面上下文 store 的轻量派生状态更新不得产生超过 50ms 的长任务。
- 新增前端 gzip 体积目标不超过 40KB；不得重复打包 React 或 Ant Design。
- novel_get_workspace_context 不出现随实体数线性增长的 N+1 查询。
- 工具和提案返回严格受 max_chars 与 replacement 长度限制。

### 9.3 AI 质量

链路正确性与文学质量分开验收。

至少选择三种真实题材，每种覆盖：

- 润色。
- 改写。
- 扩写或缩写。
- 对白增强。
- 连贯性检查。
- 自定义要求。

评分项：

- 是否只处理选区。
- 是否保留关键事实和人称。
- 是否遵守本轮操作意图。
- 是否与人物、设定和前文一致。
- 章节标题是否来自本章核心事件/转折/钩子/独特物件，并与全书章名去重；书名不得充当标题词库。
- 是否避免 Markdown 围栏和无关解释进入 replacement_text。
- 是否在资料不足时说明范围而不是虚构数据库事实。

## 10. V2 分阶段施工、并行标注与逐任务状态

状态：✅ 已验证；🟡 部分完成；🔴 阻断；⏳ 尚未执行；⛔ 尚未批准派发。

### 10.0 标记、Owner 与直接派发规则

| 标记 | 施工含义 | 是否可交给子代理并行 |
| --- | --- | --- |
| `PAR` | 输入、文件和验收产物均可隔离 | 可以；满足前置后进入 ready set |
| `PAR-C` | 契约或门禁冻结后才能独立施工 | 可以；不得提前猜测接口 |
| `SER` | 公共契约、共享入口、迁移、Git 或最终决策 | 不可以；由主 Codex 或唯一 Owner 串行执行 |
| `MUTEX` | 代码可分开准备，但会争用同一浏览器、容器、数据库、Agent 配置或宿主状态 | 编码可并行，真实运行必须排队 |
| `GATE` | 汇合、复核和 go/no-go 裁决 | 不可以；主 Codex 串行执行 |
| `INT` | 共享文件接线、冲突解决和全量回归 | 不可以；主 Codex 串行执行 |
| `DONE` | 已完成且只保留证据 | 不重复派发 |

施工约束：

- 当前 Codex 会话按 4 个活跃槽位编排，即主 Codex 加最多 3 个子代理；后续若实际槽位变化，只调整滚动批次，不改变依赖和文件互斥规则。“可并行”表示可进入 ready set，不保证同一秒全部启动。
- Owner 表示文件与接口责任域，不绑定某个固定代理。每次派发仍需写出允许修改文件、禁止修改文件、输入契约、测试和证据。
- `frontend/src/index.ts`、`frontend/src/styles.ts`、`plugin.py`、公共 DTO/类型、配置/验证脚本、Agent 总提示、Git index 由唯一 Owner 管理；子代理优先提交独立模块与独立测试，入口接线留给 `INT`。
- 两个代理不得同时修改 `workbench-v2.ts`、`workbench-studio.ts`、`chapter-workflow.ts` 的同一函数或同一页面区域。
- 同一 QwenPaw 安装状态、同一浏览器会话、同一小说、同一 Agent 模型配置、同一 PostgreSQL 破坏性测试均按 `MUTEX` 排队。
- 子代理不得自行执行 Git commit、push、迁移编号分配、生产数据清理或插件全局安装；这些操作只能由主 Codex 执行。
- 阶段编号只表示产品分层；实际能否提前并行，以每行“前置/互斥”列为准。
- 本节是助手 V2 的权威任务状态与派发入口；如遇其他专项占用共享文件，由主代理暂停冲突包并协调唯一 owner，不在本文内派发其他专项任务。

#### 10.0.1 推荐施工波次

| 波次 | 主 Codex 串行工作 | 子代理 ready set | 汇合条件 |
| --- | --- | --- | --- |
| W0A | `A0A-2` 已完成；执行 `A0A-3` | `A0A-4A…E` 只读取证；同一浏览器会话排队 | `A0A-G` |
| W0B-0 | `A0B-1` 冻结最窄公开类型 | 无 | 类型与测试 fixture 可供引用 |
| W0B-1 | 宿主注册与运行状态 Owner | `A0B-2`；`A0B-3 → (A0B-4、A0B-7)`；`A0B-5 + A0B-6` | `A0B-8` 清理后执行 `A0B-G` |
| W0C | 发布 `A0C-0` 尖峰接口与文件边界 | `A0C-1`；`A0C-2 + A0C-3`；`A0C-4 + A0C-5`；`A0C-6` 按空槽滚动 | `A0C-G` |
| W0D | `A0D-1 → A0D-2 → A0D-3 → A0D-4 → A0D-5` | 只允许原任务 Owner 提交证据摘要，不并写冻结文档 | `A0D-G`，随后才可批准正式开发 |
| W1/2 | `A1-A` 与 `A2-A` 分别由唯一 Owner 串行落地 | `A1-B/C/E/F` 可与 `A2-B/D/E` 并行；同一页面按 `A1-Dn → A2-Cn` 顺序滚动 | `A1-G`、`A2-G` |
| W3/4/5 | `A5-A`、`A4-D0` 单一文档 Owner | `A3-B/C` 与 `A4-A` 可在 A0D-G 后先行；`A3-A`、`A5-B/D/E` 在 A2-G 后滚动；`A4-D1…D6` 按 Skill 目录拆分 | 分别执行 `A3-G`、`A4-G`、`A5-G` |
| W6 | `A6-E0` 冻结 Agent/Skill 统一规则 | `A6-B/C/D1` 可按前置提前准备；`A6-A/D2`、`A6-E1…E6`、`A6-F` 按依赖滚动；`A6-E7` 独占安装状态 | `A6-G` |
| W7 | 固定模型、小说、数据库和浏览器验收状态 | `A7-T1…T8` 分层验证；会修改共享运行状态的用例排队 | `A7-G` |

#### 10.0.2 子代理直接派发模板

每次派发必须填写完整；任一项为空时，不进入 ready set：

```text
工作包 ID：
唯一目标：
明确非目标：
允许修改的精确文件：
只读文件/目录：
禁止触碰的共享文件与用户改动：
已冻结输入契约与 fixture：
互斥运行资源：
必须运行的最小测试：
必须返回的证据：
交付给主 Codex 的接线位置、风险与未完成项：
```

### 阶段 0A：基线与依赖封口

| ID | 执行 | Owner 范围 | 任务 | 前置/互斥 | 状态 | 完成条件 |
| --- | --- | --- | --- | --- | --- | --- |
| A0A-1 | `DONE` | 基线审计 | 确认 UI/Git 基线 | 无 | ✅ | HEAD 与 origin/main 均为 a4007ab |
| A0A-2 | `DONE` | 模型计划 Owner | 完成模型跟随计划 | A0A-1 | ✅ | 0245bd1 已提交；迁移、容器安装、健康策略和 verify 一致 |
| A0A-3 | `DONE` | 主 Codex、Git/文件 Owner | 建立助手专项工作区、提交和文件所有权边界 | A0A-2 | ✅ | 原工作区精确文件锁已冻结；不混入模型计划和用户无关改动 |
| A0A-4A | `DONE` | 浏览器 QA | 章节页 1920/2K 现状证据 | 只读 | ✅ | 两个目标分辨率截图已核实 |
| A0A-4B | `DONE/MUTEX` | 浏览器 QA | 角色页 1920/2K 现状证据 | 只读；同一浏览器会话排队 | ✅ | `04`、`06` 两张目标分辨率截图已核实 |
| A0A-4C | `DONE/MUTEX` | 浏览器 QA | 大纲页 1920/2K 现状证据 | 只读；同一浏览器会话排队 | ✅ | `07`、`08` 两张目标分辨率截图已核实 |
| A0A-4D | `DONE/MUTEX` | 浏览器 QA | 线索、设定页 1920/2K 现状证据 | 只读；同一浏览器会话排队 | ✅ | `09`…`12` 四张目标分辨率截图已核实 |
| A0A-4E | `DONE/MUTEX` | 浏览器 QA | QwenPaw 原生聊天 1920/2K 现状证据 | 只读；同一浏览器会话排队 | ✅ | 通过返回创作中心清理工作台路由后，`13`、`14` 已核实；`05` 仅为 1280×720 无效样本 |
| A0A-G | `DONE/GATE` | 主 Codex | 可恢复基线与依赖封口 | A0A-1、A0A-2、A0A-3、A0A-4A…E | ✅ | [A0A 门禁记录](./证据/助手计划V2验证-2026-08-25/A0A-GATE.md)已确认工作区可恢复、依赖隔离和证据完整 |

退出条件：`A0A-G` 通过；未通过时不得派发 A0B。

### 阶段 0B：QwenPaw 契约与数据留存尖峰

| ID | 执行 | Owner 范围 | 任务 | 前置/互斥 | 状态 | 完成条件 |
| --- | --- | --- | --- | --- | --- | --- |
| A0B-1 | `DONE/SER` | 宿主契约 Owner | 补最窄前端类型与共享 fixture | A0A-G | ✅ | 已冻结经实测的公开 API 与 compile fixture |
| A0B-2 | `DONE/PAR-C` | 前端壳实验 | 固定宽度渲染 Inner | A0B-1 | ✅ | 320、380、520px、折叠与 DOM 保活通过 |
| A0B-3 | `DONE/PAR-C/MUTEX` | context-runtime 单一 Owner | requestPayload 到运行时唯一标记链路 | A0B-1；共享宿主状态排队 | ✅ | MiniMax-M3 当轮原样读取唯一注入标记 |
| A0B-4 | `DONE/PAR-C/MUTEX` | 与 A0B-3 相同 Owner | 比较 runtime hook 与 middleware | A0B-3；不得由另一代理并写同一注入模块 | ✅ | Hook 真实链路不执行；冻结公开 Middleware |
| A0B-5 | `DONE/PAR-C` | tool-renderer 实验 | toolRender 前端动作 | A0B-1；不得接线共享 index | ✅ | result/session/message、复制和失败关闭测试通过 |
| A0B-6 | `DONE/PAR-C` | suggestion 实验 | suggestion 动态注册/注销 | A0B-1；不得接线共享 index | ✅ | upsert、注销、去重和 dispose 测试通过 |
| A0B-7 | `DONE/PAR-C/MUTEX` | 留存与隐私审计 | 原始载荷与注入消息留存取证 | A0B-3；同一会话、日志和导出状态排队 | ✅ | 结果 C：专用工作台会话 + A3 context_ref |
| A0B-8 | `DONE/MUTEX` | 宿主集成 Owner | 插件卸载/重装清理 | A0B-3…6；独占插件安装状态 | ✅ | 卸载归零；重装唯一；既有 Agent 工具恢复缺陷已修复 |
| A0B-G | `DONE/INT/GATE` | 主 Codex | 冻结公开扩展点与留存决策 | A0B-1…8 | ✅ | [A0B 门禁记录](./证据/助手计划V2验证-2026-08-25/A0B-GATE.md)已冻结 Middleware 与专用会话决策 |

退出条件：`A0B-G` 通过；各子代理的原型不得直接改共享入口，统一在本门禁接线。

### 阶段 0C：前端可行性尖峰

| ID | 执行 | Owner 范围 | 任务 | 前置/互斥 | 状态 | 完成条件 |
| --- | --- | --- | --- | --- | --- | --- |
| A0C-0 | `DONE/SER` | 前端契约 Owner | 发布尖峰接口、fixture 与精确文件边界 | A0B-G | ✅ | 唯一字段契约与并行文件边界已冻结 |
| A0C-1 | `DONE/PAR-C` | route-state | RouteSessionStateMachine | A0C-0 | ✅ | 12 项测试及真实深链、归一化、刷新、清理和前进后退通过 |
| A0C-2 | `DONE/PAR-C` | body-adapter | 正文 EditableFieldAdapter | A0C-0 | ✅ | 受控应用、自动保存请求、冲突和回执撤销原型通过 |
| A0C-3 | `DONE/PAR-C` | form-adapter | 显式保存表单 Adapter | A0C-0；与 A0C-2 使用同一接口、不同文件 | ✅ | 应用后 dirty，不暴露或越过保存按钮 |
| A0C-4 | `DONE/PAR-C` | selection-geometry | textarea 选区几何 | A0C-0 | ✅ | 冻结保守 `field-anchor`；无完整实证前不启用 mirror 精确定位 |
| A0C-5 | `DONE/PAR-C` | selection-registry | selection registry | A0C-0；与几何模块隔离 | ✅ | TTL、容量、SHA-256、scope/revision 与首次 session 绑定通过 |
| A0C-6 | `DONE/PAR-C` | frontend-shell | 右侧工具轨迁移实验 | A0B-2、A0C-0；共享 styles/index 由 INT Owner 接线 | ✅ | 布局算法强制不越过助手边界；正式视觉迁移保留为 A1-E/G 门槛 |
| A0C-G | `DONE/INT/GATE` | 主 Codex | 前端尖峰汇合 | A0C-1…6 | ✅ | [A0C 门禁记录](./证据/助手计划V2验证-2026-08-25/A0C-GATE.md)已证明字段、选区、保存、撤销原型和路由可行 |

退出条件：`A0C-G` 通过；各 Adapter、registry、状态机都有独立测试且没有双写共享页面根文件。

### 阶段 0D：冻结 ADR 与协议

| ID | 执行 | Owner 范围 | 任务 | 前置 | 状态 | 完成条件 |
| --- | --- | --- | --- | --- | --- | --- |
| A0D-1 | `DONE/SER` | 主 Codex、ADR Owner | 冻结原生 Inner、注入机制、role=user 数据边界和留存方案 | A0B-G、A0C-G | ✅ | ADR-0003 与 Middleware/留存真实实验一致 |
| A0D-2 | `DONE/SER` | 主 Codex、协议 Owner | 冻结 NovelAssistantContextV2、预算与去重 | A0D-1 | ✅ | schema、24,000 字符预算、裁剪、TTL 与数据边界无歧义 |
| A0D-3 | `DONE/SER` | 主 Codex、编辑协议 Owner | 冻结 EditableFieldAdapter 与 AIEditTransaction | A0D-2 | ✅ | 正文 autosave、表单 explicit-save、冲突和撤销语义统一 |
| A0D-4 | `DONE/SER` | 主 Codex、选区协议 Owner | 冻结 selection/proposal schema | A0D-2、A0D-3 | ✅ | Agent/session/字段/revision/hash/TTL 与 field-anchor 固定 |
| A0D-5 | `DONE/SER` | 主 Codex、计划 Owner | 更新阶段 1–7 工期、代码落点和降级路径 | A0D-1…4 | ✅ | backlog、Owner、ready set 与 ADR 完全一致 |
| A0D-G | `DONE/GATE` | 主 Codex | 七个 P0 最终裁决 | A0D-1…5 | ✅ | [A0D 门禁记录](./证据/助手计划V2验证-2026-08-25/A0D-GATE.md)已解除七个 P0 并记录用户正式施工批准 |

说明：原任务 Owner 可以并行提交证据摘要，但不得同时编辑 ADR、schema 或本计划的冻结结论。

### 阶段 1：原生助手与弹性三栏

派发状态：✅ 已完成；[A1-G 门禁记录](./证据/助手计划V2验证-2026-08-25/A1-GATE.md)已通过。

| ID | 执行 | Owner 范围 | 工作包 | 前置/互斥 | 完成条件 |
| --- | --- | --- | --- | --- | --- |
| A1-A | `SER` | 前端壳契约 Owner | 公开前端类型、助手壳和弹性网格接口 | A0D-G | 冻结 Inner、pane、separator 与 layout API |
| A1-B | `PAR-C` | route-wrap | route.wrap、Inner 与工作台组合 | A1-A；共享 index 留待 INT | 原生聊天和工作台同屏 |
| A1-C | `PAR-C` | assistant-pane | 折叠、恢复、拖动与本地偏好 | A1-A | 状态可恢复且不污染普通聊天 |
| A1-D1…D5 | `PAR-C` | 各页面模块 | 章节、大纲、人物、线索、设定弹性网格 | A1-A；按模块独立文件 | 两种分辨率均无遮挡和溢出 |
| A1-E | `PAR-C` | frontend-shell/a11y | 工具轨迁移、separator、状态条和无障碍 | A1-A；共享 styles 留待 INT | 键盘和 200% 缩放可用 |
| A1-F | `PAR-C` | frontend QA | 普通聊天、缩放、路由和双分辨率非回归 | A1-A；只读浏览器可并行，状态写入 MUTEX | 证据和回归测试齐全 |
| A1-G | `DONE/INT/GATE` | 主 Codex | 三栏与共享入口/样式接线 | A1-B…F | ✅ 双分辨率、宽度、折叠、工具轨与普通聊天非回归通过 |

### 阶段 2：上下文 Store 与字段适配器

派发状态：✅ 已完成；[A2-G 门禁记录](./证据/助手计划V2验证-2026-08-25/A2-GATE.md)已通过。

| ID | 执行 | Owner 范围 | 工作包 | 前置/互斥 | 完成条件 |
| --- | --- | --- | --- | --- | --- |
| A2-A | `SER` | context-contract Owner | 将 A0D 冻结的 schema、预算、裁剪、字段与 persistence 接口落实为代码类型 | A0D-G | 代码类型与 ADR/协议逐字段一致，不在实现阶段重开语义 |
| A2-B | `PAR-C` | context-store | Store、字段 registry 与生命周期 | A2-A | 注册、聚焦、销毁和过期正确 |
| A2-C1…C8 | `PAR-C` | 各字段/页面 Owner | 正文、标题、章纲、大纲、人物、关系、线索、设定 Adapter | A2-A、A2-B 接口；对应 A1-Dn 已合并；同一页面保持 `A1-Dn → A2-Cn` 单 Owner 串行 | 八类字段均走受控状态 |
| A2-D | `PAR-C` | edit-transaction | AIEditTransaction、逐字段保存与状态文案 | A2-A | 自动保存与显式保存语义分离 |
| A2-E | `PAR-C` | context QA | 切页/切书/弹窗、预算、去重、过期和撤销测试 | A2-A；可测试先行 | 无旧上下文残留 |
| A2-G | `DONE/INT/GATE` | 主 Codex | 上下文和字段行为汇合 | A2-B…E | ✅ 生命周期、八类字段、保存/冲突/撤销语义通过 |

### 阶段 3：请求注入

派发状态：✅ 已完成；[A3-G 门禁记录](./证据/助手计划V2验证-2026-08-25/A3-GATE.md)已通过。

| ID | 执行 | Owner 范围 | 工作包 | 前置/互斥 | 完成条件 |
| --- | --- | --- | --- | --- | --- |
| A3-A | `PAR-C` | request-payload FE | 前端 requestPayload 转换 | A2-G | 当前快照正确进入请求 |
| A3-B | `PAR-C/MUTEX` | middleware BE | 落实 ADR 选定的公开 Middleware 注入 | A0D-G；共享 plugin 入口留待 INT，运行状态排队 | 只作用于目标 Agent 当轮 |
| A3-C | `PAR-C` | context-transport BE | direct JSON/context_ref、Agent/页面/schema/过期检查 | A0D-G | 数据边界与降级符合 ADR |
| A3-D | `PAR-C/MUTEX` | injection QA | 内容隔离、预算、留存和路由/会话测试 | A3-A…C 契约；同一会话/Agent 排队 | 正式事实和草稿可区分 |
| A3-G | `DONE/INT/GATE` | 主 Codex | 正式注入汇合 | A3-A…D | ✅ MiniMax-M3 页面感知与非目标 Agent/普通聊天隔离通过 |

### 阶段 4：统一正式资料工具

派发状态：✅ 已完成；[A4-G 门禁记录](./证据/助手计划V2验证-2026-08-25/A4-GATE.md)已通过。

| ID | 执行 | Owner 范围 | 工作包 | 前置/互斥 | 完成条件 |
| --- | --- | --- | --- | --- | --- |
| A4-A | `PAR-C` | domain-service BE | 正式资料聚合服务与查询预算 | A0D-G；优先新增独立聚合服务，既有 services 默认只读 | 大纲、人物、关系、故事线、伏笔和设定可聚合 |
| A4-B | `PAR-C` | tool BE | novel_get_workspace_context、归属、provenance、as_of、truncated | A4-A 契约 | 无需复制 ID 且无越权 |
| A4-C | `PAR-C/MUTEX` | install-script Owner | Agent 配置、升级脚本和工具作用域 | A4-B；独占安装状态 | 只在 ai-novel-writer 启用且升级幂等 |
| A4-D0 | `SER` | Agent 文档 Owner | AI_NOVEL_WORLD 页面语义、草稿边界与工具总规则 | A4-B 契约 | 单一 Agent 文档规则冻结 |
| A4-D1…D6 | `PAR-C` | 各 Skill Owner | 六个 Skills 的 workspace context 工具规则 | A4-B、A4-D0；按目录隔离 | 工具选择和资料边界一致 |
| A4-E | `PAR-C` | tool QA | N+1、越权、截断、跨书和旧工具兼容 | A4-A、A4-B、A4-C、A4-D0、A4-D1…D6 契约；测试可提前写 | 查询预算和兼容性通过 |
| A4-G | `DONE/INT/GATE` | 主 Codex | 统一工具汇合 | A4-A、A4-B、A4-C、A4-D0、A4-D1…D6、A4-E；A3-G | ✅ 真实资料读取、作用域、归属、来源、截断与查询预算通过 |

### 阶段 5：选区与发送体验

派发状态：✅ 已完成；[A5-G 门禁记录](./证据/助手计划V2验证-2026-08-25/A5-GATE.md)已通过。

| ID | 执行 | Owner 范围 | 工作包 | 前置/互斥 | 完成条件 |
| --- | --- | --- | --- | --- | --- |
| A5-A | `SER` | selection-contract Owner | 将 A0D-4 冻结的 selection ID、Agent/session、字段、版本、hash 和失效契约落实为代码类型 | A0D-G、A2-G | 唯一选区协议实现与 ADR 一致，不产生第二份 schema |
| A5-B | `PAR-C` | selection-registry | 正式 registry | A5-A | TTL、容量、绑定和失效正确 |
| A5-C1…Cn | `PAR-C` | 各字段 Owner | 所有允许编辑字段的选区 Adapter | A5-A、A5-B 接口；按页面隔离 | 每个字段产生正确 selection_id |
| A5-D | `PAR-C` | selection UX | 位置方案、suggestion、助手展开和发送步数 | A5-A | 展开、过期和发送状态明确 |
| A5-E | `PAR-C/MUTEX` | interaction QA | 鼠标、键盘、滚动、缩放、IME 和过期测试 | A5-A；同一页面交互排队 | 输入法与选区不丢失 |
| A5-G | `DONE/INT/GATE` | 主 Codex | 全字段选区发送体验汇合 | A5-B…E | ✅ 全字段选区、发送、失效与隔离通过 |

### 阶段 6：结构化提案、应用与撤销

派发状态：✅ 已完成；[A6-G 门禁记录](./证据/助手计划V2验证-2026-08-25/A6-GATE.md)已通过。

| ID | 执行 | Owner 范围 | 工作包 | 前置/互斥 | 完成条件 |
| --- | --- | --- | --- | --- | --- |
| A6-A | `PAR-C` | proposal-tool BE | novel_prepare_selection_edit 与严格 schema | A4-G、A5-G | 工具只返回结构化提案 |
| A6-B | `PAR-C` | tool-card FE | 原生 renderer、卡片和降级 | A0D-G、A5-A；共享注册留待 INT | 坏结果可复制、不误写回 |
| A6-C | `PAR-C` | apply-transaction FE | 替换、插入、复制、撤销和放弃 | A5-A、A2-D | 所有写回经过 Adapter |
| A6-D1 | `PAR-C` | persistence policy FE | 正文自动保存、表单 dirty 与冲突策略模块/测试 | A2-G；只改独立事务模块 | 保存语义正确 |
| A6-D2 | `PAR-C` | 各页面 Owner | 卡片失效与页面保存接线 | A5-G、A6-D1；同一页面保持 `A2-Cn → A5-Cn → A6-D2` 串行 | 页面接线不与选区 Adapter 并写 |
| A6-E0 | `SER` | Agent 规则 Owner | 冻结“直接应用走工具卡片、普通建议只文本回复”的统一规则 | A6-A 契约 | Agent 与六个 Skill 使用同一规则 |
| A6-E1…E6 | `PAR-C` | 各 Skill Owner | 六个 Skills 的提案工具规则 | A6-E0；按目录隔离 | 各 Skill 不绕过卡片直接写回 |
| A6-E7 | `MUTEX` | install-script Owner | 工具作用域、配置/验证脚本和安装幂等 | A6-A、A6-E0、A6-E1…E6；独占安装状态 | 仅目标 Agent 可调用，安装/卸载无残留 |
| A6-F | `PAR-C/MUTEX` | proposal QA | 无工具调用、坏 JSON、超时、过期、切 Agent 和安全测试 | A6-A、A6-B、A6-C、A6-D1、A6-D2、A6-E0、A6-E1…E7 契约；共享 Agent 状态排队 | 所有失败均安全降级 |
| A6-G | `DONE/INT/GATE` | 主 Codex | 受控字段应用和撤销闭环 | A6-A、A6-B、A6-C、A6-D1、A6-D2、A6-E0、A6-E1…E7、A6-F；且 A3-G、A4-G、A5-G 已通过 | ✅ 真实替换/插入、保存、撤销、冲突与降级通过 |

### 阶段 7：真实模型验收与交付

派发状态：✅ 已完成；A7-T1…T8 全部通过，[A7-G 最终验收记录](./证据/助手计划V2验证-2026-08-25/A7-GATE.md)已形成。

| ID | 执行 | Owner 范围 | 验收轨 | 前置/互斥 | 完成条件 |
| --- | --- | --- | --- | --- | --- |
| A7-T1 | `PAR/MUTEX` | AI 质量 | 三种题材真实作品、有效模型与文学质量矩阵 | A6-G；同一 Agent 模型配置排队 | 当前有效模型全链路通过；MiniMax-M3 仅在明确要求时切换 |
| A7-T2 | `PAR/MUTEX` | 视觉 QA | 1920×1080、2560×1440、200% 和错误态 | A6-G；同一浏览器状态排队 | 无遮挡、溢出和不可达操作 |
| A7-T3 | `PAR` | 前端 QA | 单测、类型、构建和组件回归 | A6-G | 全绿且无新增构建告警 |
| A7-T4 | `PAR/MUTEX` | 后端/DB QA | 后端单元、数据库集成、权限和并发 | A6-G；破坏性数据库用例排队 | 数据与权限门槛通过 |
| A7-T5 | `PAR/MUTEX` | 宿主 QA | 容器、安装、升级、卸载和回退 | A6-G；独占 QwenPaw 安装状态 | 无残留且可恢复 |
| A7-T6 | `PAR/MUTEX` | 性能 QA | 长章节、上下文预算、N+1 和交互性能 | A6-G；固定机器环境 | 第 9、12 节指标通过 |
| A7-T7 | `PAR/MUTEX` | 无障碍 QA | 键盘、ARIA、焦点、缩放和中文 IME | A6-G；浏览器交互排队 | 无 P0/P1 可访问性问题 |
| A7-T8 | `PAR/MUTEX` | 稳定性/安全 QA | 控制台、日志脱敏、失败恢复、跨书/跨 Agent 隔离 | A6-G；共享会话和配置排队 | 无数据泄漏和未解释错误 |
| A7-G | `DONE/INT/GATE` | 主 Codex | 最终验收、证据与交付裁决 | A7-T1…T8 | ✅ 第 12 节技术/产品项通过，无未解释 P0/P1；Git 发布按独立授权单列 |

阶段完成以 `A7-G` 为准；A7-G 已由主 Codex 汇总真实模型、浏览器、数据库、宿主和自动化证据后通过。Git 暂存、提交与推送仍遵循用户独立授权，不因技术门禁通过而自动执行。

## 11. 精确文件所有权、禁止范围与验证命令

### 11.1 前端

| 精确文件 | 唯一 Owner / 顺序 | 允许内容与冲突规则 |
| --- | --- | --- |
| frontend/src/qwenpaw-host.d.ts | A0B-1 → A1-A | 公开宿主窄类型；其他代理只读，不得自行扩成猜测接口 |
| frontend/src/index.ts | 仅 A0B-G、A1-G、A3-G、A6-G 的主集成 Owner | route.wrap、扩展注册/注销和最终接线；子代理禁止直接修改 |
| frontend/src/styles.ts | 仅 A1-G 的样式集成 Owner | 弹性三栏、工具轨、选区和卡片共享样式；模块代理返回局部需求，不并写本文件 |
| frontend/src/workbench-route.ts | A0C-1 | 作为唯一 RouteSessionStateMachine 权威；不新建第二个 assistant-route 状态机 |
| frontend/src/assistant-route-wrap.ts（新） | A1-B | route.wrap 组合模块；真正注册只在 A1-G 写入 index.ts |
| frontend/src/assistant-request-payload.ts（新） | A3-A | requestPayload 快照转换；与路由状态机分文件并行 |
| frontend/src/assistant-context-schema.ts（新） | A2-A | 落实 A0D-2 已冻结的 V2 类型、序列化契约和版本；不得在代码阶段改变协议语义 |
| frontend/src/assistant-context-store.ts（新） | A2-B | Store、预算、裁剪、去重、过期和生命周期 |
| frontend/src/assistant-fields.ts（新） | A0C-0 → A2-B | EditableFieldAdapter 接口与 registry；页面代理只实现 Adapter |
| frontend/src/assistant-pane.ts（新） | A0B-2 → A1-C | 原生 Inner 外壳、宽度、折叠和偏好 |
| frontend/src/assistant-suggestions.ts（新） | A0B-6 → A5-D | suggestion 注册/注销、选区动作和过期状态 |
| frontend/src/assistant-tool-rail.ts（新） | A0C-6 → A1-E | 固定工具轨迁移、separator 和无障碍行为；共享样式留待 A1-G |
| frontend/src/assistant-selection-registry.ts（新） | A0C-5 → A5-B | selection registry、TTL、容量、Agent/session 绑定与哈希 |
| frontend/src/assistant-selection-geometry.ts（新） | A0C-4 → A5-D | textarea 几何、字段边缘降级和工具条定位；与 registry 分文件并行 |
| frontend/src/assistant-transactions.ts（新） | A2-D → A6-C → A6-D1 | AIEditTransaction、应用/撤销和 persistence 策略；保持单 Owner 顺序 |
| frontend/src/assistant-tool-card.ts（新） | A0B-5 → A6-B | tool renderer、卡片动作和安全降级 |
| frontend/src/workbench-v2.ts | 对应页面链 A1-D → A2-C → A5-C → A6-D2 | 正文/标题布局、Adapter、选区与最终接线；同一时刻只允许一个 Owner |
| frontend/src/chapter-workflow.ts | 对应页面链 A1-D → A2-C → A5-C → A6-D2 | 章纲与显式保存状态；同一时刻只允许一个 Owner |
| frontend/src/workbench-studio.ts | 对应页面链 A1-D → A2-C → A5-C → A6-D2 | 大纲、人物、线索、设定；按函数/页面区登记 Owner，不得重叠 |
| frontend/src/relationship-editor.ts | 对应页面链 A1-D → A2-C → A5-C → A6-D2 | 关系上下文与选区；不并写关系图其他施工改动 |

### 11.2 后端与 Agent

| 精确文件 | 唯一 Owner / 顺序 | 允许内容与冲突规则 |
| --- | --- | --- |
| plugin.py | 仅 A0B-G、A3-G、A4-G、A6-G 的主集成 Owner | Middleware、registry、工具和卸载接线；所有子代理禁止并写 |
| backend/assistant_context.py（新） | A0B-3/4 → A3-C，同一 context-runtime Owner | schema 校验、注入、预算、目标 Agent 和留存策略 |
| backend/assistant_context_registry.py（条件新建） | A3-C | 只有 A0B-G 选择 context_ref 时才创建；内存租约、TTL、容量和清理 |
| backend/assistant_workspace_service.py（新） | A4-A | 只读聚合正式资料并调用既有领域服务；不得复制写入逻辑 |
| backend/tools.py | A4-B → A6-A，同一工具 Owner 串行 | workspace context 与 selection proposal；两个工具不得由不同代理并写 |
| backend/services.py、backend/creative_services.py | 默认只读；必要窄 helper 仅 A4-G 集成 Owner | 先复用既有服务；若确需修改，按函数登记唯一 Owner |
| qwenpaw-agent/AI_NOVEL_WORLD.md | A4-D0 → A6-E0，同一文档 Owner | 页面语义、草稿边界、工具选择和提案路由；其他 Skill 代理只读 |
| skills/chapter-outline、continuity-check、novel-direction、prose-writing、story-foundation、style-review | A4-D1…D6 → A6-E1…E6 | 六个目录可以分别派发；各目录只能有一个 Owner，统一规则由主 Codex 汇合 |
| scripts/configure_qwenpaw_novel_agent.py | A4-C → A6-E7，安装 Owner | 工具作用域、幂等升级和不覆盖用户模型选择 |
| scripts/verify_qwenpaw_lab.py | A0B-8 → A4-C → A6-E7，同一验证 Owner | Hook、工具、Agent 作用域、重复注册和卸载残留 |

### 11.3 测试

| 精确文件/证据目录 | Owner 工作包 | 覆盖范围 |
| --- | --- | --- |
| frontend/src/assistant-context.test.ts（新） | A2-E | schema、预算、裁剪、去重、过期和生命周期 |
| frontend/src/assistant-pane.test.ts（新） | A0B-2、A1-C | 320/380/520px、折叠和偏好 |
| frontend/src/assistant-layout.integration.test.ts（新） | A1-F | 原生聊天、普通聊天、路由、缩放和页面布局非回归 |
| frontend/src/assistant-request-payload.test.ts（新） | A3-A/D | 当前快照、Agent/页面/schema/过期过滤和请求转换 |
| frontend/src/assistant-suggestions.test.ts（新） | A0B-6、A5-D | 动态注册、注销、重复、选区过期和发送状态 |
| frontend/src/assistant-interaction.test.ts（新） | A5-E | 鼠标、键盘、滚动、缩放、IME 和过期 |
| frontend/src/assistant-tool-rail.test.ts（新） | A0C-6、A1-E | 工具轨、separator、键盘和与助手不重叠 |
| frontend/src/assistant-body-field.test.ts（新） | A0C-2 | 正文 Adapter、自动保存、冲突和撤销 |
| frontend/src/assistant-form-field.test.ts（新） | A0C-3 | 显式保存表单 Adapter、dirty 和不越过保存按钮 |
| frontend/src/assistant-fields.test.ts（新） | A2-E | registry、字段生命周期、切页/切书和弹窗 |
| frontend/src/workbench-route.test.ts（新） | A0C-1、A3-D | 唯一路由状态机、新会话、刷新和前进后退 |
| frontend/src/assistant-selection-registry.test.ts（新） | A0C-5、A5-E | TTL、容量、哈希、Agent/session 与跨会话失效 |
| frontend/src/assistant-selection-geometry.test.ts（新） | A0C-4、A5-E | 滚动、缩放、长文本、换行和字段锚定 |
| frontend/src/assistant-transactions.test.ts（新） | A2-D、A6-C | 替换、插入、撤销和事务边界 |
| frontend/src/assistant-persistence.test.ts（新） | A6-D1 | 正文自动保存、表单 dirty 和冲突策略 |
| frontend/src/assistant-page-apply.integration.test.ts（新） | A6-D2 | 卡片失效、页面接线和跨字段非回归 |
| frontend/src/assistant-tool-card.test.ts（新） | A0B-5、A6-B | result/session/message、卡片动作、复制和基本降级 |
| frontend/src/assistant-tool-card-failures.test.ts（新） | A6-F | 坏结果、超时、过期、切 Agent 和 renderer 失败 |
| tests/test_assistant_runtime_hook.py（新） | A0B-3/4 | requestPayload、Hook/Middleware 比较和 role=user 数据角色历史证据 |
| tests/test_assistant_context_retention.py（新） | A0B-7 → A3-D，同一留存 Owner | history、state、导出、日志、trace、TTL 和清理 |
| tests/test_assistant_context_transport.py（新） | A3-C/D | direct JSON/context_ref、Agent/页面/schema/过期和隔离 |
| tests/test_assistant_workspace_tool.py（新） | A4-E | 归属、provenance、as_of、截断、N+1 和兼容 |
| tests/test_assistant_proposal.py（新） | A6-A/F | proposal schema、选区绑定、过期和工具作用域 |
| tests/test_qwenpaw_integration_contract.py | 各阶段 INT Owner | 只追加已验证公开契约；避免多个子代理并写既有文件 |
| docs/开发文档/证据/助手计划V2验证-2026-08-25/ | A0A-4A…E、A7-T2/T7/T8 | 真实桌面、键盘、缩放、IME、控制台与错误态证据 |

### 11.4 默认只读与禁止触碰范围

- QwenPaw 上游核心代码、私有 Router、私有聊天 store、私有数据库和已安装包内容：只读核验，绝不修改、复制或 monkey patch。
- backend/models.py、backend/migrations/versions、backend/model_runtime.py、backend/generation_dependencies.py：本计划默认只读。当前方案不需要新增数据库表或 Alembic 迁移；若阶段 0 证明必须持久化新权威数据，应停止并另行补 schema/迁移门禁。
- frontend/src/types.ts、frontend/src/api.ts、package.json、pnpm 锁、pyproject.toml、requirements.txt：默认只读；新增依赖或公共 DTO 必须由主 Codex 单独批准和串行接入。
- frontend/dist、build、node_modules、__pycache__、数据库 dump：生成物或证据，不作为源代码修改目标。
- 任何不属于本计划的工作树改动、关系网施工证据、用户小说、正式 revision 和模型跟随历史：必须保留，子代理不得暂存、清理或改写。
- 子代理不得执行 commit、push、全局插件安装/卸载、Agent 模型切换、迁移、数据库恢复或生产数据写入。

### 11.5 每波必须执行的验证与证据

每个代码波次的通用命令：

```bash
git status --short
git diff --check
pnpm test
pnpm typecheck
pnpm build
.venv/bin/python -m pytest -q -ra
```

A0B-G、A3-G、A4-G、A6-G、A7-G 等涉及打包、宿主或安装状态的门禁另外执行：

```bash
docker compose config --quiet
docker compose ps
.venv/bin/python scripts/package_plugin.py
.venv/bin/python scripts/verify_qwenpaw_lab.py
```

执行规则：

- 子代理运行自己工作包的最小测试并返回原始结果；`INT/GATE` 由主 Codex 在集成树上重跑所有受影响测试。
- 后端数据库集成测试必须使用明确测试库；未配置时要报告 skipped 数量，不能把跳过写成通过。
- A0B/A3/A4/A6 的真实宿主验证必须保存唯一标记、Agent、session、安装版本和清理结果。
- A0A/A1/A5/A7 的浏览器证据必须记录实际像素尺寸；文件名不能替代图像真实尺寸。
- 1920×1080、2560×1440、200% 缩放、键盘、中文 IME、控制台和错误态证据按工作包落入证据目录。
- 每个 GATE 都要记录输入工作包、未通过项、降级决定和下一波 ready set；没有门禁记录不得只凭子代理口头结论继续。

## 12. 最终验收矩阵

### 12.1 依赖与安装

- [x] 模型计划已独立提交（0245bd1）。
- [x] 本地源码、安装容器和 verify 脚本运行策略一致；2026-08-25 复查通过。
- [x] 插件重装/升级后新工具、Hook 和前端扩展只注册一次。
- [x] 插件卸载后无 Hook、renderer、suggestion 和 context registry 残留。

### 12.2 UI 与原生聊天

- [x] 1920×1080 下章节树、正文和助手同时可用。
- [x] 2560×1440 下空间利用合理。
- [x] 大纲、角色、线索和设定页均完成弹性三栏。
- [x] 助手 320、380、动态最大宽度可用。
- [x] 助手折叠、刷新和恢复偏好正确。
- [x] 原生 Agent、模型、历史、输入、附件、工具调用和停止功能无回归。
- [x] 固定右侧章节工具不与助手重叠。
- [x] 普通聊天没有小说外壳。
- [x] 200% 缩放无关键操作丢失。

### 12.3 页面与会话感知

- [x] 所有页面和弹窗返回正确实体及字段集合。
- [x] 多字段表单不会只发送最后一个字段。
- [x] dirty、truncated、omitted 字段状态准确。
- [x] /chat 到 /chat/session 规范化不丢工作台。
- [x] 工作台新会话和主动普通聊天可以区分，或按批准降级执行。
- [x] 刷新、前进后退、关闭弹窗和切换作品无旧上下文。
- [x] 切换 Agent 后立即停止注入和直接应用。

### 12.4 数据边界

- [x] 小说内容以“待分析数据”注入，不冒充系统指令。
- [x] 原始 request_context 与注入后消息的留存路径都已经实测。
- [x] 若使用 context_ref，租用、幂等重入、FINALLY 清理、TTL、容量和重启失效正确。
- [x] context_ref 同源 POST、owner/tab/Agent/作品/session 绑定、大小/频率限制和不可枚举失效响应通过。
- [x] 若注入消息进入会话历史，专用工作台会话和作者提示已经验收。
- [x] 普通聊天、其他 Agent、长期 Memory、项目文件和无关日志不意外接收页面草稿。
- [x] 正式资料与未保存草稿有清晰来源标签。

### 12.5 选区、应用与撤销

- [x] 鼠标、键盘、长文本、换行、滚动、缩放和 IME 选区可用。
- [x] selection_id 绑定 Agent、Session、作品、字段、版本和哈希。
- [x] 等待期间内容变化会使旧卡片失效。
- [x] 替换只改变选区，插入只在选区后增加。
- [x] 正文应用后进入恢复草稿与自动保存。
- [x] 标题、章纲、人物、线索和设定应用后仍等待显式保存。
- [x] 每个字段可以撤销最近一次 AI 修改。
- [x] 过期、坏 JSON、超时、无工具调用和 renderer 失败均不误写。
- [x] 普通回复不会被自动解析写回。

### 12.6 正式资料工具

- [x] 无需复制 novel_id/document_id 即可读取当前范围。
- [x] document/entity/关系端点归属检查通过。
- [x] novel_id 属于服务端当前 owner，模型传入其他作品 UUID 不能绕过范围校验。
- [x] 返回 schema_version、as_of、provenance、truncated。
- [x] 无 N+1 查询。
- [x] Default 与 QA Agent 不启用新工具。
- [x] 旧工具和历史会话兼容。

### 12.7 工程质量

- [x] TypeScript 检查通过。
- [x] 前端单元测试通过。
- [x] 后端单元和配置数据库集成测试通过。
- [x] Vite 生产构建通过。
- [x] Docker 容器健康。
- [x] 浏览器控制台无新增 error/warn。
- [x] 100 次输入不触发 Inner 每键重渲染。
- [x] 快照构建 p95 不超过 50ms。
- [x] 前端 gzip 增量不超过 40KB。
- [x] git diff --check 通过。
- [ ] 每阶段有独立提交、证据和可恢复点。证据与恢复点已齐；当前工作区尚未获本轮独立提交/推送授权，因此提交项不得勾选。

### 12.8 AI 质量

- [x] 三种题材完成规定操作矩阵。
- [x] replacement_text 不含无关解释或 Markdown 围栏。
- [x] 关键事实、人称、时态和人物关系不被无意改变。
- [x] 助手能区分正式事实、草稿和创作假设。
- [x] 资料不足时说明限制，不虚构数据库事实。
- [x] 章节标题基于本章正文证据并完成书内重复/近重复检查，不再由书名联想命名。

## 13. 风险与降级

| 风险 | 验证 | 降级 |
| --- | --- | --- |
| Inner 在 320–520px 不可用 | 阶段 0 窄容器尖峰 | 右侧覆盖抽屉；仍使用原生 Inner |
| requestPayload 无法到达 Hook | 唯一标记回显 | 显式可见上下文提示或工具读取 |
| 原始 request_context 被持久化 | 原始标记在历史、state、日志、trace 中取证 | context_ref 内存注册表 |
| 注入消息进入 Agent 会话状态 | 注入标记在 history/state 中取证 | 专用工作台会话；仅显式动作发送 dirty 草稿 |
| 裸 `/chat` 无法单独区分宿主新会话与普通聊天 | RouteSessionStateMachine + 2026-08-25 真实回归 | 同一运行期 owner + tab owner/novel 双匹配时保留工作台；fresh/direct `/chat` 与显式普通导航清理 |
| textarea 几何不稳定 | 滚动、缩放、IME 实验 | 工具条锚定字段边缘 |
| toolRender 无法安全应用 | session/message/selection 尖峰 | 只显示和复制，不直接应用 |
| 受控表单回写失败 | Adapter 尖峰 | 对该字段只复制，暂不开放应用 |
| 等待期间内容变化 | 哈希与范围校验 | 卡片失效并要求重新框选 |
| Agent 切换或并发响应 | Agent/session 绑定 | 只允许复制 |
| 上下文过大 | 总预算与去重 | 只保留定位和选区，正式资料走工具 |
| QwenPaw 升级破坏契约 | 重跑阶段 0 | 禁用助手扩展，保留工作台与数据 |
| 后续助手改动破坏已冻结模型跟随契约 | 复跑模型编排、Agent 配置和 verify 测试 | 暂停冲突工作包；只消费 effective-model 公共契约，不重开固定模型或双轨路径 |

## 14. Git 提交顺序

1. docs: validate qwenpaw assistant plan v2
2. test: spike qwenpaw assistant contracts
3. docs: record assistant integration adr
4. feat: restore native qwenpaw assistant pane
5. feat: add workbench route and field adapters
6. feat: add novel assistant context protocol
7. feat: inject ephemeral workbench context
8. feat: add unified novel workspace context tool
9. feat: add selection proposal and apply workflow
10. test: verify assistant aware workbench

每次提交前：

- 明确 git diff 中只包含当前阶段。
- 不重开模型计划语义，不混入用户其他修改。
- 运行对应测试、类型和 diff check。
- 保存浏览器证据。
- 记录已知降级。

## 15. V2 自查与批准结论

### 15.1 七个 P0 回查

本节的 `[x]` 表示“计划已经覆盖该问题”，不表示对应功能已经实现；真实解除状态以第 2 节和阶段 GATE 为准。

- [x] 协议已覆盖完整实体与多字段编辑。
- [x] 阶段 0 已实测选择公开 Middleware；真实不执行的 Hook 不接生产。
- [x] 所有写回必须通过受控字段 Adapter。
- [x] 正文自动保存与显式保存表单已经分开。
- [x] 增加 RouteSessionStateMachine 和无法区分时的明确降级。
- [x] 已分开验证原始 request_context 与注入消息，冻结工作台会话披露 + 短期内存 context_ref。
- [x] 模型计划提交、安装和 verify 一致性已经实测闭环，P0-7 解除。

### 15.2 P1 回查

- [x] 增加全局预算、优先级和去重。
- [x] 增加 selection TTL、容量、Agent/session 绑定、UTF-16 和 SHA-256。
- [x] 增加版本化提案 schema。
- [x] 增加 prompt/content 数据隔离。
- [x] 增加模型不调用工具和 renderer 失败降级。
- [x] 增加 Agent 切换和并发响应处理。
- [x] 增加无障碍、200% 缩放和 IME。
- [x] 增加可量化性能门槛。
- [x] 把链路正确性与文学质量拆分验收。
- [x] 增加正式资料 provenance、as_of、截断和查询预算。
- [x] 增加动态 suggestion 注销。
- [x] 明确选区动作可能仍需要一次用户发送。

### 15.3 最终施工审计结论

| 审计角度 | 结论 | 最终事实或保留边界 |
| --- | --- | --- |
| 目标与非目标 | ✅ | 复用原生聊天、不改 QwenPaw 核心、作者显式应用；未扩大到手机版或第二套 Runtime |
| 当前工程事实 | ✅ | HEAD 仍为 a4007ab；A1–A7 是已验收但尚未获提交授权的工作区候选，effective 模型为 MiniMax-M3 |
| 阶段门禁 | ✅ | A0A–A7 逐门通过；[A7-G](./证据/助手计划V2验证-2026-08-25/A7-GATE.md)汇总全部前序门禁 |
| 串并行依赖 | ✅ | 公共契约先冻结，独立工作包并行，入口、样式、插件状态、数据库和最终验收由单一 Owner 串行汇合 |
| 文件冲突 | ✅ | 共享文件按 Owner 汇合；用户朗读设计稿与关系网数据库备份未触碰 |
| 数据与隐私 | ✅ | context_ref 租约、限流、绑定、清理及会话披露通过；不宣称零留存 |
| 状态、保存与撤销 | ✅ | 正文自动保存、显式表单 dirty、替换/插入、冲突、撤销和失败降级均以真实页面复验 |
| 路由与会话 | ✅ | 深链、session 规范化、前进后退、切书、普通聊天和非目标 Agent 隔离通过 |
| UI 与可访问性 | ✅ | 精确 1920×1080、2560×1440、320/380/动态宽度、折叠、200% 缩放、键盘与 IME 通过 |
| 工具与 Agent 作用域 | ✅ | 目标 Agent 为 6 Skills / 5 tools；Default、QA 为 0；安装、卸载、重装无残留 |
| 测试与交付 | ✅ | 前端 231 项、隔离数据库后端 216 项、typecheck/build/package/verify/Compose 全部通过；Git 发布待独立授权 |
| AI 质量 | ✅ | 三题材矩阵通过；标题命名已改为“本章正文证据 + 全书章名去重”，禁止书名充当词库 |

本轮最终解决了计划与施工两层问题：七个 P0、原生聊天组合、弹性工作台、页面上下文、受控字段、正式资料工具、结构化提案、安装卸载和真实模型质量均已闭环。真实验收又发现并修复了宿主 renderer 封装、route 重挂载、弹窗层叠、焦点回归、IDE 审阅器层级和章节标题书名驱动等自动化桩未能提前暴露的问题。

### 15.4 最终批准

V2 是本目标 A1–A7 的唯一施工计划。A0A–A0D 的现实门槛和 A1–A7 的正式施工、逐环节真实测试均已有证据；A7-G 已通过，目标的技术与产品范围完成。

该完成结论不扩大范围，也不把 Git 管理动作写成已执行：当前候选尚未暂存、提交或推送，只有用户再次明确授权后才能进行精确提交与发布。未知未来 QwenPaw 版本仍需在本项目适配层复跑兼容门禁。
