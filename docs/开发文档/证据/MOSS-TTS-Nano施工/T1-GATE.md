# T1-GATE 基础设施集成门禁

结论：**PASS_WITH_EXPLICIT_PRODUCT_AND_PRODUCTION_ROLE_HOLDS**。

记录日期：2026-08-26（Asia/Shanghai）。T1-DEP 与 T1-A…T1-G 已在各自冻结边界内完成并由主集成 Owner 复核，T1 基础设施阶段通过。这不等于多角色智能朗读产品已可用；所有用户可见入口、播放器、自动选角、reference clone 和 VoiceGenerator 仍保持关闭。

## 1. 工作包接收

| 工作包 | 结论 | 门禁依据 |
| --- | --- | --- |
| T1-DEP | ACCEPT | Linux/arm64 固定依赖、私网、只读模型／密钥卷、无 Docker socket；Compose 两套 config 通过 |
| T1-A | ACCEPT | adapter、scope、taxonomy、capability、fingerprint 公共契约冻结 |
| T1-B | REAL PASS | 真实 Nano 协议 1.1、60 秒短租约、续租、卸载、陈旧凭据拒绝、取消、故障与新 generation 恢复 |
| T1-C | ACCEPT | 持久 job/attempt/lease/fence/retry/dead-letter/manual retry 基础 |
| T1-D | ACCEPT | Alembic 0010…0015 线性迁移、schema 约束和条件回退；正式库仍 0009 |
| T1-E | ACCEPT | 媒体、Range/ETag、原子发布、引用与 GC 基础 |
| T1-F | ACCEPT | request/snapshot/settings/script/Edition/render/Manifest/progress 领域服务 |
| T1-G | ACCEPT_WITH_ROLE_HOLD | 真 PostgreSQL 18 集成、并发锁、崩溃恢复与发布原子性通过；最小权限角色包仍 HOLD |

## 2. 真实模型与 PawApp 生命周期

- [`T1-B/runner-real-lease-1.1-transcript.json`](./T1-B/runner-real-lease-1.1-transcript.json) 是当前唯一 T1-B 真实主 transcript：候选镜像 `sha256:78a2af…c9422`，初次／恢复 generation 不同，两轮均完成 5 次续租、陈旧 token 拒绝与最终 `unloaded`，`cleanup.failures=[]`。
- PawApp 默认 false 路径在读 token/HTTP 之前返回；`/health` 只输出无密钥快照，`product_visible=false`。
- [`T1-PAWAPP-RUNTIME-REAL.json`](./T1-PAWAPP-RUNTIME-REAL.json) 使用当前候选代码、正式 QwenPaw 进程环境与私网 Sidecar，真实完成 `activate → health → warmup → renew → stop/deactivate`；停止后为 `disabled/WORKER_LEASE_INACTIVE`。候选只暂存 `/tmp` 并已删除，未安装到正式 QwenPaw，未访问数据库。

## 3. 数据库、事务与恢复

- 隔离 PostgreSQL 18 的当前 head 为 `20260826_0015`；migration `6/6`、request sealing `8/8`、asset migration `2/2`、current-head live suite `56/56`。
- domain concurrency `10/10` 使用真实两会话锁等待；publication atomicity `1/1` 完整用例重复两次通过。
- claim-before-commit 重放、过期 lease reconcile、新 epoch 拒绝旧 fence、DB 回滚无部分权威行、确定性文件 re-adopt 均已验证。
- 正式 PostgreSQL 仍在 `20260825_0009`；T1 未读、未迁移、未降级正式库。`docker/postgres-roles` 是同一 PostgreSQL 的未来角色隔离，不是 TTS 第二数据库；当前 `production_role_switch=HOLD`。

## 4. 当前包安装／卸载非回归

[`T1-GATE-INSTALL-t1gate04.json`](./T1-GATE-INSTALL-t1gate04.json) 是唯一成功验收输入（`t1gate01…03` 仅保留失败与成功清理过程）。它证明：

- 候选树 SHA-256 `076330ec1c83216e4f45f384e330912e95fd60d2558d871695707f2c8d51167e`，每次安装前在容器内重算一致。
- 精确 2 个临时容器（QwenPaw 2.1.0 + PostgreSQL 18）、5 个临时卷、1 个 internal 网络；0 Sidecar、0 模型/token 挂载、0 host bind、0 host port、无出站路由，`AI_NOVEL_TTS_RUNTIME_ENABLED=false`。
- 公开 API 初装 → 0015 迁移 → force reinstall → DELETE 卸载 → 插件/PawApp/Skills/tools/路由/文件零残留 → reinstall 全通过；正式 QwenPaw 原生页壳、agents/skills/tools 仍响应。
- 数据库哨兵和 4 个命名卷哨兵在 force reinstall、uninstall 与 reinstall 后均不变；最终只按精确名称+双标签删除本轮全部资源，无残留。

## 5. 全量自动化和打包

| 验证 | 实际结果 |
| --- | --- |
| Python 全量 | `559 passed, 86 skipped`；skip 均为未注入 live 测试库，相应 T1 数据库路径已由上述独立 PostgreSQL 18 门禁覆盖 |
| T1 runtime/host/install 组合 | `144 passed` |
| 前端 | 39 files / `318 passed`，TypeScript `tsc --noEmit` 通过 |
| 前端生产构建 | 49 modules，`frontend/dist/index.js` 1,986.57 kB，gzip 713.11 kB |
| 插件打包 | `build/ai-novel-world-2026`，候选树 hash 如上；含 narration 生命周期与 0015 |
| manifest/宿主契约 | `22 passed` |
| Python 依赖 | `pip check` 通过 |
| Compose | 默认与 `--profile tts` 均 `config --quiet` 通过 |

## 6. 正式 Sidecar 与容器清理

- [`T1-FORMAL-SIDECAR-DEPLOYMENT.json`](./T1-FORMAL-SIDECAR-DEPLOYMENT.json) 记录同名 Sidecar 原位更新到 1.1；模型／密钥卷均只读，Sidecar/QwenPaw 均 healthy，QwenPaw 容器身份与启动时间未变。
- 两个 exit 0 的一次性 init/installer 容器已删除，命名卷全部保留。项目长期容器收敛为 QwenPaw、PostgreSQL、Sidecar 三个；没有清理任何其他项目容器。
- 旧 1.0 容器引用的 Docker content digest 已缺失，无法制作可执行快照。回退是保持 capability/runtime false、停 Sidecar、保留全部卷并按固定源重建已验证 1.1 镜像；不允许删库或 `down -v`。

## 7. 显式 HOLD 与下一 ready set

```json
{
  "narration_product_enabled": false,
  "product_player_enabled": false,
  "editor_production_enabled": false,
  "generic_voice_pool_enabled": false,
  "automatic_generic_casting_enabled": false,
  "reference_clone_visible": false,
  "voice_generator_visible": false,
  "production_role_switch": "HOLD",
  "formal_plugin_rollout": "HOLD"
}
```

`formal_plugin_rollout=HOLD` 表示不用未提交且混有其他任务改动的工作树覆盖唯一正式 PawApp；当前候选已在独立 QwenPaw 中完成全生命周期验证。

T1-GATE 只开放 **T2-A（SER）**：先冻结设置／音色／绑定／试听 API、DTO、错误码和 capability 状态。T2-A 通过后，再按专项文档波次并行派发 T2-B…T2-H；不允许越过 T2-GATE 启动 T3 产品能力。
