# T3-H 脚本复核、冻结策略与 UI 候选证据

## 结论

- 工作包：`T3-H`（`PAR-C`）
- Owner：主代理 `/root`
- 候选结论：`PASS`；允许进入 T3-I/T3-GATE 集成审查
- 产品结论：`HOLD`；本包未接共享入口、数据库 backend、request 编排或 Edition，不能据此宣称自动识别/选角已对用户可用
- 开始/结束：2026-08-26 22:48–23:12（Asia/Shanghai）
- 开始基线：`2caab228af15d5e4a5e858264799a67aede62f3d`
- 并行工作树说明：施工期间另一个已授权任务在 23:07 把 `HEAD` 推进到 `9d1ad30e9fbbc70d4b1ccce1e2d9bdb7eaae1ce1`；T3-H 没有执行 Git 写操作，九个实现/测试文件仍为未跟踪候选。工作树同时含其他任务改动，本包未清理、覆盖、暂存或提交它们。

## 冻结输入

- `backend/narration/script_contracts.py` 与 `tests/fixtures/narration/script-contract-v1.json`（T3-A GO）
- `backend/narration/contracts.py` 的 `narration-review-taxonomy/1`
- `backend/narration/script_versions.py` 的 T1 不可变版本、请求 generation guard 与批准基础（本包只读）
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T0-H/gate-decisions.md`
- 主方案 1.2、5.1、13.4、18.0.4、18.0.9、18.0.11 与 18.0.13
- UI 发布目标：且仅验收 1920×1080、2560×1440 各自助手收起／展开的四个精确组合；低于 1920×1080、移动、窄屏和 200% 等效小视口不是本专项目标、测试项或发布阻断项

## 实际修改文件与 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/script_review.py` | `f9d259cef19972fe409d4e802cbceef1370bde72b0a99636ac7b309b51b0ecd6` |
| `backend/narration/script_api.py` | `90e4741f84d0e9175ab51fd676a67603d4e4314565d221cf078dc22600ff3999` |
| `tests/narration/test_script_review.py` | `cf46f9994b7921d1abebdabd33de846b32722119da799bdf69c9ec984d21c704` |
| `tests/narration/test_script_api.py` | `b1d07e047e9b6a0d3feb808e0e52cb21c1655a23f94ddacab8ef535de4591dd3` |
| `frontend/src/narration/script-contracts.ts` | `9abb754ce8c45925c7bd38c968f6efc57138ddf4147c8321cd976c153d0d54cb` |
| `frontend/src/narration/script-api.ts` | `d259451b8251937ae6339502cfa3b2a818caf9e7a3421db004c9e66bfd857a31` |
| `frontend/src/narration/script-api.test.ts` | `035d35f2d53fad6ac3a111d6f508fd99af615f6d11ec575f7b585663ab51497c` |
| `frontend/src/narration/script-review-panel.ts` | `69e708e3fd95cf3465ecac32cf1148ba004ec120a1fb95f9427ba8fed34bcb4a` |
| `frontend/src/narration/script-review-panel.test.ts` | `6bae0da8be358d8580682d8d43dd8fdb1e05e2fe93e27e0fae739a35bf71715b` |

上述 hash 是 23:12 窄测时的原始记录；后续若主代理因自查修正文件，T3-GATE 必须重新计算并以门禁记录为准，不得把旧 hash 当作最终发布 hash。

## 已实现的不变量

### 领域复核与两条冻结路径

- severity 只能由冻结 taxonomy 服务器重算；未知 code、未来 taxonomy、模型/客户端伪造 severity 和重复 issue evidence 全部拒绝。
- `analyze_only` 即使零 blocker 也永不冻结、永不授权 Edition。
- `blockers_only + 0 blockers + 显式生成意图` 只允许 `system/service` 记录 `auto_no_blockers`。
- `always_review + 0 blockers` 只允许 owner 记录 `manual_after_review`。
- blocker 不可在旧版本原地“勾掉”；作者修正必须形成新版本，blocker 清零后再批准。
- 父版本必须由服务端互斥且穷尽分类为 `manual-review` 或 `verified non-review`；缺失/重叠分类失败关闭。已验证 blocker 修正子版本不能绕过人工复核。
- 批准只改变状态/审计，不改变现有不可变脚本 hash。

### 严格 API facade

- 冻结六个受控动作：analyze、get script、get version、segment correction、approve、reanalyze segments。
- segment correction 返回新脚本版本候选，不 PATCH 持久旧句段；请求携带旧 version/hash/local hash 与幂等键。
- approve 必须携带 request、version/hash、来源 revision 和显式 `confirmed=true`；客户端不能传 owner/workspace/actor。
- reanalyze 最多 64 个唯一 segment id；所有写动作使用 8–128 字符安全幂等键。
- backend 未由 T3-GATE 安装时统一 `503 SCRIPT_BACKEND_NOT_INSTALLED` 且 `Cache-Control: no-store`。
- response 严格拒绝未知字段、计数漂移、非法 issue/segment 关系、unknown 无 blocker、未解析 casting 无 blocker、低/中/未知置信缺少对应问题、越 scope、superseded 仍可批准和伪造批准 actor。

### 复核面板

- 默认只看 blocker，可切换全部 warning；零 blocker 的 `always_review` 仍显示全章句段。
- blocker 未清零时主按钮不可调用；批准会实际调用严格 API，而不是演示按钮。
- 修改人物/音色只在真实编辑回调存在时可操作；单句重新分析调用受控 API 并只接受同 script/document 的更高新版本。
- working copy 已分歧时，作者必须明确选择“继续生成该快照”或“使用最新正文重新分析”；无真实回调的动作保持禁用。
- 打开面板后聚焦首个 blocker（无 blocker 时聚焦标题）；关闭/卸载后只恢复一次原触发控件焦点。
- 状态同时使用文字、计数和 `data-severity`，含 `dialog`、heading、live status 与 `aria-busy`；组件标记 `data-min-viewport="1920x1080"`。

## 实际验证

环境：macOS arm64；项目 `.venv` Python `3.12.13`；Codex 工作区 Node `v24.19.0`；根项目固定 `pnpm@11.19.0`。

```text
.venv/bin/python -m pytest -q \
  tests/narration/test_script_review.py \
  tests/narration/test_script_api.py
=> 39 passed，0 failed，0 skipped；1 条既有 Starlette/httpx2 deprecation warning

.venv/bin/python -m pytest -q \
  tests/narration/test_script_contracts.py \
  tests/narration/test_script_review.py \
  tests/narration/test_script_api.py
=> 93 passed，0 failed，0 skipped；1 条同上 warning（2026-08-26 23:17 最终窄测）

pnpm exec vitest run \
  frontend/src/narration/script-api.test.ts \
  frontend/src/narration/script-review-panel.test.ts
=> 2 files passed；28 tests passed；0 failed

pnpm typecheck
=> PASS

pnpm build
=> PASS；71 modules transformed；frontend/dist/index.js 2,212.31 kB（生成物未手改、未纳入本包）

.venv/bin/python -m py_compile <四个 T3-H Python 文件>
=> PASS

逐文件 git diff --no-index --check /dev/null <九个未跟踪候选>
=> PASS
```

`.venv/bin/ruff` 不存在，因此没有伪称执行 Ruff；项目要求的 Python 窄测、`py_compile`、行尾检查和 100 字符行长自查已执行。

## 人工验收与未验证项

- 已人工检查：所有按钮均为真实 API/显式回调/本地确认动作；未接回调的按钮禁用；错误消息不显示 backend 原始异常；面板不会修改正文或历史脚本。
- 尚未执行真实浏览器截图、系统中文 IME、1920×1080/2560×1440 焦点走查和 QwenPaw 入口/卸载非回归，因为共享入口与样式属于 T3-GATE，当前产品仍 HOLD。
- 尚未安装 DB-backed script backend、request/Edition 编排；未运行真实模型、网络、Docker、数据库或媒体。
- 尚未证明 T3-B–T3-G 组合结果能完整 round-trip 到持久 `script_versions.py`；这是 T3-I/T3-GATE 的集成责任。

## 风险、回退与主代理接线说明

- `script_api.py` 当前只冻结 facade；T3-GATE 必须用固定 owner/workspace 的服务端 factory 接线，并在卸载时按 identity-safe 方式移除。
- T3-GATE 必须把 T3-A typed script 无损投影到现有 `script_versions.py`，重放原 action/time/approval/model/cloud evidence，禁止第二套 hash、状态机或迁移。
- segment correction backend 必须创建新 immutable version；若旧 version/hash/local hash 或正文/设置 fingerprint 变化，返回 `STALE_INPUT`/`VERSION_CONFLICT`，不得套用到最新 working copy。
- 真实浏览器只验收 1920×1080 与 2560×1440；共享 `frontend/src/narration/styles.ts` 和入口仅由 T3-GATE Owner 修改。
- 本包未产生持久数据。门禁前回退可删除这九个候选文件和本证据目录；合入后使用普通 Git revert。不得删除数据库卷、小说 revision、历史脚本或媒体。
