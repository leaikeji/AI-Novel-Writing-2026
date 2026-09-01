# 计划 45 浏览器验收

日期：2026-09-01（Asia/Shanghai）

## 客观 Chromium 探针

- 浏览器：Edge/Chromium `152.0.4191.53`。
- 正向组：`220 Hz`、`440 Hz` 各覆盖 `0.5×、0.75×、1×、1.25×、1.5×、1.75×、2×、2.25×、2.5×、2.75×、3×`。
- `preservesPitch=true` 时主频分别稳定在 `219.7265625 Hz` 与 `439.453125 Hz`。
- 负对照 `preservesPitch=false` 能检测到随速率移动的主频：`220×1.5→329.58984375 Hz`、`220×2→439.453125 Hz`、`440×1.5→660.64453125 Hz`、`440×2→880.37109375 Hz`。
- 所有样本 `waiting=0`、`stalled=0`、`error=0`；控制台 `0 error / 0 warning`；探针总状态 `pass`。

## 尚未完成

隔离小说没有可供作者连续听检的旁白、男声、女声真实章节音频，因此没有把频率探针冒充真人听感，也没有把播放器最终门禁写成 PASS。

裁决：`PITCH45-BROWSER=PASS_OBJECTIVE_PROBE`，`PITCH45-AUTHOR-LISTENING=HOLD`。
