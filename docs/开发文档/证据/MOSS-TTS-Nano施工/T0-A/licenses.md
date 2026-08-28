# T0-A 许可证与依赖审查

> 状态：阶段 0 候选基线（非生产法务批准）
> 抓取日期：2026-08-26（Asia/Shanghai）
> 原则：只使用官方 GitHub、Hugging Face、PyPI/npm 发布元数据与 FFmpeg 官网；固定值以 `model-sources.lock.json` 为准。

## 模型、源码与转码器

| 对象 | 固定 revision / 版本 | 官方许可证证据 | 覆盖判断 | T0-A 结论 |
|---|---|---|---|---|
| MOSS-TTS-Nano 代码 | `cc7bdf19c7639c0870dab22045a33b442760f6be` | [GitHub LICENSE](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/cc7bdf19c7639c0870dab22045a33b442760f6be/LICENSE) | 代码，Apache-2.0 | 可进入隔离原型，保留 NOTICE/归属义务。 |
| MOSS-TTS 代码（VoiceGenerator 依赖参考） | `58b20a0d5fcc6766658d50967a90a9d890009a46` | [GitHub LICENSE](https://github.com/OpenMOSS/MOSS-TTS/blob/58b20a0d5fcc6766658d50967a90a9d890009a46/LICENSE) | 代码，Apache-2.0 | 仅作 T0-D 官方实现与依赖参考。 |
| MOSS-TTS-Nano Reader | `c3b2333b88e0f062ca49d403540a169609354d93` | [官方仓库](https://github.com/OpenMOSS/MOSS-TTS-Nano-Reader/tree/c3b2333b88e0f062ca49d403540a169609354d93) 无根 LICENSE，GitHub 许可证字段为空 | 不明 | **NOASSERTION：只读参考，禁止复制、打包或再分发源码。** 其 vendored ORT 头部标识 1.24.3/MIT，不会为 Reader 其余代码自动授权。 |
| Nano 100M PyTorch | `44502f80dbf9743528fa921cc544d662c685ebec` | [官方模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M/blob/44502f80dbf9743528fa921cc544d662c685ebec/README.md) 元数据 `apache-2.0` | 仓库代码和权重发布元数据；未发现独立权重 EULA | 可做技术评估；对外分发权重前仍需法务确认实际权利链。 |
| Audio Tokenizer Nano PyTorch | `6aa02b01e445cc585582cf0ba480bc3ea6c8dd68` | [官方模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano/blob/6aa02b01e445cc585582cf0ba480bc3ea6c8dd68/README.md) 元数据 `apache-2.0` | 同上 | 同上。 |
| Nano 100M ONNX | `f52645cb467506d8e18e746ddd59482685b74e58` | [官方模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX/blob/f52645cb467506d8e18e746ddd59482685b74e58/README.md) 元数据 `apache-2.0` | 同上 | 主 CPU/浏览器候选；对外分发前仍需法务门禁。 |
| Audio Tokenizer Nano ONNX | `ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae` | [官方模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX/blob/ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae/README.md) 元数据 `apache-2.0` | 同上 | 主 ONNX 音频解码候选。 |
| MOSS-VoiceGenerator | `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4` | [官方模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/blob/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/README.md) 元数据 `apache-2.0` | 同上；选定产物约 4.24 GB | 仅 T0-D 隔离尖刺；未下载、未运行。 |
| FFmpeg 源码与窄构建 | `9.0.1` / commit `bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa` / source SHA-256 `cf38e0e…f635` | [官方 legal](https://ffmpeg.org/legal.html) 与源码内 `COPYING.LGPLv2.1`/`LICENSE.md` | macOS 与 Linux/arm64 Sidecar 最终 `ffmpeg -buildconf` 均为窄 LGPL-2.1-or-later 运行时；明确关闭 GPL/version3/nonfree/网络与自动外部依赖 | macOS arm64 二进制/许可证/参数已固定；T0-B 另将 Linux/arm64 产物锁入固定 Sidecar 镜像。源码 PGP 签名链、再分发归档与跨浏览器矩阵仍是生产门禁。 |

模型卡的 `license: apache-2.0` 是官方发布元数据，本证据不把它扩大解释为对训练数据、输出人格权、声音权或所有下游商业场景的保证。项目仍只能处理用户自有、获授权或公开允许的文本与音频。

## 隔离运行时依赖

- Python 直接候选锁：`torch==2.7.0` / `torchaudio==2.7.0`（PyTorch BSD 系列）、`transformers==4.57.1` 与 `huggingface-hub==0.36.0`（Apache-2.0）、`onnxruntime==1.24.3`（MIT）、`sentencepiece==0.2.2`（Apache-2.0）、`numpy==2.3.3`（BSD-3-Clause）、`soundfile==0.14.0`（BSD-3-Clause；运行时还需核对携带的 libsndfile/LGPL），以及 FastAPI/Uvicorn 服务层候选。精确闭包及 SHA-256 在 `python-requirements.lock`。
- Node 直接候选锁：CodeMirror 6 各包、Monaco 0.56.0、ONNX Runtime Web 1.24.3、jsdom 30.0.1、Vite 6.3.5、Vitest 4.1.11 均为 MIT；TypeScript 5.8.3 为 Apache-2.0。准确传递闭包与 npm integrity 在 `pnpm-lock.yaml`。
- Manifest player 本身不新增播放依赖；CodeMirror/Monaco 是 T0-F 编辑器候选，并非已批准的生产选型。Monaco worker/CSP/单 Blob ES module 打包兼容性待验证。

## 不能跨过的缺口

1. **P1：官方 ONNX `torch-free` 说法与固定代码矛盾。** `onnx_tts_runtime.py` 顶层仍 `import torch`/`torchaudio`，参考音频路径也使用它们；官方 `requirements.txt`/`pyproject.toml` 仍锁 `torch==2.7.0`/`torchaudio==2.7.0`。T0-B 不得先宣称 Python ONNX 路径无 Torch。
2. **P1：WeTextProcessing 在 M4/PyPI 路径不可重建。** `WeTextProcessing==1.2.0` 依赖 `pynini>=2.1.6`，`pynini==2.1.6.post1` 没有 macOS ARM64 wheel。本候选锁明确排除 WeText；如启用 conda-forge/源码构建，必须另立锁与许可证门禁。
3. **P1：VoiceGenerator 依赖矛盾。** Nano 官方锁为 Torch 2.7.0/Transformers 4.57.1，VoiceGenerator 说明指向 Transformers 5.0.0 且 MOSS-TTS 可选运行时指向 CUDA 12.8 的 Torch 2.9.1。Apple M4 上的可行性、内存与速度未验证，不得并入 Nano 主环境。
4. **P1：Reader 无仓库许可证。** 只可观察行为，不可作为可复用代码来源。
5. **P2：预置音色清单不一致。** ONNX manifest 有 18 个内置音色（中 6/英 5/日 7），固定 Python runtime 映射仅 16 项且存在命名差异；T0-E 必须以实际 manifest 做契约验证。
6. **P1：FFmpeg 还不是完整跨浏览器生产分发物。** macOS arm64 窄构建与 Linux/arm64 Sidecar 窄运行时、二进制/镜像 hash 已审计，Chromium 151 的 AAC-LC/M4A 播放已通过；但源码 PGP 链、Safari/Firefox/移动端播放矩阵、许可证归档与再分发义务仍是 T1-DEP/后续 UI 的生产门禁。
7. 本阶段未完成全部传递许可证归档或权重对外分发法务评审；这些都是生产前门禁。
