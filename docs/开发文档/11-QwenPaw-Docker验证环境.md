# QwenPaw Docker 验证环境

验证日期：2026-08-23（Asia/Shanghai）；统一编排复核更新于 2026-08-31；QwenPaw 2.2.1 正式升级复核于 2026-09-13。

状态：**长期 `18088` 已运行 QwenPaw 2.2.1，并通过固定镜像、完整插件生命周期、轻量卷快照、全量自动化和正式桌面非回归。** 早期环境搭建与旧 TTS 链细节按历史事实保留，现行宿主身份以[计划 78](./78-QwenPaw-2.2.1补丁升级实施记录.md)为准。

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
| QwenPaw 包版本 | `2.2.1` |
| 镜像来源 | `docker.io/agentscope/qwenpaw` |
| arm64 平台 manifest digest | `sha256:9ea8531d57c7f6b117c2f9854750099b9616b1b82ce969c35b5a15da13595967` |
| 多平台顶层 digest | `sha256:4127130c41f415434aca5a9ea8eada99d3185d99e2bf181bd95c6e7fb959a3a7` |
| 平台 | `linux/arm64` |
| 镜像内 Python | `3.11.2` |
| 项目派生镜像 | `ai-novel-2026-qwenpaw-runtime:2.2.1-mvp0`；image ID `sha256:eadfdf5bbcb9e3a5ccc45b6684dd707236dbce099ecf4e01578813c610b0f560` |

**已核实事实**：2.2.1 升级时官方 ACR 域名在本机 DNS 不可达，因此改用 QwenPaw 官方 Docker Hub 镜像源。本机固定到 `v2.2.1` 的 arm64 manifest，而不是使用可漂移的 `latest`。

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
| 版本一致性 | 通过 | 容器内 Python 元数据返回 `qwenpaw=2.2.1`、`agentscope=2.0.7.post1` |
| 持久化 | 通过 | 受控重启前后 `/app/working/config.json` SHA-256 都是 `b60661293f3598812e3e2417e68edf5969e738a975c7e4a55d7b927190bc0856` |
| 重启恢复 | 通过 | 重启后重新达到 `healthy`，首页仍返回 HTTP `200`，回环映射未变化 |
| 当前配置 | 通过 | `AI小说作家` 使用 `bigmodel/glm-5.3-flash`；12 个小说 Skill 与 8 个小说工具保持 Agent 隔离 |

## 5. 安全和范围边界

- QwenPaw 2.2.1 Docker 控制台本身没有登录认证。本验证环境只允许本机可信单用户使用，禁止把端口发布到 `0.0.0.0` 或局域网。
- Provider 密钥只保存在独立 secrets 卷；升级与证据记录不读取或输出真实值。
- 当前已安装小说 PawApp 0.4.0，并创建独立“AI小说作家” Agent；12 个小说 Skill 和 8 个小说工具只在该 Agent 中启用，Default 与 QA 中保持关闭。AI 生成仍遵守候选／提案与作者确认边界。
- “AI小说作家”额外启用项目管理的 `AI_NOVEL_WORLD.md` 系统提示文件，用于自主 Skill 路由；QwenPaw 原生 `AGENTS.md`、`SOUL.md`、`PROFILE.md` 保留。默认首次引导文件已改名归档，避免继续污染小说对话。
- 本机 Docker Desktop 偶发在 QwenPaw 停止后立即复用命名卷时卡住。安装脚本现使用 30 秒优雅停止、确认容器完全退出并等待卷释放，再启动临时安装容器；修改后重复安装已正常完成。
- PostgreSQL 18.6 + pgvector 0.8.6 与 QwenPaw 2.2.1 长期容器已启动并健康；本地 Qwen TTS 由项目现行按需 Provider 链管理。Portkey、Ollama、TEI 和图片服务未进入默认 Compose。
- 后续录入 Provider 密钥时，必须验证浏览器存储、API 响应和日志不回显密钥；密钥目录继续与普通工作卷隔离。

## 6. 当前编排拓扑与日常管理

- 普通 `docker compose up -d` 启动 PostgreSQL 与 QwenPaw；默认 Compose 不再包含旧 Nano、VoiceGenerator、模型安装器或下载网络。
- QwenPaw 在 PostgreSQL 健康后启动；宿主补丁升级可以用 `--no-deps --force-recreate --no-build qwenpaw` 只重建 QwenPaw，不重建数据库。
- PostgreSQL 与 QwenPaw 位于默认业务网络；长期端口均只绑定 `127.0.0.1`。
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

项目初始化和阶段二尖峰见[新项目初始化与兼容性验证](./13-新项目初始化与兼容性验证.md)；阶段 3–6 基线见[阶段 3–6 实现与验收记录](./14-阶段3至6实现与验收.md)；当前 QwenPaw 2.2.1 身份、回退点与正式验收见[计划 78](./78-QwenPaw-2.2.1补丁升级实施记录.md)。Portkey、Ollama、TEI 和图片服务仍未自动启用。
