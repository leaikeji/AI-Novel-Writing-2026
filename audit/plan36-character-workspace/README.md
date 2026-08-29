# 计划 36 安装与人物卡验收证据

日期：2026-08-29（Asia/Shanghai）

## 安装与数据库

- PawApp health：`ready`
- PostgreSQL：connected
- 安装后 Alembic head：`20260829_0033`
- 安装前 head：`20260829_0031`；安装按线性顺序执行 `0031 → 0032 → 0033`
- 仓库外备份：`/Users/liujia/AI小说世界2026-backups/plan36-20260829-before-0033/`
- 备份 SHA-256：`9a38066fe523add3b4a26cf6579b7820654ba5a1c870a96f644619b8195bfe33`
- 未调用真实正文模型或向量模型。

## 浏览器验收

实验小说：`848309a8-3e1e-459a-aea3-69084ad28a33`。

- 多时间线首次打开：先显示时间线和人物版本选择；两个字段均明确选择后才允许打开人物卡。
- 1920×1080：浏览器实际内容区 1901×1069；人物卡 900×814；页面 `scrollWidth == innerWidth`。
- 2560×1440：浏览器实际内容区 2534×1426；人物卡 900×814；页面 `scrollWidth == innerWidth`。
- 390×844：浏览器实际内容区 386×835；人物卡 386×836，贴边全屏；正文区独立纵向滚动；页面 `scrollWidth == innerWidth`。
- 基础资料、本线档案、成长与状态、声音四页签均可打开；声音页复用现有人物声音组件。

截图：

- `character-workspace-1920x1080.png`
- `character-workspace-2560x1440.png`
- `character-workspace-390x844.png`

## 自动化结果

- `.venv/bin/python -m pytest --ignore=tests/narration`：763 passed，35 skipped。
- `.venv/bin/python -m pytest`：3134 passed，138 skipped，2 failed；两项失败均为计划 35 测试把 migration head 写死为 `0032`。
- `pnpm typecheck`：PASS。
- `pnpm build`：PASS。
- `pnpm test`：940 passed，1 failed；失败项为计划 35 测试仍要求旧人物弹窗源码 token。
- `docker compose config --quiet`：PASS。
- `.venv/bin/python scripts/package_plugin.py`：PASS。

## 独立剩余风险

计划 35 的 TTS 密钥引导、产品运行门禁和迁移测试均把数据库版本写死为“恰好 `20260829_0032`”。计划 36 的合法后续迁移使 TTS 产品状态报告 `TTS_DATABASE_SCHEMA_OUTDATED`；sidecar、技术运行时、模型指纹和既有密钥环仍正常。计划 35 必须独立把该判断改成祖先链/最低所需迁移语义，并更新其旧人物弹窗测试后，才能恢复 TTS 产品 PASS。
