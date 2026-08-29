# ADV-CONTRACT-GATE：Nano 高级解码参数契约证据

状态：**2026-08-29 后端候选契约与聚焦自动化通过；产品入口保持隐藏。PostgreSQL worker 活测受既有测试夹具与当前数据库 trigger 漂移阻断，尚未达到发布门。**

工作包：`MNX-ADV-SPIKE`

## 1. 冻结结论

- 历史 v1 请求继续按隐式官方默认解释，不回填、不改写历史 Voice Version、Edition 或缓存身份。
- 新参数对象固定为 `moss-nano-decode-parameters/2`；只有 `sample_mode=full` 可携带，`fixed/greedy` 携带该对象直接拒绝。官方预设的默认直用路径仍为 `fixed`，不受高级实验参数影响。
- 浮点参数在 wire contract 中使用千分整数，避免跨 Python/JSON 的浮点规范化差异：temperature、top-p 和 repetition penalty 分别以 `*_milli` 传输。
- 新对象完整进入 Voice Version 参数指纹、Sidecar canonical JSON/HMAC、ModelRun 参数摘要以及 render/cache 身份；未知字段和越界值 fail closed。
- Sidecar 仅在一次 `full` 合成调用范围内覆盖 manifest 的 `generation_defaults`，并在 `finally` 中恢复。未传新对象的旧请求不改变运行时默认。

## 2. 参数与边界

| 参数 | wire 字段 | 边界 |
| --- | --- | --- |
| text temperature | `text_temperature_milli` | `100..2000` |
| text top-p | `text_top_p_milli` | `1..1000` |
| text top-k | `text_top_k` | `1..100` |
| audio temperature | `audio_temperature_milli` | `100..2000` |
| audio top-p | `audio_top_p_milli` | `1..1000` |
| audio top-k | `audio_top_k` | `1..100` |
| audio repetition penalty | `audio_repetition_penalty_milli` | `1000..2000` |

这些边界是本项目的窄安全约束，不宣称等于官方全部理论输入范围。`max_new_frames`、CPU threads、execution provider、输出格式和播放器倍速/音量不属于音色调教对象。

## 3. 源码证据

- `backend/narration/contracts.py`：`NanoDecodeParametersV2`、bounds、wire 双读和 `SynthesisRequest` 的 full-only 约束。
- `backend/narration/runtime.py`、`backend/narration/sidecar_server.py`：canonical 请求、HMAC 覆盖、exact-shape 校验、运行时参数应用与恢复。
- `backend/narration/voice_product.py`、`backend/narration/worker.py`：不可变版本参数、preview/ModelRun/Sidecar/render/cache 指纹传播。
- 官方固定源码 `cc7bdf19c7639c0870dab22045a33b442760f6be` 的 `ort_cpu_runtime.py` 已核实 full Python sampling 路径实际读取上述七项；fixed sampler graph 不接受逐项运行时覆盖，因此禁止在 fixed 模式展示这些旋钮。

## 4. 实际验证

```text
.venv/bin/python -m pytest -q \
  tests/narration/test_voice_product.py \
  tests/narration/test_contracts.py \
  tests/narration/test_runtime.py \
  tests/narration/test_sidecar_server.py
PASS（约 221 项）
```

隔离 PostgreSQL 18 已迁移到候选 head `0031` 后运行 worker ModelRun 测试；测试在进入本次高级参数断言前，被既有 `_seed_pending_publication` 夹具触发现存数据库规则 `queued narration request requires a proven review pointer` 阻断。未为追求绿灯而放宽数据库规则，也未污染长期数据库。

## 5. 门禁裁决

`ADV-CONTRACT-CANDIDATE=PASS`；`ADV-CONTRACT-GATE=HOLD`。在以下条件全部完成前，高级参数页面保持隐藏：

1. 修复 PostgreSQL worker 测试夹具，使其按当前 review pointer 规则建数，并验证 ModelRun digest；
2. 提供创建新不可变实验 Voice Version 的产品 API，不允许原地修改官方版本；
3. 完成 full 与历史 fixed 的真实合成、缓存隔离和质量回归；
4. 前端仅在 capability 放行后展示完整且真实生效的控件。
