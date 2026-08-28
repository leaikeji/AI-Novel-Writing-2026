# 阶段 0 隔离依赖

本目录只服务 MOSS-TTS-Nano 阶段 0 原型，不是 PawApp 生产依赖。`python-requirements.in` 是人工冻结的直接依赖输入，仓库上一级的 `python-requirements.lock` 是带 SHA-256 的解析结果；Node 候选由上一级 `package.json` 和 `pnpm-lock.yaml` 冻结。

当前 M4 候选明确关闭 WeTextProcessing：官方 `WeTextProcessing==1.2.0` 依赖 `pynini>=2.1.6`，而 PyPI 的 `pynini==2.1.6.post1` 没有 macOS ARM64 wheel。不得把官方 README 的 conda-forge 方案静默混入项目 Python 环境。后续若批准启用，必须另行冻结 conda/source-build、许可证、离线安装和卸载路径。

`torch==2.7.0` 与 `torchaudio==2.7.0` 仍保留在候选锁中：官方固定 revision 的 ONNX Python 模块顶层会导入它们，因此当前不能把 Python ONNX 路径称为已验证的 torch-free。浏览器 `onnxruntime-web==1.24.3` 与官方 Nano Reader 固定 revision 中的 vendored 运行时版本对齐；Nano Reader 仓库本身没有可核实的根许可证，不能复制或打包其源码。

## 固定音频转码器

阶段 0 不使用机器 `PATH` 中的偶然安装。`model-source-policy.json` 和上一级 `model-sources.lock.json` 固定 FFmpeg 9.0.1 官方源码、SHA-256、LGPL 窄构建参数，以及当前 macOS arm64 二进制和许可证文件的大小/hash。二进制只保存在仓库外 `stage0/tools/runtime/<runtime_layout>`，通过：

```bash
prototypes/moss-tts-nano/.venv/bin/python scripts/tts/collect_dependency_inventory.py \
  --local-tool-runtime-root '/absolute/stage0/tools/runtime'
```

校验后才可调用。构建明确关闭 GPL、nonfree、网络、自动外部依赖探测和非音频组件，只保留 WAV/FLAC/AAC-LC、`ffmpeg`、`ffprobe`、重采样和本地 file/pipe。macOS 产物不复制进 Git，也不能拿到 Linux 容器复用；T1-DEP 应从同一官方源码/hash 在固定容器工具链中执行同一 LGPL 参数（把 `--cc=/usr/bin/clang` 换为镜像内固定编译器），随后为目标架构新增独立 runtime build hash。未完成 Linux 构建与容器门禁前，不得把 Darwin 二进制称为容器产物。
