# UD3-FE-QA：前端只读验收

状态：**✅ 通过。专项、扩展回归、类型、全量测试、生产构建和 12,000 字性能门禁均通过；本工作包未修改实现源码。**

验收日期：2026-08-25（Asia/Shanghai）

范围：批准计划 W3 `UD3-FE-QA`。本记录只裁决前端自动化与性能，不替代浏览器视觉/无障碍、真实模型、安装/卸载和共享数据库验收。

## 1. 环境

- Workspace：`/Users/liujia/Documents/AI小说世界2026`
- Node：`v24.19.0`
- pnpm：项目固定 `11.19.0`
- Vitest：`4.1.11`
- Vite：`6.3.5`
- Node PATH：`/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin`
- pnpm fallback PATH：`/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback`

## 2. 命令与结果

### 2.1 计划规定专项

```bash
pnpm exec vitest run \
  frontend/src/selection-edit-review.test.ts \
  frontend/src/selection-edit-review-surface.test.ts \
  frontend/src/assistant-selection-controller.test.ts \
  frontend/src/assistant-tool-card.test.ts \
  frontend/src/assistant-transactions.test.ts \
  frontend/src/assistant-page-apply.integration.test.ts
```

结果：`6` 个测试文件、`87` 项测试全部通过；无 skipped/todo 报告。

### 2.2 Host、桥接和撤销扩展回归

```bash
pnpm exec vitest run \
  frontend/src/selection-edit-runtime.test.ts \
  frontend/src/selection-edit-page-hosts.integration.test.ts \
  frontend/src/assistant-body-field.test.ts \
  frontend/src/assistant-form-field.test.ts \
  frontend/src/assistant-tool-card.test.ts
```

结果：`5` 个测试文件、`33` 项测试全部通过；无 skipped/todo 报告。

### 2.3 类型、全量与构建

```bash
pnpm typecheck
pnpm test
pnpm build
```

结果：

- `pnpm typecheck`：通过，`tsc --noEmit` 无报错。
- `pnpm test`：`38` 个测试文件、`300` 项测试全部通过；无 skipped/todo 报告。
- `pnpm build`：通过，转换 `48` 个模块，耗时 `1.07s`。
- 构建产物报告：`frontend/dist/index.js` 为 `1,975.35 kB`，gzip `711.33 kB`，source map `4,565.35 kB`。本计划没有 bundle-size 失败门槛；该尺寸作为后续性能治理信息保留。

## 3. 专项核对

### 3.1 聊天桥 DOM 不含完整候选

`assistant-tool-card.test.ts` 的通过断言覆盖：

- 不使用 `dangerouslySetInnerHTML`，也不渲染候选 `<pre>`。
- 不可信候选、V2 完整候选、原选区和 warning 均不出现在聊天可见 DOM。
- ready 状态只显示“在编辑器中打开审阅 / 复制 / 放弃”。
- V1 历史结果仍是紧凑桥；expired/conflict 只允许复制和放弃。
- 完整候选只经内存 `openReview(candidate)` 交给编辑器，不在聊天卡片展开。

结论：**通过。**

### 3.2 页面 Host 覆盖

`selection-edit-page-hosts.integration.test.ts` 的通过断言覆盖：

- 章节工作流 `10` 个字段：正文、标题、章纲正文、目标字数、本章期待、禁止事项及四类角色约束。
- 工作室 `31` 个静态字段：总体大纲、建书角色、角色卡、故事线、伏笔和设定；每个静态 Adapter 恰好归属一个 Review Host，无遗漏、无重复。
- 关系编辑器 `6` 个字段全部归属关系弹窗 Review Host。
- 合计 `47` 个静态字段的唯一归属契约通过。

只读源码核对还确认：设定弹窗会把当前 `template_data` 动态键转换为 `settings.templateData.*` 并追加到同一 Host。该动态路径的真实弹窗渲染仍属于浏览器 E2E，而非本只读包的替代结论。

结论：**自动化静态覆盖通过；真实页面呈现留给 `UD3-E2E`。**

### 3.3 本轮撤销回归

通过断言覆盖：

- `SelectionEditRuntime` 创建一个受审计 job，接受全部后只调用一次 Adapter；一步撤销后恢复原值，Adapter 总调用次数为两次。
- 正文 Adapter 应用与撤销都请求原 autosave 链路，第二次 autosave 对应撤销。
- 显式保存表单撤销后仍保持 dirty，不绕过原保存按钮。
- 作者在生成/哈希期间修改字段时，不应用也不生成可误导的完成状态。

结论：**通过。**

## 4. 12,000 字性能探针

探针直接导入 `rebuildSelectionEditTexts`，用 `2,000` 组“3 字上下文 + 3 字替换”构造 `4,000` 个 segment；base/candidate 均为精确 `12,000` 个 Unicode 字符。预热 `50` 次后采集 `500` 次样本，每次都断言双向重建与预期文本完全相等。

复现命令：

```bash
node --experimental-strip-types \
  docs/开发文档/证据/选区AI中央统一Diff审阅-2026-08-25/UD3-FE-QA/performance-probe.mjs
```

结果见 [performance.json](./performance.json)：

- base：`12,000` 字，重建正确。
- candidate：`12,000` 字，重建正确。
- p50：`0.0267ms`。
- p95：`0.0806ms`。
- max：`1.0187ms`。
- 门槛：p95 `<100ms`。

结论：**通过，p95 低于门槛约三个数量级。**

## 5. Git 与裁决

- 验收开始时工作区已有多项主代理/其他工作包修改；本包没有 reset、stash、暂存、提交或清理任何内容。
- `pnpm build` 只更新被 Git 忽略的生成目录，未在 `git status --short` 增加实现文件。
- 写证据前 `git diff --check` 通过。
- 本包唯一预期 Git 影响是新增本目录的 `README.md` 与 `performance.json`。
- 未发现前端自动化 P0/P1，也没有命令失败或跳过项。

裁决建议：**`UD3-FE-QA` 可以通过。** 主代理仍应等待 `UD3-BE-QA`、`UD3-A11Y-QA` 和 `UD3-E2E`，并在最终集成点重跑全量门禁后再裁决 `UD3-G`。

## 6. 最终集成复跑

同视口视觉复核后，主代理补充了章节主区最小宽度、density 驱动章节树宽度和打包洁净度测试。最终安装链路再次执行类型检查、全量测试和生产构建：

```text
38 test files
303 passed
tsc --noEmit passed
48 modules transformed
production build passed
```

新增布局测试验证：1525×1031 等窄桌面工作区先夹紧助手，不再让 520px 持久偏好挤压章节树和中央 Diff；更窄工作区改用可折叠 overlay。最终结论仍为：**UD3-FE-QA 通过。**
