# VC43-BE-CORE — 后端领域与 API 收口

状态：**PASS**

日期：2026-08-31（Asia/Shanghai）

## 实现结论

- 新建 chapter 必须显式携带当前小说的有效 `volume_id`；缺失、已删除或跨书分卷在 Document／revision／working copy／chapter draft 写入前失败。
- `Volume.title` 和 chapter `Document.title` 只保存可选语义名称；旧序号仅在明确边界处剔除，卷号／章号按规范树实时派生。
- 章节草稿原分卷失效时，同一 `draft_key` 保留标题、期待、大纲和关联选择并原子重绑；完成时竞态返回 409 `chapter_draft_volume_stale`。
- 卷章位置写入在小说锁内串行化，同 key 首次草稿使用 PostgreSQL upsert 收敛；重排拒绝重复 UUID 和非规范树序。
- 全书导出使用一份 `REPEATABLE READ` 快照，Markdown、text 与 metadata 标题一致。
- 最后复查增加防御性读路径：历史异常的非本书 `volume_id` 不再让章节从树或导出中消失，只读降级到未分卷组，不改写存储。

## 关键文件

`backend/volume_chapter_titles.py`、`backend/services.py`、`backend/creative_services.py`、`backend/app.py`、`backend/creative_api.py`、`backend/schemas.py`、`backend/creative_schemas.py`，以及对应的 title/API/domain integration 测试。

## 验证

- `tests/test_volume_chapter_titles.py tests/test_volume_chapter_api_contract.py`：24 项通过。
- 隔离 PostgreSQL `tests/test_domain_integration.py`：38 项通过，无数据库跳过。
- 最后防御性补丁再跑 title/API 定向测试、`py_compile` 和 `git diff --check`：通过。
