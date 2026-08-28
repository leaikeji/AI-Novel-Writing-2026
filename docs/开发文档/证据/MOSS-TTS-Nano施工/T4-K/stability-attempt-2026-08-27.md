# T4-K 30 分钟稳定性首次完整观测

状态：`COMPLETE_OBSERVATION / TECHNICAL_MEMORY_SAFETY_GATE_FAILED / RETRY_REQUIRED`

日期：2026-08-27（Asia/Shanghai）。本记录是作者／操作员本机的脱敏附属证据，不是远程证明，也不是 T4-K `PASS`。

> 2026-08-28 后续事实（不改写本次历史失败）：fresh canonical run `270ea179-e3cf-4095-a928-56b414070719` 已使用冻结的 result/probe 2.2 完成精确 31 点／1800 秒真实窗口并取得技术 PASS；Sidecar `peak=3695819358 B`、`growth=0 B`、restart=0、health failure=0、QwenPaw slowdown=false。当前总状态仍为 `HUMAN_LISTENING_PENDING`，详见[真实本地编排运行增量](./真实本地编排运行增量-2026-08-28.md)。下文“尚未经 fresh real run”只描述本文件写成时的历史状态，不能覆盖这条后续事实。

## 观测范围

- 正式窗口：2026-08-27 22:29:16 至 22:59:16（本地时间），完整 1800 秒。
- 样本：31 点，覆盖起点至第 30 分钟。
- 运行对象：既有 QwenPaw、PostgreSQL 与 MOSS-TTS-Nano Sidecar 三容器；未新增容器或数据库。
- 本轮发生在最小磁盘保护与 deterministic pending-gap 候选重新安装之前，因此即使内存门禁通过，当前 head 集成后仍须重跑。

## 脱敏结果

| 指标 | 实际值 |
| --- | ---: |
| Sidecar 全部健康 | `true` |
| Sidecar restart counts | `[0]` |
| 最大 health failure count | `0` |
| 最大 active synthesis count | `0` |
| 最大 queued job count | `0` |
| 最小 resident memory | `3598108852` bytes |
| 最大 resident memory | `3612067496` bytes |
| QwenPaw 最大观测延迟 | `14` ms |
| QwenPaw slowdown | `false` |
| Pageouts 增量 | `2503` pages |
| Swapouts 增量 | `0` |
| host paging observed | `true` |

`Pageouts`／`Swapouts` 来自 macOS `/usr/bin/vm_stat` 的全机累计计数器窗口差，不是 PawApp 或 Sidecar 的 PID 级指标，也不能据此把 2503 次 pageout 归因给 TTS。本轮当时使用的 result/probe 2.1 硬门禁规定任一增量大于 0 即 `host_paging_observed=true`，因此当时必须返回 `TECHNICAL_MEMORY_SAFETY_GATE_FAILED`；这一历史裁决保留，不重标为 PASS。

2026-08-28 冻结的 result/probe 2.2 候选已取代“任意全机 paging 即失败”作为当前完工门禁。原始 `pageout_delta`、`swapout_delta` 及其派生布尔值继续保留为 telemetry，缺失、负数、类型错误或布尔值与原始差值不一致仍 fail-closed，但非零不再单独导致失败。新硬门禁对固定 31 点 Sidecar 容器内存样本分别取首 5 点和末 5 点的排序中值，定义 `growth=max(0, tail-baseline)`、`limit=max(128 MiB, ceil(baseline×5%))`，仅 `growth>limit` 失败，等号通过；同时要求 `peak<=4 GiB`、restart=0、health failure=0 和 QwenPaw slowdown=false。这是代码契约候选，尚未经 fresh real run，不构成 T4-K 或 T4-GATE PASS。

## 后续动作

1. 保留本轮失败事实，不改写布尔值、不裁剪 31 点。
2. 完成当前代码集成、恢复与 teardown 后使用新 canonical run 重新执行。
3. 重跑前先完成同一 Nano 路径预热，确认固定 Sidecar 容器、`4 GiB` 上限和采样链一致。
4. 使用 fresh canonical run 执行 result/probe 2.2 的完整 31 点／30 分钟窗口；保留全机 paging telemetry，但按 Sidecar 趋势、peak、restart、health failure 和 QwenPaw slowdown 作新裁决。
