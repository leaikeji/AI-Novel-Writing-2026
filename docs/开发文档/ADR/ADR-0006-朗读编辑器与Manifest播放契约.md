# ADR-0006：朗读编辑器与 Manifest 播放契约

状态：**🟢 已由 T0-GATE 条件接纳为后续实现输入。CodeMirror/Manifest/Range/浏览器播放隔离原型已通过；唯一公共 wire contract、ready-window 和安全降级已冻结。固定 QwenPaw 产品接线、系统中文 IME、独立相邻句段听检、1920×1080／2560×1440 桌面布局和正式媒体鉴权仍是 T4 启用门禁；低于 1920×1080 的视口不再属于本专项目标。本文不得被表述为产品 UI 已经实施。**

决策日期：2026-08-26（Asia/Shanghai）。

关联资料：

- [MOSS-TTS-Nano 多角色智能朗读产品与技术设计](../18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md)
- [T0-F 编辑器证据](../证据/MOSS-TTS-Nano施工/T0-F/README.md)
- [T0-F/T0-G 固定宿主接线只读审计](../证据/MOSS-TTS-Nano施工/T0-F/fixed-host-wiring-audit.md)
- [T0-G Manifest/播放器证据](../证据/MOSS-TTS-Nano施工/T0-G/README.md)
- [T0-H 契约审查](../证据/MOSS-TTS-Nano施工/T0-H/contract-review.md)
- [T0-H 数据/API/安全冻结候选](../证据/MOSS-TTS-Nano施工/T0-H/gate-decisions.md)

## 1. 决策范围

本 ADR 冻结正式编辑器候选、安全降级、`NarrationEditorBridge`、句段跳播、Manifest revision、ready-window、Range/ETag 和播放器调度契约，同时接纳脚本复核与请求隔离的 P0 安全条件。它不批准产品前端或后端施工；T0-GATE 当前只形成 `T1-DEP` ready set，正式目录、迁移和产品接线仍由后续工作包与阶段门禁放行。

## 2. 已接受决策 1：CodeMirror 6 与 textarea 降级

- CodeMirror 6 是唯一正式编辑器候选；只使用公开 `EditorState`、transaction、decoration、line-number gutter、history、keymap 和 update listener API。
- Monaco 仅保留风险对照，不进入正式依赖；其 worker/CSP/体积没有通过，不允许 T4-DEP 同时接入两个编辑器。
- 现有 textarea 是安全降级：保留正文编辑、selection、自动保存与 CAS，但不伪造可编辑正文内 decoration/gutter，不使用透明叠层。
- textarea 降级时，跳播入口只来自明确段落列表、不可变 Edition 旧稿或显式命令；播放器字幕/旧稿抽屉显示当前句段，正文修改后提示“更新朗读”。

阶段 0 已验证 CodeMirror 的 UTF-16、高亮、undo/redo、隔离自动保存回调、可点击行号 gutter、Blob module 和当时约定的四种视口；只读宿主审计确认正式正文仍是 controlled textarea，现有 IndexedDB recovery、600 ms debounce、保存中 100 ms 追保存、CAS 409 与 AI apply 保存链尚未由 CodeMirror 驱动。系统中文候选窗、固定宿主产品接线、长章以及 1920×1080／2560×1440 桌面布局仍是启用门禁。历史小视口证据继续保留，但根据用户 2026-08-27 的最新范围裁决，低于 1920×1080、移动窄屏和 200% 等效小视口均不再阻断 T4。

T0-GATE 已冻结 `editor_candidate=codemirror6` 的条件性候选和 `production_enabled=false`；textarea 继续作为可编辑/可保存的安全降级。Monaco 为 `NO-GO/HIDDEN`，T4-DEP 不得同时接入两套编辑器。

## 3. 已接受决策 2：`NarrationEditorBridge`

正式 Bridge 至少提供：

- 读取正文、UTF-16 selection、composition、手动滚动/自动跟随和当前 segment；
- 按 `segment_id` 或 `source_block_key + UTF-16 range` 安装/移除当前句段 decoration；
- 从明确 gutter/命令/只读句段解析跳播意图；普通正文点击始终只移动光标，不自动开始朗读；
- composition 期间禁止播放器 decoration、滚动和焦点抢占；结束后再应用最新 segment；
- 手动滚动后暂停自动跟随，作者显式恢复或重新播放后继续；
- transaction 只映射未相交且锚点仍一致的旧 segment；相交、边界相邻、段落拆并、引号/标点附近变化保守失效；
- working copy 与 Edition source hash 不一致时不猜测相似文本，不把旧时间轴贴到新正文。

前后端位置统一使用 UTF-16 offset，并覆盖 emoji、代理对、组合字符和特殊标点。播放器同步权威是 `segment_id`，不是 DOM 位置或定时器猜测。

## 4. 已接受决策 3：不可变脚本与显式请求

- `NarrationScriptVersion.approved` 是不可变合成输入终态；`stale`/`working_copy_diverged` 由新正文和当前指针派生，不回写或改坏旧 approved 版本。
- `analyzed`、聊天建议或模型输出不能创建正式 Edition；只允许 `approved + 可解析音色 + blocker=0 + 用户显式生成意图` 进入合成。
- 分析和合成命令必须先创建持久 `narration_requests`，保存 request kind、source revision/hash、设置 fingerprint、同意记录、幂等键、状态和结果引用。
- `analyze_only` 在 API、领域服务、job 创建和数据库约束四层禁止创建 Edition/render/media；不能只靠前端隐藏按钮。

## 5. 已接受决策 4：复核分类权威

- 服务端使用版本化 `narration-review-taxonomy/1`，由确定性规则计算 blocker/warning/info；模型只能提供候选、证据和置信度，不能自报“无阻断”。
- blocker 至少覆盖：说话人冲突、角色/匿名音色未解析、引用来源不存在、别名歧义、范围越界、source/hash 漂移、音色版本不可用和权利阻断。
- `blockers_only` 自动冻结只在 taxonomy 计算 blocker=0 且有用户显式生成请求时成立；其他策略需要 owner 人工复核证据。
- taxonomy 版本、策略版本和统计写入脚本版本、设置快照与 Edition，后续规则变化不能改写历史。

## 6. 已接受决策 5：Manifest v2 与追加 revision

- Manifest 绑定不可变 Edition/source revision/content hash、`initial_buffer_policy_version` 和有序 segment 状态；不存在隐式切换 Edition。
- 唯一公共 wire schema 为 `schema_version="narration-manifest/2.0"` 的 snake_case JSON；`manifest_revision>=1`，segment `ordinal` 从 0 连续递增，range 使用半开 `end_ordinal_exclusive`。schema、TypeScript DTO/parser、正反 fixture 以 [T0-G 冻结产物](../证据/MOSS-TTS-Nano施工/T0-G/README.md) 为单一输入，不保留 camelCase、revision 0 或一基 ordinal 兼容协议。
- Manifest revision 只追加、不原地改写。热刷新只接受同 Edition、同 source revision/hash 和更高 revision；相同 revision 仅在强 ETag 相同时作为幂等重放，ETag 不同按 `revision_collision` 拒绝。
- 每个 ready segment 保存无 token/query/fragment 的同源 PawApp 媒体 URL、实际 SHA-256、与实际摘要一致的强 ETag、duration/sample rate/channels 和 `gap_after_ms`；pending/failed/cancelled 不能暴露可播放音频。公共 Manifest 不回显句段原文、短文本 SHA/HMAC、内部路径或人物绑定。
- `ready_ranges/ready_prefix_count/default_start_ready/last_playable_start_ordinal/status` 由服务端回传，但客户端必须从有序 `segments + buffer_policy` 重新推导并逐字段核对；不另存一套可能漂移的状态真相。范围时长包含内部音频时长与句间 gap，不包含 range 末段后的 gap。
- 播放会话固定一个 Manifest revision 的已排队资产；只在句段边界拉取同 Edition 更新以延长窗口，不能中途换正文、音色或整章文件。

## 7. 已接受决策 6：初始缓冲与随机跳播

策略版本初始冻结为 `initial-buffer/v1-3-segments-8000ms`：

- 从合法起点连续至少 3 个 ready segment，且音频加内部 gap 累计至少 8000 ms，才可立即播放；
- 若从该起点到章末的全部剩余内容都 ready，则允许不足 3 段或 8 秒；
- 默认起点只能是章首或已保存进度，不能为了快出声跳过其前方 pending/failed；
- 作者显式选中中段时，只提升该 segment 开始的连续 `prepare-range`，不能回退章首或跨 gap；
- failed gap 阻断并显示具体失败；pending gap 等待/生成，绝不静默跳段；
- 同 client/Edition 的新交互 seek supersede 尚未执行的旧 seek，旧 completion 由 token 拒绝；后台请求通过有界公平老化避免永久饥饿。

上述门槛由 Manifest/服务端决定，前端只消费 `ready_ranges/last_playable_start_ordinal`，不能临时改成“看见一个 ready 就播”。

## 8. 已接受决策 7：媒体 Range、ETag 与播放器

- 浏览器只访问 PawApp 媒体 API 和 server-issued asset ID，不接触路径、模型目录或存储后端。
- 媒体 ETag 使用实际不可变播放资产 SHA-256 的强 validator；支持 GET/HEAD、单 byte Range、If-None-Match 和强 If-Range。非法/多 Range 返回 416，不能把 Range 内容传给文件系统。
- 正式服务必须重新验证固定 owner/workspace、novel、Edition、Manifest revision 和资产可达性；阶段 0 的内存 loopback 原型不能直接进入生产。
- 前端必须使用专用媒体读取适配器经 `window.QwenPaw.host.fetch` 发送 Range/If-Range/AbortSignal 并读取 Blob/ArrayBuffer；现有强制 JSON 的 `apiRequest()` 不能复用为音频入口，API token 也不能进入媒体 URL。
- Web Audio 同一时钟调度是首选分段播放路径；宿主不兼容时回退双 `<audio>` 预加载。二者都按 segment 边界更新编辑器高亮、保存播放进度并处理失败。
- 当前真实浏览器原型测得 Web Audio 调度漂移 0 ms、双 audio ended→playing 0.2 ms；它重复使用同一授权 segment，只证明调度，不替代独立相邻句段的人耳接缝验收。
- T0-GATE 已冻结调度算法和 `range_etag_contract=GO_FOR_T1-E`；正式 endpoint 与播放器均保持 `product_player_enabled=false`，直到 T4 完成真实鉴权、持久 CAS、流式 Range、宿主 UI 和独立句段接缝门禁。

## 9. 已接受决策 8：历史可读与媒体 GC

- Manifest、Edition、render 和媒体引用追加记录；当前指针变化或播放会话结束都不删除历史。
- T1 对全部历史 Edition/Manifest revision **无限期保留**；任一历史 Manifest、Edition、export、locked voice、voice reference、源资产或未过期运行租约可达的资产都是 GC root，T1 不实现按配额删除历史朗读。
- 普通 GC 只处理可重建派生物：无结构化 FK 引用且无活跃 job 的 staging/orphan 满 24 小时后才可成为候选；ready 派生资产先写 generation mark，至少等待 7×24 小时，再在同一 scope 一致性快照中复核引用与 generation，仍不可达才物理删除并写 tombstone。
- source upload、normalized reference 和 locked voice source 永不进入普通 GC；引用权威来自明确 FK/已知表，不扫描 JSON、文件名或目录。
- 文件删除失败保持 `deleting` 并重试；数据库提交失败后的 content-addressed orphan 同样服从 24 小时与 mark/recheck。缓存清理或插件升级不得造成当前播放队列中途 404。
- T6 若要增加历史 Edition 配额或保留期限，必须以新的用户可见策略、影响预览、迁移和 ADR 重开，不能静默缩短本基线。

## 10. 不采用

- 在普通正文点击上绑定播放，破坏光标定位和选区。
- textarea 叠层模拟 decoration/gutter，或凭相似文本猜旧 Edition 映射。
- 逐字卡拉 OK 时间轴作为首版范围；当前只承诺句段级同步。
- 前端从零散 ready segment 自行拼窗口，或跨 pending/failed gap 连播。
- 同 revision 不同内容仍接受，或播放中无提示切换 Edition。
- 先生成整章单文件才能播放，或把整章文件当唯一缓存权威。
- 让模型决定 blocker、审批状态、owner scope 或最终 Manifest。

## 11. 回退

- CodeMirror 宿主门禁失败时回退现有 textarea 和只读段落跳播，不影响正文编辑、保存或旧 Edition 播放。
- Web Audio 失败时使用经实测的双 audio；两者都失败时保留下载/导出和错误恢复，不自动换 Edition。
- Range/ETag/CAS 正式化失败时不开放分段播放器，不能退回未鉴权文件路径或整章临时 URL。
- 禁用 PawApp 时卸载编辑器 adapter、播放器、路由和任务监听，QwenPaw 原生页面与聊天恢复，用户正文和受保护源资产按声明保留。
- `chat.disposeAll(APP_ID)` 只清聊天扩展；播放器还必须在 React effect/disposer 中关闭 AudioContext、撤销 object URL、取消 Range 请求并清理 timer、事件监听和正在等待的 seek。

## 12. T0-GATE 接纳后的产品启用门禁

1. 固定 QwenPaw 2.1.0 中的正式 bundle/Blob 接线，以及 CodeMirror 对现有 recovery、600 ms debounce、100 ms 追保存、CAS 409、AI apply/undo 和章节切换的非回归；旧 timer/response 必须用 document id/generation fencing，不能写入新章；
2. 系统中文 IME 候选窗、长章滚动、页面重载、键盘与可访问性，以及 1920×1080／2560×1440 两个目标桌面分辨率；低于 1920×1080、移动窄屏和 200% 等效小视口为非目标、非阻断；
3. 两个独立真实合成相邻 segment 的 Web Audio/双 audio 人工接缝听检；
4. T0-H 十项安全裁决的精确字段、状态、Owner 和测试由 [gate-decisions.md](../证据/MOSS-TTS-Nano施工/T0-H/gate-decisions.md) 给出；T0-GATE 已对固定 hash 作 `ACCEPT_UNCHANGED`，实施结果继续由 T1/T3/T4/T6 各门禁验证。

原第 4 项 Manifest fixture/ready-range 契约已由 T0-G 的 snake_case schema、正反 fixture、24/24 TypeScript 和 21/21 Range/ETag 测试关闭；这只冻结实现输入，不提前放行正式 endpoint 或播放器。

T0-GATE 已按“契约接纳、产品关闭”的安全降级接纳本文。阶段 0 关闭后下一 ready set 仅为 `T1-DEP`；T4 仍须依次等待 T1-GATE、T3-GATE 及主计划列出的全部前置，不能提前施工。任何默认可见产品能力都保持关闭；正式 CodeMirror、播放器和媒体 endpoint 必须继续关闭到 T4-GATE。
