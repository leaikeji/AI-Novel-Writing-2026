# T1-DEP 回退与卸载清单

## 安全回退

1. 保持 `COMPOSE_PROFILES` 为空且不传 `--profile tts`：默认 Compose 只有 QwenPaw，TTS
   Sidecar 不构建、不创建、不启动。
2. 当前 `production-runtime` 因 T1-B 三个精确文件缺失而 fail-closed；不得把
   `dependency-runtime` 标签改成生产服务，也不得用 T0 原型 server 冒充。
3. 如果后续 production target、握手、镜像 registry digest 或模型 hash 不一致，保持 TTS
   capability off；不切回 PawApp 进程内 Nano 或宿主 macOS worker。
4. 本工作包没有替换 QwenPaw 基础镜像、核心源码、路由、数据库或当前运行容器。回退不需要
   修改上游核心，也不影响原生聊天。

## 完整卸载边界

- 可以在确认无任务后停止并移除未来 `tts-sidecar` 容器和私网；不要停止/删除 QwenPaw 或
  PostgreSQL 容器/卷。
- 本地候选镜像只能在确认没有容器引用后删除；registry 镜像按发布治理处理。
- `ai-novel-2026-novel-media` 和 `ai-novel-2026-moss-models` 是持久数据卷，**完整卸载默认保留**。
  删除任一卷都需要用户明确授权、精确目标、备份和恢复验证；不得使用带 `--volumes` 的宽泛
  Compose down。
- `novel-media` 只归 PawApp 媒体生命周期所有，`moss-models` 的 RW 初始化只归模型生命周期
  Owner；Sidecar 永远只读模型卷，且永远不得挂载小说媒体、数据库或 QwenPaw 卷。
- token secret 是短期外部文件。停用后由部署 Owner 精确轮换/删除该 `.secret` 文件；不得记录
  token 值或把它迁入 `.env`、URL、Compose environment、日志或 Git。

## 当前工作包没有执行的动作

没有运行 `docker compose up/down`，没有重建或重启当前 QwenPaw，没有创建 TTS volume/network，
没有下载/加载模型，也没有删除任何镜像、卷、媒体或用户内容。
