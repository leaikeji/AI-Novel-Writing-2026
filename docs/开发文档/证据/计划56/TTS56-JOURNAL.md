# TTS56 施工日志

状态：**执行中；最新检查点见第9节。用户已授权正式正常流程验收，已备份并发布修复候选；正式通用包继续构建、人物专属/章节链补验中，尚未最终通过。原有作品只读，作者听检未完成，未提交或推送Git。下文早期记录保留各自当时状态，不代表当前门禁。**

## 2026-09-03 G0/C0

- 用户明确要求优化计划并使用目标模式执行；目标已创建，尚未完成。
- `main@0a686c2a9b776983f2bc8f3068bca4e6b53c51b8`与origin/main同步；开工脏文件仅本任务五份规划/索引/纠偏文档，保留它们。
- 源码与正式库唯一head为`20260903_0040`；正式health ready；本项目三个长期容器healthy，不操作其他项目容器。
- 正式公开generic-pack为missing、0/24；官方cast command已有1条ready_applied_with_warnings，不由状态单独推导真实全链通过。
- Nano模型当前未加载，idle_unload_seconds=300；生产运行就绪，automatic_generic_casting因缺active包仍unavailable。
- 独立私有保全目录：`/Users/liujia/Documents/AI小说世界2026-backups/plan56-EUdaURFG`；归档`tts55-audio-preserved.tar.gz`包含原`tts55-listening`及`tts55-real-media.j0uWv6`，没有删除或改写源文件。
- 归档SHA-256：`f9ddd2a2de5062a15a88fdd72eb962796754947fc807bef01465f58b07d8694e`；目录0700、文件0600。从归档解出的06音频hash为`76a929d18dc31a3e13cceb76937463eaf072e3cdafb27532586e0bbfec5a513d`，与作者批准版本一致。只证明媒体保全，不证明完整旧隔离数据库可恢复。
- 当前授权：源码/隔离测试/本轮证据保全可执行；已发一次合并问题询问正式备份、必要部署和24槽建包授权，尚未收到答复。真实书绑定/正文写入、Git、历史资源删除不在范围。
- C0冻结：沿用capabilities/4、0040与现有API/state/CAS；官方选角整批原子，专属准备逐人CAS；不新增schema/基础设施/模型。A/B先只读审计，尚不允许产品文件写入。
- 主代理持有共享入口、provider、计划/索引、正式环境、浏览器和重模型锁；当前不运行重模型。A只写`TTS56-A-POOL.md`；B只写`TTS56-B-UI.md`，不操作Docker/浏览器/正式库。

## 初始证据清单（不是最终PASS）

| 检查 | 本轮处理 |
| --- | --- |
| 01默认旁白、02官方目录 | 优先复用35/55已验收链，抽查当前目录与调用 |
| 03官方智能匹配 | 补真实Agent单人与全书成功/恢复；已有单条command不等于完整通过 |
| 04专属生成、06章节链 | 复用55六人物与16段实际证据；补受影响/缺少路径，不重写四章样书 |
| 05通用池 | 正式0/24，授权后建立；恢复代码先审计 |
| 07高级/删除 | 复用已有独立风险覆盖，相关改动才重验；真实删除仅隔离 |
| 08播放器 | 复用可适用客观探针，补必要作者听检 |
| 09/10桌面/性能 | 核实当前源码的刷新/滚动生命周期，再做1080P/2K真实补验 |
| 11发布恢复、12资源证据 | 新正式包需新备份及还原；现有声音先保全，空闲释放补观察 |

## 2. 缺陷冻结与修复派发

A/B审计已返回。C0增量冻结：不改API、DTO、schema和状态集合；A在现有服务内修包失败收敛、重生成原子性/幂等和首次并发串行点，测试落现有PG专项。B修三个进度组件轮询自abort与抽屉隐藏控件焦点；仅把两个同类组件及测试加入明确所有权。主代理修共享入口的局部刷新与VG试听路径，并把缺active通用包的原因码由处理器故障改为既有`GENERIC_VOICE_PACK_NOT_READY`。不重做已修滚动/遮罩。

固定Node 24.19.0与pnpm 11.19.0已解析；仓库package.json在根目录，计划中的旧`--dir frontend`命令已更正。独立PG只用于本计划恢复/事务验证，不使用正式数据和卷；模型与正式环境仍未写入。

PG资源：`ai-novel-tts56-postgres`，仅127.0.0.1:58857，独立tmpfs，head0040；A独占测试期，其他包不并跑数据库。初始provider与runtime定向62项通过；入口/朗读页27项通过，尚待补浏览器和全量。

C0补充：A的真实PG反例证明固定seed重生成会复现同音频并撞fingerprint唯一约束。允许**仅作者显式重生成的目标槽**在不可变Draft中派生新的确定性seed，同请求重放/失败重试保持一致，不改固定目录/描述或其他槽。实际seed须进入既有身份与模型证据，不能加随机盐绕过约束。审计中的“VG试听”还需区分后端未投影临时Preview导致禁用与前端误走Nano实验；当前媒体读取只有三条scope授权，不允许裸读音频绕过，需要单独冻结最小修复后再接线。

同样适用于作者明确reject后首次继续建立的目标继任；普通技术失败重试不得换seed。这是对“重做不喜欢声音”的现有语义修复，不改变固定目录。

## 3. 第一批集成检查（施工中，非FINAL）

- 三种进度组件拆开timer与请求生命周期，补真实pending Promise、同timestamp续跑、卸载/切scope、取消与错误恢复。B定向57项通过，文件已交回。
- 共享ReadingPage刷新保留同小说子树，网络失败保留编辑器并显示可重试错误；跨小说在effect前也不展示旧数据。卡片声音写入只刷新binding/profile，删除一次重复overview请求，不卸载配置器/高级参数。
- 当前全量pytest：3754 passed / 200 skipped，跳过项不计通过；运行期间A仍补PG测试，最终汇合后应重跑。当前前端全量1219 passed；typecheck、build、插件打包、136项manifest/Skill/宿主契约、Compose与diff-check通过。
- 正式旧版本只读UI补验：打开既有人物声音抽屉，展开两组details；1080P和2K请求视口下，滚动top从146到849、再到1341，容器overflow=auto，scrollHeight=2683；2K clientHeight=1341，能到达底部；Escape关闭；无本次控制台error/warn。截图：[1080P](./TTS56-live-baseline-1920.jpg)、[2K](./TTS56-live-baseline-2560.jpg)。浏览器截图坐标受宿主缩放影响，记录请求viewport与实际DOM测量，不伪称像素严格1:1。
- 遮罩完整覆盖宿主左上与左下；已修旧问题无需再改CSS。此次仅复核旧版基线，**不替代未部署候选的UI验收**。未点击生成/绑定/保存/删除。
- 专属试听实际缺口已在正式既有数据只读复现：沈听澜有专属版本，但名单试听disabled。继续冻结授权读取链后修复，不能以文件存在宣称可播放。

尚未进行正式建包/发布、候选版本真实浏览器、真实官方选角补验、最终恢复与作者听检；目标保持active。

## 4. 第二批集成与真实候选检查（2026-09-03 19时，非FINAL）

- A已交回：通用包首次创建并发、scheduler失败/取消收敛、重生成原子性与幂等修复完成。普通失败重试保留seed；只有显式重生成或拒绝后继续的继任Draft派生新seed，其他23槽不变。A定向36项通过，详见`TTS56-A-POOL.md`。
- C已交回：专属音色投影/GET/HEAD复用同一只读解析器，核查生成命令、版本、权利、双ModelRun和资产身份；不创建临时Preview，不重新合成。新增互斥header，不新增路由或schema。C 92项内存测试＋2项真实PG测试通过；PG用真实processor发布形状、模型使用测试适配器，**不是实际VoiceGenerator推理**。主代理补实际文件Range GET/HEAD（206、RIFF、16字节、stream期间无数据库事务）。
- 合并PG专项（C/通用生成/通用包/功能API）130 passed、0 skipped；随后扩充的C专项94 passed、0 skipped。主代理独占`TTS_TEST_DATABASE_URL`测试库运行，未接正式库。
- 第二次全量后端3846 passed / 203 skipped / 3 warnings；前端142文件1220 passed，typecheck/build通过；136项宿主/manifest/Skill契约通过。这些是D修复及浏览器新缺陷修复前的候选成绩，最终仍需针对最终源码重验。

### 4.1 隔离资源及边界

- 独立数据库容器`ai-novel-tts56-postgres`仅127.0.0.1:58857、tmpfs、head0040；分开`ai_novel_world_2026_tts_test`与`ai_novel_world_2026_tts56_browser_test`，不会在浏览器库运行迁移破坏测试。
- 隔离宿主`ai-novel-tts56-qwenpaw`仅18192，独立`ai-novel-tts56-qwenpaw-data`和`ai-novel-tts56-qwenpaw-secrets`卷；独立`ai-novel-tts56-net`网络。通过项目打包与QwenPaw公开plugin install命令安装候选，不改上游核心。
- 隔离`ai-novel-tts56-sidecar`只读复用固定模型与单用途Sidecar令牌卷，网络别名沿用协议要求的`tts-sidecar`；不挂正式小说媒体/数据库。新宿主使用新生成的独立HMAC keyring，未打印密钥。
- 首次环境的Sidecar别名不符合冻结拓扑、媒体目录未建立均已修正；不把隔离环境配置错误记为产品源码缺陷。当前technical/product ready，VG因未配置隔离host token unavailable，通用选角因缺包unavailable。
- 通过公开API补建最小样本`雾港回声`（`0068961c-e55b-4854-bdb7-b97a0b0d7653`）和两人物沈砚、方若岚，未在正式作品库增书。隔离AI小说作家已创建，但未配置有效Provider/模型；尚不能把官方智能匹配算作真实通过，不读取/复制正式Provider密钥绕过。
- 上述资源均标记`ai-novel-world-2026.resource=tts56-isolated-qa`。PG是tmpfs，清理前必须保全本次真实模型资产及相关数据库证据；不得删除只读借用的正式模型/令牌卷。其他项目容器不动。

### 4.2 真实UI新发现与修复

1. 在隔离宿主选择官方音色，抽屉、展开项和参数草稿能保留，未复现整页卸载；但高级调音底音仍为旧值，轮询同state响应也有停止风险。已冻结D续包：同scope重取保Panel/草稿、跨scope隔离、同state续跑；文件范围见计划8.1。尚待D交回和真实复验。
2. 焦点会驱动`overflow:hidden`的抽屉外层滚动38.61px，使标题y=-38.61。主代理只将外层/抽屉改为`overflow:clip`，正文仍`overflow:auto`。两桌面实测外层scrollTop=0、标题y=0、正文能滚至底（1080P实际client984/scrollHeight3129/scrollTop2144.55；2K实际client1341/scrollHeight3075/scrollTop1734.16）。修复前截图保留：`TTS56-candidate-1920-scroll.jpg`、`TTS56-candidate-2560-scroll.jpg`；修复后：`TTS56-candidate-1920-header-fixed.jpg`、`TTS56-candidate-2560-header-fixed.jpg`。不是覆盖历史失败证据。
3. 官方`CN 京味胡同闲聊`真实Nano于11:09:12 UTC完成，job succeeded、Preview ready，但GET Preview返回500。根因是媒体投影函数重命名后`voice_product.py`仍动态import旧`_media_link`，只在ready分支触发。已统一调用`voice_preview_media_link`并补成功资源投影回归，25项专项通过。真实数据库同一Preview在修复后的领域投影返回ready；HTTP/浏览器复验待候选更新。音频3440ms、660524字节、SHA256=`2513931396bd75dfec874b12026a948ba0cb4574d1bae019dc9461c947101f70`。尚不以合成成功宣称页面播放成功。

### 4.3 正式只读请求基线

正式小说`1e405084-319f-472d-b95d-d003ed1e305d`每接口连续6次只读GET，未清缓存，因此首条不是严格冷启动，不报告伪p95：

| 接口 | 首次ms | 后5次中位ms | 后5次最大ms | 字节 |
| --- | ---: | ---: | ---: | ---: |
| narration-overview | 53.51 | 14.84 | 18.28 | 5592 |
| character-voice-bindings | 56.91 | 20.12 | 31.16 | 2247 |
| voice-profiles（含library） | 17.50 | 14.89 | 15.82 | 17467 |

样本不支持把页面慢归因于数据库；已确认的重复刷新、请求生命周期与重挂载应分别验证。隔离两人物与正式六人物不是同输入，不能直接比较延迟并宣称优化百分比。正式授权仍未收到，正式通用包0/24与真实Agent验收、主观听检、最终发布恢复均未完成。

## 5. 真实合成、调音、空闲和隔离恢复（2026-09-03 19:30）

- 试听500修复后的公开GET Preview为200/ready；同一音频GET/HEAD Range为206，Content-Length=16，GET以RIFF开头，HEAD空body。最初手工探针误用`X-Narration-Preview-Id`被422拒绝，改用冻结的`X-Narration-Voice-Preview-Id`才成功，证明未提供正确scope不能裸读媒体。
- 真实候选页面点击`CN 京味胡同闲聊`试听，显示“试听已开始”，无浏览器console error/warn；试听后绑定仍为Junhao，没有偷换当前声音。
- Junhao→Zhiming及反向切换，高级底音名称同步，seed `987654321`草稿保持；固定标题y=0。D 28项定向测试通过，已交回并接入入口refreshVersion。
- Junhao高级参数采用默认采样值、seed=987654321；命令`28cf1091-4c5c-5742-b34a-51a855f31cf5`于11:21:30 UTC成为ready_applied。参数digest `785167930378e2b15bb7ec6abe155bc780918393363e6a111979575dedb44fb7`，fingerprint `ec0826540caf2332bf5c97c6838b03afe82c81fa50a513f99b61a308d16240bc`；3040ms音频hash `07849e96b53eb3c82660a95ae4152b207586c99cac79779efa52410be4f676f2`。页面无需第二次点击即更新当前音色。
- “恢复官方音色”一次点击成功；不可变历史实验仍存在，但页面不再把它声明成当前已应用。seed草稿保留。
- Zhiming自定义seed=987654322、text temperature=1.1、audio temperature=0.9、audio top-k=20，其余默认；命令`b4389026-1478-5101-a77a-23a104ff29f5`于11:22:24.149638 UTC成为ready_applied。参数digest `5758ccbd05553bb8f3e066d9e9fb4bf7cc7fb4a6a5a4b6c0f067611e24e3d614`，fingerprint `a3ce743051e6b2664870e78eabbfcbd451d886909c0fee4542cfdb42408284ce`；2320ms音频hash `4ef618fc3ef2a8fdafe7252e3d4c954de7d1431debc8090c97bf387493bce11c`。与第一条不串缓存。
- 四个真实Nano ModelRun均success，requested=actual=`OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX+MOSS-Audio-Tokenizer-Nano-ONNX`，revision=`f52645cb467506d8e18e746ddd59482685b74e58+ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae`，模型fingerprint=`3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d`。未更换模型/静默默认重试。
- 11:21:37、11:23:32、11:24:34、11:26:26 UTC读取model_loaded=true；11:27:33.749 UTC为false、worker_generation=null。末次完成后309.6秒，符合300秒+60秒观察容差。容器统计由1.582GiB/36 PID降到25.72MiB/3 PID；不把常驻容器内存说成零。此观察在重新安装候选前完成，非重启卸载假象。VG host只读verify ready，本轮未启动VG模型。
- Escape后抽屉保留DOM但hidden/inert/aria-hidden、display:none，焦点回到原“更换”；保留DOM为保存任务实例，不是关闭失败。折叠后Tab顺序为关闭→立即智能匹配→官方列表summary→私人summary→关闭，未进入隐藏输入。IME保护有自动化负向覆盖，未冒充真实输入法听检。
- 缺有效AI模型时单人物匹配明确显示“AI小说作家当前没有可用的有效模型”和重试按钮；当前高级音色不变。此项仅为失败保留验证，**真实官方智能匹配成功仍未完成**。
- 后续UI补验发现私人选择器将被过滤的官方音色标为不可用、将Nano实验误要求VoiceGenerator能力，名单还把高级调音标为专属音色。主代理在原组件修复来源分类/能力映射及精简文案；未移除权利、来源、机器验证、锁定或CAS校验。最终候选需安装后再看这几处。

### 5.1 可恢复材料（仅隔离环境，不替代正式发布备份）

目录仍为仓库外0700私有目录`/Users/liujia/Documents/AI小说世界2026-backups/plan56-EUdaURFG`，新增文件均0600：

- `tts56-browser-20260903.dump` SHA256=`ae1a203b560cd059fe303d8b503efde94369c8f3b786774a91d6eef5a4d4aa16`。
- `tts56-browser-media-20260903.tar.gz` SHA256=`888825853ecfba3b33276530e72315c32b0db7af8ceb04987fcdf91a24a7bbc8`。
- `tts56-isolated-hmac-keyring.json`为本轮新建的项目专用HMAC keyring，受限备份供恢复；未输出内容，未复制正式Provider、Sidecar或VG令牌，也未读取宿主私有配置。
- dump通过`pg_restore --exit-on-error --single-transaction`还原到同一隔离PG的独立`ai_novel_world_2026_tts56_restore_test`；head0040，1小说/2人物/4Preview/4ModelRun/2Nano实验。逐一从归档流式校验4份ready媒体的路径、SHA256和字节数，全部一致，独立keyring可按权限规则加载。
- 源浏览器数据库和媒体仍保留，没有用备份覆盖源，也没有触碰正式库。后续若新增实质音色/命令须另存新检查点，不覆盖此包。

## 6. 当前检查点与下一步（2026-09-03 19:36）

- 最终源码候选：backend全量3848 passed / 203 skipped / 3 warnings；隔离PG明确155 passed / 0 skipped；frontend 142文件1238 passed；typecheck/build/package、136项manifest/Skill/宿主契约、Compose和diff-check通过。跳过项不计通过，主体播放驱动/模型/迁移未修改。
- 最终bundle SHA256=`a9546444c93a48f434300e26369f4e243ca96b670008498407d553887ec17323`，隔离18192公开文件接口返回字节hash完全一致。最终可恢复包`tts56-candidate-20260903-v2.tar.gz` SHA256=`9d607fa7c56f592df5b473f21dd321c3af1b13293d69b9d2d6f024d248897c0d`；早先未含最后文案的包保留为历史检查点，不冒充最终包。
- 最终候选两桌面截图：`TTS56-final-candidate-1920.jpg`、`TTS56-final-candidate-2560.jpg`。1080P实际1901×1069：内容高3075、容器高984、scrollTop2090.59；2K实际2534×1426：内容高3075、容器高1341、scrollTop1734.16。均滚至底、外层scrollTop0、标题y0、无横向溢出，console error/warn为空。左上/左下宿主区域没有穿透遮罩。
- Nano调音在VG未连接情况下出现在私人选择器中，名单与选项标为“高级调音”，不冒充描述生成的新声线；官方音色只因私人过滤而未列出时不再显示虚假不可用。所有保存仍经现有CAS和后端资格检查。
- 正式18088仍ready，Nano未加载，通用包仍missing。没有正式安装、迁移、建包、正文/人物绑定写入、媒体删除、Git暂存/提交/push。

| 检查项 | 当前可宣称的证据／尚缺 |
| --- | --- |
| 01默认旁白 | 当前普通建书Junhao实测；创建/向导/作者改选不回正的自动化通过，未改相关领域规则 |
| 02官方目录 | 既有18项证据保留；本轮修复并真实通过受影响的官方试听HTTP/媒体/浏览器链；未声称重新合成18项 |
| 03官方智能匹配 | 无有效模型时失败保留已验；真实Agent成功补验等待隔离模型配置 |
| 04人物专属 | 复用55实际六人物生成记录；新专属媒体授权的严格PG/文件流验证通过；当前正式媒体/UI仍需发布后只读核对，作者专属听检未完成 |
| 05通用包 | 恢复/重生成/seed/并发PG通过；正式0/24，等待正式操作授权，不伪导入旧WAV |
| 06章节链 | 保留55真实16段及历史Edition证据；本轮准备轮询缺陷测试通过；受影响真实Agent章节补验未完成 |
| 07高级/删除 | 两底音真实高级创建应用/恢复/参数hash通过；删除生命周期未修改，保留其独立安全恢复测试证据 |
| 08播放听感 | 播放后端未改；计划45客观探针不等于作者倍速听检，当前仍HOLD_AUTHOR_LISTENING |
| 09桌面UI | 当前受影响抽屉/官方列表/调音在1080P/2K实测通过；其他入口依赖共享组件与已有证据，整章联合验收仍待模型条件 |
| 10性能/刷新 | 删除重复overview请求；pending/切scope/同state/错误恢复测试与真实切音色保草稿通过；正式六次只读基线如4.3，不夸大冷启动或优化比例 |
| 11发布恢复 | 隔离候选、DB还原和4媒体校验通过；正式备份/发布/24槽新包恢复尚未执行 |
| 12资源证据 | 本轮Nano空闲300秒+容差通过，VG只读host ready；旧批准音频与本轮真实音频已保全；本轮未删历史资源 |

### 下一次恢复顺序与外部条件

1. 先读本日志，确认main工作区仍为本轮候选、18192/58857隔离资源及上述hash；不从头重建样本或重复合成。
2. 隔离AI小说作家缺有效Provider/模型，需要作者在隔离宿主公开设置中配置与当前选定写作模型一致的可用连接。不得读取/复制正式Provider密钥、修改宿主私有配置或伪造模型响应来通过。
3. 正式备份、按需部署重启、正式24槽建包的合并授权已询问但未收到。取得明确授权才进入正式步骤；仍不包含真实小说写入、删除、Git。
4. 配置与授权就绪后，补真实官方匹配/章节受影响链、正式启用与恢复，再集中提供专属/倍速待听检内容。旧已批准六条仅在音频hash一致时复用听检，不重复请作者确认同一文件。
5. 三个`ai-novel-tts56-*`隔离容器暂保留供恢复，模型已卸载；两独立卷/隔离网络有归属标签，不设置自动重跑或清理正式资源。本轮结束验收后按第10节列精确目标清理。PG tmpfs不可直接停后当作仍有数据，必须从已验dump还原。

目标仍active，未作TTS56-FINAL裁决；当前需要的是模型配置、正式操作授权与后续作者听检，不是新一轮增加功能的计划。

## 7. 原生单选键盘与人物卡入口补验（2026-09-03 19:51）

- 继续核销计划44键盘缺口时发现：隔离方若岚官方列表选中Junhao后按ArrowDown能绑定Zhiming，但焦点变成BODY，第二次方向键不能继续选择。根因是`official-voice-selection-panel.ts`在每次projection/settings刷新时先设置loading，将已聚焦radio从DOM移除。这是本次真实发现，不将第6节抽屉滚动通过扩大为所有键盘行为通过。
- 最小修复：同scope重取保留ready列表；切换小说/目标时同步隐藏旧数据；旧scope响应和回调无效；成功绑定receipt取消在途旧读取，较低settings/binding版本不得回退最新CAS。读取失败复用唯一“刷新当前设置”恢复入口，不新增绑定动作、缓存层或协议。effect测试harness补齐依赖与cleanup语义，覆盖pending、旧响应、旧projection、跨scope和失败刷新。
- 隔离18192安装后，方若岚从Zhiming连续ArrowDown至Weiguo、Xiaoyu，两次均自动绑定并保持INPUT焦点，aria-label分别为“当前使用…CN 说书／CN 明星”；中间没有重新鼠标点击。沈砚高级音色未改，正式小说未写入。
- 人物卡入口1080P补验：打开方若岚→声音→展开官方与私人区→滚到底；body高795/内容高3010，最终scrollTop2214.36，选项卡y120.67保持不变。可切回基础资料、当前线设定、状态与经历；Escape关闭。该入口指针打开后按既有modality规则关闭时blur，未把BODY焦点另误判成官方radio丢失问题。
- `TTS56-character-card-1920.jpg`记录滚动动画中的瞬时空白帧，不能作稳定成功截图；`TTS56-character-card-1920-stable.jpg`为动画完成后的稳定底部内容与可见四栏目。保留前者为原始证据，不篡改成成功图。此次额外人物卡入口检查仅1080P；已有2K共享抽屉几何证据仍可复用，没有声称新跑了2K人物卡。
- 前端全量142文件 **1242 passed**；定向24 passed；typecheck/build/package/diff-check通过。此次只改前端局部状态/测试，后端未再改，沿用第6节backend3848与PG155结果。无浏览器console error/warn。
- 当前bundle SHA256=`c811047d7de0107b438e415e6432234e58000ebc21090b510b83842c3b5b9a7e`，隔离公开文件接口hash相同。v3备份包`tts56-candidate-20260903-v3.tar.gz` SHA256=`b233496861084050cc3bdf25730c031efd57dfacd6fe04fc58af77e1d6602125`，仍在第5.1私有目录、权限0600。
- 方若岚新增的官方绑定/审计检查点保存为`tts56-browser-20260903-v3.dump`，SHA256=`2dc0c2d131f779883144b44a27de2e856ecd3ccf6eb652b0e15515edb4fd2be4`，权限0600；媒体和模型记录未新增，沿用前述4份媒体归档/keyring。v3为新dump检查点，本轮没有重复执行完整pg_restore，不冒称v3已单独恢复演练。
- 第6节外部条件不变：隔离Agent没有有效模型，正式备份/部署/建包尚未收到授权，作者专属/倍速听检尚未完成。目标不标完成；不为等待而下载模型、搬运正式密钥、替换正式容器或提交Git。

## 8. 外部阻塞审计与恢复点（2026-09-03 19:52）

- 上一目标轮为progress：修复真实radio焦点缺陷、补4个测试、前端1242通过及人物卡入口浏览器证据；本轮为外部阻塞复核，不把重复状态读取或写此日志算新增功能进展。
- 当前main仍`0a686c2`，工作区候选和bundle仍为第7节身份，diff-check通过。三个精确`ai-novel-tts56-*`隔离容器均运行，保留可恢复现场；未重启正式容器、未清理卷、未新建模型作业。
- 11:51:47 UTC公开GET `/generation-model`（18192）返回503、`generation_model_unavailable`、AI小说作家没有可用有效模型。正式18088与隔离18192的公开GET `/voice-library/generic-pack`均missing、0/24、command=null；不存在可通过等待完成的本轮建包命令。一次误带`/narration`的GET为404，随后按源码router已纠正路径；不以404判断真实包状态。
- 自动目标续轮没有新增正式操作授权或作者听检回复。连续三轮均遇到同一组外部条件；前两轮已继续完成独立修复与补验，当前继续实质端到端/正式启用需要用户输入，故按目标规则转为**blocked**，不标complete。
- 恢复所需：①授权正式备份、按需部署重启与24槽建包（仍不含真实正文/人物绑定写入、媒体删除或Git）；②在隔离宿主公开模型设置中为AI小说作家配置可用的当前写作模型连接；③音频准备齐后由作者集中听检。不得把自动续轮视为上述授权。
- 恢复时先核对第7节包/数据库检查点，再进入真实Agent成功链和正式启用；已有声音、模型、schema、测试证据按依赖复用。保持原十二项终点，不缩减为源码通过。

## 9. 正式环境授权与发布（2026-09-03 20:13起）

- 用户在收到备份/部署/专门验收作品/24槽包/听检的具体说明后，再次明确“授权里直接使用正常的环境去测试”。计划更新V1.2，正常功能验收切换18088，取消隔离模型配置前置；负向故障测试复用已有证据。旧3小说/13文档/20音色档案不改，只为本轮新建作品写入正常人物/章节/绑定与Edition；ID创建后立即登记。Git、真实删除、故障注入、降schema和模型下载未授权。
- 发布前head0040；background_jobs全部终态（662 succeeded、33 failed、1 cancelled），官方cast/VG命令无活动项。QwenPaw容器ID仍85d0cb14…a7f82，image仍ea2c0858…15b1；固定模型未改。20:15停止QwenPaw后制作一致性备份，没有迁移。
- 备份目录`/Users/liujia/Documents/AI小说世界2026-backups/plan56-live-before-qMI5lU`，目录0700、文件0600；自定义dump目录1551项可读，6份tar均可完整列目录，未读取/输出宿主私有配置内容，仅作不透明卷备份。

| 备份文件 | 字节 | SHA256 |
| --- | ---: | --- |
| database.dump | 24974939 | 2e21a1735d090a6aa46d69e381f21da12b2369ba7adb235b8425321cf975f4d4 |
| old-plugin.tar.gz | 4923539 | 1f5b44ea9728fc00fc6b5fbd0c00a1af09a920b640bd1f7fbf56263ee5d37ded |
| candidate.tar.gz | 2332381 | 9337bdebad07b4dda055d20be94139f7cb4c3e6163f7bc7eae5b0fd11901f14e |
| qwenpaw-data.tar.gz | 165171073 | 5f5d5743aa0d564a4323260c7b71d90fd9555e8c673a27da889fede5ae366456 |
| qwenpaw-secrets.tar.gz | 7420392 | 256ad8e005066348a301759a5d0ac28194a14f988f8461f8f75c98c197864fe0 |
| qwenpaw-backups.tar.gz | 84432618 | 05b8ec83d0985e8743a506ee6128a93d74de2c6a4848f357aaffbfe0e17dce04 |
| novel-media.tar.gz | 365322645 | 6d0d3c362269bb805b7c867ebbadc04382d2dfbdf3b270e3e0739cc1255f0a3d |
| media.SHA256SUMS | 365840 | b3a41809ac1f611dbe2100c8ea6e70c614e7fe754db53ff6f205847033e392e5 |

- 候选tree=`323af3428ca6e3e62832b96d29252bc0204b8b04f3826cbdfe23c12a403bc0d6`，bundle仍c811047d…5b9a7e；使用已有offline-install-stopped窄命令绑定绝对候选路径、tree、0040、正式容器与镜像ID。已提交Git基线仍0a686c2，工作区修复候选未提交。
- 20:17公开安装成功并启动同一正式容器；health ready，数据库 connected，Nano technical/production ready且model_loaded=false，VG/智能选角/高级调音/删除能力enabled；automatic_generic_casting精确显示GENERIC_VOICE_PACK_NOT_READY。正式公开bundle hash与候选c811047d…5b9a7e完全一致，写作Agent仍minimax-cn/MiniMax-M3，没有改Provider。
- 20:17:51通过公开POST启动正式通用包；Idempotency-Key=`tts56-live-generic-pack-v1`，command/pack ID=`8273efba-0c35-5c36-b7f1-cd3b29fd11d9`，初态building、0/24、female_child_bright。之后必须查询此ID，不重复创建包。
- 本轮唯一新增验收作品为《雨港来信》，novel白名单=`af44b1e0-9a3d-459a-b915-a848c5ef8fc1`，初始章document白名单=`cbdcf117-5df8-4bdd-98bf-36ad80644793`。仅这一新作品允许本轮人物/正文/绑定/Edition正常写入；不操作既有3书。标题正文不写测试占位，日志明确其验收用途。

### 9.1 正常写作模型与运行恢复（20:33检查点）

- 人物白名单：主角程砚`d99a37f5-2e4d-4ce3-8776-705c129fefc8`、许澄`2c898886-738c-460d-be46-6a06e1fea357`；配角韩启`cb1f875b-c171-4984-bade-40c44bab53cf`、周姨`cfd73f42-ef21-46e5-aaeb-d272b1b3fcc5`、何小川`37d197cc-2f0c-4c02-937b-4a3afb1fd21d`、梁峥`6dcb8c6b-61b5-4495-8e30-6cbb2ea79152`。保存的描述有中文及声音维度，不从姓名猜测。
- 首次整书命令`59351112-b791-4b36-921c-d66bfabb9b87`，真实MiniMax-M3完成4人、保留旁白，周姨/梁峥因`CHARACTER_VOICE_BRIEF_INVALID`被阻止；不是全部一次通过。再次点击产生`7d5a4be2-a389-4933-8305-326bd462cc73`，保留5目标并补齐2人。旁白Junhao，程砚Weiguo、许澄Xiaoyu、韩启/周姨Yuewen、何小川Zhiming、梁峥Lingyu；中文6preset对7目标仅耗尽后复用，最终0待配置。旧成功项未重做。单程砚“立即智能匹配”也成功应用Weiguo，保留真实请求与服务端审计。
- 发现提示把`CHARACTER_CAST_OFFICIAL_POOL_REUSED`写作“1项需手动处理”，源码已按blocked目标计数修复；成功提示`Weiguo`改用既有目录名称解析。尚未把此新候选冒称已经发布。
- 正式包前两槽实际完成：female_child_bright命令`a32f9006-f572-43a9-99ca-0fbf9384ff47`，female_teen_gentle命令`b681a051-ffb8-4537-861f-89bd9ff09f4a`。第三槽命令`d50cfa51-309c-421d-af1e-6ab96f78cea3`在20:26:32因一次host进度GET超时被业务job标`HOST_UNREACHABLE`；native实际20:30:04正常完成，音频SHA256=`cbe859b977480d9830760a6594f8cbc20c6f227a67e335bad3afd8d4263da00f`，937004字节，没有进入Nano验证，不能当作已可用第三槽。
- native第三槽无进程重叠、回收成功，最低可用960446464字节、最大swap增量5265298555字节；不新增4GiB门禁。20:32health active_request_id=null，确认安全交接。修复仅对同request进度查询最多重试2次并保留心跳/取消/fence，不无限重发或放行证据错误。旧failed包不可变，后续走已有公开retry创建继任包并复用前两槽，原第三条native原始结果保留，不伪导入。
- 新章《雨夜的来信》已通过公开CAS保存和checkpoint，463非空字符，draft_version=3，revision=`e28b85e9-9f58-4f7c-815f-ce17c4d58e05`，SHA256=`fe71a3078bd05abf886f7a77a7f1efe0b3ca5b58c55a3042cfe45fc8bd44582a`。正文仅程砚/许澄有直接台词，另有无卡男童/青年女性，可验证章节只等必需人物和通用槽；其他四人仅被叙述提及，按计划55可后台继续准备，但不应阻塞本章续接。
- 正式1080P与2K抽屉滚至底实测：实际1901×1069/2534×1426，body分别984/1341高、内容3180、scrollTop2195.54/1839.11，外层scrollTop和顶部均0、无横溢出；两截图`TTS56-live-drawer-1920.jpg`/`TTS56-live-drawer-2560.jpg`，console error/warn空。截图仍是c811候选，含待修提示原貌。
- 本次窄修复全量backend3853 passed/203 skipped/3 warnings，frontend142文件1244 passed；typecheck通过。底层schema/媒体验证/PG事务未变，沿用此前明确测试库155 passed，不在正式库跑pytest。

### 9.2 恢复修复发布与继任建包（20:36）

- 全部formal业务job终态且native active=null后，20:34停止同一QwenPaw，追加一致性备份，不覆盖上一份：`database-before-recovery-fix.dump` SHA256=`82298613cb25ad82c16cf6f0c061fffc52cd484b6159f8a86f1fbd185f00c49f`，`media-before-recovery-fix.tar.gz`=`a5a290eef25397c21b86ccea2340c1cb9ba447db5f758a6ddfc76488ac2a15bd`，`candidate-recovery-fix.tar.gz`=`de24e1ead9de154ab5a775bb7bb6291585a71f4a48afbac3f32a82733e4ae2da`，均在第9节0700目录、文件0600。
- 新候选tree=`589b7a63ad4a13b74822488e3fc8dd97fd0f84951cc65e9ba58fff0451587045`，bundle=`db467179ac67e9ab1da4ab3006b31c5254ab022137ea6e6e906ea6be76df7c68`；同一offline-install-stopped入口和固定container/image/head门禁安装成功，启动后health ready，公开bundle一致。136项宿主/manifest/Skill契约、build/package/Compose/diff-check通过；没有迁移或Git操作。
- 20:36对旧failed pack公开retry，返回继任command/pack=`2ea94b23-ac69-545c-bd15-31beca8ddaef`，从2/24续建female_young_gentle；前两槽精确复用Version `f3211f64-ec9c-5cda-9d01-0b89575b6464`/`3d11588a-ccf1-5093-82b1-84c7b261a2a6`，原failed包/未验证native音频保留。技术重试保留seed，不做作者拒绝重生成。
- 已只读确认隔离browser库无queued/running/cancel_requested job，停止`ai-novel-tts56-qwenpaw`和`ai-novel-tts56-sidecar`减少空转内存；没有删除容器/卷，tmpfs PostgreSQL保持运行并保留既有dump，不拿正式环境做故障测试。后续正常流程仅18088。

### 9.3 跨入口并发预约问题（20:43，修复候选未部署）

- 单程砚专属命令`a398b8c3-b8dc-45ee-8b4f-e306237ef135`已由人物抽屉一次点击创建，waiting_for_heavy_runtime后按调度器优先于下一通用槽进入generating_voice。等待期间未提交seed=568888、scrollTop603.47、展开状态保持，轮询没有整页刷新。继任包已完成3/24，新第三条native与旧失败请求具有同一音频hash，但新请求通过正常Nano和证据落库后才计可用。
- 在此独立人物命令未完成时点击新章“智能朗读”，父命令`d18346d4-90cc-4af7-82a9-0d7bdc4f90b5`接受并完成preflight：request=`ce7361de-c4c6-4f19-b376-aa26ec48c47e`，script=`9469bdf9-8fa4-59bf-983a-33f83121a4d6`，chapter_speaker两人、background_remaining4。但为程砚第二次预约遇到已有活动命令，留下queued且child ID=null；对账器又因其他pending项跳过它，导致0/6无限等待。没有产生朗读Request或覆盖人物声音。
- C0窄修复候选：领域预约遇业务冲突进入明确failed/superseded并释放父活动槽，不窃取/取消独立人物命令、不刷新作者CAS；对账器恢复无child ID的queued项，即使还有其他pending人物。真实SQL/进程丢响应仍沿用原幂等预约；协议/schema不变。新增三项定向回归通过，主代理等待安全发布点后才安装，不在现有模型作业中替换容器。
- 真实Agent证据是model-execution-evidence/2的pre/post effective均minimax-cn/MiniMax-M3，reported_actual=null、usage not_exposed；证明使用公开Agent并检查前后一致，不伪称上游报告了actual模型或token数。

### 9.4 长参考音频接入与并发修复发布（21:02）

- 程砚native请求`083f9fcc-0b82-4d39-8966-376a9c8ad888`在20:45正常完成，2442284字节/610560帧/12.72秒，SHA256=`4d3ab8ca0fa7eb13ea7d13f2fa388d59ee8a6c995a86fd47392fb4dede1cac43`，seed104729。业务命令因`SYNTHESIS_ERROR_IDENTITY_MISMATCH`进入failed_nano_validation，原官方绑定未改。
- 用原完整WAV只读执行两端解析：VG19.2秒上界接受，Sidecar12.5秒上界明确`REFERENCE_DURATION_INVALID`；HTTP仅在完整解析成功后设置request ID，故普通拒绝被适配器视作身份错误。不是模型OOM，不是seed溢出，也不是实际模型哈希漂移。固定官方ONNX源码encode_reference_audio按实际waveform_length编码，无12.5秒常量。
- C0修复Sidecar参考上界为19.2秒（与VG240×80ms一致），保持完整音频、hash、字节、格式与模型边界；上传规范化仍12秒。合法JSON字段/UUID后发生的拒绝保留request ID，非法包不伪造身份。测试12.72秒/19.2秒接受、19.2秒+1帧/尾随字节拒绝且不重启健康worker通过。并发准备修复增加2项真实PG活动唯一槽释放回归，明确58857测试库3 passed；全量backend3860 passed/205 skipped/3 warnings。前端未再修改，复用1244及typecheck/build结果。
- 20:57公开cancel继任pack`2ea94b23-ac69-545c-bd15-31beca8ddaef`，保留5/24；等待所有job终态和native active_request_id=null。新章卡住父命令通过公开cancel退出，未删除记录或媒体，未取消/改写其他书。此次是正常暂停部署，不做故障注入。
- 构建时固定Dockerfile frontend下载无进展，已中止；不下载模型。离线从精确旧镜像`sha256:9af6a3224be51267f7e59687387a8d4585cf79c4fed6aed5e0986217fdbce632`复用已验证依赖，只机械提取仓库Dockerfile的production-runtime阶段，将其FROM替换成该不可变镜像，通过legacy builder/network none执行同一COPY和5源码hash校验。未增加临时Dockerfile/新依赖或改上游。新镜像=`sha256:7fd898aa6fba4a13ce4c1fece2c496a8e4e6fd75607523bb9bbe5858cb5a813a`；旧镜像另保留tag`tts56-before-reference-bound`，生产默认tag更新到新镜像。
- 正式无活动业务job后停止同一QwenPaw，追加一致性备份至第9节目录：`database-before-reference-fix.dump` SHA256=`400758956ad885d9aa898c44e3cd2651544867642fd1d203716082c2bc60fa29`（TOC1561项）；`media-reference-fix-from-stopped-pawapp.tar.gz`=`bf27100fe521e2be1a93751ff0b08b3216f20aa93f924f94d55530ea3ee0c912`（4043项，以novel-media为根）；`candidate-reference-fix.tar.gz`=`8ccf986a6a29827b9b9bc684e55b52176f7b9cb870ffc42b99baa4ef4fb078ae`。权限0600，前述旧备份不覆盖。临时tar助手启动等待后实际完成的`media-before-reference-fix.tar.gz`也保留，不以它替代本次已核验的主要媒体归档。
- 候选tree=`2794e02172d90ab503247bbeae7dcbf577f9029e4075622c081317d57ff9c85e`，bundle仍db467179…df7c68，head0040不迁移。公开offline-install-stopped成功；Compose仅重建本项目Sidecar，container=`d5cb3047b41ddfdabf5b14813095878b86e58d3b50e024a932542abb4e5bd577`，随后启动原85d0…QwenPaw。真实长音频重试及继续建包尚待下一检查点，不因部署成功宣布全链通过。

### 9.5 新候选正常任务续跑检查点（21:07）

- 正式health ready/database connected/Nano ready，model_loaded=false，原固定fingerprint不变；公开bundle与db467179…df7c68相同。没有新增迁移或改模型/Provider。完整dump已由pg_restore解码到/dev/null，无损通过；不是实际还原演练，最终24槽备份还原仍待完成。
- 通过旧程砚任务公开retry创建`d4e25c9f-14a4-499b-9087-f71c8287523a`，host request=`8f03249d-bc9d-43fa-ba43-119130f12797`；保存的instruction HMAC与旧命令一致、seed仍104729。实际进度generating_voice，原binding=1/Weiguo不变。浏览器重新进入正式人物配音并打开程砚抽屉，找回同一任务，50%/取消入口/原声音均正确，无console warn/error；未额外点击重新生成。
- 正式通用包公开retry创建第二继任`9be0bac0-bb41-5a94-967b-d77f0e87da66`，复用5/24，从female_middle_warm继续。人物priority80优先于通用包60，同一时刻一个重模型；后续按此ID查询，不再次建包。
- 当前4小说/14文档，新增仅第9节白名单作品/章；现有3书未写入。停止的孤立准备命令和两份旧包保留，不删除失败证据或用户媒体。
- 另一个媒体归档`media-before-reference-fix.tar.gz`实际已完成：371599882字节、SHA256=`17752bc293a42c515cf1eedcc5f89d6de83bee05834bdcf8655455636f8353b4`，保留作原始备份，不与根目录结构不同的主要归档混用。
- get_goal确认本轮授权后原执行目标已恢复active；不新建替代目标，不标最终完成。下一顺序：程砚真实Nano通过/自动绑定/试听→本章新智能朗读保留该声音、准备剩余人物并自动续接→24槽active后补匿名通用链→完整备份还原/集中作者听检/资源核验。

### 9.6 Nano后续验证仍失败（21:10，未最终通过）

- 新程砚native于21:07:43完成，原始音频仍精确`4d3ab8ca…cac43`/2442284字节/12.72秒，排除重新生成成另一条短音频而假通过。无模型进程重叠、回收成功，最低可用1171374080字节；不以低于4GiB判失败。
- 新业务命令`d4e25c9f-14a4-499b-9087-f71c8287523a`随后仍进入failed_nano_validation，但失败码变成`VOICE_GENERATOR_VALIDATION_FAILED`，不再是Sidecar参考时长导致的身份错误；VoiceProfile/Version仍null，原官方绑定未改变。**尚不能宣布专属链通过。**
- 当前处理器`process()`的通用异常分支只存阶段笼统码，没保留具体验证原因；原始Nano输出没有在失败前持久化。静态定位候选包括`process_synthesis_wav`的短中文时长/静音/削波检查或其他未分类异常，但没有足够证据作确定判断，不调低质量/身份门槛、不自动换参数重试。
- 下一窄修复优先补文本无关的精确诊断：`worker.py`已有`_failure_evidence`白名单reason映射，应复用/提炼到`audio_pipeline.py`，避免复制第二份原因表；processor记录稳定原因、不输出小说文本或原始异常。该方案尚未改源码；实施先追加C0文件所有权/测试，等待当前通用模型job安全终态再发布，禁止在活动推理时替换容器或绕过持久job直接调用重模型。
- 当前正式包仍`9be0bac0-bb41-5a94-967b-d77f0e87da66`、building5/24、female_middle_warm；不用另一ID重开。新章没有Edition，取消父命令仍保留，暂不再创建重复人物准备请求。浏览器临时2K设置已reset，当前人物抽屉可查看失败与原声音。目标active，正常功能测试在正式18088继续；不标blocked/complete，不提交Git。

### 9.7 诊断发布、7槽检查点及备份还原（21:18–21:29）

- 已完成8.4共享音频错误白名单提取，worker原契约不变；VG细化Nano音频、存储与数据库发布失败码，没有更改质量/模型/seed。processor/audio/worker定向119 passed，全量3864 passed/205 skipped/3 warnings，打包/Compose/diff-check通过。新增测试最初4项fixture使用错误hash，修正后才得到上述通过结果；不把修正前失败算产品通过。
- 等第7槽female_middle_authoritative完成后，21:17公开cancel包`9be0bac0-bb41-5a94-967b-d77f0e87da66`，保留7个已验证Version；当前包superseded/命令cancelled，**暂未创建下一继任包**。所有正式业务job终态、native空闲后停止QwenPaw，继续复用同一容器/Sidecar镜像，没有新建正常验收容器。
- 第9节私有备份目录新增：`database-before-diagnostics.dump` SHA256=`f6354bd2ad2151d221a0665a42321d249f67f20b40a7f9be212e7d23c2c11a0a`；`media-before-diagnostics.tar.gz`=`9d3c1fa16b4699526ec9335a3a4641300f5dfebd22485a2132f437aed4bd66fb`（4053归档项）；`candidate-diagnostics.tar.gz`=`d769c99e94cd4d4d7485e217cb07c0b8987c7cb00d3111413ef7e1255293ac56`。文件0600，旧检查点均保留。
- 21:18公开安装候选tree=`37f07164a03db095bb06bf06dddba089ae20acfb01cd9e6767ee9e78d4754bc0`，bundle仍db467179…df7c68/head0040/Sidecar7fd898…13a。health ready，未改模型、上游、schema或Git。
- 在已有58857备份验证PostgreSQL新建精确副本库`ai_novel_world_2026_tts56_formal_restore_test`，使用`pg_restore --no-owner --no-privileges --exit-on-error --single-transaction`成功还原上述dump：head0040、4书14章，包历史2/5/7槽完整。未覆盖正式库或旧备份验证库。流式检查媒体归档与副本库每项ready/local资产，**1265/1265大小及SHA256一致**，无漏项。只证明7槽检查点可恢复，不替代最终24槽备份。
- 21:19程砚公开retry命令`2ac47843-c5f1-4c9f-a408-0992a908c520`、native`c9ed0370-9a04-4c40-997b-23f44dc49f33`。native21:23:50完成，仍同12.72秒/2442284字节/hash4d3ab8…cac43；无重模型重叠，恢复成功。业务却停generating，attempt`77881175-ab00-48eb-b9b5-50d4b5d9bed1`最后heartbeat21:19:15、lease_until21:21:15。
- PostgreSQL从21:21:19重复明确`invalid VoiceGenerator command state transition`；日志栈定位scheduler.maintain_once→terminalize_job_in_session。现实现把任何过期命令设failed_storage，但0035不允许generating→failed_storage，导致事务整体回滚，活动槽不释放。**已确定恢复缺陷，心跳最初中止原因仍未确定；本次没有进入Nano，不据此推断Nano失败原因。**
- 21:28:58经公开cancel结束这一精确命令，原binding=1/官方Weiguo不变，无新Version/Edition、无媒体删除。源码按既有阶段图修正终态投影，并把生成完成→unloading移到参考文件存储前，避免存储失败同类非法转换；补真实PG各阶段过期/取消与唯一槽回归，尚待本检查点之后测试/发布。未重试第四次生成，正式包继续保留7槽暂停。

### 9.8 过期状态修复发布、继续建包（21:34–21:35）

- 明确58857测试库的VG PostgreSQL/processor共29项通过（包括新增8项四阶段过期/取消恢复）；真实数据库时钟与原trigger完整启用，SET CONSTRAINTS ALL IMMEDIATE闭环成功并能再次正常预约。首次未提供测试密码仅连接失败，修正为内部读取已有测试连接后运行，未触及正式库。全量pytest再次退出0，8个PG新用例在未设置URL全量运行中跳过，专项已实际执行；Compose/package/diff-check通过。前端无新改动，沿用1244通过及双桌面证据。
- 发布前native ready/active=null、全部job终态；停止同一正式QwenPaw，备份`database-before-terminal-recovery.dump` SHA256=`9293d8f4cf09e2f69f2dab07f03657dfa9416bb02689e5b82b48f58162ff7a6d`，候选`candidate-terminal-recovery.tar.gz`=`1a444703daee4e380697a123263e9dea593ecf35ff18d736c161522beab4d35f`。新任务停于生成阶段，没有新ready媒体，1265份仍沿用已还原验证的21:17媒体备份；旧备份全部保留，文件0600。
- 21:34公开offline-install-stopped安装tree=`897e7b7a44dca4a3cbb19fe431baacbe99e5f953167d52a5cc73a7d6a4e5ec8d`，启动后health ready/Nano ready且未加载。bundle仍db467179…df7c68，head0040，Sidecar7fd898…13a；未迁移/改宿主/提交Git。
- 公开retry原7槽包产生继任`25f14f48-6400-5788-b785-ab7ebb1122e0`，从7/24复用继续female_elderly_kind。之后仅按此ID找回，不再从零建包。
- 第二主角许澄首次单人物命令`3e8faa92-c533-494b-aa43-92b2ab4274c7`因CHARACTER_VOICE_ANALYSIS_INVALID终态，未运行VG/未改绑定；正常retry产生`bdc03927-d3df-4b46-816b-b60d4e0958eb`，已获得合法人物简报并进入waiting_for_heavy_runtime，job=`5359ef94-87b1-4c3a-8e11-59d7cbd4c2e9`，原binding1保留。这是另一必验主角，不是对程砚无限换seed重试。
- 当前一条通用VG运行、一条人物任务排队，按共享调度器串行；暂无章节Edition。后续先看许澄精确Nano结果，再处理程砚、章节自动续接、24槽激活与最终听检/备份；目标继续active，不把发布成功或七槽当最终完成。

### 9.9 主动卸载竞态复现与补丁发布（21:39–21:54）

- 第8槽female_elderly_kind完成并保留；native `71c847ec-5da3-46ef-a0cf-c03b3b20a05a` 输出SHA256=`ec8cc420284bcdc0ceab1f1f152d0ba9520587928a2fc0e647cd5a40af8c0921`，814124字节。随后25f14f48包failed8/24，未激活；旧通过槽不得重做。
- 许澄bdc03927命令13:39:00开始generating，最后业务心跳13:39:06、lease截止13:41:06；新终态修复正确收敛failed_generation/LEASE_EXPIRED，原binding1不变。native `cf11744e-fd2d-4de2-8a44-b564cbe544cb`独立在13:42:48完成，SHA256=`75c39570fd2288a3c7c9129b72953779762b1980a61f06802e79a90016eeaa35`，768044字节，无模型进程重叠、资源60秒内恢复；未通过业务Nano发布，不能当专属音色成功。
- 确認源码竞态：release_model_for_heavy_runtime先deactivate，restart/activate之间renew_lease可见空token，令pawapp_runtime撤销adapter；production worker等待5秒后被取消，心跳停止而已接受的native继续。新增Event屏障测试在旧源码稳定复现WORKER_LEASE_INACTIVE；未通过时不对正式环境注入故障。
- 修复以model_release_lock包围完整主动卸载/重启/再获取租约窗口，renew_lease同锁等待；idle/heavy复用唯一卸载方法，移除重复实现。6项重模型/闲时×成功/失败/取消并发用例通过，166项sidecar/pawapp/production/processor通过；全量**3872 passed/213 skipped/3既有warning**，138项manifest/Skill/宿主合同通过，Compose/diff检查通过。未放松租约/质量/模型证据或增加schema。
- 21:39至21:47抽屉草稿seed568889、焦点anw-nano-tuning-seed、scrollTop396.03961181640625保持，覆盖waiting→generating→失败；1080设置后的实际viewport1901×1069持续超过5分钟，header可达、未发生整页重建。该输入未提交，没有生成Nano实验。随后用户切到原生聊天，未强行操作其页面，已reset测试viewport。
- 同原作品只读6次请求复测：overview热中位13.10ms/最大17.36ms、5595字节；bindings21.43/23.32ms、2247字节；profiles20.41/20.78ms、17737字节。首请求非冷启动，不伪称冷载入或p95；只证明此时元数据读取不等待重模型，不把profile不同载荷当纯性能提升。
- 另一任务确认计划57两新增Skill及对应公开configure已获用户授权且冻结，可纳入一次联合候选，不自行改其源码/模型或提交。计划57所有权仍归原任务，后续注册证据回传；原九个Skill未改变。
- native ready/active=null且无queued/running/cancel_requested业务job后，停止同一正式QwenPaw追加备份：`database-before-lease-guard.dump` SHA256=`ab31526e1120f26223f71fc5da1605981908564a7ae35d24cbcf921dce22128a`；`media-before-lease-guard.tar.gz`=`73887fcef397d519066bd4b49851cb692b5689397cb90691a4973e7db24d6e19`；`candidate-lease-guard.tar.gz`=`d3750bacc1bdc9376522563eaa751ff9389e389e6f3fda35db441aa72ac65f52`。同第9节私有目录/0600，旧备份不覆盖。尚未把此8槽检查点单独还原，不代替最终24槽恢复。
- 当前候选tree=`51156d2eae280b52c6e2699c4cea8f1d9c30b2c72e927e904ea2e1c6695acfc0`，head0040，bundle不变db467179…df7c68。Sidecar以旧固定7fd898镜像为离线基底，机械提取Dockerfile生产阶段重建，五份源码hash验证通过，得到`sha256:ef641b9b4c7b8b9e0f7c5eb0e1b78124e9a954cd06cffb05230c2c43c87a5d62`；没有网络/模型/依赖下载，旧镜像保留。实际安装与后续业务结果继续追加，不能把回归通过当真实专属音色完成。

### 9.10 联合候选运行与计划57交接（21:53–21:55）

- 公开offline-install-stopped成功，原QwenPaw容器/基础镜像不变；启动health ready、数据库connected、Nano生产worker running且冷模型未加载。公开`frontend/dist/index.js` 3633049字节，SHA256=`db467179ac67e9ab1da4ab3006b31c5254ab022137ea6e6e906ea6be76df7c68`与本地候选一致。通用自动选角仍因包未齐明确GENERIC_VOICE_PACK_NOT_READY，不冒报全能力ready。
- 按计划57 Owner确认的用户授权执行现有`QWENPAW_BASE_URL=http://127.0.0.1:18088 .venv/bin/python scripts/configure_qwenpaw_novel_agent.py`：created=false，11 Skills及既有5工具启用；effective provider/model前后均`minimax-cn/MiniMax-M3`，未调用模型设置写接口。
- 公开GET `/api/skills`（逐Agent header）返回：`suspense-writing`和`golden-finger-writing`在`ai-novel-writer`均source=`plugin:ai-novel-world-2026`、enabled=true；在`default`和`QwenPaw_QA_Agent_0.2`均同source、enabled=false。没有对无关Agent启用这两项。
- 专用Agent公开workspace文件`AI_NOVEL_WORLD.md` GET为5831字符、SHA256=`8831bbce1dfdf934e8e8d22245e218f0be6fbe3149968c0614c92880626d70ff`；源5832字符、SHA256=`bd93627d1c3622907fdd8dd791c2a3a6f4c499e348e9ab1ffebb146bd7fe41ba`。逐字符串验证**源恰为远端内容加一个末尾换行**，rstrip后完全相同，不是正文丢失。system-prompt-files仍`AGENTS.md/SOUL.md/PROFILE.md/AI_NOVEL_WORLD.md`，其他成员保留。部署前沿用20:13完整QwenPaw卷备份；本次未额外制作即时提示文件独立快照，不能把21:52小说库dump称为提示备份。
- 两新Skill启用是作者采用发布，不代表研究效果门槛通过；效果仍inconclusive。其源码所有权和效果记录留在计划57，本任务仅回传公开安装/注册证据，不提交其文件。
- 原许澄命令公开retry产生`ae3501cb-1f1b-421c-b5d5-ec9559591d47`，job=`4b5a9655-225d-4d5f-b625-0da3e6e4c03b`，进入generating_voice；原8槽包retry产生`ca81c497-971d-56f5-8fc2-972efdf707a1`，8项reused，从female_elderly_stern继续。后续只读取这两个持久ID，不重复新建。

### 9.11 首位主角全链完成、章节正常自动准备（21:58起）

- 许澄ae3501cb在13:58:10.986792Z达到**ready_applied**，binding1→2，专属Version=`6336e660-1202-5a05-b15e-89e08a6ec606`、Profile=`d67fc8f8-ea5c-5d22-9316-c5061ec434a8`。native `d4487862-0580-4e27-b993-c8545b643e1b`输出721964字节，SHA256=`633701d309515c4f47b0b61dfb0fdc5182a037d09153350c89836c2c03c2b8e2`；生成期间业务心跳持续超过原2分钟截止点，未撤销worker。
- VG ModelRun=`fdacd602-273c-5612-9292-6fd1f3277dd0`，Nano ModelRun=`94cd8270-520a-5431-b0d4-cbf613483a38`；参考asset=`9adb2767-4cb5-5a80-8d35-dd0560317c91`，Nano试听asset=`afba6c90-d06b-5441-8eb1-c6467f002bed`、4秒、768044字节、SHA256=`1aaa41672b35fc6c38f04237e71aede2977aea9087adee04082831cdffb10847`。通过正式媒体API和X-Narration-Voice-Version-Id取得并核对完整hash/大小，持久试听`第9节备份目录/许澄-6336e660-Nano试听.wav`（0600）。这是机器全链通过，作者听检尚未通过。
- 正式2K设置实际viewport2534×1426，章节player底1416.75位于编辑区同底；只显示角色/操作而非复制正文，未越过写作中列。截图观察后已reset窗口尺寸。
- 21:59只点击一次《雨夜的来信》“智能朗读”，得到准备命令`be13205d-368b-4055-bbcc-cf4978b462fd`：许澄新Version原样preserved、没有生成child；程砚required/chapter_speaker=true，child=`0f65ec9b-4bfe-48e7-aa62-e8cefa308513`；其余4人物background_remaining=4。页面正常显示1/6准备中，尚无最终Edition，继续按此命令追踪，不额外手工生成程砚。

### 9.12 章节恢复候选与正常任务结果（22:04–22:20）

- 正式通用包ca81c497完成第9槽female_elderly_stern后，通过公开cancel停下后继排队，保留9/24；已通过槽不重新生成。此次是部署检查点的正常暂停，不是故障注入。后续只能从该包公开retry继任，不另起零槽包。
- 章节自动准备真实保留许澄；何小川a063f582达到ready_applied，Version=`bef659de-40e5-5eb8-826a-3163f8505e1a`；韩启b009d5e0也达到ready_applied。22:20只剩周姨1a468a75正在生成，未停止活动模型/容器。已验证主动卸载后的多个长任务持续心跳并能进入Nano，不再把成功的native和过期业务误当同一结果。
- 程砚0f65ec9b最终failed_nano_validation，精确码`NANO_SHORT_CHINESE_DURATION_IMPLAUSIBLE`；梁峥7b589160为failed_audio_validation/`AUDIO_MACHINE_VALIDATION_FAILED`。两者没有发布新Version/覆盖原绑定；父命令按既有失败策略使用原官方声音，不声称两人专属已通过。程砚native=`9bec9375-52e5-4581-90a1-6301e480711a`，本次未留存失败Nano媒体，不能在没有音频证据时推断具体是拖音或重复，也不放宽质量门槛或无限换seed。
- 章节已自动续接真实request=`4e145a1d-f1dc-4bf4-9c54-d04a1f4695f3`，script=`8e8c12c3-8e5a-53e1-ab9a-c69347fa51cb`，原revision/hash未变。状态review_required：5处对话各有unknown/low-confidence/unresolved三个阻断，共15项、另1匿名warning，尚无Edition。不是数据库慢；当前生产script_analysis明确仅local_rules_only，cloud_assisted仍HOLD，不能把人物简报AI已接入误当章节语境AI已接入。许澄动作后对话、男孩/摊主引语及“程砚念完”未被本地规则确定。不得靠改写正文或假标高置信度凑单击通过；后续需区分正常人工审核路径与额外智能归属能力。
- 刷新真实复现：父准备仍在后台，但章节入口仅加载Edition而回到空闲按钮。8.6候选新增同小说/同章节持久命令查找和既有resume；首次/恢复共用等待与展示，已终态但仍review_required的request也能找回；更新后的cancel不复活更早命令。查询期间占用按钮以免重复create，切章/取消Abort及scope围栏保留；零正文保存、零新任务创建。
- 候选前端全量1256 passed/142文件，typecheck/build通过；随后只补查询期间busy保护，45项章节/准备/contracts通过且typecheck通过。最初从frontend工作目录直接执行根工具造成配置路径错误，没有运行到产品测试，已改回根目录真实执行；不是产品测试失败。最新打包和正式部署尚待完成，当前正式bundle仍db467179…df7c68，不能宣称页面恢复已上线。

### 9.13 章节恢复正式发布（22:24–22:25）

- 周姨1a468a75也达到ready_applied。发布前正式queued/running/cancel_requested业务job为0，native ready/active_request_id=null；正常生成均已结束才停止同一QwenPaw。四人物专属成功、两人物失败保留官方，不混称六人全部成功。
- 补busy保护后的最终前端全量再次1256 passed/142文件；typecheck、build、138项manifest/Skill/宿主契约、Compose、diff-check通过。没有再改后端，复用同源码3872项后端结果。
- 第9节私有备份目录新增一致性检查点：`database-before-chapter-recovery.dump` SHA256=`1939b4f319a73392affac5e5f20ce477429506f9de2945214307e54478fca48c`；`media-before-chapter-recovery.tar.gz`=`63fd4bdbf8b128e9c015e4b143aa782e75c4a9f3b0f40051291d5b292a352c1b`；`candidate-chapter-recovery.tar.gz`=`f2f1bca75fcbf0d101a697505812a5491ff5878533659940f6445420a8343746`。停止PawApp后dump/复制媒体，0600/no-clobber，旧备份不覆盖。此9槽＋4人物检查点尚未单独还原，最终包恢复仍待验收。
- 新候选tree=`02703cfaca3b8f8ce0bf348326c573d410cf9e14374ac4ac26736ac8ce50f6ba`、bundle=`d9e7ec8625386d9e2677e42bbd5ab8622793ae3cd18f6bb1d5f2ca49b10cb34a`、schema仍0040。公开offline-install-stopped通过，22:24:57启动原85d0…容器/原ea2c…宿主镜像；没有重建Sidecar、迁移、下载或修改上游。后续真实恢复页面与健康结果另记，不把安装退出0代替浏览器通过。

### 9.14 最终24槽、恢复演练与V6候选（2026-09-07）

- 正式中文通用包`a3b96009-f6f3-5bf0-8681-8e33f3e7e32f`已成为唯一active版本，`validated_slot_count=24/24`，对应命令ready/terminal。能力矩阵中`generic_voice_pool`与`automatic_generic_casting`均enabled/actionable；旧失败、取消和superseded版本保留审计，不删除、不冒充active。
- 正式PawApp最终窄候选位于仓库外私有目录`/Users/liujia/Documents/AI小说世界2026-backups/plan56-live-before-qMI5lU/candidate-chapter-runtime-ux-v6`，tree SHA256=`817ae79871ecef56d09369eacd052cd3e2e65fea7a3ad03e9092062ff3854212`；已安装/公开bundle SHA256=`ad77817f5b76fba7c3a55f0307194920e1dac726a4133a15565183b9981b9cd1`。长期schema仍为`20260903_0040`，没有安装同工作区计划58尚未提交的0041/0042。
- 正式三个项目容器均healthy；health为ready/database connected，Nano technical/product ready，模型身份与固定fingerprint不变。VoiceGenerator固定模型和运行时身份不变，没有下载新模型或修改QwenPaw上游。
- 最终恢复包保存在同一私有目录：`database-final-24.dump` SHA256=`920e73454d23862dd973830d4000324c269e65a5528567ecf76a2d1be84f4a10`、`media-final-24.tar.gz`=`1bcd55304f81e098e8b9db3ddcb1b6efbf2ae5aa9463a86528a2bbd7cad3521e`、`installed-plugin-final-24.tar.gz`=`5338b36090a1906996681df53f2b1207a2b291d7bb1b87498c30c50eed60caca`，均为0600。
- 上述dump已还原到独立数据库`ai_novel_world_2026_tts56_final_restore`，验证head0040、4本小说、14份文档、active通用包24/24和1307份ready媒体记录；媒体与插件归档同时保全。恢复没有覆盖正式数据库或正式媒体。此次已完成真实还原演练，不再沿用早期“只解码dump”的弱结论。

### 9.15 正式章节正常流程闭环与桌面UI（2026-09-07）

- 白名单验收作品仍只限《雨港来信》`af44b1e0-9a3d-459a-b915-a848c5ef8fc1`及第1章`cbdcf117-5df8-4bdd-98bf-36ad80644793`；长期库仍为4书14文档，其他3书未写入。为处理两条真实短句的Nano异常，只通过章节编辑器将“信是谁送来的？”改成“这封信究竟是谁送来的？”，并将“许澄说”改成带明确动作主语的自然表达；draft version=4、正文hash=`5f3cdf660e0f102dca1d1ca5c4caf6c53cfb665335019fae032eb9e12a6658d7`。没有测试字样或故障注入。
- 原朗读请求`1e1c26c6-86d8-43af-93b5-3edbea7c258a`生成Edition `60cff3a7-140b-4677-8f9e-9b4c79c4ff41`，29段中27段ready；第3段和第21段分别以`SHORT_CHINESE_DURATION_IMPLAUSIBLE`失败。每段只执行一次人工重试，仍为同一非重试质量失败后即停止重复请求；原绑定、正文和已成功音频不变。V6页面正确显示“当前/下一句段生成失败”和“停止重复合成”，不再提示无效的继续重试。
- 更新朗读后，自动声音准备`c8d556bf-432e-4895-b07b-888d87d7b64f`保留4条已验证专属声音，程砚/梁峥失败时保留各自官方音色；脚本复核只对两句许澄台词通过真实UI选择“角色·许澄”，由两次不可变script version归零6个阻断。冻结后新请求`549744db-0da4-47f6-abc5-aab7e5bf6ee5`与revision `017584cd-f5d3-4c4a-9a3b-d4ff28945ff2`完成，Edition `1312aacd-3b7c-49f6-8529-aa649591ed29`为29/29 ready。
- 更新Edition创建后不会静默替换当前播放指针；通过朗读详情正常选择新Edition并确认“该版本对应当前正文”，`document_narration_state`现指向`1312aacd…`、pointer version=2，页面显示“当前版本·29/29句可用”，旧27/29版保留为历史版本，正文不一致提示消失。此处是既有不可变Edition安全语义，不直接改数据库指针。
- V6真实浏览器检查只覆盖用户指定桌面：1920×1080时编辑区x=481/w=836、播放器x=505/w=788/底=1071；2560×1440时编辑区x=527/w=1430、播放器x=551/w=1382/底=1431。两档均无水平溢出，播放器对齐中间写作区，不复制正文；失败详情可见，console error/warn为空。没有把浏览器外框或移动端冒充本轮桌面验收。

### 9.16 VoiceGenerator宿主超时修复与正式重试（2026-09-07 13:11–13:19）

- 正式程砚命令`9372689f-acf6-4f33-9b91-b9dfa88f19f0`在主阶段仍有进展时被旧180秒上限终止为`RUNTIME_TIMEOUT`。只将固定本机MPS VoiceGenerator主阶段上限从180秒提高到有界360秒；Codec仍为180秒，内存压力、取消、租约/fence、两重模型互斥和60秒恢复门槛均保留。定向host/management测试18项通过。
- 所有业务job终态且native空闲后，通过公开管理脚本安装不可变host release `341c57d85b1dfb96f4b2b2ff4fd0fde0e05bd1204fe5dc72fdf81700a4141481`；安装内容核对`GENERATOR_TIMEOUT_SECONDS=360.0`，旧release仍保留可回退。launchd重启窗口内第一次verify短暂`HOST_HEALTH_UNAVAILABLE`，端口监听后再次verify为READY，runtime fingerprint仍`f39979f7a522a4db308968d3e00b3ba217b9e154a04967c329d5adfabc2b79b7`。
- 通过正式人物抽屉“一键重试”创建命令`898f2bcd-0b3b-45f2-9faf-ef2de3c9eb95`、host request=`6f459e87-8e32-4176-a2d7-c54a3f36a194`。Generator成功产生159×16 token，Codec成功输出12.72秒、2442284字节、SHA256=`4d3ab8ca0fa7eb13ea7d13f2fa388d59ee8a6c995a86fd47392fb4dede1cac43`的48kHz双声道PCM；两阶段进程不重叠并在完成后退出。
- 最终Nano复验仍以`NANO_SHORT_CHINESE_DURATION_IMPLAUSIBLE`拒绝，命令终态`failed_nano_validation`，程砚继续使用`CN 说书`。同一人物历史多次均在固定seed=104729下得到相同类型结果；这是稳定的音质围栏拒绝，不再无限重试、不改seed碰运气、不降低短中文时长门槛。正式人物中许澄、韩启、周姨、何小川已有generated/accepted专属Version，程砚和梁峥失败时保留官方声音，证明正常自动准备的部分成功、原绑定保护和降级路径均可用；不把程砚本次失败写成专属音色成功。

### 9.17 最终听检材料与当前裁决

- 私有听检目录为`/Users/liujia/Documents/AI小说世界2026-backups/plan56-live-before-qMI5lU/TTS56-final-listening`（0700），8份WAV均0600：
  1. `01-主角-沈砚-专属音色.wav`，SHA256=`893fa302a14afe257fef5a4b7cbd9f062e91984d12573ee16c47ec01c967ab79`；
  2. `02-主角-沈听澜-专属音色.wav`，`ac435f64031db845e1382e515371df949afecbb599c0ea7b0dcd34ff0b9c68f6`；
  3. `03-通用-男童明亮.wav`，`d5d8868404068d3b75002983276469646371474a31c9943506519760f99da479`；
  4. `04-通用-青年女性明快.wav`，`bb6c6271c2964e7f560fbe1da89177c700118fe1f9dd3fb36b9df57b9d2d89fc`；
  5. `05-通用-中年男性温厚.wav`，`ba02cd9c3fb0cbbf416033d7c6f6aa52af8df9dee280653eeee39d678d0ef807`；
  6. `06-通用-老年女性慈祥.wav`，`3cc48c76f9040b14ebfcc3f169b3c77c676d2b93d0a6bb74a1462e79edfe00dc`；
  7. `07-通用-青年中性.wav`，`cda1a78459813d1f8370ff062a04a552f3cbe8c5c898f73467a753e0749a8ba2`；
  8. `08-通用-未具名男性单人声线.wav`，`fbbbeef33f0c497f96e161750a748a2022a912bd8743b4d8cae1f9e96e4d4b56`。
- 《雨港来信》许澄正式专属Nano试听另存为`/Users/liujia/Documents/AI小说世界2026-backups/plan56-live-before-qMI5lU/许澄-6336e660-Nano试听.wav`，SHA256=`1aaa41672b35fc6c38f04237e71aede2977aea9087adee04082831cdffb10847`。通用包本次正式输出hash不同于计划55旧批准文件，不能复用旧的主观结论。
- 代码、正式能力、24/24通用包、29/29章节、桌面UI、恢复演练和双模型空闲释放均已有客观证据；最终状态仍为`HOLD_AUTHOR_LISTENING`。作者需确认两条主角专属样本、六条通用代表样本，以及章节播放器的旁白/低男/高女在`1×、1.25×、1.5×、1.75×、2×、2.5×、3×`和播放中`1→1.5→2→1`的清晰度/音高。未收到反馈前不作TTS56-FINAL PASS，也不提交或推送Git。

### 9.18 最新状态恢复、资源回收与最终自动化（2026-09-07 13:26–13:29）

- 因9.14的最终24槽恢复包早于9.15的新章节Edition，本轮额外制作最新一致性检查点，而不是拿旧备份冒充当前状态：`database-final-post-chapter.dump` SHA256=`f03f3b15f1911d7e1d6b15da71b583b4d21b4791bb827efb5672277c096d5e5f`、`media-final-post-chapter.tar.gz`=`3f09196f2ff944ece82dbf47dea2d79b03d14c2fe1ddb0321718d0bdeae4a8ca`、`voice-generator-host-release-341c57.tar.gz`=`4de0bf3570d8714e84906aa1650779fa76384902595b182e0031fb7bd8149d5e`，均在9.14私有目录且权限0600。
- 新dump已用`--no-owner --no-privileges --exit-on-error --single-transaction`恢复到独立数据库`ai_novel_world_2026_tts56_final_post_chapter`；验证head0040、4书14文档、active包24/24、当前Edition=`1312aacd…`且29/29 ready、ready媒体1369项。没有删除或覆盖正式库、旧恢复库、正式媒体或旧备份。
- 从恢复库导出只含路径/hash/字节的私有清单`media-final-post-chapter-ready.tsv`，SHA256=`b6f1c21b8795e8b7de3f3f48d563ed977e0655d775ad5854a1d4489d56de0302`。对压缩归档逐成员拒绝绝对路径、`..`、链接和重复项后，1369/1369份ready媒体的字节数与SHA256全部一致；没有解包覆盖正式媒体。
- 最后Nano请求完成后按300秒阈值实际回收：health `model_loaded=false`、`worker_generation=null`；VoiceGenerator所有native worker均退出，host verify READY，仅保留轻量监听进程。两个重模型没有同时常驻，未用重启伪造空闲释放。
- 最终源码回归：后端全量`4055 passed, 256 skipped, 3`个既有弃用warning；前端`148`个文件、`1339 passed`；typecheck与production build通过；插件打包通过；manifest/Skill/QwenPaw宿主契约`139 passed`；`docker compose config --quiet`与`git diff --check`通过。跳过项不计通过。最初照旧文字执行`pnpm --dir frontend`因本项目没有`frontend/package.json`而未进入测试，随后使用根`package.json`和工作区固定Node运行时完成上述真实成绩；不把命令环境错误记作产品失败。

| 检查项 | 2026-09-07裁决 | 证据边界 |
| --- | --- | --- |
| TTS56-01 默认旁白 | PASS | 新小说默认Junhao的领域/事务回归与既有正式创建证据有效；作者已改选的旧小说不强制覆盖 |
| TTS56-02 18官方音色 | PASS | 18项目录、试听与直接绑定链有效；试听不偷换绑定 |
| TTS56-03 官方智能匹配 | PASS | 正式Agent模型有效，人物匹配/整书确定性选角及失败不覆盖已有证据完整 |
| TTS56-04 专属生成 | PASS（带模型样本拒绝） | 许澄等正式generated/accepted链通过；程砚坏样本由Nano拒绝并保留官方音色，不算系统绕过失败 |
| TTS56-05 通用音色 | PASS（机器） | 正式active 24/24、自动通用选角enabled；代表音色仍待作者听感 |
| TTS56-06 章节闭环 | PASS（机器） | 正常UI更新、脚本复核、冻结、原子Edition和29/29播放资源完成 |
| TTS56-07 高级与删除 | PASS | 两底音真实调音参数/fingerprint及恢复官方完成；删除沿用隔离恢复证据，未在正式库做破坏性验收 |
| TTS56-08 播放听感 | HOLD_AUTHOR_LISTENING | 保音高驱动和频率探针通过；主观清晰度/音高必须由作者确认 |
| TTS56-09 桌面UI | PASS | 仅按用户要求覆盖1920×1080与2560×1440；无溢出、重复正文或console错误 |
| TTS56-10 性能/刷新 | PASS | 元数据热读取不等待模型，抽屉/章节命令找回及无整页重建证据完整；不虚构冷载入p95 |
| TTS56-11 发布恢复 | PASS | 24槽恢复及最新29/29恢复均真实还原；1369/1369媒体核对 |
| TTS56-12 资源与证据 | PASS | Nano 300秒回收、VG一次性进程退出、不可变host release和私有听检材料已保全 |

当前没有已知P0/P1或影响日常使用但仍未修复的工程缺陷；唯一未关闭门禁是作者听检。目标继续active，不提前标complete，不自动提交或push。

### 9.19 感知响度修复、正式Edition与恢复检查点（2026-09-07 18:35–19:11）

- 作者听检指出不同声线音量不一致后重新打开TTS56。8份最终试听的普通RMS均为`-20.00 dBFS`，但带门限K加权节目响度为`-17.63..-16.37 LUFS`，部分400ms短时窗口跨度约13 dB；因此根因不是播放器全局音量或数据库读取，而是旧流水线只统一未加权RMS，不能统一人耳感知响度。
- `backend/narration/audio_pipeline.py`升级为`narration-audio-pipeline/2`：固定48 kHz K加权、400ms块/100ms步长、绝对及相对门限，目标`-18 LUFS`；保留`-1 dBFS`样本峰值、3ms接缝、静音/削波/时长围栏，且不增加DSP依赖、不恢复Web Audio、不加入动态压缩。8份旧试听离线处理后均为`-18.000 LUFS`，峰值`-8.23..-2.80 dBFS`。
- 首个正式v7候选tree=`9b24bf014aa4e60399a5fdb8d5df991b2a403fd92b95eb664d4f96db47d58625`部署后，请求`866d6fee-2695-4ed8-8f85-1e08e519de9f`生成Edition `7021d9c6-1b1a-48ca-8c0b-df742eb4e1f3`，29/29 ready。实际逐份解码FLAC发现28段约为目标，但第3段“这封信究竟是谁送来的？”仅`-26.422 LUFS`；旧最大`+6 dB`补偿先触发，而输出峰值仍为`-9.13 dBFS`，证明不是削波限制。
- 根据真实证据将最大补偿扩大为`+18 dB`，仍由`-1 dBFS`硬峰值限制兜底。最终v8候选tree=`09c3ded7f380b1a0e776eb19cb4f22ab87ef2b19827ae46a2cbe261cf9674270`、生产postprocess fingerprint=`4af0fd739ce328e311bdf41eacac179b60f7a67bea067809a674192ec1109217`。请求`2aa9b3b4-1909-4e10-9f35-4d95dc9812fd`沿用此前两处已确认的说话人修正，生成Edition `6be350e3-e7be-42d3-857b-4222a3dd6aa7`并29/29 ready；所有master逐份解码实测为`-18.296..-17.878 LUFS`，跨度`0.418 dB`，最高峰值`-1.000 dBFS`，零失败。该Edition已通过公开CAS切换为当前版本，pointer version=3；旧Edition均保持不可变。
- 正式部署前v7备份：数据库`c69e29f0…4bc0`、媒体`3f09196f…8ca`（与9.18媒体逐字节相同）、旧插件`f91e932c…2848`、候选归档`c5e0cdf5…cb88`。v8部署前备份：数据库`1bd9b1a9…2731`、媒体`157f76cb…df2a`、旧插件`4c13a966…13e6`、候选归档`a57fd6f9…ff60`。文件均在第9节0700私有目录且为0600；两次安装均绑定原QwenPaw container/image及head0040，没有迁移、替换基础镜像或改上游。
- 最终检查点：`database-final-loudness-v8.dump` SHA256=`5e7590146fcb8b26ad74034feaac668758c3e96c6d264fa643c7695a883be1e8`、`media-final-loudness-v8.tar.gz`=`d0fd25999b22092ae185c9c3af26c39251a89be413779f0e72e2a67b03f24f35`、`installed-plugin-final-loudness-v8.tar.gz`=`a6d31044604f6bc2c7bc1972211bae143329e90c3cfbc26a8b6022b5c5d460b2`。dump已还原至独立库`ai_novel_world_2026_tts56_loudness_v8`，验证head0040、4书14文档、active包24/24、当前Edition正确且29段ready；媒体归档拒绝绝对路径、`..`、链接与重复项后1485/1485份ready资产大小/hash全部一致。
- 修复后后端全量`4126 passed,292 skipped,3`个既有弃用warning；前端全量154文件/1365项、typecheck/build、插件结构/生命周期、manifest/Skill/宿主契约、Compose和diff-check通过。正式health ready、全部8项TTS能力enabled/actionable、Nano冷载`model_loaded=false`，VoiceGenerator host READY。当前唯一门禁为作者对新Edition及等响度试听材料的复听；未收到结论前不作最终PASS。
