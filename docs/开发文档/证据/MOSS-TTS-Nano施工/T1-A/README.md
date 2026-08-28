# T1-A Narration 公共契约与适配器抽象交付记录

状态：**T1-A 候选实现完成；固定 scope、taxonomy v1、adapter capabilities/health/model fingerprint、canonical fingerprint 和 fail-closed fake/disabled adapter 已通过 53/53 专项测试。独立红队发现的嵌套可变 model parameters 与非精确 capability 类型 P1 已由主代理在消费者落地前收紧并复验。本文不表示 Sidecar 生命周期、真实模型、数据库、API、媒体或任何产品入口已经实现；全部产品可见性保持 false。**

工作包：`T1-A`

Owner：`/root/tts_t0c_persistent_quality`

执行日期：2026-08-26（Asia/Shanghai）；证据收口时间 07:21 CST。

## 1. 基线与工作树边界

本工作包在主代理明确接收 `T1-DEP` 后启动。任务禁止 Git 操作，因此没有重新读取或改变 HEAD、暂存区、分支和远端；逻辑基线只使用下列固定输入。共享工作树既有修改全部视为其他 Owner/用户资产，本工作包仅写任务卡精确允许的 10 个路径。

| 冻结输入 | 状态 / SHA-256 |
| --- | --- |
| T0-GATE | `PASS_WITH_EXPLICIT_NO-GO_CAPABILITIES` |
| T1-DEP | `ACCEPT`（由主代理作为本工作包前置输入） |
| `T0-evidence-manifest.json` | `5a65e4d939b2ab39e26948964f0f0ada9aaaa8e8e8b5a7934e837ff7eac254e9` |
| `T0-H/gate-decisions.md`（2026-08-26 原始冻结快照；后加官方预设范围注释不重算旧 hash） | `2437be4e13e182aae554cb853f16afbc0b475d51848ce2d413eb4c3d9076e283` |
| `T0-H/contract-review.md` | `afed19c3cca22bed3de919caa2ec0219efc8e067648063751a0efe95d8e83a5e` |

未读取或修改 QwenPaw 上游、旧项目 Data、真实小说、私人音频、数据库、模型或密钥；未取得模型、依赖、数据库或浏览器锁。

## 2. 实际文件

| 文件 | 用途 | SHA-256 |
| --- | --- | --- |
| `backend/narration/__init__.py` | 经门禁允许的 49 个公共符号；导入无模型、Sidecar、DB 或注册副作用 | `263a5c01aca8675d201fedd37f0a645fd811e9b0f39d8141ad71790a448a02ef` |
| `backend/narration/contracts.py` | 固定 scope、taxonomy、能力/健康、请求/结果、actual hash 与模型指纹 DTO | `f5b3028a3dae3d3247110bb3cc8852b9116cfb2c11542c5ecd61df3a3f7efc1f` |
| `backend/narration/adapters.py` | 两个 ABC、Nano/VoiceDesign capability 常量、fake 与当前 VoiceGenerator disabled 实现 | `76ca0ebb5de1b80dbcb6597c5126ce18e634dea5add646fc6f067f435c697786` |
| `backend/narration/fingerprints.py` | 版本化 canonical JSON、scope/model/capability/Edition/render SHA-256 | `2a89f692d301ba55c2a7b5a2fcc90680c56dd9b9549d0153e5dd761e8e5492bb` |
| `tests/narration/test_contracts.py` | scope、全部 taxonomy code、unknown/version、hash、canonicalization、嵌套可变参数与 exact runtime type 负向测试 | `1b30b21da877d2cafdc151fbc220a272efac4d79633283563610be7e8dcf7eb3` |
| `tests/narration/test_adapters.py` | ABC、fake WAV/hash/cancel、capability 对照、VoiceGenerator disabled 测试 | `279991dac63a93ce145880c1298a85dca70620aba95770ef961ba887dff1859a` |
| `tests/fixtures/narration/review-taxonomy-v1.json` | 7 warning、11 blocker、7 workflow failure 与 unknown/approval 策略 | `a9ed5ab76f8d157ac132825edc0d0c973fb73e58d84d002ee97607850e1df975` |
| [contract-summary.json](./contract-summary.json) | scope/taxonomy/fingerprint/公共接口机器可读摘要 | `147efa7a2cbeff11dd72dbeddcdcb16678917db23340418d689214ba2bb9e8f8` |
| [capability-comparison.json](./capability-comparison.json) | Sidecar 目标、Nano fake、VoiceDesign NO-GO 与 fake 的四行对照 | `9e74e29a8a7f2cadeacafc574a988a8f38a6559005a784716018b95c725691f2` |

本 README 不内嵌自身 hash，避免自引用循环。

## 3. 冻结公共契约

### 3.1 Scope 与 taxonomy

- `NarrationRequestScope` 固定 `narration-scope/1`、owner `29cf94d9-a5c9-54ec-912c-5dfff8738c4c`、workspace `f0e2e632-bc99-52d2-9916-bb906aa4da6e`、`app_id=ai-novel-world-2026`、`is_local_only=true`；这是服务端隔离标签，不是认证凭据。非固定值由 `ensure_fixed_local()` 拒绝。
- `narration-review-taxonomy/1` 精确包含 7 warning、11 blocker、7 workflow failure。issue severity 由服务器常量决定；未知 issue/failure/version 一律 fail-closed，workflow failure 不能伪装成 issue 后参与零 blocker 审批。
- `B_VOICE_RIGHTS_UNAVAILABLE` 独立于 `B_VOICE_VERSION_UNAVAILABLE`，覆盖缺失、revoked、expired、review-blocked 权利事件。

### 3.2 Adapter 与健康

- `MossNanoTTSAdapter` 公共方法：`capabilities/health/model_fingerprint/warmup/synthesize/cancel`。
- `VoiceDesignAdapter` 公共方法：`capabilities/health/model_fingerprint/warmup/design_voice/cancel`。
- capability 与 health 分离：技术接口支持不等于当前健康，更不等于产品可见。`MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES` 仅供 T1-B 实现消费，仍为 `product_visible=false/production_ready=false`。
- `VOICE_DESIGN_NO_GO_CAPABILITIES` 全部执行能力 false；`DisabledVoiceDesignAdapter` 返回 `disabled/VOICE_GENERATOR_NO_GO` 并对调用 fail-closed。
- 两个 fake 都带 `is_test_double=true`，构造时禁止 `product_visible` 或 `production_ready`。Nano fake 只生成标准库构造的 48 kHz、双声道、16-bit 测试 WAV；不加载模型、不进入媒体或产品路径。

### 3.3 Fingerprint canonicalization

canonical envelope 固定为 `{"schema_version": <version>, "payload": <value>}`，UTF-8、Unicode NFC、key 排序、无空格 JSON 和 SHA-256。版本是 digest 输入；当前只接受 scope/model/capability/Edition/render 五个已列版本。未知版本、bytes、float、非字符串 key、NFC 后重复 key 和不支持类型全部拒绝；二进制必须先保存实际小写 SHA-256，浮点参数必须由调用方按版本化契约转为整数或定点值。

`ModelFingerprint` 冻结 adapter contract、model name/revision、artifact tree hash、runtime/version、execution backend、protocol、deployment topology 和不可变参数映射。`SynthesisResult`/`VoiceDesignResult` 对返回 bytes 重算 `actual_output_sha256`；seed 不被解释成预期内容哈希。

红队复核进一步证明 Python 类型注解本身不足以形成运行时边界：原候选允许把嵌套 list/dict 放入 `ModelFingerprint.parameters`，外部修改后会让同一 frozen 对象的 digest 漂移，也没有对 capability/health 的 bool/enum 做 exact type 校验。主代理已在 T1-B/T1-D 消费前改为只接受并复制 `str | int | bool | null` 标量参数，拒绝嵌套可变值，并对 capability boolean、enum、并发整数和 health status 做 fail-closed 运行时校验；相应正负测试已纳入 53 项结果。

## 4. 环境与真实命令结果

环境：Darwin 25.5.0 arm64；项目 `.venv` CPython 3.12.13、pytest 9.1.1。另用 T0 隔离 CPython 3.11.16 做只读 import/contract smoke，满足项目 `>=3.11,<3.14` 边界。

| 命令/检查 | 原始退出码 | 通过 | 失败 | 结果 |
| --- | ---: | ---: | ---: | --- |
| `.venv/bin/python -m pytest -q -ra tests/narration/test_contracts.py tests/narration/test_adapters.py` | 0 | 53 | 0 | 53/53 passed（含主代理红队 hardening 复验） |
| `.venv/bin/python -m json.tool tests/fixtures/narration/review-taxonomy-v1.json` | 0 | 1 | 0 | JSON 有效 |
| 临时 `PYTHONPYCACHEPREFIX` 下 `py_compile` 六个 Python 文件 | 0 | 6 | 0 | 语法通过，无仓库内 pycache |
| CPython 3.11.16 import/scope/fake visibility smoke | 0 | 3 assertions | 0 | Python 3.11 兼容 |
| capability JSON 与四个代码 capability 对象逐字段对账 | 0 | 4 | 0 | 4/4 一致 |

## 5. 未验证、风险与回退

未验证：真实 Linux Sidecar adapter、握手/认证/health/warmup、模型下载/加载、真实 bytes stream、取消/重启、实际模型 fingerprint、数据库约束、任务、媒体、API 和 UI。它们分别属于 T1-B、T1-D 及后续工作包；本 T1-A 不把 T0 技术证据冒充项目运行实现。

主要风险是后续消费者重新发明 taxonomy code、把 fake healthy 当产品健康、把 capability 支持当产品开关，或把 float/bytes 直接塞入 fingerprint。公共常量、严格构造校验和负向测试已令这些路径 fail-closed；若消费者需要新语义，必须发布新版本并回到门禁，不得放宽当前版本。

本工作包没有数据库、进程、容器、模型、媒体、QwenPaw 或用户内容副作用。回退时由主集成 Owner 精确移除第 2 节 10 个文件即可；不得清理共享目录或其他 Owner 文件。

## 6. 给 T1-B / T1-D 的接线说明

1. T1-B 子类化 `MossNanoTTSAdapter`，直接返回 `MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES` 的兼容值；不得改 topology、把文件路径传给 worker、静默回退 macOS 或在 import 时启动模型。真实 health/model fingerprint 必须来自握手与已验证资产，不复制 fake identity。
2. T1-B 必须对实际响应 bytes 重算 hash，再构造 `SynthesisResult`；取消只承诺 `segment_boundary`。当前产品可见性仍为 false，T1-B 成功也不能自行翻开关。
3. T1-D 直接消费 `NarrationRequestScope` 常量和 taxonomy fixture 建约束；owner/workspace 使用 UUID，scope 由服务端注入，issue code/severity/version 必须受枚举/CHECK/FK 或等价数据库约束，workflow failure 独立保存。
4. T1-D 不把 capability、fingerprint payload 或客户端 JSON 当数据库权威枚举来源；fingerprint schema version 和 digest 保存为不可变输入，unknown version 拒绝写入。
5. T1-G/后续测试可使用 fake，但必须断言 `is_test_double=true`、产品 flags false；`DisabledVoiceDesignAdapter` 是当前真实默认，只有新证据和新门禁才能替换。
