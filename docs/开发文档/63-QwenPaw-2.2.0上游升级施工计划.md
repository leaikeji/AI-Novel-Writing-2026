# QwenPaw 2.2.0 上游升级施工计划

状态：**V1.0 已完成并 PASS；长期 `18088` 已于 2026-09-10 切换到 QwenPaw 2.2.0，回退快照与 2.1.0 派生镜像保留。**

日期：2026-09-10（Asia/Shanghai）

## 1. 目标与非目标

目标：把 AI小说世界2026 的固定 QwenPaw 宿主从 `2.1.0` 升级到官方稳定版 `2.2.0`，继续通过公开 PawApp／PluginApi／前端扩展点运行，不修改 QwenPaw 上游核心，并形成可恢复、可审计的安装、升级、卸载和回退证据。

非目标：

- 不升级 PostgreSQL、pgvector、本地 Qwen TTS 模型或阿里云 Provider；
- 不改变小说数据 schema，生产数据库 head 保持 `20260909_0050`；
- 不借宿主升级施工计划 27、28、29、38、58、60 或其他尚未批准功能；
- 不切换计划 53 中仍为 `HOLD` 的 API／worker 数据库运行角色；
- 不修改、复制、覆盖或 monkey patch QwenPaw 核心源码，不读取其私有数据库或私有配置结构；
- 不删除 QwenPaw、PostgreSQL、小说媒体、模型或密钥卷。

## 2. 冻结版本与当前事实

| 项目 | 旧基线 | 升级目标 |
| --- | --- | --- |
| QwenPaw tag | `v2.1.0` | `v2.2.0` |
| 上游 commit | `e4995dcf516d27400fbc33891aa3dcbcf79acc7a` | `ae092fdca62164b467dee998893cbc450b97d59f` |
| 多平台 digest | `sha256:1132da56170f49c63aa583dd1ea3b09c19ce1ab76a1983813b8ad2f220771bcd` | `sha256:0c23ee08c700efe408796847f37f297c274ba190aa407605d1b124542fe1dcfd` |
| ARM64 manifest | `sha256:847fa1b01969492587fcf9b01f28fef97cb4039de92148c08c49486b94b3d912` | `sha256:c9cd6a8d2b7bd2fbee36415709e153a7b478302e2ee1a57a5768dbcb2ef457e6` |
| PawApp | `0.4.0` | `0.4.0`，只扩大经验证的宿主兼容范围 |
| PawApp 兼容声明 | `>=2.1.0,<2.2.0` | 验证通过后 `>=2.1.0,<2.3.0` |
| 生产数据库 | `20260909_0050` | 不变 |

2026-09-09 施工前只读核验：长期 QwenPaw 容器、PostgreSQL、PawApp、数据库和朗读 worker 健康；工作区干净。官方 2.2.0 发布说明包含 AgentScope、统一模型路由、Skills 更新、Extensions／插件管理和插件 workspace 恢复相关变化，因此必须对本项目实际使用的公开契约做定向复验。

## 3. 冻结接口与风险

以下接口在升级中不可静默改变：

- 宿主入口 `/apps/ai-novel-world-2026` 和后端 `/api/ai-novel-world-2026/...`；
- `PawApp`、`PluginApi.register_skill_provider`、`register_tool`、公开 HTTP 路由和 Middleware 工厂；
- `window.QwenPaw.route.wrap("core.chat")`、宿主 React／ReactDOM／Ant Design 单实例和当前聊天扩展；
- `ai-novel-writer` 是唯一小说生成 Agent，模型策略继续为 `follow-agent-effective`；
- 模型 fallback 不得绕过作者选择或伪造 requested／actual 模型证据；
- working copy、不可变 revision、CAS、候选／Diff／作者确认边界不变；
- 十一个小说 Skills 和五个工具只在批准的 Agent 作用域启用，卸载后必须完整清理；
- TTS、本地模型、媒体 Range、向量配置和密钥存储路径不变。

主要风险：插件版本保险丝阻止 2.2.0 安装；AgentScope 或 Middleware 生命周期变化；模型统一路由引入静默回退；Extensions 管理变化导致安装／卸载残留；Skills 自动更新覆盖用户启停；QwenPaw working 数据在新版本启动时发生不可逆迁移；派生镜像依赖解析覆盖宿主包。

W1 构建发现上游 2.2.0 自带 `cryptography 50.0.1`，旧项目 pin 会把宿主降级到 48.0.1。镜像内元数据确认 QwenPaw 2.2.0 只要求 `cryptography>=43`，`alibabacloud-tea-openapi 0.4.6` 在 Python 3.9+ 要求 `>=3,<51`；因此候选同步固定 50.0.1，避免为旧宿主约束降级新宿主。

## 4. 子代理并行施工设计

**本任务不并行。** 原因是 Docker 基础镜像、`plugin.json`、`compose.yaml`、唯一长期 QwenPaw 安装态和维护窗口均为共享互斥资源；在公开契约与镜像身份尚未冻结前拆分写入会增加错误切换和证据串线风险。施工由当前主代理作为唯一集成责任人串行完成，不创建子代理。

| 波次 | 工作包 | 类型 | 目标与前置 | 精确所有权 | 验收与证据 |
| --- | --- | --- | --- | --- | --- |
| W0 | `QPAW63-FREEZE` | `SER/GATE` | 冻结版本、digest、范围、公开契约与回退；作者已批准开始 | 本文；只读官方 v2.2.0 tag／release／插件文档 | 版本和 digest 可复核；长期切换仍 HOLD |
| W1 | `QPAW63-ADAPT` | `SER/MUTEX` | 形成 2.2.0 候选，保持上游薄层 | `plugin.json`、`docker/qwenpaw/Dockerfile`、`compose.yaml`、`scripts/tts/verify_qwenpaw_plugin_lifecycle.py`、直接相关测试 | manifest、Python、前端、打包、Compose 检查 |
| W2 | `QPAW63-ISO` | `SER/GATE` | W1 全绿；在唯一命名的隔离资源运行 2.2.0 安装／强制升级／卸载／重装 | 只允许新建 `ai-novel-2026-t1gate-*` 隔离容器／卷／网络；证据写 `docs/开发文档/证据/计划63/` | 生命周期 PASS；自动清理；长期资源身份不变 |
| W3 | `QPAW63-COMPAT` | `SER/GATE` | W2 PASS；验证原生页面、Agent／Skill／Tool、模型证据、工作台、数据与 TTS 非回归 | 隔离 2.2.0 环境与只读长期基线；不写正式小说 | 专项自动化、浏览器矩阵、受控样书／模型调用按需授权 |
| W4 | `QPAW63-BACKUP` | `SER/MUTEX/GATE` | W3 PASS；切换前一致性备份与恢复演练 | 备份目录、四个长期数据卷、固定旧镜像；禁止删除或覆盖旧备份 | custom dump、schema-only、卷／媒体清单、SHA-256、恢复 PASS |
| W5 | `QPAW63-RELEASE` | `SER/MUTEX/GATE` | W0–W4 全绿；维护窗口切换长期宿主 | 唯一长期 QwenPaw 容器和公开安装流程；PostgreSQL／媒体卷不迁移 | 2.2.0 健康、PawApp 0.4.0、DB `0050`、原生与产品门禁 PASS |
| W6 | `QPAW63-INT` | `INT` | W5 PASS；汇总证据、文档和回退信息 | README、开发索引、依赖基线、本文及计划63证据 | 全量回归、`git diff --check`、最终状态与恢复说明 |

## 5. 只读、禁止触碰与共享资源锁

- 只读：QwenPaw v2.1.0/v2.2.0 官方 tag、发布说明和公开插件契约；历史计划与历史验收证据；长期小说数据只用于计数、hash 和健康验证。
- 禁止触碰：旧项目 `/Users/liujia/Documents/AI小说世界3` 及其全部 `Data`；QwenPaw 上游源码；真实密钥值；未分配计划文件；任何用户正文内容。
- `LOCK-QWENPAW-IMAGE`：W1 构建和 W2 隔离验证独占派生镜像标签。
- `LOCK-QWENPAW-LIVE`：只有 W4/W5 可以停止或重建长期 QwenPaw；同一时间禁止其他安装、Agent 配置或插件管理动作。
- `LOCK-DB-BACKUP`：W4 由唯一 owner 创建备份并复核，不删除旧备份或生产卷。
- `LOCK-DOC-INTEGRATION`：W6 最后更新状态和索引，历史证据不倒改。

## 6. 门禁与验收命令

候选静态门禁：

```bash
.venv/bin/python -m pytest tests/test_manifest.py tests/test_qwenpaw_integration_contract.py tests/test_assistant_install_contract.py tests/test_skill_contract.py tests/narration/test_qwenpaw_plugin_lifecycle_runner.py
pnpm typecheck
pnpm test
pnpm build
.venv/bin/python scripts/package_plugin.py
docker compose config
git diff --check
```

隔离生命周期门禁使用 `scripts/tts/verify_qwenpaw_plugin_lifecycle.py` 的唯一资源前缀和显式确认值，目标镜像必须是本次 digest 固定基础镜像构建出的本地不可变 image ID。必须证明：只创建两个隔离容器、五个隔离卷和一个内部网络；不挂载长期卷、密钥、模型或宿主目录；完成 install／force-upgrade／uninstall／reinstall；最终自动清理。

长期切换门禁至少覆盖：

1. 当前 2.1.0 容器 ID、派生 image ID、上游 digest、PawApp tree hash、Agent／Skill／Tool 状态冻结；
2. QwenPaw working、secrets、backups、PostgreSQL 和小说媒体的一致性备份、SHA-256 与隔离恢复；
3. 普通 `/chat`、模型、Agents、Skills、MCP、Extensions 和 QwenPaw OS 原生页面；
4. 创作中心、章节打开／保存／CAS、历史恢复、候选／Diff／撤销、上下文和只读工具；
5. 向量本地／云端失败降级边界和本地 Qwen TTS health／播放／Range；
6. 完整卸载后原生 QwenPaw 恢复，重装后用户 Agent 模型与 Skills 启停不被覆盖；
7. 1920×1080、2560×1440 和受影响的 390×844 路径；
8. 最终全量 `.venv/bin/python -m pytest`、`pnpm test`、`pnpm typecheck`、`pnpm build`、打包和 `docker compose config`。

## 7. 回退

- W0–W3 失败：保持长期 2.1.0 不变，删除仅由计划63创建且已核对标签的隔离资源；保留失败证据，不扩大兼容声明。
- W4 失败：不得进入切换；修复备份或恢复演练后重新门禁。
- W5 启动或兼容失败：停止 2.2.0 QwenPaw，恢复固定 `v2.1.0@sha256:847fa1…` 派生镜像和升级前 PawApp 包；若 QwenPaw working 数据已变化，从本次只读冻结备份恢复。PostgreSQL schema 未改变时不得倒库；只有证明数据库被改变且需要恢复时才使用本次 custom dump。
- 任何回退均不删除数据卷，不改写 Alembic 历史，不用私有接口紧急修补上游。

## 8. 最终退出判断

`QPAW63-FREEZE` 至 `QPAW63-INT` 全部完成。正式容器运行派生 image ID `sha256:a7430e32833b6211f37200ee4e8c798946d8719772efcd650b92c1f663834fb3`，容器内 `qwenpaw=2.2.0`、`cryptography=50.0.1`、数据库 head `20260909_0050`，`pip check` 无破损依赖。PawApp 安装包 tree SHA-256 为 `b554733bb53a882dfabad0d629a500ce3d1dfcc27cb1287569c1d395a82324b4`。

隔离生命周期的 install／force-reinstall／uninstall／reinstall 与零残留清理通过；真实数据副本和正式环境均保持 `ai-novel-writer` 的 MiniMax-M3 有效模型、十一项 Skill 的作者关闭状态、五项小说工具的唯一 Agent 作用域。正式 TTS 恢复为 runtime/product ready，validation/reference-clone disabled。桌面与 390×844 创作中心、原生 Agent／Skills／Tools／Extensions 页面通过，正式最终浏览器控制台无 error。

升级中识别并修复两项安装门禁缺口：替换宿主启动前可显式传入旧宿主冻结的 Skill 状态；重启期间仅对 PawApp 瞬时 404／连接中断重试。其他 HTTP 错误、无效 Skill 快照和不匹配的 TTS 拓扑仍失败关闭。详细身份、备份、哈希与恢复路径见[计划 63 证据索引](./证据/计划63/README.md)。
