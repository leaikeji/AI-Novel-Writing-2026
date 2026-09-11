# Plan 67 V0.4 长期发布记录

状态：**RELEASE PASS（功能、长期发布、最终销毁、残留复核与授权后的精确 housekeeping 均已通过）**
日期：2026-09-11（Asia/Shanghai）

## 已通过

- 后端全量：2715 passed、256 skipped、3 warnings。
- 前端全量：149 files、1282 tests passed；typecheck、build 通过。
- 打包与 `git diff --check` 通过。
- 仅含 Plan 67 的候选：`/private/tmp/plan67-v04-release-candidate-20260911/build/ai-novel-world-2026`；验证器 tree SHA-256 `a0b04e91545a395ad8ed718563262593d944ab18112c4adffe1fdc5f7e6cfa7f`；head `20260911_0053`。
- 隔离空库从 base 升至 0053，目标审计列计数 1；隔离执行“建测试书→回收→验证 v2 备份回执→完整销毁→审计”通过，结果 `deleted=true`、audit=`completed`。
- 停写前长期库为 0052，活动后台任务 0；4 本正式作品保持 active，只读；验收书 `a9e9a9b5-59f7-49a7-bfdc-aa659c9e70f7` 为 recycled、version 2、媒体 0、文档 0、活动任务 0。
- 停写恢复点：`/Users/liujia/Documents/AI小说世界2026-backups/plan67-v04-20260911-0019-before`，mode 0700；归档 mode 0600。
  - database.dump：14668488 bytes，SHA-256 `8f17d9400b10229517a0b20e3e7d0cac3854bdd68ac10bdfd337c3b8fab4000c`
  - novel-media.tar.gz：212021134 bytes，SHA-256 `5ff8e41c4b1cad866e22a7a133b50549734ee3b14a91167f10cab1e366b9b013`
  - old-working.tar.gz：SHA-256 `67601fef734a23a05dfa3b9bf93ed8b13da2b6772e6149551a4cd670d9ea5318`
  - candidate.tar.gz：SHA-256 `a3a27943c55af0001cb1053a1f26b9332dc930bc175026afd43dca6663d0db4d`
- 数据库归档可由 `pg_restore --list` 列举；恢复到 `plan67_v04_restore_20260911` 后 head=0052，novels=5、documents=22、document_revisions=59、background_jobs=169，验收书仍为 `2:recycled`。
- 长期库已由 schema-owner 单步迁移到 0053；实际 head=0053，`backup_receipt_sha256` 列计数 1。
- QwenPaw 专用备份卷已保存数据库、媒体和隔离恢复证据；目标验收书的 v2 回执按 UUID/version 固定命名，等待部署后由服务端再次复算。

## 当前阻断与保护状态

- 作者于 2026-09-11 明确授权重启 Docker Desktop；引擎已恢复，未删除任何业务卷。空的失败 bootstrap 容器已精确移除。
- `bootstrap-20260911_0053` 幂等完成；`validate-20260911_0053` 为 PASS：61 张保护表，API／worker 均无 raw DML，角色登录、owner、ACL 与独立 `0600` passfile 门禁通过。
- 冻结候选已在 QwenPaw 停止状态下离线安装；运行态公开验证为 ready，保留 AI 小说作家当前模型 `minimax-cn / MiniMax-M3`、11 个小说 Skill 与 5 个小说工具。
- 运行态错误确认词 `confirmation_text="删除"` 返回 422；固定 v2 回执再次由服务端代码复算，精确绑定验收书 UUID、version 2、空媒体清单摘要与隔离恢复 PASS，回执 SHA-256 为 `eb34aade72199319015778a983f93ca9dab596a3a4bede8c13234af9782c11aa`。
- 真实浏览器发现正式作品《刑侦1988:消失的档案》曾被其他动作移入回收站；已通过正常恢复确认流程恢复。删除前复核显示四本正式作品均为 active，回收站仅剩验收书 `a9e9a9b5-59f7-49a7-bfdc-aa659c9e70f7`。
- 真实浏览器已验证回收站说明、恢复、逐字确认输入和按钮禁用／解锁。弹窗曾精确显示验收书名并输入 `确认删除`，并在最终不可逆点击前停止；随后该 in-app browser 标签已关闭。服务端复核仍仅列出该验收书且 version 2。未取得动作时确认前不得重新打开并点击，也不得把本记录写成发布完成。
- 作者随后明确回复 `确认删除`。真实浏览器重新从 PawApp 入口进入回收站，再次核对唯一目标、书名和 version 2，逐字输入固定短语并点击最终“彻底删除”。结果弹窗报告数据库与媒体已删除、本浏览器清理 0 条恢复稿；该验收书本来没有 document ID，因此 0 条为精确预期值。

## 最终动作与残留复核

- 真实浏览器回收站显示 `共 0 本作品`；独立 API 复核 `total_count=0`、`items=[]`，目标普通详情为 404。
- 长期数据库中目标 `novels`、`documents`、`media_assets`、`background_jobs` 均为 0；删除审计为 `completed`、expected version 2、media count/bytes 0、无 failure code，数据库与媒体完成时间均非空，备份回执摘要与删除前复算值一致。
- 对 public schema 全部 UUID、text、varchar、char、json/jsonb 列扫描精确 UUID，只命中允许保留的 `novel_lifecycle_events.novel_id` 和 `novel_deletion_audits.novel_id` 各 1 条；没有业务数据残留。
- 只读挂载媒体卷并按目标 UUID 扫描路径，结果为 0。备份卷中的固定 v2 回执、数据库／媒体备份及隔离恢复证据按审计和恢复策略保留，不计作业务残留。
- 普通作品 API 仍精确返回四本正式作品：`刑侦1988:消失的档案` v6、`末日：我把危楼建成地下堡垒` v2、`超能梦境` v2、`潮汐盲区` v4，均为 active。前者在验收期间发现被其他动作移入回收站后，经正常恢复流程恢复；其版本按生命周期 CAS 前进，未倒拨历史。
- 桌面真实浏览器和 Edge 390×844 显式 viewport 均完成空回收站视觉与可访问树检查；标题、返回、刷新、说明、数量和空态可见，无横向截断。临时 viewport 已 reset。
- V0.4 冻结候选又通过真实隔离插件生命周期门禁 `plan67v04a`：initial install、force reinstall、uninstall、reinstall 全部 PASS；卸载后 PawApp 路由／静态资源为 404，原生 shell／Agent／Skills／Tools 仍正常，4 个卷 sentinel 与数据库 sentinel 在重装后保持，0053 head 与候选 tree SHA 再次匹配。验证器仅创建唯一标签的 2 个容器、5 个卷和 1 个 internal network，已逐个精确清理，`broad_cleanup_used=false`、failure 0。机器可读证据为 `audit/plan67/plugin-lifecycle-v04.json`。

## Housekeeping 完成证据

- 作者随后明确授权清理五个测试数据库与临时凭据目录。执行前再次按精确名称复核，`plan67_recycle_test_20260910`、`plan67_restore_test_20260910`、`plan67_upgrade_test_20260910`、`plan67_v04_restore_20260911`、`plan67_v04_upgrade_20260911` 的连接数均为 0；五次 `DROP DATABASE` 均成功。
- 删除后从 `pg_database` 按同一精确集合查询返回 0 行；没有使用模糊匹配或广泛清理。
- 精确删除 `/private/tmp/plan67-admin-pgpass-20260910`，复核路径不存在。该临时秘密未读取、未打印、未提交；此删除不可恢复。
- 长期数据库、长期备份、QwenPaw 备份卷、purge receipt、maintenance root 和脱敏审计证据均保留。长期 QwenPaw 容器仍为 `5c49b826fd39`，状态 `healthy`；没有 Plan 67 临时容器残留。

## 2026-09-11 V0.5 删除确认修复

- 作者在真实回收站报告输入 `确认删除` 后仍无法删除。实际页面复现显示输入值完整匹配且最终按钮已解锁；对《潮汐盲区》v5 只读调用现行校验器，精确错误为缺少 `/app/working.backups/ai-novel-world-2026/purge-receipts/b9983b07-f3aa-44e5-9433-d367563f48e4.v5.json`。正式作品未执行最终销毁。
- 根因是 V0.4 把逐 UUID＋version 维护回执设为作者 UI 的隐藏第三条件，却没有任何产品入口生成它。V0.5 按作者“两步删除＋逐字确认”裁决移除该隐藏条件；严格请求体、回收态、精确版本、完整运行时、活动任务、文档与媒体双重快照、唯一销毁链和脱敏审计均保留。v2 回执链保留为可选运维加强模式。
- 前端删除了误导性备份必需文案，并在当前确认弹窗内显示服务端失败原因。后端全量为 2716 passed、257 skipped、3 warnings；前端为 153 files、1304 tests passed，typecheck 与 build 通过。
- 部署候选 tree SHA-256 为 `93702e767cbcd2b0ae501b4e6a3fec8bb0e291dbcf039f988f9351660bce44ab`、head `20260911_0053`；安装前插件副本为 `/private/tmp/plan67-delete-fix-before.Y9alh6`，tree SHA-256 `31dd2a2914a77890330699a55e510cb767d8352f2084373cedaf4ca1619fdc18`。公开离线安装成功，宿主／PawApp 健康、朗读运行态 ready。
- 新建空验收书《Plan67删除修复验收-1309》（`db07ca33-093a-4d3b-bde0-c09da36cbbb2`），经公开 API 移入回收站后，真实页面显示 1 章、0 字、0 字节媒体；新文案可见，输入确认词后按钮已解锁。最终不可逆点击仍等待动作时确认，因此本条不宣称真实销毁已经完成。
