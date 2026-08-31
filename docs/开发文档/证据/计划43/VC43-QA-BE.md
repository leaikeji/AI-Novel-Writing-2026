# VC43-QA-BE — 后端与隔离数据库验收

状态：**PASS**

日期：2026-08-31（Asia/Shanghai）

## 环境边界

- 使用一次性 PostgreSQL，宿主端口 `127.0.0.1:15439`，测试库 `ai_novel_world_2026_vc43_test`。
- Alembic 升级到 `20260830_0035`；不连接长期 `15432` 数据库，不读写真实小说。
- 验收后已删除精确命名的临时容器和卷。

## 实际结果

| 验证 | 结果 |
| --- | --- |
| title/API 定向 | 24 项通过 |
| `tests/test_domain_integration.py` | 38 项通过，数据库用例无 skip |
| `tests/test_character_profile_completion_integration.py` | 6 项通过，无 skip |
| `tests/embedding/` | 152 项通过 |
| manifest/QwenPaw/Skill 契约 | 127 项通过 |
| 全仓 Python | 收集 3571 项，进度到 100%、退出码 0，无失败；存在项目原有的环境门禁 skip |
| `py_compile` / `git diff --check` | 通过 |

全仓命令使用了双 `-q`，pytest 未输出可靠的精确 pass/skip 汇总；因此本记录只保留已实际观察的“3571 项已收集、100%、退出码 0”，不推断精确跳过数。
