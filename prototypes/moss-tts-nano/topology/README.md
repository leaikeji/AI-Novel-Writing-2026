# T0-B 四拓扑基准原型

状态：**受管子进程协议已通过真实 cancel / 推理中 SIGKILL / 新 PID 恢复与 30 分钟耐久；另建的生产窄协议 Linux/arm64 Sidecar 已通过真实基础/参考输入、故障恢复和独立 30 分钟耐久。历史 path runner 仍仅为测试 harness，浏览器路径仍未通过。完整结论以 T0-B 证据为准。**

本目录只保存 T0-B 原型测试和外部 runner 配置格式。权威入口是
`scripts/tts/benchmark_nano_topologies.py`；它先校验 T0-I fixture 与 T0-A
模型锁，再把每次不可变原始结果、WAV 和运行日志写到证据目录之外。证据目录只接收经
`render_benchmark_report.py` 严格校验产生的 `metrics.json`。

## 三种模式

- `contract`：默认无模型路径时使用。四个拓扑全部明确记录 `blocked`，只证明输入和报告链路可复核。
- `fake`：生成短测试 WAV，覆盖成功、失败、句段间取消和崩溃后复用；模型字段固定为 `fake`，不得用于任何性能或音质结论。
- `real`：必须显式传入 T0-A 固定 revision 的 `--source-root` 与 `--model-root`。脚本逐文件校验 size/hash 后才加载模型。

`--case-id` 是资源锁下的精确 smoke 过滤器，可重复指定；未知 ID 会在加载模型前拒绝。省略时才运行全部 27 cases。它不能用于把单 case 结果表述成完整基准通过。

进程内和受管子进程可由脚本直接加载官方固定 ONNX runtime。Linux ARM64 Sidecar 与浏览器
试听候选必须提供经过独立审计的窄 runner；示例文件只冻结握手，不是可运行实现。runner
从 stdin 收一个 JSON 请求、stdout 返回一个 JSON 对象，不得把正文放入命令行；返回音频必须
位于本次外部 runtime 目录。

## 受管本机 worker 协议 2.0

本机 worker 是持久 JSONL 进程，不再把 voice、seed 或采样参数固化为进程级请求：每次
`synthesize` 都必须携带 `request_id`、`voice`、`seed`、`max_new_frames`、
`sample_mode` 和受控 `output_path`。进程级参数只作缺省值。一次成功请求严格回传：

```text
started(pid, generation, request_id, parameters)
  -> inference_entered(pid, generation, request_id)
  -> ready(ready_wav_ms, internal_first_audio_ms?, ru_maxrss_bytes, actual hash)
  -> published(wall_ms, final path, actual hash)
```

worker 先写同目录唯一 `.part`，完整 WAV ready 并计算 actual hash 后才原子发布到最终路径。
父进程会校验事件顺序、request/PID/generation 一致性，并把不含正文的逐请求事件写到外部
runtime 的 `managed-worker.events.jsonl`。`process_start_to_ready_ms`、内部首段音频、完整 WAV
ready 和发布 wall 是四种不同语义；官方固定 runtime 不暴露内部时间戳时，
`internal_first_audio_ms` 必须为 null，不能用完整 WAV 时间冒充。

`cancel` 是对活 worker 的真实 JSONL 往返确认。崩溃探测在收到下一请求 `started` 后发送
SIGKILL，要求最终路径未出现、无 `published` 事件；恢复必须是更高 generation 的新 PID。
已经 ready 的片段在恢复前后重新计算 hash，且调用计数证明没有重合成。关闭后必须完成
wait/reap 并以系统进程检查证明无孤儿。

stdout 只能由一个专用 blocking reader thread 读取并写入 Queue；禁止把 `select()` 与
`TextIOWrapper.readline()` 混用，因为后者会预读相邻 JSON 行，使 OS fd 看似不可读。活动请求
若超时、收到非法 JSON、request/PID/generation 不一致或事件错序，adapter 立即进入 poisoned
状态；显式 stop/restart 前不得接收下一请求，迟到事件不得串入下一请求。adapter 强制
single-flight，并发调用直接 fail-closed，不在同一 JSONL stream 上交错两个请求。

## Linux/arm64 生产 Sidecar 协议 `moss-tts-sidecar/1.0`

生产 Sidecar 与下方历史 path runner 是两套明确分离的契约。HTTP 只在 Compose internal network
暴露容器端口，不发布 host port。每个 `/v1/*` 请求都必须带版本 header 与 32–256 字符的随机
token header；token 来自短期 secret file，不能出现在 URL、query、正文、响应或日志。

无参考的 `POST /v1/synthesize` 只接受：

```json
{
  "request_id": "controlled-request-id",
  "asset_id": "controlled-asset-id",
  "text": "bounded authorized text",
  "parameters": {
    "voice": "Junhao",
    "seed": 42,
    "max_new_frames": 100,
    "sample_mode": "fixed"
  }
}
```

参考克隆使用恰好两个 multipart part：`metadata` 是同一 JSON，并增加
`reference_audio:{reference_asset_id,declared_sha256,format,size_bytes}`；`reference_audio` 是无
filename 的 `audio/wav` 或 `audio/flac` bytes。协议递归拒绝 path、directory、URL、DB/DSN 和
token 字段；metadata ≤64 KiB、正文 ≤4,000 字、参考 ≤12 MiB 且 ≤12.5 秒。Sidecar 复算参考
hash、size、format、duration，受控 scratch 文件在 `finally` 清除；不得接收参考路径或 URL，
不得查 PawApp DB/媒体库。

成功响应只返回最多 16 MiB 的 `audio/wav` bytes；headers 必须精确带回 request/asset ID、actual
SHA-256、sample rate/channels/sample width、inference/ready/wall、Linux peak RSS、PID 与
generation。PawApp 重新校验 bytes 和所有 header，只在自己的媒体根执行 fsync + no-overwrite
原子发布；Sidecar 不挂载 PawApp media。`POST /v1/cancel` 只接受 request/asset ID，并返回
`cancel_requested` 或 `not_active`。

候选容器固定 Linux/arm64 wheels、模型/source 树 hash 与窄 LGPL FFmpeg；以 uid 65532、只读
rootfs、drop all capabilities、`no-new-privileges`、只读模型/source mount 运行。精确候选锁在
`sidecar/image-lock.json`，Compose 策略在 `sidecar/compose.production.yaml`，fake/真实 smoke 与
耐久驱动在 `sidecar/run_sidecar_gate.py`。现有 3/5/8/12 秒参考资产只可用于隔离技术测试，
真实通过不授予产品声音权利或分发权。

`run_sidecar_gate.py --mode reference-recheck` 只运行固定四档 reference case。启动容器前必须严格
验证 T0-C manifest schema/status/隔离权利边界，并逐档核对 basename、size、SHA-256、PCM WAV
descriptor、frame count 与一帧 duration 容差；每个请求前后再次复核。证据只保存 expected/actual
hash、size、duration、format 等脱敏审计字段，不保存参考 bytes 或绝对路径。

## Sidecar / 浏览器测试 harness 协议 1.0（非生产 GO）

下列 `output_path/audio_path` 只用于 T0 测试 harness。它允许任意文件路径的形态不能接入生产
PawApp。生产窄协议已经按上一节另行冻结和实测；不能因为两者都叫 Sidecar，就把本节的路径
字段、runner 响应或测试结论迁入生产实现。

- `capabilities`：返回 `{"status":"ok","protocol_version":"1.0"}`。
- `synthesize`：请求含 `text` 与受控 `output_path`；成功返回 `audio_path`、`first_packet_ms`、
  `wall_ms`、`peak_rss_bytes` 和可空 `peak_accelerator_bytes`。
- `restart`：必须真实终止并重建目标执行上下文，成功返回 `{"status":"ok"}`；仅刷新一个
  JavaScript 对象或复用同一已损坏 worker 不算恢复。

配置只能放可执行路径与超时，不写 token、cookie、用户正文、私人音频或带凭证 URL。

## 边界说明

- 目前官方 Python ONNX runtime 在 API 返回前才暴露完整 WAV，因此 `first_packet_ms` 的冻结语义是
  “adapter 边界第一次可取得可播放 WAV”的时间，不冒充内部首帧回调。
- 进程内拓扑无法在不杀死 PawApp 的情况下证明进程崩溃恢复，所以对应 fixture 必须是
  `blocked/CRASH_RECOVERY_UNSUPPORTED`；这是拓扑缺陷证据，不允许用假重启改成通过。
- 取消测试发生在第一个独立句段 ready 后、下一个句段尚未提交前，并由活 worker 回传
  `cancelled`；它只证明句段间取消。单句推理仍不能优雅抢占；SIGKILL 探测只证明进程隔离、
  不发布半成品与可重启，不能包装成普通用户取消。
- 同 seed 的重复探测必须如实记录每次 actual hash；即使某一轮 bit-exact，也不能据此把 seed
  当作内容寻址或幂等键。
- 真实人工听检属于 T0-C。T0-B 的真实通过音频仍标记 `listening=pending`，不能由脚本推断听感。
