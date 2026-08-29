# MNX-DEL-AUDIT：私人音色删除引用图与冻结写集合

状态：**2026-08-29 只读审计完成；允许进入 profile 删除后端候选施工。`VG1=NO-GO`，本轮不存在 VoiceGenerator candidate 表，candidate trash/restore 分支不建空壳。**

## 1. 审计裁决

1. 首版删除目标只能是一个本书范围的私人 `VoiceProfile`，且其所有 version 的 `source_type` 必须全部属于 `uploaded|generated`。只含 preset 或 preset/private 混源 profile 一律拒绝；不尝试在删除事务内自动迁移官方版本。
2. `VoiceProfileVersion` 和历史 `NarrationEditionSegment` 都保留。锁定 version 不改写为 deleted；profile 置 `unavailable` 即可让 `require_usable_voice()` 阻止新渲染，同时保留历史身份、rights、fingerprint 和审计链。
3. 当前选择必须解除：`NovelNarrationSettings` 清空 narrator pair 并递增 version；`CharacterVoiceBinding` 改为 `unset`、清空 pair 并递增 version；`AnonymousSpeaker.voice_version_id` 清空；引用目标 version 的 `GenericVoiceSlot` 置 `enabled=false`（列非空，不能清空或删除历史 slot）。
4. 所有引用目标 version 的 Edition 保留，统一转 `state=unavailable`、`unavailable_reason=unavailable_private_voice_deleted`。`DocumentNarrationState.current_edition_id` 与 `NarrationEditionState.current_manifest_id` 保留，供页面解释“当前朗读因私人音色删除不可播放”，不得静默切版。
5. 现有 Manifest 是追加不可变证据，不能原地重写 canonical JSON。首版不伪造一个没有音频的新 Manifest；保留 `NarrationEditionState` 的当前指针用于解释历史，播放/媒体 API 必须先检查 Edition 的 `unavailable_private_voice_deleted`，不得继续按旧 Manifest 发放媒体。旧 Manifest/ManifestSegment 全部保留。
6. 相关 render 行保留，转 `quarantined`；EditionSegment 转 `quarantined` 并写 failure code。物理删除范围包含这些 render 的 master/playback 资产，以及受影响 Edition 的 export 资产。正文、script、Edition、Manifest、render 元数据和 playback progress 不级联删除。
7. 私人来源资产范围包含每个 version 的 `reference_asset_id/preview_asset_id`、`VoiceReferenceAssetLink.source_asset_id/reference_asset_id`、`VoicePreview.reference_asset_id/result_asset_id`。同一 asset 去重；只允许 scope、class、path、hash、size 全部可证明的本地 media。
8. 普通 GC 不能删除仍有结构化引用的这些资产。删除请求必须持久冻结每项资产的 storage identity/hash/generation，并以 request-scoped 计划授权 unlink；finalize 后的 `AssetTombstone.deletion_request_id` 必须非空。任何未在计划中的路径都不能删除。
9. 当前 schema 没有项目可审计的备份 manifest/retention evidence。产品只能报告 `external_backup_status=unmanaged`；在线字节核验删除后可进入 `completed`，但不得写“所有备份永久删除”。

## 2. 精确引用图

### 2.1 指向 profile/version 的外键

| 引用表 | 字段 | 删除处理 |
| --- | --- | --- |
| `voice_profiles` | `current_version_id + id` | 保留；profile 置 unavailable |
| `voice_profile_versions` | `profile_id` | 保留全部 version |
| `novel_narration_settings` | narrator version/profile pair | 清空并 CAS/version++ |
| `character_voice_bindings` | version/profile pair | 置 unset、清空并 version++ |
| `anonymous_speakers` | `voice_version_id` | 清空 |
| `generic_voice_slots` | `voice_version_id` | 保留，`enabled=false` |
| `voice_previews` | version/profile pair | 保留执行证据；取消 queued/running，媒体进入计划 |
| `voice_reference_asset_links` | version/profile pair | 保留 provenance 行，媒体进入计划 |
| `narration_edition_segments` | version/profile pair | 保留，标记 quarantined/失败原因 |
| `narration_segment_renders` | `voice_version_id` | 保留，标记 quarantined，关联媒体进入计划 |
| `voice_action_commands` | version/profile pair | 保留不可变命令证据 |
| `voice_deletion_requests` | `voice_profile_id` | 保留删除状态机 |

### 2.2 指向 media 的外键

`VoiceProfileVersion.reference_asset_id/preview_asset_id`、`VoiceReferenceAssetLink.source_asset_id/reference_asset_id`、`VoicePreview.reference_asset_id/result_asset_id`、`NarrationRenderAsset.asset_id`、`NarrationExport.asset_id` 都是删除资产根。`ActiveJobAsset` 和 `MediaGcDeletionPlan` 是执行 fence；存在活动租约时不能进入 unlink。`Novel.cover_asset_id` 不应与 narration 私人音色资产重叠；若重叠则按结构化引用冲突拒绝。

### 2.3 Edition/Manifest/current pointer

- `NarrationEditionSegment` 冻结声音身份，是历史影响的权威查询入口。
- `NarrationManifestSegment.render_id` 可把多个 Edition 指向共享 render；影响集必须从目标 voice version 的 render 与所有 fanout Manifest/Edition 反向闭包计算，不能只看最初请求的小说章节。
- `NarrationEditionState` 和 `DocumentNarrationState` 指针保留；播放 API 先看 Edition unavailable reason，返回稳定错误，不从旧 Manifest 继续暴露已删字节 URL。
- `NarrationExport` 虽然当前产品导出已取消，schema 仍可能存在历史行；受影响 Edition 的 export 资产必须进入计划，行保留并转不可用需要新增明确状态或以 Edition unavailable 阻断读取。首版不得忽略它。

## 3. 影响快照与状态机

删除请求创建时冻结：profile id/version、novel scope、全部 version id/source type、当前旁白/人物/匿名/slot 引用、历史 Edition/render/export 数量、精确资产数量与总字节、活动 job/lease、`external_backup_status=unmanaged`，并计算 HMAC impact digest 与过期时间。

- 无当前/历史/slot/job 引用的私人 profile：`discard_unreferenced_private_voice`，进入 `grace_pending`；`execute_after` 前可 cancel。
- 存在任一引用：`true_delete_private_voice`，进入 `requested`；同一影响弹窗确认一次。确认必须重新计算影响并校验 profile CAS + impact digest + snapshot expiry。
- `live_deleting` 后不再允许撤销；失败只能复用同一 request 与同一资产计划 retry。
- 在线资产全部核验 absent、DB finalize 和 tombstone 对账完成后，因没有受管备份证据，进入 `completed` 并返回 `external_backup_status=unmanaged`。

## 4. 冻结 schema 增量

沿 `0031` 后追加一个线性 migration，且只允许：

- 扩充 `voice_deletion_requests`：`novel_id`、`expected_profile_version`、`execute_after`、`cancelled_at/cancelled_actor`、`impact_snapshot_json`、`impact_expires_at`、`asset_count/total_bytes`、`external_backup_status`、`completed_at/updated_at`；状态加入 `grace_pending|cancelled`，command 加入 `discard_unreferenced_private_voice`；增加同 profile 单一活动请求约束。
- 新建 `voice_deletion_asset_plans`：request/scope/asset、storage backend/path、hash/size/generation、role、state、unlink/finalize 时间、failure code；`(request_id, asset_id)` 唯一。
- request-scoped 数据库约束保证 true-delete tombstone 的 request 非空且 asset 必须属于冻结计划。
- 不创建 candidate 表，不修改历史 migration，不放宽普通 GC 引用保护。

## 5. 冻结实现文件

后端候选允许修改：`backend/models.py`、新 `backend/migrations/versions/20260829_0032_private_voice_deletion.py`、新 `backend/narration/voice_deletion.py`、`backend/narration/media.py`、`backend/narration/schemas.py`、`backend/narration/narration_api.py`、`backend/narration/playback_api.py`，以及对应新测试与迁移测试。只有确有 worker 恢复接线时才可再使用计划最大允许集中的 `worker.py/background/jobs.py`。

前端公共 DTO/API 冻结后，仅新增 `voice-lifecycle-panel/state/styles`，再由主集成者接入现有音色库。不得为了删除 UI 复制一套 profile 列表或 modal 框架。

## 6. 施工前阻断与验证要求

- 计划 34 的 `0030` 和本计划 `0031` 仍在同一 dirty worktree，`0032` 只能作为候选，不能在跨计划 migration head 汇合前发布到长期数据库。
- 测试只使用隔离 PostgreSQL 与临时媒体目录，不操作真实用户媒体。
- 至少覆盖 mixed profile 拒绝、官方 preset 拒绝、无引用 grace/cancel、影响变化冲突、current binding 解除、共享 render fanout、旧 Edition 不可用、计划外 asset 拒绝、unlink 三崩溃边界、tombstone request 非空、retry 幂等、unmanaged backup 文案。
