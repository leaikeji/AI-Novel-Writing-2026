# VG0-A：MOSS-VoiceGenerator 官方模型、许可与运行约束核验

> 状态：**只读核验完成。建议有条件 `GO` 进入 VG1 的制品锁定、依赖解析与无模型加载预检；当前 Apple M4 / 16 GiB 的真实加载与生成子阶段 `NO-GO`，须与 VG0-B 的资源门禁汇合后迁移到至少 24 GiB、建议 32 GiB 的隔离主机。该结论不是 `VG1-GATE=GO`，产品 capability 继续隐藏。**
> 工作包：`MNX-VG0-A`
> 核验日期：2026-08-29（Asia/Shanghai）
> 核验方式：只读取 OpenMOSS 官方 Hugging Face / GitHub 的固定 revision 页面、原始文本和仓库元数据 API；未下载权重，未安装依赖，未导入或加载模型，未生成音频。
> 边界：本报告只裁决是否具备进入后续尖峰的可复核输入，不宣称 M4 可运行、输出质量合格、Nano 二次克隆通过或人物专属音色已可产品化。

## 1. VG0-A 结论

### 1.1 已核实事实

1. `OpenMOSS-Team/MOSS-VoiceGenerator` 是公开、非 gated、未 disabled 的官方 Hugging Face 模型仓库；2026-08-29 的 `main` 仍解析到 `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`。
2. 官方把它定义为 1.7B `MossTTSDelay` voice-design 模型：输入自由文本 `instruction` 与试听 `text`，无需参考音频，可描述音色、人物感、情绪、风格、语速与音高；模型卡只明确承诺中文和英文。
3. VoiceGenerator 固定 revision 的 15 个运行制品合计 `4,244,233,010` bytes；其中 `model.safetensors` 为 `4,228,278,872` bytes，Hub 元数据给出的 LFS SHA-256 为 `dbe345257ff9f6cc84195bed830a268b39d5e0b728ff3ba90e715150a49b16d4`。
4. `MossTTSDelayProcessor.from_pretrained()` 默认还会加载未固定 revision 的 `OpenMOSS-Team/MOSS-Audio-Tokenizer`。本轮把该 full codec 的当前官方 revision 冻结为 `3cd226ba2947efa357ef453bcad111b6eafba782`；其两个权重分片合计 `7,098,461,728` bytes。
5. VoiceGenerator 运行制品加 full codec 完整仓库快照合计 `11,345,349,008` bytes，即约 `10.566 GiB`；两者权重文件合计约 `10.549 GiB`。官方 CPU 路径把 VoiceGenerator 从 BF16 转为 FP32，连同 codec 的 FP32 权重，静态权重下界为 `15,555,019,472` bytes，即约 `14.487 GiB`，尚未包含 Python、激活、KV cache、allocator、音频 buffer、OS 或其他服务。
6. 官方源码仓库 `OpenMOSS/MOSS-TTS` 的 `main` 在核验时解析到 `58b20a0d5fcc6766658d50967a90a9d890009a46`。官方推荐隔离 Python 3.12 环境和 Transformers 5.0.0；当前 `torch-runtime` extra 固定 CUDA 12.8 的 Torch / Torchaudio 2.9.1。
7. 官方 quickstart 和 Gradio app 只实现 `CUDA -> CPU` 选择：CUDA 使用 BF16，其他情况使用 FP32；没有 MPS 分支。Apple M4 上的 MPS 可用性不能从官方示例推导。
8. VoiceGenerator、full codec 的 HF metadata 均标记 `apache-2.0`；官方源码仓库含完整 Apache License 2.0 文本，并声明 MOSS-TTS Family 模型使用 Apache 2.0。

### 1.2 进入 VG1 的裁决

| 子阶段 | 裁决 | 理由 |
| --- | --- | --- |
| 固定 revision、精确制品清单、下载前磁盘预算、仓库外 staging、下载后逐文件 hash | **有条件 GO** | 官方仓库公开且 revision、文件大小和大文件 SHA-256 可冻结；本轮尚未本地下载或复算 hash |
| Python 3.11/3.12 arm64 隔离环境的纯依赖解析、锁文件候选、`pip check`、不加载模型的 import 前检查 | **有条件 GO** | 依赖边界可识别，但官方 `torch-runtime` 是 CUDA 固定版本，macOS 锁必须另行解析并留下差异证据 |
| 当前 M4 / 16 GiB 上的 CPU/FP32 真实加载或生成 | **NO-GO** | 静态权重下界约 14.487 GiB，已无法满足项目 4 GiB 宿主安全余量；VG0-B 还确认当前 Docker VM 只有约 7.75 GiB |
| 当前 M4 / 16 GiB 上把设备字符串改成 `mps` 后直接真实加载 | **NO-GO** | 官方没有 MPS 路径、依赖锁或运算兼容证据；不能以理论 BF16 体积替代峰值实测和失败中止设计 |
| 至少 24 GiB、建议 32 GiB 的隔离 Apple Silicon，或官方受支持且资源充足的 Linux CUDA 主机上的一次性真实 worker | **可作为后续 VG1 候选** | 仍需先完成本地 hash、独立依赖锁、资源中止器、真实峰值/退出回收和 Nano 二次克隆验证；结果默认仍是 `HOLD/NO-GO`，通过全部门禁才可转 `GO` |

因此，本报告的简写结论是：**`GO` 进入受限 VG1 前置，`NO-GO` 在当前 16 GiB M4 上进入成功导向的真实生成；绝不等于 VoiceGenerator 已可用。** 资源结论与同目录 [VG0-local-topology.md](./VG0-local-topology.md) 一致。

## 2. 官方来源与固定 revision

以下 URL 均在 2026-08-29 复核。带 revision/commit 的链接是本报告的可重复证据；`main` 只用于确认当日指向，不作为运行输入。

| 对象 | 本轮冻结值 | 官方一手来源 | 用途 |
| --- | --- | --- | --- |
| VoiceGenerator 模型 | `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4` | [固定 revision tree](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/tree/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4)、[固定 revision API（含 blob/LFS 元数据）](https://huggingface.co/api/models/OpenMOSS-Team/MOSS-VoiceGenerator/revision/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4?blobs=true) | 文件、体积、hash、public/gated/license metadata |
| VoiceGenerator 模型卡 | 同上 | [README.md](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/blob/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/README.md) | 能力、输入、推荐解码值、官方 quickstart |
| VoiceGenerator 配置 | 同上 | [config.json](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/blob/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/config.json) | 架构、dtype、24 kHz、Qwen3-1.7B、Transformers 序列化版本 |
| Processor 自定义代码 | 同上 | [processing_moss_tts.py](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/blob/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/processing_moss_tts.py) | codec 默认引用、输入规范化、编码/解码接口 |
| Model 自定义代码 | 同上 | [modeling_moss_tts.py](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/blob/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/modeling_moss_tts.py) | `generate()` 默认参数、随机采样和最大 token 行为 |
| full audio tokenizer | `3cd226ba2947efa357ef453bcad111b6eafba782` | [固定 revision tree](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer/tree/3cd226ba2947efa357ef453bcad111b6eafba782)、[固定 revision API](https://huggingface.co/api/models/OpenMOSS-Team/MOSS-Audio-Tokenizer/revision/3cd226ba2947efa357ef453bcad111b6eafba782?blobs=true) | codec 完整文件、体积、权重 SHA-256 |
| full audio tokenizer 模型卡/配置 | 同上 | [README.md](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer/blob/3cd226ba2947efa357ef453bcad111b6eafba782/README.md)、[config.json](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer/blob/3cd226ba2947efa357ef453bcad111b6eafba782/config.json) | 24 kHz、32 层 RVQ、12.5 Hz、FP32、encode/decode 约束 |
| 官方源码仓库 | `58b20a0d5fcc6766658d50967a90a9d890009a46` | [commit](https://github.com/OpenMOSS/MOSS-TTS/commit/58b20a0d5fcc6766658d50967a90a9d890009a46)、[README.md](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/README.md) | 当前环境安装说明和模型家族定位 |
| VoiceGenerator 源模型卡/官方 app | 同一源码 commit | [模型卡](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/docs/moss_voice_generator_model_card.md)、[Gradio app](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/clis/moss_voice_generator_app.py) | 设备选择、dtype、参数范围、输出、单并发参考实现 |
| 依赖与许可 | 同一源码 commit | [pyproject.toml](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/pyproject.toml)、[LICENSE](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/LICENSE) | Python/运行依赖和 Apache 2.0 完整文本 |

### 2.1 revision 冻结规则

- VG1 不得把 `main`、短 SHA、网页显示日期或下载时“最新版”写入锁；必须使用上表完整 40 位 revision。
- VoiceGenerator processor 的默认 `codec_path` 只有仓库名，没有 codec revision。VG1 必须把两个固定 revision 分别安装为仓库外、只读的本地 snapshot，再以本地绝对路径传给 `pretrained_model_name_or_path` 与 `codec_path`。
- 不建议在远程加载调用中同时传 VoiceGenerator `revision=97521...` 和默认 codec 名称：processor 会把剩余 kwargs 同时转交 VoiceGenerator config/tokenizer 与 codec 的 `AutoModel.from_pretrained()`；独立仓库的两个 SHA 不能用同一个 `revision` 表达。这是基于固定 processor 代码的**技术推断**，VG1 应用一个不下载权重的最小调用测试复核。
- 所有 `trust_remote_code=True` 的代码也属于制品锁的一部分；不能只 hash 权重而让 Python 自定义代码跟随 `main`。

## 3. 官方能力与输入/输出约束

### 3.1 已核实能力

| 维度 | 官方已核实范围 | 不得扩大解释 |
| --- | --- | --- |
| 音色设计 | 由自由文本 `instruction` 直接设计 speaker timbre；无需参考音频 | 不是从人物卡自动读取事实；人物卡到 instruction 仍是本项目后续 AI/领域编排 |
| 可描述特征 | voice characteristics、emotion、style、speed、pitch；官方示例还使用年龄感、口音、清晰度和角色语气 | 这些是自然语言条件，不是音高 Hz、语速倍数等精确物理旋钮 |
| 语言 | 模型卡明确中文和英文 | 日文及其他语言未由本模型卡承诺；不能因 MOSS 家族其他模型支持而外推 |
| 使用形态 | 可独立合成，也可作为下游 TTS 的 voice-design layer | “可作为下游层”不是 Nano 克隆保真已经验证的证据 |
| 批处理 | 官方 quickstart 一次构造 4 条中英文 conversation 并批量调用 | 产品默认并发和内存容量仍未验证；官方 Gradio app 将队列并发限制为 1 |

### 3.2 输入约束

- 官方模型卡把 `text: str` 与 `instruction: str` 都列为必填；官方 Gradio app 对 trim 后空值直接报错。
- `text` 是实际生成的试听内容，不是人物音色参数；`instruction` 才是音色、风格与表现描述。
- 官方 quickstart 使用 `normalize_inputs=True`。固定 processor 会：
  - 删除 instruction 中方括号 `[...]` 与花括号 `{...}` 包裹内容；
  - 去除换行，把一组装饰符号替换成逗号，并合并连续标点；
  - instruction 含中文时把英文逗号替换成中文逗号；
  - 对 text 也执行其独立的 normalization。
- **项目约束建议：**后续 `VoiceDesignDraft` 不应把必须保留的结构化字段编码为 `[]`/`{}` 标签后直接送模型；VG1 必须记录送入 processor 前后的 canonical instruction。
- 固定 `config.json` 的 language backbone 最大位置为 `40960`，但官方模型卡没有给出可保证成功的 text/instruction 字符上限。产品不能把 `40960` 直接展示成作者字符限制；VG1 需用短、固定 fixture 冻结更窄的输入上限。

### 3.3 解码参数

官方模型卡推荐值，也是固定 `model.generate()` 的 audio 默认值：

| 参数 | 官方推荐/模型默认 | 官方 Gradio 范围 |
| --- | ---: | ---: |
| `audio_temperature` | `1.5` | `0.1–3.0`，步长 `0.05` |
| `audio_top_p` | `0.6` | `0.1–1.0`，步长 `0.01` |
| `audio_top_k` | `50` | `1–200`，步长 `1` |
| `audio_repetition_penalty` | `1.1` | `0.8–2.0`，步长 `0.05` |

补充事实：

- 固定模型代码还存在 text sampling 默认值：`text_temperature=1.5`、`text_top_p=1.0`、`text_top_k=50`；官方产品模型卡没有把它们列为 VoiceGenerator 推荐调音入口。
- `model.generate()` 的 `max_new_tokens` 默认是 `1000`；官方 Gradio app 把默认值改成 `4096`，范围 `256–8192`、步长 `128`。这两者不是同一个默认口径。
- 温度大于 0 时启用随机采样；官方 app 没有 seed 控件或可重复性承诺。VG1 必须自行记录 PyTorch seed、完整参数与制品 fingerprint，并验证同 seed 是否真正可复现。
- 官方材料未给出 `max_new_tokens` 到音频秒数的一一保证，也未给出文本长度、生成时长或内存的安全上限；产品不得据 UI slider 推断可生成 10 分钟稳定音频。

### 3.4 输出约束

- 固定配置的采样率是 `24,000 Hz`、`n_vq=16`；模型先生成多通道离散 token，processor 再调用 full codec 解码。
- 官方 quickstart 取 `message.audio_codes_list[0]`，加一个 channel 维后用 `torchaudio.save(..., sampling_rate=24000)` 保存 WAV；官方 Gradio app 返回 `(sample_rate, 1-D float32 numpy waveform)`。因此后续 spike 可把“24 kHz 单通道可解码 waveform/WAV”作为技术检查，但不能在实测前承诺位深、响度、时长或听感。
- full codec 模型卡说明 24 kHz 输入、12.5 Hz frame rate、32 层 RVQ，encode/decode 支持 `chunk_duration`；流式 chunking 仅支持 batch size 1，chunk 秒数还须不超过 context duration且换算 sample 数可被 downsample rate 整除。
- VoiceGenerator processor 的 decode 路径当前给 codec `chunk_duration=8`。这不等于 VoiceGenerator 本身是低延迟流式模型，也不构成首包延迟承诺。

## 4. 精确文件清单与元数据 hash

以下 hash 全部来自固定 revision 的官方 Hugging Face API，**尚未在本机下载后复算**。普通 Git 文件列 `blobId`（Git blob SHA-1）；LFS/Xet 大文件列 API 报告的 SHA-256。VG1 只有下载后逐文件 SHA-256 与锁一致才可进入 import/load。

### 4.1 VoiceGenerator `97521ec…`

| 文件 | bytes | 官方元数据 hash | VG1 用途 |
| --- | ---: | --- | --- |
| `.gitattributes` | 1,570 | blob SHA-1 `52373fe24473b1aa44333d318f578ae6bf04b49b` | 仓库元数据，不是运行必需 |
| `README.md` | 15,002 | blob SHA-1 `54a3f7323a01921acc15a4c28446990dd67898a5` | 模型卡，不是运行必需 |
| `__init__.py` | 0 | blob SHA-1 `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391` | 运行 |
| `added_tokens.json` | 704 | blob SHA-1 `82da7c72d0a900d520bfe3ef5e2b3bb95bf87f6d` | 运行 |
| `chat_template.jinja` | 352 | blob SHA-1 `92909f8edadc3842c289ccfd7cd5de6a9ac655e4` | 运行 |
| `config.json` | 2,203 | blob SHA-1 `260e999b1652268d7f1214947610e98171bf545b` | 运行 |
| `configuration_moss_tts.py` | 5,584 | blob SHA-1 `f7e91c65f7f30c35d309b4ebc50453cf5c89eebf` | `trust_remote_code` 运行 |
| `inference_utils.py` | 5,092 | blob SHA-1 `b2175d852af5469e3e9dd7688b2c8798d1a1cea8` | `trust_remote_code` 运行 |
| `merges.txt` | 1,671,853 | blob SHA-1 `31349551d90c7606f325fe0f11bbb8bd5fa0d7c7` | tokenizer |
| `model.safetensors` | 4,228,278,872 | SHA-256 `dbe345257ff9f6cc84195bed830a268b39d5e0b728ff3ba90e715150a49b16d4` | 权重 |
| `modeling_moss_tts.py` | 25,329 | blob SHA-1 `422a2f57f79ef7ea99b9b2904cbe755f1a16a977` | `trust_remote_code` 运行 |
| `processing_moss_tts.py` | 37,220 | blob SHA-1 `cd4192a647a8def1fc1b23923b780983c66658ce` | `trust_remote_code` 运行 |
| `processor_config.json` | 145 | blob SHA-1 `b5df3b949f047d5949fafa7d42b9cf8693fcbb94` | 运行 |
| `special_tokens_map.json` | 631 | blob SHA-1 `f1e356a4bfa4ead1419a3116957555c1cbfeb26a` | tokenizer |
| `tokenizer.json` | 11,422,691 | SHA-256 `cb3c8fa82993d515469c2800cc455bff4aaa3c4fed9da1f2b0c0668c304f335a` | tokenizer |
| `tokenizer_config.json` | 5,501 | blob SHA-1 `c75c008749bc999e4749eafb407512f428b01acc` | tokenizer |
| `vocab.json` | 2,776,833 | blob SHA-1 `4783fe10ac3adce15ac8f358ef5462739852c569` | tokenizer |

汇总：完整仓库 `4,244,249,582` bytes；排除 `.gitattributes` 与 README 的 15 个运行制品为 `4,244,233,010` bytes；权重为 `4,228,278,872` bytes。

### 4.2 Full MOSS-Audio-Tokenizer `3cd226…`

| 文件 | bytes | 官方元数据 hash | VG1 用途 |
| --- | ---: | --- | --- |
| `.gitattributes` | 1,826 | blob SHA-1 `5d06fbf1ca526fa43520fa5ed380c75e8c012678` | 仓库元数据 |
| `README.md` | 10,778 | blob SHA-1 `9c7fd4615e79e32fa82deb5b66aa44b641252f50` | 模型卡 |
| `__init__.py` | 52 | blob SHA-1 `be87d805388ff76659c35e7273e8c3687b55eeff` | 运行 |
| `config.json` | 6,601 | blob SHA-1 `7683ae6ce1697e4ce5894de857a28d08df79ef59` | 运行 |
| `configuration_moss_audio_tokenizer.py` | 12,933 | blob SHA-1 `d82791b43f5cb87256a810b8ee718c2ba4b685fa` | `trust_remote_code` 运行 |
| `images/arch.png` | 214,969 | SHA-256 `6a7108429fc230ead608a22837a27615aae3458f86e5e47d12fd3bd5d95c7058` | 文档，不是运行必需 |
| `images/pesq-nb.png` | 743,304 | SHA-256 `107c2f8fb91247264497b50f0bb42f34390ce4593eed28ce4dfea47b88a36797` | 文档，不是运行必需 |
| `images/pesq-wb.png` | 511,823 | SHA-256 `ae7b264b13e8570c292d8843ce83fcf21e96360e2900c8e19a8ff837be3c90fd` | 文档，不是运行必需 |
| `images/sim.png` | 492,914 | SHA-256 `79c6340a32e1229ab89fdc71447aa0addf91f146d250b1c3416707c5aacee75d` | 文档，不是运行必需 |
| `images/stoi.png` | 440,051 | SHA-256 `86d2a427d213fbd8913052d0d16e87c2384a6643f26458314c8771b95eab89c4` | 文档，不是运行必需 |
| `model-00001-of-00002.safetensors` | 4,998,259,168 | SHA-256 `037f441ed30a0ab59f6049de83b824a1b3bd6feb7dbd46c3fbca41fc2f649f28` | 权重 |
| `model-00002-of-00002.safetensors` | 2,100,202,560 | SHA-256 `a187d73d2cda1c2d0676586d9d03c09c0a5813450266af32029c871493fc9582` | 权重 |
| `model.safetensors.index.json` | 148,113 | blob SHA-1 `f29f2656102e41040db3d3e5223464249891b44e` | 权重索引 |
| `modeling_moss_audio_tokenizer.py` | 70,906 | blob SHA-1 `2956a4b4482433ad3face7f6ee7eb176891a449a` | `trust_remote_code` 运行 |

汇总：完整仓库 `7,101,115,998` bytes；排除 `.gitattributes`、README 与 5 张文档图后的运行制品为 `7,098,700,333` bytes；两个权重分片为 `7,098,461,728` bytes。

## 5. 依赖与设备约束

### 5.1 已核实依赖

官方源码 `pyproject.toml` 在 `58b20a…` 的边界是：

- Python 包声明：`requires-python = ">=3.10"`；官方 README 推荐干净的 Python 3.12 环境。
- core：`safetensors==0.6.2`、`numpy==2.1.0`、`orjson==3.11.4`、`tqdm==4.67.1`、`PyYAML==6.0.3`、`einops==0.8.1`、`scipy==1.16.2`、`librosa==0.11.0`、`tiktoken==0.12.0`，以及 `psutil/packaging/ninja/setuptools/wheel/gradio`。
- `torch-runtime` extra：`torch==2.9.1+cu128`、`torchaudio==2.9.1+cu128`、`torchcodec==0.8.1`、`transformers==5.0.0`、`accelerate>=1.10.1`。
- `flash-attn` 是可选 extra；官方代码只在 CUDA、FP16/BF16 且设备 capability major ≥ 8 时尝试，否则 CUDA 用 SDPA、CPU 用 eager。
- VoiceGenerator `config.json` 写有 `transformers_version=4.57.1`，full codec 写有 `4.56.0.dev0`；它们是导出配置元数据，官方当前运行依赖仍明确为 Transformers 5.0.0。这个跨版本组合必须由真实 import/generate 验证，不能任选一个版本后宣称兼容。

### 5.2 官方材料中的依赖漂移

- 固定 VoiceGenerator HF README 仍展示 `pip ... -e .`，但又说 pyproject 固定 Torch/Torchaudio；当前固定源码实际上把 Torch 栈放在 `torch-runtime` extra，源码根 README 已改为 `-e ".[torch-runtime]"`。
- 当前 `torch-runtime` 用显式 `+cu128` 版本且没有 Darwin environment marker。**技术推断：**官方命令不能原样解析为 macOS arm64 运行环境；VG1 必须在独立目录形成一份项目自有、可重建的 CPU/MPS 依赖锁，并把与官方 CUDA 锁的差异写入证据。
- 源码仓库新出现的 llama.cpp / ONNX tokenizer extra 不构成 VoiceGenerator 已支持该后端的证据；固定 VoiceGenerator 模型卡和 app 仍使用 Torch `AutoModel` + full PyTorch codec。VG1 不得未经专门证据把其它 MOSS-TTS 后端套到 VoiceGenerator 上。

### 5.3 设备和内存

官方路径：

```text
torch.cuda.is_available() == true  -> device=cuda, dtype=bfloat16
其他                                -> device=cpu,  dtype=float32
```

没有 `torch.backends.mps.is_available()` 分支，也没有 macOS/MPS wheel lock、attention 实现或 codec 运算支持声明。

静态体积算术：

```text
VoiceGenerator BF16 权重               4,228,278,872 bytes
CPU 路径转 FP32 的 VG 静态下界          8,456,557,744 bytes
full codec FP32 权重                    7,098,461,728 bytes
CPU/FP32 静态权重下界合计              15,555,019,472 bytes = 14.487 GiB
```

这是由官方文件体积、配置 dtype 和示例设备分支得到的**技术推断**，不是峰值 RSS。实际峰值只会再加入运行时和激活等成本，因而不能用“16 GiB 大于 14.487 GiB”推导可运行。

## 6. 许可证核验

### 6.1 已核实事实

- VoiceGenerator 固定 HF README front matter 为 `license: apache-2.0`，固定 revision API 也返回 `license:apache-2.0` tag。
- full MOSS-Audio-Tokenizer 固定模型卡和 API 同样标记 Apache 2.0，并在模型卡 License 小节明确声明 Apache 2.0。
- 官方源码 `pyproject.toml` 指向 `LICENSE`，固定 commit 的 LICENSE 是标准 Apache License 2.0 全文；官方根 README 声明 MOSS-TTS Family 模型按 Apache 2.0 发布。
- 两个模型仓库在核验时均为 `private=false`、`gated=false`、`disabled=false`，不存在必须接受额外 gated 条款才可获取的官方 API 状态。

### 6.2 许可边界与仍待法律/产品判断

- 本轮未发现 VoiceGenerator 或 codec 的额外“仅研究/禁止商用”模型许可证；Apache 2.0 允许在遵守其版权、许可、NOTICE/修改说明、专利与商标条款的前提下使用、修改和分发制品。这里是工程许可证核验，不是针对具体发行方式的法律意见。
- HF 模型 snapshot 本身未携带一份独立 LICENSE 文件；许可证全文来自同一官方源码仓库，HF 侧以 metadata/model card 标识。这足以作为 VG1 的来源证据，但产品打包/再分发时仍应由后续运行包保留 LICENSE/NOTICE 和精确制品来源。
- Apache 2.0 管的是官方代码/模型制品，不自动授予第三方小说文本、真人姓名/声纹、肖像人格、隐私、商标或生成音频传播权。本项目“只允许自有/授权文本、拒绝可识别真人模仿、默认私人本地用途”的边界必须继续保留。
- 固定 VoiceGenerator 模型卡没有给出训练数据明细、模型局限/滥用章节、真人相似度防护或生成音频专门条款；这些不能被“仓库公开”替代。

## 7. 技术推断（不得写成已验证事实）

1. **独立环境是硬要求。** VoiceGenerator 的 Torch 2.9.1 / Transformers 5.0.0 与现有 Nano 运行栈不同；把依赖混进 Nano Sidecar 或 QwenPaw 进程会制造不可审计的版本漂移。
2. **默认 codec 会漂移。** VoiceGenerator revision 自 2026-02-11 未变，但它引用的 codec `main` 在本轮解析到 2026-06-05 的 `3cd226…`。只固定 VoiceGenerator 不能重复构建同一条音频链。
3. **MPS 不能只改一行设备名。** VoiceGenerator 主模型、full codec、自定义 processor/attention、Torchaudio 和 FP32/BF16 转换都需共同通过；任一 unsupported op 回退 CPU 都可能突破内存门禁。
4. **当前 16 GiB 主机不具备成功导向的 CPU 尖峰预算。** 14.487 GiB 只是静态权重下界，且 VG0-B 已观测 Docker VM 仅约 7.75 GiB、宿主还承载 QwenPaw/PostgreSQL/Nano。
5. **生成候选不是人物音色已建档。** VoiceGenerator 输出需退出并释放重模型 residency，再由 Nano 做独立克隆/测试，随后才能在短事务中提升为不可变 generated version；本轮没有验证这条闭包。
6. **官方 app 的 `default_concurrency_limit=1` 是实现参考，不是数据库互斥。** 产品化仍需计划 33 定义的跨进程共享 residency claim；两个不同 resource key 不能证明 VoiceGenerator 与 Nano 不同时常驻。

## 8. 仍待 VG1 验证

### 8.1 制品与供应链

- 在仓库外 staging 按两个完整 revision 获取精确 allowlist；逐文件复算 SHA-256，并为所有小文件生成项目锁使用的 SHA-256，不能长期只依赖 Git blob SHA-1。
- 验证 VoiceGenerator、codec 自定义 Python 文件与锁完全一致，离线加载不会回访 `main`，没有额外隐式模型下载。
- 验证失败下载可只清理精确 staging，不碰 Nano 模型卷、用户媒体或 Git；原子安装后运行挂载只读。
- 补齐分发所需 LICENSE/NOTICE、来源 URL、revision、文件清单和修改说明。

### 8.2 macOS arm64 依赖

- Python 3.11（项目真实宿主下限）与官方推荐 Python 3.12 各自的可解析性；最终生产候选必须兼容项目 `>=3.11,<3.14` 边界。
- macOS arm64 的 Torch/Torchaudio/Torchcodec/Transformers 精确版本与 wheel 来源、`pip check`、导入闭包；不允许静默换版本。
- Transformers 5.0.0 是否可执行导出时标记 4.57.1 / 4.56.0.dev0 的两套 custom code。
- MPS 是否支持主模型和 codec 的全部运算、所需 dtype、attention、随机采样、decode 与 Torchaudio 输出；是否出现 CPU fallback。

### 8.3 真实运行与退出

- 冷启动、加载峰值、首个完整候选耗时、RTF、MPS allocated/driver memory、宿主 RSS、memory pressure 和 swap 增量。
- 固定 fixture 下的 24 kHz、单通道、非空、可解码、时长、NaN/Inf、削波、响度和 hash；模型卡的主观能力主张不能替代本项目听检。
- 相同 seed/参数/输入的可重复性，以及连续推进 seed 的可感知差异。
- 有界取消、超时、OOM/unsupported-op 后的失败收敛；中途结果不得发布。
- 一次性 worker 退出后 PID、RSS、MPS 内存和文件句柄确实释放；VoiceGenerator 完全退出后 Nano 才加载。
- 三类虚构人物的默认候选和两次“换一个”、中英文输入、Nano 二次克隆的可懂度/基本辨识度、QwenPaw 原生功能非回归。

### 8.4 产品和权利边界

- 人物卡明确字段到 `instruction` 的确定性映射、缺字段中性处理、禁止从姓名/头像/民族推断声音特征。
- 拒绝“模仿某可识别真人”的 prompt，日志只保留 HMAC/fingerprint，不泄漏人物描述或试听文本。
- generated reference 提升、ModelRun、不可变版本、绑定 CAS、失败不改当前声音和删除生命周期仍需后续 gate；VG0-A 不授权提前开放入口。

## 9. VG1 前置输入与硬停止条件

### 9.1 可交给 VG1 的冻结输入

```text
voice_generator_repo     = OpenMOSS-Team/MOSS-VoiceGenerator
voice_generator_revision = 97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4
voice_generator_weight   = model.safetensors
voice_generator_sha256   = dbe345257ff9f6cc84195bed830a268b39d5e0b728ff3ba90e715150a49b16d4

codec_repo               = OpenMOSS-Team/MOSS-Audio-Tokenizer
codec_revision           = 3cd226ba2947efa357ef453bcad111b6eafba782
codec_shard_1_sha256     = 037f441ed30a0ab59f6049de83b824a1b3bd6feb7dbd46c3fbca41fc2f649f28
codec_shard_2_sha256     = a187d73d2cda1c2d0676586d9d03c09c0a5813450266af32029c871493fc9582

source_repo_revision     = 58b20a0d5fcc6766658d50967a90a9d890009a46
license                  = Apache-2.0
sample_rate_hz           = 24000
official_audio_defaults  = temperature 1.5 / top_p 0.6 / top_k 50 / repetition_penalty 1.1
```

### 9.2 硬停止条件

任一条件发生，VG1 保持 `NO-GO/HOLD`，不得开启 capability：

- revision、文件 allowlist、下载后 SHA-256 或许可证证据不一致；
- 依赖解析需要污染 Nano/QwenPaw 现有环境，或不能形成独立可重建锁；
- 任何远程代码/codec 仍跟随 `main`；
- 当前 16 GiB 主机试图绕过 VG0-B 的内存与 Docker 门禁开始真实加载；
- MPS unsupported op、隐式 CPU fallback、OOM、持续红色内存压力、swapout 持续增长或 QwenPaw 健康下降；
- 取消/退出后模型内存不回落，或 Nano 必须与 VoiceGenerator 同时常驻；
- 输出不可解码、空音频、明显技术失败，或 Nano 二次克隆不满足最小可懂度/辨识度；
- 未授权真人模仿、第三方文本/声音权利或隐私边界无法收敛。

## 10. 可复核命令

以下命令只请求官方仓库引用、文本与元数据；本轮没有调用任何权重 `resolve` URL，也没有创建模型缓存。

```bash
git ls-remote https://github.com/OpenMOSS/MOSS-TTS.git refs/heads/main

curl -fsSL \
  'https://huggingface.co/api/models/OpenMOSS-Team/MOSS-VoiceGenerator/revision/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4?blobs=true' \
  | jq '{id,sha,lastModified,private,gated,disabled,tags,siblings}'

curl -fsSL \
  'https://huggingface.co/api/models/OpenMOSS-Team/MOSS-Audio-Tokenizer/revision/3cd226ba2947efa357ef453bcad111b6eafba782?blobs=true' \
  | jq '{id,sha,lastModified,private,gated,disabled,tags,siblings}'

curl -fsSL \
  'https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/raw/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/README.md'
curl -fsSL \
  'https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/raw/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/config.json'
curl -fsSL \
  'https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/raw/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/processing_moss_tts.py'
curl -fsSL \
  'https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/raw/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/modeling_moss_tts.py'

curl -fsSL \
  'https://raw.githubusercontent.com/OpenMOSS/MOSS-TTS/58b20a0d5fcc6766658d50967a90a9d890009a46/pyproject.toml'
curl -fsSL \
  'https://raw.githubusercontent.com/OpenMOSS/MOSS-TTS/58b20a0d5fcc6766658d50967a90a9d890009a46/clis/moss_voice_generator_app.py'
curl -fsSL \
  'https://raw.githubusercontent.com/OpenMOSS/MOSS-TTS/58b20a0d5fcc6766658d50967a90a9d890009a46/LICENSE'
```

## 11. 最终建议

**建议：`GO` 进入 VG1 的受限前置阶段，`NO-GO` 当前 M4 / 16 GiB 的真实加载阶段。**

官方制品、能力、许可、输入输出和依赖风险已经足够明确，继续做精确 artifact lock、离线 snapshot、hash 与 arm64 依赖解析有工程价值；但官方并未提供 MPS 路径，CPU/FP32 静态权重下界又已接近整机物理内存。下一步应先汇合 VG0-B，在至少 24 GiB、建议 32 GiB 的隔离主机上，以一次性进程和严格资源中止器执行真实 VG1。没有真实峰值、退出回收、三类虚构人物、Nano 二次克隆和听检证据前，`VOICE_GENERATOR_NO_GO` 与隐藏 capability 必须保持不变。
