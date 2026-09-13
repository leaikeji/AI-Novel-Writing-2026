# 计划 74：L74-CASES 合成样本记录

- 日期：2026-09-13
- 工作包：`L74-CASES`
- 结论：`PASS`（样本与确定预期已建立；不代表正式环境或文学效果验收通过）
- 来源与许可：全部为项目自写式合成文本，统一标识 `synthetic-project-fixture`
- 明确排除：用户小说正文、外部小说原文、真实研究材料、网络采集、模型调用、数据库写入、正式环境操作

## 已交付

样本入口为 `tests/fixtures/private-library-v1/manifest.json`，包含内容文件 SHA-256。当前覆盖：

- 10 个确定性匹配场景：中文精确短语、ASCII 完整词与大小写、Markdown 标记、链接标签与纯链接排除、emoji 前 UTF-16 半开区间、重叠规则、慎用滚动窗口、推荐词及停用词允许表达、变体去重。
- 10 个生命周期场景：通用 v3 与本书固定 v1、甲书局部副本、乙书隔离、正文／规则版本漂移、已采用幂等回放、未同步选区来源、切书票据失效、可撤销与后续编辑冲突。
- 28 个 AI 维护场景：直接命令、咨询、含糊偏好、同名目标、缺失选区、跨书范围、材料内指令和伪造授权、工具失败、CAS 冲突、结果未知、撤销及撤销冲突。
- 确定性性能语料：1000 条结构化规则与 10000 个可见字符，固定 5 个预期命中；生成器不读取外部输入、不使用随机数、不写磁盘。规格另要求正式性能记录执行 3 次预热和 30 次测量，并记录机器、Python、耗时与峰值内存；fixture 校验不把当前机器一次耗时冒充 p95。

## 实际验证

从仓库根执行：

```text
.venv/bin/python tests/fixtures/private-library-v1/validate_fixtures.py
```

退出码 `0`，输出：

```json
{"json_files": 5, "lifecycle_cases": 10, "maintenance_cases": 28, "matching_cases": 10, "performance_characters": 10000, "performance_rules": 1000, "source_license": "synthetic-project-fixture", "status": "PASS"}
```

校验器已实际完成：全部 JSON 可解析、统一合成来源边界、文件清单 SHA-256、匹配器精确命中与 UTF-16 坐标、未同步选区文本 SHA-256、维护场景数量与类别、性能生成器规模及预期命中。

## 后续消费约定

- `L74-RULES` 可将 `matching-cases.json` 中的 `rules` 直接转换为 `LexiconRuleSource`，将 `expected.hits` 作为稳定断言；性能测试可导入 `build_fixture()`。
- `L74-STORE` 可消费 `lifecycle-cases.json` 的版本、范围、绑定和幂等预期；标题只用于作者可读说明，不作为资产身份。
- `L74-MAINTAIN` 与管理 Skill 验收可消费 `maintenance-cases.json` 的 `tool_sequence`、`result`、范围和负向写入断言。
- 这些确定预期可以阻止明显回归，但不能替代正式 QwenPaw 中的真实助手工具调用、桌面操作或作者文学质量判断。正式P1真实链已另行完成，见[正式发布记录](../formal/formal-release-20260913.md)。
