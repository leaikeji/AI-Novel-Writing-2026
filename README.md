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
- 私有素材不可变版本与小说固定绑定、统一 V3 生成上下文，以及基于 PostgreSQL + pgvector 的可重建语义索引 schema。
- PawApp 自有“向量模型接入”页和小说内授权卡片；当前固定阿里云百炼 `qwen3.7-text-embedding`、1024 维 Dense 契约，但未配置密钥、未授权小说、未调用真实接口。
- Docker Compose、迁移、前后端测试、安装和运行验证脚本。

选区 AI 候选、统一 Diff 审阅和作者确认应用已经进入现有工程；Agent 仍不能绕过作者确认直接改写权威正文。向量模型配置与本地派生索引管理已交付，但真实语义检索只有在作者配置密钥、测试连接并按小说授权后才会启用；它不包含计费功能，也不替代正文生成模型。图片和富文本编辑器尚未作为当前公开能力交付。聊天模型仍由用户在 QwenPaw 原生模型页选择；向量模型使用 PawApp 自有独立页面，不修改 QwenPaw 全局模型页。

## MOSS-TTS-Nano 当前范围

MOSS-TTS-Nano 是个人、本地、单用户功能。正式产品范围仅包含 6 个中文 `official_preset`：`onnx.Zhiming`、`onnx.Junhao`、`onnx.Weiguo`、`onnx.Xiaoyu`、`onnx.Yuewen`、`onnx.Lingyu`；固定 ONNX manifest 的 18 项目录只用于底层兼容和技术溯源，不代表 18 项全部进入当前产品范围。作者已确认并锁定绑定旁白 `onnx.Zhiming`、林晚 `onnx.Xiaoyu`、沈川 `onnx.Junhao`，正式产品只使用官方 manifest prompt codes 与官方默认参数。2026-08-28 canonical run `bb03ccaf-4681-490a-b987-84bec9199b3b` 已完成真实 Nano、网页播放器、CodeMirror、跳播、Range/ETag、四桌面组合与固定 30 分钟稳定性；作者随后明确确认“完整章节通过”，同 run listening finalize、resume 与 teardown 已完成，最终 result 为 `PASS_CANDIDATE`、human state 为 `PASS`。长期 QwenPaw 已升级到迁移 `20260828_0024` 并在 `runtime=true / product=true / validation=false / reference=false` 的个人本地产品模式通过验证，隐藏验证 token 已销毁。系统中文输入法另由作者本人确认亲自输入至少两个汉字且功能正常；验收执行器曾因只允许三次撤销而在输入后的基线恢复阶段返回 `HOLD`，该执行器缺陷已修复并通过自动回归，不得反写成用户输入失败。

商业发布／再分发审批、英文／日文专项、云端／远程／共享／复杂继承、OS signing／SSHSIG 以及章节／全书音频导出均是当前非目标，不阻断 T4；历史商业和签名审计保留，但其作为本地产品放行前置的旧口径已被取代。云端辅助说话人识别与高级匿名选角继续 `HOLD`，等待单独裁决。个人本地中文有限核心已通过 [T4-GATE](./docs/开发文档/证据/MOSS-TTS-Nano施工/T4-GATE.md)；最终候选 tree 为 `7a57471ebe9ea6cffc6d76529e3fdcab6c1683ad236499fbc2d1fdfb720bde13`。

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
