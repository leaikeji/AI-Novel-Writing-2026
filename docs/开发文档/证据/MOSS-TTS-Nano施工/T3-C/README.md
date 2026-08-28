# T3-C 场景、别名与本地说话人规则证据

日期：2026-08-26（Asia/Shanghai）

结论：**T3-C 局部候选 PASS；已严格消费 T3-A typed contract，完成可审计场景切分、别名规范化与本地优先说话人归因。T3-GATE runtime 仍为 HOLD。**

本结论不表示自动人物识别、匿名身份持久化、自动选角、云端辅助、脚本复核、合成或播放已在产品中可用。本工作包未暂存、未提交、未推送。

## 1. 范围与冻结输入

本工作包只修改主文档分配的 5 个路径：

- `backend/narration/aliases.py`
- `backend/narration/scenes.py`
- `backend/narration/speaker_rules.py`
- `tests/narration/test_speaker_rules.py`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T3-C/README.md`

未修改 T3-A 三个冻结文件、`backend/narration/__init__.py`、`script_versions.py`、主 TTS 文档、索引、共享入口或其他工作包。

| T3-A 冻结输入 | 复核 SHA-256 |
| --- | --- |
| `backend/narration/script_contracts.py` | `c32cd8db3a52ff4a0495ff30947b38a08885c952fd7743b88ee6298a0719656c` |
| `tests/fixtures/narration/script-contract-v1.json` | `558c80d3dd8fa877fc9d58d18727aa9436db61dcd7814a054891c505effbc78d` |
| `docs/开发文档/证据/MOSS-TTS-Nano施工/T3-A/README.md` | `d02e8b149d7b238480c8603eae737bec5fd4f584d33355fe0989dc66c1df4ae9` |

## 2. 实现结果

### 2.1 人物别名

- `character-alias-normalization/1` 使用 Unicode NFKC + casefold + 空白折叠，只做精确键匹配，不做拼音、编辑距离或模糊猜测。
- 构建索引时必须传入服务端允许的 `character_id` 集合；越界别名行直接拒绝，规则层不能创建或扩大正式人物集合。
- 同一规范化别名指向同一人只去重；指向多个活跃人物时返回有序冲突集，不根据“当前场景只有一人”静默选择。
- 非活跃别名不参与归因；单一规范化键最多 32 个候选，与 T3-A evidence 上限一致。

### 2.2 场景

- 直接输出 T3-A `SceneContract`；`scene_id`、UTF-16 半开区间、局部哈希和连续 ordinal 均按冻结规则生成。
- 默认只识别 ATX Markdown 标题和独立场景分隔行；无可靠边界时稳定回退为一个章节范围，不把普通空行猜成新场景。
- Setext 标题下划线不会被误判为分隔符；分隔符后紧跟标题时合并为一个边界；文末分隔符不伪造空场景。
- T3-B 会把分隔符结构文本并入邻近 source segment。`source_segment_ranges_utf16` 因此接受 T3-B 的完整分区：自动分隔符向前对齐到下一句段边界，人工或段落边界若落在句段内则拒绝，保证每个 source segment 恰好属于一个场景。
- `scene_ids_for_source_ranges()` 为 T3-GATE 提供精确的 segment range → scene ID 映射；跨场景、无匹配或多重匹配均 fail-closed。
- v1 只可产生 `document_start | markdown_heading | scene_separator | paragraph_rule | manual`，不存在 `cloud_assisted` 输出路径。

### 2.3 本地说话人规则

- 直接输出 `SpeakerRef + ConfidenceLevel + AttributionEvidence(origin=local_rule)`，并可物化为 T3-A `ScriptIssueContract`。
- 覆盖旁白／标题／合成停顿、前置提示语、后置提示语、人名+动作+对话、T3-B 拆开的相邻 cue、显式内心独白／消息等配置说话人，以及同段延续说话人。
- 精确人名／别名是高置信本地证据；只有服务端明示 `same_paragraph_continuation=true` 才继承前一个正式／匿名／群体说话人，并固定为 `medium + W_SPEAKER_MEDIUM_CONFIDENCE`。
- 单一场景候选、普通“上一说话人”、代词、多个不同 cue、别名冲突或非法人物 ID 都不猜测。`unknown` 必定同时带 `B_SPEAKER_LOW_CONFIDENCE + B_SPEAKER_UNKNOWN`，别名冲突另带 `B_CHARACTER_ALIAS_CONFLICT`。
- 匿名／群体 label 只能解析为其他 Owner 传入的服务端授权 `SpeakerRef`。新匿名描述只产生 `unresolved_label` 提示和 blocker，不创建、持久化、合并或拆分匿名身份。
- 配置型 `explicit_speaker` 只允许用于内心独白、消息、信件、广播和电话；对话不能用它绕过 cue／别名冲突。

## 3. 冲突与失败关闭矩阵

| 输入 | 结果 | 是否可猜测或创建人物 |
| --- | --- | --- |
| 唯一活跃别名 | typed `character` + `high` + exact alias evidence | 否，只能返回 allowlist 已有 ID |
| 同别名指向多人 | `unknown` + low/unknown/alias 三项 blocker | 否 |
| 别名与已授权匿名／群体同键 | `unknown` + 跨类型冲突 | 否 |
| 新“一个年轻女人” | typed `unknown` + unresolved anonymous hint + blocker/warning | 否，交 T3-E |
| 单一场景人物，无 cue | `unknown` + 两项必备 blocker | 否 |
| 多个 cue 指向不同人 | `unknown` + 候选 ID 合集 + blocker | 否 |
| 同段明示延续 | 复用已授权前说话人 + `medium` warning | 是否延续由上层结构证据决定 |
| 非 allowlist 人物 ID | `unknown` + `B_CHARACTER_REFERENCE_INVALID` + 必备 blocker | 否 |
| 人工／段落场景边界落在句段内 | 拒绝组装 | 否，先分割 source segment |
| 不可确定场景 | 章节级单场景 | 否，不伪造“当前场景人物” |

## 4. 实际验证

| 检查 | 实际结果 |
| --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/narration/test_speaker_rules.py -q` | `43/43 passed` |
| T3-A + T3-C 联合回归 | `97/97 passed` |
| T3-A + T3-B + T3-C 联合回归 | `139/139 passed` |
| 最终工作区全量后端 `.venv/bin/python -m pytest -p no:cacheprovider -o addopts='' -q -ra` | `974 passed, 89 skipped, 1 warning, 2 failed`；两项均位于并行 T3-E `test_anonymous_speakers.py`，不在 T3-C 允许修改范围 |
| T3-B/T3-C 真实中间产物对齐 probe | `4 segments -> 2 scenes`，4/4 句段恰属一场景 |
| Python `py_compile` | 3 个源文件与测试文件全部通过 |
| 模块 `__all__` | 23 个导出，0 missing，0 duplicate |
| 行尾空白与范围复核 | 0 问题；只有本 README 第 1 节的 5 个路径为 T3-C 新文件 |

89 项 skip 来自未注入的 PostgreSQL／集成测试 URL；唯一 warning 是现有 Starlette/httpx 弃用提示。最终全量的两项失败分别是 T3-E 测试缺少 `ScriptContractError` import，以及 T3-E 负测在进入目标分支前用非 canonical UUID tuple 构造对象；T3-C 按文件 Owner 边界未修改它们。因此 T3-C 专项与 T3-A/B 联合束通过，而当前全局 T3 仍须等待 T3-E Owner 收敛。T3-C 未连接数据库，未运行 Docker、QwenPaw、模型、媒体或真实小说。

## 5. 产物 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/aliases.py` | `212771499e7d45f45aa8a9d1cde38cf22bd535c7b4d8859d6390f32e08c93bda` |
| `backend/narration/scenes.py` | `c8b3a9a3016b9e1470173a4773fa8db2f0e195ae54af0768311cf12502c81466` |
| `backend/narration/speaker_rules.py` | `7d72d655be8bf73e8d4d143354c7c3e95a2eee8613ed3a01ebe81ffe5ea25cee` |
| `tests/narration/test_speaker_rules.py` | `a9fd2576f09da812375b0374874597c3e21d5b2959cec689dbef0c96e5135c60` |

本 README 不记录自身 hash，避免自引用循环。第 5 节哈希必须在主代理集成前以最终文件再复核。

## 6. T3-GATE 集成顺序

1. 从 T3-B `SegmentationResult` 取权威 `source_text`、`script_version_id` 和有序 `segment.source_range_utf16`，调用 `build_scene_contracts(..., source_segment_ranges_utf16=...)`。
2. 调用 `scene_ids_for_source_ranges()` 获得与 T3-B segments 同序的 `scene_id`；任何跨场景句段都必须在组装前失败。
3. 从服务端人物卡与别名行构建 `CharacterAliasIndex`，`allowed_character_ids` 不得由模型或客户端传入。
4. 对每个 T3-B segment 构造 `SpeakerRuleContext`；对话 cue 只传相邻必要句段，`scene_character_ids` 仅作审计上下文，不可消解别名冲突。
5. T3-E 若已解析匿名／群体身份，再以精确 allowlist 构建 `ResolvedSpeakerIndex`；未解析 label 保持 `unknown` blocker，不得在 T3-C 内随机生成 ID。
6. 将 `SpeakerRuleDecision.speaker/confidence/attribution` 与 T3-F casting、T3-G emotion/delivery/confidence 结果合并为 `SegmentContract`；通过 `to_script_issues()` 物化本包警告／阻断，再合并其他 Owner 的 issues。
7. 最终脚本由 T3-GATE 唯一 Owner 执行 T3-A 完整 source mapping、authority、immutable hash 与状态机校验，再接入 `script_versions.py`。

## 7. 剩余边界

1. 本地规则是确定性中文小说 cue 子集，不声称是完整 NLP。代词、隐含轮次、异常语序和跨段暗示默认为 `unknown`，后续只能进入 T3-D 受控辅助或 T3-H 人工复核。
2. 本包没有别名 ORM loader、场景持久化、匿名稳定键、选角、置信校准数据集或脚本 reverse loader；这些仍归 T3-E/T3-F/T3-G/T3-GATE 唯一 Owner。
3. T3-GATE 必须传入 T3-B 完整 segment 分区进行场景对齐；若省略该输入，原始结构边界仍可能落在 T3-B 吸收结构文本的 segment 内，不得直接持久化。
4. 全量测试中未运行的 PostgreSQL 项目与本纯规则工作包无关，仍由 T3-GATE 按整体门禁验收。
5. 本包无 UI；用户已冻结的“不考虑 1080P 以下布局”与本后端规则工作包无直接验收项。
