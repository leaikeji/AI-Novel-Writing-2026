# 计划 63：QwenPaw 2.2.0 升级证据索引

状态：**V1.0 已完成并 PASS；长期 `18088` 已切换到 QwenPaw 2.2.0，PawApp、数据、Agent、模型、Skill、Tool 与 TTS 状态均通过复核。**

日期：2026-09-10（Asia/Shanghai）

## 1. 冻结与最终身份

| 项目 | 值 |
| --- | --- |
| 旧 QwenPaw | `v2.1.0`，派生 image ID `sha256:3a15aa8c762dfb1254332dafef931c7cf6dd377ede4d93380da39eb27db9b96e` |
| 新 QwenPaw | `v2.2.0`，commit `ae092fdca62164b467dee998893cbc450b97d59f` |
| 新上游 digest | multiarch `sha256:0c23ee08c700efe408796847f37f297c274ba190aa407605d1b124542fe1dcfd`；arm64 `sha256:c9cd6a8d2b7bd2fbee36415709e153a7b478302e2ee1a57a5768dbcb2ef457e6` |
| 新派生镜像 | `sha256:a7430e32833b6211f37200ee4e8c798946d8719772efcd650b92c1f663834fb3` |
| 最终正式容器 | `01cfc850894d0f79cda2453e1b446047e2897f747e4702d180b01d7bdcab081c`，Docker health `healthy` |
| PawApp | `ai-novel-world-2026@0.4.0`；兼容范围 `>=2.1.0,<2.3.0` |
| PawApp tree SHA-256 | `b554733bb53a882dfabad0d629a500ce3d1dfcc27cb1287569c1d395a82324b4` |
| 数据库 | PostgreSQL 18.6；Alembic `20260909_0050 (head)`，升级未新增 schema |
| 容器依赖 | Python 3.11.2、AgentScope 2.0.7.post1、FastAPI 0.141.1、cryptography 50.0.1；`pip check` PASS |

QwenPaw 官方公开插件文档明确 `qwenpaw_version.min` 为包含下限、`max` 为不包含上限；因此 2.2.0 验收后的兼容声明使用 `<2.3.0`，不承诺未知 2.3.x。[官方契约](https://github.com/agentscope-ai/QwenPaw/blob/v2.2.0/website/public/docs/plugins.en.md)

## 2. 自动化与生命周期

| 门禁 | 结果 |
| --- | --- |
| 最终 Python 全量 | PASS：2668 passed、253 skipped、3 个既有 deprecation warnings |
| 前端 typecheck | PASS：`tsc --noEmit` |
| 前端 Vitest | PASS：151 files、1286 tests |
| 前端 build | PASS：Vite 6.3.5，193 modules transformed |
| Compose／依赖 | PASS：`docker compose config --quiet`、容器 `pip check` |
| 打包 | PASS：最小候选 tree SHA-256 见上表 |
| 隔离插件生命周期 | PASS：install／force-reinstall／uninstall／reinstall、数据库与卷哨兵、卸载零残留、精确资源清理；原始 JSON 见 [QPAW63-ISO-plugin-lifecycle.json](./QPAW63-ISO-plugin-lifecycle.json) |
| 真实数据副本升级 | PASS：从正式卷快照和数据库 dump 恢复到独立 `18089`；2.2.0、PawApp、MiniMax-M3、Skill／Tool 作用域与数据可见性通过 |
| 正式安装闭环 | PASS：维护态安装、迁移、Agent 配置、TTS 密钥验证、正式开关恢复与最终公开契约核验完整成功退出 |
| 最终静态检查 | PASS：`git diff --check`；最终状态复核见本次任务交付 |

隔离生命周期脚本只创建两个容器、五个卷和一个内部网络，不挂载正式卷、模型、token 或宿主目录；结束后按精确名称和 ownership label 清理。另一个真实数据副本演练使用 `plan63-upgrade-lab` 标签资源，只消费快照，不写正式环境。

## 3. Agent、模型、Skill 与工具

- 专用 Agent 仍为 `ai-novel-writer`，公开 effective model 为 `minimax-cn / MiniMax-M3`；升级脚本未写模型字段。
- 升级前公开状态显示 11 个项目 Skill 全部为关闭；冻结文件见 [QPAW63-preupgrade-skill-state-18088.json](./QPAW63-preupgrade-skill-state-18088.json)。真实数据副本和正式升级后均保持全部关闭，没有因插件替换被自动开启。
- 五个小说工具仅在 `ai-novel-writer` 中启用：`novel_get_context`、`novel_get_document`、`novel_get_workspace_context`、`novel_prepare_selection_edit`、`novel_search`；`default` 与 `QwenPaw_QA_Agent_0.2` 均无项目工具泄漏。
- `AI_NOVEL_WORLD.md` 与现有系统提示文件保持，`BOOTSTRAP.md` 不重新出现。

本次没有发起新的计费模型生成；模型路由、provider/model 身份和已存在会话／小说可见性使用公开 API 与浏览器做非写入核验。

## 4. TTS 与浏览器非回归

- 正式最终开关保持升级前状态：runtime `ready`、product `ready`、validation `disabled`、reference clone `disabled`。
- HMAC keyring 仅做有效性校验，key id 为 `narration-local-2026-08`；没有输出或复制密钥值。
- 正式 health 的 worker、playback、digest keyring 和 production backend 全部 ready；provider selection fingerprint 在升级前后均为 `32ce6265c58a9f99d5a692d76faf40b19d77e76b0cda7f27ba6556e1b7b6d76e`。
- 真实浏览器检查覆盖 QwenPaw 2.2.0 原生 Agent 切换、Skills、Tools、Extensions、PawApp 打开、桌面创作中心和 390×844 窄屏。正式最终创作中心可见原有小说，浏览器控制台无 error。

升级演练暴露并修复两项安装器问题：

1. 替换宿主可能先启动而无法从旧插件读取 Skill 状态，安装器新增受作用域和绝对路径校验的 `--previous-skill-state`；
2. QwenPaw 根健康先于 PawApp 路由就绪，重启窗口会短暂返回 404。等待器现在只重试 404、连接中断与超时，其他 HTTP 错误和错误拓扑仍立即失败。

## 5. 备份与恢复

切换前保留两组只读快照。最终切换时刻快照为：

- `ai-novel-2026-qwenpaw-data-plan63-cutover220`
- `ai-novel-2026-qwenpaw-secrets-plan63-cutover220`
- `ai-novel-2026-qwenpaw-backups-plan63-cutover220`
- `ai-novel-2026-novel-media-plan63-cutover220`

它们均带 `ai.novel.world.purpose=plan63-cutover220-backup` 标签，复制后按源／目标 `du -sk` 一致性校验。较早的 `*-plan63-pre220` 快照继续保留，不覆盖。

最终数据库转储位于正式 backups 卷：

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| `/app/working.backups/plan63-qwenpaw-220-20260910-0040/database.dump` | 16,880,782 bytes | `6257e55ecf9c02002b2fe2fc5f58be62d1c31ac13eb72f87ada23ecd62f5d488` |
| `/app/working.backups/plan63-qwenpaw-220-20260910-0040/schema.sql` | 486,757 bytes | `1d1bad7adfdba087fcff2f51255c314f7baad35d28759719324ee0d0b2b6af35` |

恢复顺序：停止当前 QwenPaw；将四个 `plan63-cutover220` 快照复制回对应正式卷；使用 `compose.yaml` 加 [QPAW63-compose-rollback-210.yaml](./QPAW63-compose-rollback-210.yaml)、`--no-build` 与原 TTS 开关重建 2.1.0；数据库 schema 未变化时不倒库，只有证明数据库已受损才恢复 custom dump。旧 image ID 与快照均未删除。

## 6. 结论与剩余边界

QwenPaw 2.2.0 长期升级完成，未修改上游核心、未改写迁移历史、未删除正式卷，PawApp 可继续独立升级／卸载。未知未来版本仍必须重新做公开契约与隔离升级门禁；`<2.3.0` 不是对 2.3.x 的提前承诺。
