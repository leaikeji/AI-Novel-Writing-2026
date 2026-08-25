# A3-G：页面上下文注入门禁

- 状态：✅ 通过
- 日期：2026-08-25
- 范围：前端请求载荷、短期 `context_ref`、公开 Middleware、目标 Agent/session/作品绑定及普通聊天隔离。
- 真实模型：`minimax-cn / MiniMax-M3`。

## 通过结论

- 前端只发送冻结的 `NovelAssistantContextV2`；较大草稿先写入同源、短期、不可枚举的 `context_ref`，请求中仅传引用。
- 后端校验 owner、tab、Agent、session、作品、schema、TTL、大小和频率；租用后以 `finally` 释放，重启后旧引用失效。
- 生产链路使用 QwenPaw 公开 Middleware；未在真实链路执行的 Runtime Hook 没有接入生产。
- 注入内容以 role=user 的“待分析数据”进入目标工作台会话，不冒充系统指令；页面 UI 明示该工作台会话会携带当前草稿。
- MiniMax-M3 在真实章节页正确识别作品、章节和当前字段；切换到非目标 Agent 后不再注入，也不能直接应用提案。
- 普通聊天、其他 Agent、长期 Memory、项目文件和无关日志未发现页面草稿泄漏。

## 主要证据

- `A3-G-MiniMax-M3-页面感知-通过.png`
- `A3-G-非目标Agent-页面上下文隔离.png`
- [A0B 真实注入与留存记录](./A0B-context-runtime.md)

## 门禁结论

`A3-G` 通过。留存事实仍按 ADR-0003 执行：专用工作台会话披露，不宣称零留存。
