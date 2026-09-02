# L52-W4：隔离 QwenPaw 1080P／2K UI 验收

日期：2026-09-02（Asia/Shanghai）
状态：**PASS（完整候选、合成 500 万字作品）**

## 1. 隔离边界

- 一次性 QwenPaw 使用 `127.0.0.1:18089`，一次性 PostgreSQL 使用 `127.0.0.1:15440`；数据库精确为 `ai_novel_world_2026_plan52_test`，迁移 head 为 `20260902_0039`。
- 不共享长期 `18088` 的 data、secret、backup、media 或 PostgreSQL 卷；无 Provider 凭证，真实模型调用为 0。
- 合成作品共 2,500 章、5,000,000 字、10,000 条合成事实和 7,500 个语义分块。验收完成后，两个容器、五个卷和一个网络均精确清理，残留计数为 0；合成小说随一次性数据库删除。

## 2. 实测发现与修复

第一次打开章节列表时，分页 API 已不返回正文，但项目章节面板仍挂载 2,500 个章节行，页面约 40,891 个元素；这不满足长篇 UI 有界门禁。修复后，项目章节面板和章节编辑器共用固定行高虚拟窗口；项目列表补齐可聚焦 scrollport 以及 `Home`、`End`、`PageUp`、`PageDown` 键盘滚动，跳章后的编辑器目录改为在新窗口提交后再定位，并按当前 manifest 行数重新核对定位。

## 3. 真实浏览器结果

Browser 目标 viewport 分别设为 1920×1080 和 2560×1440；受浏览器内容边框影响，页面实际 `innerWidth × innerHeight` 分别为 1901×1069 和 2534×1426，未把该差异伪称为精确内容尺寸。

| 路径 | 1920×1080 | 2560×1440 | 结论 |
| --- | ---: | ---: | --- |
| 2,500 章项目列表实际章节 DOM 行 | 19 | 19 | 有界 |
| 章节编辑器目录 DOM 行 | 29（末章） | 37（助手展开） | 有界 |
| 项目列表总 DOM 元素 | 约 1,216 | 约 1,218 | 不随 2,500 章线性挂载 |
| 编辑器总 DOM 元素 | 约 950 | 约 974 | 有界 |
| 页面横向溢出 | `body clientWidth = scrollWidth` | `body clientWidth = scrollWidth` | 无页面级横向溢出 |

实际交互覆盖：

- 助手展开／折叠，两档分辨率均不遮挡章节目录、正文和当前状态；
- 搜索“蓝钥匙”只返回匹配片段并打开第 3 章，正文读取为 2,000 字；
- 2K 下聚焦章节列表后按 `End`，仍只渲染 19 行并显示第 2,482–2,500 章；
- 打开第 2,500 章后，编辑器正文和左侧活动目录项均为第 2,500 章，目录窗口为第 2,472–2,500 章；
- 语义索引页如实显示“本小说已授权云端向量处理”与“当前模型尚未激活／尚未构建”，没有把 consent 冒充 ready；设置深链保持在 `settings_tab=semantic-index`；
- 应用自身没有 console error。观察到一条 QwenPaw 宿主级既有 warning：`Module not found: AppCenter`，不来自 PawApp 代码且未阻断页面。

## 4. 证据

- [`L52-UI-1920x1080-assistant-expanded.png`](./L52-UI-1920x1080-assistant-expanded.png)
- [`L52-UI-2560x1440-assistant-expanded.png`](./L52-UI-2560x1440-assistant-expanded.png)
- [`L52-UI-2560x1440-chapter-2500.png`](./L52-UI-2560x1440-chapter-2500.png)
- [`L52-isolated-plugin-lifecycle-final.json`](./L52-isolated-plugin-lifecycle-final.json)：候选树 SHA-256 `cf7d5a93600d174275162c1b51bca5b94002be5484bad2e3644875be97af74d9`；安装、强制重装、卸载零残留、重装、迁移和精确资源清理均通过。

本报告保留发布前隔离 QA 的历史候选身份，不倒改当时事实。此后长期真实数据只读 UI 复验发现 QwenPaw 长会话标题和 sender action list 在助手窄面板内不能正确收缩；修复仅作用于 `.anw-assistant-pane`，并新增前端契约测试。提交前复查又把未获准的计划 55 默认旁白候选和计划 52 开工前 UI 候选从发布树中隔离。最终纯计划 52 候选树 SHA-256 为 `90f1a601546ccbc458e557a65a9c9b421d6e3b1413bd50dda9d4f3b68dd5fc03`，已重新通过隔离插件生命周期并发布到长期 `18088`；原始生命周期记录见 [`L52-isolated-plugin-lifecycle-scope-corrected.json`](./L52-isolated-plugin-lifecycle-scope-corrected.json)。完整证据见 [`L52-RELEASE`](./L52-RELEASE-长期发布与双分辨率验收.md)。真实云模型调用仍未执行。
