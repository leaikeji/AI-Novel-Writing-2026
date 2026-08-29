# MNX-DEL 私人音色删除实施证据

状态：**2026-08-29 后端状态机、精确资产计划、物理删除恢复和前端状态/面板候选已完成；隔离 PostgreSQL 与三崩溃边界回归通过。`DEL-RELEASE=HOLD`：持久的撤销截止时间/重启对账循环尚未接入生产 worker，前端也尚无服务端权威 eligibility 投影。UI 未接线，后端路由强制 fail-closed。**

## 1. 已实现的候选

- 追加迁移 `20260829_0032_private_voice_deletion.py`，线性依赖计划 34 的 `0030` 和本计划官方直用 `0031`。新 schema 只扩展删除请求/墓碑底座，不改写历史迁移。
- 同一 profile 只允许一个活跃删除请求，由 PostgreSQL 部分唯一索引与服务层共同保护；创建请求的 Idempotency-Key 持久保存并校验请求哈希。
- 仅允许删除本书范围、全部 version 均为 `uploaded/generated` 的私人 profile；official 或混源 profile 稳定拒绝。
- 未引用 profile 进入 `grace_pending`，30 秒内可撤销；逾期后不再允许撤销。已引用 profile 先冻结影响摘要和 HMAC digest，只需一次确认。
- 确认后原子解除当前旁白/人物/匿名说话人/通用槽位引用，保留不可变 Edition/Manifest/渲染元数据，将相关历史朗读标记为 `unavailable_private_voice_deleted`。
- 每个媒体文件先持久冻结 storage path/hash/generation/device/inode，再 unlink，最后由 request-scoped trigger 写入非空 `deletion_request_id` 墓碑并删除资产行。普通 GC 无法冒充本流程。
- 文件不存在的幂等重放、unlink 失败、中途崩溃、活动 job 先取消后重试都使用同一冻结计划，不重算为新的宽范围删除。
- 历史播放读取在解析旧 Manifest 前检查 Edition 不可用原因，返回稳定、不可重试的“私人音色已删除”错误，不回退到当前绑定。
- 前端候选包含未引用一键删除、30 秒倒计时撤销、已引用影响摘要、音色名精确确认、物理阶段不可撤销、失败重试和外部备份 `unmanaged` 真实文案；默认 capability 为 false。

## 2. 隔离验证

使用一个临时 PostgreSQL 18 容器和独立数据库，没有连接或修改长期 `15432` 数据库。验证结果：

```text
alembic upgrade head (0001 -> 0032)                     PASS
0032 downgrade -> 0031 -> 0032                         PASS
request-scoped deletion trigger / partial indexes      PASS
private voice physical-delete PostgreSQL suite         8 passed
API/resource/playback focused suite                     PASS
frontend voice lifecycle state/panel/styles             17 passed
frontend typecheck                                      PASS
```

PostgreSQL 用例覆盖：

- 官方/混源音色拒绝；
- 未引用 profile 的 grace/cancel/逾期确认；
- 已引用 profile 的冻结影响、解绑、Edition 不可用、文件物理消失和单墓碑；
- unlink 前崩溃、unlink 后/DB finalize 前崩溃、finalize 后崩溃三个边界；
- 已确认请求只允许活动 job 数下降，其他影响漂移仍 fail-closed。

## 3. 未通过的发布门

`DEL-GATE` 要求撤销截止时间到达后不依赖页面点击，且应用重启后会自动继续 `grace_pending/live_deleting/failed-waiting-jobs` 对账。当前生产 Nano 循环位于 `backend/narration/production_runtime.py`，而计划 33 冻结的 DEL 最大文件集未授权在本工作包修改该文件。不能为了假装完成而把一次页面请求当作持久 worker。

另一未完成项是前端需要的 `unreferenced/referenced/blocked` 必须由服务端根据当前与历史引用计算，不能由浏览器从 profile 版本列表猜测。现有 API 尚未返回这个权威投影。

因此当前采用两层关闭：

1. `voice-lifecycle-panel` 未接入生产页面，默认 capability 为 false；
2. 所有私人音色删除 HTTP 路由 `_require_private_voice_deletion_release()` 统一返回 503，即使手工调用 URL 也不会绕过发布门。

## 4. 数据与恢复声明

- 本轮没有迁移唯一长期数据库，没有删除真实私人音色、媒体或小说数据。
- 候选迁移可在隔离库回退到 `0031`；已进入物理删除阶段的精确媒体不能被伪装为可撤销，只能按持久计划收敛。
- 外部 Time Machine、用户快照或其他项目外备份始终标记 `unmanaged`，不声称“全球永久删除”。
