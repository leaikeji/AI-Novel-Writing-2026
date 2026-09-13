# V1.2正式发布门禁

日期：2026-09-13。状态：`96b8aed RELEASED / 6c63ac6 SOURCE-HOLD / G3-F01-HOLD`。

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
