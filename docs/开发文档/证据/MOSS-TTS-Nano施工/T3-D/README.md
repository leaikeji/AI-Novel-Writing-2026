# T3-D 最小云端说话人分析证据

状态：**T3-D 独立工作包已完成 fake-only 实现与窄测试；不代表真实云端供应商、T3 集成或产品能力已放行。T3-GATE runtime 继续 HOLD。**

日期：2026-08-26（Asia/Shanghai）

## 1. 本工作包完成内容

- `backend/narration/speaker_model.py`：冻结 provider-neutral 的严格请求/响应 wire contract、唯一 prompt template version、受限说话人证据代码和可注入 adapter protocol。本文件没有网络客户端或真实供应商实现。
- `backend/narration/cloud_analysis.py`：只对服务端标记的不确定句段生成 radius-one 最小窗口，进行授权/正文 CAS 双边界检查、requested/actual 模型恒等校验、严格结果解析、HMAC-SHA256 证据和冻结 workflow failure 分类。
- `tests/narration/test_cloud_analysis.py`：仅使用 fake adapter，覆盖外发最小化、未授权 0 调用、身份不匹配、结构错误、外来 ID、正文变化、运行中撤权、adapter 失败、unknown 安全降级和精确 `CloudAuthorityRecord` 绑定。

本工作包未修改 T3-A 冻结文件、持久化、API/UI、共享入口、主计划、依赖、Docker、数据库或 Git。

## 2. 决策边界

```text
本地分析器标记 uncertain target
        |
        v
目标句段 + 最多 1 个前文 + 最多 1 个后文
        |
        +-- 有限、服务端授权的 speaker/casting 候选
        |
        v
授权 + source fingerprint 调用前检查
        |
        v
injected adapter（T3-D 测试只使用 fake）
        |
        +-- actual model identity 由 adapter 可信元数据返回
        +-- model JSON 只能选说话人，不能自报 actual model
        |
        v
严格 schema + allowlist + 调用后授权/source 复核
        |
        v
AttributionEvidence + exact CloudAuthorityRecord
```

模型不是人物或选角权威：它只能在 `BoundSpeakerCandidate` 中选择。每个候选在调用前已绑定完整 `SpeakerRef + CastingDecision`；返回非 allowlist 人物/匿名/群体 ID 会以 `F_SCOPE_VIOLATION` 作废。`unknown` 是唯一隐式安全选项，固定映射为 `SpeakerKind.UNKNOWN + CastingDecisionOrigin.UNRESOLVED`，不猜测人物。

## 3. 外发字段矩阵

| 层级 | 允许外发 | 不外发 |
| --- | --- | --- |
| 顶层 | `schema_version` / `template_version` / `task` | novel/document/revision ID，consent/model-run ID，requested/actual model，任何密钥 |
| 目标 | `segment_id` / 完整目标句段 `text` / `truncated=false` | `source_local_hash`，整章正文，working copy，正文 revision 实体 |
| 上下文 | 最多各 1 个相邻 `segment_id/text/truncated`；前文只留靠近目标的尾部 600 字符，后文只留头部 600 字符 | 其他段落、整场景正文、整章 |
| 场景 | 可空、最长 120 字符的 `scene_hint` | 场景账本、世界设定、关系图 |
| 前一说话人 | 可空的类型化 speaker identity；只允许旁白/unknown/当前候选 | 未入选人物卡或其他场景人物 |
| 候选 | 最多 16 个；`speaker` 类型化 ID、`display_name`、最多 8 个别名、最长 80 字符 `role_hint` | 全人物库、完整人物卡、人物秘密、参考音频、音色设置、casting binding/profile/slot ID |

模型响应只包含 `schema_version / segment_id / speaker / confidence / evidence_codes`，不允许自由文本解释、severity、approval、casting、actual model 或任意扩展字段。JSON 重复 key、`NaN/Infinity`、未知字段、非 canonical UUID、错误 identity discriminator 和未知 enum 均 fail-closed。

## 4. T3-A 证据绑定

每个成功结果直接构造 T3-A `AttributionEvidence(origin=cloud_assisted)` 与 `CloudAuthorityRecord`，其中：

- `consent_id`：本次检查的作品授权快照 ID；
- `model_run_id`：必须由上层服务端事先分配，T3-D 不随机生成，以便幂等 replay；
- `input_digest_key_id + input_digest`：对实际 canonical 外发 JSON 做 HMAC-SHA256；
- `output_digest`：使用同一 key 对经严格解析后的 canonical 响应投影做 HMAC-SHA256；
- `model_fingerprint`：只取 adapter 可信 actual identity，并且必须与 requested identity 完全相同；
- `segment_id + source_local_hash + speaker_target_hash`：绑定精确目标句段、正文和服务端 speaker/casting decision，防止证据改绑。

HMAC key 只以注入的 `HmacDigestKey` 存在于运行内存，最小 32 bytes；测试使用固定假 key。代码不读取 `.env`、真实 keyring 或密钥文件，不把 key 写入返回结果、错误或证据文档。

## 5. 失败分类

| 失败码 | T3-D 触发条件 | 结果 |
| --- | --- | --- |
| `F_ANALYZER_RUNTIME` | guard 或 adapter 未分类运行异常 | 安全错误，不携带 source/adapter 异常文本，无权威写入 |
| `F_MODEL_IDENTITY_MISMATCH` | adapter actual provider/model/fingerprint 不等于 requested | 结果作废，不回退另一模型 |
| `F_MODEL_OUTPUT_SCHEMA_INVALID` | JSON/严格 schema/discriminator 非法 | 结果作废，不猜测修复 |
| `F_INPUT_FINGERPRINT_CHANGED` | 调用前或接受结果前任一窗口句段已改变 | 调用前变化时 0 外发；迟到结果丢弃 |
| `F_SCOPE_VIOLATION` | consent 作品/模型不匹配，model-run 映射不精确，或响应 segment/speaker 不在 allowlist | 结果作废，不回显外来实体 |
| `F_CONSENT_REVOKED_BEFORE_CALL` | 非 active/错告知版本，或调用前/接受结果前的最新 consent 检查失败 | 调用前失败时 0 外发；运行中撤权丢弃迟到结果 |
| `F_ADAPTER_UNAVAILABLE` | 未注入 adapter 或 adapter 明确不可用 | 不静默切换供应商/模型 |

冻结 taxonomy 当前没有独立 `F_CONSENT_REVOKED_DURING_CALL`；因此调用后接受边界的撤权仍使用现有 `F_CONSENT_REVOKED_BEFORE_CALL`，但结果不发布。如要新增独立失败码，须发布 taxonomy v2，不属于 T3-D。

## 6. 实际验证

执行：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider \
  tests/narration/test_cloud_analysis.py -q
```

结果：`20/20 passed`。

另与冻结 T3-A 契约测试合并运行：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider \
  tests/narration/test_cloud_analysis.py \
  tests/narration/test_script_contracts.py -q
```

结果：`74/74 passed`（T3-D 20 + T3-A 54）。

覆盖的关键断言：

- 相邻不确定目标产生互相重叠但 radius 恒为 1 的窗口；
- 未授权、撤权、consent 作品/模型错配和调用前 source 变化的 adapter 调用数均为 0；
- 响应不能自报 actual model，requested/actual mismatch 只调用 1 次且不回退；
- 恶意重复 JSON key、`NaN`、未知字段、外来 segment/character 均失败闭合；
- guard/adapter 异常的私密 canary 不进入公开错误或 exception cause；
- 成功结果的 T3-A authority 精确绑定 model/segment/source/speaker-casting digest；
- batch 只调用 uncertain target，且要求精确、唯一、服务端预分配的 model-run ID 映射。

## 7. 实现 hash

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/cloud_analysis.py` | `2c98d9912bdfba5852dc33af7644c14115976335cd0913e898c3ec2cb21932e1` |
| `backend/narration/speaker_model.py` | `22a24efc98c8c4807cc7f6500ee3505e7339334aa9cae357809bcec763afdec9` |
| `tests/narration/test_cloud_analysis.py` | `213a1050756c21e4d240da6080b0456bd35bbef57882d084128eb4bda4f312b0` |

T3-A 冻结输入只读参照 hash：

- `backend/narration/script_contracts.py`: `c32cd8db3a52ff4a0495ff30947b38a08885c952fd7743b88ee6298a0719656c`
- `tests/fixtures/narration/script-contract-v1.json`: `558c80d3dd8fa877fc9d58d18727aa9436db61dcd7814a054891c505effbc78d`
- `tests/narration/test_script_contracts.py`: `9db55718c9c3eafd9216c3c74b7da94228abf289a8b87cf6b992e56c09eac3ad`

## 8. T3-GATE 集成说明

T3-GATE 主集成 Owner 必须完成：

1. 从已持久 consent 行构造 `CloudConsentSnapshot`，并以 DB-backed `CloudAnalysisGuard` 在调用前和接受结果前复核 consent/source；
2. 从受控“AI 小说作家”有效模型获取 requested identity，由可信 adapter/usage metadata 给出 actual identity；不得从模型 JSON 取 actual；
3. 在调用前幂等分配/replay `model_run_id`，在现有 `model_run_records` 记录 requested/actual/provider/model/template/HMAC digest 与结果分类；
4. 从受控 secret keyring 注入 active `HmacDigestKey`，不从 `.env` 注入原始 key，并保留旧 key 的只读校验能力；
5. T3-C/T3-E/T3-F 只交付同作品、精确关系、已授权的 `BoundSpeakerCandidate`；T3-D 不生成人物、匿名身份或选角规则；
6. T3-H 为每个成功 cloud-assisted 句段增加 `W_CLOUD_ASSISTED_USED`，并对 unknown/低置信度生成冻结 blocker；workflow failure 不能伪装成 issue 后自动批准；
7. 由 T3-I/T3-GATE 补真实预发 adapter 身份元数据能力、网络捕获字段矩阵、日志 canary=0、重试/idempotency 和持久 round-trip 证据；未通过前产品 capability 保持 false/HOLD。

## 9. 剩余风险

- 本工作包没有调用真实供应商；QwenPaw 有效模型 API 与 usage metadata 是否能稳定提供 provider/model/revision fingerprint，仍需 T3-GATE 实测。
- 实现当前按目标串行调用，未在 T3-D 引入重试、并发或供应商限流；这些必须复用现有 job/attempt/fencing，不得在本模块创建第二套任务系统。
- 目标句段最长 2,000 字符；T3-B 切分集成时必须在进入 T3-D 前满足该界限，不得由 T3-D 静默截断目标。
- 即使是最小上下文仍可能包含敏感内容；产品必须保留作品级明示授权、撤权说明和本地规则优先选项。
- 新匿名人物的稳定身份建立属于 T3-E；T3-D 只能选已由服务端绑定的匿名/群体候选，否则返回 unknown，不伪造 ID。
