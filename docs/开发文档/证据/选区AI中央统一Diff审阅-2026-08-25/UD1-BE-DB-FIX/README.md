# UD1-BE-DB-FIX：selection_edit 隔离数据库覆盖

状态：**✅ selection_edit PostgreSQL 持久化门禁已补齐并通过；全量适用数据库门禁 0 skipped。**

日期：2026-08-25（Asia/Shanghai）。

## 1. 修改范围

本修复只新增：

- `tests/test_selection_edit_domain_integration.py`
- 本证据文件

没有修改 backend 实现、Alembic 迁移、配置、依赖、锁文件、Git index、QwenPaw 安装态、Agent、模型或用户数据。

## 2. 测试代码的数据库保险

新测试继续复用项目既有 `AI_NOVEL_TEST_DATABASE_URL` 约定，并在调用 `create_engine` 前增加 fail-closed 校验：

1. 数据库名必须匹配明确的 `*_test` 命名；默认正式库名 `ai_novel_world_2026` 会在连接前被拒绝。
2. 如果同时配置 `AI_NOVEL_DATABASE_URL`，测试 URL 的 host、port、database 三元组不得与其相同。
3. 未配置测试 URL 时条件跳过，不自行猜测或连接数据库。
4. 每个测试只创建带 `pytest-selection-edit-db-` 前缀的小说；fixture 只清理此前缀，其他记录不在清理范围。

这使测试代码可以安全进入普通全量套件，同时要求发布门禁显式提供隔离库才能取得 0 skipped。

## 3. 新增的真实 PostgreSQL 场景

### 3.1 生命周期、结果与恢复

- V1 canonical input snapshot 原样写入 JSONB。
- execution Agent、requested Provider/模型和 generation contract 持久化。
- project-owned V2 result、纯候选文本、字符数、warnings、稳定 Diff segments 持久化。
- 从数据库重新加载后 Diff 仍严格重建 base/candidate。
- 同一 running/ready 输入默认返回同一 job。
- 按 `kind=selection_edit&selection_id=...` 恢复，只返回当前 novel scope；错误 selection 和另一小说均返回空。
- 显式 `force_new` 形成 attempt 2。
- requested/actual 不一致后 attempt 2 持久化为 failed，保留实际模型和错误信息，不保存候选；迟到 complete 不能覆盖终态。

### 3.2 并发幂等与唯一 attempt

- 两个线程同时以 `force_new=false` 发起同一输入，只产生一个 attempt 1；仅一个调用取得执行权。
- 两个线程随后同时 `force_new=true`，产生唯一 attempt 2、3。
- PostgreSQL 中最终只有三个对应 job，验证 advisory lock 与 `uq_creative_generation_attempt` 的真实行为。

### 3.3 scope/实体归属

- 作品 B 请求引用作品 A 已持久化角色时，服务拒绝 `选区编辑目标实体不属于当前小说`。
- 失败校验没有为作品 B 创建 selection_edit job。

## 4. 隔离数据库方案与实际操作

使用当前 PostgreSQL 服务进程中新建的独立可丢弃数据库：

```text
ai_novel_world_2026_ud1be_selection_test_20260825a
```

安全步骤：

1. 只连接 PostgreSQL 管理库 `postgres`，精确检查上述名字此前不存在，并确认它不等于容器 `POSTGRES_DB`。
2. 使用 `createdb` 创建该新库；没有连接 QwenPaw 正式数据库。
3. 使用本地隐藏凭据构造 URL，凭据未打印、未写入证据或命令输出。
4. 对新库执行当前 Alembic 全量升级，最终 revision 为 `20260825_0009`。
5. 专项与全量测试完成后检查核心业务表记录数均为 0。
6. 使用精确数据库名执行 `dropdb --force`，随后从 `postgres` 管理库确认剩余数量为 0。

可复用的门禁形式如下，`<isolated-test-url>` 必须由调用者安全注入，不能填正式 URL：

```bash
AI_NOVEL_DATABASE_URL=<isolated-test-url> .venv/bin/alembic -c alembic.ini upgrade head
AI_NOVEL_TEST_DATABASE_URL=<isolated-test-url> .venv/bin/python -m pytest tests/test_selection_edit_domain_integration.py -vv
AI_NOVEL_TEST_DATABASE_URL=<isolated-test-url> .venv/bin/python -m pytest
```

## 5. 实际命令结果

空库迁移：

```text
20260823_0001 -> ... -> 20260825_0009
exit 0
```

专项最终结果：

```text
tests/test_selection_edit_domain_integration.py
3 passed in 0.43s
```

首次专项运行曾有一个测试断言把数据库非空默认 `output_json/output_text` 误写成 `None`；模型定义实际冻结为 `{}`/`""`。修正测试期望后全部通过，没有修改 backend 实现。

带隔离数据库的全量结果：

```text
251 passed, 0 skipped, 1 warning in 1.80s
```

唯一 warning 仍是既有 FastAPI TestClient 的 `StarletteDeprecationWarning`，不影响 selection_edit 或数据库结果。

测试清理后、删除隔离库前的只读核验：

```text
current_database=ai_novel_world_2026_ud1be_selection_test_20260825a
novels=0
creative_generation_jobs=0
novel_creation_drafts=0
private_assets=0
asset_presets=0
alembic_version=20260825_0009
```

删除后的管理库核验：

```text
isolated_test_database_remaining=0
```

## 6. 数据影响与门禁结论

- 正式数据库连接：0。
- 正式小说或 QwenPaw 数据变更：0。
- 隔离库在测试前新建，测试后业务表为 0 行并已整库删除。
- 用户数据影响：**0**。
- selection_edit 的 PostgreSQL 输入、结果、模型证据、attempt、失败终态、并发幂等、恢复查询和跨书实体拒绝已有真实覆盖。
- 原先 UD3-BE-QA 中“本功能缺少数据库专项覆盖”和“21 个适用 DB 测试 skipped”两项门槛，在本次明确隔离运行中均已解除。

结论：**UD1-BE-DB-FIX 数据库门禁通过。** 模型外围文本容错和打包 `pyc` 洁净度仍是另一份 QA 记录中的独立裁决项，本修复没有扩大范围处理。
