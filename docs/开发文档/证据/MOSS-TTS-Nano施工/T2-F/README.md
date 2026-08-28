# T2-F 发音、停顿与缓存设置施工证据

> 状态：**T2-F 局部施工候选已完成，尚未接入 T2-GATE，尚未做真实浏览器/数据库/媒体盘验收**
>
> 日期：2026-08-26
>
> 工作包：T2-F（PAR-C，本包唯一写 Owner）

## 1. 结论边界

T2-F 现在提供了可供 T2-GATE 调用的窄后端 handler、作品级发音配置面板和二阶段缓存面板。这些局部模块尚未进入共享 dispatcher、导航、样式汇总或真实运行态，因此不表示用户现在已能在产品页面中使用它们。

- 发音 PUT 是真实的全量 CAS replacement：锁作品，重验 novel/volume/chapter scope、NFKC 归一化后重复、优先级、replace/skip 形状和语言标签；每次变化创建新 `PronunciationProfile` 与完整 entries，不更新或删除历史行。
- T1 schema 没有 pronunciation action 列且 `spoken_text` 不可为空；本模块使用服务端专有的精确空字符串表示 `skip`，wire 上仍严格返回 `action=skip, spoken_text=null`。
- 停顿值不在 pronunciation DTO 中；它们的权威来源是已冻结的 `NarrationSettingsValues.timing`。面板只显示宿主传入的句/段/分隔停顿真实值，并可通过 `onOpenReadingSettings` 返回基础朗读设置；没有伪造第二份停顿 PUT。
- 缓存状态按 source / locked voice / referenced Edition / unreferenced derivative 互斥分类。只有 T1-E GC 已判定为 `delete`/`resume_delete` 的派生且无结构化引用资产才进入候选；新鲜的 `mark` 资产不计入可回收字节。
- 缓存快照指纹同时绑定资产行、结构化引用类别和当前 GC 决策。资产跨过宽限期边界时指纹必然变化，不能出现“执行比预览多删候选”。
- cleanup 必须是 status snapshot → preview → 勾选显式确认 → execute。token 使用 HMAC-SHA256 签名并绑定 novel、snapshot 和过期时间。物理 unlink 发生在两个短事务之间；最终 tombstone 确认失败时整体报错，不伪装成成功或安全跳过。
- execute 结果中 source、locked voice、referenced asset 删除数依冻结 wire contract 为字面量 `0`；前端再次拒绝任何违反该契约或超出预览数量/字节的“成功”响应。

## 2. 冻结输入复核

| 只读输入 | 要求 SHA-256 | 实际 SHA-256 | 结果 |
| --- | --- | --- | --- |
| `backend/narration/schemas.py` | `1e189e812cf674b0d9457328d4e74e95fda57a67b62a83f99eb31d299633fdbd` | `1e189e812cf674b0d9457328d4e74e95fda57a67b62a83f99eb31d299633fdbd` | PASS |
| `backend/narration/settings_api.py` | `05b1a6be9ab58d30ccb12d143033a96aa8feb9fec7a6ed7ad1a6560894505378` | `05b1a6be9ab58d30ccb12d143033a96aa8feb9fec7a6ed7ad1a6560894505378` | PASS |
| `frontend/src/narration/contracts.ts` | `9a62723164027da7607ee4df0dc39bd61e9c21e89519d6cfb13352dfb66fc5ec` | `9a62723164027da7607ee4df0dc39bd61e9c21e89519d6cfb13352dfb66fc5ec` | PASS |
| `frontend/src/narration/api.ts` | `2c675603fe7e19b0d2dcf362015a432a2fe1cf36920b4096bf52c8a479b9dce8` | `2c675603fe7e19b0d2dcf362015a432a2fe1cf36920b4096bf52c8a479b9dce8` | PASS |

本包未修改上述四个文件，也未修改 schema、Alembic、共享入口、`index.ts`、共享 `styles.ts`、workbench、Docker、依赖或正式数据库。

## 3. 实际文件

1. `backend/narration/pronunciations.py`
2. `tests/narration/test_pronunciations.py`
3. `frontend/src/narration/pronunciation-panel.ts`
4. `frontend/src/narration/pronunciation-panel.test.ts`
5. `frontend/src/narration/cache-panel.ts`
6. `frontend/src/narration/cache-panel.test.ts`
7. `frontend/src/narration/styles/t2-f.ts`
8. `docs/开发文档/证据/MOSS-TTS-Nano施工/T2-F/README.md`

## 4. 状态矩阵

### 4.1 发音/停顿面板

| 状态 | 显示 | 可执行动作 | 安全结果 |
| --- | --- | --- | --- |
| 无 `can_read` | 阻断文案 | 无 GET/PUT | 旧作品数据不渲染 |
| loading / 作品切换 | 加载态 | 无修改 | AbortController 取消旧请求，novel scope fence 拒绝旧响应 |
| 空 profile | version 0、空表 | 可新增第一条 | 不伪造默认发音行 |
| 成功/未修改 | 当前版本、发音表、基础停顿真实值 | 新增/编辑/移除本地草稿 | PUT 按钮禁用 |
| 本地校验失败 | 字段错误/alert | 可继续修改 | 不发 PUT |
| authorization 只读 / capability HOLD | 真实配置和 reason code | 无修改 | GET 可用，PUT 不可用 |
| saving | `aria-busy`、保存中 | 取消旧 save 后单请求 | 携带当前 `expected_version` |
| CAS conflict | 聚焦 alert、服务端版本 | “读取最新版本并保留草稿” | 用户草稿不丢失，新基线后才能重试 |
| save error | alert、草稿保留 | 修改/重试 | 旧 profile/entry 不改写 |
| save success | 新 profile 版本 | 继续编辑 | 明示“不改正文/历史 Edition” |

### 4.2 缓存面板

| 状态 | 显示 | 清理动作 | 安全结果 |
| --- | --- | --- | --- |
| loading / load error | 加载或 alert | 无 | 可取消、可重试，不保留旧 novel 快照 |
| authorization 只读 / 全局或嵌套 capability HOLD | 分类状态和 reason code | 禁用 | 前后端均 fail-closed |
| reclaimable = 0 | 精确 0 B | 禁用预览 | 不伪造可回收量 |
| disk free = 0 | alert 显示空间不足 | 仍受全部门禁 | 只对“精确 0”作确定性判断，不自创磁盘阈值 |
| status ready | 七项精确字节/计数 | 只可请求 preview | 没有一键危险执行 |
| previewing | `aria-busy` | 无 execute | 快照变化则拒绝 |
| preview ready / 未勾选 | 候选数、保护数、精确字节、过期时间 | execute 禁用 | 明示尚未删除 |
| preview ready / 已勾选 | 显式确认文案 | execute 可用 | 传入 token + fingerprint + `confirmed:true` |
| token 过期 / snapshot 冲突 | alert | 必须刷新/重新预览 | 清空旧确认，不报告删除 |
| execute 竞态保护 | 候选跳过 | 不碰物理文件 | 新引用/新 generation 优先保护 |
| execute 最终确认失败 | storage error | 停止 | 不把已缺失 blob 伪报成成功/跳过 |
| execute success | 服务端实际 deleted/reclaimed | 必须刷新后才能再预览 | source/locked/referenced 删除数必须为 0 |

## 5. 验证记录

### 5.1 实际失败与修复

| 命令/阶段 | 原始结果 | 处理 |
| --- | --- | --- |
| `pnpm typecheck` | FAIL：当前 shell 找不到 `node` | 使用 Codex workspace 已提供的 Node 运行时加入临时 `PATH`；未安装依赖 |
| 首次带 Node 的 `pnpm typecheck` | FAIL：`unit` 被推断为字面量 `KiB` | 将其收窄为单位 tuple 的 union，随后 PASS |
| 首次 pronunciation Vitest | FAIL：在 `frontend/` cwd 使用了相对 root 错误的 filter，`No test files found` | 回到仓库根用完整 `frontend/src/...` filter；记为命令路径错误，不记为测试通过 |
| pronunciation Vitest 首跑 | 5 PASS / 2 FAIL：重复用例 scope 组合错误；测试把 input value 当作 text child | 修正 fixture 和断言，随后 7/7 PASS |
| cache Vitest 首跑 | 6 PASS / 1 FAIL：期望字符串少一个空格 | 修正断言，随后 7/7 PASS |
| 新增测试后 typecheck | FAIL：一个永不 resolve 的 mock 被推断为 `Promise<unknown>` | 显式标注 `Promise<PronunciationProfileResource>`，随后 PASS |
| backend 合并复跑 | 8 PASS / 1 FAIL：签名篡改用例将最后一位写成原本就是的 `0` | 改为必然切换 `0/1`；随后扩展至 13/13 PASS |
| 可选 `.venv/bin/python -m ruff check ...` | SKIP：项目 `.venv` 未安装 `ruff` | 遵守本包“禁止依赖安装”，未临时安装；该项不是必须门禁 |

### 5.2 最终命令与结果

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/narration/test_pronunciations.py -q` | PASS，13 passed |
| `pnpm exec vitest run frontend/src/narration/pronunciation-panel.test.ts frontend/src/narration/cache-panel.test.ts` | PASS，2 files / 14 tests |
| `pnpm typecheck` | PASS（使用 workspace Node 的临时 `PATH`） |
| `.venv/bin/python -m py_compile backend/narration/pronunciations.py` | PASS |
| `git diff --check` + 本包八文件尾随空白检查 | 最终复核见主代理汇合结果；本 README 写入后重跑 |
| 冻结四文件 SHA-256 | PASS，见第 2 节；本 README 写入后重跑 |

本包没有 skip 的目标自动化测试。

## 6. T2-GATE 接线契约

### 6.1 后端

1. 请求级 composite dispatcher 用调用方已拥有的 `NarrationStore` 构造 `PronunciationSettingsHandler(store, cache_runtime=...)`，并且仅对 `PronunciationSettingsHandler.handles(operation)` 为真的五个 operation 委派。
2. 发音 GET/PUT 使用调用方事务；handler 只 `flush`，不 commit。T2-GATE 必须在异常时 rollback，成功时按现有 API 约定 commit。
3. 缓存状态/预览/执行必须注入 `SqlAlchemyNarrationCacheRuntime`，其输入为独立 `session_factory`、已验证 `NarrationStorage`、当前 `cache_cleanup` capability、至少 32 字节 token secret、tombstone digest key ID/key。secret 不得写入前端、日志或本证据目录。
4. cache runtime 自主使用短事务：事务 A 冻结 durable deletion plan，事务外 unlink，事务 B 验证并 tombstone。不得把物理操作改回路由调用方的长事务。
5. T2-GATE 必须在 dispatcher 之前确认固定 local owner/workspace 的 `can_read/can_configure` 授权；只有全局和 runtime 嵌套 `cache_cleanup` capability 都为 enabled/visible/actionable 时才可执行清理。本模块内也固定 novel owner/workspace scope，但这不取代 API authorization。
6. 未注入 runtime 时的默认是结构化 `STORAGE_UNAVAILABLE`；capability HOLD 时 preview/execute 是 `CAPABILITY_DISABLED`。不得为了接线方便把它们改为空成功。

### 6.2 前端

- 工厂契约：
  - `createPronunciationPanel(window.QwenPaw.host.React, api?) -> (props) => unknown`
  - `createCachePanel(window.QwenPaw.host.React, api?) -> (props) => unknown`
- React host 的普通 props 更新就是 update；React unmount 就是 destroy，会 abort 进行中请求并调用可选 `onReturnFocus`。本包不自建第二套 mount 或 DOM runtime。
- pronunciation props：`novelId`、`capabilities`、`authorization`、`scopeOptions`、`timing`；可选 `className/onOpenReadingSettings/onSaved/onReturnFocus`。`scopeOptions` 必须是当前作品不可变 volume/chapter ID；`timing` 必须来自基础朗读设置响应。
- cache props：`novelId`、`capabilities`、`authorization`；可选 `className/onCleaned/onReturnFocus`。
- T2-GATE 导出/组合局部样式 `T2_F_NARRATION_SETTINGS_PANEL_STYLES`；本包不修改冻结的共享 `narration/index.ts` 或 `narration/styles.ts`。
- pronunciation 面板的 pause 跳转由 T2-B/T2-GATE 实现；缓存面板成功后快照明示过期，宿主应保留“刷新状态”而不在本地减去预览字节。

## 7. 未验证、已知缺口与风险

1. **尚未验证真实 PostgreSQL**：本包按指令未连正式库、未跑迁移、未修改 schema。后端单测使用无 I/O store/fake session。T2-GATE/T2-H 必须在隔离测试库验证 novel lock、scope trigger、unique guards、rollback 和 GC durable plan/tombstone。
2. **尚未验证真实媒体盘**：未 unlink 任何文件。需用临时媒体根验证 inode/root identity、存储失败、中断恢复和实际回收字节；不得指向用户正式音频。
3. **尚未做真实浏览器/视觉验收**：没有伪造截图。舒适/紧凑/受限宽度、移动窄屏、真实焦点顺序和屏幕阅读器检查后移 T2-H/T2-GATE。
4. **精确历史回退缺口**：T1 schema 只有 `(novel_id, fingerprint)` unique，没有可切换的 current-profile pointer。当请求内容与非当前历史 profile 完全相同时，既不能重用旧行冒充当前版本，也不能重复 fingerprint；现在结构化 fail-closed，未扩 schema。
5. **停顿写入不属于 pronunciation API**：写入由已冻结基础 settings CAS 负责。若 T2-GATE 不提供 `onOpenReadingSettings`，本面板仍会真实显示停顿，但不显示伪修改入口。
6. **按章节的音频明细未冻结**：T2-A cache DTO 只有作品级汇总，没有章节正文版本/脚本/时长/失败句段/过期状态列表 DTO。本包没有伪造该页；需后续契约决策后另行实现。
7. **当前产品 capability 仍为 HOLD**：这是正确的非 actionable 状态。不得因本包单测通过就翻转 capability。

## 8. 回退

本包无 schema、迁移、依赖、共享入口或用户数据变更。在 T2-GATE 接线前，回退只需移除第 3 节列出的八个本包文件；不需要数据库回退。接线后回退时，先从 composite dispatcher/前端组合/样式汇总移除 T2-F 引用，再回退局部文件；不得删除媒体卷、发音历史行或 Edition。
