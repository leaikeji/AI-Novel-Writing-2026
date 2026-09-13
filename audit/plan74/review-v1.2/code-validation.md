# V1.2代码验证记录

日期：2026-09-13。状态：`G2-A PASS / COMMITTED-CODE PASS / RELEASE-SOURCE HOLD`。这不是正式产品验收；提交树已通过代码复验，但尚不包含正式环境的未提交外任务功能，不能部署替换正式环境。

## 已执行

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

两组测试数量差异来自精确排除了外任务作品资料及朗读续播源码／测试，不是跳过私有库失败用例。提交树代码可独立构建，但部署它会遗漏正式已用外任务功能，因此G2-B发布源门禁仍HOLD；不能仅凭代码绿灯继续安装。
