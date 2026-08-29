# TTS 按需加载与 Docker CPU 优化计划

状态：**已于 2026-08-29 完成实施与真实部署验证。**

基线日期：2026-08-29（Asia/Shanghai）

## 1. 目标与边界

本次只处理两类本机资源问题：

1. MOSS-TTS-Nano 不再随 PawApp 启动常驻模型；正式产品模式改为首次合成时加载，最后一次模型活动后自动卸载。
2. 降低项目可控的空闲唤醒，并核实 Mac 长期高 CPU 属于 Docker Desktop 宿主、容器业务进程还是两者叠加。

不修改 QwenPaw 上游核心，不改变小说正文、revision、故事账本、数据库 schema、持久卷或 TTS 模型身份；不降低现有 4 GiB Sidecar 内存上限，因为该上限是运行保护而不是空闲占用目标。隐藏 T4 验收模式继续启动预热，避免改变既有验收门禁的含义。

## 2. 已核实事实与裁决

### 2.1 资源基线

- **已核实事实**：空闲容器采样中，QwenPaw 约 `0.4%–3.35% CPU / 1.15 GiB`，TTS Sidecar 约 `0.02%–0.03% CPU / 3.44 GiB`，PostgreSQL 约 `0.06%–0.27% CPU / 0.52 GiB`。
- **已核实事实**：TTS Python 进程匿名 PSS 约 3.58 GiB；模型文件约 729 MiB，ONNX Session 和原生分配器使驻留内存显著膨胀。
- **已核实事实**：既有真实证据中的冷启动／warmup 约 `2.06–2.14s`，可播放 WAV 约 `1.68–1.81s`。
- **已核实事实**：Mac 上 `com.apple.Virtualization.VirtualMachine` 长期约占一个核心；容器内同期业务进程没有对应的持续满核占用。Docker Desktop 4.87.0 的内部 `/initd services` 约 100% CPU，Dashboard 打开时还会每秒轮询容器 stats/events。
- **技术判断**：高内存主要来自项目当前的 TTS 启动预热策略；长期高 CPU 的主因是 Docker Desktop 虚拟机内部服务，TTS 空闲时不是持续满核来源。项目的 5 秒健康检查和 0.5 秒数据库轮询是次要、可消除的唤醒源。

### 2.2 空闲卸载时间

默认配置冻结为：

```text
AI_NOVEL_TTS_IDLE_UNLOAD_SECONDS=300
```

仅接受 `60–3600` 的十进制整数；非法值令 TTS 技术运行时配置失败并保持 fail-closed。选择 300 秒的理由：

- 足以覆盖作者连续试听、跳段和短暂停顿，避免每一小段都支付约 2.1 秒冷加载；
- 停止朗读约 5 分钟后即可回收约 3.4 GiB 常驻内存；
- 卸载检查与现有 15 秒租约续期合并，不增加高频后台定时器，因此实际释放时间为 300–315 秒。

后续只有在真实使用证据显示频繁抖动或回收过慢时才调整：频繁短暂停顿后又朗读可升至 600 秒；强内存约束机器可降至 120 秒；不建议低于 60 秒。

## 3. 冻结实现

正式产品模式的状态流为：

```text
PawApp 启动
  -> 只连接 Sidecar、取得短租约并核验协议/能力
  -> 模型保持未加载
  -> 首个 segment/voice-preview 合成在单推理锁内 warmup
  -> 连续合成复用同一模型，完成一次合成就重置空闲计时
  -> 满 300 秒且没有在途合成时，释放租约并证明模型已卸载
  -> 监督器替换已空闲的 Sidecar 进程，归还 ONNX 原生分配器保留页
  -> 立即取得新的未加载租约，保持 Sidecar 与生产 worker 可用
  -> 下次合成再次 warmup
```

生产策略仍使用仓库冻结的期望模型指纹；首次 warmup 与每次实际输出继续校验 Sidecar 返回的真实指纹和 generation。仅清空 Python／ONNX Session 后，原生分配器实测仍可能保留约 2.6 GiB RSS，因此空闲释放必须在“租约已释放、无在途合成、模型已卸载”的证明之后，通过既有受监督重启契约换新 Sidecar 进程；这不是重启 QwenPaw 或删除容器／卷。模型卸载不得让生产 worker 退出、隐藏朗读入口或新建第二套任务队列。取消、租约失效、卸载失败或重新激活失败继续按现有 poison/restart 和可重试任务规则 fail-closed。

## 4. CPU 优化

- Docker Desktop 更新到当前已提供的维护版本后重启引擎并复测虚拟机 CPU；Dashboard 保持关闭，避免可见页面的每秒 stats/events 轮询。
- Compose 中 QwenPaw、PostgreSQL 与 TTS Sidecar 健康检查由 5 秒调整为 30 秒，保留启动宽限、超时与失败重试。
- 共享 TTS job worker 的空闲轮询由 0.5 秒调整为 1 秒；最多增加 0.5 秒取任务延迟，不影响权威任务状态或失败恢复。
- 不通过删除卷、停止数据库、降低 TTS 可用内存上限或修改 Docker Desktop 私有文件来换取表面数字。

## 5. 子代理并行施工设计

**本任务不并行。** 原因是核心改动集中在同一 Sidecar adapter／PawApp 生命周期状态机，部署验证还独占同一 Docker Desktop 与同一套长期数据卷；并行写入会扩大竞态和误操作风险。用户未要求子代理，主代理是唯一集成责任人。

| 波次 | 工作包 | 标记 | 所有权与目标 | 前置／门禁 | 验收 |
|---|---|---|---|---|---|
| W0 | `CPU-BASE` | `SER` | 只读采样 Docker VM、容器 stats、进程 PSS | 保留所有卷 | 基线数据可复核 |
| W1 | `TTS-LIFE` | `SER` `MUTEX` | `backend/narration/runtime.py`、`pawapp_runtime.py`：按需 warmup、300 秒空闲释放、租约竞态 | 冻结上述状态流 | 聚焦 pytest |
| W1 | `CPU-WAKE` | `SER` | `compose.yaml`、生产 worker 默认轮询：降低空闲唤醒 | 不改变启动依赖 | `docker compose config`、聚焦 pytest |
| W2 | `CONTRACT` | `SER` | `.env.example`、测试与本文档：配置边界和故障语义 | W1 完成 | 契约测试、`git diff --check` |
| W3 | `LIVE-GATE` | `GATE` `INT` | 构建／重建项目容器，验证冷态、首次朗读、空闲回收、CPU 与数据保留 | Docker Desktop 可用；不得删卷 | 健康检查、容器 stats、宿主 CPU、真实数据非回归 |

禁止触碰：QwenPaw 上游核心、Alembic 历史、PostgreSQL／QwenPaw／媒体卷、用户现有的计划 22／28／29、`skills/prose-writing` 及对应审计目录。共享资源锁为 Docker Desktop 引擎和长期 Compose 项目；仅主代理操作。

## 6. 恢复路径

- 代码回退：移除按需加载分支并恢复启动 warmup；配置变量缺省不会影响旧镜像。
- 部署回退：重新运行上一版 QwenPaw 镜像和既有 Sidecar 镜像，不删除任何卷。
- 运行失败：停止取得新 TTS 工作，保留数据库 job、草稿和既有媒体；Sidecar 租约 watchdog 负责最终卸载，QwenPaw 原生功能继续可用。

## 7. 完成门禁

只有同时满足以下条件才能把本文状态改为“已完成”：

1. 启动后 TTS 模型不加载，Sidecar 内存明显低于原 3.44 GiB 基线；
2. 首次真实朗读能自动 warmup 并产出可播放音频；
3. 设定空闲期后无在途合成，Sidecar 证明卸载并释放大部分模型内存；
4. 连续朗读不会反复装卸，取消／失败／重启不会发布错误媒体；
5. Docker VM 的长期 CPU 复测给出明确结果，项目侧健康检查与轮询优化通过；
6. 相关测试、Compose 配置、构建、健康检查、`git diff --check` 与工作区复核通过，且持久卷和用户内容未删除。

## 8. 实施与验证结果

- **按需加载已部署**：QwenPaw 启动和 TTS Sidecar 重建后，健康接口为 `ready`，同时明确报告 `model_loaded=false`、`idle_unload_seconds=300`；朗读入口、生产 worker 和模型指纹校验保持可用。
- **真实首次合成已通过**：冷态首次合成实测约 `3.3–4.34s`，成功生成 `48 kHz` WAV；该烟测未写入数据库、正式正文或媒体记录。
- **真实空闲释放已通过**：无在途合成时释放模型、完成受监督进程替换并重新取得冷租约；TTS Sidecar 从基线约 `3.44 GiB` 降至约 `25 MiB`，后续合成仍可再次按需加载。
- **CPU 根因已隔离并缓解**：Docker Desktop 已更新至 `4.88.1` 并重启；关闭 Dashboard 后，`com.apple.Virtualization.VirtualMachine` 从持续约 `101%–114% CPU` 降至复测约 `1.1%–3.9%`，Docker 内部日志在 20 秒复测窗口内无新增。最终单点采样为约 `2.6% CPU`。
- **项目侧空闲唤醒已降低**：三个 Compose 健康检查均为 `30s`，TTS worker 空闲轮询为 `1s`；最终容器采样为 QwenPaw `1.43% / 720.8 MiB`、TTS `0.12% / 25.04 MiB`、PostgreSQL `0.11% / 39.44 MiB`。
- **验证结果**：TTS Sidecar 镜像契约、PawApp 生命周期、Sidecar server 和生产运行时聚焦测试全部通过；插件打包、Sidecar 镜像构建、`docker compose config`、真实健康检查和数据连接均通过。全量测试为 `2822 passed, 126 skipped, 8 failed`；8 个失败均来自任务开始前用户正在修改的 `skills/prose-writing/SKILL.md` 与冻结哈希不一致，不属于本次 TTS／Docker 改动，且本次未覆盖该文件。
- **数据安全**：未删除或重建 PostgreSQL、QwenPaw、媒体及 TTS 模型持久卷；没有修改 QwenPaw 上游核心。
