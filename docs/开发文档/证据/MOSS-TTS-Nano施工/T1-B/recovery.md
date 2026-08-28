# T1-B 恢复与回退证据

## 已由自动化和真实 Nano 共同验证

- 控制 token 与 Worker token 分离；Worker token 只属于当前 lease generation，陈旧 token 不能复用。
- 60 秒短租约可续租；两轮真实 smoke 均完成 5 次续租。主动 release 和 watchdog expiry 均撤销 Worker 权限并卸载模型。
- 返回响应丢失时，caller 只在认证 health 明确证明“同 lease generation 且 inert”时接受已释放；其他情况 poison 并进入 supervisor 恢复。
- backend unload 在有界 daemon teardown 线程中执行；超时则以 75 退出，不让卡死卸载永久占有 Sidecar。
- 活动请求取消以 `REQUEST_CANCELLED` 终止且不发布音频。在已观察 active request 后强制终止专用 Sidecar，客户端非成功退出；重启后 generation 改变，重新 warmup/smoke 成功。
- WAV/FLAC 截断、尾随字节、未完整解码、request/generation/model/protocol 漂移均 fail-closed。

专项测试为 `104/104`；真实主证据为 `runner-real-lease-1.1-transcript.json`，记录初次 generation `9183407905447616316`、恢复 generation `7531935992487800683`、最终两轮均 `unloaded`且 `cleanup.failures=[]`。

## 正式 Sidecar 原位更新

- 替换前先用新镜像、正式模型卷和密钥卷的只读挂载运行单容器探针，获得 `moss-tts-sidecar/1.1` live 响应；探针退出后精确删除。
- 只原位重建同名 `ai-novel-2026-moss-tts-sidecar`，使用 `--no-deps --no-build --force-recreate`，未启动 init/installer，未更改 QwenPaw 或 PostgreSQL。
- 新容器为 `healthy`，镜像 ID `sha256:78a2af56924f5593bc9391b9f288ffef428d3350cd6b859476e8ee29a9bc9422`，两个挂载均 `rw=false`；QwenPaw 容器 ID、启动时间和健康状态未变。
- 已成功退出的 init/installer 容器已删除，命名卷保留；没有使用 `compose down -v`、prune 或通配清理。

## 失败回退

旧容器引用的一个 Docker content digest 已被后台清理，因此无法将旧 1.0 根文件系统生成可执行回退镜像；该失败发生在原位替换之前，未影响容器或卷。当前可执行回退为：

1. 保持 `AI_NOVEL_TTS_RUNTIME_ENABLED=false` 和产品 capability `false`，停止接收新请求。
2. 停止或删除仅 Sidecar 容器，不删除模型、密钥、媒体、QwenPaw 或 PostgreSQL 卷。
3. 使用已固定 Dockerfile/source SHA 重建当前通过真实 runner 的 1.1 镜像，再重放健康、鉴权、租约和恢复门禁。

本阶段不需要为回退而启动第二数据库或保留额外长期容器。
