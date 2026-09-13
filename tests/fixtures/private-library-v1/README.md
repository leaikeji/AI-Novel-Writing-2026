# Plan 74 private-library fixtures

本目录只包含为计划 74 编写的项目合成材料，不含用户小说正文、外部小说原文、榜单文本或真实研究材料。所有文件的统一来源与许可标识为 `synthetic-project-fixture`。

## 文件

- `matching-cases.json`：确定性词项匹配、Markdown 可见文本和 UTF-16 坐标预期。
- `lifecycle-cases.json`：版本固定、本书隔离、检查过期和选区来源预期。
- `maintenance-cases.json`：AI 助手维护的直接命令、咨询、歧义、注入、失败和撤销场景。
- `performance-spec.json`：1000 条规则、10000 个可见字符性能语料的冻结规格。
- `generate_performance_fixture.py`：不写磁盘的确定性生成器；标准输出为完整 JSON fixture。
- `validate_fixtures.py`：解析 JSON、核对清单哈希、运行匹配预期和性能语料完整性。
- `manifest.json`：机器可读清单、权利边界和内容哈希。

从仓库根验证：

```bash
.venv/bin/python tests/fixtures/private-library-v1/validate_fixtures.py
```

这些 fixture 是后续 RULES、STORE 和 MAINTAIN 测试的输入，不是正式环境数据，也不授权模型调用、数据库写入或自动采用任何规则。
