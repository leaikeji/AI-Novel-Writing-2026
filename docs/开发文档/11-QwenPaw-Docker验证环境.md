# QwenPaw Docker 验证环境

验证日期：2026-08-23（Asia/Shanghai）；统一编排复核更新于 2026-08-31。

状态：**已部署并通过基础运行、回环监听、重启持久性、PawApp、PostgreSQL/pgvector、MOSS-TTS-Nano 与阶段 3–7 首个纵向闭环验证；2026-08-31 已将三个长期容器收敛到默认 Compose 启动链。** QwenPaw 当前 Agent 已完成真实正文候选和结构化情报提案调用。

## 1. 当前可用入口

- Web：<http://127.0.0.1:18088>
- 容器名：`ai-novel-2026-qwenpaw-lab`
- 容器内部端口：`8088`
- Mac 主机映射：`127.0.0.1:18088`
- 重启策略：`unless-stopped`

端口满足本项目规则：保留容器原始端口，主机端口为五位数且首位为 `1`，并且只绑定 Mac 回环地址。

## 2. 固定镜像与运行时

| 项目 | 已验证值 |
| --- | --- |
| QwenPaw 包版本 | `2.1.0` |
| 镜像来源 | `agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/qwenpaw` |
| arm64 平台 manifest digest | `sha256:847fa1b01969492587fcf9b01f28fef97cb4039de92148c08c49486b94b3d912` |
| 多平台顶层 digest | `sha256:1132da56170f49c63aa583dd1ea3b09c19ce1ab76a1983813b8ad2f220771bcd` |
| 平台 | `linux/arm64` |
| 镜像内 Python | `3.11.2` |
| 本地镜像大小 | `924,596,160` bytes，约 925 MB |

**已核实事实**：Docker Hub 的精确镜像拉取在本机网络下长期无有效进展，因此本次使用 QwenPaw 官方 ACR 镜像源。核对结果表明 ACR 与 Docker Hub 的 `v2.1.0` 多平台顶层 digest 相同；本机固定到其中的 arm64 manifest，而不是使用可漂移的 `latest`。

**项目影响**：PawApp 后端代码必须首先兼容真实宿主 Python 3.11.2。开发工具可以使用更高的 Python 3.13 做最高兼容测试，但包元数据、语法和依赖不能只在 3.13 可用。

## 3. 持久卷

| 命名卷 | 容器目录 | 用途 |
| --- | --- | --- |
| `ai-novel-2026-qwenpaw-data` | `/app/working` | QwenPaw 配置、workspace、日志和 Skills 等工作数据 |
| `ai-novel-2026-qwenpaw-secrets` | `/app/working.secret` | Provider 等服务端密钥目录 |
| `ai-novel-2026-qwenpaw-backups` | `/app/working.backups` | QwenPaw 备份目录 |
| `ai-novel-2026-postgres-data` | `/var/lib/postgresql` | PostgreSQL 18.6 权威小说账本与 pgvector 扩展 |

三个卷带有 `ai.novel.world.project=AI小说世界2026` 和各自用途标签。停止或重启容器不会删除这些卷。

这三个 QwenPaw 核心卷由插件安装流程创建，Compose 以 `external` 方式复用；即使误用 `docker compose down --volumes`，Compose 也不会删除它们。PostgreSQL、小说媒体与 TTS 模型等项目卷仍由本项目 Compose 管理，长期环境依然禁止执行带 `--volumes` 的清理命令。

## 4. 已执行验证

| 检查 | 结果 | 证据摘要 |
| --- | --- | --- |
| 容器启动 | 通过 | 状态 `running`，健康检查 `healthy` |
| 首页响应 | 通过 | `GET /` 返回 HTTP `200`，页面标题为 `QwenPaw Console` |
| 回环绑定 | 通过 | Docker 端口为 `127.0.0.1:18088 -> 8088/tcp`；macOS 监听也仅为 `127.0.0.1:18088` |
| 版本一致性 | 通过 | 容器内 Python 元数据返回 `qwenpaw=2.1.0` |
| 持久化 | 通过 | 受控重启前后 `/app/working/config.json` SHA-256 都是 `b60661293f3598812e3e2417e68edf5969e738a975c7e4a55d7b927190bc0856` |
| 重启恢复 | 通过 | 重启后重新达到 `healthy`，首页仍返回 HTTP `200`，回环映射未变化 |
| 初始配置 | 通过 | 首次启动已创建配置与内置 workspace；当前没有默认聊天模型 |

## 5. 安全和范围边界

- QwenPaw 2.1.0 Docker 控制台本身没有登录认证。本验证环境只允许本机可信单用户使用，禁止把端口发布到 `0.0.0.0` 或局域网。
- 当前未录入任何模型 API Key，未替用户选择或配置聊天 Provider。
- 当前已安装小说 PawApp 0.3.0，并创建独立“AI小说作家” Agent；六个小说 Skills 和三个只读小说工具只在该 Agent 中启用，Default 与 QA 中保持关闭。AI 只生成候选与情报提案，正式写入仍由 PawApp 作者确认命令完成。
- “AI小说作家”额外启用项目管理的 `AI_NOVEL_WORLD.md` 系统提示文件，用于自主 Skill 路由；QwenPaw 原生 `AGENTS.md`、`SOUL.md`、`PROFILE.md` 保留。默认首次引导文件已改名归档，避免继续污染小说对话。
- 本机 Docker Desktop 偶发在 QwenPaw 停止后立即复用命名卷时卡住。安装脚本现使用 30 秒优雅停止、确认容器完全退出并等待卷释放，再启动临时安装容器；修改后重复安装已正常完成。
- PostgreSQL 18.6 + pgvector 0.8.6、MOSS-TTS-Nano Sidecar 已启动并健康；VoiceGenerator 由 macOS 原生服务管理；Portkey、Ollama、TEI 和图片服务未启动。
- 后续录入 Provider 密钥时，必须验证浏览器存储、API 响应和日志不回显密钥；密钥目录继续与普通工作卷隔离。

## 6. 当前编排拓扑与日常管理

- 普通 `docker compose up -d` 会启动 PostgreSQL、TTS 初始化器、固定模型安装器、Nano Sidecar 和 QwenPaw，不再需要 `data`／`tts` profile。
- QwenPaw 仅在 PostgreSQL 与 Nano Sidecar 通过健康检查后启动；初始化器和安装器是幂等的一次性服务，成功完成后保持退出状态属于正常现象。
- PostgreSQL 与 QwenPaw 位于默认业务网络；Nano Sidecar 只与 QwenPaw 共享内部 `tts-private` 网络，模型安装器只使用下载网络。
- VoiceGenerator 需要 Apple MPS，继续作为 macOS 原生 launchd 服务运行，不进入 Docker Linux VM；PawApp 通过固定宿主地址和私有 token 调用。
- 停止服务使用 `docker compose stop`；不得使用带 `--volumes` 的 `down` 操作长期环境。

```bash
# 查看状态
docker compose ps -a

# 查看日志
docker logs --tail 200 ai-novel-2026-qwenpaw-lab

# 启动完整容器栈；命名卷都会保留
docker compose up -d

# 停止或重新启动完整容器栈；不要附加 --volumes
docker compose stop
docker compose restart
```

本文不提供自动删除容器或命名卷的命令。若以后需要清理，必须先确认目标并备份必要数据。

## 7. 下一步验证

项目初始化和阶段二尖峰见[新项目初始化与兼容性验证](./13-新项目初始化与兼容性验证.md)；阶段 3–6 基线见[阶段 3–6 实现与验收记录](./14-阶段3至6实现与验收.md)；0.3.0 结果见[阶段 7：章节候选与情报提案闭环](./15-阶段7章节候选与情报提案闭环.md)。Portkey、Ollama、TEI 和图片服务仍未自动启用。
