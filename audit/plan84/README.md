# 计划84正式实施总回执

记录时间：2026-09-14 23:39—2026-09-15 01:11 CST

状态：`CLOSED_WITH_LIMITS`；作者接受F84-01的上游阻塞并停止本项目绕行施工。F84-02—F84-07拆分候选已完成代码QA与正式桌面矩阵，独立状态为`FORMAL_PASS_F84_02_07`；当前正式环境安装该拆分候选。

## 已完成

- 第七版全量候选的冻结身份、正式失败与回退历史见[candidate/README.md](./candidate/README.md)。
- 2026-09-15已从当前生产源码、测试和包中剥离F84-01，并修复搜索非空关键词竞态和建书连续关闭的同步互斥；F84-02—F84-07拆分候选的身份、全量测试与两路最终只读QA见[split-candidate/README.md](./split-candidate/README.md)。
- 拆分候选首次公开CLI热更新因草稿绑定前置不成立而停止并回退，完整历史见[首次正式尝试](./formal-split-attempt-20260915/README.md)。作者随后采用该草稿作为唯一验收草稿；重新安装同一候选后，F84-02—F84-07剩余桌面矩阵全部完成，见[正式完成记录](./formal-split-completion-20260915/README.md)。
- 发布前冻结了正式容器、上一插件、Agent／Skill／工具／prompt、数据库计数、目标私有库版本和唯一建书草稿；恢复命令见`/private/tmp/plan84-release-axbqjO/ROLLBACK.md`。
- 第七版经公开CLI原位热更新，安装树与候选一致；未重启容器、未卸载、不动数据卷。

## F84-01正式失败与边界

- 正式Edge 1920×1080从`/apps/ai-novel-world-2026`冷加载后，最终仍为裸`/chat/{sessionId}`和原生聊天，未出现创作中心规范参数与界面。
- 两次正式现象与QwenPaw 2.2.1公开插件生命周期／路由API共同支持“首轮宿主路由早于插件注册”的工程推断；公开API没有首轮路由前注册或未知路由重放合同。原始浏览器日志与截图当时没有归档到本仓库，因此不得把该时序写成由现存原始日志直接证明。
- 公开合同依据：[QwenPaw v2.2.1 Plugin System](https://github.com/agentscope-ai/QwenPaw/blob/v2.2.1/website/public/docs/plugins.en.md)，其中前端插件生命周期为宿主启动后再获取并执行bundle，路由API仅列`add`、`replace`、`wrap`和`remove`。
- 继续用Performance根URL、时间窗或当前裸session猜测入口会产生普通聊天侵占风险；修改上游核心又违反项目硬约束。因此F84-01按计划记`BLOCKED_UPSTREAM`，不是PASS。
- 第七版的URL门禁失败后没有继续执行其余正式交互；后来部署的拆分候选不含F84-01，因此其余六项可独立验收，但不能据此宣称F84-01通过。

## 当前正式结果

- 正式环境当前安装不含F84-01的拆分候选；结束验证器通过，容器保持原启动时间且healthy，Agent模型、12项Skill、8项小说工具、4份prompt和TTS状态无漂移。
- 数据库最终为作品根行6、建书草稿7、私有资产16、内容版本41；获准复用的草稿`7b520cff-0a54-423e-9a3a-c0e1cc52aa34`从version 2单次保存至version 3，未新增第二份草稿或完成作品。
- 排除运行时`__pycache__`／`*.pyc`后，当前安装树哈希为`6ee292e7…`，bundle与manifest为`f993d703…`／`79fae92a…`，与拆分候选冻结值一致；上一包恢复点及命令仍保留在`/private/tmp/plan84-split-release-WWWpeG`。

## 当前边界

1. F84-01继续登记上游阻塞，等待QwenPaw提供首轮路由前注册／重放的公开契约；
2. F84-02—F84-07已完成代码QA与正式产品矩阵，独立记`FORMAL_PASS_F84_02_07`；该结论不依赖也不掩盖F84-01。

作者已据此将计划84裁决为`CLOSED_WITH_LIMITS`。不得再次安装第七版，不把F84-02—F84-07的正式通过外推为`CLOSED_PASS`；除非上游公开合同发生可核实变化，否则F84-01不再进入主动施工。
