# T4-GATE-FE-API：章节朗读生产 API 契约证据

状态：**技术契约与 mock HTTP 客户端测试通过；尚未进行工作台接线或真实浏览器验收。**

验证日期：2026-08-27（Asia/Shanghai）。

## 1. 本工作包完成范围

- 新增严格、精确字段、fail-closed 的章节朗读生产契约解析器：
  - `DocumentNarrationContext`
  - `NarrationWorkflowResource`
  - `NarrationEditionResource`
  - `SwitchNarrationEditionResponse`
- Context 复用 `parseDocumentEditionHistory`，并继续核对外层 document／pointer／working copy、current／active、source snapshot、兼容状态、旧稿提示和可切换 Edition 列表。
- 新增章节生产 API 客户端：
  - `getDocumentNarrationContext(documentId, activeEditionId?, signal?)`
  - `getNarrationEdition(editionId, signal?)`
  - `createNarrationWorkflow(documentId, request, idempotencyKey, signal?)`
  - `getNarrationWorkflow(requestId, signal?)`
  - `switchNarrationEdition(documentId, request, signal?)`
- `Idempotency-Key` 只进入请求头；正文保存版本、正文哈希和设置版本继续留在精确 JSON 请求体。
- 生产 API 错误使用独立 `NarrationProductionApiError`，没有扩大既有 Settings `NarrationApiError` 的 code/detail 类型。
- 新增 `getNarrationScriptVersionForEdition(versionId, expectedScope, signal?)`：允许从严格响应中发现 `script_id`，但必须核对 novel、document、revision、source hash 和 ScriptVersion。

明确未做：后端、数据库、迁移、工作台入口、根导出、UI、样式、播放器、编辑器、真实浏览器及真实 HTTP 服务接线。

## 2. 自动化覆盖

- 成功资源缺字段或多字段均拒绝。
- Workflow 的 `analyze_only` 生产资源隔离、job ID 唯一性。
- Edition 句段状态计数上界。
- Context 嵌套 history、active/current/source snapshot、兼容状态和可切换集合漂移。
- 无当前 Edition 时保持未绑定，不静默选择历史版本。
- 切换请求 `confirmed` 必须精确为 `true`，拒绝 `false`、`1`、字符串和 `null`。
- Idempotency-Key 仅在 header，body 注入伪字段会在网络 I/O 前失败。
- 切换响应 target、CAS pointer、mode、start/progress 漂移均拒绝。
- Edition ScriptVersion 跨 novel／document／revision／source hash／version 均拒绝。
- AbortSignal 透传到 QwenPaw host fetch。

## 3. 原始验证命令与结果

相关契约/API Vitest（包含复用的 Edition history 回归）：

```bash
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  /Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm \
  exec vitest run \
  frontend/src/narration/chapter-contracts.test.ts \
  frontend/src/narration/api.test.ts \
  frontend/src/narration/script-api.test.ts \
  frontend/src/narration/edition-history.test.ts
```

原始计数：

```text
Test Files  4 passed (4)
Tests       55 passed (55)
```

全量 TypeScript 类型检查：

```bash
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  /Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm \
  typecheck
```

结果：`tsc --noEmit` 退出码 0，无诊断输出。

## 4. 剩余门禁

- 本工作包只证明 TypeScript 契约、作用域校验和 mock `window.QwenPaw.host.fetch` 请求行为。
- 未进行真实浏览器、真实 PostgreSQL、真实章节工作台或真实音频播放验收。
- 根导出和工作台消费由唯一集成 Owner 串行完成；在其完成前，不把本证据表述为章节朗读 UI 已可用。
