# 计划84 F84-02—F84-07拆分候选冻结

冻结时间：2026-09-15 00:08 CST

状态：`FORMAL_PASS_F84_02_07`（不含F84-01；代码QA与正式桌面矩阵均完成，作者已将计划84整体裁决为`CLOSED_WITH_LIMITS`）

## 拆分边界

- 当前diff不再包含`creative-center-entry.ts`、`novel-surface-navigation.ts`、`workbench-route.ts`、`assistant-route-wrap.test.ts`及三份对应路由测试的改动；这些文件均与HEAD一致。
- `creative-center.ts`只保留F84-02、F84-04和建书弹窗部分的F84-05，不含入口pending、Performance Navigation、URL重写或查询恢复逻辑。
- F84-01继续登记`BLOCKED_UPSTREAM`；第七版失败候选不得再次部署。

## 候选身份

- 8个生产源码有序SHA-256再哈希：`abc3bf0d6c7420f3fdece8e841f8d67b9c6ee1dfba5f7ec56cf1faea2cbdcb1e`
- 打包树确定性哈希：`6ee292e7d470da113b4ae21792e8d5bae004a3e512a32e1f3a37a930aeac2b22`
- 前端bundle SHA-256：`f993d703c445d5815c97564ba9bd5d150674bf230a26404632bf0175ec0d6bd0`
- `plugin.json` SHA-256：`79fae92a55706815babcd349bae892f70f680cd8d4f3abdcc363210bcec18605`
- PawApp manifest仍为0.4.0；无迁移、依赖或锁文件变化。

生产源码集合：

- `backend/private_library/lexicon_service.py`
- `frontend/src/creative-center.ts`
- `frontend/src/template-field-meta.ts`
- `frontend/src/private-library/contracts.ts`
- `frontend/src/private-library/model.ts`
- `frontend/src/private-library/private-library-workspace.ts`
- `frontend/src/workbench-studio.ts`
- `frontend/src/styles.ts`

## 本轮复查修复

- 全书搜索在关键词发生任何变化时立即清空旧结果并推进请求代际；旧关键词的迟到成功、失败或`finally`均不能污染新关键词状态。
- 建书关闭在任何异步等待及React状态提交前用共享ref同步加锁；连续Escape／关闭只允许一次草稿PATCH和一次关闭。成功、失败、无草稿及完成回调路径最终都会释放锁，保存失败仍保持弹窗打开。

## 实际验证

- 定向前端：14个文件、123项通过；同步锁加入后关键3文件21项通过。
- 最终全前端：165个文件、1573项通过。
- `pnpm typecheck`：通过。
- 最终全Python：3209项通过、329项按既有外部环境条件跳过；4项既有弃用告警。
- `pnpm build`、`.venv/bin/python scripts/package_plugin.py`、`git diff --check`：通过。
- 两路最终只读QA分别复算四项身份并复核F84-02—F84-07，均未发现P0—P3。

## 正式产品验证

- [首次正式尝试](../formal-split-attempt-20260915/README.md)因浏览器草稿绑定前置不成立而安全停止并回退；作者随后明确采用该次产生的草稿作为唯一验收草稿，历史记录不倒改。
- 2026-09-15重新安装同一冻结候选后，正式Edge完成F84-02—F84-07的私有库、设定、建书／搜索Escape、1920×1080／2560×1440／1366×768双助手态、无障碍及只读非回归矩阵。
- 正式计数在本轮前后均为`6/7/16/41`；同一授权草稿从version 2单次保存至version 3，没有新增第八份草稿或其他权威数据变化。
- 结束验证器、容器健康、Agent／Skill／工具／prompt／TTS保持；排除运行时Python缓存后的安装树、bundle和manifest与本页冻结身份完全一致。完整证据见[正式完成记录](../formal-split-completion-20260915/README.md)。
