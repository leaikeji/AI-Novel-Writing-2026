# 计划69施工与验证记录

日期：2026-09-11（Asia/Shanghai）。范围：计划69四个维护／验证脚本及对应测试；不发布计划70、不调用模型、不修改正式数据或QwenPaw核心。工作区已有计划66／70改动，不归入本次施工。

## 代码交付

- INSTALL：沿用v1快照；明确持久输出，拒绝覆写、错误宿主／Agent、既有Agent空目录与无基线替换；标准库进程锁覆盖捕获至读回。
- RESTORE：公开批量接口仅恢复专用Agent的项目Skills；显式关闭保留，新发布模块单列；错误后先读回，最多一次差异补偿。不会借窄恢复更新提示、模型或工具。
- OFFLINE：替换前要求冻结快照，保持“不启、不停宿主”；返回`pending_skill_restore`，按原发布流程启动后执行同一窄恢复，不伪装完整PASS。
- VERIFY：分别报告`state_preserved`、`writing_skills_ready`与`scope_isolated`。无基线为null；全关可保态成功但不就绪；可选分类Skill关闭不使无关主任务一并失败。
- LIFECYCLE：现有隔离器增加`--skill-state-check`，复用上述真实项目函数；覆盖首次初始化、混合状态、重复热装、重启、全关、卸载零残留、基线重装、离线替换与其他Agent前后状态。测试适配仅限本项目模块与独立资源，未改宿主导入器或核心。

## 自动化结果

| 实际命令／范围 | 结果 | 证据／边界 |
| --- | --- | --- |
| 安装／恢复／验证三组pytest | 142 passed | [JUnit](./plan69-unit.xml)；无真实模型 |
| 现有隔离器定向pytest | 77 passed | [JUnit](./plan69-lifecycle-unit.xml)；Fake公开I/O执行真实项目函数，不是Docker PASS |
| `.venv/bin/python -m pytest -o addopts='' -q --tb=short` | 2795 passed，263 skipped，3 warnings | [JUnit](./plan69-backend.xml)；数据库等可选运行前置未具备的测试跳过，不能声称全部集成验证通过 |
| 现有项目Node路径下pnpm typecheck／test／build | 全通过；153测试文件、1308 tests；build 190模块 | 本轮无前端源代码变更；直接pnpm最初因PATH没有node失败，复用项目`pnpm_environment`后通过，未加依赖 |
| `.venv/bin/python scripts/package_plugin.py` | PASS | 仅本地打包，没有正式安装 |
| 四个脚本Python3.11语法解析 | PASS | 实际测试解释器为项目Python3.12；语法兼容检查不是Python3.11真实运行证明 |
| 隔离器`--mode dry-run --skill-state-check` | PASS | 无Docker动作；候选head `20260911_0053`，tree `89ee005d33fb42f2a8efcb8cb87ba5306423a2c09161666fd4a29443e84c8002`；dry-run本身不写transcript |

## 正式当前状态与UI

仅GET公开Agent／Skills接口：[状态摘要](./plan69-public-check.json)。11项已启用、主任务方法可用、其他Agent没有项目Skill启用；`state_preserved=null`，因为没有本次正式替换前基线。主方法文件核查来自本地候选，未把它说成已安装包逐字一致。

截图步骤与逐步评价：[技能页复验](./plan69-ui.md)。桌面、正常刷新通过；390×844状态可见，但当前Agent名称随收缩侧栏隐藏，登记U016。没有再次开关Skills，没有进入QwenPaw助手；完整键盘／读屏恢复路径未验收。

## 测试环境障碍

为补数据库测试，先后创建两个精确标注`s6920260911`的独立PostgreSQL容器（有／无tmpfs各一次），均停留`created`、PID0、无日志。测试库迁移在建立连接时失败，没有执行DDL。已按核对后的精确ID删除本轮容器及新建匿名测试卷；查询该标签为空。仅终止本轮两个悬挂Docker客户端，没有重启Docker或操作正式容器／卷。两种挂载均失败，不能归因为tmpfs。

最后一次真实安装生命周期尝试使用现有隔离器与内部网络，不映射宿主端口。结果见下节；若环境启动失败，不将离线逻辑测试或历史诊断PASS替代本次真实验收。

## 真实生命周期结果

本次`s69real0911`退出码1：`COMMAND_EXECUTION_FAILED`，失败步骤`start-postgres`。Docker服务和两镜像预检通过，创建内部网络／卷成功，但PG的`docker run`在90秒超时；容器仍为`created`，没有日志，不是已发现的插件或Skill恢复失败。QwenPaw容器尚未创建，安装、恢复与真实离线测试均未执行。原始证据：[真实运行JSON](./plan69-lifecycle-real.json)。

精确清理PASS：删除本次1个未启动PG容器、5个新建命名卷、1个内部网络；结束后分别按本次所有权标签查询容器／卷／网络均为空。均为本轮可重建的测试资源，无正式数据；未做prune、Compose重建或Docker重启。

最终裁决：`CODE_VERIFIED / REAL_LIFECYCLE_HOLD`。S001不关闭，计划70不因此获准跳过前置门禁。接下来先解决Docker新容器启动阻断，再用新run-id／新transcript重跑同一隔离门禁；若处理需要重启Docker、影响唯一正式环境，必须先明确维护授权与恢复安排。

收尾检查：`git diff --check`通过；本轮计划／UI／验证文档本地链接检查通过，状态与审查台账／开发索引已同步。已复核本次四脚本及相关测试diff，原有计划66／70改动保留，未暂存、提交或推送。
