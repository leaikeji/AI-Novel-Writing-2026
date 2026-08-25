# A0B-G：QwenPaw 契约、运行时注入与留存门禁

- 日期：2026-08-25
- 输入工作包：A0B-1…A0B-8
- 结论：**通过，允许进入 A0C。**
- 限定：只证明公开扩展点、助手壳可行性、真实注入/留存和卸载重装；1920×1080 下工具轨重叠、编辑区空间与多页面弹性布局仍由 A0C/A1 负责，不能写成 UI 已完成。

## 1. 冻结的公开扩展点

- 前端：`route.wrap`、`chat.requestPayload`、`chat.toolRender`、`chat.suggestion`、`chat.disposeAll`。
- 原生助手：直接渲染宿主提供的 `Inner`，不复制聊天 UI、Agent、模型、历史、附件或工具执行。
- 后端注入：`PluginApi.register_middleware(factory, priority=80)`；真实宿主证明 `PRE_EXECUTE` Hook 在当前控制台链路不执行，因此不注册 Hook。
- 数据角色：页面上下文作为 `Msg(name="system", role="user")` 数据消息；作者文本不是系统/开发指令。
- 模型权威：`ai-novel-writer` 的有效模型，实测 `minimax-cn / MiniMax-M3`；没有第二个模型选择器或静默回退。

## 2. 助手壳真实浏览器结果

证据文件：

- `15-a0b-pane-1920x1080.png`
- `16-a0b-pane-2560x1440.png`
- `17-a0b-pane-collapsed-2560x1440.png`
- `18-a0b-uninstalled-native-chat-1920x1080.png`
- `19-a0b-reinstalled-pane-single-1920x1080.png`
- `20-a0b-pane-520-functional-proof-3200x1800.png`

已实测：

- 默认 380px；Home 到 320px；在足够宽的功能视口 End 到 520px。
- 折叠后原生 textarea 仍在 DOM（数量 1），只是不可见/不可交互；重新展开不重建会话。
- separator 具备 role、min/max/now；折叠/展开按钮具备可访问名称。
- 输入框可真实输入并清空，没有发送测试草稿。
- 重装后页面只有 1 个助手 aside、1 个 separator、1 个原生 textarea。

未通过的布局项：1920×1080 下章节树、中心编辑器、助手和旧固定工具轨发生挤压/重叠；2K 下空间明显改善但工具轨仍覆盖助手。这不是 A0B 壳可行性失败，已作为 A0C-6 与 A1-E 的硬验收项，A1-G 前不得放行。

## 3. MiniMax-M3 与双标记结果

最终源代码安装后的探针：

- session：`a0b-final-5088cc73-a362-4eb0-9ae9-da3f964d8862`
- 原始 marker：`anw-raw-8ccd03c643fee3d5544f3585940bd78d`
- 注入 marker：`anw-injected-294b6063d36459e7ce4d36394e73c858`
- 模型：`minimax-cn / MiniMax-M3`
- 模型回复：与注入 marker 完全一致。

留存取证使用较早的同构成功 session `a0b-retention-a77141bc-656f-4bad-b122-bf911ba5711a`：公开聊天历史为 `user / user / assistant` 三条，第 1 条 user 消息含注入标记，原始标记不在公开历史；容器重启后仍存在。普通 session 中两标记命中均为 0。已知隔离错误 dump 只出现原始 marker，普通服务日志均未命中；未配置 Langfuse/OTEL/trace。

决策：结果 C，后续必须使用**专用工作台会话**；A3 再实现**短期内存 context_ref**，以减少原始 payload 的错误落盘面。离开工作台只能停止新注入，不能声称已删除历史中的作者材料。

## 4. 卸载、重装与恢复

完整循环真实执行两次。最终一次自动循环结果：

- 卸载后：插件 0、PawApp 0、小说工具 0、插件 Skills 0、健康端点 404；新标签页为纯原生聊天，无小说外壳和助手 pane。
- 首轮重装发现既有 Agent 的插件工具 registry 不会自动恢复，安装脚本正确失败。
- 修复：重装后对既有 Agent 调用公开无损 `PUT /api/agents/{id}`，刷新物化工具 registry，再启用插件工具。
- 修复后：插件唯一计数 1；小说工具 3；插件 Skills 6；MiniMax-M3、system prompt 文件和既有聊天均保留。
- 重装唯一性模型探针：公开历史仅 1 条注入 user 消息，没有重复 Middleware。

没有删除 QwenPaw 数据卷、Agent workspace、聊天、小说数据库或备份。

## 5. 验证记录

- 前端：11 files / 50 tests；`pnpm typecheck`、`pnpm build` 通过。
- 助手运行时/留存/宿主契约：27 tests 通过。
- 安装全门禁：`82 passed, 21 skipped`；skipped 为既有条件测试，未计作通过。
- `scripts/verify_qwenpaw_lab.py` 通过。
- `git diff --check` 通过。

## 6. A0C ready set

A0C-0 可以冻结 Adapter、route、selection、geometry、registry、工具轨六类尖峰接口。A0C-G 前必须提供：普通聊天/工作台/刷新/前进后退路由证据，正文与显式保存表单回写证据，选区 TTL/哈希/几何证据，以及工具轨与助手零重叠证据。
