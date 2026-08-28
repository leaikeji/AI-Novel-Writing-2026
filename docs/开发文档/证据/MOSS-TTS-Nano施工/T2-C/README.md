# T2-C 人物卡“声音”局部面板施工记录

结论：**PASS_CANDIDATE；T2-C 局部实现与目标自动化通过，等待 T2-GATE 唯一集成 Owner 接线和 T2-H 真实浏览器验收。**

工作包：`T2-C`（`PAR-C`）。Owner：子代理 `/root/t2c_character_voice`。执行日期：2026-08-26（Asia/Shanghai）。

本结论只证明人物卡声音局部组件的实现和 Node/Vitest 级别行为，不表示页面入口、真实后端、数据库、浏览器截图或产品 capability 已经打开。

## 1. 冻结输入与边界

| 项目 | 实际值 |
| --- | --- |
| 前置门禁 | `T2-A = ACCEPT_UNCHANGED` |
| `frontend/src/narration/contracts.ts` | `9a62723164027da7607ee4df0dc39bd61e9c21e89519d6cfb13352dfb66fc5ec` |
| `frontend/src/narration/api.ts` | `2c675603fe7e19b0d2dcf362015a432a2fe1cf36920b4096bf52c8a479b9dce8` |
| `backend/narration/schemas.py` | `1e189e812cf674b0d9457328d4e74e95fda57a67b62a83f99eb31d299633fdbd` |
| `backend/narration/settings_api.py` | `05b1a6be9ab58d30ccb12d143033a96aa8feb9fec7a6ed7ad1a6560894505378` |
| API 限界 | 只使用 `getCharacterVoiceBinding`、`listVoiceProfiles`、`putCharacterVoiceBinding` |
| 运行态 | 未访问 DB、Docker、QwenPaw 宿主、MOSS 模型、媒体或真实小说 |

开工时工作树已有 T0/T1/T2-A 候选以及其他专项和用户改动。本工作包没有暂存、提交、推送、清理或修改任何未分配路径，也没有修改上述冻结文件。

## 2. 实际文件与 SHA-256

| 文件 | 用途 | SHA-256 |
| --- | --- | --- |
| `frontend/src/narration/character-voice-panel.ts` | 局部 React factory、权限/能力门禁、三态绑定、CAS 与影响提示 | `2bad9d256c31c389e50a857cfd2da5eddc98bc6ec7ff338e66f6488d3e7fb576` |
| `frontend/src/narration/character-voice-panel.test.ts` | 资格过滤、权限、键盘语义、CAS 冲突、scope 与清理测试 | `7442ff2d8c51c135fbeeaa0f6203a8dfd4e7afad0017de7be17560d0061e49c0` |
| `frontend/src/narration/styles/t2-c.ts` | T2-C 独占样式片段，包含窄屏和 `:focus-visible` | `965b2220715a8198826fe7cd53dc42bed93318eea071950f5e0aed1a56cdae91` |
| `docs/开发文档/证据/MOSS-TTS-Nano施工/T2-C/README.md` | 本证据 | 不记录自身 hash，避免自引用循环 |

## 3. 已实现行为

1. 用原生 `fieldset`/`legend`/radio/label/select/input/button 组成键盘可达的人物声音面板，不依赖第二份 React 或 Ant Design。
2. 提供 `dedicated | inherited | unset` 三态。`unset` 精确提交空 profile/version；其他两态必须指向可选的不可变音色版本。
3. 可选音色必须同时满足：profile 为 `active`、scope 为当前作品或同 owner/workspace 公共库、`current_version_id` 指向 `locked`、`quality_state=accepted`、`rights.state=active`，且对应来源 capability 为 `enabled + visible + actionable`。
4. 人物声音修改还要求 `narration_product` 和 `reading_settings` 两个 capability 都可操作，以及 authorization 的 `can_read + can_configure`。任意一项不允许时，修改控件全部 fail-closed；`can_read=false` 时不发起 GET 且不渲染已加载数据。
5. 个人声音保存始终携带当前绑定 `expected_version`。`VERSION_CONFLICT` 后保留用户草稿，明示服务端版本，必须先点“刷新最新绑定”；刷新后仍保留选择，重试改用新版本 CAS。
6. 个人 GET、列表 GET 和 PUT 响应都在 UI 边界复核 novel/character scope；跨作品音色、重复 profile identity 或错人物响应会被拒绝，不渲染绑定控件。
7. 服务端 `impact` 以“保存影响预览（服务端基线）”展示受影响章节、句段、历史 Edition 数和 `regeneration_required`。候选变更未保存时明示最终数量以 PUT/CAS 响应重算为准，不伪造 dry-run 数据。
8. 文案明确承诺本次设置不改写或替换历史 Edition；需重生时也只在作者主动更新朗读后处理受影响句段。
9. 异步请求使用 `AbortController` 和序号 fencing；scope/授权变化时同步隐藏旧数据，卸载时 abort 并通知 host 恢复触发控件焦点。

## 4. 状态与可操作矩阵

| 状态 | 数据可见 | 配置可修改 | 保存 | 用户反馈 |
| --- | ---: | ---: | ---: | --- |
| `can_read=false` | 否 | 否 | 否 | 权限说明，不发 API |
| loading | 否 | 否 | 否 | `aria-busy` + live status |
| ready + 能力/授权允许 | 是 | 是 | 仅 dirty 且草稿合法时 | 同步/未保存状态 |
| ready + capability hold/unavailable | 是 | 否 | 否 | 显示稳定 reason code，所有修改控件 disabled |
| ready + `can_configure=false` | 是 | 否 | 否 | 只读说明 |
| 无合格音色 | 是 | 可切 `unset` | 配置态无合格版本时否 | 说明锁定/质量/授权/来源门禁 |
| saving | 是 | 否 | 否 | `aria-busy` + 保存中 |
| save-error | 是 | 是 | 可重试 | 稳定错误文案，草稿保留 |
| conflict | 是 | 否 | 否 | focusable alert，保留草稿，强制先刷新 |
| load-error/scope drift | 否 | 否 | 否 | alert + 重试；不回显跨 scope 数据 |

## 5. 验证与失败事实

Node 使用 Codex bundled Node 与 pnpm 11.19.0。

| 检查 | 最终结果 |
| --- | --- |
| `pnpm exec vitest run frontend/src/narration/character-voice-panel.test.ts` | 1 file，`10 passed`，0 failed，0 skipped |
| `pnpm typecheck` | `tsc --noEmit` exit 0 |
| 三个源文件尾随空白检查 | 0 命中 |
| T2-A 前端冻结 hash 复核 | `contracts.ts` 和 `api.ts` 均与冻结值一致 |

施工中的第一次目标 Vitest 为 `9 passed`。自查发现“授权或 character scope 在已加载后变化”的瞬时旧投影风险，于是在渲染和保存边界增加同步 scope 检查，并增加第 10 项回归测试。修正后目标 Vitest 和 typecheck 都一次通过；没有被隐藏的 failed/skipped 用例。

## 6. T2-GATE 接线契约

1. 本模块使用项目既有 factory 适配方式：`createCharacterVoicePanel(window.QwenPaw.host.React)` 返回 React component。正常 props 更新就是 update；React unmount 就是 destroy，会 abort 请求并调用可选 `onReturnFocus`。不需要额外 DOM mount runtime。
2. T2-GATE 只能在已有人物编辑表单的“声音”局部区域渲染它；新建人物尚无 server `character_id` 时不能伪造绑定，应先保存人物。
3. `capabilities` 和 `authorization` 必须直接传入 T2-B/T2-G 经冻结 parser 校验的服务端投影，禁止 host 伪造 enabled/actionable 值。
4. 本模块已直接使用 T2-A API client；集成层不得再包一套 DTO、CAS、错误映射或权限规则。`onSaved` 可用于 host 刷新作品概览，不得借此触发 TTS 或改写 Edition。
5. T2-GATE 由唯一 Owner 从本模块导出 `createCharacterVoicePanel`，并把 `T2_C_CHARACTER_VOICE_PANEL_STYLES` 按工作包顺序合入共享 `frontend/src/narration/styles.ts`。子代理本轮未修改 `index.ts`、共享 styles 或 workbench。
6. T2-H/T2-GATE 必须在真实人物卡 host 里检查焦点恢复、Tab/Shift+Tab、radio 箭头键、390 px 窄屏、720 px 对话框、加载/冲突/空音色状态，并用真实截图补齐视觉证据。

## 7. 未验证、风险与回退

未验证：真实 QwenPaw React/Ant Design host 中的布局、真实浏览器键盘/读屏、后端 dispatcher、数据库绑定、音色实体授权、动态 capability 全链路和真实影响重算。本轮没有生成截图；截图证据显式后移 T2-H/T2-GATE，不以 fake React tree 冒充 UI 实测。

冻结契约只提供 PUT 后的 `impact`，没有候选变更 dry-run API。因此面板展示服务端基线并说明最终值以 CAS 响应为准；若未来产品要求保存前精确模拟，必须由主 Owner 重开 T2-A 契约锁，本工作包不会自行添加第四个 API。

本工作包尚未接入共享入口，所以没有运行态副作用。如 T2-C 退回，只需由主 Owner 回退第 2 节三个源文件和本证据；不删除数据库、卷、音色资产、模型、历史 Edition 或用户正文。
