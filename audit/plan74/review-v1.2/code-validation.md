# V1.2代码验证记录

日期：2026-09-13。状态：`77870d4 G2-B PASS / F08-F09正式复验待续`。新源前端1521／类型／构建／包检查、Python全量和314项临时数据库代码检查退出0；下方旧代码检查及HOLD保留历史。正式分项不等于G3整体通过。

## F08／F09精确提交树复验

`77870d41ebb24f666f5507a3527d6b6c34e5bfaf`独立检出`/private/tmp/plan74-final-source.jn7Nb1/code`，未包含计划79工作区候选，检查后status为空；没有建立第二套QwenPaw环境。

- 原锁文件离线复用64包、0下载；168文件1521项通过，typecheck、202模块build退出0。[前端日志](locate-intent-source-frontend.log)。工作区1522与这里1521的差异来自未纳入的朗读任务用例。
- 同一源树用项目解释器运行`-m pytest -q`全量退出0，4项既有弃用警告；未提供数据库的跳过项不记通过。[后端日志](locate-intent-source-backend.log)。
- 同一源树临时库`plan74_v12_78be29b75b134415_test`升级0056后，私有库／选区／正文领域314项代码检查通过，随后只删除该临时库；没有对正式业务库运行测试。[数据库日志](locate-intent-source-database.log)。
- `scripts/package_plugin.py`退出0，包只来自本次干净构建；JS与tree见[来源](source-manifest.md)。正式锁已交其他任务，未为了复验再安装或重启。

## 已执行

2026-09-13后续F08／F09工作区检查（尚非正式复验）：F08合并原句选择的同步呈现与显式滚动请求，移除重复dispatch；弹窗动画关闭后再定位，普通关闭保留焦点恢复，切章使旧回调失效。定向62项、前端全量168文件1522项、typecheck与202模块build退出0。F09补充常见“修改……为……”识别，否定／假设／引用／询问在接受与撤销之前拒绝；已明确修改后的完整“不要改其他包”范围限制不否认该修改。定向76项通过，包括同请求应用、拒绝旧提案应用和拒绝撤销补偿。工作区全量含其他任务代码，最终发布必须另从精确提交复验；未据此关闭正式F08／F09。

| 范围 | 实际命令／结果 |
| --- | --- |
| Python全量 | `.venv/bin/python -m pytest`：3131通过、297跳过、4项既有弃用警告，18.83秒，退出0。跳过项不记通过 |
| PostgreSQL领域及选区链 | 用本文目录`run-code-database.py`执行`tests/private_library tests/test_selection_edit_domain_integration.py tests/test_domain_integration.py`：263项通过、退出0；包括13项私有库真实PostgreSQL用例、既有选区持久化／并发／恢复和正文领域链 |
| 前端页面接线 | `pnpm exec vitest run frontend/src/creative-center-private-library.test.ts`：4项通过；完整详情不截断、服务端分页／修改后重置、迟到查询及可见开关错误 |
| 章节候选接线 | 逐项决定／报告CAS重查与真实`ChapterWorkflowPanel`定向29项通过；迟到采用响应不能回写新页，不重调模型 |
| Workbench实际保存入口 | `pnpm exec vitest run frontend/src/workbench-private-library-save.test.ts`：15项通过；切章、IDB延迟、AI后连续手写、待选择恢复、冲突转手写、撤销前／中和读取失败 |
| 前端全量／类型 | 最终`pnpm test`：167文件、1492项全部通过，4.07秒；`pnpm typecheck`退出0 |
| 合成语料校验 | `validate_fixtures.py`退出0；清除4个新文件末尾多余空行并同步manifest的hash，无语义改变；10匹配／10生命周期／28维护场景与1000条规则、10000字的固定生成规格保持 |
| 前端构建 | `pnpm build`：202模块，退出0；当前工作区`frontend/dist/index.js` SHA-256 `f5ae18bedceff76183d5736c58b494ef3bae1650ec95c6b52670706541a17595`。尚非发布候选hash |
| 包审核 | `.venv/bin/python scripts/package_plugin.py`退出0；输出仅为工作区构建，未安装 |
| Diff检查 | `git diff --check`退出0；最终提交前仍需复查 |

数据库只创建本轮精确命名的专用代码临时库。最终通过运行使用`plan74_v12_7330ce60b73c4796_test`，从空库升级至0056，执行完成后已删除该唯一临时库；正式库未修改。凭据仅通过进程环境传入，没有写入报告或输出。

## 发现、修复与重跑

- 首轮受控保存/目录数据库定向64项通过；之后扩大到完整领域链发现旧选区持久化断言未包含服务端新增的genre/subgenre和空规则快照。按确切合同补全预期，未删除模型证据／失败／恢复／Diff断言，重跑263项全部通过。
- 前端全量初次暴露两处旧章节面板请求stub缺少当前`/library-checks`；补足真实请求和完整候选fixture，并追加迟到响应与报告CAS用例。新页面fixture缺少`current_version_id`及ES目标不支持`Array.at`也已修正。
- 只读汇合复核发现旧保存定时器未绑定章节、CAS完成后未重查页面、旧普通稿排队回退、隐藏恢复稿被激活和可变绑定回执覆盖。补修后以真实Workbench函数和回调驱动异步边界；宿主／HTTP／IndexedDB使用可控I/O，不能称为浏览器或正式写作证据。

## 复用证据的边界

本轮未改scanner、renderer、0056迁移和维护Skill，不能借修复改写已执行迁移。扫描器`lexicon_matcher.py`的开工tar快照与当前文件SHA-256同为`1f62cf58533035b4f769a8de011ce690a941b1120c47bde66ad4a9668b85b040`；原固定语料性能只按原范围引用，不外推网络/数据库/大库产品表现。

全部子代理已停止写入，最终前端全量／类型检查与暂存diff检查通过。随后完成下节独立提交树复验；正式桌面与真实写作链仍未执行。当前正式库schema只读复核为`20260913_0056`，它不证明新修复已部署。

## 独立提交树复验

提交`ea02b99e9793fa8da1dee457ce0f62f3d8bf0129`，tree `23dd0d85fcbe022a0d9f70a0a3e8e4a96d455297`；从它创建只做代码验证的detached worktree `/private/tmp/plan74-committed-source.Qv4ure/code`，没有建立任何第二套QwenPaw运行环境。

- pnpm离线安装使用原锁文件，复用64包、下载0；不添加依赖。确认Python导入来自该检出的`backend/__init__.py`。
- `pnpm test`：165文件、1461项通过；`pnpm typecheck`通过；`pnpm build`：200模块通过。
- 先完成前端构建，再运行项目解释器`-m pytest`：3124通过、291跳过、4警告，18.77秒。首次过早运行全量时，唯一失败来自打包合同所需`frontend/dist`尚未构建；完成构建后原样重跑通过，没有放宽断言。
- 同一提交树临时数据库运行上述263项领域／选区／私有库用例全部通过，库`plan74_v12_b685934865974fc4_test`已删除，正式库未改动。
- `scripts/package_plugin.py`审核通过，检出树`git status --short`为空。前端JS SHA-256为`ecc1e4cf023979d8dbd0ff6688ee5ee14cd49142f8a7e6217888df01fb8f3b4a`；包及来源见[source-manifest.md](./source-manifest.md)。

两组测试数量差异来自精确排除了外任务作品资料及朗读续播源码／测试，不是跳过私有库失败用例。此时提交树代码可独立构建，但部署它会遗漏正式已用外任务功能，因此当时G2-B发布源门禁HOLD；不能仅凭代码绿灯继续安装。

## 批准依赖后的完整提交树复验

作者本轮同意单独提交正式已有依赖。`96b8aed`在`/private/tmp/plan74-complete-source.8dnb1X/code`重新检出，status为空。使用原项目解释器和原锁文件，前端离线复用64包、下载0，typecheck通过，167文件1492项通过，构建202模块；Python全量退出0（4项既有弃用警告），同一源树打包成功。日志见[前端](complete-source-frontend.log)、[后端](complete-source-backend.log)。

该源树再次运行相同263项真实PostgreSQL代码用例，退出0；临时库`plan74_v12_423bc2982888442d_test`已精确删除，未连接正式业务库执行用例。见[日志](complete-source-database.log)。metadata的6项旧独立端口数据库用例本轮仍跳过，不计入这些私有库专项；其已上线行为来源为计划70现有正式证据。

完整G2-B通过，随后安装的是这次构建，不是旧独立包或脏工作区。正式运行合同和真实桌面仍分开计数，见[发布记录](formal-release.md)。

## F01修复提交的独立复验

`6c63ac650044e0cdf663121208d8e57c1a59c737`，tree `a906436d416f947fe7c0998dd95a9b088740f898`；独立检出`/private/tmp/plan74-capture-source.i7Vzhx/code`。新增14项capture用例与既有10项绑定用例共24项定向通过；工作区Python全量及277项数据库代码检查退出0。随后在该精确提交树重跑：

- `-m pytest -q`退出0、4项既有弃用警告；[后端日志](capture-fix-backend.log)。未把未提供数据库的跳过项记通过。
- 相同领域／选区命令增加14项后共277项真实PostgreSQL代码检查通过；临时库`plan74_v12_7e4e59c563484a2e_test`已精确删除。[数据库日志](capture-fix-database.log)。
- 离线固定依赖复用64包、0下载；167文件1492项通过、typecheck／202模块构建／package_plugin均退出0；[前端日志](capture-fix-frontend.log)。JS仍为`f5ae18bedceff76183d5736c58b494ef3bae1650ec95c6b52670706541a17595`，未夹带工作区新的朗读修复。

本提交代码复验PASS；正式prepare发现新外任务来源漂移，未安装，因此不能记F01产品PASS。小窗口审阅工具栏裁切在正式截图复查中另记未修复项，不受这些代码结果覆盖。

## F02／F03界面修复代码复验（后续目标轮）

正式来源HOLD仍在，继续只做本计划内可独立推进的界面修复。`859a643`把正文选区工具栏原视口1100规则替换为已有编辑区840容器规则，保留换行覆盖且避免长按钮挤出；不平行堆叠一套旧断点。容器／审阅／实际保存定向44项、前端1493、类型和构建通过。该提交独立检出再次前端1493、Python全量、类型／构建／包审核退出0。

`682fc604366070db5f0daf7b6515ff48480fd7f6`继续更正助手私有库范围状态条：读同一个选书状态并订阅切书／清空，不改上下文或工具权限。路由／上下文ref／私有库页面／容器定向29项通过，新增真实状态组件的切换与卸载取消订阅用例。

最终精确检出`/private/tmp/plan74-ui-source.2hohEa/code`，tree `c92efbc5c8c75ac4833c5b5f2254b7c1b24f3266`，status为空；离线64包复用、0下载；前端167文件1494项、typecheck、202模块构建、Python全量及package_plugin退出0。见[前端日志](ui-fixes-frontend.log)与[后端日志](ui-fixes-backend.log)。JS SHA `6c6827cd323cbc55bc873f87573c2f48ea1e032b783f71d93a27838a766aaf55`。

已用Git比较确认自6c63ac6起backend、tests、Skills、manifest、Python依赖和pnpm锁文件无差异，277项PostgreSQL代码结果按该相同后端范围复用，本轮不再创建数据库或写正式业务。以上均非视觉／正式维护PASS；候选未部署，需依赖来源解阻后整包正式复验。
