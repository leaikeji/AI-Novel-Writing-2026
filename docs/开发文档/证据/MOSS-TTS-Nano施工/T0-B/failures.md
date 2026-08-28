# T0-B 拓扑故障、能力与降级矩阵

状态：**受管本机子进程与生产窄协议 Linux/arm64 Sidecar 的真实 cancel、故障注入/恢复和独立 1,800 秒耐久均已通过；进程内完整矩阵、浏览器、全 fixture、人工听检与正式 PawApp 接线仍待验证。** 任何“支持”只表示当前列出的精确证据，不自动放行 T0-GATE 或产品能力。

## 0. 最新故障裁决

| 故障/能力 | 最终真实结果 | 裁决 |
| --- | --- | --- |
| 句段间取消 | 活 worker 回传 cancelled；只保留首段 ready hash | 受管 worker 通过；不等于单句优雅抢占 |
| 推理中 SIGKILL | `inference_entered` 后 kill，exit -9，无 final/published/.part | 进程隔离通过 |
| 崩溃恢复 | PID 29126→29129、generation 1→2 | 通过 |
| ready 资产复用 | 恢复前后 hash 相同、case 调用增量 1、复用 1 段 | 通过 |
| stdout 相邻行 | 第一轮第 551 请求暴露 select/readline 预读死锁 | 第一轮 failed，不能抹除 |
| reader 修复 | dedicated reader thread + Queue；协议异常 poison 到 restart | 22/22 单测 + 真实探针 + 1,800 秒通过 |
| single-flight | 并发非阻塞拒绝，不交错 JSONL | 通过单测，生产调度仍需上层队列 |
| 30 分钟 | 1,800.219 秒、822 endurance 请求、单 PID/generation | 通过 |
| 协议完整性 | 826 个请求均四事件 exact request/PID/generation；0 mismatch/timeout/restart | 通过 |
| 资源 | peak ru_maxrss 1,836,892,160 bytes | 通过本机观测；QwenPaw 共存门禁未完成 |
| 固定 seed | 822 次出现 13 个 actual hash | 明确不得作内容键 |

现有 Sidecar / browser runner 1.0 的任意文件路径参数只属于测试 harness，仍保持禁止生产接线。
本轮另行冻结和实测的 `moss-tts-sidecar/1.0` 生产窄协议已通过技术门禁；它不接收路径，且以
私网 header 鉴权、无 host port/DB/媒体卷权限、受限 bytes 回传和 PawApp 原子发布形成独立边界。

### 0.1 Linux/arm64 生产 Sidecar 最新故障裁决

| 故障/能力 | 最终真实结果 | 裁决 |
| --- | --- | --- |
| 固定镜像/依赖 | arm64 manifest `56bb12bd…07fe0`；固定 wheels、FFmpeg、模型/source hash | 候选镜像锁通过 |
| 首次 runtime import | Torchaudio 缺 `libgomp.so.1`，模型 ready 前 exit 1、0 发布 | failed 已保留；从同一 snapshot builder 补 runtime 后通过 |
| 私网与权限 | internal network、0 host binding、只读 root/source/model、非 root/drop all；无 DB/media/Qwen volume | 通过 |
| 生产请求边界 | 受控 ID/文本/参数；header token；拒绝 path/URL/DB/token 字段 | 通过单测与容器 smoke |
| 私人参考输入 | 3/5/8/12 秒 WAV multipart bytes 真实合成；伪 hash/坏格式/超限/路径字段 fail-closed | 技术能力通过；产品权利与人工听检未通过 |
| 严格 reference recheck | manifest schema/status/权利标记、固定 filename/size/SHA/格式/精确时长先验证；四次请求前后再复算；4/4 published | 通过严格 runner 复验；不扩展为产品权利或人工音质结论 |
| ready 复用 | PawApp 命中 ready 后跳过 Sidecar，请求计数不增加 | 通过 |
| 取消 | 活动请求 cancel ack，客户端非成功终态，0 发布 | 通过故障门禁；不等于单句优雅抢占 UX |
| 活动请求 SIGKILL | `active_request_count=1` 后 kill；连接断开、无 ready/半成品；新 generation 恢复并成功合成 | 通过活动请求故障恢复；Sidecar 无独立 inference-entered 事件，不得升级表述 |
| 容器 restart | 新 generation，恢复后成功合成 | 通过 |
| 30 分钟 | 1,804.466 秒、750 请求、单 PID/generation、0 failure/restart | 通过 |
| 发布/scratch/退出 | 最终 757 WAV、0 `.part`/unexpected、scratch 0；精确清除后 0 container/process/orphan | 通过 |
| 资源/QwenPaw | Linux peak ru_maxrss 1,972,305,920 bytes；QwenPaw 全程 healthy | 技术共存通过；宿主 swap 只报告快照变化、不作单因果 |

Sidecar smoke 和耐久没有证明其单样本性能优于受管本机 worker。后续拓扑选择应依据故障/依赖
隔离、可重建部署与恢复边界，而不是用两个不同环境的单样本时间作速度宣传。

以下第 1–5 节保留 02:36 初测时的矩阵、风险与下一轮顺序作为历史审计记录；其中“未测/下一次”
若与本节冲突，以本节和 `managed-hardening.json` 为准。

## 1. 四拓扑矩阵

| 能力 / 故障 | 进程内 ONNX CPU | 受管本机子进程 | Linux ARM64 Sidecar | 浏览器 ONNX 试听 |
| --- | --- | --- | --- | --- |
| 固定 revision 加载前校验 | 13 source + 16 model 资产通过 | 同一资产通过 | 主机锁校验通过；容器内复核待做 | 主机锁校验通过；浏览器缓存复核待做 |
| 冷启动 / warmup | 新进程/热文件缓存 2,138.235 ms；无 warmup 第二样本 | worker ready 2,060.910 ms；无 warmup 第二样本 | 未测 | 未测 |
| adapter 可播放首包 | 完整 WAV 返回 1,813.219 ms | 完整 WAV 返回 1,683.625 ms | runner 必填；未测 | runner 必填；未测 |
| RTF / RSS / accelerator | 0.298227 / 1,608,450,048 bytes / CPU | 0.276912 / 1,600,847,872 bytes / CPU | 未测 | 未测 |
| PawApp 事件循环隔离 | **无**；调用同步阻塞约 1.81 s | 有进程边界；单 case 未显示明显 IPC 成本 | 有容器边界；网络/容器开销待测 | 有页面/Worker 边界；宿主 UI 抢占待测 |
| 首个 ready 后停止后续片段 | fake 通过 | fake 通过 | fake 通过 | fake 通过 |
| 单句运行中抢占 | 未实现 / 未验证 | 未实现 / 未验证 | runner 未冻结此能力 | runner 未冻结此能力 |
| worker 崩溃且宿主存活 | **拓扑上不成立** | 原型支持 kill/restart | runner 要求真实重启；未测 | runner 要求页面/Worker 重建；未测 |
| ready 片段 hash 复用 | 崩溃项 blocked | fake 通过 1 个 | fake 通过 1 个 | fake 通过 1 个 |
| 自动拉起 / 版本握手 | 不适用 | JSONL ready 握手真实通过；故障后拉起未测 | runner 1.0 握手；未测 | runner 1.0 握手；未测 |
| 输出路径越界防护 | 原型强制 | 主进程 + worker 双重强制 | runner 回包由主进程强制 | runner 回包由主进程强制 |
| 日志脱敏 / 轮转 | 正式策略待做 | 外部 stderr 文件；正式策略待做 | 待做 | 浏览器控制台待做 |
| 30 分钟稳定性 | 未测 | 未测 | 未测 | 未测 |
| 当前裁决 | 真实 smoke 通过、恢复 HOLD | 真实 smoke 通过、优先候选、恢复 HOLD | blocked / 容器回退 | blocked / 试听探索 |

两个真实输出均为 6.08 秒、48 kHz 双声道 PCM，SHA-256 都是 `28973a0adff8e42442d234e15a8a8739d4b1504c73880ebf0abd197f97a329d3`。这证明同参数下当前两种本机封装没有改变音频结果，不证明跨机器 bit-exact、听感或完整 fixture 通过。

初测时两个 topology 也在同次运行中 bit-exact，但共同 hash 是另一个值 `6abd2aa1c3df7723c45cc5fbfe02e1d9d6db9edac048c72eab08c7df66a81516`。同参数/seed 的修复重试变成 `28973a0a…`，所以跨 invocation bit-exact **未通过**。不得用 seed 预测输出 hash；失败恢复必须优先复用已完成片段，重生成产物按新的 actual hash 登记。

## 2. 已实际注入的 fake 故障

| Fixture | 注入时机 | 四拓扑结果 | 可复核断言 |
| --- | --- | --- | --- |
| `injected-adapter-failure` | 第 1 个片段前 | 4 × `failed` | `failure_injected=true`、无最终音频、无 ready hash、错误脱敏 |
| `cancel-after-first-ready` | 第 1 个独立片段 ready 后 | 4 × `cancelled` | 请求/确认均为 true、保留 1 个 ready hash、未启动后续片段 |
| `crash-and-resume` | 第 1 个独立片段 ready 后 | 3 × `passed`；进程内 1 × `blocked` | 隔离 topology 复用 1 个 hash；进程内明确 `CRASH_RECOVERY_UNSUPPORTED` |
| 3/5/8/12 秒参考 | 加载参考前 | 16 × `blocked` | 没有音频资产、reference SHA-256 为空、未伪造参考录音 |

这些结果来自 fake tone 和 fake restart，不是 ONNX 推理或实际进程/容器/页面恢复。本轮真实授权只含 `narration-neutral`，所以取消/崩溃行仍未被真实证据替换。

## 3. P0 / P1 失败条件

### P0：任何一个命中即不得选择该 topology

- 模型 revision 或任一 participating artifact size/hash 不匹配。
- 产生的音频路径逃出本次受控 runtime，或证据目录出现音频、权重、私人参考录音。
- 失败/取消/崩溃改变 fixture、正文、revision 或正式媒体引用。
- 声称取消成功但取消后仍启动新的片段，或删除已合法 ready 片段。
- 隔离 topology 崩溃后无法握手恢复、重复合成已 ready 片段或复用 hash 不一致。
- Sidecar 监听非 loopback/容器私网，或浏览器能直接访问本地模型业务 Sidecar。
- 真实 artifact 仍使用 `not_applicable` hash，或把 fake/contract run 写成真实通过。

### P1：可降级但必须在 T0-GATE 解释

- 进程内速度达标但阻塞 PawApp 事件循环或无法隔离崩溃：降级到受管子进程。
- 受管子进程性能略差但恢复、资源释放达标：可以优先可靠性，门槛数值需由真实数据冻结。
- Linux ARM64 Sidecar wheel/镜像/内存不达标：本机 macOS 默认不启用容器路径。
- 浏览器 CSP、缓存或页面生命周期不达标：隐藏浏览器试听，不影响后端正式生成。
- 单句不可抢占：收紧句段/文本 token 上限，并在 UI 显示“当前句完成后取消”；不得声称即时取消。
- 官方 Python ONNX 仍强制 Torch/Torchaudio：记录真实依赖与 RSS，不再使用“torch-free”文案；若进程内污染正式环境，改为受管隔离环境。
- 固定 seed 跨 invocation 仍非 bit-exact：不阻断“可播放”本身，但阻断任何依赖可预测输出 hash 的幂等设计；以 persisted ready asset + actual hash 回退。

## 4. 下一次真实锁的固定顺序

```text
LOCK-NANO
  1. 复核 source + TTS ONNX + codec ONNX 的全部 size/hash
  2. 受管子进程真跑 cancel-after-first-ready
  3. 受管子进程真跑 crash-and-resume，核对调用计数与 ready hash
  4. 受管子进程完整 27 cases + 30 分钟稳定性 + 资源释放
  5. 仅在需要对照时再跑进程内完整矩阵
  6. 若 Sidecar runner 已审核，再独占 Docker/LOCK-NANO 实测
  7. 若浏览器 runner 与 LOCK-BROWSER 均已审核，再串行实测
  8. 严格报告、人工核对、释放 LOCK-NANO
```

不允许同时加载 Nano 与 VoiceGenerator，也不允许 T0-B 与 T0-C 的真实 Nano 负载重叠。

## 5. 暂定选择与回退

单 case 有真实指标，但恢复与稳定性门禁未通过，因此仍不选最终 topology。当前工程优先级为：

```text
受管本机子进程（首选验证）
  ├─ 性能、恢复、资源释放达标 → 提交 T0-GATE 冻结
  ├─ IPC 成本不达标但进程内安全门槛可接受 → 评估进程内
  └─ 本机依赖不可重建 → 评估 Linux ARM64 Sidecar

浏览器 ONNX
  └─ 只做即时试听；任何失败都降级到后端生成，不拥有持久任务
```

回退始终保持上层 `TTSAdapter`、Edition fingerprint 和 Manifest 语义不变；物理 topology 切换不能创建第二套任务账本、业务 API 或媒体真相源。
