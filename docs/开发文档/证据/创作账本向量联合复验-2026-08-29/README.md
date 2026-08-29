# 创作账本与 2048 维向量联合复验证据

状态：**2026-08-29 已完成。** 本目录只保存脱敏结论与安装后真实页面截图；不保存 API Key、正文请求体、完整向量或数据库备份。

## 1. 环境与恢复点

- 长期 PawApp：QwenPaw `2.1.0`，PawApp `0.4.0`，`http://127.0.0.1:18088`。
- PostgreSQL：18.6 + pgvector；Alembic head `20260829_0029`。
- 事前仓库外备份：`/Users/liujia/Documents/AI小说世界2026-backups/20260829-cdg-w4-before-0029/`。
- 备份清单摘要：`6110158a799cb9db8fa0d6e63721b2b2f0a7d57da5e0f24a56338ba211b42c27`。
- 实验小说：`507efd23-5886-4d5f-9474-da1420dade1a`，标题“逆潮邮局（账本向量联合复验·20260829-140023）”。
- 测试驱动首次运行多建了一个自动占位的空白首章；已在确认内容为空、版本为 1 且已有上述备份后，精确删除文档 `5ebdfe8a-9184-49a6-a0ba-ab59ad2824df` 及其空卷 `995ab157-2e96-47d7-97f1-70f4cd4614be`。驱动已改为复用建书时的首章和首卷，后续不会再产生该冗余。

## 2. 账本闭环结果

- 正文为 3 章，非空白字符数分别为 2053、2041、2053，总计 6147；工作台显示 3 章节。
- 主时间线：`72838d8b-0d39-47a1-863e-d3f7a882599d`。
- 人物“沈见星”正式改名为“沈照”后，人物根和人物实例稳定引用不变；`former_name` 与 `official_name` 别名链均有效。
- 三份 ChapterBrief 均保存 V3 稳定人物引用；旧名章纲在改名后仍能解析到同一人物根和实例。
- 三份正文 revision 均保存结构化时间线映射；故事年 2034 下人物年龄按出生年返回区间，不使用服务器日期。
- 5 条已确认 `StoryFact v2` 覆盖改名、关系互信、故事线进展、伏笔揭晓和知识获得；关系、故事线、伏笔读取投影分别为“互信”、`active/70`、`resolved/100`。
- 私有素材固定绑定旧 version；素材根更新后只显示“有更新”，未静默改变小说绑定。
- GET/list/context/search 前后 StoryFact 数量不变，读路径零写入。

## 3. 真实向量结果

- 服务商／协议／模型：阿里云百炼／DashScope Native／`qwen3.7-text-embedding`。
- 请求与实际维度：2048；输出 Dense；距离 cosine。
- active generation：`4e74dff1-74d0-4e42-a96e-5f9af34c5cdd`，第 12 代，`active`，固定评测 `passed`。
- chunker：`semantic-char-chunker/4`，单块最多 256 个字符、重叠 32；33/33 后台批次完成。
- 当前语料：正文 3 来源／30 块，规划 2 来源／2 块，绑定私有素材 1 来源／1 块，总计 6 来源／33 块／0 失败。
- 33 个向量的实际维度均为 2048；只有该实验小说处于已授权状态。
- 查询“七角蓝蜡封对应哪道潮闸”能召回固定版本私有素材；精确查询“七角蓝蜡封对应第七潮闸”首位命中，通道为 dense + lexical，且无隔离警告。
- 健康接口：`vector_retrieval_enabled=true`，`embedding_runtime.state=ready`；未读取或记录完整 API Key。

## 4. 真实页面三视口

全局“向量模型接入”页：

- [1920×1080](./向量模型接入-1920x1080.png)
- [2560×1440](./向量模型接入-2560x1440.png)
- [390×844](./向量模型接入-390x844.png)

小说内“语义索引”卡片：

- [1920×1080](./小说语义索引-1920x1080.png)
- [2560×1440](./小说语义索引-2560x1440.png)
- [390×844](./小说语义索引-390x844.png)

结果：桌面两视口和折叠宿主助手后的 390px 单列布局均无页面级横向溢出；窄屏 `documentElement.scrollWidth=386`、`window.innerWidth=386`。浏览器控制台错误为 0。QwenPaw 在 390px 下展开助手时会覆盖 PawApp，这是宿主布局行为；本项目不修改 QwenPaw 核心，验收时通过宿主已有“折叠助手”操作进入 PawApp。

## 5. 自动化与冗余清理

- 定向回归：166 passed。
- 最终安装器全量结果：后端 3022 passed / 127 skipped；前端 92 files / 836 tests；typecheck、build、打包、Alembic 和长期热安装通过。
- 已删除施工中的旧线程池／隔离事件循环 worker 方案；生产 embedding 只保留单一后台运行器。
- embedding 统一通过 `backend.background.jobs` 访问共享任务围栏，不再直接依赖 narration job 实现。
- chunker 版本只保留 `semantic-char-chunker/4` 权威常量；旧版本只存在于不可变审计 generation，不保留生产分支。
- 仍被安装器、生命周期门禁和只读验收调用的 TTS 运维脚本没有删除，而是统一更新为当前 Alembic head `20260829_0029`；仓库中 `20260828_0024` 只剩迁移链与迁移契约测试的历史引用。
- `novel_chunks` 按 31 号计划作为空弃用兼容表保留，Alembic 历史不删除；V2 renderer 是下一阶段独立 corpus 的冻结入口，不属于重复实现。

截图 SHA-256：

```text
2f7213fca720a213b0fcb0ffc9026378bef63df1ebb61748afe16ab6b4b3ec6b  向量模型接入-1920x1080.png
613d2aa584859b08e5386da1a89a567754aca32ac51098bd141765161f6294bb  向量模型接入-2560x1440.png
1e3bb7503c5c442a390844a174909b2963dc7dc2141e034c89110ff1b837ef04  向量模型接入-390x844.png
9eff6565fcef97100c7a6d5407955b15c73bc813f683394e6892c994dc5a86a6  小说语义索引-1920x1080.png
382361d5d795ef36666cdb71af80b16c04e185a89ed91a830dab225214031a0b  小说语义索引-2560x1440.png
4ad634e15c151471f59a67c6b9b3a868ddb3f2c97fafc9f4321bb3aa70d1e2b4  小说语义索引-390x844.png
```
