# V1.2源码与发布来源清单

日期：2026-09-13。状态：`SOURCE COMMITTED / CODE VERIFIED / RELEASE HOLD`；已有精确源码commit和独立构建包，尚无本轮正式安装回执。

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
