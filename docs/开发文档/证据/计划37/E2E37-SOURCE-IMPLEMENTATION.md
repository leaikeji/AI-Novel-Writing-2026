# E2E37-SOURCE-IMPLEMENTATION：写作链源码施工与非 TTS 自动化证据

日期：2026-08-29（Asia/Shanghai）

状态：`SOURCE_READY / DEPLOYED / REAL_CHAIN_PASS_WITH_CONTENT_REVIEW_RISK`

范围：计划 37 的非 TTS 写作链。源码阶段完成后，作者另行授权了合成实验小说的真实正文／百炼调用以及长期 PawApp 安装；未点击或测试朗读、声音、Nano、VoiceGenerator、播放器及声音绑定，未提交或推送 Git。

## 一、已完成的源码修复

1. Context V4 多时间线装载改为按目标线人物实例和正文 revision mapping 取数；兄弟线、父线分叉后片段、失效或缺失映射均 fail closed，单时间线继续使用 `single-timeline-identity/1`。
2. 新正文生成任务强制要求 `WritingPosition`、有效模型窗口和 Context V4；生成快照固定为 schema 4，不再产生 `context_v3`、`previous_context` 等 V3 新任务字段。历史 V3 读取与独立公共 context 兼容接口仍保留。
3. 新增从当前正式正文 revision、正式大纲／设定和已绑定固定素材版本读取的纯本地词面回退；无 active generation、Dense 故障或未授权时无需云端调用、无需数据库写入。未来章节、兄弟线、未映射片段、未绑定／prohibited 素材和非作者视角秘密均被过滤。
4. 检索只对 provider、网络、超时和派生索引错误降级；owner、scope、timeline 和 mapping 等确定性错误保持结构化失败，不再被吞成普通空结果。
5. AI 人物草案输出升级为 `OutlineCharacterDraftV2` 对齐字段；同名人物由 `draft_key`／稳定 ID 区分，不再按姓名拒绝或自动合并。
6. 删除生产 prompt 中“久别重逢和治愈”题材硬编码；正文长度失败诊断改用任务冻结的目标、上下限和实际字符数。
7. 章节审稿和关系同步统一使用公开模型证据标签；`not_exposed` 不再显示“实际模型已验证”。
8. 删除时间线工作区重复的人物实例档案写表单，统一跳转正式人物卡；删除无调用者的旧 `frontend/src/workbench.ts` 和 `workbench-v2.ts` 内重复创作中心实现。
9. 390×844 下工作台主容器恢复纵向滚动，避免大纲底部“下一步：生成人物草案”等操作被固定高度容器永久裁掉。

## 二、自动化与构建结果

使用专用临时 PostgreSQL 容器 `ai-novel-plan37-pg`、数据库 `ai_novel_plan37_test`；未连接长期数据库。

```text
AI_NOVEL_TEST_DATABASE_URL=<隔离测试库> .venv/bin/python -m pytest --ignore=tests/narration <排除两项 TTS 安装意图测试>
826 passed, 36 skipped, 2 deselected, 3 warnings

node node_modules/vitest/vitest.mjs run --exclude frontend/src/narration/**
55 files passed, 402 tests passed

node node_modules/typescript/bin/tsc --noEmit
PASS

node node_modules/vite/bin/vite.js build
PASS；frontend/dist/index.js SHA-256:
f4ecf801ef02ab189e451d15f91b98aec0705ae23337b7d52b25f071ed7336bf

docker compose config --quiet
PASS

.venv/bin/python scripts/package_plugin.py
PASS；输出 build/ai-novel-world-2026

git diff --check
PASS
```

三条 warning 来自 Starlette `TestClient`／httpx 弃用提示以及两处 FastAPI 旧 422 常量弃用提示，不改变写作行为。一次数据库测试命令曾因临时容器密码占位值错误而在连接前失败；另一次把生产 URL 与测试 URL 指向同一隔离地址，按安全门禁主动拒绝。纠正测试环境变量后，826 项实际执行均通过，36 项按环境条件跳过；两次前置失败都不是产品断言失败。

## 三、浏览器基线与已修复缺陷

长期运行包（安装前基线）在 1920×1080、2560×1440 和 390×844 均能渲染“大纲／人物草案”，“下一步：生成人物草案”按钮处于 enabled。移动端实测发现 `.anw-workbench-main` 为固定高度且 `overflow-y:hidden`，按钮虽在 DOM 中却位于可视区下方且无法到达；已增加窄屏滚动规则和前端回归测试。

该浏览器结果最初只证明旧包基线和缺陷复现；后续候选已安装，并在三档视口完成第三章 2128 字正文成功态复验，结果见 `E2E37-LIVE.md`。

## 四、保留项与清理裁决

- `backend/context_v3/**` 与 `get_novel_context()` 仍被公共 `/context`、Agent 工具和历史测试使用，具有独立兼容价值，未删除；新正文生成任务已不再调用它。
- `backend/writing_eval_*` 是计划 22 的显式开关、非持久化写作 A/B 研究能力及历史契约，不是计划 37 样书 fixture，未越权删除。
- 旧 generation、revision、迁移和验收原始证据属于审计／回退记录，未删除。
- TTS/narration 文件、计划 35 文档、`pyproject.toml` 及其共享运行态均未纳入本计划修改或验收。

## 五、最终施工补充

作者随后授权真实模型和长期 PawApp 操作，计划 35 也明确释放长期环境锁。最终包已安装，三章正文为 2059、1783、2128 字，第三章快照命中前两章 current revision，active index 收敛到 version 7；三视口正文成功态无横向溢出。长度闭环、结构化重试、采用防御门禁和最终运行证据见 `E2E37-LIVE.md`。

剩余风险不是部署门禁：真实模型对“林渡与林砥是同一人”的复合语义约束发生一次误判，因此正文候选仍必须由作者审阅后采用。TTS 继续明确排除，Git 未提交、未推送。
