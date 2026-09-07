# S57 正式采用与安装验收

日期：2026-09-03。状态：两份源码正式采用完成，联合安装已启用；写作增益仍为 `inconclusive`。本轮未提交、未推送。

## 结果与来源

- 正式模块：`suspense-writing@1.0.0`、`golden-finger-writing@1.0.0`；应用仍为 0.4.0。
- 悬疑依据九书扩展对照和四项候选；金手指依据 20 本授权前缀（19×200章、1×169章）机制矩阵和三项候选。保留适用条件、反例和替代解释，不搬运来源小说专名、原句或独特事件组合。
- 原九个通用 Skill 源码保持不变；新增两份分类/机制 Skill、Agent 路由及配置名单，总数为 11。
- 分类方法优先于通用偏好；正式事实、作者要求、权限和输出契约仍优先。类型不明回退通用。正文默认连续可读，不把内部账本和 JSON 评测字段塞进文章。
- 作者采用以本轮明确指令为准，不再要求补写评审理由作为使用前提。旧 V3/V3.2、作者金标准未完成、失败与不确定结论不改标。

作者原话、源文件 SHA-256、研究候选和机器可读状态见研究库的 [采用记录](/Users/liujia/Documents/小说扫榜/08-写作评测/正式发布/悬疑与金手指-作者采用-20260903.json)。

## 实际工程验证

| 检查 | 结果 | 限制 |
| --- | --- | --- |
| Skill Creator 官方 quick_validate | 两份均通过 | 本地解释器缺 PyYAML，使用既有容器独立 /tmp 内 Python 3.11 + PyYAML 6.0.3；未改依赖或安装副本 |
| Skill/manifest/QwenPaw 合同 | 138 passed | 原生注册、路由与配置的自动化合同，不等于所有模型实际遵守 |
| 全量 pytest（第二次） | 3872 passed，213 skipped，3 warnings，34.35s | 同期 TTS 增加测试；未设置真实数据库环境，skip 不算通过；警告来自既有弃用项 |
| 隔离 package_plugin | 11 个 Skill 打包成功 | OUTPUT 指向新 /tmp，不占共享 build；临时包包含并行 TTS，未自行部署该包 |
| 独立 Codex 前向检查 | 4 个样本完成 | 不是用户 Provider 调用、A/B、隐藏集或作者评分 |
| 原通用 Skill | 九目录无本次源码差异 | 保留受控单 Skill 路径的已有类型基线 |
| 研究根校验 | 0 errors，0 warnings | 本轮只增采用记录/索引，未重跑全部正文哈希核验 |
| 发布前静态复核 | 两仓库 git diff --check 通过；8个冻结源码 SHA-256 一致 | 无自动暂存、提交或推送；其他任务未提交改动保留 |

命令：

```sh
.venv/bin/python -m pytest -o addopts='' tests/test_skill_contract.py tests/test_manifest.py tests/test_qwenpaw_integration_contract.py -q
.venv/bin/python -m pytest -o addopts='' -q
```

官方快校验暂存目录：`/tmp/s57-skill-validation-hIB19w`；隔离打包最终目录：`/tmp/s57-package-fxvef3/ai-novel-world-2026-final`。二者仅是验证临时文件，不是持久发布入口。

独立样本与执行者观察存于 [forward-check](./forward-check/README.md)。集成复核保留两项问题：封闭材料样本推进较保守；标点样本只验证分类不误触发，没有实际装载通用 `style-review`，不据此宣称全路由已验证。

## 联合安装事实

部署唯一所有者为任务“优化 MOSS-TTS-Nano 音色配置”（`01a0497e-72a6-72f0-aa25-cc7853e9bb81`）。本任务确认精确文件所有权、冻结哈希和用户授权后交接；没有抢占长期环境、重模型或安装锁。

该任务回传：通过正常公开插件安装及 `configure_qwenpaw_novel_agent.py` 完成联合部署，长期 18088 ready，插件 0.4.0，head0040；联合树 SHA-256 为 `51156d2eae280b52c6e2699c4cea8f1d9c30b2c72e927e904ea2e1c6695acfc0`。

- `ai-novel-writer`：11 个项目 Skill 和 5 个原有工具启用，`created=false`。
- 两份新 Skill 来源均为 `plugin:ai-novel-world-2026`；专用 Agent 启用，`default` 与 `QwenPaw_QA_Agent_0.2` 未启用。
- 模型仍为 `minimax-cn/MiniMax-M3`，未为本轮调用模型切换接口。
- 公开 Agent 提示 GET 仅去掉源码最后一个换行，`source == remote + "\n"`；正文无差异。归一 SHA-256：`8831bbce1dfdf934e8e8d22245e218f0be6fbe3149968c0614c92880626d70ff`。system-prompt-files 保留原有其他三项，共四项。
- 部署方已有整体 QwenPaw/小说数据备份；本任务没有另做即时提示文件备份，不宣称有独立备份。

本节安装结果来自部署所有者公开 API 检查回传，已核读 [计划56日志](../计划56/TTS56-JOURNAL.md)第9.10节，不冒充本任务另行安装或独立运行检查。TTS 其余验收与本次方法发布无因果关系。

## 明确未验收项与恢复

1. 新模块已经注册、启用并写入原生 Agent 路由，但未用当前用户模型验证每次都会装载。
2. PawApp 受控生成目前调用单一 `ctx.chat(skill="prose-writing")`，且可信任务禁止额外工具；本轮没有增加上下文装配业务代码。因此“不额外操作就能保证每个章节按钮自动用到两份新分类方法”未验收，不能宣称。保留原九通用 Skill，避免损坏原有路径。原生“AI 小说作家”可明确要求使用对应模块。
3. 本轮未对新装模块做完整卸载/重装、所有原生页面回归或真实用户模型 A/B。既有生命周期合同通过不代替上述运行验收。
4. 如果后续发现方法不合适，可在专用 Agent 停用相应模块，退回通用方法；如需彻底回退路由应恢复本次提示改动并按公开配置同步。不得重置用户小说、模型或其他 Skill。
