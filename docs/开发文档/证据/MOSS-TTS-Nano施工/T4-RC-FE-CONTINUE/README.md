# T4-RC-FE-CONTINUE 人工批准后继续生产证据

- 日期：2026-08-27
- 工作包：`T4-RC-FE-CONTINUE`
- 状态：独立前端控制器与自动化通过；尚未接共享页面，未做真实 HTTP／PostgreSQL／Nano／浏览器验收
- UI 范围：本包无页面与样式改动；后续只验收 1920×1080、2560×1440 各自助手收起／展开的四个精确组合，低于 1920×1080、移动、窄屏和 200% 等效小视口不设计、不测试、不阻断发布

## 1. 交付文件

- `frontend/src/narration/script-review-continue.ts`
- `frontend/src/narration/script-review-continue.integration.test.ts`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T4-RC-FE-CONTINUE/README.md`

未修改 `workbench-v2.ts`、`script-review-panel.ts`、`script-api.ts`、`api.ts`、共享 `index/styles`、后端、数据库、package 或锁文件。

## 2. 控制器边界

`continueApprovedScriptProduction(...)` 只消费 `approveNarrationScriptVersion` 已真实返回的 `approved` `ScriptReviewResource`，不会重复批准 mutation，也不会在前端创建或伪造 Edition。

调用方必须显式注入现有 `getNarrationWorkflow`。控制器按已知 `request_id` 立即查询并有界轮询，逐次校验：

- 批准审计必须为同 request、owner actor 的 `manual_after_review`，脚本已 approved 且 blocker 为 0；
- workflow 的 `request_id`、`script_version_id`、source revision/hash 必须与批准资源一致；
- `request_version` 不得倒退，`analyze_only` 不得进入生产；
- 只有 `queued | rendering | partial_ready | ready` 且存在合法真实 `edition_id` 才成功；
- `review_required`、`failed`、`cancel_requested`、`cancelled` 分别返回真实失败；
- 等待次数和时间均有界，父级 Abort 原样返回 `AbortError`；即使依赖忽略 Abort，硬超时也能结束本地等待。

## 3. 覆盖矩阵

| 场景 | 自动化结论 |
| --- | --- |
| analyzed → queued | 使用同 request 轮询，第二次取得真实 Edition 后成功 |
| 四个生产成功态 | queued/rendering/partial_ready/ready 均要求非空合法 Edition |
| scope 漂移 | request、ScriptVersion、source revision/hash 任一漂移均 fail-closed |
| 假成功防护 | queued 无 Edition、等待态提前带 Edition 均拒绝 |
| 审核与终态 | review_required、failed、cancel_requested、cancelled 不得成功 |
| 批准权威 | 非 approved、有 blocker、缺审计或审计 request 不一致时不发 API 请求 |
| 有界轮询 | 最大次数、墙钟硬超时与永不 settle 的 API 均受控结束 |
| Abort | 面板关闭／章节切换 Abort 后不再发起下一次 workflow 查询 |
| 观察者隔离 | UI 观察者抛错不改变 request/Edition 权威或轮询结果 |

## 4. 原始验证结果

```text
$ PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" pnpm exec vitest run frontend/src/narration/script-review-continue.integration.test.ts
Test Files  1 passed (1)
Tests       23 passed (23)
失败 0，跳过 0
```

```text
$ PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" pnpm exec vitest run frontend/src/narration/script-review-continue.integration.test.ts frontend/src/narration/script-review-panel.test.ts frontend/src/narration/chapter-narration-workflow.test.ts frontend/src/narration/script-api.test.ts frontend/src/narration/api.test.ts
Test Files  5 passed (5)
Tests       84 passed (84)
失败 0，跳过 0
```

```text
$ PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" pnpm typecheck
$ tsc --noEmit
退出码 0
```

```text
$ PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" pnpm exec vitest run frontend/src/narration
Test Files  38 passed (38)
Tests       376 passed (376)
失败 0，跳过 0
```

## 5. 共享页面最小接线

唯一集成 Owner 在 `ScriptReviewPanel.onReviewChanged` 中保留现有 `setScriptReview(nextReview)`；仅当 `nextReview.state === "approved"` 时：

1. 为当前章节／面板创建 AbortController，并在章节 generation 改变、面板关闭或卸载时 abort；
2. 调用 `continueApprovedScriptProduction({ requestId: scriptReviewRequestId, approvedReview: nextReview, dependencies: { getWorkflow: getNarrationWorkflow }, signal })`；
3. 成功后使用返回的真实 `workflow.edition_id` 刷新现有 narration context/session，不直接在前端拼 Edition 或 Manifest；
4. `REVIEW_REQUIRED`、生产失败、取消、超时或 Abort 分别展示真实状态，保留作者可恢复路径。

`onReviewChanged` 同时承载修正／重分析资源，必须保留 `state === "approved"` 门禁，不能对普通 review 变化启动生产轮询。

## 6. 风险、回退与未完成项

- 本包未证明后端批准 mutation 与同事务 Edition 创建已经真实开放；必须以 T4-RC 后端、真实 HTTP 和 PostgreSQL 门禁为准。
- 未运行真实浏览器或网络时序；轮询测试使用显式注入的确定性 API 替身，不等同真实批准成功。
- 接线失败可删除共享页面中的单一调用并 abort 当前控制器；本包无持久写入、无数据库迁移，也不改变批准或 Edition 权威数据。
- 在真实后端门禁通过前，不得因本控制器存在而把人工批准或 Edition 表述为可用。
