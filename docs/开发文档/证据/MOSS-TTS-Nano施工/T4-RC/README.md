# T4-RC 人工复核继续生产门禁

状态：**PASS_WITH_T4_K_AND_T4_GATE_PRODUCT_HOLDS / NOT RELEASED**

日期：2026-08-27（Asia/Shanghai）

## 1. 本工作包边界

T4-RC 只补齐同一 generation request 的人工脚本复核闭环：

```text
review_required
  -> 作者修正句段（不可变子 ScriptVersion）
  -> 作者批准（manual_after_review）
  -> request CAS 进入 queued 或更后状态
  -> 同 request 的唯一 Edition、segment/render/job 计划
```

本包继续复用现有 PostgreSQL、现有后台任务表和现有 TTS Sidecar；没有新增数据库、队列、容器或第二套状态机。Nano、FFmpeg、网络及 Sidecar 均不得在上述数据库事务内调用。

本专项 UI 只验收 1920×1080 与 2560×1440；低于 1920×1080 不设计替代布局，也不构成本门禁阻断项。

## 2. 已完成且已复核的候选

- `20260827_0020_narration_script_review_actions.py` 已线性接在 0019 后，在现有 PostgreSQL 中增加 request 当前复核指针、不可变动作账本、唯一批准与 deferred reverse guard。
- 人工修正使用 request/version/immutable hash/local hash CAS；父版本及其 scene/segment/issue 零写入，结果是新的完整 typed 子版本。
- 人工批准候选在同一短事务内执行脚本冻结、request 推进、唯一 Edition、render/job 规划及批准动作账本；成功响应不携带、也不伪造 `edition_id`，客户端只能从同 request 的真实 workflow/Edition 查询得到。
- 旁白音色从 request 冻结设置快照解析；人物只能使用当前作品中 active 且绑定完整的角色；客户端 `speaker_label`、profile/version/binding/casting 均不是服务端权威。
- 前端工作台已接入真实 request_version、句段修正、批准后轮询、真实 Edition 载入及章节/会话/Abort 围栏。
- GROUP、部分重分析以及“任意新增匿名路人身份”仍保持 HOLD；当前匿名身份只接受 typed contract 已授权且仍 active 的记录。
- request、document、Novel、ScriptVersion 与全部声音权威采用确定性锁序；声音图按类型和 UUID 稳定排序，锁前收集、锁后 CAS。公开 `LOCK_VOICE_PROFILE` 路由也已统一为 `VoiceProfileVersion → VoiceProfile`，不再与人工复核形成反序锁。
- `spoken_text` 在 HTTP DTO 与领域入口均限制为最多 4000 个 Unicode codepoint，并拒绝非 NFC 和未配对代理字符。
- production policy、queue factory 和 enqueue 的缺失、异常或错误类型均清洗为 retryable `503 STORAGE_UNAVAILABLE`；已落账的同键历史回放不依赖这些运行时组件。

## 3. 当前验证结果

### 3.1 迁移与 PostgreSQL 约束

- 静态迁移：`10 passed, 1 skipped`。
- exact disposable PostgreSQL 18.6 / `ai_novel_world_2026_tts_test` / head `20260827_0020`：迁移约束与真实后端并发两文件合计 `7 passed`，其中 `test_script_review_backend_postgres.py` 为 `6 passed`。
- 已验证旧行绕过拒绝、指针 CAS、动作不可变、重复 transition 拒绝、无动作的 manual approval 拒绝、合法 approve + Edition + queued 提交，以及有权威数据时 downgrade 拒绝。
- 已验证两个真实 Session 的反向多音色批准、反向修正、PATCH/APPROVE 同键与异键竞争、provider/queue 回滚、deferred commit，以及公开音色锁路由与复核交错；未出现 `40P01`，失败分支无孤儿 action、子版本、Edition、render 或 job。
- 迁移候选 SHA-256：`c83b50c249ccf4989a51fea73d47982996e9e28c4e5763cf26b9aa24150356c1`。

详细记录见 [T4-RC-PG-GATE](../T4-RC-PG-GATE/README.md)。

### 3.2 领域、HTTP 与前端

- 源级人工复核／锁序／失败语义专项：`97 passed`；FastAPI continue 文件：`16 passed`。
- Python narration 全量 JUnit：`1196 tests = 1117 passed + 79 skipped`，`0 failed / 0 errors`；跳过项是未提供各自隔离 live 环境的显式集成测试，不包括上方已单独执行的 head0020 PostgreSQL 门禁。
- FastAPI 真实路由候选已覆盖：force-review 零 blocker、PATCH 子版本、同键重放、异输入冲突、owner approve、同 request 唯一 Edition、workflow/Edition 反查、provider/queue 故障全图零写、故障期间合法历史回放。
- 前端 narration：`38 files / 377 tests passed`；前端全量：`80 files / 717 tests passed`；`pnpm typecheck` 与 `pnpm build` 通过。
- `.venv/bin/python scripts/package_plugin.py` 通过；安装／QwenPaw／Skill／production runtime 契约组合为 `50 passed`。
- 相关 Python `py_compile`、全工作区 `git diff --check` 通过；0020 迁移哈希未漂移。

## 4. 对抗复核与门禁裁决

只读 red-team 未发现 P0 或账本/Edition 绕过，施工中发现并关闭了两个并发可靠性 P1：

1. 多个 request 以相反段落顺序使用相同声音权威时，旧候选可能按不稳定顺序取锁；现已改为固定类型顺序和同类型 UUID 顺序，并以真实 PG 反向请求证明无 `40P01`。
2. 公开音色锁路由原为 `VoiceProfile → VoiceProfileVersion`，与 review 的 `Version → Profile` 相反；现已统一为 `Version → Profile`，真实跨路由交错证明等待发生在 Version，未提前持有 Profile，释放后双方均按各自合法终态收口。

另在真实 PostgreSQL 首轮运行发现 `NarrationEditionState` 的 ORM 主键是 `edition_id`，不能按不存在的通用 `id` 查询；该 P0 候选已改为 `find_one(..., edition_id=...)`，随后完整并发文件连续通过。T4-RC 当前未保留已知 P0/P1。

T4-RC 只放行进入 T4-K/T4-GATE 的集成候选，不等于产品发布。公共 mutation、人工复核、Edition、合成、播放器和编辑器同步仍须固定 QwenPaw、真实 Nano／媒体及 1920×1080／2560×1440 浏览器门禁后，才能翻转产品 capability；低于 1920×1080 继续为非目标。

## 5. 退出条件结果

- **通过：**真实 PostgreSQL 双连接竞争无 `40P01`，同键只产生一个动作/Edition，异键只有一个胜者且无孤儿子版本、Edition 或 job。
- **通过：**provider/queue 缺失、抛错、错类型、enqueue/flush/commit 故障均返回冻结错误结构并证明事务零残留；合法历史回放仍可读取。
- **通过：**新 Session 可从 request 指针和动作账本恢复当前候选与批准结果。
- **通过：**Python narration 全量、前端全量、类型检查、构建、打包、相关宿主契约及 `git diff --check`。
- **后续产品门禁：**只有 T4-K 和 T4-GATE 在固定 QwenPaw、真实 Nano/媒体、1920×1080 与 2560×1440 浏览器中通过，才允许翻转对应产品 capability。
