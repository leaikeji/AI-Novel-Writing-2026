# T3-G 表达、置信度与人工覆盖继承证据

日期：2026-08-26（Asia/Shanghai）

结论：**T3-G 局部候选 PASS；已完成确定性情绪／表达分类、说话人置信等级与严格的人工覆盖继承判断，且可组装 T3-A typed contract。T3-GATE runtime 仍为 HOLD。**

本结论不表示脚本生成、人工复核、选角、TTS 合成或页面功能已可用。本工作包未连接 API、数据库或共享入口，未运行模型，未暂存、提交或推送。

## 1. 范围与冻结输入

本工作包只新增主文档分配的 4 个路径：

- `backend/narration/expression.py`
- `backend/narration/confidence.py`
- `tests/narration/test_confidence.py`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T3-G/README.md`

未修改 T3-A 冻结文件、T3-B/T3-C 候选、`backend/narration/__init__.py`、`script_versions.py`、API、迁移、UI、选角、音频、Docker、数据库、主 TTS 文档、索引或其他工作包。

| 只读输入 | 复核 SHA-256 |
| --- | --- |
| `backend/narration/script_contracts.py` | `c32cd8db3a52ff4a0495ff30947b38a08885c952fd7743b88ee6298a0719656c` |
| `backend/narration/contracts.py` | `f5b3028a3dae3d3247110bb3cc8852b9116cfb2c11542c5ecd61df3a3f7efc1f` |
| `backend/narration/aliases.py` | `212771499e7d45f45aa8a9d1cde38cf22bd535c7b4d8859d6390f32e08c93bda` |
| `backend/narration/scenes.py` | `c8b3a9a3016b9e1470173a4773fa8db2f0e195ae54af0768311cf12502c81466` |
| `backend/narration/speaker_rules.py` | `7d72d655be8bf73e8d4d143354c7c3e95a2eee8613ed3a01ebe81ffe5ea25cee` |

## 2. 情绪与表达分类

`narration-expression-rules/1` 是本地、无依赖、可审计的 v1 子集：

| 证据形状 | `emotion` | `emotion_confidence` | 处理 |
| --- | --- | --- | --- |
| 无情绪标记 | `neutral` | `high` | 代表“默认规则结果确定”，不是心理学概率 |
| 单一情绪类别、1 个非重叠标记 | 该情绪 | `medium` | 保留 `single` 规则证据 |
| 单一情绪类别、至少 2 个非重叠标记 | 该情绪 | `high` | 保留 `corroborated` 证据 |
| 多类别竞争，有唯一领先者 | 领先情绪 | `low` | 保留 `emotion_competing` 冲突 |
| 多类别最高证据打平 | `neutral` | `unknown` | 保留 `emotion_tie`，不猜测 |

支持的冻结情绪值是 `neutral | happy | sad | angry | fearful | tense`。表达值是 `normal | whisper | shout | inner_monologue`：

- `inner_monologue` 由已分段的结构类型决定，优先于词汇 cue；
- `whisper` 与 `shout` 同时出现时回退 `normal`，并保留 `delivery_competing`；
- 输入只是已分段的 `source_text/spoken_text` 和有界相邻 cue，分类不改动源文本与 source mapping；
- 相互包含的词组只算一条词汇观测，例如“呼吸急促／急促”不会伪造两条佐证。

## 3. 说话人置信等级与冻结 taxonomy

`speaker-confidence-policy/1` 使用离散决策树，不输出伪精确百分比。冲突与未知先于所有正向信号：

| 输入条件 | 等级 | 冻结 issue |
| --- | --- | --- |
| `SpeakerRef.UNKNOWN` | `unknown` | `B_SPEAKER_LOW_CONFIDENCE` + `B_SPEAKER_UNKNOWN` |
| 身份冲突、候选数不为 1、已授权佐证冲突 | `low` | `B_SPEAKER_LOW_CONFIDENCE` |
| 唯一候选 + 直接身份证据 | `high` | 无置信 issue |
| 唯一候选 + 至少 2 个独立本地规则家族 | `high` | 无置信 issue |
| 唯一候选 + 1 个本地规则 + 已授权佐证一致 | `high` | 无置信 issue |
| 唯一候选 + 1 个本地规则 | `medium` | `W_SPEAKER_MEDIUM_CONFIDENCE` |
| 唯一候选 + 唯一上下文规则 | `medium` | `W_SPEAKER_MEDIUM_CONFIDENCE` |
| 唯一候选 + 只有已授权佐证 | `medium` | `W_SPEAKER_MEDIUM_CONFIDENCE` |
| 唯一候选但无可解释证据 | `low` | `B_SPEAKER_LOW_CONFIDENCE` |

`ModelConsistency` 只是对“上游已授权佐证结果”的离散表示；本包不调用模型或云端。T3-GATE 只能在通过 T3-A `CloudAuthorityRecord` 精确校验后填入 `consistent/conflicting`；未校验时必须保持 `not_evaluated`。

T3-A 的冻结 issue taxonomy 只定义了“说话人置信度”的 warning/blocker，没有情绪专用 issue code。因此本包不会把情绪冲突伪装成 `B_SPEAKER_*`；情绪的 `low/unknown` 保留在 typed 字段与规则证据中，由 T3-H/T3-GATE 按冻结契约显示复核。

## 4. 人工覆盖继承决策

`override-inheritance-policy/1` 将“来源权威”与“本地规则”彻底分开。只有以下条件全部成立才会输出新的 `OverrideProvenance(kind=inherited)`：

1. 来源脚本已 `approved`，来源句段是 `manual_override` 或已验证的 `inherited_override`；
2. 来源快照完整命中服务端 `authorized_sources` 精确集合，不接受仅 ID 相同的宽松匹配；
3. 来源、目标和 authority 属于同一作品，来源版本与目标版本不同；
4. 来源 provenance 的局部哈希、前后锚点与 `speaker_target_hash(speaker, casting)` 与来源快照完全一致；
5. 目标局部哈希、前后锚点值与来源完全一致；
6. 目标完整文档中局部哈希、存在的前锚点、存在的后锚点及组合匹配次数都等于 1；文档边界的空锚点必须有精确的 start/end 位置证明；
7. 目标 `speaker-casting` digest 与来源一致；
8. 新审计动作的 owner 与 authority 一致，`action_id` 未复用，UTC 时间不早于来源操作。

重复局部文本即使表面上可被一对锚点区分，v1 也拒绝继承并转人工复核。任一条件失败都返回稳定 `OverrideInheritanceReason`，`eligible=false` 且不携带 provenance，不会通过部分匹配猜测。

正向路径可直接产生：

- T3-A `OverrideProvenance(kind=inherited)`；
- T3-A `AttributionEvidence(origin=inherited_override)`；
- T3-A `ScriptIssueContract(code=W_MANUAL_OVERRIDE_INHERITED)`。

## 5. 实际验证

主计划指定的专项命令：

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/narration/test_confidence.py
```

结果：exit 0，原始输出为 `76/76` 点阵通过。为显式记录计数，另运行：

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -o addopts='' -q tests/narration/test_confidence.py
```

结果：`76 passed in 0.07s`。

T3-A + T3-C + T3-G 窄联合非回归：

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -o addopts='' -q tests/narration/test_script_contracts.py tests/narration/test_speaker_rules.py tests/narration/test_confidence.py
```

结果：`173 passed in 0.35s`（T3-A 54 + T3-C 43 + T3-G 76）。

其他实际检查：

- Python `py_compile`：`expression.py`、`confidence.py`、`test_confidence.py` 共 3 个文件全部通过；编译产物写入精确临时目录后已移除，工作区无本包 `pyc`。
- 76 项专项用例覆盖表达／输入契约、12 个冻结置信校准样本、置信阈值边界、人工继承正负路径与权威边界；`--collect-only` 与最终运行的原始计数均为 76。
- 未读取真实小说正文，未运行模型、浏览器、Docker 或 PostgreSQL，未新增依赖。

## 6. 产物 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/expression.py` | `36acf1b1bb44cabba226dcfdc79ba6ae2be6101716bbbbccfd5cb9d2b0b76156` |
| `backend/narration/confidence.py` | `2d954ff9f455b15e8c845b6aa7bb1fb9e290dd3a761b8e9fd0ee587d4c545699` |
| `tests/narration/test_confidence.py` | `e8e4e0345d20cee41edbd8e6edfeb9ff87ddbc210dee74cdefe8360dd5bd86cf` |

本 README 不记录自身 hash，避免自引用循环。主代理集成前必须对本节哈希再复核。

## 7. T3-GATE 接线顺序

1. 从 T3-B `MaterializedSegment` 取已校验的 `segment_kind/source_text/spoken_text`，只追加有界相邻 cue，调用 `classify_expression()`。
2. 将 T3-C 精确别名／配置身份映射为 `direct_identity_match`，同段延续映射为 `contextual_rule_count=1`；候选人物必须先去重并进行作品 allowlist 校验。
3. 仅当 T3-D 结果的 `CloudAuthorityRecord` 精确匹配 segment、局部哈希、模型指纹和 `speaker_target_hash` 时，才能设置 `ModelConsistency`；未授权输入不得抬高置信等级。
4. 调用 `assess_speaker_confidence()` 作为最终置信等级与冻结 confidence issue 的唯一映射；再与 T3-C 的别名／非法引用 issue、T3-E 匿名 issue 和 T3-F 选角 issue 做集合并集，不得用本包结果覆盖其他 blocker。
5. 继承判断必须在 T3-F 选角结果形成后执行，因为继承同时绑定 speaker 与 casting。由服务端反向加载已批准源脚本、不可变 hash、当时句段快照和人工 provenance，构造 `OverrideInheritanceAuthority`。
6. 对目标完整不可变 source 扫描局部 hash/前锚点/后锚点/组合的真实出现次数，由服务端构造 `AnchorUniquenessEvidence`；不得信任客户端或模型传入的计数。
7. `decide_override_inheritance()` 只在 `eligible=true` 时将 `to_attribution()` 与 `to_script_issues()` 组装进目标 segment，并将 `manual_override=true`；任一拒绝原因都不得生成 inherited provenance，只能继续当前自动决策或转人工复核。
8. 将 `ExpressionDecision.emotion/emotion_confidence/delivery`、最终 speaker confidence、归因、选角和所有 issues 合并为 T3-A `SegmentContract`，最后由 T3-GATE 唯一 Owner 执行完整 `NarrationScriptContract` authority、source mapping、issue count、immutable hash 与状态机校验。

## 8. 剩余边界与风险

1. 词汇规则是保守的中文小说 v1 子集，不是完整 NLP。否定（如“我不害怕”）、反讽、隐含情绪、复杂语序与跨句反转可能形成保守或冲突结果，需 T3-H 显示人工复核。
2. `high/medium/low/unknown` 是可解释等级，不是从生产样本中学习的统计概率。本次“校准样本”是 12 个冻结决策矩阵样本与边界负测；上线后若要修改阈值，必须新版策略 ID、新验收样本和主文档裁决，不得就地改写 `/1`。
3. 本包没有 ORM loader、完整文档锚点计数器、审计动作持久化、reverse loader、API 或复核 UI；它们属于 T3-GATE/T3-H 唯一 Owner。
4. 重复文本一律拒绝自动继承，可能比未来更精细的锚点策略更保守；该取舍优先避免把作者手工选角套到错句。
5. 本包是纯后端规则，用户已冻结的“不考虑 1080P 以下布局”与本工作包无直接验收项。

T3-GATE 接线前不得将本局部 PASS 改写为“多角色智能朗读已对用户可用”。
