# 运行观察

状态：聊天页探索样本完成1份；研究运行器已能安全保存完整结果并拒绝状态胶囊，但有效盲评样本仍为0份，批量生成保持停止。

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

## 第二次真实运行器哨兵

### `mystery-ab-runner-sentinel-v2` / X01

- 派发：新 session、新 run id，只请求一次，没有自动重试。
- 请求模型：`bigmodel / glm-5.3-flash`，来源为调用前公开 effective-model API。
- 流式结果：首事件320毫秒，末事件308.590秒，`stream_completed=true`。
- 结构计数：14,492个事件，其中 `text=14,485`、`agentresponse=3`、`message=2`、`reasoning=2`；未观察到 `tool_call` 或 `tool_result`。
- 最终状态：HTTP 502，`writing_evaluation_model_verification_failed`。
- 失败原因：closing assistant message 缺少 `qwenpaw_turn_usage`，不能核验 actual provider/model 或 token usage。
- 数据处理：没有保存正文，没有生成匿名评测样本，没有计入 A/B，也没有继续其余15个样本。

该请求完整结束且未触发600秒上限，因此本次不是 Provider 永久等待或可见工具循环；约5分9秒的长响应表明模型推理/生成时间本身足以显著影响墙钟时间，但不能仅凭第二次运行倒推首次600秒的唯一深层原因。

本机已安装 QwenPaw 的公开 `PawAppContext.chat_stream()` 只承诺返回异步事件流，`chat()` 只是把同一流聚合为 `ChatReply`。真实事件的 closing message 没有本项目原先假设的 `qwenpaw_turn_usage`。项目现有 `model_runtime.py` 虽有内部 usage buffer 兼容分支，但研究运行器按边界明确没有传入 session id；继续保持这一限制，不能依赖 QwenPaw 私有内部状态完成评测。

恢复后研究路由为404，QwenPaw 根页面、PawApp 注册表、项目健康接口为200，TTS Sidecar healthy，四个既有 TTS 验证字段与运行前逐项等值。运行窗口附近新增43条 `model_run_records`，全部关联 `narration.segment_render` 与 MOSS-TTS-Nano；新增两条 `document_revisions` 的 `source` 均为 `tts_snapshot`。这些是共享环境中的并行朗读写入，不是 X01 的写作评测记录；因此本轮不能使用“总表计数完全一致”措辞，只能说明未发现 X01 写入小说权威表的行级证据。

当前阻断已经从“看不见超时阶段”收敛为“公开 PawApp 返回不满足 actual/usage 审计合同”。在 QwenPaw 提供公开证据或用户另行裁决降低审计要求前，批量评测保持停止。

## 2026-08-28 用户裁决后的合同调整

用户同意不再因 QwenPaw 未公开 usage 而丢弃已完整生成的正文。调整后的证据边界是：生成前后各通过一次公开 effective-model API，provider/model 必须一致；公开 usage 存在时严格核验 actual，不存在时只能标记 `actual_model=not_exposed`、`usage=not_exposed`，不能把 effective 模型冒充 actual，也不能读取内部 usage buffer。

schema `1.1` 与 CLI 候选已完成，定向测试 `58 passed`、相关回归 `202 passed`、项目全量 `2445 passed, 116 skipped`，合同自检、Compose override 静态解析、Python 编译和 PawApp 本地打包通过。此处仍只是源码候选；第三次 X01 尚未派发，研究路由保持404，其余15个样本保持停止。

## 第三次真实运行器哨兵

### `mystery-ab-runner-sentinel-v3` / X01

- 派发：新 session、新 run id，只请求一次，没有自动重试。
- 技术结果：283.697秒后成功，`1 completed / 0 failed`；流完整结束，共14,560个事件。
- 公开模型证据：生成前后均为 `bigmodel / glm-5.3-flash`；actual provider/model 与 usage 没有公开，按合同保存为 `null + not_exposed`，没有读取私有 usage buffer。
- 输出证据：原始输出 SHA-256 为 `ec77f129fc177382140d727fb611e8e1e4552c151228d8b694439a95cb75019f`，非空白字符711，篇幅和四个固定锚点候选检查通过。
- 人工正文观察：第三人称限知稳定；饶真从索要开门转为先验证读数；联名责任和十五分钟停止条件构成代价；验证结果保持未知。
- 质量硬门槛：失败。正文末尾附加独立 `⟦…⟧` Agent 状态胶囊，概括评测约束和完成判断，违反“只输出正文”并破坏匿名盲评；现有自动包装检测器漏报。
- 处理：保留原始 `output.txt`、`result.json`、`hard-gates.json` 和匿名文件，不裁剪、不覆盖；新增 `semantic-review.json` 将样本标为盲评不可用。

研究窗口关闭后，研究开关已移除且路由为404；QwenPaw 根页面、PawApp 注册表和项目健康接口均为200，TTS Sidecar healthy，四个原有 TTS 验证字段逐项等值。恢复卷中的插件包与 PostgreSQL dump 哈希复核通过，临时副本已清理。运行窗口内新增的一条正式章节任务和一条 `outline_highlight` 任务来自共享环境的并行流程；研究路由不连接数据库，本次未读取其内容或干预状态。

结论：运行器已证明可以在公开 usage 不暴露时保存完整原始结果，但尚未证明能稳定产出纯正文评测样本。其余15个样本继续停止；下一次模型请求前先补状态胶囊检测和拒绝回归。

## 第四次真实运行器哨兵

### `mystery-ab-runner-sentinel-v4` / X01

- schema：`1.2`；纯净度合同：`writing-eval-output-purity-v1`。
- 技术结果：326.836秒后流完整结束，15,687个事件；生成前后公开模型均为 `bigmodel / glm-5.3-flash`，actual/usage 为 `not_exposed`。
- 自动门禁：末尾状态说明被识别为 `agent_status_capsule=true`、`output_purity_pass=false`；运行结果为 `0 completed / 1 failed`，原始输出保留，没有盲评文件和自动重试。
- 长度解释：完整输出非空白字符802；只读去除末行后的正文主体为661，符合500—800范围。原始证据没有被裁剪或转记为有效样本。
- 正文正向信号：视角、四锚点、策略变化、责任交换、停止条件和未知校准结果成立。
- 正文改进信号：临时引入检修短廊、十九分钟和偏差幅度来缩小缺口，存在未铺垫资源便利解题倾向。

自动化门禁为定向64项、相关228项、全量2451项通过，116项跳过；2条警告均为既有 Starlette 弃用警告。运行后研究入口404、项目健康200、QwenPaw/TTS Sidecar healthy，十一项数据库计数和迁移头前后相同，插件与 PostgreSQL 备份哈希复核一致。

连续两次真实 X01 都产生同类状态说明，说明它不是可以忽略的一次性噪声；新运行器已经能可靠拦截，但当前正式盲评有效样本仍为0。下一阶段不新增 Skill，只按开发计划第9节窄幅强化 `prose-writing` 和 `scene-craft`，先通过新合同下的 A/B 同题哨兵，再决定是否进入完整16样本。

## V2 同提示 Skill 包哨兵

`mystery-skill-ab-sentinel-v2-a` 在基线 `prose-writing` 哈希核对通过后派发 X01，但58.313秒后得到 `RemoteProtocolError`，没有正文。只读诊断确认请求期间唯一 QwenPaw 被共享 TTS 验收流程重建：容器创建于 `18:38:40Z`，客户端失败于 `18:38:43.858202Z`，新容器启动于 `18:38:44.417591047Z`。因此本次没有可评价文本，不能判断基线或候选写作质量。

冻结门禁要求任一侧失败即停止，故没有启动 X14/B，也没有自动重试。候选 `prose-writing`、`scene-craft` 已恢复，研究入口404，QwenPaw/PawApp健康、TTS Sidecar和原有TTS字段均恢复；共享数据库变化的元数据为 `tts_snapshot` 与 narration `update`，且新的 TTS 真实验收随即启动，本专项未读取其正文或改变状态。V2 有效样本仍为0。

## V2 无外部重建的600秒超时

`mystery-skill-ab-sentinel-v2b` 在无活动共享任务、最近两分钟项目模型记录为0、基线 Skill 哈希和 schema 1.3 合同均通过后，只派发 X01/A 一次。容器在请求窗口内未重建；首事件99毫秒，末事件599.944秒，共20,013个结构事件，公开流没有结束，服务端在600秒取消并返回 HTTP 504。项目 `model_run_records` 在该请求窗口新增0条。

没有正文、结果包、硬门禁或盲评文件，故不能评价基线文质。X14/B 未启动，没有自动重试。候选 Skill、关闭态、TTS 字段和健康状态已恢复；备份保留于 `/app/working.backups/writing-eval-skill-v2b-20260828-pre`。

## V3 第二组预登记哨兵合同

用户批准使用原16样本矩阵的 SP-02 attempt 2：X11/A 成功后才允许 X05/B。V3 不重试 X01，不延长600秒上限，不缩短或更换题面；SP-02 本身目标为500–800个非空白 Unicode 字符，因此前次超时不能归因于长章节必然耗时。

流诊断 `writing-eval-stream-diagnostics-v2` 只增加文本值数量/长度、末事件类型、assistant 消息数和公开 usage 封套数，仍固定 `content_recorded=false`，超时流正文不保存。V2 证据继续由不可变哈希回归保护。V3 真实调用只在源码、合同、打包、空闲和恢复门禁通过后串行执行。

## V3 X11 基线结果

X11/A 在500.567秒后完整结束，最终原始输出665个非空白字符，目标篇幅和四个锚点字符串通过，但末尾再次附加独立状态胶囊，复述封套、篇幅、锚点、策略和禁项检查。自动门禁判定 `agent_status_capsule=true`、`output_purity_pass=false`；原文保留、不裁剪、不进入盲评。

诊断 v2 记录18,011个事件，最大单个公开文本值52,535字符、累计观察值212,900字符；这些是流事件字符串长度计数，不等于最终正文长度，且没有保存诊断正文。生成前后公开模型一致，actual/usage 未公开。按规则 X05/B 未启动。运行窗口内42条项目模型记录全部属于 `narration.segment_render`；研究路由无项目数据库持久化。恢复后候选 Skill 哈希、普通关闭态和健康状态正确。

## X05/B 候选缺陷检查

用户批准采用轻量、单样本方式先验证候选，而不继续堆规则或直接跑八份正文。独立 run `mystery-skill-candidate-remediation-v3-x05` 只调用 X05/B 一次；它与 V3 使用同一冻结题面和候选 Skill 身份，但明确不计作被冻结顺序中的 V3 A/B 结果。

流在314.754秒完整结束，共14,179个事件；首次事件188毫秒，末事件类型为 `agentresponse`。事件中观察到 `plugin_call=2`、`plugin_call_output=2`，诊断仍只保留结构和长度计数、不保存诊断正文。公开文本值最大单值35,130字符、累计158,432字符，不等于最终733个非空白字符的原始输出。生成前后公开模型一致，actual/usage 未公开。

篇幅和四个字符串锚点通过，但原始输出末尾仍出现状态胶囊，自动门禁正确标记 `agent_status_capsule=true` 并拒绝。请求窗口内项目 `model_run_records` 为0；恢复后研究入口404、QwenPaw根页面与PawApp健康为200、QwenPaw和TTS Sidecar均healthy，目标 Agent 与插件包内候选哈希一致。候选缺陷未修复，后续质量样本停止。
