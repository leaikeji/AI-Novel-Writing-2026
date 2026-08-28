# T4-GATE-FE-GUTTER：CodeMirror 段落朗读 gutter 扩展

- 日期：2026-08-27（Asia/Shanghai）
- 工作包：`T4-GATE-FE-GUTTER-EXT`
- 状态：本独立工作包的实现与单元验证已完成；不代表 `T4-GATE` 已通过，仍需主代理完成章节工作台接线、真实播放与桌面浏览器验收。

## 1. 变更边界

本工作包只新增：

- `frontend/src/narration/editor-paragraph-gutter.ts`
- `frontend/src/narration/editor-paragraph-gutter.test.ts`
- 本证据文件

未修改 `editor-codemirror.ts`、`chapter-editor-surface.ts`、`workbench-v2.ts`、样式、依赖或锁文件；未执行 Git 暂存、提交或推送。

## 2. 冻结实现语义

- 使用独立 CodeMirror 6 `gutter()` 扩展，不改造也不复用行号点击。
- `EditorParagraphGutterEntry` 保留冻结的 `ParagraphGutterButtonModel` 不变，另携带 `sourceStartUtf16`；按该 UTF-16 起点所在文本行显示 `▶` 按钮。
- `editorParagraphGutterEffect`、`replaceEditorParagraphGutter(...)` 和 `clearEditorParagraphGutter()` 可直接放入 CodeMirror `view.dispatch({ effects: ... })`。
- `createEditorParagraphGutterExtension({ onActivate })` 生成扩展；只有按钮 `click`、`Enter` 和 `Space` 会以 `paragraphOrdinal` 调用回调。
- 按钮 `pointerdown` 同时 `preventDefault` 与 `stopPropagation`，不抢正文 selection；普通编辑器点击、行号点击、选区与文本 transaction 都没有播放回调。
- 每个按钮带 `type=button`、`aria-label`、`title`、`disabled` 和可核对的 ordinal/availability data 属性；扩展使含交互 gutter 的 CodeMirror gutter 容器不再被 `aria-hidden` 隐藏，销毁时恢复原属性。
- 按钮监听器支持幂等销毁；更新、清空和销毁均不会触发播放。

## 3. Fail-closed 规则

以下任一情况都会拒绝整组 payload 并清空 gutter，不保留可能对错段落的部分按钮：

- payload 或按钮字段结构非法；
- `available` / `disabled` / `targetSegmentId` 状态不自洽；
- 起点越界或切开 UTF-16 surrogate pair；
- `paragraphOrdinal`、`sourceBlockKey`、起点或起始文本行重复；
- 正文 transaction 映射后多个段落起点折叠。

## 4. 主接线说明

1. 在创建 `ChapterEditorSurface` 前创建 `createEditorParagraphGutterExtension(...)`，并通过已冻结的 `codeMirrorExtensions` 传入；回调只调用当前、未过期的 `ProductionParagraphGutterController.requestFromGutter(ordinal)`。
2. 章节 Session 就绪后，按 `paragraphOrdinal` 将 `bundle.paragraphs[].range.startUtf16` 与 `gutterController.listButtons()` 一对一合并为 `EditorParagraphGutterEntry[]`，再 dispatch `replaceEditorParagraphGutter(entries)`。
3. 切换章节、Edition、document generation，进入旧 Edition 不可装饰模式，或 Session 错误/销毁时，立即 dispatch `clearEditorParagraphGutter()`；旧回调仍要由 document/Edition lease 再次 fail closed。
4. CodeMirror adapter 需为主代理提供一个受控 effect dispatch 窄接口，不应将整个 `EditorView` 暴露给工作台。textarea 安全降级不安装本扩展、也不伪造 gutter 能力。

## 5. 实际验证

命令：

```bash
/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node node_modules/vitest/vitest.mjs run frontend/src/narration/editor-paragraph-gutter.test.ts
/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node node_modules/vitest/vitest.mjs run frontend/src/narration/editor-paragraph-gutter.test.ts frontend/src/narration/paragraph-gutter.test.ts frontend/src/narration/editor-codemirror.test.ts frontend/src/narration/chapter-editor-surface.test.ts
/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node node_modules/typescript/bin/tsc --noEmit
```

结果：

- Vitest：`1` 个测试文件、`16` 项测试全部通过。
- 相关回归：新 gutter、领域 gutter controller、CodeMirror adapter 和 ChapterEditorSurface 共 `4` 个测试文件、`42` 项测试全部通过。
- TypeScript 全量严格类型检查：退出码 `0`。

本工作包未做真实浏览器点击、真实音频或 1920×1080 / 2560×1440 工作台验收；这些属于主 `T4-GATE` 汇合门禁。
