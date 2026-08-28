# T0-A 依赖、模型资产与许可证冻结证据

> 状态：**候选完成；隔离 Python/Node、29 个 Nano 资产与固定 LGPL 转码器均已真实验收，不代表 T0-GATE 放行或生产可用**
> Owner：T0-A / `tts_t0a_dependency_baseline`
> 执行时间：2026-08-26（Asia/Shanghai），固定转码器补充收口 03:13 CST
> Git 基线：`9b5be4a`；开始与收口时工作树均为 dirty，其他任务的已跟踪/未跟踪改动全部保留且未触碰。

## 结论

T0-A 已用官方一手来源固定 9 个组件、71 个精确上游产物、44 个 Python 闭包、11 个 Node 直接候选，以及 1 个 macOS arm64 FFmpeg 窄构建的 4 个本地产物；官方远程漂移复核与本地 runtime hash 校验均为 0 错误。模型资产、工具源码、二进制和验证音频都留在仓库外；未读取私人音频或额外小说正文。

FFmpeg 9.0.1 已从锁定官方源码 `cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635` 本机构建。最终配置关闭 GPL、nonfree、网络、自动外部依赖与所有非必要能力，只启用 WAV/FLAC/MOV(AAC-LC)、48 kHz 双声道规范化、`ffmpeg` 与 `ffprobe`。真实 Nano WAV 已成功生成逐样本无损一致的 FLAC master 和 128 kbps AAC-LC/M4A 播放副本；损坏输入返回非零且没有发布 final，随后仅从已验证 master 重建播放副本，结果与首次成功输出 bit-exact。

Owner 首次执行 Node `--frozen-lockfile` 安装时，npm registry 下载 `onnxruntime-web`/Monaco 连续重试，按主代理收口指令人工中止（exit 130）。主代理随后移走损坏缓存，并使用同一冻结 lock 重跑成功；详见“主代理后续集成复验”。首次部分安装从未被当作验收产物。

## 冻结输入

- Python 范围：`>=3.11,<3.14`；解析锁指定 Python 3.11、仅二进制 wheel、SHA-256 hashes，只位于 `prototypes/moss-tts-nano` 隔离边界。
- 平台候选：macOS arm64 / Apple M4；不得将本锁静默合并进项目根环境。
- Node：Node `>=24.19.0 <25`、pnpm `11.19.0`；所有直接版本精确锁定，传递包由 pnpm lock integrity 冻结。
- 模型/代码/FFmpeg：revision、URL、大小与 hash 在 `model-sources.lock.json`；下载必须显式 `--download-component` + `--download-dir`，超过 25 MB 还必须第二次 `--allow-large-downloads` opt-in。转码调用只能使用锁内 `runtime_layout` 的显式绝对路径，不搜索 `PATH`。
- 基准 JSON 仅保存脱敏的依赖、版本、URL、hash、平台和计数；不保存权重、密钥、用户媒体或 `.env` 值。

## 实际文件

- `scripts/tts/collect_dependency_inventory.py`：纯标准库、默认无网络/无写入/无下载；可显式刷新、查远程、校验本地资产与下载。
- `prototypes/moss-tts-nano/{python-requirements.lock,model-sources.lock.json,package.json,pnpm-lock.yaml}`。
- `prototypes/moss-tts-nano/dependencies/{README.md,python-requirements.in,model-source-policy.json}`；FFmpeg runtime build 的参数、产物大小/hash 同时冻结在 policy 与 model lock。
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T0-A/{README.md,dependency-lock.json,licenses.md}`。
- 本地可丢弃且不应提交：`prototypes/moss-tts-nano/.venv`、`node_modules`。两者已由主代理按冻结 lock 完整重建，仍不是提交产物。

## 环境

| 项 | 实际值 |
|---|---|
| OS | macOS 26.5.2 build 25F84 |
| CPU / RAM | Apple M4，10 logical CPU，16 GB |
| 项目 Python | `.venv` CPython 3.12.13 |
| T0-A Owner 初始校验解释器 | 原型隔离 `.venv` CPython 3.12.13；锁解析目标为 3.11（uv 托管 CPython 3.11.16） |
| 主代理最终原型解释器 | 原型隔离 `.venv` CPython 3.11.16；44 包 hash lock 已完整安装 |
| Node / pnpm | Codex 捆绑 Node 24.19.0 / pnpm 11.19.0；shell 原 PATH 无 Node，命令时临时追加捆绑 runtime 路径，可移植 lock 中未写入该私有绝对路径 |
| 外部音频工具 | 原 PATH 仍无 `ffmpeg`/`ffprobe`/`sox`；仓库外固定 FFmpeg/ffprobe 9.0.1 arm64 通过绝对路径调用 |

## 命令与结果

| 命令（等价摘要） | 退出码 | 通过 / 失败 / 跳过 |
|---|---:|---|
| `collect_dependency_inventory.py --help` | 0 | 通过 1 |
| `collect_dependency_inventory.py` 初始默认无下载校验，连续两次并 `cmp` | 0 / 0 / 0 | 通过 3；初始两次输出 SHA-256 一致 `ec5122055c7747692f97856d77b4bdf7f585c8419b5d80bb7431fa53f445e90f`；后续 schema 增加 runtime 状态字段后以结构化证据文件为准 |
| `collect_dependency_inventory.py --check-remote --output .../dependency-lock.json` | 0 | 通过：9 组件 / 71 产物 / 44 Python / 11 Node；0 error / 0 warning / 0 download；71 个本地权重校验因未下载而跳过 |
| `pnpm --dir prototypes/moss-tts-nano install --lockfile-only --ignore-workspace` | 0 | 通过：生成 173 个 sha512 integrity 条目 |
| `pnpm ... install --frozen-lockfile --ignore-workspace` | 130 | **HOLD：** lock 与 supply-chain policy 已通过，但 registry 下载重试期间按收口指令中止；不计为功能失败，也不计为完整安装通过 |
| Python hash lock 生成 | 0 | `uv 0.12.5 --python-version 3.11 --only-binary :all: --generate-hashes`，44 包；未安装 Torch 等重运行时 |
| FFmpeg 官方源码下载与 SHA-256 | 0 | 12,036,420 bytes；SHA-256 与锁一致 |
| 固定窄构建、`ffmpeg -buildconf`、`ffprobe -version`、Mach-O/动态链接检查 | 0 | FFmpeg/ffprobe 9.0.1 arm64；许可证输出 LGPL 2.1-or-later；仅链接 macOS 系统库/Framework |
| `collect_dependency_inventory.py --check-remote --local-assets-root ... --local-tool-runtime-root ...` | 0 | 30 个上游资产 present / 41 skipped；1 个当前平台 build、4 个 runtime artifacts 均 `present`；0 error / 0 warning |
| runtime 校验正/负路径：同一默认报告两次 `cmp`、真实 runtime、空 runtime root | 0 / 0 / 1(expected) | 默认报告确定性 SHA-256 `cac66cfe89aadaf79752b9a2288bca6f7152c2ec9f17c7762d02d8d27e4ee748`；真实 4/4 present；空 root 精确返回 4 个 missing finding |
| 真实 Nano WAV → FLAC master → AAC-LC/M4A → WAV round-trip 与结构化 ffprobe 断言 | 0 | 均为 48 kHz/双声道/5.92 秒；FLAC PCM 与输入逐样本一致；播放副本 97,701 bytes |
| 无效输入与 master-only 恢复 | 183 / 0 | 失败未发布 final；从已验证 FLAC master 重建成功，两个 M4A SHA-256 完全一致 |

## 主代理后续集成复验

Owner 收口后，主代理独占 `LOCK-DEPENDENCIES` 与 `LOCK-MODEL-ASSETS` 补齐以下门禁；原始失败仍保留在上表，不能抹去：

| 命令/动作 | 退出码 | 结果 |
|---|---:|---|
| 移走并保留损坏的 prototype `node_modules`，以同一 lock 重跑 `pnpm --dir prototypes/moss-tts-nano install --frozen-lockfile --ignore-workspace` | 0 | 123/123 包安装完成；pnpm policy 忽略 `esbuild@0.25.12`、`protobufjs@7.6.5` install script，后续 Vite/Vitest 实跑均通过 |
| 把临时 Python 3.12 环境移动到可恢复临时目录，以 uv 托管 CPython 3.11.16 重建 prototype `.venv` | 0 | 与 lock 解析目标一致；未改项目根 `.venv` |
| `uv pip install --require-hashes --only-binary :all: -r python-requirements.lock` | 0 | resolved 44，安装 43，`packaging` 由 seed 环境满足；无 hash 降级 |
| prototype `.venv/bin/python -m pip check` | 0 | `No broken requirements found` |
| 导入 `numpy` / `onnxruntime` / `torch` / `torchaudio` / `transformers` | 0 | 版本分别为 2.3.3 / 1.24.3 / 2.7.0 / 2.7.0 / 4.57.1；MPS built/available 均为 true |
| 固定 revision 下载源码、Nano ONNX 与 codec ONNX到仓库外目录；随后 `collect_dependency_inventory.py --local-assets-root ...` | 0 | 29 个目标资产存在且验 hash，42 个未获本轮下载范围的资产显式 skipped，0 error / 0 warning |

模型资产没有进入 Git：源码 13 文件/184,171 bytes，Nano ONNX 10 文件/672,619,352 bytes，codec ONNX 6 文件/90,572,161 bytes。运行布局使用普通 hard link 组成官方要求的两个兄弟目录，不使用 symlink；其树 hash 为 `0aa88a384369f3b9a3bdc12a039559b7bced3ce47be8360106895b2dd81b634d`。下载期间两条慢速/卡住路径被中止，部分文件均移动到可恢复的 `/tmp` 隔离目录；最终资产只以锁定 SHA-256 验证结果为准。

## 固定 FFmpeg 运行时与音频验证

仓库外 runtime layout：`stage0/tools/runtime/ffmpeg-9.0.1-darwin-arm64`。证据不保存用户主目录绝对路径；实际位置由部署配置提供，运行前必须以结构化 lock 验 hash。

| 产物 | 大小 | SHA-256 |
|---|---:|---|
| `bin/ffmpeg` | 3,882,504 | `f39e5777dc535a6bcf9301a0c1766e6008b259893083d4effbb226e01532bc28` |
| `bin/ffprobe` | 3,672,856 | `cb7fe36657fc81c3a8299ab74c5a2a951e42862d5145c88cbb17247ef3741a30` |
| `licenses/COPYING.LGPLv2.1` | 26,517 | `246041b6ecf9bc32d718a62c57877c78b5eb397b6467e74ed7ae2626ab189c30` |
| `licenses/LICENSE.md` | 4,346 | `2e1d16c72fd74e12063776371da757322f8b77589386532f4fd8634bde7de1af` |

最终 LGPL 窄构建参数完整保存在 `model-source-policy.json`/`model-sources.lock.json`；关键边界为 `--disable-gpl --disable-version3 --disable-nonfree --disable-network --disable-autodetect --disable-everything`，再显式启用所需 demuxer/decoder/encoder/muxer/filter。构建时曾先发现只启用 MOV muxer 不足以用同一 ffprobe 复核播放副本；该候选未被接受，最终构建补入 MOV demuxer 与 AAC decoder 后才形成上述 hash。

真实验证输入是 T0-C 已授权的 Nano 输出，SHA-256 为 `2627997330f3df9d61f7a3565f11fc1a1af2bfbce333714b2222b62d26efa4bb`，仅作只读输入。结果如下：

| 层 | 编码/容器 | 采样 | 时长 | 大小 | SHA-256 |
|---|---|---|---:|---:|---|
| 输入 | PCM s16le / WAV | 48 kHz、双声道 | 5.920 s | 1,136,684 | `2627997330f3df9d61f7a3565f11fc1a1af2bfbce333714b2222b62d26efa4bb` |
| master | FLAC s16 / FLAC | 48 kHz、双声道 | 5.920 s | 351,318 | `9c4d9814ae9184a7b60669d7b2006f60097ba848978b31136e04819460c28abb` |
| 播放副本 | AAC-LC / M4A | 48 kHz、双声道、128,966 bps | 5.920 s | 97,701 | `22f87204678c6d05d529a72fe29f66a011f9e030c7d7b377ac9f078c5886187c` |

`soundfile` 逐样本复核输入与 FLAC master：284,160×2 samples 完全相同，PCM SHA-256 `c24bf5f0eae774eb2c9fd2824da0df50af95d04d4ad5c50c462e3ec5c3107060`。失败测试使用非音频输入，FFmpeg exit 183，未出现 `failed.m4a`；随后从 master 恢复生成的 M4A 与首次成功文件 hash 相同，证明“播放副本失败只重转码、不重合成”的路径成立。

主代理持有 `LOCK-BROWSER` 在 Chromium 151 复验同一 M4A：`loadedmetadata` 55.9 ms，duration 5.92 s，`canplaythrough` 时 `readyState=4`/`errorCode=null`；点击后进入 `playing` 并正常 `ended`，控制台 0 error / 0 warning。因此阶段 0 浏览器候选冻结为 AAC-LC/M4A；Safari/Firefox 与移动端矩阵仍由后续 UI/真实宿主门禁覆盖。

## 产物 hash

| 产物 | SHA-256 |
|---|---|
| `collect_dependency_inventory.py` | `aa5c9cdfa18c15b5d57b61cdb20c25be8875ccb874c6039d0e6ba7b04fe4ee7d` |
| `python-requirements.lock` | `196885c7bdb417ca6df16406ca8eb9784a29a993726c5e75ded3df832d6f0ac3` |
| `model-sources.lock.json` | `0485cdfb15eb01f7c4c0f65049f1c477fb6391ec523c5b7159ab25f763ab469d` |
| `package.json` | `8c25128e26c2f2662261825e7320e728f332d95a09efb09ccf40a61956413d18` |
| `pnpm-lock.yaml` | `a486e6024d813dcbacc83eec6a0d717daeca3b4a6de1d28ec0b9cebfcf9b0a5a` |
| `model-source-policy.json` | `d4ccbf173b74bd6cf5f29ef3305b101418edbe4f129d05ebc40021970ea2fce9` |
| `python-requirements.in` | `9e10e8b9d90311521707ab3a2c2124c8cea40b7cb80936c81f1998d7896962b5` |
| `dependencies/README.md` | `814720ae030a22b43ac887dbbeb5966f4920ac7e881a95f4caa581ececeb799f` |
| `dependency-lock.json` | `f743f9411fc95ac2e4a11c953e1a98896900908fca778eb2b7cdb2853da780fe` |

README 与 `licenses.md` 的 hash 不自引用，避免循环更新；其余 hash 由上述命令在收口前复核。

## 未验证项、风险与回退

- P1/P2 缺口见 `licenses.md`：Python ONNX 顶层 Torch 导入矛盾、WeText/Pynini 的 M4 wheel 缺口、VoiceGenerator CUDA/版本冲突、Reader 无许可证、ONNX 18 音色与 Python 16 映射差异，以及 FFmpeg 的 PGP/跨浏览器/再分发矩阵未验。macOS arm64 FFmpeg 二进制已验版本、配置、大小和 hash；后续 T0-B 已另将 Linux/arm64 窄运行时锁入固定 Sidecar 镜像。
- Python 3.11 全量 hash install 已由主代理完成；它只证明隔离环境可重建，不批准把这些重依赖接入 PawApp 生产环境。
- 回退无需数据恢复：本工作包未修改根依赖、业务代码、数据库或用户媒体。集成人可仅移除“实际文件”中的 T0-A 源文件；本地 `.venv`/`node_modules`、仓库外阶段 0 模型，以及精确 runtime layout `stage0/tools/runtime/ffmpeg-9.0.1-darwin-arm64` 均可在确认无运行中任务后移到隔离/废纸篓，再由 lock 重建。验证输出位于独立 `stage0/tools/validation/T0-A-ffmpeg-*`，同样不是用户媒体。不得删除项目根环境、整个 stage0 根或用户数据。

## 给主代理的接线说明

1. T0-B/T0-C 只能从 `model-sources.lock.json` 的 pinned URL/hash 取资产，不允许使用 floating `main`/`latest`；根项目依赖不受本原型锁影响。
2. T0-D 必须独占 `LOCK-MODEL-ASSETS`，不得在当前 Nano 环境直接安装 VoiceGenerator 的 CUDA/Transformers 5 依赖。
3. T0-E 必须核对 18/16 音色差异，不得复制无许可证的 Reader 代码或用它作许可证依据。
4. T0-F/T0-G 已可消费主代理完成的 frozen Node 安装；CodeMirror/Monaco 原型自动化已运行，真实 Blob worker/CSP/IME 与 `onnxruntime-web==1.24.3` 浏览器门禁仍待完成。
5. **当时交接记录：**T0-GATE 后续已把 macOS arm64 固定转码器、Chromium AAC-LC/M4A 与 T0-B 固定 Linux/arm64 Sidecar 运行时接纳为技术输入；许可证、资源与后续产品门禁仍未放行“Python ONNX torch-free”“VoiceGenerator 可用”或“生产依赖已接入”等表述。
