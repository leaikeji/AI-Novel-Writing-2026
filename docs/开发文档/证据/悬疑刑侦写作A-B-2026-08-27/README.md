# 悬疑刑侦写作候选规则首轮 A/B

状态：**运行中；探索性研究，不是正式 Skill 验收。**

日期：2026-08-27（Asia/Shanghai）

## 目标

验证三书前100章首次对照形成的三个窄候选，能否在当前 `AI小说作家` 的既有九个 `0.4.0` Skills 上带来可观察的写作增益。A组只使用当前正式能力；B组使用同一能力并在用户请求内追加冻结的临时候选覆盖层。本轮不修改、安装或替换任何 Skill。

## 边界

- 只使用项目合成题 `CF-01`、`SP-02`、`DS-01`、`GP-02`，不把授权小说正文放进提示或证据目录。
- 每题每组独立生成2次，共16份候选；每次使用新聊天，避免上下文串扰。
- 请求前核对 `ai-novel-writer` 的 effective provider/model；生成后优先从公开聊天记录保存实际模型证据。当前公开 HTTP 未暴露或持久返回实际模型时，必须将 `actual_model` 记为 `not_exposed`，只保留调用前 requested 证据与聊天页模型标识，不得把 requested 冒充 actual。
- 模型参数若宿主UI和公开记录不提供，登记为 `not_exposed`，不得猜测。
- 硬门槛、失败、平局和退化样本全部保留。
- 自动或模型评审只形成探索性结果；计划22要求的正式人工匿名盲评仍需另行完成。

## 冻结输入

- 题库：`tests/fixtures/writing_skill_eval/cases.json`
- 题库 SHA-256：`86ce85e26070bb66355f83f76a09ff37e02d18c806cbe7b955ee7fe571acbebf`
- 当前模型策略：`follow-agent-effective`
- 运行前 effective 模型：`bigmodel / glm-5.3-flash`
- 候选覆盖层：[candidate-overlay.md](./candidate-overlay.md)
- 运行合同：[manifest.json](./manifest.json)
- 评分合同：[rubric.md](./rubric.md)
- 运行观察：[runtime-observations.md](./runtime-observations.md)
- 研究运行器：[runner.md](./runner.md)

## 提示拼接

- A组：合成题面、冻结硬约束和纯正文要求。
- B组：A组完整提示后追加候选覆盖层的通用约束，并且只追加当前题对应的一条信息释放规则；不把其他题的模式或 case id 注入该次请求。
- 每份样本保存最终拼接提示 SHA-256、输出 SHA-256、聊天标识、请求模型、实际模型可得性和 UI 用量摘要。

## 已知运行限制

已有 UI 样本 X01 无法从公开聊天接口恢复 `qwenpaw_turn_usage` 中的 actual provider/model，因此不能纳入“16/16 实际模型一致”的强证明。新研究运行器只接受本次结构化 closing reply 的公开 metadata；真实哨兵尚未执行，在它证明 actual/usage 可保存前仍不得启动16样本或宣称模型一致。

## 完成条件

只有16份生成全部得到可复核状态、硬门槛与盲评原始记录保存、盲码解封后完成成对归因，才能把本目录状态改成“首轮完成”。即使首轮胜出，也不得直接修改正式 Skill。
