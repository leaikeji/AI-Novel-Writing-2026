# UD1-FE-CORE：中央统一 Diff 前端核心证据

状态：**工作包实现完成；专项测试与限定文件 TypeScript 编译通过，尚未接页面/API/Adapter。**

日期：2026-08-25（Asia/Shanghai）

## 实现边界

- 新增 API 无关的 V2 结果校验与 base/candidate 严格重建。
- 新增 `idle → preparing → generating → reviewing → applying → applied/discarded` 状态机，并覆盖 `failed/conflict`；迟到任务事件不能重新打开已放弃会话。
- 逐处决定只创建新的只读 `reviewDraft`；未决定项、零差异和全拒绝均不能形成应用请求。
- “接受全部”或完整逐处决定只产出一个 `apply` effect；本模块不调用字段 Adapter，也不写页面字段。
- 新增受控、纯 `SelectionEditReviewSurface`：统一 Diff、非颜色 `+ / −` 语义、ARIA toolbar/live region、IME 安全键盘事件和焦点目标事件。

## 导出接口

- `createSelectionEditReviewCoordinator()`：`getState()`、`subscribe(listener)`、`dispatch(event)`、`dispose()`。
- `validateSelectionEditResultV2()`、`rebuildSelectionEditTexts()`。
- `setSelectionEditReviewDecision()`、`composeSelectionEditReview()`、`selectionEditReviewMetrics()`。
- `createSelectionEditReviewSurface(React)`：受控 props 为 `state`、`onAction`、可选 `onReturnFocus/onFocusTarget`。
- `selectionEditReviewEventForSurfaceAction()`：把纯 UI 动作映射为 coordinator event；复制候选和发送助手显式留给集成层。

## 状态与焦点证据

| 输入/状态 | 结果 | 字段影响 |
| --- | --- | --- |
| 合法 V2 ready | 严格重建后进入 `reviewing`，焦点请求首个变更 | 无 |
| 无差异 V2 | `reviewing` 空差异，焦点请求审阅标题，不能应用 | 无 |
| 部分决定 | 保持 `reviewing`，未决定项阻止应用 | 无 |
| 全部决定/接受全部 | 进入 `applying`，只发出一个合成 replacement | 本模块无写入 |
| 失败/冲突 | 显示独立状态；冲突候选为只读 Diff | 无 |
| 应用/放弃/撤销完成 | 请求焦点返回原字段 | 由后续 Adapter 集成负责 |

## 实际验证

```bash
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH" \
  pnpm exec vitest run \
  frontend/src/selection-edit-review.test.ts \
  frontend/src/selection-edit-review-surface.test.ts
```

结果：`2` 个测试文件、`33` 项测试全部通过。

```bash
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH" \
  pnpm exec tsc --noEmit --target ES2020 --module ESNext \
  --moduleResolution Bundler --lib ES2020,DOM,DOM.Iterable \
  --strict --skipLibCheck \
  frontend/src/selection-edit-review.ts \
  frontend/src/selection-edit-review-surface.ts \
  frontend/src/selection-edit-review.test.ts \
  frontend/src/selection-edit-review-surface.test.ts
```

结果：限定本工作包文件编译通过。运行期间全仓 `pnpm typecheck` 曾被并行中的 `UD1-BRIDGE` 未完成文件阻断，因此本记录不把当时的全仓状态写成通过；最终全仓门禁由主集成负责人在 W1 汇合后执行。

并行文件收口后再次执行 `pnpm typecheck`，结果为通过；最终集成阶段仍需按计划重跑该门禁。

## 集成说明

1. 页面/API Owner 先在自身作用域保存 Selection Registry、完整字段哈希和 Adapter/CAS 元数据，再把最小 `SelectionEditReviewIdentity` 交给本状态机。
2. coordinator 发出 `effect.type === "apply"` 时，只消费一次 `request.replacementText`；最终写回仍必须走既有 `AIEditTransactionManager.apply`。
3. Surface 不自行弹确认框。若 `dispatch({type: "exit"})` 返回 `exit-confirmation-required`，页面 Owner 显示宿主确认 UI，作者确认后再 dispatch `confirm-exit`。
4. `copy-candidate` 与 `send-to-assistant` 是显式兼容动作，不会自动写剪贴板或操作 QwenPaw 私有 DOM/store。
