# T0-E 通用音色池来源与授权台账

> **适用范围更正（2026-08-27）：** 本文保留为商业发布／模型与音频再分发风险审计，不再是个人本地产品的预设可用性门禁。固定 ONNX manifest 的全部 18 个官方预设在个人本地版均允许，包括 `Trump`、`Xiaoyu` 及任何明星／公众人物标签；商业状态未评估不得阻断本地展示、试听、绑定、合成或播放。现行裁决见 [个人本地版官方预设裁决](./local-personal-official-presets.md)，下文历史审计原文不重写。

> 状态：**24 个槽位均未获得生产授权，完整基础包 HOLD**
>
> 核对日期：2026-08-26（Asia/Shanghai）
>
> 边界：本文是工程证据与阻断台账，不代替正式法务意见。

## 可复核结论

> 本节及后续“来源类型决策”“18 个 ONNX 预设逐项用途门禁”“参考音频文件审计”记录的是 2026-08-26 商业发布／再分发候选审计原口径。其中 `isolated/no-go/excluded/永久排除` 只保留历史含义，均不能解释成现行个人本地预设可用性；个人本地版以固定 ONNX manifest 的 18 个 exact preset ID 为准并全部可用。

- 固定 ONNX `browser_poc_manifest.json` 含 18 个预设：中文 6、英文 5、日文 7。固定 Python runtime 映射只有 16 个，其中同名且文件名完全一致的只有 8 个；不得只按名称静默迁移。
- 固定 ONNX 模型卡明确声明 `license: apache-2.0`；固定 GitHub 源仓有根 Apache-2.0 `LICENSE`，且 13 个 `assets/audio/*.wav` 位于同一固定树中。但是仓库没有单独的录音来源、说话人身份/同意、声音/人格权、再分发或商用授权文件。**代码许可、模型权重许可、音频文件版权许可和声音/人格权不是同一件事。**
- 本项目只把“正式官方发布物在本机封闭、不面向用户、不再分发的技术评估”视为窄 `allowed_for_isolated_test`；这不是法务或生产授权。18 个 ONNX 预设中，`Trump` 和显示名为 `CN 明星` 的 `Xiaoyu` 直接排除该窄评估，其余 16 个可做隔离技术测试；中文为 **5/6**。Python runtime 的 16 个映射中，只有 6 个同时具有固定树中的文件且不存在跨 runtime 身份冲突，可做窄隔离测试。允许再分发、允许商用产品、允许进入 24 槽生产包均为 **0**。
- 名为 `Trump` 的公众人物仿声预设明确排除，不用于通用音色池、旁白、默认界面或降级包。
- `MOSS-TTS-Nano-Reader` 固定 revision 无根许可证，状态为 `NOASSERTION`；本工作包没有复制、打包、再分发或将其任何内容当作音色授权依据。
- VoiceGenerator 的固定模型元数据为 Apache-2.0，但“生成输出”仍要经过来源指纹、意外相似真人/公众人物检查和项目用途复核；T0-D 元数据尖刺已建议在 M4/16 GB 上隐藏 capability，且没有下载模型、生成候选或产生可授权资产。

以上两条排除与 16/18、5/6 是历史商业候选审计原文；个人本地裁决已废止这些排除。`Trump`、`Xiaoyu` 与其他 16 项当前均可作为 `official_preset` 展示、试听、绑定、合成和播放。

## 固定官方一手证据

| 证据 | 固定 revision / 结论 |
| --- | --- |
| [ONNX 模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX/blob/f52645cb467506d8e18e746ddd59482685b74e58/README.md) | revision `f52645cb467506d8e18e746ddd59482685b74e58`；front matter 为 `license: apache-2.0`，清单把 `browser_poc_manifest.json` 定位为 browser integration 示例 |
| [Nano 源仓 LICENSE](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/cc7bdf19c7639c0870dab22045a33b442760f6be/LICENSE) | revision `cc7bdf19c7639c0870dab22045a33b442760f6be`；Apache-2.0，git blob `f95ac2d6ec3449e33a18b54792e733a1701d6482` |
| [Nano 固定源码树](https://github.com/OpenMOSS/MOSS-TTS-Nano/tree/cc7bdf19c7639c0870dab22045a33b442760f6be/assets/audio) | `assets/audio` 有 13 个 WAV；`assets/demo.jsonl` 明示 `zh_11.wav` 为“杨幂”、`en_7.wav` 为“Taylor Swift”；固定树中没有单独的音频来源、同意、声音/人格权或再分发/商用授权文件 |
| [权重许可官方答复](https://github.com/OpenMOSS/MOSS-TTS-Nano/issues/91#issuecomment-5104235585) | 官方协作者确认当前 HF 模型卡声明 Apache-2.0；该答复仍未补充参考录音与说话人权利链 |
| [VoiceGenerator 模型卡](https://huggingface.co/OpenMOSS-Team/MOSS-VoiceGenerator/blob/97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4/README.md) | revision `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`；模型元数据 Apache-2.0；不等于任何生成声音必然无真人相似或可商用 |
| [Nano Reader 固定树](https://github.com/OpenMOSS/MOSS-TTS-Nano-Reader/tree/c3b2333b88e0f062ca49d403540a169609354d93) | 固定树未发现根 `LICENSE`；本项目因此按 `NOASSERTION` 处理并禁止复制、打包和再分发，不把这一项目政策错误归因为官方法律指令 |

## 来源类型决策

下表的“允许范围”和“本阶段决定”只描述当时的商业候选／24 槽审计；现行个人本地版对固定 ONNX manifest 18 项的决定均为 `official_preset` 可用，商业状态作为独立信息字段保留。

| 来源 | 固定证据 | 允许范围 | 缺口 | 本阶段决定 |
| --- | --- | --- | --- | --- |
| MOSS-TTS-Nano ONNX 内置 prompt codes | ONNX revision `f52645cb467506d8e18e746ddd59482685b74e58`；模型卡 Apache-2.0 | 仅 16/18 个预设可做本机封闭技术测试 | `Trump`、`Xiaoyu/CN 明星` 排除；其余参考说话人授权、人格/声音权、槽位年龄和听感去重未证明 | 中文 5 个仅隔离测试；分发/商用/生产 0 个 |
| MOSS-TTS-Nano Python 预设文件映射 | 源码 revision `cc7bdf19c7639c0870dab22045a33b442760f6be`；代码 Apache-2.0 | 只读比对运行时契约 | 18/16 清单、名称和文件不一致 | 不是授权来源；不做名称推断 |
| MOSS-VoiceGenerator | revision `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`；模型仓元数据 Apache-2.0 | 只有未来重新通过 T0-D 锁与资源门禁后才可隔离生成候选 | 当前 capability `hide`；输出权利、意外相似、Nano 二次克隆保持度未验 | 48 个 ID 只是保留计划，0 个真资产 |
| 用户/项目获授权参考录音 | 尚无资产 | 只有在权利记录完整后可做 fallback | 出处、贡献者/说话人同意、用途、期限、地域、署名、撤回及未成年人监护授权 | 尚无可用候选 |
| MOSS-TTS-Nano-Reader | revision `c3b2333b88e0f062ca49d403540a169609354d93`；`NOASSERTION` | 只读行为研究 | 无项目级许可证 | **禁止复用/打包/再分发** |
| 公众人物或知名角色仿声 | 不适用 | 无 | 人格、声音、商标/角色等高风险 | **禁止** |

上表是历史商业发布／再分发候选决策原文。现行覆盖：ONNX 内置 prompt codes 18/18 均可用于个人本地；“公众人物或知名角色仿声”禁令只约束外部素材、用户上传、生成声音与主动仿声，不用于过滤 fixed manifest 官方预设。

## 18 个 ONNX 预设逐项用途门禁

`isolated` 只表示上述窄封闭测试；`distribution` 与 `commercial` 是包含所有权利层后的有效项目结论，不是只看 Apache-2.0 的版权结论。完整机器可读缺口见 `voice-pack-manifest.json`。

| preset | isolated | distribution | commercial | unresolved / 决定 |
| --- | --- | --- | --- | --- |
| `Junhao` | allowed | no-go | no-go | 说话人身份、同意、声音/人格权、再分发与商用范围未提供 |
| `Zhiming` | allowed | no-go | no-go | 同上；另有 runtime 文件映射不一致 |
| `Weiguo` | allowed | no-go | no-go | 同上；另有 runtime 文件映射不一致 |
| `Xiaoyu` | **no-go** | no-go | no-go | 显示名 `CN 明星` 指向公众人物风险；身份与授权未解 |
| `Yuewen` | allowed | no-go | no-go | 说话人身份、同意、声音/人格权、再分发与商用范围未提供 |
| `Lingyu` | allowed | no-go | no-go | 同上 |
| `Trump` | **no-go / excluded** | no-go | no-go | 明示公众人物仿声；项目永久排除当前预设 |
| `Ava` | allowed | no-go | no-go | 说话人身份、同意、声音/人格权、再分发与商用范围未提供 |
| `Bella` | allowed | no-go | no-go | 同上 |
| `Adam` | allowed | no-go | no-go | 同上 |
| `Nathan` | allowed | no-go | no-go | 同上；另有 runtime 文件映射不一致 |
| `Soyo` | allowed | no-go | no-go | 同上；固定源码树没有 `jp_1.wav` |
| `Saki` | allowed | no-go | no-go | 说话人身份、同意、声音/人格权、再分发与商用范围未提供 |
| `Mortis` | allowed | no-go | no-go | 同上；固定源码树没有 `jp_3.wav` |
| `Umiri` | allowed | no-go | no-go | 同上；固定源码树没有 `jp_4.wav` |
| `Mei` | allowed | no-go | no-go | 同上；固定源码树没有 `jp_5.wav` |
| `Anon` | allowed | no-go | no-go | 同上；固定源码树没有 `jp_6.wav` |
| `Arisa` | allowed | no-go | no-go | 同上；固定源码树没有 `jp_7.wav` |

上表完整保留 2026-08-26 商业发布／再分发审计原文；其中 `Xiaoyu`、`Trump` 的 `no-go/excluded/永久排除` 不适用于个人本地版，当前 18 项均可作为 `official_preset` 使用。

## 参考音频文件审计

- 固定 GitHub 树实际只有 13 个 WAV；ONNX 18 个 `audio_file` 引用中只有 11 个在树中，Python 16 个映射中只有 8 个在树中。`en_6.wav`、`en_7.wav` 在树中但不属于两份固定预设清单。
- 两份清单引用但固定树找不到的文件是：`en_1.wav`、`en_5.wav`、Python Sakura 的 `jp_1.mp3`、ONNX Soyo 的 `jp_1.wav`、`jp_3.wav`、`jp_4.wav`、`jp_5.wav`、`jp_6.wav`、`jp_7.wav`、`zh_2.wav`、`zh_5.wav`。找不到文件不影响 ONNX manifest 已内嵌 prompt codes 的技术存在，但阻断录音来源核验；`jp_1.mp3` 与 `jp_1.wav` 也不得视作可互换。
- Python runtime 只有 `Junhao/Yuewen/Lingyu/Ava/Bella/Adam` 6 个映射可做窄隔离测试；`Zhiming/Weiguo/Nathan/Sakura/Aoi/Hina/Mei` 缺固定音频，`Xiaoyu/Yui` 的同一文件在 ONNX manifest 中属于另一身份，`Trump` 则由公众人物规则排除。16 个映射的逐项权限均在 manifest 中，不按名称或文件名猜测替换。
- **现行覆盖：** 上条是历史商业候选原文。个人本地 ONNX 路径不采用人物排除，也不按名称跨 runtime 推测；必须以当前固定 ONNX manifest、模型 fingerprint 和 exact preset ID 为权威。
- 13 个文件的路径、大小、固定 git blob SHA-1、关联预设及四项用途门禁均写入 `voice-pack-manifest.json`。`assets/demo.jsonl` 明示 `zh_11.wav` 为“杨幂”、`en_7.wav` 为“Taylor Swift”，两者连隔离测试也阻断；其余 11 个仅可做本机封闭技术测试。**13/13 均不得作为已清权素材再分发或进入商用产品。**
- 没有下载或试听这些参考录音；本结论来自固定官方树元数据、根许可证和“无独立授权文件”的只读核验。

## 24 槽授权逐项台账

`source_status = planned_no_asset` 表示只保留了候选 ID，没有声音资产；不是 placeholder 通过。所有槽位的 `enabled=false`、`production_status=blocked`。

| # | slot_id | 计划来源 | source | rights | quality | 生产 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `generic.child.male.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 2 | `generic.child.female.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 3 | `generic.adolescent.male.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 4 | `generic.adolescent.male.b` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 5 | `generic.adolescent.female.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 6 | `generic.adolescent.female.b` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 7 | `generic.young_adult.male.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 8 | `generic.young_adult.male.b` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 9 | `generic.young_adult.male.c` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 10 | `generic.young_adult.female.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 11 | `generic.young_adult.female.b` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 12 | `generic.young_adult.female.c` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 13 | `generic.middle_aged.male.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 14 | `generic.middle_aged.male.b` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 15 | `generic.middle_aged.male.c` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 16 | `generic.middle_aged.female.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 17 | `generic.middle_aged.female.b` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 18 | `generic.middle_aged.female.c` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 19 | `generic.senior.male.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 20 | `generic.senior.male.b` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 21 | `generic.senior.female.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 22 | `generic.senior.female.b` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 23 | `generic.unknown.neutral.a` | VoiceGenerator 两候选；授权参考 fallback | planned_no_asset | unresolved | not_tested | blocked |
| 24 | `group.mixed.neutral.a` | 单一群体代表声；T6 才可另做混音 | planned_no_asset | unresolved | not_tested | blocked |

## 每个真实候选必须补齐的权利记录

1. `candidate_id`、`slot_id`、来源类型和不可变来源指纹。
2. VoiceGenerator 需保存固定模型 revision、描述文本 hash、seed、生成参数、原始输出 hash；不得用“AI 生成”代替权利复核。
3. 外部/用户参考需保存来源 URL 或贡献者记录、原始文件 hash、说话人同意证据、许可/用途范围、期限、地域、署名、可撤回性和第三方权利。
4. 真实未成年人参考还必须有监护人和合法使用授权；没有即拒绝。
5. 检查不是公众人物、知名角色或可识别真人仿声；任何不确定均保持 `unresolved/blocked`。
6. 权利审核人、时间、结论、证据 hash 与适用的 pack version；授权改动不就地改写已锁定版本。

以上第 5 项只适用于 VoiceGenerator、外部／用户参考录音和未来 24 槽商业候选，不适用于 fixed manifest 的个人本地 `official_preset`；不得据此建立官方预设名称或人物排除名单。

## 生产授权闸门与回退

单个槽位只有在「来源指纹完整 + 权利证据批准 + 无仿声风险 + Nano 质量通过 + 人工听感去重通过」全部成立后才可标记 `ready`。一旦锁定，任何来源、授权、音频、模型、描述或后处理变更都必须生成新音色/音色池版本。

若 T0-D 不可用，只有两种合法回退：

1. 采购/录制至少 24 个权利清晰的参考音色，逐槽走同一闸门；
2. 只发布明确标识缺失类别与撞声风险的“有限音色预览”，默认关闭自动通用选角，不宣称完整 24 槽。
