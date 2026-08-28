# 写作研究运行器

状态：schema 1.4 源码候选；默认关闭；V3 基线与独立 X05 候选缺陷检查均因末尾状态胶囊未通过纯净度门禁；正式盲评有效样本仍为0，批量保持停止。

2026-08-27 源码门禁：冻结合同/API/CLI 新增测试 `52 passed`，相关定向回归 `166 passed`，项目全量回归 `2376 passed, 116 skipped`；合同自检、Compose override 配置解析和 PawApp 打包通过。以上只证明运行器候选可进入真实哨兵，不证明模型侧链路或写作质量已经通过。

首次真实哨兵 run id 为 `mystery-ab-runner-sentinel-v1`。固定合同和路由预检通过后只派发 X01 一次，最终得到 HTTP 504，结果为 `0 completed / 1 failed`；没有正文、actual 模型或 token usage，运行器未重试。前后小说权威表计数一致，研究入口已恢复404，原生根页面、PawApp 注册表和项目健康接口均为200。该结果只证明超时失败被安全收口，不批准继续16样本。

## 作用范围

运行器只执行 `mystery-ab-20260827-v1` 已登记的16个项目合成样本。HTTP 不接受 prompt、题面、小说正文、文件路径、Agent、Skill、Provider、模型或采样参数；服务端不连接小说数据库，也不创建候选、revision 或故事事实。

后端固定使用 `ai-novel-writer` 与 `prose-writing`，在可信 `chapter_generation` 任务模式下以提示约束禁止工具和持久化。调用前后保存公开 effective 模型；公开 closing reply 含合法 usage 时核验 actual 模型与 token，未暴露时透明保存 `actual_model=null`、`usage=null` 与 `not_exposed`，前后模型不一致或证据状态矛盾时样本作废。运行器不使用 QwenPaw 内部 usage buffer。

## 默认关闭

普通 `compose.yaml` 不传研究开关，路由返回404。短期研究窗口使用独立 override：

```bash
docker compose -f compose.yaml -f docker/writing-eval.compose.yaml config
docker compose -f compose.yaml -f docker/writing-eval.compose.yaml up -d qwenpaw
```

研究结束后使用普通 Compose 重建 `qwenpaw`，移除开关：

```bash
docker compose -f compose.yaml up -d --force-recreate qwenpaw
```

启停共享 QwenPaw 运行环境属于串行操作；真实执行前必须先完成打包、安装与原生功能非回归，不能在其他专项正在操作唯一运行环境时切换。

## 主机命令

先验证冻结合同，不调用模型：

```bash
.venv/bin/python scripts/run_writing_eval.py verify-contract
```

真实运行必须明确承认模型调用成本。先做单个哨兵：

```bash
.venv/bin/python scripts/run_writing_eval.py run \
  --run-id mystery-ab-runner-sentinel-v1 \
  --sample X01 \
  --acknowledge-model-cost
```

同一 run 继续时必须显式 `--resume`。已有完整且哈希一致的样本会跳过；存在 dispatch 后无结果或失败记录时不会自动重试，必须保留旧 run 并另行裁决。

```bash
.venv/bin/python scripts/run_writing_eval.py run \
  --run-id mystery-ab-20260827-run1 \
  --acknowledge-model-cost

.venv/bin/python scripts/run_writing_eval.py status \
  --run-id mystery-ab-20260827-run1

.venv/bin/python scripts/run_writing_eval.py verify \
  --run-id mystery-ab-20260827-run1
```

## 证据

每个 run 保存 `plan.json`、`summary.json`、逐样本 prompt、正文、模型证据、硬门槛候选和匿名样本。模型失败、超时、身份缺失、模型漂移、保存中断和硬门槛失败都保留，不自动重抽样。

程序只直接判断空输出、NFC 后非空白字符数和明确包装；锚点、人物知识、视角、禁止新增、状态变化和悬疑机制仍需匿名人工复核。

## 超时诊断合同

2026-08-28 的源码修复改用公开 `ctx.chat_stream()`。服务端只记录事件类型、消息角色、内容块类型及首末事件耗时的有界计数，固定 `content_recorded=false`，不把推理、正文片段、工具参数或文件内容放进诊断响应。

每次结果或失败都必须如实记录：Skill 只是通过 `PawAppContext` 参数请求，工具限制只是 `prompt_only`，不能写成宿主已经强制禁用工具。失败响应携带 session id、开始时间和流式结构摘要；CLI 保存受64 KiB上限保护的 JSON 错误正文、HTTP状态、正文哈希和客户端耗时。该修复只补观测能力，不批准真实重跑。

本次诊断修复的模拟定向测试为 `54 passed`，项目全量回归为 `2436 passed, 116 skipped`；合同自检、Compose override 静态解析、Python 编译和 PawApp 本地打包通过。验证过程没有启用研究入口、安装插件或发起模型调用。

## 第二次流式哨兵

`mystery-ab-runner-sentinel-v2` 只派发 X01 一次。响应流于308.590秒完整结束，共14,492个结构事件；没有观察到工具调用类型，也没有触发600秒超时。随后模型身份核验失败并返回 HTTP 502，因为 closing assistant message 缺少 `qwenpaw_turn_usage`。运行器按合同没有保存正文、actual 模型或 token usage，也没有重试。

该结果证明流式观测已能区分“流没有结束”与“流结束后证据不足”，但也证明当前冻结成功条件无法通过公开 PawApp 合同满足。不得改用私有 usage buffer，也不得把调用前 effective 模型当作 actual 模型。其余15个样本继续停止。

运行窗口结束后研究路由恢复404，QwenPaw/PawApp/项目健康接口正常，TTS Sidecar healthy，原有 TTS 验证字段等值恢复。共享环境同时产生43条 TTS segment render 模型记录和两条 `tts_snapshot` 正文版本；行级类型表明它们来自并行朗读流程，不能写成评测运行前后总表计数完全一致。

## 公开模型前后核对合同

用户已批准在 QwenPaw 不公开 usage 时保留完整正文。新 schema `1.1` 要求生成前后的公开 effective 模型 provider/model 完全一致；如公开 reply 含 usage，仍严格核验 actual，若不含则保存 `actual_model=null`、`usage=null` 并标记 `not_exposed`。任何情况下都记录 `private_usage_buffer_used=false`，不读取内部 usage buffer。

该合同降低的是模型用量证据门槛，不降低正文质量门槛，也不把 effective 模型表述成 actual 模型。源码定向测试 `58 passed`、相关回归 `202 passed`、项目全量 `2445 passed, 116 skipped`；合同自检、Compose override 静态解析、Python 编译和 PawApp 本地打包通过。第三次 X01 只有在备份和恢复门禁通过后执行，其余15个样本不启动。

## 第三次哨兵与纯净度阻断

`mystery-ab-runner-sentinel-v3` 只派发 X01 一次，在 283.697 秒后成功保存完整原始输出。流完整结束，共14,560个事件；生成前后公开 effective 模型均为 `bigmodel/glm-5.3-flash`。公开 actual/usage 未暴露，结果按 schema `1.1` 保存为 `null + not_exposed`，没有读取私有 usage buffer。

技术成功不等于评测样本有效。人工复核发现正文末尾附有独立 `⟦…⟧` 状态胶囊，概括了题目锚点、状态变化和完成判断，违反“只输出正文”并泄漏评测信息。现有自动 wrapper 检测漏报；原始结果未裁剪，另以 `semantic-review.json` 将该样本标记为硬门槛失败和盲评不可用。正文主体虽呈现稳定视角、策略变化、代价和未决结果，也不能抵消纯净度失败或证明 Skill 已提升。

研究路由已恢复404，健康检查和原有 TTS 验证配置均已恢复，恢复备份保留，临时副本已清理。下一次模型请求前必须先让运行器显式检测并拒绝末尾状态胶囊；其余15个样本继续停止。

## schema 1.2 纯净度门禁与第四次哨兵

运行器现使用 `writing-eval-output-purity-v1`：本地重新计算确定性检查，识别末尾独立 `⟦…⟧`／`⟧…⟧` 状态说明；污染原文、结果和哈希照常保存，但不创建盲评文件、不计完成、不自动重试。普通正文内部括号不触发该规则。v3 原始输出只读回放已命中，原文件未修改。

`mystery-ab-runner-sentinel-v4` 只派发 X01 一次，326.836秒后完整结束。模型生成前后公开身份均为 `bigmodel/glm-5.3-flash`，actual/usage 未公开并透明标记。输出再次附加状态说明，新门禁正确返回 `0 completed / 1 failed`，保留 `output.txt`、`result.json`、`hard-gates.json` 和 `failure.json`，没有生成 `blind-samples/X01.md`，其余15项没有启动。

自动化为定向64项、相关228项、全量2451项通过（116项跳过、2条既有警告）。研究入口已恢复404，项目健康恢复200，数据库计数前后相同，备份保留。正式 Skill 优化方案见开发计划第9节；在新 prompt contract 和两个目标 Skill 候选完成前，批量仍停止。

## V2 同提示 Skill 包对照

新实验 `mystery-skill-ab-20260828-v2` 使用 schema `1.3` 与 `writing-eval-prompt-v2`。A/B 不再通过不同 prompt overlay 制造差异：同 case、同 attempt 的 prompt 必须逐字节相同，A 只接受冻结基线 `prose-writing` 哈希，B 只接受候选哈希。服务端在调用模型前核对 PawApp 包内 Skill 文件；错配返回 `writing_evaluation_skill_variant_mismatch` 与 `model_called=false`，CLI 再核对 `writing-eval-skill-package-sha256-v1` 证据。

冻结 manifest、variant policy 和基线 Skill 原文位于 `experiments/mystery-skill-ab-20260828-v2/`。V1 manifest/overlay 由旧哈希回归保护，历史运行证据保持只读。V2 自动化相关231项、全量2459项通过（116项跳过、2条既有警告），Skill quick validator、编译、合同自检、打包、Compose 静态解析和 diff 检查通过。

V2 A 侧随后以 `mystery-skill-ab-sentinel-v2-a` 派发 X01。调用前基线 Skill 哈希、合同、备份、健康和 TTS 字段均通过；但请求窗口内另一项 TTS 流程重建唯一 QwenPaw，客户端在58.313秒后得到 `RemoteProtocolError`，没有正文或结果包。容器创建、启动与客户端失败时间构成直接证据，不能归因于 Skill 质量。

运行器保留 `0 completed / 1 failed` 且未自动重试；按任一侧失败即停止的冻结规则，X14/B 未启动。候选两个 Skill 已恢复，研究入口为404，根页面和 PawApp 健康为200，TTS Sidecar healthy，既有 TTS 字段等值恢复，备份保留。下一轮 TTS 真实验收已再次占用共享锁，因此本轮不创建新 run 重试。X01/X14 只显式调用 `prose-writing`，不能把 `scene-craft` 候选质量写成已经由该哨兵验证。

## V2 新运行的600秒流超时

用户明确要求继续后，新 run `mystery-skill-ab-sentinel-v2b` 在无活动 TTS/写作评测进程、最近两分钟项目模型记录为0、基线 Skill 哈希与 schema 1.3 合同一致的条件下，只派发 X01/A 一次。该请求没有发生 QwenPaw 重建或断连；公开模型流在99毫秒出现首事件，持续到599.944秒，共观察到20,013个结构事件，但始终没有完成信号，最终由固定600秒服务端门禁取消并返回 HTTP 504。

本次没有可保存正文、结果包、硬门禁或盲评样本，不能评价基线文质，也不能将超时归因于候选 Skill。运行器保持 `0 completed / 1 failed`、不重试，X14/B 未启动。候选 Skill 已恢复，研究入口恢复404，QwenPaw/PawApp/TTS Sidecar 健康，TTS 运行字段等值恢复；新备份保留于 `/app/working.backups/writing-eval-skill-v2b-20260828-pre`。下一次真实模型调用前必须先裁决“保持一次调用不重抽样”与“如何取得可完成的基线样本”，不得通过偷偷延长超时、裁剪未完成流或把超时计作写作质量分数绕过可比性门禁。

## V3 第二组预登记哨兵

用户已批准 `mystery-skill-ab-20260828-v3` 使用原16样本矩阵中预登记的 SP-02 attempt 2，固定顺序 X11/A→X05/B。它不是 X01 的重试：V2 两次 X01 失败保持不可变，V3 有独立 experiment、manifest、策略和 run id；X11 失败即停止，X05 不启动。题面、500–800字符目标、最终输出要求、600秒服务端上限及基线/候选 Skill 哈希保持不变。

`writing-eval-stream-diagnostics-v2` 在不记录正文的前提下增加文本值数量/长度、末事件类型、assistant 消息数和公开 usage 封套数。它只能帮助区分大量重复/累计文本事件、缺少结束消息和正常完成，不能从长度计数恢复正文，也不能替代质量审阅。冻结文件位于 `experiments/mystery-skill-ab-20260828-v3/`；variant policy SHA-256 为 `6e64c9590c330ac89a2a48c79bc6aa989bb86a0237b3d7f36feef05537f9a4db`，manifest SHA-256 为 `e0019fc951819c2fc40055cd7e866d2ec15a1602ea99fcdc023d643d76838cd4`。

### V3 实际结果

`mystery-skill-ab-sentinel-v3a` 只派发 X11/A。公开流在500.567秒后完整结束，最终原始输出665个非空白字符、四锚点和目标篇幅通过，但末尾再次出现独立状态胶囊；纯净度门禁正确返回 `0 completed / 1 failed`，没有盲评文件。诊断 v2 保存18,011个事件及长度计数，不保存诊断正文。按冻结顺序门禁，X05/B 未启动。

候选 Skill 和普通关闭态已恢复，研究入口404，QwenPaw/PawApp/TTS Sidecar健康，备份保留。请求窗口的42条项目模型记录全部关联 `narration.segment_render`，不是研究路由持久化。V3 证明第二次预登记基线能够完整返回，也再次复现基线状态胶囊；它仍没有候选输出，不能形成 A/B 质量结论。

## X05 候选缺陷修复检查

`mystery-skill-candidate-remediation-v3-x05` 是用户批准的独立、单样本候选检查，不是 V3 冻结顺序的续跑。它只派发 X05/B 一次，沿用同一 SP-02 attempt 2 题面和 schema 1.4 合同，不重试、不改题、不延长600秒上限，也不进入完整矩阵。

公开流在314.754秒后完整结束，共14,179个事件。候选 Skill 哈希核对通过，生成前后公开 effective 模型均为 `bigmodel/glm-5.3-flash`，actual/usage 未公开。输出733个非空白字符，目标篇幅与四锚点通过，但末尾仍有独立 `⟦…⟧` 状态胶囊；纯净度门禁返回 `0 completed / 1 failed`，没有盲评文件。该检查否定了“候选已修复状态胶囊”，不形成 A/B 文质结论，后续四场景评测不启动。

运行后候选哈希、普通关闭态和健康状态恢复，研究入口404；请求时间窗内项目 `model_run_records` 为0。证据见 `runs/mystery-skill-candidate-remediation-v3-x05/`。
