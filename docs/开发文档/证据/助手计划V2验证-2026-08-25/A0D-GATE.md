# A0D-G：ADR、协议与正式施工批准门禁

- 日期：2026-08-25
- 输入：A0A-G、A0B-G、A0C-G，以及用户当前“处理剩余门槛，然后开始使用目标模式完成开发，并真实测试每个环节”的明确施工指令。
- 结论：**通过；阶段 1–7 正式开放。**

## 冻结结果

1. A0D-1：接受 [ADR-0003](../../ADR/ADR-0003-QwenPaw原生助手上下文与受控编辑边界.md)，冻结原生 `Inner`、公开 Middleware、role=user 数据消息、工作台会话边界与短期内存 context_ref。
2. A0D-2：冻结 `NovelAssistantContextV2`、24,000 字符总预算、12,000 字符选区上限、1,500×2 前后文、20 分钟快照和 5 分钟 ref 生命周期。
3. A0D-3：冻结 `EditableFieldAdapter`、正文 autosave、表单 explicit-save、完整字段 SHA-256 冲突检查和单字段最近一次 `AIEditTransaction` 撤销。
4. A0D-4：冻结 selection/proposal 的 Agent/session/作品/文档/字段/revision/hash/TTL 绑定；几何采用 `field-anchor`；普通文本禁止自动写回。
5. A0D-5：阶段 1–7 的文件 Owner、波次、门禁和降级路径已与 ADR 对齐；共享入口、样式、工具、Agent/Skill 与安装状态继续单一 Owner 串行汇合。

## 七个 P0 裁决

| P0 | 裁决 |
| --- | --- |
| 上下文协议 | ✅ schema、枚举、预算、裁剪和三层数据来源已冻结 |
| 注入机制 | ✅ 真实链路选择公开 Middleware；Hook 不接生产 |
| 受控字段 | ✅ 正文与显式表单 Adapter 尖峰、冲突和回执已通过 |
| 保存/撤销 | ✅ autosave/explicit-save 分离并冻结 AI 事务语义 |
| 路由生命周期 | ✅ 唯一四态状态机和无法区分时退出工作台降级已通过 |
| 草稿留存 | ✅ 结果 C；会话历史披露 + 工作台会话绑定 + context_ref 减少原始暴露 |
| 模型依赖 | ✅ 跟随 Agent effective model；当前 MiniMax-M3 已验证 |

## 正式施工门禁

- 允许按计划 W1/2 → W3/4/5 → W6 → W7 滚动派发已批准工作包。
- A1-G、A2-G、A3-G、A4-G、A5-G、A6-G、A7-G 仍须逐门通过；A0D-G 不是最终功能验收。
- 工具轨视觉迁移、字段页面接线、context-ref 后端、正式资料工具、选区 UX、提案应用和真实三题材质量测试均仍是待施工事实。
- 不得修改 QwenPaw 上游核心；不得覆盖用户现有脏改动；不得把跳过测试计作通过。
