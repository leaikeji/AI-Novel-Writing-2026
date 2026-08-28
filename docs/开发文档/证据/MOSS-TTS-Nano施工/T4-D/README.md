# T4-D Manifest v2、prepare-range 与流式媒体

状态：**`IMPLEMENTED_CANDIDATE_WITH_APP_ENTRY_AND_REAL_STORAGE_HOLDS`（2026-08-27）**。严格 Manifest v2、持久 revision/CAS、prepare-range 任务提权、播放资产可达性和专用媒体 fetch 已进入源码；共享 PawApp 入口、真实 PostgreSQL/媒体卷与固定宿主浏览器仍须由 T4-GATE 汇合，因此不得据此宣称产品播放器已经开放。

## 1. 实现边界

- 后端只公开可验证的 `narration-manifest/2.0`；解析时重算 segment 顺序、ready prefix/ranges、持续时间和强 ETag，章首首段未 ready 时不伪造公共 Manifest。
- `prepare-range` 验证 Edition、segment、Manifest revision 和服务端缓冲策略，只复用并短期提升既有未完成 job，不创建第二份 render job。
- media 路由必须同时提供 Edition 与 Manifest revision 头，并逐级验证 `MediaAsset → playback RenderAsset → ManifestSegment → exact Manifest → Edition`；只接受 GET/HEAD、单 Range、If-Range、If-None-Match，返回 200/206/304/416。
- 前端媒体读取使用独立 `window.QwenPaw.host.fetch` 适配器，透传 Range/条件头/`AbortSignal`，不复用强制 JSON 的公共请求器，也不在 URL 放 token。
- `VERSION_CONFLICT` 只在前端兼容层投影为 `MANIFEST_REVISION_CONFLICT`，不建立第二套后端错误状态机。

## 2. 实际验证

```text
.venv/bin/python -m pytest tests/narration/test_manifest_v2.py -q
7 passed

.venv/bin/python -m pytest \
  tests/narration/test_manifest_v2.py \
  tests/narration/test_narration_worker.py \
  tests/narration/test_audio_pipeline.py \
  tests/narration/test_domain_services.py -q
42 passed

pnpm exec vitest run \
  frontend/src/narration/playback-api.test.ts \
  frontend/src/narration/segment-playback-queue.test.ts \
  frontend/src/narration/narration-player.test.ts
3 files / 23 tests passed

pnpm typecheck
PASS
```

实现代理另在同一文件 hash 下完成当时全量后端 `1266 passed / 98 skipped` 与前端 `67 files / 566 tests passed`；主代理将在 T4-GATE 对最终汇合树重新执行全量门禁。

## 3. 仍为 HOLD

- `backend/app.py` 的 router 与 request-scoped storage factory 尚未由唯一入口 Owner 接线。
- 真实 PostgreSQL、`novel-media` inode/Range 流式读取、固定 QwenPaw Blob/CSP/鉴权和真实浏览器取消尚未验证。
- 失败段重试继续服从 T4-CONTRACT 的显式 HOLD；整书批量属于 T6。

## 4. 文件摘要

```text
backend/narration/manifest.py                              c0d832c9dd9bdc7c6585bd30b9c9c87d8b8c87ce0d6c043e03b47e7ffc06ab92
backend/narration/playback_api.py                          49bd21da8b936fe800a9fcfafc942feb2eec7c9bd84c8db9f78f24321f42cd7f
tests/narration/test_manifest_v2.py                        1f7c5a7800a7ce978039d666802b5fd1450f2d40558ac3baa3efaac9ac7a3a1d
tests/fixtures/narration/manifest-v2.json                  090c479eb782e6df22939f0718a4f533cfc1a79300aa5bf4c00df634cfb54d84
frontend/src/narration/playback-contracts.ts               ff518c089554df3cc38d53ec715c408481f028faab699e52436853b1e9f45673
frontend/src/narration/playback-api.ts                     bbd60ce69eb64b7c84295fe0613f64e878b6c80289d6363e115406a3853a5745
frontend/src/narration/playback-api.test.ts                05b2a359b4b58a0ea9f5b9963cc58a8f7bb6fd8a22fef01eb705cd4b6bb7e954
```
