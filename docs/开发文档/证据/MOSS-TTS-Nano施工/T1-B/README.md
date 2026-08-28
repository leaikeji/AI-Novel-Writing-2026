# T1-B 生产 Sidecar、短租约与模型资产闭环证据

- 状态：**T1-B REAL PASS**。固定 runner 已使用真实 MOSS-TTS-Nano 完成协议 1.1、控制／Worker 凭据分离、60 秒短租约、续租、过期卸载、陈旧凭据拒绝、合成、取消、活动请求故障、新 generation 恢复与精确清理。
- Owner：T1-B；执行日期：2026-08-26（Asia/Shanghai）。本结论只关闭 Sidecar/模型资产基础包；用户可见产品 capability 继续为 `false`。
- 冻结输入：协议 `moss-tts-sidecar/1.1`；生产模型 fingerprint `3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d`；测试 fingerprint `9846cd5d051a8dc124441d6704cd7db1d27f3db91c493b176c4d1a5643876ed3`；生产锁 SHA-256 `c6491f44c87e05d3d8075a102d65c019e7b40608a977baa05366929e7684e137`；29 项 inventory `d0f173dbc661d0352825dd28a5b35a1c65d60be540badacf7ef3b1a57b0b416d`。
- 当前候选镜像：`sha256:78a2af56924f5593bc9391b9f288ffef428d3350cd6b859476e8ee29a9bc9422`，`linux/arm64`，标签的 protocol/fingerprint 与代码一致。

## 已实现的运行边界

- `sidecar_server.py`：控制 token 只能申请／续租／释放租约；Worker token 仅在当前 lease generation 内可用。Watchdog 在 60 秒过期后撤销身份、等待活动请求边界并卸载模型；陈旧 token 和 ABA 卸载均被 fencing。
- native backend 卸载在 daemon teardown 线程中按剩余 drain deadline 执行；卡死则 poison 并使 Sidecar 以 75 退出，由无 Docker socket 的外部 supervisor 按 `on-failure` 恢复。
- `runtime.py`：全响应校验 protocol/request/generation/model/actual-model；释放响应丢失时，只接受“已认证、同 lease generation、已 inert”的 health 证明，否则 fail-closed 并重启。
- `validate_sidecar_lifecycle.py`：默认 dry-run；real 需精确确认与 `LOCK-NANO`。正式源模型卷按项目／用途标签前后检查，只读挂载，29 项先离线验证再复制到 runner 自有卷。Token 使用 `docker create → docker cp → docker start`，不使用主机 bind mount；清理从不删除源模型卷。
- WAV/FLAC 完整解码、原子发布、取消后无 bytes 发布、模型实际身份和 ready payload/header 原子一致均已由负向测试覆盖。

## 实际验证

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts='' -q \
  tests/narration/test_runtime.py tests/narration/test_sidecar_server.py
104 passed (runtime 43 + sidecar 61)

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/tts/validate_sidecar_lifecycle.py \
  --mode real --image-mode prebuilt \
  --source-model-volume ai-novel-2026-moss-models \
  --confirm-source-model-volume USE-LABELED-READONLY-MOSS-MODEL-VOLUME ...
status=real_pass; protocol=moss-tts-sidecar/1.1; cleanup.failures=[]
```

当前 runner SHA-256 为 `23305c611d115361b378a142c2e675625d2eb9fbda045c14f1570210edd4c999`，结构化 transcript schema 为 `t1-b-sidecar-lifecycle-transcript/1.2`。真实结果：

- 源卷两次标签校验通过，只读挂载，29/29 离线校验；源卷不在 cleanup 权限内。
- 初次 generation `9183407905447616316`，故障恢复 generation `7531935992487800683`，已变更。
- 两轮均执行 5 次续租，陈旧 Worker token 被拒绝，最终状态 `unloaded`。
- 普通合成 `430124 bytes / 107520 frames`；reference 合成 `476204 bytes / 119040 frames`。
- 活动取消终态 `REQUEST_CANCELLED`；活动请求强制故障时客户端非成功退出，恢复后再次合成通过。
- transcript 为 `0600`，明确记录 `secrets_recorded=false`、`text_recorded=false`、`audio_bytes_recorded=false`。

## 正式运行态与回退

- 正式 Sidecar 已在不改容器名和长期服务数量的前提下原位更新到上述 1.1 镜像；模型卷和密钥卷均为只读，Sidecar/QwenPaw 均 `healthy`。
- QwenPaw 容器 ID 和启动时间未变，`AI_NOVEL_TTS_RUNTIME_ENABLED=false`；正式已安装 PawApp 仍是旧包，没有用当前未提交工作树覆盖。当前包的安装／卸载由独立 QwenPaw 2.1.0 门禁验证。
- 两个已成功退出的一次性 init/installer 容器已删除，数据卷保留；项目当前长期容器只有 QwenPaw、PostgreSQL 和 Sidecar。
- 旧镜像已被 Docker 后台清理，无法生成可执行快照；本阶段失败回退为保持 capability/runtime `false`、停止 Sidecar、按固定 Dockerfile 重建当前已验证镜像，不删除任何卷。

真实主证据为 [`runner-real-lease-1.1-transcript.json`](./runner-real-lease-1.1-transcript.json)；旧 1.0 transcript 仅作历史过程，不是当前验收输入。
