# 计划 75 候选验收记录

状态：**V1.0 正式 `18088` 已发布并通过；隔离 QwenPaw 生命周期的 Docker Desktop 启动失败证据仍保留。**

日期：2026-09-12（Asia/Shanghai）

## 已通过

- 后端全量：`2838 passed, 273 skipped, 3 warnings`；跳过的数据库用例不计为通过。
- 前端全量：153 个测试文件、1328 项通过；`pnpm typecheck` 通过；production build 为 190 modules。
- 插件候选打包成功：`build/ai-novel-world-2026`。
- Alembic 唯一 head：`20260912_0054`；临时 PostgreSQL 18 空库从 0001 全链升级到 0054。
- 9 个官方 preset 在临时库逐项通过闭包正向和篡改拒绝测试。
- 本机真实 MLX CustomVoice 逐项生成 9 个 speaker，均返回 `local_qwen3_tts`、固定模型 `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit`、revision `41d3337e8b7f2843a75841595fc14e4b9a7a4b96`，且 WAV 有效、非静音。

| preset | speaker | 音频字节 | 时长 | PCM RMS |
| --- | --- | ---: | ---: | ---: |
| `qwen.WarmFemale` | `Serena` | 134444 | 2.80s | 1473.8 |
| `qwen.Vivian` | `Vivian` | 119084 | 2.48s | 3207.0 |
| `qwen.UncleFu` | `Uncle_Fu` | 203564 | 4.24s | 1628.4 |
| `qwen.Dylan` | `Dylan` | 111404 | 2.32s | 1555.9 |
| `qwen.Eric` | `Eric` | 172844 | 3.60s | 2364.5 |
| `qwen.ClearMale` | `Aiden` | 126764 | 2.64s | 4929.3 |
| `qwen.Ryan` | `Ryan` | 192044 | 4.00s | 1751.9 |
| `qwen.OnoAnna` | `Ono_Anna` | 188204 | 3.92s | 1249.6 |
| `qwen.Sohee` | `Sohee` | 153644 | 3.20s | 3272.8 |

样音只在内存校验，没有写入仓库、数据库或媒体目录，也没有发起云端请求。

## 正式发布

- 正式发布已按作者授权完成，详细证据见 [`formal-release-20260912.md`](./formal-release-20260912.md)。
- 正式数据库 head 为 `20260912_0054`，目录为 `qwen-tts-preset-catalog/2` 且精确 9 项。
- 正式 9 音色 HTTP 试听全部返回有效 WAV，Provider／模型／revision／speaker 响应身份精确匹配；桌面页面显示 9 项并真实点击 Sohee 进入播放。
- 旧正文、Edition、渲染和媒体未被发布流程改写；停服前在线窗口新增的一条 WarmFemale 角色绑定作为正常用户数据保留。

## 仍保留的隔离环境失败证据

隔离生命周期脚本的标准入口连续两次在 `start-postgres` 阶段超时：Docker 已创建容器，但容器保持 `created`，没有自动进入 `running`。随后用不写入仓库的一次性 create→start 驱动复核，并从另一个 Docker CLI 明确把本轮临时 PostgreSQL 启动到 `running`；但驱动内的 `docker start` 子进程仍不返回并最终超时，生命周期仍未进入插件安装。该结果不指向插件或 TTS 代码。各轮都通过标签校验精确删除了临时容器、网络和卷，无残留：

- [`lifecycle.json`](./lifecycle.json)
- [`lifecycle-retry.json`](./lifecycle-retry.json)
- [`lifecycle-manual-start.json`](./lifecycle-manual-start.json)
- [`lifecycle-review.json`](./lifecycle-review.json)

因此不能宣称本轮隔离安装／强制升级／卸载／重装门禁通过。作者随后授权正式发布；正式环境使用发布前完整备份、恢复演练、精确迁移、公开安装、运行态契约、9 音色 HTTP 与桌面试听独立通过。正式通过不篡改或替代上述隔离失败结论。

## 数据与恢复边界

- 隔离临时 PostgreSQL 容器和生命周期资源已全部删除；无残留。
- 正式数据库只执行 `0053 -> 0054` 约束／闭包迁移；试听无状态，不写声音版本、Edition、媒体或正文。
- 发布前 dump、旧安装树、候选和 Skill 快照仍保存在冻结恢复目录；恢复方法见正式发布证据。
