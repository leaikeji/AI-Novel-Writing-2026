# T0-G Manifest 2.0 线协议与播放队列证据

状态：**Manifest 2.0 公共 wire contract 冻结产物已完成；24/24 TypeScript 专项测试、严格类型检查和 21/21 Range/ETag 测试通过。该结论只允许后续实现消费契约，不表示正式 API、产品播放器、独立相邻句段人听或 T0-GATE 已通过；`product_player_enabled=false`。**

## 1. 基线与边界

- 基线 commit：`9b5be4a`。
- Owner：T0-G Manifest 单一集成 Owner。
- 收口日期：2026-08-26（Asia/Shanghai）。
- 修改范围：`prototypes/moss-tts-nano/manifest-player/**` 与本 `T0-G/**`。
- 非目标：不创建数据库、正式 API、产品 UI 或媒体，不修改主计划/ADR/索引/根依赖，不运行 Nano，不读取用户正文或私人音频。
- 原 15/15 播放队列和 20/20 Range/ETag 结果作为历史原型证据保留；本轮在同一原型上补齐正式 wire shape、正反 fixture、严格 parser、派生一致性与 identity 输入门禁，最终计数为 24/24 和 21/21。

## 2. 唯一公共 Manifest 线协议

`manifest-v2.schema.json`、`manifest-player.ts` 和正向 fixture 现在使用同一协议，不再保留 camelCase/旧 revision/一基 ordinal 的第二套公共 DTO。

| 项目 | 冻结规则 |
| --- | --- |
| 命名 | 公共 JSON 全部使用 `snake_case` |
| 版本 | `schema_version = "narration-manifest/2.0"` |
| Manifest revision | `manifest_revision` 是安全整数且 `>= 1`；相同 revision/不同强 ETag 为 `revision_collision` |
| Segment ordinal | 从 0 开始、按数组位置连续；range 使用半开区间 `end_ordinal_exclusive` |
| Manifest ETag | `"<64 位小写 SHA-256>"` 形式的强 validator |
| Buffer policy | Manifest 内嵌不可变 `buffer_policy`：版本、最小段数、最小时长、目标段数和章末例外 |
| 服务端 ready 权威 | wire 必含 `ready_ranges`、`ready_prefix_count`、`default_start_ready`、`last_playable_start_ordinal` 和 `status` |
| 公共文本证据 | 只保留整章不可变来源的 `source_sha256`；segment 不暴露短文本 SHA/HMAC，`text_sha256/text_hmac` 属于未知字段并拒绝 |
| 媒体 URL | 只允许 `/api/ai-novel-world-2026/...` 下无 query/fragment/credentials/traversal 的相对路径；token 不进入 URL |
| 音频身份 | `audio.actual_sha256` 是实际播放字节摘要，`audio.etag` 必须精确等于带引号的该摘要 |

顶层 wire 字段固定为：

```text
schema_version, edition_id, chapter_id, source_revision_id, source_sha256,
buffer_policy, manifest_revision, etag, generated_at, status,
ready_prefix_count, default_start_ready, last_playable_start_ordinal,
ready_ranges, segments
```

每个 segment 只允许：

```text
segment_id, ordinal, paragraph_ordinal, source_block_key,
source_start_utf16, source_end_utf16, gap_after_ms,
render_status, audio, failure
```

`audio` 只允许 `url/actual_sha256/duration_ms/sample_rate/channels/etag`。`ready` segment 必须有 audio 且 `failure=null`；`failed` 必须有脱敏 failure 且 `audio=null`；其他状态两者均为 null。UTF-16 offset 必须为非空半开范围，同一 source block 内不得与较早范围重叠。

## 3. ready-window 精确一致性

公共 `ready_ranges` 是服务端权威响应字段，但不能成为脱离 segment 真相的第二套状态：客户端 parser 会从 `segments + buffer_policy` 重新计算并逐字段比对。

1. 只扫描 `render_status=ready` 且具有合法 audio 的最大连续区间；不能跨 pending/queued/rendering/failed/cancelled gap。
2. 非章末区间至少存在一个起点同时满足 `minimum_segments` 和 `minimum_duration_ms` 才进入 `ready_ranges`。
3. `duration_ms` 等于区间内音频时长加内部 `gap_after_ms`，不包含区间末段之后的 gap。
4. `last_playable_start_ordinal` 是该 range 内最靠后的立即可播起点；章末例外只在 policy 明确允许时生效。
5. `ready_prefix_count` 是从 ordinal 0 开始的原始连续 ready 数；它不因未达到播放门槛而伪造成 0。
6. `default_start_ready` 只在 ordinal 0 属于可播 range 时为 true；顶层 `last_playable_start_ordinal` 是所有 range 的最大合法起点，无 range 时为 null。
7. `status` 由 segment 状态确定性派生：全 ready 为 `ready`，部分 ready 为 `partial_ready`，否则依次为 `pending/failed/cancelled`。

任何 range 起止、数量、时长、最后起点或顶层派生字段不一致都会使整个 Manifest fail-closed。播放器只消费已经通过该一致性验证的服务端 range，不在 UI 中自行拼接零散 ready segment。

## 4. 产物与 fixture

- `manifest-v2.schema.json`：Draft 2020-12 公共 shape、严格 `additionalProperties=false`、状态相关 audio/failure 条件。
- `manifest-player.ts`：snake_case DTO、`parseManifest()`、严格未知字段/URL/ETag/UTF-16 校验、ready 派生复核、播放决策、refresh CAS 与队列 guard。
- `fixtures/manifest-v2.valid.json`：两个合法 ready range，覆盖非章末双门槛与章末例外。
- `fixtures/manifest-v2.invalid.json`：revision 0、弱 ETag、错误时间、非法 policy、短文本 digest、token URL、hash/ETag 不一致、offset 和 ordinal 错误。
- `manifest-player.test.ts`：schema 判别器、正反 fixture、公共摘要阻断、URL token/traversal、派生字段逐项漂移、播放/刷新/队列负向测试。
- `range_etag_server.py`：媒体强 ETag/Range 原型和 Manifest identity `revision>=1`、source hash、强 ETag 输入门禁。
- `queue-metrics.json`：证据自身使用独立 metrics schema；其中 camelCase 指标键不是 Manifest wire 字段。

## 5. 自动化验证

### 5.1 Manifest parser、领域不变量与播放器

重写后的首次运行是 23 项中 1 项失败：当一个 ready range 同时触发局部结构错误时，validator 过早跳过了与 `segments + buffer_policy` 的精确派生比对，测试在 `ready_ranges[0].start_ordinal` 处暴露该缺口。随后把条件改为“基础数据仍可安全派生就继续做领域比对”，并补入 schema 文件直接对账；最终完整复跑如下，未把首次失败记成通过。

```text
PATH=<Codex bundled Node>:$PATH pnpm --dir prototypes/moss-tts-nano exec vitest run \
  --config manifest-player/vitest.config.ts

exit=0
test_files=1 passed
tests=24 passed, 0 failed, 0 skipped
duration=164 ms
```

覆盖 `schema_version`、revision>=1、0-based contiguous ordinal、UTF-16、未知字段、无公共短文本摘要、受控无 token URL、actual hash/强 ETag、ready ranges/顶层派生值精确一致、章末例外、failed gap、热刷新冲突、快速 seek 与公平老化。

### 5.2 严格 TypeScript 检查

```text
pnpm --dir prototypes/moss-tts-nano exec tsc --noEmit \
  --target ES2022 --module ESNext --moduleResolution Bundler \
  --resolveJsonModule --allowSyntheticDefaultImports --strict \
  manifest-player/manifest-player.ts manifest-player/manifest-player.test.ts

exit=0
diagnostics=0
```

### 5.3 Range/ETag 与 Manifest identity

```text
prototypes/moss-tts-nano/.venv/bin/python \
  prototypes/moss-tts-nano/manifest-player/test_range_etag_server.py

exit=0
tests=21 passed, 0 failed, 0 skipped
duration=0.527 s
```

### 5.4 JSON 语法与 schema 对账

`python -m json.tool` 对 schema、正向 fixture、负向 fixture 和 `queue-metrics.json` 均返回 0。Vitest 直接导入 schema 与两个 fixture，额外核对 schema discriminator、revision 下限、严格 segment 字段、短文本摘要缺席，并由 parser 分别接受正向 fixture、拒绝负向 fixture。

## 6. 既有浏览器证据与不能推出的结论

历史隔离 Chromium 151 原型仍证明：章首 pending gap 不跳过、中段合法 ready window、failed gap 阻断、rapid seek 最后意图、Web Audio 同时钟调度和双 `<audio>` 回退可运行。截图和测量继续由 `queue-metrics.json` 引用。

但两个播放测量重复使用同一个授权 segment，只证明调度，不替代两个独立合成相邻句段的人听。当前仍未验证：

- 固定 QwenPaw 宿主 Blob/CSP、生命周期与正式 bundle；
- 正式 PawApp owner/workspace/novel/Edition 鉴权、持久 CAS、反向代理和大文件流式 Range；
- 两个独立真实相邻句段的人工接缝、漏字/重复/爆音/自然停顿；
- 系统中文 IME、200%、完整键盘/焦点/ARIA；
- 真实 Nano 不可抢占推理反馈与长时间调度稳定性。

因此本工作包只消除“Manifest wire contract 互相矛盾”这一门禁，不得写成产品播放器、媒体 endpoint、人听质量或 T0-GATE 已通过。

## 7. 非自引用产物 SHA-256

| 产物 | SHA-256 |
| --- | --- |
| `manifest-v2.schema.json` | `41b3d1573ef727dbd1727456cf168d32d244d6d9786a5c019931758ed5dc2df2` |
| `queue-metrics.json` | `923cafcbb8ab4ef4b845e22689ed54f8246eac5f10c99a016ed0a82dc24445d5` |
| `range-etag.md` | `84239e86606e75cae0489978775efc3a021be35aa1d9b18a50ee2ecedc09d1b6` |
| `manifest-player.ts` | `bbfcabacda27f8efd2aad12555491df6c4805f4805d6251d0df09145b93d4730` |
| `manifest-player.test.ts` | `69f9cb24748b52d41fcc740392884cb2b74c6417552103cc0ddbd248bb5263b2` |
| `fixtures/manifest-v2.valid.json` | `3938d8fcb53e0eab896c15315aee3ba4c7b0569a6d090b4ddfd5c0413510d2b8` |
| `fixtures/manifest-v2.invalid.json` | `1be46058bd8abf36bd9ea7fa40f9bbadbb0fd816c6bbb451a5cedee9d7b96718` |
| `range_etag_server.py` | `0bc6582a8f6ea584ea8e3aa992df0af6415dcfc52af5eac49df62f693b70fe85` |
| `test_range_etag_server.py` | `85ac8ec55956daabe1f0dcf323e7c5429530affe58be6332b9485b4603abc4d5` |
| `vitest.config.ts` | `95a4c7457265f73ea68c12d48ed0b10f01a5e13a6e46657519840fdb079de2d3` |

`README.md` 不记录自身 hash，避免自引用循环。

## 8. 回退与接线

本轮没有数据库、模型、媒体、QwenPaw 或用户内容副作用。若 T0-GATE 否决，只能由集成人精确回退本工作包列出的 T0-G/manifest-player 文件，不得清理其他共享工作。

后续 T1/T4 必须直接消费本 schema/fixture 生成或实现 DTO；不得恢复 camelCase 公共 Manifest、revision 0、一基 ordinal、客户端自造 ready range、短文本摘要或带 token URL。正式 endpoint 与播放器继续保持 `HOLD`，直到各自阶段门禁完成。
