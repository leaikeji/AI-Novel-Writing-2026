# 计划 49 验收证据

状态：**`TTS49-CODE-FINAL=PASS`、`TTS49-SCHEMA-COMPAT-FINAL=PASS`、`TTS49-RELEASE-READY=PASS`。候选尚未提交、推送或部署到长期环境。**

日期：2026-09-01（Asia/Shanghai）

## 候选身份

- 施工分支：`codex/tts49-compat-hardening`
- 施工基线：`84e4858e0a7f87e41dfe2578e6c7e20eeef4f348`
- 插件：`ai-novel-world-2026@0.4.0`
- 唯一迁移 head：`20260901_0036`
- 候选整树 SHA-256：`396500e75c4250492816fb1248bca2a1ddb97f471f3762ed59a358f7dc61f5b3`
- 正式前端 bundle SHA-256：`f394db08ccffe07afd6ba2968751d843515f66b66e25dbec32db21449759f147`
- 正式前端 bundle 大小：`3,438,034` 字节

## 已完成范围

- 脚本复核的 `high / medium / low / unknown` 只在协议中保留，作者界面统一显示“置信度：高／中／低／未知”。
- Edition 聚合加载补齐次数耗尽、超时、dispose、旧请求被新请求取代、不可重试错误和零副作用回归；测试未证明生产重试实现有缺陷，因此没有重写播放器或聚合加载器。
- `local-owner` 历史请求完成当前 HTTP 修正、批准、查询和 Edition 链；覆盖幂等重放、精确人工修正继承、actor 不一致拒绝和数据库封印。
- 仓库当前 head、候选包 head、功能最低迁移和历史迁移证据使用四种独立语义；候选迁移只经 AST 静态解析，不导入或执行候选代码。
- 当前 schema PostgreSQL 测试共用唯一 head helper；章节 readiness 接受 `0034` 的合法线性后代。
- PostgreSQL 权威表矩阵扩展为 `0034=62`、`0035=65`、`0036=67`，当前 Python/SQL 清单一致，新增 TTS 表不再落出显式保护范围。
- 隔离浏览器先暴露脚本复核在窄容器内两列挤压的问题；已增加 `≤768px` 单列安全降级与回归。用户随后明确将本轮正式浏览器矩阵收敛为 1080p 和 2K，因此移动端不计入最终浏览器裁决。

## 自动化与隔离验证

| 门禁 | 结果 |
| --- | --- |
| 定向 Python | 施工定向 `106 passed / 32 skipped`；生命周期专项 `64 passed`；最终审计回归 `141 passed / 5 skipped` |
| 定向前端 | 最终 `57 passed`，TypeScript 通过 |
| 当前 schema 隔离 PostgreSQL | `30 passed / 1 skipped`；唯一跳过项为未配置 `TTS_REAL_NANO_TOKEN_FILE` 的真实 Nano 门禁 |
| 角色矩阵 | `0034`、`0035`、`0036` 各 `18 passed` |
| 迁移链 | `0034 → 0035 → 0036 → 0035 → 0036` 通过；整书选角迁移往返专项 `1 passed` |
| 后端全量 | `3524 passed / 167 skipped / 3 warnings` |
| 前端全量 | `126 files / 1095 tests passed` |
| TypeScript / Vite | typecheck 通过；正式构建通过 |
| 插件与宿主契约 | 打包通过；manifest/Skills/QwenPaw 契约 `128 passed` |
| Controller Node | `57 passed` |
| Compose / diff | `docker compose config --quiet` 与 `git diff --check` 通过 |

全量后端在清除数据库、角色和真实 Nano 可选环境变量后运行；隔离 PostgreSQL、角色与生命周期门禁只注入各自所需的精确变量。所有真实写入均位于一次性数据库或一次性容器中。

## 生命周期发现与修复

真实隔离生命周期共保留四份脱敏原始记录：

- [`TTS49-LIFECYCLE-RAW.json`](./TTS49-LIFECYCLE-RAW.json)：首次安装遇到 QwenPaw 插件加载器短暂 `503`，仍完成精确清理；据此增加只接受公开固定响应的有界重试。
- [`TTS49-LIFECYCLE-RAW-2.json`](./TTS49-LIFECYCLE-RAW-2.json)：发现禁用态健康契约漏校验 `model_loaded` 与 `idle_unload_seconds`，仍完成精确清理；契约和回归随后修正。
- [`TTS49-LIFECYCLE-RAW-3.json`](./TTS49-LIFECYCLE-RAW-3.json)：修正后的候选生命周期首次通过。
- [`TTS49-LIFECYCLE-RAW-4.json`](./TTS49-LIFECYCLE-RAW-4.json)：正式前端重构建后的最终候选再次通过，是发布裁决的权威记录。

最终运行 `tts49real0904` 完成安装、迁移、强制重装、卸载零残留、重新安装、数据库/卷哨兵保留和精确资源清理；无 host bind、无宿主端口、无 Sidecar、无模型或 token 挂载，也没有广义清理。

## 桌面浏览器

用户最终指定只验收：

- `1920×1080`：四种中文标签均出现一次，无英文枚举、无横向溢出；面板可纵向滚动，底部主操作完整位于视口内；关闭动作将焦点恢复到原按钮。
- `2560×1440`：四种中文标签完整，无英文枚举和横向溢出；面板内容无需纵向滚动，底部主操作完整可见。

最终顶层候选页面在两种视口下无新增 console warning/error。浏览器只使用隔离 QwenPaw、隔离 PostgreSQL和虚构脚本片段，未写入长期小说或长期数据库。

## 保留门禁

- `PITCH45-FINAL=HOLD_AUTHOR_LISTENING`
- `TTS47-UX-FINAL=HOLD_AUTHOR_LISTENING`
- `TTS47-CAST-FINAL=HOLD_BROWSER_MODEL_PROVIDER`
- `TTS47-EXPR-SPIKE=NOT_RUN`

计划 49 的 `RELEASE-READY=PASS` 只说明候选具备另行授权发布的条件，不代表上述作者听感、真实 Provider 或表达风格门禁已经通过。

## 资源清理

- 已关闭本轮浏览器标签并恢复临时视口覆盖。
- 已按精确名称删除计划 49 的三个隔离容器、两个隔离网络和六个隔离卷；没有使用 Compose project label、`down` 或 prune。
- 浏览器 harness、临时构建目录和角色验证临时文件已移入系统废纸篓；仓库中没有残留 harness 源码或生成物。
- `anw-ccl-*`、长期 QwenPaw、长期 PostgreSQL、长期 Nano Sidecar 和其他任务的 `ui44` 容器均未触碰；清理后长期 health 仍为 `ready`。

详细迁移与角色结论见 [`TTS49-SCHEMA-COMPAT.md`](./TTS49-SCHEMA-COMPAT.md)，部署差异和恢复边界见 [`TTS49-RELEASE-READINESS.md`](./TTS49-RELEASE-READINESS.md)。
