# MOSS-TTS-Nano 施工证据索引

> **2026-08-28 最新覆盖：**作者已完成 canonical run `270ea179-e3cf-4095-a928-56b414070719` 的实际听检，样本 01、04 被明确判定为不可理解的非正常中文，最终结果为 `HUMAN_LISTENING_FAILED`，不是 pending 或 PASS。两者精确绑定为 `onnx.Zhiming` 的 5 字旁白提示语 `林晚说道：`（3760 ms）与 `沈川说道：`（22080 ms）；其余样本正常。隔离真实 Nano 矩阵已确认 fixed seed 0 的短提示语确定性退化，fixed seed 1 与 greedy 候选仍待作者听感确认。T4-K／T4-GATE／公开 capability 继续 HOLD，后续先完成短提示语修复、新 Edition 重合成和全链复验。详见 [T4-K 人工听检失败与短提示语诊断](./T4-K/人工听检失败与短提示语诊断-2026-08-28.md)。

> 2026-08-28 result/probe 2.2 补记：fresh canonical run `270ea179-e3cf-4095-a928-56b414070719` 已完成固定精确 31 点／30 分钟技术门禁。Sidecar `peak=3695819358 B`、`growth=0 B`、restart=0、health failure=0、QwenPaw slowdown=false；原始 pageout/swapout 继续作为 whole-host telemetry 且一致性 fail-closed。历史 result/probe 2.1 的 paging FAIL 不重标。当前结果为 `HUMAN_LISTENING_PENDING`，不是 T4-K/T4-GATE PASS。

状态：**2026-08-26 已获用户完整实施与多子代理滚动并行授权。T0–T3 及 T4-RC 的历史技术门禁结论保留；现行正式产品范围是个人、本地、单用户，产品音色目录仅含六个中文 `official_preset`。旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao` 已实际 `locked + accepted + bound`；baseline request／Edition 和 Manifest revision 42 均 ready。fresh canonical run `270ea179-e3cf-4095-a928-56b414070719` 已同 run 完成真实 partial-ready、pending-gap、四桌面播放器／CodeMirror 主交互、result/probe 2.2 固定精确 31 点／30 分钟技术 PASS、报告自动导入与基线恢复；当前精确停在 `HUMAN_LISTENING_PENDING`。当前 head 的真实隔离安装／强制原位重装／卸载／再安装非回归已通过且临时资源精确清理；最终听检、同 run resume/teardown 与 T4-GATE 尚未收口，所以公开产品 capability 仍为 false。云端辅助说话人识别和高级匿名人物选角继续 HOLD／待用户裁决；五项取消范围继续为 superseded／非目标／非阻断。**

门禁汇总：[T0-GATE 最终报告](./T0-GATE.md) · [T0 能力矩阵](./capability-matrix.md) · [T1-GATE 最终报告](./T1-GATE.md) · [T1-B 真实 Sidecar](./T1-B/README.md) · [T1-D schema/live](./T1-D/README.md) · [T1-G 集成恢复](./T1-G/README.md) · [T2-A 契约冻结](./T2-A/README.md) · [T2-GATE 最终报告](./T2-GATE.md) · [T3-A 脚本契约冻结](./T3-A/README.md) · [T3-GATE 最终报告](./T3-GATE.md) · [T4-DEP 正式编辑器依赖](./T4-DEP/README.md) · [T4 核心生产契约冻结](./T4-CONTRACT/README.md) · [T4-A 生产编排](./T4-A/README.md) · [T4-B Worker](./T4-B/README.md) · [T4-C 音频链](./T4-C/README.md) · [T4-D Manifest/媒体](./T4-D/README.md) · [T4-E 播放队列](./T4-E/README.md) · [T4-F 编辑器桥](./T4-F/README.md) · [T4-G 跳播与跟随](./T4-G/README.md) · [T4-H 旧稿／新稿共存](./T4-H/README.md) · [T4-I 局部重生成与历史](./T4-I/README.md) · [T4-J 自动化闭环](./T4-J/README.md) · [T4-RC 人工复核继续生产](./T4-RC/README.md) · [T4-PRESET 官方预设集成](./T4-PRESET/README.md) · [T4-K 真实章节门禁准备](./T4-K/README.md)。

2026-08-27 范围覆盖声明：下表 T0-F/T0-G 中“200% 后移为 T4 P0”是当时的历史门禁记录，现已被用户最新的 TTS UI 范围裁决取代。历史自动化或截图仍保留为证据，但 200% 等效小视口、移动和窄屏不再是 T4-K/T4-GATE 测试项或发布阻断项。

2026-08-27 官方预设覆盖声明：T0-E 历史 JSON/hash 与商业发布／再分发风险审计保留，不作静默改写。其 18 项 manifest/catalog 只是底层兼容与技术溯源全集；现行 UI 和中文专项的六项产品子集以本页最新状态与 [T4-K 准备报告](./T4-K/README.md) 为准。

## 开工基线

- 目标文档：`docs/开发文档/18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md`
- 基线提交：`9b5be4a`（`main` 与 `origin/main` 一致）
- 目标环境：Apple Silicon M4、16 GB；QwenPaw 2.1.0 PawApp
- 开工时间：2026-08-26（Asia/Shanghai）
- Git 权限：本次指令未授权提交或推送；`LOCK-GIT` 由主代理保留但不执行发布动作。
- 状态口径：工作包完成只表示候选结果和证据可供集成；历史 T5/T6 不再属于当前完成定义。只有现行 T4-GATE 与安装／升级／卸载最终非回归全部通过，才可把本次中文本地多角色朗读标为已实现。

## 开工前未提交改动隔离

开工时已有其他专项或用户改动。除本专项文档自身的既有优化，以及 `docs/开发文档/README.md` 中第 20 项 TTS 索引状态的最小同步外，下列路径中的既有/其他专项内容均为本专项只读禁区，不得暂存、覆盖、清理或纳入 TTS 交付：

- `backend/creative_api.py`
- `backend/creative_services.py`
- `backend/selection_edit_diff.py`
- `design-qa.md`
- `docs/开发文档/21-选区AI中央统一Diff审阅施工计划.md`
- `docs/开发文档/README.md`（只允许同步既有 TTS 索引项；其余用户改动只读）
- `frontend/src/selection-edit-review-surface.test.ts`
- `frontend/src/selection-edit-review-surface.ts`
- `frontend/src/styles.ts`
- `skills/prose-writing/SKILL.md`
- `skills/style-review/SKILL.md`
- `tests/test_api_model_orchestration.py`
- `tests/test_selection_edit_diff.py`
- `tests/test_skill_contract.py`
- `docs/开发文档/23-小说拆解驱动的通用与分类Skill架构计划.md`
- `docs/开发文档/证据/关系网P0优化-2026-08-25/pre-relationship-cleanup.dump`
- `docs/开发文档/证据/助手计划V2验证-2026-08-25/pre-a3a4-install.dump`
- `docs/开发文档/证据/选区AI中央统一Diff审阅-2026-08-25/UD5-CONTEXT-AUDIT/`
- `docs/开发文档/证据/选区AI中央统一Diff审阅-2026-08-25/UD5/`

施工期间还出现了其他任务新增的 `docs/开发文档/24-小说语义检索与向量模型专项施工计划.md`；它不属于开工基线，也继续按只读禁区处理。

`docs/开发文档/18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md` 在开工前已有未提交的施工依赖/CLI 修订；主代理将其作为本专项基线继续维护。

## 当前派发与资源锁

| 工作包 | 状态 | 写 Owner | 资源锁 | 说明 |
| --- | --- | --- | --- | --- |
| T0-A | 已交付；主代理最终本地复验通过 | `tts_t0a_dependency_baseline` → 主代理 → `tts_t0a_ffmpeg` | 已释放 | Python 3.11 hash install、Node 123/123、30 个已下载上游资产与 4 个固定工具产物验 hash；FFmpeg 9.0.1 LGPL 窄构建、WAV→FLAC→AAC-LC/M4A、失败不发布、master-only 恢复与 Chromium 151 完整播放均通过 |
| T0-H | 已交付；T0-GATE 按固定 hash 接纳 | `tts_t0h_contract_audit` → 主代理 | 无 | 6 项 P0 已展开为 10 项精确决策，见 `T0-H/gate-decisions.md`；只冻结 T1-A/T1-D 输入，不代表 ORM、迁移或领域服务已经实现 |
| T0-I | 已交付；主代理已复核 | `tts_t0i_fixture_tooling` → 主代理 | 无 | 26 条授权文本、27 case、29 coverage、统一结果契约已冻结；脚本已用原型 Python 3.11.16 复验；冻结产品 fixture 的 3/5/8/12 秒 profile 仍是显式占位，仓库外 isolated-test-only 技术输入另由 T0-C 管理，不得混为产品资产 |
| T0-E | 历史商业审计已交付；现行六个中文产品预设已冻结 | `tts_t0e_voice_pool` → `tts_t0e_rights` → `T4-PRESET-DOC` | 已释放 | 24 槽／48 候选和 18 项 manifest/catalog 全集都只保留历史或底层技术用途。当前产品目录仅 Junhao、Zhiming、Weiguo、Xiaoyu、Yuewen、Lingyu；商业／再分发与英语／日语质量均不进入本轮门禁 |
| T0-B | macOS 诊断 worker 与 Linux/arm64 私网 Sidecar 技术门禁均通过 | `tts_t0b_topology_spike` → `tts_t0b_harden` → 主代理 | 已释放全部 `LOCK-NANO` | managed worker 22/22；Linux Sidecar 22/22；固定 `linux/arm64` 镜像、普通/reference、取消、活动请求 SIGKILL、恢复、新 generation、容器重启通过。1804.466 秒完成 750 个请求、0 失败、单一 PID/generation、0 restart；最终清理 0 容器/进程/orphan/`.part`，QwenPaw 健康。首轮 macOS 请求 551 预读死锁失败证据保留，修复后 1800.219 秒 822 endurance 请求通过；同参数多 actual hash 证明 seed 不是内容键 |
| T0-C | 20-case 与 reference 4-case 技术矩阵通过；产品权利与人听仍关闭 | `tts_t0c_quality_spike` → `tts_t0c_persistent_quality` → `tts_t0b_harden` | 已释放 `LOCK-NANO` | 20/20 case 技术通过；22 个质量句段 + 3 个 probe 同 PID/generation，0 hash/event mismatch，median RTF 0.361503、P95 0.392402。3/5/8/12 秒仓库外 isolated-test-only 参考输入已核对顺序、字节、SHA、48 kHz 双声道 16-bit WAV 和精确时长，Linux 真容器 4/4 recheck 通过；正式权利、产品 fixture 与人工听感仍未通过，`reference_clone_visible=false` |
| T0-D | 已交付，建议 `hide` | `tts_t0d_voicegen_spike` | 已释放 | 6/6 测试；固定资产约 10.566 GiB，16 GiB 上 CPU FP32 静态权重余量不足；未下载/加载模型，VoiceGenerator 默认隐藏 |
| T0-F | 25/25 与隔离 Chromium 通过；固定宿主只读审计完成，宿主门禁 HOLD | `tts_t0f_editor_spike` → `tts_t0gate_host_topology_audit` → 主代理 | 已释放 | CodeMirror 仅 `CONDITIONAL GO` 候选且默认关闭；正式正文仍是 textarea，现有 recovery/debounce/CAS/AI apply 未完成 CodeMirror 非回归；系统 IME、固定宿主完整 bundle、200%、长章/可访问性后移为 T4 启用 P0 |
| T0-G | Manifest 2.0 wire 与真实播放调度原型通过；产品门禁仍关闭 | 主代理 + `tts_t0g_range_etag` + `tts_t0gate_host_topology_audit` → `tts_t0gate_final_redteam` | 已释放 | 唯一 snake_case wire 已冻结：`narration-manifest/2.0`、revision>=1、0-based ordinal、半开 ready range、服务端字段与客户端派生严格一致，24/24 TS 与 21/21 Range/ETag 通过。可供 T1/T4 作契约输入，但正式仓库仍无媒体 endpoint，播放器默认关闭；独立相邻句段听检、正式鉴权/流式 Range、卸载清理与 200% 后移为 T4 启用 P0 |
| T1-DEP | 已交付；T1-GATE 接受 | `tts_t0b_harden` → 主代理 → `tts_t0gate_final_redteam` | 已释放 `LOCK-DEPENDENCIES` | Linux/arm64 固定依赖、29 项资产锁、FFmpeg、私网、只读卷和无 Docker socket 边界已由生产 1.1 候选与正式 Sidecar 原位更新复核。 |
| T1-A | 已交付；主代理复验并经红队加固后接受 | `tts_t0c_persistent_quality` → 主代理 → `tts_t0gate_final_redteam` | 已释放 | Adapter、能力、健康、fingerprint、固定 scope 与 7/11/7 taxonomy 已冻结；53/53 通过，嵌套可变 parameters 与非精确 bool/enum/int P1 已闭合；产品 flags 仍全 false。 |
| T1-B | 真实通过；T1-GATE 接受 | 主代理 + 生命周期红队 | 已释放 `LOCK-MODEL-ASSETS` / `LOCK-NANO` | 协议 1.1、60 秒短租约、续租、陈旧 token fencing、卸载、取消、活动故障与新 generation 恢复真实通过；产品 false。 |
| T1-C | 已交付；T1-GATE 接受 | `tts_t0gate_final_redteam` → 主代理 | 已释放 | job/attempt/lease/fence/retry/dead-letter/manual retry 基础完成。 |
| T1-D | 已交付；T1-GATE 接受 | 唯一迁移 Owner → 主代理 | 已释放 | 0010–0015 线性链；migration `6/6`，current-head live suite 已验证；正式项目库已在 T2-GATE 安全升级到 `20260826_0015 (head)`。 |
| T1-E | 已交付；T1-GATE 接受 | 主代理汇合 | 已释放 | media/storage/Range/ETag/引用/GC 与原子发布基础完成。 |
| T1-F | 已交付；T1-GATE 接受 | `tts_t0b_harden` → 主代理 | 已释放 | request/snapshot/settings/script/Edition/render/Manifest/progress 领域基础完成。 |
| T1-G / T1-GATE | 已通过，带显式 HOLD | 主集成 Owner | 共享锁已释放 | PostgreSQL 18 真锁/恢复、PawApp 真实生命周期、隔离安装／卸载、正式 Sidecar 1.1 与精确清理通过；产品、正式插件发布和 DB role switch 仍 HOLD。 |
| T2-A | 已通过；wire invariant 保持，implementation source 于 T2-GATE re-freeze | 主代理（SER）+ 只读红队 | 共享 API/DTO 锁继续冻结 | 21 paths/29 operations、版本／DTO／错误码未漂移；`settings_api.py` 因 namespace import 和领域错误适配加固从历史 `05b1…` re-freeze 为 `5f22…`，独立审计 Python 90、前端 22 通过。 |
| T2-B / T2-C / T2-D | 局部候选已完成并汇合 | 各工作包唯一写 Owner → 主代理 | wire invariant 未变化；实现源已在 GATE 显式审计后 re-freeze | 朗读页、人物声音、音色来源和旁白合法 profile 映射已接入；来源 capability 仍 HOLD。 |
| T2-E | 候选实现已通过；`PASS_WITH_PRODUCT_HOLD` | 主代理 | 无共享锁 | Python 9、前端 6 与 typecheck 通过；24 位均为分类投影，0 production ready，无假试听/自动选角动作。 |
| T2-F / T2-G | 局部候选已完成并汇合 | 各工作包唯一写 Owner → 主代理 | wire invariant 未变化；实现源已在 GATE 显式审计后 re-freeze | 发音／缓存、隐私／状态已接线；后端授权红队问题已闭合。 |
| T2-H | 自动化与正式浏览器已完成 | 独立测试 Owner → 主代理 | `LOCK-BROWSER` 已释放 | 后端 `741 passed / 87 skipped`、前端 `448 passed`；1920×1080／2560×1440、深链接刷新、人物卡键盘页签和状态矩阵通过。 |
| T2-GATE | `PASS_WITH_EXPLICIT_T3_PLUS_HOLDS_AND_OPERATIONAL_CLEANUP` | 主代理（INT/GATE） | 共享锁已释放 | QwenPaw／PostgreSQL／Sidecar healthy；29/29 live HTTP、完整 install→uninstall→reinstall、原生宿主和数据 hash 保留通过。一个不运行的旧 `Created` installer 条目待未来获准维护窗口后精确清理。 |
| T3-A | GO；契约冻结已通过 | 主代理（SER）+ 三路只读终审 | 契约文件转只读；释放 T3-B–T3-I 文件级并行 | UTF-16 完整分区、typed relation/cloud decision authority、复核父版本分类、唯一持久 hash 和公共 parser 负测通过；54 专项、113 联合、804 全量通过。T3-GATE runtime 仍 HOLD。 |
| T3-B～T3-I | 已完成并由主代理汇合 | 各文件 Owner → 主代理 | 文件锁已释放；共享 contract invariant 保持 | 确定性切分／场景／归因／选角／表达／复核 facade 与独立 QA 均完成；高级路径按 T3-GATE 明确 HOLD。 |
| T3-GATE | `PASS_WITH_LOCAL_ONLY_SCRIPT_RUNTIME_AND_EXPLICIT_T4_PLUS_HOLDS` | 主代理（INT/GATE）+ 独立只读红队 | T3 共享锁已释放；T4-DEP/DTO/migration 锁转由主代理持有 | Python 1211、前端 499、live PostgreSQL 2、真实 HTTP、卸载重装、数据计数保留通过；P0=0、P1=0。只启用 local-only 脚本技术闭环。 |
| T4-DEP | `PASS_DEPENDENCY_ONLY_WITH_T4_F_AND_T4_GATE_HOST_HOLDS` | 主代理（SER）+ 只读依赖审计 | `LOCK-DEPENDENCIES` 已释放；T4 公共 DTO/migration 锁仍由主代理持有 | 根项目只新增 CodeMirror commands/state/view 三项固定直接依赖；11 包闭包全 MIT，typecheck/build、单 ESM、0 imports/0 dynamic imports 和 0 bundle 漂移通过。产品接线与固定宿主仍 HOLD。 |
| T4-CONTRACT | `FROZEN_FOR_T4_W4_1` | 主代理（SER）+ 三路只读审计 | 公共 DTO、0017 migration、媒体头和共享入口继续只允许主代理演进 | 发现并关闭 T3 `analyzed` 到 T4 `queued` 的状态断点；同事务 Edition deferred guard、source-job 唯一约束、生产 API、播放租约、EditorBridge 和唯一保存链已冻结。当时的 1920×1080 最低边界已被 2026-08-27 的精确四组合发布合同取代。 |
| T4-A | `IMPLEMENTED_CANDIDATE_WITH_APP_ENTRY_AND_LIVE_PG_HOLDS` | 子代理实现 → 主代理复核/串行修正 | 不接模型/FFmpeg/媒体；公共 fingerprint 由服务器权威注入 | 生产请求/Edition/cache/job 事务候选、render input v2、全缓存零任务即时 Manifest 与三路 API 已实现，25/25 专项、56/56 组合测试通过；入口和 live PG 仍 HOLD。 |
| T4-B | `IMPLEMENTED_CANDIDATE_WITH_FIXED_RUNTIME_HOLD` | 主代理（SER） | 不新增队列、数据库或容器；真实 Nano 继续持有 `LOCK-NANO` | 短事务调度、事务外重任务、心跳/取消、双 fence 发布、失败分类与进程内持续循环已实现，9/9 单测通过；固定宿主真实链仍 HOLD。 |
| T4-C | `IMPLEMENTED_CANDIDATE_WITH_REAL_LISTENING_HOLD` | 主代理（PAR-C） | 不在数据库事务内调用 FFmpeg；一般失败不得误用 WAV fallback | PCM 校验、确定性响度/接缝和固定转码适配已实现，13/13 单测通过；真实 FFmpeg 与相邻句段听检仍 HOLD。 |
| T4-D | `IMPLEMENTED_CANDIDATE_WITH_APP_ENTRY_AND_REAL_STORAGE_HOLDS` | 子代理实现 → 主代理复核 | Manifest/媒体 wire 冻结；不复用 JSON fetch、不允许 token URL | Manifest/CAS/prepare-range/播放资产可达性与 GET/HEAD/Range 已实现；后端联合 42/42、前端播放联合 23/23 通过，入口和真实卷仍 HOLD。 |
| T4-E | `IMPLEMENTED_CANDIDATE_WITH_PAGE_AND_REAL_AUDIO_HOLDS` | 子代理实现 → 主代理复核 | 完整播放租约；仅两个 audio 回退；低于 1920×1080 非目标 | Web Audio、3–5 段预取、缺口停止、暂停/恢复/倍速和晚到拒绝已实现，16/16 专项与 23/23 联合通过；页面/真音频仍 HOLD。 |
| T4-F | `IMPLEMENTED_CANDIDATE_WITH_MAIN_WIRING_AND_BROWSER_HOLDS` | 子代理实现 → 主代理复核 | 不形成第二套正文保存链；低于 1920×1080 非目标 | Bridge/CodeMirror/textarea fallback 已实现，38/38 与全局 typecheck 通过；工作台唯一保存链接线及固定宿主 IME/UI 仍 HOLD。 |
| T4-G | `IMPLEMENTED_CANDIDATE_WITH_MAIN_WIRING_AND_DESKTOP_BROWSER_HOLDS` | 子代理实现 → 主代理复核 | 普通正文单击只移动光标；精确四组合由 T4-GATE 唯一浏览器 Owner 串行 | gutter／命令／键盘跳播、句段高亮、跟随暂停／恢复与完整 fencing 已通过定向自动化；四个真实浏览器组合及真音频仍 HOLD。 |
| T4-H | `IMPLEMENTED_CANDIDATE_WITH_FIXED_HOST_BROWSER_HOLDS` | 主代理汇合 | 旧 Edition 不可变；更新朗读和 Edition 切换均须显式操作 | 旧稿／新稿分歧、旧稿字幕、复核紧凑播放器和焦点恢复已通过 32 项窄自动化；四组合真实 DOM、IME 与音频仍 HOLD。 |
| T4-I | `IMPLEMENTED_CANDIDATE_WITH_RETRY_ENDPOINT_AND_APP_INTEGRATION_HOLDS` | 子代理实现 → 主代理复核/串行缓存语义修正 | 旧 Edition 只读；不跨 Edition 猜测进度；低于 1920×1080 非目标 | 局部失效/复用、零任务收口、历史/rights、同 Edition 进度恢复及 latest-wins 跳播已实现；Python 37、前端 29 与 typecheck 通过，retry endpoint 和页面入口仍 HOLD。 |
| T4-J | `PASS_AUTOMATION_ONLY_WITH_REAL_RUNTIME_AND_BROWSER_HOLDS` | 子代理实现 → 主代理复核 | 假适配器不代替真实 Nano/媒体；低于 1920×1080 非目标 | 自动/人工继续生产、播放恢复和正文按键零 TTS 自动化已汇合；真实宿主与听感仍由 T4-K/GATE 裁决。 |
| T4-RC | `PASS_WITH_T4_K_AND_T4_GATE_PRODUCT_HOLDS` | 主代理串行 + 三路并发测试/复核 | 现有 PostgreSQL/队列/Sidecar；确定性锁序；公共 capability 仍 HOLD | Python narration 1117 passed/79 skipped、live PG 7 passed、前端 717 passed、typecheck/build/package 通过；两个并发 P1 与 EditionState 主键问题已关闭，T4-K 可进入 ready set。 |
| T4-K | `THREE_PRESETS_LOCKED_BOUND / REAL_NANO_BASELINE_READY / RESULT_PROBE_2_2_TECHNICAL_PASS / HUMAN_LISTENING_PENDING / REAL_PRODUCT_VALIDATION_HOLD` | 主代理串行 + 多子代理分离审计／自动化 + 作者／操作员本地探针 | 只复用现有 PostgreSQL／QwenPaw／Sidecar；隐藏 validation 与公开 product 互斥；exact novel/document、24 小时 expiry、三把私有锁 | 六个中文预设是唯一产品目录；正式三绑定、baseline、真实 partial-ready/pending-gap、四桌面主交互、报告导入、固定精确 31 点／30 分钟 result/probe 2.2 技术门禁与基线恢复均已完成。当前 head 真实隔离安装生命周期非回归已 PASS；最终听检与同 run resume/teardown 仍 HOLD。 |

## 汇合规则

T0、T1、T2、T3 已依次汇合并通过各自历史门禁。重复句段 render fanout、正式三绑定、真实 Nano baseline、partial-ready/pending-gap、四桌面浏览器主交互、result/probe 2.2 固定精确 31 点／30 分钟技术门禁、报告导入与基线恢复均已完成。当前 head 真实隔离安装／强制原位重装／卸载／再安装与 QwenPaw 原生功能非回归已通过；ready set 只剩：作者最终人工听检；同 run resume/teardown；最后由 T4-K-I 与 T4-GATE 裁决。云端辅助说话人识别与高级匿名人物选角不在 ready set，继续 HOLD／待裁决。

## T0-H 主代理复核结果

主代理已接纳 T0-H 的六项 P0，并在 `T0-H/gate-decisions.md` 将其展开为 10 项精确决策：固定 UUID scope 与直接列、`approved` 终态及派生 stale、持久请求/Edition 隔离、taxonomy v1、job lease fencing/attempt、追加式 Manifest/CAS/GC、独立 rights、版本化 HMAC keyring、彻底删除状态机，以及 Owner/测试映射。T0-GATE 已对 2026-08-26 原始快照的固定 SHA-256 作 `ACCEPT_UNCHANGED`；2026-08-27 的官方预设范围覆盖注释不重算或替代该历史 hash。这仍只表示施工输入冻结，ORM、迁移、fixture、领域服务和负向测试均不得表述为已实现。

## T0 最终验证摘要

- macOS managed worker：22/22；Linux Sidecar：22/22；T0-C：10/10；T0-D：6/6；T0-F：25/25；T0-G TypeScript：24/24；Range/ETag：21/21；基准 CLI help：6/6。
- Linux Sidecar 固定镜像 digest：`sha256:56bb12bdef8f0c8c174ec86aa4dfbeac1dee1dd9cb9a215ff305eca7c8307fe0`，`linux/arm64`，用户 `65532`。
- 最终复验：证据 JSON 可解析、Markdown 本地链接无缺失、证据目录无音频/模型/密钥、0 TTS 容器/进程，QwenPaw 健康，专项 diff check 通过。
- 37 个 canonical artifact 的最终 SHA-256 由 [`T0-evidence-manifest.json`](./T0-evidence-manifest.json) 统一锁定，清单自身 SHA-256 为 `5a65e4d939b2ab39e26948964f0f0ada9aaaa8e8e8b5a7934e837ff7eac254e9`；清单明确区分 T0-C 历史单例 smoke 与最终 20-case 技术矩阵，且不包含自身或引用其 hash 的根门禁文件，避免循环哈希。
