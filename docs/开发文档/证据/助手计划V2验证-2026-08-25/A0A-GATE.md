# A0A 基线与依赖封口门禁

日期：2026-08-25（Asia/Shanghai）

结论：**通过。** A0A-1…A0A-4E 的代码、运行环境、文件所有权和桌面双分辨率证据均已复核；可以进入 A0B。此结论只解除 A0B 的前置门禁，不代表 A0B–A7 已实现。

## 1. Git 与文件所有权

- 当前分支为 `main`，`HEAD` 与 `origin/main` 均为 `a4007ab`。
- 工作区已有模型证据、关系网和页面改动。为了不切换分支时夹带或覆盖这些改动，本阶段采用“原工作区 + 精确文件锁”而不是创建/切换分支。
- 现有脏文件全部保留，助手施工首先只新增 `frontend/src/assistant-*`、`backend/assistant_*` 及独立测试；`frontend/src/index.ts`、`plugin.py`、`backend/tools.py` 等共享入口只允许主集成 Owner 串行接线。
- `backend/model_runtime.py`、`backend/creative_services.py`、`frontend/src/api.ts`、`frontend/src/api.test.ts`、`frontend/src/chapter-workflow.ts`、`frontend/src/workbench-studio.ts`、`frontend/src/relationship-workspace.ts`、`frontend/src/creative-center.ts` 和相应既有测试在当前并行工作完成前锁定为只读。
- `frontend/src/styles.ts` 当前也有改动；若后续必须增加助手布局样式，由主集成 Owner 基于现有 diff 做增量合并，不得覆盖已有响应式规则。
- 数据库 dump、关系网证据、模型计划证据不读取、不清理、不暂存，也不混入助手提交。

## 2. 真实桌面页面证据

以下图像由当前 `http://127.0.0.1:18088` 真实 QwenPaw 2.1.0 环境采集。文件扩展名沿用既有目录命名；`file` 检查确认浏览器实际返回的是 JPEG 数据，像素尺寸与目标一致。

| 模块 | 1920×1080 | 2560×1440 | 结论 |
| --- | --- | --- | --- |
| 章节编辑器 | `02-editor-1920x1080.png` | `03-editor-2560x1440.png` | 已核实 |
| 角色 | `04-roles-1920x1080.png` | `06-roles-2560x1440.png` | 已核实 |
| 大纲 | `07-outline-1920x1080.png` | `08-outline-2560x1440.png` | 已核实 |
| 线索 | `09-clues-1920x1080.png` | `10-clues-2560x1440.png` | 已核实 |
| 设定 | `11-settings-1920x1080.png` | `12-settings-2560x1440.png` | 已核实 |
| QwenPaw 原生聊天 | `13-native-chat-1920x1080.png` | `14-native-chat-2560x1440.png` | 已核实 |

`05-native-chat-1920x1080.png` 实际只有 1280×720，仅保留为早期无效样本，不计入门禁。

### 路由基线发现

- 从工作台直接导航到 `/chat` 时，当前 `sessionStorage` 路由记忆会继续让 PawApp 接管原生聊天；这不是原生聊天证据。
- 通过页面的“返回创作中心”按钮执行项目公开的 `clearWorkbenchRoute()` 后，再进入 `/chat`，能够恢复真实 QwenPaw 原生聊天，并被 `13`、`14` 两张图复核。
- A0C 必须冻结“进入工作台 / 返回创作中心 / 原生聊天”三类路由状态与清理语义；不得把携带旧工作台状态的 `/chat` 误判为原生聊天。

## 3. 自动化与运行环境

| 检查 | 结果 |
| --- | --- |
| 前端 Vitest | 6 个文件、22 项测试通过 |
| TypeScript | `tsc --noEmit` 通过 |
| 前端生产构建 | Vite 6.3.5 通过；`frontend/dist/index.js` 1,757.65 kB，gzip 655.98 kB |
| Python 全量（明确使用当前隔离验证环境 PostgreSQL） | 83 项全部通过 |
| `git diff --check` | 通过 |
| Docker | PostgreSQL 与 QwenPaw 均为 healthy |
| 真实安装校验 | `scripts/verify_qwenpaw_lab.py` 通过 |
| 当前小说 Agent 模型 | `minimax-cn / MiniMax-M3`；只作为运行态事实，不新增固定模型规则 |

集成测试使用当前 Docker 验证环境的 `AI_NOVEL_DATABASE_URL`，只将容器主机名/端口映射到本机验证端口；命令不打印凭据。测试自身仅使用 `pytest-*` 数据并执行清理，不触碰正式小说。

## 4. 门禁判断

- A0A-1：通过。
- A0A-2：通过。
- A0A-3：通过，采用精确文件锁与唯一集成 Owner。
- A0A-4A…E：通过，目标桌面分辨率证据完整。
- A0A-G：**通过；允许进入 A0B。**

恢复方式：本阶段没有修改数据库、正式小说或宿主核心；新增证据可独立移除。源代码继续以 `a4007ab` 为可恢复 Git 基线，现有未提交改动保持原样。

### 施工中边界复核（03:13 CST）

A0B 施工期间又检测到其他任务新增/更新了模型计划、模型验收记录及 `docs/开发文档/设计稿/18-MOSS-TTS-Nano智能朗读-页面设计评审-2026-08-25/`。这些文件与目录立即加入只读锁：助手任务不读取其正文、不修改、不暂存、不清理。该变化不触及已经分配给助手任务的全新 `assistant-*` / `assistant_*` 文件，也不撤销 A0A-G；共享入口接线前仍会再次检查状态。
