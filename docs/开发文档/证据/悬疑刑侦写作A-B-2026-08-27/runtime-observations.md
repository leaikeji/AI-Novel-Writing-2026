# 运行观察

状态：首个样本完成；批量生成尚未完成。

## 已完成样本

### X01 / SP-02

- 聊天标识：`37cd965f-bbf7-4de0-be0d-65a89a66c346`
- 请求前 effective 模型：`bigmodel / glm-5.3-flash`
- 聊天页模型标识：`bigmodel / glm-5.3-flash`
- actual provider/model：`not_exposed`
- UI 用量：`25.2K tok`，其中 `in 24.5K`、`out 690`
- 墙钟时间：22:11:18—22:15:48，约4分30秒
- 正文非空白字符：527，篇幅门槛通过
- 模型行为：调用正式 `prose-writing` Skill，并在其 Agent workspace 内创建临时计数文件、执行字符计数；主项目目录未发现 `scene_eval.txt`。

确定性硬门槛初检：篇幅通过、非空通过、无标题或 Markdown/JSON/XML 包装。锚点、知识边界、状态变化等语义门槛尚待匿名人工复核，不能提前记为通过。

## 未计入样本的中断运行

| 临时目标 | chat_id | 处理 | 原因 |
| --- | --- | --- | --- |
| X02 | `90313bf6-cf2e-48b8-aeb1-bb4931890414` | 中止，不计入 | 并发拥塞后单路继续仍超过10分钟，未出现最终正文 |
| X03 | `3dfb10ec-b006-43be-8845-5e571c9eb37b` | 中止，不计入 | 三路并发造成推理队列拥塞 |
| X04 | `908ea9ed-28cc-4dbd-a643-010c6c11b6e6` | 中止，不计入 | 三路并发造成推理队列拥塞 |

这些 chat id 不得复用为正式盲评样本；重新生成时必须使用新聊天。

## 运行限制

1. 当前聊天 UI 适合交互式写作，不适合直接承担16次可审计批量评测：单样本长思考、自检和 Skill 调用使墙钟时间较长，并发又会造成拥塞。
2. QwenPaw 公开聊天 HTTP 当前不能恢复本次消息和 `qwenpaw_turn_usage`；实际 provider/model 与精确 token 字段不能事后补猜。
3. 在没有新增可保存原始 reply metadata 的非持久评测入口前，本轮只能证明 requested effective 模型和聊天页标识一致，不能证明16次 actual 模型完全一致。

## 研究运行器源码门禁

最小研究运行器源码候选已完成，默认关闭且不连接小说数据库。它固定 experiment/sample、Agent、Skill 和题面，只接受空请求体；actual provider/model 与 token usage 必须来自本次结构化 closing reply 的公开 metadata，缺失或漂移即失败。新增合同/API/CLI 测试 `52 passed`，相关定向回归 `166 passed`，全量回归 `2376 passed, 116 skipped`，Compose override 配置解析和 PawApp 打包通过。

这只能消除上面第2、3项在“后续新样本”中的设计缺口，不能补全已有 X01 的 actual 证据，也不能把旧 UI 样本转成正式运行器样本。

## 首次真实运行器哨兵

### `mystery-ab-runner-sentinel-v1` / X01

- 用户明确授权：一次模型调用成本。
- 预检：固定 experiment 合同返回200；只允许 X01—X16；`server_persistence=none`、`arbitrary_prompt_allowed=false`；QwenPaw 根页面、PawApp 注册表和项目健康接口均返回200。
- 派发：只派发 X01 一次，没有并发或自动重试。
- 结果：HTTP 504；运行摘要为 `0 completed / 1 failed`。
- 缺失证据：没有最终正文、actual provider/model 或 token usage，因此不能计入 A/B 样本。
- 恢复：普通 Compose 已重新创建 QwenPaw，研究路由恢复404；QwenPaw、PostgreSQL、TTS Sidecar 均为 healthy。

项目权威表只读计数在哨兵前后完全一致：小说9、文档25、不可变正文版本126、working copy 25、章节生成任务50、候选26、故事事实510、情报提案29、创作生成任务162、模型运行记录53。活动后台任务和活动朗读请求前后均为0。该结果证明失败没有修改小说数据，但不证明模型调用链可用。

## 下一步裁决点

下一步不是放宽超时后直接重跑，更不是启动16份。应先补齐 HTTP 失败响应正文、服务端阶段时间点和 Agent 是否进入工具循环的可观测证据，并裁决是否能在公开 QwenPaw 契约内真正禁止该研究调用使用工具。诊断完成后如需第二次真实请求，必须重新取得模型调用成本授权并使用新的 run id；不得复用或覆盖本次失败 run。

## 2026-08-28 只读诊断结论与源码修复

已核实首次失败精确命中本项目600秒硬上限；直接原因是 `ctx.chat()` 未在期限内关闭响应流。现有证据不能继续区分长推理、Agent/工具多轮或 Provider 等待。题面仅727字符，数据库、后台任务、路由和容器健康均已排除为直接原因。

QwenPaw 当前公开 `PawAppContext.chat/chat_stream` 参数不包含逐请求工具策略，而 `AI小说作家` 当前有9个启用 Skill 和29个启用工具。因此旧运行器把 `tools=forbidden` 写入提示，只能表达意图，不能证明运行时隔离。当前模型 `bigmodel/glm-5.3-flash` 的公开元数据为 `relay_reasoning=true`，thinking budget 未暴露；这些是解释候选，不是已证明根因。

诊断源码候选现改用 `ctx.chat_stream()`：只保存流式事件结构计数和耗时，不保存内容；失败响应返回 session、开始时间、请求模型和提示级工具策略，CLI 保存有界 JSON 错误正文与本地时间链。纯模拟定向测试 `54 passed`，项目全量回归 `2436 passed, 116 skipped`，合同自检、Compose override 静态解析、Python 编译和 PawApp 本地打包通过。整个验证过程未启用研究入口、未安装到共享容器、未调用模型。真实根因分类仍须未来获得新的明确授权后，用新 run id 执行一次带观测的哨兵；在此之前保持停止。
