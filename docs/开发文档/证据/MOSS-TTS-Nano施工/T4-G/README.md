# T4-G 段落跳播、句段跟随与章节播放协调

状态：**`IMPLEMENTED_CANDIDATE_WITH_MAIN_WIRING_AND_DESKTOP_BROWSER_HOLDS`（2026-08-27）**。显式段落 gutter／右键上下文命令／`Mod+Alt+Enter`／textarea 光标跳播、句段级高亮与自动跟随、编辑优先暂停／显式恢复，以及 document／Edition／Manifest revision／request generation 完整围栏已经汇入共享工作台候选。自动化已覆盖入口接线；仍需由 T4-K/T4-GATE 完成固定宿主真实浏览器、真实媒体、系统 IME、精确四桌面组合与宿主非回归，因此不得据此宣称章节智能朗读已经对用户开放。

## 1. 实现边界

- 段落模型提供明确的 `▶` 入口语义、可读的“从第 N 段朗读”ARIA 标签、不可朗读/映射失效/安全降级原因；含多个句段的段落固定解析到该段第一个仍可验证的 `segment_id`。
- 可编辑 gutter、上下文命令、聚焦按钮的 `Enter`/`Space` 和显式 `Mod+Alt+Enter` 跳播均通过冻结的 `NarrationEditorBridge.requestPlayback()`；普通正文单击固定返回 `editor_click_moves_caret_only`，不会调用 Player。
- 快速连续跳播只允许最新 request generation 完成；迟到结果同时校验 document ID/generation、Edition、Manifest revision、request generation 和外部完整租约，不把旧章节或旧 Manifest 结果应用到当前页面。
- Player 只在句段边界驱动当前句段 decoration；手动滚动、光标移动、选择、输入和 composition 只暂停跟随，不暂停音频。作者显式“返回当前朗读位置”或重新发起播放后才恢复滚动。
- composition 期间不安装 decoration、不滚动、不改 selection；结束后再应用最新句段。已被正文编辑失效的旧 Edition 句段不映射到相似新正文。
- gutter、context、keyboard、decoration、follow、scroll、seek 的 `OnEditorDocChanged` 调用次数均为 0；本工作包不创建 narration job，不触发 recovery、自动保存或 TTS。
- textarea fallback 不伪造可编辑 gutter；仍允许显式“从光标所在段朗读”命令进入安全的 Bridge 解析路径。

## 2. 实际验证

本轮在 2026-08-27 的同一工作树和下列文件摘要下重新执行，而非沿用实现时口头结果。

### 2.1 T4-G 定向测试

```text
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  /Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm \
  exec vitest run \
  frontend/src/narration/paragraph-gutter.test.ts \
  frontend/src/narration/segment-follow.test.ts \
  frontend/src/narration/chapter-playback.test.ts

Test Files  3 passed (3)
Tests       31 passed (31)
```

覆盖：首句解析、禁用原因、普通点击 caret-only、上下文/键盘入口、快速连续跳播、document/Edition/Manifest/request 围栏、句段高亮、手动操作暂停、显式恢复、播放重新开始恢复、composition 缓冲、局部映射失效，以及所有展示动作保存回调为 0。

### 2.2 T4-D/E/F/G 兼容回归

```text
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  /Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm \
  exec vitest run \
  frontend/src/narration/playback-api.test.ts \
  frontend/src/narration/segment-playback-queue.test.ts \
  frontend/src/narration/narration-player.test.ts \
  frontend/src/narration/editor-bridge.test.ts \
  frontend/src/narration/editor-codemirror.test.ts \
  frontend/src/narration/editor-textarea-fallback.test.ts \
  frontend/src/narration/paragraph-gutter.test.ts \
  frontend/src/narration/segment-follow.test.ts \
  frontend/src/narration/chapter-playback.test.ts

Test Files  9 passed (9)
Tests       92 passed (92)
```

### 2.3 全局类型检查

```text
PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  /Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm \
  typecheck

tsc --noEmit
PASS
```

## 3. UI 验收范围

用户最终冻结的 TTS UI 发布验收矩阵且仅包含：

| 视口 | 原生 AI 助手 |
| --- | --- |
| 1920×1080 | 收起 |
| 1920×1080 | 展开 |
| 2560×1440 | 收起 |
| 2560×1440 | 展开 |

- 上述四个组合都是阻断目标；缺少任一组合的真实浏览器证据都不得通过 T4-GATE，不再区分“唯一目标”与“补充目标”。
- 低于 1920×1080、移动、窄屏和 200% 等效小视口均为**非目标、非阻断**；本轮不为其设计替代堆叠布局，也不补做截图或兼容修复。
- 本证据只关闭确定性逻辑与类型检查，尚未形成上述四个组合的固定 QwenPaw 真实 DOM 截图；浏览器证据仍由主集成/T4-GATE 完成。

## 4. 主集成接线

1. 先创建并绑定 T4-F Editor Bridge，再创建并绑定 T4-E Player/Manifest。
2. 在任何 gutter 操作发生前创建 `ChapterPlaybackCoordinator`，使现有 CodeMirror gutter 发出的 Bridge intent 也进入同一 fenced Player 路径。
3. 页面使用 `ParagraphGutterController.listButtons()` 渲染显式按钮，并把 context menu、`Mod+Alt+Enter`、聚焦按钮 `Enter`/`Space` 接到对应 controller 方法；普通正文 DOM 不安装 seek handler。
4. 创建 `SegmentFollowController` 后，把作者光标/选择/输入/composition 手势显式通知 `noteAuthorInteraction()`。CodeMirror adapter 已独立判定 programmatic/manual scroll；页面对 `view.scrollDOM` 只追加 `synchronizeNow()`，不能再次调用 `noteManualScroll()`，以免把程序滚动误判为人工操作。
5. 章节切换固定先使旧 document generation 失效，再依次 dispose gutter/follow/coordinator、Player、Bridge/adapter；旧 completion 即使随后返回也只能得到 stale 结果。
6. `ProductionNarrationPlayerController` 已实现 `setFollowPaused()`，但当前冻结的 `NarrationPlayerController` interface 未声明该方法；T4-G 使用 optional `FollowAwareNarrationPlayerController` 窄端口兼容。主集成可传入具体 Production controller，不能为方便复制第二套播放状态。

## 5. 仍为 HOLD

- `frontend/src/narration/index.ts`、workbench、播放面板、CodeMirror gutter extension 和 T4 样式已由唯一主集成 Owner 接线，但 `product_player` 与 `editor_production` 在 T4-GATE 前仍继续为 false。
- 显式 gutter 按钮、context menu、快捷键监听、“返回当前朗读位置”按钮及焦点恢复已有 DOM 候选和自动化；固定宿主键盘遍历、可见焦点、ARIA、高对比度与系统中文 IME 仍须真实浏览器验收。
- 精确四组合下编辑器、播放器、复核面板和右侧原生助手共存尚未截图验收；低于 1920×1080、移动、窄屏和 200% 等效小视口不进入 HOLD 清单。
- 真实 Manifest 刷新、PawApp 鉴权媒体 Range、Web Audio/双 audio、AAC-LC、独立相邻句段接缝和真实章节跳播尚须 T4-K/T4-GATE。
- 现有唯一正文保存链、600 ms debounce、保存中追保存、CAS 409、recovery、AI apply/undo 和章节切换仍须主集成回归；本工作包只证明其展示动作没有直接触发 `OnEditorDocChanged`。
- 固定 QwenPaw 中的卸载清理、刷新恢复、原生聊天与设置非回归尚未完成。

## 6. 文件摘要

```text
frontend/src/narration/paragraph-gutter.ts                 17b617b45ba17cf9b2a25529700e779b18db4468ced01cdd6e4fbb0f8ab9effe
frontend/src/narration/paragraph-gutter.test.ts            c0c5ccc9ee1fb5f7cf7a4260ee02ed59ec0fa0074c95312295e0b554efa801b2
frontend/src/narration/segment-follow.ts                   83a430dbe5ebf5a310d6986cb485f6a888309b0b0eedef769cd97fe90fceed24
frontend/src/narration/segment-follow.test.ts              95f99bf0171ca0d5f3d0b63486299b2c45ff613ef7827f5e0b4b688a0606460e
frontend/src/narration/chapter-playback.ts                 9b27411bec298fff8e0b01ecc1c8ec148dbff8ab9ae3a5d2922de3a5cd881da2
frontend/src/narration/chapter-playback.test.ts            f29bc62003c4b04f1b8b3423183bc433848461e38771a2979ca6a1f6d82db735
```

上表是本证据首次形成时的历史快照；`paragraph-gutter.ts` 及共享集成文件已继续变化，不得再当作当前源码摘要。T4-GATE 必须使用最终候选重新生成摘要和验证。
