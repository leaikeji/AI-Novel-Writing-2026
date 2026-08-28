# T2-D 音色来源、授权、试听与锁定实现证据

结论：**PASS_WITH_EXPLICIT_SOURCE_PREVIEW_AND_PROFILE_IDEMPOTENCY_HOLDS**。

工作包：`T2-D`（`PAR-C`）。Owner：子代理 `/root/t2d_voice_sources`；唯一集成责任人：主代理 `/root`。

执行日期：2026-08-26（Asia/Shanghai）；执行窗口约 16:45–17:27 CST。

> **现行个人本地版覆盖说明（2026-08-27）：** 本文是 T2-D 当时的 fail-closed 实现证据，其中 preset “权利／质量未批准”“没有获准来源”和 `VOICE_SOURCE_UNAVAILABLE` 是历史阶段状态，不再构成当前 `official_preset` 的关闭理由。固定 ONNX manifest 的 18 项现均可用于个人本地版，不设公众人物排除；现行目录、真实试听和来源证明由 T4-PRESET 接线，商业发布／再分发状态不参与本地 usability。

本结论表示：冻结的音色 profile/version HTTP 命令已具备可由最终唯一 dispatcher 调用的 T2-D handler；profile 列表、读取、改名和归档具备领域读写、固定本机作用域与 CAS；profile 创建只有在 caller 提供同事务的**持久幂等回执 port**时才会写入，默认 handler 真实 fail-closed；multipart、rights、试听状态和前端交互均有 fail-closed 实现与测试。它**不表示**持久回执 schema、preset、reference clone、VoiceGenerator、真实参考录音标准化、真实试听、试听状态存储、Nano 模型调用或产品入口已经可用。

## 1. 基线与冻结输入

| 项目 | 实际值 |
| --- | --- |
| Git 基线 | `2caab228af15d5e4a5e858264799a67aede62f3d`（`main`） |
| 前置门禁 | `T2-A = ACCEPT_UNCHANGED` |
| Python wire | `backend/narration/schemas.py` = `1e189e812cf674b0d9457328d4e74e95fda57a67b62a83f99eb31d299633fdbd` |
| HTTP facade | `backend/narration/settings_api.py` = `05b1a6be9ab58d30ccb12d143033a96aa8feb9fec7a6ed7ad1a6560894505378` |
| TypeScript wire | `frontend/src/narration/contracts.ts` = `9a62723164027da7607ee4df0dc39bd61e9c21e89519d6cfb13352dfb66fc5ec` |
| TypeScript API | `frontend/src/narration/api.ts` = `2c675603fe7e19b0d2dcf362015a432a2fe1cf36920b4096bf52c8a479b9dce8` |
| 运行态访问 | 未访问数据库、Docker、QwenPaw、模型、媒体目录、私人录音或真实小说 |

四个冻结输入在 T2-D 结束时与 T2-A 证据完全一致。工作树开工前已有 T0/T1、其他并行工作包和用户改动；T2-D 只修改本文件第 2 节六个精确路径，不暂存、提交、推送、清理或覆盖其他文件。

## 2. 交付文件与 SHA-256

| 文件 | 作用 | SHA-256 |
| --- | --- | --- |
| `backend/narration/voices.py` | profile CRUD/CAS/持久回执 port、rights 与媒体安全投影、窄 multipart、试听 unavailable 投影、10 操作 handler | `07a7193900c5a292f7aa8ea57ed33f66d095dc0679f6741c2a252e59ee05fcf0` |
| `tests/narration/test_voices.py` | 领域、作用域、持久回执缺失、幂等、multipart、rights、试听和 no-go 负测 | `3ecaaccab48f48ef15f7210e3c1403e9f4321d9724ff69dbd9bb7350112926c8` |
| `frontend/src/narration/voice-source-panel.ts` | capability/authorization 驱动的面板模型、显式授权上传、202 轮询、错误与取消状态、无障碍局部 renderer | `fd879643a2c5e40c0614b9b666f0d008d5fff879766921b374d3153d862c0bb3` |
| `frontend/src/narration/voice-source-panel.test.ts` | no-go 可见性、权限、上传、轮询身份、取消、错误和 renderer 测试 | `d59eef09ca8128ab81ef6b3a8efbe1f3568041a1a3f923da1158349fb2af9c08` |
| `frontend/src/narration/styles/t2-d.ts` | T2-GATE 后才可注入的局部响应式、焦点与 44 px hit target 样式 | `fe1d302b8a8e32144ac2388fa5abbc9384256bce227001f255f7e35a5a327ddf` |
| `docs/开发文档/证据/MOSS-TTS-Nano施工/T2-D/README.md` | 本证据 | 不记录自身 hash，避免自引用循环 |

## 3. 契约可调用与产品可用必须分开

`VoiceSettingsHandler.operations` 精确拥有 T2-A 冻结的 10 个音色操作；它不是第二套路由，也不安装 factory。

| operation | 当前行为 | 产品能力结论 |
| --- | --- | --- |
| `LIST_VOICE_PROFILES` | 固定 owner/workspace；指定 novel 时只返回该作品和可选私人库，不泄漏其他作品 | 可接线 |
| `CREATE_VOICE_PROFILE` | 默认无持久 receipt 时返回 `STORAGE_UNAVAILABLE` 且不建 profile；只有同事务 receipt port 先冻结 key/payload hash/resource identity 后才写 profile | **条件接线：需主代理补持久 receipt owner/schema** |
| `GET_VOICE_PROFILE` | 严格 scope；公开 rights 只返回来源 SHA-256；媒体只返回受控 asset link | 可接线 |
| `PUT_VOICE_PROFILE` | 精确 CAS；archived/unavailable 禁止改名；不修改任何 version | 可接线 |
| `ARCHIVE_VOICE_PROFILE` | 精确 CAS；只改变 profile 状态；历史锁定 version 不变 | 可接线 |
| `CREATE_PRESET_VOICE_VERSION` | 历史 T2-D 行为：先校验 profile/CAS/幂等键，再返回 `VOICE_SOURCE_UNAVAILABLE` + `preset_voice_source` | **历史阶段不可用：当时尚无目录／运行接线；“权利未批准”已不是当前本地关闭理由** |
| `CREATE_UPLOADED_VOICE_VERSION` | 在任何持久化前完整解析 metadata/audio/rights/hash；随后返回 `VOICE_SOURCE_UNAVAILABLE` + `reference_clone`；不建 asset/rights/version | **不可用：reference clone HOLD** |
| `CREATE_VOICE_PREVIEW` | 重新检查 profile/version/当前 rights；合法时返回 terminal `unavailable` 临时资源，`job_id/asset/expires_at = null` | **不可用：不伪造 queued/ready** |
| `GET_VOICE_PREVIEW` | 无持久试听资源时返回 `PREVIEW_UNAVAILABLE` | **不可用：未建试听状态存储** |
| `LOCK_VOICE_PROFILE` | CAS、version 归属和当前 rights 再检查在前；来源 gate 在任何字段修改前终止 | **不可用：没有已批准来源可锁定** |

`KeyError` 只用于最终 dispatcher 把非 T2-D 操作交给其他唯一 owner；HTTP 仍由冻结的 `settings_api.py` 统一做 DTO、错误码与状态码处理。

## 4. 状态、rights 与不可变边界

| 风险 | 实现与测试结论 |
| --- | --- |
| 跨作品/跨 owner | profile、version、rights、preview asset 逐层核对固定 owner/workspace 和 novel/profile 归属；跨 scope 返回 404 类错误，不回传数据 |
| 私人来源泄漏 | `VoiceRightsRecord.source_identifier` 仅在服务端计算 SHA-256；响应、错误、证据不含 locator、文件路径或原始说明 |
| rights 撤销/到期/复核阻断 | 每次试听与锁定前重新扫描 `revoked/expired/review_blocked` 事件及 `expires_at`；任何负面证据阻断新操作，但不改写历史版本 |
| 锁定版本可变 | profile 改名/归档不修改 `VoiceProfileVersion`；handler 在来源 HOLD 下不会进入锁定写入；测试快照核对 version identity/state/fingerprint/lock evidence 均不变 |
| 假 ready 试听 | T2-D 不创建 job、asset 或音频；只有冻结 parser 已确认的未来 ready resource 才可由前端播放受控 `/media-assets/{asset_id}/content` |
| 媒体 locator | profile 投影只在 preview asset 为同 scope、`preview/ready`、有 size/duration/SHA/verified evidence 时发布受控 link；不回传 storage path |
| 幂等 | profile create 使用 operation + fixed scope + key 的 deterministic identity，同时要求持久 receipt 冻结 canonical creation payload hash；同 key/同原始 payload 在 profile 后续改名后仍可安全返回当前资源，不同 payload 冲突。默认没有 receipt port 时不写 profile；不使用进程内 map 冒充产品持久化 |
| 前端旧草稿/污染版本 | 上传运行时重新绑定当前 `model.profile`、`profile_id` 和 profile CAS version，任何缺失、切换或过期均在 hash/API 前终止；选中版本还必须属于当前 profile，污染投影不会进入试听或锁定状态 |

## 5. Multipart 安全矩阵

解析函数 `parse_uploaded_voice_multipart` 是纯内存、无 I/O 的前置校验器；返回对象把原始 bytes 标为 `repr=False`。handler 必须先完成下表全部校验，再查询或创建持久行；当前来源 gate 随后关闭，因此成功解析也不会落盘。

| 项目 | 冻结行为 |
| --- | --- |
| envelope | 必须 `multipart/form-data; boundary=...`，拒绝 header 换行、parser defects、嵌套 multipart 和超过 `16 MiB + 64 KiB` 的包络 |
| 字段 | 恰好两个且唯一：`metadata`、`reference_audio`；直接扫描 raw `Content-Disposition`，要求一个普通 `name`，并只允许零或一个普通 `filename`；拒绝额外/重复字段、重复参数及 `name*`/`filename*` 扩展歧义 |
| metadata | UTF-8 JSON，最大 64 KiB；必须通过 `UploadedVoiceVersionMetadata` 严格 DTO 和显式 rights confirmation |
| 文件名 | header 与 metadata 完全一致；1–240、无 `/`、`\`、`.`/`..`、控制字符；扩展名与 MIME 一致 |
| 类型 | 只接受 `audio/wav` + `.wav` 或 `audio/flac` + `.flac`；拒绝重复 Content-Type、重复 Content-Transfer-Encoding，单个 transfer encoding 也只允许 `binary`/`8bit` |
| 大小 | 音频必须 1..16 MiB |
| 内容 | WAV 必须 `RIFF....WAVE`，FLAC 必须 `fLaC`；实际 bytes SHA-256 必须与 metadata 一致 |
| 失败副作用 | 不创建 `MediaAsset`、`VoiceRightsRecord`、`VoiceProfileVersion`，不写文件，不保存原始 bytes |

Python `email` headerregistry 会规范化并可能折叠重复的 disposition 参数，不能把“没有 parser defect”当成安全证据；实现因此在 `get_param()` 前读取 `raw_items()` 并自行计数普通/扩展参数。负测覆盖重复 `name`、重复 `filename`、`name*`、`filename*` 和双 Content-Transfer-Encoding，全部在返回原始 bytes 或进入 handler 持久化路径前拒绝。

本轮只使用 16 字节的合成 WAV header fixture 验证解析规则；没有使用、生成或保存真实音频。

## 6. 前端真实状态设计

1. 卡片只有在服务端 capability `visible=true` 时展示，只有 capability enabled/actionable、source availability 和 authorization 同时通过时可点击；历史 T2-A 当时只显示 disabled preset，reference clone 与 VoiceGenerator 隐藏。当前官方预设状态应由 T4-PRESET catalog、固定溯源、模型 fingerprint、实际推理和产品 GATE 投影，不得继续使用商业授权或人物标签作为禁用原因。
2. 上传必须勾选“有权用于声音克隆”和“已确认授权声明”，提供来源说明、合法文件、MIME/扩展名/大小与浏览器 SHA-256；disabled gate，以及当前 profile 缺失、`profile_id` 切换或 CAS version 过期，均在 hash 和 API 调用前终止。
3. `VoiceSourcePanel` 提供真实文件输入和“上传并创建候选版本”，但当前 T2-A capability 不会让该按钮出现或可用。
4. 选中版本必须属于当前 profile，且对应 source card 同时 `visible=true`、`enabled=true` 才允许试听；试听支持 202 `queued → running → ready/failed/cancelled/unavailable` 轮询，每次响应必须保持 preview/profile/version 三重身份，切换身份立即停止且不暴露 asset。
5. `unavailable/failed/cancelled` 均是 terminal；只有 strict ready resource 才携带 asset。取消使用 `AbortSignal`，错误只展示稳定、脱敏中文，不回显服务端私人文本。
6. 局部 renderer 含 `aria-labelledby`、status/alert live region、disabled/aria-disabled、键盘焦点、44 px 点击区、920 px 单列回流和 reduced-motion；共享样式注入留给 T2-GATE。

## 7. 自动化结果

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/narration/test_voices.py -q` | `20 passed` |
| `pnpm exec vitest run frontend/src/narration/voice-source-panel.test.ts` | `16 passed` |
| `pnpm typecheck` | exit 0 |
| `.venv/bin/python -m pytest tests/narration/test_settings_contract.py tests/narration/test_voices.py -q` | `49 passed`；仅 1 条既有 Starlette TestClient deprecation warning |
| `pnpm exec vitest run frontend/src/narration/contracts.test.ts frontend/src/narration/api.test.ts frontend/src/narration/voice-source-panel.test.ts` | 3 files，`38 passed` |
| `rg '[[:blank:]]+$' <T2-D 六个文件>` 反向断言 | `whitespace-ok` |

测试全部使用内存 store、短合成 header 和浏览器 `Blob`；没有正式 DB、迁移、容器、模型、真实媒体或网络副作用。

## 8. 最终 dispatcher 与 T2-GATE 接线

主代理后续唯一接线顺序：

1. 每个 request session 只创建一个 `SqlAlchemyNarrationStore(session)`。在没有持久 profile-create receipt 实现时，用 `VoiceSettingsHandler(store)` 保持 create fail-closed；若主代理以后增加专用 receipt schema/实现，必须与 profile 写入共享同一 session/transaction，再构造 `VoiceSettingsHandler(store, profile_creation_receipts=receipt_port)`。
2. 聚合 backend 在 `handler.handles(command.operation)` 为真时调用 `handler.dispatch(command)`；不要复制 T2-D 路由、DTO、权限或 HTTP 错误映射。
3. caller 负责一次业务动作的 commit/rollback；T2-D 只 `flush`。若出现 `NarrationApiFault`、rights、CAS、scope 或 validation 错误，整次权威写入回滚。
4. **[历史 T2-GATE 接线约束]** T2-GATE 当时只能接入 profile list/get/update/archive、create 的 `STORAGE_UNAVAILABLE` 和其他真实 unavailable 投影；持久 receipt 未完成前不得把 profile create 表述为可用。当时也不得把 `preset_voice_source`、`reference_clone`、`voice_preview` 或 `voice_generator` 翻为 enabled，不得添加演示音色、内存 receipt/试听表或伪 asset。后续 T4-PRESET 已可通过独立 catalog、溯源、真实 Nano 试听与专门 GATE 推进官方预设；本条不再是其商业权利门禁。
5. `VoiceSourcePanel` 和 `T2_D_NARRATION_STYLES` 只由共享前端入口 owner 组装/注入；T2-D 未修改 `index.ts`、共享 `styles.ts`、workbench 或 creative center。

## 9. 显式 HOLD、后续缺口与回退

历史 T2-D 收口时，schema 没有 profile-create idempotency receipt，也没有独立、可按 `preview_id` 读取的 voice-preview 状态资源，且当时没有完成 preset/reference source 接线。因此 T2-D 没有用进程内 map 冒充持久化，也没有在数据库事务内标准化音频或调用模型。后续由新的精确 Owner 工作包补：

- transaction 外的原始私有资产落盘、可解码性/时长/静音/削波/噪声校验和标准化；
- staging row → 外部媒体处理 → 短发布事务/fence 的恢复协议；
- 持久 preview identity/state/job/expiry，及 Nano 真实试听 worker；
- fixed official preset catalog 的 exact ID、官方来源、revision、manifest／prompt-code hash、模型 fingerprint、质量和真实推理证据；商业／再分发状态只单独记录，不作为个人本地批准条件；
- profile-create 持久 receipt 表/迁移、同事务 port 和 PostgreSQL 并发／改名后重放测试；
- PostgreSQL 其他并发幂等冲突专项测试。

这些缺口不应通过 T2-GATE 静默扩大能力。当前回退无数据副作用：只删除第 2 节六个 T2-D 新文件并从聚合 dispatcher/前端共享入口移除尚未发生的接线即可；不得删除数据库、卷、媒体、模型、用户正文或其他工作包文件。
