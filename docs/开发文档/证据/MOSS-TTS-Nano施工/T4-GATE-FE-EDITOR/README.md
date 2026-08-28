# T4-GATE-FE-EDITOR 章节正式编辑器表面候选

状态：**`IMPLEMENTED_CANDIDATE_WITH_WORKBENCH_AND_BROWSER_HOLDS`（2026-08-27）**。CodeMirror 6 主编辑器、同一容器内的真实 textarea 降级、`NarrationEditorBridge`、助手 selection/focus 控制和单次 `docChanged` 入口已经收敛到统一 `ChapterEditorSurfaceHandle`。本工作包没有修改 Workbench、朗读会话、播放器面板、样式总入口、根依赖锁或后端，也没有启用产品 capability。

## 1. 冻结结果

- `createChapterEditorSurface()` 先创建 CodeMirror；只有 CodeMirror 构造真实抛错时才清理该次新增 DOM，并在同一 `parent` 内创建 textarea adapter。原有容器子节点不被删除。
- `ChapterEditorSurfaceHandle` 暴露 `kind`、`bridge`、`assistantControl`、`readValue()`、`setValue()`、`focus()` 和幂等 `dispose()`；CM 与 textarea 使用同一个对外端口。
- `assistantControl.selectionStart/selectionEnd/selectionDirection` 始终读取实际 CodeMirror selection 或 textarea selection；`setSelectionRange()` 与 `focus()` 操作实际编辑控件。
- CodeMirror 行号只保留视觉编号，已删除“任意行号点击即播放”的事件。普通正文点击只产生 caret/selection 行为，不发出播放 intent；正式段落 gutter 必须由 `paragraph-gutter.ts` 后续独立接线。
- CM/textarea 的输入、组合输入、undo/redo 和外部 `setValue()` 每次正文变化只调用一次 Bridge 交易、一次 `OnEditorDocChanged`。textarea 根据原生 `inputType=historyUndo/historyRedo` 保留 undo/redo origin。
- selection、caret、手动滚动和 composition 会暂停 Bridge 自动跟随并通知可选 `onAuthorInteraction`；focus/blur 只通知 `onFocusChange`。
- decoration、当前句段高亮、程序滚动和助手 selection presentation 均使用展示交易，不产生正文变化或保存回调。
- textarea 是唯一 DOM 输入 Owner；统一表面不再额外挂 React `onChange`，因此不存在 adapter 与受控 textarea 双写。

## 2. 实际验证

### 2.1 编辑器定向回归

```text
PATH=/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:/usr/bin:/bin \
  /Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm \
  vitest run \
  frontend/src/narration/editor-bridge.test.ts \
  frontend/src/narration/editor-codemirror.test.ts \
  frontend/src/narration/editor-textarea-fallback.test.ts \
  frontend/src/narration/chapter-editor-surface.test.ts

Test Files  4 passed (4)
Tests       48 passed (48)
```

覆盖：CM/textarea 输入、IME、undo/redo、AI `setValue`、真实 selection/focus 代理、presentation 写入隔离、普通点击不跳播、构造失败降级、原容器节点保留、lease/dispose 拒绝迟到写入。

### 2.2 全量 TypeScript

```text
PATH=/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:/usr/bin:/bin \
  /Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm \
  typecheck

tsc --noEmit
PASS
```

## 3. 主代理接线示例

以下只表示冻结端口，不表示本工作包已经修改 Workbench：

```ts
const surface = createChapterEditorSurface({
  parent: editorMount,
  lease: { documentId: document.id, generation: documentGeneration },
  initialValue: contentRef.current,
  currentContentHash: document.content_hash,
  ariaLabel: "章节正文",
  isLeaseCurrent: (lease) => isCurrentDocumentLease(lease),
  onDocChanged: (event) => {
    if (!isCurrentDocumentLease(event.lease)) return;
    commitEditorValueThroughExistingSaveChain(event.nextValue, event.origin);
  },
  onFocusChange: (focused) => bodyAssistantBinding.setFocusedField(focused),
  onAuthorInteraction: (kind) => followController?.noteAuthorInteraction(kind),
});

editorControlRef.current = surface.assistantControl;

// AI apply、AI undo 和 recovery 也只走这一入口。
surface.setValue(nextValue, "ai-apply");

// 切章时先让旧 generation 失效，再清理旧表面。
surface.dispose();
```

主接线必须删除原正文 textarea 的 React `value/onChange` 输入 Owner，把 `onDocChanged` 唯一接回既有 content/recovery/600 ms debounce/CAS/保存中 100 ms 追保存链。展示事件不得调用该保存链。

## 4. 尚未完成及风险

- 尚未修改 `workbench-v2.ts`，所以当前实现仍是可接线候选，不是已对用户开放的章节编辑器。
- 尚未运行固定 QwenPaw 真实浏览器、系统中文输入法候选窗、焦点/ARIA、长章滚动和 1920×1080／2560×1440 检查。
- textarea 降级不提供可编辑句段 decoration 或 gutter；旧稿句段列表和显式命令由主集成提供，不能用视觉叠层伪装。
- CodeMirror 构造失败原因目前通过 `handle.kind === "textarea-fallback"` 对外可观察，但本端口不自行弹错误提示；页面是否提示由主集成裁决。
- `product_player` 和 `editor_production` 必须继续关闭，直至 T4-GATE 完成 Workbench、会话、播放器和真实浏览器闭环。

## 5. 文件摘要

```text
frontend/src/narration/chapter-editor-surface.ts             c664fb857a2a4fd108ed063983514697f1607d0fe679eb65294f67d45ca8c942
frontend/src/narration/chapter-editor-surface.test.ts        6cf9f44984f1dce81092b1fb5ee303222de437194933bb621ef7feed237c7352
frontend/src/narration/editor-codemirror.ts                   9e6bbced0b27648291434f496307863593ecc9d95ffc893594cb734f19bf9d21
frontend/src/narration/editor-codemirror.test.ts              bc4159744fcf792a1b0f212942d86a8886c9f857f30db2a271b2e136b0671bf7
frontend/src/narration/editor-textarea-fallback.ts            04f16d1a5c8eac51448a3d26ecee63d0c6a91838cd69687b1370667d9afeef83
frontend/src/narration/editor-textarea-fallback.test.ts       b8094b77324614a751d4823b436e3c7b92b2e9b415620f86681f4d1b83aa67a2
```
