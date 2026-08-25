# A0B-3 / A0B-4 / A0B-7：页面上下文运行时与留存尖峰

- 日期：2026-08-25
- 工作包：A0B-3、A0B-4、A0B-7
- 状态：**A0B-G 已完成真实宿主、MiniMax-M3、双标记留存及卸载/重装验证；最终选择公开 Middleware 注入。**
- 边界：仅使用 QwenPaw 公开 PawApp、PluginApi、HTTP、Hook/Middleware 契约和隔离探针会话；未修改 QwenPaw 核心、私有配置或私有数据库，也未写入任何正式小说。

## 1. 环境与可复核来源

### 已核实事实

隔离运行容器：`ai-novel-2026-qwenpaw-lab`。

- QwenPaw：`2.1.0`
- AgentScope：`2.0.4.post1`
- `qwenpaw/plugins/api.py`：`c1bfc5dcb444dc1979551c296d6a52b17b865653df80d520917006018adf92de`
- `qwenpaw/runtime/hooks.py`：`328e9f358facb1e4bdc60579faf15ca4a03a8ffa67c6788d8cb2cbb48f870bf5`
- `qwenpaw/runtime/runtime.py`：`00c23d94f9066346ab1f9e3f2cb95e3a2f7fe3dd8b18a6030bbad05cf12ea1db`
- `qwenpaw/hooks/session/session_hook.py`：`43d78bb982af1de21f0f3dd5e6910f2766a21d68b384fd8418c9ad28f635dcc6`
- `qwenpaw/app/routers/console.py`：`1e680b70e8bb58e0384fed4a656c59f5cbd0053a3a17a5b6bcc50c348376d8ff`
- `qwenpaw/app/chats/query_error_dump.py`：`0ce485be9d25295954d7e6962a7661db37b293d211ff29dd779bd86a9f88a48d`
- `agentscope/agent/_agent.py`：`c98fadccfdfa09a021a86aec619a31afb9a50836637d1c1b2dc387cacd9d1f1d`

以上是已安装公开包的只读文件摘要，不是把 QwenPaw 源码复制进本项目的依据。

## 2. A0B-3：request_context → 运行时注入校验链

候选字段固定为：

```text
AgentRequest.request_context["ai_novel_context"]
```

值兼容两种前端/宿主边界形态：

1. JSON 字符串，优先匹配 QwenPaw `request_context: dict[str, str]` 的窄契约；
2. 已解析映射，只用于宿主把前端对象保持为对象的兼容情况。

两种形态进入同一校验器，不存在第二套运行时或第二套业务协议。

### 注入前强制条件

- `HookContext.agent_id == "ai-novel-writer"`；
- `root_agent_id` 为空或同为 `ai-novel-writer`，不向其他根 Agent 的嵌套调用泄漏；
- payload、AgentRequest 与 HookContext 的 `session_id` 必须一致，缺失也拒绝；
- `schemaVersion == 2`；
- 作品、页面、预算和字段快照具备最小合法形态；
- 当前页面 section 仅允许 `chapters / outline / roles / clues / settings`；
- 快照有效期不超过 20 分钟，允许最多 60 秒时钟偏差；
- 完整注入文本不超过 24,000 字符，选区不超过 12,000 字符；
- 坏 JSON、非目标 Agent、session 不匹配、过期、未来时间、超预算和畸形字段均不注入。

注入内容明确标为 `role=user` 数据，声明作者材料不是系统/开发指令，并区分未保存草稿与正式资料。作者文本中的包装结束符会被 JSON Unicode 转义，不能提前闭合数据段。

同一校验器可供 Hook 或 Middleware 工厂调用。最终实装的 Middleware 只在工厂校验通过后，于 `on_reply` 最前方追加一条 `Msg(name="system", role="user")` 数据消息；不会改请求载荷、正式小说、Agent 人设或长期 Memory。

## 3. A0B-4：runtime hook 与 middleware 比较

| 维度 | PRE_EXECUTE runtime hook | AgentScope middleware |
| --- | --- | --- |
| 官方入口 | `PluginApi.register_runtime_hook()` | `PluginApi.register_middleware()` |
| 页面快照入口 | 直接读当次 `HookContext.request.request_context` | 工厂在 AgentBuilder 阶段读 ctx，再创建 middleware |
| 注入能力 | `HookContext.inject_context()` 是专用公开契约 | 需要实现 AgentScope `MiddlewareBase` 并改写 reply/reasoning 输入 |
| 生命周期 | 明确绑定单次 Runtime 请求和 PRE_EXECUTE | 进入 AgentScope 洋葱链，可能覆盖 reply、reasoning、acting 多层 |
| 依赖面 | QwenPaw HookBase / Phase / HookContext | QwenPaw 工厂 + AgentScope middleware 类型和回调协议 |
| 重复注入风险 | 每个 Runtime 请求执行一次，来源和 priority 可审计 | 若挂错回调，可能在多轮 reasoning 重复附加 |
| 留存影响 | 见第 4 节；并不天然“只在内存” | 同样不能天然消除 Agent state 留存 |

### 真实决策

**最终选择公开 `PluginApi.register_middleware()`，不注册 runtime hook。**

真实 QwenPaw 2.1.0 控制台请求中，`register_runtime_hook()` 返回且插件正常加载，但隔离探针确认 `PRE_EXECUTE` Hook 运行次数始终为 0，MiniMax-M3 也读不到注入标记。切换为公开 Middleware 工厂后，同一请求的校验结果为 `injected`，`on_reply` 只执行一次，MiniMax-M3 原样回复 `anw-injected-*` 唯一标记。

这不是修改 QwenPaw 核心，也不是复制第二套 Agent Runtime；它使用 QwenPaw 2.1.0 文档化的 Middleware 工厂扩展点。重装后的隔离会话只有 1 条注入 user 消息，证明没有重复注册。

## 4. A0B-7：双标记留存结论

### 已核实事实：原始 request_context 存在落盘路径

QwenPaw 控制台路由会把 `request_context` 保留在 native payload，再恢复到 `AgentRequest.request_context`。错误规范化路径调用 `write_query_error_dump()`，其中 `_request_to_dict()` 会序列化完整 AgentRequest，并写入临时 JSON。

因此，即使普通成功请求未把原始 payload 写入聊天历史，**直接 JSON 也不能被声明为“必定不落盘”**；错误路径已经是可核实的原始载荷留存面。

### 已核实事实：注入消息进入公开聊天历史并在重启后恢复

最终成功探针会话 `a0b-retention-a77141bc-656f-4bad-b122-bf911ba5711a` 使用两个不同标记：

- 原始 request_context：`anw-raw-0f308ce2607db4c3a67ec10019454f80`；
- Middleware 生成消息：`anw-injected-c117ad9fe02c4147dd7374cecf083e44`。

MiniMax-M3 原样回复注入标记。公开 `GET /api/chats/{id}` 返回 3 条消息，角色为 `user / user / assistant`；第 1 条 user 消息包含注入标记，第 2 条才是带 `external_user_query` 标签的作者请求，原始标记不在公开历史。容器重启后仍为 3 条消息且注入标记仍在，证实结果 C。

### 技术判断

- 计划决策树应按“结果 C”处理：**使用专用小说工作台会话并明确提示页面内容可能进入该工作台会话历史/state**。
- 仅使用 `context_ref` 不能消除注入消息进入 Agent state；它只能减少原始 payload 在请求、错误 dump、日志或 trace 中暴露的范围。
- 因原始 request_context 已有错误 dump 留存面，后续 A3 的推荐组合是：**专用工作台会话 + 短期内存 context_ref**。context_ref endpoint、租用、TTL、限流、FINALLY 清理和重启失效必须另行通过 A3-C/D；本尖峰没有提前创建 registry。
- 页面草稿不得写入 Agent 人设、长期 Memory 或本项目开发文档。

### 其他真实留存面

- 已知隔离错误 dump `/tmp/qwenpaw_query_error_2edz8aa2.json` 中只匹配原始标记 `anw-raw-a594a85b97fbda19cdbb20c2c15d0f78`，没有注入标记，证明原始 request_context 存在错误落盘面。
- 成功标记和错误标记在容器普通日志中的精确命中数均为 0。
- 运行环境没有 `LANGFUSE`、`TRACE` 或 `OTEL` 配置项，也没有公开 trace/export 接口；未越界读取私有数据库或私有内部状态。
- 普通隔离会话 `a0b-normal-994ef76f-173b-40ad-b43d-aed57eb2c522` 使用同一 Agent 和 MiniMax-M3，但不携带 request_context；公开历史中两种成功探针标记命中数均为 0。

因此最终留存方案冻结为：**专用小说工作台会话 + A3 短期内存 context_ref**。context_ref 只降低原始载荷的错误日志/trace 暴露，不能替代专用会话隔离。

## 5. 可执行验证

已执行：

```bash
.venv/bin/python -m pytest \
  tests/test_assistant_runtime_hook.py \
  tests/test_assistant_context_retention.py -q
```

当前结果：`18 passed`（运行时/留存两文件）。

相关宿主契约回归一起执行：

```bash
.venv/bin/python -m pytest \
  tests/test_assistant_runtime_hook.py \
  tests/test_assistant_context_retention.py \
  tests/test_qwenpaw_integration_contract.py -q
```

当前结果：`27 passed`；完整安装门禁为 `82 passed, 21 skipped`，跳过项均为未提供外部数据库/宿主条件的既有条件测试，未伪报通过。

覆盖：有效唯一标记注入、公开 Middleware 单次前置、非目标/嵌套 Agent、三重 session 绑定、坏 JSON、schema、超限、页面与选区过期/未来/过长 TTL、12,000 字选区、作者包装符、原始对象不变、两标记三分支留存判定。

## 6. 主集成唯一接线点

A0B-G 通过并由主 Codex 独占修改 `plugin.py` 时，唯一接线形态为：

```python
from .backend.assistant_context import create_ai_novel_page_context_middleware

# AINovelWorldPlugin.register(api) 内，仅注册一次
api.register_middleware(
    create_ai_novel_page_context_middleware,
    priority=80,
)
```

A0B-8 已确认卸载后插件/PawApp/工具/Skills 全部归零；重装后插件唯一、3 个工具和 6 个 Skills 恢复。既有 Agent 需要通过公开 `PUT /api/agents/{id}` 做一次无损刷新，安装脚本已补此步骤并验证不改变 MiniMax-M3、system prompt 文件或既有聊天。
