# MOSS-TTS-Nano 优化冗余台账

状态：**2026-08-29 `MNX-PRUNE-AUDIT=PASS`，`MNX-PRUNE=PASS`。W6 已仅删除 `RED-008/009/010` 中有精确零引用与替代回归证据的旧实现；其他条目依照下表保留。**

## 1. 保护规则

- 不删除或改写 `0010–0029` 已执行迁移、历史验收/审计原始证据、QwenPaw 上游、用户任务外 dirty 文件。
- 不因名称相似或测试覆盖重叠就删除；仍承担兼容、负向、并发、恢复、安全或历史回放语义的代码/测试必须保留。
- 子代理只能报告候选，不能自行删文件；主代理在各波汇合时补齐调用图，W6 串行执行精确删除。
- `RETAIN` 表示已证明当前有独立价值；`REVIEW` 表示替代路径接线后重新判断；`DELETE` 必须同时具备零调用者、替代测试、回退证据和精确恢复方式。

## 2. W0 候选与裁决

| ID | 精确文件/符号 | W0 调用证据 | 替代方向 | 当前裁决 | Owner / 复核点 | 恢复方式 |
| --- | --- | --- | --- | --- | --- | --- |
| `RED-001` | `backend/narration/official_presets.py::{PRODUCT_OFFICIAL_PRESET_IDS,PRODUCT_OFFICIAL_PRESETS,require_product_official_preset}`；catalog v1 schema/parser 及对应前端常量 | backend API、`scripts/verify_qwenpaw_lab.py`、章节 E2E、Python/TS 契约测试均有真实调用；当前是 6 项产品范围权威 | catalog v2 固定 18 项；是否保留 v1 只由 `P0-CONTRACT-GATE` 的真实调用者审计决定 | `REVIEW`，禁止现在删除 | `MNX-P0-CONTRACT` → `MNX-P0-INT` → W6 | Git 精确恢复符号及调用测试；不得恢复为 v2 的六项过滤 |
| `RED-002` | `frontend/src/narration/voice-source-panel.ts`、`voice-source-workspace.ts`中旧 official source/catalog/request/state/action/render 分支及对应 tests | P0 反向搜索确认旧六项官方候选的前端建档路径已无生产调用；上传/generated 私人来源工作区仍有真实调用 | 官方来源由 `official-voice-selection-panel` 的 18 项一步直用完全承接；原文件收缩为私人来源专用 | `DELETE-PARTIAL=DONE`：已删除精确官方分支；`RETAIN`：保留私人来源组件 | `MNX-P0-FE` / `MNX-P0-INT`；W6 零引用复扫 | Git 可恢复被删分支；恢复会重新引入双轨官方权威，仅用于回归定位 |
| `RED-003` | `frontend/src/narration/styles/t4-chapter.ts` 中旧 `--anw-chapter-player-height: 94px`、固定 `min-height/margin/padding-bottom` 计算 | P1 实现后 `rg` 零引用；聚焦测试还显式断言 `94px`/变量不存在 | 新 flex 布局、紧凑/展开/失败详情状态已承接 | `DELETE=DONE`：旧声明已由 PLAYER-VIEW 包删除；保留整份新样式 | `MNX-P1-PLAYER-VIEW` / `MNX-P1-INT`；W6 复扫 | Git 恢复精确声明仅用于回归定位，不恢复为正式布局 |
| `RED-004` | `narration_playback_progress.playback_rate_millis`、`backend/narration/narration_api.py` 旧 0.25–4.0 契约、前端 progress restore 依赖 | 当前持久进度、恢复测试、Edition 会话和历史 migration 均有真实调用 | 新作品 settings 成为倍速/音量唯一权威；旧 progress rate 只作兼容/故障回退 | `RETAIN-COMPAT`；不删列、不改历史迁移，只清理正常路径的重复权威 | `MNX-P1-BE-CONTRACT` / `MNX-P1-PLAYER-CORE` | 回退到 progress fallback；保留独立恢复/旧值 clamp 测试 |
| `RED-005` | `backend/narration/adapters.py::DisabledVoiceDesignAdapter` 及 capability-disabled 分支 | 生产 `VOICE_GENERATOR_NO_GO` 和能力关闭/卸载回退仍依赖 | VG GO 后仍需作为关闭开关和失败降级实现 | `RETAIN` | `MNX-VG-RUNTIME` / `MNX-VG-INT` | 不适用；它是必要降级路径 |
| `RED-006` | `backend/models.py::VoiceDeletionRequest`、`AssetTombstone` 与现有媒体删除防线 | schema/migration/媒体 PostgreSQL 测试有独立安全覆盖，当前不是完整产品服务 | P2-DEL 在原底座上窄化扩展 candidate/profile 两条生命周期 | `RETAIN`；严禁以“旧删除设计”名义重建或删除底座 | `MNX-DEL-AUDIT` / `MNX-DEL-BE` | 数据库只追加迁移；保留原安全约束与历史行 |
| `RED-007` | P0/P1/VG/DEL 新旧 tests 中未来出现的同语义重复夹具 | W0 尚无精确重复项；现有测试分别覆盖 v1 兼容、负向、恢复和运行验收 | 每波汇合后逐个 path/test name 记录；只有完全由等价或更强测试承接才可标记删除 | `REVIEW`，当前不允许批量删测试 | 各工作包报告 → W6 | Git 恢复精确测试；先跑被删测试与替代测试对照 |
| `RED-008` | `frontend/src/narration/styles.ts`、`styles/t2-c.ts` 中 `.anw-narration-character-picker*` 旧人物胶囊选择器样式 | `index.ts` 已改用 `CharacterVoiceRoster`；删除后 `rg` 零引用 | 人物覆盖卡片样式已承接 | `DELETE=DONE`：已删除精确选择器声明 | `MNX-P1-INT` → `MNX-PRUNE`；`reading-page`/新偏好/新覆盖 22 项通过，`pnpm typecheck` 通过 | Git 恢复精确 CSS 声明；不恢复旧选择器 DOM |
| `RED-009` | `frontend/src/narration/reading-page.ts::{createNarratorSettingsPanel,createScopeOverridesPanel}` 及仅验证旧组件的 `reading-page.test.ts` 用例 | 生产 `createReadingPage` 已改用 `ReadingPreferencesPanel` 与新 `scope-overrides-panel.ts`；删除后旧符号零引用 | 新受控语言/停顿/播放偏好/折叠覆盖已承接；第一人称与内心独白已迁入新高级区 | `DELETE=DONE`：已删除旧组件、其专用 helper 与仅服务旧组件的用例 | `MNX-P1-INT` → `MNX-PRUNE`；`reading-page`/新偏好/新覆盖 22 项通过，`pnpm typecheck` 通过 | Git 恢复精确函数和旧用例；不得重新接入生产树 |
| `RED-010` | `frontend/src/styles.ts` 旧章节失败列表/重试样式 | 新 `styles/t4-chapter.ts` 已包含详情抽屉内同名类的完整样式；删除后由 narration 样式唯一拥有 | 删除宿主重复声明 | `DELETE=DONE`：已删除精确重复段 | `MNX-P1-PLAYER-VIEW` → `MNX-PRUNE`；相关前端 22 项通过，`pnpm typecheck` 通过 | Git 恢复精确段落 |

## 3. W0 调用图命令

```bash
rg -n "PRODUCT_OFFICIAL_PRESET_IDS|PRODUCT_OFFICIAL_PRESETS|require_product_official_preset|moss-tts-official-preset-catalog/1\\.0" backend frontend tests scripts plugin.py
rg -n "voice-source-panel|voice-source-workspace|chapter-narration-panel|reading-rules-panel|pronunciation-panel|character-voice-panel" frontend/src -g '*.ts'
rg -n -- "--anw-chapter-player-height|94px|playback_rate|playback.*volume|volume" frontend/src/narration backend/narration tests/narration
rg -n "voice_deletion_requests|VoiceDeletionRequest|AssetTombstone|true_delete|delete.*voice|archive.*voice" backend/narration backend/models.py frontend/src/narration tests/narration
```

## 4. W0 退出结论

- 所有已识别旧路径在 W0 都仍有真实调用者或独立安全/兼容价值，没有可安全立即删除的文件。
- `MNX-PRUNE-AUDIT=PASS` 的含义是调用图和后续裁决流程已冻结，不是“已经完成冗余删除”。
- 各波新增实现不得旁路叠加；替代路径接线通过后必须把对应 `REVIEW` 条目更新为精确 `DELETE` 或有调用者/sunset 的 `RETAIN`。

## 5. W6 执行结论

- `RED-008/009/010` 已按冻结范围删除，没有删除文件、迁移历史、独立负向/恢复测试或用户数据。
- `RED-001` 仍被 QwenPaw 集成、章节 E2E 数据脚本和 v1 兼容测试调用，保留为 exact-six 兼容边界；新 v2 目录仍严格返回 18 项。退出条件是这些调用者全部迁移到 v2 并完成独立回归。
- `RED-004/005/006` 分别承担旧进度恢复、VoiceGenerator 能力关闭和删除安全底座，均不是冗余。`RED-007` 未发现可在不损失独立语义下删除的精确测试。
