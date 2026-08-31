# VG40-CORE-DEPLOY：计划 35 长期部署记录

状态：**2026-08-30 PASS。MOSS-TTS-Nano CORE 已在长期 `127.0.0.1:18088` 恢复为 ready；本记录不包含 VoiceGenerator 可行性结论。**

## 可恢复边界

- 部署前数据库 head：`20260829_0033`。
- 仓库外备份：`/Users/liujia/Documents/AI小说世界2026-backups/plan40-20260830-core-deploy`。
- 备份包含 PostgreSQL custom dump、原安装插件目录、224 MiB 实际小说媒体副本、迁移头与 1037 条逐文件 SHA-256。
- 恢复时先停止新写入，恢复原安装插件与数据库 dump；媒体仅在确认对应数据库基线后恢复。
- 未删除或重建 PostgreSQL、QwenPaw、媒体、模型或密钥卷。

## 发布身份

- 数据库 head：`20260829_0034`。
- 前端 bundle SHA-256：`86b8ea39bdec6e1fa4ce1f0cd993540f64cd3a7661a8338ce51483d2bf2e8e63`。
- 插件目录清单摘要：`dc3a994dccd13bfc48d5899a32673a0a933f57e7eaa68bfa1b4ef8963ba8f156`。
- Sidecar image digest：`sha256:a3b63657b2c74a4862448cfc6e798c52d1ea74d92e5e2a8910dd6b545054ce4e`。
- PawApp 版本保持 `0.4.0`，实际写作模型保持 `minimax-cn / MiniMax-M3`。

## 验证

- QwenPaw、PostgreSQL、Nano Sidecar：healthy。
- PawApp health：ready。
- narration technical：ready；Sidecar reachable，模型按需未加载。
- narration production：ready；digest keyring、生产后端和 worker 均 ready。
- 官方音色目录：`moss-tts-official-preset-catalog/2.0`，18 项完整。
- 新能力 schema：`narration-feature-readiness/1`；人物匹配、高级调音与私人删除由同一 readiness provider 驱动。
- 原生 Agent、九个小说 Skills、五个小说工具和 `MiniMax-M3` 有效模型均通过 verifier。

## 启动竞态复盘

第一次恢复时，长期机器上仍运行计划 35 之前的旧 Sidecar 镜像。旧进程在 PawApp 重启时进入 poisoned 终态并按 fail-closed 退出，PawApp 正确报告 `SIDECAR_LIFECYCLE_FAILED`，没有伪装 ready，也没有改变用户绑定或媒体。随后从当前候选重建 Sidecar，先等待 Sidecar healthy，再重启 PawApp；完整 verifier 通过。该竞态说明正式恢复顺序必须固定为 Sidecar → PawApp。

结论：`CORE-FINAL=PASS_DEPLOYED`；VoiceGenerator 的 `VG16-*` 仍为未测量，不能据此宣称人物全新音色生成已可用。
