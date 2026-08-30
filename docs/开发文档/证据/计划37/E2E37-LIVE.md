# E2E37-LIVE：长期 PawApp 与真实写作链裁决

日期：2026-08-30（Asia/Shanghai）

状态：`PASS_WITH_CONTENT_REVIEW_RISK`（2026-08-30 完成长度闭环、三章真实复测和最终安装验收）

范围：计划 37 的非 TTS 写作链、向量 V1 索引和三视口只读验收。TTS/朗读/声音/Nano 明确未测试；Git 未提交、未推送。

## 一、部署与恢复证据

- TTS 计划确认只在独立 worktree 施工，未占用长期 PawApp、浏览器或安装/重启锁后，才执行长期环境操作。
- 安装前备份位于仓库外：`/Users/liujia/Documents/AI小说世界2026-backups/plan37-20260829-live-e2e`。
- 备份包含 PostgreSQL custom dump、原插件目录、迁移头记录和 SHA-256 清单；恢复时先停止写入，再恢复插件目录及数据库 dump。
- 候选包通过公开插件安装路径安装；长期容器恢复为 `healthy`，PawApp health 为 `ready`。
- 原有 TTS runtime/product 环境开关原样保留，但未进入任何 TTS 页面、接口或验收流程。一个仅属于 TTS 的 keyring bootstrap 返回 `DIGEST_KEYRING_SCHEMA_NOT_READY` 后即停止该步骤，没有改写写作 schema，也不用于本计划裁决。

## 二、真实模型与向量基线

- 当前公开有效正文模型：`minimax-cn / MiniMax-M3`，公开有效输入窗口 `1000000`。本文件保留前述 `bailian / qwen3.8-max` 失败记录作为历史证据。
- 向量模型：`qwen3.7-text-embedding`，Dense 维度 `2048`；active generation 为 `4e74dff1-74d0-4e42-a96e-5f9af34c5cdd`。
- 新建合成实验小说：`5207d392-2471-4211-9bb0-26da0006c479`；只处理该实验小说，没有读取或修改真实用户小说。
- v2 云端授权生效后，初始索引收敛为 `ready/current`：`index_version=4`、3 个 current source、3 个 chunk、0 个失败；语料为 2 个 planning source 和 1 个绑定私有素材 source。因为正文尚未成功采用，manuscript source 合法为空。
- 全局向量页显示服务商阿里云百炼、DashScope Native、固定 2048 维和正常连接；API Key 输入框为空，只显示脱敏状态，未回显明文。

## 三、三次真实正文调用

真实正文调用严格限定为计划授权的三次，没有发起第四次：

| 次数 | generation job | 用时 | 结果 |
| --- | --- | ---: | --- |
| 1 | `6de3ef40-a848-4a2e-9f54-7fe004139430` | 241409 ms | failed，0 字，无 final |
| 2 | `54b24b09-0cb6-4eac-868e-1de0a2452e48` | 208750 ms | failed，0 字，无 final |
| 3 | `0a8a34b1-299a-46e2-b9ec-bae5120852cd` | 218650 ms | failed，0 字，无 final |

三次任务均冻结 2000 字目标和 1700–2300 字验收范围。公开模型证据均为 `model-execution-evidence/2` 的合法 `not_exposed`：preflight/postflight 都是 `bailian / qwen3.8-max`，宿主没有公开 actual model、usage、Token 或 provider request ID，因此这些字段保持空，而不是伪造为已验证。

第三次新增的脱敏结构诊断为 `chunks=11,responses={}|{}|{},standalone=none`：公开回复产生了事件，但 closing AgentResponse 没有 output，也没有可作为最终正文的独立 completed assistant Message。诊断不保存正文、reasoning、tool 参数或完整消息内容。

裁决：这是当前正文 Agent 输出链的真实阻断。失败路径正确地拒绝空结果，没有创建候选、没有采用正文、没有写入 StoryFact，也没有发布错误的 manuscript 向量来源。实验小说仍为 0 正文字、1 个空章节。

### 3.1 切换到 MiniMax-M3 后的第二轮授权复测

作者切换有效正文模型后，公开 preflight 为 `minimax-cn / MiniMax-M3`，有效输入窗口 `1000000`。第二轮再次严格限制三次正文调用：

| 次数 | generation job | 用时 | 输出 | 裁决 |
| --- | --- | ---: | ---: | --- |
| 1 | `6eeceab1-db6c-4083-b531-1e855c2cddca` | 17211 ms | 2059 字 | `ready/meets_target`，候选已采用 |
| 2 | `6e7eedbb-97e6-43e4-8206-146606bdc416` | 17005 ms | 3387 字 | `failed/above_target`，超过 2300 上限 |
| 3 | `3e4c2a88-604b-4c10-9792-0ea06479db90` | 42692 ms | 3959 字 | `failed/above_target`，超过 2300 上限 |

三次均获得独立 final，且公开模型证据都是合法 `not_exposed`：preflight/postflight 均为 MiniMax-M3，actual 字段保持空。由此可以排除旧模型的“没有 final”故障，但暴露出 MiniMax-M3 在当前章节 prompt 中不稳定遵守正文长度硬范围。

第一章采用后的权威结果：

- 正文 2059 个可见字符，正式 working copy/revision 更新成功；
- `青铜第七码`、`出生记录`、`知情范围` 三个必要锚点存在；
- `黑曜雨燕`、`朱砂鲸`、`白鸥钥匙`、`退役版本哨兵`、`他书来源哨兵` 均未出现；
- active index 从 version 4 收敛到 version 5，authority/published digest 一致；
- manuscript corpus 为 1 个 current source、11 个 chunk、0 失败；总计 4 个 source、14 个 chunk。

第二章两次任务的冻结 `WritingContextSnapshotV2` 均为 hybrid、generation `4e74dff1-74d0-4e42-a96e-5f9af34c5cdd`、index version 5，并命中：第一章 current `chapter_revision`、当前固定私有素材、正式 outline 和 setting。两次均保存 provider request ID、Token 和延迟证据，`degraded_reason=null`。这证明向量检索已经真实进入正文生成主链，而非只在手动搜索页面可用。

第二章两次超长结果均未产生 candidate，第二章仍为 0 字、初始 revision/hash 未变；索引继续保持 version 5 和第一章唯一 manuscript source。即使在章纲中追加“必须 1700–2300 字、禁止额外支线”，第三次仍输出 3959 字，因此不能把问题归因于缺少一次简单的长度提示。

## 四、窄修复与验证

为提高可诊断性并避免错判，完成以下窄修复：

1. 正文 prompt 明确要求本轮必须返回独立 final 正文，不能停在计划、工具、等待或自检状态。
2. 模型运行时只保存有界的结构诊断；不记录消息正文或隐私内容。
3. 按 QwenPaw 公开 `ChatReply` 契约，在 closing AgentResponse.output 为空时，仅允许最后一条独立 completed assistant Message 作为严格 fallback；reasoning、tool、delta 和旧响应仍被拒绝。
4. 生成历史的失败卡也统一使用 V2 模型证据文案；`not_exposed` 显示“宿主未公开实际模型；任务前后有效模型一致”，不再退回“实际未核验”的旧标签。

相关后端专项测试：`61 passed`。第三次真实调用仍没有 standalone Message，说明本次阻断不是前端文案或 final 提取器误分类造成的。

## 五、安装后三视口结果

- `390×844`：大纲工作台主区域可纵向滚动，底部“下一步”操作可达；根页面无横向溢出。
- `1920×1080`：角色列表与 900px 正式人物卡可打开；基础资料、本线档案、成长与状态正常，成长页保持确定性只读；正文空态和三次失败历史可见。
- `390×844`：正式人物卡为全屏，无横向溢出；未点击“声音”页签。
- 小说语义索引卡：v2 查询文本披露、2048 维、generation 12、index version 4、3/3/0 来源/分块/失败和各 V1 corpus 状态可见。
- `2560×1440`、`1920×1080`、`390×844`：全局向量配置页均无横向溢出，Key 未明文回显。

由于真实正文 3/3 未形成候选，正文成功态、连续三章召回、采用后增量 manuscript 索引、StoryFact 同步、真实审稿和选区链不能继续，均记为 `BLOCKED`，不得伪装为已验收。

## 六、历史阶段影响与后续边界

- **已改善**：MiniMax-M3 能稳定返回 final；第一章 2059 字候选已通过并采用，旧模型的空 final 阻断不再出现。
- **仍受影响**：MiniMax-M3 的章节长度遵守不稳定，第二章连续两次超长，因此三章连续 AI 写作闭环仍不可发布为可用。
- **已证实可用**：人工写作与保存、正式大纲/人物卡/账本读取、向量配置、V1 增量索引、手动 hybrid 检索、写作任务自动 hybrid 检索及失败数据保护。
- **未裁决**：TTS 全部能力；它必须回到计划 35 单独验收。
- 下一步应针对“模型输出严重超长”建立独立失败回归并裁决长度控制策略；优先比较更明确的分段预算／输出收束契约，以及在不改写原候选的前提下生成新的受控重写任务。不能通过放宽 1700–2300 门禁、截断正文、接受超长候选或绕过模型证据获得 PASS。再次真实调用需新的当次授权。

## 七、长度闭环修复与真实复测

作者随后授权继续真实测试。施工没有修改 QwenPaw 上游，也没有使用模型级全局 `max_tokens`：QwenPaw 2.1.0 的公开 PawApp `ctx.chat` 契约不提供单次输出上限，临时修改共享模型配置会产生并发串扰和崩溃残留，故明确拒绝该方案。

本轮实现 `chapter-prose-candidate/v3` 与 `follow-agent-effective-v6`：

- 初次及重试继续冻结 1700–2300 字最终验收范围，不截断、不接受超长候选、不以摘要代替正文；
- 长度失败返回结构化 `chapter_length_out_of_range`，前端不再匹配中文错误文本；
- 同 document、brief、base revision、working draft/hash、模型和冻结窗口的失败任务才能形成重试谱系；
- 每次重试保存 root/previous job、轮次、上次实际字数和增减差值；
- 依据 `requested² / previous_actual` 生成受限的 drafting anchor，但最终硬门禁保持不变；
- 单次作者确认最多执行三次完整生成，UI 明确披露，不形成隐藏无限调用；
- 采用时重新计算候选真实可见字符并核对冻结上下限，防止伪造 job count 绕过门禁。

第二章在只加入普通数字反馈时，三次自动重写仍分别为 3829、2529、3377 字，均被安全拒绝，正式正文、revision、StoryFact 和 current 向量来源保持不变。加入校准 drafting anchor 并重新安装后，下一次生成一次成功：

| 章节 | document | generation job | 正式 revision | 可见字符 | 结果 |
| --- | --- | --- | --- | ---: | --- |
| 第一章 | `fc36bc1e-9b63-44a7-8ee6-dc93f32f7128` | `6eeceab1-db6c-4083-b531-1e855c2cddca` | `d9be6297-3ea9-42ac-b72c-702ff24cecd4` | 2059 | adopted |
| 第二章 | `328f5b16-2e9f-4ed0-acda-d0d0ccae10f5` | `7f623d45-17be-49fe-a9bd-e06268e11f83` | `4dc4b184-f942-495c-aa00-feafd52985fc` | 1783 | adopted |
| 第三章 | `03aac0e7-645a-49b0-a26b-af05a7877787` | `b29d6a26-b116-4010-a17d-0e37554bdd8a` | `d2feb93f-3858-423b-91ee-7846f0fa34ec` | 2128 | adopted |

第二章成功任务冻结 retry round 5、previous 3377 和 calibrated drafting anchor 1184；这只是生成锚点，不改变 1700–2300 的最终验收范围。第三章首次任务直接得到 2128 字合法候选。

## 八、向量、隔离与内容裁决

第三章 `WritingContextSnapshotV2` 使用 hybrid 检索，固定 active generation `4e74dff1-74d0-4e42-a96e-5f9af34c5cdd` 和当时 index version 6；证据精确包含：

- 第一章 current revision `d9be6297-3ea9-42ac-b72c-702ff24cecd4`；
- 第二章 current revision `4dc4b184-f942-495c-aa00-feafd52985fc`；
- 当前正式 outline、setting 和绑定私有素材版本。

第三章正式化后 active index 收敛到 version 7，`authority_digest == published_digest`、`pending_refresh_count=0`：

| corpus | sources | chunks | failures |
| --- | ---: | ---: | ---: |
| manuscript | 3 | 33 | 0 |
| planning | 2 | 2 | 0 |
| private_asset | 1 | 1 | 0 |

`character / relationship / story_event / storyline / foreshadow / timeline` 仍按冻结边界保持 disabled。三章正文未出现 `黑曜雨燕`、`朱砂鲸`、`白鸥钥匙`、`退役版本哨兵` 或 `他书来源哨兵`，没有未来章节、兄弟时间线、失效 revision 或未绑定素材泄漏。

内容质量另有一项真实发现：第三章虽包含 `青铜第七码`、`F-04-补` 和 `林砥`，却把章纲明确要求的“林渡与旧名林砥是同一人”解释成了父女关系，违反“禁止把林渡与林砥写成两个人”。这不是稳定 ID、人物实例或向量来源错绑；人物档案同时给出“真名是林砥”和“海灯编码设计者的孩子”，而模型仍对组合约束作了错误推理。正常产品流程中正文先形成候选、由作者审阅后才采用；本次为链路 E2E 才执行自动采用。结论是：**工程链路可发布，真实内容仍必须作者审阅；不得增加未经批准的关键词权威判定来伪装语义正确。**

## 九、最终自动化、安装与三视口

- 隔离 PostgreSQL：`826 passed, 36 skipped, 2 deselected, 3 warnings`。两项 deselect 是 `tests/test_qwenpaw_integration_contract.py` 中只验证 TTS 安装意图的用例；36 项 skip 也是环境条件用例，不是写作失败。
- 非 TTS 前端：55 个文件、402 项测试全部通过。
- `pnpm typecheck`、`pnpm build`、`docker compose config --quiet`、`.venv/bin/python scripts/package_plugin.py`、`git diff --check` 全部通过。
- 最终包与长期安装目录的 `backend/services.py`、`backend/model_runtime.py`、`frontend/dist/index.js` SHA-256 完全一致。
- 长期 PawApp `health=ready`、PostgreSQL connected、embedding runtime ready；公开正文模型为 `minimax-cn / MiniMax-M3`。
- `1920×1080`、`2560×1440`、`390×844` 的第三章工作台均显示 2128 字、审稿／情报和写作工作流操作，根页面无横向溢出；移动窄屏保持纵向可读。浏览器视口随后恢复默认。
- 备份位于仓库外 `/Users/liujia/Documents/AI小说世界2026-backups/plan37-20260830-length-control`，包含数据库 dump、安装前插件、迁移头和 SHA-256 清单。

TTS、朗读、声音、Nano 和播放器仍全部 `OUT_OF_SCOPE`，没有因此修改或验收；Git 仍未提交、未推送。
