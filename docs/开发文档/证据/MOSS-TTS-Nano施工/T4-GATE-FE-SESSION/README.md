# T4-GATE-FE-SESSION 章节朗读生产会话证据

- 日期：2026-08-27
- 工作包：`T4-GATE-FE-SESSION`（PAR-C）
- 状态：前端纯自动化通过；未做真实浏览器、Nano、PostgreSQL 或网络运行
- UI 范围：本工作包不实现页面，也不声明浏览器验收；后续 TTS UI 发布验收只接受 `1920×1080 × 助手收起/展开` 与 `2560×1440 × 助手收起/展开` 四个精确组合

## 1. 交付文件

- `frontend/src/narration/chapter-narration-session.ts`
- `frontend/src/narration/chapter-narration-session.test.ts`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T4-GATE-FE-SESSION/README.md`

未修改 `narration-player.ts`、共享页面、样式、根入口、后端、数据库迁移或运行时。

## 2. 冻结接口

- `ChapterNarrationBundle`：保存 Context、Edition、ScriptVersion、Manifest、Bridge 句段、段落描述及 `segmentById`。
- `loadChapterNarrationBundle(...)`：按 Context → Active Edition → Edition ScriptVersion → Manifest 顺序加载；无 Edition 返回显式 `status: "no-edition"`。
- `ChapterNarrationSession` / `createChapterNarrationSession(...)`：提供 `load`、`refresh`、快照、player/coordinator/follow、seek、暂停/恢复、倍速、跟随暂停/恢复及释放。
- 生产默认依赖复用现有 `getDocumentNarrationContext`、`getNarrationEdition`、`getNarrationScriptVersionForEdition`、`getNarrationManifest`、`prepareNarrationRange` 和播放器/编辑桥契约。

## 3. 覆盖矩阵

| 门禁 | 自动化证据 |
| --- | --- |
| 无 Edition 显式结果 | 不伪造空 bundle，不创建播放器，不请求 Edition/Script/Manifest |
| 四层 scope | Context novel/document、Edition scope/ScriptVersion、Script revision/hash、Manifest Edition/chapter/revision/hash 任一漂移均 fail-closed |
| 句段完整性 | 数量、重复/缺失、顺序、ID、ordinal、source block、UTF-16 起止和 source text 长度严格一致；不完整或逆序 anchor 拒绝 |
| 当前稿绑定 | 仅 source hash 等于 working-copy hash 且编辑器正文逐段匹配时绑定 Bridge |
| 旧稿播放 | 旧 Edition 保留 immutable script/Manifest 播放能力，但不绑定、不高亮当前正文 |
| prepare → poll → play | 准备后使用 AbortSignal 与有界退避轮询；ready range 出现后才重放目标 |
| ETag 递进 | 轮询收到新 Manifest 后，后续 `If-None-Match` 使用最新 ETag；304 不允许 ETag 漂移 |
| latest seek | 新 seek 取消旧轮询；旧结果不覆盖 session 快照；仅最后有效句段进入播放队列 |
| 终态与超时 | failed/cancelled 立即阻塞；超时不再发出截止线后的 Manifest 请求；Abort 返回 superseded |
| 生命周期 | dispose 取消 load/poll、停止并释放播放器、销毁 coordinator/follow 订阅、解绑 Bridge，无残留计时器 |
| 编辑安全 | seek、highlight、follow、暂停、倍速和展示事件均不调用正文 `onDocChanged` |

## 4. 原始验证结果

```text
$ PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" pnpm exec vitest run frontend/src/narration/chapter-narration-session.test.ts
Test Files  1 passed (1)
Tests       20 passed (20)
失败 0，跳过 0
```

```text
$ PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" pnpm exec vitest run frontend/src/narration
Test Files  37 passed (37)
Tests       353 passed (353)
失败 0，跳过 0
```

```text
$ PATH="/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" pnpm typecheck
$ tsc --noEmit
退出码 0
```

## 5. 未做与剩余风险

- 未启动真实 MOSS-TTS-Nano、PostgreSQL、容器或浏览器。
- 未验证真实媒体下载、Web Audio/双 audio 后端、服务端渲染耗时和实际网络 ETag 时序；本工作包使用既有播放器与 API 契约的确定性测试替身。
- 未连接 React 面板、`workbench-v2.ts`、`narration/index.ts` 或样式；由唯一集成 Owner 在共享入口阶段接线。
- 真实浏览器验收需在入口接线后对上述四个组合逐一执行，不接受任意更大视口或模糊范围作为替代；低于 1920×1080、移动、窄屏和 200% 等效小视口不测试且不阻断发布。

## 6. 主代理接线说明

1. 在章节朗读面板获得稳定的 `novelId`、`documentId`、document generation 与现有 editor bridge 后创建一个 session。
2. 文档、generation 或 active Edition 改变时，先 dispose 旧 session，再创建/加载新 session；不要跨章节复用。
3. UI 只读取 session snapshot 和 `bundle.paragraphs`/`segmentById`；显式句段点击调用 `playSegment`，普通编辑器点击仍只移动光标。
4. 不要为旧稿强行绑定当前 Bridge；旧稿字幕/只读句段应读取 immutable script。
5. 入口接线后补真实浏览器与媒体后端验收，不把本证据升级为浏览器已通过。
