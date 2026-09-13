# F21历史计数修复与正式复验

日期：2026-09-13 22:50（Asia/Shanghai）。状态：F21 PASS；整体G3仍未闭合。本次无新模型调用、迁移或重启。

## 修复与代码证据

- 源码`6837e1be0e0ed1516e04b1c2ba5b302a5053d327`，tree `4759634dbde21c2c1e40d7673f40c209335f7828`。仅chapter-workflow.ts历史标签与chapter-panel.test.ts两文件；不改报告、扫描、采用或写回逻辑。
- 用“用词报告：扫描共N处命中 · 当前M处禁用表达待处理”区分两个计数；零待处理分支仍展示总命中及采用前复核提醒，failed/stale/incomplete不宣称通过。
- [红测](history-count-red.log)真实显示“生成时检查 · 禁用表达1处”，与扫描总数2矛盾；三个失败覆盖部分保留、未保留及全部保留标签。保留已有失败／过期／未完成、兼容和迟到响应的独立用例，不新增平行显示实现。
- 工作区定向35项、前端170文件1560项、typecheck及[构建](history-count-workspace-build.log)通过。干净检出`/private/tmp/plan74-incomplete-source.7FA64V/code`明确切换至6837e1b，再次完成[1560项／类型／构建／打包](history-count-source-frontend.log)，退出0。
- 与fbfc3e6相比backend、tests、skills、manifest、Python依赖均无差异；Python3210／331跳过及工作区PostgreSQL357项沿用F19同源证据，本轮没有伪称重跑或把跳过算通过。

## 正式备份、更新与恢复

- 22:47:23通过公开热更新安装，仅`frontend/dist/index.js`变化，SHA `d2876aa5d14505d24589e846874f8f79c00f36f0e34c8de312c0c1cfe542f5aa`。[精确来源](history-count-release-manifest.json)、[安装回执](history-count-install-result.json)、[健康](history-count-health-after.json)。旧JS `6e6399d85eb657004f4bb3d88f1c8c62d80f25ce919a71948150910d1f853e4c`即15f4f5f，年龄描述、声音和其他既有功能不回退。
- 本机备份`/private/tmp/plan74-history-count-release.kACQSE`；耐久副本`/app/working.backups/plan74-history-count-release-20260913-kACQSE`。两处数据库归档SHA `0726138d404e042227f47c150f34757ddd46a786096d3d0d706ebfbf7a66e086`、候选归档`c2876295505a28f7654efbaade29047042d20d0ee7155f46262fe20a0bf0a58d`、旧插件`08edd0ef76a6c1569577610598d5c667105d22e786643a85b74d56488b76e6a5`均一致，pg_restore列表验证通过。
- prepare/install/verify全部退出0，schema0056、容器身份／启动时点、健康ready／TTS ready及逐Agent选择保持。更新窗口的[实际有效模型](history-count-model-after.json)已是gemini/gemini-3.8-flash，[稍后只读观察](history-count-model-observed.json)相同；没有把旧候选请求的glm-5.3-flash强制设回。模型何时由谁切换不作无证据推断。
- 本次只读复验未产生新正文，若安装异常且脚本前置仍满足，可执行下列公开插件回退；有后续写作时先保留新稿、复核兼容，不倒回数据库：

```bash
.venv/bin/python audit/plan74/review-v1.2/release.py rollback --source /private/tmp/plan74-incomplete-source.7FA64V/code --backup /private/tmp/plan74-history-count-release.kACQSE --commit 6837e1be0e0ed1516e04b1c2ba5b302a5053d327 --before-writing
```

## 正式作者可见结果

- 刷新后从第二章历史查看2668字未采用候选：显示“扫描共2处命中 · 当前1处禁用表达待处理”，与报告v2一致。两个旧历史卡也分别展示总数／待处理数，不把本报告当已采用事实。[1080P画面](desktop/50-history-count-1080.jpg)实际CSS1920×1080、图片1919×1080。
- 缩小到CSS1267×713后，当前候选卡clientWidth=scrollWidth=655，标签在卡片内，无横向溢出。Escape退出，恢复默认viewport；没有操作任何“恢复此版本”或改变保留决定。
- [正文](history-count-document-after.json)、[任务及候选](history-count-jobs-after.json)、[词包绑定](history-count-bindings-after.json)分别与上一轮preview对应JSON完全相同：第二章draft11／2535；新候选仍ready，报告v2仍只保留第一项；没有新job、采用事件或revision。
- F21关闭。23:03后续已用独立Edge补齐原生2560×1440历史及候选逐项检查截图，见[桌面记录](desktop-validation.md#2303独立edge完整2k候选复验6837e1b)；通用库total13不足真实101+数据继续保留。网络／CAS等未正式覆盖项按原分层记录，不将本次标签复验扩大为所有恢复路径PASS。AI维护统计、文学A/B与拆书仍不在本轮执行范围。
