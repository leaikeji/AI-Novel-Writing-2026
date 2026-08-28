# T0-C Nano 质量基准原型

该目录只定义阶段 0 质量驱动器与 runner 边界，不是 PawApp 生产代码。`benchmark_nano_quality.py` 本身不下载模型，也不把模型、参考音频或生成音频写入 Git 证据目录。

## 唯一执行协议：复用 T0-B managed worker

T0-C 不再为每个句段启动一次 `official_onnx_quality_runner.py`。驱动器只加载 T0-B 的 `ManagedSubprocessOnnxAdapter`，由它启动一次：

```text
python scripts/tts/benchmark_nano_topologies.py __worker__ ...
```

模型在 worker ready 握手前只加载一次；随后 20 个质量 case 的每个句段都通过 JSONL 请求显式传入 `voice`、`seed`、`max_new_frames` 和 `sample_mode`，并要求每个事件具有完全一致的 request_id/PID/generation，按 `started -> inference_entered -> ready -> published` 顺序原子发布 WAV。模型、媒体、worker event log 和 fixture 原文请求均留在仓库外运行目录。

指标语义明确分离：

- `process_start_to_ready_ms`：一次性的模型进程启动与 ready 时间，只放在运行参数/诊断，不计入 steady-state RTF；
- `request_to_internal_first_audio_ms`：worker 若能提供，表示内部 codec 首个非空音频，明确不是客户端可播放首包；当前冻结 worker 返回 `null`；
- `request_to_ready_wav_ms`：完整 WAV 在 worker 边界 ready，是严格结果契约里的 `first_packet_ms`；
- `request_wall_ms`：一次 worker 请求从开始到原子发布完成；case 的 `synthesis_wall_ms` 为各句段 request wall 之和，不含进程启动；
- `peak_rss_bytes`、worker PID/generation、事件顺序和实际 WAV SHA-256 均逐句段保存于 `diagnostics.managed_worker_segments`。

`--quality-matrix` 固定选择 19 个中文/对话/文本规范化 case 加 1 个 independent-segment 接缝 case，共 20 个；不把 T0-B 已验的故障/取消/崩溃控制面 case 混入质量矩阵。`--same-worker-probe-repetitions 3` 可在同一 worker 内用同参数重复，记录 PID/generation 与每次实际输出 hash，不把“同 seed”误报成内容幂等键。

`official_onnx_quality_runner.py` 与 `fake_quality_runner.py` 仅保留为早期单进程 smoke 的可复核历史和输入校验测试；当前质量驱动器没有 `--runner-script` 入口，也不会调用它们。任何非 T0-B worker 路径都会被拒绝。

`fake_quality_runner.py` 只生成确定性测试 WAV，用于验证驱动器、hash、WAV 检查和 independent-segment 调用次数。它必须显式使用 `--allow-fake-runner-for-tests`，且驱动器会拒绝将这类结果写入仓库证据目录。

## 干跑与真实运行

干跑只验证 fixture/授权文本/组合 hash、coverage、case 选择和证据契约。非参考 case 只能是 `skipped`，3/5/8/12 秒参考占位只能是 `blocked`，绝不产生 `passed`。

```bash
prototypes/moss-tts-nano/.venv/bin/python scripts/tts/benchmark_nano_quality.py \
  --fixture-manifest tests/fixtures/narration/benchmark_manifest.json \
  --output-dir /tmp/t0c-dry-run \
  --dry-run
```

真实运行必须由主代理释放 `LOCK-NANO`，并显式给出 `--source-dir`、`--model-dir`、`--media-output-dir`、`--source-revision` 和 `--model-revision`。默认 worker 固定为仓库内 T0-B 脚本，没有下载、网络或隐式模型路径。3/5/8/12 秒参考克隆即使提供并通过授权/hash/时长检查，当前也会以 `managed_worker_reference_audio_unsupported` 保持 `blocked`，因为冻结 JSONL 请求尚无 reference-audio 字段；驱动器绝不静默忽略参考音频。

参考输入技术格式固定为仓库外普通文件、显式 SHA-256、48 kHz 双声道 16-bit PCM WAV，并检查实际时长 tolerance；仓库内路径、symlink、hash 漂移、错误时长或错误格式均 fail-closed。T0-C 已从项目自有 fixture 对应的现有 Junhao 输出无损裁切出仓库外 isolated-test-only 技术候选，但这些文件不替换 fixture 的 `placeholder_only`、不具备产品/分发权利，也不能在 T0-B reference API 冻结前接线。

20 case 命令骨架：

```bash
prototypes/moss-tts-nano/.venv/bin/python scripts/tts/benchmark_nano_quality.py \
  --fixture-manifest tests/fixtures/narration/benchmark_manifest.json \
  --output-dir /path/to/redacted-evidence-candidate \
  --source-dir /external/pinned-source \
  --model-dir /external/pinned-model \
  --media-output-dir /external/controlled-media \
  --source-revision PINNED_SOURCE_REVISION \
  --model-revision PINNED_MODEL_REVISIONS \
  --quality-matrix \
  --same-worker-probe-case-id narration-neutral \
  --same-worker-probe-repetitions 3
```

听感结论不由程序推断。真实输出也只会在 `metrics.json` 中标记 `listening.status=pending`，由审听人在 `listening.md` 实际听完后填写。
