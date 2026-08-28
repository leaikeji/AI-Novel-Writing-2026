# T0-C 持久受管 worker 真实 20-case 结果

> 后续状态：本页记录的是当时的 macOS JSONL worker run，原始 metrics/占位结果不改写。其后 T0-B 已冻结 `moss-tts-sidecar/1.0` multipart bytes reference 协议，并在 Linux 真容器完成 3/5/8/12 秒 isolated-test-only 技术 smoke；产品权利和人工听感仍未通过。

状态：**技术矩阵 20/20 passed；人工听感 20/20 pending，因此这里只证明受管 worker 技术执行与音频文件检查通过，不证明中文朗读主观质量通过。**

## 运行边界

- Run ID：`T0-C-20260826T041358+0800-31505-aee0deec`
- 时间：`2026-08-26T04:13:58+08:00` 至 `04:15:10+08:00`
- 执行次数：1 次真实 run；退出码 0；没有修复重试。
- 选择：`--quality-matrix`，19 个中文质量 case + 1 个 independent-segment 接缝 case；另在同一 worker 内对 `narration-neutral` 做 3 次同参数重复 probe。
- 资产：固定 source tree `dfeedbbfae13dd04c78280e660de7d3d3c5297a82f720da44e7cb9029b4ccc65`；固定 ONNX model tree `0aa88a384369f3b9a3bdc12a039559b7bced3ce47be8360106895b2dd81b634d`。
- worker：`scripts/tts/benchmark_nano_topologies.py` SHA-256 `2ccf2ca714d66371c4ca09b1608512f7d4c51d9fda5f7c980742988c1ca1abb1`。
- 外部音频：位于受控媒体根下的 `$MEDIA_ROOT/T0-C-20260826T041358+0800-31505-aee0deec/`；本文和 metrics 不保存绝对私人路径。

## 精确命令（路径脱敏）

```bash
prototypes/moss-tts-nano/.venv/bin/python scripts/tts/benchmark_nano_quality.py \
  --fixture-manifest tests/fixtures/narration/benchmark_manifest.json \
  --output-dir <new-evidence-candidate> \
  --source-dir <pinned-source> \
  --model-dir <pinned-model> \
  --media-output-dir <controlled-media-root> \
  --source-revision cc7bdf19c7639c0870dab22045a33b442760f6be \
  --model-revision f52645cb467506d8e18e746ddd59482685b74e58+ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae \
  --expected-source-tree-sha256 dfeedbbfae13dd04c78280e660de7d3d3c5297a82f720da44e7cb9029b4ccc65 \
  --expected-model-tree-sha256 0aa88a384369f3b9a3bdc12a039559b7bced3ce47be8360106895b2dd81b634d \
  --quality-matrix --voice Junhao --seed 0 --cpu-threads 4 \
  --sample-mode fixed --max-new-frames 375 \
  --same-worker-probe-case-id narration-neutral \
  --same-worker-probe-repetitions 3 --case-timeout-seconds 600
```

结果：退出码 0；20 cases = 20 passed；22 个真实句段 ready WAV；20 个最终 case WAV；3 个 probe WAV；人工听感均为 `pending/not_reviewed`。

## 性能与资源

| 指标 | 结果 |
| --- | ---: |
| process start → ready | `2922.688250 ms` |
| 20-case ready WAV（严格 `first_packet_ms`） | min `399.016250` / median `2278.081000` / p95 `5949.676083` / max `7195.815708 ms` |
| 22 句段 request wall | min `399.403083` / median `2278.939708` / p95 `5951.662500` / max `7197.819250 ms` |
| case RTF | median `0.361503` / p95 `0.392402` / max `0.395649` |
| worker peak RSS | min `1,715,273,728` / max `1,753,530,368 bytes` |
| 内部 first audio | 0/22 非空；冻结 worker 未提供，因此没有冒充客户端可播放首包 |

## 单进程、事件与 hash 证明

- 所有 22 个质量句段和 3 个 probe 均由 PID `31506`、generation `1` 完成。
- 完整外部 event log：101 行 = 1 个 `process_ready` + 25 个请求 × 4 个事件；SHA-256 `0913cb77ea8e211cecf2910fd992da269d004174651ed8e2398aecf675aeb7ca`。
- 25/25 请求均严格为 `started -> inference_entered -> ready -> published`，逐事件 exact request_id/PID/generation 一致。
- 22 个质量句段实际文件 SHA-256 与 metrics 逐一重算，0 mismatch；3 个 probe 实际文件也为 0 mismatch。
- probe 3 次实际 hash 全为 `2627997330f3df9d61f7a3565f11fc1a1af2bfbce333714b2222b62d26efa4bb`，同 PID、同 generation、distinct hash count = 1。此结果只证明本次参数/输入下重复一致，不把 seed 当生产内容键。
- 完成后 `pgrep '[b]enchmark_nano_topologies.py'` 为 0；受控 T0-C media root 内 `.part` 为 0；本 run 共 26 个 WAV（22 segment + 1 joined + 3 probe）。

## 验证与证据

| 检查 | 退出码 / 结论 |
| --- | --- |
| 主真实命令 | 0；20/20 passed |
| `render_benchmark_report.py metrics.json --stdout-format json` | 0；严格 `moss-tts-benchmark-result/1.0` 通过 |
| `jq` case/PID/generation/四事件/timing/hash 断言 | 0 |
| 外部 22 segment + 3 probe 文件逐一 `shasum -a 256` | 0 mismatch |
| orphan / `.part` | 0 / 0 |
| T0-C Python 3.11 unittest | 8/8 passed |
| `git diff --check`（T0-C 分配范围） | 0 |

真实 metrics 首次写出后发现 driver 的 telemetry snapshot 位于 3 次 probe 之前。没有重跑模型；依据已完成外部 event log 确定性更正 event count/hash 与 `narration-neutral` 请求计数，并在 metrics 的 `post_run_evidence_correction` 保存更正字段、原因、未重试标志及原始 metrics SHA-256 `a7e66791fc284ea10ea41cac75c8f7428a8218d15b2a6bd41556a6cab26f0b8c`。驱动器已修为 probe 后取最终 snapshot。

## 参考音频与人工听感

- `reference-placeholders/metrics.json`：3/5/8/12 秒四项均为 `reference_placeholder_only/blocked`，严格 renderer 通过；没有参考音频、没有模型执行、没有伪造替代样本。
- 本历史 run 使用的 macOS JSONL worker 当时没有 reference-audio 字段，所以本目录四项正确保持 `blocked`；后续共享 Sidecar 协议与 Linux 技术 smoke 见 T0-B，不能反向改写本 run 的历史结果。
- `listening.md` 保持 20/20 `pending/not_reviewed`。漏字、重复、多音字、姓名/年代、标点停顿、中英混读、噪声、音色漂移和 independent seam 仍须实际审听。

## 文件指纹

| 文件 | SHA-256 |
| --- | --- |
| `metrics.json`（透明更正后） | `3ee72c3d605f08d494e6e9a31aa62950c1477953fd65c39aeac90c236d15caba` |
| `listening.md` | `24c1b03b8002b425a89629be885488fc428eec7672e7110ad28b2b7e887a6cbb` |
| `reference-placeholders/metrics.json` | `34703cbb57a0a945efb8e16f4b973415a6203cd6ddd12c3bf239496b4ace009d` |
| `reference-placeholders/listening.md` | `1ab2530e41209673d129438e62893c00c61fa2ff4cc89bd7e2ae8fd89a162191` |
