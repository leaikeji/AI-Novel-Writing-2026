# VC43-RO-AUDIT — 卷章标题与创建入口只读审计

状态：**PASS，阻断调用点已全部分配。**

日期：2026-08-31（Asia/Shanghai）

审计快照聚合 SHA-256：`e588898402019fbf08b54779beb16df4b0112e1f7997dd478a3b71cca398f2fb`

## 阻断结论

- `backend/services.py`：通用 chapter 创建仍允许空卷；卷章 position 无小说级串行化；普通搜索、旧上下文、情报快照仍使用 raw title／全局 position。
- `backend/creative_services.py`：章节草稿缺卷会选首卷；同 key 首次创建有竞态；完成只锁草稿；卷章更新、重排、导出和关系／人物快照仍有 raw title／全局 position。
- `backend/context_v4_loader.py`、`assistant_workspace_service.py`、`character_workspace/service.py`：运行上下文直接消费 raw title，Context 片段后缀可能突破 240 字符。
- `backend/embedding/indexing.py`、`local_lexical.py`、`worker.py`、`writing.py`：标题进入索引文本，narrative position 仍按全局 position；纯重排缺少向量复用的 metadata-only 路径。
- `backend/embedding/api.py`：作者可见 snippet 会直接包含 renderer 标题头；空名称内部标签可能泄漏。V0.3 已把该文件和 `tests/embedding/test_api_local_fallback.py` 分配给 `VC43-BE-CONSUMERS`。
- `SemanticSearchHit` 没有 title 字段。G0 裁决为不改变公共契约：只清理作者可见 snippet；已有标题表面按 source entity 投影当前序号。
- `frontend/src/presenters.ts`：旧前缀没有词边界且空名称回写序号；`workbench-v2.ts`、`workbench-studio.ts`、`chapter-workflow.ts` 仍存在绕过、局部计数与 raw title 消费。

## 所有权补充

- `VC43-BE-CORE` 追加验收：`tests/test_creative_read_safety.py`、`tests/test_character_profile_services.py` 的情报、关系、人物快照标题与规范树反例。
- `VC43-BE-CONSUMERS` 追加允许修改：`backend/embedding/api.py`、`tests/embedding/test_api_local_fallback.py`。
- 未发现需要修改 QwenPaw 核心、迁移历史或真实数据库的调用点。

## 退出判断

- RO-AUDIT 完成后才允许启动源码写包。
- 新发现的源码文件仍须先由主代理补入计划所有权，不能由子代理自行扩大范围。
