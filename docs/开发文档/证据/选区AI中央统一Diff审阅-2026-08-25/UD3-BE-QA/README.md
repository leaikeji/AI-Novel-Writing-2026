# UD3-BE-QA 后端只读验收

状态：**✅ 原只读运行识别出的数据库与打包门槛已由后续修复解除；UD3-BE-QA 最终通过。第 2–7 节保留首次审计事实，第 8 节记录最终裁决。**

日期：2026-08-25（Asia/Shanghai）。

基线提交：`95ead01e9e4813a57dbd4e66f6116d23798920ee`；同时存在主代理与其他工作包的未提交施工改动，本轨没有修改或回退它们。

环境：Apple arm64、macOS 26.5.2、Python 3.12.13、pytest 9.1.1。

## 1. 范围与数据影响

本轨只读检查当前共享工作区的 `selection_edit` 输入/结果契约、模型规范化、Skill、幂等、失败恢复、scope/实体归属、requested/actual 模型一致性、Diff 性能和打包结果。

- 没有连接 PostgreSQL：专用变量 `AI_NOVEL_TEST_DATABASE_URL` 未配置。
- 没有访问共享数据库、真实小说、QwenPaw 安装态、Agent、模型、真实会话、浏览器或网络。
- 没有修改实现源码、迁移、测试、Git index 或其他工作包证据。
- `scripts/package_plugin.py` 按计划重建了被 Git 忽略的 `build/ai-novel-world-2026/` 验证产物；没有安装或卸载插件。
- 用户数据影响：**0**。

## 2. 必跑命令与结果

### 2.1 后端专项

```text
.venv/bin/python -m pytest tests/test_selection_edit_diff.py tests/test_model_runtime.py tests/test_domain_unit.py tests/test_api_model_orchestration.py tests/test_skill_contract.py
77 passed in 0.48s
```

覆盖并通过：严格 V1 snapshot、字段枚举、UTF-16/哈希、七 operation/Skill 映射、模型候选规范化、项目生成 V2 Diff、双向重建、相同文本无伪变更、幂等复用、`force_new` attempt、失败 actual 模型留痕、按 selection id 恢复，以及 Skill 聊天/任务模式边界。

### 2.2 全量 Python

```text
.venv/bin/python -m pytest
227 passed, 21 skipped, 1 warning in 0.52s
```

警告是 FastAPI TestClient 引入的 `StarletteDeprecationWarning`：当前 Starlette/httpx 兼容层提示未来改用 `httpx2`。它没有造成失败，但属于后续依赖升级债务。

### 2.3 打包

```text
.venv/bin/python scripts/package_plugin.py
/Users/liujia/Documents/AI小说世界2026/build/ai-novel-world-2026
```

命令成功，产物共 82 个文件；未发现 `.env`、`Data`、`node_modules` 或 Git 元数据路径。

### 2.4 工作区检查

`git diff --check` 无输出；本轨开始与完成时的 tracked dirty 文件集合没有因本轨改变。构建目录受 `.gitignore` 管理。

## 3. 21 个 skipped 逐项审计

共同原因：`tests/test_domain_integration.py` 以 `AI_NOVEL_TEST_DATABASE_URL` 作为唯一显式测试库入口；变量未配置，所以 21 项均以 `integration database not configured` 跳过。本项目正式使用 PostgreSQL，这些不是可永久忽略的可选平台测试；它们是**当前环境导致的适用门禁未验证**，本轨没有把任何一项记为通过。

| # | 测试 | 与本专项关系 | 分类 |
| ---: | --- | --- | --- |
| 1 | `test_migration_installs_pgvector_and_authority_tables` | 直接核实复用的 `creative_generation_jobs` 表、模型证据列和唯一约束 | 适用门禁，未验证 |
| 2 | `test_sync_progress_incrementally_materializes_relationships_and_respects_manual_override` | 其他领域非回归 | 适用的全量 DB 回归，未验证 |
| 3 | `test_relationship_graph_is_versioned_atomic_and_layout_persistent` | 其他领域非回归 | 适用的全量 DB 回归，未验证 |
| 4 | `test_draft_cas_checkpoint_search_and_restore` | 与最终正文安全/CAS 间接相关，不是 selection job 自身 | 适用的全量 DB 回归，未验证 |
| 5 | `test_create_novel_is_ready_to_write` | 其他领域非回归 | 适用的全量 DB 回归，未验证 |
| 6 | `test_novel_scoped_queries_and_commands_never_cross_books` | 直接相关的跨书 scope/权限基线 | 适用门禁，未验证 |
| 7 | `test_reviewed_candidate_and_intelligence_are_separate_authority_steps` | 与候选不直接写权威资料的原则相关 | 适用的全量 DB 回归，未验证 |
| 8 | `test_restore_reactivates_target_facts_without_duplicate_commits` | 其他领域非回归 | 适用的全量 DB 回归，未验证 |
| 9 | `test_candidate_adoption_rejects_a_changed_working_copy` | 与最终应用冲突策略间接相关，不是 selection job | 适用的全量 DB 回归，未验证 |
| 10 | `test_six_step_creation_is_persisted_validated_and_idempotent` | 其他领域非回归 | 适用的全量 DB 回归，未验证 |
| 11 | `test_novel_delete_requires_current_version_and_removes_the_exact_novel` | 其他领域非回归 | 适用的全量 DB 回归，未验证 |
| 12 | `test_private_library_presets_produce_immutable_generation_snapshots` | 其他领域非回归 | 适用的全量 DB 回归，未验证 |
| 13 | `test_outline_completion_materializes_roles_and_updates_main_storyline` | 其他领域非回归 | 适用的全量 DB 回归，未验证 |
| 14 | `test_next_chapter_required_roles_reject_uncertain_supporting_inference` | 其他领域非回归 | 适用的全量 DB 回归，未验证 |
| 15 | `test_six_step_chapter_creation_rejects_cross_book_references` | 跨书实体归属的间接基线 | 适用的全量 DB 回归，未验证 |
| 16 | `test_generation_requires_matching_model_evidence_and_acceptance_window` | requested/actual 与终态语义的通用生成基线 | 适用门禁，未验证 |
| 17 | `test_fail_path_preserves_known_actual_model_and_terminal_state` | 直接复用的 creative generation 失败留痕 | 适用门禁，未验证 |
| 18 | `test_concurrent_forced_generation_allocates_unique_attempts` | advisory lock/唯一 attempt 的同类生成基线；当前用例是章节任务 | 适用门禁，未验证 |
| 19 | `test_cover_settings_and_narrative_foreshadow_progress_persist` | selection 可定位字段的实体持久化间接基线 | 适用的全量 DB 回归，未验证 |
| 20 | `test_structured_creative_jobs_keep_failed_attempts_and_model_identity` | 直接复用的任务表、attempt、失败历史和模型证据 | 适用门禁，未验证 |
| 21 | `test_volume_chapter_reorder_delete_guard_and_export_structure` | 其他领域非回归 | 适用的全量 DB 回归，未验证 |

额外检查：`tests/test_domain_integration.py` 当前没有 `selection_edit` 专项用例。因此即使未来把以上 21 项跑绿，仍需用明确隔离数据库补充或执行至少以下真实持久化场景，才能完整覆盖本门禁：

1. 同一 canonical selection input 的 running/ready 复用与 `force_new` 并发 attempt；
2. document 跨书、character/relationship/storyline/foreshadow/outline 跨书 entity id 拒绝；
3. failed job 保存 requested/actual、脱敏错误和 input snapshot，同时不生成 ready output；
4. `kind=selection_edit&selection_id=...` 只恢复当前 novel/document scope 的任务；
5. JSONB V1/V2 原样持久化和重建，终态迟到回调不改写结果。

结论：计划要求的“适用门禁 0 skipped”当前为 **未满足**，不是测试失败，但也不能写成数据库验收通过。

## 4. 12k Diff 性能复测

原文和候选各 12,000 个 Python Unicode 字符，每组 100 次；每次同时验证 base/candidate 双向重建。

```json
{"case":"bounded_fallback","runs":100,"original_chars":12000,"candidate_chars":12000,"segments":1,"p50_ms":1.077,"p95_ms":1.175,"max_ms":2.036,"threshold_ms":100}
{"case":"structured_changes","runs":100,"original_chars":12000,"candidate_chars":12000,"segments":41,"p50_ms":1.315,"p95_ms":1.403,"max_ms":1.479,"threshold_ms":100}
```

两条路径均通过，p95 分别只占 100ms 门槛约 1.18% 和 1.40%。

## 5. 代码与契约复核

### 已核实通过

- 请求快照使用 `extra=forbid` 的严格 DTO，限制 operation、entity type、稳定 field id、persistence、版本语义、选区/上下文长度、UTF-16 和 SHA-256。
- 服务端从路径重新验证 novel/document，并按持久化实体查询 outline、character、relationship、storyline、foreshadow 的 `novel_id`；settings 必须绑定当前 novel。
- `review -> style-review`，其余六种编辑操作 `-> prose-writing`；没有让请求提供任意 Skill。
- input hash 包含 canonical snapshot、Agent、requested Provider/模型、generation contract 和目标字符参数；running/ready 默认复用，显式 `force_new` 才增加 attempt。
- API 在解析、模型身份或 Diff 失败时调用统一失败记录；实际 Provider/模型在已知时保留。complete 路径再次严格比较 requested/actual。
- 模型只拥有 `replacement_text/short_summary`；schema、selection、operation、字符数、warnings、Diff 和 segment id 由项目代码生成。
- 结果验证要求 Diff 严格重建 base/candidate，拒绝伪 replacement、空 segment、非法 Unicode/控制字符和超限结果。

### 待主代理裁决的契约差异

当前 prompt 与两个 Skill 都要求模型回复首字符为 `{`、末字符为 `}`，禁止围栏和对象外自然语言；但 `model_runtime.normalize_creative_generation_json` 明确容忍单个 JSON 围栏或对象外 reasoning，只提取唯一的两字段候选对象，专项测试也把这种容忍行为冻结为通过。

- 正向边界：外围文本不会进入 `output_json`、候选、Diff 或作者字段；多个候选对象、重复 key、候选内状态胶囊和 Skill 工作语句仍会失败。
- 差异：这不是 Skill 宣称的“原始回复严格单对象”，且候选外状态文字目前不参与污染拒绝。
- 建议：若这是为真实 Provider 行为设置的受控传输容错，应在计划/ADR 或 runtime 契约中明确“模型仍被要求严格输出，后端只容忍并丢弃唯一候选外壳”；否则恢复原始回复 fail-closed 语义。当前 DTO 没有漂移，但在裁决前不应把“原始模型输出严格单对象”写成已验证事实。

## 6. 打包洁净度观察

打包命令成功，但 `copy_tree("backend")` 同时复制了本机缓存：产物包含 28 个 `*.pyc`，合计约 756 KiB，并带有多个 `__pycache__` 目录。没有发现密钥或用户数据路径，但这会把本机 Python 3.12 缓存带入支持 Python 3.11 的可分发包。

分类：P2 构建洁净度，不是 selection_edit 功能失败。建议由打包 Owner 在后续修复中排除 `__pycache__`/`*.pyc` 并重新执行打包；本只读 QA 不修改脚本。

## 7. 门禁裁决建议

1. 专项 77 项、全量非数据库 227 项、Skill 契约、打包命令和 12k 性能可记为通过。
2. **暂不通过 UD3-BE-QA 总门禁**：21 个核心 PostgreSQL 用例全部因没有隔离测试库而未验证，且尚无 selection_edit 专项数据库用例。
3. 主代理应创建或确认一个可丢弃、与用户数据隔离的测试库，执行 21 项现有集成测试，并补跑上述 selection_edit 持久化矩阵；不得改用当前共享运行库充当测试库。
4. 在最终 `UD3-G` 前裁决模型外围文本容错是否为正式契约，并把打包缓存列为修复项或有理由接受的已知风险。

## 8. 后续修复与最终裁决

首次审计之后完成以下独立门槛：

1. [UD1-BE-DB-FIX](../UD1-BE-DB-FIX/README.md) 新增 `selection_edit` PostgreSQL 专项覆盖，使用明确 `*_test` 可丢弃数据库迁移到 `20260825_0009`；专项 `3 passed`，带隔离数据库的全量结果为 `251 passed, 0 skipped, 1 warning`。测试后业务表为 0 行，隔离库已精确删除，正式数据库连接与用户数据影响均为 0。
2. 模型外围文本正式裁决为“提示词仍要求裸严格 JSON；运行时只容忍并丢弃单个、唯一、严格两字段候选对象外的 Provider 传输壳”。多个候选对象、重复 key、额外字段、非法常量、状态胶囊和候选内工作语句继续 fail closed；外围文字不持久化、不显示、不进入 Diff 或字段。该容错不改变 V1/V2 领域 DTO。
3. `scripts/package_plugin.py` 已统一排除 `__pycache__`、`*.pyc`、`*.pyo`，契约测试通过；重建产物再次用 `rg --files` 核验为 0 个 Python cache artifact。
4. 最终安装链路重跑的非数据库 Python 结果为 `228 passed, 24 skipped, 1 warning`；这些 skipped 只说明默认安装命令没有注入测试库，不能替代上面的独立 251/0 隔离数据库门禁。

唯一 warning 仍是既有 Starlette/httpx TestClient 弃用提醒，未造成测试失败，作为依赖升级 P2 保留。

最终结论：**UD3-BE-QA 通过。**
