# 计划74恢复说明

日期：2026-09-13。适用对象：计划74首发P1正式发布。

## 可用恢复材料

- 首次发布前总备份：`/private/tmp/ai-novel-world-2026-plan74-hCbpXPg7`。
- 正式持久卷副本：`/app/working.backups/plan74-20260913-before`。
- 最终生命周期前数据库：`final-lifecycle/database-before.dump`，SHA-256 `2f0b6337de4a6b88f54d35e8bbcb4a2079725eadf02a713f9db5cbda929b9649`。
- 最终生命周期前插件树：`final-lifecycle/plugin-before.tar.gz`，SHA-256 `711eff48304b4149ba531410ad5baf30423e9666729df218d87dd5fd7b10a82e`。
- 最终生命周期前Skill状态：`final-lifecycle/skills-before.json`，SHA-256 `6787fdd6340802f18a68e7fe3233a3d4cbaa44bf02119a3672cb8271f360e814`。

## 默认恢复策略

1. 先停止计划74的新增写操作，只读核对`/health`、`/api/pawapps`、Alembic head、当前插件树和最近变更回执。
2. 如果只是代码或前端故障，优先通过QwenPaw公开安装接口回装备份插件树；不修改上游源码，不清空数据卷，不降级数据库。
3. 回装后使用`skills-before.json`恢复既有Skill启用选择，再验证只有`ai-novel-writer`启用12项小说Skill与8项小说工具，默认Agent和QA Agent保持关闭。
4. 如果schema仍为`20260913_0056`，旧PawApp代码必须容忍新增表／列；默认保留加法schema，不执行`downgrade`删除计划74数据。
5. 数据库dump只用于严重数据损坏的灾难恢复。恢复前必须再次取得作者明确授权，把dump先还原到一个新建恢复库并核对作品、revision、私有资产、绑定、回执和检查报告；禁止直接覆盖正式数据库。

## 内容级恢复

- 资产修改与归档通过不可变新版本恢复，不倒拨或改写历史。
- 助手“撤销”创建补偿回执；若内容版本恢复后作品仍固定旧版本，必须再明确更新该书绑定，并分别核对资产当前版本和绑定版本。
- 生成或扫描失败不修改正式正文；working copy、候选、检查报告和历史revision继续保留。
- 禁用规则不能阻断作者手写、自动保存、崩溃恢复或历史恢复。

## 已执行的恢复演练

正式完整卸载后，PawApp、小说Skill和小说工具均归零，插件路由404；QwenPaw、PostgreSQL和`20260913_0056`保持。随后公开热装同一候选并恢复Skill状态，正式健康回到`ready`，资产、绑定、回执与检查报告保留。演练未删除或重建任何持久卷。

## 必须中止并人工裁决的情况

- 备份hash不匹配、目标插件或数据库身份不明确；
- 正式schema不是预期head，或出现未知迁移分叉；
- 回装要求修改QwenPaw核心、私有数据库或未公开模块；
- 恢复会覆盖较新的正文、revision、资产版本或作者绑定；
- Skill／工具出现在非`ai-novel-writer`Agent，或任何跨书写入证据。
