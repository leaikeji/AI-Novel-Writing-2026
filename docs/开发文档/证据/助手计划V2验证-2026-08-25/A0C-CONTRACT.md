# A0C-0：前端尖峰接口与文件边界冻结

- 日期：2026-08-25
- 状态：**已冻结；A0C-1…6 可以按下列边界并行。**
- 前置：A0B-G 已通过。

## 1. 共享接口

`frontend/src/assistant-fields.ts` 是本阶段唯一字段适配契约，冻结：

- `EditableFieldAdapter`
- `AIApplyMeta`
- `SelectionSnapshot` / `SelectionRange`
- `autosave` / `explicit-save`
- `EditableFieldRegistry`

页面 Adapter 必须通过 React/表单受控 callback 调用 `applyValue`；禁止 `querySelector` 后直接写 DOM value。正文应用进入原自动保存语义，显式表单只标 dirty，不能替作者点击保存。

## 2. 并行文件边界

| 工作包 | 唯一文件所有权 | 只读/禁止 |
| --- | --- | --- |
| A0C-1 | `workbench-route.ts`、`workbench-route.test.ts` | 不新建第二状态机；`index.ts` 禁改 |
| A0C-2/3 | `assistant-body-field*`、`assistant-form-field*` | `assistant-fields.ts` 只读；页面文件禁改 |
| A0C-4/5 | `assistant-selection-geometry*`、`assistant-selection-registry*` | 页面、样式和字段契约禁改 |
| A0C-6 | `assistant-tool-rail*` | `styles.ts`、`chapter-workflow.ts` 和 `index.ts` 暂不接线 |
| A0C-G | 主 Codex 独占集成、真实浏览器和文档 | 不覆盖其他任务现有脏改动 |

## 3. 冻结行为

- 路由只有 `ordinary-chat / workbench-no-session / workbench-session / leaving-workbench` 四态；无法用公开能力区分的宿主新会话按计划降级退出工作台。
- 选区 registry 只在浏览器内存，默认 TTL 20 分钟、容量 50、session 只允许首次原子绑定。
- 几何测量不可靠时必须返回字段锚定，不得伪造“贴选区”坐标。
- 工具轨不得继续使用相对浏览器窗口的 `position: fixed; right: 40px`；窄中心区降级为横向 footer，任何模式的 `railRight <= assistantLeft`。
- 本阶段不接模型、不写数据库、不修改正式正文；真实模型和页面接线分别由 A3/A6 承担。

## 4. A0C-G 输入证据

- 每个模块独立 Vitest。
- `pnpm typecheck`、`pnpm build`、`git diff --check`。
- 路由真实浏览器覆盖进入、深链刷新、返回普通聊天和前进/后退。
- 工具轨在 1920×1080 与 2560×1440 下与助手零重叠；若尚未接线，A0C-G 只能放行 A1-E 施工，不能宣称最终 UI 已修复。
