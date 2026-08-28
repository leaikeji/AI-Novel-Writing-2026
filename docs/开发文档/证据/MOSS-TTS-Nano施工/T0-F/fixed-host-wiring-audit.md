# T0-F/T0-G 固定宿主接线只读审计

状态：**审计完成；只支持“契约条件放行、产品能力默认关闭”的 T0 结论，不支持声称 CodeMirror、正式自动保存、播放器或 Range 已接入 QwenPaw 产品。**

审计日期：2026-08-26（Asia/Shanghai）。

审计方式：只读检查当前 PawApp 源代码、公开宿主类型、构建配置、T0-F/T0-G 原型与证据；未修改 QwenPaw 上游、未安装 disposable PawApp、未触碰用户正文或正式媒体。

## 1. 当前实现事实

- `frontend/src/index.ts` 当前只注册 PawApp 自有作品入口和 `core.chat` 包装；公开宿主契约提供 `route.add/wrap`、`host.fetch/getApiUrl/getApiToken` 和聊天扩展清理能力。后续 TTS 只能接在自有 `NovelWorkbench`/PawApp 命名空间内，不能覆盖上游页面或路由。
- `vite.config.ts` 固定单 ES module 和 `inlineDynamicImports=true`，因为宿主从 Blob URL 执行 PawApp。这是正式 bundle 的构建约束，但不证明阶段 0 的 CodeMirror 原型已经进入正式 bundle。
- 根 `package.json` 当前没有 CodeMirror；T0-F 的根 build 也明确没有接入该原型。T4-DEP 必须只引入 T0-GATE 选定的一套编辑器依赖，并重新验证干净安装、单 chunk、Blob 执行和 bundle 增量。
- 正式正文仍是 `frontend/src/workbench-v2.ts` 中的 controlled `textarea`。其保存链包含 IndexedDB recovery、600 ms debounce、保存中产生新内容后的 100 ms 追保存、CAS 409 保留本地稿和 AI apply 接线。T0-F 只验证隔离 change hook，未调用这条正式链，因此“现有自动保存非回归”仍未通过。
- 当前正式仓库没有媒体 Range/ETag/206/416 路由。`frontend/src/api.ts` 的 `apiRequest()` 强制按 JSON 读取响应，不能作为音频流入口；T0-G 的 Range/ETag 结果只是 loopback 协议原型。

## 2. 阶段 0 能与不能证明的范围

阶段 0 已证明的窄事实：

- CodeMirror 公共 transaction、decoration、gutter、history、UTF-16 映射和 import-free 单 ESM 原型可运行；
- textarea 可作为不伪造 decoration/gutter 的安全降级；
- Manifest revision、ready-window、pending/failed gap、快速跳播和公平老化算法；
- 单 Range、强 ETag、If-Range/If-None-Match 的隔离协议；
- Web Audio 与双 `<audio>` 的调度路径。

阶段 0 尚未证明：

- CodeMirror 与正式 `workbench-v2.ts` state/ref/recovery/CAS/AI apply 的集成；
- 完整产品 bundle 在固定 QwenPaw Blob/CSP 下运行；
- 正式 owner/workspace/novel/Edition/Manifest 鉴权、持久 CAS、反向代理和大文件流；
- 播放器同页布局、焦点、章节切换、刷新和卸载清理；
- 系统中文 IME、200% 缩放、键盘跳播、屏幕阅读器与两个独立真实相邻句段的人耳接缝。

## 3. T0-GATE 安全裁决输入

| 能力 | 建议裁决 | 当前启用状态 |
| --- | --- | --- |
| `editor_candidate=codemirror6` | `CONDITIONAL GO`，只允许进入 T4-DEP/T4-F | `production_enabled=false` |
| `existing_textarea_editor` | `GO` 仅表示既有正文编辑/保存是当前非回归基线，不表示朗读 fallback 已实现 | 保持现状 |
| `narration_textarea_fallback` | `CONDITIONAL_FOR_T4`；只读段落层、旧稿字幕/抽屉和显式跳播仍待实现/验收 | `production_enabled=false` |
| Monaco | `NO-GO/HIDDEN`；worker/CSP/体积无证据 | 不引入根依赖 |
| Manifest v2、revision collision、ready-window、pending/failed gap | 契约 `GO` | 仅供 T1/T4 实现消费 |
| Web Audio + 双 audio 调度器 | `CONDITIONAL GO` | `product_player_enabled=false` |
| Range/ETag 契约 | `GO_FOR_T1-E` | 正式媒体 endpoint `HOLD` |

这个裁决只允许 T1 后端底座在其他 T0 P0 全部收敛后继续，不能提前显示朗读产品入口或把 T4 写成已完成。

## 4. T4 启用前 P0

1. **T4-DEP**：只新增 CodeMirror 一套依赖；冻结明确的 raw/gzip 增量预算，验证 frozen install、单 chunk、无静态/动态外部 import、固定宿主 Blob/CSP、解析/启动/内存和 textarea 回退。
2. **T4-F**：编辑器只在 `update.docChanged` 时把纯 `nextValue` 送入唯一正式保存链；decoration、跟随、seek 绝不能写 recovery、触发保存或触发 TTS。覆盖 600 ms debounce、保存中 100 ms 追保存、CAS 409、断网/reload recovery、AI apply/undo、章节切换、selection、composition 和卸载。
3. 当前保存 timer/response 必须增加 document id 或 generation fencing，避免旧章节定时器或旧响应写入新章节；不能直接复制现状中的生命周期缺口。
4. **T4-D**：正式媒体 API 重新验证 owner/workspace/novel/Edition/Manifest 可达性；实现 GET/HEAD、单 Range、If-Range/If-None-Match、206/416、持久 CAS、AbortSignal 与流式读取。
5. 前端新增专用 `mediaFetch`，通过 `window.QwenPaw.host.fetch` 发送 Range/If-Range/AbortSignal 并读取 Blob/ArrayBuffer；不得复用强制 JSON 的 `apiRequest()`，不得把 API token 放进 URL。若采用 `<audio src>`，必须先冻结受控短期 URL 或同源认证契约。
6. **T4-E/G/H/K/GATE**：完成固定宿主完整 bundle、系统中文 IME、普通正文点击仅移动光标、键盘和焦点、ARIA/live region、手动滚动暂停/恢复、长章、200%、两个独立相邻句段听检、正式 Range、章节切换/刷新/卸载和原生聊天非回归。
7. 插件/路由卸载必须显式关闭 AudioContext、撤销 object URL、取消 Range 请求、清理 timer 和全局监听；`chat.disposeAll(APP_ID)` 只能清聊天扩展，不能代替播放器生命周期清理。

## 5. 结论

系统中文 IME、正式自动保存、固定宿主 Blob/CSP、键盘焦点、200% 和正式媒体鉴权都是“默认启用产品能力”前的 P0；它们不是“以 capability 默认关闭并继续 T1 后端底座”的 T0 阻断。若 T0-GATE 试图直接显示 CodeMirror 或播放器，则这些项目立即升级为 T0 阻断，当前证据不足，必须 `HOLD`。
