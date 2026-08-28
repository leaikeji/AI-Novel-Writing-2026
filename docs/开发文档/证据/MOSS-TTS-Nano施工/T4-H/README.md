# T4-H 旧稿、新稿与复核播放器共存证据

状态：**`IMPLEMENTED_CANDIDATE_WITH_FIXED_HOST_BROWSER_HOLDS`（2026-08-27）**。旧稿／新稿来源分歧、不可变 Edition 字幕、显式更新、显式 Edition 切换、复核面板内紧凑播放器和焦点恢复已进入领域与前端候选实现，并通过 32 项窄自动化；真实 Nano、固定 QwenPaw、系统中文 IME、真实音频和目标桌面浏览器仍由 T4-K/T4-GATE 验收。本报告不代表产品 capability 已放行。

## 1. 已实现契约

- `project_document_narration_context()` 只读比较 working copy 与不可变 Edition 来源快照，区分 `current`、`working_copy_diverged`、`superseded`、`unavailable` 和无当前 Edition；查询不移动指针、不创建请求、Edition、render 或 job。
- working copy 分歧后，旧 Edition 可继续播放，但默认只显示不可变旧稿字幕，不把相似文本重新贴回已修改正文；只有当前会话已验证且未冲突的句段映射才允许继续 decoration。
- 共享工作台在首次 `docChanged` 的同一次通知中立即投影 `working_copy_diverged`，无需重新加载章节；当前音频继续播放，编辑器跟随则按旧稿安全规则降级。
- 更新朗读必须由作者显式触发，并携带稳定保存回执、draft version、content hash、settings version、current Edition 和 pointer version；自动保存、键盘输入和过期 document generation 不能冒充更新动作。
- 历史／新 Edition 选择先形成只读确认投影，确认后才以 pointer CAS 切换；读取、选中候选或发现新版本都不会静默改换当前 Edition。
- 脚本复核打开时，完整章节播放器隐藏；只有确有活动播放会话时才在复核面板显示一个紧凑播放器。面板挂载、关闭和卸载不会暂停音频，关闭后焦点返回原触发控件。
- 后端命令适配器已把文档朗读上下文与显式 Edition 切换接入现有生产 API 事务边界，没有新增数据库、容器、队列或第二套状态机。

## 2. 自动化证据

### 2.1 Python

```bash
.venv/bin/python -m pytest -q \
  tests/narration/test_document_narration_state.py
```

结果：`16 passed / 0 failed / 0 skipped`。

覆盖只读投影、旧稿分歧、显式保存屏障、自动保存拒绝、历史 Edition、不可用 Edition、指针 CAS、播放进度、跨文档／跨 scope 拒绝和事务调用边界。

### 2.2 前端

```bash
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH" \
  pnpm exec vitest run \
  frontend/src/narration/chapter-narration-state.test.ts \
  frontend/src/narration/script-review-player.integration.test.ts
```

结果：`2 files / 16 tests passed / 0 failed / 0 skipped`。

覆盖当前稿时间线、旧稿不可变字幕、会话安全映射、复核面板紧凑播放器、播放不中断、稳定保存回执、显式选择／确认、指针竞争、精确起播和跨文档 fencing。

上述 `83 files / 739 tests passed` 只是历史快照。2026-08-27 的最新朗读前端集成回归为 `43 files / 453 tests passed`，包含实时旧稿投影与共享工作台候选；仍不能替代真实浏览器与音频验收。

## 3. UI 验收范围

用户已明确不考虑 1080P 以下布局。T4-H 与后续 T4-GATE 只验收：

| 分辨率 | 原生助手 |
| --- | --- |
| 1920×1080 | 收起 |
| 1920×1080 | 展开 |
| 2560×1440 | 收起 |
| 2560×1440 | 展开 |

低于 1920×1080、移动端、窄屏和 200% 等效小视口均为非目标、非阻断，不要求补做替代布局或截图。

## 4. 仍然 HOLD

- 未在固定 QwenPaw 中用真实 Edition、真实音频和真实复核请求验证紧凑播放器、旧稿字幕与编辑器同时存在。
- 未执行目标四组合的真实 DOM、键盘、焦点、ARIA、滚动与遮挡检查；源码自动化不构成视觉 PASS。
- 未执行系统中文 IME、章节切换／刷新、Blob/CSP、Range 鉴权、卸载重装和原生聊天非回归。
- 产品开关及 `automatic_speaker_detection`、`narration_synthesis`、`product_player`、`editor_production` 等 capability 在 T4-K/T4-GATE 前继续保持 false/HOLD。

## 5. 文件摘要

```text
backend/narration/document_state.py                              cac085ede58921d1ae35d0b086ee2287642f5bbbee83b7841413dfcccdaff6bb
tests/narration/test_document_narration_state.py                 accbfbcbbd2aa6df812a4cced3ce9e389cba048b00f4dd8524d824deffc567a4
frontend/src/narration/chapter-narration-state.ts                156c9b9fcbb251d6b1ec261901ce1635dc08d6d8af5fc1ba183ad0fff49b8f4d
frontend/src/narration/chapter-narration-state.test.ts           23fd472a3df41187e292528910e6f4accf43e6ecd06a125c73cbc31f4cdb3d98
frontend/src/narration/script-review-player.integration.test.ts  937adebfffc663377be1b8cec1bc217d59ecdc8c934cdab2dd70e3706270bd73
```

这些 hash 只冻结本证据首次形成时的历史输入；`chapter-narration-state.ts` 及其测试已继续变化。T4-GATE 必须对最终候选重新验证和生成摘要，不能沿用本表推定通过。
