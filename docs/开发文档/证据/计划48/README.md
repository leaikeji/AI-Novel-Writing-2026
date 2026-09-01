# 计划 48 施工与隔离验收证据

状态：**候选施工和隔离运行验收完成；长期 `18088` 未安装；精确提交构建门禁未封口。**

日期：2026-09-01（Asia/Shanghai）

## 1. 范围与隔离

- 施工分支：`codex/plan48-character-theme-focus`
- 施工基线：`858e50fd8fc97316a2b5de79a3bd07c5c39c008f`（`origin/main`）
- 施工工作树：`/Users/liujia/Documents/AI小说世界2026-cc48`
- 隔离运行态：QwenPaw 2.1.0，`http://127.0.0.1:18190`
- 合成小说：`1a734808-914c-408b-93a8-82cbf5e2ca4f`
- 合成人物：`47e8cdb8-4899-450e-aee3-6fad12facf1d`（林遥）
- 长期 `18088` 只做版本、哈希、功能矩阵和只读 API 基线核对；没有安装、卸载、写库或写入《潮汐盲区》。
- 根工作树已有 TTS／朗读等用户改动未进入本候选包；包内不存在 `20260901_0036_character_cast_plans.py`。

## 2. 已实现内容

1. 人物卡在 portal 内建立局部浅色 token 和 `color-scheme: light`，不向 `html`、`body` 或宿主组件泄漏。
2. 表单、事实筛选 `select`／`option`、禁用态、抽屉标题、关闭按钮、正文和页脚均使用显式可读前景／背景／边界。
3. 普通文字、弱化文字、控件边界和焦点色分别加入 `4.5:1`、`4.5:1`、`3:1`、`3:1` 的专项回归门禁。
4. 来源、事实修正、同步批次撤销三个嵌套对话框的 ID 从人物卡实例 ID 派生；相同人物并存挂载仍保持唯一。
5. 抽屉触发器由事件 `currentTarget` 显式记录；打开后焦点进入最上层抽屉，Tab／Shift+Tab 留在抽屉内，关闭后返回原触发器，触发器失效时进入确定性 fallback。
6. 来源读取允许 loading 中关闭，并通过请求世代丢弃迟到或被后续请求取代的响应。
7. 修正／批次写入中关闭按钮、取消和 Esc 同步禁用，抽屉暴露 `aria-busy` 和可见忙碌提示。
8. 人物卡鼠标关闭后恢复再 blur，卡片不会残留装饰性蓝框；键盘路径保留 `:focus-visible`。
9. 后端生产代码未改；FastAPI 路由回归扩为默认 V1、显式 V1、显式 V2 三组参数化用例。

## 3. 自动化门禁

| 门禁 | 实际结果 |
| --- | --- |
| 定向人物卡 Vitest | 4 files，32 tests passed |
| 全量前端 Vitest | 123 files，1052 tests passed |
| TypeScript | `tsc --noEmit` passed |
| 前端构建 | 157 modules，`frontend/dist/index.js` 3392.23 kB，passed |
| 全量 Python | 3433 passed，161 skipped，3 warnings |
| Skill 契约 | 12 passed |
| 插件打包 | `scripts/package_plugin.py` passed |
| Diff 格式 | `git diff --check` passed |

说明：第一次全量 Python 在尚未生成 `frontend/dist` 时有 1 个打包契约失败（3432 passed／161 skipped／1 failed）；完成前端构建后立即重跑，全量结果为 3433 passed／161 skipped。未把第一次失败写成已通过。

## 4. 真实浏览器证据

### 4.1 桌面尺寸

- 1440×900 覆盖后的页面实际 viewport 为 1426×891；人物卡宽度 1239.998px，页面与弹窗均无横向溢出。
- 2560×1440 覆盖后的页面实际 viewport 为 2534×1426；人物卡宽度 1239.998px，居中且保持 1240px 上限。
- 浅色宿主：`body` 为 `rgb(249, 248, 244)`；人物卡仍为白底 `rgb(255, 255, 255)`、深色文字 `rgb(31, 41, 55)`。
- 深色宿主：`body` 为 `rgb(20, 20, 20)`；人物卡仍为同一白底／深色文字，`color-scheme` 为 `light`。
- 原生筛选控件在两种宿主主题下均为白底、`rgb(31, 41, 55)` 文字和 `rgb(124, 135, 152)` 边界。

### 4.2 交互与焦点

- 指针关闭人物卡后，原卡片 `focus=false`、`focus-visible=false`、`outline=none`、`box-shadow=none`、`transform=none`。
- 来源抽屉打开后焦点落在“关闭来源证据”；只有一个可聚焦控件时，Tab 与 Shift+Tab 均保持在该按钮。
- Esc 关闭来源抽屉后，焦点返回对应“查看来源”。
- 来源抽屉打开时点击人物卡遮罩，来源抽屉和人物卡都保持打开，不会误关父对话框。
- 事实修正抽屉打开后焦点落在“关闭修正面板”，关闭后返回对应“修正”。
- 人物卡与来源／修正抽屉的 `aria-labelledby` 均指向实例唯一标题 ID。
- 页面控制台在明暗主题、历史、来源和修正路径中均无新增 error／warn。

### 4.3 截图

- [1440 深色宿主基础资料](screenshots/character-card-basic-1440.png)
- [1440 深色宿主状态与来源证据](screenshots/character-state-source-1440.png)

## 5. API 与运行态门禁

隔离候选热安装后：

| 请求 | 结果 |
| --- | --- |
| 默认 workspace | 200，`character-workspace/1` |
| `view_version=1` | 200，`character-workspace/1` |
| `view_version=2` | 200，`character-workspace/2` |
| facts 首分页 | 200，20 items，存在 `next_cursor` |
| QwenPaw `/` | 200 |

卸载／回退顺序及结果：

1. 通过公开 `qwenpaw plugin uninstall ai-novel-world-2026` 热卸载候选；PawApp 列表不再包含插件，插件 workspace 为 404，QwenPaw 根页面仍为 200。
2. 从仓库外备份 `/tmp/cc48-isolated-rollback.YmP9ab/ai-novel-world-2026` 回装旧包；默认 V1、显式 V1、显式 V2 全部恢复为 200。
3. 再次热卸载旧包并回装候选；上述 workspace、facts 和宿主页全部再次通过。
4. 候选包与隔离安装目录排除运行时 `__pycache__`／`.pyc` 后均为 246 个文件，路径＋内容确定性摘要一致：`9fb7db6405859ed81368aaf330dfb9e7f22c7ae919b2870ddf401cba49f8595b`。

## 6. 尚未通过的发布门禁

- 当前候选来自未提交施工工作树，因此还不能满足 `CC48-PACKAGE-G` 的“从精确提交构建”。
- 合成数据中唯一带 `commit_batch_id` 的事实已经是 `batch_reverted`，真实浏览器没有伪造当前批次来强行打开批次撤销抽屉；该抽屉的唯一 ID、忙碌态、关闭禁用和 Esc 禁用由专门 Vitest 覆盖。
- 来源 loading 竞态没有在真实网络中人为篡改响应时序；迟到响应失效由 deferred Promise 单元测试覆盖，真实宿主验证了 loading 抽屉可关闭和普通来源焦点闭环。
- 长期 `18088` 仍是旧人物卡安装包：默认 workspace 为 V1，显式 V1／V2 为 422。该事实只用于说明长期包尚未替换，不代表候选后端失败。
- 长期安装、长期数据库备份、长期旧包回退和《潮汐盲区》只读验收仍需用户单独授权；本轮没有执行。

## 7. 恢复信息

- 隔离旧包备份目录：`/tmp/cc48-isolated-rollback.YmP9ab/ai-novel-world-2026`
- 旧包确定性树摘要：`a084c127c2cacf5d55109c6186e1e9f8e647fe13604c47410869e4b93ef1906f`
- 隔离环境当前状态：候选包已重新安装；旧包备份仍保留。
- 长期 `18088` 没有发生状态变化，因此无需长期恢复动作。
