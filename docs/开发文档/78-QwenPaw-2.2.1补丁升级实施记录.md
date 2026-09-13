# QwenPaw 2.2.1 补丁升级实施记录

状态：**V1.0 已完成并 PASS；正式 `18088` 已升级至 QwenPaw 2.2.1。**

日期：2026-09-13（Asia/Shanghai）

## 1. 目标与范围

把长期 `127.0.0.1:18088` 的 QwenPaw 宿主从 `2.2.0` 升级到官方稳定版 `2.2.1`，继续使用公开 PawApp／PluginApi／前端扩展点，不修改 QwenPaw 上游核心。

本轮只升级宿主基础镜像并复验直接受影响的模型、Agent、Skill、Tool、插件与页面契约；不改变 PawApp 版本、数据库 schema、TTS 模型、Provider、作品内容或计划 74 的业务范围。

作者已明确现有作品均为测试数据，不要求按正式创作资产执行重型数据保护或真实数据副本恢复演练。项目上游升级硬门禁仍保留一次轻量卷快照、旧镜像和明确回退命令，不删除任何长期卷。

## 2. 冻结身份与公开变化

| 项目 | 旧基线 | 目标 |
| --- | --- | --- |
| QwenPaw tag | `v2.2.0` | `v2.2.1` |
| 上游 commit | `ae092fdca62164b467dee998893cbc450b97d59f` | `cae5773707b26ab2fd00903f84b712387894b256` |
| 多平台 digest | `sha256:0c23ee08c700efe408796847f37f297c274ba190aa407605d1b124542fe1dcfd` | `sha256:4127130c41f415434aca5a9ea8eada99d3185d99e2bf181bd95c6e7fb959a3a7` |
| ARM64 manifest | `sha256:c9cd6a8d2b7bd2fbee36415709e153a7b478302e2ee1a57a5768dbcb2ef457e6` | `sha256:9ea8531d57c7f6b117c2f9854750099b9616b1b82ce969c35b5a15da13595967` |
| PawApp | `0.4.0` | `0.4.0` |
| 兼容声明 | `>=2.1.0,<2.3.0` | 不变；2.2.1 验证后记录实证 |

官方 2.2.1 的直接相关变化包括每 Agent 模型路由／fallback、Skill 指令预加载、插件和 PawApp 更新检测、工具配置修复及 Console 导航变化。因此本轮定向验证这些公开契约，不把同 minor 版本号当作自动兼容证明。

## 3. 子代理并行施工设计

**本任务不并行。** QwenPaw 基础镜像、长期容器、三个外部 QwenPaw 卷、PawApp 安装态及计划 74 未提交工作区均为共享资源；由主代理作为唯一集成责任人串行完成，避免升级证据与业务候选串线。

| 波次 | 工作包 | 类型 | 目标与前置 | 精确所有权 | 验收与证据 |
| --- | --- | --- | --- | --- | --- |
| W0 | `QPAW78-FREEZE` | `SER/GATE` | 冻结运行身份、官方 tag／commit／digest、作者数据口径 | 本文；正式环境只读 | 2.2.0 健康、旧 image ID 与目标 digest 可复核 |
| W1 | `QPAW78-ADAPT` | `SER/MUTEX` | 更新薄镜像和生命周期常量，不改变插件契约 | `docker/qwenpaw/Dockerfile`、`compose.yaml`、`scripts/tts/verify_qwenpaw_plugin_lifecycle.py` | Compose、相关测试、镜像内依赖检查 |
| W2 | `QPAW78-CANDIDATE` | `SER/GATE` | 构建不可变 2.2.1 派生镜像并做无长期卷启动探针 | 新 2.2.1 镜像与一次性容器 | `qwenpaw=2.2.1`、`pip check`、根健康 |
| W3 | `QPAW78-BACKUP` | `SER/MUTEX/GATE` | 轻量冻结配置与卷回退点；作者已声明作品为测试数据 | 精确命名的三项 QwenPaw 卷及小说媒体卷快照；旧 2.2.0 镜像 | 源／目标文件数、字节数与内容哈希一致；不改写 PostgreSQL |
| W4 | `QPAW78-RELEASE` | `SER/MUTEX/GATE` | 用 Compose 正常重建唯一长期 QwenPaw | 长期 QwenPaw 容器；PostgreSQL 不重建 | 2.2.1、健康、PawApp、Agent／模型／Skill／Tool、TTS、原生页面 |
| W5 | `QPAW78-INT` | `INT` | 汇总证据、更新现行基线 | 本文、依赖基线、README 与索引、计划78证据 | 定向自动化、`git diff --check`、最终状态复核 |

## 4. 文件与资源边界

- 允许修改：本计划、现行索引与依赖基线、QwenPaw Dockerfile、Compose 镜像名、生命周期验证常量和计划 78 证据。
- 计划 74 的代码、迁移、Skill、工具与现有未提交内容必须原样保留；重叠文件只做最小行级合并。
- 禁止触碰 QwenPaw 上游源码、旧项目及其 `Data`、真实密钥值、PostgreSQL 数据、小说正文和媒体。
- `LOCK-QWENPAW-LIVE`：W3/W4 独占长期 QwenPaw；不得同时热安装 PawApp、迁移或切换 Agent 配置。

## 5. 门禁、切换与回退

候选至少执行：

```bash
.venv/bin/python -m pytest tests/test_manifest.py tests/test_qwenpaw_integration_contract.py tests/test_assistant_install_contract.py tests/narration/test_qwenpaw_plugin_lifecycle_runner.py
pnpm typecheck
pnpm build
.venv/bin/python scripts/package_plugin.py
docker compose config --quiet
```

正式切换前确认没有对应的实时模型／朗读进程，保留旧派生 image ID `sha256:a7430e32833b6211f37200ee4e8c798946d8719772efcd650b92c1f663834fb3`，并创建精确命名的 QwenPaw data／secrets／backups 与小说媒体卷快照。数据库中存在两条 2026-09-11 遗留的 `selection_edit/running` 测试记录，但没有对应执行进程；本轮不篡改这些历史记录。切换只重建 `qwenpaw` service，不重建 PostgreSQL、不运行数据库迁移。

中止条件：2.2.1 镜像依赖破损、PawApp 无法加载、Agent 模型或 Skill 状态漂移、小说工具越权、TTS 健康退化、原生聊天／模型／Agent／Skill／Tool／Extensions 页面不可用。中止后使用旧 image ID 重建 QwenPaw；若 working 配置被不兼容改写，再从本轮轻量卷快照恢复。任何回退均不删除卷。

## 6. 实际执行结果

- `QPAW78-FREEZE`：PASS。旧派生镜像保留为 `ai-novel-2026-qwenpaw-runtime:2.2.0-mvp0`，image ID 为 `sha256:a7430e32833b6211f37200ee4e8c798946d8719772efcd650b92c1f663834fb3`。
- `QPAW78-ADAPT`：PASS。官方 ACR 域名在本机 DNS 不可达，因此改用同一官方发布的 Docker Hub arm64 manifest `docker.io/agentscope/qwenpaw:v2.2.1@sha256:9ea8531d57c7f6b117c2f9854750099b9616b1b82ce969c35b5a15da13595967`；仍为固定 digest，不使用浮动 tag。
- `QPAW78-CANDIDATE`：PASS。派生镜像 `ai-novel-2026-qwenpaw-runtime:2.2.1-mvp0` 的 image ID 为 `sha256:eadfdf5bbcb9e3a5ccc45b6684dd707236dbce099ecf4e01578813c610b0f560`；镜像内 `qwenpaw=2.2.1`、`agentscope=2.0.7.post1`、`cryptography=50.0.1`、`fastapi=0.141.1`，`pip check` 无冲突；一次性无长期卷容器根页面返回 HTTP 200，随后已精确删除该一次性容器。
- `QPAW78-BACKUP`：PASS。停止长期 QwenPaw 后创建四个卷快照：`ai-novel-2026-qwenpaw-data-plan78-pre221`、`ai-novel-2026-qwenpaw-secrets-plan78-pre221`、`ai-novel-2026-qwenpaw-backups-plan78-pre221`、`ai-novel-2026-novel-media-plan78-pre221`。四组源／目标文件数、字节数和排序内容 SHA-256 完全一致；已有数据库 dump `/app/working.backups/plan74-20260913-before/formal-project-before.dump` 大小为 51,156,514 bytes，本轮宿主补丁升级未执行 schema 变更或数据库写入。
- `QPAW78-RELEASE`：PASS。只执行 `docker compose up -d --no-deps --force-recreate --no-build qwenpaw`；新容器 ID 为 `5a821a85df0e01cfbef85c64845a13bff04c8cfa14b8e11d4478c04a8da97492`，健康检查通过，根页面 HTTP 200，PostgreSQL 未重建。
- `QPAW78-INT`：PASS。正式验证确认 PawApp `0.4.0`、`bigmodel/glm-5.3-flash`、12 个小说 Skill 和 8 个小说工具均保持，仅在 `ai-novel-writer` 启用；TTS `runtime/product/reference clone` 均 ready，参考音频指纹保持 `32ce6265c58a9f99d5a692d76faf40b19d77e76b0cda7f27ba6556e1b7b6d76e`。

## 7. 验证证据

- 定向 Python 契约：206 passed。
- 全量 Python：3074 passed，284 skipped，4 个既有 deprecation warning。
- 前端：`pnpm typecheck`、`pnpm build` 通过；Vitest 161 个文件、1411 项测试全部通过。
- 打包与 Compose：`scripts/package_plugin.py`、`docker compose config --quiet` 通过；打包树 SHA-256 为 `0687e038d709eeecbe2d0717fabd3779fce7efe5ce5f7214561c2e3b5c7de508`。
- 2.2.1 隔离生命周期：安装、强制替换、全关、卸载零残留、重装和离线恢复全部 PASS；结构化记录见[生命周期结果](./证据/计划78/QPAW78-lifecycle.json)。该隔离门禁未连接正式卷或正式数据库。
- 正式桌面浏览器：QwenPaw 页头显示 `v2.2.1`；创作中心、模型、通用设置、Agent Skill 与工具页面均正常打开；Skill 页显示 12 个激活，工具页包含 8 个 `novel_*` 工具。浏览器控制台无 error，只有上游模块注册器的按需加载 warning。
- 正式容器最近日志未检出 `traceback`、`exception`、`critical`、`fatal` 或独立 `error`。

## 8. 回退点

普通宿主回退只需把 `compose.yaml` 的 QwenPaw image 临时改回 `ai-novel-2026-qwenpaw-runtime:2.2.0-mvp0`，再执行：

```bash
docker compose up -d --no-deps --force-recreate --no-build qwenpaw
```

若 2.2.1 曾不兼容地改写 QwenPaw 工作目录，应先停止 QwenPaw，再从本节四个 `plan78-pre221` 快照逐项恢复到对应长期卷；不得删除长期卷。当前升级后配置、Skill、工具与作品页面均未漂移，因此未触发卷恢复。
