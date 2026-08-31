# VG40-A-OFFICIAL：MOSS-VoiceGenerator 官方事实、Apple 运行边界与 T1–T4 建议

状态：**2026-08-30 只读复核完成；未下载权重、未安装依赖、未运行模型，不能据此裁决 `VG16-SAFE`。**

工作包：`VG40-A-OFFICIAL`

复核日期：2026-08-30（Asia/Shanghai）

适用主机：Apple M4／16 GiB

唯一目的：为计划40的 `VG40-T0` 固定官方 revision、权重事实、官方设备分支、codec 加载边界、MPS 候选条件和量化来源边界。

## 一、结论先行

### 1.1 本轮已经证明的事实

1. **“VoiceGenerator 只有 1.7B，所以 16 GiB 一定够”不是完整资源口径。**官方 VoiceGenerator 权重有 `2,114,118,656` 个 BF16 参数，权重文件约 4.23 GB；它的官方 `AutoProcessor` 还会立即加载 `MOSS-Audio-Tokenizer`，后者有 `1,774,566,400` 个 F32 参数、权重约 7.10 GB。
2. **官方 PyTorch 示例没有 MPS 分支。**固定源码只在 `torch.cuda.is_available()` 为真时使用请求设备和 BF16；否则直接创建 CPU device 并把 VoiceGenerator 设为 FP32。即使传入 `--device mps`，该分支也会回落 CPU。
3. **官方 PyTorch 示例会让 VoiceGenerator 与完整 codec 同时驻留。**`AutoProcessor.from_pretrained(...)` 先加载 Audio Tokenizer，随后再加载 VoiceGenerator；生成完成后 `processor.decode(outputs)` 直接调用 codec 解码。
4. **官方原始 CPU/FP32 组合路径的静态参数下界约 14.49 GiB。**这还不含 Python、PyTorch、模型对象开销、KV cache、激活、临时 tensor、文件页、macOS 和其他服务。因此该组合路径不应在 16 GiB 主机上实跑。
5. **分阶段解码在数据结构上有可信边界，但不是官方 PyTorch 公共 API。**VoiceGenerator 先输出离散多通道 token；官方 processor 随后执行 de-delay、分段、codec decode。官方 `OpenMOSS/llama.cpp` 端到端工具也明确把 `raw.codes.bin` 与后续音频解码分成两个步骤。这支持计划40继续做 T3/T4，但必须做固定源码的窄适配和 parity 验证。
6. **Apple 平台具备 MPS 与 BF16 的平台基础，但 MOSS-VoiceGenerator 的 MPS 可用性仍未被官方证明。**Apple 官方说明 macOS Sonoma 起 MPSGraph 支持 BF16，当前稳定 PyTorch 可通过 `mps` device 使用 Apple GPU；MOSS 官方源码却没有 MPS 选择、MPS attention 分支或该模型的 Apple 验收证据。
7. **截至本次复核，没有 OpenMOSS 官方发布的 VoiceGenerator 量化权重。**Hugging Face 模型树只列出一个个人账号的 BF16 GGUF 转换；它不是 OpenMOSS 官方制品，也不是低比特 VoiceGenerator。Audio Tokenizer 存在社区 MLX 8-bit 转换，但不属于 OpenMOSS 官方 namespace，也没有本项目所需的 VoiceGenerator 端到端 parity 证据。

### 1.2 当前裁决

| 项目 | 裁决 | 原因 |
| --- | --- | --- |
| 官方 PyTorch CPU/FP32 组合路径 | `NO-RUN` | 仅静态参数已约 14.49 GiB，不能保持计划要求的 4 GiB 系统余量 |
| 官方 PyTorch 原样传 `mps` | `BLOCKED_BY_CODE` | 源码在无 CUDA 时强制 CPU，`mps` 参数不会生效 |
| MPS/BF16 单模型、一次性进程 | `PROCEED_TO_T1/T2` | 平台具备候选能力，但必须验证实际算子、dtype、峰值和回收 |
| VoiceGenerator→token→退出→codec | `PROCEED_TO_T3/T4` | 官方内部结构及官方 llama.cpp 工具证明中间 token 边界存在；仍缺本模型 parity |
| 官方 llama.cpp 直接运行 VoiceGenerator | `NOT_READY_AS_IS` | conversion 架构可识别 16-VQ，但现有便捷 prompt 路径硬编码 32-VQ／`Instruction=None`，官方文档也未给 VoiceGenerator 成功命令 |
| 社区 GGUF／MLX 量化直接进入产品 | `REJECT_FOR_NOW` | 非官方、缺本项目 parity/质量/安全证据，不满足计划40供应链门禁 |

## 二、固定官方来源与 hash

以下 revision 均为本轮访问时读取到的固定对象；后续下载不得使用浮动 `main` 替代。

### 2.1 MOSS-VoiceGenerator

| 项目 | 固定值 |
| --- | --- |
| 官方模型仓库 | [`OpenMOSS-Team/MOSS-VoiceGenerator`](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator) |
| 固定 revision | [`97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/tree/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4) |
| 仓库 API `usedStorage` | `4,239,701,563` bytes |
| safetensors 参数 | BF16 `2,114,118,656` |
| `model.safetensors` | `4,228,278,872` bytes |
| `model.safetensors` LFS SHA-256 | `dbe345257ff9f6cc84195bed830a268b39d5e0b728ff3ba90e715150a49b16d4` |
| `config.json` SHA-256 | `5b6ccfbf309a5844c130d09c9b5fa8b9eef55db27f1b7072695483b6f5524685` |
| `processing_moss_tts.py` SHA-256 | `16dda5233f9f752518d07a6b780d6555945b48547fba0b4e7faf6eb2c4ed0038` |
| 许可证 | Apache-2.0 |

固定配置事实：

- architecture：`MossTTSDelayModel`；
- language backbone：Qwen3-1.7B 结构，28 层、hidden size 2048；
- `n_vq=16`；
- `audio_vocab_size=1024`；
- `sampling_rate=24000`；
- 配置声明 `dtype=bfloat16`；
- 官方模型卡的推荐参数：`audio_temperature=1.5`、`audio_top_p=0.6`、`audio_top_k=50`、`audio_repetition_penalty=1.1`；
- 官方定位是“从自由文本描述直接设计音色，不要求参考音频”，支持中文和英文。

来源：固定 revision 的 [`config.json`](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/blob/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/config.json)、[模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/tree/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4)及 [MOSS-TTS 固定源码中的模型卡](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/docs/moss_voice_generator_model_card.md)。

### 2.2 MOSS-Audio-Tokenizer

| 项目 | 固定值 |
| --- | --- |
| 官方模型仓库 | [`OpenMOSS-Team/MOSS-Audio-Tokenizer`](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer) |
| 固定模型 revision | [`3cd226ba2947efa357ef453bcad111b6eafba782`](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer/tree/3cd226ba2947efa357ef453bcad111b6eafba782) |
| 仓库 API `usedStorage` | `7,100,864,789` bytes |
| safetensors 参数 | F32 `1,774,566,400` |
| shard 1 | `4,998,259,168` bytes；SHA-256 `037f441ed30a0ab59f6049de83b824a1b3bd6feb7dbd46c3fbca41fc2f649f28` |
| shard 2 | `2,100,202,560` bytes；SHA-256 `a187d73d2cda1c2d0676586d9d03c09c0a5813450266af32029c871493fc9582` |
| 两个 shard 合计 | `7,098,461,728` bytes |
| `config.json` SHA-256 | `0f669e288d39c9c0ffae4e39babe5167b57e89d3132f0785655d1096a8da8e45` |
| `modeling_moss_audio_tokenizer.py` SHA-256 | `65cae7744845f1b8ac65957e918cea508efe331a38e87b882b7530b6c8d7caa5` |
| 许可证 | Apache-2.0 |

官方模型卡说明该 codec 为约 1.6B 参数的统一音频 tokenizer，24 kHz、12.5 Hz frame rate、32 层 RVQ；`encode` 和 `decode` 支持 `chunk_duration` 流式分块，batch size 仅支持 1。VoiceGenerator 配置使用其中前 16 个 VQ 通道。

源码关系也需要单独固定：

- `OpenMOSS/MOSS-TTS@58b20...` 将 `moss_audio_tokenizer` 作为 Git submodule 固定在 [`OpenMOSS/MOSS-Audio-Tokenizer@56776e867cb38446fa4bc00d0aceccab5001b008`](https://github.com/OpenMOSS/MOSS-Audio-Tokenizer/commit/56776e867cb38446fa4bc00d0aceccab5001b008)；
- 截至本轮只读检查，Audio Tokenizer GitHub `main` 已前进到 `8c50ac4c5d7287d2ed6ea20a08c90ca439887d23`；
- 因此尖峰必须同时记录“模型仓库 revision”和“实际审核/运行的 remote-code revision”，不能用一个 hash 模糊代替两个来源。

### 2.3 MOSS-TTS 官方运行源码

| 项目 | 固定值 |
| --- | --- |
| 官方 GitHub | [`OpenMOSS/MOSS-TTS`](https://github.com/OpenMOSS/MOSS-TTS) |
| 固定 commit | [`58b20a0d5fcc6766658d50967a90a9d890009a46`](https://github.com/OpenMOSS/MOSS-TTS/commit/58b20a0d5fcc6766658d50967a90a9d890009a46) |
| `clis/moss_voice_generator_app.py` SHA-256 | `9047a1bf6a73d264ffaa41f42428680d8bc7ad79d1d3e69eba08b0c65c04aa02` |
| 官方 Python 要求 | `>=3.10` |
| 官方 torch runtime extra | `torch==2.9.1+cu128`、`torchaudio==2.9.1+cu128`、`transformers==5.0.0` |

固定 [`pyproject.toml`](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/pyproject.toml) 的默认 torch runtime 明确面向 CUDA 12.8；不能原样作为 macOS/arm64 依赖锁。计划40建立独立 Apple 运行环境是必要适配，不是修改 PawApp 主依赖。

### 2.4 官方 ONNX codec

| 项目 | 固定值 |
| --- | --- |
| 官方仓库 | [`OpenMOSS-Team/MOSS-Audio-Tokenizer-ONNX`](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-ONNX) |
| 固定 revision | [`c7468e67a0ce987a6a76c4dfb3314e400cc335a2`](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-ONNX/tree/c7468e67a0ce987a6a76c4dfb3314e400cc335a2) |
| 仓库总量 | `14,218,233,931` bytes |
| `decoder.data` | `7,098,576,524` bytes；SHA-256 `e5680b64d283e68fd9a7cc4074ddcd7f65a7c89e460ec6f74db379920e2cbb3e` |
| `decoder.onnx` | `13,900,498` bytes；SHA-256 `f90ac5129d47c9b571fc2521eff6c9948fb9fdf2f27ff077414286638f453aa8` |
| `encoder.data` | `7,101,884,132` bytes；SHA-256 `79b0eccd392bc08243a3e40cd4a826556f1a46a4f82973efc2b01df9f4da2eff` |
| `encoder.onnx` | `1,469,716` bytes；SHA-256 `b22b3a8e4cc7a2fda4a50cb93f4480188f3a7c18b275aa72d4b1ac9283cb0faa` |

官方说明支持 ONNX Runtime CPU、ONNX Runtime GPU 和用户自建 TensorRT；**没有宣称 PyTorch MPS、Core ML 或 ONNX Runtime CoreML Execution Provider 已通过。**VoiceGenerator 不使用参考音频时只需要 decode，因此 T4 可只准备 decoder 两文件，不应下载或加载 encoder 来增加磁盘和内存压力。

### 2.5 官方 llama.cpp 第一方实现

| 项目 | 固定值 |
| --- | --- |
| 官方仓库/分支 | [`OpenMOSS/llama.cpp:moss-tts-firstclass`](https://github.com/OpenMOSS/llama.cpp/tree/moss-tts-firstclass) |
| 固定 commit | [`b785003ba497794ecfa337c3e47f01af79489888`](https://github.com/OpenMOSS/llama.cpp/commit/b785003ba497794ecfa337c3e47f01af79489888) |
| 第一方 E2E 文档 SHA-256 | `4a67a202c49ab8e81641da0f5bdc0378adfc303781ae75fbc04ce70da3f414d7` |

官方 [E2E 文档](https://github.com/OpenMOSS/llama.cpp/blob/b785003ba497794ecfa337c3e47f01af79489888/docs/moss-tts-firstclass-e2e.md) 明确提供：

```text
generation input
→ llama.cpp backbone
→ raw.codes.bin
→ 独立 ONNX audio decode
→ wav
```

但它当前不能被写成“VoiceGenerator 已可直接运行”：

- 文档命令只针对 `OpenMOSS-Team/MOSS-TTS`；
- `tools/tts/moss_tts_processor.py` 固定 `N_VQ = 32`，VoiceGenerator 配置是 16；
- 原生 C++ text prompt 固定 `Instruction=None`；
- conversion class 能读取 `n_vq` 并识别 `MossTTSDelayModel`，说明结构有适配基础，但官方没有给出 VoiceGenerator conversion、instruction prompt 和音频质量 parity 的完整通过证据；
- 官方没有发布 VoiceGenerator 对应的预转换/预量化 GGUF。

因此它是 T3/T4 的参考实现和后备尖峰方向，不是当前可替换 PyTorch 路径的成品。

## 三、官方设备分支与内存下界

### 3.1 官方代码实际做了什么

固定 [`moss_voice_generator_app.py`](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/clis/moss_voice_generator_app.py) 的关键逻辑是：

```text
device = requested device if CUDA available else CPU
dtype = BF16 only when device is CUDA, otherwise FP32
AutoProcessor.from_pretrained(...)     # 这里立即加载完整 Audio Tokenizer
processor.audio_tokenizer.to(device)
AutoModel.from_pretrained(...).to(device)
model.generate(...)
processor.decode(outputs)              # 这里调用 Audio Tokenizer decode
```

attention 分支也只有：

- CUDA + FlashAttention 2；
- CUDA + SDPA；
- 非 CUDA + eager。

没有 MPS、Metal、MLX 或 Apple 专用分支。

### 3.2 静态权重下界

| 拓扑 | 计算 | 静态参数下界 |
| --- | --- | ---: |
| VoiceGenerator 保持 BF16 | `2,114,118,656 × 2 bytes` | `3.94 GiB` |
| VoiceGenerator 被官方 CPU 路径转 FP32 | `2,114,118,656 × 4 bytes` | `7.88 GiB` |
| Audio Tokenizer 官方 F32 | `1,774,566,400 × 4 bytes` | `6.61 GiB` |
| 官方 CPU/FP32 两者同时驻留 | 上两项相加 | `14.49 GiB` |
| 假设 VG 在 MPS 保持 BF16、codec 仍 F32且同时驻留 | 两项相加 | `10.55 GiB` |

这些值只是参数 tensor，不是进程峰值。至少还会有：

- safetensors 加载与 dtype 转换瞬态；
- module、allocator 和 Metal buffer；
- 生成 KV cache；
- 17 通道输出 head/logits 与采样 tensor；
- codec 工作区和 waveform tensor；
- Python、Transformers、PyTorch、macOS 及长期服务占用。

按 VoiceGenerator 的 28 层、8 KV heads、head dim 128 粗算，4096 step 的 BF16 K/V 本身约 `448 MiB`；这仍未计 logits 和其他激活。该值是**工程估算**，必须由 T3 的真实指标取代。

### 3.3 对“16 GiB 能不能运行”的准确回答

- **已核实事实：**官方原始 CPU/FP32 组合路径没有安全余量，不能运行。
- **工程推断：**VoiceGenerator 单独 BF16 约 3.94 GiB，Audio Tokenizer 单独 F32 约 6.61 GiB；若真正分进程、分阶段且能避免加载期双副本，两个阶段各自有可能落入 16 GiB。
- **仍待验证：**MPS/BF16 全算子闭包、单模型真实峰值、退出回收、codec decode 峰值、速度与音质。

所以计划40继续尝试是合理的，但“1.7B 模型很小”不能直接替代 T1–T4。

## 四、MPS 可行性复核

### 4.1 平台层事实

Apple 官方资料说明：

- PyTorch 的 `mps` device 通过 MPSGraph 和 Metal kernel 使用 Apple GPU；
- 当前稳定 PyTorch 的 Apple 安装要求包括 Apple silicon、macOS 14.0+、Python 3.10+；
- MPS backend 仍处于 beta；
- macOS Sonoma 起 MPSGraph 支持 BF16，Apple 也说明 MPS 自动混合精度可使用 FP16/BF16。

来源：[Apple：Accelerated PyTorch training on Mac](https://developer.apple.com/metal/pytorch/)、[WWDC23：Optimize machine learning for Metal apps](https://developer.apple.com/videos/play/wwdc2023/10050/)。

### 4.2 不能从平台事实推出什么

上述资料不能证明以下事项：

- `MossTTSDelayModel.generate()` 的所有 op 都支持 MPS/BF16；
- Audio Tokenizer 的 causal transformer、RVQ 与 chunk decode 全部支持 MPS；
- unsupported op fallback 不会产生 CPU/GPU 复制和双份内存；
- BF16 模型的 attention、采样和 logits 在该环境中数值稳定；
- MPS allocator 会在子进程退出前主动把内存还给系统；
- 官方 CUDA 锁定的 PyTorch/Transformers 组合可无修改安装到 macOS。

因此 MPS 是**首选候选拓扑**，不是已交付能力。

### 4.3 对 T1 的要求

T1 应只建立 macOS/arm64 独立环境并做空载探针：

1. 不安装官方 `torch-runtime` extra；它固定 `+cu128`。
2. 单独锁定 Apple wheel、Transformers、safetensors、torchaudio 等兼容版本，并保存解析结果。
3. 验证 `torch.backends.mps.is_available()`、BF16 tensor 创建、embedding、RMSNorm、RoPE/三角 mask、SDPA/eager attention、multinomial/top-k/top-p 所需基础 op。
4. 默认禁止静默 MPS→CPU fallback；任何 fallback 必须进入证据并重新测峰值。
5. 只解析固定 config/remote-code allowlist，不读取完整权重。
6. 子进程退出后验证内存基线回落。

T1 通过只代表可以进入单模型加载，不代表模型可以生成。

## 五、codec 加载边界

### 5.1 已核实调用关系

固定 VoiceGenerator `processing_moss_tts.py` 中：

1. `MossTTSDelayProcessor.from_pretrained()` 默认把 `codec_path` 解析为 `OpenMOSS-Team/MOSS-Audio-Tokenizer`；
2. 它立即调用 `AutoModel.from_pretrained(audio_tokenizer_name_or_path)`；
3. 无参考音频的 generation 输入只需要 tokenizer/config，不需要 Audio Tokenizer encoder；
4. `model.generate()` 返回 `(start_length, generation_ids)`，其中 `generation_ids` 包含 1 个 text channel 与 16 个 audio channels；
5. `_parse_audio_codes()` 先执行 de-delay、去 pad、分段，然后才调用 `decode_audio_codes()`；
6. `decode_audio_codes()` 最终调用 Audio Tokenizer `decode(..., chunk_duration=8)`。

### 5.2 可分阶段的工程推断

可尝试的最窄边界是：

```text
固定 tokenizer + config + processor 逻辑（audio_tokenizer=None）
→ VoiceGenerator.generate()
→ 保存 start_length + packed generation_ids / de-delayed codes + schema + hash
→ 退出 VoiceGenerator 进程
→ 等待内存回落
→ 新 codec 进程加载固定 Audio Tokenizer
→ decode(codes, chunk_duration=8)
```

中间数据很小：若按最大 4096 step、17 channel、int64 计算，packed tensor 约 `544 KiB`；短样音会更小。它没有必要为了节省内存而使用有损压缩。

### 5.3 必须防止的错误实现

- 不能先 `AutoProcessor.from_pretrained()` 再把 `audio_tokenizer=None`；codec 已经加载过，峰值已发生。
- 不能在同一 Python 进程里依赖 `del`、`gc.collect()` 或 `torch.mps.empty_cache()` 就宣称“完全释放”；计划40要求进程退出作为硬边界。
- 不能调用官方 `processor.decode()` 后再保存 token；该方法已经执行 codec decode。
- 不能复制整份 remote code 后无版本差异审计；应使用固定 snapshot、allowlist 和最窄 parse-only adapter。
- 不能把 private method 的当前行为当长期公共协议；中间 schema 必须带源 revision、`n_vq`、pad code、shape、dtype、start length 和 digest。
- 不能把 Audio Tokenizer v2 替换进来；VoiceGenerator 固定配置是 24 kHz／16 VQ，v2 是另一条 48 kHz stereo 路线，未证明兼容。

## 六、量化与替代运行时来源

### 6.1 官方可用来源

| 来源 | 官方性 | 当前用途 | 本计划结论 |
| --- | --- | --- | --- |
| VoiceGenerator BF16 safetensors | OpenMOSS 官方 | PyTorch 原始权重 | T2 首选基线 |
| Audio Tokenizer F32 safetensors | OpenMOSS 官方 | PyTorch codec | T2/T4 精确基线 |
| Audio Tokenizer ONNX | OpenMOSS 官方 | CPU/GPU/TensorRT codec | T4 可选 decoder-only 路线 |
| OpenMOSS/llama.cpp first-class | OpenMOSS 官方源码 | GGUF/原始 codes/独立 decode 参考 | 可做后备尖峰，不能原样宣称 VoiceGenerator 可用 |
| MOSS-TTS-GGUF | OpenMOSS 官方 | MOSS-TTS 8B backbone | 不是 VoiceGenerator 权重，不可替换 |

### 6.2 本轮发现的社区来源

| 来源 | 观察事实 | 风险裁决 |
| --- | --- | --- |
| [`ilintar/moss-voicegen-gguf`](https://huggingface.co/ilintar/moss-voicegen-gguf) | 个人账号；基于固定官方 VoiceGenerator/codec；两个 GGUF 合计约 7.3 GB；模型卡标注主体为 BF16/F32，并非低比特 VoiceGenerator | 不是官方量化，不用于首轮 T1–T4；若官方路径失败，只能经新供应链审计、源码审计和 parity 后另行裁决 |
| [`appautomaton/openmoss-audio-tokenizer-mlx`](https://huggingface.co/appautomaton/openmoss-audio-tokenizer-mlx) | 社区 MLX 8-bit codec，artifact 约 2.00 GB | 非官方；无本项目 VoiceGenerator 端到端 parity 与音质证据，不直接采用 |
| [`mlx-community/MOSS-Audio-Tokenizer-MLX-8bit`](https://huggingface.co/mlx-community/MOSS-Audio-Tokenizer-MLX-8bit) | 明确标注为上项的社区镜像；权重 SHA 与上项相同 | 镜像不增加独立证据，不能当作 OpenMOSS 官方发布 |

Hugging Face 的“Quantizations”模型树只表示仓库作者声明了 base-model 关系，不代表 OpenMOSS 审核、官方质量认证或本机安全认证。

### 6.3 量化决策

计划40当前优化顺序应保持不变：

1. 官方 BF16 VoiceGenerator，分阶段；
2. 官方 F32／官方 ONNX codec，分阶段；
3. 只有官方精度路径不能达到内存门禁时，才研究从固定官方权重本地产生的量化候选；
4. 量化必须保存转换代码 commit、输入/输出 SHA-256、tensor inventory、校准方式和与官方精度音频的盲听/结构 parity；
5. 不把社区 GGUF/MLX 下载作为 T1–T4 的隐含捷径。

## 七、T1–T4 明确建议与退出条件

### `VG40-T1`：依赖与空载设备探针

建议：

- 使用一次性 macOS/arm64 环境，基线候选为 Apple 当前稳定 PyTorch，而不是官方 CUDA extra；
- 固定 Python、PyTorch、Transformers、safetensors、torchaudio 与 remote-code revision；
- 执行 MPS availability、BF16 和模型所需基础 op 探针；
- 记录是否发生 fallback、MPS allocator、进程 RSS/phys_footprint、退出回落；
- 不读取 `model.safetensors` 或 codec shards。

退出：

- `PASS`：MPS/BF16 基础闭包通过、无静默 fallback、退出回收正常；
- `HOLD`：依赖组合无法同时满足 fixed remote code；
- `BLOCKED_MPS`：关键 op 或 BF16 不支持。此时不得静默改 FP32 MPS，应回到计划变更门禁。

### `VG40-T2`：两个单模型分别只加载

建议阶段 A：

- 不调用 `AutoProcessor.from_pretrained()`；
- 只加载 VoiceGenerator fixed BF16 权重和最小 tokenizer/config；
- 使用 `low_cpu_mem_usage`/safetensors mmap 候选前后分别测量，不能只测最终 RSS；
- 只加载不生成，然后退出进程并等 60 秒。

建议阶段 B：

- 新进程只加载官方 Audio Tokenizer F32；
- 不加载 VoiceGenerator；
- 再评估官方 ONNX decoder-only 是否比 PyTorch codec 峰值更低；
- 不下载/加载 ONNX encoder。

退出：任一单模型触发 `<4 GiB` 系统余量、critical pressure、超额 swap 或回收失败，立即停止该拓扑，不进入 T3。

### `VG40-T3`：最短真实 token 生成

建议：

- 使用固定中性描述和 3–5 秒短句；
- processor 只保留 tokenizer/config，`audio_tokenizer=None`；
- 使用官方推荐的四个 audio sampling 参数；
- 先把 `max_new_tokens` 设为满足短句且有硬上限的值，不直接用 4096 做第一条；
- 只产出带 schema/hash 的 packed token；本阶段不加载 codec；
- 保存实际 `start_length`、shape、dtype、`n_vq=16`、结束标记与自然停止原因；
- VoiceGenerator 进程退出并确认内存回落后才算成功。

退出：token 缺失自然结束、出现非法 code/pad、MPS 数值异常、fallback 引发双份内存或超过安全门禁时停止。

### `VG40-T4`：独立 codec 解码与 parity

建议：

1. 在 VoiceGenerator 进程完全退出后启动新 codec 进程；
2. 校验中间文件 revision、schema、digest、shape、code range 和 `n_vq`；
3. 使用官方 de-delay/segment 语义转换为 codec 输入；
4. 首选官方 F32 codec 的 `decode(..., chunk_duration=8)`；
5. 若内存/速度不合格，再比较官方 ONNX decoder-only；
6. 记录两个重模型驻留区间，要求交集为 0；
7. 对 waveform 做采样率、时长、NaN、静音、削波、DC offset 和听检；
8. 在可用环境中补一次官方组合路径或官方可信平台的同 seed 对照，验证 parse-only adapter 没有改变 de-delay、trim 和分段语义。

退出：

- `PASS_CANDIDATE`：独立 decode 成功、内存安全、波形有效、结构 parity 通过；
- `HOLD_PARITY`：波形有效但没有官方组合对照；
- `BLOCKED_CODEC_MEMORY`：codec 单阶段仍突破门禁；
- `BLOCKED_SEMANTICS`：parse-only 输出与官方语义不一致。

## 八、仍待验证清单

以下问题本轮没有、也不能通过只读审计回答：

1. 当前 M4 的实际 macOS/PyTorch 组合是否完整支持 VoiceGenerator MPS/BF16；
2. BF16 safetensors 加载到 MPS 时的真实 CPU staging 峰值；
3. 生成期间的 MPS allocator、KV cache、logits 和采样峰值；
4. `MossTTSDelayModel.generate()` 是否出现 unsupported-op fallback；
5. Audio Tokenizer 在 MPS 上能否运行，或 CPU/ONNX decoder 哪个峰值更低；
6. parse-only adapter 与官方 `processor.decode()` 的逐 token/de-delay/trim parity；
7. 一次短样音的实际耗时和三次冷运行稳定性；
8. 子进程退出后 10/30/60 秒 phys_footprint 与系统可用内存回落；
9. 官方 BF16 路径输出的主观音质和人物指令遵循；
10. 量化是否必要，以及量化后的音质损失。

这些项目分别由 T1–T5 的真实证据裁决。本文不把它们提前标成通过。

## 九、给主代理的集成建议

1. 保留计划40的优化顺序，但把第一条具体化为“**VoiceGenerator-only MPS/BF16 进程**”，不要调用官方 AutoProcessor 完整加载路径。
2. T2 先分别证明 `VG-only` 和 `codec-only`；任何单体失败都不值得进入组合尝试。
3. T3/T4 采用进程级硬分隔，中间文件保存 packed token 或 de-delayed codes，不保存 Python pickle。
4. 初始 codec 基线用官方 F32/PyTorch；官方 ONNX decoder-only作为对照，不把它误称 MPS。
5. 官方 first-class llama.cpp 只作为结构与 parity 参考；在 16/32 VQ 和 instruction prompt 修复、测试完成前不要替换主路线。
6. 不下载社区 GGUF/MLX；若后续进入量化波次，先修订计划并单独做供应链、许可证、转换和音质裁决。
7. `VG40-SPIKE` 下载清单应只包含本阶段必需文件。若先走 PyTorch：VoiceGenerator 完整 fixed snapshot + Audio Tokenizer fixed snapshot；若单独验证 ONNX decoder：只取 `decoder.onnx` 与 `decoder.data`，不取 encoder。
8. 最终证据同时记录四类身份：MOSS-TTS source commit、VoiceGenerator model revision、Audio Tokenizer model revision、实际 remote-code hashes。

## 十、自查

- [x] 只使用官方 OpenMOSS/Hugging Face/Apple 一手资料判定正式能力。
- [x] 社区模型仅用于确认“是否存在”，没有作为官方事实或可用结论。
- [x] revision、权重大小、LFS SHA-256、source SHA-256 均固定。
- [x] 区分了模型仓库 revision、GitHub source commit 与 Audio Tokenizer submodule commit。
- [x] 区分了已核实事实、工程推断和仍待验证项。
- [x] 没有把 MPS 平台支持写成 MOSS-VoiceGenerator 已支持。
- [x] 没有把官方 first-class llama.cpp 写成 VoiceGenerator 即插即用。
- [x] 没有下载权重、安装依赖、运行模型或操作长期环境。
- [x] 给出了 T1–T4 的明确执行与停止条件。

只读复核最终结论：**允许按计划进入 T1/T2；禁止运行官方 CPU/FP32 组合路径；T3/T4 的分阶段方向有官方结构证据支持，但必须通过真实 MPS、内存与 parity 门禁。**
