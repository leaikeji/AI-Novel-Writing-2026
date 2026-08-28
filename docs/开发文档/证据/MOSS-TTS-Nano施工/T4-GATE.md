# T4-GATE：个人本地中文多角色朗读最终门禁

状态：`PASS_LOCAL_CHINESE_CORE`

日期：2026-08-28（Asia/Shanghai）

## 裁决

T4 在当前批准范围内通过：个人、本地、单用户；只面向 6 个中文 `official_preset`；旁白 `onnx.Zhiming`、沈川 `onnx.Junhao`、林晚 `onnx.Xiaoyu`；使用固定官方 ONNX manifest 的原始 prompt codes 与官方默认参数。真实章节、网页分段播放器、CodeMirror 句段跟随、段落／光标跳播、倍速／进度、更新朗读、失败恢复、Range/ETag、固定 31 点／30 分钟、四桌面组合、作者听检、同 run resume／teardown、缓存／磁盘保护契约、安装升级卸载非回归和正式 product mode 已形成相互绑定的技术或作者证据。

本裁决只放行上述有限核心，不放行云端辅助说话人识别、高级匿名人物选角、reference clone、VoiceGenerator、24 槽通用音色、英文／日文专项、商业／再分发审批、共享／复杂继承、OS signing／SSHSIG 或音频导出。低于 1920×1080、移动、窄屏和 200% 等效小视口不在本专项范围。

## 权威证据

- canonical run：`bb03ccaf-4681-490a-b987-84bec9199b3b`。
- 技术结果：`PASS_CANDIDATE`；作者完整章节听检：`PASS`；同 run resume：`PASS`；teardown：`TOOLS_CLEANED`。
- listening record SHA-256：`70f005a209be1b75cde351e0352bb89654a29256b7c5004decc5fd7bfa2a3ec0`。
- listening receipt SHA-256：`1d8c69a23de5cdd41fed50f6c715836887b7992bbcfa938cea34cce6119a66e1`。
- result SHA-256：`afc70316e08a7ea8cc053a622c5733c27c48e18a0a605ce8eef557b65bdd49f5`。
- 最终候选及安装源码 tree：`7a57471ebe9ea6cffc6d76529e3fdcab6c1683ad236499fbc2d1fdfb720bde13`；安装树重算时只排除运行时生成的 `__pycache__`／`.pyc`。
- PostgreSQL Alembic head：`20260828_0024`。
- 产品矩阵：`runtime=true / product=true / validation=false / reference=false`；Sidecar、播放器、digest keyring、生产 backend 和 worker 均 ready。
- QwenPaw、PostgreSQL、MOSS-TTS Sidecar 三个长期容器均 `healthy`、restart count 0；容器内 validation token 不存在。
- 机器可读汇总：[T4-GATE-final-product-2026-08-28.json](./T4-GATE-final-product-2026-08-28.json)。

## 冗余清理裁决

最终真实页面复核发现旧“通用音色 24 分类位”仍公开可见，与现行 6 个中文官方预设范围冲突。已安全删除该前端页面、导航／快捷入口、专用样式、仅供该页面使用的前端 API／DTO 解析器及 7 项专项测试；生产 bundle 从 112 个模块降为 110 个模块，约减少 13.4 KiB raw／3.2 KiB gzip。已执行迁移、后端兼容 schema、历史 T2-E 证据和数据库数据均保留，避免破坏恢复与升级路径。

最终部署页面实测只保留“总览、旁白、人物配音、选角规则、发音与停顿、音频与缓存”六个朗读设置入口；“通用音色／24 分类位”不存在，旁白音色区域明确显示当前产品的 6 个中文官方预设。

## 实际验证

- Python 全量：`2821 passed, 126 skipped, 2 warnings`；warning 为既有 Starlette/FastAPI 弃用提示。
- 前端：`88` 个测试文件、`813 passed`；`pnpm typecheck` 与 production build 通过。
- 包与安装契约：`128 passed`。
- 固定 Controller Node：`54/54`；browser supplement Python：`11/11`。
- 失败重试／缓存／磁盘保护窄回归：`342 passed`。
- disposable PostgreSQL 18：失败句段重试 `9/9`，媒体保护／GC `11/11`；临时测试角色权限及原 SCRAM verifier 已恢复。
- 最终公开安装流程再次执行完整前后端回归、打包、事务化 Alembic upgrade、digest keyring 校验、Agent 配置、QwenPaw reload 和 product verifier，全部成功。

## 证据边界与非阻断剩余项

- 系统中文 IME 由作者本人确认亲自输入至少两个汉字正常。自动 supplemental v1 envelope 因执行器恢复缺陷与后续超时未生成；缺失事实保留为 `NOT_PRODUCED_NON_BLOCKING`，不伪造自动 PASS，也不要求作者重复验证。
- 本地 Node／Playwright 报告是作者／操作员执行并核验的本机证据，不宣称第三方或密码学远程证明。
- 为避免破坏用户数据，未在长期产品卷真实制造低于 1 GiB、真实删除专用缓存资产或人为制造失败句段。对应状态机、磁盘 fail-closed、两阶段 GC、权威媒体保护和 PostgreSQL 并发边已由单元／集成测试覆盖；这三项破坏性注入不作为个人本地 T4 放行前置。
- 云端辅助说话人识别与高级匿名人物选角继续 `HOLD_PENDING_DECISION`，不得随本门禁自动放行。

## 恢复

升级前 custom-format dump SHA-256 为 `667e06e5c4e628c4863f7347a3a1cff2c035954fab923616c53d4ec65a7340d8`，schema-only SQL SHA-256 为 `79c2aaba72084bb3c7efabb769ec050cc3b95853ca8c304bc45d0c95b641df6e`。失败时可退回上一个固定 QwenPaw 基础镜像／PawApp 候选并从上述备份恢复；不得删除现有 PostgreSQL、QwenPaw、媒体或 Sidecar 卷。
