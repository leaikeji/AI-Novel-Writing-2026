# 创作中心原生壳与 AI 助手验收记录

日期：2026-08-26

## 1. 验收对象

- 公开入口：`/apps/ai-novel-world-2026`
- wrapper 入口：`/chat?novel_center=1`
- QwenPaw：2.1.0
- PawApp：0.4.0

## 2. 自动化结果

| 验证 | 结果 |
|---|---|
| 定向 Vitest | 5 个文件、32 项通过 |
| TypeScript | `pnpm typecheck` 通过 |
| 暂存区隔离前端 Vitest | 39 个文件、309 项通过 |
| 暂存区隔离前端构建 | Vite 构建通过，gzip 712.23 kB |
| QwenPaw 集成契约 | 10 项通过 |
| 最小发行目录 | `scripts/package_plugin.py` 通过 |
| Diff 格式 | `git diff --check` 通过 |

## 3. 真实浏览器结果

| 场景 | 结果 |
|---|---|
| 1920×1080 | 宿主侧栏 240px、创作中心主区 1190px、助手 480px，inline 显示 |
| 2560×1440 | 创作中心主区 1830px、助手 480px，inline 显示 |
| 960×540 | 主区 710px、助手 480px，沿用既有 overlay 策略 |
| 公开入口 | 自动进入创作中心 wrapper，页面和助手均显示 |
| 创作中心 → 章节页 → 创作中心 | surface 在 `creative-center/workbench/creative-center` 间正确切换 |
| 私有库 | 保持创作中心 surface 与右侧助手，返回正常 |
| 普通聊天 | `.anw-workbench-frame` 和 PawApp 助手 pane 均退出 |
| 助手折叠 | 宽度从 480px 折叠到 52px，并可恢复到 480px |
| 页面上下文状态 | 显示“创作中心 / 未发送作品页面内容 / 未进入具体作品” |

浏览器只发现 QwenPaw 现有警告 `[moduleRegistry] Module not found: AppCenter`，未出现本次 PawApp 新增错误。

## 4. 截图

- [1920×1080 桌面](./desktop-1920x1080.png)
- [2560×1440 桌面](./desktop-2560x1440.png)
- [960×540 窄屏](./narrow-960x540.png)
- [原始桌面窗口](./desktop-1934x1249.png)

## 5. 运行态部署边界

当前 QwenPaw 环境只定向替换了本 PawApp 的 `frontend/dist/index.js` 和 source map，并在重启后通过健康检查。未修改 QwenPaw 核心、后端、数据库、迁移或数据卷。

没有执行整包安装/卸载：当前工作区同时存在其他专项的未完成后端与迁移改动，整包打包安装会把它们带入唯一共享运行环境。替换前的前端 bundle 备份保存在：

```text
/tmp/ai-novel-center-runtime-backup.OkG1Yb/
```

## 6. 未执行项

- 删除作品、创建作品等会改变用户创作数据的浏览器操作；
- 完整插件安装、卸载及其他 Agent/设置页面的全量人工巡检。

这些未执行项不影响本次“创作中心复用现有原生壳”的核心布局结论，但不能表述为完整插件生命周期已经重新验收。
