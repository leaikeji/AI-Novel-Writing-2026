# TTS56-B-UI：人物声音与通用包只读审计

日期：2026-09-03；基线：`main@0a686c2`，计划56 V1.1。

状态：**审计完成后收到主代理明确PAR-C派发，已修复三组件轮询与名单焦点圈定，定向回归通过；共享刷新/媒体试听由主代理集成，尚未进行本轮浏览器复验。**

所有权：审计阶段仅写本文；主代理随后明确追加PAR-C允许`character-voice-roster.ts`、`generic-voice-pack.ts`、`voice-preparation.ts`、`character-voice-generator.ts`及同名测试。共享入口、播放、样式、浏览器、模型、Docker、正式数据库及Git仍由主代理持有。现有README/索引/计划55与56改动均保留。

## 1. 结论先行

不能把旧截图中的全部问题当作仍未修复：遮罩层级和抽屉滚动已有实际修复及发布证据。本轮必要施工集中于请求生命周期、完成回调刷新与专属声音试听，不需要重设计整个页面。

| 项目 | 本次结论 | 最小范围 |
| --- | --- | --- |
| 左栏顶部/底部未遮灰 | 已有源码修复，复用历史发布；主代理补当前真实桌面复验 | 不先改CSS |
| 展开抽屉无法滚动 | 已有源码修复及实际滚动证据 | 不先重建抽屉 |
| 通用包/专属准备/单人物生成自动进度 | 确认自我取消GET的生命周期缺陷 | 修3个组件轮询，补真实延迟响应回归 |
| 后台完成后整页刷新/抽屉丢失 | 源码可追溯到reload→loading→卸载子树 | 共享入口+reading-page局部刷新，保留挂载 |
| 已生成专属人物的名单试听 | 错误地仅查询Nano实验记录 | 按版本来源走现有preview asset播放 |
| 展开后折叠的键盘圈定 | querySelectorAll包含不可见控件，边界判断不正确 | 过滤真正可聚焦项，补Tab/Shift+Tab |

## 2. 已确认P1：轮询启动会取消自身请求

位置：

- `frontend/src/narration/generic-voice-pack.ts:389-418`
- `frontend/src/narration/voice-preparation.ts:462-497`（主代理所有权）
- `frontend/src/narration/character-voice-generator.ts:573-611`（主代理所有权）

三个effect的结构相同：依赖`busyAction`；timer触发后先`setLocal(...busyAction:"refresh")`，再调用携带AbortSignal的GET；React随后处理busy state重绘，清理上一effect，立即`controller.abort()`。新effect因为busy不为空直接返回。真实慢响应会被取消，catch又因为signal已abort而不清空busy，页面可卡在“正在恢复”且停止继续追踪任务。后端任务可能继续运行，前端状态却不再推进。

### 非写入复现

用项目固定Node与TypeScript编译器在内存转译原模块，使用遵守effect依赖/cleanup顺序的hook harness，注入不会立即resolve的GET。执行：首次render安排timer → timer发请求并改busy → 第二次render触发effect cleanup。

实际输出：

```json
{"file":"generic-voice-pack","beforeBusyRerender":false,"afterBusyRerender":true,"busyAction":"refresh"}
{"file":"voice-preparation","beforeBusyRerender":false,"afterBusyRerender":true,"busyAction":"refresh"}
```

这不是浏览器网络验收，但已经直接执行当前组件证明控制器被自身状态改变中止。单人物生成同构源码仍须在修复中补独立回归。

当前三个测试文件的baseProps都把`refreshIntervalMs`设为0，已有通过结果没有覆盖该风险。

最小修复：分离timer调度与在途请求所有权；自身busy重绘不得取消有效GET，只有卸载/scope/命令身份更换等真正失效时取消；响应落地检查scope/sequence/abort；完成后再安排下一次，有界单请求，不引入第二队列或通用轮询框架。

必须补验：deferred GET跨一次以上render、返回后继续推进、terminal停止、真实AbortError不锁死、卸载/换scope忽略旧响应、重复timer不重入。

## 3. 已确认P1：完成通知导致整页/卡片子树卸载

追踪：

1. `index.ts:728-729`：自动准备到terminal调用`refreshRoster()`。
2. `index.ts:544-545`：`refreshRoster`直接调用`context.onRefresh()`。
3. `reading-page.ts:504`：刷新增加reloadVersion。
4. `reading-page.ts:453-456`：每次刷新都把整个页面置为loading。
5. `reading-page.ts:510-519`：loading只返回ReadingOverview，CharacterVoiceSection/已打开Roster Drawer被卸载。
6. 单人物声音改变亦经`index.ts:1351-1354`同时增加卡片reloadVersion与调用父onChanged；卡片自身在加载中也以placeholder替换配置器（`index.ts:1277`附近），导致未提交调音/搜索/展开状态消失。

因此不仅是网络慢造成闪动：当前数据结构实际移除了仍在使用的子树。当前页面静置且无活动命令时是否仍存在额外刷新源，本审计未作浏览器判定，不能声称存在无限刷新。

最小修复：同小说refresh采用保留ready快照的后台校验；人物绑定/音色资料更新为局部数据更新，首次加载或小说scope改变才显示全页loading。保持同人物配置器身份与抽屉、输入草稿、展开、scrollTop、焦点；失败明确显示局部错误，不用旧CAS继续写。绑定列表应在完成后重新读取，不可只刷新profiles。跨小说返回必须继续fail closed。

必须补验：抽屉正在填写seed时后台另一任务完成；同人物更换官方音色后抽屉保留；发生CAS drift不误更新选择；同scope刷新失败不清空草稿；小说切换不泄露旧资料。主代理当前浏览器锁下做1080P/2K补验。

## 4. 已确认P1：专属生成音色的名单试听路由错误

位置：`index.ts:765-779`，以及`character-voice-roster.ts:235-247`。

Roster把具有`preview_asset`的`source_type="generated"`版本标记为可试听；但点击后共享入口将所有generated版本都查询`listNanoVoiceExperiments()`，只找experiment.version_id。真正由VoiceGenerator产生、activation_basis为`character_one_click_generation`的版本没有Nano experiment记录，若前端接收到可用preview_asset，就会错误提示“当前高级调音试听已过期，请重新创建并使用”。

主代理进一步核查发现后台投影缺口：`voices.py:441`只从未过期VoicePreview投影preview_asset，而VG处理器仅写version.preview_asset_id、未写VoicePreview，因此实际名单可能首先表现为按钮禁用，不能声称正式环境一定点击后报错。当前media API只有Edition/VoicePreview/generic-slot授权，不能把版本媒体裸URL直接交播放器。该问题是“后台可授权预览投影＋前端来源路由”两层缺口，主代理统一冻结最小修复。

最小修复：先补合法受scope/hash约束的预览授权投影，再区分专属生成与高级实验来源；不绕过media校验、不伪造实验记录、不重新生成音色。试听永远不写绑定。错误文案不得把正常专属声音引导为无必要的重建。

必须补验：官方preset、专属generated、实验generated三路；专属preview不得调用实验列表；失效asset正确报错；不匹配scope/hash拒绝；全部试听零绑定写入。

## 5. P2：折叠后焦点圈定列表包含隐藏后代

位置：`character-voice-roster.ts:378-403`。

FOCUSABLE_SELECTOR结果没有过滤`details:not([open])`、hidden/inert或布局不可见后代。配置器为了保留内容，在首次展开后不卸载低频内容（`character-voice-configurator.ts:328-352`），这是正确的保留草稿方向，但与当前圈定算法冲突：重新折叠后，隐藏的末尾input/button仍被当作“最后可聚焦项”，最后实际可见summary上按Tab时不会被拦住；Shift+Tab可能尝试focus不可见末项。

最小修复限定roster：只把真正可聚焦且可见项参与首尾判断，保留原生radio方向键及details语义；不要靠卸载折叠区“解决”而丢失调音草稿。同步核验IME Escape不应误关抽屉。类似人物卡工作台自有圈定逻辑可由主代理按复现决定是否纳入，不自动扩范围。

此项为源码可证明的列表错误，实际宿主Tab泄漏程度仍待浏览器补验；不把未运行的浏览器结论写PASS。

## 6. 可复用修复与证据

- `frontend/src/styles.ts:613`：存在drawer时workbench frame提升到z-index900，避免宿主sticky侧栏穿过遮罩；没有改QwenPaw核心。
- `frontend/src/narration/styles/t2-c.ts:376-409`：viewport固定layer，`minmax(0,1fr)`与drawer min/max-height/overflow约束。
- 同文件`:450-469`：正文scrollport的`overflow-y:auto`、稳定scrollbar gutter、overscroll与可见thumb。
- `计划55/TTS55-RELEASE.md:47`：已记录展开官方音色后clientHeight984、scrollHeight1131、实际scrollTop146.04/147及Escape关闭。可以复用为历史修复成立，不代表本轮确切1080P/2K viewport验收。
- Configurator惰性首次挂载官方库/高级内容，scope变化取消匹配请求，匹配结果并发漂移不覆盖并可显式应用；这部分不重写。
- 官方音色库使用radio change作为唯一绑定动作，预览按钮独立；通用crowd男女展示已改为“未具名…对白（单声线）”，不再重做已完成文案。

## 7. 已运行测试

固定运行时：`/Users/liujia/Library/Application Support/AI小说世界2026/controller-runtime/node-v24.19.0-darwin-arm64/bin/node`。

```text
<固定Node> node_modules/vitest/vitest.mjs run \
  frontend/src/narration/character-voice-roster.test.ts \
  frontend/src/narration/character-voice-configurator.test.ts \
  frontend/src/narration/generic-voice-pack.test.ts \
  frontend/src/narration/voice-preparation.test.ts \
  frontend/src/narration/reading-page.integration.test.ts \
  frontend/src/workbench-container-layout.test.ts
```

结果：**6个文件、45测试通过，254ms**。没有改源码、测试、依赖；这些既有测试通过不抵消上面新发现。

未运行：真实浏览器、长期写入、TTS推理、Docker、部署、移动端。浏览器与全量集成由主代理统一执行。

## 8. 交回与待派发

审计建议后主代理冻结了扩展的精确PAR-C范围（见本文顶部）；共享index/reading-page与媒体试听仍由主代理统一集成。没有证据支持大规模视觉重设计或重复CSS重构。

## 9. PAR-C修复与交回（18:41）

- 三个异步组件将timer cleanup与请求controller ownership分离：busy rerender只清timer；命令身份变化/卸载以及单人物scope变化才中止在途GET；迟到/忽略abort的响应不发布。
- 轮询结束递增内部pollRevision，保证同timestamp响应、同错误或批处理掉中间busy render时仍能安排下一轮。不新增接口/共享轮询框架/外部队列。各次GET串行，terminal不续跑。
- 单人物异步手动结果也核对当前scope，避免切换人物后旧结果回写UI。
- Roster圈定使用可见且非hidden/inert的元素，展开后折叠内容继续挂载保留草稿；Tab/Shift+Tab不指向隐藏后代。IME组合态Escape不关抽屉。
- 已移除原timer effect中造成自取消的controller cleanup，未保留第二套轮询路径；未修改CSS、Configurator、共享入口、API或媒体授权。

新增9项回归覆盖真正pending响应跨render、非重入、取消后不续跑、卸载abort/忽略迟到结果、换人物scope、错误后续跑、同timestamp续跑及隐藏焦点/IME。测试harness增加显式unmount清理，不以`refreshIntervalMs:0`覆盖这些用例。

最终定向命令：固定Node运行Vitest的`generic-voice-pack.test.ts`、`voice-preparation.test.ts`、`character-voice-generator.test.ts`、`character-voice-roster.test.ts`、`character-voice-configurator.test.ts`。

结果：**5个文件57测试通过（181ms）**；固定Node `node_modules/typescript/bin/tsc --noEmit`通过；`git diff --check`通过。共享主代理候选的最终typecheck/build/全量与真实1080P/2K浏览器仍需集成验证，不用本结果代替。

交回8个产品/测试文件与本文后不再自行写入，等待主代理集成。此次没有调用模型、改正式数据或操作Docker/Git提交。

## 10. 专属试听最小授权路线只读复核

主代理后续独立派发只读调查；本节只追加建议，不修改任何源码/DTO/schema，不执行浏览器/模型/数据库。

### 10.1 现有公开路径无法直接服务该验证资产

| 既有路径 | 为什么不能直接复用 |
| --- | --- |
| Edition + manifest header | 只授权冻结Edition段的可达资产，VG验证短句不是已发布章节段；伪造Edition会增加无关数据 |
| `X-Narration-Voice-Preview-Id` | `resolve_voice_preview_media()`要求ready且未过期的VoicePreview、temporary_preview retention和相同expires_at；VG资产是private_voice_validation，没有该Preview |
| `X-Narration-Generic-Voice-Slot-Id` | 要求真实workspace通用slot/pack/version闭环；小说人物专属不属于通用slot |
| POST创建VoicePreview | `voice_product.py:2212`明确只支持uploaded/preset，且会发新Nano任务；改它来伪造ready预览或为播放重推理均不合理 |
| GET人物生成command | 能投影result_version，不提供合法媒体读取授权；结果版本preview同样经voices.py的临时Preview查询，故仍缺失 |

推荐：**只给既有`GET/HEAD /media-assets/{asset_id}/content`增加一个互斥的`X-Narration-Voice-Version-Id`授权选择器**（名称须由主代理C0冻结）。不增业务路由、表、迁移、模型任务或新能力键；复用现有`VoiceProfileVersionResource.preview_asset`字段，合法VG验证音频从既有不可变证据投影。header不是认证凭据，仍受既有PawApp/T4路由权限及固定本机scope约束。

### 10.2 可复用函数与精确接线文件

- `backend/narration/services.py:254 require_local_novel()`：确认小说存在且属于固定owner/workspace。
- 同文件`:276 voice_activation_evidence_is_usable()`、`:374 require_usable_voice()`：复用激活、locked、active、rights scope/到期/负向历史规则。注意后者使用Version→Profile→Rights短锁；不得在该事务里读整段文件。它们**不等于**已验证VG双ModelRun/command图，仍需下一节的窄关联校验。rights确认事件可复用`voices._rights_state()`/`voice_product._required_active_rights()`现有规则，避免单凭无撤销就假设已确认。
- `backend/narration/voices.py:405 voice_preview_media_link()`：通用preview资产metadata安全检查与现有MediaAssetLink投影。新增generated专属分支不能放开任意旧`preview_asset_id`；应共享一个受完整证据约束的窄解析器，由profile投影和HTTPresolver共同使用。
- `backend/narration/generic_voice_pack_service.py:262 resolve_generic_voice_slot_media()`：只参考其选择器→关联图→精确asset的组织方式，不拿generic slot替代人物version，也不照抄它较弱的模型校验。
- `backend/narration/playback_api.py:578 read_media()`、`:1048 _read_media()`、`:1105 GET`、`:1141 HEAD`：现有三个授权分支扩为四个且继续exactly-one；同步`PlaybackApiBackend` Protocol、resolver注入与工厂。
- `backend/narration/production_runtime.py:1455`附近媒体resolver和`:2111`附近工厂：接入同一只读解析器；媒体读取不应要求VG模型当前驻留，更不能为试听启动重模型。仍遵守当前产品媒体发布门禁。
- `backend/narration/media.py:147 _validate_ready_asset_for_read()`、`:200 plan_media_read()`、`stream_read_decision()`：原样复用canonical路径、ready/local、真实SHA-256/大小、inode、MIME、GET/HEAD/Range/ETag。当前playback backend在解析后expunge/rollback再hash/open，保持这条事务边界。
- `frontend/src/narration/voice-preview-playback.ts`：复用`mediaPath()`、`assertMediaResponse()`、`playObjectUrl()`，增加version selector的窄fetch/play入口；`index.ts`按`activation_basis`选择VG版本预览，Nano高级实验保持原临时Preview路径。

不建议让profile列表为每一个官方版本执行VG证据查询；先仅对`generated + character_one_click_generation`且候选资产存在的版本进入解析。预计很少的专属版本使用有界关系查找；正式存在大量版本时按IDs批量预取，而非新增缓存服务。删除/撤权等正常不可用返回preview null，不能让一条历史不可用记录拖垮整个声音列表。

### 10.3 必须校验的最小证据闭环

先由请求的version查出profile和novel，不信任客户端另传人物/小说范围。不能用当前人物绑定作为试听授权前提：`ready_unapplied`是有效生成结果，作者后来改选也不应使旧的仍有效私人声音无法试听。

1. Novel/Profile/Version/Rights的owner/workspace/novel严格同域；这里只接**小说专属**，不接受library、uploaded、preset、generic或实验版绕入。Profile active、Version locked/accepted/machine_validated/character_one_click_generation，rights有效且有confirmed、无负向/到期。
2. 找到恰好对应该profile/version的持久VoiceGeneratorCommand，而非“该人物最新一条”。只接受`ready_applied/ready_unapplied`，completed_at存在、failure_code为空、精确draft/job/人物范围；`nano_validation_asset_id == version.preview_asset_id == asset_id`，`generated_reference_asset_id == version.reference_asset_id`。
3. Command的generator/nano ModelRun均success且来自同一成功BackgroundJobAttempt、该attempt属于command.background_job_id，job kind为narration.voice_generate且succeeded；command/draft/job同scope、job.input_hash等于draft fingerprint。
4. ModelRun的requested/actual provider、model、revision及fingerprint与生成时固定协议证据一致；Nano output_digest==验证音频hash，VG output_digest==参考音频hash。version.model_run_id==command.nano_model_run_id；version参数中的nano_parameters_digest匹配Nano run。不要读当前模型是否加载来决定旧音频可否播放。
5. VoiceGeneratorRunEvidence必须对应同一command/generator run/attempt，success、协议/topology/runtime identity一致；audio_digest==reference hash，instruction_digest及key identity与VoiceDesignDraft/Version一致。复用现有固定模型常量，不能另抄一套散落字符串。
6. 验证MediaAsset必须是该小说`narration_voice_preview / preview / private_voice_validation`且ready，metadata.command_id精确指向该command；validation_json中的reference_sha256和Nano fingerprint一致。只返回Nano验证音频，不开放reference原始音频或任意asset ID。
7. profile unavailable/archived、asset deleting/deleted/tombstone、撤权、关系缺失/混域均fail closed。`voice_deletion.py:365-366`已纳入version的reference/preview计划，无须新建删除根。原0035闭环刻意允许deleting/deleted保留历史审计，因此“迁移约束没报错”不能当可播放。

源码参考：`voice_generator_processor.py:483-724`保存完整图；`20260830_0035_voice_generator_design.py:545-676`是既有数据库闭环定义，只读参考不修改/不从HTTP调用trigger。应用层解析器应复用既有激活/rights规则并补这张窄关联图，不为媒体读取复制整个生成服务。

“历史”分开处理：当前仍active/完整的已生成版本可以试听，不能强迫等于当前人物绑定；无完成command图的旧legacy preview字段继续为空。删除围栏之后的新GET/HEAD/304必须拒绝；已经下载到浏览器Blob或已打开fd的播放无法承诺追溯抹除，这是已有媒体生命周期边界，不另造强制远程撤回系统。

### 10.4 同源技术约束

- 原生`<audio src=...>`不能附自定义selector header，应继续`window.QwenPaw.host.fetch('/ai-novel-world-2026/media-assets/...') → Blob object URL → HTMLAudioElement`；不改宿主fetch、不放query token、不用物理路径/file URL。
- 只允许canonical asset path/UUID，拒绝query/hash/外域；新header与Edition/Preview/Generic任一混用均422，GET/HEAD行为一致。现有host负责公开插件转发，不新增跨域服务/CORS放宽。
- 服务端必须在304/HEAD之前重新校验授权和文件身份；前端复用长度/MIME检查，不能把该检查说成前端已算SHA-256（当前helper并未计算hash）。共享server物理读取已做实际hash校验。
- 取消/退出/播放结束释放object URL，不写绑定；失败文案说“专属音色试听暂不可用”，不能误引导“重新创建高级调音”。

### 10.5 最小测试清单

- `tests/narration/test_voices.py`：真实闭环VG版本投影preview；遗留字段/缺图/删除/撤权为null；官方与高级Preview到期逻辑不变；不可用旧版本不污染全列表。
- `tests/narration/test_voice_generator_processor.py`或新增窄resolver测试：复用processor完成图fixture，逐一破坏command状态、scope、ModelRun requested/actual、run output hash、attempt/job、rights/evidence、asset指向，均拒绝；ready_unapplied及后来改选的有效旧版本可读。
- `tests/narration/test_manifest_v2.py`：第四授权分支GET/HEAD/Range/304；零头/双头/半Edition/非法UUID/query拒绝；原三路径不变；resolver未装配fail closed。
- `tests/narration/test_media.py`/`test_media_postgres.py`：缺文件、hash/inode/size改变、围栏后读及304仍拒绝；复用已有物理读取负向覆盖，不全量重复。
- `frontend/src/narration/voice-preview-playback.test.ts`：唯一version header、canonical path、HTTP/MIME/size失败、abort/objectURL释放；不带绑定操作。
- `frontend/src/narration/t2-gate.integration.test.ts`：VG走version preview，Nano实验走原Preview，官方走原preset；不能对正常VG调用实验列表或模型创建接口。
- 主代理隔离/正式只读验收：点击已有已生成角色的试听，GET200与声音播放，绑定版本/生成command数不变，零模型唤醒；然后用隔离图验证删除后失效。无需重新生成音色。

结论：该增量是现有数据已具备、公开媒体授权缺一支的修复，不是新音色产品或新生成基础设施。全部接线/DTO与错误码变更仍由主代理C0决定；本子任务只有本节文档写入。

## 11. TTS56-C-PREVIEW：授权解析器实施与交回

主代理随后完成C0并将此工作包从只读转为PAR-C施工。本节更新第10节的阶段状态；第10节保留当时审计，不再表示当前仍未实施。子代理仅新增`backend/narration/voice_version_media.py`、`tests/narration/test_voice_version_media.py`和追加本报告；HTTP/runtime/voices投影/前端接线由主代理独占。

### 11.1 已实现的窄修复

- 冻结入口为`resolve_voice_version_media(store, version_id, asset_id, *, at=None) -> MediaAsset`，只返回真实完成的人物专属Version的精确Nano验证资产。没有新DTO/schema/VoicePreview/任务、文件读取或模型调用。
- 用只读Store适配器复用`require_local_novel`、`require_usable_voice`，屏蔽其写锁；写入、flush、publication调用直接拒绝。Novel/Profile/Version/Rights/Command/Draft/Job/Character/Media全部检查固定scope和小说关联。
- 除active/locked/rights确认/负向历史外，校验成功Command、成功Job/Attempt、双ModelRun requested/actual身份、输出hash、native runtime receipt、draft HMAC摘要交叉引用、Version fingerprint和资产metadata/validation来源。按真实processor参数格式重新计算VG参数和Nano验证参数digest，不能仅用两边相同的标签代替真实参数校验。
- 只支持现有固定`character_one_click_generation`发布图；uploaded/preset/实验/generic不走此路。reference原始音频、任意替换asset、缺图、撤权、归档、删除围栏/墓碑均拒绝。已有legacy裸preview字段不被升级为可信播放链接。
- 不要求当前人物仍绑定此Version、不访问当前模型进程：`ready_unapplied`和已被作者改选的有效旧版本均可试听。固定历史模型身份来自已有协议常量，而不是运行中的health。
- 与主代理`voices.py`接线联合验证：合法专属版本的`preview_asset`非空；撤权后列表仍可读取，但该字段为null。播放API仍应经过现有物理文件hash/路径/inode读取层；本解析器不取代物理校验。

### 11.2 实际验证

1. MemoryStore定向覆盖92项：正常applied/unapplied、逐类缺图、跨owner/novel、运行失败/错误requested/actual/receipt、参数双边同时伪改、asset替换/原始reference、删除和撤权；所有lookup显式断言无`for_update`，写入/flush/publication均禁止。
2. 隔离PostgreSQL沿用既有`test_voice_generator_postgres.vg_pg_runtime`的loopback+精确库名+repository head安全检查，使用主代理确认的58857 tmpfs测试库。复用真实`VoiceGeneratorProcessor`发布事务、现有`_Host`/`_Nano`确定性适配器和临时媒体目录；没有启动或下载任何模型，没有操作正式数据库/媒体。
3. 两个PG正向均通过：正常生成后`ready_applied`；生成期间作者绑定官方音色触发CAS后的`ready_unapplied`。两者均能解析已有Nano验证音频并从profile列表投影。原始reference读取拒绝；追加真实rights revoked事件后解析拒绝、preview投影null。
4. PG单profile投影实测23条SELECT，分别9.74ms/10.21ms（本机隔离测试值，不是正式环境性能承诺），无FOR UPDATE。没有为日常试听增加模型探测或跨请求缓存；查询数随专属版本数量线性增加，大量专属版本可在后续按IDs批量预取，不能以加缓存服务掩盖。官方版本不进入此解析分支。
5. 最后回归：`.venv/bin/python -m pytest -o addopts='' tests/narration/test_voice_version_media.py tests/narration/test_voices.py tests/narration/test_voice_generator_processor.py -q`：**122 passed, 2 skipped**（未带PG变量时两项按安全约定跳过；此前带明确隔离URL的两项均已实跑通过）。`git diff --check`通过。

PG共享锁已交回主代理。本子任务不宣称浏览器/真实音频/生产验收完成；主代理继续HTTP/前端集成、实际试听及整体性能核验。已经送到浏览器Blob的音频无法追溯撤回，后续新请求按当前授权fail closed，保持既有生命周期边界。

## 12. TTS56-D-ADV-UI：更换官方基础音色后的高级调音同步

主代理在18192真实复现：人物原绑定Junhao，输入seed=987654321后从官方列表改选Zhiming，抽屉和输入仍在，但高级标题继续显示Junhao。问题不是缺少整页刷新，而是高级Workspace没有订阅现有局部profile刷新版本；此外Panel的默认draft scope包含preset，直接更新base会重置草稿。

主代理C0冻结`NanoAdvancedWorkspaceProps.refreshVersion?: number`并负责index入口传值；随后明确扩本工作包到`nano-advanced-tuning.ts`和同名测试。本子代理只修改这两个组件及对应测试、本报告，不修改私人删除组件/后台/API，不使用浏览器/数据库/Git。

### 已实施

- 高级Workspace订阅refreshVersion，同小说+目标在后台重新获取profiles/bindings/experiments，保持Panel组件类型和key，不先退回loading卸载已有编辑界面。刷新失败保留草稿，提供本区域的重试按钮，不触发上层整页重载。
- Panel新增可选`draftScopeKey`：Workspace传`novelId:target`，同目标切换preset只更新显示、请求base和CAS，保存参数草稿；切换小说/目标立即隔离旧数据并清空草稿。独立Panel未提供此参数时保留原有按base重置行为。
- 修复高级实验GET连续返回running时只轮询一次的问题：每次成功响应推进局部poll revision，再在1秒后调度；实际pending Promise期间不发第二条GET、不因普通重绘自abort。错误停止自动查询并提供明确重试；结束、卸载、切target/base清理计时器和AbortController。
- 本地实验快照也经过target/base/version选择器，不再用`experiment ?? ...`跳过身份检查。恢复官方后历史ready_applied不冒充当前绑定；CAS来自当前显示所依据的settings/binding，不用历史命令携带的旧current_*覆盖。
- create/apply/restore复用现有signal参数，添加组件局部请求围栏、防重复提交；卸载/跨scope会abort，迟到响应不能覆盖当前人物、设置错误或触发父级刷新。没有新增调度框架或任务系统。

### 自动化与交回

- 定向Vitest：`voice-feature-workspaces.test.ts` + `nano-advanced-tuning.test.ts` **28 passed**。包含真实pending Promise跨重绘、单flight、同state续跑、错误重试、scope切换、卸载、错目标响应、双击/迟到mutation，以及Junhao→Zhiming保留987654321、跨小说/人物清空、独立Panel兼容、恢复官方后拒历史CAS等回归。
- pinned Node运行`node_modules/typescript/bin/tsc --noEmit`通过，`git diff --check`通过。
- 无实际DOM/IME/焦点/浏览器PASS冒报：组件测试证明Panel类型/key/草稿scope保持不变；真实浏览器原复现路径和输入焦点/滚动仍由主代理在新候选部署后复验。
