# T3-E 匿名人物稳定身份与历史回放证据

日期：2026-08-26（Asia/Shanghai）

结论：**局部候选 PASS；匿名人物稳定键、同作品作用域、合并、拆分、晋升和不改写历史的回放契约已通过专项验证。T3-GATE runtime 仍为 HOLD。**

## 1. 范围与冻结输入

本工作包只实现纯领域层契约：

- 严格复用 T3-A `anonymous-speaker-stable-key/1` 的稳定键和 UUID 派生，本包不发明第二套算法；
- 服务端权威的 novel、chapter、scene 作用域和 scene—chapter 归属；
- 版本化、可重放的 register、merge、split、promote 操作日志；
- 合并作用域包含、拆分的精确历史引用分区、禁止歧义继承；
- 晋升为同作品正式人物后只改变未来脚本解析，原匿名身份和历史脚本快照保持不变；
- 严格 JSON-safe 操作载荷往返、幂等 action 重试及投影重建。

明确非目标：API／路由接线、数据库迁移、`script_versions.py`、人物卡 UI、选角、音频、Docker、PostgreSQL 与 Git 操作。本包不声称用户已可在页面中合并／拆分／晋升匿名人物。

消费的只读冻结输入：

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/script_contracts.py` | `c32cd8db3a52ff4a0495ff30947b38a08885c952fd7743b88ee6298a0719656c` |
| `backend/narration/contracts.py` | `f5b3028a3dae3d3247110bb3cc8852b9116cfb2c11542c5ecd61df3a3f7efc1f` |
| `tests/fixtures/narration/script-contract-v1.json` | `558c80d3dd8fa877fc9d58d18727aa9436db61dcd7814a054891c505effbc78d` |
| `backend/narration/segmentation.py` | `bb1366e6f557b53658af9d4f5b6e6e905f071ff2ec87d0ee9715478a1873b6e5` |
| `backend/narration/source_mapping.py` | `551bf3bd88f0fda94cf7903b415de1cd802ebce4e7938c0afab79ec7bad14be4` |

## 2. 产物与关键不变量

| 产物 | 作用 | SHA-256 |
| --- | --- | --- |
| `backend/narration/anonymous_speakers.py` | 作用域权威、稳定身份、操作日志、血缘重放和未来解析 | `002c5394053599bf0eceb5bae19ac99d540b7bb9028a339cce84eb9de55907f7` |
| `tests/narration/test_anonymous_speakers.py` | 稳定键／作用域／合并／拆分／晋升／回放正负测 | `c44164cf2cb8bebcf1940c1e33140848e793978dba7643f1a95eeecf77141040` |

本 README 不记录自身 hash，避免自引用循环。

关键不变量：

1. `AnonymousIdentitySeed` 必须用 T3-A 冻结函数重算 stable key 和 anonymous speaker UUID；未知算法版本、篡改的 scope／key／ID 全部 fail-closed。
2. 权威边界只接受同作品 chapter、scene 和 character ID。默认复用限于 scene 或 chapter；novel 作用域必须有明确别名证据或 owner 确认。
3. `anonymous-speaker-operation/1` 日志必须从 ordinal 0 连续、`recorded_at` 不回退、`action_id` 唯一。完全相同的 action 重试幂等；同 ID 不同载荷拒绝。
4. merge、split 和 promote 只接受 owner 操作。merge 目标的作用域必须包含每个源身份，不允许用已合并／已拆分／已晋升的非活跃身份再制造二义。
5. split 必须将父身份及已合并血缘中的权威历史 reference **完整、互斥、无额外值**地分配到至少两个子身份；子作用域还必须同时覆盖其每个已分配 reference 的真实使用作用域。
6. split 父身份不允许隐式继承；未来解析必须提供精确历史 reference，无路由或缺少 reference 均报歧义，不猜测子身份。
7. promotion 仅将未来解析指向同作品 character；已持久化脚本／Edition 继续保留原 `AnonymousSpeakerIdentity`，不因合并、拆分或晋升被改写。
8. wire loader 只接受闭合字段、规范 UUID、微秒精度 UTC 和已知枚举；未知 kind／version、额外字段或非规范顺序不进入回放。

## 3. 实际验证

主计划指定的原样专项命令：

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/narration/test_anonymous_speakers.py
```

结果：exit 0，`37/37` 通过；项目根 `addopts` 已包含 quiet，因此该原样命令的原始末行为 `..................................... [100%]`。为记录明确计数，另执行：

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -o addopts='' -q tests/narration/test_anonymous_speakers.py
```

结果：`37 passed in 0.06s`。

T3-A + T3-B + T3-E 联合非回归：

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -o addopts='' -q tests/narration/test_script_contracts.py tests/narration/test_segmentation.py tests/narration/test_anonymous_speakers.py
```

结果：`133 passed in 0.34s`（T3-A 54 + T3-B 42 + T3-E 37）。

其他实际检查：

- `py_compile` 对 `anonymous_speakers.py` 和专项测试共 2 个文件检查：`2 files passed`；编译产物仅写入自动回收的临时目录，未写入工作区 `__pycache__`。
- `git diff --check`：exit 0；对两个新建源／测试文件额外扫描行尾空白：0 命中。
- 专项 37 项覆盖稳定派生、scene／chapter／novel 范围、别名证据、算法篡改、作用域越界、动作幂等／冲突，merge 链，split 完整分区与多层血缘 reference 重放，promotion 历史不变，以及 register／merge／split／promote 全部 wire 分支。

未读取真实小说正文，未运行模型、浏览器、Docker 或 PostgreSQL，未新增依赖，未修改入口，未暂存、提交或推送。

## 4. 剩余风险与 T3-GATE 接线说明

1. 现有 `anonymous_speakers` 表只有稳定身份、`inferred_json`、`promoted_character_id` 和 `lifecycle_state` 等投影，没有本包可以假定的专用 merge／split 事件表。T3-GATE 必须由唯一集成 Owner 裁决如何在**已批准的现有持久投影**中原子保存 `anonymous-speaker-operation/1` 载荷并可无损重放；若无法做到，runtime 必须继续 HOLD，T3-E 不得自行新建 migration。
2. T3-GATE 必须从服务端同作品查询构造 `AnonymousScopeAuthority`：精确 novel—chapter、scene—chapter、novel—character 关系，以及每个历史 segment/reference 当时的 scene／chapter 作用域。不得相信模型或客户端传入的 ID 集合。
3. owner 身份必须由 T3-GATE 的真实鉴权和作品权限校验后才能物化为 `AnonymousOperationActor.OWNER`；本纯领域包不代替 API 权限层。
4. 持久写入必须在同一业务事务／CAS 中锁定当前 ordinal，先按 `action_id` 识别幂等重放，再追加完整 wire 载荷，重放全日志并比对 DB 投影。不得只直接更新 `lifecycle_state` 而丢失血缘证据。
5. T3-GATE 组装 T3-A `anonymous_speakers` 历史快照时仍使用脚本创建时的稳定身份；merge／split／promotion 仅用于生成新脚本的解析。任何已有 script version、segment、Edition 和音频资产均不做就地改写。
6. split 后接线必须同时传入未来句段的 `usage_scope_kind`/`usage_scope_id` 与确定分支所依据的精确 historical reference ID；无精确唯一证据时转人工复核，不能默认选第一个子身份。
7. 重命名、描述、显示置信度和声音绑定是可变实时元数据，不得借此修改稳定键算法、原 scope 或历史脚本字节。其 API／持久化／UI 不属于 T3-E，继续由 T3-GATE 和后续已分配工作包负责。

T3-GATE 接线前不得将本局部 PASS 改写为“匿名人物功能已对用户可用”。唯一集成 Owner 还需完成持久化适配、共享入口、权限、全量回归和 GATE 记录。
