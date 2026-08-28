# T4-J 章节朗读自动化证据

状态：**PASS（仅 T4-J 领域与前端模块自动化）**

日期：2026-08-27（Asia/Shanghai）

## 1. 范围与结论

本工作包只使用已冻结的 T4-A～T4-I 领域与前端模块契约，没有修改生产实现、API、migration、runtime、共享页面、样式或入口。窄自动化结果如下：

- 零阻断的显式作者请求会自动冻结脚本，建立唯一 Edition 并为每个句段入队；不改写 working copy。
- unknown 说话人在 `blockers_only` 下停在 `review_required`，不建 Edition、render 或 job，不调用生产队列。
- 完全 ready 的 v3 render 可被新请求复用；新 Edition 零新 job 收口为唯一 Manifest revision 1，幂等重放不增行。
- 公共 Manifest 不含台词、文本摘要/HMAC、音色版本或内部解析字段；v3 render 只保留服务端 key id 与 HMAC，不保留 naked text SHA。
- 播放进度只能在同一 Edition 中跟随更高 Manifest revision，仍需要精确 EditionSegment、ready range 和 CAS；不跨 Edition 猜测。
- 普通按键、单击、selection、highlight、follow 和滚动恢复都是纯前端呈现动作：零播放请求、零网络/TTS 请求、零正文保存回调。只有真实 `docChanged` 会产生一次已有保存链回调。
- 只有明确的 `Mod+Alt+Enter`、gutter、上下文命令或只读旧稿句段才进入播放控制器；seek/highlight/follow 不写正文。
- 本地编辑后失效句段不再贴回旧音频高亮；旧 Edition 音频可继续在不可变字幕中播放，页面状态投影为 `working_copy_diverged` / `immutable-edition-only`。

本工作包没有执行真实 Nano、真实浏览器、真实音频或 live PostgreSQL，因此不声称 T4-GATE 产品可用。本纯自动化工作包不做视口结论；后续 UI 只验收 1920×1080、2560×1440 各自助手收起／展开的四个精确组合，低于 1920×1080、移动、窄屏和 200% 等效小视口均不设计、不测试、不阻断发布。

## 2. 覆盖矩阵

| 自动化场景 | 文件 | 关键断言 |
| --- | --- | --- |
| 零阻断自动冻结 | `test_narration_e2e.py` | 显式作者证据、approved/auto-no-blockers、唯一 Edition、每段一 job、working copy 不变 |
| 阻断暂停 | `test_narration_e2e.py` | `review_required`、阻断计数、Edition/job/render/queue 均为 0、working copy 不变 |
| 缓存恢复与 Manifest | `test_narration_e2e.py` | 新 Edition 复用 render fingerprint、零新 job、ready Manifest、重放零增行 |
| 公共隐私 | `test_narration_e2e.py` | Manifest 无台词/短文本摘要/音色内部字段；render input v3 为 HMAC |
| Manifest 刷新后恢复 | `test_playback_recovery.py` | 精确句段、offset、倍速和 ready range 在 revision 2 恢复，读恢复不改写旧 progress |
| 不跨 Edition/不猜映射 | `test_playback_recovery.py` | 另一 Edition 不借用进度，损坏/变化的 segment mapping 失败关闭 |
| 进度 CAS | `test_playback_recovery.py` | 过期 writer 不能覆盖最新可恢复位置 |
| 编辑输入隔离 | `chapter-narration.integration.test.ts` | 普通键/单击/IME repeat 零播放、零 fetch、零保存；`docChanged` 恰好一次保存 |
| 明确 seek/highlight/follow | `chapter-narration.integration.test.ts` | 明确快捷键仅播放，句段级高亮/滚动，手动滚动暂停与显式恢复，零正文写入 |
| 编辑映射与旧稿音频 | `chapter-narration.integration.test.ts` | 失效当前稿 gutter 失败关闭；只读旧句段可播但不高亮当前稿，只显示旧稿字幕 |

## 3. 变更文件

- `tests/narration/test_narration_e2e.py`
- `tests/narration/test_playback_recovery.py`
- `frontend/src/narration/chapter-narration.integration.test.ts`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T4-J/README.md`

## 4. 验证记录

### 4.1 必选 Python 窄套件

```bash
.venv/bin/python -m pytest tests/narration/test_narration_e2e.py tests/narration/test_playback_recovery.py -q
```

最终结果：`6 passed / 0 failed / 0 skipped`。项目的 pytest `addopts=-q` 只渲染 `...... [100%]`；两个文件共收集 6 项测试。

### 4.2 必选前端窄套件

当前桌面 shell 未预置 Node `PATH`，首次调用在 Vitest 启动前以 `node: not found` 终止，不是测试失败。将 Codex 工作区自带 Node 运行时只加入本命令 `PATH` 后重跑：

```bash
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  pnpm exec vitest run frontend/src/narration/chapter-narration.integration.test.ts
```

最终结果：`1 test file passed / 3 tests passed / 0 failed / 0 skipped`。

### 4.3 相关冻结模块联跑

```bash
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  pnpm exec vitest run \
  frontend/src/narration/chapter-narration.integration.test.ts \
  frontend/src/narration/chapter-playback.test.ts \
  frontend/src/narration/paragraph-gutter.test.ts \
  frontend/src/narration/segment-follow.test.ts \
  frontend/src/narration/editor-bridge.test.ts \
  frontend/src/narration/chapter-narration-state.test.ts \
  frontend/src/narration/edition-history.test.ts
```

最终结果：`7 test files passed / 69 tests passed / 0 failed / 0 skipped`。

```bash
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" pnpm typecheck
```

最终结果：`PASS`（`tsc --noEmit`）。

## 5. 暴露的缺陷与修正

- **生产实现缺陷：未发现。**
- 编写自动化时发现测试夹具若用随机 UUID 对 render 排序后与 Edition segment 按 ordinal 直接 `zip`，会产生非确定配对。已在 T4-J 测试中改为按 `render_fingerprint` 精确配对，不修改生产实现。
- 首次前端命令的 `node: not found` 属于当前 shell 运行时路径问题；没有改动 `package.json`、lockfile 或任何系统配置。

## 6. 给主集成 Owner 的接线说明

1. 共享章节页只能把真实编辑器 `docChanged(nextValue)` 接入现有自动保存链；decoration、seek、highlight、follow、播放进度不得进入正文写链。
2. 普通单击保持光标语义；仅 gutter、显式上下文命令、`Mod+Alt+Enter` 和只读旧稿句段可调用 `requestPlayback`。
3. 页面不得在任何按键事件中调用生成 API；新 Edition 只由作者明确的“生成/更新朗读”动作创建。
4. 共享页面需同时绑定 document id/generation、Edition id、Manifest revision 和 request generation；任一维变化都废弃旧回调。
5. 当 working copy 与 Edition 来源分歧，只有当前会话内已验证的未相交映射可继续高亮；其他情况只显示不可变旧稿字幕，并提供显式“更新朗读”。
6. T4-GATE 仍须另行完成共享入口、真实 Nano/音频、live PostgreSQL、固定 QwenPaw 浏览器与 1920×1080／2560×1440 各自助手收起／展开的四组合验收；不得把本 T4-J PASS 提前表述为产品已可用。
