# 开发计划 35（修订定稿）：MOSS-TTS-Nano 全功能闭环

状态：**2026-08-29 已获用户批准进入施工。** 当前源码施工受计划 36 的稳定提交与迁移 `20260829_0033` 前置门禁约束；门禁满足前只允许开展只读事实冻结与审计，不得修改计划 36 所有权文件。本文中的 `TTS35-*` 工作包 ID 只属于本计划。

## 一、目标与完成口径

当前事实：

- 计划 33 已提交并推送，长期服务健康，固定目录的 18 个官方音色均可查询、试听和直接绑定。
- 新朗读设置页、人物配音表和播放器已有实现，但仍需真实浏览器与章节朗读正式验收。
- 长期数据库仍为 `20260829_0031`；私人音色删除迁移 `0032` 尚未部署，删除接口保持关闭。
- Nano 高级参数已能传入 Sidecar，但尚无安全的异步验证、自动绑定和页面闭环。
- 当前 M4／16 GiB 主机无法安全运行约 10.6 GiB 的 MOSS-VoiceGenerator。

最终分成两个独立终点：

- `CORE-FINAL`：18 音色直用、设置、播放器、人物卡匹配官方音色、高级调音、私人音色删除全部正式可用。
- `VG-FINAL`：人物卡分析后真正生成一条全新专属音色并自动使用。

当前主机必须完成 `CORE-FINAL`；只有 `CORE-FINAL` 与 `VG-FINAL` 分别通过，才允许表述为“TTS 全部功能均可正常使用”。

## 二、产品与门禁设计

| 操作 | 作者操作门禁 |
| --- | --- |
| 选择任意官方音色并使用 | 0 次确认，试听可选 |
| 根据人物卡匹配官方音色并使用 | 点击一次，完成后自动绑定 |
| 创建并使用 Nano 高级调音 | 点击一次，后台机器验证后自动绑定 |
| 恢复官方默认音色 | 点击一次，直接绑定官方 fixed 版本 |
| VoiceGenerator 生成人物专属音色 | `VG-FINAL` 后点击一次，成功后自动绑定 |
| 删除未引用私人音色 | 不弹窗，进入 30 秒可撤销期 |
| 删除已使用或有历史朗读的私人音色 | 只显示一次影响摘要并确认 |
| 官方音色 | 不提供删除入口 |

不增加版权、语言、试听、质量或名称输入门禁。官方来源、模型 revision 和用途证据只保留在后台及折叠详情中。上传第三方参考录音的权利边界保持不变。

### 设置与播放器

- 设置页固定为“基础朗读、官方音色、人物配音、高级调音、私人音色”五个区域，默认只展开日常选项。
- 18 个官方音色全部可搜索、按语言筛选并直接设为旁白或人物声音；跨语言只提示，不阻断。
- 播放器保留播放/暂停、前后段、进度跳播、倍速、音量、当前说话人、失败重试和 Edition 身份；桌面与窄屏均不得遮挡正文或助手。
- 当前实现通过验收的部分不重写；只修复真实缺陷并删除旧六音色限制、旧播放器和重复样式。

### 人物卡一键配音

当前主机提供“根据人物卡匹配官方音色并使用”：

1. 读取计划 36 提供的权威人物工作区快照。
2. 复用 `ai-novel-writer` 生成 `CharacterVoiceBrief/1`，只从已保存的人物资料提取语言、声音表达、音高、语速、能量和质感倾向；缺失项保持未知。
3. 服务端使用同语言官方音色的固定声学基线做确定性评分，AI 不直接输出任意 preset ID。
4. 选择最高分音色，并复用现有官方音色原子绑定服务。
5. 绑定 CAS 未变化时自动使用；发生并发修改时保留结果但不覆盖作者的新选择。
6. 模型失败时显示“一键重试”和手动音色库，不静默退回当前按人物 UUID 哈希分配的旧算法。

新流程验收后删除 `stableOfficialVoiceAssignment` 及其重复前端目录常量。

## 三、公共契约、状态机与迁移

### 1. 统一能力来源

将能力契约升级为 `narration-capabilities/2`，新增：

- `character_voice_matching`
- `nano_advanced_tuning`
- `private_voice_deletion`

新增唯一 `NarrationFeatureReadinessProvider`，同一实例同时驱动：

- 设置页能力矩阵；
- HTTP 路由服务端门禁；
- production runtime／health 状态。

删除 `PRIVATE_VOICE_DELETION_RELEASED` 等常量门禁。数据库结构、存储、digest、Sidecar 协议、处理器和对账器任一未就绪时必须原子 fail closed；关闭或崩溃时先撤销能力，再停止任务。

### 2. Nano 高级调音

开放以下真实参数，界面显示小数，协议继续使用整数千分位：

- `seed`：`0..2^63-1`
- text temperature：`0.1..2.0`，默认 `1.0`
- text top-p：`0.001..1.0`，默认 `1.0`
- text top-k：`1..100`，默认 `50`
- audio temperature：`0.1..2.0`，默认 `0.8`
- audio top-p：`0.001..1.0`，默认 `0.95`
- audio top-k：`1..100`，默认 `25`
- audio repetition penalty：`1.0..2.0`，默认 `1.2`

高级路径固定 `sample_mode=full`、`max_new_frames=375`。首版不提供未经听检的“自然／稳定／活跃”模板，只提供参数重置和“恢复官方音色”。

新增接口：

- `GET /novels/{novel_id}/nano-voice-experiments`
- `POST /novels/{novel_id}/nano-voice-experiments`
- `GET /novels/{novel_id}/nano-voice-experiments/{command_id}`
- `PUT /novels/{novel_id}/nano-voice-experiments/{command_id}/binding`

异步流程固定为：

1. 短事务创建或复用“小说＋基础 preset”唯一实验 Profile，写入不可变 pending Version、命令、VoicePreview 和 BackgroundJob。
2. 事务外执行真实 Nano 合成。
3. 校验音频、ModelRun、requested/actual 模型、参数 digest 和输出 hash。
4. 成功后短事务将 Version 转为 `experimental_machine_validated`，再执行目标 CAS 绑定。
5. CAS 未变化进入 `ready_applied`；CAS 已变化进入 `ready_unapplied`。
6. 合成、校验或数据库失败均不得改变原绑定，不允许静默按官方默认参数重试。
7. 相同参数、seed、模型和 preset 的已验证 Version 可复用；不同输入必须形成不同 fingerprint。

### 3. 私人音色生命周期

统一为 novel-scoped API：

- `GET /novels/{novel_id}/private-voice-lifecycle`
- `POST /novels/{novel_id}/voice-profiles/{profile_id}/deletion-requests`
- `GET /novels/{novel_id}/voice-deletion-requests/{request_id}`
- `POST .../{request_id}/confirm`
- `POST .../{request_id}/cancel`
- `POST .../{request_id}/retry`

创建请求保留持久 `Idempotency-Key`；confirm、cancel、retry 删除当前未使用的假幂等请求头，改由 request ID 和单调状态机保证重复调用安全。

所有响应包含：

- `server_now`
- `execute_after`
- `cancellable`
- `retryable`
- `terminal`
- 稳定 `failure_code`
- 服务端权威 eligibility、引用数量、资产数量和影响摘要

增加终态 `superseded`：

- 物理删除围栏前出现 Profile 版本变化、影响变化、摘要过期或 job drain 超时，事务内转为 `superseded`，释放活动请求唯一槽位。
- 页面直接重新加载最新影响并允许创建新请求，不让旧请求永久卡住。
- `VOICE_DELETE_WAITING_FOR_JOBS` 可自动重试且在围栏前可取消。
- 围栏后的临时 unlink/storage 失败按原精确计划自动或手动重试，不重新计算资产范围。
- 文件身份、scope 或资产集合异常为不可重试安全失败，保持 fail closed。

对账器采用启动扫描、状态变化事件唤醒、按最近 deadline 睡眠和最长 60 秒空闲兜底，不使用持续 5 秒轮询。每批最多处理 25 个请求；停机时停止领取新请求，已持久化的精确计划由本次或下次启动收敛。

### 4. 数据库序列

计划 36 已占用 `20260829_0033`，因此 TTS 实施必须等待该迁移进入稳定提交，然后创建：

`backend/migrations/versions/20260829_0034_narration_voice_lifecycle_and_experiments.py`

`0034` 只做：

- 扩展 Voice Version 的机器验证约束并增加 ModelRun 关联；
- 新增 Nano 实验命令表；
- 增加删除请求 `superseded` 终态和时间字段；
- 更新相关 PostgreSQL trigger、检查约束与活动唯一索引；
- 注册必要的运行时 schema sentinel。

迁移不得执行模型、网络或文件删除。真正的 VoiceGenerator 仅在 `VG-GO` 后追加 `0035`，失败时不留下预留表、死 API 或空依赖。

全局插件版本继续保持 `0.4.0`；本专项发布身份使用 Git commit、插件包 hash、bundle hash 和迁移 head，避免无关修改九个小说 Skills 的版本。

## 四、实施波次与并行施工

### 前置门禁

- 计划 36 必须先形成稳定提交，`0033` 不再处于未提交状态。
- 当前 `backend/context_v4/**`、`backend/model_execution/**`、`backend/character_workspace/**`、`backend/models.py`、`backend/generation_dependencies.py`、`backend/model_runtime.py`、`pyproject.toml` 及计划 36 文档/测试均视为其他任务所有权。
- 若仍有脏文件，TTS 在独立 `codex/tts35-*` worktree 施工；不得 stash、覆盖或混入提交。

### 波次

1. `TTS35-G0`（`GATE/SER`）：重新冻结 Git、安装包、长期 API、数据库 head、Sidecar 和 18 音色事实。
2. `TTS35-C0`（`MUTEX/SER`）：冻结 capabilities v2、三个 API 契约、状态机、错误码和 `0034`。
3. `TTS35-W1`（`PAR`）：后端删除审计、前端/播放器审计、VoiceGenerator 硬件复核并行。
4. `TTS35-W2`（`PAR-C`）：能力 provider、高级调音、删除服务、人物匹配、前端组件按冻结 DTO 并行。
5. `TTS35-MIG`（`MUTEX/SER`）：唯一 Owner 修改 ORM、`0034` 和迁移测试。
6. `TTS35-INT`（`INT/SER`）：主代理接入 API、runtime、worker、设置页、人物卡和播放器，删除旧路径。
7. `TTS35-QA`（`GATE/SER`）：隔离 PostgreSQL、真实 Nano、隔离 QwenPaw、浏览器和恢复验证。
8. `TTS35-DEPLOY`（`MUTEX/SER`）：备份、长期迁移、安装、重启及只读健康检查。
9. `TTS35-FINAL`（`INT/GATE/SER`）：分别裁决 P0/P1、CAST、ADV、DEL、CORE 和 VG。

### 子代理所有权

| 工作包 | 允许修改 | 必须运行 |
| --- | --- | --- |
| `TTS35-A1-DEL` | `docs/开发文档/证据/MOSS-TTS-Nano闭环/TTS35-DEL-AUDIT.md` | 只读检查 `voice_deletion.py`、`0032`、ORM 和测试 |
| `TTS35-A2-UI` | `docs/开发文档/证据/MOSS-TTS-Nano闭环/TTS35-UI-AUDIT.md`、`docs/开发文档/证据/MOSS-TTS-Nano闭环/TTS35-UI-AUDIT/` | 四视口截图、键盘、IME、网络与控制台检查 |
| `TTS35-A3-VG` | `docs/开发文档/证据/MOSS-TTS-Nano闭环/TTS35-VG-RECHECK.md` | 只读核实模型 revision、磁盘和硬件；禁止下载 |
| `TTS35-B1-CAP` | `backend/narration/feature_readiness.py`、`tests/narration/test_feature_readiness.py` | `.venv/bin/python -m pytest tests/narration/test_feature_readiness.py tests/narration/test_production_runtime.py` |
| `TTS35-B2-ADV` | `backend/narration/nano_experiments.py`、`tests/narration/test_nano_experiments.py` | `.venv/bin/python -m pytest tests/narration/test_nano_experiments.py tests/narration/test_voice_product.py tests/narration/test_sidecar_server.py` |
| `TTS35-B3-DEL` | `backend/narration/voice_deletion.py`、`backend/narration/voice_lifecycle.py`、`tests/narration/test_voice_deletion.py`、`tests/narration/test_voice_lifecycle.py` | `.venv/bin/python -m pytest tests/narration/test_voice_deletion.py tests/narration/test_voice_lifecycle.py tests/narration/test_media_postgres.py` |
| `TTS35-B4-CAST` | `backend/narration/character_voice_matching.py`、`backend/narration/resources/official_voice_casting_v1.json`、`scripts/tts/build_official_voice_casting_baseline.py`、`tests/narration/test_character_voice_matching.py` | `.venv/bin/python -m pytest tests/narration/test_character_voice_matching.py` |
| `TTS35-B5-FE` | `frontend/src/narration/nano-advanced-tuning.ts`、对应测试/样式，以及现有 `voice-lifecycle-state.ts`、`voice-lifecycle-panel.ts` 及其测试 | `pnpm --dir frontend test -- nano-advanced-tuning.test.ts voice-lifecycle-state.test.ts voice-lifecycle-panel.test.ts` |

共享 DTO、`backend/models.py`、迁移、`backend/app.py`、`production_runtime.py`、公共 API、`frontend/src/narration/contracts.ts`、`api.ts`、`index.ts`、`reading-page.ts`、工作台入口、长期环境和 Git 只由主代理修改。子代理不得提交、推送、操作长期数据库、下载模型或删除任何媒体。

汇合顺序固定为：审计 → 契约 → `CAP/ADV/DEL/CAST` → `0034` → runtime/API → 前端入口 → 隔离测试 → 浏览器 → 冗余清理 → 部署 → 最终裁决。

## 五、VoiceGenerator 条件分支

当前 M4／16 GiB 保持 `voice_generator=unavailable`，页面不显示一个不可执行的主按钮，只提供官方音色匹配。

只有同时满足以下条件才进入 `VG-SPIKE`：

- 至少 24 GiB 内存，建议 32 GiB；
- 至少 30 GiB 可用磁盘；
- 用户单独授权下载约 10.6 GiB 固定模型；
- 独立模型目录和进程，不与 Nano 同时常驻。

三次连续真实运行必须无 OOM、无持续 swap 抖动，并保留至少 4 GiB 系统余量。通过后才实现：

- `CharacterVoiceBrief/1 → VoiceDesignDraft → VoiceGenerator → Nano 技术验证 → generated Voice Version → CAS 自动绑定`
- 一次点击完成，不增加人工试听确认。
- 并发修改时进入“已生成、未应用”，提供一次“使用此音色”。
- 生成结果直接进入统一私人音色删除生命周期。

失败则记录 `VG-FINAL=BLOCKED_HARDWARE`，不影响 `CORE-FINAL`，也不以官方音色匹配冒充新音色生成。

## 六、测试、发布与恢复

### 自动化

```text
.venv/bin/python -m pytest
pnpm --dir frontend test
pnpm --dir frontend typecheck
pnpm --dir frontend build
.venv/bin/python scripts/package_plugin.py
.venv/bin/python -m pytest tests/test_manifest.py tests/test_skill_contract.py tests/test_qwenpaw_integration_contract.py
docker compose config --quiet
git diff --check
```

PostgreSQL 专项必须使用明确的 `TTS_TEST_DATABASE_URL`／`TTS_VOICE_DELETION_TEST_DATABASE_URL` 隔离库，覆盖：

- `0031 → 0032 → 0033 → 0034 → 0033 → 0034`
- 高级合成失败、进程崩溃、响应丢失及 CAS 漂移均不改变原绑定
- 相同参数幂等复用，不同参数/seed 不串缓存
- 删除影响变化、过期和 job drain 超时均进入 `superseded` 并释放活动槽
- 围栏前、unlink 后、finalize 前后三类崩溃恢复
- capability provider 在启动、关闭、对账器崩溃和 Sidecar 失联时统一 fail closed

### 真实验收

- 18 个官方 preset 各合成一条固定短句，验证 requested/actual 模型、revision、音频非空和直接绑定。
- 至少两个音色验证官方 fixed、高级默认和边界内自定义参数；核实 ModelRun、HMAC、Version 和 cache fingerprint。
- 一章至少三人物朗读，验证漏读、重复、跳播、进度、音量、倍速和冻结 Edition 身份。
- 浏览器覆盖 `2560×1440`、`1920×1080`、`1280×800`、`390×844`。
- 删除测试只使用隔离环境的合成私人音色和媒体，绝不操作真实用户音色。

### 部署与回退

- 长期部署前备份数据库，记录媒体清单/hash、旧包 hash、镜像 digest 和迁移 head。
- 所有写入型浏览器验收在隔离 QwenPaw/隔离数据库完成；长期环境部署后只做健康、目录、能力和原生页面只读验证。
- 已产生 `0034` 实验或删除记录后不降 schema；只关闭能力并回退兼容代码，保留数据库和媒体卷。
- 删除对账异常时停止新请求；已进入物理围栏的请求按原精确计划修复并收敛。
- 卸载 PawApp 后不得残留路由包装、Skills、工具或对 QwenPaw 原生聊天/设置的拦截。

## 七、自查结论

本计划已修复上一版的全部阻断项：

- 高级调音已冻结“先异步真实验证、成功后 CAS 绑定”的安全顺序。
- 删除漂移/过期有明确终态，不再占用活动唯一槽。
- UI、路由和健康状态统一使用同一能力 provider。
- 倒计时使用服务端时间，对账改为事件驱动和低频兜底。
- confirm/cancel/retry 不再接收未使用的假幂等键。
- TTS 迁移固定顺接计划 36 的 `0033`，不会形成 Alembic 双头。
- 长期环境不写入永久合成小说或测试媒体。
- 首版删除未经听检的调音模板，只开放真实模型参数。
- 当前 16 GiB 不再被表述为能生成全新人物音色。
- 所有子代理路径、测试、共享锁和汇合顺序均已冻结。

终审裁决：`CORE` 方案已具备可施工条件，但源码施工必须等待计划 36 的 `0033` 稳定提交；`VG` 仍受硬件和模型下载授权约束。Git 提交与推送仍需用户在施工完成后单独明确授权。
