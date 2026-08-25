# A0C-G：前端可行性尖峰门禁

- 日期：2026-08-25
- 输入工作包：A0C-0…A0C-6
- 结论：**通过，允许进入 A0D 串行冻结。**
- 限定：本门禁证明状态机、受控字段接口、选区注册与保守定位、工具轨布局算法可以实现；页面级字段接线和工具轨视觉迁移仍属于 A1/A2/A5/A6，不能写成正式 UI 或完整应用闭环已经完成。

## 1. 路由与会话状态机

唯一权威实现为 `frontend/src/workbench-route.ts` 的 `RouteSessionStateMachine`，状态固定为：

- `ordinary-chat`
- `workbench-no-session`
- `workbench-session`
- `leaving-workbench`

标签页 owner token 使用 Web Crypto 随机数，只保存在 `sessionStorage`。裸 `/chat`、不匹配的原生会话路径和无法用公开能力区分的“新会话”均清理 owner 并降级普通聊天，不猜测宿主私有状态。

真实浏览器结果（实际图像均为 2560×1440）：

- `21-A0C-workbench-deeplink-2560x1440.png`：带作品/文档参数的深链进入章节工作台。
- `22-A0C-session-path-preserved-2560x1440.png`：宿主从 `/chat?...` 归一化到真实 `/chat/{session}` 后，章节树与原生助手仍保留。
- `23-A0C-bare-chat-clears-workbench-2560x1440.png`：进入裸 `/chat` 后只剩原生聊天；随后后退、前进均未误恢复工作台。
- `24-A0C-return-center-clears-state-2560x1440.png`：从章节页返回列表并点击“返回创作中心”后，工作台与助手包装均清理。

路由单测 12 项覆盖进入、会话路径归一化、直接切换会话、刷新、深链、前进/后退、切书和清理。

## 2. 正文与显式保存表单 Adapter

- 正文 Adapter 只能调用受控 `applyEditorContent`，随后复用页面自动保存回调；禁止 DOM 直接写值。
- 表单 Adapter 只能更新受控 draft 并标记 dirty，不暴露保存 callback，原保存按钮仍是唯一持久化入口。
- 两者都在应用前核对全文 SHA-256，并在异步哈希后复查 getter，阻止作者输入竞态和旧基线覆盖。
- before/after 值、哈希、选区和 dirty 回执足以供正式 `AIEditTransaction` 建立单步撤销。
- 8 项 Adapter 测试覆盖应用、自动保存请求、dirty、不越过保存按钮、冲突、受控状态拒绝、焦点/选区恢复和基于回执的撤销原型。

## 3. Selection Registry 与几何决策

- Registry 使用 Web Crypto UUID 和 SHA-256；默认 TTL 20 分钟、容量 50、FIFO 淘汰。
- 记录绑定 Agent、作品、文档、字段、上下文 revision 和首次 session；禁止跨会话改绑。
- 工具卡片应用前重算字段哈希；过期、切书、字段销毁、scope/revision 变化或内容变化均拒绝。
- 几何尖峰覆盖滚动、缩放、高 DPI、长行、换行和 IME 风险。由于尚无全部真实浏览器探针连续稳定证据，A0D 必须冻结为 **`field-anchor`**，不得宣称 textarea mirror 可以精确贴选区。

## 4. 工具轨迁移实验

`assistant-tool-rail.ts` 的纯布局算法按中心区与助手边界计算：空间足够时使用编辑器右缘纵向工具轨，空间不足时降级为中心区底部横向 footer；强制 `railRight <= assistantLeft`，并提供方向键 roving focus。

本阶段没有改写共享 `styles.ts` 或页面根组件。因此“现有黑色固定工具轨仍可能覆盖助手”继续是 A1-E/A1-G 的硬门槛；A0C 只放行该正式迁移工作，不把算法单测当作视觉验收。

## 5. 验证记录

- A0C 相关：6 files / 49 tests 通过。
- 前端全量：18 files / 101 tests 通过。
- `pnpm typecheck`：通过。
- `pnpm build`：通过；`frontend/dist/index.js` 1,773.53kB，gzip 660.67kB。
- 真实 PawApp 重装门禁：82 passed、21 skipped；跳过项未计作通过。
- 重装后 Agent 有效模型：`minimax-cn / MiniMax-M3`；小说 Skills 6、既有小说工具 3，均保持原作用域。
- `git diff --check`：通过。

## 6. A0D ready set

A0D 必须串行冻结以下事实后才能进入正式功能施工：

1. 原生 `Inner` + 公开 Middleware + `role=user` 数据消息；专用工作台会话与短期内存 `context_ref`。
2. `NovelAssistantContextV2` 的 schema、总预算、裁剪、去重、过期和草稿标记。
3. `EditableFieldAdapter`、正文自动保存、表单显式保存、`AIEditTransaction` 与冲突/撤销语义。
4. selection/proposal 的 Agent/session/字段/revision/hash/TTL 绑定，以及 `field-anchor` 降级。
5. 工具轨正式迁移仍为 A1-E/A1-G 必过项。
