# VM34 向量写作闭环验收记录

日期：2026-08-29（Asia/Shanghai）

## 结论

VM34 的源码、线性迁移、长期 PawApp 安装、v2 授权、增量索引、写作检索快照、未来信息隔离和三视口 UI 已完成。冻结离线检索门禁通过。真实三次正文生成中只有一次满足长度门槛，因此最终裁决为：**向量写作链路通过，正文模型单次长度遵循部分通过，不能宣称三章真实生成全部通过。**

## 可复核事实

- 数据库迁移 head：`20260829_0031`；其中 VM34 schema 为 `20260829_0030`，`0031` 属于并行 TTS 工作。
- `novel_chunks`：长期 PostgreSQL 中不存在；现行表为 `semantic_sources`、`semantic_chunks` 和 `semantic_embeddings`。
- 迁移前备份：`/Users/liujia/Documents/AI小说世界2026-backups/vm34-20260829-1750/ai_novel_world_2026-before-vm34.dump`。
- 备份 SHA-256：`a7d11dd0982082d5e2c437f5781fe87791896e7259bc1fa233c803892d9fadf0`。
- 长期健康端点：PawApp `ready`、PostgreSQL connected、embedding runtime `ready`、向量检索 enabled；TTS 同时保持 `ready`。
- active generation：`qwen3.7-text-embedding`、2048 维、PostgreSQL + pgvector 精确 cosine；未增加 ANN、第二套向量数据库或计费 UI。

## 冻结评测

`scripts/embedding/evaluate_v2.py` 使用 36 个非自查询固定案例：24 个正例、12 个无答案／隔离负例。结果：

```text
Recall@5                 1.00
MRR                      1.00
无答案正确拒答率         1.00
泄漏                     0
lexical-only Recall@5   0.50
hybrid Recall@5         1.00
```

该结果证明固定契约、排名和隔离门禁，不代表任意真实小说的普遍质量。线上阈值仍应随更多作者自有 query-label 样本持续校准。

## 真实联合 E2E

- 合成小说：`潮声档案室（VM34·20260829-180610）`，ID `848309a8-3e1e-459a-aea3-69084ad28a33`。
- 授权：`novel-embedding-consent/2`，写作 query 已明确授权。
- 最终索引：ready/current，index version 7，6 个来源、34 个块、0 失败，authority digest 与 published digest 一致。
- V1 corpus：正文 3 来源／31 块，规划 2／2，绑定私有素材 1／1；V2 结构化 corpus 保持关闭。
- 人物稳定根从“林渡”改名为“林砥”后 ID 保持；建立隐藏真实身份、固定 required 素材与兄弟时间线干扰。
- 在第三章已入索引后，以第二章截止位置查询“银色鲸铃”，第三章 revision 命中数为 0。
- 三次真实正文调用输出 1295、1995、2526 个可见字符；只有 1995 通过 1700–2300 门禁。为继续验证索引链，第一、三章使用明确标记的作者合成恢复稿正式化。未追加真实调用。

真实 E2E 脚本默认拒绝运行；只有显式传入 `--confirm-live VM34-LIVE-3-CALLS` 才会创建实验小说并发起三次正文调用，避免误触发云端。

## 浏览器验收

- 1920×1080：向量配置页和小说语义索引卡片布局正常。
- 2560×1440：向量配置页 `innerWidth == scrollWidth`，无横向溢出。
- 390×844：向量配置页与语义索引卡片纵向重排正常，`innerWidth == scrollWidth`。
- 页面显示固定只读 2048 维、write-only 掩码 Key、v2 告知、写作 query 状态、同步版本、来源／分块／失败数和 V2 corpus 禁用状态。
- 控制台只有一条宿主级 `[moduleRegistry] Module not found: AppCenter` warning；未发现 VM34 页面 error。

## 恢复与剩余风险

需要回退数据时，先停止长期服务，再用上述 dump 恢复到新建的隔离数据库核验，禁止直接覆盖当前长期库。旧 active generation 和历史快照保留，candidate 失败不替换 active。

## 自动化与共享工作区阻断

- `pytest tests/context_v4 tests/embedding`：147 项通过。
- VM34 相关前端：45 项通过。
- `pnpm typecheck`、`pnpm build`、`docker compose config --quiet`、`scripts/package_plugin.py`：通过。
- 全量 Python 当前在并行 TTS 的 `test_settings_api.py` 收集期因 settings operation 集合未同步而失败。
- 全量前端当前为 855 通过、10 个 TTS 播放／阅读页测试失败；失败集中在 TTS volume/rate 新契约和阅读页导航变更。
- `git diff --check` 还报告并行 TTS 文件 `frontend/src/narration/narration-player.ts:152` 的尾随空格。

这些共享工作区失败不来自 VM34，且计划 34 无权改写计划 33 的未收口文件，因此没有通过修改、回退或混入 TTS diff 来制造“全量通过”。

剩余风险有两项：正文生成模型的单次长度遵循尚不稳定；现有通用安装验证脚本仍按 TTS catalog 1.0 断言，而当前并行 TTS 运行包已为 2.0。这一 TTS 验证脚本漂移不属于 VM34，也没有通过回退 TTS 代码规避。
