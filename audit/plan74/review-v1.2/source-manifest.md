# V1.2源码与发布来源清单

日期：2026-09-13。状态：`96b8aed RELEASED / 6c63ac6 VERIFIED BUT SOURCE-HOLD / G3 OPEN`。作者本轮“同意”已解除原作品资料／续播来源HOLD；新的失败句段重制依赖在F01重发前出现，未在此前授权内，故暂停安装。详见[formal-release.md](formal-release.md)。

## 本轮批准与完整候选

- 仅补交正式已上线的作品资料和朗读续播：`96b8aed87baa1f370f76b5e34699d061b67909d5`，tree `bcc2dc9bb289c84f7d95ba78e7572d91c2e1b0e9`，16文件。未纳入compose语义路由配置；未继续计划70的新功能或质量修复。
- 完整独立检出`/private/tmp/plan74-complete-source.8dnb1X/code`，前端1492项、Python全量、临时数据库263项、类型、构建及打包退出0。JS SHA-256 `f5ae18bedceff76183d5736c58b494ef3bae1650ec95c6b52670706541a17595`。
- 新包`/private/tmp/plan74-v12-release.VlD8BU/candidate.tar.gz`，SHA-256 `8be7e89d651b8ac08761108c8d0ea7ed809793dab673e528ca12b0d2f46bd32a`。14:54正式公开热更新成功，安装文件与完整包一致。原`ea02b99`私有库单独包仍不可用于替换正式环境。
- 本阶段按§14.6由主代理串行承担Git、备份、共享正式环境和最终集成，不再派发并行写入。下文未提交归属表和询问为批准前历史，以上批准只覆盖明确依赖。
- F01修复`6c63ac650044e0cdf663121208d8e57c1a59c737`，tree `a906436d416f947fe7c0998dd95a9b088740f898`，4文件（2后端、14项用例、合同补记）。独立构建277项数据库／前端1492／Python全量／类型／打包通过；源码检出`/private/tmp/plan74-capture-source.i7Vzhx/code`，未安装。
- 新未提交外任务文件为`backend/narration/failed_segment_retry.py`和`tests/narration/test_failed_segment_retry.py`；正式运行已含前者。与compose原样保留，不暂存、不混入私有库提交。需单独来源协调后重建完整候选，不把此前一次批准扩张为所有后续依赖授权。

## 已核实来源

- 开工基线：`5692dbc03a4452f9e60648df56f3a81039b309df`；工作区已有计划74首发实现及证据，尚未由本任务提交。
- 独立宿主升级来源：`d6d1dba`、`2f9caa7`已经进入当前HEAD。其QwenPaw 2.2.1镜像与生命周期证据属于计划78，不重复记为本任务施工。
- 开工未提交源码可恢复快照及SHA见[baseline.md](./baseline.md)。本轮改动由该快照与当前diff双重核对，禁止整目录暂存。

## 共享hunk及外任务依赖

| 文件／范围 | 归属及处理 |
| --- | --- |
| `backend/app.py`的novel_metadata_router导入／注册 | 计划70作品资料；不署为计划74。其独立模块`backend/novel_metadata_api.py`、`backend/novel_metadata_service.py`和`tests/test_novel_metadata.py`也不在本任务提交范围 |
| `frontend/src/workbench-studio.ts`两处NovelMetadataEditor接线，`novel-metadata.ts`及测试 | 计划70作品资料；原样保留，正式已用功能不能因本轮发布消失 |
| `frontend/src/workbench-v2.ts`的reuseExistingAudio接线、narration恢复独立模块及相关测试 | 计划70朗读恢复；原样保留。该文件的私有库定位与受控保存接线属于计划74，必须逐hunk区分 |
| `compose.yaml`的AI_NOVEL_CHAPTER_SEMANTIC_ROUTING_ENABLED | 其他写作路由任务；不提交、不改配置，不因本轮修复重启宿主 |
| `docs/开发文档/README.md`计划70状态行 | 外任务文档；保留而不以本任务提交覆盖其归属 |
| 生命周期脚本和测试中的private-library-maintenance及三项维护工具清单 | 计划74首发必要注册合同；只提交对应清单hunk，不顺带改变计划78生命周期逻辑 |
| `backend/narration/novel_deletion.py`私有库证据销毁保护 | 虽位于narration目录，新增guard明确属于计划74；不误归为朗读修复 |

G2-B发布前必须取得已上线外任务依赖的可重建Git来源；若仍未提交，先解决来源协调，不偷偷夹带、也不发布会退掉现有功能的包。本表不是额外任务施工或提交授权。

## 提交树与包

- 本任务源码提交：`ea02b99e9793fa8da1dee457ce0f62f3d8bf0129`；tree `23dd0d85fcbe022a0d9f70a0a3e8e4a96d455297`。共138文件；共享的app、workbench和开发索引按hunk暂存，计划70／compose改动仍在原工作区未提交。
- 独立代码检出：`/private/tmp/plan74-committed-source.Qv4ure/code`，已通过[提交树复验](./code-validation.md#独立提交树复验)。保留该目录供复核，不含正式数据或密钥。
- 包：`/private/tmp/plan74-committed-source.Qv4ure/ea02b99-plugin.tar.gz`，SHA-256 `ddf568e3c9327d7f18eda644c9128a2e062690732c9b1e0a115ea8ebd831ce52`。此包不包含外任务未提交功能，标为不可安装，不是正式发布包。
- 正式安装：`NOT_RUN`；本轮没有重启、更新宿主、修改业务数据或调用模型。正式0056只读核验保持。
- 已向作者请求窄范围决定：是否允许把正式已有的作品资料／朗读续播改动作为依赖单独提交。未得到回复，不夹带提交，也不让正式功能倒退。

后续证据提交与源码提交分开。Git远端验证记录补在本页末尾；代码push本身不关闭正式G3或整项W5。

2026-09-13已执行`git push origin main`，随后`git ls-remote origin refs/heads/main`返回`ea02b99e9793fa8da1dee457ce0f62f3d8bf0129`，与本任务源码提交完全相同。本页和最终状态更新另作纯证据提交，不改变已验证代码树。

2026-09-13本轮已将批准依赖`96b8aed`和F01修复`6c63ac6`一起push，随后实际`ls-remote`确认main为`6c63ac650044e0cdf663121208d8e57c1a59c737`。后续纯证据提交不改变该候选的源码／包内容；新朗读依赖与compose仍不在本轮提交范围。代码已push不解除F01重发来源HOLD、桌面裁切或未完成真实链门禁。
