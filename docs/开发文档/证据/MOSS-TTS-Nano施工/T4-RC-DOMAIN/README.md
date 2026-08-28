# T4-RC-DOMAIN 人工句段修正与动作账本证据

- 日期：2026-08-27（Asia/Shanghai）
- 工作包：`T4-RC-DOMAIN`
- 状态：**领域候选与 in-memory 自动化通过；共享加载／HTTP／批准继续生产／PostgreSQL 仍 HOLD**
- 施工边界：只新增窄领域模块、窄测试与本证据；没有修改 ORM、migration、共享分析器、API、Edition、运行时、前端、数据库或容器
- UI 范围：本工作包不涉及页面或布局；低于 1080P 不属于本专项范围

## 1. 已实现事实

`backend/narration/review_actions.py` 暴露以下最小领域接口：

- `CorrectReviewSegment`
- `ReviewSegmentCorrectionResult`
- `correct_review_segment(store, command)`
- `ReanalyzeReviewSegments`
- `reanalyze_review_segments(store, command)`（明确失败关闭）

一次有效人工修正由调用方拥有的同一短事务包住，并按以下权威边界执行：

1. 同 `(owner_id, workspace_id, idempotency_key)` 已有动作时，先比较完整 canonical request hash；同输入只读重放原结果，异输入抛 `IdempotencyConflict`。
2. 新动作锁定 `NarrationRequest`，校验固定本地 scope、显式 generation intent、`review_required`、完整 review pointer 及 `request.version` CAS。
3. 锁定 document 分配互斥点，重新校验 request 当前指针，再校验当前 ScriptVersion 的 version number、immutable hash 与目标 segment local hash。
4. 人工修正不改父版本；它创建 typed immutable child，并为**全部** scene、segment 和 source block 重新派生 version-scoped ID/key。
5. 目标句段写入 owner `manual_current` provenance、服务端已解析的 speaker/casting、high confidence 与 spoken text；只移除可由该人工决定确定解决的 speaker/casting finding，保留 voice rights、音色缺失、发音、云端及 fallback finding。
6. child、scene、segment、issue、`NarrationScriptReviewActionRecord`、request current pointer 与 request version 在调用方同一事务中写入；request version 精确 `+1`，request state 保持 `review_required`。
7. 动作结果写入后再次从持久投影重建 typed contract、immutable hash、来源映射、作用域与账本 provenance；不创建 Edition、render、job、媒体或网络调用。

旧父版本零写入由测试同时比较 ScriptVersion、所有 scene、segment、issue 的 ORM 列快照与父 contract 重载结果，不以“对象看起来未变”代替证据。

## 2. canonical action 与重放结果契约

`patch_segment` 的 request hash 固定包含：

- action contract/version 与 action kind；
- request、父 ScriptVersion、父 segment；
- expected request version、script version number、immutable hash、segment local hash；
- owner actor；
- 完整 typed speaker 与 casting target/decision；
- spoken text 与作者 reason。

公开结果固定返回：action ID、request hash、request version before/after、script ID、parent/result ScriptVersion ID、完整 typed result contract 与 `replayed`。同键原输入即使在该 request 后续又完成其他修正，也重放原 action/result，不倒拨当前 request 指针。

## 3. 自动化覆盖（9 项）

| 场景 | 关键断言 |
| --- | --- |
| 单句修正成功 | typed immutable child、request pointer/version CAS、动作账本、零 Edition |
| 全量 ID 重派生 | 所有 scene ID、segment ID、source block key 与父版本不相交 |
| 父版本零写入 | ScriptVersion/scene/segment/issue 列快照完全不变，父 contract 可原样重载 |
| 幂等 | 同键同 canonical input 零新增重放；同键异输入冲突 |
| 多层人工链 | 第二次修正可读取首个人工 child；旧 manual provenance 保留；首次动作在指针继续前进后仍可重放 |
| CAS 与 stale guard | request version、current pointer、immutable hash、local hash 任一漂移均在写入前失败 |
| finding 边界 | speaker/casting blocker 被移除；`B_VOICE_MISSING` 保留并重指向 child segment ID |
| 当前音色权威 | 已解析 casting 在写 child 前重新校验 profile/version/rights；不可用音色零写入失败 |
| 禁止路径 | 缺 review pointer、speaker/casting 交叉不一致、partial reanalysis 均失败关闭且零新增行 |

## 4. 实际验证

### 4.1 必选窄测试

```bash
.venv/bin/python -m pytest -q tests/narration/test_script_review_actions.py
```

最终结果：`9 passed / 0 failed / 0 skipped`。

### 4.2 相关 typed script 回归

```bash
.venv/bin/python -m pytest -q \
  tests/narration/test_script_review_actions.py \
  tests/narration/test_script_versions_t3_gate.py \
  tests/narration/test_script_analysis.py
```

最终结果：`32 passed / 0 failed / 0 skipped`；未运行 PostgreSQL、容器、真实 HTTP 或 Nano。

### 4.3 允许文件 diff 检查

```bash
git diff --check -- \
  backend/narration/review_actions.py \
  tests/narration/test_script_review_actions.py \
  docs/开发文档/证据/MOSS-TTS-Nano施工/T4-RC-DOMAIN/README.md
```

最终结果：`PASS`（退出码 0、无输出）。

当前项目环境未安装 `ruff`（`.venv/bin/python -m ruff` 返回 `No module named ruff`），所以没有把 lint 表述为已通过；Python import/compile 由 pytest 实际覆盖。

## 5. 明确未实现／失败关闭

### 5.1 局部重新分析

`reanalyze_review_segments()` 当前无条件抛 `InvalidNarrationState`，不创建 action、child 或任何其他行。原因是共享分析器只有完整 document/revision 的分析入口，尚无同时满足以下条件的 subset authority：

- 锁定同一 request/current pointer；
- 对选中旧 segment 做 local hash/anchor CAS；
- 对受影响 source block/scene 执行确定性邻域扩展；
- 重跑 speaker/casting/finding 且不信任客户端结果；
- 为全 child 重派生 ID 并保存 `reanalyze_segments` action；
- 对范围外 manual override 做可验证继承，而不是静默覆盖。

在共享分析器提供上述输入/结果契约前，禁止把“重新分析”按钮接成成功态。

### 5.2 批准与继续生产

本模块不批准 ScriptVersion、不创建 Edition、不推进 `queued`。`approve` 动作必须由唯一集成 Owner 在共享批准/Edition 服务中实现，并满足 0020 的同事务形状：result version 等于当前 version、result Edition 非空、request version 精确 `+1`，且 Edition 确实引用同 request/current approved ScriptVersion。

## 6. 主代理必须完成的精确接线

### 6.1 `backend/narration/script_backend.py`

1. 只有完成本节全部条件后，才能把 `PATCH_SEGMENT` 从 `_HOLD_OPERATIONS` 移除。
2. 在 `Session.begin()` 同一事务中，把 API payload 转为 `CorrectReviewSegment` 并调用 `correct_review_segment()`；不得先提交 child、再另事务移动 request pointer。
3. `SegmentReviewPatch` 原始 speaker 字段不是 casting authority。适配器必须从当前 settings、CharacterVoiceBinding、AnonymousSpeaker/GenericVoiceSlot、VoiceProfileVersion 与权利状态重新解析 typed `SpeakerRef`/`CastingDecision`；不得相信 `speaker_label` 或客户端自报音色关系。
4. 当前 HTTP DTO 没有 `expected_request_version`。必须冻结并补充该字段，或另行批准等强 CAS 契约；直接把锁到的“当前版本”代填会绕过作者所见资源的 request-generation CAS。
5. 成功后用 `result.contract` 构造真实 `ScriptReviewResource`；同键重放必须返回同一 result contract，不能返回“当前最新版本”冒充原 action 结果。
6. 映射 `NarrationCasConflict`、`StaleNarrationInput`、`IdempotencyConflict` 与 `InvalidNarrationState` 为既有 409/422 失败契约；SQL 唯一冲突需重新读取 action 并做 canonical hash 比较，不能统一伪装成 503。

### 6.2 `backend/narration/script_versions.py`

现有 `_build_script_authority_for_candidate()` 明确拒绝 manual attribution，以及 `MANUAL_OVERRIDE` casting；因此现有 `load_script_contract()` / `load_script_version_for_read()` / freeze 路径无法读取本模块产生的人工 child。主代理必须把本模块已经验证的 ledger-backed manual authority 收敛为共享、公开的 typed loader 路径，至少覆盖：

- GET 当前人工 child；
- 后续人工修正读取 parent；
- manual approval/freeze；
- 批准后 Edition 生产与历史只读。

不得通过删除 provenance、把 manual 伪装成 `LOCAL_RULE`、跳过 source mapping/immutable hash，或降级成 legacy read 来“修复”该断链。

### 6.3 `backend/narration/script_api.py`

- 为 patch 冻结 `expected_request_version` wire CAS；同步严格 DTO、前端 client 与测试。
- 只有服务端真实支持的 speaker/casting 选择才能出现在 allowed actions/editor choices；无法解析可用音色时返回 blocker，不显示伪成功按钮。
- `REANALYZE_SEGMENTS` 保持 HOLD，直到共享 analyzer subset 契约与 `reanalyze_segments` ledger 路径落地。

### 6.4 `backend/narration/edition_service.py` / approve 集成

- 批准前必须重载 request current manual child，校验零 blocker、source/settings/current pointer/CAS；不得批准 URL 指定的历史版本。
- approve audit、ScriptVersion approved、Edition、request `review_required -> queued` 与 approve action 必须共享一次数据库事务；任何失败整体回滚。
- 继续生产必须复用现有 `create_production_for_approved_script()` 领域入口，不在 review 模块复制 Edition/job/render 逻辑。

## 7. 已知风险与后续门禁

- 本包只按任务要求使用 fake/in-memory store；尚未证明 0020 在真实 PostgreSQL 上的触发器顺序、复合 FK、并发唯一冲突与事务回滚。
- 同一 request 的并发动作由 request row mutex + version/pointer CAS 串行化；不同 request 误用同一个 workspace idempotency key 时，最终仍由数据库唯一约束裁决。SQL adapter 必须把唯一冲突重读并分类为 replay/conflict，不能返回不确定成功。
- 0020 action 只保存 canonical hash，不保存 canonical payload/reason 明文；它足以比较调用方重放输入，但不能仅凭账本逆向恢复作者 reason。若产品要求可读审计，需要新的已批准 schema，而不是改写 0020 历史。
- 窄模块为避免现有共享 loader 的 manual HOLD，暂时复用了 `script_versions.py` 的私有 typed 投影/authority helper；主集成应把它收敛为共享公共服务，避免长期双 loader 漂移。
- 本模块函数只 `flush` 不 `commit`。调用方异常必须回滚整个事务；禁止在捕获异常后继续提交半成品 Session。
- 一旦真实 action 行存在，它是不可变审计证据。回退应用功能时可重新 HOLD 路由，但不得删除 action/child、倒拨 request 指针或用 downgrade 丢弃证据。

## 8. 文件清单与回退

- `backend/narration/review_actions.py`
- `tests/narration/test_script_review_actions.py`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T4-RC-DOMAIN/README.md`

本候选尚未接生产入口。代码级回退只需保持 patch/reanalyze 路由 HOLD 并移除未接线模块引用；没有数据库、容器、媒体或用户正文副作用。若未来已产生 action/child 数据，必须保留不可变历史并采用向前修复。
