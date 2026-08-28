# T1-DEP：Linux/arm64 Sidecar 依赖与 Compose 接入证据

状态：**T1-DEP 技术验收通过；`production-runtime` 明确等待 T1-B，任何 TTS 业务健康、API、任务、
媒体发布或用户可见能力仍为 NO-GO。**

工作包：`T1-DEP`（SER）；唯一写 Owner 持有 `LOCK-DEPENDENCIES`。执行日期：2026-08-26。

## 1. 结果

- 新增自包含的 `docker/tts-sidecar/` 依赖层：固定 Linux/arm64 Python 3.11.16、完整 hash-locked
  wheels、FFmpeg/FFprobe 9.0.1 窄 LGPL、固定 libgomp、模型/源码锁、NOTICE、运行时 verifier 与
  fail-closed inert entrypoint。镜像不含模型、MOSS source、小说媒体、私人参考音频或业务 server。
- 生产模型锁只包含获准的三个组件，并从 T0 原锁逐字段移植 13 个 source、10 个 Nano ONNX、
  6 个 codec ONNX artifact。每项都有相对 path、冻结 revision URL、size、hash 与 hash algorithm；
  canonical inventory SHA-256 为 `d0f173db…b416d`，与 T0 三组件逐字段相等断言通过。
- Dockerfile 使用根 build context。当前唯一可验收 target 是 `dependency-runtime`；未来
  `production-runtime` 只精确 COPY T1-B 的 `sidecar_server.py`、`runtime.py`、`model_assets.py`，
  不 COPY 整个 backend。三个文件现在不存在，因此 production target 构建失败是预期门禁。
- 根 Compose 增加显式 `tts` profile、internal 私网、`moss-models` / `novel-media` 持久卷和
  secret-file token 边界。默认 profile 仍只有 QwenPaw；Sidecar 0 host ports、非 root、只读
  rootfs/模型卷、drop ALL、no-new-privileges，并且没有 DB、novel-media 或 QwenPaw 卷。
- 根 PawApp 已有 `httpx==0.28.1`；因此 `pyproject.toml`、`requirements.txt`、
  `requirements-dev.lock` 与 `docker/qwenpaw/Dockerfile` 保持零改动。Torch/ONNX/FFmpeg 重依赖
  只存在于 Sidecar。

## 2. 镜像与 digest

`dependency-runtime` 本地标签为 `ai-novel-world/moss-tts-sidecar:t1-dep-linux-arm64`，当前
manifest-list / RepoDigest 为：

```text
sha256:60780eaf16dafde8d3b379ec16637fd900dad11713180d5884698695ac165be9
```

它不是 T0 的 `56bb12bd…07fe0`：根生产 context、inert entrypoint、provenance labels 和未来精确
production target 改变了镜像字节，因此本证据没有沿用旧 digest 冒充同一镜像。当前 digest 是
Docker Desktop BuildKit 对单一 linux/arm64 image 加 provenance attestation 生成的本地 manifest
list；正式发布前仍必须 push registry 后重新解析并冻结 registry digest。

先前 `1a89a24b…56a663` 已明确 superseded：它只有 repo/revision/aggregate tree 元数据，不能给
T1-B 提供逐文件下载 allowlist。当前新 digest 来自 29 项锁与构建期严格 verifier，不能混用。

## 3. 实际验证

- 根 `.venv` `pip check`：通过；根依赖零新增。
- Compose 默认与 `--profile tts` 两种 `config --quiet`：均通过；默认 services 只有 `qwenpaw`。
- dependency image build：冷依赖层 436.37 秒通过；unconditional T1-B fail-closed 入口的全缓存
  重建为 3.02 秒，29 项 allowlist P0 修复后的最终全缓存重建为 3.00 秒。第一次 root-context
  构建的 PyPI read timeout 和此前设计切换产生的 Ctrl-C 均保留在 `validation.json`，没有改写成成功。
- 镜像 architecture/user：`linux/arm64`、`65532:65532`；大小 284,667,658 bytes。
- 容器内 `pip check`、8 个关键包 import/version、FFmpeg/FFprobe version/buildconf、二进制、
  LGPL 文件和 libgomp SHA-256：全部通过。模型锁 verifier 同时核验固定三组件/29 项、路径、URL
  revision、size 汇总、hash 算法/格式、component 内 path 唯一、inventory 与 source/model tree hash。
- 默认 entrypoint：exit 78，`status=inert`，明确 `health_endpoint_available=false`、
  `business_runtime_available=false`。
- 当前 QwenPaw 只读复核：容器 ID、started-at 与施工前一致，running/healthy/OOM=false，HTTP 200；
  未执行 compose up/down，0 TTS 容器，且未创建 TTS volume/network。
- 项目既有 `scripts/package_plugin.py`：通过；镜像、模型和媒体不进入 PawApp plugin package。

## 4. 当前边界与交接

T1-B 只能创建 Dockerfile 已冻结的三个 `backend/narration/` 文件并完成真实窄协议 runtime；不得
把 prototype path、整个 backend、模型、媒体或 `.venv` COPY 入镜像。T1-B 完成后应构建 Compose
已预声明的 `t1-runtime-linux-arm64-candidate`，验证私网握手/业务健康，再产生新的实际 digest；
在那之前不得启动 `tts` profile。

模型生命周期 Owner 后续可通过单独 one-off installer 以 RW 初始化 `moss-models`；依赖镜像已
预建 owner `65532:65532`、mode `0750` 的空根。正式 Sidecar 只读挂载该卷。`novel-media` 只给
PawApp 的受控项目媒体路径，任何删除都需要用户授权、备份和恢复验证。

剩余非阻断 P1：FFmpeg 源码 PGP 链、最终许可证/registry 再分发归档和模型权重发布权利仍未完成。
这些不阻断本地依赖层接入，但阻断对外发布。真实 Nano、业务健康、Adapter、模型生命周期、媒体、
数据库/API/UI 均未实施，必须由后续工作包单独验收。
