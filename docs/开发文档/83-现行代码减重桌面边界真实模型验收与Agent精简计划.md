# 83 现行代码减重、桌面边界、真实模型验收与 Agent 精简计划

状态：`ACTIVE_CLOSEOUT`（作者已批准废弃代码核实与手机端专属代码移除；真实模型要求按可执行验收口径收敛；Agent 改写尚未部署）

版本：V0.1
日期：2026-09-14（Asia/Shanghai）

## 1. 目标与非目标

本计划只做现有工程减重和验收口径收敛，不新增产品能力、数据库表、模型选择器、Agent Runtime 或 QwenPaw 上游改动。

目标：

1. 从真实插件／前端入口核实生产模块可达性，移除已经被替代、未接线或只由自身测试引用的实现及冗余测试；
2. 删除手机／平板视口专属 CSS、触控优化和相应移动端断言；
3. 所有能够得出“真实写作效果／文学质量／模型链可用”结论的正式验收必须调用当前专用 Agent 的真实模型，并保存 requested／actual provider、model、请求证据和作者可见产物；
4. 精简“AI小说作家”Agent 的系统提示上下文，减少通用模板和重复规则对创作注意力的干扰。

非目标：

- 不删除为桌面窗口缩放、系统缩放、宿主侧栏／助手挤压服务的 container query；
- 不删除 `prefers-reduced-motion`、`forced-colors`、键盘焦点和可访问性规则；
- 不让单元、契约、迁移、失败恢复、安全边界或纯 UI 测试访问真实模型；
- 不把模型返回替代确定性断言，不为跑测试制造正式作品或反复消耗模型额度；
- 不覆盖作者以后对 Agent workspace 文件、模型或 Skill 开关的自定义。

## 2. W0 核实结论

完整证据见[`audit/plan83/README.md`](../../audit/plan83/README.md)。本轮不是按文件名猜测，而是建立静态 import 图：后端从`plugin.py`进入，前端从`frontend/src/index.ts`进入，并以全仓精确引用搜索、历史计划状态和替代链交叉复核。

- 后端现行非迁移 Python 共 223 个模块；199 个可从插件入口到达，24 个未到达项中有若干仅为 namespace `__init__`，最终确认 18 个生产／支持文件属于退役孤岛。
- 前端现行生产 TS 共 203 个；192 个可从入口到达，11 个未到达项中一项为测试 fixture；最终确认 11 个未接线实现／支持文件，另有一份只因误接全局样式而进入 bundle 的退役 lifecycle CSS。
- 第一轮共移除30个生产／支持文件、7,435行；同时移除14个只覆盖这些孤岛的独立测试文件及1个空测试包标记，并从混合测试中删除退役分支。历史迁移和验收原始证据保留。
- 这不等于“其余模块全部经动态运行证明必需”。结论是其余模块至少位于当前静态生产可达图；反射、字符串注册和按配置路径仍需由全量测试、打包与正式运行非回归补证。

## 3. W1 废弃代码移除范围

已确认并移除：

- MOSS／旧云端说话人分析孤岛：`cloud_analysis.py`、`speaker_model.py`、`anonymous_speakers.py`；
- 未接入现行 Qwen TTS 的旧声音 brief／instruction：`narrator_voice_brief.py`、`voice_brief.py`、`voice_design.py`；
- 被 evaluation v2／现行索引链替代或从未接线的 embedding v1 evaluation 与 `embedding/renderers/`；
- 旧受管写作准备候选 `writing_skills/dispatch.py`；
- 未接线的助手工具轨、建书草稿上下文副本、textarea auto-size、音色生命周期面板／状态／样式、大纲人物草稿目录。

禁止删除：Alembic 历史、`audit/`、开发文档证据、现行 schema 兼容字段、语义独立的负向／恢复／安全测试，以及仍从当前入口可达的代码。

## 4. W2 桌面 only 样式边界

已删除所有生产 TS 中宽度不超过 768px 的 viewport `@media (max-width: ...)` 手机／平板分支，以及`-webkit-overflow-scrolling: touch`、`touch-action`触控专属声明；同步删除只验证这些分支的测试断言。

继续保留：

- 840／900／980／1040px 的桌面窗口布局规则；
- 组件自身空间不足时使用的 `@container` 规则，包括 390px 的音色库组件内部降级。这里的 390px 指宿主侧栏和助手挤压后的组件宽度，不是手机视口；
- 桌面低高度、超宽屏、减少动画、强制颜色、滚动、键盘焦点及无障碍规则。

退出门禁：源码不得再出现手机／平板术语、<=768px 的 viewport width media query 或触控专属声明；真实桌面至少覆盖 1920×1080、2560×1440、200%缩放和宿主助手展开挤压。

## 5. W3 真实模型验收口径

“所有测试都调用真实模型”不能按字面落地：迁移往返、CAS、权限隔离、哈希、失败恢复、CSS、类型检查等测试没有模型语义；强行接入会让结果不确定、昂贵且无法证明原本的工程性质，也与本项目代码校验／正式验收分层冲突。

因此冻结为以下强制口径：

| 层级 | 是否调用真实模型 | 可以证明什么 |
| --- | --- | --- |
| 单元／契约／迁移／安全／UI／构建 | 禁止作为必需依赖 | 工程逻辑、边界和可重复性 |
| Provider 接线 smoke | 必须真实调用目标 Provider | requested／actual 身份、超时、错误与恢复链 |
| 产品／文学／Skill 正式验收 | 必须通过正式环境与`ai-novel-writer`真实模型 | 作者可见写作链实际工作；仍不自动证明文学质量 |

以后任何使用 fake／mock／stub／静态 JSON 的结果不得把产品、Agent、Skill 或文学质量标为 PASS。正式模型验收优先复用计划66《槐巷早饭》和计划68三卷九章中作者已拥有的素材，冻结小样本、最大调用次数、停止条件和作者审阅入口；不为了“全量”重跑数千个确定性测试。

## 6. W4 Agent 是否需要优化

结论：需要，但方向是减法，不是再增加一层 Agent Runtime 或继续堆规则。

当前仓库提示文件`qwenpaw-agent/AI_NOVEL_WORLD.md`约14.9KB，已经包含 Skill 路由、工具权限、受管模式、选区操作和回答边界；安装器只写入这一文件并追加到 system prompt 列表，未处理宿主自动生成的通用`AGENTS.md`、`SOUL.md`和未填写`PROFILE.md`。正式 Agent 因而同时承载项目规则、通用助理模板和空白人设，容易重复、冲突并浪费上下文。

拟定优化：

1. 只通过公开 workspace API读取文件与 system prompt 清单；
2. 记录宿主默认模板的精确内容摘要；只有文件仍与已知默认模板完全一致时，才从该专用 Agent 的 system prompt 清单中排除，文件本身不删除；
3. 任一文件被作者修改即视为作者资产，安装、升级和卸载都不得覆盖或排除；
4. 把`AI_NOVEL_WORLD.md`收缩为 Agent 身份、权威边界、Skill 选择原则和工具安全规则；具体写法继续归各版本化 Skill，避免两处复制；
5. 以同一冻结创作任务做现行／精简提示 A/B，真实调用同一个 requested 模型，记录 actual 身份、调用次数、Skill／工具证据、事实一致性和作者判断；不能只凭提示更短就宣布更好。

W4 会改变正式 Agent 的 system prompt 组成，因此在完成代码、测试和公开 API 回退设计后，部署前单独向作者展示精确 diff 与恢复路径；本轮不修改正式 Agent。

本节只处理专用 Agent 的提示上下文卫生；计划80的原生助手智能 Skill 路由仍是独立`PROPOSED`范围，不因计划83获准而自动施工。

## 7. 子代理并行施工设计

本轮不并行。删除范围横跨共享 import 图、全局样式和测试清单，且最终集成、全量回归、Agent system prompt 与正式环境均要求单一所有者；拆成多个写入者会增加漏删引用和误删现行路径的风险。

| 波次 | 工作包／标记 | 所有权与目标 | 门禁、测试与证据 |
| --- | --- | --- | --- |
| W0 | `P83-AUDIT / SER/GATE` | 主代理只读全仓，冻结入口、不可达集合、替代关系 | 不改代码；输出可复核清单 |
| W1 | `P83-DEAD / SER/MUTEX` | 主代理独占上述30个文件及关联测试 | 精确引用归零、静态可达图、定向与全量测试 |
| W2 | `P83-DESKTOP / SER/MUTEX` | 主代理独占受影响样式及其测试 | <=768 viewport／触控规则归零；保留桌面 container／a11y |
| W3 | `P83-REAL / SER/GATE` | 主代理独占验收脚本与正式证据 | 先冻结样本、额度、requested模型和停止条件；正式环境唯一写入锁 |
| W4 | `P83-AGENT / SER/GATE` | 主代理独占安装器、Agent prompt与公开 workspace 配置 | 默认模板精确匹配、用户改动保留、安装升级卸载回退、真实A/B |
| W5 | `P83-INT / INT/GATE` | 主代理集成、全量回归、打包、正式桌面复验 | 禁止子任务提交／推送；Git交付另需作者指令 |

冻结接口：`plugin.py`注册、PawApp命名空间、现行HTTP／工具DTO、Alembic head、12 Skill与8 Tool清单、Agent模型选择和作者正文权威均不得改变。唯一集成责任人是主代理。

## 8. 验证、恢复与完成条件

至少执行：

```bash
.venv/bin/python -m pytest
pnpm test
pnpm typecheck
pnpm build
.venv/bin/python scripts/package_plugin.py
git diff --check
git status --short
```

代码校验不冒充正式产品验收。部署候选前按现行正式环境流程备份并声明中止条件；无 schema 变更，不删除数据。源码误删可按本计划精确文件从 Git 恢复；历史迁移与证据不动。

本计划只有在以下条件同时满足后才可`CLOSED_PASS`：不可达清单复核、全量自动化与打包通过、正式桌面非回归通过、真实模型验收门禁可执行、Agent 精简经真实同模型 A/B 和作者裁决。若 W3／W4 尚未执行，只能保持`ACTIVE_CLOSEOUT`或按作者决定拆为条件门禁，不能把代码减重写成 Agent／文学质量已通过。

### 8.1 当前执行结果（2026-09-14）

- 清理后静态图复跑：后端实质性不可达模块0，前端生产不可达模块0；namespace与测试fixture不计入生产孤岛；
- Python全量：`3159 passed, 329 skipped`；首次运行唯一失败是shell无Node，按用例契约显式设置工作区`CHARACTER_VOICE_NODE`后全量通过；
- 前端全量：`163 passed`测试文件、`1552 passed`测试；
- `pnpm typecheck`、`pnpm build`通过；生产构建转换203个模块；
- `scripts/package_plugin.py`通过，候选输出至`build/ai-novel-world-2026`，退役模块名在候选包中检索为0；
- 手机／平板viewport宽度规则、触控声明和相关术语在生产TS中检索为0；`git diff --check`通过。
- 已建立更新前精确恢复点`/private/tmp/plan83-release-7GWuie`，并通过QwenPaw公开CLI接口把候选原位热更新到正式环境；候选树与安装树完全一致，产品和朗读健康状态均为`ready`，容器未重启，Agent模型／Skill／工具／prompt清单保持不变；
- 正式页面刷新后，PawApp自身已注入样式中的<=768px viewport规则、`touch-action`和`-webkit-overflow-scrolling`运行态匹配均为0；QwenPaw宿主自己的全局响应式／触控规则不属于本仓库，也不得越权修改；
- 真实桌面浏览器`2552×1251`（DPR 2）中，助手折叠时工作台主区宽2210px；助手展开后主区宽1678px、助手宽584px，页面`scrollWidth === clientWidth === 2552`，作品页与助手同时可见；浏览器无PawApp错误，仅有宿主既有`Module not found: Chat`警告；
- 本轮正式运行只验证部署与桌面非回归，没有触发模型、没有修改作品内容。

已完成W0／W1／W2及W5中与本候选相关的全量集成、正式热更新和真实桌面非回归。尚未执行：真实写作模型验收、Agent prompt改写与同模型A/B。因此当前仍为`ACTIVE_CLOSEOUT`，不得写成整体PASS。
