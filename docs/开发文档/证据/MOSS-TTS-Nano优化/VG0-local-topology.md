# VG0-B：VoiceGenerator 本机资源与隔离拓扑核验

> 状态：**只读核验完成；当前 Apple M4 / 16 GB 与 Docker 7.75 GiB 配额不满足成功导向的 VoiceGenerator 真实加载预算。VG1 仅可先做无模型加载的制品/依赖预检，真实生成应迁移到至少 24 GB、建议 32 GB 的隔离主机后再裁决。**<br>
> 工作包：`MNX-VG0-B`<br>
> 核验时间：2026-08-29 18:55–19:00（Asia/Shanghai）<br>
> 边界：未下载、导入或加载 VoiceGenerator/Nano 模型；未启动、停止或重启任何长期容器；未读取运行时环境变量值、token、密钥值或私人媒体；未修改运行环境。

## 1. 结论

1. **已核实事实：**宿主为 Mac mini / Apple M4 / 10 核 / 16 GiB；Docker Desktop VM 只有 `8,319,504,384` bytes，约 `7.75 GiB`。现有 Nano Sidecar 已占用独立 `4 GiB / 4 CPU` 上限。
2. **已核实事实：**当前 Nano 模型卷约 `729 MiB`，Sidecar 镜像约 `271.5 MiB`；模型卷以只读方式挂载到长期 Sidecar，秘密卷另行只读挂载，QwenPaw 不直接挂载模型卷。
3. **已核实事实：**本机没有 VoiceGenerator 运行镜像、专用 Sidecar 目录或已安装模型缓存；只有旧 T0-D 元数据审计和无模型加载的 benchmark 骨架。
4. **已核实事实：**旧 T0-D 固定元数据表明 VoiceGenerator 加 full codec 的仓库快照约 `10.566 GiB`、权重文件约 `10.549 GiB`；官方 CPU/FP32 路径的静态权重下界估算约 `14.487 GiB`。权重文件数量级已经大于当前整个 Docker VM，CPU 静态估算在 16 GiB 宿主上只剩约 `1.513 GiB`，低于项目既有 `4 GiB` 安全余量。
5. **已核实事实：**采样时 macOS swap 已使用约 `4.68 GiB`；`memory_pressure` 报告系统级空闲百分比 `37%`。这是单点快照，不能单独证明持续压力，但说明当前机器不适合在日常 QwenPaw 工作负载旁无界尝试大模型加载。
6. **项目建议：**VoiceGenerator 与 Nano 必须使用两个独立进程/镜像和独立依赖锁，并共享一个跨进程、互斥的 `LOCK-MODEL-HEAVY` residency claim。现有 `moss-nano:inference` 与 `voice-generator:generation` 是两个不同 exact resource key，**当前并不互斥**，不能把计划锁名写成已经存在的数据库事实。
7. **VG1 裁决建议：**当前机器可进入“制品锁、hash、依赖解析、启动前资源门禁”子阶段；不得在当前 Docker 配额内进入真实加载。成功导向的真实生成和 Nano 二次克隆应在至少 24 GB、建议 32 GB 内存的隔离 Apple Silicon 或受支持 CUDA 主机执行。若坚持在本机做负向加载探针，需另行批准维护窗口、精确 RSS/内存压力中止器及 QwenPaw 非回归方案，且结果默认只能是 `HOLD/NO-GO`，不能开启产品 capability。

## 2. 已核实本机事实

### 2.1 宿主与即时资源

| 项目 | 只读观测 | 口径 |
| --- | ---: | --- |
| 设备 | Mac mini `Mac16,10` | `system_profiler` 过滤输出；未记录序列号 |
| SoC | Apple M4 | 10 核：4 性能核 + 6 能效核 |
| 架构 | `arm64` | 宿主原生架构 |
| 物理内存 | `17,179,869,184` bytes / 16 GiB | `sysctl hw.memsize` |
| macOS | 26.5.2 / build 25F84 | 2026-08-29 快照 |
| 数据卷可用磁盘 | 约 47 GiB | `/System/Volumes/Data`；总量 228 GiB，已用约 138 GiB |
| swap | 6 GiB 总量，约 4.68 GiB 已用 | 加密 swap；单点观测，不等于本轮新增 |
| 内存空闲百分比 | 37% | `memory_pressure` 单点观测 |

### 2.2 Docker Desktop 与长期容器

| 项目 | 只读观测 | 判断 |
| --- | ---: | --- |
| Docker Client / Server | 29.7.2 / 29.7.2，API 1.55 | `aarch64` Docker Desktop |
| Docker VM | 10 CPU / `8,319,504,384` bytes（约 7.75 GiB） | 小于 VoiceGenerator + full codec 的权重文件数量级，不具备真实加载预算 |
| Nano Sidecar | healthy；4 GiB、4 CPU、256 PID；只读 rootfs | 私有网络；模型卷和秘密卷均只读 |
| Nano 即时用量 | 31.61 MiB / 4 GiB，3 PID | **技术推断：**与按需卸载冷态相符；本轮未调用健康/加载接口确认模型 residency |
| QwenPaw | healthy；即时约 837.6 MiB | 未设置独立容器内存上限，共享 Docker VM 余量 |
| PostgreSQL | healthy；即时约 136 MiB | 未设置独立容器内存上限，共享 Docker VM 余量 |
| Docker 总体存储 | images 14.28 GB；volumes 5.347 GB；build cache 23.67 GB | 只读统计；本轮未清理任何镜像、卷或缓存 |

长期 Nano 容器的边界为：

```text
QwenPaw（默认网络）
  └─ 仅通过 tts-private 网络请求 Nano Sidecar

Nano Sidecar（tts-private，read-only rootfs，4 GiB / 4 CPU）
  ├─ ai-novel-2026-moss-models -> /opt/moss-assets（只读）
  ├─ ai-novel-2026-moss-tts-secrets -> /run/moss-tts-secrets（只读）
  └─ /tmp（256 MiB tmpfs）

模型安装器（仅 profile 启动的一次性进程）
  └─ 唯一允许写 moss-models 的既有模型生命周期路径
```

### 2.3 已有 Nano 缓存和依赖

- `ai-novel-2026-moss-models` 当前约 `729 MiB`；锁文件固定 3 个组件、29 个制品：Nano 源码、MOSS-TTS-Nano-100M-ONNX 与 MOSS-Audio-Tokenizer-Nano-ONNX。
- Nano Sidecar 镜像大小为 `284,719,762` bytes，架构 `linux/arm64`。
- 镜像内实际包版本与 `docker/tts-sidecar/requirements.lock` 一致：Torch 2.7.0、Torchaudio 2.7.0、ONNX Runtime 1.24.3、Transformers 4.57.1、NumPy 2.3.3、SoundFile 0.14.0、FastAPI 0.141.1、Uvicorn 0.52.4。
- `docker/tts-sidecar/model-source.lock.json` 明确排除 VoiceGenerator、Reader、PyTorch 模型快照和预设声音音频。因此现有 Nano 卷不是 VoiceGenerator 缓存，也不能在其上静默追加未锁定权重。
- `docker/voice-generator-sidecar/` 当前不存在；没有 VoiceGenerator 的 Dockerfile、独立 requirements lock、model-source lock、NOTICE 或运行镜像。计划 33 已把这些未来产物分配给 `MNX-VG-RUNTIME`，VG1 不应临时混入 Nano 镜像。

## 3. 依赖与内存差异

### 3.1 已核实差异

| 维度 | Nano 当前实现 | VoiceGenerator 官方/旧审计事实 | 结论 |
| --- | --- | --- | --- |
| 推理形态 | ONNX Runtime，100M Nano + Nano codec | Qwen3-1.7B 背骨 + full audio tokenizer | 不是同一资源级别 |
| Torch | 2.7.0 | 官方源说明 CUDA 锁为 2.9.1+cu128 | 不可复用同一环境 |
| Transformers | 4.57.1 | 官方源说明 5.0.0 | 必须独立解析并冻结 |
| 设备分支 | linux/arm64 CPU/ONNX 已验证 | 官方示例为 CUDA，否则 CPU；没有明确 MPS 分支 | 不能把 Apple MPS 可用等同模型可用 |
| 模型制品 | 约 729 MiB 已装 | VG + full codec 快照约 10.566 GiB，未下载 | 不得写入 Nano 既有模型卷 |
| CPU 静态权重下界 | Nano 由实际 4 GiB 容器界限覆盖 | 约 14.487 GiB | 16 GiB 宿主不满足 4 GiB 余量门禁 |

### 3.2 资源算术

旧 T0-D 的固定元数据给出：

```text
VoiceGenerator 选定制品               4,244,233,010 bytes
full audio tokenizer 仓库快照         7,101,115,998 bytes
合计快照                              11,345,349,008 bytes = 10.566 GiB

VoiceGenerator + codec 权重文件       11,326,740,600 bytes
官方 CPU/FP32 静态权重下界估算        15,555,019,472 bytes = 14.487 GiB
16 GiB 宿主理论剩余                    1,624,849,712 bytes = 1.513 GiB
项目既有最小安全余量                   4 GiB
```

这些数字是**制品元数据求和和保守技术推断**，不是峰值 RSS。真实运行还要容纳 Python、allocator、激活值、KV cache、音频 buffer、OS、Docker VM、QwenPaw 和数据库。由此可以得出两个确定结论：

- 当前 `7.75 GiB` Docker VM 小于约 `10.549 GiB` 的权重文件数量级，真实运行不应开始；
- 官方 CPU/FP32 路径即使绕开 Docker，也无法在 16 GiB 宿主上同时满足既有 4 GiB 安全余量。

MPS/BF16 是否能降低实际峰值仍待验证；官方路径未声明支持 MPS，不能据此放宽门禁。

## 4. 独立进程与共享 `LOCK-MODEL-HEAVY` 候选

### 4.1 目标拓扑

```text
Background job lease / CAS
          |
          v
共享 residency claim：LOCK-MODEL-HEAVY（全局容量 1）
          |
          +-- owner=moss-nano --------> Nano Sidecar / Nano 独立依赖锁
          |
          `-- owner=voice-generator --> VoiceGenerator Sidecar / VG 独立依赖锁
```

**当前实现事实：**当前代码、迁移 seed 与契约测试已定义 `moss-nano:inference` 和 `voice-generator:generation` 两个各自并发为 1 的 exact resource key；它们防止同类任务并发，却不能防止两类模型同时常驻。本轮未查询长期运行数据库内容，不把源码事实冒充实时数据库状态。

**项目建议：**产品化时新增一个跨进程的共享 residency claim，容量严格为 1。名称可以是 `model-heavy:residency`，文档简称 `LOCK-MODEL-HEAVY`；最终 schema/字段由后续契约与迁移包冻结，VG0-B 不提前写死数据库表。

必须满足：

1. job lease 不能替代 residency claim；两者绑定同一个 job/attempt/worker generation；
2. claim 至少记录 owner kind、owner identity、generation/fence、lease expiry 和 `loading/resident/draining` 状态；
3. owner 周期续租；进程退出或明确 unload 后才能释放；
4. lease 过期只允许进入恢复核验，不能让竞争模型立刻加载；必须先证明旧 PID/Sidecar 不存在或健康状态为 unloaded；
5. 取得 claim 后再次检查竞争 Sidecar 已卸载，防止“检查后到加载前”竞态；
6. 发布候选/音频时同时验证 job fence、resource fence 和 residency generation，旧 worker 不得发布；
7. 任一 unload 超时或内存未回落时，把进程标记 poisoned 并重建，不能仅靠 `del model` 宣称已释放。

## 5. 加载、卸载与失败恢复候选

### 5.1 Nano

- 复用现有 Sidecar lease、按需 warmup、idle unload 和 poison/restart 语义；源码与测试存在默认 300 秒 idle unload 路径。
- 在交出共享 claim 前，必须等待 Sidecar 报告 `unloaded`、active request 为 0，且 lease generation 与 worker generation 匹配。
- 本轮未调用实时健康接口，因此“不常驻”只依据 31.61 MiB 冷态用量作技术推断，VG1 前仍需由公开健康接口复核。

### 5.2 VoiceGenerator

- 使用独立 Python 3.11 进程/Sidecar、独立 hash 锁和独立模型卷；不得安装进 Nano 镜像或 QwenPaw 进程。
- VG1 首选“一次尖峰一个子进程”：加载、生成、写入仓库外临时媒体、flush/hash、退出。**进程退出是尖峰阶段唯一可信的完全卸载证据。**
- 若后续产品化改为常驻 Sidecar，也只能按需加载；空闲后先 draining、拒绝新请求、完成当前候选、卸载并复核 RSS。卸载超时必须进程级重启。
- 取消分两级：生成循环可协作取消时先请求取消；超过有界 grace period 则终止整个 VoiceGenerator 子进程，结果保持 cancelled/failed，不发布半成品。
- VoiceGenerator 完全退出并释放 `LOCK-MODEL-HEAVY` 后，Nano 才能取得 claim 执行二次克隆；禁止为了 A/B 试听同时常驻两个模型。

## 6. VG1 隔离测试候选

### 6.1 可在当前机器先执行的无加载阶段

1. 冻结 VoiceGenerator 与 full codec 的精确 revision、文件清单、许可和 SHA-256；权重保存在仓库外独立目录。
2. 下载前要求宿主数据卷至少 `42 GiB` 可用；下载/原子安装结束后至少保留 `24 GiB`。原因是 10.566 GiB 最终快照外，还需下载临时文件、hash/安装临时空间、独立环境和安全余量。安装器应在同一文件系统 staging 后原子 rename，避免无界复制。
3. 独立解析 arm64 CPU/MPS 依赖锁，执行 `pip check` 与**不导入模型模块**的包元数据核验。
4. 构建独立 VoiceGenerator 镜像/环境；权重不进镜像和 Git。模型卷只允许 installer 写，运行容器只读。
5. 验证启动参数、网络隔离、只读 rootfs、tmpfs、非 root、cap drop、PID/CPU/内存限制和无密钥输出。

### 6.2 当前机器禁止直接执行的真实加载阶段

当前 Docker VM 只有 7.75 GiB，禁止用增加容器 `mem_limit` 的方式伪装容量。把 Docker VM 提升到接近 16 GiB 也会挤压 macOS/QwenPaw，不能满足 4 GiB 宿主余量。

成功导向的 VG1 应迁移到：

- **最低候选：**24 GiB 统一内存且能证明峰值仍有 4 GiB 余量；
- **推荐：**32 GiB 统一内存 Apple Silicon，或官方依赖明确支持且有足够显存/主存的 Linux CUDA 主机；
- Docker/运行时内存预算先给 VoiceGenerator `20 GiB` 上限候选，Nano 保持独立 `4 GiB`；两者由共享 claim 串行，**不是**同时预留 24 GiB；最终上限以真实峰值 RSS/加速器内存再收紧。

### 6.3 真实阶段顺序

```text
记录宿主/Docker/QwenPaw 基线健康与资源
  -> 证明 Nano unloaded
  -> 取得 LOCK-MODEL-HEAVY(owner=voice-generator)
  -> 启动一次性 VG 子进程
  -> 加载前、加载后、生成峰值持续采集 RSS/内存压力/swap/RTF
  -> 仅用项目 fixture 生成 1 个最小候选
  -> WAV 技术检查与 hash；不写 Git
  -> VG 子进程完全退出，RSS/PID/挂载复核
  -> 释放共享 claim
  -> Nano 取得共享 claim，执行同文本与留出文本二次克隆
  -> Nano 卸载并释放 claim
  -> QwenPaw 原生聊天、设置、Agent 非回归
```

首个真实 case 通过后才扩展到计划的 3 类虚构人物、默认生成和连续两次“换一个”。出现 OOM、持续黄色/红色内存压力、swapout 持续增加、进程无法在 grace period 内退出、QwenPaw 健康下降或模型输出不可解码时，立即终止本轮并保持 capability 隐藏。

## 7. 进入 VG1 的资源预算建议

| Gate | 当前状态 | VG1 建议 |
| --- | --- | --- |
| 宿主内存 | 16 GiB | **真实成功探针 NO-GO**；换至少 24 GiB、建议 32 GiB 主机 |
| Docker VM 内存 | 7.75 GiB | **NO-GO**；不要在 16 GiB 宿主上简单扩到 20 GiB |
| 磁盘 | 约 47 GiB 可用 | 可做制品预检；下载前 ≥42 GiB，完成后 ≥24 GiB |
| VG 最终制品 | 10.566 GiB 元数据估算 | 独立只读模型卷；预留约 12 GiB 最终空间 |
| 下载/原子安装临时空间 | 未占用 | 额外预留约 12 GiB；失败可删除精确临时目录，不碰共享卷 |
| VoiceGenerator 运行内存 | 未实测 | 在 ≥32 GiB 主机先给 20 GiB 有界候选；测得峰值后收紧 |
| Nano 运行内存 | 现有上限 4 GiB | 保持；只在 VG 完全退出后加载 |
| CPU | 宿主 10 核 | VG 尖峰先限 6 核，保留 QwenPaw/OS；Nano 保持 4 核但不并发 |
| tmpfs/输出 | 未设计 | tmpfs 512 MiB 候选；WAV 写仓库外精确媒体临时目录 |
| 共享重型模型并发 | 当前为两个独立 key | `LOCK-MODEL-HEAVY` 全局容量 1；无 claim 不加载 |
| unload grace | VG 未实现 | 协作取消 10 秒、进程退出总 grace 30 秒候选；超时 poisoned/restart |
| capability | 当前 `VOICE_GENERATOR_NO_GO` | 全部真实门禁通过前继续隐藏 |

上述 20 GiB、6 CPU、512 MiB tmpfs、10/30 秒 grace 是**VG1 初始实验预算建议**，不是已验证生产配置。真实证据必须记录实际峰值并据此收紧，不能因容器没有 OOM 就宣称资源安全。

## 8. 仍待验证

- VoiceGenerator 官方固定 revision 与 full codec revision/全部文件是否已在 VG0-A 重新核实并冻结；本轮没有联网复核。
- Apple M4 上是否存在不修改官方核心源码的可用 MPS 路径；当前官方示例没有明确 MPS 分支。
- VoiceGenerator 的真实峰值 RSS、MPS allocated/driver memory、首包时间、RTF、取消延迟和退出后内存回落。
- full codec 是否必须整体常驻、能否合法且不改变模型语义地懒加载/卸载。
- 真实生成候选的可懂度、人物贴合度、可区分度，以及 Nano 二次克隆的音色保持度。
- 产品化共享 residency claim 的最终 schema、恢复所有者和迁移 revision；VG0-B 只冻结互斥语义。
- 长期运行态公开健康接口中的 Nano `model_loaded/unloaded` 实时值；本轮为避免触发任何运行行为未调用。

## 9. 可复核命令与脱敏说明

以下命令均为只读。文档只保留硬件、资源、镜像/容器限制、相关卷标签和包版本；省略无关 volume 名称、绝对 Docker mountpoint、容器环境变量和全部秘密值。

```bash
sw_vers
uname -m
sysctl -n machdep.cpu.brand_string hw.memsize hw.physicalcpu hw.logicalcpu
system_profiler SPHardwareDataType \
  | awk -F': ' '/Model Name|Model Identifier|Chip|Total Number of Cores|Memory/ {print $1 ": " $2}'
vm_stat
sysctl vm.swapusage
memory_pressure
df -h / .

docker version --format 'client={{.Client.Version}} server={{.Server.Version}} api={{.Server.APIVersion}}'
docker info --format 'os={{.OperatingSystem}} arch={{.Architecture}} cpus={{.NCPU}} memory={{.MemTotal}} driver={{.Driver}} root={{.DockerRootDir}}'
docker ps --no-trunc --format 'name={{.Names}} image={{.Image}} status={{.Status}} ports={{.Ports}}'
docker system df
docker stats --no-stream --format \
  'name={{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}} limit={{.MemPerc}} pids={{.PIDs}}' \
  ai-novel-2026-qwenpaw-lab ai-novel-2026-moss-tts-sidecar ai-novel-2026-postgres
docker inspect --format \
  'name={{.Name}} image={{.Config.Image}} state={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} memory={{.HostConfig.Memory}} nanocpus={{.HostConfig.NanoCpus}} pids={{.HostConfig.PidsLimit}} readonly={{.HostConfig.ReadonlyRootfs}} network={{.HostConfig.NetworkMode}} mounts={{range .Mounts}}{{.Name}}:{{.Destination}}:{{.RW}};{{end}}' \
  ai-novel-2026-moss-tts-sidecar ai-novel-2026-qwenpaw-lab ai-novel-2026-postgres
docker inspect --format \
  'name={{.Name}} networks={{range $k, $v := .NetworkSettings.Networks}}{{$k}};{{end}}' \
  ai-novel-2026-qwenpaw-lab ai-novel-2026-moss-tts-sidecar ai-novel-2026-postgres
docker volume inspect --format 'name={{.Name}} driver={{.Driver}} scope={{.Scope}} labels={{json .Labels}}' \
  ai-novel-2026-moss-models ai-novel-2026-moss-tts-secrets ai-novel-2026-novel-media
docker image inspect --format \
  'image={{index .RepoTags 0}} size={{.Size}} architecture={{.Architecture}} os={{.Os}}' \
  ai-novel-world/moss-tts-sidecar:t1-b-linux-arm64

docker exec ai-novel-2026-moss-tts-sidecar \
  sh -lc 'du -sh /opt/moss-assets; find /opt/moss-assets -maxdepth 3 -type f -exec stat -c "%s %n" {} \;'
docker exec ai-novel-2026-moss-tts-sidecar \
  python -m pip show torch torchaudio onnxruntime transformers numpy soundfile fastapi uvicorn

rg -n '^(torch|torchaudio|onnxruntime|transformers|numpy|soundfile|fastapi|uvicorn)==' \
  docker/tts-sidecar/requirements.lock
sed -n '1,320p' docker/tts-sidecar/model-source.lock.json
rg -n 'resource_class|moss-nano:inference|voice-generator:generation' \
  backend/models.py backend/narration tests/narration
```

本轮 `docker exec` 只读取已运行 Nano 容器内的模型目录大小和 Python 包元数据；没有调用模型模块、推理端点、warmup、lease acquire/release 或健康变更接口。

## 10. 恢复与非影响声明

本工作包没有改变 Docker、容器、卷、模型缓存、数据库、网络、依赖或用户媒体。唯一新增文件是本文；无需运行态恢复。若撤回本证据，只删除本文即可，但不得据此清理任何现有 Docker volume、模型缓存或长期容器。
