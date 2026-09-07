# 悬疑与金手指正式 Skill 作者采用发布计划

状态：用户于 2026-09-03 明确批准悬疑正式使用，并要求制作金手指 Skill；两份 1.0.0 源码采用与专用 Agent 联合安装启用已完成。研究增益仍为 inconclusive，受控章节按钮自动装载未验收。用户已于 2026-09-07 明确授权提交并 Push 当前候选。

## 决策与范围

本轮按作者采用决定发布两个独立能力模块 `suspense-writing`、`golden-finger-writing`，方法版本均为 `1.0.0`。保留九个通用任务 Skill，分类方法优先于通用偏好；未知分类回退通用；正式事实、作者限制、权限和输出契约始终高于分类方法。金手指是跨题材机制，不等于玄幻或系统面板。正文仍由 `prose-writing` 收口，不建单书 Skill、第二个 Agent 或逐模型规则。

这是对计划 23 中“最多一个分类路由入口”候选设计的明确收敛：本次只增加用户点名的两个模块，不展开分类×任务矩阵。也是一次作者自主采用，不是对 V3/V3.2 研究门槛的追认：既有 `inconclusive`、失败、未完成校准原样保留。正式可用与实证增益分开记录，禁止写成 H4/隐藏集/A/B 已通过。

仅修改本计划列出的源文件、安装配置、窄合同测试及研究发布记录。不改变业务 API、schema、模型、用户小说或 TTS；不提交或推送 Git。应用仍为 `0.4.0`，新增能力用自身 `capability_version=1.0.0` 版本化，不借方法发布冒充整应用升级。

## 冻结接口

- 新增目录：`skills/suspense-writing/`、`skills/golden-finger-writing/`。入口 frontmatter 使用现有 QwenPaw 约定 `plugin_skill_version: "0.4.0"`，另加 `capability_version: "1.0.0"`、`release_status: author_approved`、`empirical_status: inconclusive`。
- 两模块负责分类决策，默认不打印内部检查表，不强制 JSON；作者/可信任务封套指定格式时遵从原契约；不抢占正文输出、不调用写入工具。开放创作允许有铺垫的新内容，封闭事实任务不补造解题事实。
- 通用 Agent 路由最多组合本次相关的两个能力模块，普通校对、机械字段操作不自动加载；分类不明不凭书名猜测。
- 所有正式生成、确认、保存仍遵循原 PawApp / `ai-novel-writer` 通道。
- 研究材料只读：九书悬疑对照、20书金手指机制矩阵、反例、七项候选 JSON；不读取新的正文。Skill 只含抽象机制与候选编号，不复制专名、原句、事件序列。

## 子代理并行施工设计

唯一集成责任人：当前主代理。无数据库/DTO 变更；共享 Skill 集合、Agent 文件、测试和发布记录由主代理唯一写入。已有未提交 TTS、README 导航改动保持，不整文件覆盖。

| 波次/ready set | 工作包 | 标记 | 唯一目标与文件所有权 | 前置/验收 |
| --- | --- | --- | --- | --- |
| W0 | `S57-SER-01` | SER | 冻结本计划、作者采用与证据边界 | 当前用户批准；完成后放行 W1 |
| W1 | `S57-PAR-GF` | PAR | 仅新增 `skills/golden-finger-writing/SKILL.md` 与其 `references/mechanisms.md` | 按上述元数据；读取研究候选001—003及矩阵/反例；quick_validate；返回来源与边界 |
| W1 | `S57-SER-SUS` | SER | 主代理新增 `skills/suspense-writing/` 两文件；审查公开安装能力 | 不改变冻结接口；悬疑四候选与九书补充 |
| W2 | `S57-INT-01` | INT/MUTEX | 主代理修改 `qwenpaw-agent/AI_NOVEL_WORLD.md`、`scripts/configure_qwenpaw_novel_agent.py`、`scripts/verify_qwenpaw_lab.py`、`tests/test_skill_contract.py`；按需收敛 `skills/prose-writing/references/genre-promises.md`；新增窄测试 | W1 两模块完成；总数与注册/安装清理合同一致；不改通用事实边界 |
| W3 | `S57-PAR-QA` | PAR-C | 只读独立前向任务检查；只在新临时目录产出测试回答 | 给真实用户任务，不给预期答案；不调用用户模型、不接触小说 |
| W3 | `S57-GATE-01` | GATE/SER | 主代理自动化、打包、公开安装与作用域核查 | Skill 快校验、pytest 合同和全量、package、diff；不为本次测试删除用户数据 |
| W4 | `S57-INT-02` | INT | 主代理追加本计划结果、开发索引及 `小说扫榜/08-写作评测/正式发布/` 新记录 | 区分源码发布/安装事实/作者采用/效果未证实；旧证据不改标 |

子代理不得修改公共脚本、测试、Agent、其他 Skill、用户改动或 Git 暂存区；不得安装/卸载、切换模型或操作共享环境。W3 前向检查与主代理静态/自动化检查可并行，最终集成串行。两代理不得同时写同一目录。

## 发布门禁与恢复

使用现有公开 Skill/PawApp 安装接口；先只读确认能力和目标状态。长期 TTS 正在施工，禁止把脏工作树整包覆盖到唯一环境，不停止/重启 TTS、不改变共享模型、不直接改已安装 QwenPaw 或打包副本。若公开接口不能安全独立发布，源码及可安装 Skill 交付照常完成，但“长期已启用”必须保持待部署并明确报告，不能伪称生效。

验收至少执行 `.venv/bin/python -m pytest tests/test_skill_contract.py tests/test_manifest.py tests/test_qwenpaw_integration_contract.py`、Skill Creator `quick_validate.py`、`.venv/bin/python scripts/package_plugin.py`（共享 build 空闲时）、`.venv/bin/python -m pytest`、`git diff --check`。无前端改动，不制造无关浏览器验收。生命周期或真实模型未执行项单列；作者批准不代替工程验证。

恢复时停用两个分类能力、回到原九个通用 Skill；不修改用户正文、小说事实或模型配置。保留原版本和发布清单以便逐文件还原本轮改动，不使用破坏性 Git 回滚。

## 执行结果（2026-09-03）

W0—W4 已按文件所有权完成。金手指由 S57-PAR-GF 独立产出，主代理集成；S57-PAR-QA 产出四个有限前向样本并保留实际任务文本。Skill Creator 校验、138 项目标合同、3872 项全量测试通过；213 项跳过不计入验收，3 项既有警告保留。隔离打包含 11 个 Skill，九个原通用 Skill 没有本次源码变更。

因长期环境由计划56持有部署锁，本任务没有自行覆盖或重启。主代理向部署所有者交付冻结文件并确认本轮授权；由计划56一次正常联合安装、公开configure，随后回传两个新模块在 ai-novel-writer 启用且其他两个 Agent 未启用，模型仍为 minimax-cn/MiniMax-M3，Agent 提示正文一致。安装工程证据见 [计划56日志](./证据/计划56/TTS56-JOURNAL.md)第9.10节。这次协调不授权本任务修改 TTS 或执行其他计划施工。

详情、SHA-256 采用清单及保留风险见 [S57 发布记录](./证据/计划57/S57-RELEASE.md)。未执行真实用户模型 A/B 或本轮新模块的完整卸载/重装；受控生成的单一 prose-writing 调用未改为分类上下文装配。原生 Agent 已具备分类模块及路由，但不承诺所有生成按钮自动装载。提交与推送按 2026-09-07 的当前用户授权执行，不改变上述验收边界。
