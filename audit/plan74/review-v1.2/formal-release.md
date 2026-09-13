# V1.2正式发布门禁

日期：2026-09-13。最新状态：`33ca983 RELEASED / SOURCE-HOLD CLOSED / G3 PARTIAL`。下文旧HOLD记录是当时执行事实，不再构成再次索要作者授权的依据。

## 17:47完整依赖合并后的公开更新

- 源`33ca983bec44e0813f37f085826696c6ecd3d6d4`、tree `108e0231e67fd40647d6ef25cc53b4f28ab86bf5`。计划79已发布的13个源码／测试文件逐文件与其冻结发布源cmp一致，由主代理独立依赖提交，未纳入79／80文档及审计目录。包含本任务F08／F09／F10，不退掉正在使用的朗读能力。
- 独立检出`/private/tmp/plan74-integrated-source.HovjgJ/code`前端1530、类型／构建、Python全量、临时数据库相关回归及打包通过，status为空。包SHA `c124a3151a3754ac3dea00ce6d9a488f6d057827647597b0ab9810b420d05c9e`；安装差异仅`backend/private_library/maintenance.py`和`frontend/dist/index.js`，见[完整清单](integrated-release-manifest.json)。
- 新备份`/private/tmp/plan74-integrated-release.x2LJU0`，持久副本`/app/working.backups/plan74-integrated-release-20260913-x2LJU0`。DB SHA `6269c165c7547d9667ceed2544fec4af5e8de322bcc289923ea0a2d358bf4cd4`；旧插件SHA `1a49cbec6806091d7f378340bffa75dff2ab1c7ba35dda8b9a1a6a6413cb80ab`；备份目录及持久副本hash校验通过，未恢复数据库。
- 17:47:16经公开hot-install更新，[回执](integrated-install-result.json)state_preserved=true。release verify和完整公开验证脚本退出0，安装文件与候选一致；逐Agent选择文件cmp无差异，[健康](integrated-health-after.json)／[模型](integrated-model-after.json)保持0056、ready、bigmodel/glm-5.3-flash；容器ID、镜像及启动时间未变，无重启或迁移。公开完整校验结果为当次工具退出0，本次未另存它的终端全文，不伪造原始日志。
- 计划79完成的210/210句新音频保留。18:48—18:50重新加载页面后实际核对原句定位和明确助手维护，结果见[桌面续验](desktop-validation.md#33ca983完整发布后的正式续验)。原句可见定位PASS，助手缺失可信上下文拒绝、零资料写入，G3未闭合。
- 本轮结束后明确释放正式环境／数据库／本地模型／浏览器给计划76；对方承诺仅做私人音色链、不安装、不改74／私有库／第一章。后续维护上下文候选`6e45e2f`尚未安装，必须等待共享锁释放后再按同源／备份门禁更新，不为省事覆盖已安装副本。

进入本轮新创作以后继续保留正文、报告和音频，不以旧数据库恢复作回退。源码push已通过实际远端确认；后续文档提交不改变发布包。

## 16:38桌面与编辑器公开更新

- 精确源`1712883aae92d3049c4b45e2a979d1d03d1e36e7`、tree `ef181ce5a16857a38ce22f1905b0670c69f15733`；独立检出`/private/tmp/plan74-desktop-source.NzhMUK/code`。前端168文件1515项、类型／构建／包检查通过。Python首次两项安装合同失败与prepare共享锁运行重叠；两项单独复跑退出0，随后停止并行prepare完整串行重跑退出0，见[日志](desktop-source-backend.log)。没有跳过两项或修改安装器。
- 新备份`/private/tmp/plan74-desktop-release.Mj07IA`，持久副本`/app/working.backups/plan74-desktop-release-20260913-Mj07IA`；DB SHA `7795b9f4a2f0bc284151adcd802ba6e3c0c22d7f4b7ffb28b0e856c3c42ac251`，归档目录验证通过，未恢复数据库。
- 包SHA `998b7c021a7ea2eb52ec436622a99f7bafadcd5b32ae7de91bd4194322b348ab`，仅`frontend/dist/index.js`与原正式树不同。[完整清单](desktop-release-manifest.json)、[更新回执](desktop-install-result.json)。16:38:38公开hot-install，随后release verify及[公开合同复核](desktop-public-verify.log)退出0；逐文件／逐Agent选择／模型／健康／0056保持，无重启。
- F06受控恢复稿经正常“恢复本地稿”写入draft4、4394字，刷新保持；报告与正文同事务应用回执可复核，未转手写。进入写作后不执行旧数据库恢复或未经兼容核对的插件回退。
- 助手查询／修改／补偿撤销和桌面复验见[分项记录](desktop-validation.md)。明确指令分类与定位滚动仍有后续候选，不宣称整体G3通过。
- 16:50后本轮模型／工具操作已停止并协调释放唯一正式环境给计划79；其后续发布由所属任务负责，本记录只证明以上时点的1712883运行树，不能断言此后环境始终不变。新修复须等共享锁和新来源核对后再部署。

## 16:16完整来源公开更新

作者已全权授权本计划及正式测试，必要已部署依赖的来源协调与独立提交由主代理自主完成。已将正式现有失败句段重试依赖及测试单独提交`da36b47d475f46441f64cadea2389873457427f7`，未混入计划79未部署候选；与任务“设计 Qwen-TTS 云本地混合方案”协调独占正式安装窗口。

- 独立源`/private/tmp/plan74-authorized-source.oEyCy6/code`：前端1494、Python全量、临时数据库277、类型／构建／包检查通过。日志见`authorized-source-*.log`；SQL代码检查未连接正式库。
- 最新备份`/private/tmp/plan74-final-release.jF2lcX`，正式卷副本`/app/working.backups/plan74-final-release-20260913-jF2lcX`；数据库归档`5301fac1d9267c096fdbef437c28a8e65cf46ea0561f1a46efbc632b21446111`，插件前态`af535937c7fe49f71deaccdc826dd8866cd28610f081bf1c4a1d8a4579dbe4ba`。
- [清单](authorized-release-manifest.json)记录commit/tree与全部文件hash；候选包SHA-256 `fb5541636bf6da7f0b8f91cb45a08f4635f80bcd60ba8085e4d70db156e04e38`；差异仅`creative_data_api.py`、`private_library/service.py`、`frontend/dist/index.js`。
- 16:16[公开更新回执](authorized-install-result.json)成功；`release.py verify`及完整`verify_qwenpaw_lab.py`退出0。正式安装树精确一致，三个Agent的模型、12项Skill、8项工具及提示文件选择全部保持，schema0056、健康ready、TTS ready，无容器重启／镜像变化／数据库恢复。
- 源码已push，实际远端main核对`da36b47d475f46441f64cadea2389873457427f7`。后续其他任务提交独立记录，不冒充本任务。

正式续验已验证收藏v8与绑定同步、归档停用和恢复不自动启用、1280审阅按钮可见；另发现收藏展开定位、私有库窄容器、导航范围通知及CodeMirror整文替换选区问题，正在按本计划补充工作包修复，G3尚未整体通过。原稿draft3未被失败采用覆盖；本地受控恢复稿和持久候选保留，不回滚数据库。

## 14:54及之后的历史过程

14:54通过公开热更新发布完整提交`96b8aed`。安装文件逐项一致，三个Agent的Skill、工具、有效模型和提示文件选择完全保持，正式健康ready、schema0056、TTS生产链ready；容器ID、image和启动时间未改变。真实桌面写作链正在执行，不能据此宣布整体G3通过。

此前的发布源阻断已由作者本轮“同意”解除：允许将正式已有的作品资料编辑和朗读续播作为依赖单独提交，再继续计划74。依赖提交`96b8aed87baa1f370f76b5e34699d061b67909d5`为16文件，不包含compose语义路由开关，也没有扩展计划70施工。

完整源树`bcc2dc9bb289c84f7d95ba78e7572d91c2e1b0e9`在`/private/tmp/plan74-complete-source.8dnb1X/code`独立检出。离线固定依赖、前端167文件1492项、类型、构建202模块、Python全量和263项临时数据库专项均退出0，随后由同一源树打包。相关日志和[发布清单](release-manifest.json)保留；metadata的6项专用旧端口数据库用例本轮未运行，不把它们计入263项。

## 新备份与恢复

备份根`/private/tmp/plan74-v12-release.VlD8BU`；更新前完整复制到正式备份卷`/app/working.backups/plan74-v12-20260913-VlD8BU`。仅本项目数据库和插件、公开配置，不读取QwenPaw私有配置或核心。

| 归档 | SHA-256 |
| --- | --- |
| database-before.dump | d308fd3681d4e12339f38ad77665e7cc704e81c603eac6a23e3ef8fc31ab6a51 |
| plugin-before.tar.gz | 70055a363795b3efaf0d0047505959ea3d160160e0503aa42e52b51d5c0733e3 |
| candidate.tar.gz | 8be7e89d651b8ac08761108c8d0ea7ed809793dab673e528ca12b0d2f46bd32a |

数据库custom归档头和`pg_restore --list`目录验证通过，未执行恢复。更新前无新活动业务任务；两项早于容器启动的历史selection_edit running原样保留。新旧运行树差异12文件，详见发布清单；不改Skills、注册、上游、schema或朗读模块。公开完整合同检查退出0，见[输出](public-contract-verify.json)。

[release.py](release.py)提供prepare/install/verify和仅限新写作前的rollback；参数为上述source、backup及完整commit，恢复插件仍走公开hot-install，不恢复数据库。进入本轮受控写作后，旧包不保证认识新的待保存元信息，不能直接覆盖安装；先保留本地稿／回执，核对兼容性并停用受影响入口。健康、文件、配置漂移或越界写入立即中止后续操作。

G3桌面和真实写作见后续分项记录。只读查询时通用资产含归档共13项，正式第101项之后的大库搜索仍无足够真实资料，不制造占位包凑数；该必验项保留，不能借263项临时库用例宣称正式大库验收通过。

正式F01：在《缺氧：末日地下世界》第一章收藏“电工胶布”并选择用于本书，收集词包升到v5，但本书仍固定v4；之后资料编辑升v7，仍未改变绑定。API此前以有novel_id就返回已用于本书，不能代表实际生效。已暂停模型调用／采用，保留两个真实模型任务、4处差异待审候选和4380字原文。修复须通过新代码门禁并重新备份公开更新，原96b8aed运行合同PASS不替代该业务项通过。

完整来源与可恢复代码／包位置见[source-manifest.md](./source-manifest.md)。

## F01修复重发前安全中止

15:26前后，对代码门禁通过的`6c63ac6`执行prepare，新备份`/private/tmp/plan74-capture-release.jJ6qpM`。数据库归档／目录和插件哈希校验通过；此时不执行install，未复制到正式备份卷，不把prepare记为发布完成。

预期运行差异只有creative_data_api和private_library/service，但清单还包含`backend/narration/failed_segment_retry.py`：正式SHA `a51e683a51bc7fbe68df554a74f8157c465696acffa797d28ea85d7d610abdee`恰好等于工作区另一任务的未提交版本；候选该文件SHA `0d33ab3aa068d640d4c74ff1d9ede4773e8ce6700f148b8f29f755e74d445c40`。它新增“此前仅Provider不可用不消耗首次音质重试”的窄例外，已超出本轮已批准补交的作品资料／续播依赖，不由私有库任务擅自提交或回退。

因此停止安装，没有运行rollback。先协调这项新依赖的独立Git来源／提交授权，再重新取得包含它的完整提交树，复验和新备份后才可重发。不能直接把两个修复文件写入已安装副本绕过公开部署。中止清单见[capture-fix-blocked-manifest.json](capture-fix-blocked-manifest.json)，包SHA `510981329405372e17b4f24dc30b8b88038d3fe49eed72b012f6e5deda73ea27`，明确不可安装到当前正式环境。

正式桌面实写及两项实际缺陷、候选与原稿保留状态见[分项记录](desktop-validation.md)。恢复安排是保留当前健康插件／数据及候选，解决源码依赖后前向修复；不得用旧数据库备份覆盖这次资料维护和后续作者创作。

后续目标轮只完成F02工具栏与F03助手范围提示代码修复，最新候选`682fc60`，前端1494、Python全量、类型／构建／包审核通过。新朗读依赖仍未提交也未获得补交授权，因此本轮未再prepare／install或执行正式写作，来源HOLD不变；两项界面修复尚不能记为正式PASS。
