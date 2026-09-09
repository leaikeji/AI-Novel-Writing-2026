# Qwen3-TTS macOS 本地运行时

本目录只负责 Mac 原生 MLX 进程，不改 QwenPaw 上游，也不把 MLX 装入 Linux 容器。

```bash
python3.12 -m venv .venv-qwen-tts
.venv-qwen-tts/bin/pip install -r scripts/qwen_tts/requirements-macos.txt
QWEN_TTS_LOCAL_TOKEN_FILE='/Users/liujia/Library/Application Support/AI小说世界2026/qwen-tts/local-token' \
QWEN_TTS_LOCAL_BIND=0.0.0.0 \
PYTHONPATH=. .venv-qwen-tts/bin/python -m tts_runtime
```

QwenPaw 侧使用相同的 `QWEN_TTS_LOCAL_TOKEN`，默认访问
`http://host.docker.internal:8766`。非回环地址启动时令牌为必填，HTTP access log
默认关闭。

可选的本地模型目录变量：

- `QWEN_TTS_CUSTOM_VOICE_MODEL_PATH`
- `QWEN_TTS_BASE_MODEL_PATH`
- `QWEN_TTS_VOICE_DESIGN_MODEL_PATH`

未设置时，`mlx-audio` 会按代码中冻结的仓库与 revision 下载。三种模型只允许按需
串行装载；16 GiB 机器不应同时常驻。

本机 2026-09-08 已验证的持久部署位于：

- 运行环境：`/Users/liujia/Library/Application Support/AI小说世界2026/qwen-tts/runtime-venv`
- 模型根：`/Users/liujia/Library/Application Support/AI小说世界2026/qwen-tts/models`
- 共享令牌：`/Users/liujia/Library/Application Support/AI小说世界2026/qwen-tts/local-token`（`0600`，内容不得输出或提交）

从仓库根启动时，显式设置三个模型路径；若监听 `0.0.0.0` 供容器访问，还必须设置
随机长令牌文件：

```bash
QWEN_TTS_CUSTOM_VOICE_MODEL_PATH='/Users/liujia/Library/Application Support/AI小说世界2026/qwen-tts/models/customvoice-8bit-modelscope' \
QWEN_TTS_BASE_MODEL_PATH='/Users/liujia/Library/Application Support/AI小说世界2026/qwen-tts/models/base-8bit-modelscope' \
QWEN_TTS_VOICE_DESIGN_MODEL_PATH='/Users/liujia/Library/Application Support/AI小说世界2026/qwen-tts/models/voice-design-bf16-modelscope' \
QWEN_TTS_LOCAL_TOKEN_FILE='/Users/liujia/Library/Application Support/AI小说世界2026/qwen-tts/local-token' \
QWEN_TTS_LOCAL_BIND=0.0.0.0 \
PYTHONPATH=. \
'/Users/liujia/Library/Application Support/AI小说世界2026/qwen-tts/runtime-venv/bin/python' -m tts_runtime
```

Q0 本机技术门已通过：三个角色均在 16 GiB Apple Silicon 宿主逐个完成真实中文
生成且全程 0 swap，CustomVoice 连续热路径 RTF 为 0.65–0.71。完整制品哈希、内存、
性能和样音记录见 `audit/qwen-tts/Q0-本机MLX可行性记录-20260908.md`。Q0 通过不等于
整体发布通过；云端真实 smoke、两端最小章、切换与恢复门完成前仍不得清理旧 TTS 链。
