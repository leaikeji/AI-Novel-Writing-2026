# T0-I 固定语料与验收工具交付记录

状态：**工作包 T0-I 候选完成；fixture、JSON 契约和标准库工具已通过原 Owner Python 3.12 假数据自测及主代理 Python 3.11.16 兼容复验。未运行真实 TTS，未完成真实人工听感；3/5/8/12 秒仍只是 placeholder/blocked。**

## 1. 基线与 Owner

- 基线 commit：`9b5be4a`
- Owner：Codex 子代理 `/root/tts_t0i_fixture_tooling`
- 开始时间：`2026-08-26 01:30:08 +0800`
- 结束时间：`2026-08-26 01:51:57 +0800`
- 工作区：开始时非洁净；所有范围外改动均视为用户或其他工作包资产并保持不动。

开始时 `git status --short`：

```text
 M backend/creative_api.py
 M backend/creative_services.py
 M backend/selection_edit_diff.py
 M design-qa.md
 M docs/开发文档/18-MOSS-TTS-Nano多角色智能朗读产品与技术设计.md
 M docs/开发文档/21-选区AI中央统一Diff审阅施工计划.md
 M docs/开发文档/README.md
 M frontend/src/selection-edit-review-surface.test.ts
 M frontend/src/selection-edit-review-surface.ts
 M frontend/src/styles.ts
 M skills/prose-writing/SKILL.md
 M skills/style-review/SKILL.md
 M tests/test_api_model_orchestration.py
 M tests/test_selection_edit_diff.py
 M tests/test_skill_contract.py
?? docs/开发文档/23-小说拆解驱动的通用与分类Skill架构计划.md
?? docs/开发文档/证据/关系网P0优化-2026-08-25/pre-relationship-cleanup.dump
?? docs/开发文档/证据/助手计划V2验证-2026-08-25/pre-a3a4-install.dump
?? docs/开发文档/证据/选区AI中央统一Diff审阅-2026-08-25/UD5-CONTEXT-AUDIT/
?? docs/开发文档/证据/选区AI中央统一Diff审阅-2026-08-25/UD5/
```

施工期间共享代理新增了其他 `prototypes/`、TTS 证据和脚本目录内容；本 Owner 未读取为输入、未修改，也未执行 Git 暂存、提交或推送。

## 2. 冻结输入与范围

冻结输入：专项文档的 T0-I 行、`moss-tts-benchmark-manifest/1.0`、`moss-tts-authorized-texts/1.0`、`moss-tts-benchmark-result/1.0`、`moss-tts-audio-inspection/1.0` 与 `moss-tts-benchmark-summary/1.0`。

实际新增文件：

- `scripts/tts/inspect_audio.py`
- `scripts/tts/render_benchmark_report.py`
- `tests/fixtures/narration/benchmark_manifest.json`
- `tests/fixtures/narration/authorized-texts.json`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T0-I/README.md`
- `docs/开发文档/证据/MOSS-TTS-Nano施工/T0-I/tooling-contract.md`

没有实现或运行真实 TTS、下载模型、创建参考音频、修改依赖/lock、业务代码、迁移、专项主文档或共享入口。

## 3. 交付结果

- 授权台账含 26 条本项目新编短句；每条均登记作者、来源、项目内测试许可、用途和精确 UTF-8 SHA-256。
- 基准清单含 27 个 case、29 个 coverage 标签、4 个参考时长占位，覆盖旁白、多类人物/对白、文本边界、独立句段及失败/取消/崩溃恢复。
- 3/5/8/12 秒参考项没有音频文件或伪造 hash，只能在获得另行授权前报告 `blocked`。
- 单次结果契约记录硬件/系统/Python、模型 revision/artifact hash、执行后端、参数、输入 hash、首包、RTF、峰值内存、命令/退出码、取消/失败/崩溃、最终/ready 片段输出 hash、WAV 技术指标和人工听检状态。
- WAV 工具只读支持 8/16/24/32-bit 无压缩 PCM WAV；汇总工具严格拒绝未知/缺字段 schema，并生成 Markdown 或 JSON 摘要。
- `tooling-contract.md` 提供人工听感与恢复证据模板、隐私边界、状态枚举、退出码和四个后续基准工作包的接线规则。

## 4. 运行环境

```text
硬件：Apple M4，17179869184 bytes（16 GiB）
系统：macOS 26.5.2 (Build 25F84)，Darwin arm64 25.5.0
项目解释器：Python 3.12.13
依赖：两个工具只使用 Python 标准库
```

原 Owner 执行时没有可直接调用的裸 `python3.11`。T0-A 随后建立 CPython 3.11.16 隔离解释器，主代理已用该解释器复跑 CLI、JSON、`py_compile`、WAV 正/负路径和严格报告器；见第 5 节补充记录。

## 5. 命令、原始退出码与计数

| 验证 | 原始退出码 | 通过 | 失败 | 跳过 | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| `.venv/bin/python scripts/tts/inspect_audio.py --help` | 0 | 1 | 0 | 0 | CLI 参数完整 |
| `.venv/bin/python scripts/tts/render_benchmark_report.py --help` | 0 | 1 | 0 | 0 | CLI 参数完整 |
| `.venv/bin/python -m json.tool tests/fixtures/narration/authorized-texts.json` | 0 | 1 | 0 | 0 | JSON 有效 |
| `.venv/bin/python -m json.tool tests/fixtures/narration/benchmark_manifest.json` | 0 | 1 | 0 | 0 | JSON 有效 |
| 授权文本/manifest 内联契约检查 | 0 | 26 texts / 27 cases / 29 coverage / 4 refs | 0 | 0 | ID、逐文本 hash、组合 hash、coverage、引用和占位策略一致 |
| 临时目录 WAV/报告端到端自测 | 0 | 5 组断言 | 0 | 0 | 源 hash 不变；8/16/24/32-bit；12000 frames/0.25s；报告 1 run/1 case；RTF 0.5 |
| `inspect_audio.py` 输入/输出同路径拒绝 | 2（预期） | 1 | 0 | 0 | 稳定错误且源 hash 不变 |
| 坏结果 schema 拒绝 | 2（预期） | 1 | 0 | 0 | stderr 为显式 `schema_error` JSON |
| `PYTHONPYCACHEPREFIX=<临时目录> .venv/bin/python -m py_compile ...` | 0 | 2 modules | 0 | 0 | 语法通过 |
| `git diff --check -- <6 个所辖文件>` | 0 | 1 | 0 | 0 | 所辖文件没有已跟踪 whitespace error；因文件均为新增，另做 no-index 检查 |
| 逐文件 `git diff --no-index --check /dev/null <file>` | 每项 1（新增差异，预期） | 6 files | 0 | 0 | 六项 stderr/stdout 均为空，即没有 whitespace error |
| 真实 TTS 与真人听检 | 未执行 | 0 | 0 | 1 类 | 明确超出 T0-I；由 T0-C/T0-D/T4-K 持锁执行 |
| prototype CPython 3.11.16：两个 `--help`、两份 `json.tool`、`py_compile` | 0 | 6 | 0 | 0 | 主代理兼容复验通过 |
| prototype CPython 3.11.16：临时 48 kHz WAV 检查、同路径拒绝、现有真实 metrics 严格汇总 | 0 / 2（预期）/ 0 | 3 | 0 | 0 | 12,000 frames / 0.25 s；源 hash 不变；summary 1 run / 1 case |

临时自测只生成半静音、半 440 Hz 正弦的无版权 WAV，并由 `TemporaryDirectory` 自动移除；没有音频进入仓库。核心原始输出：

```text
inspect_selftest_exit=0 source_unchanged=true widths=8/16/24/32-bit
frames=12000 duration=0.25 silent_ratio=0.5025 peak=0.5
overwrite_refusal_exit=2 source_unchanged=true
report_selftest_exit=0 run_count=1 case_count=1 rtf_median=0.5
invalid_schema_exit=2 explicit_schema_error=true
temporary_artifacts_removed=true
```

## 6. 产物 SHA-256

```text
ced9c955320e5e86cd11d617f46a4c82643d0d4fc3de49fa22781405bf30fdf8  scripts/tts/inspect_audio.py
aea2dabfcff0af1300bd49c6200f60c72f30c194dfbff0fa8ed56347987974a9  scripts/tts/render_benchmark_report.py
6750b722ad411839e369c617a9245c9578335d05b0c6117bcedfec3cfd6bbe35  tests/fixtures/narration/benchmark_manifest.json
434de78a9aca59ef5e1409b12ae39157b51e855e69503587fb4845502374c598  tests/fixtures/narration/authorized-texts.json
cde926888502ea41da960c7b750e2edf2718bd205be2b53b122945e59aeea82a  docs/开发文档/证据/MOSS-TTS-Nano施工/T0-I/tooling-contract.md
```

本 README 不内嵌自身 hash，避免自引用导致内容与 hash 永远变化；主代理接收时可从工作树直接计算。

## 7. 人工验收、未验证与风险

已人工复核：

- fixture 没有用户小说正文或外部小说摘录；所有文本均标为本项目新编测试语料。
- 参考音频全部为显式空占位，清单禁止自动创建、下载或提交替代品。
- 证据输出只允许文件名/hash/指标，不记录完整媒体路径、音频、模型权重或凭证 URL。

未验证：

- 真实 Nano/VoiceGenerator 输出、48 kHz 立体声实际表现、首包、RTF 与峰值内存；
- 真实 3/5/8/12 秒已授权参考音频；
- 人工听感、漏字/重复/音色漂移/停顿/接缝；
- Python 3.11 工具兼容已复验；真实模型/人工听感仍分别由 T0-B/C/D/T4-K 负责；
- 压缩 WAV（按契约主动拒绝，不属于本工具支持面）。

主要风险：未来基准脚本若绕过 hash 复核、把私人路径或音频写入证据、把 `blocked/skipped/pending` 汇总成通过，会破坏可复核性。报告器会拒绝 schema 漂移，但不能替代 T0-GATE 对真实输出和人工记录的检查。

## 8. 回退与主代理接线

本工作包只新增源码、fixture 和文档，没有数据库、模型、媒体或运行态副作用。拒绝候选时精确移除本节列出的 6 个新增文件即可；不要触碰共享目录中的其他工作包文件。

主代理接线步骤：

1. 核对本 Owner 只改上述 6 个文件，并重算 hash。
2. 让 T0-B、T0-C、T0-D 与 T4-K 消费 `benchmark_manifest.json`，启动前复核授权台账的逐文本与组合 hash。
3. 要求四个基准输出 `moss-tts-benchmark-result/1.0`；取消/崩溃场景还要填写 `ready_segment_sha256[]` 和复用计数。
4. 用报告器汇总自动指标，把 `tooling-contract.md` 的听感/恢复模板复制到各自证据目录；未实际听检不得填 `pass`。
5. T0-GATE 只能把本交付判为“工具就绪”，不能据此宣称模型、音色、播放器或质量已通过。
