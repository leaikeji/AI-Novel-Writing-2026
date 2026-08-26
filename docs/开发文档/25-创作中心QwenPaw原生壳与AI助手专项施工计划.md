# 创作中心复用章节列表原生壳施工计划

状态：**已于 2026-08-26 完成前端实施并通过核心自动化与真实浏览器验收**。当前 QwenPaw 验证环境已定向部署本次前端 bundle；为避免把工作区中其他未完成的后端、迁移和 TTS 施工混入运行环境，本次未执行整包安装/卸载非回归。

日期：2026-08-26

## 1. 目标

让“爱创作中心”直接复用章节列表页面现有的 QwenPaw 工作台外壳：

- 左侧继续显示 QwenPaw 宿主导航；
- 中间显示现有 `NovelLibraryPage`；
- 右侧显示章节列表正在使用的原生 `AssistantPane`；
- 保留创作中心现有作品管理、搜索、筛选、创建和删除行为；
- 不新增第二套聊天界面，不修改 QwenPaw 上游核心。

## 2. 当前实现事实

章节列表页面已经具备所需结构：

```text
QwenPaw 宿主页面
├─ 左侧宿主导航
└─ .anw-workbench-frame
   ├─ .anw-workbench-main
   │  └─ NovelWorkbench
   └─ AssistantPane
```

相关现有实现：

- `frontend/src/assistant-route-wrap.ts` 负责 `.anw-workbench-frame` 和右侧 `AssistantPane`；
- `frontend/src/assistant-layout.ts` 负责主区、助手宽度、折叠和窄屏覆盖；
- `frontend/src/workbench-studio.ts` 负责章节页内部的作品栏和章节工作区；
- `frontend/src/styles.ts` 已包含工作台外壳样式；
- `frontend/src/index.ts` 当前把创作中心直接注册到 `APP_PATH`，尚未经过聊天页 wrapper。

因此本任务不复制截图布局，也不重新实现左右侧栏；只让创作中心进入现有 wrapper，并把中间内容切换为 `NovelLibraryPage`。

## 3. 目标路由与渲染

保持公开入口 `/apps/ai-novel-world-2026` 不变，由薄入口跳转到：

```text
/chat?novel_center=1
```

`core.chat` wrapper 按 query 渲染：

```text
普通聊天
└─ QwenPaw 原生 Inner

novel_center=1
└─ NovelLibraryPage + AssistantPane

novel_workbench=1
└─ NovelWorkbench + AssistantPane
```

创作中心与章节页共用同一个外层布局和助手实例。创作中心不渲染章节页内部的 `.mb-book-rail`。

## 4. 范围

### 4.1 本次实施

- 增加创作中心 query 的解析与类型；
- 增加薄入口，把宿主 PawApp 地址导入现有聊天 wrapper；
- 在 wrapper 中增加创作中心渲染分支；
- 调整创作中心进入章节页、章节页返回创作中心的导航；
- 创作中心显示右侧原生助手，但不自动发送作品、书库或草稿内容；
- 补充路由、布局和非回归测试；
- 完成桌面和窄屏真实浏览器检查。

### 4.2 明确不做

- 不修改后端、数据库或 Alembic；
- 不修改 QwenPaw 上游代码；
- 不新增 ADR；
- 不扩展助手 V2 上下文协议；
- 不新增模型选择器、聊天前端或 Agent Runtime；
- 不涉及 Skills、TTS、向量、媒体或依赖升级；
- 不重做创作中心视觉设计。

## 5. 助手上下文规则

创作中心不是具体作品工作区，因此进入该页面时：

- 清除上一部作品遗留的 scope、selection 和 reference；
- 助手状态显示“创作中心；未发送作品页面内容”；
- 不把书名列表、作品卡片、私密元数据或草稿自动注入会话；
- 进入具体章节页后，继续使用现有工作台 V2 上下文；
- 返回创作中心时再次清空作品级上下文。

## 6. 预计文件

### 6.1 允许修改

- `frontend/src/contracts.ts`
- `frontend/src/workbench-route.ts`
- `frontend/src/assistant-route-wrap.ts`
- `frontend/src/creative-center.ts`
- `frontend/src/workbench-v2.ts`
- `frontend/src/index.ts`
- 对应现有测试文件

### 6.2 预计新增

- `frontend/src/creative-center-entry.ts`
- `frontend/src/creative-center-shell.test.ts`

### 6.3 条件修改

- `frontend/src/styles.ts`：仅当真实浏览器检查发现现有样式无法复用时，增加最小兼容规则。该文件已有其他未提交改动，实施时必须避开非本任务 diff。

### 6.4 禁止触碰

- QwenPaw 安装目录和上游源码；
- `backend/`、迁移、部署、依赖和锁文件；
- 与本任务无关的用户现有改动；
- 旧项目 `/Users/liujia/Documents/AI小说世界3`，尤其禁止处理其 `Data` 目录。

## 7. 子代理并行施工设计

本任务不使用子代理并行施工。

原因：改动集中在同一套路由、wrapper 和导航文件，工作量小且共享文件多；并行会增加接口冻结和冲突处理成本。由主代理作为唯一集成责任人串行完成。

| 顺序 | 工作包 | 标记 | 内容 | 文件所有权与门禁 |
|---|---|---|---|---|
| 1 | CC-S0 | SER/GATE | 固化现有章节页外壳、路由和助手行为基线 | 只读相关前端文件；确认不需要改 QwenPaw 核心 |
| 2 | CC-S1 | SER/MUTEX | 增加创作中心 query、薄入口和 wrapper 分支 | 独占 `contracts.ts`、`workbench-route.ts`、`assistant-route-wrap.ts`、`index.ts`、新入口 |
| 3 | CC-S2 | SER/MUTEX | 接通创作中心与章节页双向导航，清理陈旧作品上下文 | 独占 `creative-center.ts`、`workbench-v2.ts` |
| 4 | CC-S3 | INT/GATE | 补测试并完成类型、单测、构建和插件契约验证 | 主代理汇合所有 diff；失败不得进入浏览器验收 |
| 5 | CC-S4 | MUTEX/GATE | 在唯一共享运行环境做真实浏览器检查并保存证据 | 不并行操作运行环境；主代理作最终退出判断 |

依赖顺序：

```text
CC-S0 → CC-S1 → CC-S2 → CC-S3 → CC-S4
```

冻结接口：

- 公开 PawApp 入口保持 `/apps/ai-novel-world-2026`；
- 章节工作台继续使用 `novel_workbench=1`；
- 创作中心新增 `novel_center=1`；
- 右侧助手继续使用现有 `AssistantPane` 和布局控制；
- 不改变后端 API、DTO、数据库字段或 Agent 工具协议。

共享锁：

- `assistant-route-wrap.ts`、`index.ts`、`styles.ts` 和本地 QwenPaw 运行实例均为 `MUTEX`；
- 任何已有用户改动只读保留，若与目标行重叠则先停止并重新核对。

## 8. 验收

### 8.1 自动化

```bash
pnpm exec vitest run \
  frontend/src/contracts.test.ts \
  frontend/src/workbench-route.test.ts \
  frontend/src/assistant-route-wrap.test.ts \
  frontend/src/assistant-layout.test.ts \
  frontend/src/assistant-layout.integration.test.ts \
  frontend/src/creative-center-shell.test.ts

pnpm typecheck
pnpm test
pnpm build
.venv/bin/python -m pytest tests/test_qwenpaw_integration_contract.py
.venv/bin/python scripts/package_plugin.py
git diff --check
```

### 8.2 真实浏览器

至少检查：

- 1920×1080、2560×1440；
- 960×540，模拟 200% 缩放或窄屏；
- 创作中心作品列表、空态、搜索、筛选、创建与删除弹窗；
- 创作中心进入章节页，再返回创作中心；
- 左侧宿主导航、右侧助手的展开、折叠、宽度和滚动；
- 返回创作中心后没有残留上一部作品的上下文；
- 普通聊天、其他 Agent 和原生设置页面非回归；
- 禁用或卸载 PawApp 后宿主原生行为不受拦截。

证据目录：

```text
docs/开发文档/证据/创作中心原生壳与AI助手-2026-08-26/
```

## 9. 完成标准

- 创作中心在 QwenPaw 左侧导航与右侧原生助手之间正常显示；
- 页面直接复用章节列表外壳，不存在第二套侧栏或助手实现；
- 公开入口、页面刷新和前后导航可恢复；
- 创作中心不会泄漏或自动发送作品内容；
- 章节工作台现有助手上下文不回归；
- 自动化和真实浏览器验收全部通过并留存证据；
- 最终 diff 不包含无关文件、生成物、密钥或用户现有改动。

## 10. 2026-08-26 实施记录

已完成：

- 公开 PawApp 入口通过薄组件进入 `/chat?novel_center=1`；
- 创作中心与章节工作台共用 `.anw-workbench-frame` 和原生 `AssistantPane`；
- 创作中心 route owner 可跨 QwenPaw 原生会话路径归一化保持；
- 私有库继续留在同一外壳，返回创作中心不丢失助手；
- 进入作品、返回创作中心和普通聊天退出路径均已验证；
- 创作中心不启动作品上下文 ref 或选区控制器，状态栏明确显示“未发送作品页面内容”；
- 右侧助手在 960×540 下沿用现有 overlay 策略。

已通过：

- 前端定向 Vitest：5 个文件、32 项；
- `pnpm typecheck`；
- 暂存区隔离前端 Vitest：39 个文件、309 项；
- `pnpm build`；
- QwenPaw 集成契约：10 项；
- `scripts/package_plugin.py`；
- 1920×1080、2560×1440、960×540 真实浏览器验证。

未执行：

- 删除作品、创建作品等会改变用户创作数据的浏览器操作；
- 完整插件安装/卸载。当前工作区存在其他专项的未完成后端与迁移改动，整包安装会扩大本任务范围。运行态只替换了本 PawApp 的已构建前端 bundle，未修改 QwenPaw 核心、后端、数据库或数据卷。

详细证据见[创作中心原生壳与 AI 助手验收记录](./证据/创作中心原生壳与AI助手-2026-08-26/README.md)。
