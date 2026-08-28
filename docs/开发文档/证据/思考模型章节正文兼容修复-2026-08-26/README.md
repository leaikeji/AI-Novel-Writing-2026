# 思考模型章节正文兼容修复证据

状态：**已完成代码、隔离数据库、真实 QwenPaw 安装、真实模型与浏览器验收。**

日期：2026-08-26（Asia/Shanghai）

目标对象：`AI小说作家` Agent；作品《刑侦1988:档案里消失的人》；章节《护城河的绳结》。

## 1. 已核实问题

- QwenPaw 公开模型信息中，`qwen3.7-plus`、`deepseek-v4-flash` 与 `MiniMax-M3` 均为 `thinking_enabled=null`、`reasoning_effort=null`、`thinking_budget=null`、`relay_reasoning=true`。因此没有证据证明 MiniMax 是因为“关闭思考模式”才成功。
- 三者使用的公开适配器不同：Qwen 为 `OpenAIResponseModel`，DeepSeek 为 `OpenAIChatModel`，MiniMax 为 `AnthropicChatModel`。`null` 只代表没有显式覆盖，不等于开启或关闭。
- 修复前，同一章节的 DeepSeek 已实际返回 46089、31979、19735 个可见字符并因旧 1500 字上限失败，另有超时；Qwen 出现空 final 与 300 秒超时。公开 token 用量显示模型确实被调用，故不是简单网络未连接。
- 章节任务书实际保存 `target_word_count=2500`，旧实现却把生成目标硬改为 1250、验收范围硬改为 1000–1500，属于历史验收窗口泄漏到生产逻辑。

## 2. 只前滚修复

- 所有 PawApp 生成入口不再把聚合 `reply.text` 直接作为业务结果；统一从最后一个结构化 Agent 响应中倒序提取最终 `message`，排除 reasoning、thinking、tool、delta 与中间轮次。存在结构化响应但没有 final 时可见失败，不用聚合文本冒充正文。
- `prose-writing` 增加通用 `chapter_generation` 任务模式：允许模型内部充分思考，但本任务不调用工具、不开启后续 Agent 轮次，只返回一次最终正文。没有模型名分支、模型白名单、逐模型 Skill、静默回退或关闭思考。
- 章节长度以任务书目标为唯一基准，通用合格范围为 `floor(target × 0.85)` 到 `ceil(target × 1.15)`。2500 字对应 2125–2875 字；前端、提示词、任务快照、服务端校验和历史展示使用同一证据。
- 当前章旧稿从“前文上下文”中分离，明确只保留事实、人物声音和连续性，不得原样返回，必须生成达到目标范围的新候选。
- 生成契约升级为 `follow-agent-effective-v2`；旧任务快照与历史范围保持原样，不改写历史证据。

## 3. 真实模型验收

| 模型 | 任务 ID | requested / actual | 用时 | 输出 | 结果 |
| --- | --- | --- | ---: | ---: | --- |
| DeepSeek V4 Flash | `6f4b6e6d-78d3-4588-938c-739d395549b7` | `deepseek/deepseek-v4-flash` | 约 177 秒 | 2580 字 | `ready / meets_target` |
| Qwen3.7-Plus 首次新契约 | `987638dc-0a44-46c9-96a7-8a096e5e6404` | `bailian/qwen3.7-plus` | 约 24 秒 | 1129 字 | 正确按 2125 下限拒绝；证明 final 已形成，但旧稿指令仍歧义 |
| Qwen3.7-Plus 修正旧稿语义后 | `afea995f-c338-40e8-8655-73327a7671ed` | `bailian/qwen3.7-plus` | 约 119 秒 | 2134 字 | `ready / meets_target` |

两份成功结果只保存为候选：

- DeepSeek candidate：`2a10bfb5-99e9-4a7f-84c5-d3023f076798`
- Qwen candidate：`8cfa4700-b471-425d-87be-0d544dda7c7b`

均未采用。正式正文保持 `draft_version=2`、1129 字、内容哈希 `bf55900b6c1075b645188c49d935f42562af2a0d9978f8b5aed59f85278ac597`。验收结束后 Agent 已恢复为用户原选择 `deepseek/deepseek-v4-flash`。

## 4. 自动化与运行验证

- Python：`tests/test_model_runtime.py`、`tests/test_api_model_orchestration.py`、`tests/test_generation_runtime.py`、`tests/test_skill_contract.py` 共 55 项通过。
- PostgreSQL 18 隔离库：字数 ±15%、低于、超过、合格及超时恢复 2 项通过；临时库已删除。
- 前端：TypeScript 通过；55 个测试文件、448 项测试通过；Vite 生产构建通过。
- QwenPaw：公开 `plugin validate` 通过，`plugin install --force` 热安装成功，PawApp health=`ready`。
- 浏览器：生成历史真实显示 `验收 2125–2875 字`，Qwen 2134 字与 DeepSeek 2580 字成功记录均可见；旧固定 `1000-1500` 新任务文案不存在。

## 5. 安全与恢复

- 没有修改 QwenPaw 核心、私有配置或私有数据库结构；模型切换与安装均使用公开 UI/API/插件命令。
- 没有新增 schema 或迁移，没有更改正式正文、revision 或故事事实。
- 失败任务和旧 1000–1500 快照继续保留为历史证据；新任务只走 `follow-agent-effective-v2`，不恢复固定 MiniMax 或双轨模式。
