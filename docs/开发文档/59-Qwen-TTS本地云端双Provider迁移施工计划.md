# 开发计划 59：Qwen TTS 本地＋云端双 Provider 迁移施工计划

状态：**V1.8 本地链已长期部署并完成真实浏览器播放；朗读页面并发只读投影的语音权限行锁死锁已修复并复验。QwenPaw 2.1.0 PawApp、数据库 `20260909_0048`、本地 Qwen3-TTS 运行时、统一执行层、正式 worker、崩溃后媒体接管、缓存隔离和前端手动切换均已验证；MOSS/Nano/VoiceGenerator/24 槽现行运行链已移除。阿里云 Provider 已接入但尚未执行真实凭据 smoke，历史数据库表尚未物理删除。**

日期：2026-09-08（Asia/Shanghai）

## 1. 目标与完成边界

把当前 MOSS TTS 实现完整迁移为两条可手动切换、行为一致的 Qwen TTS 路径：

- 本地：Apple Silicon 上的 MLX 社区运行时，使用 Qwen3-TTS-12Hz 1.7B；
- 云端：阿里云百炼北京地域的 Qwen-Audio 3.0 TTS，默认 `qwen-audio-3.0-tts-plus`，可显式选择 `flash`；
- 业务层只认识统一 TTS Provider 契约，不认识 MLX tensor、DashScope HTTP 细节或旧模型参数；
- 保留章节分段、说话人识别、持久任务、Edition、媒体、缓存、重试、恢复和播放器；
- 删除 MOSS 运行时、Nano 高级调音、VoiceGenerator 专用链和 24 槽通用音色池；
- 官方预设与人物专属音色保留，但改为按 Provider 保存可复现的版本；
- 不修改 QwenPaw 上游，不新增第二套任务队列、数据库或前端框架。

“完整移除”指当前源码、配置、Compose、公开接口、UI、测试与现行文档不再依赖或展示 MOSS。历史迁移、历史计划和历史验收证据保留其当时事实，不重写历史。

## 2. 已冻结的产品决策

1. Provider 由用户手动选择；不做静默自动回退。失败时保留任务状态，允许原 Provider 重试或由用户显式换 Provider 重新生成。
2. 默认优先本地；云端默认 Plus，Flash 只作为显式低延迟选择。
3. 本地三个 1.7B 模型按需串行加载，不同时常驻：
   - `CustomVoice`：官方预设与主要朗读；
   - `Base`：参考音频克隆；
   - `VoiceDesign`：文字描述设计音色。
4. MLX 候选优先验证 8-bit CustomVoice/Base 与 BF16 VoiceDesign；具体仓库、revision、量化和峰值内存以 Q0 真机证据冻结，不在文档中假装已通过。
5. 先生成当前播放所需的首段，再按模型分组后台生成其余段；编辑只使受影响的音频指纹失效。
6. 同一逻辑声音可有本地、云端两个实现版本；切换 Provider 不伪装成同一底层模型。
7. 参考音频、参考转写、音色描述与作者确认是耐久资产；模型派生的 voice prompt/cache 可删除、可按实现重建。
8. 旧 TTS 数据全部为测试数据。用户已明确授权：无需备份，待新链验证后按精确表、媒体前缀和卷范围直接清理；小说正文、revision、故事账本及非 TTS 媒体绝不在清理范围。
9. 不维持双写兼容期。迁移过程允许短暂保留旧代码作回退，但正式切换一次完成，随后删除旧路径。

## 3. Provider 最小契约

冻结到业务层的输入输出只有以下概念：

- `provider_id`：`local_qwen3_tts` 或 `aliyun_qwen_audio_tts`；
- `model_id`、`model_revision`、`runtime_id`、`quantization`；
- 操作：`synthesize`、`design_voice`、`clone_voice`、`health`、`warmup`、`cancel`；
- 合成输入：文本、语言、声音版本、可选自然语言指令、seed、输出格式；
- 合成输出：音频流或完成资产、采样率、时长、实际模型身份、请求证据和稳定错误码；
- capability 明确声明预设、克隆、设计、指令控制和流式首段是否可用。

HTTP、MLX arrays、云端 voice ID 与 SDK 对象不得穿过 Provider 适配层。正文和私人参考音频只有在作品级云端 TTS 同意仍有效时才能发往云端；该同意与“说话人分析”同意分开。

## 4. 缓存与恢复

音频复用键至少包含：Provider、模型与 revision、runtime/量化、声音版本 fingerprint、参考资产 hash、规范化文本、语言、指令、seed、输出和后处理版本。不同 Provider 绝不共享音频缓存。

持久任务继续使用现有 request/job/segment/attempt 与 fence；外部调用不持有数据库长事务。取消、超时或崩溃后已 ready 的同指纹段继续复用，未完成段可恢复领取。首段就绪即可播放，不等待整章。

## 5. 数据迁移与删除边界

- 新增一个 Alembic revision，基于施工时唯一 head；不修改任何历史 revision。
- 保留通用的声音档案、声音版本、章节脚本、Edition、render、媒体和任务表；删除或收缩只服务于 Nano 实验、VoiceGenerator 命令和 24 槽通用池的表与约束。
- 迁移先使新 Provider 字段和约束可写，再由精确清理脚本删除旧 TTS 测试记录和旧媒体；脚本必须支持 dry-run、输出计数、重复执行安全，并拒绝超出白名单表/媒体根。
- 旧音频不转换、不冒充 Qwen 生成；切换后按需重新生成。
- 历史数据库表和旧 TTS 测试记录的物理清理由[计划 62](./62-Qwen-TTS失败恢复与MOSS残留清理计划.md)接管。鉴于作者已明确不回退 MOSS，且本地 Qwen 已通过真机生成与真实播放，MOSS 物理清理不再等待阿里云真实 smoke；阿里云最小章、手动切换和实际模型回执仍是“云端正式可用”的独立门禁，未通过时不恢复 MOSS，也不得宣称双 Provider 全部验收。

## 6. 施工波次与子代理并行设计

共享契约、迁移、Compose、入口接线、删除和最终集成由主代理单一所有。工作包 ID 只属于本计划。

| 波次 | 工作包 | 类型 | 目标与文件所有权 | 前置／门禁 | 验收与返回证据 |
| --- | --- | --- | --- | --- | --- |
| W0 | Q59-C0 | SER/GATE | 本计划、ADR-0010、Provider DTO 与错误码；`docs/开发文档/**`、`backend/narration/contracts.py` | 用户批准 | 文档链接、契约单测、`git diff --check` |
| W0 | Q59-Q0 | SER/MUTEX/GATE | 本机 MLX 尖峰；仅 `scripts/qwen_tts/**` 与 `audit/qwen-tts/**` | C0 | 三类模型逐个加载、首段/RTF/RSS/释放实测；不改业务库 |
| W1 | Q59-L | PAR | 本地 sidecar 与 adapter；仅新建 `tts_runtime/**`、`backend/narration/providers/local.py` 及对应测试 | C0、Q0 PASS | health、预设/克隆/设计代表样本、取消和卸载 |
| W1 | Q59-C | PAR | 阿里云 adapter；仅 `backend/narration/providers/aliyun.py` 及对应测试 | C0 | mock 契约、超时/限流/鉴权脱敏；真实 smoke 需现有凭据与同意 |
| W1 | Q59-F | PAR | 前端 Provider 设置与旧入口删除；仅 narration 前端模块，不触碰 `frontend/src/index.ts` | C0 | Vitest、typecheck；本地/云端切换无静默回退 |
| W2 | Q59-D | SER/MUTEX | 新 revision、模型约束和精确清理脚本；`backend/models.py`、`backend/migrations/**`、`scripts/**` | L/C 契约稳定 | upgrade、downgrade/前滚恢复、dry-run、幂等清理测试 |
| W2 | Q59-I | SER/MUTEX | worker、services、API、settings、Compose 和共享入口接线 | L/C/D | 后端相关测试、Compose config、分段恢复与缓存隔离 |
| W3 | Q59-R | SER | 删除 MOSS/Nano/通用池现行代码、配置、测试和现行文案；历史资料只标记被替代 | I | `rg` 白名单扫描、全量回归、无孤儿导入 |
| W4 | Q59-V | GATE/INT | 本地、云端、切换、恢复、桌面 UI 和清理验收；主代理唯一集成 | R | pytest、pnpm、真实浏览器、运行证据、回退演练 |

并行约束：L、C、F 只能在 C0 冻结后并行；不得同时修改同一文件。`backend/models.py`、迁移链、`compose.yaml`、锁文件、`frontend/src/index.ts`、正式数据库和唯一模型运行时均为 MUTEX。子代理不得提交、推送、清数据或操作长期环境。汇合顺序为 L/C/F → D → I → R → V，主代理是唯一集成责任人。

计划 58 当前工作区文件是只读保护区；若最终入口接线不可避免与其相交，先复核现有 diff，只做最小合并并单独跑计划 58 相关回归。

## 7. 轻量门禁

只保留五个必须通过的门，不建设新平台：

1. **Q0 本机门**：M4 16 GiB 上代表中文段可生成，三个模型逐个加载/释放，不发生重模型并驻；记录实际而非承诺的首段、RTF 和峰值内存。
2. **契约门**：本地和云端对同一 Provider 测试套件返回一致状态与稳定错误码。
3. **恢复门**：修改一个句段只重生受影响指纹；中断后不重复已 ready 媒体。
4. **隐私门**：未同意不出机；日志、错误和证据不含正文、参考音频或密钥。
5. **发布门**：新链两端 smoke、手动切换、无静默回退、旧数据精确清理、MOSS 现行引用扫描、插件安装/卸载和原生功能非回归全部通过。

目标性能是热路径首个可播放段约 10 秒、稳定 RTF ≤ 1；它是优化目标，不是以牺牲恢复性、内存安全或正确性为代价的硬发布断言。若本机实测达不到，先保证编辑不阻塞和后台可恢复，再决定量化或分段参数。

## 8. 官方实现替换边界

未来从 MLX 换到 Qwen 官方 PyTorch 实现，只允许替换本地 Provider 进程内的模型加载、输入转换与推理代码；API、业务任务、声音版本、缓存身份和 UI 不改。因为权重格式、设备要求、voice prompt 序列化和性能特征不同，模型需重新下载并重建派生缓存，Q0/Q59-V 必须重跑；不会承诺“只改一个包名即可”。

## 9. 非目标

- 自动云端回退、动态价格路由和多 Provider 调度器；
- 同时常驻三个本地模型；
- 实时多人合声、情绪时间线编辑器或新的通用声音市场；
- 自建鉴权中心、对象存储、消息队列、第二套数据库；
- 修改 QwenPaw 核心、复制其私有模块或覆盖原生路由。

## 10. 官方基线

- Qwen3-TTS 官方仓库及模型矩阵：<https://github.com/QwenLM/Qwen3-TTS>
- MLX-Audio Qwen3-TTS 文档：<https://github.com/Blaizzy/mlx-audio/blob/main/docs/models/tts/qwen3-tts.md>
- 阿里云 Qwen-Audio 3.0 TTS Plus：<https://help.aliyun.com/zh/model-studio/qwen-audio-3-0-tts-plus>
- 阿里云语音合成：<https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide>
- 阿里云声音复刻与设计 API：<https://help.aliyun.com/zh/model-studio/voice-clone-design-http-api>

## 11. 施工进度（2026-09-08）

- 已完成：统一 Provider DTO/错误码、`local_qwen3_tts` HTTP 适配器、Mac 原生 MLX 运行时、阿里云 Plus/Flash HTTP 适配器、严格手动 Provider 注册表、设置持久化与前端选择、独立云端 TTS 授权 API。不会因为存在配置或密钥而自动切换 Provider。
- 本地运行时已按 `mlx-audio==0.5.2` 的真实调用形态适配生成器返回值、内存参考音频和语言映射；三个模型均冻结精确 revision 与期望制品树指纹。
- 已通过本轮全量回归：后端全量 pytest 通过；前端 148 个测试文件、1261 项测试全部通过；生产构建、插件打包和 `docker compose config` 通过。授权表允许“说话人分析”与“云端 TTS”分类共存，查询会显式拒绝用途或数据范围漂移。
- 全局 `pnpm typecheck` 仍被计划 58 保护区内 6 个施工中类型错误阻塞；本计划未修改这些文件，Qwen TTS 定向 Vitest 与全量构建已单独通过。
- Q0 已通过：三个冻结模型的关键权重哈希一致，并在 M4 16 GiB 宿主逐个完成 CustomVoice 预设、Base 参考克隆和 VoiceDesign 描述设计；全程 0 swap。CustomVoice 连续热路径 RTF 为 0.65–0.71，Base/VoiceDesign 作为低频音色准备分别为 1.84/1.25。运行时在模型切换和进程退出时均显式卸载。详见 [Q0 本机记录](../../audit/qwen-tts/Q0-本机MLX可行性记录-20260908.md)。
- 作者完成三类 Qwen 样音听检后，明确授权提前释放本机 MOSS 模型空间；已删除 MOSS 容器、模型卷、镜像和原型可重建依赖，但未删除旧 TTS 数据、QwenPaw/数据库卷。随后在作者明确不再回退 MOSS 后继续删除 Compose 拓扑和 sidecar 镜像源码。详见 [MOSS 模型制品清理记录](../../audit/qwen-tts/MOSS-模型制品清理-20260908.md)。
- 作者随后明确不再回退 MOSS。Compose 已移除 MOSS 服务、卷、网络和旧环境变量，`docker/tts-sidecar/**` 已删除；Qwen 本地 Provider 在 Q0 与人工听检后标记为 production-ready。Mac 与 QwenPaw 改为共享一个仓库外 `0600` 令牌文件，令牌值不进入 `.env`、Git 或 `docker inspect`。
- 统一 `TTSExecutionService` 已通过真实本地调用：从业务 Provider 层生成 24 kHz WAV，返回精确 `local_qwen3_tts`/CustomVoice 身份，完整身份复核通过，无回退。取消也按显式 selection 路由。
- Qwen Provider 的 24 kHz 单声道 PCM 已有独立标准化入口：先核对 Provider 声明与 WAV 元数据，再确定性转换为既有 48 kHz 双声道媒体契约；下游转码、媒体和播放器无需为 Provider 分叉。
- 新建 Edition 已从作品设置快照冻结实际 Provider 选择指纹，不再使用运行进程里的全局 MOSS 模型身份。本地与云端缓存隔离，云端 Plus/Flash 也隔离；本地模式下未启用的云端型号变化不会造成无效重生成。
- 正式 segment worker 已改接统一执行层；新生成固定使用 Qwen Provider 契约和 v3 渲染指纹，Nano decode、短句采样特例、通用音色试听授权以及旧 voice-preparation 前置工作流均已移除。章节工作流简化为保存、创建生成任务、轮询进度。
- capability 契约升级为 `narration-capabilities/5`，只保留现行 Qwen 产品能力；本地运行状态从旧 sidecar 语义改为 Provider 可达性。官方音色目录固定为当前两个 Qwen 跨 Provider 映射。
- 长期环境已完成两次短维护安装：数据库从 `20260903_0040` 经计划 58 的 `0041/0042` 升至 `20260908_0043`，QwenPaw 与 PostgreSQL 均恢复 `healthy`，PawApp `0.4.0` 公共健康为 `ready`。发布前快照位于 `/app/working.backups/plan59-qwen-cutover-20260908-173327-before`，包含旧安装树、候选树和可由 `pg_restore` 读取的数据库 dump；详见 [长期发布记录](../../audit/qwen-tts/长期部署与浏览器复核-20260908.md)。
- 真实浏览器桌面复核通过：本地 Qwen3-TTS 与阿里云 Qwen-Audio 3.0 均作为显式单选项显示，本地默认选中并显示“本地 TTS 技术就绪”；旧 MOSS 声音档案已从现行 Qwen 选择器过滤，不再导致 `INVALID_STATE`，浏览器控制台无 error/warn。历史行仍保留为数据库审计事实，没有冒充 Qwen 声音。
- 2026-09-09 真实章节恢复与浏览器播放通过：迁移 `0045`—`0047` 将官方 Qwen 音色约束、provenance 字段和渲染/重试资源类闭包前滚到 Qwen；`0048` 只把首次冻结账本校验限定在 `analyzed/review_required → queued`，不再错误拦截已有严格授权的 `failed → queued` 句段重试。worker 使用现有 `verify_existing_media()` 验明并接管“文件已耐久发布但数据库事务回滚”的同哈希音频，不放宽普通媒体碰撞规则。
- 同章前三段已从历史失败中受控恢复：Manifest `ready_prefix_count=3`、总时长 13.8 秒，章节指针已建立。真实浏览器点击播放后从第 1 句推进至第 2 句，时间从 `0:00` 走到 `0:04 / 0:13`；未调用云端。该历史测试 Edition 仍有 107 个旧失败句段，未把局部恢复冒充整章完成。
- 后续真实浏览器复测发现：章节上下文和失败句段两个只读投影会并发以不同顺序对同一批 `voice_profile_versions` 执行 `FOR UPDATE`，触发 PostgreSQL 死锁，API 将其封装为误导性的“朗读生产数据库当前不可用”。现已仅对这两个只读投影使用无锁权限快照读取，重试、生成和发布等写操作仍保留原行锁。定向回归通过；长期环境重启后，第一章播放器可加载并从第 1 段进入“正在播放”，页面中的数据库不可用与加载失败提示均消失，测试期间数据库日志无新 deadlock。正文和既有朗读版本均未修改。
- 当前剩余门禁分为两组：阿里云真实凭据＋作品级授权 smoke 仍决定云端能否正式发布；受影响窄屏路径、当前章节 107 个历史／质量失败的恢复和 MOSS 残留清理由已复查优化但尚未开工的[计划 62](./62-Qwen-TTS失败恢复与MOSS残留清理计划.md)承接。本地运行时当前由 macOS `screen` 会话托管，退出登录或重启后需要手工重启；LaunchAgent 方案因启动上下文不稳定已撤回，不为本次切换引入新的守护平台。这些限制不会阻塞当前登录会话内的本地 Qwen 使用，但完成前不宣称云端正式发布、开机自启或数据库历史结构已清空。
- 云端域名、会员渠道、模型映射与密钥将由 [计划 61](./61-语音模型接入入口与多渠道配置页面计划.md) 建设创作中心配置页；在该页完成并由作者再次授权前，本计划不执行真实云端调用。
