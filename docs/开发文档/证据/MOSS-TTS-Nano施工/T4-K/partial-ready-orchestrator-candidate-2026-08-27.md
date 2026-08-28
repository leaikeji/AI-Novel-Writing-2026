# T4-K 真实 partial-ready 与本地编排器代码候选

状态：`SOURCE_CANDIDATE_VERIFIED / REAL_RUNTIME_NOT_YET_EXECUTED / T4_GATE_HOLD`

日期：2026-08-27（Asia/Shanghai）

## 本次完成

- 正式音色绑定保持不变：旁白 `onnx.Zhiming`、沈川 `onnx.Junhao`、林晚 `onnx.Xiaoyu`。本工作包没有创建新的选声点，也没有沿用 Lingyu／Yuewen／Junhao 旧候选映射。
- 新增隐藏 validation-only 的句段领取 gate。它默认放行，只在同一 canonical run、novel、document 和有效 token 下临时限制一次真实 segment claim；不修改 schema、Manifest、任务状态或产品 capability。
- 固定 launcher 在技术检查阶段基于已经完成的 automatic ready Edition 追加两个 run-derived 中文句段，通过现有 HTTP、CAS 和 recovery checkpoint 创建独立 append-only Edition。只有观测到至少 3 个连续缓存命中、至少 8 秒 ready 前缀、至少 2 个真实 miss job、`partial_ready` Manifest／Edition 与 gate `claimed=1` 后，才把该 Edition 切为当前播放版本并启动真实浏览器采集。
- 浏览器采集完成或任意失败后，executor 在等待任务继续前最多执行两次有界幂等 gate release；随后等待临时 Edition 完成，并以 CAS 恢复进入该检查前的正文、ready Edition 和 script pointer。冲突、TTL 到期、错误 scope、错误 Manifest 或恢复失败均 fail-closed。
- 私有 `partial-ready-validation.json` 使用 `0600`、canonical JSON、原子替换和 previous-record SHA-256 链，只保存 ID、hash、计数和稳定错误码，不保存正文、音频、token、URL 或文件路径。
- 本地宿主编排器只复用既有 PostgreSQL、QwenPaw 和 MOSS-TTS Sidecar 三个容器。预检逐项绑定固定镜像、网络、卷名、挂载类型及读写属性；不允许调用方注入 URL、容器、数据库、浏览器、selector、viewport、输出目录或 import path。
- 长时 launcher 不再使用可能填满的 stdout/stderr PIPE；异常停止按 `SIGINT → TERM → KILL → reap` 有界执行，确认进程退出后才走异常释放。报告事务允许在 collector 或 probe 已成功发布后幂等补齐，commit marker 始终最后发布；status／cleanup 会校验 run、scope、fixture、bundle、operator evidence root、result 和 recovery 绑定。
- cleanup 删除范围仍只包含该 run 的 `incoming` 和 `tool` 临时目录，不删除 recovery、结果、正文、数据库、媒体、模型或 Docker 卷。它先写入私有 cleanup authorization，允许 incoming 已删除后的幂等重试，并最后删除 tool。

## 实际验证

- `.venv/bin/python -m pytest tests/narration/test_chapter_e2e_executor.py tests/narration/test_run_chapter_e2e_real.py -q`：`64 passed`。
- `.venv/bin/python -m pytest tests/narration/test_run_local_chapter_e2e.py tests/narration/test_local_chapter_e2e_container.py -q`：`31 passed`。
- `.venv/bin/python -m pytest`：`2430 passed, 116 skipped`；仅有 2 条既有 Starlette 弃用警告。
- `pnpm typecheck`、`pnpm test -- --run`、`pnpm build`：类型检查通过，`86 files / 802 tests` 通过，生产构建成功。
- `.venv/bin/python scripts/package_plugin.py` 与 `tests/test_qwenpaw_integration_contract.py`：通过；宿主验收 runner、Node Controller、历史 signing 实验、token、模型、prompt codes、生成音频均未进入 PawApp 包。
- `docker compose config --quiet` 与 `git diff --check`：通过。

## 尚未完成与恢复边界

- 上述结果仅证明当前源码候选与自动化，不是新包安装后的真实 Nano／Edge／30 分钟／恢复／teardown 通过证据。现有容器仍需重新安装当前候选后再执行完整运行。
- 真实 pending gap 必须由上述独立 Edition 在浏览器中实际观测，不能用单元测试或全 ready Edition 的 `not_observed` 冒充。
- cleanup 仍有一个不影响产品数据的极窄工具性风险：若进程恰好在最后删除 `tool` 目录的系统调用中被外力强杀，目录可能部分删除，无法再从该目录启动自清理 helper。彻底消除此窗口需要常驻 finalizer 或新的 rename／descriptor 状态机；现行个人本地范围不扩建该服务。正常异常、incoming 已删除、tool 删除失败等路径均已可重试并有测试。
- 本文当时的 result/probe 2.1 要求整个窗口 `pageout_delta=0`、`swapout_delta=0`；首次 `pageout_delta=2503` 的 `TECHNICAL_MEMORY_SAFETY_GATE_FAILED` 历史记录保持有效，不得重标为通过。当前 result/probe 2.2 候选已将原始 pageout/swapout 改为保留且一致性 fail-closed 的 telemetry，并使用固定 31 点 Sidecar 首末各 5 点中值趋势、`peak<=4 GiB`、restart=0、health failure=0 和 slowdown=false 作硬门禁；尚须以 fresh real run 验证，不得用代码候选冒充 T4 PASS。
