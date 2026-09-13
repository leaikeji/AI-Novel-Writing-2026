# AI小说世界2026

AI小说世界2026 是运行在 QwenPaw 2.2.1 中的个人小说写作 PawApp。

2026-09-10 当前运行版本已完成[计划 64](./docs/开发文档/64-账本前端移除与系统自动维护收口.md)：移除新增账本页面、入口及流程技术提示，保留原有创作布局，并修复事实去重和上下文冲突截断。候选已安装到长期 `18088`，QwenPaw 与 PostgreSQL 容器健康；桌面及 390×844 窄屏实际页面确认项目导航只保留章节、大纲、角色、线索、设定、朗读六项，正文编辑可打开且浏览器控制台无错误。专用 Agent 的 11 个小说 Skills 已启用，默认与 QA Agent 未被污染。未调用真实付费模型，因此不据此宣称文学质量已经提升。作者已否定计划 60 整份方案，不继续其界面重设计。具体证据见[本次记录](./audit/plan64/README.md)。

同日已完成[计划 65](./docs/开发文档/65-创作中心整书删除修复与测试小说清理.md)：修复含朗读、媒体、音色和后台任务数据时整书删除被数据库保护链阻断的问题，生产数据库升至 `20260910_0051`。在完整双备份及作者动作时再次确认后，真实创作中心已逐本删除《雾宅来信》《裂隙追凶》《雨港来信》；业务表与媒体残留为零，三本保留作品与删除前快照一致。证据见[计划 65 记录](./audit/plan65/README.md)。

阶段 3–6 的本机工程闭环已经完成，当前包含：

- QwenPaw 官方 PawApp 插件清单和后端入口。
- PostgreSQL 18.6 + pgvector 0.8.6、Alembic 和单一故事账本权威链。
- 作品库、卷章、Markdown 源文本、CAS 自动保存、不可变检查点、历史恢复和 IndexedDB 崩溃恢复。
- 一个通过官方 `route.wrap` 与 QwenPaw 原生聊天共存的三栏工作台；普通 `/chat` 不变。
- 专用“AI小说作家” Agent，以及只在该 Agent 中启用、可持续优化的十二个小说 Skills。
- 八个受范围校验的小说工具；HTTP UI 与工具共用同一领域服务。
- 正式大纲／设定／人物不可变 revision、稳定人物根与时间线人物实例、`StoryFact v2`、单线零配置与显式多时间线投影。
- 私有素材不可变版本与小说固定绑定、统一 Context V4／WritingContextSnapshot V1，以及基于 PostgreSQL + pgvector 的可重建语义索引。
- PawApp 自有“向量模型接入”页和小说内授权卡片；当前固定阿里云百炼 `qwen3.7-text-embedding`、2048 维 Dense、cosine。正式正文、规划和已绑定私有素材支持 active generation 增量同步；v2 授权后，正文生成、章纲、审稿和部分选区操作可自动检索并在云端失败时降级到本地词面检索。
- Docker Compose、迁移、前后端测试、安装和运行验证脚本。

选区 AI 候选、统一 Diff 审阅和作者确认应用已经进入现有工程；Agent 仍不能绕过作者确认直接改写权威正文。Dense 查询只有在作者配置密钥、索引就绪并把小说授权升级到 `novel-embedding-consent/2` 后才会启用；未授权、撤销、超时或云端失败时不会阻断正文写作。它不包含计费功能，也不替代正文生成模型。图片和富文本编辑器尚未作为当前公开能力交付。聊天模型仍由用户在 QwenPaw 原生模型页选择；向量模型使用 PawApp 自有独立页面，不修改 QwenPaw 全局模型页。

## Qwen TTS 当前范围

朗读已迁移为本地＋云端双 Provider：默认使用本机 Qwen3-TTS-12Hz 1.7B，作者可显式切换到阿里云 Qwen-Audio 3.0 Plus/Flash；系统不做静默自动回退。本地 CustomVoice、Base 克隆和 VoiceDesign 按需串行加载，编辑文章时只重生失效句段，避免把频繁修改全部变成云端调用。当前产品只保留官方预设与人物专属声音，MOSS/Nano/VoiceGenerator/24 槽通用池现行运行链已经移除。

计划 61 已在长期 `18088` 的创作中心上线“语音模型接入”页；云端 Base URL、质量／速度模型 ID 和只写 API Key 均在该页面维护，可保存多个公共 HTTPS 会员渠道但同时只启用一个，本地模型无需填写域名或 Key。桌面与 390×844 窄屏真实页面已复核，本地状态显示运行正常。旧 `QWEN_TTS_ALIYUN_*` 环境变量不再启用云端 Provider；真实云端测试继续等待作者配置完成后的明确授权。

长期 `18088` 已安装 PawApp `0.4.0`，生产数据库为 `20260910_0051`，宿主已按[计划 78](./docs/开发文档/78-QwenPaw-2.2.1补丁升级实施记录.md)从 QwenPaw 2.2.0 升级至 2.2.1；QwenPaw、PostgreSQL、本地 Qwen Provider 和朗读 worker 健康。计划 62 已恢复 103/107 个失败句段，剩余 4 个为有明确提示且不可自动重试的音频质量失败；旧 MOSS/Nano/VoiceGenerator/24 槽活跃代码、数据、schema 和共享 scope trigger 旧分支均已移除。1677 个旧 TTS 音频经清单、大小与 SHA-256 复核后按作者明确授权销毁，共释放 293,194,837 bytes；当前 Qwen 音频仍可真实播放。数据库四角色、完整插件生命周期、全量自动化和媒体 Range 均通过。云端 Provider 的接口、授权和失败语义已实现，但真实凭据 smoke 尚未执行。实施与恢复证据见[计划 59](./docs/开发文档/59-Qwen-TTS本地云端双Provider迁移施工计划.md)、[计划 61](./docs/开发文档/61-语音模型接入入口与多渠道配置页面计划.md)、[计划 62](./docs/开发文档/62-Qwen-TTS失败恢复与MOSS残留清理计划.md)、[计划 62 施工记录](./audit/qwen-tts/plan62/施工记录.md)、[计划 78 证据](./docs/开发文档/证据/计划78/README.md)和[计划 65 证据](./audit/plan65/README.md)。

计划 52 的 `0039` 只为 working copy 增加可回填的可见字数列，不建立第二套账本。计划 54 已在双备份和隔离往返后删除 7 本精确测试小说、保留 3 本正式／不确定小说，并移除故事账本旧 HTTP 路径、人物 V1、提交覆盖字段和两个等值兼容列；人物卡、Context、Embedding 与全书工作台只消费同一 `story_facts` 权威链。计划 53 建立的四角色和 schema-owner 维护链继续有效，API／worker 运行连接切换仍按设计 `HOLD`。MOSS 时代的计划、迁移和验收材料只保留历史审计事实，不再作为现行运行路径。商业发布／再分发审批、云端／远程／共享、OS signing／SSHSIG 以及章节／全书音频导出仍是当前非目标。

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

开发和验证命令见[初始化说明](./docs/开发文档/13-新项目初始化与兼容性验证.md)；当前故事账本结构、清理与长期运行证据见[计划 54](./docs/开发文档/54-故事账本单契约收缩与测试小说清理计划.md)及其[验收证据](./docs/开发文档/证据/计划54/README.md)。
