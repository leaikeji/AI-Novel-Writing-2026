# T4-CONTRACT：核心朗读生产闭环冻结

状态：**`FROZEN_FOR_T4_W4_1`（2026-08-27）。T4-DEP 已通过；公共 API／DTO、状态机、媒体读取、编辑器桥、播放控制、唯一前向 migration、共享文件 Owner 和精确四组合 UI 门禁已经主集成 Owner 冻结。T4-A～T4-F 只可按本文的非重叠范围进入首波施工。本文是实现输入，不代表 Edition、合成、播放器或编辑器同步已经可用；对应 capability 在 T4-GATE 前继续为 false。**

## 1. 数据库与迁移裁决

不新增数据库、容器、表或普通字段；继续复用小说项目的同一个 PostgreSQL。现有 T1 表已经覆盖 request、Edition、segment render、media、Manifest、document state、progress、job/attempt/lease/resource fence 和 model run。

唯一前向迁移为 `20260827_0017_narration_generation_transaction_guards.py`，父版本固定为 `20260826_0016`，不得改写 0010～0016。它只完成三个 P0 修复：

1. Python 与 PostgreSQL 同步允许 generation request 从 `analyzed -> queued|cancel_requested|failed`；`analyze_only` 仍由数据库 check 和服务层禁止进入生成态；
2. 两个 `DEFERRABLE INITIALLY DEFERRED` constraint trigger 强制：request 提交为 `queued/rendering/partial_ready/ready` 时必须已有同 request 的 Edition；Edition 插入时 request 必须是 `create/update/batch` 且处于兼容生成态；因此 `analyzed -> queued` 与 Edition 必须同事务提交；
3. `narration_segment_renders.source_job_id` 增加唯一约束 `uq_narration_segment_render_source_job`，一个 segment-render job 只能标识一个 render。

升级前重复 `source_job_id` 会显式拒绝迁移，不静默改数据。实测 0016→0017、0017→0016→0017、正向同事务创建，以及无 Edition 的 queued 提交拒绝均通过。测试库仍为一次性 `ai_novel_world_2026_tts_test`／`tts_test`，验证后数据库和角色计数均恢复为 0；未创建新容器，长期容器仍只有既有 QwenPaw、PostgreSQL 和 TTS Sidecar。

## 2. 后端公共 wire：`narration-production-api/1`

所有 Pydantic wire model 使用 `extra="forbid"`；UUID、SHA-256、整数、布尔和枚举严格校验。客户端不得提交或覆盖 owner/workspace、effective policy、审批结论、服务端状态、voice rights、fingerprint 或资源锁。

### 2.1 请求与 Edition

`POST /api/ai-novel-world-2026/documents/{document_id}/narration-requests`

- Header：`Idempotency-Key`；
- Body：`intent: create|update|analyze_only`、`expected_draft_version`、`expected_content_hash`、`expected_settings_version`、`force_review`；
- T4 不接受 `batch`；`force_review` 只能收紧审核；
- Response：`contract_version`、`request_id`、`intent`、`request_version`、`workflow_state`、`source_revision_id`、`source_content_hash`、`settings_fingerprint`、`warning_count`、`blocker_count`、可空 `script_version_id/edition_id/current_manifest_revision`、`job_ids`、`replayed`。

恢复查询：

- `GET /api/ai-novel-world-2026/narration-requests/{request_id}`；
- `GET /api/ai-novel-world-2026/narration-editions/{edition_id}`。

不公开 `POST Edition`。Edition 只能由请求编排服务在同一短事务中创建；外部分析、Nano、FFmpeg、文件读取/写入均不得占用该事务。

T4-A 权威事务顺序固定为：

```text
working-copy CAS/保存屏障
  → TTS snapshot + settings snapshot
  → narration request + approved script
  → analyzed→queued
  → Edition + Edition segments
  → render cache lookup
  → cache miss jobs + pending renders
  → commit
```

任何异常整体回滚，不得留下 queued 孤儿。`analyze_only` 在 API、服务、job 和 DB 四层继续保证 Edition/job/render/media 数为 0。

### 2.2 Manifest、prepare-range 与媒体

- `GET /api/ai-novel-world-2026/narration-editions/{edition_id}/manifest`：可选 `manifest_revision`，支持 `If-None-Match`，返回唯一 `narration-manifest/2.0` 和强 ETag；首段尚未 ready 时返回工作流“尚不可播放”，不得伪造 pending Manifest；
- `POST /api/ai-novel-world-2026/narration-editions/{edition_id}/prepare-range`：Header `Idempotency-Key`；Body 为 `start_segment_id`、`reason: user_seek|resume`、`expected_manifest_revision`；Response 为 Edition、起始 segment/ordinal、`state: ready|preparing|failed`、当前 revision/etag、可用 ready range 和被提升的 job IDs；
- `GET|HEAD /api/ai-novel-world-2026/media-assets/{asset_id}/content`：支持单 Range、`If-Range`、`If-None-Match`，返回 200/206/304/416；T4 仅允许 `segment_playback`。

媒体 URL 不含 token、query、fragment 或本地路径。每次媒体读取除普通条件头外，客户端必须发送 `X-Narration-Edition-Id` 与 `X-Narration-Manifest-Revision`；服务端重新验证：

```text
fixed owner/workspace
  → novel
  → Edition
  → exact Manifest revision
  → ManifestSegment
  → RenderAsset(role=playback)
  → MediaAsset(state=ready, asset_class=segment_playback, actual hash/ETag)
```

只知道 asset UUID 不构成授权；master、reference、source、preview 和不可达历史资产不得通过播放路由读取。媒体前端使用专用 fetch，不复用强制 JSON 的 `apiRequest()`；Range、条件头与 `AbortSignal` 经 `window.QwenPaw.host.fetch` 原样传递。

## 3. 状态机、Worker 与发布

- Request：沿用 T1/T3，仅新增受限 `analyzed -> queued|cancel_requested|failed`；
- Edition：`created -> rendering -> partial_ready -> ready`，沿既有规则可进入 `unavailable`；
- EditionSegment：`pending -> queued -> rendering -> ready|failed|cancelled|quarantined`；
- Render：`pending -> rendering -> ready|failed|cancelled|quarantined`；
- Job/attempt/lease/resource fence：保持 T1 状态与 `moss-nano:inference` 最大并发 1；
- Manifest：只追加 revision；只有语义内容变化才新增，current pointer 使用 CAS；相同 revision+ETag 是幂等重放，相同 revision+不同 ETag 是冲突。

Worker 固定为：

```text
短事务 claim + commit
  → 事务外 Nano／转码／文件处理
  → 重新检查取消
  → 短事务重新获取 job fence + resource fence
  → 原子发布 model-run + media + links + render + attempt
  → 幂等推进 EditionSegment／Manifest／Request
```

晚到结果、过期 lease 或资源 generation 不匹配时不得发布。失败文件只能停留在 staging/orphan 恢复策略中，不得成为正式 Manifest 可达资产。

## 4. Manifest v2 与播放器公共契约

继续使用 T0-G 唯一 snake_case schema：`schema_version="narration-manifest/2.0"`、0-based ordinal、UTF-16 半开 source range、`manifest_revision>=1`、`ready_ranges` 半开。客户端必须重新推导并核对 ready prefix/range；pending/failed gap 不得静默跨越。

播放会话租约固定为：

```ts
type PlaybackLease = Readonly<{
  documentId: string;
  documentGeneration: number;
  editionId: string;
  manifestRevision: number;
  requestGeneration: number;
}>;
```

`NarrationPlayerController` 冻结最小能力：

```ts
interface NarrationPlayerController {
  readonly lease: PlaybackLease;
  readState(): NarrationPlayerState;
  bindManifest(manifest: NarrationManifestV2): void;
  playFromSegment(segmentId: string, source: "default"|"resume"|"gutter"|"command"|"readonly-segment"): Promise<PlaybackDecision>;
  pause(): void;
  resume(): Promise<PlaybackDecision>;
  setRate(rate: number): void;
  updateManifest(manifest: NarrationManifestV2): void;
  subscribe(listener: (state: NarrationPlayerState) => void): () => void;
  dispose(): void;
}
```

`NarrationPlayerState.phase` 只允许 `idle|preparing|buffering|playing|paused|blocked|ended|error`；状态至少包含 current segment/ordinal、offset/duration、rate、followPaused、结构化 failure。新 seek 递增 request generation 并取消旧 Range/fetch；旧 completion 必须由完整 lease 拒绝。Web Audio 是首选同一时钟调度，双 `<audio>` 为唯一回退；两条路径都只能在 segment 边界更新高亮和进度。

## 5. 编辑器桥与唯一正文写入链

```ts
type DocumentLease = Readonly<{ documentId: string; generation: number }>;
type OnEditorDocChanged = (event: Readonly<{
  lease: DocumentLease;
  nextValue: string;
  origin: "input"|"composition"|"undo"|"redo"|"ai-apply"|"ai-undo"|"recovery"|"external";
  composing: boolean;
}>) => void;
```

`NarrationEditorBridge` 必须暴露 `kind`、`lease`、capabilities、snapshot、Edition bind/unbind、UTF-16 mapping、播放意图解析、current segment decoration、自动跟随暂停/恢复、selection/focus 和 `dispose()`。冻结规则：

- 只有 CodeMirror `update.docChanged===true` 或 textarea 实际值变化调用 `OnEditorDocChanged`；
- decoration、scroll、selection、focus、gutter、seek 和播放进度写入正文/recovery/自动保存/TTS 的次数必须为 0；
- 普通正文点击只移动光标；仅 gutter、只读旧 Edition 段落和显式命令跳播；
- composition 期间不装 decoration、不滚动、不抢焦点；结束后只应用最新待跟随 segment；
- Bridge 与 `DocumentLease` 一一绑定；generation 变化必须 dispose 旧实例；
- textarea fallback 不伪装 editable decoration/gutter；
- working copy 与 Edition hash 不一致时不猜相似文本，旧时间轴只显示在 immutable Edition/字幕面板。

主集成 Owner 在 `workbench-v2.ts` 串行建立唯一 `commitEditorValue(event)`：textarea、CodeMirror、AI apply/undo 和 recovery restore 全部汇入同一 React/ref、recovery、600 ms debounce 与 CAS 保存队列。`flushDraft` 闭包捕获 documentId、generation、expected draft version 和 markdown；旧 generation 响应不得更新新章节、显示新章节冲突或读取全局新 ref 追保存。

章节切换固定顺序：取消 debounce → 完成/显式处理当前保存 → generation+1 → abort 旧 load/TTS/media → 新 load → documentId+generation 双校验 → 挂载新 Bridge。

## 6. UI 边界

用户已明确低于 1920×1080 的布局不需要考虑。本专项只验收 `1920×1080 × 助手收起`、`1920×1080 × 助手展开`、`2560×1440 × 助手收起`、`2560×1440 × 助手展开` 四个精确组合。低于 1920×1080、移动窄屏和 200% 等效小视口均为非目标、非测试项、非发布阻断项；历史小屏证据只保留为历史记录，不重做，也不形成继续兼容承诺。

播放器与复核面板只占 PawApp 编辑主区，不修改 QwenPaw 原生助手列。完整播放器是编辑滚动区下方的正常布局行，不使用 viewport fixed；复核面板打开时在其顶部使用 compact player，并隐藏下方完整播放器，禁止两个重叠播放器。T2“书本管理 → 朗读”继续负责旁白、通用声音、人物音色、发音和缓存设置；章节页面只负责生成、复核、播放、跳播和边听边改。

## 7. 首波非重叠施工与唯一 Owner

T4-DEP、公共 DTO、0017 migration 和本冻结文档由主代理持锁完成。首波只释放：

| 工作包 | 唯一写范围 | 禁止触碰 |
| --- | --- | --- |
| T4-A | `requests.py`、新 `edition_service.py`、`render_cache.py`、`narration_api.py` 及两个指定测试 | models、migration、app、jobs、manifest、media、publication |
| T4-B | 新 `worker.py`、`scheduler.py`、`test_narration_worker.py` | jobs、adapters、runtime、publication、models、migration |
| T4-C | 新 `audio_pipeline.py`、`transcoding.py`、`test_audio_pipeline.py` | storage、media、publication、models、migration |
| T4-D | `manifest.py`、新 `playback_api.py`、Manifest fixture／后端测试、`playback-contracts.ts`、`playback-api.ts` 及测试 | app、models、migration、页面入口、共享样式 |
| T4-F | `editor-bridge.ts`、`editor-codemirror.ts`、`editor-textarea-fallback.ts` 及测试 | workbench、index、共享样式、package/lock |

同一文件同一时刻只有一个 Owner。`backend/app.py`、`frontend/src/index.ts`、`narration/index.ts`、`narration/styles.ts`、`workbench-v2.ts`、`workbench-studio.ts`、根 `package.json`/lock 和最终接线继续由主代理串行持有。

## 8. 明确 HOLD

- `retry-failed-segments`：现有 DB 终态不允许 failed 回到 pending，未重新裁决前不公开；
- batch／全书生成：T6；
- production player、CodeMirror、自动人物识别产品 capability：T4-GATE 前仍 false；
- 云分析、人工脚本 mutation、继承／群体／高级匿名、casting rule：继续按 T3-GATE HOLD；
- reference clone、VoiceGenerator、生产通用音色、缓存物理清理：继续按既有阶段 HOLD。

## 9. 冻结时实际验证

```text
alembic heads                                      20260827_0017 (single head)
0016 -> 0017                                       PASS
0017 -> 0016 -> 0017                               PASS
live PostgreSQL 18 positive transaction            PASS
live queued-without-Edition deferred rejection      PASS
tests: migrations + domain + publication            19 passed / 3 skipped（无测试库 URL 时）
live PostgreSQL: publication                         2 passed
T4-DEP pnpm install/typecheck/build                  PASS
single ESM / imports / dynamic imports               1 / 0 / 0
disposable DB/role cleanup                           0 / 0
```
