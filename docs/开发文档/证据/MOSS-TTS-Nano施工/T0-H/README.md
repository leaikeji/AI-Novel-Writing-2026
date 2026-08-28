# T0-H 数据/API/安全契约审查证据

工作包：`T0-H`

Owner：`/root/tts_t0h_contract_audit`（只读审查与证据编写；主代理是唯一集成责任人）

状态：**工作包审查与主代理冻结完成；T0-GATE 已对 `gate-decisions.md` 的 2026-08-26 原始快照固定 SHA-256 作 `ACCEPT_UNCHANGED`。2026-08-27 只增加个人本地官方预设适用范围覆盖，不重算或替代历史 hash。该接纳只冻结后续施工输入，不代表 T1 schema、API、worker、媒体或隐私控制已经实现；T0 总门禁仍等待其他工作包收口。**

开始时间：2026-08-26 01:29:53 +0800

结束时间：2026-08-26 01:42:27 +0800

## 1. 结论

- T0-GATE 关闭前仍不得直接并行写 T1 migration/API；
- 固定本地 owner/workspace、approved script 不可变、持久 narration request、taxonomy v1、job fencing 和 Manifest/媒体 GC 六项 P0 已由主代理展开为 10 项精确决策并按固定 hash 接纳；
- 推荐方案不修改 QwenPaw 上游、不建设 RBAC、不创建第二套业务 API 或任务账本；
- 详细契约见 [contract-review.md](./contract-review.md)，STRIDE 与隐私/滥用风险见 [threat-model.md](./threat-model.md)。
- 主代理冻结裁决见 [gate-decisions.md](./gate-decisions.md)；T0-GATE 已接纳其固定 hash，但仍须等 T0 总门禁形成下一 ready set 后才可按其中 Owner 顺序开放 T1。

## 2. 基线与 dirty 状态

- 仓库：`/Users/liujia/Documents/AI小说世界2026`
- 分支：`main`
- 启动基线 HEAD：`9b5be4a`
- 启动 `git status --short`：20 条既有 dirty/untracked 项；它们全部视为其他任务/用户改动，未修改、暂存、提交或清理。
- 专项主文档本身在启动时已有未提交施工授权/CLI 修订；本审查冻结并读取当时的 working-copy 快照，不把它改回 HEAD。下表 hash 是执行时快照，后续主代理集成继续修改该文档时不会追写为当前 hash。
- 禁止范围：未访问旧项目 `/Users/liujia/Documents/AI小说世界3/Data`；未读取 `.env`；未访问真实小说、私人音频、正式数据库或模型权重。

### 2.1 冻结输入

| 输入 | SHA-256 / 标识 |
| --- | --- |
| `docs/开发文档/18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md`（T0-H 开工时 working-copy 快照，非当前文件 hash） | `9b37d4c2e1cdf0e1b30aa8d8123bbaf2df3853efb2242aabaa654f307cda6b69` |
| `docs/开发文档/01-架构边界与模型接入决策.md` | `4b9986689e321e42ea787fb0504152ba43aeb7b6cb9a7298c79acee2c754f45d` |
| `docs/开发文档/06-总体架构与核心流程.md` | `81c2703791f202be8d3bdbf5b4db0e07894e568edde936d71dfbd29059604f44` |
| `docs/开发文档/09-创作工作台内容模型与关系图产品规格.md` | `f9eec8df9019037c2896c17bb2762cacf42e941dfc92e8d4099b730caf793771` |
| `backend/models.py` | `047b53f372d95ebc132370823de769f310f3501463560cabc78b268a022800eb` |
| `backend/services.py` | `c03b95d71cc6b60b8e6cbdf6f49ef59bb3963e68060db18a5ba7472bf83a0049` |
| `backend/app.py` | `084217300c4354f12143ad9f4f72c4844bf1d6ea90f2b375b2bf41b8a39ed705` |
| ADR | `ADR-0001..ADR-0004` 当前 working tree 只读内容 |
| 迁移头 | `20260825_0009`，`down_revision=20260824_0008`（只读核对，未分配新 revision） |

只读范围还包括当前 backend creative/model/assistant/job 代码、相关测试、plugin、compose、Dockerfile、`.env.example` 与安装/卸载验证脚本。未把专项目标误写成当前实现。

## 3. 实际产物

| 文件 | 用途 | SHA-256 |
| --- | --- | --- |
| [contract-review.md](./contract-review.md) | 事实/目标/缺口、P0/P1/P2、T1 schema/API/state/transaction/media/privacy/非回归冻结建议；末尾保留主代理候选裁决追记 | `afed19c3cca22bed3de919caa2ec0219efc8e067648063751a0efe95d8e83a5e` |
| [threat-model.md](./threat-model.md) | STRIDE、隐私与声音滥用风险、缓解、验证证据和剩余裁决 | `f9728e5ae8c01e62f19a582bc97b60e6ddcc42236a8de1aa0b0f7af2e9ccbcfe` |
| [gate-decisions.md](./gate-decisions.md) | 主代理冻结的 10 项精确 T0-GATE 候选、唯一 Owner 顺序与负向测试映射；hash 指 2026-08-26 原始快照，后加范围注释不重算 | `2437be4e13e182aae554cb853f16afbc0b475d51848ce2d413eb4c3d9076e283` |
| `README.md` | 基线、命令、环境、结果、风险、回退和接线说明 | 自引用文件不内嵌自身 hash；交接时由主代理重新生成 evidence manifest |

产物均为 Markdown；没有权重、音频、私人正文、数据库 dump、secret 或生成物。

## 4. 环境

```text
OS      Darwin 25.5.0 arm64
macOS   26.5.2 (25F84)
Python  3.12.13（项目 .venv；本工作包未执行 Python 代码）
Git     2.50.1 (Apple Git-155)
DB      未连接、未迁移、未读取正式数据
Model   未下载、未加载、未调用
Browser 未启动
```

## 5. 命令、退出码与计数

### 5.1 输入审查

| 命令/检查 | 退出码 | 通过 | 失败 | 跳过 | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| `git status --short` + `git rev-parse --short HEAD` | 0 | 1 | 0 | 0 | HEAD `9b5be4a`；记录 20 条既有 dirty/untracked |
| `sed`/`rg` 读取 README、索引、专项 18、01/06/09、ADR-0001..0004、backend/迁移/测试/插件与部署边界 | 0 | 1 | 0 | 0 | 只读完成；未访问禁止目录/真实数据 |
| `shasum -a 256` 冻结核心输入 | 0 | 7 | 0 | 0 | hash 见第 2.1 节 |

### 5.2 Markdown 与链接自检

首次完整产物自检结果：

| 检查 | 退出码 | 通过 | 失败 | 跳过 | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| 本地 Markdown 链接逐项 `test -e` | 0 | 2 | 0 | 0 | `local_link_missing=0` |
| fenced code block 偶数检查 | 0 | 2 | 0 | 0 | contract 14、threat model 4 |
| 标题/表格结构统计 | 0 | 2 | 0 | 0 | contract 45 headings/138 table rows；threat 11/46 |
| 行尾空白 `rg -n '[[:blank:]]+$'` | 0 | 2 | 0 | 0 | 0 命中 |
| 运行时/数据库/真实模型测试 | 未运行 | 0 | 0 | 1 | T0-H 是只读契约审查，且生产 schema/worker 尚不存在 |

最终包含 README 的链接、结构和 `git diff --check` 补充结果由本文件第 8 节记录。

## 6. 未验证与已知风险

未验证：

- 尚未执行 migration、API、数据库约束、job runner、Range/ETag、GC、consent、日志捕获或卸载运行测试；
- 当前没有 TTS schema/代码，报告给出的约束都是 T0-GATE/T1 的施工输入；
- 固定本地 owner/workspace、HMAC keyring 和彻底删除语义已由 T0-GATE 按固定 hash 正式接纳，但仍需后续 migration/服务/恢复测试验证；
- 物理 Nano/VoiceGenerator 拓扑、资源限制和 loopback/IPC 认证要结合 T0-B/T0-D 实测；
- 声音许可的法律充分性不能只靠工程字段自动保证。

历史风险是未冻结契约就让 T1 子代理各自解释 schema，最可能造成跨 scope 缓存、`analyze_only` 绕过、approved 行被改写、过期 worker 发布和 GC 误删；该解释分叉已由固定 hash 接纳关闭。当前 T1 仍因 T0 总门禁尚未关闭而保持 `HOLD`，后续实现必须逐项验证而不能把契约接纳当成代码通过。

## 7. 回退与接线说明

### 7.1 回退

本工作包及主代理汇合只新增/修改本目录四份文档，没有运行时、数据库、媒体或用户创作内容变化。若 T0-GATE 否决候选，应修订或移除 `gate-decisions.md` 并保留原审查历史；无数据库/进程/卷恢复动作。子代理未执行 `git add`、`git commit` 或 `git push`。

### 7.2 接线

主代理已在 T0-GATE 完成前四项冻结动作，后续施工继续遵守：

1. ADR-0005/0006 与 T0-GATE 已引用同一 `gate-decisions.md` 固定 hash；
2. `H-P0-01…06`、`H-P1-01…10` 已全部 `ACCEPT_UNCHANGED`，不得由实现工作包另行解释；
3. T1 ready set 形成后，给 T1-A/C/D/E/F 施工卡附上对应章节和唯一 schema owner；
4. T1-D 只消费已冻结的 owner/workspace、request intent、taxonomy、approved 终态、job fencing、Manifest/GC；
5. 在 T1-GATE 执行 threat model 第 4 节负向测试与 QwenPaw TTS 非回归验证；
6. 若选择不同方案，更新专项主文档中的矛盾点后再开放下一 ready set。

本报告不修改专项主文档，避免子代理越过文件 Owner；主代理负责最终集成。

## 8. 最终自检补充

README 与主代理候选文件写入后重新检查四份文件：

| 检查 | 退出码 | 通过 | 失败 | 跳过 | 最终结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| 本地 Markdown 链接逐项存在 | 0 | 4 | 0 | 0 | `local_link_missing=0` |
| fence 偶数、标题/表格可识别、行尾空白为 0 | 0 | 4 | 0 | 0 | fence 为 README 2、contract 14、gate decisions 16、threat 4；四文件 trailing whitespace 均为 0 |
| `git diff --check -- <T0-H目录>` | 0 | 1 | 0 | 0 | 无诊断 |
| `git diff --no-index --check /dev/null <file>` 补查未跟踪内容 | 1（预期表示有 diff） | 4 | 0 | 0 | 四文件 check diagnostics 均为 0；未用暂存绕过未跟踪文件限制 |
| `git status --short -- <T0-H目录>` | 0 | 1 | 0 | 0 | 仅显示 `?? .../T0-H/`；未触碰目录外文件 |

原只读审查交付时共 842 行；主代理完成最终 wire 对账后共 1,078 行（README 136、contract 551、gate decisions 230、threat 161），非自引用产物 hash 见第 3 节。T0-H 契约已被固定 hash 接纳，但 T0 总门禁仍为 `HOLD`，不能仅凭本工作包开放 T1。
