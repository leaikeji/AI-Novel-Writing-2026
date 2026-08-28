# T0-F 编辑器兼容性尖峰交付记录

状态：**CodeMirror 候选已通过严格 TypeScript 语义检查、25/25 专项 Vitest及真实 Chromium 的中文文本写入、undo/redo、自动保存回调、可点击行号 gutter、UTF-16 高亮、合成事件保护、Blob module 和多尺寸布局复验。系统级中文 IME、固定 QwenPaw 2.1.0 宿主 CSP、200% 缩放、长章滚动及可访问性仍未完成；当前为“CodeMirror 条件首选、textarea 安全降级、宿主门禁 `HOLD`”，不得表述为正式产品编辑器已经接入。**

## 1. 基线、Owner 与 dirty 状态

- 基线 commit：`9b5be4a1f8d20c707e5cd612186ffaa44fbd1ae0`
- Owner：Codex 子代理 `/root/tts_t0f_editor_spike`
- 开始时间：`2026-08-26 01:44 +0800`
- 收口时间：`2026-08-26 02:15 +0800`
- 工作区：开工前非洁净；既有 20 项 dirty/untracked 均按[专项证据总索引](../README.md)列出的只读禁区处理。
- 本 Owner 未修改、暂存、提交或清理范围外用户/其他工作包文件；未执行 Git 提交或推送。

开工 HEAD 与用户指定基线一致。施工期间其他 Owner 新增了 `prototypes/moss-tts-nano/package.json`、`pnpm-lock.yaml`、`node_modules`、其他 T0 原型、fixture 和证据；T0-F 只读消费 package/lock，未修改或接管这些路径。首次 frozen install 因 registry 重试中止；本工作包首次收口后，主代理移走损坏缓存并以同一 frozen lock 完成 123/123 包安装（exit 0）。pnpm policy 忽略 `esbuild`/`protobufjs` install scripts，但本节记录的 Vite/Vitest 实际命令均成功。

## 2. 冻结输入与输入 hash

| 输入 | SHA-256 | 用途 |
| --- | --- | --- |
| `docs/开发文档/18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md`（T0-F 开工时快照，非当前文件 hash） | `9b37d4c2e1cdf0e1b30aa8d8123bbaf2df3853efb2242aabaa654f307cda6b69` | T0-F、编辑器跟随、UTF-16、降级与门禁契约 |
| `vite.config.ts` | `58602266d6808de70f625a19616faed6b5df40a66d5ea276bfefea5111cdf0b4` | 单 ES module、`inlineDynamicImports`、Blob URL 事实 |
| `frontend/src/workbench-v2.ts` | `b5734a573961b3fbc20941b624e414809972226fe380c24a044a060a5768b853` | 当前受控 textarea、selection 与自动保存接线事实 |
| `prototypes/moss-tts-nano/package.json` | `8c25128e26c2f2662261825e7320e728f332d95a09efb09ccf40a61956413d18` | T0-A 冻结的 CodeMirror/Monaco/Vitest/Vite 版本 |
| `prototypes/moss-tts-nano/pnpm-lock.yaml` | `a486e6024d813dcbacc83eec6a0d717daeca3b4a6de1d28ec0b9cebfcf9b0a5a` | T0-A frozen lock；主代理后续安装成功 |

只读范围还包括根 `package.json`、当前 textarea 自动尺寸、选区、UTF-16 transaction、undo 与相关测试。未访问旧项目禁止目录、`.env`、真实小说、浏览器扩展、QwenPaw 私有实现或真实用户数据。

## 3. 实际产物

| 文件 | 用途 | SHA-256 |
| --- | --- | --- |
| `prototypes/moss-tts-nano/editor/editor-spike.ts` | 最小 `NarrationEditorBridge`、保守 transaction 映射、可挂载 CodeMirror 公共 API 适配尖峰和 textarea 降级常量 | `b4a13385623f63058292f904103018b3a6234f6bfb61c3d6688461cba19d26f7` |
| `prototypes/moss-tts-nano/editor/editor-spike.test.ts` | 25 个已通过用例；新增真实挂载、行号 gutter DOM 可达性和公开 undo/redo handle 断言 | `2dcb40e21dbac8889872ddf1a95b3a6a41a0adb2abd1b95bbf2264f0f4ba0ea4` |
| `prototypes/moss-tts-nano/editor/vitest.config.ts` | 隔离 jsdom Vitest 配置 | `a6b6d270f8346d69748942a12051984dfc73533473ce159ffa895ae37bcb9617` |
| [matrix.json](./matrix.json) | CodeMirror、Monaco、textarea 的事实/隔离浏览器结果/宿主待验证三态矩阵 | `9d776fa54f89c982b10504fea85ee95249893f761cdf7a4976966ec2121ec288` |
| `README.md` | 本记录 | 自引用文件不内嵌自身 hash |

主代理取得 `LOCK-BROWSER` 后新增四张真实 Chromium 截图，并以 `sips` 二次核验实际像素：`editor-1920x1080.png`、`editor-2560x1440.png`、`editor-constrained-1024x768.png`、`editor-mobile-390x844.png`。它们是隔离原型证据，不是 QwenPaw 正式页面截图。

## 4. 已实现的候选契约

`PrototypeNarrationEditorBridge` 当前源代码候选提供：

- 读取正文、UTF-16 selection、composition、自动跟随和当前句段状态；
- 按 `segment_id`、`source_block_key + UTF-16 range` 或光标解析仍合法的播放起点；
- 标记、滚动、清除当前句段，且这些操作不改 selection；
- 只为 gutter、显式命令和明确标识的不可变旧稿句段发出跳播意图；普通正文点击固定为 caret-only；
- transaction 只移动未相交且源文本/局部锚点仍一致的映射；相交、边界相邻、段落拆并、引号和标点边界按来源块保守失效；
- IME composition 期间禁止播放器高亮或滚动抢焦点；手动滚动后暂停跟随，只有显式恢复才继续；
- 活跃会话中的 undo 不自动猜回已失效映射；页面重载后只有服务端确认正文 hash 与 Edition 完全一致时才能按不可变源范围重绑；
- textarea 降级不做视觉叠层：只允许旧稿只读句段、段落列表或显式命令跳播，正文分歧时使用播放器字幕/不可变旧稿抽屉和“更新朗读”。

CodeMirror 尖峰只使用公开 `EditorState`、`StateEffect`、`StateField`、`Decoration`、`lineNumbers`、`history`、`keymap` 和 `EditorView.updateListener`。真实浏览器首轮发现空 `gutter()` 没有可点击行标记，主代理改为带事件处理器的 `lineNumbers()` 后复验 4 个可见行号，第二行点击准确产生 UTF-16 offset `8`；该失败与修复均保留。Monaco 同一测试文件中的公开 model/range/decoration/edit/undo 风险探针已通过；它不启动 worker，不能据此推定 worker、CSP、完整 bundle、IME 或 glyph margin 通过。

## 5. 用例清单与真实执行口径

当前共 **25 个已通过用例**，覆盖：

- emoji、组合字符和禁止拆分代理对的 UTF-16 边界；
- 段前、段内、段后、句段起止边界、段落拆分/合并、引号和标点；
- 局部文本/锚点复核、1,500 来源块长章节；
- composition 期间不跟随、selection 保留、手动滚动暂停/恢复；
- 普通点击不跳播，gutter/命令/旧稿句段意图分离；
- 工作稿分歧后的页面重载失效与精确 Edition hash 重绑；
- CodeMirror decoration 映射、history undo/redo、自动保存 change hook、gutter 扩展；
- Monaco model UTF-16/range/decoration/edit/undo 风险探针；
- 内存中 Vite 单 import-free ES module 构建断言。

最终执行结果为 **25 passed / 0 failed / 0 skipped**。期间保留四类失败事实：错误 Monaco export 路径导致 0 test、jsdom 跨 Realm `TextEncoder` 使静态 Vite/esbuild import 导致 0 test、`import.meta.url` 被 Vitest 转换为非 `file:` URL 导致 23 pass / 1 fail，以及真实浏览器发现空 gutter 不可点击。前三类分别通过正确公开导出和独立 Node 子进程修正，最后一类通过可点击 `lineNumbers()` 修正；没有用跳过、mock pass 或降低断言掩盖失败。

## 6. 环境

```text
硬件：Apple M4，17179869184 bytes（16 GiB）
系统：macOS 26.5.2 (Build 25F84)，Darwin arm64
Node：24.19.0（Codex bundled runtime）
pnpm：11.19.0（Codex bundled runtime）
QwenPaw 目标：2.1.0 PawApp，真实浏览器未启动
原型依赖：package/lock 已冻结；主代理 frozen install exit 0（123/123 包）
安装说明：pnpm policy 忽略 esbuild/protobufjs install scripts；本机 Vite/Vitest 实跑成功
```

## 7. 命令、原始退出码与结果

| 验证 | 原始退出码 | 通过 | 失败 | 未执行 | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| `git status --short`、README/索引/专项与现有编辑器只读审查 | 0 | 1 | 0 | 0 | 基线与只读边界已记录 |
| TypeScript compiler API `createSourceFile` 解析三份 TS 文件 | 0 | 3 files / 0 syntax diagnostics | 0 | 0 | 早期语法预检 |
| 首次语义 `tsc`（默认 `--types node`） | 2 | 0 | 1 environment | 0 | `@types/node` 是非根链接；改用已安装包的精确只读 `typeRoots`，未改 package/lock |
| 第二次语义 `tsc`（精确 `typeRoots`） | 2 | 0 | 5 diagnostics | 0 | 发现 closure 内 `lookup.range` 可能为 undefined；修正显式局部窄化 |
| 最终严格 `tsc --noEmit --strict ...` | 0 | 3 files | 0 | 0 | 语义检查通过 |
| `.venv/bin/python -m json.tool .../T0-F/matrix.json` | 0 | 1 | 0 | 0 | JSON 有效 |
| 根 `pnpm build` | 0 | 48 modules / 1 runtime JS chunk | 0 | 0 | 当前共享 dirty 产品构建为 `index.js` 1984.66 kB、gzip 712.48 kB；**没有接入本原型** |
| 首次 Vitest：错误 Monaco export 路径 | 1 | 0 | 1 suite / 0 tests | 0 | 修正为 0.56 package exports 暴露的路径 |
| 第二次 Vitest：jsdom/esbuild 跨 Realm | 1 | 0 | 1 suite / 0 tests | 0 | bundle 构建迁入独立 Node 子进程 |
| 第三次 Vitest：非 `file:` 的 `import.meta.url` | 1 | 23 | 1 | 0 | 改用 Vitest cwd 下的确定性 entry |
| 最终 `pnpm --dir prototypes/moss-tts-nano exec vitest run --config editor/vitest.config.ts` | 0 | 25 | 0 | 0 | 1 test file；25/25；2.89s |
| CodeMirror/Monaco 公共 API 实际运行 | 0 | 2 candidate probes | 0 | 0 | jsdom 窄 API 通过；不含真实 IME/worker/CSP |
| 独立 Node 中的 Vite 单 ESM 构建/执行 | 0 | 1 | 0 | 0 | 原 Owner 的 editor-only bundle 为 602394 bytes；主代理组合浏览器 bundle 为 367410 bytes、gzip 103090 bytes，均为 import-free 单 ESM |
| 真实 Chromium：中文文本写入、undo/redo、自动保存、gutter、synthetic composition、UTF-16、Blob module | 0 | 7 | 0 | 0 | 自动保存事件 3；第二行 gutter offset 8；Blob module pass；干净 tab 控制台 0 error/warning |
| 真实 Chromium：1920×1080、2560×1440、1024×768、390×844 | 0 | 4 | 0 | 0 | 四张截图实际像素已用 `sips` 核验；390px 宽回流无横向遮挡 |
| 固定 QwenPaw 宿主、系统级中文 IME、长章滚动、200% 与可访问性 | 未执行 | 0 | 0 | 1 类 | 仍为 T0-F 宿主门禁，不用 synthetic composition 冒充系统输入法 |
| 最终 T0-A frozen install | 0（由主代理交接，非本 Owner 命令） | 123 packages | 0 | 0 | 损坏缓存已移走；忽略两个 install scripts 的限制见环境说明 |

根 build 会按既有配置再生成被 Git 忽略的 `frontend/dist`；`git status --short -- frontend/dist` 无输出，没有形成待交付跟踪文件。专项 bundle 使用 `write:false`，没有落盘产物；本工作包没有创建截图或浏览器 profile，也未修改 package、lock 或主代理所有的 `node_modules`。

## 8. 当前结论、未验证与风险

当前可以得出：

- CodeMirror 6 是**通过隔离原型自动化与真实 Chromium 子集的条件性首选候选**；其 transaction/decoration/可点击 gutter/history、UTF-16、undo/redo、自动保存 hook、Blob module 和响应式原型均有可运行证据，但固定 QwenPaw 宿主门禁前仍不能写成正式接入完成；
- Monaco 的无 worker 公共 model API 探针通过，仍只保留风险对照；worker/CSP/完整 bundle/体积/内存/IME 全部待真实证据；
- 原生 textarea 是明确的安全降级，不承担可编辑正文内 decoration、gutter 或透明叠层映射；
- T0-F 可条件进入真实浏览器门禁；正式编辑器冻结仍保持 `HOLD`，详细三态见 `matrix.json`。

未验证：真实系统中文输入法、现有工作台自动保存接线、固定 QwenPaw 2.1.0 Blob/CSP、Monaco worker、屏幕阅读器、实际手动滚动、真实长章 DOM/虚拟化、200% 缩放和启动内存。synthetic `CompositionEvent` 只证明保护分支，不替代系统输入法；隔离 Vite 页面中的 Blob URL 也不替代 QwenPaw 宿主策略。

主要风险：若把 jsdom 与 data URL 结果解释成真实 QwenPaw/中文 IME 已通过，仍会提前冻结错误依赖；若允许 textarea 叠层或普通点击跳播，会破坏 selection、IME、undo 和作者编辑习惯；若 undo 或页面重载后凭相似文本猜测旧映射，会把旧 Edition 时间轴错误贴到新正文。

## 9. 回退与主代理接线

本工作包没有业务运行态、数据库、模型、媒体、QwenPaw 或用户正文副作用。拒绝候选时只移除第 3 节列出的 5 个新增文件；根 `frontend/dist` 可由既有 `pnpm build` 重建，不需要数据恢复。不得删除 T0-A 所有的 package、lock、node_modules 或其他工作包文件。

主代理接线顺序：

1. 主代理已接收严格 typecheck、25/25 Vitest、单 ESM 与隔离 Chromium 结果；
2. 在固定 QwenPaw 2.1.0 中继续运行 CodeMirror 和 textarea 降级；Monaco 只在 CodeMirror 宿主门禁失败时投入额外 worker 风险验证；
3. 补齐系统中文 IME、现有 recovery/600 ms debounce/100 ms 追保存/CAS 409/AI apply 自动保存链、普通点击、手动滚动、长章节、页面重载、宿主 Blob/CSP、200% 和可访问性；详见 [固定宿主接线只读审计](./fixed-host-wiring-audit.md)；
4. 把 `matrix.json` 的 `pending_real_browser` 更新为实际 `pass/fail`，失败也必须保留原始证据；
5. T0-GATE 再决定 ADR-0006 的正式编辑器，T4-DEP 只接入最终选中的一个依赖；若真实浏览器不合格，回退 textarea 安全模式，不以视觉叠层补洞。

本交付仅供主代理继续验证和 ADR 输入，不能开放 T4-DEP，更不能宣称朗读编辑器已实施。

## 10. 主代理真实浏览器复验（2026-08-26）

复验浏览器为 Codex 内置 Chromium `151.0.0.0`、`devicePixelRatio=2`。固定测试文本仅来自项目 fixture；真实 WAV 只从仓库外阶段 0 媒体目录读取。复验先打开一个发生过构建错误的旧 tab，随后另开干净 tab 重新加载最终 bundle；干净 tab 在全部编辑器和 Manifest 交互后 `error/warning` 日志均为 0。

真实结果：

- 中文两行正文写入成功，随后 undo/redo 成功，`onDocumentChange` 记录 3 次事件；
- 第二行行号 gutter 可点击并返回 UTF-16 offset `8`；首轮空 gutter 不可点击的问题已修复并加入 DOM 回归断言；
- 当前句段 decoration、emoji 与组合字符均按 UTF-16 计数；
- synthetic composition 期间拒绝跟随，结束后恢复；该结果明确不等同于系统输入法；
- Blob URL 动态 ES module 返回预期导出，隔离浏览器 CSP 未阻断；
- 四个目标视口截图像素与文件名一致，桌面双栏和 390px 单栏均可用；200% 尚未执行。

因此 T0-F 的原型缺陷已经收敛，但最终裁决仍是 `HOLD at host gate`，不是失败，也不是已实施。

主代理另在 Microsoft Edge `151.0.0.0` 中用真实系统键盘事件复验：逐键英文输入、CodeMirror history 和撤销清理均正常，原始正文已恢复并关闭测试 tab。当前自动化能力不能触发 macOS 的全局输入源切换，因而没有出现系统中文候选窗；此尝试记录为 `blocked_by_automation`，不能计作系统 IME 通过，也没有改变用户输入源设置。

## 11. 固定宿主接线审计补充（2026-08-26）

主代理对子代理只读审计结论完成复核。现阶段可以冻结 CodeMirror/Manifest/Range 的候选契约，但不能据此写成正式产品接线：根依赖没有 CodeMirror，正文仍是 controlled textarea，正式保存链尚未由原型驱动，正式仓库也没有媒体 Range/ETag endpoint。T0-GATE 应采用“条件放行、能力默认关闭”；完整边界、T4 P0 和回退见 [fixed-host-wiring-audit.md](./fixed-host-wiring-audit.md)。
