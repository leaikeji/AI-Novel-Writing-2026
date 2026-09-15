# 计划76人物音色最终收口证据

日期：2026-09-15（Asia/Shanghai）

结论：**`CLOSED_PASS`**。作者在正式试听后明确回复“适合，采用”，新生成的陈屿音色已由作者确认、锁定并绑定到人物；章节已生成并切换到使用该音色的新朗读版本。新旧朗读音频均实际播放，旧候选、旧绑定历史和旧Edition均保留。

## 1. 范围与施工组织

本次只完成计划76已定义的作者触发窄任务：一份新候选、一次作者试听裁决、锁定、人物绑定、章节更新、播放与恢复验证，以及过程中发现的显式更新恢复错误修复。不修改正文、schema、Provider选择、Agent、Skill、工具或QwenPaw上游，不删除任何音色、媒体或朗读历史。

本次**不并行、不启动子代理**。作者听感裁决、正式环境、声音档案、人物绑定和同一章节Edition指针都是共享`MUTEX`资源；由主代理串行操作并承担唯一集成责任。只读范围为计划76、声音与朗读现行契约及历史证据；禁止触碰旧项目`Data`、正式正文和无关工作区文件。

## 2. 事前恢复点

- 正式数据库及运行态备份：`/private/tmp/plan76-final-closeout.q5yX71`
- 数据库dump：`database-before.dump`，66,581,644 bytes，SHA-256 `8bef467a3821e89bfa068d5ab675dc31504667b26d4d17cb4c0bd5adf493b8cf`
- 初次缺陷修复前端恢复点：`/private/tmp/plan76-voice-v08-final.hlGLQw`
- 收口清理前的现行前端恢复点：`/private/tmp/plan76-voice-v08-cleanup.0ryAZR`
- 恢复点包含已安装插件树、Agent／Skill选择、活动状态、容器状态和精确哈希。
- 当前包的即时插件回退命令：`.venv/bin/python audit/qwen-tts/plan76/character-voice-final-20260915/release.py rollback --backup /private/tmp/plan76-voice-v08-cleanup.0ryAZR`

数据库dump只作灾难恢复证据，不能自动覆盖已产生的新正式数据。若作者改回声音，优先在正常界面重新选择人物声音并切回旧Edition；不会删除本次新资产。

## 3. 真实模型与作者裁决

复用私人声音档案：

- 档案：`0f3a9676-bf94-5fcf-a9c7-7e485cdc7cd5`，`陈屿｜冷静坚韧男声`
- 新候选版本：`0974975f-56a6-5eae-b696-c0c21fccfad6`，版本号2
- 描述：`人物实际26岁；保持青年年龄感，男声；标准普通话，自然对白，吐字清楚。`
- Provider：`qwen-tts`
- VoiceDesign模型：`mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16`
- 最终Base模型：`mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`
- 试听任务：`8575f771-01a8-4e8d-9660-c78dd9b41156`
- 试听：`4805042f-a0cf-541f-a527-b8e330afda06`
- 试听资产：`ee7507ac-53c6-59c7-80f9-8697bfa292bd`
- WAV：48kHz、双声道、12,560ms、2,411,564 bytes，SHA-256 `26a393bb58ee140f235fab658b9e811383ca9dd0b10aa7fb41658ec5ff00f846`

同一初始任务的模型运行记录显示两次真实阶段调用都`success`：VoiceDesign requested／actual模型完全一致，耗时5,520ms；Base requested／actual模型完全一致，耗时12,560ms。任务只有attempt 1，`retry_kind=initial`，没有自动重试。

作者在播放这份新候选后明确回复“适合，采用”。随后通过正式页面确认质量并锁定，版本最终状态为`locked`、`quality_state=accepted`、`activation_basis=preview_confirmed`、`validation_basis=human_accepted`；耐久参考资产为`3661cc5a-a5b1-5494-82f3-d08695ef2454`。试听资产继续按既有临时资产策略保留，不能误记为取消过期。

陈屿人物`b8bd1936-c706-45b7-963e-51d9da9d8cd5`最终为`dedicated`绑定，指向上述档案和版本2。档案为`active`且`current_version_id`指向版本2。旧版本1 `030e5b2a-807a-55d7-ab17-4708278528b0`仍为`preview_ready/pending`，没有删除或覆盖。

## 4. 显式更新恢复缺陷与修复

正式页面点击“重新生成朗读”后已建立新的更新请求与含4句陈屿对白的脚本，但前端把相同正文／设置误判为可复用历史音频，恢复了旧Edition并丢失新请求的页面控制权。根因是`reuseExistingAudio`没有区分首次创建和作者明确发起的更新。

修复范围：

- `frontend/src/workbench-v2.ts`：只有`intent === "create"`的首次创建允许历史音频恢复；显式更新必须保留新请求，使新人物声音冻结进新Edition。
- `frontend/src/workbench-book-narration-recovery.test.ts`：增加显式更新不得使用历史音频恢复的回归断言。

代码验证：

- 前端全量Vitest：165个文件、1574项通过。
- `pnpm typecheck`：通过。
- `pnpm build`：通过。
- `.venv/bin/python scripts/package_plugin.py`：通过。
- 初次修复包`frontend/dist/index.js` SHA-256：`9b2996f9f7e9f8fdcfe7c6b9a4b4ad550ec01a1231ce815f0071bfd43be436f1`；后续等价收口清理形成的现行包见第7节。

候选经公开热更新原位安装，未重启Docker。安装后的第一次即时精确验证遇到短暂健康就绪竞态并按门禁停止；随后的纯只读健康查询恢复`ready`，重复精确验证通过。不得把第一次即时验证写成通过，也没有因此重复安装。

## 5. 章节应用与播放

缺陷发生前服务端已经持久化新请求，未重复创建或重发。因页面已失去该请求控制权，使用同一正式产品公开API、作者已确认的CAS版本和幂等键`plan76-final-approve-20260915`完成批准；客户端等待超时后没有重复提交，服务端继续完成唯一动作。

- 请求：`063f42ae-7406-46cf-a0f7-81ea8b2672cc`
- 脚本版本：`93806d54-a175-511e-86ea-fb950718f60e`
- 不可变脚本哈希：`bcb048900e1b2ac7f7336c16e9be08902d176000cb7e313743478976b44eba32`
- 新Edition：`a7e85200-af15-466f-83bb-b1e7995b0289`
- Edition状态：`ready`，210/210句可用；206句沿用官方旁白，4句使用陈屿版本2。
- 正式页面已明确选择该版本并点击“确认切换”；`document_narration_state`当前指向新脚本和新Edition，版本3。

陈屿的4句分别位于ordinal 19、21、53、63。桌面Edge中实际播放了至少两段不同文本：

- ordinal 19：`再传了十年要拆，对吧。`，资产`6152a026-a40e-5453-b72f-2abbf8c320fd`，2,880ms，SHA-256 `9a1a40df24a0deb6b2d95731aae5c632a7461c0a2927b4c04209213042c03c4c`
- ordinal 21：`漾水巷，我知道那一片。`，资产`3c0ef1e0-8e95-5714-9422-a3cbcb9da233`，2,560ms，SHA-256 `a65710da73077f3050092901b0e3c406c024c880bec4752615056cc495dacf2a`

旧Edition `12d6fbb0-8562-4ddd-bddb-e6c8942633c6`仍在历史中且210/210句可用；切换前已在正式页面播放。其首段旧资产`a49aa829-c7c6-56fb-b96f-c2fce770d34f`经Edition与manifest revision 206范围头读取为HTTP 200，72,380 bytes，SHA-256与清单值`4abe1f087d94be0b7b70f36b18b80b256723e16f6de003a81b37d95e2637c4d7`一致。

## 6. 最终只读复核

- 正式PawApp健康：`ready`；朗读生命周期`ready`、worker运行、Base参考复刻可用。
- 正式容器持续健康，启动时间未改变，未重启。
- 精确安装包、Agent／Skill／工具／模型和prompt选择保持；公开发布验证器最终`VERIFY PASS`。
- 声音档案`active`、版本2`locked/human_accepted`、人物`dedicated`绑定正确。
- 当前Edition `ready`，210/210句，其中4句使用新人物音色；旧版本和旧Edition均存在。
- 无schema、正文或QwenPaw上游改动；无声音、媒体、作品或历史Edition删除。

## 7. 结项后同范围冗余清理与正式复核

作者继续确认清理计划76相关区域中的真实冗余。本轮保持同一窄范围，不新增功能、不改变任何数据或声音权威：

- `frontend/src/workbench-v2.ts`移除已无调用者的章节首项、旧封面和旧分区图标辅助代码及对应导入；
- `frontend/src/narration/contracts.ts`移除未使用的本地类型导入和两个未使用正则；
- `frontend/src/narration/chapter-narration-workflow.ts`在工作流本体再次强制`intent === "create"`才允许历史音频恢复，避免其他调用者绕过页面层门禁；
- 用行为回归测试替代依赖源码字符串的脆弱断言，证明显式`update`即使收到恢复提示也不会调用历史恢复。

代码验证全部通过：定向2文件／24项、全量前端165文件／1574项、`pnpm typecheck`、`pnpm build`、`.venv/bin/python scripts/package_plugin.py`。现行`frontend/dist/index.js` SHA-256为`6bfb413400c722dc63a4a7f405343ddcd8fb58ee743bdf1a42ab47b4144b1a05`。候选经公开热更新原位安装；恢复点`/private/tmp/plan76-voice-v08-cleanup.0ryAZR`的`prepare`、安装后精确`verify`均通过，正式容器未重启，配置与活动状态未漂移。

正式桌面页面只读复核确认：朗读设置可用，陈屿仍显示`专属音色`绑定；第一章最终载入现行播放器并显示210句、既有播放进度及可播放控制，第二章准确显示尚未生成朗读。本轮未点击播放或重新生成。第一章脚本详情接口返回约151KB，单次实测23.1秒，期间界面持续显示“正在读取朗读版本”；请求最终HTTP 200并正确载入。这是独立性能观察，不是本次清理回归，也不授权删除不可变哈希、来源或权限复证逻辑，后续若优化需先建立查询／解析剖析与等价安全门禁。
