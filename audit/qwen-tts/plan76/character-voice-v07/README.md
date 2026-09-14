# 计划76 V0.7.1 人物音色生成优化记录

日期：2026-09-14（Asia/Shanghai）。范围：[计划76第10节](../../../../docs/开发文档/76-Qwen3-TTS本地声音设计与复刻最小闭环计划.md#10-v07-人物音色生成优化计划2026-09-14)。

状态：作者要求“请你让页面生效”后，已公开更新正式插件并重载本机TTS，页面年龄描述与档案选择已核实。2026-09-14后续只读复核确认既有候选可在桌面Edge完整播放，内置浏览器仍会在点击播放时崩溃；没有生成新声音，V0.7.1新候选生成、作者听感、锁定、人物采用与章节应用仍待验证。相关源码已由提交`32bea56`纳入并推送，索引补记已由`38da2e0`纳入并推送；本文早先“未提交／推送”只描述当时时点。

## 改动与代码证据

- F01：唯一后端普通话校验识别有界排除／转折；实际前端函数输出直接进入真实Pydantic请求与同一领域校验，无手写描述替身。
- F02—F04：实际年龄、明确听感与稳定音质分离；保留中文数字和年龄限定，排除他人／外貌／临时／否定描述；含糊条目给核对提示。保守规则不等于通用语义理解。
- F05—F06：人物卡使用已保存字段，工作台接收实际绑定档案ID；无绑定不默认首项。手改输入按档案隔离，最新资料只自动更新未编辑内容，切人物拒绝旧异步结果。
- F07：自然对白试听文本；另一版生成新的31位seed；同步防重入；显式原请求重试使用原描述／seed／CAS／幂等快照。会话存储只记录标识，不存描述／正文／音频。
- F08：generated与uploaded均可进入人物面板，继续检查锁定／质量／权利／参考证据；已有合成参考按Base能力判断，不依赖VoiceDesign当前是否可用。
- 刷新可找回确切响应对应的候选；无法证明归属时不按姓名、时间或新增数量猜测。已有试听播放后可确认锁定，修改描述不冒充已改变候选。

## 验证

执行工具：项目`.venv/bin/python`；Node24目录`/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin`加入PATH后运行pnpm／跨层测试。

- 后端定向：`pytest tests/narration/test_voice_design_language.py tests/narration/test_character_voice_design_handoff.py tests/narration/test_qwen_tts_provider_contract.py tests/narration/test_qwen_voice_product.py`：59 passed，1 skipped。
- 全量后端：`.venv/bin/python -m pytest`：3250 passed，331 skipped，4项既有弃用警告。跳过项目不计通过，不以模拟或未运行的数据库／模型用例宣称真实链成功。
- 全量前端：`pnpm test`：170文件、1616项通过，包含最终人物主体补充。建议函数单独53项通过。
- `pnpm typecheck`、`pnpm build`、`.venv/bin/python scripts/package_plugin.py`与`git diff --check`通过。

本次构建基于工作区HEAD `76e2bf0e1731a3b73d42dac5685c72d7b617b1fa`加本轮未提交增量；前端产物SHA-256：`70f258797e17b512831f2386a796dd2129f0bafacdcb4bcd02b75bfe4a67329b`。冻结来源重建及正式安装后逐文件校验均匹配该产物；不是新的Git提交号。

## 未执行与恢复

代码施工阶段未操作正式环境。随后本轮部署只公开更新本项目插件、只读备份数据库和配置、重载原受管TTS进程；未生成、锁定或绑定声音，未改正文或章节音频；未暂存、提交或推送Git。计划66／79／80等既有无关改动保留。

G2精确来源、备份、公开更新以及本地TTS进程规则版本核对已完成；G3实际人物资料→设计参考→Base试听→真实浏览器播放仍未闭合。作者确认声音后才执行锁定、明确绑定与章节采用。

## 正式生效记录（2026-09-14）

- 组织：Q76V7-R／GATE／MUTEX由主代理串行实施；本轮不并行，正式环境和部署锁只有一个所有者。
- 来源裁决：先前“必须先提交Git”来自旧审计发布脚本，不是公开更新API要求。本次使用`git archive HEAD`加明确16文件覆盖、全树／包SHA-256固定来源；不以部署请求代替Git授权。脚本为[release_snapshot.py](./release_snapshot.py)。
- 冻结来源与恢复点：`/private/tmp/plan76-voice-v07-oNcv2c`，含`source.json`、`manifest.json`、`source-head.tar`、`plugin-before/`、`database-before.dump`、逐Agent公开选择与Skills状态、原LaunchAgent配置及原源码。数据库dump已校验PGDMP及目录清单，0600；不入Git、不自动恢复数据库。该路径是本机临时恢复点，不承诺长期留存。
- 相对旧包恰好2文件变化：`frontend/dist/index.js`、`backend/narration/contracts.py`。公开热更新成功；全包哈希一致，逐Agent模型／Skill／工具／提示文件选择保持，schema仍为`20260913_0056`，容器ID、镜像及启动时间未改变。
- 活动门禁：无新活动生成；精确识别并原样保留两项2026-09-11的`selection_edit running`历史记录（早于当前容器启动，先前计划74已记录）；不放宽其他任务门禁、不取消任务、不修改表。
- 本机只执行一次`launchctl kickstart -k`：PID `51761 → 98890`，仍从原仓库加载；运行时源码与冻结来源一致，共用校验模块哈希一致，plist字节未改变。健康`reason_code=null`，模型按需未加载时为`degraded`；正式产品、worker、Base能力均`ready`。不把未加载模型状态写为合成通过。
- 正常作者路径：创作中心→《缺氧：末日地下世界》→朗读→人物配音；陈屿仍绑定`Serena｜温暖女声`，私人档案未自动选择。再由角色→陈屿人物卡→声音→私人音色，明确选中现有“陈屿｜冷静坚韧男声”；页面提示不改变绑定并恢复版本1和试听控件。
- 正式资料仍是男、小传明确26岁。点击“按最新人物资料更新描述”仅更新表单，输出：`人物实际26岁；保持青年年龄感，男声；标准普通话，自然对白，吐字清楚。` 页面说明普通性格／沙哑不会自行改变年龄感。“设计另一版”可用但未点击。
- 播放已有试听时，内置浏览器显示`This page crashed`，未获得时间推进证据；本轮只通过页面入口与描述校验，不能宣称试听／音质完成。新声音及作者听感保持待验证。
- 已重新打开正式创作中心，通过正常入口恢复并保留“朗读→人物配音”页面，桌面截图确认可用。最终`final-check.json`核对全包、配置、容器和任务计数均未漂移，没有新生成任务。工作区检查期间出现其他任务的计划81文档，原样保留、不纳入发布。

## G3既有试听播放复核（2026-09-14）

- 正式公开API确认《缺氧：末日地下世界》的陈屿仍绑定官方`Serena｜温暖女声`，绑定版本1、更新时间仍为`2026-09-12T06:28:42.898355Z`。私人档案“陈屿｜冷静坚韧男声”仍为`draft`、档案版本2、`current_version_id=null`；其2026-09-13创建的版本1为`preview_ready`，没有被锁定或采用。
- 既有试听资产为6秒、48kHz、双声道、16-bit WAV，1152044字节；公开媒体接口在`X-Narration-Voice-Version-Id`范围头下返回200，SHA-256为`d91d0dd9f3a9a431450e0988f0588c33044db627ec42d2b2a191ba4d41516d9d`，与API声明一致。实读RMS为2755.1、峰值26920，不是空白或全静音文件。
- 正常页面路径“创作中心→角色→陈屿→声音→定制私人音色→继续完成”能够恢复版本1和已有播放器。Codex内置浏览器再次在点击“播放”时崩溃，故该浏览器仍不计通过；同一正式页面改用桌面Microsoft Edge后，按钮从“播放”切换为“暂停”，页面显示“已有试听已开始播放”，6秒结束后按钮自动回到“播放”，桌面浏览器播放门禁通过。
- 未勾选“我已听过，声音清晰，适合这个角色”，未点击“确认并锁定音色”，未生成另一版、未改试听文本或人物绑定。复核后公开API仍显示档案`draft`、版本`preview_ready`、陈屿仍绑定Serena；产品与朗读健康均`ready`。
- 本次任务计数与此前`final-check.json`完全一致：章节生成`failed=6/ready=13`，创作生成`failed=5/ready=58/running=2`，后台任务`dead_letter=1/failed=11/succeeded=1951`；两项`running`仍是2026-09-11的既有`selection_edit`记录。没有新模型任务或正式数据写入。

本次只关闭“既有候选在普通桌面浏览器可播放”这一技术子门禁。该候选早于V0.7.1创建，不能证明V0.7.1的新人物资料→VoiceDesign→Base生成链；作者也尚未给出听感结论。当前没有运行中的生成、发布或绑定动作，候选以`draft/preview_ready`安全保存，因此计划76转为`CONDITIONAL`，不再占当前施工队列。只有作者明确接受这份候选或要求按V0.7.1描述生成一份新候选时，才恢复相应窄任务。

恢复命令（执行前再次核对活动、包和配置）：`.venv/bin/python audit/qwen-tts/plan76/character-voice-v07/release_snapshot.py rollback --backup /private/tmp/plan76-voice-v07-oNcv2c`只通过公开更新恢复旧插件。本机规则需同时以项目解释器执行`/private/tmp/plan76-voice-v07-oNcv2c/runtime-before-source/scripts/qwen_tts/macos_runtime_service.py install`指向已保留旧源码，核对哈希及健康；不能只退容器规则。未实际执行回退，未恢复数据库。
