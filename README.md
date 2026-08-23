# AI小说世界2026

AI小说世界2026 是运行在 QwenPaw 2.1.0 中的个人小说写作 PawApp。

阶段 3–6 的本机工程闭环已经完成，当前包含：

- QwenPaw 官方 PawApp 插件清单和后端入口。
- PostgreSQL 18.6 + pgvector 0.8.6、Alembic 和最小小说账本。
- 作品库、卷章、Markdown 源文本、CAS 自动保存、不可变检查点、历史恢复和 IndexedDB 崩溃恢复。
- 一个通过官方 `route.wrap` 与 QwenPaw 原生聊天共存的三栏工作台；普通 `/chat` 不变。
- 专用“AI小说作家” Agent，以及只在该 Agent 中启用、可持续优化的六个小说 Skills。
- 三个只读小说工具；HTTP UI 与工具共用同一领域服务。
- Docker Compose、迁移、前后端测试、安装和运行验证脚本。

当前不包含 AI 正文写回、确认、Diff、向量检索、TTS、图片或富文本编辑器。聊天模型仍由用户在 QwenPaw 原生模型页选择；项目不另建模型配置页。

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
