# 计划 79 施工与验收记录

日期：2026-09-13（Asia/Shanghai）

当前状态：**PASS；代码门禁、正式 PawApp V2、LaunchAgent 保活、真实掉线自恢复、整章自动生成和实际播放均已通过。**

## 已完成

- 生产 worker 在 ready 前先完成本地健康检查和 CustomVoice warmup；segment worker 返回实际 Provider，共享调度循环在本地 Provider 不可达／超时后停止领取后续任务，健康与 warmup 通过后自动续行。
- 本地首次短中文时长异常只进行一次固定策略重生；第二次异常终止并保留时长证据，失败 WAV 不发布。云端不会因此自动增加计费请求。
- macOS LaunchAgent 管理器已实现路径、三模型、专用 Python 和 `0600` token 文件校验；配置固定 UTF-8，token 值不进入 plist。
- 朗读设置对 `TTS_PROVIDER_RECOVERING` 显示“本地语音服务正在自动恢复”。
- 正式章节验收新发现并修复两处前端缺口：后台生产不再禁用旧 Edition 的播放／跳转／倍速／音量；首批新 Edition 投影短暂 404 纳入既有次数和时间上限内重读，不做无限重试。

## 已通过的代码门禁

- 共享工作区最终 `.venv/bin/python -m pytest`：`3186 passed, 311 skipped`，4 条既有弃用警告，用时 23.62 秒；包含并行任务已提交的新用例，但无失败。
- 独立发布源 `.venv/bin/python -m pytest`：`3149 passed, 311 skipped`，4 条既有弃用警告，用时 25.33 秒。
- 共享工作区 `pnpm test`：168 个文件、1530 项全部通过；`pnpm typecheck`：PASS。
- 独立发布源 `pnpm test`：168 个文件、1519 项全部通过；`pnpm typecheck`：PASS；`pnpm build`：PASS，202 个模块构建成功。
- `.venv/bin/python scripts/package_plugin.py`：PASS。
- `docker compose config --quiet`：PASS。
- LaunchAgent 实际路径 `check`：PASS；候选 plist `plutil -lint`：PASS。
- `git diff --check`：PASS（代码全量回归后的中间检查；正式发布前需再次执行）。

## 正式环境已通过

- 独立发布源固定在 `1712883aae92d3049c4b45e2a979d1d03d1e36e7`，只覆盖计划 79 文件，不夹带共享工作区内计划 74／80 候选。V1 候选包归档 SHA-256：`4e79770be746373b437a9279056848c893eae33d28467c8ef57e2936fc5c0b32`。
- V1 更新前备份位于 `/private/tmp/plan79-release.zqiu4Q`：数据库 dump SHA-256 `01be950979d8ee05b70b8261f11365743ba4036ad8b0352d201e526ea34e89c5`，已通过 `pg_restore --list`；旧 PawApp 归档 SHA-256 `0e6691cdd937ef81729188879dc882d2c569a1fc70a1fec41b43fcf7d66c0044`。
- V1 经 QwenPaw 公开热安装更新，容器未重建、数据库仍为 `20260913_0056`；发布包相对旧安装只改变 `backend/narration/production_runtime.py`、`backend/narration/worker.py`、`frontend/dist/index.js`。完整 `verify_qwenpaw_lab.py` 通过，正式健康、朗读生产、本地 TTS、12 项 Skill 与 8 项工具保持。
- `com.ai-novel-world-2026.qwen-tts` 已取代手工 `screen`。首次交接暴露 macOS `launchd` 缺失 `__CF_USER_TEXT_ENCODING` 会令含中文 `PYTHONPATH` 卡在 codec 初始化；加入 `0x1F5:0x0:0x0` 后，plist 校验、启动、CustomVoice warmup 和受控终止后的 KeepAlive 换 PID 重启均通过。冻结模型仍为 `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit`、revision `41d3337e8b7f2843a75841595fc14e4b9a7a4b96`、artifact `728e8b60b4cdb195a1379faf033b428bf93feaceccbdcf3c3a4bd3a6698b4fb6`。
- 正式真实作品《缺氧：末日地下世界》第1章《签下这栋破楼》（4394 字）从页面发起更新朗读，206 个新句段入队。受控终止本地运行时后，203 个尚未领取任务保持 queued，只有正在执行的 1 个任务进入 retry_wait；LaunchAgent 拉起后该任务以第 2 次尝试成功，队列随后持续产生 succeeded，未形成整章失败风暴。
- 请求 `289151a3-7800-478c-96ef-96ec3f233138` 最终为 `ready`：206 个后台任务全部 `succeeded`、0 个错误码，只有上述 1 个任务的 `attempt_count=2`；Edition `12d6fbb0-8562-4ddd-bddb-e6c8942633c6` 为 210/210 ready、0 失败。
- V2 候选相对 V1 只改变 `frontend/dist/index.js`，归档 SHA-256 `e9677b6a2b444d83e2d806d5d59aff10f91e2c59e2ce66a36797392a627c2c7f`。更新前备份位于 `/private/tmp/plan79-v2-release.Mqx27B`：数据库 dump SHA-256 `4d1befbf4e3d4f17926bfa89dbc1517531f62728283ca9914fbc578707c4e7b5`，`pg_restore --list` 得到 1419 项；PawApp 归档 SHA-256 `f85b8d780d1451aaabbb52accfcbca75ad3390a0b602d9bb63da5aa577fddfe0`。
- V2 经 QwenPaw 公开热安装成功且 Skill 状态原样恢复。更新前后容器 ID 均为 `5a821a85df0e01cfbef85c64845a13bff04c8cfa14b8e11d4478c04a8da97492`，镜像 digest 均为 `sha256:eadfdf5bbcb9e3a5ccc45b6684dd707236dbce099ecf4e01578813c610b0f560`；数据库仍为 `20260913_0056`。已安装 `frontend/dist/index.js` 与候选 SHA-256 同为 `bf6dba78dc63b741ccfd8fc18aa6eb5f5dff83f51e2588147bfca33a0282c19b`。
- 更新后的完整正式验证通过：健康与朗读生产 ready、Reference Clone ready、隐藏验证 disabled、12 项小说 Skill 与 8 项工具保持。LaunchAgent 仍为 running、PID `51761`；本地模型身份仍为 `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit`、revision `41d3337e8b7f2843a75841595fc14e4b9a7a4b96`、artifact `728e8b60b4cdb195a1379faf033b428bf93feaceccbdcf3c3a4bd3a6698b4fb6`。
- 正式页面将新 Edition 切为当前版本后显示 210/210 句可用、0 失败；实际播放从第 1 句推进至第 2 句／0:09，暂停后刷新仍恢复在第 2 句。旧 206/209 Edition 继续作为历史版本保留。

## 已知边界

- 本轮没有为证明“后台生产时旧 Edition 可播”再重复生成整章；该交互由新增回归用例覆盖，正式环境则验证了 V2 后新 Edition 切换、播放、暂停与刷新恢复。V1 正式生成期间已经观察到旧 Edition 被保留，本轮没有删除或覆盖它。
- 短中文质量异常只自动换固定种子重生一次，第二次仍异常会按句段失败；本地和云端之间不做静默切换，避免不可审计输出和意外云端费用。
