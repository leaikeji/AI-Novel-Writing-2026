# UD5-CONTEXT-AUDIT：QwenPaw 注入上下文气泡公开折叠能力审计

- 日期：2026-08-25（Asia/Shanghai）
- 工作包：`UD5-CONTEXT-AUDIT`
- 审计对象：QwenPaw 2.1.0 + AI小说世界2026 PawApp
- 状态：**只读审计完成；公开气泡 renderer 存在，但当前公开契约不足以可信地只识别并折叠 Middleware 注入消息，因此尚不可进入生产施工。**
- 边界：未操作真实会话，未修改实现、QwenPaw 上游、私有 DOM/store/数据库或正式小说；本文件是本工作包唯一新增物。

## 1. 审计问题与判定标准

目标是判断：能否只使用 QwenPaw 2.1.0 已验证的公开扩展点，把 AI 小说工作台 Middleware 注入的 `role=user` 页面上下文在右侧原生聊天中折叠或隐藏，同时满足：

1. 模型继续收到完整页面上下文；
2. 不修改、复制、覆盖或 monkey patch QwenPaw 上游；
3. 不读私有 store/数据库，不依赖 DOM/CSS 选择器；
4. 不误隐藏作者自己的 user 消息；
5. 插件禁用/卸载后完整恢复原生聊天；
6. 只依赖可冻结、可测试的公开契约，不把一次运行中偶然出现的内部字段当作稳定 API。

审阅了以下本项目文件（全部只读）：

- `frontend/src/qwenpaw-host.d.ts`
- `frontend/src/assistant-host-contract.test.ts`
- `frontend/src/assistant-route-wrap.ts`
- `backend/assistant_context.py`
- `plugin.py`
- `tests/test_qwenpaw_integration_contract.py`
- `tests/test_assistant_runtime_hook.py`
- `docs/开发文档/ADR/ADR-0003-QwenPaw原生助手上下文与受控编辑边界.md`
- `docs/开发文档/证据/助手计划V2验证-2026-08-25/A0B-context-runtime.md`

外部一手来源固定到 QwenPaw `v2.1.0` tag，避免把 `main` 的新能力误算进目标版本：

- [QwenPaw v2.1.0 插件文档：Frontend Extension API](https://github.com/agentscope-ai/QwenPaw/blob/v2.1.0/website/public/docs/plugins.en.md)
- [QwenPaw v2.1.0 公开 TypeScript 契约](https://github.com/agentscope-ai/QwenPaw/blob/v2.1.0/console/src/plugins/types/qwenpaw.d.ts)

## 2. 已核实事实

### 2.1 当前注入消息确实是模型可见、历史可见的普通 user 消息

`AINovelPageContextMiddleware.on_reply()` 在上游输入最前方插入：

```python
Msg(
    name="system",
    role="user",
    content=[TextBlock(text=injection_text)],
)
```

`tests/test_assistant_runtime_hook.py` 对 `role == "user"`、`name == "system"`、上下文正文可见及输入顺序进行了断言。`plugin.py` 只通过公开 `PluginApi.register_middleware(..., priority=80)` 注册该生产链路，契约测试同时断言生产入口没有注册运行时 Hook。

ADR-0003 与 A0B 真实宿主证据已经确认：公开历史角色序列为 `user / user / assistant`，第一条 user 消息是注入上下文，第二条才是作者请求；注入消息在容器重启后仍恢复，MiniMax-M3 能读取其中唯一标记。离开工作台只能停止未来注入，不能删除或伪装删除既有历史。

### 2.2 `route.wrap` 只能包装页面，不能按消息识别或改写原生气泡

QwenPaw v2.1.0 文档把 `route.wrap(pluginId, targetId, wrapper)` 定义为页面组件 onion wrapper。项目当前 `assistant-route-wrap.ts` 也只把宿主 `Inner` 当作不透明 React 组件：

- 普通聊天直接 `return h(Inner)`；
- 工作台把同一个 `Inner` 交给右侧 `AssistantPane`；
- wrapper 没有公开的消息列表、单条 message identity 或 bubble renderer 参数。

因此 `route.wrap` 可以控制助手栏宽度、折叠和外围状态条，不能合规地只折叠其中某一条注入 user 气泡。对 `Inner` 做 DOM 遍历、CSS 选择器隐藏或复制消息列表，均超出本项目边界。

### 2.3 QwenPaw v2.1.0 **存在**公开 user-message renderer

官方 v2.1.0 插件文档的 “Message Bubble Customization” 明确给出：

```ts
window.QwenPaw.chat.request.render(
  pluginId,
  ({ data, fallback }) => ReactNode,
)
```

公开类型进一步定义：

- `chat.request.render()`：替换整条 user request card；
- `chat.request.prepend()` / `append()`：在 user 气泡前后插入内容；
- renderer 可以调用 `fallback()` 保留原生显示；
- 所有注册返回 `Disposable`，并可由 `chat.disposeAll(pluginId)` 清理。

因此，“QwenPaw 2.1.0 完全没有公开消息 renderer”是错误结论。项目本地 `qwenpaw-host.d.ts` 只声明了此前验证过的窄子集（`requestPayload`、`toolRender`、suggestion、dispose），没有声明官方 v2.1.0 已公开的 `chat.request` / `chat.response`。本地窄声明只能证明当前项目尚未接线，不能反向证明宿主没有该 API。

### 2.4 公开 renderer 缺少可信的“这是插件注入消息”判别字段

官方 v2.1.0 类型把 renderer 的数据定义为：

```ts
/** Opaque request/response data. Plugin authors can cast if they need strong typing. */
type ChatRequestData = Record<string, unknown>;
```

该公开契约没有冻结以下任一字段：

- message id / role / name；
- 消息来源 middleware、plugin id 或 source kind；
- 可验证的 `origin` / `presentation` metadata；
- content block 的稳定形状；
- “仅模型可见、默认不显示”的明确语义。

`backend/assistant_context.py` 虽然给 runtime-hook 尖峰定义过 `HOOK_SOURCE = "ai-novel-world-2026.page-context"`，但最终生产 Middleware 创建的 AgentScope `Msg` 只带 `name/role/content`，且现有证据没有证明某个可信 source metadata 会被保留并公开给前端 renderer。

### 2.5 `chat.toolRender` 不是普通 user 消息 renderer

官方文档把 `chat.toolRender(pluginId, toolName, renderer)` 限定为工具调用结果显示；项目当前也只用于工具结果卡片。Middleware 注入的是普通 `role=user` 消息，不是工具结果，不能借 `toolRender` 隐藏。

### 2.6 显示层 renderer 不应改变模型输入，但本项目尚未做该路径的真实宿主回归

**技术判断：** `chat.request.render` 属于浏览器前端显示扩展，而 Middleware 注入发生在后端 Agent 输入链路；只替换 React 气泡的设计目标不会删除后端历史或缩短模型输入。

**仍待验证：** 本项目没有对 `chat.request.render` 做目标版本真实宿主探针，因此不能把“注册后模型输入、历史、导出、刷新和卸载均完全不变”写成已验收事实。任何未来实现仍需以双标记和公开历史回归证明这一点。

## 3. 公开能力矩阵

| 公开扩展点 | 能否改变显示 | 能否只识别注入消息 | 是否影响模型完整上下文 | 本次裁决 |
| --- | --- | --- | --- | --- |
| `route.wrap("core.chat")` | 只能改变页面外围/布局 | 否；`Inner` 是不透明组件 | 不改变 | 保留现有三栏与整栏折叠，不能做单消息折叠 |
| `chat.request.render` | 是；可替换整条 user 气泡 | **公开契约未提供可信判别字段** | 技术上应只影响显示，尚待真实回归 | 有基础能力，但当前不足以生产接线 |
| `chat.request.prepend/append` | 只能在气泡前后加内容 | 同样缺少可信判别字段 | 技术上应只影响显示 | 不能隐藏原始正文 |
| `chat.requestActions.add` | 可加 user 消息动作 | 同样缺少可信判别字段 | 不改变 | 不能默认折叠/隐藏正文 |
| `chat.toolRender` | 是；仅工具结果 | 不适用于普通 user 消息 | 不改变 | 不采用 |
| `chat.requestPayload.add` | 改发送请求载荷 | 不负责历史气泡 | 可能改变请求 | 继续只用于 `context_ref`，不负责显示 |
| 私有 DOM/store/DB 或 CSS 选择器 | 表面上可能 | 不可靠 | 不可证明 | 明确禁止 |

## 4. 是否可施工

### 4.1 当前结论

**不能按生产功能直接施工。**

更精确地说：QwenPaw 2.1.0 已经公开了实现“折叠气泡外观”所需的 renderer，但没有公开一个稳定、可信、不可与作者消息混淆的注入来源标识。当前不能同时满足“只折叠插件上下文”和“仅依赖冻结公开契约”两项门禁。

以下做法均不获准：

1. 假定 opaque `data` 内一定存在某个未文档化字段；
2. 按当前 DOM 层级、class、文本节点或 CSS 选择器隐藏；
3. 仅凭注入前缀文本判断并隐藏；作者可以输入同样文本，且 content block 形状未被公开冻结；
4. 折叠所有 user 气泡；这会把作者请求一起隐藏并破坏原生聊天；
5. 复制/fork QwenPaw 消息列表或读取私有 store/数据库取得 message id；
6. 把历史已存在的注入消息描述为“已删除”或“零留存”。

### 4.2 可批准的后续只读/隔离尖峰

若后续计划显式批准，可在隔离 QwenPaw 2.1.0 环境对公开 `chat.request.render` 做一个窄探针，仅验证：

- 注册、dispose、插件卸载和普通聊天非回归；
- renderer 的实际调用次数及 `data` 顶层字段名/值类型，不采集正文；
- 注入消息、作者消息是否存在公开且不同的可信来源字段；
- 折叠显示后，MiniMax 模型读到的双标记、公开历史、刷新和重启结果是否不变。

但运行时偶然出现的字段仍不等于公开稳定契约；只有上游文档/类型冻结来源字段，或项目得到明确的版本锁定与降级裁决后，才能进入生产。

## 5. 若不可施工的合规降级

当前应保持 ADR-0003 的诚实边界：

1. 继续显示 `role=user` 页面上下文，不伪装删除；状态条保留“页面内容可能成为此工作台会话历史的一部分”。
2. 保留现有右侧助手整栏折叠；作者需要更大编辑空间时折叠整栏，而不是对原生消息做选择器隐藏。
3. 继续使用“专用工作台会话 + 短期内存 `context_ref`”：它降低原始 request payload 的错误日志/trace 暴露，但不声称消除已注入消息的历史留存。
4. 普通聊天、其他 Agent、跨书、跨 session、过期或无效 ref 均不注入；插件卸载后恢复原生聊天。
5. 如果可见上下文被判定为不可接受，唯一合规的现有降级是关闭自动页面注入，退回显式只读资料工具/作者手工发送；这会降低无感页面感知能力，属于产品/ADR 变更，不能在本工作包静默实施。

## 6. 需要上游新增的最小公开契约

### 6.1 首选：可信来源 metadata 贯穿后端消息与前端 renderer

最小增量不是新的聊天前端，而是在公共消息协议中增加不可由作者正文伪造、由宿主设置并透传的来源字段，例如：

```ts
interface ChatRequestData {
  id: string;
  role: "user";
  origin?: {
    pluginId: string;
    kind: string;
  };
}
```

后端公开 Middleware/Msg API 同时需要允许插件声明并由宿主保存：

```python
origin={
    "plugin_id": "ai-novel-world-2026",
    "kind": "page-context",
}
```

宿主必须保证：

- `origin` 由已注册插件/宿主产生，不能从作者正文解析；
- 同一字段进入公开 `ChatRequestData`，含义在 2.1.x 契约中冻结；
- `chat.request.render` 仍可调用 `fallback()`，且 dispose/卸载后恢复原生气泡；
- renderer 只改变显示，不改变消息历史、模型输入、导出和审计；
- 历史记录仍诚实存在，只是默认以“已附加页面上下文 · N 字 · 展开”呈现；键盘和读屏可展开。

### 6.2 次选：公开的 model-only context 通道

上游也可以提供明确的单轮 model-only context API，例如公开 `inject_context(..., presentation="hidden")`，并冻结其模型可见性、持久化、审计、导出、重放和错误 dump 语义。项目此前真实验证的 `register_runtime_hook(PRE_EXECUTE)` 在控制台链路执行次数为 0，因此不能把现有 Hook 尖峰当作该能力已经可用。

### 6.3 生产放行门禁

即使上游新增上述契约，项目仍需在隔离目标版本通过：

1. 注入消息只折叠，作者 user 消息保持原生；
2. 模型读取完整唯一标记；
3. 公开历史、刷新、重启和导出仍含完整消息；
4. 普通聊天和非目标 Agent 不出现小说上下文 UI；
5. dispose、禁用、完整卸载后无 renderer 残留；
6. 升级契约变化时自动降级为原生 `fallback()`，不能误隐藏消息。

## 7. 最终结论

### 已核实事实

- QwenPaw 2.1.0 有公开 `chat.request.render/prepend/append`；本地窄 `qwenpaw-host.d.ts` 尚未声明它们。
- `route.wrap` 只包装页面，`toolRender` 只渲染工具结果，均不能只处理 Middleware 注入的普通 user 消息。
- 生产 Middleware 把完整页面上下文作为 `Msg(name="system", role="user")` 注入；真实历史与模型都能看到它。
- 公共 `ChatRequestData` 是 opaque `Record<string, unknown>`，没有公开冻结的插件来源 discriminator。

### 是否可施工

- **显示层能力存在，但“只识别插件注入消息”的必要公开契约不存在；本轮不得直接实现生产折叠/隐藏。**

### 合规降级

- 保留真实可见消息、留存提示、专用工作台会话、短期 `context_ref` 和整栏折叠；若不可接受可见消息，则经 ADR 裁决关闭自动注入并退回显式资料工具。

### 上游最小契约

- 首选给消息增加宿主可信、公开稳定并透传到 `ChatRequestData` 的 `origin.pluginId/kind`；renderer 仅据此折叠显示。
- 备选提供语义明确、真实控制台链路可执行的 model-only context API，并公开冻结留存和审计语义。
