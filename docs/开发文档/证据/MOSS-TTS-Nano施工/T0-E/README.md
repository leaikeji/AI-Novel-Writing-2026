# T0-E 24 槽位通用音色池候选契约与来源台账

> **现行个人本地版覆盖说明（2026-08-27）：** 本文原有公众人物排除、16/18 隔离测试上限及预设 `no-go` 结论，只保留为商业发布／再分发风险审计的历史记录，不再限制个人本地版。固定 ONNX manifest 的全部 18 个官方预设（包括 `Trump`、`Xiaoyu`）均可用于本机展示、试听、绑定、合成和播放；现行权威见 [个人本地版官方预设裁决](./local-personal-official-presets.md)。下文历史原文及其 hash 证据不重写。

> 状态：**槽位 schema、候选名额和来源/授权台账已形成可复核候选；实际 24 音色包 HOLD**
>
> Owner：T0-E / `/root/tts_t0e_voice_pool`；权利门禁复核 `/root/tts_t0e_rights`
>
> 执行时间：2026-08-26（Asia/Shanghai）
>
> Git 基线：`9b5be4a`；开始和结束时共享工作树均为 dirty，本工作包只修改分配的 5 个路径，不缓存、提交或推送。

## 结论

1. 按主设计 6.2 的每类下限冻结了恰好 24 个稳定 slot ID：儿童 2、少年/少女 4、青年 6、中年 6、老年 4、中性/未知 1、群体代表 1。
2. 每个槽位都显式包含年龄/声线呈现、语言、音高、音色质感、气质、场景/禁用标签、优先级、版本、来源策略、2 个保留候选 ID、去重规则、锁定状态以及 `source_status/rights_status/quality_status/production_status`。
3. 当前是 **48 个计划 ID、0 个真实资产、0 个已选槽、0 个生产 ready**。所有槽位都是 `planned_no_asset / unresolved / not_tested / blocked`、`enabled=false`；没有用 placeholder 冒充可用声音。
4. 只读核对了固定 ONNX manifest 的 18 个预设和 Python runtime 的 16 个映射。两者同名 12，同名且文件完全相同 8；`Zhiming/Weiguo/Xiaoyu/Nathan` 同名却文件不同，日文名称/数量也不一致。ONNX manifest 是 ONNX 内置声契约，禁止按名称跨 runtime 静默替换。
5. **[历史商业发布／再分发审计，非个人本地门禁]** 固定 ONNX 模型卡与 GitHub 根许可证能证明发布物的 Apache-2.0 版权许可基线，但固定源码树没有单独的录音来源、说话人同意、声音/人格权、再分发或商用授权文件。原审计只允许 16/18 进入当时定义的商业候选技术池，并排除 `Trump` 与 `Xiaoyu/CN 明星`；该排除已被个人本地裁决废止。允许分发、允许商用、允许进入 24 槽生产包仍为 **0/未评估**，但不影响 18 项官方预设的本机使用。
6. **[历史商业发布／再分发审计，非个人本地门禁]** 固定源码树只有 13 个参考 WAV：ONNX 的 18 个音频文件引用只有 11 个存在，Python 的 16 个映射只有 8 个存在且仅 6 个没有跨 runtime 身份冲突。`assets/demo.jsonl` 又把 `zh_11.wav` 标为杨幂、`en_7.wav` 标为 Taylor Swift；原商业候选审计据此排除两者。该结论不再限制固定 ONNX manifest prompt codes 的个人本地使用；跨 runtime 仍必须按 exact preset ID／manifest／fingerprint 处理，不能按名称猜测。
7. **[历史商业发布／再分发审计，非个人本地门禁]** 原记录对 `Trump` 类公众人物仿声作商业候选排除；该排除不适用于个人本地官方预设。无许可的 Nano Reader 仍禁止复制、打包或再分发。
8. T0-C 已完成真实 Nano 20/20 技术矩阵，但没有完成 24 音色候选、真实 reference clone 或人工听感；T0-D 已建议在 M4/16 GB 上隐藏 VoiceGenerator，且没有生成候选。因此 T0-GATE 对“完整 24 槽位基础包”仍必须判定 `HOLD/no-go`，不得启用默认自动通用选角。

## 冻结输入

| 输入 | 固定值 / SHA-256 |
| --- | --- |
| 主设计 | `docs/开发文档/18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md` 6.2；24 槽最低分类 |
| T0-A 模型来源锁 | `model-sources.lock.json` = `0485cdfb15eb01f7c4c0f65049f1c477fb6391ec523c5b7159ab25f763ab469d`；含最终 FFmpeg 窄构建/runtime hash 收口 |
| ONNX 内置音 manifest | revision `f52645cb467506d8e18e746ddd59482685b74e58`；`browser_poc_manifest.json` = `097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee` |
| Python runtime 映射 | revision `cc7bdf19c7639c0870dab22045a33b442760f6be`；`moss_tts_nano_runtime.py` = `696abcc54dae09e0f8eda701a3ad45e1a28277fd1516379a77ef9ec97c51cfc3` |
| VoiceGenerator | revision `97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4`；未下载、未运行 |
| Reader | revision `c3b2333b88e0f062ca49d403540a169609354d93`；`NOASSERTION`，只读/禁止复用 |
| T0-C | 已完成 20/20 真实 Nano 技术矩阵；未形成 24 音色候选、真实 reference clone、人工听感或权利通过证据 |
| T0-D | 元数据/代码路径尖刺建议 `voice_generator_visible=false`；模型下载/加载/候选生成均为 0 |

## 实际修改文件

- `tests/fixtures/narration/voice_pool_slots_v1.json`：24 槽位、状态词表、来源策略、10 维听感去重和不可变锁定闸门。
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T0-E/voice-pack-manifest.json`：18/16 官方清单差异、18 个预设和 13 个参考 WAV 的逐项用途门禁、每槽两个非仿声候选描述和 fallback/锁定规则。
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T0-E/licenses.md`：固定官方一手来源、代码/权重/录音/声音权分层、未成年人和公众人物风险台账。
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T0-E/listening.md`：后续 48 候选、Nano 二次克隆、24 槽全池去重和人工锁定模板。
- 本 `README.md`。

## 运行环境与资源边界

| 项 | 实际值 |
| --- | --- |
| OS / CPU / RAM | macOS 26.5.2 / Apple M4 / 16 GB（沿用 T0-A 同一阶段基线） |
| 验证解释器 | 项目 `.venv` CPython 3.12.13 |
| 模型/音频动作 | 只读核对主代理已放置的固定 manifest/runtime；本工作包未申请 `LOCK-MODEL-ASSETS`，未下载、生成、移动或提交模型/音频 |
| 隐私 | 没有读取用户正文、参考录音、真实密钥、QwenPaw 私有数据或旧项目 `Data` |

## 命令与结果

| 命令（等价摘要） | 退出码 | 通过 / 失败 / 跳过 |
| --- | ---: | --- |
| `.venv/bin/python -m json.tool tests/fixtures/narration/voice_pool_slots_v1.json` | 0 | JSON 1/1 通过 |
| `.venv/bin/python -m json.tool .../T0-E/voice-pack-manifest.json` | 0 | JSON 1/1 通过 |
| 标准库内嵌 validator：schema/必填字段/状态词表、24 索引与唯一 ID、12 类下限、48 候选引用与唯一性、全阻断状态、输入 hash、ONNX 18 预设逐项对照、Python AST 16 映射、34 项预设权限、13 源 WAV 指纹、公众人物排除 | 0 | `PASS schema=2 slots=24 category_minimums=24 planned_candidates=48 unique_candidates=48 official_presets=18 onnx_isolated=16 runtime_presets=16 runtime_isolated=6 source_wavs=13 source_wavs_isolated=11 distribution=0 commercial=0 production_ready=0` |

上表 validator 行是 2026-08-26 历史原文／原输出，其中“公众人物排除”和 `onnx_isolated=16` 只描述当时的商业候选规则，不是现行个人本地预设门禁。
| `git diff --check` | 0 | 已跟踪 diff 无空白错误；不修改其他 dirty 文件 |
| 对 5 个新文件逐个 `git diff --no-index --check /dev/null <file>` | 每文件 1（预期“存在差异”） | 5/5 无空白诊断，聚合检查退出 0 |
| 真实 VoiceGenerator/Nano/人工听感 | 未运行 | 按 `LOCK-VOICEGEN/LOCK-NANO`、T0-C/T0-D 前置与本工作包边界跳过；因此完整包保持 HOLD |

## 产物 SHA-256

| 产物 | SHA-256 |
| --- | --- |
| `voice_pool_slots_v1.json` | `b4b4410f6fbef702bc28358fb16558e0fe1032613674c597cb48d5bf6c0cc911` |
| `voice-pack-manifest.json` | `155f740d5df12a469c0ecfb3e7b7c04ca7bb9a7ee02807cf9a52abe2307c66bb` |
| `licenses.md`（2026-08-26 原审计快照；后续范围注释不重算旧 hash） | `a063ff3c38037266b9a6c36af277ab407ce9fa7f87b7c4b8083bd66a3b4e8608` |
| `listening.md`（2026-08-26 原听检模板；后续范围注释不重算旧 hash） | `6a1836ecb78d8aa6f14a04168fa12983fbdffd1680c3ed708eee9cfde84c3d4d` |

`README.md` 不记录自身 hash，避免自引用循环。

## 人工复核

- 已核对每个槽位的分类、计划来源、权利状态、去重 profile、锁定阻断和禁用标签。
- 已核对 ONNX manifest 里 18 个预设的名称、显示名、组别和文件名，并与固定 Python runtime 映射比较。
- 已从固定 GitHub tree API 核对 13 个 `assets/audio/*.wav` 的路径、大小和 git blob SHA-1；固定树只有根 Apache-2.0 `LICENSE`，没有单独音频权利/同意文件。本工作包没有下载或试听这些 WAV。
- 未听任何实际候选，未对年龄、性别呈现、音质、相似度或去重做通过判断；`listening.md` 所有 24 行均保持 `not_generated/not_tested/unlocked`。

## 未验证项、风险与回退

1. **P0：没有真实 24 音色包。** 48 个候选均未生成；不能启用完整自动通用选角。
2. **P0：没有人工听感/去重。** 标签和描述不能证明音色不撞声。
3. **P0：没有生产授权声音。** 模型/代码 Apache-2.0 不能代替参考录音中真人的说话人同意和声音/人格权记录。
4. **P0：T0-C/T0-D 无法产出完整包。** T0-C 的 20/20 技术矩阵已通过，但无人审听、没有 24 音色候选或真实 reference clone；T0-D 当前隐藏 VoiceGenerator 且 0 候选，Nano 二次克隆保持度无从验证。
5. **P1：18/16 预设漂移。** 必须用 model fingerprint + 实际 manifest 定位，不能把同名当作同一音色。
6. VoiceGenerator no-go 时，回退到“至少 24 个明确授权参考音色”；仍不足 24 则只能是 capability-labelled 有限预览，告知缺失类别/撞声风险并默认关闭自动选角。
7. 本工作包没有修改业务代码、数据库、项目依赖、QwenPaw 或用户媒体。回退只需由主代理移除本工作包的 5 个新文件，不需数据恢复；不得删除其他任务文件或模型目录。

## 给主代理的接线说明

1. 可把 `voice_pool_slots_v1.json` 当作 T1/T2 冻结 DTO/resource 的槽位契约输入，但在 T0-GATE 前不得将其说成已导入生产的音色资源。
2. 当前按 T0-D 隐藏 VoiceGenerator。未来若独立真实 probe 通过并重新裁决，才可使用 `voice-pack-manifest.json` 的 48 个稳定 ID/描述生成候选；生成音频不进本证据目录或 Git。
3. T0-C 的 20-case 技术结果已经回收；仍须等待 T0-D 或其他权利清晰来源产生候选，再回填真实 asset hash、权利记录、Nano 二次克隆和 `listening.md`；没有实际审听人时仍保持 HOLD。
4. 锁定时必须创建新的不可变 pack version 和内容 hash；不得就地把 `0.0.0-stage0-candidate-plan` 的阻断状态编辑为 ready，历史 Edition 永远绑定原 pool/voice version。
5. 官方预设与 24 槽项目基础包继续分开；当前权利 `HOLD` 的预设只可作为非用户可见的本机封闭技术夹具，不能进入安装验证、初始化、降级试听或完整 24 槽覆盖率。未来只有权利和质量均通过的新资产才能重新申请有限预览。

   **[现行覆盖，不改写上方历史原文]** 上述限制不再适用于个人本地 `official_preset`：固定 ONNX manifest 的 18 项均可进入本机展示、试听、绑定、合成和播放。24 槽完整通用音色包仍须由其独立的权利、质量和覆盖门禁决定，不能借官方目录冒充已完成。
