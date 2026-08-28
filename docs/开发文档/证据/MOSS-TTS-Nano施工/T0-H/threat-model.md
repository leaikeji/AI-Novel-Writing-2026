# T0-H 威胁模型：MOSS-TTS-Nano 多角色智能朗读

> **官方预设范围更正（2026-08-27）：** 下文 PM-01 针对用户上传、文字描述生成、外部素材和主动仿声，不得用于过滤固定 ONNX manifest 的个人本地 `official_preset`。18 项官方预设全部可本地使用，包括 `Trump`、`Xiaoyu`；商业发布／再分发风险仍单独审计。

状态：**施工前威胁模型；仅描述风险、控制和待验证证据，不代表任何控制已经实现。**

版本：`tts-threat-model/1-draft`

日期：2026-08-26（Asia/Shanghai）

配套契约审查：[contract-review.md](./contract-review.md)

## 1. 资产、主体与信任边界

### 1.1 受保护资产

- 私人小说 working copy、不可变 revision、朗读脚本和人工修正；
- 人物、别名、匿名身份、选角规则、发音表和 settings snapshot；
- 上传源录音、标准化参考音频、试听、锁定音色、句段 master/playback 和导出；
- voice rights、cloud consent、审批、删除、model run 和 job 审计；
- 模型权重、revision/hash、loopback token、staging 文件和媒体路径；
- QwenPaw 原生聊天、Agent、Provider、Skills、MCP、工具、workspace 和持久卷。

### 1.2 主体

- 本地作者；
- PawApp 浏览器前端；
- PawApp API/领域服务；
- background job runner；
- Nano/VoiceGenerator 本机执行后端；
- 可选受控云端聊天模型；
- ffmpeg/解码器/文件系统；
- QwenPaw 宿主与插件安装器。

### 1.3 边界图

```text
作者/浏览器（不可信 ID、文件名、正文变化）
        |
        v  同源 PawApp API；scope/CAS/intent
PawApp 领域服务 + PostgreSQL（业务权威）
        |                 |
        | job + fencing   +--> novel-media（受控 root、内容寻址）
        v
后台执行器（非权威、可崩溃/重试）
   |              |
   | loopback/IPC | 最小授权 payload
   v              v
Nano/VoiceGen   云端聊天模型（可选、外部信任域）

QwenPaw 上游核心是宿主信任域；插件只能经公开扩展点进入，不能修改核心。
```

### 1.4 假设与非保证

- 目标是个人本机使用；当前没有可信 QwenPaw 人类身份，固定 owner/workspace 只提供结构隔离，不构成多用户认证。
- 宿主和 Mac 本机管理员可访问本地文件/数据库，不在首版防御范围内；最小权限、回环绑定和日志脱敏仍需执行。
- 云端供应商收到的已授权 payload 无法由本项目保证物理删除；撤权只保证未来不再调用并丢弃未提交结果。
- 模型许可证不等于参考声音、人格权或商业使用授权。

## 2. STRIDE 风险登记

| ID | 类别 | 攻击面/场景 | 影响 | 等级 | 缓解契约 | 必须验证的证据 | 剩余风险/裁决 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TM-S-01 | Spoofing | 请求体/header/模型伪造 owner、workspace、novel 或 Agent | 跨作品/未来跨 owner 访问 | P0 | 服务端固定 `NarrationRequestScope`；ID 只作定位；统一 404 | 每个 API 的越权 UUID/父子错配/任意 header 测试 | 当前仍非真实多用户认证，UI 必须说明本地个人边界 |
| TM-S-02 | Spoofing | 模型返回 allowlist 外 character/segment/profile ID | 错绑人物、泄露实体存在 | P0 | 只接受本次 server allowlist；非法 ID 转安全 blocker/failure，不回显对象 | 非允许 ID 数量 0；错误响应不含目标详情 | taxonomy 需决定非法候选是 blocker 还是 workflow failure |
| TM-S-03 | Spoofing | 假冒/旧 Nano Sidecar，或 loopback 端口被其他进程占用 | 错模型、恶意音频、路径读取 | P0 | 随机启动 token、协议/模型 hash 握手、只回环/私网、请求限额 | 错 token、旧协议、错误权重、端口抢占均拒绝 | 物理拓扑待 T0-B 冻结 |
| TM-S-04 | Spoofing | requested 模型与实际 provider/model/revision/tokenizer 不一致 | 错误分析/不可复现音频被批准 | P0 | actual 只能由可信 adapter/usage 产生；不匹配即作废且不发布 | chat/Nano/VoiceGen 三类 mismatch 测试；model_run 记录 | 各 adapter 可提供的实际身份字段待阶段 0 实测 |
| TM-T-01 | Tampering | PATCH 已 approved script 或把旧版状态改为 stale | 审批证据/Edition 基线被改写 | P0 | approved 终态；stale 派生；新修正建新版本；immutable hash | SQL/服务层更新拒绝；旧 hash/Edition 不变 | 数据库 trigger 或服务约束由 T1-D 裁决 |
| TM-T-02 | Tampering | 同 Idempotency-Key 换 payload，或重放 create 为 analyze-only | 重复 Edition、越过显式意图 | P0 | key + canonical request hash；intent 不可改；冲突 409 | 同 key 同/异 payload、并发重放测试 | key 保留期应覆盖历史恢复期限 |
| TM-T-03 | Tampering | 过期 worker、重复 attempt 或取消后 worker 发布 render/Manifest | 重复/错误音频进入 Edition | P0 | lease generation/token fencing；发布前重校验 cancel/scope/fingerprint | kill/续租/租约过期/双 worker/取消竞态测试 | 底层模型不支持强取消时仍会浪费算力 |
| TM-T-04 | Tampering | 修改 staging/媒体文件、伪造 MIME/hash 或符号链接逃逸 | 播放恶意文件、任意文件读取 | P0 | allowlist root、O_NOFOLLOW/等价校验、解码探测、内容 hash、原子改名 | `..`、symlink、NUL、错 MIME、半文件、hash 变更测试 | macOS/Linux 文件语义需分别验证 |
| TM-T-05 | Tampering | 覆盖 Manifest JSON 或非 CAS 更新 current revision | 播放跳段、跨 Edition 热切换 | P0 | Manifest revision 追加式不可变；Edition pointer CAS；segment 属于 Edition | 并发发布、旧 revision GET、pending gap、不跨 Edition 测试 | 旧 revision 保留期待 T0-GATE 冻结 |
| TM-T-06 | Tampering | 普通清缓存误删参考录音、locked voice 或历史 render | 私人源资产/历史可回放性损坏 | P0 | 显式 FK 可达图、类别 allowlist、mark/grace/recheck、tombstone | GC dry-run、引用变化竞态、源资产计数 0 删除 | 彻底删除是独立高风险命令 |
| TM-R-01 | Repudiation | 自动/人工审批无 actor、策略、taxonomy 或输入证据 | 无法解释为何生成/谁批准 | P0 | immutable approval audit；auto 绑定显式 intent；manual 绑定 owner actor/time | 两种策略全字段断言；模型不能写 approval | 固定本地 actor 只能证明本机动作，不能证明现实人物身份 |
| TM-R-02 | Repudiation | voice 上传/生成/锁定/撤权/删除缺少权利链 | 无法证明声音使用授权 | P1 | 不可变 rights record、告知文本版本、来源、许可范围、撤权和 tombstone | 每个 voice slot/source 的授权清单；缺失时锁定失败 | 法律充分性仍需用户/发布场景自行判断 |
| TM-R-03 | Repudiation | job retry/failure 被覆盖，供应商 request ID 丢失 | 崩溃后无法复核重复调用 | P1 | model_run 每 attempt 追加；manual retry actor/reason；失败历史不覆盖 | retry/dead-letter/requeue 全链审计 | 供应商 request ID 的真实性取决于 adapter |
| TM-I-01 | Information disclosure | 日志、trace、异常、SSE 记录完整正文/提示/人物资料 | 私人小说泄露 | P0 | 字段级日志 allowlist；hash/长度代替内容；错误清洗；捕获测试 | caplog/日志扫描正文 canary 为 0 | 第三方库日志需单独压测 |
| TM-I-02 | Information disclosure | 参考音频、base64、server path 或供应商 URL 出现在 API | 私人声音/目录结构泄露 | P0 | asset ID + 受控 content API；不回显 path；无 provider redirect | API snapshot、错误态和浏览器网络检查 | 本机管理员仍可访问文件系统 |
| TM-I-03 | Information disclosure | 同 fingerprint 跨 owner/workspace cache 命中或 timing oracle | 私人文本/音色存在性泄露 | P0 | unique key 含 owner/workspace；非枚举 404；首版禁止跨 scope 复用 | 两 scope 同文本/同音色不共享 render/media；时间/状态不暴露 foreign hit | 当前只有固定 owner，但结构约束仍需先建 |
| TM-I-04 | Information disclosure | 私人短句的裸 SHA-256 可被字典猜测 | 通过数据库/日志 hash 推断常见台词 | P1 | server HMAC/pepper 或不可逆 keyed digest；hash 不回传客户端 | 常见短句 hash 不等于公开 SHA-256；密钥轮换测试 | 备份恢复必须保留或版本化 key |
| TM-I-05 | Information disclosure | cloud_assisted 发送整章/全角色/参考音频，或撤权后仍外发 | 私人正文与声音外泄 | P0 | purpose consent、字段 allowlist、最小窗口、调用前复核、网络捕获 | 未授权/撤权请求 0；授权 payload 精确字段/长度 | 供应商已处理数据不能由本项目远程抹除 |
| TM-I-06 | Information disclosure | Range/HEAD/304/SSE 分支漏做 scope 校验 | 绕过普通 GET 权限 | P0 | 所有分支复用同一 resolver；统一 404 | GET/HEAD/valid+invalid Range/If-None-Match/SSE 越权矩阵 | CDN 不在首版本地拓扑内 |
| TM-D-01 | Denial of service | 超大/畸形音频、压缩炸弹、ffmpeg hang | CPU/内存/磁盘耗尽 | P0 | 上传限额、流式落盘、解码时长/尺寸限额、超时、隔离 staging | 超限、损坏、长时长、并发上传测试；无半成品 ready | 解码器自身漏洞依赖固定版本与升级流程 |
| TM-D-02 | Denial of service | 连点试听/prepare-range 创建任务风暴并饿死批量任务 | QwenPaw/M4 无响应 | P1 | 幂等 render/job、最后意图提升、公平老化、资源类别配额、重模型单并发 | 100 次重复请求仅一份 job/render；批量最终获调度 | 精确配额待真实 M4 基准 |
| TM-D-03 | Denial of service | 模型权重、staging、音频和导出填满磁盘 | 正文保存/宿主异常 | P0 | 预留空间、quota、写前检查、staging TTL、可达 GC；绝不自动删源资产 | 磁盘不足注入；正文 hash 不变；恢复后重试 | 用户若拒绝清理/扩容，生成只能暂停 |
| TM-D-04 | Denial of service | Sidecar/worker 崩溃或 Nano 卡死持有租约 | 队列停滞 | P1 | 超时、健康检查、租约续期/过期、进程重启、dead-letter | kill -9/重启/30 分钟稳定性；不重复 ready render | 物理拓扑待 T0-B |
| TM-E-01 | Elevation of privilege | 直接调用 Edition 创建或伪造 `auto_no_blockers` | 绕过复核和显式生成 | P0 | 不暴露 direct Edition HTTP；Edition/render/render-job 使用 request generation guard 复合 FK；service 重算 policy/issues；approval kind 不在客户端 DTO | direct recovery/analyze-only/blocker 未清零均创建 0 Edition/render/生成媒体 | Edition 创建已冻结为 request 领域服务内部步骤；恢复命令也走同一 guard |
| TM-E-02 | Elevation of privilege | Sidecar 获数据库/novel-media 全目录权限 | 模型进程成为第二业务服务 | P0 | 窄 adapter、job 私有临时输入、无 DB 凭证、root allowlist、私网 | 容器/进程 env/mount/端口检查；浏览器不可达 | 进程内 ONNX 的故障隔离较弱，待基准裁决 |
| TM-E-03 | Elevation of privilege | 为实现 TTS 修改 QwenPaw 核心/私有 store/路由 | 升级破坏、插件卸载残留 | P0 | 仅 PawApp/public extension；thin Docker；契约测试和完整卸载 | package diff、安装/升级/卸载、原生页面非回归 | 未来上游契约变化可能需要插件适配 |
| TM-E-04 | Elevation of privilege | 插件卸载后 worker/loopback token/路由仍活跃 | 无 UI 的后台处理继续读取私人数据 | P0 | uninstall epoch、停止接单、worker fencing、token 撤销、进程/路由为 0 | 卸载时运行 job 场景；原生 QwenPaw 恢复；数据卷保留 | 不可中断模型调用可能短暂继续算，但不得发布 |

## 3. 隐私与滥用风险（STRIDE 之外）

| ID | 风险 | 等级 | 控制 | 剩余裁决 |
| --- | --- | --- | --- | --- |
| PM-01 | 用户上传、外部素材或主动生成的未经授权真人／名人声音克隆，或以文字描述规避 | P0 | 上传／生成／锁定均需 rights record；主动名人仿声默认禁止；风险词只作告警，最终由产品政策与人工确认控制；不用于过滤 fixed manifest 的个人本地官方预设 | 发布到公共／商业场景时需另做政策／法律审查 |
| PM-02 | 说话人归因错误造成诽谤或人物关系误导 | P1 | evidence/confidence、blocker taxonomy、人工覆盖、新版本不改正文 | 中置信度 warning 仍可能产生主观错误，作者需试听 |
| PM-03 | 云端最小上下文仍可包含敏感片段 | P1 | 作品级 purpose consent、逐字段最小化、网络捕获和撤权 | 获授权并不等于内容无敏感性 |
| PM-04 | 彻底删除 voice 后备份中仍留副本 | P1 | UI 明示在线数据与备份策略；删除审计列出备份保留/到期 | 安全擦除受文件系统和备份实现限制 |
| PM-05 | T0 测试证据误提交私人小说/音频/权重 | P0 | fixture 只用授权短文本；证据目录只放 hash/摘要/截图；git diff secret/media 扫描 | 人工听检音频留在外部受控目录，不进 Git |

## 4. 安全验证矩阵

以下均为未来阶段必须产生的证据；本次 T0-H 未运行这些尚不存在的测试。

| 阶段 | 测试组 | 必须断言 |
| --- | --- | --- |
| T1-A/D | scope/schema | owner/workspace/novel/document/character/segment/edition/job/media 父子错配全部拒绝；越权响应不可枚举 |
| T1-C | jobs | SKIP LOCKED 唯一领取、续租、过期领取、stale worker fencing、attempt 记录、dead-letter、manual retry、cancel |
| T1-D/F | immutability | tts_snapshot 不移动 working copy；approved script/locked voice/Manifest revision 不可改；current pointer CAS |
| T1-E | media | path traversal、symlink、MIME、大小、解码、Range/HEAD/ETag、staging crash、引用变化 GC、源资产保护 |
| T2-D/G | rights/privacy | 无权利声明不能锁定；consent 创建/撤权/用途；日志 canary 0；本地模式外发 0 |
| T3-I | analysis/review | 非法 model ID、schema invalid、requested/actual mismatch、taxonomy 全代码、两审批路径、analyze-only 0 Edition |
| T4-J/K | production | render scope、取消竞态、Manifest CAS、pending gap、旧 revision、播放器正文 hash、缓存隔离、磁盘不足 |
| 各 GATE | QwenPaw | 打包、幂等安装、原位升级、完整卸载、原生聊天/设置/Agent/Skills/MCP/工具、数据卷、worker/进程为 0 |

建议安全负向 fixture 使用随机 UUID、两个逻辑 scope、两个 novel、相同短文本和相同 voice fingerprint，明确证明“相同内容”不会越过 scope 复用。

## 5. 安全日志最小事件

只记录结构化元数据，不记录私人内容：

```text
narration.scope_denied
narration.idempotency_conflict
narration.model_identity_mismatch
narration.consent_revoked_before_call
narration.consent_revoked_during_run
narration.job_lease_fenced
narration.media_validation_failed
narration.media_range_rejected
narration.gc_candidate_cancelled_due_to_new_reference
narration.voice_rights_missing_or_revoked
narration.plugin_epoch_rejected_publish
```

字段 allowlist：event、timestamp、内部 request/job/attempt ID、不可逆 scope tag、error code、model fingerprint、字节/时长/耗时和结果。禁止正文、spoken text、人物描述、voice description、路径、URL token、音频和密钥。

## 6. 发布前剩余风险裁决

T0-GATE：

1. 冻结 owner/workspace 的固定主体来源及“不提供多用户认证”的准确表述；
2. 冻结模型进程物理拓扑、loopback/IPC 认证和资源限制；
3. 冻结 taxonomy v1、approved 终态、request intent 与 Edition FK；
4. 冻结 job fencing、媒体 staging/publish、Manifest 追加和 GC 宽限协议；
5. 冻结 VoiceGenerator/基础音色包的权利证据标准。

T1-GATE 前：

1. 所有 H-P0 必须有自动化负向测试；
2. migration upgrade/downgrade 和固定 owner 回填必须在隔离库验证；
3. 不存在任何可从 path/job/media UUID 直接越权读取的 API；
4. fake adapter 的取消、错模型、崩溃和重复发布全部有可复核证据。

发布前：

1. 真实浏览器网络捕获证明 local 模式正文外发 0；
2. 真实安装/升级/卸载证明 worker/Sidecar/token/路由无残留且原生 QwenPaw 非回归；
3. 普通清缓存删除源/参考/locked voice 数量为 0；
4. 真实多角色样章只使用用户自有/授权文本与声音；
5. 所有 P0/P1 数据安全、声音权利和版本一致性问题清零，否则功能不得默认可见。
