# 小说写作能力 Skill 优化与评测计划

状态：**用户已于 2026-08-25 明确把实际写作能力设为项目第一优先级，并授权优化或新增小说 Skills；本文批准 S0–S3 进入施工。Skill 文件、安装契约和自动化通过只代表候选实现完成，未经过真实模型盲测前不得宣称写作质量已经提升或经过市场验证。**

计划版本：V1.0

制定日期：2026-08-25（Asia/Shanghai）

目标版本：AI小说世界2026 PawApp `0.4.0`，QwenPaw 兼容边界保持 `>=2.1.0,<2.2.0`

关联资料：

- [阶段 3–6 实现与验收](./14-阶段3至6实现与验收.md)
- [妙笔神书一比一创作闭环与三书实写总目标](./16-妙笔神书一比一创作闭环与三书实写总目标计划.md)
- [跟随“AI 小说作家”Agent 模型切换计划](./19-跟随AI小说作家Agent模型切换开发计划.md)
- [QwenPaw 原生助手与创作上下文联动 V2](./20-QwenPaw原生助手与创作上下文联动施工计划.md)

## 0. 结论与事实边界

### 0.1 产品优先级

本项目的第一质量目标是：作者能够用它持续产出有吸引力、有人物辨识度、结构和因果成立、符合题材承诺且可继续修订的长篇小说。数据安全、可恢复、可审计和 QwenPaw 兼容是不可降低的基础门槛，但不能替代写作质量。

### 0.2 当前实现事实

**已核实事实**：当前项目有六个 `0.3.0` 小说 Skill，共 266 行 `SKILL.md`。六个 Skill 已覆盖方向、故事设定总表、章纲、正文、连续性和文风，并已验证 Agent 作用域、工具调用、候选/Diff、作者确认和权威正文保护。

**已核实事实**：当前 Skill 的工具、安全与选区协议明显多于创作方法。正文写作的创作主体只有八条工作规则；章纲、故事设定总表、连续性和文风各只有三至六条主体规则。现有自动化主要验证文件集合、关键协议语句和安全边界，不能证明人物、场景、对白或成文质量。

**已核实事实**：历史真实模型验证证明部分窄约束得到改善，例如方案数量、字数标签和不新增世界规则；同时也记录了 Skill 选择存在随机波动。项目尚无同模型、同输入、旧版与新版匿名盲评的写作质量证据。

**项目决策**：保留现有六个 Skill 的安全外壳，新增人物、场景和对白三个专业 Skill；同步强化方向、故事设定总表、章纲、正文、连续性和文风。总数从六个变为九个，不建设逐模型 Skill，不把多个 Agent Runtime 或模型选择器引入本计划。

### 0.3 术语决策

**项目决策（2026-08-25）**：全书人物、世界规则、时间线、已确认事实和承诺回收的统一资料称为“故事设定总表”，技术 ID 为 `story-foundation`。它回答“这个故事已经确立了什么、当前状态是什么”；大纲回答“故事将按什么因果顺序推进”，两者不是同一东西。本轮不保留含宗教色彩的展示名、技术 ID 或空目录；安装验证以九个中性 ID 的精确集合为门禁，出现旧目录或额外插件 Skill 时必须失败，不静默兼容。

## 1. 开源学习来源与版权边界

以下数据于 2026-08-25 从 GitHub 仓库页面只读核验。星数只用作社区关注度信号，不作为小说质量结论。

| 项目 | 当日信号 | 可学习内容 | 许可证与使用边界 |
| --- | ---: | --- | --- |
| [wordflowlab/novel-writer](https://github.com/wordflowlab/novel-writer) | 931 stars / 176 forks | 创作原则、故事规格、关键澄清、计划、任务、写作、分析的循环；中文长篇流程 | MIT；只吸收方法概念，本项目重新表述并保留自己的数据模型 |
| [wordflowlab/novel-writer-skills](https://github.com/wordflowlab/novel-writer-skills) | 256 stars / 51 forks | 类型知识、对白、场景结构、人物弧线和一致性检查的模块化 | MIT；不复制其模板文本、命令命名或宣传性断言 |
| [danjdewhurst/story-skills](https://github.com/danjdewhurst/story-skills) | 186 stars / 23 forks | 章节前后状态、人物知识、读者问题、承诺/回收、确定性连续性检查 | MIT；借鉴“结构化状态 + 语义审查”原则，不复制其文件 schema 或 CLI |
| [EthanYoQ/AI-Novel-Writer](https://github.com/EthanYoQ/AI-Novel-Writer) | 447 stars / 63 forks | 从故事前提到定稿的人工可控闭环、审稿意见逐项确认和不可变快照 | GPL-3.0；只做产品模式研究，不复制代码或派生实现 |
| [KazKozDev/NovelGenerator](https://github.com/KazKozDev/NovelGenerator) | 143 stars / 33 forks | 多视角人物知识、并行情节和时间同步 | 无人干预整书生成与作者主导原则冲突，不采用其自动写完路径 |

本文和新增 Skill 均为针对本项目公开契约与真实缺陷重新编写的原创综合，不逐句翻译或复制外部 Skill。若后续确需引入外部代码、模板或长段文本，必须单独记录文件、commit、许可证、修改和 NOTICE 义务。

## 2. 写作能力架构

### 2.1 九个 Skill 的职责

| Skill | 唯一主职责 | 明确非目标 |
| --- | --- | --- |
| `novel-direction` | 前提、题材承诺、核心冲突、读者期待和方向取舍 | 不直接写整章 |
| `story-foundation` | 全书事实层、主题、世界规则、主线、角色与承诺的统一基线 | 不把讨论候选冒充正式事实 |
| `character-craft` | 人物欲望/需求/恐惧/矛盾、能动性、关系压力、弧线和声音 | 不只生成静态标签卡 |
| `chapter-outline` | 本章入口状态、场景链、升级、转折、人物变化和出口状态 | 不用事件清单冒充因果章纲 |
| `scene-craft` | 单场目标、阻力、策略变化、信息分配、转折、余波和场景接口 | 不替代整章正文 Skill |
| `dialogue-craft` | 人物声音、目的、潜台词、权力变化、动作节拍和信息节制 | 不用对白倾倒设定 |
| `prose-writing` | 基于作者约束和正式上下文输出可读正文 | 不解释创作过程污染正文 |
| `continuity-check` | 人物知识、状态、时间、地点、物件、因果、伏笔和承诺/回收 | 不把偏好误报为事实矛盾 |
| `style-review` | 发展性、场景、行文和校对分层诊断，保护作者声音 | 不把全文统一成模型腔 |

### 2.2 共享创作原则

1. 每个场景必须改变至少一个有意义的状态：目标、关系、知识、风险、选择或资源；纯信息堆积不算推进。
2. 人物行为来自“想要什么—误判什么—愿付什么代价”，不能只靠作者安排或突然降智推动情节。
3. 人物只能依据已获得的信息判断；作者知道、读者知道和人物知道必须分开。
4. 重要转折由前置选择和因果触发；巧合可以制造麻烦，不能无代价解决核心问题。
5. 具体细节服务于视角、情绪和行动，禁止用无差别感官堆砌冒充文学性。
6. 对白是行动：每轮至少承担争取、试探、遮掩、施压、连接或撤退之一，并改变关系或信息状态。
7. 修改先确认修订层级。发展性问题、场景问题、行文问题和校对问题不能混成一次无边界重写。
8. 类型惯例是读者承诺，不是固定模板；先满足核心承诺，再在角色、代价或因果上做变化。

### 2.3 上下文装载

正文和修订任务采用由近及远的上下文：本轮硬约束 → 当前章和相邻接口 → 相关人物/设定/故事线/伏笔 → 全书摘要。只有任务确需逐句声音或细节时才读取完整近场正文；结构卡与正文冲突时，以已采用正文和正式 revision 为准并报告结构资料过期。

详细技法通过各 Skill 的 `references/` 按任务读取；核心规则仍保留在 `SKILL.md`，避免宿主未成功读取参考文件时完全失去写作方法。参考文件不得包含项目数据写入权限或第二套模型配置。

## 3. 评测合同

### 3.1 评测集

首版至少覆盖十二个自有或合成任务，分为六类：

1. 封闭事实集续写：不能新增人物、组织、关键物件或规则。
2. 场景推进：同一地点内目标、阻力、策略和转折可识别，结尾状态与开头不同。
3. 人物声音：三名人物去掉姓名后仍能通过措辞、关注点和回避方式区分。
4. 对白潜台词：角色不能直说秘密或用问答方式倾倒背景，关系权力必须发生可解释变化。
5. 跨章连续性：人物知识、伤势、位置、物件所有权、时间、伏笔状态无冲突。
6. 类型承诺：年代言情、东方玄幻、近未来悬疑各至少两个任务，不能只换名词复用同一节奏。

评测材料只使用项目自有、用户授权或本计划新写的合成文本；不把竞品正文或未授权小说放入仓库。

### 3.2 两层评分

**确定性门槛**：检查指定人物/视角/时态、禁用事实、篇幅范围、输出纯净度、必须出现/不得出现的状态变化、对白角色和系统文本污染。硬门槛失败的样本不能靠主观高分抵消。

**匿名人工盲评**：隐藏版本和模型身份，对旧版/新版随机排序，按 1–5 分评价吸引力、人物可信度、场景推进、语言自然度、类型满足度和可继续修改性，并记录更愿意保留的版本。评审不得看到实现说明或预期答案。

### 3.3 退出门槛

Skill `0.4.0` 只有同时满足以下条件才可写成“写作能力改进已通过”：

- 安全与事实硬门槛通过率不低于 `0.3.0`，权威正文零自动写入；
- 十二个样本全部完成同模型 A/B；每个版本至少独立生成两次，用于暴露随机波动；
- 新版匿名偏好胜率至少 65%；
- 六个主观维度的平均总分相对旧版提高至少 15%，且没有单一维度下降超过 0.25 分；
- 三个题材都至少有一个样本偏好新版，不能靠单一题材拉高总分；
- 所有失败、平局和退化样本保留，不删除不利证据。

未达到门槛时保留代码候选和报告，但不得替换唯一正式安装；应定位具体 Skill 退化并缩小修改，不为追分改模型或偷偷增加样本。

## 4. 施工工作包与子代理并行设计

### 4.1 当前任务执行方式

本任务当前采用**单一所有者串行施工**。原因不是任务不可拆，而是九个 Skill 共享 Agent 路由、选区协议、安装列表和同一评测合同；在首次冻结前让多个写入者同时修改会放大语义冲突。当前聊天未单独启动子代理。后续真实模型样本在提示、模型、温度和输入冻结后可按题材并行生成，但同一本书的连续章节仍必须串行。

### 4.2 Ready set

| 波次 | 工作包 | 标记 | 目标 | 前置/门禁 |
| --- | --- | --- | --- | --- |
| S0 | `WC-S0-CONTRACT` | `SER/GATE` | 冻结九 Skill 职责、来源、评测和版本 | 用户优先级指令；当前实现核验 |
| S1 | `WC-S1-CRAFT` | `SER/MUTEX` | 新增人物/场景/对白，强化六个既有 Skill | S0；锁定 `skills/` |
| S2 | `WC-S2-WIRING` | `SER/MUTEX` | Agent 路由、安装/验证列表、版本和文档同步 | S1；Skill 名称冻结 |
| S3 | `WC-S3-AUTO` | `SER/GATE` | Skill 校验、契约测试、评测集校验和打包 | S2 |
| S4 | `WC-S4-AB` | `PAR-C/GATE` | 三题材同模型双生成、匿名盲评、退化归因 | S3；固定真实模型与样本 |
| S5 | `WC-S5-INT` | `INT/SER` | 唯一正式安装、范围复核和结论裁决 | S4 通过；安装前备份与回退 |

### 4.3 文件所有权

| 工作包 | 允许修改 | 只读输入 | 禁止触碰 |
| --- | --- | --- | --- |
| `WC-S0-CONTRACT` | 本文、`docs/开发文档/README.md` 的本计划索引行 | 现有开发文档、GitHub 公开来源 | 旧项目及其 `Data`、数据库、前后端业务代码 |
| `WC-S1-CRAFT` | `skills/*/SKILL.md`、各 Skill 自有 `references/` | `qwenpaw-agent/AI_NOVEL_WORLD.md`、公开来源 | 其他 Skill 写入者、QwenPaw 上游源码 |
| `WC-S2-WIRING` | `qwenpaw-agent/AI_NOVEL_WORLD.md`、`scripts/configure_qwenpaw_novel_agent.py`、`scripts/verify_qwenpaw_lab.py`、`plugin.json`、`backend/contracts.py`、`pyproject.toml`、`package.json`、根 `README.md` | 公开 Agent/Skill 契约 | Provider 设置、模型白名单、数据库迁移 |
| `WC-S3-AUTO` | `tests/test_skill_contract.py`、`tests/test_assistant_install_contract.py`、`tests/test_qwenpaw_integration_contract.py`、`tests/fixtures/writing_skill_eval/` | 全部候选 Skill | 前端现有未提交文件、正式小说数据 |
| `WC-S4-AB` | 新建的专项证据目录 | 冻结样本、候选包、真实模型 | 修改 Skill、删除失败样本、切换模型补分 |
| `WC-S5-INT` | 仅门禁通过后的公开安装/验证动作和验收记录 | 打包产物、运行备份 | Git 提交/推送、数据卷删除、上游核心修改 |

共享锁：`skills/`、Agent 路由文件、三个安装/验证 Skill 集合和评测样本 ID 均为 `MUTEX`。唯一集成责任人是当前主代理；负责复核全部 diff、运行集成测试、处理失败并作退出判断。

## 5. 冻结接口与非目标

- 保持 `/apps/ai-novel-world-2026` 与 `/api/ai-novel-world-2026/...` 命名空间不变。
- 保持 `ai-novel-writer` 为唯一小说生成 Agent 和模型权威来源。
- 保持五个小说工具及其服务端权限不变；本计划不新增写正文工具。
- 不修改 QwenPaw 上游核心，不复制其私有模块，不增加第二套聊天或 Agent Runtime。
- 不建设逐模型、逐 Provider 或逐书固定 Skill；模型差异用实际模型证据和评测暴露。
- 不以 GitHub 星数、README 宣传、单个漂亮样章或一次模型输出作为完成证据。
- 不在本计划施工中央统一 Diff、TTS、向量、关系网或其他专项功能。

## 6. 验证、证据与回退

### 6.1 自动化命令

```bash
.venv/bin/python /Users/liujia/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/<skill-name>
.venv/bin/python -m pytest tests/test_skill_contract.py tests/test_assistant_install_contract.py tests/test_qwenpaw_integration_contract.py
.venv/bin/python scripts/package_plugin.py
git diff --check
```

若变更只涉及 Skill、Agent 路由、安装列表和文档，不要求触碰正式 PostgreSQL；全量 Python 回归仍在正式安装门禁前运行。打包验证使用当前前端构建产物，不把 `build/` 纳入手工源文件或 Git。

### 6.2 证据

S3 至少保存：九 Skill 清单、quick validator 结果、契约测试、打包文件树和 diff 复核。S4 另建日期化证据目录，保存冻结输入、匿名候选、实际模型、生成 attempt、确定性检查、原始评分和汇总；不得只保存获胜样本。

### 6.3 回退

本计划不改 schema 和用户正文。候选失败时回退源代码中的 Skill、Agent 路由、安装列表和版本号即可；若已经在隔离或正式 QwenPaw 安装，使用官方 PawApp 卸载/安装流程恢复最后一个通过门禁的 `0.3.0` 包，并复核目标 Agent 六 Skill、其他 Agent 零小说 Skill、五工具作用域及原生功能。不得删除 QwenPaw 或 PostgreSQL 数据卷。

## 7. 当前阶段判断

- S0：已完成，范围、来源、九 Skill 集合和评测门槛已冻结。
- S1：已完成 `0.4.0` 源码候选；六个现有 Skill 已强化，并新增 `character-craft`、`scene-craft`、`dialogue-craft`，九个 Skill 都有按需加载的技法参考文件。
- S2：已完成源码候选；Agent 路由、安装/验证清单、业务调用点和 Python/Node/PawApp 版本已同步为九 Skill `0.4.0`。全书资料 Skill 已使用中性 ID `story-foundation`。
- S3：已完成。Skill Creator `quick_validate.py` 对九个 Skill 全部返回 `Skill is valid!`；本次隔离暂存快照的九 Skill/评测集/版本/安装契约定向回归 `29 passed`，全量 Python 回归 `202 passed, 21 skipped`；`scripts/package_plugin.py` 打包成功，产物含九个 Skill、十个技法参考文件且清单版本为 `0.4.0`。本次未改项目运行依赖；快速校验器所需 PyYAML 仅安装在 `/tmp` 临时目录。
- S4：待执行。必须使用冻结的十二个合成任务，在同一真实模型和参数下对 `0.3.0`/`0.4.0` 各独立生成两次并匿名盲评；未执行前不宣称文笔或写作质量已提升。
- S5：只有 S4 通过才允许把“写作能力提升”写成验收结论；Git 提交和推送仍需用户另行授权。

## 8. S4-R：探索性写作研究运行器

状态：**用户于 2026-08-27 批准开发最小内部研究运行器；仅服务本轮项目合成题 A/B，不批准正式 Skill 修改、产品页面、数据库表或任意提示执行接口。**

### 8.1 冻结目标与非目标

运行器用于替代不可审计、易拥塞的聊天页面手工跑样本：由后端使用公开 PawApp 上下文固定调用 `ai-novel-writer`，每次生成前后读取 effective 模型；公开 reply 暴露 usage 时核验 actual provider/model 和 token usage，未暴露时透明记录 `not_exposed`，再把完整原始输出与证据返回给项目脚本。它不写小说数据库、不建立第二套 Agent Runtime、不切换模型、不自动修改 Skill、不执行授权小说正文，也不把一次探索性结果升级为 S4 正式结论。

HTTP 只接受冻结 experiment/sample id；题面、A/B 分配、候选覆盖层和 `prose-writing` Skill 均由服务端固定，拒绝调用者提交任意 prompt、模型、Skill、小说 ID 或正文。A/B 同题同轮只允许候选覆盖层不同。生成使用新的独立 session id、单路互斥、600 秒上限；该上限依据首个 UI 样本约 270 秒的观察设置，不代表性能目标。超时、公开 effective 模型缺失或前后不一致、公开 usage 与 actual 模型矛盾时丢弃正文并返回可审计失败。

### 8.2 冻结接口与文件协议

- `GET /api/ai-novel-world-2026/research/writing-evaluations/{experiment_id}`：返回固定合同、样本编号和哈希，不返回小说数据。
- `POST /api/ai-novel-world-2026/research/writing-evaluations/{experiment_id}/samples/{sample_id}/generate`：无请求正文；只运行已登记样本。
- 成功结果包含 `prompt_sha256`、`output_sha256`、非空白字符数、requested/actual provider/model、token usage、Skill 哈希、session id 和耗时；不持久化服务端结果。
- 主机脚本按样本原子写入专项证据目录；已有完整且哈希一致的样本默认跳过，失败单独保存，不静默重试或覆盖。
- 本轮冻结 experiment 为 `mystery-ab-20260827-v1`，题面权利基础固定为 `project-synthetic`。

### 8.3 子代理并行施工设计

| 波次 | 工作包 | 标记 | 目标 | 文件所有权 | 前置与门禁 |
| --- | --- | --- | --- | --- | --- |
| R0 | `RR-AUDIT-API`、`RR-AUDIT-HARNESS`、`RR-AUDIT-CONTRACT` | `PAR` | 只读审计公开调用、运行证据、CLI恢复和安全边界 | 不修改文件 | 本节范围获批 |
| R1 | `RR-CONTRACT` | `SER/GATE` | 主代理冻结 experiment、case、assignment、prompt 和响应 DTO | 本文、`backend/writing_eval_contract.py` | R0 汇合；接口冻结 |
| R2 | `RR-API` | `SER/MUTEX` | 实现无持久化、固定样本、单路生成 API | `backend/writing_eval_api.py`、`backend/app.py` 的唯一接线行 | R1；锁定 `backend/app.py` |
| R3 | `RR-CLI` | `SER` | 实现串行、断点续跑、原子证据保存 | `scripts/run_writing_eval.py` | R1、R2 DTO 冻结 |
| R4 | `RR-TEST` | `PAR-C` | 契约/API/CLI 定向测试和失败注入 | 新建 `tests/test_writing_eval_*.py` | R1 接口冻结；不得修改实现文件 |
| R5 | `RR-INT` | `INT/SER/GATE` | 主代理复核 diff、定向/全量测试、打包和真实单样本验证 | 专项证据目录；必要索引行 | R2–R4 完成 |

R0 可并行，写代码阶段保持单一所有者：本运行器规模小，API、合同与 CLI 紧密共享哈希和响应字段，且 `backend/app.py` 已存在其他未提交施工，串行能避免覆盖用户改动。若 R4 派发，只允许新增独立测试文件，不得修改实现、共享 fixture、现有测试或证据。共享运行环境、真实模型调用、最终集成、Git 暂存/提交/推送始终由主代理串行负责。

每个工作包都不得触碰旧项目及其 `Data`、正式数据库、小说正文、Skills、迁移、QwenPaw 上游、Provider 设置、密钥、现有用户改动和无关专项。唯一集成责任人为主代理。

### 8.4 验收与回退

最低验收：固定合同/哈希测试、未登记 experiment/sample 拒绝、无任意 prompt 字段、A/B 唯一变量测试、并发拒绝、超时、公开模型前后不一致、usage 状态矛盾、final-only 提取、正文输出纯净度、CLI 已完成跳过/失败保留/原子写入，以及 `.venv/bin/python -m pytest`、`scripts/package_plugin.py`、`git diff --check`。真实运行只做一个合成样本哨兵，确认无评测数据库写入、模型证据透明且正文质量硬门槛通过后，才允许继续16样本。

回退只需移除新路由接线、研究模块、主机脚本和专项证据；没有 schema、用户正文或数据卷恢复动作。禁用/卸载 PawApp 后仍遵循既有完整清理与 QwenPaw 原生非回归规则。

### 8.5 当前实现与阶段门禁（2026-08-27）

- `RR-CONTRACT`、`RR-API`、`RR-CLI`、`RR-TEST` 的源码候选已完成；普通 Compose 默认不启用研究开关，未写入数据库、迁移、正式 Skills 或小说正文。
- 冻结合同、API、CLI 三组新增测试共 `52 passed`；相关 QwenPaw/Skill/模型编排定向回归 `166 passed`；项目全量回归 `2376 passed, 116 skipped`。
- `scripts/run_writing_eval.py verify-contract`、Compose override 配置解析和 `scripts/package_plugin.py` 已通过；打包产物为本地生成物，不作为人工源文件编辑。
- `RR-INT` 已于 2026-08-27 在用户明确授权一次模型调用成本后执行 X01 真实哨兵：固定合同和路由预检通过，但唯一一次请求最终返回 HTTP 504，`0 completed / 1 failed`，没有取得正文、actual 模型或 token usage，且按合同没有自动重试。因此真实哨兵结论为**未通过**，不是“运行器已经可批量使用”。
- 哨兵前后项目权威表计数完全一致：小说9、文档25、不可变正文版本126、working copy 25、章节生成任务50、候选26、故事事实510、情报提案29、创作生成任务162、模型运行记录53；前后活动后台任务和活动朗读请求均为0。研究窗口已关闭，研究路由恢复404，QwenPaw 根页面、PawApp 注册表和本项目健康接口均为200。
- 在真实哨兵证明 actual/usage 可保存且数据库写入数不变之前，不得继续16样本，不得把运行器源码通过写成写作能力提升。

### 8.6 首次超时诊断与只读观测修复（2026-08-28）

用户同意先查明并修复诊断盲区，明确不再发起模型调用。首次 run 的 `dispatch.json` 与 `failure.json` 修改时间精确相差600秒，与服务端 `WRITING_EVAL_TIMEOUT_SECONDS=600` 一致；直接原因是公开 `ctx.chat()` 在硬上限内没有结束。题面只有727字符，运行前后数据库计数一致且无活动后台任务，QwenPaw/PawApp 健康，因此不能归因于题面过长、数据库写锁或安装失败。

更深层原因仍需流式证据区分：当前 `AI小说作家` 启用9个 Skill 和29个工具，`PawAppContext.chat/chat_stream` 的公开参数没有逐请求工具禁用策略；`tools=forbidden` 只能作为提示约束。当前有效 `bigmodel/glm-5.3-flash` 公开配置为 `relay_reasoning=true`，未暴露本轮 thinking budget。现有失败证据无法区分长推理、Agent/工具多轮或 Provider 等待，不得选一个猜测写成已核实根因。

本修复使用 `RR-DIAG`（`SER/MUTEX`）单一工作包，不并行：API事件摘要、失败 DTO、CLI 原子证据和三份共享测试紧密耦合，拆分会增加合同漂移风险。只允许修改 `backend/writing_eval_api.py`、`backend/writing_eval_contract.py`、`scripts/run_writing_eval.py`、`tests/test_writing_eval_*.py` 和本专项文档；禁止触碰 QwenPaw 上游、Agent/Provider设置、正式 Skills、数据库、小说正文和共享运行环境。

`RR-DIAG` 采用公开 `ctx.chat_stream()` 收集事件，只保存事件、消息角色和内容块类型的有界计数及首末事件耗时，明确 `content_recorded=false`，不保存 reasoning、正文片段或工具参数。超时/Provider/模型核验失败响应携带 session id、开始时间、请求模型、Skill请求方式、`tool_policy_enforcement=prompt_only` 和流式摘要；CLI 保存至多64 KiB的 JSON 错误正文、HTTP状态、正文哈希、派发/失败时间和客户端耗时。任何旧失败 run 保持不可覆盖；本轮不启用研究开关、不安装插件、不执行 X01。

`RR-DIAG` 源码候选验证结果：新增定向测试 `54 passed`，项目全量回归 `2436 passed, 116 skipped`；合同自检、Compose override 静态解析、Python 编译和 PawApp 本地打包均通过。两条全量警告均为既有 Starlette 弃用警告。本验证没有启用研究入口、安装插件或发起模型调用，不能据此宣称更深层超时原因已经确定。

### 8.7 第二次 X01 流式哨兵与新阻断（2026-08-28）

用户明确授权后，主代理以新 run id `mystery-ab-runner-sentinel-v2` 只派发 X01 一次，没有自动重试。派发前确认已安装 `writing_eval_api.py`、`writing_eval_contract.py` 与提交 `2f8849b` 的工作区哈希一致，数据库迁移为 `20260827_0023 (head)`；同时在 `qwenpaw-backups` 卷建立插件与 PostgreSQL 恢复备份。由于共享容器保留了与当前 `.env` 不同的四个 TTS 验证字段，本次通过权限 `0600` 的临时覆盖文件继承原值，只增加研究开关，恢复后删除临时文件且未记录字段值。

X01 在 308.590 秒后完整结束响应流，没有命中600秒硬上限。流式诊断记录 `stream_completed=true`、14,492个事件，事件类型为 `text=14,485`、`agentresponse=3`、`message=2`、`reasoning=2`；没有观察到 `tool_call` 或 `tool_result` 类型。该证据足以排除本次请求的工具循环和 Provider 永久等待，但不能反推首次600秒请求一定经历相同路径。

本次最终返回 HTTP 502，失败类型为 `writing_evaluation_model_verification_failed`：公开 closing assistant message 没有 `qwenpaw_turn_usage`，因此 actual provider/model 与 token usage 均无法核验，正文按冻结合同作废且没有保存。已核实公开 `PawAppContext.chat_stream()` 只承诺流式事件，`chat()` 也只是聚合同一公开流为 `ChatReply`；当前公开 PawApp 合同不保证 closing message 携带用量元数据。项目不得读取私有 usage buffer，也不得把调用前 effective 模型冒充 actual 模型。

运行后研究路由恢复404，QwenPaw 根页面、PawApp 注册表与项目健康接口均为200，TTS Sidecar healthy，四个既有 TTS 验证字段逐项等值恢复。核心表中出现的43条新增 `model_run_records` 全部属于并行 `narration.segment_render`，两条新增 `document_revisions` 均为 `tts_snapshot`；其他评测关注表不变，活动后台任务和活动朗读请求为0。不能把共享环境的 TTS 写入表述为评测零写入，但现有行级类型证据没有显示 X01 写入小说权威数据。

阶段门禁继续保持关闭：不得启动其余15个样本。后续只有两条合规路径：等待 QwenPaw 在公开 PawApp 契约中提供 actual provider/model 与 usage，或由用户另行裁决降低评测审计要求；不得使用私有接口、内部 usage buffer 或未经证明的 requested=actual 假设绕过门禁。

### 8.8 公开模型前后核对与 usage 可选合同（2026-08-28）

用户已明确选择第二条路径：写作质量评测不再因公开 usage 缺失而丢弃正文，但不得把调用前 effective 模型冒充 actual 模型。本轮使用 `RR-PUBLIC-EVIDENCE`（`SER/MUTEX/GATE`）单一工作包；合同、API、CLI和测试共享同一响应结构，不并行修改。允许文件限定为 `backend/writing_eval_api.py`、`backend/writing_eval_contract.py`、`scripts/run_writing_eval.py`、三份 `tests/test_writing_eval_*.py` 和本专项文档/证据；不触碰正式 Skills、小说正文、数据库 schema、QwenPaw 上游或私有 usage buffer。

结果 schema 升为 `1.1`，模型证据合同为 `writing-eval-effective-model-pre-post-v1`。服务端在生成前通过公开 effective-model API 获取 `requested_model`，流完整结束并提取 final-only 正文后再次通过同一公开接口获取 `postflight_model`；provider/model 不一致时正文仍作废。公开 closing message 含合法 usage 时继续严格核验 actual 模型；不含时固定 `actual_model=null`、`usage=null`、`actual_model_status=not_exposed`，并记录 `private_usage_buffer_used=false`。这只能证明运行窗口前后模型配置没有变化，不能证明 Provider 实际执行身份。

CLI 同时验证 schema、前后非空模型身份、模型证据状态、usage 结构、流完整性、正文与哈希；任何字段矛盾都失败。源码候选定向测试 `58 passed`、相关回归 `202 passed`、项目全量 `2445 passed, 116 skipped`；合同自检、Compose override 静态解析、Python 编译和 PawApp 本地打包通过。两条全量警告均为既有 Starlette 弃用警告。真实 X01 v3 之前仍需备份与恢复门禁；其余15个样本继续停止。

### 8.9 第三次 X01 哨兵：调用链成功、样本纯净度失败（2026-08-28）

用户同意后，以新 run id `mystery-ab-runner-sentinel-v3` 只派发 X01 一次，没有重试或继续其他样本。请求在 283.697 秒后完整结束，14,560 个流式事件全部收口；生成前后公开 effective 模型均为 `bigmodel/glm-5.3-flash`。QwenPaw 没有公开 actual/usage，结果按 schema `1.1` 如实保存 `actual_model=null`、`usage=null` 和两项 `not_exposed`，且 `private_usage_buffer_used=false`。输出哈希为 `ec77f129fc177382140d727fb611e8e1e4552c151228d8b694439a95cb75019f`，非空白字符数 711，四个固定锚点和篇幅候选门槛均通过。

人工纯净度复核发现，正文后附加一行 `⟦…⟧` Agent 状态胶囊，内容概括题目约束并自行宣称完成。现有自动包装检测器没有识别这种格式，导致 `hard-gates.json` 中四个 wrapper flag 均为 false；这是检测缺口，不是样本通过。原始 `output.txt`、`result.json`、`hard-gates.json` 与匿名样本均保持原样，没有事后裁剪或改写；另以 `semantic-review.json` 记录质量硬门槛失败。因此本次只能证明公开模型前后核对、完整正文保存和恢复链路可用，X01 不具备匿名盲评资格，也不能证明 `0.4.0` 写作能力提升。

正文主体的只读人工观察为：第三人称限知成立，人物从要求开门转为验证读数，联名责任和十五分钟停止条件形成可识别代价，验证结果保持未知。这些是正向实现信号，但不能抵消“只输出正文”硬门槛失败，也不能用单个 A 样本外推 Skill 胜率。

运行后研究开关已移除，研究路由恢复404，QwenPaw 根页面、PawApp 注册表和项目健康接口均为200，TTS Sidecar healthy，四个既有 TTS 验证字段逐项等值。备份保留于 `/app/working.backups/writing-eval-sentinel-v3-20260828-pre`，插件包与 PostgreSQL dump 哈希已复核；主机、容器与 Compose 临时副本已清理。前后表计数仅新增一条正式章节生成任务和一条 `outline_highlight` 创作任务；研究路由不连接数据库，行级元数据表明它们属于共享环境中的并行正式流程，本次未读取其内容或干预其状态。

阶段门禁保持关闭：其余15个样本不得启动。下一次模型请求前必须先补充末尾状态胶囊的显式检测与拒绝回归；本次失败证据不得覆盖、修剪或转记为有效样本。

### 8.10 schema 1.2 纯净度门禁与第四次 X01 哨兵（2026-08-28）

用户要求以目标模式完成测试并形成 Skill 优化方案。本轮使用 `RR-PURITY`（`SER/MUTEX/GATE`）单一工作包，不并行修改：评测合同、CLI 原子证据、真实运行和共享 QwenPaw 恢复紧密耦合；且正式 `prose-writing`、`style-review` 正有其他工作区改动，本轮不得覆盖。允许文件限定为 `backend/writing_eval_contract.py`、`backend/writing_eval_api.py`、`scripts/run_writing_eval.py`、三份写作评测测试和本专项文档/证据。

结果 schema 升为 `1.2`，新增 `writing-eval-output-purity-v1`。确定性检查现在能识别末尾独立 `⟦…⟧`／`⟧…⟧` Agent 状态说明，并公开 `output_purity_pass`；普通正文内部的括号不触发。CLI 重新计算完整确定性检查，拒绝服务端字段漂移；污染输出仍以原文、哈希、结果和失败记录保存，但不生成盲评文件、不计完成、不自动重试并立即停止后续样本。

自动化验证：三份写作评测定向测试共 `64 passed`；写作评测、模型编排、Skill 与 QwenPaw 契约相关回归 `228 passed`；项目全量 `2451 passed, 116 skipped`，两条警告均为既有 Starlette 弃用警告。Python 编译、合同自检、Compose override 静态解析、PawApp 本地打包、`git diff --check` 通过。对 v3 原始输出只读回放得到 `agent_status_capsule=true`、`output_purity_pass=false`，原始文件未修改。

第四次 run `mystery-ab-runner-sentinel-v4` 仍只派发 X01 一次。请求在326.836秒后完整结束，15,687个事件收口；生成前后公开 effective 模型均为 `bigmodel/glm-5.3-flash`，actual/usage 继续透明标记 `not_exposed`。模型再次追加一行143字符的状态说明；新门禁正确标记 `agent_status_capsule=true`、保存原始输出并返回 `0 completed / 1 failed`，没有生成 `blind-samples/X01.md`，其余15项没有启动。原始输出非空白字符802；只读去除末行后的正文主体为661字符，处于500—800目标范围，因此长度超限是状态说明污染的派生结果，不把裁剪正文冒充有效样本。

正文主体的人工观察为：视角、四锚点、策略变化、责任交换、停止条件和未知复核结果均成立；但临时引入“检修短廊”、十九分钟及传感器偏差幅度来缩小风险，存在用未铺垫资源便利化解冲突的倾向。该观察只能用于候选优化，不把失去盲态的 A 样本记入胜率。

运行前建立插件与 PostgreSQL 恢复备份；运行后研究入口恢复404，QwenPaw 根页面、PawApp 注册表、项目健康接口均为200，QwenPaw 与 TTS Sidecar healthy。前后十一项数据库计数及迁移头完全一致，原有朗读验证字段通过进程环境原值转发且未记录值。数据库里五条早于当前 QwenPaw 进程的 `running` 遗留记录没有被读取正文、改状态或归因给本次评测。

## 9. 真实样本驱动的 Skill 优化方案

状态：**方案已形成，尚未修改正式 Skill。当前先修复评测可信度；正式 Skill 候选必须等待其现有工作区改动完成归属确认后再施工。不得直接启动完整16样本。**

### 9.1 结论

不新增第十个 Skill，也不建立专门的“输出清洗 Skill”。输出纯净度属于运行合同和后端门禁，不能依赖模型自觉；创作方法只需窄幅强化两个现有 Skill：

1. `prose-writing`：强化最终输出停止规则和约束隐身，解决状态说明、验收复述和工作过程泄漏。
2. `scene-craft`：强化“解决资源必须有前置来源”，解决临时发明通道、设备或数字来降低核心代价的问题。

`style-review`、`continuity-check` 和其他五个 Skill 本轮不改。单个近未来悬疑场景不足以支持新增分类专用 Skill，也不足以把同一规则复制到九个 Skill。

### 9.2 候选改动

| 优先级 | 目标 | 候选规则 | 可观察验收 |
| --- | --- | --- | --- |
| P0 | 评测合同 | 建立新的 prompt contract/experiment 版本；A/B 两侧共同明确正文结束立即停止，禁止 `⟦…⟧`、完成状态、锚点清单和约束复述；旧 v1 证据保持不可变 | 新合同有独立哈希；旧 v1/v3/v4 不被覆盖；污染输出仍 fail closed |
| P1 | `prose-writing` | 在 PawApp `chapter_generation` 与“最终输出硬约束”中只保留一条精确规则：最终回答首尾都属于小说场景，正文结束立即停止，不附加状态说明、执行摘要、字数/锚点/禁项核对或下一步 | 原始模型输出无状态说明；不依赖后端裁剪才通过 |
| P1 | `prose-writing` | 增加“硬约束只控制生成、不得进入正文或尾注”；封闭输入任务不得用模糊新设施、新路线或新数值绕过事实边界 | 评测约束不在正文出现；未铺垫资源不承担解决核心冲突的关键作用 |
| P1 | `scene-craft` | 决策所用资源、权限、通道、时间收益和技术结论必须来自题面/前文，或在场景内先付出可见代价建立；新细节可以加压，不能便利解题 | X01 类场景的策略变化来自“手动复核+责任承担”，不靠临时捷径填平缺口 |
| P2 | 审稿量表 | 增加“资源来源/便利解题”和“系统文字污染”两个独立判项；前者人工评，后者确定性拒绝 | 主观优点不能抵消纯净度失败；便利解题可单独归因 |

### 9.3 调用方式

- 普通正文、续写、重写仍只以 `prose-writing` 为最终成文 Skill。
- 当任务主要难点是单场目标—阻力—策略—转折—代价时，先调用 `scene-craft` 规划，再由 `prose-writing` 输出连续正文。
- 不因为悬疑、刑侦或近未来标签自动加载额外 Skill；只有任务确需类型承诺时才读取 `prose-writing/references/genre-promises.md` 对应小节。
- 运行器的状态说明检测始终生效；Skill 改善后也不得删除后端门禁或静默裁剪研究原始样本。

### 9.4 施工工作包与并行边界

| 波次 | 工作包 | 标记 | 文件所有权 | 前置与门禁 | 验收 |
| --- | --- | --- | --- | --- | --- |
| W0 | `WSO-CONTRACT` | `SER/GATE` | 本文、未来 v2 评测合同及其独立证据目录 | 用户批准正式施工；旧实验只读冻结 | 合同/哈希/旧证据非回归 |
| W1 | `WSO-PROSE` | `SER/MUTEX` | `skills/prose-writing/SKILL.md`，必要时其现有 reference | 先确认当前未提交改动归属；锁定该 Skill | quick_validate、Skill 契约、真实裸输出 |
| W2 | `WSO-SCENE` | `SER/MUTEX` | `skills/scene-craft/SKILL.md` 或其现有场景 reference | W1 输出边界冻结；不得改其他 Skill | quick_validate、资源来源行为用例 |
| W3 | `WSO-EVAL-V2` | `SER/GATE` | `backend/writing_eval_contract.py`、API/CLI 接线、写作评测测试 | W1/W2 候选哈希冻结 | 定向、相关、全量、打包、Compose |
| W4 | `WSO-SENTINEL` | `GATE/SER` | 新实验哨兵证据目录 | 备份、无活动共享任务、研究入口最小窗口 | 先 A/B 同题各一份；两份均纯净才放行 |
| W5 | `WSO-AB` | `PAR-C` | 冻结16样本证据与独立盲评分表 | W4 通过；模型/提示/Skill 哈希冻结 | 完整矩阵、双生成、匿名评分 |
| W6 | `WSO-INT` | `INT/SER` | 文档结论、唯一正式安装 | W5 达到第3.3节门槛 | 全量回归、安装/卸载、最终裁决 |

本轮不启动子代理：目标 `prose-writing` 和共享 Skill 契约测试已有其他未提交改动，且评测合同、提示哈希和唯一共享 QwenPaw 属于互斥资源，当前并行写入会破坏归属和可复核性。未来 `WSO-AB` 只允许在合同冻结后并行进行互不共享状态的盲评或独立样本审查；真实模型生成仍按单路串行，避免已观察到的拥塞。所有工作包禁止触碰 QwenPaw 上游、Provider 设置、数据库 schema、小说正文、旧项目及其 `Data`、其他专项文件和用户未分配改动。唯一集成责任人为主代理，汇合顺序为 W0→W1→W2→W3→W4→W5→W6。

### 9.5 放行条件

先完成新的 A/B 同题哨兵，不直接跑16项：

- 两侧原始输出都没有状态说明、解释、约束复述或工作语句；
- 两侧正文主体均在目标篇幅内，四锚点成立，人物知识边界和停止条件经人工复核通过；
- 不引入承担关键解题作用的未铺垫路线、设备、权限或精确数字；
- 生成前后公开模型一致，actual/usage 未公开时继续透明标记，不读取私有状态；
- 无评测数据库写入，研究入口恢复404，备份和回退可执行。

只有同题 A/B 哨兵通过，才进入完整16样本；只有第3.3节整体门槛通过，才允许写成“Skill 写作能力已提升”。
