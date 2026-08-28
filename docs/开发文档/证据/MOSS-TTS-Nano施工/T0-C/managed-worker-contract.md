# T0-C 持久受管 worker 质量驱动候选

状态：**实现与假 worker 契约测试完成；真实 Nano 20-case 与同 worker 重复技术矩阵已通过；人工听感仍 pending，本文不宣称中文朗读主观质量通过。**

## 已冻结的更正

- T0-C 只复用 `scripts/tts/benchmark_nano_topologies.py __worker__`；一个运行只启动一个模型进程，同 PID/generation 连续服务所选 case。
- 旧 evidence 中 `171.820250 ms` 是单进程 runner 内部 codec 首个非空音频，不是浏览器可播放首包；旧 `8294.934291 ms / 5.92 s / RTF 1.401171333` 又包含该句段的新进程和模型加载，不能作为 steady-state managed-worker RTF。
- 新结果将 `process_start_to_ready_ms`、`request_to_internal_first_audio_ms`、`request_to_ready_wav_ms`、`request_wall_ms` 分开记录。严格契约中的 `first_packet_ms` 取完整 ready WAV；steady-state RTF 排除一次性 process startup。
- 每个句段记录实际 WAV SHA-256、PID、generation、ru_maxrss、事件顺序与显式 request 参数；并校验 `started -> inference_entered -> ready -> published` 的每个事件都具有同一 exact request_id/PID/generation；独立句段仍不使用 cross-fade。
- `--quality-matrix` 恰好是 19 个中文质量 case 加 1 个接缝 case。故障、取消、崩溃恢复属于 T0-B 控制面，不重复计作 T0-C 质量样本。
- 参考音频不能被静默忽略：旧 T0-B macOS JSONL worker 没有 reference-audio 字段；后续唯一共享 Sidecar 协议已经冻结为 multipart 元数据加内联 WAV/FLAC bytes，并禁止 path/URL，Linux 真容器 3/5/8/12 秒技术调用已经通过。产品资产权利与人工听感仍为 `blocked`；T0-C 不复制第二套模型生命周期。

## 已运行的非模型验证

- Python 3.11 单元测试覆盖 fixture/hash、20-case 精确选择、同一假 worker 的 PID/generation 复用、三段独立合并、same-worker 三次重复探针、严格 T0-I renderer、仓库证据禁入和 reference-audio 不得静默忽略。
- 假 worker 只验证控制/度量管线，不计入模型证据；测试产物均位于系统临时目录。

## 已完成的真实锁内运行

1. 主代理确认 T0-B 耐久 worker 已退出、无 orphan，并明确释放 `LOCK-NANO`。
2. 新 evidence candidate 与外部媒体 run 目录完成一次真实 `--quality-matrix --same-worker-probe-repetitions 3`，20/20 技术 passed、退出码 0，未覆盖旧 smoke。
3. 复核 PID/generation、四事件、实际 WAV hash、RSS、四类时延、strict renderer、0 orphan 和 0 `.part` 均通过。详细结果见 `managed-worker-real-20260826/README.md`。
4. 实际听检 20 个最终输出仍 pending，独立接缝 case 必须听三段拼接处；程序指标不得代替人工结论。
5. 冻结产品 fixture 的 3/5/8/12 秒 profile 仍为占位；仓库外 isolated-test-only 技术候选已完成 Linux Sidecar 四档真实技术调用。产品权利和人工听感仍未通过，因此参考克隆功能保持隐藏/blocked。
