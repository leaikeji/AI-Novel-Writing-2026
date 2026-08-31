# VC43-FE-STUDIO — 工作台交互接线

状态：**PASS**

日期：2026-08-31（Asia/Shanghai）

- 无分卷时“新建章节”disabled，tooltip 与空态均提示“请先创建分卷”，且不发起章节草稿请求。
- 新增卷和章节只输入可选名称，序号为只读自动预览；输入旧序号时立即规范化为语义名称。
- 名称可清空回纯 `第 N 卷／第 N 章`；大纲和设定的非空标题规则不变。
- 草稿失效重绑显示一次非阻断恢复提示，已填写数据保留；completed key 恢复原章节。
- 关键文件：`frontend/src/workbench-studio.ts`、`types.ts`、`styles.ts`、`vc43-studio-wizard.test.ts`。
- 真实浏览器已验证无卷禁建、序号预览，以及删除原卷后同草稿重绑和内容保留。
