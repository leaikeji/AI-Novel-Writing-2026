# 计划 77 正式发布记录

2026-09-12，状态：正式 UI 发布通过。作者本轮明确要求“帮我生效”；不包含 Git 提交／推送。

## 精确候选

- 使用计划 76 已发布源码作为基线，只叠加朗读前端目录内计划 77 的 29 个新增／修改文件（含测试）。未纳入工作区其他写作、后端或 Skill 候选。
- 发布包与发布前实际安装树逐文件 SHA-256 比较，唯一差异是 `frontend/dist/index.js`。后端、迁移、Skills、manifest、依赖和其余资源一致。
- 独立候选：`/private/tmp/reading77-release.rUDstb/source`。
- 正式 bundle SHA-256：`2602bf3ab572cdd75b7dbf6a91b68a3ce3790d684540c62550af7eededa76c50`；与候选一致。
- 候选归档 SHA-256：`91241d2acbad51396bd722dca3404e8ab6b664d71063702b0c1cc931b59b627f`。

## 验证与发布

- 独立候选 `pnpm typecheck`、`pnpm test`（154 文件／1336 项）、`pnpm build` 通过。与此前工作区 1344 项不同是因为排除了其他任务的候选测试，不是删减朗读覆盖。
- 用项目解释器运行 `scripts/package_plugin.py`，打包安全审计通过；`pytest tests/test_qwenpaw_integration_contract.py -q -k packag`：19 项通过。
- 初次临时目录执行 pnpm 触发依赖状态自动安装检查，因网络不可达中断；改为复用已存在的固定依赖并关闭自动安装检查完成验证，没有变更产品依赖。
- 使用当前已复核项目安装器的 `hot_install_packaged_plugin`，有安装互斥锁，公开 `qwenpaw plugin install --force` 返回 installed and loaded（hot reload）。没有直接覆盖已安装文件，没有卸载插件或重启容器。
- 初次发布辅助程序引用旧候选安装脚本，因缺少安装锁函数在任何正式写入前退出；修正为当前项目安装器后成功，未重复安装。
- 原容器 ID：`a874d5a19c130999388a9e9021a7c5496c9c17d85bc9c1798fadb564f654bbb5`，启动时间仍为 `2026-09-12T13:15:46.24776296Z`，healthy。
- 基础镜像仍为 `sha256:a7430e32833b6211f37200ee4e8c798946d8719772efcd650b92c1f663834fb3`。
- 聚合公开验收通过：health／朗读 backend／worker ready，9 个官方音色，11 个小说 Skills 与 5 个工具仅在专用 Agent 生效，写作模型仍为 `bigmodel/glm-5.3-flash`。
- 验收预期为 runtime=ready、product=ready、validation=disabled、reference-clone=ready；首轮错误使用 disabled 预期导致断言，按发布前已存在的 `reference_clone_ready=true` 修正后通过。没有修改旧兼容环境开关。
- 发布前后公开 overview 的 settings、authorization 完全一致。无数据库迁移、音频生成或清理操作。

## 正式浏览器

从创作中心选择当前作品的“朗读”进入，六分区全部可达：基础朗读、旁白音色、人物配音、私人音色、朗读规则、运行与存储。确认人物搜索入口与统一 Serena 名称、私人音色空态、9 个普通话官方选项、识别与发音切换及服务就绪显示。浏览器 error 日志为空。

- [正式基础页](./15-formal-basic.png)
- [正式私人音色页](./16-formal-private.png)

新标签冷启动直接访问 `/chat?...` 曾被宿主跳到默认会话；改从 `/apps/ai-novel-world-2026` 创作中心入口后正常进入。没有改写宿主路由，此历史入口行为未作为本轮修复项。原生聊天内容和模型选择正常显示，未发送消息。

没有实际新建音色或付费模型调用，不据此新增听感和生成全链通过结论。

## 恢复

恢复材料均在权限 0700 目录 `/private/tmp/reading77-release.rUDstb`：完整旧安装树、`installed-before.tar.gz`、`skills-before.json`、逐文件哈希和候选归档。

旧安装归档 SHA-256：`17e2bec751fc01dec6fa5f162cc928af45cab6adc72e363d80d905effdbffdea`。

需要恢复时使用项目解释器执行该目录 `deploy.py rollback`，经同一公开热安装接口重新安装旧树，并恢复快照中的 Skill 开关；无需倒退数据库或删除媒体。此次未触发恢复。
