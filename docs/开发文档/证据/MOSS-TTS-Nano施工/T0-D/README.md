# T0-D VoiceGenerator M4 可行性审计

> 状态：**元数据/代码路径尖刺候选完成；真实模型基准仍为 HOLD，当前 capability 建议 `hide`**<br>
> 工作包：T0-D / `tts_t0d_voicegen_spike`<br>
> 执行日期：2026-08-26（Asia/Shanghai）<br>
> Git 基线：`9b5be4a`；开始和收口时工作树都不洁净，范围外改动均保留且未触碰。

## 1. 结论

MOSS-VoiceGenerator 的官方资料能证明“文字描述生成音色”这一模型能力，但不能证明它在本项目 Apple M4 / 16 GB 上已可用。本轮的可审计结论是：

- **当前产品 capability：`hide`。** 不展示“文字生成音色”按钮，不把它宣称为施工后必然可用的功能。
- **VoiceGenerator no-go 不等于已有可用回退。** 用户自有且权利/质量均通过的参考录音、或已锁定且权利/质量均通过的通用预设只是未来目标来源；当前两类产品资产均为 0，多角色朗读入口仍隐藏，正式句段合成的技术执行候选才是 Nano。
- **后续可重新裁决。** 主代理持有模型锁、完成 full codec 锁定、隔离依赖、真实 MPS/CPU 运行、峰值内存、候选听检和 Nano 二次克隆后，T0-GATE 才能把它改为 `visible/experimental`。

`metrics.json` 是严格符合 `moss-tts-benchmark-result/1.0` 的 `blocked` 记录，不是伪造的通过记录。其中真实下载、模型导入、加载、候选生成、Nano 克隆和人工听检均为 0。

## 2. 已核实事实

1. 官方模型卡说明 VoiceGenerator 以自由文字描述和待合成文本为输入，可以直接设计 timbre/style/emotion，不需要参考音频。本轮只读固定的 [VoiceGenerator 模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/blob/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/README.md) 和 [MOSS-TTS 官方源文档](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/docs/moss_voice_generator_model_card.md)。
2. T0-A 锁定 VoiceGenerator revision `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`：选定仓库产物 `4,244,233,010` bytes，其中 `model.safetensors` 为 `4,228,278,872` bytes，官方 LFS SHA-256 为 `dbe345257ff9f6cc84195bed830a268b39d5e0b728ff3ba90e715150a49b16d4`。本 T0-D 未下载该文件，因此没有伪写“本地验 hash”。
3. 固定 [`processing_moss_tts.py`](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/blob/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/processing_moss_tts.py) 的 `from_pretrained` 默认把 `codec_path` 解析为 full `OpenMOSS-Team/MOSS-Audio-Tokenizer`，不是约 90 MB 的 Nano ONNX codec。
4. 2026-08-26 读取官方 [MOSS-Audio-Tokenizer 仓库元数据](https://huggingface.co/api/models/OpenMOSS-Team/MOSS-Audio-Tokenizer?blobs=true)：当时 revision 为 `3cd226ba2947efa357ef453bcad111b6eafba782`，总计 `7,101,115,998` bytes，两个权重分片合计 `7,098,461,728` bytes。该 revision 尚未进入 T0-A 锁，属于“已观测、未冻结”。
5. 固定官方示例的设备分支是 `cuda if available else cpu`，CUDA 使用 BF16，CPU 使用 FP32；示例没有 MPS 分支。“本机 Torch 报告 MPS available”只证明 PyTorch/硬件基础，不证明 VoiceGenerator 的自定义模型、codec、采样和操作符都支持 MPS。
6. 固定 [VoiceGenerator config](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/blob/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/config.json) 记录 Qwen3-1.7B 背骨、BF16、24 kHz 和 `transformers_version=4.57.1`；而官方 [MOSS-TTS pyproject](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/pyproject.toml) 的运行说明指向 `torch==2.9.1+cu128` / `torchaudio==2.9.1+cu128` / `transformers==5.0.0`。它与 Nano 隔离环境的 Torch 2.7.0 / Transformers 4.57.1 不能在未验证时合并。

## 3. 技术推断与项目门禁

| 项目 | 计算 | 性质 |
| --- | ---: | --- |
| VoiceGenerator 选定产物 + full codec 仓库快照 | `11,345,349,008` bytes / `10.566180` GiB | 元数据求和，不是峰值内存 |
| VoiceGenerator + codec 权重文件 | `11,326,740,600` bytes / 约 `10.548849` GiB | 权重文件体积，不含运行开销 |
| 官方 CPU FP32 分支下的静态权重下界估算 | `15,555,019,472` bytes / `14.486741` GiB | **技术推断**：将 BF16 VoiceGenerator 文件按 FP32 约翻倍，codec 保持 FP32 |
| 16 GiB 物理内存下估算剩余 | `1,624,849,712` bytes / `1.513259` GiB | 未计活性、KV cache、allocator、Python、OS 和 QwenPaw |

因此，“CPU fallback 存在”不等于“CPU 在 16 GB 上可接受”。阶段 0 先使用保守的 **4 GiB 实测安全余量** 作为项目候选门禁，该值是项目建议，不是官方声明；最终由 T0-GATE 依据真实峰值 RSS、MPS 内存、swap/内存压力和 QwenPaw 非回归冻结。当前 CPU 静态估算已无法满足此门禁。

## 4. 本轮实际产物

- `scripts/tts/benchmark_voice_generator.py`：Python 3.11 标准库基准骨架；先复核 T0-I 全部文本/case/coverage hash，再复核 T0-A 锁与 T0-D baseline；默认只输出 `blocked`。
- `prototypes/moss-tts-nano/voice-generator/metadata-baseline.json`：官方元数据、代码路径结论、资源预算、实验性项目门禁和两个项目自有通用音色描述。
- `prototypes/moss-tts-nano/voice-generator/test_benchmark_voice_generator.py`：6 项限定单测。
- `prototypes/moss-tts-nano/voice-generator/README.md`：安全 CLI 和源文本扫描边界。
- `metrics.json`：2 个项目自有 fixture case 均为 `blocked`，不含音频、私人路径、用户正文或权重。
- `clone-retention.md`：VoiceGenerator 完全退出后才启动 Nano 二次克隆的串行协议。

## 5. 验证记录

| 命令/检查 | 退出码 | 结果 |
| --- | ---: | --- |
| `benchmark_voice_generator.py --help` | 0 | 稳定 CLI 可用 |
| 专项文档冻结的 `BENCH-VOICEGEN` 命令 | 0 | 生成 1 run / 2 blocked cases；建议 `hide` |
| `python -m unittest -v .../test_benchmark_voice_generator.py` | 0 | 6 passed / 0 failed / 0 skipped |
| `render_benchmark_report.py metrics.json --stdout-format json` | 0 | 严格 schema 通过；`blocked=1 run/2 cases`；所有性能和听检计数均为 0 |
| `python -m json.tool` 检查 baseline/metrics | 0 | 2 JSON 有效 |
| `py_compile` 检查 driver/test | 0 | 2 modules 通过，临时 pycache 不进仓 |
| 坏授权文本 hash 且同时传入不存在的 source dir | 预期 2 | 先拒绝 `hash drift`，未访问 source，未产生 metrics |
| 已有 metrics 且没有 `--replace-existing` | 预期 2 | 原文件 bytes 不变 |
| `git diff --check` / 新文件 no-index whitespace 检查 | 0 / 预期 diff 1 | 无 whitespace error |
| 真实 VoiceGenerator/Nano/音频/听检 | 未执行 | 下载 0、导入 0、加载 0、音频 0、听检 0 |

运行环境由实际 metrics 记录：Apple M4，macOS 26.5.2，arm64，16 GiB，prototype 隔离 Python 3.11.16。

## 6. 产物 SHA-256

```text
3f1312ae123e2409a612af1e9d4107d59af2a75a7b69b2be7e13f0e968c2ab58  scripts/tts/benchmark_voice_generator.py
f45f2736196407d07055d296cfffd8032e7ffad1e79cb59a770885299a6032dd  prototypes/moss-tts-nano/voice-generator/metadata-baseline.json
6e852fb9af2c39f70a7f956f9d14894afeeed14bb24a45495a6cd71ee221cf58  prototypes/moss-tts-nano/voice-generator/test_benchmark_voice_generator.py
006489b3783c398c00455d058e45c5ec9e75f0b11278704961ab6f506d09ca68  docs/开发文档/证据/MOSS-TTS-Nano施工/T0-D/metrics.json
```

README/prototype README/`clone-retention.md` 不写自身 hash，避免自引用循环。上述 hash 在收口验证后再复核；如主代理集成修订脚本，应同步更新本节。

## 7. 主代理才能执行的最小真实 probe

1. 等待当前 Nano 工作包释放 `LOCK-NANO`；主代理串行授予 `LOCK-MODEL-ASSETS` + `LOCK-VOICEGEN`。
2. 把 full codec revision 及两个权重分片 hash 升级为隔离锁，下载到精确的仓库外目录，本地重算所有 SHA-256。
3. 以独立 Python 3.11 环境先跑官方 CPU/FP32 最小单 case，设置内存压力与有界超时保护；不把 CUDA 结果当 M4 结果。
4. 如 CPU 在加载阶段已触发换页/压力门禁，立即退出；只在可恢复的非产品适配器中尝试明确 `mps` 路径，并记录不支持的第一个操作符，不在环境内 monkey patch 官方代码。
5. 只生成 `clone-retention.md` 定义的 2 个描述 × 2 个 seed，用 `inspect_audio.py` 检查并记录峰值内存/首包/RTF，然后完全退出 VoiceGenerator。
6. 主代理释放 `LOCK-VOICEGEN`、确认内存回收后再授予 `LOCK-NANO`，串行执行同文本/留出文本克隆和人工听检。
7. 新建独立真实 result，不覆盖本元数据 run；只有全部门禁通过才向 T0-GATE 申请 `visible/experimental`。

## 8. 风险、回退与接线

- 最大风险是把仓库大小当峰值内存、把 Torch MPS available 当模型支持、把元数据 SHA 当本地验 hash，或把“能生一段 WAV”当“Nano 二次克隆保持度通过”。本证据显式分离了这四类结论。
- 本工作包没有修改项目依赖、PawApp、QwenPaw、数据库或用户媒体。回退只需移除“本轮实际产物”列出的 T0-D 文件，不得清理共享 prototype 环境或其他工作包。
- T0-E 可以消费本结论将 24 槽位标记为“VoiceGenerator 来源尚不可用”，但不能把未生成候选填入音色包。
- T0-GATE 应冻结 `voice_generator_visible=false`，并保留后续独立真实 probe 重新打开能力的明确条件。
