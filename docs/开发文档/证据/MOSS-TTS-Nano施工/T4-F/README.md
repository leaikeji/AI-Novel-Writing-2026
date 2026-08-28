# T4-F CodeMirror 编辑器桥与 textarea 降级

状态：**`IMPLEMENTED_CANDIDATE_WITH_MAIN_WIRING_AND_BROWSER_HOLDS`（2026-08-27）**。CodeMirror 6 adapter、统一 `NarrationEditorBridge` 和保守 textarea fallback 已实现，38 项隔离测试及全局 TypeScript 检查通过；现有工作台的唯一保存链接线、真实系统中文 IME 与目标分辨率浏览器检查仍须主集成/T4-GATE。

## 1. 冻结行为

- `DocumentLease(documentId,generation)`、`isLeaseCurrent()` 与 `dispose()` 共同拒绝旧章节 timer/response/播放完成回写。
- 只有 CodeMirror `update.docChanged` 或 textarea 实际 value 变化产生 `OnEditorDocChanged`；decoration、selection、focus、scroll、gutter、seek 与 follow 的正文写入次数为 0。
- composition 期间不装 decoration、不滚动、不抢焦点，只保留最后一个待跟随句段；composition 结束后再应用。
- 普通正文点击只移动光标，不触发跳播；显式 gutter/命令意图由后续 T4-G 接入。
- UTF-16 范围严格验证；正文/Edition 不一致时不猜相似文本。
- textarea fallback 不伪装 editable decoration 或 gutter 能力。

## 2. 实际验证

```text
pnpm exec vitest run \
  frontend/src/narration/editor-bridge.test.ts \
  frontend/src/narration/editor-codemirror.test.ts \
  frontend/src/narration/editor-textarea-fallback.test.ts

3 files passed
38 tests passed

pnpm typecheck
PASS
```

## 3. 主集成 HOLD

- `OnEditorDocChanged` 必须只接现有唯一 `commitEditorValue(event)`；旧 React `onChange` 不得保留为第二套 recovery/debounce/save 链。
- AI apply/undo 与 recovery restore 必须经 adapter `setValue(nextValue, origin)`；切章保存屏障完成后先使旧 lease 失效并 dispose，再挂载新 generation。
- Manifest snake_case 到 Bridge 内部 camelCase 的转换只能发生在入口边界，`sourceText` 必须来自 hash 已核对的批准脚本。
- `narration/index.ts`、workbench、styles 和真实 DOM 尚未接线；仅验收 1920×1080 与 2560×1440，低于 1920×1080 不在本专项范围。
- 固定宿主 Blob/CSP、长章、系统中文候选窗、键盘/焦点/ARIA 和 textarea 回退切换仍须 T4-GATE。

## 4. 文件摘要

```text
frontend/src/narration/editor-bridge.ts                    54c7c79c824a84677d40001ab39b161b0e797b8a18c372d0f7dc2628b59339a7
frontend/src/narration/editor-codemirror.ts                b7dcb7be1f1f6af853597006a511429ae6726e2d6434b91f7d42928083490cb4
frontend/src/narration/editor-textarea-fallback.ts         bf41f4f2fe7270726d09d0116f0fca29ed8bb931d520983e5b6c42596de79141
frontend/src/narration/editor-bridge.test.ts               3a49bdff83326cf2d06379c052623f7faeee02a712f69a209ca75480c8750a4d
frontend/src/narration/editor-codemirror.test.ts           db5836d898b357d906a57b8d8e68d442beb2409e238cc13f0437c715b8945b62
frontend/src/narration/editor-textarea-fallback.test.ts    84cb9dcb4de80db3a27853b8a7cef1b4e2216512ae468be1c81ce067b4123665
```
