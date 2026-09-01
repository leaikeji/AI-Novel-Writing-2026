# AI小说世界2026

AI小说世界2026 是运行在 QwenPaw 2.1.0 中的个人小说写作 PawApp。

阶段 3–6 的本机工程闭环已经完成，当前包含：

- QwenPaw 官方 PawApp 插件清单和后端入口。
- PostgreSQL 18.6 + pgvector 0.8.6、Alembic 和最小小说账本。
- 作品库、卷章、Markdown 源文本、CAS 自动保存、不可变检查点、历史恢复和 IndexedDB 崩溃恢复。
- 一个通过官方 `route.wrap` 与 QwenPaw 原生聊天共存的三栏工作台；普通 `/chat` 不变。
- 专用“AI小说作家” Agent，以及只在该 Agent 中启用、可持续优化的九个小说 Skills；`0.4.0` 新增人物塑造、场景构建和对白技法，并强化正文与审稿方法。
- 三个只读小说工具；HTTP UI 与工具共用同一领域服务。
- 正式大纲／设定／人物不可变 revision、稳定人物根与时间线人物实例、`StoryFact v2`、单线零配置与显式多时间线投影。
- 私有素材不可变版本与小说固定绑定、统一 Context V4／WritingContextSnapshot V1，以及基于 PostgreSQL + pgvector 的可重建语义索引。
- PawApp 自有“向量模型接入”页和小说内授权卡片；当前固定阿里云百炼 `qwen3.7-text-embedding`、2048 维 Dense、cosine。正式正文、规划和已绑定私有素材支持 active generation 增量同步；v2 授权后，正文生成、章纲、审稿和部分选区操作可自动检索并在云端失败时降级到本地词面检索。
- Docker Compose、迁移、前后端测试、安装和运行验证脚本。

选区 AI 候选、统一 Diff 审阅和作者确认应用已经进入现有工程；Agent 仍不能绕过作者确认直接改写权威正文。Dense 查询只有在作者配置密钥、索引就绪并把小说授权升级到 `novel-embedding-consent/2` 后才会启用；未授权、撤销、超时或云端失败时不会阻断正文写作。它不包含计费功能，也不替代正文生成模型。图片和富文本编辑器尚未作为当前公开能力交付。聊天模型仍由用户在 QwenPaw 原生模型页选择；向量模型使用 PawApp 自有独立页面，不修改 QwenPaw 全局模型页。

## MOSS-TTS-Nano 当前范围

MOSS-TTS-Nano 是个人、本地、单用户功能。当前固定目录的 18 个官方 `official_preset` 已进入产品范围，覆盖中文 6 项、English 5 项和日本語 7 项；作者可以搜索、按语言筛选、可选试听，并零确认直接用于旁白或人物。跨语言和未专项听检信息只作提示，不阻断本机写作朗读。人物卡同时保留“根据人物卡匹配并使用官方音色”和“生成并使用人物专属音色”两条不同链路；Nano 高级调音与私人音色生命周期继续使用既有 CAS、幂等和失败不改原绑定规则。

当前已应用的线性 Alembic 迁移链包含 `20260830_0035`。MOSS-VoiceGenerator 的 macOS 原生一次性进程、人物卡一键生成、Nano 技术验证、generated Voice Version 与 CAS 自动绑定已经通过机器和产品链路验证；作者尚未完成对专属音色的主观听检，因此不能表述为作者已经满意。商业发布／再分发审批、云端／远程／共享、OS signing／SSHSIG 以及章节／全书音频导出仍是当前非目标。历史中文有限核心证据继续保存在 [T4-GATE](./docs/开发文档/证据/MOSS-TTS-Nano施工/T4-GATE.md)，后续 18 音色与人物专属音色裁决分别以计划 35／40 的现行记录为准。

## 目录

```text
backend/                 PawApp API、领域服务、SQLAlchemy 模型与 Alembic
frontend/                共享 QwenPaw React/Ant Design 的前端入口
skills/                  小说 Skills
scripts/                 构建、安装、Agent 配置、验证和显式卸载脚本
tests/                   Python 单元、契约与 PostgreSQL 集成测试
docs/                    开发文档与只读产品研究
plugin.py                QwenPaw 后端插件入口
plugin.json              QwenPaw PawApp 清单
compose.yaml             Mac 本机回环运行拓扑
```

开发和验证命令见[初始化说明](./docs/开发文档/13-新项目初始化与兼容性验证.md)，最新运行证据见[阶段 3–6 实现与验收](./docs/开发文档/14-阶段3至6实现与验收.md)。
