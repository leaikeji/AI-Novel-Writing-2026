# T3-F 确定性选角与 scope 优先级证据

> 状态：`PASS_LOCAL_CANDIDATE_WITH_T3_GATE_HOLD`
>
> 日期：2026-08-26（Asia/Shanghai）
>
> 工作包：`T3-F`（`PAR-C`）
>
> 结论：已严格消费 T2 声音设置和 T3-A 冻结契约，完成旁白 scope 继承、作品规则、人物专属／继承绑定、匿名绑定与 24 槽确定性通用选角。任一高优先级目标不可用时均输出冻结 blocker，不会静默降级。当前项目仍无已批准 24 槽音色包，因此本结论不表示自动通用选角已在产品 runtime 可用；`T3-GATE` 继续 HOLD。

## 1. 范围、输入与安全边界

本工作包只新增：

- `backend/narration/casting.py`
- `tests/narration/test_casting.py`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T3-F/README.md`

未修改 T3-A 三个冻结文件、`backend/narration/__init__.py`、`script_versions.py`、ORM、迁移、API/UI、主计划、共享入口、依赖、Docker、数据库、密钥或 Git 状态；未读取真实小说或音频，未访问网络，未调用模型。

冻结输入复核值：

| 输入 | SHA-256 |
| --- | --- |
| `backend/narration/script_contracts.py` | `c32cd8db3a52ff4a0495ff30947b38a08885c952fd7743b88ee6298a0719656c` |
| `backend/narration/contracts.py` | `f5b3028a3dae3d3247110bb3cc8852b9116cfb2c11542c5ecd61df3a3f7efc1f` |
| `backend/narration/settings.py` | `2f5c7f3134d224be757cacfa8cfe5c5a86052ddb2ffdb854b8d9a94a087a9000` |
| `backend/narration/voices.py` | `c89fad5f5b5c0f1993579895fd89603bc92ba5b0461d33b8ff7a95aff2b7f1f0` |
| `backend/narration/voice_pool.py` | `4a081cc6e0d69acbdbc1387f384ca63b06c9a4780ba5c9052515b79197b5c4f1` |
| `backend/narration/schemas.py` | `1e189e812cf674b0d9457328d4e74e95fda57a67b62a83f99eb31d299633fdbd` |
| `backend/models.py` | `516b87909d683688e61e0ee8a51c3c26e157ae1c3841e592be20eb6e7f7ef8ac` |
| `T3-A/README.md` | `d02e8b149d7b238480c8603eae737bec5fd4f584d33355fe0989dc66c1df4ae9` |
| `T2-A/README.md` | `c970ebe93cf201e9aa98e93ed87b5297f18b36bc5ac9b04b589c4645b40f3f9d` |
| `T2-E/README.md` | `f1aa10ca676a045c6296d915c9d895402a6c4cb0c827a4257e7f19b3b401401f` |

## 2. 冻结优先级与不降级语义

| 顺序 | 当前可接线来源 | T3-A 决定 origin／target | 失效处理 |
| ---: | --- | --- | --- |
| 1 | 章节旁白设置 | `narrator_setting` / `profile` | 本级有设置但版本／权利失效时立即阻断，不改用分卷 |
| 2 | 分卷旁白设置 | `narrator_setting` / `profile` | 同上，不改用作品级 |
| 3 | 作品级旁白／已启用显式选角规则 | `narrator_setting` 或 `casting_rule` | 最高 priority 匹配规则失效即阻断，不试低优先级规则或人物绑定 |
| 4 | 正式人物 `dedicated` | `character_binding` / exact `binding_id + character_id` | 缺版本／失效／失权即阻断，不改用通用池 |
| 5 | 正式人物 `inherited` | `character_binding` / exact `binding_id + character_id` | 同上 |
| 6 | 已知匿名说话人绑定 | `anonymous_binding` / exact `anonymous_speaker_id` | 失效即阻断，不为同一匿名身份重新抽签 |
| 7–9 | 服务端规则授权的描述、年龄／性别、中性通用槽 | `casting_rule` / exact `pool_id + slot_id` | 只有完整 24 槽均就绪时可用；无合格槽或去重耗尽直接阻断 |
| 10 | 无法安全解析 | `unresolved` | 至少生成 `B_CASTING_TARGET_UNRESOLVED`，不可进入 approved Edition |

T2 当前 `NarrationScopeOverrideValues` 只为旁白、语言、正文规则和停顿开放章节／分卷覆盖；本包因此只对旁白做章节＞分卷＞作品继承，没有伪造一套 T2 不存在的“人物章节绑定”持久协议。句段人工覆盖及其跨版本 provenance 仍属于 T3-G，本包不复制第二套。

## 3. 精确关系、音色可用性与 blocker

### 3.1 服务端 snapshot

`VoiceVersionSnapshot` 只接受服务端读取的 profile/version/fingerprint/scope/status/quality/rights 证据。新工作要求：

- profile 必须是 `active`，且属于当前作品或本地全局库；
- version 必须是 immutable `locked + accepted`；
- rights record 必须存在且当前状态为 `active`；
- uploaded 来源另外必须允许 voice cloning。

character binding 构造时校验 exact `binding_id—character_id—profile_id—version_id`；anonymous binding 校验 exact `anonymous_speaker_id—profile_id—version_id`，若来源于通用槽则额外校验 exact slot voice 和 pool version；generic rule 只能解析它声明的 exact `pool_id—slot_id`；所有成功 `casting_rule` 决定同时生成 T3-A `CastingRuleAuthorityRecord`，绑定 exact `rule_id—rule_version—decision—segment_id—source_local_hash—speaker_target_hash`。

### 3.2 冻结 issue 矩阵

| 情况 | 输出 |
| --- | --- |
| 任何 `unresolved` | `B_CASTING_TARGET_UNRESOLVED` |
| 未配置旁白、无最终 profile/version/slot、24 槽包缺失或无合格槽 | `B_VOICE_MISSING` |
| version 不存在、非 locked/accepted、profile 非 active 或 scope 不匹配 | `B_VOICE_VERSION_UNAVAILABLE` |
| rights record 缺失，或 revoked/expired/review-blocked，或 uploaded 无 cloning 权 | `B_VOICE_RIGHTS_UNAVAILABLE` |
| speaker 未知 | `B_SPEAKER_UNKNOWN + B_CASTING_TARGET_UNRESOLVED` |
| 合法使用通用槽 | `W_GENERIC_VOICE_FALLBACK` |

一个目标同时有 version 和 rights 问题时会同时输出两个专用 blocker，不会用“文件还在”或笼统的 missing 掩盖失权原因。服务端 authority snapshot 自身关系造假、跨作品混入、重复 priority 或 readiness 汇总与槽不一致属于编程／权威输入错误，使用 `CastingInputError` fail-closed，不伪装成可自动批准的 issue。

## 4. 24 槽 readiness 与确定性算法

自动通用选角必须同时满足：

1. pool 为 `ready`、有稳定 `pool_id` 和正版本；
2. 恰好 24 个唯一 slot id/key/position，position 完整覆盖 `0..23`；
3. ready/rights-approved/quality-approved/production-ready 计数均为 24，并且逐槽布尔证据与汇总一致；
4. 逐槽 voice 当前仍通过 locked/quality/scope/rights 复核。

任一槽当前失权即关闭整个自动通用选角，不从剩余 23 槽假装 production-ready。这与 T2-E 当前 `0/24` 且 missing/disabled 的真实产品状态一致。

匹配层级依次是“角色描述／职业标签 + 可兼容人口属性”、“性别／年龄”、“明确中性备用槽”；不做任意全池回退。同一匹配层级内使用 `narration-generic-assignment/1` SHA-256 排序，输入为：

```text
novel_id
+ character_id / T3-E anonymous stable key / group_key
+ pool_id
+ pool_version
+ slot_id
+ slot_key
```

不使用 Python 进程随机 hash。`same_scene_voice_deduplication=true` 时，从调用方给出的 exact scene（场景无法确定时为章节）已用 slot/version 集合中排除；排除只改变可用候选，不改变稳定键。候选耗尽时输出 blocker，不重复撞声。

## 5. T3-A 脚本契约与 Edition 边界

T3-A 保持唯一冻结结构：

```text
CastingDecision fields
= candidate_targets, final_target, origin, rule_id, rule_version

CastingTargetRef fields
= kind, binding_id, character_id, anonymous_speaker_id,
  pool_id, slot_id, profile_id
```

两者都没有 `voice_version_id`，T3-F 不修改该事实。`CastingResolution.resolved_voice` 的 `profile_id/version_id/version_number/fingerprint` 及可选 exact pool/slot 只是瞬态 `ResolvedVoiceSnapshot`，供已批准脚本之后的 Edition 创建重验和冻结；它不得进入 T3-A `casting_json`、不得参与或替换现有唯一 `immutable_hash`。

## 6. 自动化结果

### 6.1 T3-F 专项

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/narration/test_casting.py

33/33 passed
```

覆盖 scope 优先级、高优先级失效不降级、规则 priority、require-review、人物 dedicated/inherited、匿名槽复用、unknown/synthetic pause、24 槽 readiness/汇总防伪、权利撤销关闭整包、确定性重放、同场景去重／耗尽、三级匹配、群体／匿名稳定键、exact pool-slot、rule authority 防改绑，以及 T3-A casting 不含 `voice_version_id` 的边界回归。

### 6.2 T3-A + T2 窄联合非回归

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q \
  tests/narration/test_script_contracts.py \
  tests/narration/test_settings_contract.py \
  tests/narration/test_voice_pool.py \
  tests/narration/test_voices.py \
  tests/narration/test_casting.py

145/145 passed
= T3-A 54 + T2 settings contract 29 + T2 voice pool 9
  + T2 voices 20 + T3-F 33
```

测试只使用内存 immutable fixture，不使用 Docker/数据库/网络/模型或真实文本。联合束只有现有 FastAPI/Starlette `httpx2` 迁移提示，无失败。

### 6.3 静态检查

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile \
  backend/narration/casting.py tests/narration/test_casting.py

git diff --check -- \
  backend/narration/casting.py tests/narration/test_casting.py \
  docs/开发文档/证据/MOSS-TTS-Nano施工/T3-F/README.md

# 三个文件当前均为 untracked，因此额外逐文件执行：
git diff --no-index --check -- /dev/null <file>
```

`py_compile` 和普通 `git diff --check` 均 exit 0；`--no-index --check` 三文件均无 whitespace diagnostic（只因“文件与空输入不同”返回预期 status 1）。

## 7. 产物 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/casting.py` | `1cae9f321a8f4d9d353d62e6aed2df36924f06b929c09df85002be58d4c730b4` |
| `tests/narration/test_casting.py` | `db35750542218bec972fa52ba86e36f24bb17a9eb2ebbba382da8f24ff66f18d` |

本 README 不记录自身 hash，避免自引用循环。

## 8. T3-GATE 唯一接线清单

1. 从同一 request 冻结的 T2 settings snapshot 读取作品旁白和 exact 章节／分卷覆盖，只对当前 chapter/volume ID 构造 `NarratorSelectionSnapshot`。
2. 在服务端从固定 owner/workspace/novel scope 构造 voice snapshot；在脚本冻结与 Edition 创建时都再调用现有 `require_usable_voice`，不信任客户端或旧缓存的 rights/status。
3. 把 T2 `CharacterVoiceBinding` 与 T3-E 已验证 anonymous identity 投影为 exact binding snapshot；不在 T3-F 建立、合并或升级匿名身份。
4. T2 公开 `voice_version/generic_slot/require_review` 规则必须先在服务端解析 exact version 或 pool-slot 关系再构造 `CastingRuleSnapshot`。用于稳定多槽分配的 `automatic_pool` 是服务端内部规则动作，不是新 T2 公开 wire 值；T3-GATE 必须为它提供持久且可重放的 system `rule_id/version`，否则不得构造该规则，自动通用选角保持关闭。
5. 只在独立资产包门禁真实产生 24/24 rights/quality/production 证据后构造 `GenericPoolSnapshot(state=ready)`。当前 T2-E `0/24` 必须继续投影为 missing/disabled，不能用测试 fixture 翻转产品能力。
6. 对 T3-C/T3-D/T3-E 最终已知 speaker 的每个句段调用 `resolve_casting`；同一 scene 按 segment ordinal 累积已用 slot/version，场景不可知时按冻结章节范围累积。
7. 把 `decision`、冻结 issues 和所有成功 rule authority 纳入 T3-A 脚本组装，交由 T3-GATE 唯一 Owner 做完整 source/authority/immutable-hash 校验与 `script_versions.py` 投影。
8. `ResolvedVoiceSnapshot` 不进脚本持久；只在脚本已批准且 blocker 为 0 后，作为现有 `CreateEdition` segment input 的 profile/version/slot 候选，并由 Edition 领域服务在同一权威事务内重验。

## 9. 剩余风险和回退

1. **产品 HOLD 是真实状态**：当前 24 槽资产、权利、质量和 production-ready 均未完成；本包的 ready pool 只是纯内存测试 fixture，不可用于页面、试听、合成或 capability 翻转。
2. **窄适配待 T3-GATE**：T2 wire 的 generic rule 目标是 exact slot；多槽确定性分配所需的 system rule identity/version 必须由唯一集成 Owner 从服务端权威状态中提供。未接线前该路径 fail-closed，不静默伪造 rule ID。
3. **去重集合属于调用方权威**：T3-F 不读 scene 或数据库；T3-GATE 必须用已冻结 scene/chapter 和句段顺序构建排除集。错误集合不会被本包“猜测修正”。
4. **不保证未知未来资产包**：新 pack 仍须通过独立来源、授权、听感、完整性和生产门禁；不得只因数据结构满 24 就标记 ready。

本包无迁移、数据写入、资产或外部副作用。若主代理拒绝候选，回退只需删除本 README 列出的两个实现／测试文件和本证据目录，不需要数据恢复。
