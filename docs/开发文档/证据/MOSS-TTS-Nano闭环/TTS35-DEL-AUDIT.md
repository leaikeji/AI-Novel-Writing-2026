# TTS35-A1-DEL：私人音色删除只读审计

- 审计日期：2026-08-29
- 对应计划：开发计划 35（修订定稿）
- 工作包：`TTS35-A1-DEL`
- 性质：源码、迁移与测试的只读审计；本文不代表功能已经发布或通过 PostgreSQL／长期环境验收
- 审计范围：`backend/narration/voice_deletion.py`、`backend/narration/voice_lifecycle.py`（当前不存在）、`backend/migrations/versions/20260829_0032_private_voice_deletion.py`、`backend/models.py`、删除相关测试与 API 契约
- 禁止范围：未修改源码、测试、迁移、计划 36 文件、数据库或媒体；未执行提交、推送或真实删除

## 1. 审计结论

现有计划 33 候选实现已经具备一条值得保留的安全主干：私人／官方来源隔离、创建请求幂等、影响摘要 HMAC、删除前 CAS、精确资产计划、存储身份校验、物理删除后的数据库墓碑，以及物理阶段三类崩溃边界恢复。相关核心证据位于：

- `voice_deletion.py:203-234`：仅允许 novel-scoped 且全部 Version 均为 `uploaded/generated` 的 Profile，含 `preset` 或混合来源时拒绝。
- `voice_deletion.py:299-430`：计算当前绑定、历史 Edition／Render／Export、资产与活动任务的影响。
- `voice_deletion.py:531-612`：创建请求时校验 Profile version、持久化 `Idempotency-Key`、请求 hash、影响快照、HMAC digest 和 30 秒期限。
- `voice_deletion.py:823-949`：物理围栏前再次锁定 Profile／Version／资产集合，冻结精确资产计划，解除当前绑定并把历史 Edition／Render 标为不可用。
- `voice_deletion.py:951-1107`：事务外 unlink，事务内 finalize；失败后从相同持久化计划恢复。
- `tests/narration/test_voice_deletion.py:273-498`：覆盖真实 PostgreSQL 下的精确删除、官方 Profile 拒绝、30 秒取消和 unlink 前／unlink 后／finalize 后恢复。

但它尚未达到计划 35 的 `DEL` 完成口径。阻断点不是删除算法本身，而是缺少可发布的生命周期闭环：漂移或过期不会进入 `superseded`，等待任务时不可取消且没有超时收敛，没有启动扫描／事件唤醒对账器，没有 novel-scoped 生命周期投影，API 响应没有服务端权威操作属性，且所有物理异常被折叠成同一种可重试失败。当前 API 因常量门禁保持关闭是符合事实的，不能提前开放。

## 2. 当前实现与计划 35 的差距

| 计划 35 要求 | 当前事实与精确证据 | 差距／施工判断 |
| --- | --- | --- |
| 单一 novel-scoped 生命周期入口 | API 仍是全局 `/voice-profiles/...` 和 `/voice-deletion-requests/...`，见 `narration_api.py:1444-1575` | 缺少 `GET /novels/{novel_id}/private-voice-lifecycle`；所有 create/get/confirm/cancel/retry 路由缺少 URL 中的 `novel_id` 与服务端 scope 交叉校验 |
| 一个创建入口，服务端决定是否为无引用 30 秒撤销 | 当前由两个 API 分别传 `discard_unreferenced=True/False`，见 `narration_api.py:1444-1497`；服务层由调用方布尔值决定 command，见 `voice_deletion.py:531-549` | 删除旧 `discard-unreferenced` 分支入口；新 create 根据权威 impact 自动选择 `grace_pending` 或 `requested`，不能让客户端自行声明“无引用” |
| create 保留持久幂等，confirm/cancel/retry 依赖 request ID 单调幂等 | create 已正确持久化 key/hash，见 `voice_deletion.py:550-566`；confirm/cancel/retry API 仍强制但不使用 `_idempotency_key`，见 `narration_api.py:1512-1575` | 保留 create header；移除后三个假 header，并为重复终态调用补齐稳定返回语义 |
| 响应包含 `server_now/execute_after/cancellable/retryable/terminal/failure_code` | snapshot 仅有 execute/expiry/状态和 failure，见 `voice_deletion.py:132-150、493-514`；Pydantic 资源同样缺失布尔属性与 `server_now`，见 `narration_api.py:132-160` | 新投影必须由服务端当前时间和单调状态机派生全部操作属性；前端不得自行猜测终态或用本机时间直接计算权利窗口 |
| 服务端权威 eligibility、引用／资产数量、影响摘要 | impact 快照已有引用、历史、资产和字节数，见 `voice_deletion.py:77-129`；没有生命周期列表与稳定 eligibility 分类 | 新 `voice_lifecycle.py` 聚合私人 Profile、当前 Version、是否官方、eligibility、引用数、资产数、影响摘要和活动请求；官方音色只返回不可删除原因，不暴露操作入口 |
| 漂移、过期、job drain 超时转 `superseded` 并释放活动槽 | Profile version、impact expiry/digest、资产集合变化现在抛出 CAS/Conflict，见 `voice_deletion.py:741-764、834-861`；请求状态不变 | 这是发布阻断项。所有物理围栏前的 Profile／impact／asset-plan 漂移及 impact 过期需在同一事务转为 `superseded`，记录稳定 reason/time；活动唯一索引排除 `superseded` |
| `VOICE_DELETE_WAITING_FOR_JOBS` 可自动重试且围栏前可取消 | 当前首次确认后先写 `confirmed_at`，再进入 `state=failed`，见 `voice_deletion.py:766-785`；cancel 明确拒绝所有已确认请求，见 `voice_deletion.py:622-645` | 现状与计划冲突。等待任务必须保持“尚未物理围栏”的可取消属性，增加 drain deadline；任务释放事件自动唤醒，超时转 `superseded` |
| 启动扫描、状态事件唤醒、最近 deadline、最长 60 秒兜底、批次 25 | 仓库不存在 `backend/narration/voice_lifecycle.py`；搜索不到 deletion reconciler／生产 worker 接线 | 新增唯一生命周期／reconciler 服务；停机先停止领取，持久计划下次启动继续。不得用持续 5 秒轮询替代 |
| 围栏后临时 unlink/storage 失败按原计划重试 | 现有 plan 冻结 storage path/hash/size/generation/device/inode，且 `_resume_failed_request` 恢复同一计划，见 `voice_deletion.py:863-884、1002-1107` | 保留该设计；增加错误分类和自动／手动重试调度，不重新计算资产集合 |
| 文件身份、scope、资产集合异常不可重试且 fail closed | 围栏前异常抛 Conflict；执行期任何异常统一写 `VOICE_DELETE_UNLINK_FAILED`，见 `voice_deletion.py:989-996、1066-1080`；`retry()` 对除 WAITING 外任意 failed 均恢复，见 `voice_deletion.py:697-717` | 必须区分 transient storage/unlink 与 invariant/identity/scope/plan corruption；后者写稳定不可重试 failure code，不能进入 `_resume_failed_request` |
| 单一 readiness provider 驱动路由／UI／health | API 仍依赖 `PRIVATE_VOICE_DELETION_RELEASED=False`，见 `narration_api.py:73-78、1402-1419` | 删除常量门禁，改由同一个 `NarrationFeatureReadinessProvider.private_voice_deletion` 判定 DB schema sentinel、storage、digest、worker/reconciler 全部就绪；任一失败原子 fail closed |

## 3. 现有状态机问题

### 3.1 当前状态集合

ORM 与 0032 的状态约束均为：

```text
grace_pending | requested | cancelled | live_deleting |
live_deleted_backup_pending | completed | failed
```

证据：`backend/models.py:3074-3126`、`20260829_0032_private_voice_deletion.py:118-160`。其中活动唯一索引把 `failed` 和 `live_deleted_backup_pending` 都视为活动状态；因此 pre-fence 漂移只抛异常时，旧请求仍然占槽。迁移 trigger 只把 `completed/cancelled` 设为不可变终态，见 0032 `:164-195`。

另有两个老旧信号需要施工时先做数据审计再裁决：

- `delete_uploaded_original_only` 仍被 ORM／迁移 constraint 接受，但当前服务不会创建该 command；见 `backend/models.py:3082-3085` 与 0032 `:124-129`。
- `live_deleted_backup_pending` 在约束和服务的幂等返回中存在，但当前服务没有任何赋值路径；`external_backup_status` 又固定为 `unmanaged`。若长期库无历史行，它们属于可删除的冗余；若已有历史行，0034 必须先兼容保留，不能破坏迁移历史。

### 3.2 建议冻结后的 v2 转换

建议保持既有物理围栏状态名称，新增 `superseded` 终态并明确“失败是否终态”由 failure code 分类决定：

```text
create(no usage)     -> grace_pending --cancel--> cancelled
                                    \--deadline/reconciler--> live_deleting
create(with usage)   -> requested -----confirm--------------> live_deleting
requested/grace_pending --active jobs--> waiting-for-jobs（可取消、可自动重试）
pre-fence drift/expiry/job timeout ------> superseded
live_deleting --transient unlink error---> failed(retryable) --retry--> live_deleting
live_deleting --identity/scope/plan fault-> failed(terminal, non-retryable)
live_deleting --all exact plans finalized--------------------> completed
```

实现上可以继续用 `failed + VOICE_DELETE_WAITING_FOR_JOBS` 表示等待，但必须让 `cancel()` 在“未创建资产计划且尚未把资产切到 deleting”时可取消，并增加 `job_drain_deadline_at`。若引入独立 `waiting_for_jobs` 状态，0034 的约束、trigger、索引、API Literal 和恢复查询必须一次性同步，避免半升级。

`superseded` 至少应允许从 `grace_pending/requested/failed(waiting jobs)` 进入，并在 trigger 中成为不可变终态。建议新增 `superseded_at` 和稳定 `failure_code`；`server_now` 是响应投影值，不应持久化。若为调度增加 `next_attempt_at/last_attempt_at/job_drain_deadline_at`，trigger 的 canonical immutable 列白名单也必须同步且限制单调更新。

## 4. 0034 迁移建议清单

不得修改已存在的 0032。`20260829_0034_narration_voice_lifecycle_and_experiments.py` 的删除部分应在计划 36 的 0033 稳定后完成：

1. 扩展 `ck_voice_deletion_request_state`，加入 `superseded`。
2. 增加 `superseded_at`；按最终 reconciler DTO 冻结 `job_drain_deadline_at`、`next_attempt_at`、`last_attempt_at` 等必要时间字段，避免预留无消费者字段。
3. 重建 `uq_voice_deletion_requests_active_profile`：排除 `cancelled/completed/superseded`，并依据最终 failure 分类决定哪些 `failed` 继续占槽。不可重试安全失败若仍用 `failed` 表示，应被明确定义为 terminal 并释放槽，或拆分终态，不能靠前端猜。
4. 更新 `narration_guard_voice_deletion()`：允许合法的 `superseded` 转换、禁止终态再变、保持 confirmation write-once、限制调度时间单调变化。
5. 更新所有依赖 request state 的媒体 trigger，尤其 0032 `:276-360` 中的围栏条件，确保只有已确认且持久计划完全匹配的物理阶段可把媒体置为 `deleting`。
6. 注册 readiness 所需 schema sentinel；runtime 未观察到完整 constraint／trigger／index/sentinel 时关闭 deletion capability。
7. 升降级测试固定覆盖 `0031 -> 0032 -> 0033 -> 0034 -> 0033 -> 0034`，并验证 `superseded` 后同一 Profile 可创建新请求。
8. 迁移只改变 schema／约束／trigger／索引，不执行文件删除、模型调用或网络请求。

## 5. API 与生命周期投影建议

新 API 应只保留计划 35 冻结的 novel-scoped 路由。每次操作首先验证 URL `novel_id`、Profile／request `novel_id`、固定 owner/workspace 一致；仅凭 request UUID 不足以代替小说范围校验。

生命周期资源建议至少稳定表达：

- `server_now`：服务端 UTC 时间；前端基于它与 `execute_after` 显示倒计时。
- `eligibility`：例如 `official_not_deletable`、`private_unreferenced_grace`、`private_confirmation_required`、`active_request`、`already_unavailable`、`unsafe_evidence`；具体枚举需在 C0 契约阶段冻结。
- 当前引用计数、历史 Edition/Render/Export 数、资产数、总字节、活动 job 数和简短影响摘要。
- `cancellable/retryable/terminal`：服务端派生，不允许前端按字符串集合复制状态机。
- 稳定 `failure_code`：至少区分 waiting jobs、drain timeout/superseded、profile/impact/asset drift、storage transient、identity mismatch、scope mismatch、plan corruption。

删除无引用私人音色时，create 返回 `grace_pending + execute_after`，reconciler 在期限后自动推进；不需要第二次 confirm。已引用或有历史朗读时，create 返回一次影响摘要，只有一次 confirm。官方音色生命周期可以出现在列表中供解释，但必须始终 `cancellable=false/retryable=false/terminal=true` 或采用清晰的非请求状态，并且没有删除 action。

## 6. 对账器与停机语义

当前没有生产对账器，是常量门禁保持关闭的直接原因。建议实现的最小闭环：

1. 启动时扫描到期 `grace_pending`、可重试 waiting jobs、post-fence `live_deleting/failed(retryable)`。
2. create/confirm/cancel/job state change/retryable failure 后发送进程内事件唤醒。
3. 查询下一 deadline，睡眠到最近期限；没有期限时最长 60 秒空闲兜底。
4. 每批 `FOR UPDATE SKIP LOCKED` 最多领取 25 条，避免多 worker 重复执行；request ID 和精确 plan 仍是幂等权威。
5. 停机先让 readiness provider 撤销 `private_voice_deletion`，再停止领取；正在事务外 unlink 的请求必须保留可恢复 plan，由本轮或下次启动收敛。
6. reconciler 异常退出时 readiness 立即 fail closed；不能继续让 API 接受新请求。

## 7. 测试覆盖审计

### 已有且应保留

- impact 不暴露私人描述文本：`test_voice_deletion.py:46-71`。
- 非法 create idempotency key 与 actor 的 fail-fast：`:74-110`。
- 精确 unlink、Profile/asset 状态与 tombstone：`:273-320`。
- 30 秒取消和官方 Profile 拒绝：`:323-357`。
- 撤销窗口到期后不能取消：`:360-391`。
- unlink 前、unlink 后 finalize 前、finalize 后三类恢复：`:394-498`。
- API 当前 fail-closed 和已删除音色的稳定播放错误：`test_voice_deletion_api.py:47-106`。

### 计划 35 必补

1. Profile version 漂移、impact 内容漂移、impact expiry、资产集合变化、job drain timeout 均原子进入 `superseded`，旧请求终态不可变且释放活动槽。
2. waiting jobs：请求取消 job、仍可 cancel、job released 事件自动重试、超时 supersede；不得依赖手动轮询。
3. grace deadline：无用户 confirm 自动执行；创建后 30 秒内 cancel；重复 cancel/confirm/retry 均为单调幂等返回。
4. novel scope：跨小说读取或操作 request/profile 必须拒绝；官方和 mixed-source Profile 始终无删除入口。
5. API 不再要求 confirm/cancel/retry 的 `Idempotency-Key`；create 重放相同 key 返回同一请求，不同 hash 冲突。
6. 响应 `server_now/execute_after/cancellable/retryable/terminal/failure_code/eligibility/counts` 在每个状态下正确，倒计时不依赖客户端时钟。
7. 围栏前异常不改变 Profile/绑定/Edition/媒体；围栏后 transient storage 只重试原 plan；identity/scope/asset-plan 异常不可重试且 fail closed。
8. reconciler 启动扫描、事件唤醒、最近 deadline、60 秒兜底、批次上限 25、优雅停机与崩溃恢复。
9. readiness provider 在 schema sentinel、storage、digest、reconciler 任一缺失或崩溃时，UI/HTTP/health 同时关闭 capability。
10. PostgreSQL 迁移往返与 trigger 直接 DML 负向测试，尤其 `superseded` 终态不可变及活动唯一槽释放。

## 8. 本次只读验证证据

执行命令：

```text
git status --short
rg --files backend/narration backend/migrations/versions tests/narration | rg '(voice_deletion|voice_lifecycle|0032|models|media_postgres|narration_api)'
rg -n 'VoiceDeletionService|voice deletion|voice_deletion|VOICE_DELETE_WAITING|reconcile.*deletion|deletion.*reconcile' backend tests
.venv/bin/python -m pytest -q tests/narration/test_voice_deletion.py tests/narration/test_voice_deletion_api.py
```

结果：测试输出 `....ssssss.... [100%]`，即 8 项通过、6 项因未提供精确隔离 PostgreSQL 环境而跳过；本工作包未把这些跳过项计为已通过数据库验收。未设置或访问长期数据库，未读取或删除任何媒体。

## 9. 风险排序与交接

- `P0`：先完成 `superseded`、活动槽释放、novel scope、waiting jobs 可取消／超时、reconciler 与 readiness provider；否则 API 必须继续 fail closed。
- `P0`：错误分类必须发生在物理边界两侧；identity/scope/plan corruption 不得被当前统一的 `VOICE_DELETE_UNLINK_FAILED` 当作普通可重试错误。
- `P1`：复用现有精确资产计划和三类崩溃恢复，禁止重写成“重新扫描后删除”，否则会破坏已验证的恢复边界。
- `P1`：对 `delete_uploaded_original_only`、`live_deleted_backup_pending` 做长期库只读数据核验后再决定兼容或删除；不得修改 0032 历史迁移。
- `P1`：补齐隔离 PostgreSQL 全套测试之后才能让 provider 发布 `private_voice_deletion=true`。

审计裁决：`DEL` 当前为 **候选实现基础可复用、发布闭环未完成**。在 0034、novel-scoped API、生命周期投影、事件驱动对账器、稳定错误分类和隔离 PostgreSQL 门禁全部通过前，继续保持服务端删除能力关闭。
