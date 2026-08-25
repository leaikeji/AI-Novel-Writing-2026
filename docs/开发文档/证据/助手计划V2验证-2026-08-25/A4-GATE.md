# A4-G：正式资料读取工具门禁

- 状态：✅ 通过
- 日期：2026-08-25
- 范围：统一资料聚合服务、`novel_get_workspace_context`、归属校验、来源/时间/截断证据、Agent/Skill 作用域与旧工具兼容。
- 真实模型：`minimax-cn / MiniMax-M3`。

## 通过结论

- `novel_get_workspace_context` 无需模型复制 `novel_id`/`document_id`，由服务端当前 owner、Agent、session、作品和文档范围解析。
- 返回 `schema_version`、`as_of`、`provenance`、`truncated`、`warnings` 和预算信息；总体大纲、人物、关系、故事线、伏笔、设定按允许类别聚合。
- document/entity/关系端点均做同作品归属校验；模型传入其他作品 UUID 不能绕过服务端范围。
- 查询预算、截断、跨书、旧工具兼容和无 N+1 行为有自动化测试；三个既有只读工具继续可用。
- 最终目标 Agent 共启用 6 个小说 Skills 与 5 个小说工具；Default、QA Agent 均为 0。
- MiniMax-M3 在真实工作台会话中单次调用工具并正确引用当前作品资料。

## 标题命名窄上下文

标题编辑可显式请求 `include=["chapter_naming"]`：只返回当前章节 bounded working copy 与全书章名索引，不返回其他章节正文。标题必须从本章事件/转折/钩子/独特物件提炼并做书内去重，书名不能充当标题词库。

## 主要证据

- `A4-G-MiniMax-M3-资料工具-单次成功.png`
- `A7-标题命名-01-MiniMax正文证据去重.png`

## 门禁结论

`A4-G` 通过；资料不足或截断不足以支撑结论时，Agent 必须说明限制，不得虚构数据库事实。
