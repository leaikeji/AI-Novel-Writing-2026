# T0-G HTTP Range、强 ETag 与 Manifest CAS 隔离原型

状态：**专项原型自动化通过；不是正式 PawApp API，不单独构成 T0-GATE 通过。**

日期：2026-08-26（Asia/Shanghai）

## 1. 目标与边界

本原型只验证播放器后续接入所需的三项窄契约：

1. HTTP 请求只能用服务端已授权的 `asset_id` 取媒体，请求内容不能成为文件路径；
2. 媒体响应使用实际响应字节的 SHA-256 作为强 ETag，并正确处理单区间 Range、条件请求和 HEAD；
3. Manifest 热刷新只接受同一 Edition、同一 source 的非递减 revision，且相同 revision、不同 ETag 必须作为冲突拒绝。

产物：

- `prototypes/moss-tts-nano/manifest-player/range_etag_server.py`
- `prototypes/moss-tts-nano/manifest-player/test_range_etag_server.py`

没有创建正式路由、数据库表、媒体、容器或 QwenPaw 接线；测试只使用 `TemporaryDirectory` 中自行生成的 72 字节假 WAV 字节串，没有读取真实用户媒体。

## 2. 冻结的原型行为

### 2.1 授权与路径隔离

- 调用方先以显式映射构造 `AuthorizedAssetRegistry({asset_id: server_owned_path})`。
- 对外路由仅接受 `/media/{asset_id}`；`asset_id` 解码后必须匹配窄安全字符集，再按映射键查找。
- 请求里的文件名、绝对路径、`../`、编码后的 `/` 或 `\` 都不会传给 `Path`、`open` 或其他文件系统 API。
- 阶段 0 注册时把授权文件冻结成不可变字节快照。因此响应体和 ETag 一致，也不会因注册后的文件改写产生 TOCTOU 漂移。

### 2.2 HTTP 媒体契约

| 输入 | 原型结果 |
|---|---|
| 普通 GET | `200`、全量字节、`Accept-Ranges: bytes` |
| HEAD | 与 GET 相同的 representation headers，无响应体 |
| `bytes=start-end` / `start-` / `-suffix` | 单区间 `206`，安全的 `Content-Range` 与准确 `Content-Length` |
| 多区间、非法区间、越界区间 | `416`、`Content-Range: bytes */{size}`、空响应体 |
| `If-None-Match` 命中 | `304`、空响应体；GET/HEAD 按弱比较处理缓存验证 |
| `If-Range` 精确命中强 ETag | 执行 Range |
| `If-Range` 是弱 ETag、旧 ETag 或日期 | 忽略 Range，返回当前完整 representation |

服务端发出的 ETag 形式为 `"<64 位小写 SHA-256>"`，没有 `W/` 前缀，因此是强 validator；摘要由实际冻结响应字节计算。

### 2.3 Manifest refresh CAS

`accept_manifest_refresh(current, incoming)` 的判定顺序为：

在进入该判定前，`ManifestVersion` 先拒绝 `manifest_revision < 1`、非 64 位小写 SHA-256 的 source hash，以及弱 ETag/非 `"<64 位 SHA-256>"` 强 ETag。完整公共 Manifest shape 与 ready-window 一致性仍由 `manifest-v2.schema.json` 和 TypeScript parser/validator 负责。

1. `edition_id` 不同：`edition_mismatch`；
2. `source_revision_id` 或 `source_sha256` 不同：`source_mismatch`；
3. revision 下降：`stale_revision`；
4. revision 相同而 ETag 不同：`revision_collision`；
5. revision 与 ETag 都相同：接受为 `idempotent`；
6. revision 增长：接受为 `advanced`。

切换 Edition 或 source 是另一项显式产品操作，不能伪装成同一播放会话内的热刷新。

## 3. 自动化证据

环境：原型冻结的 CPython 3.11.16，标准库 `unittest`、`http.server` 与 `http.client`；服务只绑定测试进程的 `127.0.0.1` 随机端口。

执行命令：

```text
prototypes/moss-tts-nano/.venv/bin/python \
  prototypes/moss-tts-nano/manifest-player/test_range_etag_server.py
```

结果：

```text
Ran 21 tests in 0.527s

OK
exit=0
```

覆盖项包括：

- 全量 GET 的实际 SHA-256 强 ETag、长度与字节一致性；
- HEAD、闭区间、开区间、suffix、end clamp 和 `206 Content-Range`；
- 非法/多 Range 的 `416 bytes */size`；
- `If-None-Match` 强/弱/list/`*` 与 `If-Range` 强比较；
- 未授权 ID、原文件名、绝对路径、正反斜杠和百分号编码 traversal 均为 404；
- 注册后改写临时文件不改变已冻结 representation；
- CAS 的 revision>=1/强 ETag 输入门禁，以及 advanced、idempotent、revision collision、stale、Edition/source mismatch。

## 4. 不能由本原型推出的结论

- 这是标准库 loopback 原型，不是 `/api/ai-novel-world-2026/...` 下的正式 API，也未实现 PawApp 身份、workspace/book/chapter/Edition 范围校验或审计。
- 为确保阶段 0 的字节/ETag 一致性，资产被完整载入内存；生产媒体必须改为不可变对象存储或经过校验的流式文件句柄，不能复制该内存策略处理长章节。
- 只支持一个 byte range，明确拒绝 multipart ranges；尚未验证 CDN、反向代理、TLS、CORS/CSP、超时、并发限流、慢客户端和大文件吞吐。
- `If-Range` 的 HTTP-date 被当作不匹配并回退完整响应；未实现完整日期 validator 语义。
- CAS 函数只复核 Manifest identity/revision/ETag；完整 JSON Schema、ready ranges、segment/audio/failure 仍由 Manifest parser/领域验证负责，它也不替代 source/Edition 的服务端授权和持久化事务 CAS。
- 本测试没有使用真实音频，因而不证明浏览器解码、双播放器接缝、Web Audio 排程或听感质量。

正式 T4 接线前仍需由唯一 API/领域所有者冻结：服务端授权 asset id 的签发与失效、不可变媒体存储、Manifest 持久 revision/ETag、事务 CAS、鉴权失败响应、审计、GC 引用可达性和代理层 Range 非回归。

## 5. 回退

本原型没有修改运行态和用户数据。若 T0-GATE 否决，可精确移除上述两个 prototype 文件和本证据文件；其他 Manifest/player 原型不受影响。
