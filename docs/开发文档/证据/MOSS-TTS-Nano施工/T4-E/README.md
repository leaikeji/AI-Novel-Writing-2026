# T4-E 句段播放队列与播放器状态机

状态：**`IMPLEMENTED_CANDIDATE_WITH_PAGE_AND_REAL_AUDIO_HOLDS`（2026-08-27）**。Web Audio 优先、双 `<audio>` 唯一回退、3–5 段预取、缺口阻断和完整播放租约已进入源码并通过确定性测试；页面接线与真实浏览器接缝听检尚未完成，产品 capability 继续为 false。

## 1. 实现边界

- 默认连续预取 4 段，可配置范围严格限制为 3–5；遇到 pending、failed 或 cancelled 缺口立即停止，不搜索或跳到后续 ready 岛。
- 优先使用同一 Web Audio context；无法创建或解码时只回退到固定两个 `<audio>` 槽位，不创建无界 audio 元素。
- `PlaybackLease` 完整绑定 document ID/generation、Edition、Manifest revision 和 request generation；新 seek 中止旧 fetch/prepare，所有晚到 completion 均被 fence 拒绝。
- 状态机只使用冻结的 `idle|preparing|buffering|playing|paused|blocked|ended|error`，句段开始/结束是高亮和进度的唯一边界。
- 支持暂停/恢复和 0.5–3×；缓冲/解码期间点击暂停仍然有效，解码完成不会背着作者自动开播。
- 同 Edition 新 Manifest 只在播放边界后采用；已排队资产继续绑定原完整租约。

## 2. 实际验证

```text
pnpm exec vitest run \
  frontend/src/narration/segment-playback-queue.test.ts \
  frontend/src/narration/narration-player.test.ts
2 files / 16 tests passed

pnpm exec vitest run \
  frontend/src/narration/playback-api.test.ts \
  frontend/src/narration/segment-playback-queue.test.ts \
  frontend/src/narration/narration-player.test.ts
3 files / 23 tests passed

pnpm typecheck
PASS
```

## 3. 仍为 HOLD

- 共享 narration 导出、工作台播放器、EditorBridge 高亮、Manifest 刷新轮询和进度保存尚未由主集成 Owner 接线。
- 固定宿主中的 Web Audio/双 audio、真实 AAC-LC、相邻句段接缝、中文 IME、键盘/焦点/ARIA 仍须 T4-K/T4-GATE。
- UI 只验收 1920×1080 与 2560×1440；低于 1920×1080 不属于本专项目标或阻断范围。

## 4. 文件摘要

```text
frontend/src/narration/segment-playback-queue.ts            94b92f3d37f8316dd0cb34dc0e68565a3b27cb9e6de06117edc15f7ab00487e6
frontend/src/narration/segment-playback-queue.test.ts       2c49518fd17752e267715bb6f3c61d4fa3b0d6f3a8b72b46abfd36185a53a67a
frontend/src/narration/narration-player.ts                  f3a6661b8c6453f37143cd0a74b1a9f4d5c78066d32818a9afbccf5b8cea2089
frontend/src/narration/narration-player.test.ts             8385fafc89880c011343628566e3709f6a9bf94dc4805db7de44d6a70d5883e7
```
