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

## 下一步裁决点

下一步不是直接跑16份，而是在其他专项未占用唯一共享运行环境时，显式确认一次模型调用成本，启用独立 Compose override 并只运行新的 X01 哨兵。哨兵必须验证 actual/usage 可保存、服务端无持久化、小说数据库写入数不变和原生功能非回归；任何一项失败都停止，不自动重试。
