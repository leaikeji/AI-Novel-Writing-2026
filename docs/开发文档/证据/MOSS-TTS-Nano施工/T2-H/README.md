# T2-H 朗读设置 API／前端组合测试记录

> **2026-08-26 T2-GATE 最终更新（取代下方历史局部结论）：** `backend.app` 的 router/factory 红测已转绿，startup 启动失败会对称卸载；最终后端全量为 `741 passed, 87 skipped`，前端全量为 `55 files / 448 tests passed`，typecheck/build 均通过。真实 QwenPaw、29 个 HTTP 操作、1920×1080／2560×1440 浏览器及卸载／重装非回归也已完成，[T2-GATE 最终报告](../T2-GATE.md)已经通过。用户已明确低于 1920×1080 的布局不属于本专项验收范围。以下内容保留为 T2-H 在 17:39 CST 的测试先行历史快照，其中“一个显式红测／未接 backend.app／真实宿主未验收”等描述不再代表当前代码与门禁状态。

> **冻结源说明：** 下方表格保留 T2-H 收口时的历史 SHA-256。T2-GATE 经独立语义审计确认 wire invariant 未漂移，并把 `backend/narration/settings_api.py` 当前实现以 `AUDITED_IMPLEMENTATION_HARDENING_REFREEZE` 重新冻结；当前 `tests/narration/test_settings_api.py` SHA-256 为 `0ec41eff7e667ef612331df5d7cf6d18fcbbe318fbcedd401cafa2305209a90c`。不得用该最新值覆盖历史快照。

> **官方预设范围覆盖（2026-08-27）：** 下文“preset 可见但禁用”“无已批准 preset”只是历史 T2-H 快照，不能继续作为当前个人本地 `official_preset` 状态。固定 ONNX manifest 的 18 项全部允许本地使用，不设公众人物排除；可操作性只等待现行 catalog、溯源、实际推理与产品 GATE，商业发布／再分发未评估不阻断。

历史局部结论：**`TEST_FIRST_READY_WITH_ONE_EXPLICIT_T2_GATE_RED`。** T2-H 已在测试专属文件内完成冻结 29 个 HTTP 操作、错误映射、factory 安装／卸载、multipart 防线，以及 T2-B～T2-G 现存局部前端模块的组合与可访问性覆盖。该局部快照当时 60 个 T2-H 后端测试中 59 个通过，唯一失败是刻意保留的 T2-GATE 汇合断言；该红测后来已由上方主集成更新转绿。

工作包：`T2-H`（`TEST-FIRST`）。Owner：子代理 `/root/t2b_reading_ui`；最终汇合与门禁责任人：主代理 `/root`。

执行日期：2026-08-26（Asia/Shanghai）；局部收口时间 17:39 CST。

## 1. 基线、边界与冻结输入

| 项目 | 实际值 |
| --- | --- |
| Git 基线 | `2caab228af15d5e4a5e858264799a67aede62f3d`（分支 `main`） |
| 前置门禁 | `T2-A = ACCEPT_UNCHANGED`；T2-B～T2-G 为局部候选；T2-GATE 尚未完成共享接线 |
| 工作树 | 开工前已有 T0/T1/T2 其他工作包、其他专项和用户改动；T2-H 未覆盖、暂存、提交、推送或清理任何其他路径 |
| 运行态 | 未访问数据库、Docker、模型、媒体、私人录音、真实小说或正式 QwenPaw |
| 浏览器 | 未启动真实浏览器，未制作或伪造截图；真实 DOM/宿主验收归 T2-GATE |

收口时复核的冻结输入均与 T2-A 一致：

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/schemas.py` | `1e189e812cf674b0d9457328d4e74e95fda57a67b62a83f99eb31d299633fdbd` |
| `backend/narration/settings_api.py` | `05b1a6be9ab58d30ccb12d143033a96aa8feb9fec7a6ed7ad1a6560894505378` |
| `frontend/src/narration/contracts.ts` | `9a62723164027da7607ee4df0dc39bd61e9c21e89519d6cfb13352dfb66fc5ec` |
| `frontend/src/narration/api.ts` | `2c675603fe7e19b0d2dcf362015a432a2fe1cf36920b4096bf52c8a479b9dce8` |

T2-H 没有修改冻结输入、任何生产代码、共享入口、数据库迁移、Docker、现有其他测试或其他工作包证据。

## 2. 实际产物

| 文件 | 作用 | SHA-256 |
| --- | --- | --- |
| `tests/narration/test_settings_api.py` | 29 操作 HTTP 矩阵、27 错误码、factory 生命周期、multipart/no-go 与显式 gate 红测 | `0f2f433010926ae8f63128a37cdd5741bd4d1926003cfb6573f446d320c9e682` |
| `frontend/src/narration/reading-page.integration.test.ts` | 页面与现存局部模块组合、scope/CAS/drift、错误刷新和 abort | `229f2126dce4efe0a084e974c1a526b7fd3ff95002692e0e92de16880a8a2cdc` |
| `frontend/src/narration/reading-accessibility.test.ts` | loading/error/gated、原生键盘语义、ARIA 关联和窄屏样式钩子 | `3ea57f42a745c3007528b612ac5f9e7e1568f0b4d67be9e746d24ac4d7a5e902` |

本 README 不记录自身 hash，避免自引用循环。

## 3. 后端覆盖事实

### 3.1 29 个冻结 HTTP 操作

- 参数化矩阵精确覆盖 `NarrationSettingsOperation` 的 29 个枚举成员，并再次断言集合完全相等；
- 每条真实 FastAPI 请求只形成一个 typed command；novel/profile/preview/character/scope 身份、查询参数、幂等键和 payload 类型均在 dispatch 边界核对；
- PUT/DELETE/lock 请求携带冻结的 `expected_version` 或 `expected_profile_version`，create/consent/preview/upload 请求携带稳定 `Idempotency-Key`；
- 上传路由只把受限 multipart content type/body 交给唯一 dispatcher，不复制第二套路由或 DTO；
- 当前 backend 使用显式 no-go backend，所有操作统一得到 `CAPABILITY_DISABLED`、HTTP 409 和 `Cache-Control: no-store`，不会把“路由存在”误写成产品能力可用。

### 3.2 错误、multipart 与卸载

- `NarrationErrorCode` 当前 27 个成员全部走一次真实 HTTP 响应，逐项核对冻结 HTTP 状态、contract version、code、CAS current version 和 `no-store`；
- multipart 缺 boundary 在 dispatch 前返回 415，声明包体超过冻结 envelope 上限返回 413，缺幂等键返回 422；三种失败均不调用 backend，私人参考字节不出现在响应；
- T2-D 既有 `test_voices.py` 契约回归继续覆盖 exact two-part envelope、WAV/FLAC、16 MiB、文件名/MIME/magic/hash、重复 header/传输编码及 `rights.confirmed=false`；T2-H 实际运行并记录该回归，没有复制解析器；
- factory 安装时每个请求只打开一个 session；按同一 factory 卸载后再次请求返回 `SETTINGS_BACKEND_NOT_INSTALLED`，session 打开计数保持不变，证明卸载态先 fail-closed、零数据库访问；
- 路由面再次断言不存在 synthesis、player、VoiceGenerator 或 automatic-speaker 操作，T2-H 没有翻开任何 no-go capability。

## 4. 前端组合与可访问性覆盖

### 4.1 现存模块组合

- T2-B `createReadingPage` 从冻结 API 并行加载 overview 和 scope overrides；测试从 loading 进入 gated/ready，并只通过 `sectionContent` 组合其他工作包；
- T2-C 人物声音面板和 T2-D 音色来源面板实际作为 `characters` 局部内容注入；历史 T2 快照中 preset 可见但禁用，reference clone/VoiceGenerator 隐藏，不伪造候选音色或试听；该 preset 禁用状态已由后续官方目录裁决覆盖；
- T2-E 通用音色池实际显示 24 个定义槽和 `0/24` 的不可用事实，不生成自动选角动作；
- T2-F 发音与停顿、音频与缓存面板实际注入各自栏目；无读取授权时保持 blocked，并显示稳定原因；
- T2-G `createReadingStatus` 与 `createReadingRulesPanel` 实际注入 `casting-rules`；冻结产品 gate 下两个规则 fieldset、授权与保存操作均禁用，状态视图只呈现真实 blocker/warning 和稳定 reason，不把云端辅助或自动选角写成可用。

### 4.2 状态、范围与取消

- loading 使用 `role=status / aria-busy`；error 使用 `role=alert` 和真实 retry；gated 显示 `T2_GATE_REQUIRED` 并禁用写操作；
- scope 保存测试携带当前 CAS version 和完整 replacement；若响应漂移到其他 novel/scope，页面 fail-closed 为操作错误，并提供“刷新最新配置”；
- overview 或 scope list 返回其他 novel 时不会复用旧作品内容；重试后重新执行成对加载；
- 页面卸载会 abort 未完成的 overview/scope 加载，也会 abort 未完成的 scope mutation；迟到响应不能写入新作品页面。
- T2-F 发音／缓存面板的初始加载与 T2-G 规则面板的保存请求均在局部组件 unmount 时 abort；F 的 `onReturnFocus` 各回调一次，证明宿主销毁契约没有只停在页面壳。

### 4.3 键盘、ARIA 与窄屏

- 七项导航是 `<nav aria-label="朗读设置">` 内的原生 `<button type="button">`，只有一项 `aria-current="page"`；没有用 `role=button` 的 div，也没有把导航移出原生 Tab/Enter/Space 语义；
- overview、人物、音色来源、通用音色、发音、缓存、朗读状态和识别／复核规则局部区域的 heading/status/reason ID 均有可解析的 `aria-labelledby`、`aria-describedby` 或 live region 关联；
- disabled 音色来源按钮通过 `aria-describedby` 指向稳定 reason；隐藏 no-go 来源不进入 DOM；
- 窄屏契约验证页面根类 `anw-reading-page`、布局类 `anw-reading-layout`、导航类 `anw-reading-nav`，以及 T2-B 样式片段中的 `760px` 单栏/横向滚动、`:focus-visible` 和 reduced-motion 规则；真实布局截图仍待浏览器验收。

## 5. 自动化结果

命令使用项目 `.venv` 与 Codex bundled Node/pnpm 11.19.0。

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/narration/test_settings_api.py -q -k 'not t2_gate_deferred'` | `59 passed`，0 failed；1 条既有 Starlette TestClient deprecation warning |
| `.venv/bin/python -m pytest tests/narration/test_settings_api.py -q` | `59 passed / 1 failed`；唯一失败为第 6 节明确的 `DEFERRED_TO_T2_GATE`，0 skip，0 xfail |
| `.venv/bin/python -m pytest tests/narration/test_settings_contract.py tests/narration/test_settings_api.py -q -k 'not t2_gate_deferred'` | `88 passed`，0 failed |
| `.venv/bin/python -m pytest tests/narration/test_settings_contract.py tests/narration/test_voices.py tests/narration/test_reading_privacy.py -q` | `67 passed`，0 failed；覆盖冻结契约、multipart/rights 与当前聚合 dispatcher 领域回归 |
| `pnpm exec vitest run frontend/src/narration/reading-page.integration.test.ts frontend/src/narration/reading-accessibility.test.ts` | 2 files，`8 passed`，0 failed |
| `pnpm exec vitest run frontend/src/narration` | 13 files，`113 passed`，0 failed；包含 T2-G 自有规则／状态测试与 T2-H 组合测试 |
| `pnpm exec vitest run` | 53 files，`434 passed`，0 failed（执行时的共享工作树快照） |
| `pnpm typecheck` | `tsc --noEmit` exit 0 |
| `git diff --check -- <三个 T2-H 测试文件>` | exit 0 |
| 三个 T2-H 测试文件尾随空白检查 | 无匹配，`whitespace-ok` |
| 冻结输入 SHA-256 | 4/4 与 T2-A 一致 |

前端测试使用 repo-native 的最小 React host contract 检查状态与事件，不宣称等价于真实浏览器、ReactDOM 或 Ant Design 主题验收。

## 6. 唯一显式失败与 T2-GATE 退出条件

失败测试：

`test_t2_gate_deferred_router_and_factory_are_installed_by_pawapp_lifecycle`

当前精确缺失：

1. `router.include_router(narration_settings_router)`；
2. `install_narration_settings_backend_factory(...)`；
3. `uninstall_narration_settings_backend_factory(...)`。

该测试只读 `backend/app.py`，没有导入真实 QwenPaw 或访问数据库。T2-GATE 必须由共享文件唯一 Owner 完成路由接入，并在 startup/安装路径安装唯一 factory，在 shutdown/卸载路径按同一 factory 对称卸载。接线完成后应原样运行完整 T2-H 文件；正确结果是该红测转绿，而不是删除、skip、xfail 或弱化断言。

## 7. 给 T2-GATE 的导出、DOM 与样式接线说明

T2-H 本身只新增测试，不导出生产运行符号。T2-GATE 应消费现有局部模块，不复制实现：

- 页面：`createReadingPage`、`ReadingPageProps`、`readingSectionFromSearch`、`readingSectionSearch`；
- 总览：`createReadingOverview`、`READING_SECTIONS`；
- 人物：`createCharacterVoicePanel`；
- 音色来源：`VoiceSourcePanel`、`createVoiceSourcePanelModel`；
- 通用音色：`createVoicePoolPanel` 或 `createVoicePoolPanelView`；
- 发音／缓存：`createPronunciationPanel`、`createCachePanel`。
- 状态／规则：`createReadingStatus`、`createReadingRulesPanel`、`buildReadingStatusModel`、`buildReadingRulesPanelModel`。

页面挂载／事件契约：

- 根节点：`[data-narration-reading-page="v1"][data-novel-id]`；ready 时同时有 `data-active-section`；
- 导航事件：`onSectionChange(section)` 只同步有界 `reading_panel`，不得清除宿主 `novel_id`；
- 其他局部模块只通过 `sectionContent.characters / generic-voices / casting-rules / pronunciation / audio-cache` 注入；
- 销毁 React mount 时必须执行 effect cleanup，以触发 load/mutation AbortController；切换 novel 不复用旧 section 内容、scope target 或音色选项；
- `casting-rules` 注入 T2-G 的状态与规则组件；宿主回传的 settings/authorization/overview 必须来自同一次当前 novel 刷新，规则保存／授权变化后由回调触发总览重载。

局部样式由 T2-GATE 按唯一顺序汇合：`T2_B_READING_STYLES`、`T2_C_CHARACTER_VOICE_PANEL_STYLES`、`T2_D_NARRATION_STYLES`、`T2_E_NARRATION_STYLES`、`T2_F_NARRATION_SETTINGS_PANEL_STYLES`、`T2_G_NARRATION_READING_RULES_STYLES`。T2-G 的 style ID 为 `T2_G_NARRATION_STYLE_ID`；T2-H 已核对其 focus-visible 与 560px 窄屏规则，但真实视觉表现仍待 T2-GATE 浏览器复核。不得让并行工作包直接修改共享 `frontend/src/narration/styles.ts`。

## 8. 未验证、风险与回退

未验证：真实 QwenPaw PawApp 启停／安装／卸载、`backend/app.py` 共享接线、真实 PostgreSQL transaction/CAS、真实浏览器键盘与焦点、桌面／760px／480px 布局、200% 等效缩放、Ant Design 主题、真实网络 abort、声音文件、试听、模型和截图。T2-H 没有将这些项目写成“已验收”。

主要风险：T2-GATE 若遗漏对称 factory 卸载会让卸载后请求仍触发数据库；若把非 actionable capability 映射成可操作 section，测试的局部门禁会与共享入口漂移；若 T2-G 的设置／授权回调没有刷新同一 novel 的 overview，状态面板可能显示旧授权或旧 CAS version，因此共享接线仍须执行真实浏览器与响应漂移验收。

T2-H 没有运行态、数据库、容器、模型、媒体或用户内容副作用。需要回退时，只移除第 2 节三个测试文件和本证据；不得删除生产代码、数据库、卷、媒体、正文、其他 T2 工作包或用户改动。
