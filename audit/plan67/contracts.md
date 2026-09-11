# Plan 67 W0 契约冻结

日期：2026-09-11
工作包：`L67-CONTRACT`（SER/GATE）
结论：PASS，可进入 W1。

## 基线与边界

- 当前迁移 head：`20260910_0051`；候选后继为 `20260910_0052`。
- 固定本地 scope 沿用现有 owner/workspace 常量，不接受请求体覆盖。
- 计划 65 代码仍处于工作区候选，W1/W1b 在其上增量施工，不覆盖其他计划改动。
- 长期 `18088`、媒体卷及现有小说在 W4 前只读；测试使用隔离库、fake Provider 与临时媒体。

## 冻结接口

公共 HTTP、错误、幂等、锁序和发布决策以 [ADR-0011](../../docs/开发文档/ADR/ADR-0011-小说回收站与生命周期隔离.md) 为准。内部公共函数冻结为：

- `require_active_novel(session, novel_id, *, for_update=False)`
- `lock_active_novel(session, novel_id, expected_version=None)`
- `lock_recycled_novel(session, novel_id, expected_version=None)`
- `recycle_novel(session, novel_id, expected_version, idempotency_key, actor)`
- `restore_novel(session, novel_id, expected_version, idempotency_key, actor)`
- `list_recycled_novels(session, limit, cursor)`

领域动作只 `flush`，HTTP 编排层提交一次事务。异常独立放在 `backend/novel_lifecycle_errors.py`，避免 `services.py` 反向依赖。

## 入口与所有权清单

- W1b：`creative_api.py` 的回收／恢复／列表／旧 DELETE；`app.py` 和 `services.py` 的基础作品、卷章、文档及搜索入口。
- W2 ACTIVE-GUARDS：助手、Context V4、creative services/authority、人物、故事状态、写作 Skills、私有库绑定与五个 Agent 工具。
- W2 RUNTIME-GUARDS：background enqueue/retry/claim/result publish、embedding consent/index/search/retirement、narration request/job/playback/media/voice/GC。
- W2 FRONTEND：创作中心、回收站、API/types、编辑器 recovery、跨标签生命周期事件和 410 处理。

直接 novel UUID、document/job/asset/edition UUID、PATCH、HEAD/Range/304 入口都必须反查生命周期；`novel_id IS NULL` 的真正全局任务不能因 inner join 被饿死。任一未能经公共 QwenPaw/PawApp 扩展点隔离的入口将阻断 W4，不允许以仅隐藏页面降级。

## 维护回执

永久销毁维护输入绑定 exact UUID、version、目标 manifest SHA-256、数据库/媒体备份标识与 SHA-256、隔离恢复证据。脚本默认 dry-run，不支持标题、通配符、批量清空，也不接受普通 JSON 自报 `verified=true`。

## V0.4 自助彻底删除补充

- 作者已批准回收站内对单书执行第二步删除，并逐字输入 `确认删除`。
- `POST /recycle-bin/novels/{id}/purge` 的严格 body 仅接受 `expected_version` 与固定确认短语；备份路径和验证声明不进入 HTTP。
- 服务端固定解析 `AI_NOVEL_PURGE_BACKUP_ROOT/purge-receipts/{uuid}.v{version}.json`，使用 `novel-purge-backup-receipt/2`，复算数据库、媒体和隔离恢复证据文件摘要并拒绝软链接、越界路径与目标漂移。
- `20260911_0053` 是 0052 的前向后继，只为 `novel_deletion_audits` 增加可空的 `backup_receipt_sha256`；既有历史审计兼容。V0.4 曾要求新 UI 销毁写入非空摘要，该要求已由下节 V0.5 纠偏取代。
- 该纠偏串行施工，不重新派发已汇合的 W2 包；没有批量清空、自动清理或 Agent 永久删除工具。

## V0.5 作者自助删除纠偏

- 实际复现证明 V0.4 的按钮和确认词校验正常，但任何新作品都没有产品内途径生成 UUID＋version 回执，因此请求在进入销毁事务前必然失败。
- 作者路径以严格 `confirmation_text="确认删除"` 生成只绑定 exact UUID＋version 的服务端内部上下文；`backup_receipt_sha256` 允许按既有 schema 记录为 null。活动作品、版本漂移、活动任务、文档集合变化和媒体身份变化仍拒绝。
- v2 回执及摘要复算链继续供本地维护脚本和加强型运维销毁使用，不再是普通作者 UI 的隐藏依赖。两条授权路径共用唯一数据库／媒体销毁服务。
