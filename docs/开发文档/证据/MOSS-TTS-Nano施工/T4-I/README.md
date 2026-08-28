# T4-I 局部重生成、历史版本与播放进度

状态：**`IMPLEMENTED_CANDIDATE_WITH_MANUAL_RETRY_AND_REAL_BROWSER_HOLDS`（2026-08-27）**。局部失效投影、精确 ready-cache 复用、全缓存零任务收口、Edition 历史、working-copy 分歧、权利可用性、同 Edition 播放进度 GET/PUT、真实 offset 恢复、快速连续跳播与共享工作台接线已经实现并通过隔离测试；失败句段仍只提供资格投影，实际 retry endpoint/reset 及真实宿主验收仍 HOLD。

## 1. 已实现语义

- 局部重生成只按完整 render fingerprint 判断复用；不会把相似文本或跨 request 的 in-flight render 冒充缓存命中，也不改写历史 Edition/segment。
- 新 Edition 全部命中 authoritative ready render 且 `job_ids=0` 时，以 Request/Manifest 双 CAS 直接发布 Manifest，并把 Request `queued -> rendering -> ready`；精确重放返回同一 Manifest。
- 主集成把 canonical audio identity 修正为 `narration-render-input/2`：新 ScriptVersion 的句段 ID、来源定位 hash 和时间线停顿不再导致语音重复合成。旧 v1 行仅做原样兼容，不跨版本命中、不回写。
- Edition 历史投影区分 current/superseded/working-copy-diverged，并把 voice rights、Manifest 可播放性和 current pointer CAS 一起投影；查询本身只读。
- 播放进度只在同一 Edition 的较新 Manifest 中按精确 EditionSegment 和同一 ready range 恢复；不跨 Edition 猜测文本位置，也不在读取时改写进度。
- 服务端 `GET/PUT /narration-editions/{edition_id}/playback-progress?profile_id=...` 以 exact Edition／profile／Manifest／segment 和 CAS version 围栏读写；Session 在暂停、seek、句段边界、倍速、dispose 的有界时机保存，加载时只恢复服务端返回且同值的 Edition/profile 信封。
- Web Audio 和双 Audio 回退均使用真实 `startOffsetMs`；双 Audio 在 `loadedmetadata` 尚未到达时先暂停，后续元数据不会使音频偷跑，只在显式 resume 后单次播放。
- 前端 Edition 切换始终携带 `pointer_version` CAS；快速连续选择采用 latest-wins 和 AbortSignal，晚到结果不能覆盖最后一次意图。
- failed segment 目前只投影既有 `BackgroundJob.manual_retry` 资格，明确返回 `execution_supported=false`；未新增 endpoint、未重置终态。

## 2. 实际验证

```text
.venv/bin/python -m pytest -q -ra \
  tests/narration/test_regeneration.py
8 passed

.venv/bin/python -m pytest -q -ra \
  tests/narration/test_regeneration.py \
  tests/narration/test_edition_service.py \
  tests/narration/test_domain_services.py \
  tests/narration/test_manifest_v2.py
37 passed

pnpm exec vitest run \
  frontend/src/narration/edition-history.test.ts
1 file / 6 tests passed

pnpm exec vitest run \
  frontend/src/narration/edition-history.test.ts \
  frontend/src/narration/playback-api.test.ts \
  frontend/src/narration/segment-playback-queue.test.ts \
  frontend/src/narration/narration-player.test.ts
4 files / 29 tests passed

pnpm typecheck
PASS
```

2026-08-27 共享入口增量复验：朗读前端全套 `43 files / 453 tests passed`，包含 playback-progress contracts/API、Session、Player、dual-audio metadata 暂停回归与 Workbench 集成；`pnpm typecheck` 通过。

Python HTTP 组合只出现既存 Starlette TestClient 弃用警告。

## 3. 明确 HOLD

- 共享应用入口已汇合代码候选，但真实 PostgreSQL、正式媒体卷和固定 QwenPaw 页面尚未完成本闭环验收；不得把候选表述为当前普通用户已经可以切换/恢复 Edition。
- failed/cancelled/quarantined render 的人工 retry 执行协议、endpoint 与 UI 仍未冻结，当前仅显示资格，不执行隐式重试。
- 跨 Edition 的播放进度自动迁移继续禁止；正文变化后的目标位置只能由显式 Edition 切换流程和可校验映射决定。
- UI 只验收 `1920×1080 × 助手收起/展开`与 `2560×1440 × 助手收起/展开` 精确四组合；低于 1920×1080、移动、窄屏与 200% 等效小视口均不属于本专项目标或阻断范围。

## 4. 文件摘要

```text
backend/narration/regeneration.py                   68f7a67e8b25f869055f4a9cba103381f2deb90f76cb4d4e8e28a6069f0a6b50
backend/narration/progress.py                       1d48f9cf1c746ab7df9bd1adb463326c8bcc046b8ad51e7bd96e77618c6854ac
tests/narration/test_regeneration.py                0290deecaaf0ae03164ba4bc43b6a995de278b63c4b6207803ad54b248b2ae42
frontend/src/narration/edition-history.ts           ad4a8754759bb50079c72d831cf89c662e8fd41c1ba133c17b6b5fe98a00eace
frontend/src/narration/edition-history.test.ts      b9084afe0fd1f9df008617bcf3f18c120d40dc682629b7d32ff58fad77a0e66a
backend/narration/edition_service.py                e4c23fe10b7b9005e5520063163b902d3260ff4175d48682e8c9bb43e35d8f11
backend/narration/renders.py                        6a2e14ef20b27e2b82478d9db3a231f919976deabe0b8f5b1d2a3badb757265d
```

本表是首次候选的历史摘要，新增的 `backend/narration/playback_api.py`、`tests/narration/test_playback_progress_api.py`、前端 playback-progress contracts/API/Session/Workbench 及其测试未在表中。T4-GATE 必须在最终候选稳定后重新生成完整文件摘要，不能沿用本表作当前输入证据。
