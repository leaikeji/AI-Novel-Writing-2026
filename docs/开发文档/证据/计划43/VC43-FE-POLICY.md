# VC43-FE-POLICY — 章节向导状态机

状态：**PASS**

日期：2026-08-31（Asia/Shanghai）

- 新增可单测的 `idle/loading/ready/failure` 决策与结构化 API 错误解析。
- 每次首开、重试、重开或切书均使用不复用的 `requestGeneration`；Abort 或过期响应不得覆盖当前状态。
- 无分卷的外部打开 signal 也不会发起草稿请求。
- 关键文件：`frontend/src/chapter-creation-policy.ts` 及其测试。
- 定向 Vitest 与前端全量 1015 项测试均通过。
