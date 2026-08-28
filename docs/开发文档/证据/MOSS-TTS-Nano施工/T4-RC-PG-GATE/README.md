# T4-RC-PG-GATE：0020 真实 PostgreSQL 迁移与反绕过闸门

状态：**PASS（仅表示 T4-RC 的 0020 schema/PG 闸门通过，不代表 T4-RC 或 T4-GATE 整体已验收）**

验证日期：2026-08-27（Asia/Shanghai）

## 隔离与快照

- 只重建并操作明确授权的回环测试库 `ai_novel_world_2026_tts_test`，登录角色与数据库 owner 均为 `tts_test`。
- 实测为 PostgreSQL `18.6`、pgvector `0.8.6`，主机回环端口 `127.0.0.1:15432`。
- 未停止 PostgreSQL 容器，未删除任何 Docker volume，未对 Compose 默认正式库执行迁移或业务写入。
- 实测的 0020 源文件 SHA-256 为 `c83b50c249ccf4989a51fea73d47982996e9e28c4e5763cf26b9aa24150356c1`。
- 最终保留测试库和角色供主代理复核；测试库停在 Alembic `20260827_0020 (head)`，凭据没有写入 Git 或本证据文档。

## 真实迁移顺序

从全新测试库依次执行：

1. 运行 0001–0009 基线后，执行 0010 完整基础迁移、数据库约束负测、0010→0009 条件回退与再升级：`1 passed`。
2. 执行 `0010 → 0019 → 0020`，确认 action table、request 二元指针列和三个 deferred 约束触发器已安装。
3. 在尚无 action/指针数据时执行 `0020 → 0019`，确认先移除反向触发器/函数，再移除 action table、指针约束和列。
4. 再执行 `0019 → head`，确认最终只有 `20260827_0020` 一个 head。
5. 写入真实 action/指针测试数据后，`0020 → 0019` 被 `0020 downgrade refused` 安全拒绝，Alembic 仍保持在 0020。

## 负测与正向闭环

真实 PostgreSQL 专项测试 `tests/narration/test_script_review_postgres.py` 通过 `1 passed`，覆盖：

- 空指针的旧 request 不能进入 queued；首次绑定必须在 analyzing 中执行严格 `version + 1`。
- correction action、子 ScriptVersion 和 request 当前指针必须在提交后精确对齐；孤立 action、重复 request/version 转换均拒绝。
- action ledger 的 UPDATE/DELETE 均被 immutable trigger 拒绝。
- **仅把 ScriptVersion 改为 `approved/manual_after_review`，但不创建 approve action、Edition，也不把 request 推进到 queued，在事务提交时由 `trg_t4_manual_script_approval_required` 拒绝。**
- 创建 Edition 并尝试 request `review_required → queued`，但缺少 approve action，由 `trg_t4_review_action_required` 拒绝。
- 同一事务内写入 manual approval、Edition、approve action 和 request CAS 可合法提交。
- request 后续到达 ready 后，使用不同 `request_version_after` 和不同幂等键追加第二条假 approve，被 partial unique index `uq_narration_review_action_approve_request` 精确拒绝。
- 本次随机 seed request 下 action 共 2 条（correction 1、approve 1），不存在第二条 approve；不以保留库的全库累计行数作为断言。

## 保留库可重复运行复核

- action 幂等键由测试动作名和本轮随机 `seed.request_id` 共同构成，并显式限制为不超过 128 字符；不再与上一轮保留 action 的 owner/workspace 全局唯一键冲突。
- Edition fingerprint 同样使用本轮 `seed.request_id` 和随机 `edition_id` 生成 64 位 SHA-256，避免保留库重跑时触发 `uq_narration_edition_fingerprint`。
- 不重建、不清理、不删除保留库中任何旧行，使用同一 `PGPASSFILE` 连续执行两次 `tests/narration/test_script_review_postgres.py`，结果依次为 `1 passed`、`1 passed`。
- 每轮只对该轮随机 seed request 断言 correction 1 条、approve 1 条；保留库中的历史测试行可累积，不影响闸门语义。

## 静态与元数据闸门

- `tests/narration/test_migrations.py` 全静态集：`10 passed, 1 skipped`；跳过项是需求空库的真实 0010 闸门，已在本次重建后单独执行并通过。
- 0020 定向静态集：`5 passed`。
- Python 语法编译：通过。
- `alembic heads`：`20260827_0020 (head)`。
- `git diff --check -- tests/narration/test_migrations.py tests/narration/test_script_review_postgres.py`：通过。
- 静态断言已冻结最新标记：`became_manual_approved`、manual approval function/trigger/错误文案、action-target deferred trigger、两个复合 FK、request/version unique、request 级 approve partial unique，以及 upgrade/downgrade 反向顺序。

## 结论与保留项

- 在上述冻结快照和门禁范围内，未发现新的 P0/P1 schema 绕过，可安全进入 T4-RC 业务集成测试。
- 测试库特意保留在 0020 head 供主代理复查；如 0020 文件再发生任何修改，本证据立即过期，必须从全新的同名隔离库重跑全链。
- 本闸门不审查 1920×1080 以下布局，也不扩大到 TTS 播放器、编辑器或 Nano 运行时验收。
