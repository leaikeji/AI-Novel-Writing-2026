# T0-C Nano 中文质量、参考时长与独立句段尖峰

状态：**旧单进程 smoke 保留；持久受管 worker 真实 20-case 与同 worker 重复技术矩阵已 20/20 passed，但人工听感仍 pending、参考克隆仍 blocked，因此不得把 T0-C 写成完整产品质量已通过。**

> 2026-08-26 语义更正：本页第 5 节与当前 `metrics.json` 保存的是早期 one-process-per-segment smoke 历史，不是最终 managed-worker 性能证据。其中“首包”是 runner 内部 codec 首个非空音频，“合成 wall/RTF”含新进程及模型加载，不能与 steady-state 指标混用。当前候选契约和锁后运行序列见 `managed-worker-contract.md`；旧 metrics 不覆盖、不改写。

> 持久 worker 真实结果见 `managed-worker-real-20260826/README.md`：20/20 技术 passed、同 PID/generation、严格四事件与文件 hash 验证通过、0 orphan、0 `.part`；人工听感仍未完成。

> Reference Clone 无模型准备见 `reference-clone-prep-20260826/README.md`：仓库外 3/5/8/12 秒 isolated-test-only 技术候选及输入负向门禁已就绪；本 T0-C run 当时没有取得模型锁或执行克隆。其后 T0-B 已冻结唯一共享 Sidecar API 并完成 Linux 四档技术 smoke；产品权利和人工听感仍未通过。

## 1. 执行边界

- 工作包：`T0-C`
- Owner：旧 smoke `/root/tts_t0c_quality_spike`；持久 worker 加固 `/root/tts_t0c_persistent_quality`
- 基线 HEAD：`9b5be4a`
- 执行日期：`2026-08-26`（Asia/Shanghai）
- 隔离环境：Python 3.11.16；模型、官方源码和媒体全部位于仓库外受控目录。
- 旧 smoke 资源锁：主代理当时只释放 `LOCK-NANO` 运行一个真实 case；后续持久 worker 运行另见新 evidence。
- 禁止扩展：未并发其他模型任务，未运行第二个 Nano case，未下载新资产，未操作 QwenPaw/Docker 唯一环境。
- 共享工作树：执行前已 dirty；只写分配的 T0-C 脚本、prototype quality 目录与本证据目录。
- 隐私：证据不含用户正文、参考音频、生成音频、模型权重或绝对私人媒体路径。

## 2. 冻结输入与资产指纹

| 输入 | SHA-256 / 结论 |
| --- | --- |
| `benchmark_manifest.json` | `6750b722ad411839e369c617a9245c9578335d05b0c6117bcedfec3cfd6bbe35` |
| `authorized-texts.json` | `434de78a9aca59ef5e1409b12ae39157b51e855e69503587fb4845502374c598` |
| 授权文本 | 26 条；程序按 JSON 解码后精确 UTF-8 字节重算每条 SHA-256 |
| case | 27 个；重算 `text_ids`、逐文本 hash 及 `\n<SEGMENT>\n` 组合 hash；本轮仅选 `narration-neutral` |
| 官方 source revision | `cc7bdf19c7639c0870dab22045a33b442760f6be` |
| source tree | 13 files / 184,171 bytes / `dfeedbbfae13dd04c78280e660de7d3d3c5297a82f720da44e7cb9029b4ccc65` |
| ONNX model revisions | TTS `f52645cb467506d8e18e746ddd59482685b74e58` + codec `ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae` |
| model tree | 16 files / 763,191,513 bytes / `0aa88a384369f3b9a3bdc12a039559b7bced3ce47be8360106895b2dd81b634d` |
| 参考音频 | 冻结产品 fixture 的 3/5/8/12 秒 profile 仍为 `placeholder_only` + `not_supplied`；仓库外 isolated-test-only 技术候选已准备并验 hash/格式/时长，后续 T0-B Linux 共享 Sidecar 四档技术 smoke 已通过，但产品权利与人工听感尚未通过 |

## 3. 实现与防误报

- `benchmark_nano_quality.py` 严格重算 fixture/授权文本/case 组合 hash，默认无网络、无自动下载；当前真实运行必须显式给出 source/model/media/revision/tree hash，并固定复用 T0-B managed worker。
- 模型和媒体目录必须位于仓库外，且不得与证据目录重叠。证据 argv 保留完整标志顺序，对外部绝对路径做稳定脱敏，另记完整 argv hash。
- `official_onnx_quality_runner.py` 只接线锁定官方 `OnnxTtsRuntime`，强制显式本地资产、offline、ONNX CPU、streaming、WeText disabled 和 robust normalization；不修改 QwenPaw 或官方源码。
- 旧 smoke 首包从 codec streaming session 首个非空音频输出计时；新驱动不再把它冒充客户端可播放首包，而以 managed worker 的完整 ready WAV 作为严格契约 `first_packet_ms`。
- `fake_quality_runner.py` 只用于临时目录单测，被硬性禁止写入仓库证据目录。
- 脚本不从技术指标推断听感；真实 case 的 `listening` 仍为 `pending/not_reviewed`。
- 单进程质量驱动器不伪造耐久 crash/resume；该验收留给后续 worker harness。

## 4. 验证记录

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| Python 3.11 `py_compile` | 0 | driver、fake runner、official runner 与单测语法通过；pycache 写入临时目录 |
| 旧 smoke：`python -m unittest -v .../test_benchmark_nano_quality.py` | 0 | 当时 6/6 通过；包括坏 hash 拒绝、dry-run 无 pass、independent 三次调用/无 cross-fade、fake 证据禁入、真实证据拒绝覆盖、official runner 导入前阻断 |
| 持久 worker/reference 候选：同一 Python 3.11 unittest | 0 | 当前 10/10 通过；覆盖 20-case、同 worker、时延语义、严格 renderer、reference hash/时长/格式、symlink/仓库路径、CLI 配对与证据脱敏 |
| 全 fixture dry-run | 0 | 27 cases = 23 `skipped` + 4 参考占位 `blocked` + 0 `passed` |
| 真实 `narration-neutral` ONNX CPU smoke | 0 | 第一次通过；1 case / 1 runner invocation / 1 个 ready segment；无修复重试 |
| `render_benchmark_report.py metrics.json --stdout-format json` | 0 | 严格通过 `moss-tts-benchmark-result/1.0` |
| `inspect_audio.py <external-wav> --compact` | 0 | 二次只读 WAV 检查与 metrics 的 hash/时长/信号数据一致 |
| 证据隐私扫描 | 0 | 未发现用户名、私人绝对媒体路径、token/密钥或音频内容 |

## 5. 单 case 旧单进程 smoke 指标（仅历史，不可作为 steady-state 结论）

- Run ID：`T0-C-20260826T023010+0800-88391-747d2a44`
- 环境：Apple M4 / 16 GB / arm64 / Darwin 25.5.0 / Python 3.11.16
- 后端/参数：ONNX CPU，4 threads，fixed sample mode，seed 0，streaming，max 375 frames，chunk 上限 75 tokens，WeText disabled，robust normalization enabled
- run/case 状态：`passed` / `passed`；符合 fixture 预期终态
- 首个非空音频包：`171.820250 ms`
- 合成 wall：`8294.934291 ms`
- 音频时长：`5.92 s`
- RTF：`1.401171333`
- 进程 peak RSS：`1,607,991,296 bytes`
- 输出：48,000 Hz / 2 声道 / 16-bit PCM WAV / 1,136,684 bytes
- 输出 SHA-256：`2627997330f3df9d61f7a3565f11fc1a1af2bfbce333714b2222b62d26efa4bb`
- RMS：`-17.317749 dBFS`；DC offset：`0.000028235`
- 静音 frame：86,306 / 284,160，比例 `0.303723255`
- 峰值：`-0.000265 dBFS`；削波样本：22 / 568,320，比例 `0.000038711`
- 听感：`pending/not_reviewed`；技术 `passed` 不代表漏字、重复、停顿、噪声或主观自然度通过。

## 6. 产物 hash

下表前七行是旧单进程 smoke 当时的不可改写指纹；它们不代表当前工作树候选。随后列出的持久 worker 候选旧指纹也只反映真实 run 前的实现节点；最终实现与真实证据指纹以 `managed-worker-real-20260826/README.md` 为准。

| 文件 | SHA-256 |
| --- | --- |
| `scripts/tts/benchmark_nano_quality.py` | `073c915de4454108bc474135fd57d45d6e767953cda88801d4244d7ac7c1e9c2` |
| `prototypes/moss-tts-nano/quality/README.md` | `6b63f497ffd3b3fcd26139777b315a85aa01135e2af781c9071a10d3e2865566` |
| `fake_quality_runner.py` | `7405f8a8037b68efc678cdf6147ff981ae29dd2db08e35eb766740c0b5f164b1` |
| `official_onnx_quality_runner.py` | `31b4888ecec57892d11e575f885cec44ebfca4d758be894ae949bd2a7577a081` |
| `test_benchmark_nano_quality.py` | `9f71338ecdb228c746f0e2a6346e4c16f0b8d3503e36ade9900a77435e124dca` |
| `metrics.json` | `50cfee7f372702c716fe2d0316155de9b03f56571fe703aad5699f16c0b7d9d1` |
| `listening.md` | `0eb8f20d2ea42f43001d35fc8e08a0a027e321622538519ffea2fa71bc0e9835` |

| 持久 worker 候选文件 | 当前 SHA-256 |
| --- | --- |
| `scripts/tts/benchmark_nano_quality.py` | `528f5b31a53fbb7e6255084b2fc5f7335d3b6cfcaedcc64904d7ae6f701e18bc` |
| `prototypes/moss-tts-nano/quality/README.md` | `dc27a49aa6cbb4a15c3b7048b18cb8083fed0f72f892731506ed012bf3318eaf` |
| `test_benchmark_nano_quality.py` | `f575449f23febb023b39dcf23f1012b3b100cd2cc0f60aba26b9e494d8f0ea17` |
| `managed-worker-contract.md` | `8d2435447087d9c2afd2773eef3af1e4add3d4f47251409fd4adb65c6931e3d0` |

## 7. 旧 smoke 当时未验证项、当前闭环与剩余风险

1. 旧 smoke 当时未执行的数字/年代/标点/多音字/姓名/中英混合/长句矩阵，现已纳入持久 worker 20-case 并技术通过；但尚未人工听检，仍不能推广为中文主观质量通过。
2. independent-segment 现已真实生成三段并无 cross-fade 拼接，文件与事件技术检查通过；接缝听感仍 pending。
3. 冻结产品 fixture 的 3/5/8/12 秒参考 WAV 仍未授权、未提供，四项产品状态继续 `blocked`；仓库外技术候选已由唯一共享 Linux Sidecar 完成隔离 smoke，但不得替换 fixture 或冒充产品资产。
4. 人工听感尚未执行。必须实际听检漏字、重复、停顿、噪声、响度和自然度，且应重点确认 22 个削波样本是否可闻。
5. 耐久 crash/resume 需要可恢复 worker 状态与调用计数；T0-C 不越界创建产品 worker。
6. 若后续模型矩阵失败，回退为保留已冻结 fixture/结果契约和本单 case 原始 hash，只在 quality prototype 内调整窄 runner adapter；不改写模型、正文或 PawApp 生产代码。

## 8. 旧 smoke 实际执行数量（持久 run 数量见新 evidence）

| 类型 | 数量 | 结论 |
| --- | ---: | --- |
| 真实 Nano run | 1 | 首次通过，无重试 |
| 真实 Nano case | 1 / 27 | `narration-neutral` 技术通过 |
| 真实 runner invocation | 1 | 一个 ready segment |
| 本 T0-C 历史 run 的真实参考克隆 | 0 / 4 | 本 run 未执行；后续 T0-B Linux Sidecar 四档技术 smoke 已通过，但无产品权利/人听结论，产品仍 blocked |
| 真实 independent-segment case | 0 / 1 | 未执行 |
| 人工听检 | 0 / 1 | pending |
| fake runner 单测 | 1 case / 3 segment invocations | 仅证明驱动契约，不计入模型证据 |
