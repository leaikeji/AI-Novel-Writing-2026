# UD1-BE 后端协议、Diff 与恢复证据

状态：2026-08-25 本地工作包验证通过；尚未进入 `UD1-G` 集成门禁，尚未提交 Git。

范围：只验证 `selection_edit` 的后端请求/结果契约、scope 与实体归属、Skill 映射、有效模型审计继承、幂等、失败记录、恢复筛选和确定性 Diff。没有修改迁移、QwenPaw 核心、Agent 模型或用户数据库。

## 自动化

```text
.venv/bin/python -m pytest tests/test_selection_edit_diff.py tests/test_model_runtime.py tests/test_domain_unit.py tests/test_api_model_orchestration.py
67 passed in 0.50s
```

覆盖点：

- 七个 operation 的固定 Skill 映射；`review -> style-review`，其余直接编辑操作 `-> prose-writing`。
- 模型原始 JSON 严格只含 `replacement_text/short_summary`；项目补齐 schema、selection、operation、字符数、warnings、Diff 和稳定 segment id。
- 输入快照双层校验、UTF-16 范围、选区 SHA-256、受控字段 ID、scope/实体归属和 custom 限权。
- `force_new=false` 复用同一 running/ready job；`force_new=true` 增加 attempt。
- 失败结果记录 actual Provider/模型与脱敏失败原因，字段和正式正文没有写入路径。
- `GET /creative-generations` 可用 `kind=selection_edit&selection_id=<uuid>` 对当前 novel/document scope 做恢复筛选。

## 性能

环境：Apple arm64、macOS 26.5.2、Python 3.12.13。原文与候选各 12,000 个 Python Unicode 字符，100 次独立构建并逐次验证双向重建。

```json
{"case":"bounded_fallback","runs":100,"original_chars":12000,"candidate_chars":12000,"segments":1,"p50_ms":1.181,"p95_ms":1.528,"max_ms":3.039,"threshold_ms":100}
{"case":"structured_changes","runs":100,"original_chars":12000,"candidate_chars":12000,"segments":41,"p50_ms":1.405,"p95_ms":1.506,"max_ms":1.786,"threshold_ms":100}
```

第一组长重复片段安全降级为一个整体 replacement hunk；第二组包含 20 处离散变化并形成 41 个 segment。两者都严格重建 base/candidate，分别覆盖有界降级与正常细粒度路径。

脱敏协议样本见同目录的 `success.json`、`idempotency.json` 和 `failure.json`。
