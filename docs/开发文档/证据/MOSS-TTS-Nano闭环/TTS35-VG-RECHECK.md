# TTS35-A3-VG：VoiceGenerator 官方制品与本机资源复核

状态：**2026-08-29 只读复核完成；`VG-SPIKE=NO-GO`，`VG-FINAL=BLOCKED_HARDWARE`。** 当前 Apple M4 / 16 GiB 主机不得下载、加载或产品化 MOSS-VoiceGenerator；`voice_generator` capability 应继续为 `unavailable`。本结论不阻断计划 35 的 `CORE-FINAL`，当前产品只提供人物卡匹配官方音色。

工作包：`TTS35-A3-VG`
复核时间：2026-08-29 21:52–22:00（Asia/Shanghai）
执行边界：只读取官方 Hugging Face／GitHub 元数据、小型文本文件、项目内既有证据和本机资源状态；未下载或加载模型，未安装依赖，未启动、停止或修改容器，未读取密钥或私人媒体，未修改源码、测试、迁移及长期环境。

## 1. 裁决

| 门禁 | 当前事实 | 裁决 |
| --- | --- | --- |
| 宿主内存 | `17,179,869,184` bytes，即 16 GiB | **不通过**；低于计划最低 24 GiB／建议 32 GiB |
| 4 GiB 系统余量 | CPU/FP32 静态权重下界后理论仅余约 `1.513 GiB` | **不通过**；尚缺约 `2.487 GiB`，且未计激活、KV cache、allocator、Python、OS、QwenPaw 等 |
| Docker VM | `8,319,504,384` bytes，约 `7.75 GiB` | **不通过**；比两仓权重文件总量少约 `2.801 GiB`，比 CPU/FP32 静态下界少约 `6.739 GiB` |
| 可用磁盘 | 数据卷约 `49 GiB` 可用 | 通过计划 35 的 `≥30 GiB` 前置，也暂时高于既有原子 staging 建议的 `≥42 GiB`；但本工作包没有下载授权 |
| 模型隔离 | 没有 VoiceGenerator Sidecar 目录、镜像或专用模型卷；只有约 40 KiB 的元数据 dry-run 原型 | 产品运行路径不存在，符合 fail-closed 现状 |
| 官方 Apple 路径 | 固定官方示例仅 `CUDA → CPU`，CUDA 用 BF16、非 CUDA 用 FP32；未实现 MPS 分支 | **不通过**；不能靠把设备字符串改为 `mps` 推定可用 |
| 三次真实运行 | 未执行，且当前硬件不允许执行 | **不通过**；无峰值、swap、退出回收、Nano 二次链路和听检证据 |

因此：

- `VG-SPIKE=NO-GO`：当前主机不进入真实 VoiceGenerator 尖峰。
- `VG-FINAL=BLOCKED_HARDWARE`：不得建立 `0035`、死 API、空依赖或不可执行页面按钮。
- `CORE-FINAL` 不受影响：人物卡仍可一键分析并匹配、绑定现有官方音色，但不得表述为生成了全新音色。

## 2. 官方固定制品复核

2026-08-29 本轮再次读取官方一手元数据；三个当前 `main` 均仍解析到计划 33 已冻结的完整 revision，没有漂移：

| 对象 | 固定 revision | 官方状态／用途 |
| --- | --- | --- |
| `OpenMOSS-Team/MOSS-VoiceGenerator` | `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4` | 公开、非 gated、未 disabled；HF metadata 标记 `apache-2.0` |
| `OpenMOSS-Team/MOSS-Audio-Tokenizer`（full codec） | `3cd226ba2947efa357ef453bcad111b6eafba782` | 公开、非 gated、未 disabled；HF metadata 标记 `apache-2.0` |
| `OpenMOSS/MOSS-TTS` 源码 | `58b20a0d5fcc6766658d50967a90a9d890009a46` | 官方模型卡、Gradio app、依赖与 Apache-2.0 源码许可文本 |

官方一手链接：

- [VoiceGenerator 固定 revision 与文件元数据](https://huggingface.co/api/models/OpenMOSS-Team/MOSS-VoiceGenerator/revision/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4?blobs=true)
- [full codec 固定 revision 与文件元数据](https://huggingface.co/api/models/OpenMOSS-Team/MOSS-Audio-Tokenizer/revision/3cd226ba2947efa357ef453bcad111b6eafba782?blobs=true)
- [官方源码固定 commit](https://github.com/OpenMOSS/MOSS-TTS/commit/58b20a0d5fcc6766658d50967a90a9d890009a46)
- [VoiceGenerator 官方模型卡](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/docs/moss_voice_generator_model_card.md)
- [VoiceGenerator 官方 Gradio 运行路径](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/clis/moss_voice_generator_app.py)
- [官方依赖定义](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/pyproject.toml)

### 2.1 固定体积与 hash

| 制品 | bytes | 约 GiB | 官方元数据 hash |
| --- | ---: | ---: | --- |
| VoiceGenerator 运行制品 | `4,244,233,010` | `3.953` | 其中 `model.safetensors` SHA-256 为 `dbe345257ff9f6cc84195bed830a268b39d5e0b728ff3ba90e715150a49b16d4` |
| full codec 完整快照 | `7,101,115,998` | `6.613` | 两个权重分片 SHA-256 分别为 `037f441ed30a0ab59f6049de83b824a1b3bd6feb7dbd46c3fbca41fc2f649f28`、`a187d73d2cda1c2d0676586d9d03c09c0a5813450266af32029c871493fc9582` |
| 两仓完整快照合计 | `11,345,349,008` | `10.566` | 尚未本机下载后复算 |
| 两仓权重文件合计 | `11,326,740,600` | `10.549` | 官方 HF LFS/Xet 元数据汇总 |
| 官方 CPU/FP32 静态权重下界 | `15,555,019,472` | `14.487` | 基于固定模型 dtype 与官方非 CUDA FP32 路径的保守推算，不是峰值 RSS |

公开与 Apache-2.0 元数据说明官方制品可进入后续工程评估，但不替代硬件门禁、真实运行验证，也不自动处理第三方文本、真人声纹或传播用途的权利边界。

## 3. 本机资源快照与硬件余量

### 3.1 宿主

| 项目 | 本轮只读观测 |
| --- | --- |
| 设备 | Mac mini `Mac16,10` |
| SoC | Apple M4，10 核（4 性能核 + 6 能效核） |
| 架构 | `arm64` |
| 物理内存 | `17,179,869,184` bytes / 16 GiB |
| macOS | 26.5.2，build `25F84` |
| 数据卷可用磁盘 | `51,169,808 KiB`，`df -h` 约 `49 GiB` |
| swap 单点快照 | 4 GiB 总量，已用 `2,938.75 MiB` |
| `memory_pressure` 单点快照 | system-wide memory free `46%` |

单点空闲百分比不是可用性证明：即使完全忽略当前 QwenPaw、PostgreSQL、Nano 和 macOS 占用，`16 GiB - 14.487 GiB` 也只剩约 `1.513 GiB`，低于计划要求的 `4 GiB` 最低系统余量约 `2.487 GiB`。真实推理还需要额外运行内存，因此不能用“当前看起来还有空闲”推翻容量门禁。

### 3.2 Docker 与现有 TTS

| 项目 | 本轮只读观测 |
| --- | --- |
| Docker Desktop | 29.7.2，aarch64，10 CPU，VM 内存约 `7.75 GiB` |
| QwenPaw | healthy；单点约 `1.123 GiB` |
| Nano Sidecar | healthy；4 GiB / 4 CPU / 256 PID / read-only rootfs；单点约 `41.61 MiB` |
| PostgreSQL | healthy；单点约 `100.2 MiB` |
| Nano 模型卷 | 约 `729 MiB`，用途锁定为 Nano 模型与源码资产 |
| VoiceGenerator 运行制品 | 未发现专用 Sidecar 源码目录、镜像或专用模型卷 |

仓库中的 `prototypes/moss-tts-nano/voice-generator/` 仅约 40 KiB，内容是 README、元数据 baseline 和无模型加载测试，不是 VoiceGenerator 模型缓存或运行实现。`docker/tts-sidecar/model-source.lock.json` 也明确排除 VoiceGenerator、Reader 和 PyTorch 模型快照。

## 4. 官方运行路径事实

固定官方模型卡与 Gradio app 均采用以下设备语义：

```text
device = CUDA 可用时使用 CUDA，否则使用 CPU
dtype  = CUDA 使用 bfloat16，否则使用 float32
attention = CUDA 可选 FlashAttention/SDPA，CPU 使用 eager
```

本轮在固定源码中未找到官方 MPS 设备分支。官方 `torch-runtime` extra 还固定 `torch==2.9.1+cu128`、`torchaudio==2.9.1+cu128`、`transformers==5.0.0`；这不是可直接安装到 macOS arm64 的项目运行锁。因此：

1. 当前 M4 不能声明存在官方支持的 MPS 路径；任何 Apple Silicon 路径都必须在独立环境中重新形成、锁定并验证。
2. 不得把 VoiceGenerator 依赖加入现有 Nano Sidecar 或 QwenPaw 进程。
3. 后续尖峰必须使用独立模型目录和一次性独立进程；VoiceGenerator 完全退出后才允许 Nano 加载，两者不得同时常驻。

## 5. 未来重开 `VG-SPIKE` 的必要条件

只有同时满足下列条件，才可重新裁决；本报告不授权其中任何写入或下载动作：

1. 宿主至少 24 GiB，建议 32 GiB；真实连续三次运行均保留至少 4 GiB 系统余量。
2. 同一文件系统至少 30 GiB 可用；实际下载/原子安装前继续采用既有更保守的 `≥42 GiB` staging 门槛，完成后保留 `≥24 GiB`。
3. 用户另行明确授权下载约 10.566 GiB 的两个固定模型快照。
4. 两个 fixed revision、allowlist 与下载后逐文件 SHA-256 完全匹配；自定义远程代码和 codec 均不得跟随 `main`。
5. 独立进程、独立依赖锁、只读模型目录和跨进程重模型互斥已实现；不与 Nano 同时常驻。
6. 三次真实流程均无 OOM、无持续 swap 抖动、退出后内存回落，并完成 VoiceGenerator 输出技术检查、Nano 二次克隆、人物贴合听检及 QwenPaw 非回归。

在这些条件满足前，产品只显示可执行的官方音色匹配，不显示“生成人物专属新音色”主按钮。

## 6. 可复核只读命令

```bash
sw_vers
uname -m
sysctl -n machdep.cpu.brand_string hw.memsize hw.physicalcpu hw.logicalcpu
system_profiler SPHardwareDataType
sysctl vm.swapusage
memory_pressure
df -h /System/Volumes/Data /

docker version
docker info
docker ps
docker stats --no-stream
docker inspect ai-novel-2026-moss-tts-sidecar \
  ai-novel-2026-qwenpaw-lab ai-novel-2026-postgres
docker images
docker volume ls
docker system df

curl -fsSL \
  'https://huggingface.co/api/models/OpenMOSS-Team/MOSS-VoiceGenerator?blobs=true'
curl -fsSL \
  'https://huggingface.co/api/models/OpenMOSS-Team/MOSS-Audio-Tokenizer?blobs=true'
git ls-remote https://github.com/OpenMOSS/MOSS-TTS.git refs/heads/main
```

## 7. 证据继承与限制

- 本报告复用并复核了 [VG0-official.md](../MOSS-TTS-Nano优化/VG0-official.md)、[VG0-local-topology.md](../MOSS-TTS-Nano优化/VG0-local-topology.md) 和 [VG1-decision.md](../MOSS-TTS-Nano优化/VG1-decision.md) 的 fixed revision、制品体积和资源算术。
- 本轮没有下载制品，因此官方 API 报告的 LFS/Xet SHA-256 尚未在本机对实际文件复算。
- 本轮没有执行真实模型、MPS／CPU import、生成、取消、退出、Nano 二次克隆或听检；这些项目保持未验证，不得从元数据复核推导为可用。
- 当前磁盘满足前置不等于当前硬件可运行；内存与官方运行路径仍是独立硬阻断。
