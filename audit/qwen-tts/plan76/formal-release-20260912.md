# 计划 76 正式发布记录（2026-09-12）

## 发布结果

- 正式地址：`http://127.0.0.1:18088`
- QwenPaw：`2.2.0`，容器健康
- PawApp：`ai-novel-world-2026@0.4.0`
- 正式数据库：`20260912_0054 -> 20260912_0055`
- 发布候选树 SHA-256：`92fbbc2678b496dbdb5a80956b53f20abda5f51844053e6651bbcad37134fd65`
- 发布后容器 ID：`a874d5a19c130999388a9e9021a7c5496c9c17d85bc9c1798fadb564f654bbb5`
- 固定基础镜像 ID：`sha256:a7430e32833b6211f37200ee4e8c798946d8719772efcd650b92c1f663834fb3`

## 备份与恢复材料

恢复目录：`/private/tmp/ai-novel-world-2026-plan76-release.NWAsPG/recovery-before`

- 正式数据库 dump：`7f14e66e575442fdae8ffa0d431cef0034f5b6a0dfbac88d5e2b974a59b97a7c`
- 发布候选归档：`2f3a0b8bc2fe27bee9ddac6d53f4e8bdeadce4efbbd2e0bb761e20a4c32d6718`
- 发布前已安装插件归档：`17d198cb43a5c92c13a6ee1d6b2b0be7152e423a125a589c63352564ae251473`
- 发布前 Skills 状态：`skills-before.json`，发布后恢复结果 `state_preserved=true`
- 同一恢复目录已复制到 QwenPaw 持久卷：`/app/working.backups/plan76-20260912-before`

没有删除 PostgreSQL/QwenPaw 数据卷、小说正文、历史 revision、媒体或音色数据。

## 数据库门禁

1. 正式应用停机后核实 head 为 `20260912_0054`。
2. `bootstrap-20260912_0054` 与 `validate-20260912_0054` 通过。
3. 精确运行 `upgrade 20260912_0055`。
4. `bootstrap-20260912_0055` 与 `validate-20260912_0055` 通过。
5. 发布后 head 为 `20260912_0055`；权限验收 `status=PASS`。

## 运行态验收

正式聚合验收通过：

- `health=ready`
- `narration.lifecycle_status=ready`
- `playback_installed=true`
- `production_backend_installed=true`
- `worker_running=true`
- `reference_clone_ready=true`
- 官方音色目录为 `qwen-tts-preset-catalog/2`，共 9 个音色
- 11 个小说 Skills 仅在 `ai-novel-writer` 启用，5 个小说工具作用域不变
- 当前写作模型仍为 `bigmodel / glm-5.3-flash`

旧环境变量 `AI_NOVEL_TTS_REFERENCE_CLONE_ENABLED` 必须保持 `false`。该开关代表已经移除的旧兼容模式；计划 76 的 Qwen Base/VoiceDesign 私人音色能力由新的产品运行时在 `AI_NOVEL_TTS_PRODUCT_ENABLED=true` 时提供。将旧开关设为 `true` 会被 fail-closed 为 `TTS_PROVIDER_DISABLED`。

## 桌面浏览器验收

在正式 `18088` 的实际作品页面完成只读/播放检查：

- 朗读页显示“本地 TTS 技术就绪”，选择本地 Qwen3-TTS，语言为“普通话（固定）”；
- 私人音色页出现“文字设计音色”和“上传参考录音”两条入口；文字设计表单显示“声音语言：普通话（固定）”；
- 没有替作者创建、锁定或绑定测试音色；
- 已有章节播放器从 `1:11` 正常播放到 `1:14`，随后手动暂停；
- 既有 209 句中 206 句可播放；第 70、114、199 句均显示为音频质量终态，重试按钮统一禁用，并提示更换声音或调整正文后更新朗读。

## 已知边界

- 本次没有替作者执行新的 VoiceDesign 候选创建与锁定，作者听感仍需正常使用页面后确认。
- 10 条历史 `failed` 后台任务和 1508 条 `succeeded` 记录保持原样；没有活动任务，也没有自动删除或重试历史失败。
- 本机已有系统 swap，未建立干净启动前基线，因此不声称正式发布满足“0 swap”。
- 本轮没有提交或推送 Git。
