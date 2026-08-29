# ADR-0009：QwenPaw 公开模型证据与候选采用边界

状态：**已采用**

日期：2026-08-29（Asia/Shanghai）

## 背景

PawApp 通过 QwenPaw 公开 Agent 接口执行 `ai-novel-writer`。公开回复并不保证暴露 provider/model usage 元数据。旧实现把 usage 缺失等同于模型身份错误，并回退读取 QwenPaw 私有 usage buffer，导致正常人物生成被作废，也破坏上游隔离边界。

## 决策

1. 任务前后都通过 QwenPaw 公开 effective model API 读取身份。
2. public usage 完整且与任务前后身份一致时，证据为 `verified_from_provider_usage`。
3. public usage 完全未公开、但任务前后 effective identity 一致时，证据为 `not_exposed`；这只证明公开有效模型稳定，不证明实际模型已回显。结果可以进入作者审阅候选，actual 字段保持空。
4. usage 畸形、身份错配、effective model 变化或 postflight 失败时，证据为 `rejected`，结果不得采用。
5. 禁止导入或读取 QwenPaw 私有 usage buffer，禁止把 requested/effective model 伪装为 actual model。
6. AI 结果无论证据状态如何都不能绕过作者确认直接进入正式正文、规划、人物或故事账本。

## 影响

- 修订计划 19 中“实际 usage 元数据缺失即任务失败”的窄规则；继续保留 `follow-agent-effective` 唯一路径、无静默回退和任务级审计。
- 新生成任务保存结构化 evidence；旧任务保持不可变。
- TTS 本地模型指纹与向量模型连接/维度证据维持各自独立契约。
