# T0-I 基准工具与证据契约

状态：**T0-I 候选冻结；只定义 fixture、指标与证据格式，不代表真实 TTS、参考克隆或人工听感已经通过。**

契约版本：

- 基准清单：`moss-tts-benchmark-manifest/1.0`
- 授权文本：`moss-tts-authorized-texts/1.0`
- 单次结果：`moss-tts-benchmark-result/1.0`
- WAV 检查：`moss-tts-audio-inspection/1.0`
- 汇总结果：`moss-tts-benchmark-summary/1.0`

本契约供 T0-B、T0-C、T0-D 与 T4-K 共用。变更字段语义、枚举或哈希规则时必须提升相应 schema 版本；消费者不得靠猜测兼容未知版本。

## 1. 冻结输入

权威输入只有：

- `tests/fixtures/narration/authorized-texts.json`：保存 26 条项目自有原创短句；每条都有 `author`、`source`、`license`、`purpose` 与 `sha256`。
- `tests/fixtures/narration/benchmark_manifest.json`：只按 `text_id + sha256` 引用语料，列出覆盖面、场景、参考音频占位和预期终态。

输入哈希规则：

1. 从 JSON 解码得到字符串后，不做 NFC/NFD、空白或换行归一化。
2. 单文本 `combined_sha256` 等于该字符串 UTF-8 字节的 SHA-256。
3. 多个独立句段按清单顺序，以精确分隔符 `\n<SEGMENT>\n` 连接，再计算 UTF-8 SHA-256。
4. 执行者必须重新计算授权台账和清单中的哈希；不匹配时以 `blocked` 结束，不得自动改写 fixture。

3、5、8、12 秒参考项只是元数据占位：`asset_path` 与 `sha256` 均为 `null`，`asset_state=placeholder_only`。没有另行取得并登记授权音频时，对应用例只能记录 `blocked`；不得伪造、推断、下载或提交替代音频。

## 2. 基准清单覆盖面

`required_coverage` 是门禁清单，所有值都必须至少被一个 case 的 `covers` 引用。当前覆盖：旁白、明确说话人、双人/多人、省略主语、内心独白、匿名青年/中年/老人/儿童、群体、Markdown、emoji、变体选择符、组合字符、嵌套引号、特殊标点、多音字、人名与年代、中英混合、长句、3/5/8/12 秒参考占位、独立句段，以及失败、取消和崩溃恢复。

恢复用例只定义故障注入时机和可复核断言，不授权操作正式任务、数据库或媒体：

| Case | 注入 | 预期终态 | 必须证明 |
| --- | --- | --- | --- |
| `injected-adapter-failure` | 首个片段前适配器报错 | `failed` | 错误脱敏、无输出音频声明、源文本不变 |
| `cancel-after-first-ready` | 1 个片段 ready 后取消 | `cancelled` | 取消获确认、未开始片段不运行、合法 ready 结果不被删除 |
| `crash-and-resume` | 1 个片段 ready 后进程崩溃并重启 | `passed` | 至少复用 1 个 ready 片段、不得重复合成、最终 hash 完整 |

## 3. 单次结果 JSON

每次命令只写一个 `moss-tts-benchmark-result/1.0` 根对象：

```json
{
  "schema_version": "moss-tts-benchmark-result/1.0",
  "run": {
    "run_id": "T0-B-20260826T020000+0800",
    "benchmark_id": "nano-topology",
    "work_package_id": "T0-B",
    "status": "passed",
    "started_at": "2026-08-26T02:00:00+08:00",
    "finished_at": "2026-08-26T02:00:03+08:00",
    "environment": {
      "hardware": "Apple M4, 16 GB",
      "os_name": "macOS",
      "os_version": "26.5.2",
      "architecture": "arm64",
      "python_version": "3.12.13",
      "physical_memory_bytes": 17179869184
    },
    "model": {
      "name": "example-only",
      "revision": "fixture-only",
      "revision_sha256": null,
      "revision_hash_status": "not_applicable",
      "execution_backend": "fake",
      "artifacts": [
        {
          "name": "fake-adapter",
          "revision": "fixture-only",
          "sha256": null,
          "hash_status": "not_applicable",
          "source": "repository test fixture"
        }
      ]
    },
    "parameters": {},
    "command": {"argv": ["python", "benchmark.py"], "exit_code": 0},
    "privacy": {
      "fixture_only": true,
      "contains_user_text": false,
      "contains_private_reference_audio": false,
      "evidence_contains_audio": false
    }
  },
  "cases": []
}
```

示例中的名称、时间和环境不是实测值，不能复制成真实报告。`cases` 在有效结果中至少有一项。

### 3.1 Run 字段

| 字段 | 规则 |
| --- | --- |
| `run_id` | 单次运行唯一且稳定；同一重试使用新 ID |
| `benchmark_id` / `work_package_id` | 明确 T0-B、T0-C、T0-D 或 T4-K 的基准及归属 |
| `status` | 只能使用冻结的 run 枚举 |
| `started_at` / `finished_at` | ISO 8601；运行中 `finished_at` 可为 `null` |
| `environment` | 必填硬件、系统、架构、Python 和物理内存；不得只写“本机” |
| `model` | 必填模型名、revision、执行后端与所有参与 artifact；真实 artifact 必须记录经核验的小写 SHA-256 |
| `parameters` | 记录所有影响生成、流式、量化、线程、参考音频和后处理的参数；不得依赖隐式默认值 |
| `command` | 原样 argv 数组和原始退出码；终态运行不得省略退出码 |
| `privacy` | 本 fixture 契约下四个布尔值必须依次为 `true/false/false/false` |

Run 状态枚举：

| 状态 | 语义 |
| --- | --- |
| `pending` | 已登记但未开始；不可作为门禁证据 |
| `running` | 正在执行；不可作为门禁证据 |
| `passed` | 全部应执行用例完成且满足自动门槛；听感是否完成仍由 case 单独表达 |
| `partial` | 有通过也有未通过/未完成项，必须逐 case 解释 |
| `failed` | 运行失败或门槛不通过 |
| `cancelled` | 收到并确认取消；不得伪装成失败 |
| `crashed` | 进程异常退出且本次未恢复完成 |
| `skipped` | 有明确外部理由而未执行，不计通过 |
| `blocked` | 缺少授权、依赖、能力或前置门禁，不计通过 |

### 3.2 Case 字段

每个 case 必须包含：

- `case_id` 与冻结清单一一对应；同一结果中不得重复。
- `status`：`passed|failed|cancelled|crashed|skipped|blocked`。
- `input`：`text_ids[]`、对应 `text_sha256[]`、`combined_sha256`、可空 `reference_profile_id` 与 `reference_sha256`。
- `timing`：可空的 `first_packet_ms`、`synthesis_wall_ms`、`audio_duration_seconds`、`rtf`。RTF 定义为 `synthesis_wall_ms / 1000 / audio_duration_seconds`；无合法音频时为 `null`。
- `resources`：可空 `peak_rss_bytes` 与 `peak_accelerator_bytes`。峰值必须来自本次进程/后端监测，不得写设备总内存。
- `output`：始终包含 `ready_segment_sha256[]`。只有 `passed` 可带最终 `audio_sha256` 与 `audio_inspection`，二者 hash 必须一致；其他状态的最终两项都为 `null`，但取消/失败前已经合法 ready 的片段 hash 仍需保留在数组中。
- `control`：`cancel_requested`、`cancel_acknowledged`、`failure_injected`、`crash_recovered` 与 `ready_segments_reused`。
- `error`：通过时为 `null`；`failed|cancelled|crashed|blocked` 时必须含 `category`、`code`、`message_redacted`。
- `listening`：人工听检状态、审阅人代号、结论、七类缺陷、脱敏备注与跳过原因。

失败信息禁止包含用户正文、私人音频路径、token、密钥、环境变量值或完整模型下载鉴权信息。

### 3.3 模型 hash

`revision_hash_status` 与 artifact 的 `hash_status` 只能为：

- `verified`：值必须为 64 位小写 SHA-256；
- `unavailable`：值必须为 `null`，同时在参数/失败记录中写明不能核验的原因，不能宣称可复现；
- `not_applicable`：只允许假适配器或不产生模型资产的测试，值为 `null`。

真实 Nano、Tokenizer、ONNX、VoiceGenerator 或后处理二进制不得使用 `not_applicable`。artifact 的 `source` 只保存公开来源或脱敏标识，不保存带凭证 URL。

## 4. WAV 技术检查

`scripts/tts/inspect_audio.py` 只读检查无压缩 PCM WAV，不转码、不修复、不改源文件，支持 8/16/24/32-bit、小端、单声道或多声道。默认静音阈值是 `-50 dBFS`，一个 frame 的所有声道都不高于阈值才计为静音。

输出 `moss-tts-audio-inspection/1.0`，至少记录：文件名（不含绝对路径）、文件大小、SHA-256、采样率、声道、sample width、frame/sample 数、时长、峰值、RMS、DC offset、静音 frame 比例和削波 sample 比例。空音频的比例为 `0`，峰值/RMS dBFS 为 `null`。

技术检查只能证明容器和信号指标，不能证明无漏字、重复、错读、音色漂移或接缝问题。每个通过的真实生成 case 仍必须人工听检。

CLI：

```bash
.venv/bin/python scripts/tts/inspect_audio.py --help
.venv/bin/python scripts/tts/inspect_audio.py generated.wav --output inspection.json
```

退出码：`0` 成功，`2` 输入/格式/读取错误。`--output` 与输入相同会被拒绝。

## 5. 汇总报告

`scripts/tts/render_benchmark_report.py` 接受一个或多个结果 JSON，先按本契约严格校验，再汇总 run/case 状态、首包、RTF、峰值内存、取消/失败/崩溃复用、ready 片段 hash 数、听检状态与缺陷。中位数和 P95 使用排序后的 nearest-rank；无样本输出 `null`/破折号，不把缺失值当 0。

```bash
.venv/bin/python scripts/tts/render_benchmark_report.py --help
.venv/bin/python scripts/tts/render_benchmark_report.py metrics.json \
  --markdown-output report.md \
  --json-output summary.json
```

默认无输出路径时把 Markdown 写到 stdout；`--stdout-format json` 可输出 JSON。退出码：`0` 成功，`2` schema/JSON 错误，`3` 文件或输出路径错误。schema 错误以稳定 JSON 写到 stderr 并逐字段列出；脚本不会静默跳过坏文件。

## 6. 人工听感证据模板

每个 T0-C/T0-D/T4-K 报告复制以下表格。审阅者必须实际听完目标 case；未听时用 `pending` 或 `skipped_with_reason`，不得填 `pass`。

```markdown
## 人工听感记录

- Run ID：
- Case ID：
- 输出 SHA-256：
- 审阅人代号：
- 时间与监听设备：
- 对照文本：只写 fixture `text_id`，不要复制用户正文
- 听检状态：pending / completed / skipped_with_reason
- 结论：pass / fail / inconclusive / not_reviewed

| 项目 | 是 | 否 | 无法判断 | 说明（脱敏） |
| --- | --- | --- | --- | --- |
| 漏字 |  |  |  |  |
| 重复 |  |  |  |  |
| 音色漂移 |  |  |  |  |
| 异常停顿 |  |  |  |  |
| 独立句段接缝异常 |  |  |  |  |
| 爆音或噪声 |  |  |  |  |
| 响度不一致 |  |  |  |  |

- 与旁白/其他人物的可区分性：
- 跨句段稳定性：
- 跳过原因（如有）：
```

## 7. 失败、取消与崩溃恢复证据模板

```markdown
## 恢复验证

- Run ID / Case ID：
- 注入类型与精确时机：
- 注入前 ready segment IDs 与 hashes：
- 进程/任务原始状态：
- 取消是否请求/确认：
- 重启或重试次数：
- 恢复后复用 segment IDs 与 hashes：
- 是否发现重复生成：
- 最终状态与退出码：
- 错误 category/code（已脱敏）：
- 源 fixture hash 是否保持：
- 是否产生未登记音频、临时文件或证据泄漏：
- 清理/回退动作：
- 结论：pass / fail / blocked
```

恢复通过不能只看最终可播放：必须以 segment hash、调用计数或假适配器审计证明合法 ready 片段被复用且未重复合成。取消不得删除已完成合法输出；失败、取消和崩溃都不得改变正文、revision 或正式媒体引用。

## 8. 接线约束

后续四个基准脚本必须：

1. 只接受专项文档冻结的 `--fixture-manifest` 和 `--output-dir` CLI；T4-K 另有 `--duration-minutes`。
2. 加载授权台账并复核 ID、逐文本 hash、组合 hash、coverage 和参考占位，发现漂移即阻断。
3. 把真实音频写到受控外部媒体目录；证据目录只写脱敏 JSON、Markdown、日志摘要和截图。
4. 每次运行生成一个单次结果 JSON；不得在不同机器或重试之间覆盖原始 run。
5. 使用本工具生成汇总，但人工听感由真实审阅人填写，工具不得推断 `pass`。
6. T0-B/C/D 使用 prototype 的隔离 Python；本工具本身只依赖 Python 3.11 标准库，可由项目解释器执行。

回退：任何消费者尚未支持 `/1.0` 时应停止接线并保留原始结果；不得删除字段、把未知状态映射为 `passed`，或继续使用旧 fixture 生成不可比较报告。
