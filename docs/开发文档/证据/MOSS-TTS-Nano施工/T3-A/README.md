# T3-A 朗读脚本公共契约冻结记录

结论：**GO；T3-A 串行契约冻结通过，释放 T3-B–T3-I 按文档并行施工。T3-GATE runtime 仍为 HOLD。**

工作包：`T3-A`（`SER`）。Owner：主代理 `/root`。只读终审：`t3a_utf16_schema_audit`、`t3a_state_redteam`、`t3a_compat_audit`。

执行日期：2026-08-26（Asia/Shanghai）。Git 基线：`2caab228af15d5e4a5e858264799a67aede62f3d`（`main` / `origin/main`）。本工作包未暂存、未提交、未推送。

本结论只冻结不可变脚本、场景、句段、说话人、选角、权威证据与状态机的 v1 契约。它不表示自动人物识别、自动选角、脚本持久化适配、脚本复核 UI、语音合成或播放已可用。

## 1. 冻结产物与 SHA-256

| 文件 | 作用 | SHA-256 |
| --- | --- | --- |
| `backend/narration/script_contracts.py` | typed runtime contract、派生 ID、唯一持久投影、权威校验与 wire parser | `c32cd8db3a52ff4a0495ff30947b38a08885c952fd7743b88ee6298a0719656c` |
| `tests/fixtures/narration/script-contract-v1.json` | Draft 2020-12 版本化 schema、短文 fixture、状态机与持久投影声明 | `558c80d3dd8fa877fc9d58d18727aa9436db61dcd7814a054891c505effbc78d` |
| `tests/narration/test_script_contracts.py` | 结构、权限、UTF-16、状态、哈希与兼容负测 | `9db55718c9c3eafd9216c3c74b7da94228abf289a8b87cf6b992e56c09eac3ad` |

本 README 不记录自身 hash，避免自引用循环。

## 2. 已冻结的关键不变量

- 权威 revision 按 UTF-16 code unit 的半开区间映射；source-bound segment 和 source block 必须从 0 到末尾完整分区，不得有缺口、重叠、回退或区块交错。
- scene/segment/source-block/anonymous/group ID 均由版本、范围、局部哈希或稳定键派生；非规范 UUID、surrogate 断点、非 NFC 可发声文本和未知枚举均 fail-closed。
- `CastingTargetRef`、`CastingDecision`、`CastingRuleAuthorityRecord` 保留精确 character—binding、anonymous—binding、pool—slot 以及 rule—version—decision—segment—source—speaker/casting 关系，不接受“每个 ID 都合法但组合是假的”。
- `CloudAuthorityRecord` 精确绑定 consent/model-run/keyed input/output digest、actual model fingerprint、segment、源文局部哈希和 speaker/casting digest；同一证据不得重放为另一人物或音色决定。每个云端辅助句段必须有 `W_CLOUD_ASSISTED_USED`。
- v1 不提供缺少持久证据位的 `cloud_assisted` 场景边界来源；云端建议只能先物化为本地/人工边界。
- 每个父版本必须由服务端完整且互斥地分类为 `manual-review` 或 `verified non-review`；缺失或重叠分类直接拒绝。已验证的 blocker 修正子版本不得自动批准，只能由 owner `manual_after_review`。
- state、version、policy、requested/actual model 和完整 approval actor/time 均与服务端 authority 精确相等。workflow failure 属于 request，不写入 script issue。
- 当前版本只有一个权威 `immutable_hash`：对 T1 `NarrationScriptVersion` 现有持久投影的 canonical JSON 直接 SHA-256。未新增第二 envelope/hash，也未把 `voice_version_id` 冻结入脚本。

## 3. 自动化与终审

| 检查 | 实际结果 |
| --- | --- |
| `.venv/bin/python -m json.tool tests/fixtures/narration/script-contract-v1.json` | exit 0 |
| Python `py_compile` | `script_contracts.py` 和测试文件 exit 0 |
| `.venv/bin/python -m pytest -p no:cacheprovider tests/narration/test_script_contracts.py -q` | `54/54 passed` |
| T1 contract + T3-A + domain service 联合束 | `113/113 passed`（`47 + 54 + 12`） |
| `.venv/bin/python -m pytest -o addopts='' -q -ra` | `804 passed, 88 skipped, 1 warning` |
| `__all__` 完整性 | 64 个导出，0 missing，0 duplicate |
| `git diff --check` | exit 0 |
| UTF-16/schema 只读终审 | GO；P0=0，P1=0；1 项非阻断 schema 证据债 |
| state/cloud 只读红队 | GO；P0=0，P1=0，P2=0；额外 23 项固定 authority 矩阵 0 failure |
| T1 持久兼容只读终审 | T3-A GO；P0=0，P1=0；T3-GATE runtime HOLD |

88 项 skip 均来自未注入的 PostgreSQL/集成测试 URL；T3-A 是纯契约工作包，未触碰正式数据库、Docker、QwenPaw 宿主、模型、媒体或真实小说。

## 4. 剩余 HOLD 与非阻断债

1. 项目 `.venv` 未安装 `jsonschema`，checked-in 测试使用依赖无关的窄 schema 校验器，未验证 Draft 2020-12 `format`。运行时仍对 UUID、UTC datetime、SHA-256、NFC 和闭合字段严格解析，因此这是证据 P2，不是运行时绕过。本工作包不为此引入新运行依赖。
2. T1 `script_versions.py` 尚未实现 typed reverse loader、旧行兼容读、幂等 replay 服务端 ID/version/action/time/cloud evidence、完整 authority loader 或合法 synthetic pause 空 `spoken_text`。这些必须在 T3-GATE 的唯一 Owner 中集中适配，不得由 T3-B–T3-I 分散改共享文件。
3. 自动人物识别、自动选角、脚本复核和用户可用 runtime 继续为 false/HOLD，只有 T3-B–T3-I 完成并经 T3-GATE 集成后才能改变。

## 5. 下一 ready set

T3-A 从此作为冻结输入，释放不重叠的 `T3-B`、`T3-C`、`T3-D`、`T3-E`、`T3-F`、`T3-G`、`T3-H`、`T3-I`。各工作包只能修改主文档 18.0.11 分配的精确文件；`backend/narration/script_contracts.py`、fixture、`script_versions.py`、共享入口和本文档均只读。主代理在全部候选回传后依次执行越界复核、集成、全量回归和 T3-GATE。
