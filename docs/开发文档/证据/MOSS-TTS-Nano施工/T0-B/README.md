# T0-B MOSS-TTS-Nano 四拓扑基准证据

> 状态：**受管本机 worker 已通过真实取消/故障恢复与 1800 秒耐久；生产窄协议 Linux/arm64 Sidecar 也已通过真实基础/3、5、8、12 秒参考输入、取消、活动 SIGKILL、容器重启、ready 复用及独立 1800 秒耐久。进程内完整矩阵、浏览器、全 27 case、人工听检和正式 PawApp 接线仍为 HOLD，因此本文件不单独放行 T0-GATE。**
> Owner：T0-B / `tts_t0b_topology_spike` / `tts_t0b_harden`
> 执行时间：2026-08-26 02:21–06:01 CST
> Git 基线：`9b5be4a`；开始时工作树已有其他任务的已跟踪/未跟踪改动，本工作包未暂存、提交、推送或修改分配范围外文件。

## 0. 加固复验（当前权威结论）

本节是 03:07 后独立审计加固的最新结论；下方第 1–10 节保留 02:21–02:36
历史 smoke 的数据与当时判断。两者冲突时以本节、`managed-hardening.json` 和
`endurance-failure.json` 为准。

### 0.1 受管 worker 最终协议

- worker 持久运行，但 voice、seed、`max_new_frames`、`sample_mode` 均为 per-request；进程参数只作缺省值。
- 每个成功请求严格为 `started → inference_entered → ready → published`；每一行都必须 exact 匹配 request ID、PID 与 generation。
- `process_start_to_ready_ms`、`internal_first_audio_ms`、`ready_wav_ms`、发布 wall 分开记录；官方 runtime 未暴露内部首音频时间，因此该字段保持 null。
- worker 先写唯一 `.part`，完整 WAV ready 并计算 actual hash 后才同目录原子发布。父进程记录脱敏事件 JSONL；证据目录没有音频。
- stdout 由专用 blocking reader thread + Queue 唯一消费；活动请求 timeout、非法 JSON、身份不符或事件错序会 poison adapter，显式 restart 前拒绝新请求并丢弃迟到队列。
- 强制 single-flight；并发请求 fail-closed，不允许 JSONL 行交错。

22 个单元/契约测试覆盖相邻多行、空闲 reader 有界超时、活动请求超时/迟到事件、非法 JSON、缺 request ID、PID/generation 错、事件错序、EOF、cancel、推理中 kill、restart、关闭线程/reap 和并发拒绝。

### 0.2 最终真实 cancel / crash / reuse

最终协议 run group：`20260826T034152+0800-a50186a3`。

| 检查 | 真实结果 |
| --- | --- |
| 句段间取消 | 第 1 段 ready 后由活 worker 回传 `cancelled`；后续段未提交 |
| 推理中故障 | 收到 `inference_entered` 后等待 50 ms 再 SIGKILL；exit `-9` |
| 半成品发布 | killed request 最终路径 false、`published` false、`.part` 0 |
| 新进程恢复 | PID `29126 → 29129`，generation `1 → 2` |
| ready 复用 | 恢复前后 SHA-256 均为 `2586f2d8…258d5`；case 内只合成 1 次；复用 1 段 |
| same-worker probe | 新 PID 上 3 次，同一 generation；本轮 3 个 actual hash 相同 |
| 退出 | poisoned=false、worker 0、orphan 0、`.part` 0 |

### 0.3 30 分钟耐久

最终修复版 run group：`20260826T034226+0800-be5d3e42`。

| 指标 | 实测 |
| --- | ---: |
| 请求时长门槛 / 实际 | 1,800 s / **1,800.219 s** |
| endurance 完成请求 | **822** |
| 前置请求 / 总请求 | 4 / 826 |
| PID / generation | 29163 / 1（全程唯一） |
| started / inference / ready / published | 826 / 826 / 826 / 826 |
| timeout / 协议 mismatch / restart | 0 / 0 / 0 |
| wall min / median / P95 / max | 2,063.107 / 2,173.539 / 2,317.647 / 2,662.849 ms |
| peak RSS | **1,836,892,160 bytes** |
| actual audio hash 种类 | **13** |
| `.part` / worker / orphan（退出后） | 0 / 0 / 0 |

peak RSS 是 macOS `getrusage(RUSAGE_SELF).ru_maxrss` 的进程生命周期高水位，macOS 下直接按
bytes 记录；运行中 `ps rss` 是当前 resident KiB 快照，约 1.17–1.22 GiB，不能冒充 peak。
运行中宿主快照为 `memory_pressure -Q free 37%`、swap used 5,934.88 MiB；结束后为 free
42%、swap used 5,918.88 MiB。没有可靠开跑前基线，**不得把 swap 使用归因于 Nano，也不得声称无换页**。

同文本、同 voice、同 seed、同参数的 822 次耐久出现 13 个 actual hash；即使某个三连 probe
bit-exact，也再次证明 seed 不是内容寻址键。恢复、幂等和 Edition 必须复用已 ready 资产并记录
actual hash，不能重新合成后期待同 hash。

### 0.4 耐久中实际发现并修复的失败

第一轮耐久在第 551 个 endurance 请求出现：worker 已发 `ready` 且原子文件已存在，但父进程
未消费紧邻的 `published`。根因不是 ONNX 推理，而是把 `select()` 与
`TextIOWrapper.readline()` 混用；`readline()` 把下一 JSON 行预读到用户态后，OS fd 看似不可读。
该轮明确记为 failed，精确停止 PID 25435/25436 后 worker/orphan/`.part` 均为 0。修复、22/22
回归和真实 crash 探针通过后，最终 1,800 秒才从 0 重跑。详见 `endurance-failure.json`。

### 0.5 当前边界

- T0-GATE 已选定 Linux/arm64 私网 Sidecar 作为 `T1-DEP` 唯一正式拓扑输入；受管 macOS 本机子进程只保留诊断用途。选择理由是部署一致性、依赖/故障隔离和恢复边界，**不能宣称单样本更快**，也不能把 T0 原型写成生产接线已完成。
- 单句优雅抢占尚未实现；SIGKILL 是故障注入，不是普通用户取消。产品取消只能承诺“当前句完成后停止”。
- 旧 Sidecar / 浏览器 runner 1.0 的任意 `output_path/audio_path` 仍只是测试 harness，**不能接入生产**。本轮另建并实测的 `moss-tts-sidecar/1.0` 才是生产窄协议候选：受控 request/asset ID、header token、私网无 host port、Sidecar 无 DB/媒体卷、受限 WAV bytes 回传，由 PawApp 独占原子发布。
- 3/5/8/12 秒参考录音只获准用于隔离技术验证；真实 bytes/multipart 能力通过不等于私人音色产品权利、可分发声音资产或人工音质验收通过。
- 进程内、Sidecar、浏览器的完整同 fixture 对照尚未完成；全 27 case、音质、文字准确与人工听检属于其他门禁。

### 0.6 当前证据与验证

- `managed-hardening.json`：最终 cancel/crash/reuse/耐久的脱敏结构化证据。
- `endurance-failure.json`：第一轮 reader 死锁失败及精确清理证据。
- `linux-sidecar-real-smoke.json`：生产 Sidecar 真实基础/参考输入、鉴权/权限、取消、SIGKILL、恢复与容器重启证据。
- `linux-sidecar-real-endurance.json`：真实 Linux/arm64 1800 秒、31 个资源快照、QwenPaw 共存与停止清理证据。
- `linux-sidecar-prewarm-baseline.json`：加载 Sidecar 前 QwenPaw、宿主 memory/swap 与 0 Nano 进程基线。
- `linux-sidecar-postshutdown.json`：Compose 停止后 0 container/process/orphan、短期 token/media root 清理与 QwenPaw/宿主资源快照。
- `lock-nano-reconstruction.json`：原锁只能由机器时间区间与唯一集成 Owner 签署重建；明确 prewarm 是加锁前基线，不伪造精确 acquire/release。
- `lock-nano-reference-recheck.json`：06:00:09 由唯一集成 Owner 明确授予的 reference-only 锁，以及 06:01:47 Owner 明确释放；锁内只执行四档参考调用，释放前已核对 0 相关进程/容器/orphan。
- `external-endurance-ledger.json`：仍存在的仓库外 managed-worker JSONL ledger 的 SHA-256、3,305 条记录、事件/字段口径与单 PID/generation 核对。
- `linux-sidecar-reference-recheck.json`：严格 manifest runner 的 3/5/8/12 秒真实复验；4/4 published，每次调用前后 input hash/size/duration/format 均重新核对一致，单 PID/generation，随后删除 4 个生成 WAV。
- `linux-image-build-attempts.json`、`linux-sidecar-real-smoke-failure-libgomp.json`：镜像传输/供应链/运行依赖失败及精确修复历史，失败未被通过结果覆盖。
- `prototypes/.../sidecar/image-lock.json`：候选镜像、arm64 wheels、FFmpeg、GNU OpenMP、模型/source revision 与树 hash 锁。
- 最终耐久 raw：`T0-B-managed_subprocess_onnx_cpu-20260826T034226+0800-a44b52cc.json`，SHA-256 `28a8c4f0…dfb841`，仅在仓库外 runtime。
- 最终事件 JSONL SHA-256：`39105a27…bb9c2e`；3,305 行 = 1 个 process ready + 826 × 4 请求事件。
- 严格 T0-I renderer 对最终 raw 返回 0；summary SHA-256 `a1d9ca75…548f5`。
- 单测命令：`prototypes/moss-tts-nano/.venv/bin/python -m unittest discover -s prototypes/moss-tts-nano/topology -p 'test_*.py' -v`，22 passed。
- 当前项目解释器复验同一 topology 命令为 22/22；生产 Sidecar 独立命令
  `.venv/bin/python -m unittest discover -s prototypes/moss-tts-nano/topology/sidecar -p 'test_*.py' -v`
  为 22/22。后者覆盖协议正负向、reference bytes、取消、原子发布、镜像锁、Compose 权限策略，
  以及 T0-C manifest/schema/status/四档 filename、size、SHA-256、WAV 格式和一帧 duration 容差。
- 证据目录无 WAV/权重/正文/绝对 runtime 路径；最终外部 runtime 约 927 MiB。
- 当前脚本 SHA-256：`2ccf2ca7…1abb1`；测试 SHA-256：`5b43ed11…bd6f4`；topology README SHA-256：`885a3b04…699d8`。
- Sidecar gate SHA-256：`db396d7f…9cc330`；reference runner 测试 SHA-256：`3526d47b…e3733`；真实 reference recheck：`a09d3053…46e78`；真实 smoke：`10b79e22…11756`；真实耐久：`e8fb929d…8915a`。
- `managed-hardening.json` SHA-256：`9360ac44…12a9c`；`endurance-failure.json` SHA-256：`aa75a25a…6734`。

### 0.7 Linux/arm64 生产 Sidecar 最终技术门禁

生产候选协议是 `moss-tts-sidecar/1.0`，与历史 path runner 1.0 分离。它只接受受控
`request_id`、`asset_id`、文本和 voice/seed/frame/sample 参数；参考克隆只接受无 filename 的
WAV/FLAC multipart bytes 与审计 ID、声明 hash/format/size。请求拒绝任意 path、URL、DB/DSN
或 token 字段；Sidecar 复算参考 hash、格式、体积和时长，临时参考只进入容器受控 scratch，
请求结束后清除。响应是最多 16 MiB 的 WAV bytes 与 actual hash、格式、时序、PID/generation、
Linux peak RSS；PawApp 复核后在自己的媒体根 no-overwrite 原子发布。

Reference gate 的 host runner 现在必须先验证 `moss-tts-reference-prep/1.0`、
`prepared_isolated_test_only`、隔离测试权利标记，以及固定 3/5/8/12 秒四档的 basename、文件
size/SHA-256、48 kHz/双声道/16-bit PCM WAV、frame count 和一帧（1/48000 秒）duration 容差；
每个请求前后再次复核，证据逐档保存脱敏 expected/actual hash、size、duration 与格式，不保存
参考音频路径或 bytes。

该加固后的 runner 已在独占 reference-only 锁内复跑固定四档：4/4 成功，输入分别为
576,078 / 960,078 / 1,536,078 / 2,304,078 bytes，实际时长精确为 3 / 5 / 8 / 12 秒；
四次调用前后复算结果均与 manifest 声明一致。四次输出均由同一容器内 PID 7、同一 generation
`61619e5b…4077` 产生，ready WAV 用时为 2,925.904 / 2,428.290 / 2,527.582 /
3,012.735 ms。这里的输入 hash/size/duration 是技术 fixture 完整性证据，不代表产品权利或人工
音质验收。

本次锁由唯一集成 Owner 于 06:00:09 明确授予，范围只含上述四个调用；未重跑普通 smoke、取消、
SIGKILL 或耐久。06:01:35 postflight 为 0 相关进程、0 TTS 容器、0 orphan，QwenPaw 仍为
healthy/OOM=false；4 个输出 WAV（3,748,016 bytes）与短期 token root 已精确清除，Owner 于
06:01:47 明确释放锁。

容器候选为固定 `linux/arm64` manifest list
`56bb12bd…07fe0`，运行用户 `65532:65532`，只读 rootfs、drop all capabilities、
`no-new-privileges`、4 GiB/4 CPU/256 PID 上限；只读挂载固定模型和 source，网络为 Compose
internal，host binding 为 0。Sidecar 没有 PawApp media、QwenPaw volume、DB 或私人参考资产
路径权限；参考 bytes 由 PawApp harness 从独立只读授权 fixture mount 读取后上传。

首次真实启动暴露固定 Torchaudio wheel 缺少 `libgomp.so.1`，该轮在模型 ready 前失败、0 合成、
0 发布、0 `.part`，精确 Compose 树已删除。最终镜像只从同一固定 Debian snapshot builder 复制
GNU OpenMP runtime；Torch 2.7.0+cpu、Torchaudio 2.7.0、`OnnxTtsRuntime` 非 root import probe
通过。失败细节保存在 `linux-sidecar-real-smoke-failure-libgomp.json`。

`image-lock.json` 后续只补齐了已经存在于已验证镜像内的 `sidecar_client.py` 与
`pawapp_harness.py` COPY 输入 hash；镜像字节和 manifest digest `56bb12bd…07fe0` 没有改变，
该动作是 provenance metadata 补全，不是重建或重新宣称镜像通过。

真实 smoke 结果：基础发布与 PawApp 本地 ready 复用通过；3/5/8/12 秒 reference bytes 全部发布
且 actual hash 各异；伪 reference hash 被拒绝；活动请求取消不发布；`active_request_count=1`
后的 SIGKILL 使客户端
收到连接断开、无半成品，随后新 generation 恢复并合成；该探针没有独立 Sidecar
`inference_entered` 事件，不能称为“已证明推理进入”。容器 restart 再产生新 generation 并
成功合成。smoke 结束时 7 WAV、0 `.part`、0 unexpected、Sidecar scratch 0，QwenPaw healthy。

最终独立耐久从 0 计时，实际 **1,804.466 秒**、完成 **750** 请求、0 failure；全程唯一容器内
PID **7**、唯一 generation `bd578ba2…3b61`、0 restart。wall min/median/max 为
1,851.062 / 1,970.589 / 2,615.259 ms；24 个 actual audio hash 再次证明 seed 不能作内容键。
Linux `getrusage` peak `ru_maxrss` 是 **1,972,305,920 bytes** 的进程生命周期高水位；Docker
stats 是当时 current RSS，31 个约 60 秒资源快照中运行末约 1.636 GiB，两种口径不能混用。

QwenPaw 从 prewarm 的 healthy/659.7 MiB，到耐久结束前 healthy/658.4 MiB，再到 Sidecar 停止后
healthy/约 659.1 MiB；挂载始终只含自身三个 QwenPaw volume。宿主 prewarm free 34%、swap used
7,037.5 MiB；耐久首快照 free 39%、swap used 8,605.75 MiB；最终 free 35%、swap used
8,549.75 MiB。前后有可比较快照，但宿主仍可能有其他活动，证据只报告变化，**不把 swap
变化单独归因于 Sidecar，也不声称“无换页”**。

停止阶段由 gate 精确删除本轮 marker test root 内 757 个生成 WAV（smoke 7 + endurance 750，
697,745,948 bytes）；证据目录没有音频。Compose down 后 0 TTS container、0 Nano/benchmark
进程、0 orphan、0 `.part`，短期 token 文件和临时目录随后也已删除。该操作没有修改或删除
模型、授权参考 fixture、QwenPaw volume、数据库、小说媒体或用户正文。

## 1. 本轮结论

四个候选已经落成同一驱动、同一 fixture、同一结果 schema 和同一故障矩阵：

1. `in_process_onnx_cpu`：内置真实适配入口已完成；它不能在不杀死 PawApp 的情况下证明进程崩溃恢复，对 `crash-and-resume` 必须阻断，不能用“重新 new 一个对象”伪装进程恢复。
2. `managed_subprocess_onnx_cpu`：内置持久 JSONL worker、启动握手、受控输出目录、句段间取消、强制杀进程、重启与 ready 片段复用路径已完成；真实 `narration-neutral` 首次请求已通过，当前是**优先验证候选**，不是已选生产拓扑。
3. `linux_arm64_sidecar_onnx`：已冻结窄 runner 1.0 握手和故障接口；没有构建/启动真实 ARM64 Sidecar，所以为 blocked。
4. `browser_onnx_preview`：复用同一窄 runner 1.0 契约；没有用真实浏览器、ONNX Runtime Web、宿主 CSP 或缓存执行，所以为 blocked，且按产品约束仅是试听候选。

当前 `metrics.json` 是最终最小真实 smoke 的 T0-I 严格汇总：进程内和受管子进程各 1 个真实 `passed`，Sidecar 与浏览器各 1 个明确 `blocked`。两条真实路径生成 48 kHz / 双声道 / 16-bit PCM、6.08 秒音频，最终 SHA-256 完全一致；证据目录不含音频。

同一次 invocation 的两个 topology bit-exact，但两次 invocation 并不 bit-exact：初测两条共同输出 `6abd2aa1c3df7723c45cc5fbfe02e1d9d6db9edac048c72eab08c7df66a81516`，修复重试两条共同输出 `28973a0adff8e42442d234e15a8a8739d4b1504c73880ebf0abd197f97a329d3`。参数和 seed 相同，因运行上限没有第三次实验。当前只能判断“封装 topology 没有改变同次生成结果”，不能判断固定 seed 可跨进程复现；正式重试必须复用已 ready 资产并记录 actual hash，不能靠重新合成期待同 hash。

这次单 case 中，受管子进程没有显示可测的 IPC 劣势，且提供进程隔离，因此继续作为优先候选；但样本数只有 1，且真实取消/kill/restart 尚未获准执行，最终裁决仍由完整 T0-B 与 T0-GATE 作出。

### 单 case 真实数据

| Topology | 进程/worker 冷启动¹ | 首次可播放完整 WAV² | 音频 | RTF³ | 峰值 RSS | 结果 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 进程内 ONNX CPU | 2,138.235 ms | 1,813.219 ms | 6.08 s | 0.298227 | 1,608,450,048 bytes | passed |
| 受管本机子进程 | 2,060.910 ms | 1,683.625 ms | 6.08 s | 0.276912 | 1,600,847,872 bytes | passed |

1. 冷启动是 adapter 创建到 ONNX session/worker ready；此前 T0-C 已读取相同资产，因此属于“新进程 + 热文件缓存”，不是断电/清缓存后的绝对冷盘数据。首请求总 ready 时间分别约 3,951.454 ms 与 3,744.535 ms。
2. 官方 Python API 只在完整 WAV 落盘后返回路径；本字段不是 codec 第一个非空内部音频包。T0-C 对同一模型的内部首包另测为约 171.820 ms，二者语义不可混用。
3. RTF 仅为合成调用 wall / 音频时长，不含 adapter 冷启动。

## 2. 冻结输入

| 输入 | 冻结值 | 本轮处理 |
| --- | --- | --- |
| T0-I manifest | `moss-tts-benchmark-manifest/1.0`；27 cases / 29 coverage | 启动前逐 ID、逐文本 SHA-256、组合 SHA-256、coverage 和参考占位复核 |
| T0-I result | `moss-tts-benchmark-result/1.0` | 每个 topology 生成一个不可变原始结果，再由严格报告器汇总 |
| T0-I summary | `moss-tts-benchmark-summary/1.0` | 证据目录只保存汇总 `metrics.json` |
| 官方 Nano source | `cc7bdf19c7639c0870dab22045a33b442760f6be`；T0-A 全树 `dfeedbbfae13dd04c78280e660de7d3d3c5297a82f720da44e7cb9029b4ccc65` | 13 文件逐 size/hash 通过后加载 |
| TTS ONNX | `f52645cb467506d8e18e746ddd59482685b74e58`；锁内选择 672,619,352 bytes | 10 文件逐 size/hash 通过后加载 |
| Codec ONNX | `ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae`；锁内选择 90,572,161 bytes | 6 文件逐 size/hash 通过后加载 |
| ONNX runtime 全树 | T0-A `0aa88a384369f3b9a3bdc12a039559b7bced3ce47be8360106895b2dd81b634d` | 16 文件 / 763,191,513 bytes；与 T0-C 一致 |
| 文本规范化 | WeText disabled；官方 robust normalization enabled | 已写死为真实基准参数，避免 M4 Pynini wheel 缺口漂移 |
| 声音与采样 | `Junhao`、CPU 4 threads、fixed、streaming decode、seed 42、375 frames | 两个本机 topology 共用并实测 |

原始结果还保存了 T0-B 自己的“锁内 participating artifact 集”规范化指纹：model `92419b269673cd698afab06ef0e3f0b60673862c86190cc6c57ed010db9aca98`、source `547f61c24427a59d802cc31dfe532e135303b6b9f71469be19a7f35acd5d4c94`，以及合成 revision fingerprint `46be114c4b83f80b8e7d7b2b7ef2490ddaf9e2396e1157c18613effe7d8a7ea7`。它们的规范化记录结构与 T0-A 的全树算法不同，不能互相替换；T0-A 全树 hash 才是跨 T0-B/T0-C 的资产目录对照值。

官方固定源码显示 `OnnxTtsRuntime.synthesize()` 在返回时才提供完整 WAV 路径；因此本原型的 `first_packet_ms` 精确命名为“adapter 边界首次取得可播放 WAV”，不把内部解码开始时间冒充可播放首包。依据：[固定 `onnx_tts_runtime.py`](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/cc7bdf19c7639c0870dab22045a33b442760f6be/onnx_tts_runtime.py#L560-L629)、[固定 `infer_onnx.py`](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/cc7bdf19c7639c0870dab22045a33b442760f6be/infer_onnx.py#L146-L210)。

## 3. 实际修改文件

- `scripts/tts/benchmark_nano_topologies.py`
- `prototypes/moss-tts-nano/topology/README.md`
- `prototypes/moss-tts-nano/topology/topology-config.example.json`
- `prototypes/moss-tts-nano/topology/test_benchmark_nano_topologies.py`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T0-B/README.md`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T0-B/metrics.json`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T0-B/failures.md`

本轮 Linux Sidecar 加固另新增 `prototypes/moss-tts-nano/topology/sidecar/` 下的生产协议、server、
client、PawApp 测试边界、gate、Dockerfile、fake/production Compose、镜像锁和独立测试；并在本
证据目录新增 `linux-*` 的构建、prewarm、fake、真实 smoke/耐久及失败证据。它们没有修改
QwenPaw、根 Compose、PawApp 业务 API、数据库、模型/source 或用户媒体。

模型、生成 WAV 和每次不可变原始结果都没有写入 Git 证据目录。最终真实 run group 为 `20260826T023427+0800-9983ceb6`；之前的 contract/fake/初测也按各自 run group 留在受控用户应用数据目录。证据只记录 run ID、文件名和 SHA-256，不记录绝对媒体路径。

## 4. 命令与原始结果

| 命令（等价摘要） | 退出码 | 结果 |
| --- | ---: | --- |
| `prototype .venv python scripts/tts/benchmark_nano_topologies.py --help` | 0 | CLI 通过 |
| `prototype .venv python -m unittest discover -s prototypes/moss-tts-nano/topology -p 'test_*.py' -v` | 0 | 10 passed / 0 failed / 0 skipped |
| 同一入口，`--mode contract`，临时 evidence/runtime | 0 | 4 runs / 108 cases；全部明确 blocked；证据音频 0 |
| `BENCH-NANO` 等价命令加 `--mode fake` | 0 | 4 runs / 108 cases；控制面、故障矩阵和 T0-I schema 通过；不计模型通过 |
| 真实最小初测，四 topology + `--case-id narration-neutral` | 4（预期） | 2 real passed / 2 unconfigured blocked；发现冷启动未独立入账 |
| 唯一必要修复重试，同一 case/拓扑 | 4（预期） | 2 real passed / 2 blocked；冷启动、树指纹、RTF/RSS 入账；无第三次运行 |
| `render_benchmark_report.py <四个最终原始结果> --json-output metrics.json` | 0 | 由驱动内部执行；4 个输入均通过 schema 验证 |
| `pgrep -fl 'benchmark_nano_topologies.py __worker__'` | 1 | 无残留受管 worker；随后立即释放 `LOCK-NANO` |

真实命令返回 4 不是两个本机后端失败，而是同一次矩阵中 Sidecar/浏览器没有审核 runner，按设计保持 blocked。两个真实 case 的 `expected_status_match=true`，两条输出 SHA-256 均为 `28973a0adff8e42442d234e15a8a8739d4b1504c73880ebf0abd197f97a329d3`。

## 5. 环境

| 项 | 实测 |
| --- | --- |
| OS | macOS 26.5.2 build 25F84 |
| CPU / RAM | Apple M4 / 16 GiB / arm64 |
| 基准解释器 | prototype 隔离 CPython 3.11.16 |
| 真模型 | 两个本机 topology 各加载一次；随后释放 |
| 模型/Codec 合计锁定选择大小 | 763,191,513 bytes；16 文件全部校验 |
| 加速器 | 未使用；真实候选固定 ONNX CPU |
| 生成音频 | 两条真实 48 kHz / 双声道 / 16-bit PCM WAV，位于外部 runtime；证据目录 0 音频 |

## 6. 产物 SHA-256

| 产物 | SHA-256 |
| --- | --- |
| `benchmark_nano_topologies.py` | `aadf40affc19bb423a4420990239886612a44a3beb43405be34617a087a7afc5` |
| topology `README.md` | `885a3b04cc7e3dee3f0ba4743f2714ff53addb1d95b687aa656d52e2d90699d8` |
| `topology-config.example.json` | `6c327d8ddb1e51d88f92475c866232f5aeabdaae256609edb29fb1ce00fd1252` |
| `test_benchmark_nano_topologies.py` | `8c28f06b017f1008052d73dc64e1185e8289ea669d1eae43ae36b9e5be8e9b9d` |
| `metrics.json`（真实最小矩阵 summary） | `4faf86d51c3dd8e0ae26e60fd75a8e3908138200683f8e0b1f87aabc4093c613` |

最终四个原始 result 的文件名与 SHA-256 已由 `metrics.json.sources[]` 保存。README 与 `failures.md` 不自引用 hash，避免循环更新。

## 7. 人工验收

- 两条真实输出的技术检查完全一致：6.08 秒、48 kHz、双声道、16-bit、1,167,404 bytes、32 个削波 sample；不能据此推断文字准确或听感通过。
- 未执行人工听感；两个真实 case 保持 `listening=pending/not_reviewed`，Sidecar/浏览器为 `skipped_with_reason`。听感与文字准确性由 T0-C 独立验收。
- 已人工复核 evidence 目录只有 JSON/Markdown，无 WAV、模型、参考录音、用户小说正文或带凭证 URL。

## 8. 未验证项与风险

- 只执行 1/27 case；没有预热第二请求、完整矩阵或连续 30 分钟稳定性，不能把单样本中位数/P95当统计结论。
- 进程冷启动发生在此前 T0-C 已加载同一资产之后，OS 文件缓存偏热；绝对冷盘、安装后首启与内存完全回收仍未验证。
- 真实运行确认官方 Python ONNX 路径导入 Torch/Torchaudio，峰值 RSS 约 1.60 GB；不得再宣称当前官方 Python 入口“torch-free”。
- 相同 seed 的两次 invocation 输出 hash 不同，跨进程 bit-exact 不成立或至少尚未得到证明；Edition、缓存与恢复必须保存实际输出 hash，不能把 seed 当内容寻址键。
- 句段间取消和 crash/reuse 只有 fake 状态机证据。本次锁授权仅允许 `narration-neutral`，没有真实取消或 kill/restart；官方 ONNX 单句推理也没有已验证的可抢占 cancel。
- Sidecar 没有镜像、Linux ARM64 wheel、模型挂载、容器 RSS/重启或 loopback 隔离证据。
- 浏览器没有真实 runtime、模型缓存、CSP、Blob Worker、页面关闭、内存回收或刷新恢复证据。
- 原型的受管 worker stderr 只写外部 runtime；正式接线前仍需加入结构化脱敏、轮转和保留期。

完整故障与降级判断见 `failures.md`。

## 9. 回退

本轮没有修改项目依赖、业务 API、数据库、QwenPaw、用户正文或正式媒体。回退只需由集成人移除本工作包列出的源/证据文件；外部 benchmark runtime 可按精确 run group 做可恢复清理，不得递归清理项目根、用户媒体或共享应用数据目录。

## 10. 给主代理的接线说明

1. 本轮已经按主代理授权取得并释放 `LOCK-NANO`；后续完整 27 cases、真实 cancel/crash 或 30 分钟运行必须重新排队取得锁，不能沿用本次授权。
2. 真跑命令必须显式加 `--mode real --model-root <受控外部路径> --source-root <固定源码路径>`；脚本会在加载前验证全部 16 个 ONNX/metadata/tokenizer 资产及 13 个 source 文件的 size/hash。
3. 下一次优先对受管子进程做真实 `cancel-after-first-ready` 与 `crash-and-resume`，证明 kill/restart/reuse，而不是再次重复单句性能 smoke。
4. Sidecar 只有审核 runner、Linux ARM64 依赖与容器资源门禁后才可真跑；浏览器还需要 `LOCK-BROWSER`、CSP/缓存/页面生命周期证据。二者不得用 fake 状态替代。
5. 当前建议仍是受管子进程优先、进程内作性能对照；只有完整性能、恢复和资源释放门槛全部通过，T0-GATE 才能冻结正式 topology。
