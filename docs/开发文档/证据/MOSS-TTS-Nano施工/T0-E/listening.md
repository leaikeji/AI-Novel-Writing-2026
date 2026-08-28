# T0-E 24 槽候选听感、去重与锁定记录

> **适用范围更正（2026-08-27）：** 本文下方的 24 槽 VoiceGenerator／授权录音听检模板及公众人物相似风险规则，只适用于该候选音色包与商业发布／再分发审计；它不再限制固定 ONNX manifest 的 18 个 `official_preset`。全部官方预设均可进入个人本地试听与 T4-K 三角色听检，包括 `Trump`、`Xiaoyu`。现行裁决见 [个人本地版官方预设裁决](./local-personal-official-presets.md)，下文历史模板不重写。

> 状态：**未开始真实听检；0/48 候选已生成，0/24 槽已锁定**
>
> 本文不得因为 schema、描述文本或模型元数据存在就填写 `pass`。

## 当前阻断

- T0-C 已完成真实 Nano 20/20 技术矩阵与独立句段技术检查，但人工听感、24 音色候选和真实 reference clone 仍无通过证据。
- 冻结产品 fixture 的 3/5/8/12 秒参考录音仍是 `placeholder_only/not_supplied`；仓库外 isolated-test-only 技术候选不得替换 fixture，也不得用网络音频、用户私有录音或未授权素材冒充产品资产。
- T0-D 元数据/代码路径尖刺已建议在 M4/16 GB 上隐藏 VoiceGenerator；模型下载、模型加载、候选生成和 Nano 二次克隆均为 0。
- `voice-pack-manifest.json` 里的 48 个 candidate ID 只是不可变名额，没有音频、hash、授权或听感结果。
- **[历史商业发布／再分发候选池记录，非个人本地门禁]** 原听检池只接受 16/18，并排除 `Trump` 与 `Xiaoyu/CN 明星`。该排除已经失效；个人本地 T4-K 可试听并使用全部 18 项官方预设。分发／商用／24 槽生产状态仍未评估，但只作信息记录。

## 真实听检的前置输入

1. 先由独立后续门禁把 T0-D 从 `hide` 重新裁决为可用；之后才可在仓库外受控媒体目录为每槽生成两个候选，总数 48。每个保存模型 revision、参数、seed、描述 hash、原始输出 hash 和资源记录。
2. 每个未来 24 槽／VoiceGenerator／外部参考候选先经权利/相似审查；公众人物、知名角色、可识别真人或来源不明者不进入该商业候选听感池。本规则不筛除固定 ONNX manifest 的个人本地官方预设。
3. 用固定 T0-I 语料进行 Nano 二次克隆。通用稳定性用 `txt-reference-prompt`、`txt-independent-1..3`；槽位适配再用对应的 `txt-anon-child`、`txt-anon-young`、`txt-anon-middle-aged`、`txt-anon-elder`、`txt-crowd`。不在证据文档复制正文。
4. 用同一 Nano revision、解码/后处理参数、音量和监听设备；乱序候选，隐藏候选来源和变体字母。
5. 证据目录只记 candidate ID、音频 hash、脱敏评分和审阅者代号；原始/克隆音频留在受控媒体目录，不进 Git。

## 单候选听检维度

| 维度 | 记录 | 接受门槛 |
| --- | --- | --- |
| 漏字/重复/错读 | 是/否 + 用例 ID | 任一稳定复现即拒绝或返修 |
| 爆音、噪声、削波 | 是/否 + 检查摘要 | 不得有影响阅读的缺陷 |
| 异常停顿/语速 | 1–5 + 说明 | ≥ 4 |
| 普通话清晰度 | 1–5 | ≥ 4 |
| 自然度 | 1–5 | ≥ 4 |
| 槽位年龄/声线气质适配 | 1–5 | ≥ 4；不能只根据 prompt 填写 |
| 独立句段一致性 | 1–5 + 飘移标记 | ≥ 4，且无明显身份飘移 |
| VoiceGenerator → Nano 保持度 | 1–5 | ≥ 4 |
| 真人/公众人物/角色相似风险（仅 24 槽／生成／外部候选） | 无/不确定/有 | 只接受“无”；不确定亦阻断；不用于官方预设目录筛选 |
| 审阅者 | 代号、时间、设备 | 至少 1 位实际审听人；有分歧或不确定时增加第 2 位 |

## 跨槽去重规则

自动特征只用于提示，不作最终结论。审听人必须检查：

- 所有同年龄/同声线类别内的 A/B/C 成对比较；
- 与相邻年龄类别比较，特别是少年↔青年、青年↔中年、中年↔老年；
- 与中性/未知槽和群体代表槽比较；
- 体感年龄、声线呈现、中值音高/范围、明暗/厚薄、气声/沙质、语速、韵律、口音/发音、跨句身份稳定和同场景可混淆度共 10 个维度；
- 若听感上两个槽位容易被认为同一人，至少替换其中一个候选，不得用标签差异解释为“已去重”。

## 24 槽听感状态

| # | slot_id | 候选 1 | 候选 2 | 已选 | 去重 | 锁定 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `generic.child.male.a` | not_generated | not_generated | — | not_tested | unlocked |
| 2 | `generic.child.female.a` | not_generated | not_generated | — | not_tested | unlocked |
| 3 | `generic.adolescent.male.a` | not_generated | not_generated | — | not_tested | unlocked |
| 4 | `generic.adolescent.male.b` | not_generated | not_generated | — | not_tested | unlocked |
| 5 | `generic.adolescent.female.a` | not_generated | not_generated | — | not_tested | unlocked |
| 6 | `generic.adolescent.female.b` | not_generated | not_generated | — | not_tested | unlocked |
| 7 | `generic.young_adult.male.a` | not_generated | not_generated | — | not_tested | unlocked |
| 8 | `generic.young_adult.male.b` | not_generated | not_generated | — | not_tested | unlocked |
| 9 | `generic.young_adult.male.c` | not_generated | not_generated | — | not_tested | unlocked |
| 10 | `generic.young_adult.female.a` | not_generated | not_generated | — | not_tested | unlocked |
| 11 | `generic.young_adult.female.b` | not_generated | not_generated | — | not_tested | unlocked |
| 12 | `generic.young_adult.female.c` | not_generated | not_generated | — | not_tested | unlocked |
| 13 | `generic.middle_aged.male.a` | not_generated | not_generated | — | not_tested | unlocked |
| 14 | `generic.middle_aged.male.b` | not_generated | not_generated | — | not_tested | unlocked |
| 15 | `generic.middle_aged.male.c` | not_generated | not_generated | — | not_tested | unlocked |
| 16 | `generic.middle_aged.female.a` | not_generated | not_generated | — | not_tested | unlocked |
| 17 | `generic.middle_aged.female.b` | not_generated | not_generated | — | not_tested | unlocked |
| 18 | `generic.middle_aged.female.c` | not_generated | not_generated | — | not_tested | unlocked |
| 19 | `generic.senior.male.a` | not_generated | not_generated | — | not_tested | unlocked |
| 20 | `generic.senior.male.b` | not_generated | not_generated | — | not_tested | unlocked |
| 21 | `generic.senior.female.a` | not_generated | not_generated | — | not_tested | unlocked |
| 22 | `generic.senior.female.b` | not_generated | not_generated | — | not_tested | unlocked |
| 23 | `generic.unknown.neutral.a` | not_generated | not_generated | — | not_tested | unlocked |
| 24 | `group.mixed.neutral.a` | not_generated | not_generated | — | not_tested | unlocked |

## 群体声特别边界

`group.mixed.neutral.a` 在首版只表示“单一群体代表音色”。听检不得把它记录为 Nano 原生多人同时发声；2–3 音色延时混音属于 T6，需新的媒体、权利与听感证据。

## 锁定操作

只有 24 行均有实际候选 hash、授权批准、T0-C/T0-D 技术证据、人工听感和全池去重结论后，才能：

1. 为每槽写入唯一 `selected_candidate_id`；
2. 计算包内容 hash，将每槽 `lock_status` 设为 `locked`；
3. 创建不可变的新 pool version，不在 `0.0.0-stage0-candidate-plan` 上就地冒充 ready；
4. 让主代理在 T0-GATE 决定完整包 `go`、有限预览 `degraded-go` 或 `no-go`。
