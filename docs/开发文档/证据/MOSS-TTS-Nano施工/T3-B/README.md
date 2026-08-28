# T3-B 确定性切分与 UTF-16 映射证据

日期：2026-08-26（Asia/Shanghai）

结论：**局部候选 PASS；Markdown／纯文本切分已严格消费 T3-A 冻结契约并通过专项验证。T3-GATE runtime 仍为 HOLD。**

## 1. 范围与冻结输入

本工作包只实现：

- Markdown／纯文本的确定性来源块与句段切分；
- Python code point 与浏览器 UTF-16 code unit 双向边界映射；
- 从 `0` 到权威 source 末尾的 block／segment 完整、有序、无重叠分区；
- `paragraph_ordinal`、`source_block_hash`、前后锚点、`source_block_key`、`segment_ordinal_in_block`、`segment_id`和 `segment_kind` 物化；
- Markdown markup、换行、HTML 注释与明示“不朗读”区域的 `spoken_text` 投影，同时保留原始 source range；
- emoji／代理对、组合字符、ZWJ 尾部、CRLF、中英标点、嵌套引号和结构文本负测。

明确非目标：说话人识别、场景推断、云端辅助、匿名身份、选角、情绪、复核、持久化、API、UI、Docker 和数据库。本工作包不宣称自动人物识别／选角或用户可用朗读 runtime 已实现。

消费的只读冻结输入：

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/script_contracts.py` | `c32cd8db3a52ff4a0495ff30947b38a08885c952fd7743b88ee6298a0719656c` |
| `tests/fixtures/narration/script-contract-v1.json` | `558c80d3dd8fa877fc9d58d18727aa9436db61dcd7814a054891c505effbc78d` |
| `docs/开发文档/证据/MOSS-TTS-Nano施工/T3-A/README.md` | `d02e8b149d7b238480c8603eae737bec5fd4f584d33355fe0989dc66c1df4ae9` |

## 2. 产物与契约

| 产物 | 作用 | SHA-256 |
| --- | --- | --- |
| `backend/narration/source_mapping.py` | `SourceIndexMap`、代理对拒绝、完整 UTF-16 分区校验 | `551bf3bd88f0fda94cf7903b415de1cd802ebce4e7938c0afab79ec7bad14be4` |
| `backend/narration/segmentation.py` | 来源块、句段、类型、spoken projection 与冻结 ID／key 物化 | `bb1366e6f557b53658af9d4f5b6e6e905f071ff2ec87d0ee9715478a1873b6e5` |
| `tests/narration/test_segmentation.py` | 专项正负测与篡改拒绝 | `74587abc2b2670b1db79458a2cbddfcf2e25132228ec3bc2e98c4f02ddaf0c1a` |

关键决策：

1. T3-B 输出 `MaterializedSourceBlock` 和 `MaterializedSegment` 中间产物，只包含它拥有的冻结字段；不伪造 scene、speaker、casting 或 review 值。
2. Markdown 标题是有真实源范围的 `heading + narration`；不伪造只允许无源范围的 `chapter_title` 合成句段。
3. 空行、markup、场景分隔符、注释或不朗读区域不单独生成空 `spoken_text` 句段，而是作为邻近可朗读块／句段的 source 结构被完整覆盖。
4. 非空但全部不可朗读的文本失败关闭，因为 T3-A 要求非空 source 必须完整分区，且 source-bound segment 必须有非空 `spoken_text`。
5. 中文直角／弯引号和平衡英文引号保留完整引号段；明示内心 cue 只物化 `inner_monologue` 类型。本层不做人物归因。
6. `validate_segmentation_result()` 重新校验 source hash／长度、两层分区、枚举类型、连续序号、块哈希与锚点、冻结 key／ID，以及由 source 重算的 `spoken_text`；篡改值不能通过。

## 3. 实际验证

必需命令：

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/narration/test_segmentation.py -q
```

结果：`42 passed in 0.06s`。

T3-A + T3-B 联合回归：

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -o addopts='' tests/narration/test_script_contracts.py tests/narration/test_segmentation.py -q
```

结果：`96 passed in 0.28s`（T3-A 54 + T3-B 42）。

其他实际检查：

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile backend/narration/segmentation.py backend/narration/source_mapping.py`：通过；
- `git diff --check -- backend/narration/segmentation.py backend/narration/source_mapping.py tests/narration/test_segmentation.py`：通过；
- 固定种子 `20260826` 的 2,000 份随机 Unicode／Markdown 字符串分别跑 Markdown 和纯文本：3,988 份成功且逐字恢复权威 source，12 份按“无可朗读内容”预期拒绝，无未处理异常。

专项覆盖 42 项：空文本、空白文本、CRLF、emoji／代理对、组合字符、完整分区缺口／重叠，ATX／Setext 标题、fence、链接／强调，前置／后置对话提示语、嵌套引号、内心独白，消息／信件／广播／电话，跨空行不朗读区域、HTML 注释、非法标记闭合、小数点，以及 source hash／anchor／ID／`spoken_text` 篡改负测。

## 4. 剩余边界与 T3-GATE 集成说明

1. 本解析器是为小说正文冻结的无依赖、确定性 Markdown 子集，不宣称是完整 CommonMark AST。复杂嵌套 HTML、异常链接括号或非标自定义标记需在 T3-GATE 样书中继续验证；无冻结需求前不引入第三方 parser。
2. T3-GATE 必须把中间句段与 T3-C–T3-H 的 scene／speaker／casting／evidence／review 结果组装成完整 `SegmentContract`，再调用 T3-A `validate_source_mapping()` 与 authority 校验；本包不能被单独持久化为已冻结脚本。
3. T3-GATE 必须从权威 revision 元数据显式传入 `SourceFormat`，不得根据文本猜测；须将“全空白／全不朗读”错误稳定映射为产品级失败，不能伪造句段。
4. 本包未读取真实小说正文，未运行浏览器／Docker／PostgreSQL／模型，未新增依赖，未改入口与上游。这是后端契约工作包，与低于 1920×1080 的 UI 非目标无关。
5. 无 Git 提交或推送；只有主代理可执行越界复核、共享入口接线、T3-GATE 全量回归和发布。
