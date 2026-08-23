# ADR-0001：QwenPaw 原生聊天组合与小说 Agent 作用域

状态：已接受。

决策日期：2026-08-23（Asia/Shanghai）。

## 背景

小说工作台需要与 AI 助手并排使用，但不得复制、替换或修改 QwenPaw 原生聊天组件，也不得依赖上游私有 React 组件。六个小说 Skills 需要持续可改，同时不能自动影响 Default、QA 等其他 Agent。

## 已核实事实

- QwenPaw 2.1.0 的公开前端 API 提供 `route.wrap(pluginId, targetId, wrapper)`；官方文档把 `core.chat` 作为包装原生聊天的示例目标。
- 真实浏览器验证表明，包装后的 `Inner` 仍包含原生模型选择、Agent 选择、聊天历史、输入框和工具安全控制。
- 查询参数关闭时直接返回 `Inner`，普通 `/chat` 不显示小说工作台外壳。
- QwenPaw Agent API 支持独立 workspace；Skills API 通过 `X-Agent-Id` 精确作用于目标 Agent。
- PawApp Skill provider 会把六个项目 Skills 注册到现有及新建 workspace；`enabled_by_default=false` 可保证默认关闭。
- 运行时官方插件卸载 API 会执行注销并清理 PawApp、前端包装和 Skill provider。离线 CLI 卸载只删除插件文件，不会执行运行时 Skill 注销。

## 决策

1. 保留 PawApp 独立入口 `/apps/ai-novel-world-2026`。
2. 工作台模式使用官方 `route.wrap` 包装 `core.chat`，入口为 `/chat?novel_workbench=1`。
3. wrapper 只负责工作台外围布局；AI 助手区域始终渲染 QwenPaw 提供的原生 `Inner`，不添加自定义聊天消息、模型按钮或工具控制。
4. 普通 `/chat` 必须原样返回 `Inner`，因此 QwenPaw 原生聊天入口和行为不变。
5. 创建专用 Agent `ai-novel-writer`，显示名为“AI小说作家”。六个小说 Skills 只在该 Agent 中启用；Default 与 QA 中保持关闭。
6. Skills 保存在项目 `skills/` 目录并随 PawApp 版本化，可以持续修改和回归测试，不是固定模板。
7. 插件安装可以在 QwenPaw 停止时执行；完整卸载必须在 QwenPaw 运行时调用官方插件 API，以确保注销逻辑执行。

## 不采用

- 不使用 iframe 嵌入 QwenPaw 自身页面。
- 不复制或替换 QwenPaw 聊天组件。
- 不读取上游私有 Router、组件模块或内部状态。
- 不把六个小说 Skills 默认启用到所有 Agent。
- 不在本阶段加入确认、Diff、候选版本或 AI 正文写回 UI。

## 失败恢复

- 若未来 QwenPaw 升级导致 `core.chat` 包装不兼容，PawApp 按钮降级为普通 `/chat` 跳转；小说数据层不受影响。
- 若 Skill provider 或 Agent 作用域验证失败，保持全部小说 Skills 关闭，不允许自动写正文。
- 卸载前要求显式输入插件 ID；卸载后检查 PawApp、三个 Agent 的 Skill 清单和小说工具残留。

## 后续验证

- 阶段四实现真实工作台时验证窄窗口布局、侧栏折叠和滚动。
- 阶段四已按用户“编辑器暂缓”决定采用 Markdown `textarea`；Monaco/TipTap 和独立预览器保持未立项。
- 每次 QwenPaw 升级都在并行验证环境重跑普通聊天、工作台聊天、Agent 作用域和完整卸载测试。
