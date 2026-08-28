# T2-B 书本“朗读”页局部前端实现记录

结论：**`PASS_LOCAL_PENDING_T2_GATE`。** T2-B 已在独占文件中完成书本“朗读”页壳、七项语义导航、总览、作品旁白、播放偏好以及分卷/章节范围覆盖 UI，并通过目标自动化与 TypeScript 全量类型检查。当前仍未接入共享工作台、全局样式或真实后端 factory；所有产品 capability 继续保持 T2-A 冻结的非 actionable 状态，不能把本记录表述为朗读产品已上线。

工作包：`T2-B`（`PAR-C`）。Owner：子代理 `/root/t2b_reading_ui`；唯一集成责任人仍为主代理 `/root`。

执行日期：2026-08-26（Asia/Shanghai）；开工约 16:43 CST，局部收口 17:05 CST。

## 1. 基线、范围与冻结输入

| 项目 | 实际值 |
| --- | --- |
| Git 基线 | `2caab228af15d5e4a5e858264799a67aede62f3d`（`main`） |
| 前置门禁 | `T2-A = ACCEPT_UNCHANGED` |
| 工作树 | 开工前已有 T0/T1/T2 其他工作包和用户改动；本工作包未覆盖、暂存、提交、推送或清理任何既有文件 |
| 运行态 | 未访问数据库、Docker、模型、媒体、私人录音、真实小说或正式 QwenPaw |

只读冻结输入在收口时重新计算，均与 T2-A 完全一致：

| 文件 | SHA-256 |
| --- | --- |
| `backend/narration/schemas.py` | `1e189e812cf674b0d9457328d4e74e95fda57a67b62a83f99eb31d299633fdbd` |
| `backend/narration/settings_api.py` | `05b1a6be9ab58d30ccb12d143033a96aa8feb9fec7a6ed7ad1a6560894505378` |
| `frontend/src/narration/contracts.ts` | `9a62723164027da7607ee4df0dc39bd61e9c21e89519d6cfb13352dfb66fc5ec` |
| `frontend/src/narration/api.ts` | `2c675603fe7e19b0d2dcf362015a432a2fe1cf36920b4096bf52c8a479b9dce8` |

没有修改 `frontend/src/narration/index.ts`、`styles.ts`、`frontend/src/index.ts`、`creative-center.ts`、任何 workbench 文件或 `backend/app.py`。

## 2. 实际产物与哈希

| 文件 | 作用 | SHA-256 |
| --- | --- | --- |
| `frontend/src/narration/reading-page.ts` | 页面 controller、导航、旁白表单、范围覆盖、API/CAS 和跨作品 fence | `dfe6142fb3c2d50ecb3e936d4a0f422763beabb17568b7dbce61da834af9dd11` |
| `frontend/src/narration/reading-overview.ts` | 总览纯模型、能力/原因投影以及 loading/empty/success/error/gated 视图 | `ebaf81e21d8335803af4e1723511ede7274465b70e1535eac137e592375748a5` |
| `frontend/src/narration/reading-page.test.ts` | 路由、导航、CAS、跨作品、旁白和范围覆盖测试 | `0dbd9e615f46ddcafe059d5bd62341207e34ba6e94ba88ddca774a6436d54e82` |
| `frontend/src/narration/reading-overview.test.ts` | 总览状态、no-go 隐藏、门禁和快捷入口测试 | `a95457d3b1cbd3354fd8d3160ac63ed98b718ab83f7b3c7e4eee473424463ff6` |
| `frontend/src/narration/styles/t2-b.ts` | 舒适/紧凑/窄屏可组合的局部样式片段 | `5909b602dbe911bc143d815f04a37ce5a81749d3d6592969337482385d29f9f5` |

本 README 不记录自身 hash，避免自引用循环。

## 3. 已实现行为

### 3.1 页面与导航

- 页面根节点固定为 `data-narration-reading-page="v1"`，同时暴露 `data-novel-id` 与 `data-active-section`，供 T2-GATE 挂载和浏览器验收定位；
- 七项导航固定为“总览、旁白、人物配音、通用音色、选角规则、发音与停顿、音频与缓存”，使用 `<nav aria-label="朗读设置">` 与单一 `aria-current="page"`；
- `READING_WORKBENCH_SECTION = "reading"`，子页查询键为 `reading_panel`；`readingSectionFromSearch` 只接受冻结的七个值，未知值回到 `overview`；
- `readingSectionSearch` 只设置 `section=reading` 和有界 `reading_panel`，保留现有 `novel_id` 等宿主查询参数；
- T2-C…T2-G 的局部模块只通过 `sectionContent` 注入，不在 T2-B 复制其 UI 或领域逻辑；未注入时只显示明确集成占位说明，不生成试听、合成、自动识别、音色包导入等伪按钮。

### 3.2 总览状态

| 状态 | 实际表现 |
| --- | --- |
| loading | `role=status`、`aria-busy=true`，不显示旧作品数据 |
| error | 安全错误说明与真实“重新加载”操作；不回显任意原始异常 |
| empty | 仅在无持久设置、无旁白、无人物/通用音色、无已生成章节时显示初始化引导 |
| success | 展示 Runtime、隐私模式、复核策略、旁白、人物/24 槽覆盖、任务、缓存和磁盘投影 |
| gated | 显示服务端稳定 `reason_code` 与友好说明，所有配置快捷操作禁用 |

VoiceGenerator capability 为 `visible=false` 时完全不渲染；通用音色只显示真实 `0/24` 等覆盖和 capability 原因。总览没有新增“测试朗读、批量生成、扫描配置、清理缓存”等尚无 T2-B API 的操作。

### 3.3 作品旁白

- 仅接受 T2-GATE 从 T2-D 已锁定、权利有效的 profile/version 映射成 `ReadingNarratorOption`；T2-B 自身不制造预设、上传或文字生成音色；
- 作品专属音色选项必须与当前 novel 相同，公共音色使用 `novelId=null`；跨作品选项在渲染前丢弃；
- 可设置语言、是否朗读章节标题/作者的话/分隔内容、第一人称人物、内心独白、三类停顿、播放倍速和播放器音量；固定输出格式只读显示为 M4A/AAC-LC；
- 语言在提交前按冻结的短 BCP 47 约束校验；第一人称人物只接受当前作品的有界选项；
- 每次保存都调用 `buildNarrationSettingsReplacement(resource, values)`，提交完整 `NarrationSettingsValues` 和当前 `expected_version`，不会局部 PATCH 或静默丢失 T2-G 管理的复核/隐私/选角字段；
- 旧设置中的旁白或第一人称人物若不在当前可核验选项中，只作为禁用历史值显示，不冒充为“已锁定/授权有效”；用户必须重新选择或清空后才能保存；
- 无变化的作品设置不发起 PUT，避免空写入增加 CAS 冲突；切换作品或卸载页面会 abort 在途中写请求并阻止迟到响应投影；
- 页面产品 gate、reading settings gate 或 `authorization.can_configure` 任一不满足时，不发起 PUT。

### 3.4 分卷与章节范围覆盖

- `scopeTargets` 只能由当前作品树传入；跨作品目标和重复 `(scope_kind, scope_id)` 在形成控件/URL 前被移除；
- GET 列表中的当前资源提供唯一 CAS version；新范围使用 version 0；
- 启用覆盖时至少选择旁白、语言、正文朗读规则或停顿之一；旁白/语言可独立覆盖，正文规则和停顿从作品当前值显式复制后作为完整值提交；
- 复制后可继续编辑三项正文开关、第一人称人物、内心独白和三类停顿，不把“覆盖正文规则”做成只能冻结当前值的无效开关；
- 关闭覆盖固定提交 `enabled=false` 和四项全 `null`，不会残留只存在于 UI 的覆盖；
- `buildScopeOverrideReplacement` 同时校验 novel、scope kind/id 与当前版本资源；返回资源若漂移到其他 novel/scope，`replaceScopeOverride` fail-closed；
- 作品 prop 切换后，在新请求完成前不显示旧作品 ready 数据；加载请求可取消，保存完成回调使用 current-novel ref fence，迟到响应不能写入新作品页面。
- 切换分卷/章节时先进入局部 fence，新范围的服务端基线完成装载前禁止把上一范围的草稿提交到新 URL；无变化和新建 disabled 空覆盖不发起 PUT。

## 4. Capability 与授权事实

T2-B 不改变任何服务端 capability。按 T2-A 当前基线：

- `narration_product`、`reading_settings` 均为 `hold / visible / non-actionable / T2_GATE_REQUIRED`；
- `voice_generator` 为 `unavailable / hidden / non-actionable / VOICE_GENERATOR_NO_GO`；
- reference clone、24 槽音色池、自动选角、说话人识别、合成、播放器和编辑器跟随没有被本页面宣称为可用；
- 导航按钮只切换本地设置栏目，不是产品能力动作；所有会写服务器的按钮都同时检查产品 gate、功能 gate 和授权；
- 浏览器只消费 T2-A 的 narration API client，不直接访问 Sidecar、模型目录、媒体文件系统或数据库。

## 5. 自动化结果

最终命令使用 Codex bundled Node 与项目固定 pnpm 11.19.0：

| 命令 | 结果 |
| --- | --- |
| `pnpm exec vitest run frontend/src/narration/reading-page.test.ts frontend/src/narration/reading-overview.test.ts` | 2 files，`20 passed`，0 failed |
| `pnpm exec vitest run frontend/src/narration/contracts.test.ts frontend/src/narration/api.test.ts frontend/src/narration/reading-page.test.ts frontend/src/narration/reading-overview.test.ts` | 4 files，`42 passed`，0 failed |
| `pnpm typecheck` | `tsc --noEmit` exit 0 |
| 五个源码/测试/样式文件尾随空白检查 | `whitespace-ok` |
| 冻结输入 SHA-256 复核 | 4/4 与 T2-A 一致 |

测试覆盖：稳定路由、七项导航/`aria-current`、loading/error/empty/gated、隐藏 no-go、真实 capability 才允许导航动作、完整 settings replacement、scope CAS、关闭即全空 replacement、跨作品 target/response、并行加载、外部 section 注入、旁白受控选项和授权锁定，以及运行时伪授权选项拒绝、旧旁白重新核验、无变化写入阻止、scope 切换 fence 和完整正文规则编辑。

## 6. T2-GATE 接线契约

### 6.1 导出

`reading-page.ts` 的主要导出：

- `createReadingPage(React, api?)`：唯一页面组件工厂；生产环境省略 `api` 即消费冻结 narration API；
- `ReadingPageProps`：必须传 `novelId`；可传 `novelTitle`、`initialSection`、当前作品 `scopeTargets`、已批准 `narratorOptions`、`characterOptions`、其他工作包 `sectionContent` 和 `onSectionChange`；
- `createNarratorSettingsPanel`、`createScopeOverridesPanel`：仅供局部测试或 T2-GATE 精确组合，不建设第二路由；
- `readingSectionFromSearch`、`readingSectionSearch`、`READING_WORKBENCH_SECTION`、`READING_PANEL_QUERY_KEY`：共享工作台导航适配器；
- `buildNarrationSettingsReplacement`、`buildScopeOverrideReplacement`、`replaceScopeOverride`：CAS/完整替换边界；
- `scopeTargetsForNovel`、`narratorOptionsForNovel`、`characterOptionsForNovel`：客户端的附加 fail-closed 投影；服务端仍须再次校验。

`reading-overview.ts` 的主要导出：`createReadingOverview`、`buildReadingOverviewModel`、`READING_SECTIONS`、`ReadingSectionKey`、`capabilityFor` 和 `capabilityStatusText`。

局部样式只导出 `T2_B_READING_STYLES`。T2-GATE 是唯一可以把它按工作包顺序并入 `frontend/src/narration/styles.ts` 的 Owner。

### 6.2 汇合顺序

1. T2-GATE 从 QwenPaw 公共 host 取得 React，调用 `createReadingPage(window.QwenPaw.host.React)`，不要复制页面实现；
2. 在新版/兼容工作台共享 section 类型、导航和路由恢复中一次性加入 `reading`，并用 `reading_panel` 恢复子栏目；
3. 从当前 novel tree 映射 volume/chapter 为 `scopeTargets`，每项显式携带同一 `novelId`；
4. 只把 T2-D 后端返回且已锁定、rights active、当前作品或公共库范围合法的版本映射成 `ReadingNarratorOption`；不要把 T0-E 技术评估音色或 24 个虚构槽位传入；
5. 把 T2-C、T2-E、T2-G、T2-F 的组件元素依次注入 `characters`、`generic-voices`、`casting-rules`、`pronunciation`/`audio-cache`；
6. `onSectionChange` 负责以 `readingSectionSearch` 同步 URL，但不得卸载原生聊天或清除 `novel_id`；
7. 只有后端 factory、各局部模块、T2-H 自动化、真实浏览器和卸载非回归均通过后，T2-GATE 才能裁决是否翻转 `narration_product/reading_settings`；页面代码本身不会翻转 gate。

## 7. 未验证、风险与回退

未验证：共享工作台/创作中心入口、真实 ReactDOM 挂载、Ant Design 主题实测、舒适/紧凑/受限桌面宽度、移动窄屏、键盘顺序、200% 等效缩放、真实后端 factory、数据库 CAS、浏览器网络错误、Voice Profile 名称映射和 QwenPaw 安装/卸载。按工作卡要求，本工作包未制作或伪造截图；截图与真实浏览器证据归 T2-H/T2-GATE。

剩余风险：T2-GATE 若把未锁定/未授权版本映射成旁白选项，前端类型不能替代服务端权利校验；若共享路由绕过 `readingSectionSearch`，子栏目恢复可能漂移；多个设置面板并发保存会收到真实 `VERSION_CONFLICT`，当前 UI 会要求刷新而不会静默覆盖。

本工作包没有数据库、容器、模型、媒体或用户内容副作用。需要回退时，只移除第 2 节五个局部文件和本证据；不得删除数据卷、媒体、正文、其他 T2 工作包或用户改动。
