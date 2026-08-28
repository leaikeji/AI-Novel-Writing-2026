# T2-A 朗读设置／音色公共契约冻结记录

结论：**ACCEPT_UNCHANGED；T2-A 已通过串行冻结门禁。**

工作包：`T2-A`（`SER`，共享 API/DTO 锁）。

Owner：主代理 `/root`。只读红队：`/root/t1_gate_audit`。

执行日期：2026-08-26（Asia/Shanghai）；收口时间 16:40 CST。

本结论只冻结 T2 设置、音色、人物绑定、试听、授权、通用音色池、发音与缓存的前后端 wire contract。它不表示 T2-B…T2-G 领域实现、页面入口、T2-GATE 接线、正式数据库迁移或多角色朗读产品已经可用。所有产品 capability 仍按本文件第 4 节保持非 actionable。

> **现行个人本地版覆盖说明（2026-08-27）：** 第 4 节的 `preset_voice_source=unavailable / PRESET_RIGHTS_NOT_APPROVED` 与 `voice_preview=VOICE_SOURCE_NOT_APPROVED` 是 2026-08-26 的历史 T2 冻结投影，不再是官方预设关闭理由。固定 ONNX manifest 的 18 项均纳入个人本地 `official_preset` 来源，不设 `Trump`／`Xiaoyu`／公众人物排除；当前是否 actionable 只由 catalog、固定溯源、模型 fingerprint、实际推理和相应产品 GATE 决定。商业发布／再分发未评估仅作独立信息。

## 1. 基线、边界与工作树

| 项目 | 实际值 |
| --- | --- |
| Git 基线 | `2caab228af15d5e4a5e858264799a67aede62f3d`（分支 `main`） |
| 前置门禁 | `T1-GATE = PASS_WITH_EXPLICIT_PRODUCT_AND_PRODUCTION_ROLE_HOLDS` |
| 冻结版本 | `narration-settings-api/1`、`narration-settings/1`、`narration-capabilities/1`、`narration-voice/1`、`narration-cache/1` |
| Python | 项目 `.venv`，CPython 3.12；代码仍遵守宿主 Python `>=3.11,<3.14` 边界 |
| Node/pnpm | Codex bundled Node；pnpm 11.19.0 |
| 数据/运行态 | 未访问数据库、模型、媒体、私人录音、真实小说、正式 QwenPaw 或 Docker |

开工时工作树已包含 T0/T1 候选以及其他专项和用户改动。T2-A 只修改第 2 节列出的七个冻结文件并新增本证据；未暂存、提交、推送、清理或覆盖其他路径。正式 PostgreSQL 仍保持既有迁移状态，T2-A router 也尚未接入 `backend/app.py`。

## 2. 冻结文件与 SHA-256

| 文件 | 作用 | SHA-256 |
| --- | --- | --- |
| `backend/narration/schemas.py` | Python 严格 DTO、能力矩阵、错误码、跨资源不变量 | `1e189e812cf674b0d9457328d4e74e95fda57a67b62a83f99eb31d299633fdbd` |
| `backend/narration/settings_api.py` | 29 个 HTTP 操作、typed command/dispatch、结构化错误和 fail-closed factory | `05b1a6be9ab58d30ccb12d143033a96aa8feb9fec7a6ed7ad1a6560894505378` |
| `frontend/src/narration/contracts.ts` | Python wire contract 的严格 TypeScript 镜像和 `unknown` 解析器 | `9a62723164027da7607ee4df0dc39bd61e9c21e89519d6cfb13352dfb66fc5ec` |
| `frontend/src/narration/api.ts` | PawApp 命名空间 API client、CAS/幂等、pollable preview、窄 multipart | `2c675603fe7e19b0d2dcf362015a432a2fe1cf36920b4096bf52c8a479b9dce8` |
| `tests/narration/test_settings_contract.py` | Python DTO、路由、错误、安全边界和 Python/TS 对账 | `71ad0a5e7c4005f08d50237a384c6fe621b97b77725967c62212288f592c0bf9` |
| `frontend/src/narration/contracts.test.ts` | 前端响应漂移、跨资源作用域、no-go 和媒体安全负测 | `e5d5ede8a8f6d0fb864f19dffc82f814a6f5749b8ac003794a1bad967fda9e8f` |
| `frontend/src/narration/api.test.ts` | namespace、CAS、幂等、multipart、轮询、错误与取消测试 | `007644d766d94e5ec3dfc0f29c464a9b60416a7fb42b78df420098c7d2e336fd` |

本 README 不记录自身 hash，避免自引用循环。

## 3. 字段与资源契约

| 资源族 | 冻结内容 | 关键不变量 |
| --- | --- | --- |
| 总览 | capability、authorization、runtime、settings、coverage、voice sources、cache | 所有子资源必须属于同一 novel；来源可用性必须与对应 capability 一致；runtime 不得越过产品 gate；cache capability 只能比全局 gate 更保守 |
| 朗读设置 | 旁白版本、语言、输出、复核策略、分析模式、正文规则、停顿、选角、播放偏好 | PUT 是完整替换并带 `expected_version`；bool/number 使用严格运行时类型；默认投影是 null identity + version 0 |
| 范围覆盖 | volume/chapter、启用态、覆盖字段、CAS | list 必须同 novel，`(scope_kind, scope_id)` 唯一；disabled 是空 version-zero 投影 |
| 云端授权 | notice、最小数据范围、可选 provider/model 对、consent CAS version、确认/撤销证据 | POST 必须 `Idempotency-Key`；DELETE 必须指定 `consent_id + expected_version`，延迟撤销不能命中新授权 |
| 音色 profile/version | profile 稳定身份、不可变版本、preset/uploaded/generated 来源、质量、rights、锁定 | nested version 必须属于父 profile；current version 必须唯一且 locked/accepted；client 不能提交 owner/workspace 或服务端版本 ID |
| 参考录音 | metadata + binary、WAV/FLAC、16 MiB、SHA-256、显式 rights | 只允许窄 multipart；公开 rights 只返回来源 SHA-256，不回显 locator/path/URL；source kind、purpose、risk code 均为受控值 |
| 媒体链接 | asset ID、受控 path、mime、size、duration、checksum | path 必须精确等于 `/media-assets/{asset_id}/content`，不能引用另一 asset 或暴露服务器/供应商 URL |
| 试听 | queued/running/ready/failed/cancelled/unavailable、临时 asset、过期时间 | POST 返回 202 资源；GET 可轮询；只有 ready 可发布受控临时媒体，错误状态只暴露稳定错误码 |
| 人物绑定 | dedicated/inherited/unset、locked profile/version、影响预览 | list 同 novel 且 character 唯一；unset 必须无 ID/voice/time 且 version 0；历史 Edition 不被静默改写 |
| 选角规则 | 条件、目标、priority、来源/version | client 只提交 rule input，不能伪造 rule ID/source/version；目标三种 shape 严格互斥 |
| 通用音色池 | 固定 24 槽、slot 状态、四类计数、reason、CAS | ready 必须 24 个 enabled/有 voice/全批准槽；missing/disabled/incomplete 不得伪装 production ready；无已批准 pack 时保持 missing/disabled |
| 发音 | novel/volume/chapter scope、replace/skip、优先级、CAS | replacement PUT 不接受 client entry ID；action 与 spoken text 严格对应 |
| 缓存 | source/locked/referenced/derived 分类、快照、preview token、确认执行 | 只能清理可回收派生资产；结果结构把 source/locked/referenced 删除数固定为字面量 0 |

TypeScript 对所有服务响应先以 `unknown` 接收，再按精确 key、枚举、UUID、SHA-256、时间和跨字段规则解析；不使用 `any`，也不把 200/202 自动当作可信资源。

## 4. Capability 冻结矩阵

| capability | state | visible | actionable | reason | required gate |
| --- | --- | ---: | ---: | --- | --- |
| `narration_product` | hold | true | false | `T2_GATE_REQUIRED` | T2-GATE |
| `reading_settings` | hold | true | false | `T2_GATE_REQUIRED` | T2-GATE |
| `narration_synthesis` | hold | false | false | `T4_GATE_REQUIRED` | T4-GATE |
| `product_player` | hold | false | false | `T4_GATE_REQUIRED` | T4-GATE |
| `editor_production` | hold | false | false | `T4_GATE_REQUIRED` | T4-GATE |
| `voice_preview` | unavailable | true | false | `VOICE_SOURCE_NOT_APPROVED` | T2-D |
| `preset_voice_source` | unavailable | true | false | `PRESET_RIGHTS_NOT_APPROVED` | T2-D |
| `reference_clone` | hold | false | false | `REFERENCE_CLONE_PRODUCT_GATE_HOLD` | T2-D |
| `generic_voice_pool` | unavailable | true | false | `GENERIC_VOICE_ASSETS_UNAVAILABLE` | T2-E |
| `automatic_generic_casting` | unavailable | false | false | `GENERIC_VOICE_POOL_UNAVAILABLE` | T2-E |
| `automatic_speaker_detection` | hold | false | false | `T3_GATE_REQUIRED` | T3-GATE |
| `cloud_assisted_analysis` | unavailable | true | false | `CLOUD_CONSENT_FLOW_NOT_READY` | T2-G |
| `voice_generator` | unavailable | false | false | `VOICE_GENERATOR_NO_GO` | T5-GATE |
| `cache_cleanup` | hold | true | false | `T2_GATE_REQUIRED` | T2-F |

技术 Sidecar healthy 不会自行翻转这些产品状态。T2-D/T2-E/T2-G 只能实现真实状态投影和已批准来源；不得把隐藏 no-go 按钮做成可点击演示，也不得导入、默认绑定或假装存在 24 个通用音色。

上表保留的是历史 T2 freeze 证据；其中 `PRESET_RIGHTS_NOT_APPROVED` 与 `VOICE_SOURCE_NOT_APPROVED` 不得继续用于当前 `official_preset` capability。官方预设目录与 24 槽完整通用音色包是两套独立来源：前者 18 项个人本地均可用，后者仍不得假装 production-ready。

## 5. HTTP/API 对照

当前 router 包含 **21 个唯一 URL、29 个 HTTP 操作**。

| 方法与路径 | 修改保护 | 响应 DTO |
| --- | --- | --- |
| `GET /novels/{novel_id}/narration-overview` | read | `NarrationOverviewResponse` |
| `GET/PUT /novels/{novel_id}/narration-settings` | PUT `expected_version` | `NarrationSettingsResource` |
| `GET /novels/{novel_id}/narration-scope-overrides` | read | `NarrationScopeOverrideListResponse` |
| `PUT /novels/{novel_id}/narration-scope-overrides/{scope_kind}/{scope_id}` | `expected_version` | `NarrationScopeOverrideResource` |
| `POST /novels/{novel_id}/narration-cloud-consents` | `Idempotency-Key` | `NarrationCloudConsent` |
| `DELETE /novels/{novel_id}/narration-cloud-consents/current` | `consent_id + expected_version` | `NarrationCloudConsent` |
| `GET/POST /voice-profiles` | POST `Idempotency-Key` | list / `VoiceProfileResource` |
| `GET/PUT/DELETE /voice-profiles/{profile_id}` | PUT body CAS；DELETE query CAS | `VoiceProfileResource` |
| `POST /voice-profiles/{profile_id}/versions/preset` | CAS + `Idempotency-Key` | `VoiceProfileVersionResource` |
| `POST /voice-profiles/{profile_id}/versions/uploaded` | CAS metadata + `Idempotency-Key` + narrow multipart | `VoiceProfileVersionResource` |
| `POST /voice-profiles/{profile_id}/previews` | `Idempotency-Key` | 202 `VoicePreviewResource` |
| `GET /voice-previews/{preview_id}` | read/poll | `VoicePreviewResource` |
| `POST /voice-profiles/{profile_id}/lock` | profile CAS + explicit quality confirmation | `VoiceProfileResource` |
| `GET /novels/{novel_id}/character-voice-bindings` | read | `CharacterVoiceBindingListResponse` |
| `GET/PUT /novels/{novel_id}/characters/{character_id}/voice-binding` | PUT `expected_version` | `CharacterVoiceBindingResource` |
| `GET/PUT /novels/{novel_id}/generic-voice-pools` | PUT `expected_version` | `GenericVoicePoolResource` |
| `GET/PUT /novels/{novel_id}/casting-rules` | PUT `expected_version` | `VoiceCastingRulesResource` |
| `GET/PUT /novels/{novel_id}/pronunciation-profile` | PUT `expected_version` | `PronunciationProfileResource` |
| `GET /novels/{novel_id}/narration-cache` | read | `NarrationCacheStatus` |
| `POST /novels/{novel_id}/narration-cache/cleanup-preview` | snapshot fingerprint | `NarrationCacheCleanupPreview` |
| `POST /novels/{novel_id}/narration-cache/cleanup` | snapshot + expiring token + explicit confirmation | `NarrationCacheCleanupResult` |

router 未接入共享 `backend/app.py`。在 T2-GATE 安装唯一 backend factory 前，调用统一返回 `SETTINGS_BACKEND_NOT_INSTALLED`，且不会先获取数据库 session。

## 6. 错误码与 HTTP 映射

| HTTP | 稳定错误码 |
| ---: | --- |
| 404 | `RESOURCE_NOT_FOUND`、`SCOPE_VIOLATION`、`VOICE_PROFILE_NOT_FOUND`、`VOICE_VERSION_NOT_FOUND` |
| 403 | `VOICE_RIGHTS_REQUIRED`、`VOICE_RIGHTS_UNAVAILABLE` |
| 409 | `CAPABILITY_DISABLED`、`VERSION_CONFLICT`、`INVALID_STATE`、`IDEMPOTENCY_CONFLICT`、`VOICE_VERSION_NOT_LOCKED`、`VOICE_SOURCE_UNAVAILABLE`、`GENERIC_VOICE_POOL_UNAVAILABLE` |
| 412 | `CLOUD_CONSENT_REQUIRED`、`CLOUD_CONSENT_REVOKED` |
| 413 | `PAYLOAD_TOO_LARGE` |
| 415 | `UNSUPPORTED_MEDIA_TYPE` |
| 422 | `REQUEST_VALIDATION_FAILED`、`REFERENCE_AUDIO_INVALID`、`VALIDATION_FAILED` |
| 500 | `RESPONSE_CONTRACT_VIOLATION` |
| 502 | `PREVIEW_FAILED` |
| 503 | `SETTINGS_BACKEND_NOT_INSTALLED`、`MODEL_UNAVAILABLE`、`STORAGE_UNAVAILABLE`、`PREVIEW_UNAVAILABLE` |
| 507 | `DISK_SPACE_INSUFFICIENT` |

请求校验不回显私人试听文本、参考音频或原始 locator；响应 drift 统一变为结构化 500；所有响应设置 `Cache-Control: no-store`。header 字段位置会把 `Idempotency-Key` 安全归一为 `idempotency_key`。

## 7. 自动化、审计与失败记录

| 检查 | 最终结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/narration/test_settings_contract.py -q` | `29 passed`，0 failed；仅 1 条既有 Starlette TestClient deprecation warning |
| `pnpm exec vitest run frontend/src/narration/contracts.test.ts frontend/src/narration/api.test.ts` | 2 files，`22 passed`，0 failed |
| `pnpm typecheck` | `tsc --noEmit` exit 0 |
| FastAPI OpenAPI smoke | `21 paths / 29 operations`；consent POST required idempotency header、DELETE required request body 均存在 |
| 七文件尾随空白检查 | `whitespace-ok` |
| 独立只读红队终检 | 上轮 5 组 P1 + 追加 2 组 P1 全部关闭；最终 `无 P0/P1`，建议 `ACCEPT_UNCHANGED` |

施工中保留的失败事实：第一轮 P1 修复后，Python 曾有 1 项失败，暴露 header alias 大写无法写入安全 field；已改为小写归一并加路由测试。TypeScript 当轮曾有 5 个类型错误、前端 1 项失败，均为新增负测的 fixture/局部变量问题，修正后全绿。追加 cache 交叉门禁后，前端曾有 1 项失败，证明 fixture 的顶层与 nested reason 不一致；已对齐并复验。OpenAPI 首次 smoke 把 29 个 operation 误写成 27 个 unique path，断言失败；修正为真实 `21/29` 后通过。没有把这些命令入口或 fixture 失败描述成产品代码已验收。

## 8. 红队关闭项

1. consent POST 增加幂等键，DELETE 精确 CAS 到 consent identity/version；
2. voice source、capability、runtime、cache 的跨投影状态 fail-closed；
3. generic pool 的 ready/non-ready、计数、enabled、reason 和身份/version 收紧；
4. parent profile/version、media asset/path、公开 rights locator 隔离；
5. unset character binding 的 `updated_at` Python/TS 一致；
6. scope override list 同 novel 且 composite key 唯一；
7. 公开 source/risk/reason code 与上传 MIME/size 固定，不接受自由路径或漂移上限。

## 9. T2-B…T2-G 接线说明

1. 后续工作包把本文件第 2 节七个 SHA 当冻结输入，禁止修改 `schemas.py`、`settings_api.py`、`contracts.ts`、`api.ts`；发现缺口必须退回主代理重新开契约锁。
2. T2-D/E/F/G 的领域模块只能经 `NarrationSettingsApiBackend.dispatch(command)` 接入；不得复制第二套 route、DTO、权限或错误映射。T2-GATE 由主代理安装/卸载唯一 factory，并串行接入 `backend/app.py`。
3. server 根据固定 owner/workspace 和目标 novel/profile/character 做 scope 校验；client ID 不能替代授权。错误 join 必须返回 404/SCOPE，不得回传跨作品数据。
4. CAS、幂等、rights、immutable voice version 和 cache preview/execute 两步协议必须由领域层再次执行，不能只依赖浏览器或 Pydantic。
5. 外部模型、音频标准化和媒体 I/O 不得占用长数据库事务。先持久化可重试状态，外部执行后再以 fence/CAS 发布。
6. **[历史 T2 接线状态]** 当时无已接线 preset catalog／24-slot pack，T2-D/E 只能返回 unavailable/missing/disabled 真实状态；reference clone 与 VoiceGenerator 继续隐藏且不可调用。现行个人本地官方预设目录已有独立 T4-PRESET 路径，不能再以商业权利未批准为 unavailable 原因；24 槽完整通用音色包、reference clone 与 VoiceGenerator 仍走各自独立门禁。
7. T2-B/C/D/E/F/G 分别只修改专项文档分配的文件；局部样式写各自 `styles/t2-*.ts`。共享 `frontend/src/narration/index.ts`、`styles.ts`、workbench、creative center 与 `backend/app.py` 留给 T2-GATE。

## 10. 未验证、风险与回退

未验证项属于后续阶段：真实 settings/voice/pronunciation/privacy 领域服务、数据库读写、参考音频解包与标准化、真实试听、UI、浏览器可访问性、PawApp 路由接线、安装/卸载和正式运行态。当前 API factory 有意保持未安装。

主要剩余风险是后续实现绕过 frozen dispatcher、把 capability 支持误当产品开关，或在 DTO 外返回 locator/raw error。文件 Owner、严格 parser、负向测试和 T2-GATE 集成锁用于阻断这些路径。

T2-A 没有运行态副作用。若门禁回退，主代理只回退第 2 节七个候选文件和本证据，并把 ready set 恢复为 T2-A；不得删除数据库、卷、模型、媒体、用户正文或其他专项文件。
