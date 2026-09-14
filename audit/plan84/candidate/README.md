# 计划84第七版全量候选冻结（历史）

冻结时间：2026-09-14 23:34 CST

状态：`FORMAL_GATE_FAILED`（P84-INT与P84-QA曾PASS；第七版正式Edge冷加载失败并已回退，不得部署或结项）

2026-09-15已另行形成不含F84-01的F84-02—F84-07拆分候选；当前可发布候选身份只见[../split-candidate/README.md](../split-candidate/README.md)，本文件哈希仅用于复核历史失败与回退。

这是经第四版正式桌面URL门禁退回、第五／第六版QA退回并完成第七轮 P84-REWORK 后的第七版候选；23:32及更早冻结的旧候选与哈希均已废止，不得用于部署或结项。

## 候选身份

- 生产源码集合哈希：`1c0c53d4df77e27b08308729d2e896fd58d2a7c0238041d670ece6cb4037ef90`
- 打包树确定性哈希（项目生命周期门禁 `_candidate_tree_sha256`）：`42226a0e8202aaf08e77cbc9f524efda164637724eca82b40757aeb009232dfa`
- 候选前端 bundle SHA-256：`0f1c730f3ddf130971e22cb2b479d67bf5ca5d213fc905dbbb47624ec795bc6c`
- 候选 `plugin.json` SHA-256：`79fae92a55706815babcd349bae892f70f680cd8d4f3abdcc363210bcec18605`
- PawApp manifest版本仍为0.4.0；本轮通过公开 `--force` 原位更新，不新增数据库迁移。

生产源码集合哈希按以下文件的有序 SHA-256 再哈希：

- `backend/private_library/lexicon_service.py`
- `frontend/src/creative-center-entry.ts`
- `frontend/src/creative-center.ts`
- `frontend/src/novel-surface-navigation.ts`
- `frontend/src/template-field-meta.ts`
- `frontend/src/private-library/contracts.ts`
- `frontend/src/private-library/model.ts`
- `frontend/src/private-library/private-library-workspace.ts`
- `frontend/src/workbench-route.ts`
- `frontend/src/workbench-studio.ts`
- `frontend/src/styles.ts`

## 已通过代码门禁

- 第七版候选路由／包装器／子视图定向：6个文件，67项通过；计划定向前端先前114项均已通过。
- 私有库显式临时 PostgreSQL `ai_novel_plan84_test`：迁移到 `20260913_0056` 后50项通过、0跳过；结束后精确删除该临时数据库。
- `pnpm typecheck`：通过。
- 全量前端：165个文件、1588项通过。
- `pnpm build`：通过。
- 全量Python：3209项通过、329项按既有外部环境条件跳过；首次未传 Node 路径时有1项环境失败，补入 `CHARACTER_VOICE_NODE` 后完整重跑通过。
- `.venv/bin/python scripts/package_plugin.py`：通过。
- `git diff --check`：通过。

首轮QA发现并退回了创作中心裸会话URL侵占、模板非文本值改写、左导航仍落在滚动区、模板key编码边界过宽和搜索竞态测试不足五项问题。第二版候选已分别改为一次性入口过渡权限、异常原值只读保留且阻止保存、固定导航／唯一返回入口、与后端一致的URI后缀／字段ID边界，并以可控 deferred promise 覆盖请求关闭、迟到成功／失败和重开代际。顶部搜索框的鼠标点击只打开弹窗，以便在发请前使用Escape；回车仍保持打开并立即搜索。

第二轮QA又发现直接打开根规范URL时宿主首次分配会话仍会丢失界面，以及在搜索请求进行中清空关键词时未废止旧请求。第三版候选使根规范URL和官方入口共用一次性会话分配权限，参数回写后即清除；清空搜索会立即推进代际、清结果与忙碌态，作品切换或组件卸载时也会无回调废止旧请求。

第三轮QA发现同一标签已有旧创作中心会话时，重新打开根规范URL会遗留旧 `chatPath`并阻断宿主分配新会话；同时确认第三版证据误将“逐文件shasum文本再哈希”标成了正式打包树哈希。第四版候选在根规范URL上明确丢弃旧 `chatPath`，并以项目现有生命周期门禁 `_candidate_tree_sha256`的结果作为唯一正式打包树哈希。

第四版候选已通过代码QA并经公开CLI热更新，但正式冷加载观测到根规范查询最终被归一为裸会话URL，插件首次未能观测查询参数。结合QwenPaw 2.2.1公开的动态插件加载生命周期与无路由重放API，工程上推断宿主首轮路由早于插件注册；该时序没有本仓库内的原始浏览器日志直接证明。已按中止条件用公开CLI恢复上一已安装包，健康、数据与Agent配置未漂移。

第五版尝试把同源显式项目 `PerformanceNavigationTiming.name` 作为首次恢复证据；QA证明根导航记录无法区分“宿主刚分配的裸会话”和“稍后SPA进入的普通裸会话”，并发现子视图可能在宿主去参后丢失，因此未部署。第六版把未知新会话的唯一授权入口收紧为插件自有 `/apps/ai-novel-world-2026`：入口先写一次性pending权限；Performance只在已分配的`/chat/{sessionId}`路径与当前裸路径精确相同时恢复完整查询，根记录不得猜任意会话。官方私有库入口用一次性tab状态传递`view`，同会话刷新则在状态机创建前用replace语义恢复包括`view`在内的完整规范查询。当前任何显式普通query、根chat、另一作品或不同session路径始终优先，普通聊天不被旧导航记录侵占。

第六版QA继续发现入口`view`曾在React render阶段读取即删除，StrictMode或并发重试可能让未提交首帧耗尽一次性状态。第七版把读取改为纯读，只在`NovelLibraryPage`提交后的effect中清理；测试覆盖重复render式读取仍稳定、提交清理后才消失。

集成阶段另修复了一处测试自身的真实 PostgreSQL 排序不稳定：把资产根CAS改为14会触发模型的 `updated_at` 自动更新，因此分页反例显式重置目标时间到第二页。该修复只影响测试确定性，不改变生产排序合同。

候选冻结后，两路P84-QA独立复算四项身份，并分别重跑13个相关文件134项、全前端165个文件1588项及TypeScript检查；URL循环与普通聊天隔离、CAS语义、500字符边界、内容泄漏、Escape竞态、React并发首帧、左栏滚动和QwenPaw上游隔离均未发现P0—P3，代码QA结论为PASS。

23:39第七版按公开CLI原位热更新，已安装生产树与冻结树哈希一致；正式Edge从`/apps/ai-novel-world-2026`冷加载后仍落到无`novel_center=1`的`/chat/b9c0bbb4-ff55-4ad5-bbae-a092028b1302`并显示原生聊天。浏览器控制过程当时观测到插件注册晚于最终裸会话页面，但原始日志和截图没有归档；结合公开合同只能将具体时序记为工程推断。该现象足以判定第七版未通过正式URL门禁；已立即用既有恢复点回装上一包，未继续其他UI验收。第七版不得再次部署。
