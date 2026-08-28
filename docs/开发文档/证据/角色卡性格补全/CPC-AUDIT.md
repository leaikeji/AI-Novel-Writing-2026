# CPC-AUDIT：角色 `details` 调用方与兼容风险审计

状态：已完成只读静态审计；未修改代码、数据库、迁移或正式角色资料。

审计日期：2026-08-26（Asia/Shanghai）

对应计划：[26-角色卡性格补全与扩展字段安全保存开发计划](../../26-角色卡性格补全与扩展字段安全保存开发计划.md) 的 `CPC-AUDIT`。

## 1. 范围、方法与证据限制

本报告检查当前工作区中的生产代码、前端请求、迁移定义和相关测试，目标仅为：

1. 枚举角色创建、更新和绕过角色 API 直接物化角色的调用方。
2. 枚举当前存在的旧 `details` 请求形状。
3. 核实 `NovelCharacter.details` 的实际持久化约束、已知字段和整包覆盖风险。
4. 给出 `CPC-SAFE-SAVE` 所需的兼容测试清单与集成建议。

审计开始时工作区已有大量其他专项的未提交改动。本报告以审计时工作区为“施工中候选事实”，不把未提交代码表述为已经发布或验收。

本工作包禁止访问和写入真实数据库，因此：

- 没有重新查询《刑侦1988:档案里消失的人》的正式数据。
- 第 4.2 节的真实小说字段形状仅引用计划 26 第 1.1 节已经冻结的“已核实事实”，本报告不重复验证字段值和内容。
- 没有运行会创建测试数据的 PostgreSQL 集成测试。

## 2. 结论

当前角色 `details` 是一个无字段级数据库约束的 JSONB 对象。生产更新链路使用整包替换，而正式角色编辑弹窗只回传四个可见字段，因此作者只要保存一次角色，就可能删除全部未展示扩展字段。

当前存在两条独立的整包覆盖路径：

1. 正式角色 `PUT`：`update_novel_character()` 直接执行 `character.details = details`。
2. 大纲完成：`complete_outline_draft()` 直接执行 `character.details = incoming_details`；审计时的候选代码只单独保留了旧 `gender`，其他正式扩展字段仍会丢失。

`CPC-SAFE-SAVE` 不能只改前端字段名。后端领域函数必须成为唯一 patch 合并权威；兼容期内旧 `details` 请求也必须解释为字段级 patch，否则旧前端、旧会话或其他 HTTP 客户端仍可触发数据丢失。

## 3. 全部角色写入调用方

### 3.1 `create_novel_character()`

定义：`backend/creative_services.py:759-791`。

生产调用方只有一个：

| 调用方 | 位置 | 输入 | 当前语义 |
| --- | --- | --- | --- |
| 角色创建 HTTP API | `backend/creative_api.py:399-417` | `CreateCharacterRequest.details` | 把整个 `details` 作为新角色初始 JSONB；创建时没有旧字段可被覆盖，但没有字段 allowlist、值类型或长度约束 |

直接测试调用方：

- `tests/test_domain_integration.py:396,404,496,504,590,1295,1346,1354,1362,1442,1450`
- `tests/test_selection_edit_domain_integration.py:382`

这些测试调用不是第二条生产写入路径，但它们固定了旧服务签名 `details: dict[str, Any]`，实施兼容层时必须继续可用，或由主代理一次性迁移测试调用并保留 HTTP 兼容测试。

### 3.2 `update_novel_character()`

定义：`backend/creative_services.py:794-834`。

生产调用方只有一个：

| 调用方 | 位置 | 输入 | 当前语义 |
| --- | --- | --- | --- |
| 角色更新 HTTP API | `backend/creative_api.py:420-441` | `UpdateCharacterRequest.details` | 先按 `character_id + novel_id` 加行锁并校验 `expected_version`，然后整包替换 JSONB |

直接测试调用方：

- `tests/test_domain_integration.py:567,1284`

CAS 和行锁可以阻止过期版本并发覆盖，但不能阻止“最新客户端只回传四个可见字段”造成的确定性字段删除。

### 3.3 前端正式角色创建与更新

唯一生产 UI 调用位于 `frontend/src/workbench-studio.ts:2792-2821`：

```json
{
  "role_type": "main|supporting",
  "name": "...",
  "description": "...",
  "details": {
    "gender": "...",
    "age": "...",
    "identity": "...",
    "personality": "..."
  },
  "expected_version": 2
}
```

具体风险：

- `openCharacterForm()` 只读取 `gender / age / identity / personality`，见 `frontend/src/workbench-studio.ts:2792-2804`。
- `saveCharacter()` 无论哪些字段真正发生变化，都会重新构造只含四个 detail key 的对象，见 `frontend/src/workbench-studio.ts:2808-2819`。
- AI 助手受控字段只修改同一个 React 表单，最终仍通过上述保存路径落库；它不是独立 API 写入方。字段绑定见 `frontend/src/workbench-studio.ts:2236-2269`。

因此，编辑姓名、人物小传或单个可见 detail，也可能删除未展示扩展字段。

### 3.4 大纲草稿与大纲完成的旁路写入

大纲角色不是通过 `create_novel_character()` / `update_novel_character()` 物化：

1. `frontend/src/workbench-studio.ts:697-711` 把模型返回的任意 `item.details` 放入大纲草稿请求。
2. 手工编辑大纲角色时，`frontend/src/workbench-studio.ts:821-854` 又会把该角色的 `details` 重建为四键对象，可能先在草稿层删除模型或未来版本附带的扩展 key。
3. `UpdateOutlineDraftRequest.characters` 是 `list[dict[str, Any]]`，见 `backend/creative_schemas.py:288-295`。
4. `update_outline_draft()` 复制整个传入 `details`，见 `backend/creative_services.py:532-551`。
5. `complete_outline_draft()` 按姓名寻找既有正式角色并直接赋值 `character.details = incoming_details`，见 `backend/creative_services.py:603-640`。

审计时工作区中的候选修改会保留正式角色已有的非空 `gender`，见 `backend/creative_services.py:629-635`，但仍会删除 `personality`、`secret`、`core_flaw` 等所有未包含在本次大纲草稿中的字段。并且按姓名匹配不满足计划 26 的稳定角色 ID 边界。

### 3.5 明确排除的非调用方

- 朗读角色音色绑定 API 使用独立的 `character_voice_bindings`，不会修改 `NovelCharacter.details`。
- 关系图生成在 `backend/creative_services.py:1513-1523` 读取并序列化完整 `details`，但不写角色 details。
- 助手工作区快照复用 `_character_payload()`，会读取完整 `details`，但字段受损后只能读到受损结果。
- 章节“同步进展”写 `StoryFact.details` 和关系边，不写 `NovelCharacter.details`。
- 角色删除接口只更新生命周期状态，不写 details。
- `tests/narration/test_migrations.py` 中对 `novel_characters` 的原始 SQL 插入只是隔离迁移测试，不是生产角色创建调用方。

## 4. 旧 `details` 请求和实际字段形状

### 4.1 代码和测试中可复核的请求形状

| 来源 | 已观察形状 | 兼容含义 |
| --- | --- | --- |
| Pydantic 默认 | `{}` | 旧客户端可以完全省略 details；创建得到空对象，更新当前会清空全部 details |
| 多数领域测试 | `{}` | 旧服务签名必须考虑空 patch；不能把空对象解释为“删除全部字段” |
| 关系图测试 | `{"gender":"女"}`、`{"gender":"男"}` | 旧更新请求只携带一个 key；patch 后必须保留其他 key |
| 大纲完成测试 | `{"gender":"其他","identity":"学生"}` | 两键部分对象；当前测试只验证 gender 保留，没有验证 identity 之外的扩展字段 |
| 正式角色 UI | `gender / age / identity / personality` 四键，值可能为空字符串 | 兼容期内“key 存在且值为空”应继续表示作者明确清空该字段；未出现的 key 必须保留 |
| 大纲角色 UI | 同样的四键对象 | 草稿编辑也应合并当前 draft item 的未知 key，不能先在前端丢失 |
| AI 大纲结果 | 当前规范化器保留模型 `details` 中的其他 key，并规范化 `gender` | 当前提示只承诺 `gender`，不承诺 `personality`；见 `backend/model_runtime.py:689-722` 与 `backend/creative_services.py:3482-3489` |

`CreateCharacterRequest` 和 `UpdateCharacterRequest` 当前共享同一任意字典字段，见 `backend/creative_schemas.py:298-306`。前端类型 `OutlineCharacterDraft.details` 和 `NovelCharacterRecord.details` 也都是 `Record<string, unknown>`，见 `frontend/src/types.ts:353-381`。目前没有代码级 DTO 能区分完整快照、字段 patch 或删除操作。

### 4.2 已知正式数据字段

根据计划 26 第 1.1 节已经冻结的已核实事实，目标小说的正式角色 `details` 已出现：

- `age`
- `identity`
- `core_flaw`
- `core_motivation`
- `secret`
- `interlock`
- `growth_direction`

计划核验结果是这些角色缺少 `personality`。性别专项候选代码和现有测试还证明项目使用 `gender`。因此当前需要保护的已知 key 至少为：

```text
gender, age, identity, personality,
core_flaw, core_motivation, secret, interlock, growth_direction
```

这不是关闭集合。JSONB 允许历史版本、模型输出和未来功能保存其他 key；安全保存逻辑必须保留所有未提交 key，不能只为上面九个字段写硬编码“复制列表”。

## 5. 数据库与领域约束

### 5.1 已核实约束

- `backend/models.py:738-761`：`NovelCharacter.details` 为 `JSONB`、`nullable=False`、Python 侧 `default=dict`。
- `backend/migrations/versions/20260824_0004_longform_workflow.py:255-278`：原始表定义仅要求 `details` 非空，没有 JSON schema、key allowlist、字段类型、长度、来源或字段级版本约束，也没有数据库 server default。
- `backend/migrations/versions/20260824_0007_relationship_graph.py:18-31`：后续只增加生命周期字段，没有收紧 details。
- `backend/models.py:740-758`：角色具有小说内姓名唯一、位置唯一、`version` 和生命周期字段；这些约束不能自动保护 JSONB 内未知 key。
- `backend/creative_services.py:805-833`：正式角色更新使用 `SELECT ... FOR UPDATE` 与 `expected_version`，但成功后整包替换 details。

### 5.2 覆盖风险矩阵

| 操作 | 当前结果 | 最高风险字段 |
| --- | --- | --- |
| 正式角色弹窗保存 | details 变成四键对象 | `core_flaw/core_motivation/secret/interlock/growth_direction` 及所有未来 key |
| 旧 HTTP 客户端只提交 `{"gender":"女"}` | details 只剩 gender | 除 gender 外全部字段 |
| 旧 HTTP 客户端提交 `{}` | details 被清空 | 全部字段 |
| 大纲角色手工保存 | draft details 变成四键对象 | 模型或未来版本附加的草稿 key |
| 大纲完成匹配到既有角色 | 审计时仅保留旧 gender，其余由草稿整包决定 | 人工 personality、身份、秘密、缺陷、动机、人物互锁、成长方向 |
| 只修改姓名或 description | 同时触发上述整包替换 | 所有未展示 details；CAS 不会阻止 |

删除这些字段还会降低关系图生成和助手上下文质量，因为两个读取方都会消费完整角色 payload。

## 6. 兼容实施建议

### 6.1 冻结单一后端语义

1. 创建角色继续允许 `details` 作为“新对象初始值”；因为没有旧状态，创建不需要 merge，但仍应按冻结 DTO 校验已知字段。
2. 更新角色新增 `details_patch`。patch 使用 detail key 级浅合并：未提交 key 原样保留；已提交 key 替换该 key 的值。
3. 兼容期内旧 `details` 在更新请求中也按同样的 patch 语义处理，不能保留整包替换旧语义。
4. 同一个请求同时提交 `details` 和 `details_patch` 时应拒绝，避免优先级歧义。
5. 空 patch `{}` 是 no-op；某 key 明确提交空字符串仍表示作者清空该字段。
6. 删除未知 key 不通过 `null` 或空 patch 隐式完成；按计划 26 使用单独、受 allowlist 约束的删除命令。
7. 合并必须在角色行锁与 `expected_version` 校验之后执行；服务端使用数据库当前 `character.details`，不能信任客户端回传的“完整对象”。
8. 更新响应继续返回合并后的完整 details，让旧客户端能够刷新到权威结果。

这项修复只改变 JSONB 更新语义，不要求为 `novel_characters.details` 增加迁移。

### 6.2 前端集成

- 正式角色表单应记录 detail dirty key，仅发送实际变化的 `details_patch`。
- 修改姓名或 description 时不发送 detail patch。
- 明确清空 personality 时必须发送 `{"personality":""}`，不能省略该 key。
- 打开再保存但未修改的表单不应制造四个空字符串写入。
- 大纲角色手工保存至少需要以当前 `item.details` 为基线合并四个可见字段；后续稳定 DTO 可进一步改成草稿 patch。

### 6.3 大纲完成集成阻塞项

只修 `update_novel_character()` 不能关闭数据丢失风险，因为大纲完成直接写模型对象。`CPC-OUTLINE` 必须同时做到：

- 既有正式角色按稳定 `character_id` 识别，不按姓名静默匹配。
- 正式角色已有 details 默认全部保留；大纲候选只补齐允许补齐的空字段。
- 非空 `gender` 和 `personality` 绝不由大纲结果覆盖。
- 同名但没有稳定 ID 时返回冲突，由作者决定新建或合并。

## 7. 必须补齐的兼容测试

### 7.1 Schema 与 API 契约

- 旧 `PUT` 请求使用 `details={}` 时是 no-op，不清空正式 details。
- 旧 `PUT` 请求使用 `details={"gender":"女"}` 时只修改 gender。
- 新 `details_patch` 只修改提交 key。
- 同时提交 `details` 和 `details_patch` 返回 422。
- 两者都省略时允许只修改姓名/description，details 哈希不变。
- key 存在且值为空字符串会明确清空该 key。
- 非法 patch 类型、非法已知字段值和超长 personality 被拒绝，正式数据不变。
- 创建接口仍接受旧 `details` 初始对象，并完整返回已保存对象。

### 7.2 领域与 PostgreSQL 集成

使用至少包含以下扩展字段的角色 fixture：

```json
{
  "gender": "女",
  "age": "37岁",
  "identity": "刑侦科长",
  "personality": "重事实但在压力下控制欲增强",
  "core_flaw": "过度承担",
  "core_motivation": "查清旧案",
  "secret": "曾隐瞒证物",
  "interlock": "与记者互相制衡",
  "growth_direction": "学会共享判断",
  "future_extension": {"source":"author"}
}
```

必须验证：

- 只改 personality 后，除 personality 外的 canonical JSON/哈希逐键不变。
- 只改姓名、description、gender、age 或 identity 时，全部未知扩展 key 保留。
- 显式清空 personality 时只有该 key 变为空字符串。
- `{}` patch 不增加版本或按冻结契约只增加实体版本一次；必须由 `CPC-G0` 明确 no-op 版本策略并固定测试。
- stale `expected_version`、归档角色、跨小说 ID 都是零写入。
- 并发两个不同 detail patch 不能 last-write-wins；第二个使用旧版本时返回冲突。
- 输入 patch 字典本身不被领域函数原地修改。
- 更新响应与重新查询结果都包含完整合并对象。

### 7.3 大纲回归

- 新大纲角色生成的 gender、personality 和额外 fixture key 能保存到草稿。
- 手工只改大纲角色 personality 时，其他 draft details 不丢失。
- 完成大纲的新角色获得完整允许 details。
- 既有正式角色含人工 personality 和九个扩展字段时，重新完成大纲逐键不变。
- 既有 personality 为空时只能由作者采用的候选补齐，不能因同名自动覆盖。
- 同名不同角色、角色改名、跨小说 character ID 均不能错误合并。
- 大纲完成任一角色冲突时整个事务回滚。

### 7.4 前端回归

- 编辑姓名或人物小传时请求不含 `details`/`details_patch`，或只含空 patch，且后端数据不丢失。
- 只编辑 personality 时请求精确为 `details_patch.personality`。
- 清空 personality 时请求保留空字符串，不被序列化为缺失。
- 打开已有扩展字段角色并直接保存，不删除隐藏字段。
- API 返回未知扩展 key 时，类型和渲染路径不崩溃。
- AI 助手更新 personality 后仍通过同一 dirty-field patch 保存路径。

### 7.5 下游非回归

- 角色更新后，关系图快照仍包含未修改扩展字段。
- 助手工作区 `characters` section 仍返回完整合并后的 details。
- 朗读 voice binding、关系边、章节角色引用和角色归档行为不因 patch 语义变化而改变。
- 旧直接领域测试中的 `{}`、`{gender}`、`{gender, identity}` 形状均有明确兼容预期，不以机械改测试掩盖行为变化。

## 8. 给主代理的汇合建议

1. `CPC-G0` 先冻结“更新接口中的旧 `details` 等价于 patch”以及空 patch 是否增长版本；否则后端、前端和测试会产生不同语义。
2. `CPC-SAFE-SAVE` 先落后端合并与兼容测试，再切前端到 `details_patch`；这样旧前端在过渡窗口也不会删除字段。
3. `CPC-OUTLINE` 必须作为安全保存的同级关闭条件，不能因正式角色 PUT 已修复就宣告扩展字段安全。
4. 对目标小说生成性格候选前，按计划记录角色 `id/version/details` canonical hash；应用后逐键核对扩展字段，而不是只检查 personality 出现。
5. 本报告只提供静态证据。真实 PostgreSQL 回归、前端测试和目标小说候选必须由主代理在对应门禁中执行。

