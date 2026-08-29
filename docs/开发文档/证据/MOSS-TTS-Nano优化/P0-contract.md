# P0 官方音色直用契约冻结

状态：**2026-08-29 红队修订后候选；规范化 command/receipt 闭包、voice schema v2、旧锁定写者规范化与官方 provenance 正反例已在隔离 PostgreSQL 18 通过 upgrade/downgrade/重升级。但 `0031` 线性依赖计划 34 的未完成 `0030`；只有 `GATE-VM34-MIG-INTEGRATED` 通过并完成 P0 汇合回归后，才可标记冻结。长期数据库未迁移。**

## 1. 结论

当前 `locked = quality_state accepted + 人工试听确认` 的旧约束无法诚实表达“作者直接选择官方预设即可使用”。P0 采用最小追加迁移，不伪造试听、ModelRun、`quality_confirmed` 或人工 actor：

- 旧试听确认版本：`activation_basis=preview_confirmed`、`validation_basis=human_accepted`、`quality_state=accepted`；
- 官方直用版本：`activation_basis=explicit_official_preset_selection`、`validation_basis=not_required`、`quality_state=pending`；
- 后续人物一键生成/实验枚举可预留，但 P0 的 locked 约束与可用性判定必须拒绝 `machine_validated`；只能由后续 `VG-CONTRACT-GATE` 的新迁移在证据闭合后打开；
- 非 locked 版本只能保持 `preview_confirmed + pending`；上传音色现行门禁不变。

`quality_state=pending` 在官方直用场景表示“没有人工质量听检事实”，不表示不可用。可用性由受约束的 `state + activation_basis + validation_basis + source_type` 组合判定。

## 2. canonical 身份

容器身份契约版本固定为 `moss-tts-official-preset-identity/1.0`；官方直用版本身份固定为 `moss-tts-official-preset-direct-version-identity/2.0`，指纹 schema 为 `narration-official-preset-direct-version/2.0`。

- profile UUIDv5 输入：契约版本、固定本地 owner、固定本地 workspace、小说 UUID、preset ID；同一本小说的同一官方预设始终落到同一 profile 容器。
- direct version UUIDv5 输入：契约版本、profile UUID、activation/validation basis、固定模型 revision、manifest SHA-256、preset provenance fingerprint、rights policy fingerprint、decode contract version、官方默认参数 digest；隐藏试听版本不使用该 direct ID。
- profile 在模型/manifest/参数更新后保持稳定；version 随任何不可变输入变化。
- 旧手工创建的 preset 版本不迁移、不合并、不改名。只有精确 canonical ID 和完整指纹一致时复用。
- canonical profile 被归档后，只有作者再次点击“使用”才恢复为 active；`unavailable` 不自动恢复。

## 3. 原子命令与重放

命令入口：`POST /novels/{novel_id}/official-voice-selections`，必须携带 `Idempotency-Key`。

请求只允许：

- `preset_id`；
- narrator target：`expected_settings_version`；
- character target：`character_id`、`expected_settings_version`、`expected_binding_version`。

客户端不得提交 provenance、模型路径、prompt codes、语言覆盖、权利结论或解码参数。服务端从固定目录及当前作品设置派生这些值。

事务顺序固定为：

1. 校验固定 scope 与请求结构；
2. 根据幂等键读取/保留 `VoiceActionReceipt`；
3. completed 时在 CAS 之前由 `VoiceActionCommand` 的规范化列重建 `frozen_result`，不依赖可漂移的任意 JSON；
4. 新命令才锁定小说、设置和目标绑定并校验 CAS；
5. 创建或复用 canonical profile/version 与官方 rights/provenance；
6. 原子更新旁白设置或人物绑定；
7. 写入不可变结果并完成命令/receipt；
8. 任一步失败，整个数据库事务回滚；事务中不调用 Nano、不写媒体文件。

冻结结果包含命令完成时的 profile/version、settings/binding 版本、target language 和语言不匹配标签。响应字段固定为 `frozen_result + current_settings/current_character_binding + selection_still_current`；新请求必须与当前投影一致，幂等重放允许当前绑定已变，但不得改写历史结果。

## 4. 数据库防线

新增：

- `voice_profile_versions.activation_basis`；
- `voice_profile_versions.validation_basis`；
- `voice_action_commands` 不可变命令/结果表。

旧行只做语义等价回填，不改 ID、fingerprint、状态、质量决定、preview、Edition 或绑定。迁移降级在出现官方直用/机器验证证据或任何 action command 后拒绝，要求 fix-forward。

`VoiceActionReceipt.resource_id` 指向 command UUID。command 只允许完整空结果的 `reserved` INSERT 和一次 `reserved -> completed`，completed 后不可更新或删除。deferred composite FK 与双向 constraint trigger 在 commit 时闭合 receipt 的 scope/operation/resource/request hash/state/time，并校验 profile/version/rights、官方模型与 manifest 证据、以及完成时 settings/binding 投影。

`narration-voice/2` 与 `0031` 是协同发布契约。迁移后的旧式 `preview_ready -> locked + accepted + actor/time` 更新由 BEFORE trigger 自动规范化为 `human_accepted`；但一旦写入直用证据，不允许回到不理解 voice v2 的旧应用，只允许在 P0 兼容版内关闭新选择并 fix-forward。

## 5. Catalog v2

`moss-tts-official-preset-catalog/2.0` 始终按 pinned manifest 顺序精确返回 18 项，并提供：

- `validation_tier`；
- `language_scope`；
- `selectable_now`；
- `previewable_now`；
- `renderable_existing`；
- `usage_notice`。

回退只能把受影响项置 `selectable_now=false`；不能缩短 v2。现有 v1 exact-six 只在发现真实外部调用者时保留，否则在 P0 汇合后进入冗余删除清单。

## 6. 反例矩阵

必须由 PostgreSQL 约束拒绝：

- preset 使用人物生成 activation；
- uploaded 使用官方直用 activation；
- 官方直用伪造 `quality_state=accepted` 或人工 lock actor；
- preview-confirmed locked 缺少人工证据；
- 非 locked 行携带直用/机器验证 evidence，或 P0 试图将 machine-validated generated 版本 locked；
- completed command 缺少规范化结果列、正版本号或目标版本；
- command 与 receipt 的 scope/operation/request hash/state/time 不一致，或 command 跨小说引用 profile/version/rights；
- 预设 ID 看似正确但 model/revision/parameters/provenance/rights 任一伪造；
- narrator command 携带 character，或 character command缺少 character；
- completed command 的任何改写或删除。

必须允许：

- 旧 draft/preview/unavailable/deleted 行原样存在；
- 旧 preview-confirmed locked 行原样可用；
- 官方 preset 以未人工听检事实直接 locked；
- 同 key/同 payload 丢响应后重放冻结结果，不被旧 CAS 阻断；
- 同 key/不同 payload 冲突；并发首次选择只有一个命令结果。

## 7. 自审

- 没有把本地个人使用扩张成下载、外传或商业授权结论；
- 没有放宽上传参考音频的权利与试听确认规则；
- 没有在数据库事务中运行模型；
- 没有重写历史迁移；
- 新表服务于多资源原子结果，不再另建第二份幂等真相；
- 迁移编号按当前工作区实时线性 head `0030` 之后使用 `0031`，未覆盖计划 34 的用户改动；同时明确 `GATE-VM34-MIG-INTEGRATED`：计划 34 的 `0030` 未完成、未复审或 migration owner 未释放前，`0031` 不得独立冻结/发布。
