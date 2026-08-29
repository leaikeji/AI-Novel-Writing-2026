# P0 官方 18 音色直用实施证据

状态：**2026-08-29 实现与隔离验证已完成；发布候选。因 `0031` 线性依赖同一工作区中计划 34 尚未释放的 `0030`，不宣称 `P0-RELEASE` 或已切换长期运行环境。**

## 1. 已实现

- 固定 manifest 顺序的 18 项官方 ONNX preset 目录，默认全部 `selectable_now=true`；已完成章节级证据的项仅 Junhao、Zhiming、Xiaoyu，其余如实标记为 pinned catalog 未完成主观听检。
- 作者点击“使用”后，服务端在单事务中建立/复用本书 canonical profile/version、写入官方 rights/provenance，并设为旁白或绑定人物。无强制试听、质量确认、权利复选框或手工锁定。
- 旁白与人物绑定均保留 CAS；幂等键重放返回冻结结果和当前投影，不重做写入。
- `narration-voice/2` 区分人工试听确认与官方显式选择；官方直用不伪造 accepted、actor、preview 或 ModelRun 证据。
- 新音色库支持搜索、语言/类别筛选、旁白/人物目标切换和一步使用；没有真实试听处理器时，按钮明确显示“试听暂不可用”。
- 旧 `VoiceSourceWorkspace` 中官方六项建档分支已删除；组件收缩为上传/generated 私人来源边界，避免双权威。

## 2. 自动化与数据库验证

- 隔离 PostgreSQL 18：`0029 → 0030 → 0031 → 0030 → 0031` upgrade/downgrade/重升级通过；无直用数据时可回退，存在新证据时按 fix-forward 约束拒绝不安全降级。
- 隔离 PostgreSQL 官方选择：36 个目标动作（18 旁白 + 18 人物）、并发 CAS、事务回滚、deferred closure 均通过。
- 后端聚焦回归曾完成 173 项全通过；P1 接线后再次执行 `tests/narration` 全目录已通过（具备环境的 PostgreSQL/容器用例执行，其余按环境标记 skip）。
- 前端 P0 聚焦回归 74 项通过；当时全量回归为 95 个文件、865 项通过。P1 后续改动仍需在 W6 重跑最终全量。

## 3. 真实 Nano 短句烟测

在完全隔离的临时 Sidecar 中使用现有模型/密钥卷只读挂载、`--network none`、只读根文件系统及独立 4 GB / 4 CPU 上限。未触碰长期 Sidecar，未保存试听文本或音频，完成后临时容器已停止并自动移除。

18 项全部合成成功：Junhao、Zhiming、Weiguo、Xiaoyu、Yuewen、Lingyu、Trump、Ava、Bella、Adam、Nathan、Soyo、Saki、Mortis、Umiri、Mei、Anon、Arisa。输出均为 48 kHz、双声道、16-bit WAV，`clipped_fraction=0`，时长范围 2.24–10.00 秒。

真实风险记录：Yuewen 曾出现一次瞬态失败，重试成功；过短的 18 字符日语样例会导致 Saki 重试失败并污染当次隔离进程，重建临时容器并使用 32 字符日语句后通过。因此正式可选试听应使用按语种冻结的足长句子，不把过短句作为健康判定。

## 4. 未触碰的边界

- 长期 PostgreSQL 仍保持 `0029`，未执行 `0030/0031` 迁移。
- 唯一长期 QwenPaw/PawApp/Nano 运行环境未重建、未升级、未切换。
- 未删除任何真实私人音色、媒体或小说数据。
- 未提交、未推送 Git。

## 5. P0 发布阻断

`0031` 必须线性依赖计划 34 的 `0030`。在计划 34 完成、固定最终 `0030` 并释放 migration owner 之前，本计划只能宣称 P0 实现候选，不能宣称可独立发布。释放后必须从最终 `0029 → 0030 → 0031` 重做隔离迁移、全量后端、打包与安装/卸载验证。
