# T4-B 持久句段 Worker 与调度器

状态：**`IMPLEMENTED_CANDIDATE_WITH_FIXED_RUNTIME_HOLD`（2026-08-27）**。持久任务、公平领取、单 Nano 资源租约、心跳/取消、事务外音频工作和双 fence 发布编排已进入源码并通过隔离单元测试；固定 QwenPaw 内的真实 Nano→FFmpeg→PostgreSQL→Manifest 章级运行尚未在 T4-GATE 完成，因此不得把本证据表述为产品朗读已经可用。

## 1. 实现边界

- `scheduler.py`：重试提升、过期 attempt 恢复和 `moss-nano` 单任务领取分别使用短事务提交；公平老化、`SKIP LOCKED` 与 `moss-nano:inference` 最大并发 1 继续由 T1-C 的持久任务服务负责。
- `worker.py`：领取提交后加载不可变 Edition/segment/voice 输入；Nano、reference 读取、PCM 校验、FFmpeg 与不可变文件发布均在数据库事务外执行。
- 发布前再次读取取消状态，并在同一短事务内重新锁定 job fence 与 resource fence；只有 fence 仍有效时才写 model-run、media、render link、ready render、EditionSegment、Manifest 与 Request 聚合状态。
- malformed audio、模型指纹漂移、存储 inode/path 异常、转码不可用和临时外部失败使用稳定分类；过期/晚到结果只返回 `stale`，不得降级为可达媒体。
- 工作项加载失败也会 fenced 结束 attempt，不留下无人接管的 `running` claim；失败记录自身不可用时交给既有 lease reconciler 恢复。

## 2. 实际验证

```text
.venv/bin/python -m pytest tests/narration/test_narration_worker.py -q
9 passed

.venv/bin/python -m pytest \
  tests/narration/test_narration_worker.py \
  tests/narration/test_audio_pipeline.py -q
22 passed

.venv/bin/python -m py_compile \
  backend/narration/scheduler.py \
  backend/narration/worker.py
PASS
```

覆盖：成功发布、句段边界取消、心跳期间取消、静音/无效 Nano 输出、可重试转码不可用、晚到双 fence 拒绝、空队列、claim 后工作项加载失败、进程内单 Worker 持续轮询／维护／空闲等待／停机取消，以及调度维护/领取的独立提交和 `moss-nano` 资源类限定。

## 3. 仍为 HOLD

- 固定 QwenPaw 薄运行层当前尚未证明存在本实现要求的固定 FFmpeg/ffprobe 路径；不得临时新增容器或第二套任务服务规避。
- 真实 MOSS-TTS-Nano 单句、30 分钟章节、长耗时心跳、Sidecar restart、PostgreSQL crash/reconcile、AAC-LC/FLAC 文件与 Manifest 可达性均留待 T4-J/T4-K/T4-GATE。
- 失败后的局部重生成、最终聚合恢复与历史 Edition 切换属于 T4-I，不在本工作包提前扩张。

## 4. 文件摘要（本次候选）

```text
backend/narration/scheduler.py                 56a82d619ec92c2ffb9607e98230fcdae45d4e6c17216b113c52eb35fe5c75bc
backend/narration/worker.py                    d5ebd02b848f0ad28cf50f36f66f1ae2e172ca27a6b413bb32699aeafbf2fb71
tests/narration/test_narration_worker.py       021297e1c212c9fb97c9ddd31504718aa445fb894b3d0fd95f1631db07fc398d
```
