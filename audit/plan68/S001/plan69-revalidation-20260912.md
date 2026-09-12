# 计划69：Docker恢复与真实安装续验

日期：2026-09-12（Asia/Shanghai）。状态：`REAL_LIFECYCLE_PASS / S001 CLOSED（键盘专项退出范围）`。授权：作者明确“同意：安装插件、操作 Docker”；续验后又明确桌面键盘专项不重要、不再要求。本轮执行计划69既有W3，主代理串行操作；不发布计划70、不调用模型、不改写正式小说。

## 1. Docker阻断恢复

- 已核实：Docker Desktop显示running，Server 29.7.2；原有3个容器运行。项目QwenPaw和PG健康，3个容器重启策略均为`unless-stopped`。
- 最小复现：独立`ai-novel-plan69-probe-20260912`只执行`/bin/true`，`--network none`、无正式数据挂载。`docker start`25秒超时；容器created、PID0、error为空。故障不只发生于PG入口／初始化，不能归因为PG迁移或应用插件。近期Docker API代理错误查询无输出，未获得更具体根因。
- 已执行：核对探针ID／标签后精确删除探针及其新建匿名卷；按用户授权与事前中断说明执行一次官方`docker desktop restart --detach`。没有prune、清空数据、更新镜像、改写宿主核心或重建正式容器。
- 恢复结果：Docker SessionID已变化；`tomato-novel-webui-docker`、`ai-novel-2026-qwenpaw-lab`、`ai-novel-2026-postgres`全部自行恢复，后两者healthy，原先停止的showcase容器保持停止。随后同镜像独立PG及QwenPaw正常启动。
- 技术判断：本次Docker运行态的新容器启动阻断经正常重启解除；具体内部根因未确定，不把恢复成功说成已定位Docker底层缺陷。

## 2. 冻结候选与实际验收

复用2026-09-11已测试候选，未重复打包或重跑无变化的代码测试。dry-run重新核对：

- tree SHA-256：`89ee005d33fb42f2a8efcb8cb87ba5306423a2c09161666fd4a29443e84c8002`。
- Alembic head：`20260911_0053`；11项发布Skill。
- 真实run-id：`s69real0912a`。
- 真实命令：项目解释器执行`scripts/tts/verify_qwenpaw_plugin_lifecycle.py --mode real --candidate <本项目build/ai-novel-world-2026绝对路径> --run-id s69real0912a --skill-state-check --transcript <本目录plan69-lifecycle-real-0912a.json绝对路径> --confirm RUN-T1-GATE-ISOLATED-QWENPAW`。
- 结果：退出码0，`status=passed`，`failure_code=null`。原始[完整JSON](./plan69-lifecycle-real-0912a.json)与本目录6份`s69real0912a-*-skill-state.json`不可覆盖；不替换9月11日失败记录。

| 真实检查 | 结果 |
| --- | --- |
| 初始安装／专用Agent初始化 | 11项启用、主任务就绪 |
| 混合状态热替换及重启 | 10开1关精确保持，主任务就绪 |
| 重复热替换及重启 | 同一混合选择精确保持 |
| 显式全关热替换及重启 | `state_preserved=true`且`writing_skills_ready=false`，不强制启用 |
| 完整卸载 | 所有4个隔离Agent的项目Skill／Tool注册为空 |
| 根据既有混合快照重新安装 | 原选择恢复、主任务就绪 |
| 停机后离线替换 | 宿主仍停止，仅返回`pending_skill_restore` |
| 原流程启动后窄恢复 | `state_preserved=true`、`writing_skills_ready=true`、`scope_isolated=true` |
| Default、QA及观察Agent | 最终全部Skill开关与初始基线一致 |
| 隔离测试哨兵／小说路由 | 原runner既有数据保持与可用性检查通过；不是正式小说数据 |

## 3. 清理与正式环境

清理PASS：临时离线安装辅助容器在其流程内已移除；runner按精确名和双标签移除本次2个运行容器、5个卷和1个内部网络。之后按run-id分别查询容器／卷／网络均为空。均是本次可重新创建的测试资源；无正式数据卷删除，不涉及用户小说恢复。

Docker恢复后对正式环境执行`verify_qwenpaw_lab.py --skills-only`，退出0：11项仍为true，主任务就绪、作用域隔离；无本次正式替换基线，`state_preserved=null`，不冒充正式插件替换证据。正式插件未重新安装，只经历Docker正常重启。方法文件校验来自本地候选，不证明正式已安装包与候选逐字一致。

计划69改动位于维护／验证脚本，不需要为了使这些脚本生效而替换正式PawApp；当前build还包含未发布计划70候选，故本轮只在隔离环境安装，未夹带发布到正式环境。未执行正式迁移、未变更模型、未使用QwenPaw助手、未提交／push。

## 4. 收口裁决

Docker启动阻断与计划69真实安装生命周期阻断均已解除。此前桌面当前状态与刷新截图继续有效，本轮未做UI交互。作者随后明确完整桌面键盘恢复专项不重要、不再要求；该项作为产品范围决定退出门禁，不表述为键盘可访问性技术PASS。手机验收也已按R026移出范围。S001最终状态为`CLOSED / REAL_LIFECYCLE_PASS`。

分类智能选择、实际模型注入和文学质量仍属于计划70后续门禁；本轮没有真实模型调用，不据安装PASS宣称智能路由或写作质量通过。失败补偿仍以既有定向自动化为证，不声称本轮额外进行了真实网络故障注入。
