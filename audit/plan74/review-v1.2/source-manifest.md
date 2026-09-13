# V1.2源码与发布来源清单

日期：2026-09-13。状态：施工中；尚无本轮发布commit、包hash或正式安装回执。

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

## 待填写的交付对应

提交树全量验证、前端构建、包审核通过后再记录候选commit/tree、包SHA-256、公开安装回执、正式schema和逐Agent配置保持快照。后续证据提交与候选源码提交分开记录，push之后重新确认实际远端引用。
