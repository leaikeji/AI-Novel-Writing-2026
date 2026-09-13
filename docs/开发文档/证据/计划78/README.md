# 计划 78：QwenPaw 2.2.1 补丁升级证据

状态：**已完成并 PASS。**

日期：2026-09-13（Asia/Shanghai）

本目录记录 QwenPaw 2.2.1 固定镜像、候选构建、隔离生命周期、轻量回退点、正式切换和非回归结果。

## 最终结论

- 正式入口：`http://127.0.0.1:18088`
- 正式版本：`qwenpaw=2.2.1`
- 派生镜像：`ai-novel-2026-qwenpaw-runtime:2.2.1-mvp0`
- image ID：`sha256:eadfdf5bbcb9e3a5ccc45b6684dd707236dbce099ecf4e01578813c610b0f560`
- 官方基础镜像：`docker.io/agentscope/qwenpaw:v2.2.1@sha256:9ea8531d57c7f6b117c2f9854750099b9616b1b82ce969c35b5a15da13595967`
- 运行状态：QwenPaw 与 PostgreSQL 均 healthy；根页面 HTTP 200。
- 插件状态：PawApp `0.4.0` ready；12 个小说 Skill 与 8 个小说工具升级前后保持一致且仅作用于 `ai-novel-writer`。
- 桌面状态：创作中心、模型、通用设置、Skill 和工具页均可用；页头明确显示 `v2.2.1`。

## 可复核结果

| 检查 | 结果 |
| --- | --- |
| 2.2.1 隔离生命周期 | PASS；详见 [`QPAW78-lifecycle.json`](./QPAW78-lifecycle.json) |
| 定向 Python 契约 | 206 passed |
| 全量 Python | 3074 passed，284 skipped |
| 前端 Vitest | 161 files、1411 tests passed |
| 前端类型／构建 | `pnpm typecheck`、`pnpm build` PASS |
| 打包／Compose | `scripts/package_plugin.py`、`docker compose config --quiet` PASS |
| 正式插件验证 | PawApp、Agent、模型、Skill、Tool、TTS 全部 PASS |

隔离生命周期的 initialized、mixed、mixed-repeat、mixed-hot、all-off-hot 与 offline 六个 Skill 状态快照均随本目录保存；文件只记录隔离容器地址、Agent ID 和 12 个 Skill 的布尔启用状态，不含密钥或正式环境数据。

## 回退资产

- 旧镜像：`ai-novel-2026-qwenpaw-runtime:2.2.0-mvp0` / `sha256:a7430e32833b6211f37200ee4e8c798946d8719772efcd650b92c1f663834fb3`
- 卷快照：`ai-novel-2026-qwenpaw-data-plan78-pre221`、`ai-novel-2026-qwenpaw-secrets-plan78-pre221`、`ai-novel-2026-qwenpaw-backups-plan78-pre221`、`ai-novel-2026-novel-media-plan78-pre221`
- 四组快照均已复核源／目标文件数、字节数和排序内容 SHA-256 一致。

完整执行与回退说明见[计划 78 实施记录](../../78-QwenPaw-2.2.1补丁升级实施记录.md)。
