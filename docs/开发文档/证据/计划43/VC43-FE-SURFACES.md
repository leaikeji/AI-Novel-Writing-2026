# VC43-FE-SURFACES — 标题投影与非 Studio 表面

状态：**PASS**

日期：2026-08-31（Asia/Shanghai）

- presenter 与 chapter tree 统一使用规范树序，不再按原始全局 `position` 自行计号。
- 旧 `第 N 卷／章` 只在明确分隔边界剔除；“第一章里的秘密”和“第三卷轴之谜”保持原样。
- 列表、章节树、编辑器、助手上下文、选择器、确认／删除文案和朗读目标使用派生展示标题。
- 关键文件：`frontend/src/presenters.ts`、`chapter-tree.ts`、`chapter-workflow.ts`、`workbench-v2.ts` 及对应测试。
- 定向 Vitest、全量 Vitest、typecheck 与 build 通过。
