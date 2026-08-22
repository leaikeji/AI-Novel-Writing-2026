# QwenPaw Docker 验证环境

验证日期：2026-08-23（Asia/Shanghai）。

状态：**已部署并通过基础运行、回环监听和重启持久性验证**。这只是 QwenPaw 上游验证环境，不代表已经执行 AI小说世界2026 的 Git 初始化、PawApp 初始化、数据库部署或模型配置。

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

三个卷带有 `ai.novel.world.project=AI小说世界2026` 和各自用途标签。停止或重启容器不会删除这些卷。

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
- 当前未安装小说 PawApp，未创建 PostgreSQL、pgvector、Portkey、Ollama、TEI、TTS 或图片服务。
- 当前未创建 Git 仓库、工程骨架、Compose 文件或依赖锁；“执行新项目初始化”仍是独立的后续授权闸门。
- 后续录入 Provider 密钥时，必须验证浏览器存储、API 响应和日志不回显密钥；密钥目录继续与普通工作卷隔离。

## 6. 日常管理

```bash
# 查看状态
docker inspect ai-novel-2026-qwenpaw-lab --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}'

# 查看日志
docker logs --tail 200 ai-novel-2026-qwenpaw-lab

# 停止、启动或重启；命名卷都会保留
docker stop ai-novel-2026-qwenpaw-lab
docker start ai-novel-2026-qwenpaw-lab
docker restart ai-novel-2026-qwenpaw-lab
```

本文不提供自动删除容器或命名卷的命令。若以后需要清理，必须先确认目标并备份必要数据。

## 7. 下一步验证

只读 UI 盘点已经完成，结果见[QwenPaw 原生 UI 盘点与小说工作台 UI 基线](./12-QwenPaw原生UI盘点与小说工作台UI基线.md)。已确认原生聊天、应用、模型、Skills、MCP、插件和设置入口的共存边界；最终视觉稿仍需三套低保真方向比较，不要求一次性冻结所有 UI，也不依赖妙笔神书研究全部结束。

只有用户明确说“执行新项目初始化”后，才进入最小 PawApp/Compose 工程创建和插件装卸兼容尖峰。
