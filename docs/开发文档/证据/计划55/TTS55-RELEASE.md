# TTS55 长期发布记录

状态：**PASS。计划 55 已提交、推送、备份、迁移、安装、重启、只读复验并完成隔离资源清理。**

日期：2026-09-03（Asia/Shanghai）

## 1. 发布身份与边界

- 源码提交：`a2b1e90e5b0ce3ea8650bc6bb6f53057e31219b7`，已推送到 `origin/main`。
- PawApp 候选树 SHA-256：`a9aeca8233ec3ae01852876a57aea9766316059b55f091df69257754ad9d61c3`。
- 前端 bundle：`3,626,883` 字节，SHA-256 `45cac9463f1b1801be80ec60e825e1491bebb868eef3088eda9ee8080acb9643`。
- 长期 QwenPaw 容器 ID 保持 `85d0cb14e3996e4d9a2e30ed2eb74326d64b78dacdb408be83f823c1a0ae7f82`，镜像 ID 保持 `sha256:ea2c0858b94a6522821cceb73593bbea5f02c85fee2f08a8d7386ea90d9f15b1`。
- 发布未修改 QwenPaw 上游源码、镜像或核心数据结构；长期真实小说、正文、历史 Edition、音色和媒体仅做只读核验。
- 隔离验收产生的 active v9 24/24 pack 不复制进长期数据库。长期 `generic_voice_pack_versions` 与 `voice_preparation_commands` 在发布后均为 0；因此 `generic_voice_pool` 可操作，而 `automatic_generic_casting` 在建立本机 24/24 active pack 前继续 fail closed。

## 2. 发布前备份

权威备份目录为 `/Users/liujia/Documents/AI小说世界2026-backups/plan55-live-20260903-122312-before`，目录权限 `0700`、文件权限 `0600`。PostgreSQL 自定义格式 dump 已由 `pg_restore --list` 成功读取 1,480 条目录记录；`SHA256SUMS` 已逐项复核通过。

| 对象 | 字节数 | SHA-256 |
| --- | ---: | --- |
| PostgreSQL `0039` dump | 24,918,071 | `61055f1040ddac96583a01334acf0f58807321c50d3a4b02dac9082a16f29e58` |
| 旧长期插件 | 4,747,852 | `f879a6a6be2575401aef2f860b2194a6bee38219b69574d3a27f79e577f57d51` |
| `0040` 候选归档 | 2,325,980 | `2d17e04858128cfee57082997cf19d51dd5e3c22774b453af0475209ea712468` |
| QwenPaw data 卷 | 164,907,554 | `115b5a32a8d3edfdd53c9a4bf64e072c0cbef3011e4a91f70b090848c1e9f645` |
| QwenPaw secrets 卷 | 7,420,392 | `256ad8e005066348a301759a5d0ac28194a14f988f8461f8f75c98c197864fe0` |
| QwenPaw backups 卷 | 84,432,618 | `05b8ec83d0985e8743a506ee6128a93d74de2c6a4848f357aaffbfe0e17dce04` |
| 小说媒体卷 | 365,322,645 | `6d0d3c362269bb805b7c867ebbadc04382d2dfbdf3b270e3e0739cc1255f0a3d` |

## 3. 迁移、权限与安装

串行发布顺序为：确认后台活动任务为 0 → 停止 QwenPaw → 完整卷备份 → `0039` bootstrap／validate → schema owner 执行 `0039 → 0040` → `0040` bootstrap／validate → 离线公开安装同一候选 → 启动和验证。

- 迁移前角色验证 PASS：67 张受保护表、115 个 public relation、222 个 routine。
- 迁移后角色验证 PASS：73 张受保护表、121 个 public relation、225 个 routine。
- API／worker raw DML、`PUBLIC` routine execute 和未来未声明对象继续 fail closed；生产运行角色切换保持 `HOLD`。
- 离线安装同时绑定候选哈希、迁移 head、正式容器 ID 和正式镜像 ID；安装器回读候选与已安装树后才报告成功。
- 发布中发现维护包装器通过 `/release/.venv` 绝对符号链接启动 Python 时会误判虚拟环境。第一次迁移在导入 Alembic 前退出，数据库仍为 `0039`；修复为维护容器优先直接使用 `/app/venv/bin/python`，增加静态回归断言后重新执行并成功。该失败未留下部分迁移。

## 4. 长期运行与桌面只读验收

- PostgreSQL、QwenPaw、MOSS-TTS-Nano Sidecar 均为 running／healthy。
- PawApp health 为 `ready`，数据库 connected；Narration technical 与 production lifecycle 均为 `ready`。
- 18 个官方 preset 目录可读；Nano 模型当前未驻留，空闲卸载仍为 300 秒。
- 发布前后计数保持：novels 3、documents 13、voice profiles 20。新 pack 与准备命令计数均为 0。
- `1920×1080` 实际页面 `1901×1069`、`2560×1440` 实际页面 `2534×1426`：两档均无页面横向溢出、无控制台 error、人物配音和“准备专属音色”入口可见。
- 1080P 展开完整官方音色后，人物声音抽屉 `clientHeight=984`、`scrollHeight=1131`、`overflow-y=auto`；实际滚动达到 `scrollTop=146.04/147`，Escape 后 dialog 数量为 0。
- 验收没有点击智能配音、准备专属音色、创建通用包、保存设置或生成朗读。

## 5. 清理与恢复

- 已精确删除四个 TTS55 隔离容器、五个测试专用卷及 `ai-novel-tts55-real-net`；没有删除长期 PostgreSQL、QwenPaw、模型、媒体或恢复卷。
- 已删除隔离媒体目录与临时 JSON／日志；保留 `/tmp/tts55-listening` 7.6 MiB 作者听检音频作为最终听检证据。
- Docker 未使用 build cache 已回收 940.3 MiB，当前 build cache 为 0 B。
- 临时管理员 pgpass 与一次性维护运行镜像已删除；保留 `ai-novel-2026-plan55-release-root-20260903` 作为精确维护／恢复材料。
- 若需回退，先停止 QwenPaw，使用本记录备份与保留 maintenance root 复核数据库状态；已有 `0040` 记录时优先关闭新增能力并恢复兼容插件，不强制降 schema。只有确认可以无损降级时，才以 schema owner 执行 `0040 → 0039` 并恢复旧插件和完整卷备份。

最终裁决：`TTS55-LIVE-RELEASE=PASS`。
