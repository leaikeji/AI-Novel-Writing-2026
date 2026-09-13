# V1.2代码验证记录

日期：2026-09-13。状态：`2df5f17 G2-B PASS / 已正式发布且F18通过 / G3 PARTIAL`。下方旧代码检查及HOLD保留历史。正式分项不等于G3整体通过。

## 2df5f17完整候选复验

- 在d171317基础上保留76刚正式发布的9个前端文件，逐文件与其干净源`/private/tmp/plan76-age-release.T7nXDx/code`的ddbe2e4一致。只作为已部署依赖入Git，不扩大74功能、不纳入76文档。
- 干净源`/private/tmp/plan74-focus-merged-source.7Fk1vB/code`执行固定锁离线安装、pnpm test（170文件1554项）、typecheck、build（204模块）、package_plugin全部退出0，status为空。JS SHA `e347aa28210c8b3f3587c95f54207ae3eb3aec7519c2ee7e8f1b27f6c966d1e5`；比d171多6项属于76独立覆盖，不计为74新增。
- 相比6f544df，backend／tests／skills／manifest／Python及pnpm依赖文件无差异，继续引用Python3206／330跳过及数据库342的不变范围结果。正式发布与F18焦点PASS另见运行记录，不混同代码检查。

## F18关闭动画后的焦点返回

- 6f正式保存关闭通过，但真实activeElement为BODY。d171317移除closeEditor中立即聚焦旧节点的行为；捕获稳定按钮键和范围，在afterOpenChange(false)结束后解析当前按钮ref，且每次只执行一次。新面板已打开或范围变化时不抢焦点，保留现有CAS、输入及版本保护。
- 精确源`d171317f56159649edf5a6ed210fe07e88d25fa4`、tree `9157c4e6ff1d96cc121c7e665495e071e61e3c8d`，三文件提交只含工作台、同名测试和当前计划。定向2文件36项通过；共享工作区全量170文件1554项含76新增覆盖，不作为74干净源计数。
- 独立检出`/private/tmp/plan74-save-focus-source.6vUMsP/code`固定锁离线64包复用、零下载；前端169文件1548项、typecheck、203模块build、package_plugin全部退出0，status为空。JS SHA `acdb06e8307707080a133bf12fd57d7a8f6fb51fe3e01118aef86cfb680974a1`。此处记录实际工具完成结果摘要，没有另造终端原始日志。
- `git diff --exit-code 6f544df d171317 -- backend tests skills plugin.json pyproject.toml pnpm-lock.yaml`无差异，Python3206／330跳过与数据库342沿用已有不变范围证据。正式焦点尚未验证；76新依赖若加入后必须重做该完整提交的前端G2-B，不把d171的包hash当合并包hash。

## F18正常保存后的版本刷新

- 正式词项保存已成功，但current_version_id随reload改变使contextKey不同，面板误留在“上下文切换”。修复将成功后的范围身份与版本基线分开；写入前仍检查完整contextKey（含版本），真正切书／切筛选／切资料后的迟到成功仍保留原输入，不放宽CAS或写入权限。
- 定向组件／创作中心34项、工作区全量169文件1546项、类型、构建、打包均退出0；已有切书、版本变化、迟到响应和同步失败负向覆盖保留。新增资产／词项两条回归验证保存引起同资产版本变化时正常关闭并恢复焦点，不重复保存。
- 精确三文件提交`6f544df9326b4fa01cd9aa16844be95a59e201ed`，tree `55f98a7a64440b2f104311a0eddbcb54db6a88fc`；独立检出`/private/tmp/plan74-adoption-source.90xAJO/code`从干净7e切到6f，20:59重跑前端169／1546、typecheck、203模块构建、package_plugin全部退出0，检出status为空。JS SHA `a871ffcc842379dd0145057d2198f47da09c17047d5fbe88aaa88346edccc2eb`。本节保存实际工具结果摘要，没有另造原始终端日志。
- `git diff --exit-code 7e382a1 6f544df -- backend tests skills plugin.json pyproject.toml pnpm-lock.yaml`无差异；Python3206／330跳过及私有库临时数据库342沿用不变范围证据，未连接正式数据跑pytest。6f尚未安装，下一次更新只从该干净提交构建，不夹带工作区新增的角色／音色外任务改动。

## F16确认预览定位与F17采用目录同步

- 源47733df新增只读全文预览（纯字符串、UTF16精确mark、主动focus及scrollIntoView、无效位置不标记、卸载解除定位器），移除原来只setSelectionRange而不滚动的textarea。原逐项处理用例补真实接线断言，未复制另一套处置面板或改报告／采用请求。Workbench仅在现有当前页／恢复门禁通过后同步目录中相同ID的服务端结果，不查整库、不改他章和卷元数据。
- 定向4文件55项、工作区全量169文件1544项及类型／构建通过；精确7文件提交后，独立检出`/private/tmp/plan74-adoption-source.90xAJO/code`完成同样前端1544／类型／构建／打包，以及[Python](adoption-desktop-source-backend.log)3206通过、330跳过、4条既有警告。该源包含76已明确提交的e5f1846，新增1项后端用例来自其独立提交，不计为74新覆盖。
- 7e382a1再将确认内容限制在桌面可滚动高度内、预览高度随窗口收缩；同一干净检出切到`7e382a1eecba8c8b8e84513ad53961dc4ddc2fee`重跑[前端／类型／203模块构建／打包](adoption-desktop-source-frontend.log)全部退出0，status为空。tree `06f2c02396071c88eabd9af4579d12cc61ce8955`，JS SHA `89de65fd1a7493943cbce1996c5f7fd6242ad978d5ed8152791ecf46fd252800`。47733df至7e382a1后端／tests／Skill／manifest／依赖无差异，Python3206按同一不变范围引用。
- 上述代码检查完成时尚未安装；后续7e于20:43正式公开更新，21:00新规则、两命中逐项恢复采用及目录同步通过，见桌面／发布记录。Python及数据库证据按不变源码范围引用，不当作新正式场景结果。

## F14显式刷新与F15历史计数

- 源`863d4b5c33858988272c56f3c31e81e9a8398230`、tree `07d1091f22e016f1224d0c197d9e85e2a758ccaa`，独立检出`/private/tmp/plan74-refresh-source.mWGKuA/code`。只增加常驻刷新按钮与5项前端回归，历史卡不再把已保留禁用命中误称为慎用提醒；没有新增查询接口或自动重发助手消息。
- 原锁离线安装64包、零下载；前端168文件1536项、typecheck、202模块build、package_plugin退出0，检出status为空。JS SHA256 `8f374abc2f2c992817163921467a11db98ed3eedfa560f81d4b04840905912b0`。初次指定文件的`pnpm test -- ...`实际仍执行全量，记录按真实168文件，不称定向。
- [干净源Python全量](refresh-source-backend.log)3205通过、330跳过、4条既有警告。`git diff --exit-code 5919bba 863d4b5 -- backend tests skills plugin.json pyproject.toml pnpm-lock.yaml`无差异，数据库342项按不变范围复用，不另建库或接正式数据库跑pytest。
- 此节仅代码校验；公开更新及正式桌面结果另记，不能将构建成功写为已上线。

## F13显式回执撤销识别

- 先补2条正向句式红测，实测失败：旧分类器把明确“撤销已应用回执UUID”识别为DIRECT或AMBIGUOUS，无法走UNDO。修复仅加可信消息开头的完整UUID撤销句式，咨询、引用、否定、假设及不完整编号仍不授权；8条新增句式覆盖，既有成功补偿／后续编辑冲突用例各补1条新句式，并改用真实分类器输出而不是固定UNDO。
- 维护／工具定向86通过；初次命令误写不存在的test_maintenance_tool_access.py导致未收集，纠正为实际文件后成功，不计为产品失败或通过。工作区全量首次3204通过，包含其他任务1条新用例，不能作为干净发布源数量。
- 精确提交5919bba后独立检出`/private/tmp/plan74-undo-source.3J220z/code`，[Python全量](undo-source-backend.log)3205通过／330跳过／4条既有警告。离线pnpm复用64包、零下载；类型与202模块构建退出0，JS SHA `f86fd50614765abc4c80017ac6393818ac255e167201ade023e497e2e110b4b5`与3bc一致，源status为空，打包退出0。前端1531及数据库342沿用3bc未变化代码证据；本次未重跑数据库，不伪称新增正式数据覆盖。
- 未加依赖、迁移或Skill；发布唯一差异为maintenance.py的意图判定。正式原回执撤销及恢复结果单独记录于桌面证据，代码测试不替代真实链。

## F12原子保存并使用（含F11候选）

提交`3bc7fa159aba406603fe2ac5cba2a59a48621651`、tree `ee06773e3486785eb09c6bc1e86dddaf0ea6f7b4`，独立代码检出`/private/tmp/plan74-atomic-source.SG7Xnb/code`，未建立另一套宿主。新动作保留一消息一提案，支持既有本书包、通用源复制及首次本书收藏包的保存/换绑；从固定基线取词条，完整绑定CAS，事务失败整项回滚，补偿同时恢复绑定与资料。资产查询提供真实bound_version，回执返回实际target版本。旧绑定动作的逆向标量在ORM修改前冻结，共用绑定版本解析，移除等价旧片段。

- 工作区初轮临时库暴露三个冲突分支缺少`current`参数、一个注入异常同样漏参，以及跨书用例预先建立无效绑定，不能记为通过；[初轮失败](atomic-database-initial-failure.log)保留。主代理修正异常合同及跨书合法基线后，完整私有库/受控选区/正文领域临时库重跑退出0。
- 提交树固定锁文件离线安装：64包复用、0下载；前端168文件1531项、typecheck、202模块build退出0，[日志](atomic-source-frontend.log)。JS SHA-256仍为`f86fd50614765abc4c80017ac6393818ac255e167201ade023e497e2e110b4b5`，包含尚未部署的F11前端。
- 提交树Python全量：3195通过、330跳过、4项既有弃用警告，退出0，[日志](atomic-source-backend.log)。跳过项不冒充产品或数据库通过。
- 提交树临时库`plan74_v12_44994a91ef7a4bc3_test`升级0056后，`tests/private_library tests/test_selection_edit_domain_integration.py tests/test_domain_integration.py -o addopts=`共342通过、1项既有警告、退出0，[数据库日志](atomic-source-database.log)。包含19项新增PostgreSQL用例：旧固定v2/根v4、完整未修改词条保持、各usage、复制/收藏、跨书/归档/版本拒绝、幂等、整体撤销及后续根/绑定冲突、故障注入回滚。只删除该精确临时库；此前两次工作区临时库也已精确删除，不涉及正式业务数据或卷。
- `test_skill_contract`及私有库合同23项、维护Skill/注册/访问/工具80项通过。skill-creator验证器最初因项目及工具Python都缺PyYAML未运行成功；仅在`/private/tmp/plan74-skill-validator.URMBQa`安装验证工具依赖PyYAML 6.0.2后，最终Skill校验输出`Skill is valid!`。项目依赖、manifest、Skill名称/版本、注册和安装器无改动；参考更正唯一提案、固定基线和`proposal.version → proposal_version`映射。
- 同源`package_plugin.py`退出0，源与包内Skill两文件SHA一致：主文件`9ca832b9902ca7d9d33f39441b603ee04a2bde78b237ef7945d023ff4634c752`，参考`1635bb3a3322848b13039ce1f0ef8ebf258c073234cba9a0f4e9d4de27f55c38`。独立检出status为空，diff检查通过。

这些是代码证据，尚未公开更新或调用正式模型复验F11/F12；正式33ca983及计划76在途音色链保留。下一次更新需重新备份、复核逐Agent选择/模型及实际Skill内容，完成自然语言一次修改并生效和撤销，不能以新动作存在代替G3。新动作一次只处理一个词包（同包可多个词项），不承诺跨多个词包一次保存并换绑；本书包标题/标签仍沿用既有保存服务的当前根元信息行为，固定基线隔离的是词条与规则。

## 完整依赖与维护上下文准备复验

33ca983在`/private/tmp/plan74-integrated-source.HovjgJ/code`完成固定锁文件离线安装（64复用／0下载）、前端168文件1530项、typecheck、202模块build、Python全量及打包，全部退出0。[前端](integrated-source-frontend.log)／[后端](integrated-source-backend.log)。同一提交树临时库`plan74_v12_0d5c031db3564773_test`升级0056，私有库、受控选区、正文领域及新增依赖的narration worker／production_runtime数据库代码回归全部退出0，随后只删除该临时库，[日志](integrated-source-database.log)。没有连接正式业务库运行pytest。

6e45e2f只改私有库ref协调器、状态条及测试（计划范围同步），未改后端／schema／Skill／注册／依赖。新增假时钟用例实际在旧代码失败：应准备第二份ref但仍只有1次；真实状态组件期望“等待维护上下文”却仍固定显示已启用。修复后定向20项通过；测试覆盖后续ref不复用已发送ref、失败停止自动重试、显式重准备、切书／切Agent／退出／卸载清理；正文／选区ref不新增闲置续期。它不证明宿主发送时一定携带ref，正式丢失原因仍待证据。

独立源`/private/tmp/plan74-context-source.oU9WC6/code`前端168文件1531项、typecheck、202模块build、Python全量、package_plugin退出0，status为空。[前端](context-readiness-source-frontend.log)／[后端](context-readiness-source-backend.log)。`git diff --exit-code 33ca983 6e45e2f -- backend tests skills plugin.json pyproject.toml pnpm-lock.yaml`无差异，数据库代码结果按相同范围复用；没有为提示变更新建数据库或改变正式环境。UI保持原三行状态条高度，失败按钮放于说明行，视觉仍待正式复验。

## F10无效重试前置检查

3383bcd只修改runtime／review／surface及测试、计划74。显式重试先检查原选区TTL、当前作用域及完整字段hash，再进入生成；失败保留当前候选和已选决定，不续期旧绑定或猜测新选区。准备期间退出／过期零新增模型调用；连续点击合并，仍有效的失败允许再次生成。按钮改为“重新检查后生成”，不再承诺能自动把旧区间套到新稿。

- 定向3文件68项、工作区前端1527、类型／构建退出0。初写两个新增测试误用领域事件而非真实surface动作，改为`decide/apply-accepted`后通过；未放宽产品断言。
- 精确源独立检出前端168文件1526项、typecheck、202模块build退出0，[前端日志](retry-preflight-source-frontend.log)；Python全量退出0、4项既有弃用警告，[后端日志](retry-preflight-source-backend.log)；同源package_plugin通过，status为空。
- `git diff --exit-code 77870d4 3383bcd -- backend tests skills plugin.json pyproject.toml pnpm-lock.yaml`无差异，314项数据库代码证据按其相同后端／迁移范围复用，不创建额外库，不连接正式库执行测试。
- 正式只读确认首章仍draft4／4394字／hash0873af2850b92e0592295e2883133cade6e2b2831295cf7075534d6bde750d33；旧已采用整章候选不足以证明“按新规则采用新候选”，后续仍需正常真实写作链。未调用模型／安装本候选，F10不记产品PASS。

## F08／F09精确提交树复验

`77870d41ebb24f666f5507a3527d6b6c34e5bfaf`独立检出`/private/tmp/plan74-final-source.jn7Nb1/code`，未包含计划79工作区候选，检查后status为空；没有建立第二套QwenPaw环境。

- 原锁文件离线复用64包、0下载；168文件1521项通过，typecheck、202模块build退出0。[前端日志](locate-intent-source-frontend.log)。工作区1522与这里1521的差异来自未纳入的朗读任务用例。
- 同一源树用项目解释器运行`-m pytest -q`全量退出0，4项既有弃用警告；未提供数据库的跳过项不记通过。[后端日志](locate-intent-source-backend.log)。
- 同一源树临时库`plan74_v12_78be29b75b134415_test`升级0056后，私有库／选区／正文领域314项代码检查通过，随后只删除该临时库；没有对正式业务库运行测试。[数据库日志](locate-intent-source-database.log)。
- `scripts/package_plugin.py`退出0，包只来自本次干净构建；JS与tree见[来源](source-manifest.md)。正式锁已交其他任务，未为了复验再安装或重启。

## 已执行

2026-09-13后续F08／F09工作区检查（尚非正式复验）：F08合并原句选择的同步呈现与显式滚动请求，移除重复dispatch；弹窗动画关闭后再定位，普通关闭保留焦点恢复，切章使旧回调失效。定向62项、前端全量168文件1522项、typecheck与202模块build退出0。F09补充常见“修改……为……”识别，否定／假设／引用／询问在接受与撤销之前拒绝；已明确修改后的完整“不要改其他包”范围限制不否认该修改。定向76项通过，包括同请求应用、拒绝旧提案应用和拒绝撤销补偿。工作区全量含其他任务代码，最终发布必须另从精确提交复验；未据此关闭正式F08／F09。

| 范围 | 实际命令／结果 |
| --- | --- |
| Python全量 | `.venv/bin/python -m pytest`：3131通过、297跳过、4项既有弃用警告，18.83秒，退出0。跳过项不记通过 |
| PostgreSQL领域及选区链 | 用本文目录`run-code-database.py`执行`tests/private_library tests/test_selection_edit_domain_integration.py tests/test_domain_integration.py`：263项通过、退出0；包括13项私有库真实PostgreSQL用例、既有选区持久化／并发／恢复和正文领域链 |
| 前端页面接线 | `pnpm exec vitest run frontend/src/creative-center-private-library.test.ts`：4项通过；完整详情不截断、服务端分页／修改后重置、迟到查询及可见开关错误 |
| 章节候选接线 | 逐项决定／报告CAS重查与真实`ChapterWorkflowPanel`定向29项通过；迟到采用响应不能回写新页，不重调模型 |
| Workbench实际保存入口 | `pnpm exec vitest run frontend/src/workbench-private-library-save.test.ts`：15项通过；切章、IDB延迟、AI后连续手写、待选择恢复、冲突转手写、撤销前／中和读取失败 |
| 前端全量／类型 | 最终`pnpm test`：167文件、1492项全部通过，4.07秒；`pnpm typecheck`退出0 |
| 合成语料校验 | `validate_fixtures.py`退出0；清除4个新文件末尾多余空行并同步manifest的hash，无语义改变；10匹配／10生命周期／28维护场景与1000条规则、10000字的固定生成规格保持 |
| 前端构建 | `pnpm build`：202模块，退出0；当前工作区`frontend/dist/index.js` SHA-256 `f5ae18bedceff76183d5736c58b494ef3bae1650ec95c6b52670706541a17595`。尚非发布候选hash |
| 包审核 | `.venv/bin/python scripts/package_plugin.py`退出0；输出仅为工作区构建，未安装 |
| Diff检查 | `git diff --check`退出0；最终提交前仍需复查 |

数据库只创建本轮精确命名的专用代码临时库。最终通过运行使用`plan74_v12_7330ce60b73c4796_test`，从空库升级至0056，执行完成后已删除该唯一临时库；正式库未修改。凭据仅通过进程环境传入，没有写入报告或输出。

## 发现、修复与重跑

- 首轮受控保存/目录数据库定向64项通过；之后扩大到完整领域链发现旧选区持久化断言未包含服务端新增的genre/subgenre和空规则快照。按确切合同补全预期，未删除模型证据／失败／恢复／Diff断言，重跑263项全部通过。
- 前端全量初次暴露两处旧章节面板请求stub缺少当前`/library-checks`；补足真实请求和完整候选fixture，并追加迟到响应与报告CAS用例。新页面fixture缺少`current_version_id`及ES目标不支持`Array.at`也已修正。
- 只读汇合复核发现旧保存定时器未绑定章节、CAS完成后未重查页面、旧普通稿排队回退、隐藏恢复稿被激活和可变绑定回执覆盖。补修后以真实Workbench函数和回调驱动异步边界；宿主／HTTP／IndexedDB使用可控I/O，不能称为浏览器或正式写作证据。

## 复用证据的边界

本轮未改scanner、renderer、0056迁移和维护Skill，不能借修复改写已执行迁移。扫描器`lexicon_matcher.py`的开工tar快照与当前文件SHA-256同为`1f62cf58533035b4f769a8de011ce690a941b1120c47bde66ad4a9668b85b040`；原固定语料性能只按原范围引用，不外推网络/数据库/大库产品表现。

全部子代理已停止写入，最终前端全量／类型检查与暂存diff检查通过。随后完成下节独立提交树复验；正式桌面与真实写作链仍未执行。当前正式库schema只读复核为`20260913_0056`，它不证明新修复已部署。

## 独立提交树复验

提交`ea02b99e9793fa8da1dee457ce0f62f3d8bf0129`，tree `23dd0d85fcbe022a0d9f70a0a3e8e4a96d455297`；从它创建只做代码验证的detached worktree `/private/tmp/plan74-committed-source.Qv4ure/code`，没有建立任何第二套QwenPaw运行环境。

- pnpm离线安装使用原锁文件，复用64包、下载0；不添加依赖。确认Python导入来自该检出的`backend/__init__.py`。
- `pnpm test`：165文件、1461项通过；`pnpm typecheck`通过；`pnpm build`：200模块通过。
- 先完成前端构建，再运行项目解释器`-m pytest`：3124通过、291跳过、4警告，18.77秒。首次过早运行全量时，唯一失败来自打包合同所需`frontend/dist`尚未构建；完成构建后原样重跑通过，没有放宽断言。
- 同一提交树临时数据库运行上述263项领域／选区／私有库用例全部通过，库`plan74_v12_b685934865974fc4_test`已删除，正式库未改动。
- `scripts/package_plugin.py`审核通过，检出树`git status --short`为空。前端JS SHA-256为`ecc1e4cf023979d8dbd0ff6688ee5ee14cd49142f8a7e6217888df01fb8f3b4a`；包及来源见[source-manifest.md](./source-manifest.md)。

两组测试数量差异来自精确排除了外任务作品资料及朗读续播源码／测试，不是跳过私有库失败用例。此时提交树代码可独立构建，但部署它会遗漏正式已用外任务功能，因此当时G2-B发布源门禁HOLD；不能仅凭代码绿灯继续安装。

## 批准依赖后的完整提交树复验

作者本轮同意单独提交正式已有依赖。`96b8aed`在`/private/tmp/plan74-complete-source.8dnb1X/code`重新检出，status为空。使用原项目解释器和原锁文件，前端离线复用64包、下载0，typecheck通过，167文件1492项通过，构建202模块；Python全量退出0（4项既有弃用警告），同一源树打包成功。日志见[前端](complete-source-frontend.log)、[后端](complete-source-backend.log)。

该源树再次运行相同263项真实PostgreSQL代码用例，退出0；临时库`plan74_v12_423bc2982888442d_test`已精确删除，未连接正式业务库执行用例。见[日志](complete-source-database.log)。metadata的6项旧独立端口数据库用例本轮仍跳过，不计入这些私有库专项；其已上线行为来源为计划70现有正式证据。

完整G2-B通过，随后安装的是这次构建，不是旧独立包或脏工作区。正式运行合同和真实桌面仍分开计数，见[发布记录](formal-release.md)。

## F01修复提交的独立复验

`6c63ac650044e0cdf663121208d8e57c1a59c737`，tree `a906436d416f947fe7c0998dd95a9b088740f898`；独立检出`/private/tmp/plan74-capture-source.i7Vzhx/code`。新增14项capture用例与既有10项绑定用例共24项定向通过；工作区Python全量及277项数据库代码检查退出0。随后在该精确提交树重跑：

- `-m pytest -q`退出0、4项既有弃用警告；[后端日志](capture-fix-backend.log)。未把未提供数据库的跳过项记通过。
- 相同领域／选区命令增加14项后共277项真实PostgreSQL代码检查通过；临时库`plan74_v12_7e4e59c563484a2e_test`已精确删除。[数据库日志](capture-fix-database.log)。
- 离线固定依赖复用64包、0下载；167文件1492项通过、typecheck／202模块构建／package_plugin均退出0；[前端日志](capture-fix-frontend.log)。JS仍为`f5ae18bedceff76183d5736c58b494ef3bae1650ec95c6b52670706541a17595`，未夹带工作区新的朗读修复。

本提交代码复验PASS；正式prepare发现新外任务来源漂移，未安装，因此不能记F01产品PASS。小窗口审阅工具栏裁切在正式截图复查中另记未修复项，不受这些代码结果覆盖。

## F02／F03界面修复代码复验（后续目标轮）

正式来源HOLD仍在，继续只做本计划内可独立推进的界面修复。`859a643`把正文选区工具栏原视口1100规则替换为已有编辑区840容器规则，保留换行覆盖且避免长按钮挤出；不平行堆叠一套旧断点。容器／审阅／实际保存定向44项、前端1493、类型和构建通过。该提交独立检出再次前端1493、Python全量、类型／构建／包审核退出0。

`682fc604366070db5f0daf7b6515ff48480fd7f6`继续更正助手私有库范围状态条：读同一个选书状态并订阅切书／清空，不改上下文或工具权限。路由／上下文ref／私有库页面／容器定向29项通过，新增真实状态组件的切换与卸载取消订阅用例。

最终精确检出`/private/tmp/plan74-ui-source.2hohEa/code`，tree `c92efbc5c8c75ac4833c5b5f2254b7c1b24f3266`，status为空；离线64包复用、0下载；前端167文件1494项、typecheck、202模块构建、Python全量及package_plugin退出0。见[前端日志](ui-fixes-frontend.log)与[后端日志](ui-fixes-backend.log)。JS SHA `6c6827cd323cbc55bc873f87573c2f48ea1e032b783f71d93a27838a766aaf55`。

已用Git比较确认自6c63ac6起backend、tests、Skills、manifest、Python依赖和pnpm锁文件无差异，277项PostgreSQL代码结果按该相同后端范围复用，本轮不再创建数据库或写正式业务。以上均非视觉／正式维护PASS；候选未部署，需依赖来源解阻后整包正式复验。
