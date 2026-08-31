# VC43-BE-CONSUMERS — 运行标题与语义索引适配

状态：**PASS**

日期：2026-08-31（Asia/Shanghai）

## 结果

- Context V4、助手上下文、章节情报／关系快照和人物工作区均使用当前规范树的 `第 N 章`展示标题；空语义名称不会进入强制非空契约。
- Context 片段后缀在 240 字符限制内预留，完整保留 ordinal 前缀。
- Embedding 文本不含位置派生序号；空名称只在索引内部使用稳定标签“章节正文”，作者可见 snippet 会剔除 renderer 标题头。
- 纯重排使用 metadata-only reprojection，复用原 source／chunk／vector，不启动远程 embedding batch。
- 章节创建、改名、删除、移动与重排在权威事务提交后请求 active index 刷新；刷新失败不回滚作者写入，而是把索引标记为 `outdated`。

## 关键文件

`backend/context_v4_loader.py`、`backend/assistant_workspace_service.py`、`backend/character_workspace/service.py`、`backend/embedding/api.py`、`indexing.py`、`local_lexical.py`、`worker.py`、`writing.py`。

## 验证

- `tests/embedding/`：152 项通过。
- Context、assistant、character 与索引定向回归：通过。
- 隔离 PostgreSQL `tests/test_character_profile_completion_integration.py`：6 项通过，无数据库跳过。
